#!/usr/bin/env bash
# hooks/lib.sh — hooks（claude-*.sh、cursor-*.sh）の共通部品。allow・ask・deny の判定はしない。
# JSON の読み書き、プロジェクトの root と検証の道具の場所の解決、ファイルの一覧の記録と比較、記録だけを持つ。
# 現場の語の言い換えの検出（terms_check。語の一覧は持たず、My-Lab の正本の検査に任せる）、
# セッションの記録（session_*。終わりの検証の範囲を、そのセッションが書いた文書に絞る）、作業の終わりの検証の回し方（end_verify）も持つ。

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

# project_registers <root> <hooks の名前> → そのプロジェクト自身が同じ hooks を登録していれば 0
# Mac 全体の登録（--global）は、プロジェクト自身の登録があるときは理由を省くか、重ねて回さない。
project_registers() {
  local r="$1" name="$2"
  case "$name" in
    claude-*) grep -qs -- "$name" "$r/.claude/settings.json" ;;
    cursor-*) grep -qs -- "$name" "$r/.cursor/hooks.json" ;;
    *) return 1 ;;
  esac
}

# find_tree <root> <find の式...> → root の下のファイルを find で探す。node_modules、.git、.verify、dist、build、.next、target、vendor は見ない
find_tree() {
  local r="$1"; shift
  find "$r" \( -name node_modules -o -name .git -o -name .verify -o -name dist -o -name build -o -name .next -o -name target -o -name vendor \) -prune -o -type f "$@" 2>/dev/null
}

# tree_list <root> → root の下のファイルの一覧（root からの相対パス、./ 始まり）を、文字の設定によらない順に並べて標準出力に書く
tree_list() {
  (cd "$1" 2>/dev/null && find_tree . -print | LC_ALL=C sort)
}

# snapshot_tree <root> → 今のファイルの一覧を tmp/.verify/last-pass.list に書く。hooks が、検証が通った直後に呼ぶ。書けなくても 0
snapshot_tree() {
  local r="$1"
  local list="$r/tmp/.verify/last-pass.list"
  mkdir -p "$(dirname "$list")" 2>/dev/null || return 0
  if tree_list "$r" > "$list.tmp" 2>/dev/null; then mv -f "$list.tmp" "$list" 2>/dev/null; else rm -f "$list.tmp" 2>/dev/null; fi
  return 0
}

# changed_since_pass <root> → 最後に検証が PASS したあとに、ファイルを直した・足した・消した・名前を変えたなら 0
# 印（tmp/.verify/last-pass）より新しいファイルがあるか、今の一覧が印のときの一覧（last-pass.list）と違えば「変わった」。
# 印か一覧が無ければ 0（分からないときは、検証を回す側に倒す）
changed_since_pass() {
  local r="$1"
  local stamp="$r/tmp/.verify/last-pass" list="$r/tmp/.verify/last-pass.list"
  [ -f "$stamp" ] || return 0
  [ -f "$list" ] || return 0
  [ -z "$(find_tree "$r" -newer "$stamp" -print -quit)" ] || return 0
  if tree_list "$r" | cmp -s - "$list"; then return 1; fi
  return 0
}

# stop_count <session> [reset|bump] → Stop の指示で続けた回数（セッションごと）。上限は hooks が決める
#   claude-stop.sh は、返答の書き直しと検証の差し戻しを、この 1 つの回数で数える。bump で記録を書けなければ終了コード 1
stop_count() {
  local f="$LAB_ROOT/tmp/.verify/stop-count-${1:-none}" n=0
  mkdir -p "$(dirname "$f")" 2>/dev/null || true
  [ -f "$f" ] && n="$(tr -dc '0-9' < "$f")"
  n="${n:-0}"
  case "${2:-}" in
    reset) printf '0' > "$f" 2>/dev/null ;;
    bump)  n=$((n + 1))
           if ! { printf '%s' "$n" > "$f"; } 2>/dev/null; then printf '%s' "$n"; return 1; fi ;;
  esac
  printf '%s' "$n"
}

