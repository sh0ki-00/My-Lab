#!/usr/bin/env bash
# shellcheck disable=SC2329  # 場面の関数は、名前を組み立てて呼ぶ（下の「実行」）
# tools/tests/install-test.sh [<install.sh>] — install.sh の試験。偽の HOME で回し、本物の HOME には触れない。
#   引数で試す install.sh を選べる（既定は My-Lab の install.sh）。直す前の版と比べるときに使う。
#   置き場ごとに install.sh の写しと、身代わりの hooks 7 本（呼ばれた名前と引数を出すだけ）を置く。試すのは install.sh だけ。
#   場面は全部、LANG=C と LANG=ja_JP.UTF-8 の 2 通りで回す。bash は社長の機械と同じ /bin/bash（3.2）を使う。
# 出力: 場面ごとに PASS <場面> [<LANG>] か FAIL <場面> [<LANG>] <理由>。最後に RESULT 行。1 件でも FAIL なら終了コード 1。
set -u
unset CDPATH
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
NAME="install-test"
RUN_PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
REAL_HOME="${HOME:-}"
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)" || exit 1
SUT="${1:-$HERE/../../install.sh}"
total=0; failed=0

abort() {  # abort <理由> → 試験を回せない。FAIL と RESULT を出して止める
  printf 'FAIL %s %s\n' "$NAME" "$1"
  printf 'RESULT: FAIL %s (%d 件中 FAIL %d)\n' "$NAME" "$((total + 1))" "$((failed + 1))"
  exit 1
}
[ -f "$SUT" ] || abort "試す install.sh が無い（${SUT}）"
command -v jq >/dev/null 2>&1 || abort "jq が入っていない"
locale -a 2>/dev/null | grep -qx 'ja_JP.UTF-8' || abort "文字の設定 ja_JP.UTF-8 が無い（SKIP は FAIL と同じ）"
T="$(mktemp -d "${TMPDIR:-/tmp}/install-test.XXXXXX")" || abort "一時ディレクトリを作れない"
trap 'chmod -R u+w "$T" 2>/dev/null; rm -rf "$T"' EXIT
T="$(cd -- "$T" && pwd -P)" || abort "一時ディレクトリに入れない"   # /var と /private/var の別名をそろえる
# 登録の字面を「bash <置き場>/… --global」と比べるので、一時ディレクトリには空白も記号も無いこと
if printf '%s' "$T" | LC_ALL=C grep -q '[^A-Za-z0-9_./@%+=:,-]'; then abort "一時ディレクトリのパスに空白か記号がある（${T}）。TMPDIR を変えて回す"; fi

# ---- 部品
mklab() {  # mklab <置き場> → install.sh の写しと、身代わりの hooks 7 本を置く
  local d="$1" n
  mkdir -p "$d/hooks" && cp "$SUT" "$d/install.sh" || return 1
  for n in claude-pretooluse claude-preedit claude-postedit claude-stop cursor-before-shell cursor-after-edit cursor-stop; do
    cat > "$d/hooks/$n.sh" <<'EOF'
#!/bin/bash
echo "ran $(basename "$0") $*"
EOF
  done
}

