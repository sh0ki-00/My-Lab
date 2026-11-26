#!/usr/bin/env bash
# tools/tests/deployed-checks-test.sh — 写した先（<プロジェクト>/tmp/tools）で、検査の道具が決まりどおりに動くかの試験。
#   1. check-file.sh は、tmp/ の外のファイル（プロジェクト自身のもの）に、現場の語の検査（check-terms）だけを回す。tmp/ の中の文書は全部の検査を回す。
#   2. project-verify.sh は、写した先の PASS でだけ tmp/.verify/last-pass を更新する。Stop の hook は、変更の無い 2 回目を回さない。
#   3. project-verify.sh は、引数で渡した、空白と日本語を含む文書のパスを 1 本のまま check-file と check-refs に渡す。
#   4. project-verify.sh は、引数で渡した文書だけを検査する。引数が無ければ文書を検査しない。--baseline は移した時点の印を置く。
#      文書も命令も無く何も検査しない回は、PASS にせず WARN（終了コード 3）で終わり、印を書かない。
#      細かい場面（改善提案書 13 章の V-1〜V-4）は tools/tests/project-verify-scope-test.sh が確かめる。
#   5. check-file.sh は、写した先で AI が書く資料（tmp/flow、tmp/ISSUE_*）と雛形で「秘書」「社長」の語を落とす。「」の引用は通す。My-Lab の tmp/flow では見ない。
#   6. check-file.sh は、tools/ja-terms.txt の現場の語を、.md 以外の文字のファイルでも落とす。「」の中は通す。
#      移した先のプロジェクト自身のファイルは、git の HEAD から足した行だけを見る。追跡していないファイルは全体を見る。
#      HEAD を作るため、使い捨てのリポジトリ（mktemp の下）でだけ git add と git commit を回す。
# 偽のプロジェクトは手で作る（git init、tools/ を tmp/tools に写す、tmp/DEPLOYED.md を書く）。deploy.sh は使わない。
# hooks/ は使い捨ての場所に写して回す。本物の HOME と、My-Lab の tmp/.verify には書かない。
# 場面は全部、LANG=C と LANG=ja_JP.UTF-8 の 2 通りで回す。
# 出力: 場面ごとに PASS <場面> か FAIL <場面> <理由>。最後に RESULT 行。1 件でも FAIL なら終了コード 1。
set -u
LAB="$(cd "$(dirname "$0")/../.." && pwd -P)" || exit 1
NAME="deployed-checks-test"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
RUN_PATH="/opt/homebrew/bin:/usr/bin:/bin"
EN_TEXT="This service handles order intake for the shop and stores every order in PostgreSQL for later reporting."
total=0; failed=0