# ---- 現場の語の言い換え（返答、commit 文・PR 文・Issue 文）

# terms_check → 標準入力の文に、現場の語の言い換え（git のブランチを別の語にするなど）があるかを見る。
#   判定は My-Lab の正本 tools/lib/check_ja.py --terms - に任せ、hooks は語の一覧を持たない（表は tools/ja-terms.txt の 1 つ）。
#   鉤括弧の中、バッククォートの中、3 つのバッククォートの囲みの中は数えない（正本の決まり）。
#   当たれば終了コード 0 で、「語<TAB>置き換えの語」を 1 行ずつ、重ねずに書く。置き換えの語は、表の例の最初の語（括弧と句点の前）。
#   当たらなければ 1。python3 か正本か表が無いなど、数えられないときは 2（呼ぶ側は止めずに通す）。
terms_check() {
  local py="$LAB_ROOT/tools/lib/check_ja.py" tag='[現場の語]' out rc line rest word hint repl entry nl hits
  command -v python3 >/dev/null 2>&1 || return 2
  [ -f "$py" ] || return 2
  out="$(python3 -I "$py" --terms - 2>/dev/null)"; rc=$?
  [ "$rc" -eq 0 ] && return 1
  [ "$rc" -eq 1 ] || return 2
  nl=$'\n'; hits="$nl"
  while IFS= read -r line; do
    case "$line" in "FAIL "*" $tag 「"*"」→ "*) ;; *) continue ;; esac   # FAIL 入力:<行> [現場の語] 「<語>」→ <置き換えの例>
    rest="${line#*" $tag 「"}"
    word="${rest%%"」→ "*}"
    hint="${rest#*"」→ "}"
    repl="${hint%%（*}"; repl="${repl%%。*}"
    [ -n "$word" ] && [ -n "$repl" ] || continue
    entry="$word"$'\t'"$repl"
    case "$hits" in *"$nl$entry$nl"*) ;; *) hits="$hits$entry$nl" ;; esac
  done <<EOF
$out
EOF
  [ "$hits" != "$nl" ] || return 2   # 当たりの行が読めない（表が無いなど）
  hits="${hits#"$nl"}"
  printf '%s' "${hits%"$nl"}"
  return 0
}

# terms_join <terms_check の出力> <1|2> → 1 列目（語）か 2 列目（置き換えの語）を、重ねずに鉤括弧で囲んで並べる（例: 「ブランチ」）
terms_join() {
  local col="$2" w r v out="" nl=$'\n' seen=$'\n'
  while IFS=$'\t' read -r w r; do
    [ -n "$w" ] || continue
    if [ "$col" = 1 ]; then v="$w"; else v="$r"; fi
    case "$seen" in *"$nl$v$nl"*) continue ;; esac
    seen="$seen$v$nl"
    out="${out}「${v}」"
  done <<EOF
$1
EOF
  printf '%s' "$out"
}

# terms_mark <会話の名前> → Cursor の返答で見つけた言い換えの印のパス（cursor-after-response.sh が足し、cursor-stop.sh が読んで消す）
terms_mark() { printf '%s' "$LAB_ROOT/tmp/.verify/terms-${1:-none}"; }

# transcript_last_reply <記録のパス> → Claude Code の会話の記録（JSONL）から、最後の返答の文を書く。
#   最後の type が user の行（利用者の入力か、道具の結果）より後ろにある、assistant の行の text を、上から順に改行でつなぐ。
#   ほかの会話から分かれた行（isSidechain）は見ない。読むのはファイルの末尾の 4 MB まで。
#   Stop の入力に last_assistant_message が無いときに、claude-stop.sh が使う。ファイルが無い・読めない・python3 が無いときは何も書かない
transcript_last_reply() {
  [ -n "${1:-}" ] && [ -f "$1" ] && [ -r "$1" ] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  python3 -I -c '
import json, os, sys
path = sys.argv[1]
limit = 4 << 20
try:
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > limit:
            f.seek(size - limit)
            f.readline()
        data = f.read().decode("utf-8", errors="replace")
except OSError:
    sys.exit(0)
texts = []
for line in data.splitlines():
    try:
        d = json.loads(line)
    except ValueError:
        continue
    if not isinstance(d, dict) or d.get("isSidechain"):
        continue
    kind = d.get("type")
    if kind == "user":
        texts = []
    elif kind == "assistant":
        msg = d.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            texts.extend(c["text"] for c in content
                         if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str))
