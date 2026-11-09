#!/usr/bin/env bash
# tools/tests/deployed-checks-test.sh — 写した先（<プロジェクト>/tmp/tools）で、検査の道具が決まりどおりに動くかの試験。
#   1. check-file.sh は、tmp/ の外のファイル（プロジェクト自身のもの）を検査せずに PASS にする。tmp/ の中の文書は検査する。
#   2. project-verify.sh は、写した先の PASS でだけ tmp/.verify/last-pass を更新する。Stop の hook は、変更の無い 2 回目を回さない。
#   3. project-verify.sh は、空白と日本語を含む文書のパスを 1 本のまま check-file と check-refs に渡す。
# 偽のプロジェクトは手で作る（git init、tools/ を tmp/tools に写す、tmp/DEPLOYED.md を書く）。deploy.sh は使わない。
# hooks/ は使い捨ての場所に写して回す。本物の HOME と、My-Lab の tmp/.verify には書かない。
# 場面は全部、LANG=C と LANG=ja_JP.UTF-8 の 2 通りで回す。
# 出力: 場面ごとに PASS <場面> か FAIL <場面> <理由>。最後に RESULT 行。1 件でも FAIL なら終了コード 1。
set -u
LAB="$(cd "$(dirname "$0")/../.." && pwd -P)" || exit 1
NAME="deployed-checks-test"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
RUN_PATH="/opt/homebrew/bin:/usr/bin:/bin"
SKIP_MARK="写した先のプロジェクト自身のファイルは検査の対象外"
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

# check <LANG> <root> <ファイル> → root で、その root の写しの check-file.sh を回す（hooks と同じ呼び方）
check() { (cd "$2" && in_env "$1" /bin/bash "$2/tmp/tools/check-file.sh" "$3" 2>&1); }

# verify <LANG> <root> [道具の場所] → root で project-verify.sh --fast を回す
verify() { (cd "$2" && in_env "$1" /bin/bash "${3:-tmp/tools}/project-verify.sh" --fast 2>&1); }

# postedit <LANG> <root> <ファイル> → 写した Claude Code の PostToolUse 接続口に、Edit の入力を 1 回送る
postedit() {
  printf '{"tool_name":"Edit","tool_input":{"file_path":"%s"},"cwd":"%s"}' "$3" "$2" | in_env "$1" /bin/bash "$H/claude-postedit.sh" --global 2>&1
}

# stop_hook <LANG> <root> → 写した Claude Code の Stop 接続口に、Stop の入力を 1 回送る
stop_hook() {
  printf '{"session_id":"deployed-checks","stop_hook_active":false,"cwd":"%s"}' "$2" | in_env "$1" /bin/bash "$H/claude-stop.sh" --global 2>&1
}

# first_fail <出力> → 理由に添える、最初の FAIL の行（中身の無い行は飛ばす）
first_fail() { printf '%s\n' "$1" | grep -E '^(FAIL|RESULT: FAIL)' | grep -vE '\] *$' | head -1; }

# exists <パス> → 「ある」か「無い」
exists() { if [ -e "$1" ]; then printf 'ある'; else printf '無い'; fi; }

