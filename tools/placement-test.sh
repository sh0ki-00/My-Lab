#!/usr/bin/env bash
# tools/placement-test.sh — 配置の試験（仕様書 9.4 節の 7）。
#   使い捨てのリポジトリに deploy.sh を流し、tmp/ に skills・.company・tools が揃う、git status に tmp/ が出ない、
#   User Rules の本文が指す tmp/ のパスが写しの中に実在する、写しの project-verify.sh が動く、を確かめる。
#   検証の命令が無い置き場では project-verify が WARN（終了コード 3）を返し、tests/ の test_*.py は unittest で回すことも確かめる。
#   写した説明の文書（tmp/claude-code.md、tmp/cursor-user-rule.md）に、写した先の check-refs が FAIL を出さないことも確かめる。
#   さらに HOME を使い捨ての場所に向けて install.sh を回し、hooks が登録され、旧 cradle の登録が外れ、他の設定が残り、
#   常時ルール（~/.claude/CLAUDE.md、~/.cursor/rules）に何も書かれないことを確かめる。本物の HOME には触れない。
# 出力: FAIL placement [<観点>] <内容> と、最後に RESULT: PASS|FAIL placement-test。
set -u
TOOLS="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
LAB="$(cd "$TOOLS/.." && pwd -P)" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
fail=0
bad() { fail=$((fail + 1)); printf 'FAIL placement [%s] %s\n' "$1" "$2"; }

# 1. 使い捨てのリポジトリに deploy.sh
P="$T/proj"
mkdir -p "$P"
git -C "$P" init -q
printf 'x\n' > "$P/README.md"
out="$(bash "$LAB/deploy.sh" "$P" 2>&1)" || bad deploy "$out"
for d in skills .company tools samples; do [ -d "$P/tmp/$d" ] || bad 揃う "tmp/$d/ が無い"; done
for f in tools/verify-all.sh tools/check-file.sh tools/project-verify.sh .company/CLAUDE.md .company/DELIVERY.md .company/secretary/CLAUDE.md DEPLOYED.md cursor-user-rule.md claude-code.md; do
  [ -f "$P/tmp/$f" ] || bad 揃う "tmp/$f が無い"
done
[ -z "$(find "$P/tmp" -name '__pycache__' 2>/dev/null)" ] || bad 揃う "__pycache__ まで写った"
if ! { grep -qF '.claude/CLAUDE.md' "$P/tmp/DEPLOYED.md" && grep -qF 'User Rules' "$P/tmp/DEPLOYED.md"; }; then
  bad 貼り先 "DEPLOYED.md に Claude Code と Cursor の貼り先が無い"
fi
out="$(cd "$P" && bash tmp/tools/verify-all.sh --fast 2>&1)"; rc=$?
{ [ "$rc" -eq 2 ] && printf '%s\n' "$out" | grep -q 'project-verify.sh' && [ ! -e "$P/tmp/tmp" ]; } || bad verify-all "写しの verify-all が止まらない（rc=${rc}）"
grep -qx 'tmp/' "$P/.git/info/exclude" 2>/dev/null || bad exclude ".git/info/exclude に tmp/ が無い"
if git -C "$P" status --porcelain | grep -q 'tmp/'; then bad git "git status に tmp/ が出る"; fi
out="$(bash "$LAB/deploy.sh" "$P" 2>&1)" || bad deploy "2 回目: $out"
[ "$(grep -cx 'tmp/' "$P/.git/info/exclude")" -eq 1 ] || bad exclude "2 回目で exclude に tmp/ が重なる"

# 2. User Rules の本文が指す tmp/ のパスが、写しの中に実在する（後の段階で作る予定のものは除く）
planned="$(grep -v '^#' "$TOOLS/planned-paths.txt" 2>/dev/null | sed '/^$/d')"
bt='`'
for p in $(grep -oE "${bt}tmp/[^${bt}<*{ ]+${bt}" "$LAB/router/cursor-user-rule.md" | tr -d "$bt" | sort -u); do
  rel="${p#tmp/}"
  if printf '%s\n' "$planned" | grep -qx "${rel%/}" || printf '%s\n' "$planned" | grep -qx "$rel"; then continue; fi
  [ -e "$P/${p%/}" ] || bad 参照 "User Rules が指す $p が写しに無い"