ok() { total=$((total + 1)); printf 'PASS %s\n' "$1"; }
ng() { total=$((total + 1)); failed=$((failed + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }
finish() {
  if [ "$failed" -eq 0 ]; then printf 'RESULT: PASS %s (%d 件)\n' "$NAME" "$total"; exit 0; fi
  printf 'RESULT: FAIL %s (%d 件中 FAIL %d)\n' "$NAME" "$total" "$failed"; exit 1
}

if [ ! -f "$LAB/tools/check-file.sh" ] || [ ! -f "$LAB/hooks/claude-stop.sh" ]; then
  ng setup "My-Lab の tools/ と hooks/ が見つからない（${LAB}）"; finish
fi
tmpbase="${TMPDIR:-/tmp}"
T="$(mktemp -d "${tmpbase%/}/deployed-checks.XXXXXX")" || exit 1
trap 'rm -rf "$T"' EXIT
FH="$T/home"
mkdir -p "$FH" "$T/lab-hooks"
if [ "$FH" = "${HOME:-}" ]; then ng setup "偽の HOME が本物の HOME と同じ"; finish; fi
cp -R "$LAB/hooks" "$T/lab-hooks/hooks" || { ng setup "hooks/ を写せない"; finish; }
H="$T/lab-hooks/hooks"   # 写した hooks の記録（hooks.log など）は $T/lab-hooks/tmp/.verify に書かれる

# in_env <LANG> <コマンド...> → 偽の HOME と短い PATH と、指定の LANG だけの環境で回す
in_env() { local l="$1"; shift; env -i HOME="$FH" PATH="$RUN_PATH" LANG="$l" "$@"; }

# new_project <場所> [mark|nomark] → git init と、tools/ の写しを tmp/tools に置く。mark なら tmp/DEPLOYED.md も書く
new_project() {
  mkdir -p "$1/tmp" || return 1
  in_env C git -C "$1" init -q || return 1
  cp -R "$LAB/tools" "$1/tmp/tools" || return 1
  if [ "${2:-mark}" = mark ]; then printf '# この tmp/ の写しについて\n\n正本: %s\n' "$LAB" > "$1/tmp/DEPLOYED.md"; fi
}

# new_lab <場所> → My-Lab の形（root 直下に tools/）。写した先の印は無い
new_lab() { mkdir -p "$1" && cp -R "$LAB/tools" "$1/tools"; }

# unit_test <プロジェクト> <値> → tests/test_app.py。値が 1 なら通り、それ以外なら落ちる
#   project-verify.sh は、これを自動では回さない。回すときは commands_file で tmp/verify-commands.txt に書く
unit_test() {
  mkdir -p "$1/tests"
  printf 'import unittest\n\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(1, %s)\n' "$2" > "$1/tests/test_app.py"
}

# commands_file <プロジェクト> <命令...> → 社長が書く検証の命令のファイル tmp/verify-commands.txt に、1 行 1 命令で書く
commands_file() { local p="$1"; shift; printf '%s\n' "$@" > "$p/tmp/verify-commands.txt"; }
UNITTEST_CMD='python3 -m unittest discover -s tests'

# good_doc <ファイル> → 文体と資料の型の検査を通る文書（tools/placement-test.sh の見本と同じ中身）
good_doc() {
  printf '# 調査の覚え書き\n\n> **3 行でわかる要約**\n> 1. これは配置の試験で使う見本の文書です。\n> 2. 文体と資料の型の検査を通ることを確かめます。\n> 3. 次に、検査の結果を見ます。\n\n## 1. 目的\n\n写した道具が文書を検査できることを確かめます。短い文書なので、図と表は要りません。\n' > "$1"
}

# persona_doc <ファイル> <目的の段落の 1 文目> → good_doc と同じ形で、目的の段落の頭に 1 文を置いた文書
persona_doc() {
  printf '# 調査の覚え書き\n\n> **3 行でわかる要約**\n> 1. これは配置の試験で使う見本の文書です。\n> 2. 文体と資料の型の検査を通ることを確かめます。\n> 3. 次に、検査の結果を見ます。\n\n## 1. 目的\n\n%s短い文書なので、図と表は要りません。\n' "$2" > "$1"
}

# check <LANG> <root> <ファイル> → root で、その root の写しの check-file.sh を回す（hooks と同じ呼び方）
check() { (cd "$2" && in_env "$1" /bin/bash "$2/tmp/tools/check-file.sh" "$3" 2>&1); }

# verify <LANG> <root> [道具の場所] → root で project-verify.sh --fast を回す（文書の引数なし）
verify() { (cd "$2" && in_env "$1" /bin/bash "${3:-tmp/tools}/project-verify.sh" --fast 2>&1); }

# verify_docs <LANG> <root> <文書...> → root で project-verify.sh --fast に、文書を引数で渡して回す
verify_docs() { local l="$1" r="$2"; shift 2; (cd "$r" && in_env "$l" /bin/bash tmp/tools/project-verify.sh --fast -- "$@" 2>&1); }

# terms_only <出力> → 現場の語の検査（check-terms）だけが回って通った（文体・資料・shellcheck・jq などは回っていない）
terms_only() {
  printf '%s\n' "$1" | grep -q '^RESULT: PASS check-terms ' && ! printf '%s\n' "$1" | grep '^RESULT:' | grep -qv '^RESULT: PASS check-terms '
}

# postedit <LANG> <root> <ファイル> → 写した Claude Code の PostToolUse 接続口に、Edit の入力を 1 回送る
postedit() {
  printf '{"tool_name":"Edit","tool_input":{"file_path":"%s"},"cwd":"%s"}' "$3" "$2" | in_env "$1" /bin/bash "$H/claude-postedit.sh" --global 2>&1
}

# postedit_s <LANG> <root> <ファイル> → postedit と同じ入力に、stop_hook と同じ session_id を付けて送る（そのセッションが書いた記録を残す）
postedit_s() {
  printf '{"session_id":"deployed-checks","tool_name":"Edit","tool_input":{"file_path":"%s"},"cwd":"%s"}' "$3" "$2" | in_env "$1" /bin/bash "$H/claude-postedit.sh" --global 2>&1
}

# stop_hook <LANG> <root> → 写した Claude Code の Stop 接続口に、Stop の入力を 1 回送る
stop_hook() {
  printf '{"session_id":"deployed-checks","stop_hook_active":false,"cwd":"%s"}' "$2" | in_env "$1" /bin/bash "$H/claude-stop.sh" --global 2>&1
}

# first_fail <出力> → 理由に添える、最初の FAIL の行（中身の無い行は飛ばす）
first_fail() { printf '%s\n' "$1" | grep -E '^(FAIL|RESULT: FAIL)' | grep -vE '\] *$' | head -1; }

# exists <パス> → 「ある」か「無い」
exists() { if [ -e "$1" ]; then printf 'ある'; else printf '無い'; fi; }

# newer <印> <ファイル> → ファイルを印より 2 秒新しい時刻にする（同じ秒に書いた文書は「新しい」と見えない）
newer() { python3 -I -c 'import os, sys; t = os.stat(sys.argv[1]).st_mtime + 2; os.utime(sys.argv[2], (t, t))' "$1" "$2"; }

# 1. check-file.sh: 移した先では、tmp/ の外のファイルに現場の語の検査だけを回す（deploy-5。2026-11-26 に現場の語を足した）
cases_check_file() {
  local L="$1" B="$2" s="@$1" P f label out rc out2 rc2
  P="$B/check file プロジェクト"
  new_project "$P" mark || ng "setup$s" "偽のプロジェクトを作れない（${P}）"
  mkdir -p "$P/docs" "$P/scripts" "$P/tmp/flow/bad"
  printf '# Orders\n\n%s\n' "$EN_TEXT" > "$P/README.md"
  printf '{\n  /* Visit https://aka.ms/tsconfig */\n  // strict を有効にする\n  "compilerOptions": {"strict": true}\n}\n' > "$P/tsconfig.json"
  cat > "$P/scripts/list.sh" <<'EOF'
#!/bin/sh
for f in $(ls); do echo $f; done
EOF
  printf '# セットアップ\n\nこの文書は、開発の準備の手順を書きます。\n' > "$P/docs/setup.md"
  printf '# Note\n\n%s\n' "$EN_TEXT" > "$P/tmp/flow/bad/note.md"

  # プロジェクト自身のファイルは、hooks と同じ絶対パスで渡しても、現場の語の検査だけを回して PASS（英文・コメント入りの JSON・shellcheck の指摘は見ない）
  for f in README.md tsconfig.json scripts/list.sh docs/setup.md; do
    case "$f" in README.md) label=readme ;; tsconfig.json) label=tsconfig ;; scripts/*) label=script ;; *) label=docs ;; esac
    out="$(check "$L" "$P" "$P/$f")"; rc=$?
    if [ "$rc" -eq 0 ] && terms_only "$out"; then ok "project-$label$s"
    else ng "project-$label$s" "rc=${rc}。プロジェクト自身の ${f} に、現場の語のほかの検査を回した: $(first_fail "$out")"; fi
  done
  out="$(check "$L" "$P" README.md)"; rc=$?
  if [ "$rc" -eq 0 ] && terms_only "$out"; then ok "project-relative$s"
  else ng "project-relative$s" "rc=${rc}。相対パスの README.md に、現場の語のほかの検査を回した: $(first_fail "$out")"; fi

  # tmp/ の中の文書は、これまでどおり検査する
  out="$(check "$L" "$P" "$P/tmp/flow/bad/note.md")"; rc=$?
  if [ "$rc" -ne 0 ] && printf '%s\n' "$out" | grep -q '^RESULT: FAIL check-ja'; then ok "tmp-flow-checked$s"
  else ng "tmp-flow-checked$s" "rc=${rc}。tmp/flow の英文が check-ja で落ちない"; fi

  # リンクを通したパスでも、実体の置き場で決める（ディレクトリのリンクと、ファイルのリンク）
  ln -s "$P" "$B/alias"
  out="$(check "$L" "$P" "$B/alias/README.md")"; rc=$?
  out2="$(check "$L" "$P" "$B/alias/tmp/flow/bad/note.md")"; rc2=$?
  if [ "$rc" -eq 0 ] && [ "$rc2" -ne 0 ]; then ok "alias-dir$s"
  else ng "alias-dir$s" "リンク越しの README.md は rc=${rc}（0 のはず）、tmp/flow の文書は rc=${rc2}（1 のはず）"; fi
  ln -s ../../README.md "$P/tmp/flow/readme-link.md"
  ln -s ../tmp/flow/bad/note.md "$P/docs/kit-link.md"
  out="$(check "$L" "$P" "$P/tmp/flow/readme-link.md")"; rc=$?
  out2="$(check "$L" "$P" "$P/docs/kit-link.md")"; rc2=$?
  if [ "$rc" -eq 0 ] && [ "$rc2" -ne 0 ]; then ok "alias-file$s"
  else ng "alias-file$s" "実体が README.md のリンクは rc=${rc}（0 のはず）、実体が tmp/flow の文書のリンクは rc=${rc2}（1 のはず）"; fi

  # hooks を通しても同じ。プロジェクトのファイルでは止めず、tmp/flow の文書では止める（終了コード 2）
  out="$(postedit "$L" "$P" "$P/README.md")"; rc=$?
  if [ "$rc" -eq 0 ]; then ok "postedit-project$s"
  else ng "postedit-project$s" "README.md の編集で、hook が終了コード ${rc} を返した: $(first_fail "$out")"; fi
  out="$(postedit "$L" "$P" "$P/tmp/flow/bad/note.md")"; rc=$?
  if [ "$rc" -eq 2 ]; then ok "postedit-tmp-flow$s"
  else ng "postedit-tmp-flow$s" "tmp/flow の英文の編集で、hook が終了コード ${rc} を返した（2 のはず）"; fi

  # 印（tmp/DEPLOYED.md）が無い置き場と、My-Lab の形では、これまでどおり全部を検査する
  P="$B/no mark"
  new_project "$P" nomark || ng "setup$s" "偽のプロジェクトを作れない（${P}）"
  printf '# Orders\n\n%s\n' "$EN_TEXT" > "$P/README.md"
  out="$(check "$L" "$P" "$P/README.md")"; rc=$?
  if [ "$rc" -ne 0 ]; then ok "nomark-checked$s"; else ng "nomark-checked$s" "印が無いのに README.md を検査しない"; fi
  P="$B/lab"
  printf '# Orders\n\n%s\n' "$EN_TEXT" > "$P/README.md"
  out="$( (cd "$P" && in_env "$L" /bin/bash "$P/tools/check-file.sh" "$P/README.md" 2>&1) )"; rc=$?
  if [ "$rc" -ne 0 ]; then ok "lab-checked$s"; else ng "lab-checked$s" "My-Lab の形で README.md を検査しない"; fi
}

# 2. project-verify.sh: 写した先の PASS でだけ、hooks の印 tmp/.verify/last-pass を更新する（deploy-4 の前半）
cases_last_pass() {
  local L="$1" B="$2" s="@$1" P V out rc out2 out3 out4 ran1 ran2 ran3 ran4
  P="$B/verify pass"
  new_project "$P" mark || ng "setup$s" "偽のプロジェクトを作れない（${P}）"
  unit_test "$P" 1
  commands_file "$P" "$UNITTEST_CMD"
  out="$(verify "$L" "$P")"; rc=$?
  # 文書の引数が無くても、bash 3.2 の set -u で落ちない。文書は 1 本も検査しない
  if printf '%s\n' "$out" | grep -q 'unbound variable'; then ng "no-docs$s" "文書が無いと set -u で落ちる"
  elif [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -qxF '文書の指定なし（検査した文書 0 本）'; then ok "no-docs$s"
  else ng "no-docs$s" "rc=${rc}: $(first_fail "$out")"; fi
  if [ "$rc" -eq 0 ] && [ -f "$P/tmp/.verify/last-pass" ]; then
    # ファイルの一覧（tmp/.verify/last-pass.list）は Stop の hook が書く。印だけで一覧が無いうちは、hooks は「変わった」と見る（分からないときは回す）
    # shellcheck disable=SC2016  # $1 と $2 は子の bash が展開する
    if in_env "$L" /bin/bash -c '. "$1/lib.sh"; changed_since_pass "$2"' lib "$H" "$P"; then ok "no-list-runs$s"
    else ng "no-list-runs$s" "一覧（last-pass.list）が無いのに、hooks は変更なしと見る"; fi
    # 一覧を書いたあとは、hooks の判定（hooks/lib.sh の changed_since_pass）でも「直したファイルは無い」になる
    # shellcheck disable=SC2016  # $1 と $2 は子の bash が展開する
    if in_env "$L" /bin/bash -c '. "$1/lib.sh"; snapshot_tree "$2"; changed_since_pass "$2"' lib "$H" "$P"; then
      ng "last-pass$s" "印のあとに直したファイルは無いのに、hooks は変更ありと見る"
    else ok "last-pass$s"; fi
  else ng "last-pass$s" "rc=${rc}。PASS のあとの tmp/.verify/last-pass が$(exists "$P/tmp/.verify/last-pass")"; fi

  # 写した Stop の hook: 何も書いていないセッションでは回らない。書いたセッションでは、1 回目は回り、
  #   変更の無い 2 回目は回らず、直したあとの 3 回目は回る
  P="$B/verify stop"
  V="$P/tmp/.verify"
  new_project "$P" mark || ng "setup$s" "偽のプロジェクトを作れない（${P}）"
  unit_test "$P" 1
  commands_file "$P" "$UNITTEST_CMD"
  mkdir -p "$P/src"
  printf 'x = 1\n' > "$P/src/app.py"
  out="$(stop_hook "$L" "$P")"
  if [ ! -f "$V/last-fast.txt" ] && [ -z "$out" ]; then ok "stop-skips-no-writes$s"
  else ng "stop-skips-no-writes$s" "何も書いていないセッションの Stop で、命令を回した: $(printf '%s' "$out" | head -c 120)"; fi
  postedit_s "$L" "$P" "$P/src/app.py" >/dev/null
  out="$(stop_hook "$L" "$P")"
  ran1=no; [ -f "$V/last-fast.txt" ] && ran1=yes
  rm -f "$V/last-fast.txt"
  out2="$(stop_hook "$L" "$P")"
  ran2=no; [ -f "$V/last-fast.txt" ] && ran2=yes
  if [ "$ran1" = yes ] && [ "$ran2" = no ] && [ -z "$out$out2" ]; then ok "stop-skips-unchanged$s"
  else ng "stop-skips-unchanged$s" "1 回目に回った=${ran1}、変更の無い 2 回目に回った=${ran2}（yes と no のはず）$(printf '%s' "$out$out2" | head -c 120)"; fi
  # 印より 2 秒新しい時刻で、プロジェクトのファイルを直したことにする（印が無ければ今の時刻）
  if [ -f "$V/last-pass" ]; then
    python3 -I -c 'import os, sys; t = os.stat(sys.argv[1]).st_mtime + 2; os.utime(sys.argv[2], (t, t))' "$V/last-pass" "$P/src/app.py"
  else
    touch "$P/src/app.py"
  fi
  rm -f "$V/last-fast.txt"
  out3="$(stop_hook "$L" "$P")"
  ran3=no; [ -f "$V/last-fast.txt" ] && ran3=yes
  if [ "$ran3" = yes ] && [ -z "$out3" ]; then ok "stop-runs-after-edit$s"
  else ng "stop-runs-after-edit$s" "直したあとの Stop で回った=${ran3}（yes のはず）$(printf '%s' "$out3" | head -c 120)"; fi
  # ファイルを消すだけ（印より新しいファイルは無い）でも、次の Stop は一覧の違いで回る
  rm -f "$V/last-fast.txt" "$P/src/app.py"
  out4="$(stop_hook "$L" "$P")"
  ran4=no; [ -f "$V/last-fast.txt" ] && ran4=yes
  if [ "$ran4" = yes ] && [ -z "$out4" ]; then ok "stop-runs-after-delete$s"
  else ng "stop-runs-after-delete$s" "消したあとの Stop で回った=${ran4}（yes のはず）$(printf '%s' "$out4" | head -c 120)"; fi

  # FAIL（命令のファイルに書いた試験が落ちる）と、My-Lab の中で回したときは、印を書かない
  P="$B/verify fail"
  new_project "$P" mark || ng "setup$s" "偽のプロジェクトを作れない（${P}）"
  unit_test "$P" 2
  commands_file "$P" "$UNITTEST_CMD"
  out="$(verify "$L" "$P")"; rc=$?
  if [ "$rc" -eq 1 ] && [ ! -e "$P/tmp/.verify/last-pass" ]; then ok "no-mark-on-fail$s"
  else ng "no-mark-on-fail$s" "rc=${rc}（1 のはず）。印が$(exists "$P/tmp/.verify/last-pass")"; fi
  # 命令のファイルも文書の引数も無い置き場では、落ちる試験があっても自動では回さない。何も検査しないので WARN（終了コード 3）で、印を書かない
  P="$B/verify nocmd"
  new_project "$P" mark || ng "setup$s" "偽のプロジェクトを作れない（${P}）"
  unit_test "$P" 2
  mkdir -p "$P/src"
  printf 'x = 1\n' > "$P/src/app.py"
  out="$(verify "$L" "$P")"; rc=$?
  if [ "$rc" -eq 3 ] && [ ! -e "$P/tmp/.verify/last-pass" ] && ! printf '%s\n' "$out" | grep -q 'unittest' \
     && printf '%s\n' "$out" | grep -q '^RESULT: WARN project-verify --fast'; then ok "no-commands-warn$s"
  else ng "no-commands-warn$s" "rc=${rc}（3 のはず）。印が$(exists "$P/tmp/.verify/last-pass")。$(first_fail "$out")"; fi
  P="$B/lab"
  unit_test "$P" 1
  out="$(verify "$L" "$P" tools)"; rc=$?
  if [ "$rc" -eq 3 ] && [ ! -e "$P/tmp/.verify/last-pass" ] && [ -f "$P/tmp/.verify/project-verify-last-fast.txt" ]; then ok "no-mark-in-lab$s"
  else ng "no-mark-in-lab$s" "rc=${rc}（3 のはず）。My-Lab の形で印が$(exists "$P/tmp/.verify/last-pass")"; fi
}

# 3. project-verify.sh: 引数で渡した、空白と日本語を含む文書のパスを、1 本のまま渡す（deploy-8）
cases_doc_paths() {
  local L="$1" B="$2" s="@$1" P D N I out rc bt='`'
  P="$B/verify docs"
  D="$P/tmp/flow/2026-11-09 ログイン改修"
  N="tmp/flow/2026-11-09 ログイン改修/note.md"
  I="tmp/ISSUE_2026-11-09_login fix.md"
  new_project "$P" mark || ng "setup$s" "偽のプロジェクトを作れない（${P}）"
  unit_test "$P" 1
  mkdir -p "$D"
  good_doc "$D/note.md"
  good_doc "$P/$I"
  out="$(verify_docs "$L" "$P" "$N" "$I")"; rc=$?
  if [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -qF 'RESULT: PASS check-file（渡した文書 2 本）' \
     && printf '%s\n' "$out" | grep -qF 'RESULT: PASS check-refs（渡した文書 2 本）'; then ok "doc-path-space$s"
  else ng "doc-path-space$s" "rc=${rc}（0 のはず）: $(first_fail "$out")"; fi
  # 無いファイルを指す行を足すと、その文書の check-refs が FAIL を出す（切れた名前を読み飛ばさない）。渡すのは note.md の 1 本
  printf '\n手順は %sscripts/deploy-prod.sh%s に書きます。\n' "$bt" "$bt" >> "$D/note.md"
  out="$(verify_docs "$L" "$P" "$N")"; rc=$?
  if [ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -F 'FAIL check-refs（渡した文書 1 本）:' | grep -F 'ログイン改修/note.md' | grep -qF 'scripts/deploy-prod.sh'; then
    ok "doc-path-space-refs$s"
  else ng "doc-path-space-refs$s" "rc=${rc}（1 のはず）。check-refs が壊れた参照を示さない: $(printf '%s\n' "$out" | grep -F 'check-refs' | head -1)"; fi
}

# 4. project-verify.sh: 文書は引数で渡したものだけを検査する（改善提案書 13 章。2026-11-11 の範囲外の行と WARN は無くした）
#    印（tmp/.verify/last-pass）の新しさでは決めない。細かい場面は tools/tests/project-verify-scope-test.sh
cases_scope() {
  local L="$1" B="$2" s="@$1" P V out rc
  P="$B/verify scope"
  V="$P/tmp/.verify"
  new_project "$P" mark || ng "setup$s" "偽のプロジェクトを作れない（${P}）"
  mkdir -p "$P/tmp/flow/old" "$P/tmp/flow/new"
  printf '# Old\n\n%s\n' "$EN_TEXT" > "$P/tmp/flow/old/note.md"
  # 印が無く、落ちる文書があっても、引数が無ければ文書を 1 本も検査しない。名前も出さない。何も検査しないので WARN（終了コード 3）
  out="$(verify "$L" "$P")"; rc=$?
  if [ "$rc" -eq 3 ] && printf '%s\n' "$out" | grep -qxF '文書の指定なし（検査した文書 0 本）' && ! printf '%s\n' "$out" | grep -q 'old/note.md' \
     && ! printf '%s\n' "$out" | grep -q '^RESULT: [A-Z]* check-'; then ok "no-args-no-docs$s"
  else ng "no-args-no-docs$s" "rc=${rc}（3 のはず）: $(first_fail "$out")"; fi
  # 移した時点の印を置く（deploy.sh が呼ぶ --baseline）。検査は回さない
  out="$( (cd "$P" && in_env "$L" /bin/bash tmp/tools/project-verify.sh --baseline 2>&1) )"; rc=$?
  if [ "$rc" -eq 0 ] && [ -f "$V/last-pass" ] && [ -f "$V/last-pass.list" ] && grep -qxF './tmp/flow/old/note.md' "$V/last-pass.list" \
     && printf '%s\n' "$out" | grep -qF '引数で渡したものだけ'; then ok "baseline-writes-mark$s"
  else ng "baseline-writes-mark$s" "rc=${rc}（0 のはず）。印が$(exists "$V/last-pass")、一覧が$(exists "$V/last-pass.list")"; fi
  # 印より新しい文書でも、引数に無ければ検査しない（前は範囲の中に数えた）
  printf '# New\n\n%s\n' "$EN_TEXT" > "$P/tmp/flow/new/note.md"
  newer "$V/last-pass" "$P/tmp/flow/new/note.md"
  out="$(verify "$L" "$P")"; rc=$?
  if [ "$rc" -eq 3 ] && ! printf '%s\n' "$out" | grep -q 'note.md' && ! grep -q 'note.md' "$V/last-fast.txt" 2>/dev/null; then ok "newer-doc-not-checked$s"
  else ng "newer-doc-not-checked$s" "rc=${rc}（3 のはず）。渡していない文書を検査した: $(first_fail "$out")"; fi
  # 渡せば検査する。落ちれば FAIL で、渡していない文書の名前は出ない
  out="$(verify_docs "$L" "$P" tmp/flow/new/note.md)"; rc=$?
  if [ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -q '^RESULT: FAIL check-file（渡した文書 1 本）' && printf '%s\n' "$out" | grep '^FAIL check-file' | grep -q 'new/note.md' \
     && ! printf '%s\n' "$out" | grep -q 'old/note.md'; then ok "passed-doc-checked$s"
  else ng "passed-doc-checked$s" "rc=${rc}（1 のはず）: $(first_fail "$out")"; fi
  # 直して渡せば PASS。印より古い文書でも、渡せば検査する
  good_doc "$P/tmp/flow/new/note.md"
  newer "$P/tmp/flow/new/note.md" "$V/last-pass"   # 時間が進んだことにする（印が文書より新しい）
  out="$(verify_docs "$L" "$P" tmp/flow/new/note.md)"; rc=$?
  if [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -q '^RESULT: PASS check-file（渡した文書 1 本）'; then ok "fixed-doc-passes$s"
  else ng "fixed-doc-passes$s" "rc=${rc}（0 のはず）: $(first_fail "$out")"; fi
  # --baseline は My-Lab の形では止まる（終了コード 2）。印は書かない
  out="$( (cd "$B/lab" && in_env "$L" /bin/bash tools/project-verify.sh --baseline 2>&1) )"; rc=$?
  if [ "$rc" -eq 2 ] && [ ! -e "$B/lab/tmp/.verify/last-pass" ]; then ok "baseline-refused-in-lab$s"
  else ng "baseline-refused-in-lab$s" "rc=${rc}（2 のはず）。My-Lab の形で印が$(exists "$B/lab/tmp/.verify/last-pass")"; fi
}

i=0
# 5. check-file.sh: 写した先で AI が書く資料と雛形から、「秘書」「社長」の語を落とす（2026-11-13 の依頼）
cases_persona() {
  local L="$1" B="$2" s="@$1" P out rc
  P="$B/persona プロジェクト"
  new_project "$P" mark || ng "setup$s" "偽のプロジェクトを作れない（${P}）"
  mkdir -p "$P/tmp/flow/p"
  persona_doc "$P/tmp/flow/p/bad.md" "写した道具が文書を検査できることを、社長に確かめます。"
  out="$(check "$L" "$P" "$P/tmp/flow/p/bad.md")"; rc=$?
  if [ "$rc" -ne 0 ] && printf '%s\n' "$out" | grep -q '\[秘書・社長の語\]'; then ok "persona-flow-fail$s"
  else ng "persona-flow-fail$s" "rc=${rc}。tmp/flow の文書の「社長」が落ちない: $(first_fail "$out")"; fi
  persona_doc "$P/tmp/flow/p/quote.md" "依頼の原文は「社長に見せる資料を作って」です。"
  out="$(check "$L" "$P" "$P/tmp/flow/p/quote.md")"; rc=$?
  if [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -q '^RESULT: PASS check-persona'; then ok "persona-quote-pass$s"
  else ng "persona-quote-pass$s" "rc=${rc}。「」の引用の中の語で落ちた: $(first_fail "$out")"; fi
  persona_doc "$P/tmp/ISSUE_2026-11-13_x.md" "写した道具が文書を検査できることを、秘書が確かめます。"
  out="$(check "$L" "$P" "$P/tmp/ISSUE_2026-11-13_x.md")"; rc=$?
  if [ "$rc" -ne 0 ] && printf '%s\n' "$out" | grep -q '\[秘書・社長の語\]'; then ok "persona-issue-fail$s"
  else ng "persona-issue-fail$s" "rc=${rc}。Issue 文の「秘書」が落ちない: $(first_fail "$out")"; fi
  out="$(verify_docs "$L" "$P" tmp/flow/p/bad.md tmp/flow/p/quote.md tmp/ISSUE_2026-11-13_x.md)"; rc=$?
  if [ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -q '\[秘書・社長の語\]'; then ok "persona-verify-fail$s"
  else ng "persona-verify-fail$s" "rc=${rc}（1 のはず）。project-verify が語を示さない: $(first_fail "$out")"; fi
  # My-Lab の形: tmp/flow は一式そのものを書く場所なので見ない。雛形と完成例は見る
  P="$B/lab"
  mkdir -p "$P/tmp/flow/p" "$P/skills/demo/templates"
  persona_doc "$P/tmp/flow/p/lab.md" "写した道具が文書を検査できることを、社長に確かめます。"
  out="$( (cd "$P" && in_env "$L" /bin/bash "$P/tools/check-file.sh" "$P/tmp/flow/p/lab.md" 2>&1) )"; rc=$?
  if ! printf '%s\n' "$out" | grep -q 'check-persona'; then ok "persona-lab-flow-skip$s"
  else ng "persona-lab-flow-skip$s" "My-Lab の tmp/flow で check-persona が回った"; fi
  persona_doc "$P/skills/demo/templates/t.md" "写した道具が文書を検査できることを、社長に確かめます。"
  out="$( (cd "$P" && in_env "$L" /bin/bash "$P/tools/check-file.sh" "$P/skills/demo/templates/t.md" 2>&1) )"; rc=$?
  if [ "$rc" -ne 0 ] && printf '%s\n' "$out" | grep -q '\[秘書・社長の語\]'; then ok "persona-lab-template-fail$s"
  else ng "persona-lab-template-fail$s" "rc=${rc}。My-Lab の雛形の「社長」が落ちない: $(first_fail "$out")"; fi
}

# git_fixture <リポジトリ> <git の引数...> → 使い捨てのリポジトリ（mktemp の下）で git を回す。偽の HOME で、system の設定を読まず、
#   一時ディレクトリより上のリポジトリを探さない。名前と署名は -c で渡す。出力は捨てる
git_fixture() {
  local r="$1"; shift
  env -i HOME="$FH" PATH="$RUN_PATH" LANG=C GIT_CONFIG_NOSYSTEM=1 GIT_CEILING_DIRECTORIES="$T" \
    git -C "$r" -c user.name=deployed-checks -c user.email=deployed-checks@example.invalid -c commit.gpgsign=false "$@" >/dev/null 2>&1
}

# 6. check-file.sh: 現場の語（tools/ja-terms.txt）を、.md 以外の文字のファイルでも落とす（2026-11-26 の依頼）
#    移した先のプロジェクト自身のファイルは、git の HEAD から足した行だけを見る。追跡していないファイルは全体を見る
cases_terms() {
  local L="$1" B="$2" s="@$1" P W lab out rc out2 rc2
  W="$(printf '\346\236\235')"   # 現場の語の例。この試験の文に、語をそのまま書かない
  P="$B/terms プロジェクト"
  new_project "$P" mark || ng "setup$s" "偽のプロジェクトを作れない（${P}）"
  mkdir -p "$P/src" "$P/docs"
  printf '#!/bin/sh\n# 作業用の%sを切る（前からある行）\necho ok\n' "$W" > "$P/src/old.sh"
  printf '# 説明\n\n前からある%sの行です。\n' "$W" > "$P/docs/old.md"
  if ! { git_fixture "$P" add src/old.sh docs/old.md && git_fixture "$P" commit -q -m init; }; then
    ng "setup$s" "使い捨てのリポジトリに HEAD を作れない（${P}）"; return
  fi
  # 追跡していて、HEAD から変えていないファイル: 前からある行の語は数えない
  out="$(check "$L" "$P" "$P/src/old.sh")"; rc=$?
  if [ "$rc" -eq 0 ] && terms_only "$out" && printf '%s\n' "$out" | grep -qF '足した 0 行を見た'; then ok "terms-project-unchanged$s"
  else ng "terms-project-unchanged$s" "rc=${rc}（0 のはず）。前からある行を数えた: $(first_fail "$out")"; fi
  # 足した行の語は落とす。出る行番号は足した行（4 行目）だけ
  printf '# 新しい%sの行\n' "$W" >> "$P/src/old.sh"
  out="$(check "$L" "$P" "$P/src/old.sh")"; rc=$?
  if [ "$rc" -ne 0 ] && printf '%s\n' "$out" | grep -qF "$P/src/old.sh:4 [現場の語]" && ! printf '%s\n' "$out" | grep -qF "$P/src/old.sh:2 " \
     && ! printf '%s\n' "$out" | grep -q 'shellcheck'; then ok "terms-project-added-line$s"
  else ng "terms-project-added-line$s" "rc=${rc}（1 のはず）。足した行だけを落とさない: $(first_fail "$out")"; fi
  # .md も同じ見方（足した行だけ。「」の中は数えない。文体の検査は回さない）
  printf '\n「%s」とは書かない。\n' "$W" >> "$P/docs/old.md"
  out="$(check "$L" "$P" "$P/docs/old.md")"; rc=$?
  if [ "$rc" -eq 0 ] && terms_only "$out" && printf '%s\n' "$out" | grep -qF '足した 2 行を見た'; then ok "terms-project-md$s"
  else ng "terms-project-md$s" "rc=${rc}（0 のはず）: $(first_fail "$out")"; fi
  # 追跡していないファイルは全体を見る
  printf 'x\n作業用の%s\n' "$W" > "$P/src/new.txt"
  out="$(check "$L" "$P" "$P/src/new.txt")"; rc=$?
  if [ "$rc" -ne 0 ] && printf '%s\n' "$out" | grep -qF "$P/src/new.txt:2 [現場の語]"; then ok "terms-project-untracked$s"
  else ng "terms-project-untracked$s" "rc=${rc}（1 のはず）。追跡していないファイルを全体で見ない: $(first_fail "$out")"; fi
  # hooks を通しても同じ。足した行に語があれば止める（終了コード 2）
  out="$(postedit "$L" "$P" "$P/src/old.sh")"; rc=$?
  if [ "$rc" -eq 2 ]; then ok "terms-postedit-project$s"
  else ng "terms-postedit-project$s" "足した行に語があるのに、hook が終了コード ${rc} を返した（2 のはず）"; fi
  # 移した一式の中（tmp/）の .txt は、全体を見る
  printf '作業用の%s\n' "$W" > "$P/tmp/notes.txt"
  out="$(check "$L" "$P" "$P/tmp/notes.txt")"; rc=$?
  if [ "$rc" -ne 0 ] && printf '%s\n' "$out" | grep -qF "$P/tmp/notes.txt:1 [現場の語]"; then ok "terms-tmp-txt$s"
  else ng "terms-tmp-txt$s" "rc=${rc}（1 のはず）。tmp/ の .txt を見ない: $(first_fail "$out")"; fi
  # 拡張子の一覧に無い文字のファイル（.ts .tsx .go .rb .sql .vue）も、語を落とす。NUL の字を含むファイルは対象外
  for x in ts tsx go rb sql vue; do
    printf '// x\n// 作業用の%sを切る\n' "$W" > "$P/src/lang.$x"
    out="$(check "$L" "$P" "$P/src/lang.$x")"; rc=$?
    if [ "$rc" -ne 0 ] && printf '%s\n' "$out" | grep -qF "$P/src/lang.$x:2 [現場の語]"; then ok "terms-ext-$x$s"
    else ng "terms-ext-$x$s" "rc=${rc}（1 のはず）。.${x} の語を落とさない: $(first_fail "$out")"; fi
  done
  printf 'x\000%s\n' "$W" > "$P/src/blob.bin"
  out="$(check "$L" "$P" "$P/src/blob.bin")"; rc=$?
  if [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -q '検査の対象外'; then ok "terms-binary-skip$s"
  else ng "terms-binary-skip$s" "rc=${rc}（0 のはず）。NUL の字を含むファイルを検査した: $(first_fail "$out")"; fi
  # My-Lab の形: .sh のコメントの語は落とし、「」の中は通す。.md は禁則語として落とす
  lab="$B/lab"
  mkdir -p "$lab/scratch"
  printf '#!/bin/sh\n# 作業用の%sを切る\n' "$W" > "$lab/scratch/bad.sh"
  printf '#!/bin/sh\n# 「%s」とは書かない\n' "$W" > "$lab/scratch/quote.sh"
  printf '# メモ\n\n作業用の%sを切ります。\n' "$W" > "$lab/scratch/note.md"
  out="$( (cd "$lab" && in_env "$L" /bin/bash "$lab/tools/check-file.sh" "$lab/scratch/bad.sh" 2>&1) )"; rc=$?
  out2="$( (cd "$lab" && in_env "$L" /bin/bash "$lab/tools/check-file.sh" "$lab/scratch/quote.sh" 2>&1) )"; rc2=$?
  if [ "$rc" -ne 0 ] && printf '%s\n' "$out" | grep -q '\[現場の語\]' && [ "$rc2" -eq 0 ]; then ok "terms-lab-sh$s"
  else ng "terms-lab-sh$s" "コメントの語で rc=${rc}（1 のはず）、「」の中で rc=${rc2}（0 のはず）"; fi
  out="$( (cd "$lab" && in_env "$L" /bin/bash "$lab/tools/check-file.sh" "$lab/scratch/note.md" 2>&1) )"; rc=$?
  if [ "$rc" -ne 0 ] && printf '%s\n' "$out" | grep -q '\[禁則語\]'; then ok "terms-lab-md$s"
  else ng "terms-lab-md$s" "rc=${rc}（1 のはず）。.md の語が禁則語で落ちない: $(first_fail "$out")"; fi
}

for L in C ja_JP.UTF-8; do
  i=$((i + 1))
  B="$T/$i"
  mkdir -p "$B"
  new_lab "$B/lab" || ng "setup@$L" "My-Lab の形を作れない"
  cases_check_file "$L" "$B"
  cases_last_pass "$L" "$B"
  cases_doc_paths "$L" "$B"
  cases_scope "$L" "$B"
  cases_persona "$L" "$B"
  cases_terms "$L" "$B"
done
finish