sys.stdout.write("\n".join(texts))
' "$1" 2>/dev/null
  return 0
}

# ---- セッションの記録（終わりの検証の範囲を、そのセッションが書いた文書に絞る）
# セッションは、AI との 1 つの会話（Claude Code の session_id、Cursor の conversation_id）。依頼をまたいで続く。
# 置き場は <プロジェクトの root>/tmp/.verify/sessions/。My-Lab と移した先（検証の道具があるプロジェクト）でだけ書く。
#   <名前>.start: 初めて hooks が呼ばれた時刻の印（中身は空。記録の掃除に使う）。
#   <名前>.files: Write・Edit（Cursor は afterFileEdit）で書いたファイル（root からの相対パス、1 行 1 本、重ねない）。
#   <名前>.pass:  移した先で、そのセッションの文書の検証が最後に通ったときの文書の一覧（時刻は回し始め）。
#   14 日より前から、どれも変わっていないセッションの記録は、作業の終わり（Stop・stop）に消す。

# session_name <json> → セッションの名前。Claude Code の session_id、無ければ Cursor の conversation_id。
#   英数字と . _ - のほかの字は _ にし、100 字までにする。どちらも無ければ空
session_name() {
  local n
  n="$(json_get session_id "$1")"
  [ -n "$n" ] || n="$(json_get conversation_id "$1")"
  [ -n "$n" ] || return 0
  printf '%s' "$n" | LC_ALL=C tr -c 'A-Za-z0-9._-' '_' | LC_ALL=C cut -c1-100
}

session_dir() { printf '%s' "$1/tmp/.verify/sessions"; }   # session_dir <root> → 記録の置き場

# session_on <root> → セッションの記録を置くプロジェクト（My-Lab か移した先）なら 0。ほかのプロジェクトには tmp/ を作らない
session_on() { [ -n "$(tools_dir "$1")" ]; }

# session_mark <json> → <名前>.start が無ければ置く。pre の hooks が、判定とは別に（子のシェルで）呼ぶ。失敗しても 0
session_mark() {
  local root name dir
  root="$(project_root "$1")"
  session_on "$root" || return 0
  name="$(session_name "$1")"; [ -n "$name" ] || return 0
  dir="$(session_dir "$root")"
  [ -f "$dir/$name.start" ] && return 0
  mkdir -p "$dir" 2>/dev/null || return 0
  ( set -C; : > "$dir/$name.start" ) 2>/dev/null   # 同時に 2 つ呼ばれても、先に置いた時刻を残す
  return 0
}