done
# 写した説明の文書が指す My-Lab にしか無い物（hooks/ など）は、写した先の check-refs で FAIL にならない
out="$(cd "$P" && bash tmp/tools/check-refs.sh tmp/claude-code.md tmp/cursor-user-rule.md 2>&1)" || bad 参照 "写した先の check-refs が落ちた: $(printf '%s\n' "$out" | grep -E '^FAIL' | head -3)"
# DEPLOYED.md の変更の数は、ファイルの本数で書く（git status の行の数ではない）
grep -q 'git status で [0-9]* 行' "$P/tmp/DEPLOYED.md" && bad 版 "DEPLOYED.md が git status の行の数を書く"

# 3. 写しの project-verify.sh が、そのプロジェクトの命令を見つけて回す
printf '{"name":"t","private":true,"scripts":{"lint":"echo lint ok","test":"echo test ok"}}\n' > "$P/package.json"
mkdir -p "$P/tmp/flow/sample"
printf '# 調査の覚え書き\n\n> **3 行でわかる要約**\n> 1. これは配置の試験で使う見本の文書です。\n> 2. 文体と資料の型の検査を通ることを確かめます。\n> 3. 次に、検査の結果を見ます。\n\n## 1. 目的\n\n写した道具が文書を検査できることを確かめます。短い文書なので、図と表は要りません。\n' > "$P/tmp/flow/sample/note.md"
out="$(cd "$P" && bash tmp/tools/project-verify.sh --fast 2>&1)" || bad project-verify "$(printf '%s\n' "$out" | grep -E '^FAIL' | head -3)"
printf '%s\n' "$out" | grep -q 'npm run lint' || bad project-verify "package.json の lint を見つけない"
printf '%s\n' "$out" | grep -q 'RESULT: PASS check-refs' || bad project-verify "文書に check-refs を回さない"
grep -q '^RESULT: PASS project-verify --fast' "$P/tmp/.verify/last-fast.txt" 2>/dev/null || bad project-verify "tmp/.verify/last-fast.txt に RESULT 行が無い"
# 3b. 検証の命令が無い置き場では PASS にしない。tests/ の test_*.py は unittest で回す（Makefile も package.json も無い）
Q="$T/bare"
mkdir -p "$Q/src"
git -C "$Q" init -q
printf 'x = 1\n' > "$Q/src/app.py"
bash "$LAB/deploy.sh" "$Q" >/dev/null 2>&1 || bad deploy "bare への deploy が落ちた"
out="$(cd "$Q" && bash tmp/tools/project-verify.sh --fast 2>&1)"; rc=$?
{ [ "$rc" -eq 3 ] && printf '%s\n' "$out" | grep -q '^RESULT: WARN project-verify --fast (回す検証の命令が無い'; } || bad project-verify "命令の無い置き場で WARN（終了コード 3）にならない（rc=${rc}）"
mkdir -p "$Q/tests"
printf 'import unittest\n\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(1, 1)\n' > "$Q/tests/test_app.py"
out="$(cd "$Q" && bash tmp/tools/project-verify.sh --fast 2>&1)"; rc=$?
{ [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -qF 'RESULT: PASS python3 -m unittest discover'; } || bad project-verify "tests/test_*.py を unittest で回さない（rc=${rc}）"
printf 'import unittest\n\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(1, 2)\n' > "$Q/tests/test_app.py"
(cd "$Q" && bash tmp/tools/project-verify.sh --fast >/dev/null 2>&1); rc=$?
[ "$rc" -eq 1 ] || bad project-verify "落ちる tests/test_*.py で FAIL（終了コード 1）にならない（rc=${rc}）"

# 4. hooks の部品が写しの中の道具を見つける
# shellcheck source=hooks/lib.sh
# shellcheck disable=SC1091
. "$LAB/hooks/lib.sh"
[ "$(tools_dir "$P")" = "$P/tmp/tools" ] || bad hooks "tools_dir が tmp/tools を指さない: $(tools_dir "$P")"
[ "$(verify_cmd "$P")" = "bash tmp/tools/project-verify.sh --fast" ] || bad hooks "verify_cmd が project-verify を指さない"

# 5. install.sh を偽の HOME で回す。常時ルールに書かない、hooks が登録される、旧登録が外れる、他の設定が残る
FH="$T/home"
mkdir -p "$FH/.claude" "$FH/.cursor"
printf '{"model":"keep","hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"/x/cradle-guard-claude.sh"}]}]}}\n' > "$FH/.claude/settings.json"
printf '{"version":1,"hooks":{"beforeShellExecution":[{"command":"/x/cradle-guard-cursor.sh"}]}}\n' > "$FH/.cursor/hooks.json"
out="$(HOME="$FH" bash "$LAB/install.sh" 2>&1)" || bad install "$out"
[ -e "$FH/.claude/CLAUDE.md" ] && bad 常時ルール "install.sh が ~/.claude/CLAUDE.md を作った"
[ -e "$FH/.cursor/rules" ] && bad 常時ルール "install.sh が ~/.cursor/rules を作った"
jq -e . "$FH/.claude/settings.json" >/dev/null 2>&1 || bad 登録 "偽 HOME の .claude/settings.json が JSON でない"
jq -e . "$FH/.cursor/hooks.json" >/dev/null 2>&1 || bad 登録 "偽 HOME の .cursor/hooks.json が JSON でない"
grep -q 'claude-pretooluse.sh --global' "$FH/.claude/settings.json" || bad 登録 "Claude の PreToolUse が登録されない"
grep -q 'claude-stop.sh --global' "$FH/.claude/settings.json" || bad 登録 "Claude の Stop が登録されない"
grep -q 'cradle-guard' "$FH/.claude/settings.json" && bad 旧登録 "旧 cradle の登録が Claude 側に残る"
jq -e '.model == "keep"' "$FH/.claude/settings.json" >/dev/null 2>&1 || bad 保持 "他の設定（model）が消えた"
grep -q 'cursor-before-shell.sh --global' "$FH/.cursor/hooks.json" || bad 登録 "Cursor の beforeShellExecution が登録されない"
grep -q 'cradle-guard' "$FH/.cursor/hooks.json" && bad 旧登録 "旧 cradle の登録が Cursor 側に残る"
ls "$FH/.claude/settings.json.bak."* >/dev/null 2>&1 || bad 退避 "settings.json の退避ファイルが無い"
out="$(HOME="$FH" bash "$LAB/install.sh" 2>&1)" || bad install "2 回目: $out"
[ "$(grep -c 'claude-pretooluse.sh --global' "$FH/.claude/settings.json")" -eq 1 ] || bad 登録 "2 回目で Claude の登録が重なる"
[ "$(grep -c 'cursor-before-shell.sh --global' "$FH/.cursor/hooks.json")" -eq 1 ] || bad 登録 "2 回目で Cursor の登録が重なる"
# deploy.sh も HOME に何も書かない
before="$(find "$FH" -type f | sort)"
HOME="$FH" bash "$LAB/deploy.sh" "$P" >/dev/null 2>&1 || bad deploy "HOME を変えた deploy が落ちた"
[ "$before" = "$(find "$FH" -type f | sort)" ] || bad 常時ルール "deploy.sh が HOME の下に何か書いた"

if [ "$fail" -eq 0 ]; then verdict=PASS; else verdict=FAIL; fi
printf 'RESULT: %s placement-test (%d 件)\n' "$verdict" "$fail"
[ "$fail" -eq 0 ]