# 1. check-file.sh: 写した先では、tmp/ の外のファイルを検査しない（deploy-5）
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

  # プロジェクト自身のファイルは、hooks と同じ絶対パスで渡しても、検査せずに PASS
  for f in README.md tsconfig.json scripts/list.sh docs/setup.md; do
    case "$f" in README.md) label=readme ;; tsconfig.json) label=tsconfig ;; scripts/*) label=script ;; *) label=docs ;; esac
    out="$(check "$L" "$P" "$P/$f")"; rc=$?
    if [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -qF "$SKIP_MARK"; then ok "project-$label$s"
    else ng "project-$label$s" "rc=${rc}。プロジェクト自身の ${f} を検査した: $(first_fail "$out")"; fi
  done
  out="$(check "$L" "$P" README.md)"; rc=$?
  if [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -qF "$SKIP_MARK"; then ok "project-relative$s"
  else ng "project-relative$s" "rc=${rc}。相対パスの README.md を検査した: $(first_fail "$out")"; fi

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
  # 文書が 1 本も無い置き場でも、bash 3.2 の set -u で落ちない
  if printf '%s\n' "$out" | grep -q 'unbound variable'; then ng "no-docs$s" "文書が無いと set -u で落ちる"
  elif [ "$rc" -eq 0 ] && ! printf '%s\n' "$out" | grep -qF 'tmp の文書'; then ok "no-docs$s"
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

  # 写した Stop の hook: 1 回目は回り、変更の無い 2 回目は回らず、直したあとの 3 回目は回る
  P="$B/verify stop"
  V="$P/tmp/.verify"
  new_project "$P" mark || ng "setup$s" "偽のプロジェクトを作れない（${P}）"
  unit_test "$P" 1
  commands_file "$P" "$UNITTEST_CMD"
  mkdir -p "$P/src"
  printf 'x = 1\n' > "$P/src/app.py"
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
  # 命令のファイルが無い置き場では、落ちる試験があっても自動では回さず、PASS（終了コード 0）で印を書く
  P="$B/verify nocmd"
  new_project "$P" mark || ng "setup$s" "偽のプロジェクトを作れない（${P}）"
  unit_test "$P" 2
  mkdir -p "$P/src"
  printf 'x = 1\n' > "$P/src/app.py"
  out="$(verify "$L" "$P")"; rc=$?
  if [ "$rc" -eq 0 ] && [ -f "$P/tmp/.verify/last-pass" ] && ! printf '%s\n' "$out" | grep -q 'unittest'; then ok "no-commands-pass$s"
  else ng "no-commands-pass$s" "rc=${rc}（0 のはず）。印が$(exists "$P/tmp/.verify/last-pass")。$(first_fail "$out")"; fi
  P="$B/lab"
  unit_test "$P" 1
  out="$(verify "$L" "$P" tools)"; rc=$?
  if [ "$rc" -eq 0 ] && [ ! -e "$P/tmp/.verify/last-pass" ] && [ -f "$P/tmp/.verify/project-verify-last-fast.txt" ]; then ok "no-mark-in-lab$s"
  else ng "no-mark-in-lab$s" "rc=${rc}（0 のはず）。My-Lab の形で印が$(exists "$P/tmp/.verify/last-pass")"; fi
}

# 3. project-verify.sh: 空白と日本語を含む文書のパスを、1 本のまま渡す（deploy-8）
cases_doc_paths() {
  local L="$1" B="$2" s="@$1" P D out rc bt='`'
  P="$B/verify docs"
  D="$P/tmp/flow/2026-11-09 ログイン改修"
  new_project "$P" mark || ng "setup$s" "偽のプロジェクトを作れない（${P}）"
  unit_test "$P" 1
  mkdir -p "$D"
  good_doc "$D/note.md"
  good_doc "$P/tmp/ISSUE_2026-11-09_login fix.md"
  out="$(verify "$L" "$P")"; rc=$?
  if [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -qF 'RESULT: PASS check-file（tmp の文書 2 本）' \
     && printf '%s\n' "$out" | grep -qF 'RESULT: PASS check-refs（tmp の文書 2 本）'; then ok "doc-path-space$s"
  else ng "doc-path-space$s" "rc=${rc}（0 のはず）: $(first_fail "$out")"; fi
  # 無いファイルを指す行を足すと、その文書の check-refs が FAIL を出す（切れた名前を読み飛ばさない）
  printf '\n手順は %sscripts/deploy-prod.sh%s に書きます。\n' "$bt" "$bt" >> "$D/note.md"
  out="$(verify "$L" "$P")"; rc=$?
  if [ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -F 'FAIL check-refs（tmp の文書 2 本）:' | grep -F 'ログイン改修/note.md' | grep -qF 'scripts/deploy-prod.sh'; then
    ok "doc-path-space-refs$s"
  else ng "doc-path-space-refs$s" "rc=${rc}（1 のはず）。check-refs が壊れた参照を示さない: $(printf '%s\n' "$out" | grep -F 'check-refs' | head -1)"; fi
}

i=0
for L in C ja_JP.UTF-8; do
  i=$((i + 1))
  B="$T/$i"
  mkdir -p "$B"
  new_lab "$B/lab" || ng "setup@$L" "My-Lab の形を作れない"
  cases_check_file "$L" "$B"
  cases_last_pass "$L" "$B"
  cases_doc_paths "$L" "$B"
done
finish
