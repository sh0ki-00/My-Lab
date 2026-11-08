#!/usr/bin/env bash
# hooks/lib.sh — 接続口（claude-*.sh、cursor-*.sh）の共通部品。判定はしない。
# JSON の読み書き、プロジェクトの root と検証の道具の場所の解決、記録だけを持つ。

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
LAB_ROOT="$(cd "$HOOKS_DIR/.." && pwd -P)"
LOG_FILE="$LAB_ROOT/tmp/.verify/hooks.log"
export HOOKS_DIR LAB_ROOT LOG_FILE

# json_get <経路> <json>  例: json_get tool_input.command "$input"
# 経路は . 区切り。数字の区切りは配列の添字。無いときは空を返す。真偽値と数値は文字にする。
json_get() {
  local path="$1" json="$2"
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$json" | jq -r --arg p "$path" '
      try getpath($p | split(".") | map(if test("^[0-9]+$") then tonumber else . end))
      | if . == null then empty
        elif (type == "boolean" or type == "number") then tostring
        else . end' 2>/dev/null
  elif command -v python3 >/dev/null 2>&1; then
    printf '%s' "$json" | python3 -I -c '
import json, sys
path = sys.argv[1].split(".")
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for k in path:
    if isinstance(d, dict):
        d = d.get(k)
    elif isinstance(d, list) and k.isdigit() and int(k) < len(d):
        d = d[int(k)]
    else:
        d = None
if d is None:
    sys.exit(0)
print(str(d).lower() if isinstance(d, bool) else d)' "$path"
  else
    printf '%s' "$json" | node -e '
let s = ""; process.stdin.on("data", c => s += c).on("end", () => {
  let d; try { d = JSON.parse(s); } catch { return; }
  for (const k of process.argv[1].split(".")) { d = (d != null && typeof d === "object") ? d[k] : undefined; }
  if (d === undefined || d === null) return;
  process.stdout.write(String(d) + "\n"); });' "$path"
  fi
}

# json_str <文字列> → 引用符つきの JSON 文字列リテラル（1 行）
json_str() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$1" | jq -Rs '.' | tr -d '\n'
  elif command -v python3 >/dev/null 2>&1; then
    printf '%s' "$1" | python3 -I -c 'import json, sys; print(json.dumps(sys.stdin.read(), ensure_ascii=False))' | tr -d '\n'
  else
    printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/	/\\t/g' | awk 'NR > 1 { printf "\\n" } { printf "%s", $0 }')"
  fi
  printf '\n'
}

# project_root <json> → 作業中のプロジェクトの root
project_root() {
  local json="$1" r=""
  r="${CLAUDE_PROJECT_DIR:-${CURSOR_PROJECT_DIR:-}}"
  [ -n "$r" ] || r="$(json_get workspace_roots.0 "$json")"
  [ -n "$r" ] || r="$(json_get cwd "$json")"
  [ -n "$r" ] || r="$PWD"
  printf '%s' "$r"
}

# tools_dir <root> → 検証の道具の場所。root 直下の tools/（My-Lab）、無ければ tmp/tools/（他のプロジェクト）、どちらも無ければ空
tools_dir() {
  local r="$1"
  if [ -f "$r/tools/check-file.sh" ] && [ -d "$r/.company" ]; then
    printf '%s' "$r/tools"
  elif [ -f "$r/tmp/tools/check-file.sh" ]; then
    printf '%s' "$r/tmp/tools"
  fi
}

# verify_cmd <root> → 作業を終える前に回す命令（root で実行する）。無ければ空
verify_cmd() {
  local r="$1"
  if [ -n "${COMPANY_GUARD_VERIFY_CMD:-}" ]; then
    printf '%s' "$COMPANY_GUARD_VERIFY_CMD"
  elif [ -f "$r/tools/verify-all.sh" ] && [ -d "$r/.company" ]; then
    printf 'bash tools/verify-all.sh --fast'
  elif [ -f "$r/tmp/tools/project-verify.sh" ]; then
    printf 'bash tmp/tools/project-verify.sh --fast'
  fi
}

# project_registers <root> <接続口の名前> → そのプロジェクト自身が同じ接続口を登録していれば 0
# Mac 全体の登録（--global）は、プロジェクト自身の登録があるときは理由を省くか、重ねて回さない。
project_registers() {
  local r="$1" name="$2"
  case "$name" in
    claude-*) grep -qs -- "$name" "$r/.claude/settings.json" ;;
    cursor-*) grep -qs -- "$name" "$r/.cursor/hooks.json" ;;
    *) return 1 ;;
  esac
}

# changed_since_pass <root> → 最後に検証が PASS したあとに直したファイルがあれば 0。印が無ければ 0
changed_since_pass() {
  local r="$1"
  local stamp="$r/tmp/.verify/last-pass"
  [ -f "$stamp" ] || return 0
  [ -n "$(find "$r" \( -name node_modules -o -name .git -o -name .verify -o -name dist -o -name build -o -name .next -o -name target -o -name vendor \) -prune -o -type f -newer "$stamp" -print -quit 2>/dev/null)" ]
}

# stop_count <session> [reset|bump] → Stop の指示で続けた回数（セッションごと）。上限は接続口が決める
stop_count() {
  local f="$LAB_ROOT/tmp/.verify/stop-count-${1:-none}" n=0
  mkdir -p "$(dirname "$f")" 2>/dev/null || true
  [ -f "$f" ] && n="$(tr -dc '0-9' < "$f")"
  n="${n:-0}"
  case "${2:-}" in
    reset) printf '0' > "$f" 2>/dev/null ;;
    bump)  n=$((n + 1)); printf '%s' "$n" > "$f" 2>/dev/null ;;
  esac
  printf '%s' "$n"
}

# log <文> → tmp/.verify/hooks.log に 1 行。コマンドの本文は書かない（秘密が混ざるため）
log() {
  mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || return 0
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE" 2>/dev/null || true
}