# session_add <json> <ファイル> → そのセッションが書いたファイルを <名前>.files に足す。印（.start）が無ければ置く。失敗しても 0
session_add() {
  local root name dir rel
  root="$(project_root "$1")"
  case "$2" in "$root"/*) rel="${2#"$root"/}" ;; *) return 0 ;; esac
  session_on "$root" || return 0
  name="$(session_name "$1")"; [ -n "$name" ] || return 0
  dir="$(session_dir "$root")"
  mkdir -p "$dir" 2>/dev/null || return 0
  [ -f "$dir/$name.start" ] || ( set -C; : > "$dir/$name.start" ) 2>/dev/null
  grep -Fxq -- "$rel" "$dir/$name.files" 2>/dev/null && return 0
  printf '%s\n' "$rel" >> "$dir/$name.files" 2>/dev/null
  return 0
}

# session_wrote <root> <名前> → そのセッションが Write・Edit（Cursor は afterFileEdit）で何か書いていれば 0（<名前>.files に 1 行以上ある）
#   始まりの印より新しいファイルでは数えない。ほかのセッションや人の手が書いたファイルまで、自分の物と数えてしまうため（改善提案書 13.2）。
#   Bash のコマンドだけで書いたセッションは、AI が検証を自分で回す（AGENTS.md の検証の節）。
session_wrote() { [ -n "${2:-}" ] && [ -s "$(session_dir "$1")/$2.files" ]; }

# is_doc_rel <root からの相対パス> → 終わりの検証で見る文書（tmp/flow/ の下の .md、tmp/ISSUE_*.md、tmp/PR_*.md）なら 0
#   tools/project-verify.sh の is_doc と同じ決まり（変えるときは両方）
is_doc_rel() {
  case "$1" in
    tmp/flow/*.md) return 0 ;;
    tmp/ISSUE_*.md|tmp/PR_*.md) case "${1#tmp/}" in */*) return 1 ;; esac; return 0 ;;
  esac
  return 1
}

# session_docs <root> <名前> → そのセッションの文書（root からの相対パス）を 1 行 1 本、文字の設定によらない順で書く。今ある文書だけ
#   数えるのは <名前>.files に載った文書（Write・Edit と Cursor の afterFileEdit で書いた物）だけ。
#   記録に無い文書（Bash のコマンドで書いた物、ほかのセッションや人の手が書いた物）は、誰が書いたかを見分けられないので、開かず、渡さない。
#   始まりの印より新しいことで拾うと、ほかのセッションが Bash で書いた文書と人の手の文書を、どのセッションも自分の物と数えてしまう。
#   Bash のコマンドで書いた自分の文書は、AI が検証を手で回すときに引数で渡す（改善提案書 13.2）。
session_docs() {
  local r="$1" n="$2" dir f
  [ -n "$n" ] || return 0
  dir="$(session_dir "$r")"
  [ -f "$dir/$n.files" ] || return 0
  while IFS= read -r f; do
    if is_doc_rel "$f" && [ -f "$r/$f" ]; then printf '%s\n' "$f"; fi
  done < "$dir/$n.files" | LC_ALL=C sort -u
}

