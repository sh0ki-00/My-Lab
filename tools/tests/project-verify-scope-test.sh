#!/usr/bin/env bash
# tools/tests/project-verify-scope-test.sh — project-verify.sh の範囲の試験（改善提案書 13 章の V-1〜V-4）。
#   移した先の形の一時フォルダ（<プロジェクト>/tmp/tools と tmp/DEPLOYED.md）を作り、文書の検査が、引数で渡した文書だけに回るかを確かめる。
#   V-1: 別の文書が落ちていても、引数の文書が通れば PASS。別の文書の名前は、出力にも記録（tmp/.verify/last-fast.txt）にも出ない。
#   V-2: 引数なしなら、check-file が 1 回も呼ばれない。呼ばれたら印を残す偽の check-file と check-refs を tmp/tools に置いて確かめる。
#        検査した文書も命令も無い回は、PASS にせず WARN（終了コード 3）で終わり、印（tmp/.verify/last-pass）も書かない。
#   V-3: 引数の文書が落ちれば FAIL で、出力に出る文書の名前は、その文書だけ。渡した文書が 6 本でも、落ちた文書の名前が FAIL の行に出る。
#   V-4: 2 本のうち 1 本だけを渡すと、偽の check-file と check-refs が受け取るのは、渡した 1 本だけ。
#   ほかに、絶対パスと -- の区切りと同じ文書の重なり、文書でない引数、無いファイルの引数、使い方の誤り、
#   命令のファイルが引数によらず回ること、PASS でだけ印（tmp/.verify/last-pass）を書くことを確かめる。
# 偽のプロジェクトは手で作る（tools/ を tmp/tools に写し、tmp/DEPLOYED.md を書く）。git と deploy.sh は使わない。本物の HOME には触れない。
# 場面は全部、LANG=C と LANG=ja_JP.UTF-8 の 2 通りで回す。bash は /bin/bash（3.2）を使う。
# 呼び方: 手で回す（bash tools/tests/project-verify-scope-test.sh）。tools/verify-all.sh --full の 7 番も、tools/tests/ のほかの試験と一緒に回す。
# 出力: 場面ごとに PASS <場面>@<LANG> か FAIL <場面>@<LANG> <理由>。最後に RESULT 行。1 件でも FAIL なら終了コード 1。
set -u
LAB="$(cd "$(dirname "$0")/../.." && pwd -P)" || exit 1
NAME="project-verify-scope-test"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
RUN_PATH="/opt/homebrew/bin:/usr/bin:/bin"
EN_TEXT="This service handles order intake for the shop and stores every order in PostgreSQL for later reporting."
MINE="tmp/flow/このセッション/report.md"          # このセッションが書いた文書
MINE_SPACE="tmp/flow/2026-11-26 作業/notes.md"     # 空白を含む置き場の文書
OTHER="tmp/flow/ほかのセッション/draft.md"         # ほかのセッションが書いた文書（引数に入れない）
OTHER_MARK="ほかのセッション"
total=0; failed=0