run() {  # run <偽の HOME> <作業ディレクトリ> <env に渡す残り...> → OUT と RC。環境は空にし、HOME と PATH と LANG だけを渡す
  local fh="$1" wd="$2"; shift 2
  case "$fh" in "$T"/*) ;; *) abort "偽の HOME が一時ディレクトリの外にある（${fh}）" ;; esac
  [ "$fh" != "$REAL_HOME" ] || abort "本物の HOME では回さない"
  OUT="$(cd -- "$wd" && env -i HOME="$fh" PATH="$RUN_PATH" LANG="$L" "$@" 2>&1)"; RC=$?
}

last() { printf '%s\n' "$OUT" | tail -n 1; }
has() { printf '%s\n' "$OUT" | grep -qF -- "$1"; }

cmds() {  # cmds <ファイル> <イベント> [<matcher>] → そのイベント（matcher を指せばその組だけ）に登録された命令を 1 行に 1 つ
  jq -r --arg e "$2" --arg m "${3:-}" '(.hooks[$e] // [])[] | if (type == "object" and has("hooks")) then (select($m == "" or .matcher == $m) | .hooks[].command) else .command end' "$1" 2>/dev/null
}

# <ツール>:<イベント>:<matcher（無ければ空）>:<接続口の名前>。Claude の PreToolUse は Bash と Edit の 2 組
EVENTS="claude:PreToolUse:Bash:claude-pretooluse claude:PreToolUse:Edit|Write|MultiEdit|NotebookEdit:claude-preedit claude:PostToolUse::claude-postedit claude:Stop::claude-stop cursor:beforeShellExecution::cursor-before-shell cursor:afterFileEdit::cursor-after-edit cursor:stop::cursor-stop"
split_spec() { tool="${1%%:*}"; rest="${1#*:}"; e="${rest%%:*}"; rest="${rest#*:}"; m="${rest%%:*}"; n="${rest#*:}"; }   # split_spec <spec> → tool e m n
file_of() { case "$1" in claude) printf '%s\n' "$2/.claude/settings.json" ;; *) printf '%s\n' "$2/.cursor/hooks.json" ;; esac; }

one_each() {  # one_each <偽の HOME> <hooks の置き場> → 7 つの組に命令が 1 本ずつあり、字面が「bash <置き場>/<名前>.sh --global」
  local fh="$1" h="$2" spec tool rest e m n got
  for spec in $EVENTS; do
    split_spec "$spec"
    got="$(cmds "$(file_of "$tool" "$fh")" "$e" "$m")"
    [ "$got" = "bash $h/$n.sh --global" ] || { REASON="${e} の登録が想定と違う: $(printf '%s' "$got" | tr '\n' '|')"; return 1; }
  done
}

runs_each() {  # runs_each <偽の HOME> → 7 つの組に命令が 1 本ずつあり、sh -c で走らせると身代わりが名前と --global を受け取る
  local fh="$1" spec tool rest e m n got out
  for spec in $EVENTS; do
    split_spec "$spec"
    got="$(cmds "$(file_of "$tool" "$fh")" "$e" "$m")"
    [ "$(printf '%s\n' "$got" | grep -c .)" -eq 1 ] || { REASON="${e} の登録が 1 本でない: $(printf '%s' "$got" | tr '\n' '|')"; return 1; }
    out="$(cd -- "$T" && env -i HOME="$fh" PATH="$RUN_PATH" LANG="$L" /bin/sh -c "$got" </dev/null 2>&1)"
    [ "$out" = "ran $n.sh --global" ] || { REASON="${e} の命令が走らない（${got}）: ${out}"; return 1; }
  done
}

unchanged() {  # unchanged <ファイル> <写し> → 1 バイトも変わっていない
  cmp -s "$1" "$2" || { REASON="$(basename "$1") が書き換わった（$(wc -c < "$1" | tr -d ' ') バイト）"; return 1; }
}

no_backup() {  # no_backup <偽の HOME> → 退避のファイルが 1 つも無い
  local b; b="$(find "$1" -name '*.bak.*' 2>/dev/null)"
  [ -z "$b" ] || { REASON="退避ができた: $(printf '%s' "$b" | tr '\n' ' ')"; return 1; }
}

nbak() { find "$1" -name "$2.bak.*" 2>/dev/null | grep -c .; }   # nbak <ディレクトリ> <ファイル名> → 退避の数

home() {  # home [claude] [cursor] → 偽の HOME（$W/home）と、指定の設定ディレクトリを作る。FH に入れる
  FH="$W/home"; mkdir -p "$FH" || return 1
  local x; for x in "$@"; do mkdir -p "$FH/.$x" || return 1; done
}

cradle() {  # cradle → 旧 cradle-skills の実体（$W/My Lab/cradle-skills）。CR に入れる
  CR="$W/My Lab/cradle-skills"
  mkdir -p "$CR/skills/alpha" "$CR/skills/hidden" "$CR/hooks" && : > "$CR/hooks/cradle-guard-claude.sh" && : > "$CR/hooks/cradle-guard-cursor.sh"
}

old_links() {  # old_links → 偽の HOME に旧リンク 3 本（skills・Claude の hooks・Cursor の hooks）を置く
  mkdir -p "$FH/.claude/skills" "$FH/.claude/hooks" "$FH/.cursor/hooks" || return 1
  ln -s "$CR/skills/alpha" "$FH/.claude/skills/alpha"
  ln -s "$CR/hooks/cradle-guard-claude.sh" "$FH/.claude/hooks/cradle-guard-claude.sh"
  ln -s "$CR/hooks/cradle-guard-cursor.sh" "$FH/.cursor/hooks/cradle-guard-cursor.sh"
}
OLD3="claude/skills/alpha:skills/alpha claude/hooks/cradle-guard-claude.sh:hooks/cradle-guard-claude.sh cursor/hooks/cradle-guard-cursor.sh:hooks/cradle-guard-cursor.sh"

GOOD_CL='{"model":"keep","permissions":{"allow":["Bash(ls:*)"]},"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"/x/cradle-guard-claude.sh"}]}]}}'
GOOD_CU='{"version":1,"hooks":{"beforeShellExecution":[{"command":"/x/cradle-guard-cursor.sh"}]}}'

# ---- 場面
case_basic() {  # 登録の中身（字面・timeout・failClosed・loop_limit）、他の設定と他のツールの登録が残ること
  local lab="$W/lab/My-Lab"
  mklab "$lab" && home claude cursor || return 1
  printf '%s\n' '{"model":"keep","permissions":{"allow":["Bash(ls:*)"]},"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"/x/cradle-guard-claude.sh"}]},{"matcher":"Bash","hooks":[{"type":"command","command":"/opt/tool/hooks/claude-stop.sh"},{"type":"command","command":"bash /opt/tool/hooks/claude-stop-helper.sh --global"}]}]}}' > "$FH/.claude/settings.json"
  printf '%s\n' '{"version":1,"hooks":{"beforeShellExecution":[{"command":"/x/cradle-guard-cursor.sh"}],"afterFileEdit":[{"command":"/opt/tool/after.sh"}]}}' > "$FH/.cursor/hooks.json"
  run "$FH" "$W" /bin/bash "$lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="終了コード ${RC}: $(last)"; return 1; }
  jq -e --arg h "$lab/hooks" '.model == "keep" and .permissions.allow == ["Bash(ls:*)"]
    and ([.hooks.PreToolUse[].hooks[].command] == ["/opt/tool/hooks/claude-stop.sh", "bash /opt/tool/hooks/claude-stop-helper.sh --global", "bash \($h)/claude-pretooluse.sh --global", "bash \($h)/claude-preedit.sh --global"])
    and (.hooks.PreToolUse[-2] == {matcher: "Bash", hooks: [{type: "command", command: "bash \($h)/claude-pretooluse.sh --global", timeout: 20}]})
    and (.hooks.PreToolUse[-1] == {matcher: "Edit|Write|MultiEdit|NotebookEdit", hooks: [{type: "command", command: "bash \($h)/claude-preedit.sh --global", timeout: 20}]})
    and (.hooks.PostToolUse == [{matcher: "Edit|Write|MultiEdit|NotebookEdit", hooks: [{type: "command", command: "bash \($h)/claude-postedit.sh --global", timeout: 120}]}])
    and (.hooks.Stop == [{hooks: [{type: "command", command: "bash \($h)/claude-stop.sh --global", timeout: 600}]}])' \
    "$FH/.claude/settings.json" >/dev/null 2>&1 || { REASON="Claude の登録か、他の設定が想定と違う"; return 1; }
  jq -e --arg h "$lab/hooks" '.version == 1
    and (.hooks.beforeShellExecution == [{command: "bash \($h)/cursor-before-shell.sh --global", failClosed: true, timeout: 20}])
    and (.hooks.afterFileEdit == [{command: "/opt/tool/after.sh"}, {command: "bash \($h)/cursor-after-edit.sh --global", timeout: 120}])
    and (.hooks.stop == [{command: "bash \($h)/cursor-stop.sh --global", timeout: 600, loop_limit: 3}])' \
    "$FH/.cursor/hooks.json" >/dev/null 2>&1 || { REASON="Cursor の登録が想定と違う"; return 1; }
}

broken_case() {  # broken_case <settings.json の中身> <hooks.json の中身> [install.sh の引数...] → 何も書かず、FAIL と終了コード 1
  local lab="$W/lab/My-Lab" cl="$1" cu="$2"; shift 2
  mklab "$lab" && home claude cursor || return 1
  printf '%b' "$cl" > "$FH/.claude/settings.json"; cp "$FH/.claude/settings.json" "$W/orig-cl"
  printf '%b' "$cu" > "$FH/.cursor/hooks.json"; cp "$FH/.cursor/hooks.json" "$W/orig-cu"
  run "$FH" "$W" /bin/bash "$lab/install.sh" "$@"
  [ "$RC" -eq 1 ] || { REASON="終了コード ${RC}（1 のはず）: $(last)"; return 1; }
  printf '%s\n' "$OUT" | grep -q '^FAIL install: ' || { REASON="FAIL の行が無い: $(last)"; return 1; }
  unchanged "$FH/.claude/settings.json" "$W/orig-cl" && unchanged "$FH/.cursor/hooks.json" "$W/orig-cu" && no_backup "$FH"
}
case_broken_json_claude() { broken_case '{\n  // my settings\n  "model": "opus"\n}\n' "$GOOD_CU\n"; }
case_broken_json_cursor() { broken_case "$GOOD_CL\n" '{"version":1,"hooks":{},}\n'; }
case_dry_run_broken() { broken_case '{"model":"opus",}\n' "$GOOD_CU\n" --dry-run; }
case_wrong_shape() {  # 最上位が配列、hooks が配列、2 つの object、hooks の無いグループ、command が配列
  local s n=0 base="$W"
  for s in '[]' '{"hooks":[]}' '{}{}' '{"hooks":{"PreToolUse":[{"matcher":"Bash"}]}}' '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":["a"]}]}]}}'; do
    n=$((n + 1)); W="$base/$n"; mkdir -p "$W"
    broken_case "$s\n" "$GOOD_CU\n" || { REASON="形 ${s}: ${REASON}"; W="$base"; return 1; }
  done
  W="$base"
}

case_dry_run_writes_nothing() {  # 読める設定でも、--dry-run は中身を見せるだけで何も書かない
  local lab="$W/lab/My-Lab"
  mklab "$lab" && home claude cursor || return 1
  printf '%s\n' "$GOOD_CL" > "$FH/.claude/settings.json"; cp "$FH/.claude/settings.json" "$W/orig-cl"
  printf '%s\n' "$GOOD_CU" > "$FH/.cursor/hooks.json"; cp "$FH/.cursor/hooks.json" "$W/orig-cu"
  run "$FH" "$W" /bin/bash "$lab/install.sh" --dry-run
  [ "$RC" -eq 0 ] || { REASON="終了コード ${RC}: $(last)"; return 1; }
  if ! { has "claude-pretooluse.sh --global" && has "（書き込まない）"; }; then REASON="書き込む中身を見せない"; return 1; fi
  unchanged "$FH/.claude/settings.json" "$W/orig-cl" && unchanged "$FH/.cursor/hooks.json" "$W/orig-cu" && no_backup "$FH"
}

case_empty_files() {  # 0 バイトの settings.json と、空白だけの hooks.json は {} とみなして登録する
  local lab="$W/lab/My-Lab"
  mklab "$lab" && home claude cursor || return 1
  : > "$FH/.claude/settings.json"; printf '  \n\t\n' > "$FH/.cursor/hooks.json"
  run "$FH" "$W" /bin/bash "$lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="終了コード ${RC}: $(last)"; return 1; }
  one_each "$FH" "$lab/hooks"
}

case_space_path() {  # 置き場に空白がある
  local lab="$W/My Lab/My-Lab"
  mklab "$lab" && home claude cursor || return 1
  run "$FH" "$W" /bin/bash "$lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="終了コード ${RC}: $(last)"; return 1; }
  runs_each "$FH"
}

case_symbol_path() {  # 置き場に日本語・括弧・引用符がある。2 回回しても 1 本ずつ
  local lab="$W/案件 (2026)/Bob's Lab/My-Lab"
  mklab "$lab" && home claude cursor || return 1
  run "$FH" "$W" /bin/bash "$lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="1 回目の終了コード ${RC}: $(last)"; return 1; }
  run "$FH" "$W" /bin/bash "$lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="2 回目の終了コード ${RC}: $(last)"; return 1; }
  runs_each "$FH"
}

case_via_link() {  # リンク経由で回すと、hooks の無い置き場を登録せずに止まる
  local lab="$W/lab/My-Lab"
  mklab "$lab" && home claude cursor && mkdir -p "$W/bin" && ln -s "$lab/install.sh" "$W/bin/mylab-install" || return 1
  run "$FH" "$W" /bin/bash "$W/bin/mylab-install"
  [ "$RC" -eq 1 ] || { REASON="終了コード ${RC}（1 のはず）: $(last)"; return 1; }
  printf '%s\n' "$OUT" | grep -q '^FAIL install: ' || { REASON="FAIL の行が無い: $(last)"; return 1; }
  [ ! -e "$FH/.claude/settings.json" ] && [ ! -e "$FH/.cursor/hooks.json" ] || { REASON="設定ファイルを書いた"; return 1; }
}

case_moved_lab() {  # 置き場を移してから回すと、古い置き場の登録が消えて 1 本ずつになる
  mklab "$W/old/My-Lab" && home claude cursor || return 1
  run "$FH" "$W" /bin/bash "$W/old/My-Lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="1 回目の終了コード ${RC}: $(last)"; return 1; }
  mv "$W/old" "$W/new" || return 1
  run "$FH" "$W" /bin/bash "$W/new/My-Lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="2 回目の終了コード ${RC}: $(last)"; return 1; }
  one_each "$FH" "$W/new/My-Lab/hooks"
}

case_second_clone() {  # 別の clone（名前の大文字と小文字も違う）から回すと、前の登録が消えて 1 本ずつになる
  mklab "$W/a/My-Lab" && mklab "$W/b/my-lab" && home claude cursor || return 1
  run "$FH" "$W" /bin/bash "$W/a/My-Lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="1 回目の終了コード ${RC}: $(last)"; return 1; }
  run "$FH" "$W" /bin/bash "$W/b/my-lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="2 回目の終了コード ${RC}: $(last)"; return 1; }
  one_each "$FH" "$W/b/my-lab/hooks"
}

shim() {  # shim <ディレクトリ> <日時> → date が常にその日時を返す PATH の頭
  mkdir -p "$1" && printf '#!/bin/sh\necho %s\n' "$2" > "$1/date" && chmod +x "$1/date"
}

case_same_second_backups() {  # 同じ秒に 2 回書いても、元の中身の退避が残る
  local lab="$W/lab/My-Lab"
  mklab "$lab" && home claude cursor && shim "$W/shim" 20261108-120000 || return 1
  printf '%s\n' "$GOOD_CL" > "$FH/.claude/settings.json"
  run "$FH" "$W" PATH="$W/shim:$RUN_PATH" /bin/bash "$lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="1 回目の終了コード ${RC}: $(last)"; return 1; }
  jq -c '.model = "second"' "$FH/.claude/settings.json" > "$W/next.json" && mv "$W/next.json" "$FH/.claude/settings.json" || return 1
  run "$FH" "$W" PATH="$W/shim:$RUN_PATH" /bin/bash "$lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="2 回目の終了コード ${RC}: $(last)"; return 1; }
  [ "$(nbak "$FH/.claude" settings.json)" -eq 2 ] || { REASON="settings.json の退避が $(nbak "$FH/.claude" settings.json) 個（2 のはず）"; return 1; }
  grep -lq 'cradle-guard-claude.sh' "$FH/.claude/settings.json.bak."* 2>/dev/null || { REASON="元の中身（旧 cradle の登録）がどの退避にも無い"; return 1; }
}

case_unchanged_no_backup() {  # 中身が変わらない 2 回目は、書き換えも退避もしない
  local lab="$W/lab/My-Lab"
  mklab "$lab" && home claude cursor && shim "$W/s1" 20261108-120001 && shim "$W/s2" 20261108-120002 || return 1
  printf '%s\n' "$GOOD_CL" > "$FH/.claude/settings.json"; printf '%s\n' "$GOOD_CU" > "$FH/.cursor/hooks.json"
  run "$FH" "$W" PATH="$W/s1:$RUN_PATH" /bin/bash "$lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="1 回目の終了コード ${RC}: $(last)"; return 1; }
  cp "$FH/.claude/settings.json" "$W/cl1"; cp "$FH/.cursor/hooks.json" "$W/cu1"
  run "$FH" "$W" PATH="$W/s2:$RUN_PATH" /bin/bash "$lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="2 回目の終了コード ${RC}: $(last)"; return 1; }
  unchanged "$FH/.claude/settings.json" "$W/cl1" && unchanged "$FH/.cursor/hooks.json" "$W/cu1" || return 1
  [ "$(nbak "$FH" '*')" -eq 2 ] || { REASON="退避が $(nbak "$FH" '*') 個（1 回目の 2 個だけのはず）"; return 1; }
}

listed() {  # listed <見出し> → OLD3 の 3 本が「<見出し> <リンク> -> <リンク先>」で並ぶ
  local p l t
  for p in $OLD3; do
    l="$FH/.${p%%:*}"; t="$CR/${p#*:}"
    has "$1 $l -> $t" || { REASON="「$1 ${l} -> ${t}」の行が無い: $(last)"; return 1; }
  done
}

case_dry_run_lists() {  # --dry-run --remove-old-links は外すリンクを並べ、外さない
  local lab="$W/lab/My-Lab" p
  mklab "$lab" && home claude cursor && cradle && old_links || return 1
  run "$FH" "$W" /bin/bash "$lab/install.sh" --dry-run --remove-old-links
  [ "$RC" -eq 0 ] || { REASON="終了コード ${RC}: $(last)"; return 1; }
  listed "外す予定:" || return 1
  has "--dry-run なので" || { REASON="--dry-run で外していないと言わない"; return 1; }
  for p in $OLD3; do [ -L "$FH/.${p%%:*}" ] || { REASON="--dry-run なのに .${p%%:*} を外した"; return 1; }; done
}

case_real_run_lists() {  # --remove-old-links は外したリンクと指し先を並べる。実体は残る
  local lab="$W/lab/My-Lab" p
  mklab "$lab" && home claude cursor && cradle && old_links || return 1
  run "$FH" "$W" /bin/bash "$lab/install.sh" --remove-old-links
  [ "$RC" -eq 0 ] || { REASON="終了コード ${RC}: $(last)"; return 1; }
  listed "外した:" || return 1
  for p in $OLD3; do
    [ ! -L "$FH/.${p%%:*}" ] || { REASON=".${p%%:*} が残った"; return 1; }
    [ -e "$CR/${p#*:}" ] || { REASON="実体 ${p#*:} が消えた"; return 1; }
  done
}

case_narrow_match() {  # 名前に cradle-skills を含むだけの、社長自身のリンクは外さない
  local lab="$W/lab/My-Lab"
  mklab "$lab" && home claude cursor && cradle || return 1
  mkdir -p "$FH/.claude/skills" "$W/work/notes-on-cradle-skills" "$W/src/my-cradle-skills-fork/skills/team-review"
  ln -s "$W/work/notes-on-cradle-skills" "$FH/.claude/skills/review-notes"
  ln -s "$W/src/my-cradle-skills-fork/skills/team-review" "$FH/.claude/skills/team-review"
  ln -s "$CR/skills/alpha" "$FH/.claude/skills/alpha"
  run "$FH" "$W" /bin/bash "$lab/install.sh" --remove-old-links
  [ "$RC" -eq 0 ] || { REASON="終了コード ${RC}: $(last)"; return 1; }
  [ -L "$FH/.claude/skills/review-notes" ] && [ -L "$FH/.claude/skills/team-review" ] || { REASON="社長自身のリンクを外した"; return 1; }
  [ ! -L "$FH/.claude/skills/alpha" ] || { REASON="旧 cradle-skills のリンクが残った"; return 1; }
}

case_hidden_link() {  # . で始まる名前の旧リンクも外す
  local lab="$W/lab/My-Lab"
  mklab "$lab" && home claude cursor && cradle || return 1
  mkdir -p "$FH/.claude/skills" && ln -s "$CR/skills/hidden" "$FH/.claude/skills/.hidden-skill" || return 1
  run "$FH" "$W" /bin/bash "$lab/install.sh" --remove-old-links
  [ "$RC" -eq 0 ] || { REASON="終了コード ${RC}: $(last)"; return 1; }
  [ ! -L "$FH/.claude/skills/.hidden-skill" ] || { REASON=". で始まる名前の旧リンクが残った"; return 1; }
  has "外した: $FH/.claude/skills/.hidden-skill -> $CR/skills/hidden" || { REASON="外したリンクの行が無い: $(last)"; return 1; }
}

case_dir_link_warn() {  # 調べる置き場そのものがリンクなら WARN を出す。外さない
  local lab="$W/lab/My-Lab"
  mklab "$lab" && home claude cursor && cradle || return 1
  ln -s "$CR/skills" "$FH/.claude/skills" || return 1
  run "$FH" "$W" /bin/bash "$lab/install.sh" --remove-old-links
  [ "$RC" -eq 0 ] || { REASON="終了コード ${RC}: $(last)"; return 1; }
  printf '%s\n' "$OUT" | grep -F -- "$FH/.claude/skills" | grep -q '^WARN install: ' || { REASON="置き場そのもののリンクに WARN が無い"; return 1; }
  [ -L "$FH/.claude/skills" ] && [ -d "$CR/skills/alpha" ] || { REASON="置き場のリンクか実体が消えた"; return 1; }
}

case_rm_fail_continues() {  # 1 本外せなくても残りを外し、外せない名前と要約を出して、最後に終了コード 1
  local lab="$W/lab/My-Lab"
  mklab "$lab" && home claude cursor && cradle && old_links || return 1
  chmod 555 "$FH/.claude/skills"
  run "$FH" "$W" /bin/bash "$lab/install.sh" --remove-old-links
  chmod 755 "$FH/.claude/skills"
  [ "$RC" -eq 1 ] || { REASON="終了コード ${RC}（1 のはず）: $(last)"; return 1; }
  [ ! -L "$FH/.claude/hooks/cradle-guard-claude.sh" ] && [ ! -L "$FH/.cursor/hooks/cradle-guard-cursor.sh" ] || { REASON="外せるリンクまで残った"; return 1; }
  printf '%s\n' "$OUT" | grep -F -- "$FH/.claude/skills/alpha" | grep -q '^FAIL install: ' || { REASON="外せないリンクの FAIL の行が無い"; return 1; }
  has "install: 確認は" || { REASON="最後の案内が出ない"; return 1; }
}

case_no_original_message() {  # 元のファイルが無いときは、無い退避のパスを出さない
  local lab="$W/lab/My-Lab" b
  mklab "$lab" && home claude cursor || return 1
  run "$FH" "$W" /bin/bash "$lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="終了コード ${RC}: $(last)"; return 1; }
  for b in $(printf '%s\n' "$OUT" | grep -oE "${FH}/\.(claude|cursor)/[a-z]+\.json\.bak\.[0-9.-]+"); do
    [ -e "$b" ] || { REASON="無い退避を出した: ${b}"; return 1; }
  done
  [ "$(printf '%s\n' "$OUT" | grep -cF '退避: なし（元のファイルが無かった）')" -eq 2 ] || { REASON="退避が無いことを 2 つとも言わない"; return 1; }
}

case_no_cursor_dir() {  # ~/.cursor が無ければ作らず、Cursor の登録を飛ばしたと言う
  local lab="$W/lab/My-Lab"
  mklab "$lab" && home claude || return 1
  run "$FH" "$W" /bin/bash "$lab/install.sh"
  [ "$RC" -eq 0 ] || { REASON="終了コード ${RC}: $(last)"; return 1; }
  [ ! -e "$FH/.cursor" ] || { REASON="偽の HOME に .cursor を作った"; return 1; }
  has "Cursor の登録は飛ばした" || { REASON="Cursor を飛ばしたと言わない"; return 1; }
  [ "$(cmds "$FH/.claude/settings.json" PreToolUse Bash)" = "bash $lab/hooks/claude-pretooluse.sh --global" ] || { REASON="Claude の登録が無い"; return 1; }
  [ "$(cmds "$FH/.claude/settings.json" PreToolUse 'Edit|Write|MultiEdit|NotebookEdit')" = "bash $lab/hooks/claude-preedit.sh --global" ] || { REASON="Claude の Write・Edit の門の登録が無い"; return 1; }
}

case_cdpath() {  # CDPATH があっても、回した install.sh の置き場を登録する
  mklab "$W/w/Lab" && mklab "$W/o/Lab" && home claude cursor || return 1
  run "$FH" "$W/w" CDPATH="$W/o" /bin/bash Lab/install.sh
  [ "$RC" -eq 0 ] || { REASON="終了コード ${RC}: $(last)"; return 1; }
  one_each "$FH" "$W/w/Lab/hooks"
}

case_dash_dir() {  # 名前が - で始まる置き場でも、その置き場を登録する
  mklab "$W/w/-lab" && home claude cursor || return 1
  run "$FH" "$W/w" /bin/bash -- -lab/install.sh
  [ "$RC" -eq 0 ] || { REASON="終了コード ${RC}: $(last)"; return 1; }
  one_each "$FH" "$W/w/-lab/hooks"
}

# ---- 実行
CASES="basic dry-run-writes-nothing broken-json-claude broken-json-cursor dry-run-broken wrong-shape empty-files space-path symbol-path via-link moved-lab second-clone same-second-backups unchanged-no-backup dry-run-lists real-run-lists narrow-match hidden-link dir-link-warn rm-fail-continues no-original-message no-cursor-dir cdpath dash-dir"
for L in C ja_JP.UTF-8; do
  for c in $CASES; do
    W="$T/$L/$c"; FH=""; CR=""; OUT=""; RC=0; REASON=""
    mkdir -p "$W" || abort "置き場を作れない（${W}）"
    total=$((total + 1))
    if "case_$(printf '%s' "$c" | tr '-' '_')"; then
      printf 'PASS %s [%s]\n' "$c" "$L"
    else
      failed=$((failed + 1))
      REASON="${REASON:-準備に失敗した}"; REASON="${REASON//"$T"/<tmp>}"   # 1 行にし、一時ディレクトリは <tmp> と書く
      printf 'FAIL %s [%s] %s\n' "$c" "$L" "$(printf '%s' "$REASON" | tr '\n' ' ')"
    fi
  done
done
if [ "$failed" -eq 0 ]; then printf 'RESULT: PASS %s (%d 件)\n' "$NAME" "$total"; exit 0; fi
printf 'RESULT: FAIL %s (%d 件中 FAIL %d)\n' "$NAME" "$total" "$failed"
exit 1