# session_prune <root> → 14 日（20160 分）より前から、どの記録（.start・.files・.pass）も変わっていないセッションの記録を消す。常に 0
session_prune() {
  local dir f base
  dir="$(session_dir "$1")"
  [ -d "$dir" ] || return 0
  for f in "$dir"/*.start "$dir"/*.files "$dir"/*.pass; do
    [ -f "$f" ] || continue
    base="${f%.*}"
    [ -z "$(find "$base.start" "$base.files" "$base.pass" -mmin -20160 -print 2>/dev/null)" ] || continue
    rm -f "$base.start" "$base.files" "$base.pass" "$base.pass.tmp" 2>/dev/null
  done
  return 0
}

# ---- 作業の終わりの検証（claude-stop.sh と cursor-stop.sh が呼ぶ）

# pv_takes_docs <root> → 移した先の tmp/tools/project-verify.sh が、文書を引数で受ける版なら 0。
#   受ける版は、冒頭の使い方の行に「[--] [<ファイル>...]」の字がある（tools/project-verify.sh の冒頭。字を変えるときは両方）。
#   deploy.sh を回し直す前の古い版は、引数を見ずに tmp/ の文書を全部検査する。そのときは文書を渡さず、前の回し方と差し戻しの文に戻す。
pv_takes_docs() { grep -qF -- '[--] [<ファイル>...]' "$1/tmp/tools/project-verify.sh" 2>/dev/null; }

# end_verify <root> <セッションの名前> → 回すかどうかを決め、回したら結果を END_* に入れる。
#   移した先（verify_cmd が project-verify）と My-Lab（verify_cmd が verify-all）では、セッションの名前が取れないか、
#     そのセッションが Write・Edit で何も書いていなければ、何も回さず、何も読まない（改善提案書 13.2）。
#   移した先: そのセッションの文書だけを -- のあとに渡す。文書が 0 本で tmp/verify-commands.txt も無ければ、何も回さない。
#     文書は、そのセッションが最後に通ったとき（<名前>.pass）より新しい文書があるか、文書の組が変わったときに回す。
#     命令のファイルは、今までどおり changed_since_pass で決める（書いたセッションの終わりにだけ回る）。
#     project-verify.sh が引数を受けない古い版（pv_takes_docs が偽）なら、文書を渡さず、前と同じく changed_since_pass で決めて回す。
#   My-Lab: 書いたセッションでは、今までどおり changed_since_pass で決めて verify-all を回す。My-Lab の検証は、製品の門として全体を見る。
#   それ以外（COMPANY_GUARD_VERIFY_CMD の差し替え）: 今までどおり。
#   戻り値 0: 回さなかったか、通った（終了コード 0 か 3）。1: FAIL。通ったら、ファイルの一覧（last-pass.list）を書く。
#   END_RAN（回したら 1）、END_CMD（人に見せる命令）、END_OUT（出力）、END_RC、END_DOCS（渡した文書）、
#   END_DOCFAIL（渡した文書の検査が落ちたら 1。差し戻しの文を「このセッションで書いた文書の検査」にする）を書く。
#   END_DOCFAIL は、新しい版の行（「（渡した文書」と「引数のファイル」）でだけ立てる。古い版の check-file の行は、ほかのセッションの文書も含むため。
# shellcheck disable=SC2034  # END_* は呼んだ hook が読む
end_verify() {
  local r="$1" n="$2" cmd dir docs_s d need=0 has_cmds=0
  END_DOCS=(); END_CMD=""; END_OUT=""; END_RC=0; END_RAN=0; END_DOCFAIL=0
  cmd="$(verify_cmd "$r")"
  [ -n "$cmd" ] || return 0
  dir="$(session_dir "$r")"
  case "$cmd" in
    'bash tmp/tools/project-verify.sh --fast'|'bash tools/verify-all.sh --fast')
      if [ -z "$n" ] || ! session_wrote "$r" "$n"; then return 0; fi ;;
  esac
  if [ "$cmd" = 'bash tmp/tools/project-verify.sh --fast' ] && pv_takes_docs "$r"; then
    docs_s="$(session_docs "$r" "$n")"
    while IFS= read -r d; do
      if [ -n "$d" ]; then END_DOCS+=("$d"); fi
    done <<EOF
$docs_s
EOF
    [ -f "$r/tmp/verify-commands.txt" ] && has_cmds=1
    if [ "${#END_DOCS[@]}" -eq 0 ] && [ "$has_cmds" -eq 0 ]; then return 0; fi
    if [ "${#END_DOCS[@]}" -gt 0 ]; then
      if [ ! -f "$dir/$n.pass" ] || ! printf '%s\n' "${END_DOCS[@]}" | cmp -s - "$dir/$n.pass"; then
        need=1
      else
        for d in "${END_DOCS[@]}"; do
          if [ -n "$(find "$r/$d" -newer "$dir/$n.pass" -print 2>/dev/null)" ]; then need=1; break; fi
        done
      fi
    fi
    if [ "$has_cmds" -eq 1 ] && changed_since_pass "$r"; then need=1; fi
    [ "$need" -eq 1 ] || return 0
    END_CMD="$cmd"
    if [ "${#END_DOCS[@]}" -gt 0 ]; then
      END_CMD="$END_CMD --"
      for d in "${END_DOCS[@]}"; do END_CMD="$END_CMD '$d'"; done
      printf '%s\n' "${END_DOCS[@]}" > "$dir/$n.pass.tmp" 2>/dev/null   # 回し始めの時刻を、通ったときの印の時刻にする
      END_OUT="$(cd "$r" && bash tmp/tools/project-verify.sh --fast -- "${END_DOCS[@]}" 2>&1)"; END_RC=$?
    else
      END_OUT="$(cd "$r" && bash tmp/tools/project-verify.sh --fast 2>&1)"; END_RC=$?
    fi
    END_RAN=1
    if [ "$END_RC" -eq 0 ] || [ "$END_RC" -eq 3 ]; then
      snapshot_tree "$r"
      if [ "${#END_DOCS[@]}" -gt 0 ]; then mv -f "$dir/$n.pass.tmp" "$dir/$n.pass" 2>/dev/null; fi
      return 0
    fi
    if [ "${#END_DOCS[@]}" -gt 0 ]; then
      rm -f "$dir/$n.pass.tmp" 2>/dev/null
      if printf '%s\n' "$END_OUT" | grep -Eq '^RESULT: FAIL ((check-file|check-refs)（渡した文書|引数のファイル)'; then END_DOCFAIL=1; fi
    fi
    return 1
  fi
  # My-Lab の verify-all、COMPANY_GUARD_VERIFY_CMD の差し替え、引数を受けない古い project-verify: ファイルが変わっていれば回す
  changed_since_pass "$r" || return 0
  END_CMD="$cmd"
  END_OUT="$(cd "$r" && eval "$cmd" 2>&1)"; END_RC=$?
  END_RAN=1
  if [ "$END_RC" -eq 0 ] || [ "$END_RC" -eq 3 ]; then snapshot_tree "$r"; return 0; fi
  return 1
}

# guard_mode_file → 守りの設定（mode のファイル）の root 所有の置き場。自己試験だけが COMPANY_GUARD_MODE_FILE で差し替える
guard_mode_file() { printf '%s' "${COMPANY_GUARD_MODE_FILE:-/usr/local/etc/company-guard/mode}"; }

# guard_mode → 守りの設定を GUARD_MODE（deny か ask）と GUARD_MODE_WHY（deny に倒した理由。無ければ空）に入れる。常に 0
# 読む順:
#   1. 環境変数 COMPANY_GUARD_CURSOR_MODE（自己試験の差し替え）。
#   2. root 所有の置き場 /usr/local/etc/company-guard/mode（社長が sudo で 1 回作る。AI の利用者権限では書けない）。
#      置き場のフォルダがあれば、これだけを使い、~/.cursor は見ない。ファイルが無い・リンク・読めない・中身が deny と ask 以外・
#      自分の権限で書ける（ファイル・置き場のフォルダ・その親のどれか。AI が置けた物か、置き場ごと移せる物）なら、deny に倒す（fail-closed）。
#   3. 置き場が無いときだけ、今までどおり ~/.cursor/company-guard.mode を読む（移行期の互換。無ければ ask）。
#      置き場を「作る前」と「消された」は見分けられない。この Mac では親の /usr/local/etc と /usr/local が root 所有なので消せない。
# shellcheck disable=SC2034  # GUARD_MODE と GUARD_MODE_WHY は呼んだ hooks が読む
guard_mode() {
  local f d p v
  f="$(guard_mode_file)"; d="$(dirname "$f")"; p="$(dirname "$d")"
  GUARD_MODE="ask"; GUARD_MODE_WHY=""
  if [ -n "${COMPANY_GUARD_CURSOR_MODE:-}" ]; then
    [ "$COMPANY_GUARD_CURSOR_MODE" = "deny" ] && GUARD_MODE="deny"
    return 0
  fi
  if [ -d "$d" ] || [ -e "$f" ] || [ -L "$f" ]; then
    GUARD_MODE="deny"
    if [ -L "$f" ]; then GUARD_MODE_WHY="守りの設定（${f}）がリンクなので deny に倒す。"
    elif [ ! -f "$f" ]; then GUARD_MODE_WHY="守りの設定の置き場（${d}）はあるが、ファイルが無いので deny に倒す。"
    elif [ -w "$f" ] || [ -w "$d" ]; then GUARD_MODE_WHY="守りの設定（${f}）が自分の権限で書けるので deny に倒す。root 所有にする。"
    elif [ -w "$p" ]; then GUARD_MODE_WHY="守りの設定の置き場の親（${p}）が自分の権限で書けるので deny に倒す。置き場ごと移せるため、親も root 所有にする。"
    elif ! v="$(tr -d '[:space:]' < "$f" 2>/dev/null)"; then GUARD_MODE_WHY="守りの設定（${f}）を読めないので deny に倒す。"
    else
      case "$v" in
        deny) ;;
        ask)  GUARD_MODE="ask" ;;
        *)    GUARD_MODE_WHY="守りの設定（${f}）の中身が deny でも ask でもないので deny に倒す。" ;;
      esac
    fi
    return 0
  fi
  v="$(tr -d '[:space:]' < "$HOME/.cursor/company-guard.mode" 2>/dev/null || true)"
  [ "$v" = "deny" ] && GUARD_MODE="deny"
  return 0
}

# real_path <パス> → リンクをたどった実体の絶対パス。まだ無いファイルは、ある所までたどり、残りをそのまま付ける。解けなければ 1
# /bin/pwd -P を使うのは、bash 3.2 の組み込みの pwd -P が大文字小文字の違う綴りをそのまま返すため（APFS では同じ場所）
real_path() {
  local f="$1" rest="" d t n=0 m=0
  while [ "$n" -lt 64 ]; do
    n=$((n + 1))
    if [ -L "$f" ]; then                 # リンクなら 1 段たどる（指す先がまだ無くても）
      m=$((m + 1)); [ "$m" -le 20 ] || return 1
      d="$(CDPATH='' cd "$(dirname "$f")" 2>/dev/null && { /bin/pwd -P 2>/dev/null || pwd -P; })" || d="$(dirname "$f")"
      t="$(readlink "$f")" || return 1
      case "$t" in /*) f="$t" ;; *) f="$d/$t" ;; esac
      continue
    fi
    if [ -d "$f" ]; then
      d="$(CDPATH='' cd "$f" && { /bin/pwd -P 2>/dev/null || pwd -P; })" || return 1
      printf '%s%s\n' "${d%/}" "$rest"; return 0
    fi
    if [ -e "$f" ]; then
      d="$(CDPATH='' cd "$(dirname "$f")" && { /bin/pwd -P 2>/dev/null || pwd -P; })" || return 1
      printf '%s/%s%s\n' "${d%/}" "$(basename "$f")" "$rest"; return 0
    fi
    case "$f" in /|.|"") return 1 ;; esac   # 根まで何も無い
    rest="/$(basename "$f")$rest"; f="$(dirname "$f")"   # 無い部分を 1 段はがす
  done
  return 1
}

# link_count <パス> → そのファイルが持つ名前の数（ハードリンクの数）。macOS と BSD は stat -f %l、Linux は stat -c %h。取れなければ空
# Linux の stat -f はファイルシステムの情報で、%l は名前の長さの上限を返してしまうので、OS で分ける
link_count() {
  case "$(uname -s 2>/dev/null)" in
    Darwin|*BSD*) stat -f %l "$1" 2>/dev/null || : ;;
    *)            stat -c %h "$1" 2>/dev/null || : ;;
  esac
}

# lower <文字列> → ASCII の大文字を小文字にした文字列。APFS は大文字小文字を区別しないので、パスの比較の前に両側をそろえる
lower() { printf '%s' "$1" | LC_ALL=C tr '[:upper:]' '[:lower:]'; }

# log <文> → tmp/.verify/hooks.log に 1 行。コマンドの本文は書かない（秘密が混ざるため）
log() {
  mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || return 0
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE" 2>/dev/null || true
}
