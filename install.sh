#!/usr/bin/env bash
# install.sh [--dry-run] [--remove-old-links] — この Mac に 1 回だけ行う接続。
#   1) ~/.claude/settings.json と ~/.cursor/hooks.json に、この正本の hooks（--global）を登録する。
#      旧 cradle の登録（cradle-guard-*.sh）は外す。書き換える前に <ファイル>.bak.<日時> を作る。他の設定はそのまま残す。
#   2) --remove-old-links: ~/.claude/skills/ と ~/.claude/hooks/、~/.cursor/hooks/ の、旧 cradle-skills を指すリンクを外す（実体は消さない）。
#   常時ルール（~/.claude/CLAUDE.md、Cursor の User Rules、~/.cursor/rules）には書き込まない。本文は router/ にあり、社長が貼る。
#   --dry-run は、書き込む内容を表示するだけで何も変えない。
set -eu
LAB="$(cd "$(dirname "$0")" && pwd -P)"
H="$LAB/hooks"
DRY=0; RM_LINKS=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --remove-old-links) RM_LINKS=1 ;;
    *) echo "使い方: install.sh [--dry-run] [--remove-old-links]"; exit 2 ;;
  esac
done
command -v jq >/dev/null 2>&1 || { echo "FAIL install: jq が要る（brew install jq）"; exit 1; }
CL="$HOME/.claude/settings.json"
CU="$HOME/.cursor/hooks.json"
STAMP="$(date +%Y%m%d-%H%M%S)"

new_claude() {  # 既存の設定を読み、旧 cradle と自分の古い登録を外し、自分の登録を足す
  local cur="{}"
  [ -f "$CL" ] && cur="$(cat "$CL")"
  printf '%s' "$cur" | jq --arg h "$H" '
    def mine($c): ($c | test("cradle-guard")) or ($c | contains($h + "/claude-"));
    def clean(ev): ((.hooks // {})[ev] // [])
      | map(.hooks |= map(select(mine(.command // "") | not)) | select((.hooks | length) > 0));
    .hooks = (.hooks // {})
    | .hooks.PreToolUse  = clean("PreToolUse")  + [{matcher: "Bash", hooks: [{type: "command", command: ("bash " + $h + "/claude-pretooluse.sh --global"), timeout: 20}]}]
    | .hooks.PostToolUse = clean("PostToolUse") + [{matcher: "Edit|Write|MultiEdit|NotebookEdit", hooks: [{type: "command", command: ("bash " + $h + "/claude-postedit.sh --global"), timeout: 120}]}]
    | .hooks.Stop        = clean("Stop")        + [{hooks: [{type: "command", command: ("bash " + $h + "/claude-stop.sh --global"), timeout: 600}]}]'
}

new_cursor() {
  local cur='{"version":1,"hooks":{}}'
  [ -f "$CU" ] && cur="$(cat "$CU")"
  printf '%s' "$cur" | jq --arg h "$H" '
    def mine($c): ($c | test("cradle-guard")) or ($c | contains($h + "/cursor-"));
    def clean(ev): ((.hooks // {})[ev] // []) | map(select(mine(.command // "") | not));
    .version = 1 | .hooks = (.hooks // {})
    | .hooks.beforeShellExecution = clean("beforeShellExecution") + [{command: ("bash " + $h + "/cursor-before-shell.sh --global"), failClosed: true, timeout: 20}]
    | .hooks.afterFileEdit        = clean("afterFileEdit")        + [{command: ("bash " + $h + "/cursor-after-edit.sh --global"), timeout: 120}]
    | .hooks.stop                 = clean("stop")                 + [{command: ("bash " + $h + "/cursor-stop.sh --global"), timeout: 600, loop_limit: 3}]'
}

write() {  # write <ファイル> <中身>
  local f="$1" body="$2"
  if [ "$DRY" = 1 ]; then
    printf -- '--- %s（書き込まない）\n%s\n' "$f" "$body"
    return 0
  fi
  mkdir -p "$(dirname "$f")"
  [ -f "$f" ] && cp "$f" "$f.bak.$STAMP"
  printf '%s\n' "$body" > "$f"
  echo "install: $f を書いた（退避: $f.bak.${STAMP}）"
}

write "$CL" "$(new_claude)"
write "$CU" "$(new_cursor)"

# 旧リンク
old_links() {
  local d l
  for d in "$HOME/.claude/skills" "$HOME/.claude/hooks" "$HOME/.cursor/hooks"; do
    [ -d "$d" ] || continue
    for l in "$d"/*; do
      [ -L "$l" ] || continue
      case "$(readlink "$l")" in *cradle-skills*) printf '%s\n' "$l" ;; esac
    done
  done
}
LINKS="$(old_links)"
if [ -n "$LINKS" ]; then
  N="$(printf '%s\n' "$LINKS" | wc -l | tr -d ' ')"
  if [ "$RM_LINKS" = 1 ] && [ "$DRY" = 0 ]; then
    printf '%s\n' "$LINKS" | while IFS= read -r l; do rm "$l"; done
    echo "install: 旧 cradle-skills を指すリンク $N 本を外した（実体は消していない）"
  else
    echo "install: 旧 cradle-skills を指すリンクが $N 本ある。外すときは ./install.sh --remove-old-links"
  fi
fi

echo "install: 常時ルールには書き込まない。Cursor の User Rules には router/cursor-user-rule.md、~/.claude/CLAUDE.md には router/claude-code.md の本文を社長が貼る"
echo "install: 確認は bash $LAB/hooks/selftest.sh と、Claude Code の /hooks"