ok() { total=$((total + 1)); printf 'PASS %s\n' "$1"; }
ng() { total=$((total + 1)); failed=$((failed + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }
finish() {
  if [ "$failed" -eq 0 ]; then printf 'RESULT: PASS %s (%d 件)\n' "$NAME" "$total"; exit 0; fi
  printf 'RESULT: FAIL %s (%d 件中 FAIL %d)\n' "$NAME" "$total" "$failed"; exit 1
}

if [ ! -f "$LAB/tools/project-verify.sh" ] || [ ! -f "$LAB/tools/check-file.sh" ]; then
  ng setup "My-Lab の tools/ が見つからない（${LAB}）"; finish
fi
if ! locale -a 2>/dev/null | grep -qx 'ja_JP.UTF-8'; then ng setup "文字の設定 ja_JP.UTF-8 が無い（SKIP は FAIL と同じ）"; finish; fi
tmpbase="${TMPDIR:-/tmp}"
T="$(mktemp -d "${tmpbase%/}/pv-scope.XXXXXX")" || exit 1
trap 'rm -rf "$T"' EXIT
T="$(cd "$T" && pwd -P)" || exit 1   # /var と /private/var の別名をそろえる
FH="$T/home"
mkdir -p "$FH"

# in_env <LANG> <コマンド...> → 偽の HOME と短い PATH と、指定の LANG だけの環境で回す
in_env() { local l="$1"; shift; env -i HOME="$FH" PATH="$RUN_PATH" LANG="$l" "$@"; }

# new_project <場所> → 移した先の形。tools/ の写しを tmp/tools に置き、tmp/DEPLOYED.md を書く
new_project() {
  mkdir -p "$1/tmp" && cp -R "$LAB/tools" "$1/tmp/tools" && printf '# この tmp/ の写しについて\n\n正本: %s\n' "$LAB" > "$1/tmp/DEPLOYED.md"
}

# fake_checks <プロジェクト> → tmp/tools の check-file.sh と check-refs.sh を偽物に替える。
#   偽物は、受け取った引数を 1 行 1 本で tmp/tools/called-<名前>.txt に書き足し、PASS を返す。ファイルがあれば、呼ばれた印になる
fake_checks() {
  local t
  for t in check-file check-refs; do
    cat > "$1/tmp/tools/$t.sh" <<'EOF'
#!/bin/bash
log="$(dirname "$0")/called-$(basename "$0" .sh).txt"
if [ "$#" -eq 0 ]; then printf '（引数なし）\n' >> "$log"; fi
for a in "$@"; do printf '%s\n' "$a" >> "$log"; done
printf 'RESULT: PASS %s（偽物）\n' "$(basename "$0" .sh)"
EOF
  done
}

# new_fake_project <場所> → 移した先の形で、check-file.sh と check-refs.sh だけを偽物にしたもの
new_fake_project() { new_project "$1" && fake_checks "$1"; }

# good_doc <ファイル> → 文体と資料の型の検査を通る文書（tools/placement-test.sh の見本と同じ中身）
good_doc() {
  mkdir -p "$(dirname "$1")" && printf '# 調査の覚え書き\n\n> **3 行でわかる要約**\n> 1. これは配置の試験で使う見本の文書です。\n> 2. 文体と資料の型の検査を通ることを確かめます。\n> 3. 次に、検査の結果を見ます。\n\n## 1. 目的\n\n写した道具が文書を検査できることを確かめます。短い文書なので、図と表は要りません。\n' > "$1"
}

# bad_doc <ファイル> → 文体と資料の型の検査で落ちる文書（英文だけ）
bad_doc() { mkdir -p "$(dirname "$1")" && printf '# Note\n\n%s\n' "$EN_TEXT" > "$1"; }

# verify <LANG> <プロジェクト> [引数...] → プロジェクトの root で project-verify.sh --fast を回す（hooks と同じく root から）
verify() { local l="$1" p="$2"; shift 2; (cd "$p" && in_env "$l" /bin/bash tmp/tools/project-verify.sh --fast "$@" 2>&1); }

has() { printf '%s\n' "$1" | grep -qF -- "$2"; }               # has <出力> <文字列> → 出力に文字列がある
called() { cat "$1/tmp/tools/called-$2.txt" 2>/dev/null; }    # called <プロジェクト> <check-file|check-refs> → 偽物が受け取った引数
doc_names() { printf '%s\n' "$1" | grep -oE 'tmp/flow/[^ :]+[.]md' | LC_ALL=C sort -u; }   # 出力に出た文書の名前
first_fail() { printf '%s\n' "$1" | grep -E '^(FAIL|RESULT: FAIL)' | head -1; }

# V-1: 別の文書が落ちていても、引数の文書が通れば PASS。別の文書の名前は、出力にも記録にも出ない（本物の検査で回す）
case_v1() {
  local L="$1" s="@$1" P="$2/v1" out rc
  new_project "$P" || { ng "setup$s" "偽のプロジェクトを作れない（${P}）"; return; }
  good_doc "$P/$MINE"; bad_doc "$P/$OTHER"
  out="$(verify "$L" "$P" "$MINE")"; rc=$?
  if [ "$rc" -eq 0 ] && has "$out" 'RESULT: PASS check-file（渡した文書 1 本）' && has "$out" 'RESULT: PASS check-refs（渡した文書 1 本）' \
     && has "$out" 'RESULT: PASS project-verify --fast' && ! has "$out" "$OTHER_MARK"; then ok "V-1$s"
  else ng "V-1$s" "rc=${rc}（0 のはず）。ほかの文書の名前が出たか、PASS にならない: $(first_fail "$out")"; fi
  if [ -f "$P/tmp/.verify/last-fast.txt" ] && ! grep -qF "$OTHER_MARK" "$P/tmp/.verify/last-fast.txt" \
     && grep -qF "$MINE" "$P/tmp/.verify/last-fast.txt"; then ok "V-1-record$s"
  else ng "V-1-record$s" "記録 tmp/.verify/last-fast.txt に、渡した文書が無いか、ほかの文書の名前がある"; fi
  if [ -f "$P/tmp/.verify/last-pass" ]; then ok "pass-writes-mark$s"
  else ng "pass-writes-mark$s" "PASS なのに印 tmp/.verify/last-pass を書かない"; fi
}

# V-2: 引数なしなら check-file も check-refs も呼ばれない。何も検査しない回は WARN（終了コード 3）。命令のファイルの命令は、引数によらず回る
case_v2() {
  local L="$1" s="@$1" P="$2/v2" out rc
  new_fake_project "$P" || { ng "setup$s" "偽のプロジェクトを作れない（${P}）"; return; }
  good_doc "$P/$MINE"; bad_doc "$P/$OTHER"; good_doc "$P/tmp/ISSUE_2026-11-26_x.md"; good_doc "$P/tmp/PR_7.md"
  out="$(verify "$L" "$P")"; rc=$?
  if [ "$rc" -eq 3 ] && [ ! -e "$P/tmp/tools/called-check-file.txt" ] && [ ! -e "$P/tmp/tools/called-check-refs.txt" ] \
     && has "$out" '文書の指定なし（検査した文書 0 本）' && ! has "$out" 'tmp/flow/' && ! has "$out" 'ISSUE_' && ! has "$out" 'PR_7'; then ok "V-2$s"
  else ng "V-2$s" "rc=${rc}（3 のはず）。check-file が呼ばれた=$([ -e "$P/tmp/tools/called-check-file.txt" ] && echo yes || echo no): $(printf '%s' "$out" | tr '\n' ' ' | head -c 160)"; fi
  # 何も検査しない回を PASS にしない。記録にも WARN を残し、印は書かない（commit の前の証拠に使わせない）
  if has "$out" 'RESULT: WARN project-verify --fast (0 件中 FAIL 0。検査なし' && ! has "$out" 'RESULT: PASS project-verify' \
     && grep -qF 'RESULT: WARN project-verify --fast' "$P/tmp/.verify/last-fast.txt" 2>/dev/null && [ ! -e "$P/tmp/.verify/last-pass" ]; then ok "V-2-warn$s"
  else ng "V-2-warn$s" "何も検査しない回が WARN にならないか、印を書いた: $(printf '%s' "$out" | grep '^RESULT: [A-Z]* project-verify' | head -1)"; fi
  printf '# 検証の命令\necho cmd ok\n' > "$P/tmp/verify-commands.txt"
  out="$(verify "$L" "$P")"; rc=$?
  if [ "$rc" -eq 0 ] && has "$out" 'RESULT: PASS echo cmd ok' && has "$out" 'RESULT: PASS project-verify --fast (1 件中 FAIL 0)' \
     && [ ! -e "$P/tmp/tools/called-check-file.txt" ]; then ok "V-2-commands$s"
  else ng "V-2-commands$s" "rc=${rc}（0 のはず）。引数なしで命令が回らないか、check-file が呼ばれた: $(first_fail "$out")"; fi
}

# V-3: 引数の文書が落ちれば FAIL。出力に出る文書の名前は、その文書だけ。FAIL では印を書かない
case_v3() {
  local L="$1" s="@$1" P="$2/v3" out rc names
  new_project "$P" || { ng "setup$s" "偽のプロジェクトを作れない（${P}）"; return; }
  bad_doc "$P/$MINE"; bad_doc "$P/$OTHER"
  out="$(verify "$L" "$P" "$MINE")"; rc=$?
  names="$(doc_names "$out")"
  if [ "$rc" -eq 1 ] && has "$out" 'RESULT: FAIL check-file（渡した文書 1 本）' && has "$out" 'RESULT: FAIL project-verify --fast' \
     && [ "$names" = "$MINE" ]; then ok "V-3$s"
  else ng "V-3$s" "rc=${rc}（1 のはず）。出力に出た文書: $(printf '%s' "$names" | tr '\n' ' ')"; fi
  if [ ! -e "$P/tmp/.verify/last-pass" ]; then ok "fail-no-mark$s"
  else ng "fail-no-mark$s" "FAIL なのに印 tmp/.verify/last-pass を書いた"; fi
}

# V-3（文書が多いとき）: 6 本のうち、名前の順で最初の 1 本だけが落ちる。通った 5 本の行で押し出されず、落ちた文書の名前が FAIL の行に出る
case_v3_many() {
  local L="$1" s="@$1" P="$2/v3many" out rc x
  new_project "$P" || { ng "setup$s" "偽のプロジェクトを作れない（${P}）"; return; }
  bad_doc "$P/tmp/flow/many/a-bad.md"
  for x in b c d e f; do good_doc "$P/tmp/flow/many/$x.md"; done
  out="$(verify "$L" "$P" tmp/flow/many/a-bad.md tmp/flow/many/b.md tmp/flow/many/c.md tmp/flow/many/d.md tmp/flow/many/e.md tmp/flow/many/f.md)"; rc=$?
  if [ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -F 'FAIL check-file（渡した文書 6 本）: ' | grep -F 'a-bad.md' | grep -qF 'FAIL'; then ok "V-3-many$s"
  else ng "V-3-many$s" "rc=${rc}（1 のはず）。落ちた文書の名前が FAIL の行に無い: $(printf '%s\n' "$out" | grep -F 'FAIL check-file' | head -2 | tr '\n' ' ')"; fi
}

# V-4: 2 本のうち 1 本だけを渡すと、check-file と check-refs が受け取るのは、渡した 1 本だけ
case_v4() {
  local L="$1" s="@$1" P="$2/v4" out rc
  new_fake_project "$P" || { ng "setup$s" "偽のプロジェクトを作れない（${P}）"; return; }
  good_doc "$P/$MINE"; good_doc "$P/$OTHER"
  out="$(verify "$L" "$P" "$MINE")"; rc=$?
  if [ "$rc" -eq 0 ] && [ "$(called "$P" check-file)" = "$MINE" ] && [ "$(called "$P" check-refs)" = "$MINE" ] \
     && has "$out" 'RESULT: PASS check-file（渡した文書 1 本）' && ! has "$out" "$OTHER_MARK"; then ok "V-4$s"
  else ng "V-4$s" "rc=${rc}（0 のはず）。check-file が受け取った: $(called "$P" check-file | tr '\n' ' ')"; fi
}

# 引数の形: 絶対パス、-- の区切り、同じ文書の重なり、空白を含むパス、Issue 文と PR 文、文書でない引数
case_args() {
  local L="$1" s="@$1" P="$2/args" out rc want got
  new_fake_project "$P" || { ng "setup$s" "偽のプロジェクトを作れない（${P}）"; return; }
  good_doc "$P/$MINE"; good_doc "$P/$MINE_SPACE"; good_doc "$P/tmp/ISSUE_2026-11-26_x.md"; good_doc "$P/tmp/PR_7.md"; good_doc "$P/$OTHER"
  mkdir -p "$P/src" "$P/tmp/sub"
  printf 'x = 1\n' > "$P/src/app.py"
  printf '{}\n' > "$P/tmp/flow/data.json"
  good_doc "$P/tmp/sub/PR_1.md"
  out="$(verify "$L" "$P" -- "$P/$MINE" "$MINE" "./$MINE_SPACE" tmp/ISSUE_2026-11-26_x.md "$P/tmp/PR_7.md" src/app.py tmp/flow/data.json tmp/sub/PR_1.md)"; rc=$?
  want="$(printf '%s\n' "$MINE" "$MINE_SPACE" tmp/ISSUE_2026-11-26_x.md tmp/PR_7.md)"
  got="$(called "$P" check-file)"
  if [ "$rc" -eq 0 ] && [ "$got" = "$want" ] && [ "$(called "$P" check-refs)" = "$want" ] \
     && has "$out" 'RESULT: PASS check-file（渡した文書 4 本）' && ! has "$out" "$OTHER_MARK"; then ok "args-docs$s"
  else ng "args-docs$s" "rc=${rc}（0 のはず）。check-file が受け取った: $(printf '%s' "$got" | tr '\n' '|')"; fi
  if has "$out" '文書でないので見ない 3 本' && ! has "$out" '文書の指定なし'; then ok "args-not-docs$s"
  else ng "args-not-docs$s" "「文書でないので見ない 3 本」の行が無い: $(printf '%s' "$out" | tr '\n' ' ' | head -c 160)"; fi
  if grep -qF "命令: bash tmp/tools/project-verify.sh --fast -- '$P/$MINE'" "$P/tmp/.verify/last-fast.txt" 2>/dev/null; then ok "args-recorded$s"
  else ng "args-recorded$s" "記録の命令の行に、渡した引数が無い"; fi
}

# 無いファイルの引数は FAIL。使い方の誤りは終了コード 2
case_errors() {
  local L="$1" s="@$1" P="$2/errors" out rc
  new_fake_project "$P" || { ng "setup$s" "偽のプロジェクトを作れない（${P}）"; return; }
  good_doc "$P/$MINE"
  out="$(verify "$L" "$P" tmp/flow/無い.md)"; rc=$?
  if [ "$rc" -eq 1 ] && has "$out" 'RESULT: FAIL 引数のファイル（無い 1 本）' && has "$out" 'tmp/flow/無い.md' \
     && has "$out" 'RESULT: FAIL project-verify --fast' && [ ! -e "$P/tmp/tools/called-check-file.txt" ]; then ok "missing-arg$s"
  else ng "missing-arg$s" "rc=${rc}（1 のはず）: $(first_fail "$out")"; fi
  out="$(verify "$L" "$P" "$MINE" tmp/flow/無い.md)"; rc=$?
  if [ "$rc" -eq 1 ] && [ "$(called "$P" check-file)" = "$MINE" ]; then ok "missing-arg-with-doc$s"
  else ng "missing-arg-with-doc$s" "rc=${rc}（1 のはず）。渡した文書を検査しないか、無いファイルで PASS になった"; fi
  out="$(verify "$L" "$P" "$P/tmp/flow")"; rc=$?
  if [ "$rc" -eq 1 ] && has "$out" 'RESULT: FAIL 引数のファイル（無い 1 本）'; then ok "dir-arg$s"
  else ng "dir-arg$s" "rc=${rc}（1 のはず）。フォルダを渡して FAIL にならない"; fi
  out="$( (cd "$P" && in_env "$L" /bin/bash tmp/tools/project-verify.sh --bogus 2>&1) )"; rc=$?
  if [ "$rc" -eq 2 ] && has "$out" '使い方'; then ok "usage$s"; else ng "usage$s" "rc=${rc}（2 のはず）"; fi
  out="$( (cd "$P" && in_env "$L" /bin/bash tmp/tools/project-verify.sh --baseline "$MINE" 2>&1) )"; rc=$?
  if [ "$rc" -eq 2 ] && [ ! -e "$P/tmp/.verify/last-pass" ]; then ok "baseline-no-args$s"
  else ng "baseline-no-args$s" "rc=${rc}（2 のはず）。--baseline が引数を受け付けた"; fi
}

i=0
for L in C ja_JP.UTF-8; do
  i=$((i + 1))
  B="$T/$i"
  mkdir -p "$B"
  case_v1 "$L" "$B"
  case_v2 "$L" "$B"
  case_v3 "$L" "$B"
  case_v3_many "$L" "$B"
  case_v4 "$L" "$B"
  case_args "$L" "$B"
  case_errors "$L" "$B"
done
finish
