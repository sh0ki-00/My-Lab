#!/usr/bin/env bash
# hooks/selftest.sh — hooks の自己試験。
# 1) 判定本体に、承認が要る操作・取り消せない操作・読むだけの操作・合図の語を流し、判定表どおりかを見る。
# 2) 接続口に両ツールの形の JSON を流し、端から端で正しい形の出力が出るかを見る。
# 使い方: bash hooks/selftest.sh   → 1 件でも落ちれば終了コード 1
set -u
HOOKS_DIR="$(cd "$(dirname "$0")" && pwd -P)"
LAB_ROOT="$(cd "$HOOKS_DIR/.." && pwd -P)"
CORE="$HOOKS_DIR/guard-core.sh"
pass=0; fail=0
ok()  { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; }

# expect <期待> <signal> <コマンド>
expect() {
  local want="$1" mode="$2" cmd="$3" got
  got="$(bash "$CORE" --signal "$mode" -- "$cmd" | cut -f1)"
  if [ "$got" = "$want" ]; then ok; else bad "判定: 期待 $want / 実際 $got : $cmd"; fi
}

# ---- 1. 判定表
# 1a. 関所 2（外に出る操作）→ ask
expect ask deny 'git commit -m "x"'
expect ask deny 'git commit --amend --no-edit'
expect ask deny 'git -C /tmp/x commit -m x'
expect ask deny 'git -c user.name=a commit -m x'
expect ask deny 'git --no-pager commit -m x'
expect ask deny '/usr/bin/git commit -m x'
expect ask deny "'git' 'commit' -m x"
expect ask deny 'git    commit -m x'
expect ask deny "$(printf 'git\ncommit -m x')"
expect ask deny "$(printf 'git\tcommit -m x')"
expect ask deny 'git status && git commit -m x'
expect ask deny 'cd /tmp; git push origin main'
expect ask deny 'echo ok | git push'
expect ask deny 'sh -c "git push --force"'
expect ask deny 'git push'
expect ask deny 'git push -u origin HEAD'
expect ask deny 'git push origin --delete feature'
expect ask deny 'gh pr create --fill'
expect ask deny 'gh pr merge 12 --squash'
expect ask deny 'gh pr comment 12 --body hi'
expect ask deny 'gh issue create --title x'
expect ask deny 'gh issue close 3'
expect ask deny 'gh release create v1.0.0'
expect ask deny 'gh repo create foo'
expect ask deny 'gh api -X POST repos/o/r/issues'
expect ask deny 'gh api --method DELETE repos/o/r'
expect ask deny 'gh api repos/o/r/issues -f title=x'
expect ask deny 'gh secret set TOKEN'
expect ask deny 'gh workflow run ci.yml'
expect ask deny 'npm publish'
expect ask deny 'docker push img:1'
# 1b. 取り消せない操作 → ask
expect ask deny 'git reset --hard HEAD~1'
expect ask deny 'git reset --merge'
expect ask deny 'git clean -fd'
expect ask deny 'git clean -f'
expect ask deny 'git clean -xdf'
expect ask deny 'git clean --force'
expect ask deny 'git stash drop'
expect ask deny 'git stash clear'
expect ask deny 'git branch -D feature'
expect ask deny 'git branch -d feature'
expect ask deny 'git branch --delete feature'
expect ask deny 'git tag -d v1'
expect ask deny 'git checkout --ours file'
expect ask deny 'git checkout --theirs file'
expect ask deny 'git restore --theirs file'
expect ask deny 'git merge -X ours main'
expect ask deny 'git merge -Xtheirs main'
expect ask deny 'git merge -s ours main'
expect ask deny 'git rebase -i HEAD~3'
expect ask deny 'git rebase main'
expect ask deny 'git filter-branch --all'
expect ask deny 'git reflog expire --expire=now --all'
expect ask deny 'git gc --prune=now'
expect ask deny 'git checkout -- .'
expect ask deny 'git checkout .'
expect ask deny 'git checkout ./src'
expect ask deny 'git checkout -f main'
expect ask deny 'git restore src/a.ts'
expect ask deny 'git restore --staged --worktree src/a.ts'
expect ask deny 'rm -rf .git'
expect ask deny 'rm -rf /tmp/x/.git'
# 1c. 読むだけか、取り消せる操作 → allow
expect allow deny 'git status'
expect allow deny 'git diff --stat'
expect allow deny 'git log --oneline -5'
expect allow deny 'git add -A'
expect allow deny 'git add .'
expect allow deny 'git stash'
expect allow deny 'git stash list'
expect allow deny 'git stash pop'
expect allow deny 'git fetch --all'
expect allow deny 'git pull'
expect allow deny 'git pull --rebase'
expect allow deny 'git checkout main'
expect allow deny 'git checkout -b feature'
expect allow deny 'git switch -c feature'
expect allow deny 'git branch'
expect allow deny 'git branch -a'
expect allow deny 'git branch --merged'
expect allow deny 'git branch -m old new'
expect allow deny 'git branch --set-upstream-to=origin/main'
expect allow deny 'git merge feature'
expect allow deny 'git merge --no-ff feature'
expect allow deny 'git restore --staged file'
expect allow deny 'git reset HEAD~1'
expect allow deny 'git reset --soft HEAD~1'
expect allow deny 'git stash show -p'
expect allow deny 'git show HEAD'
expect allow deny 'git blame file'
expect allow deny 'git tag v1.0.0'
expect allow deny 'git tag -l'
expect allow deny 'git clean -n'
expect allow deny 'git clean --dry-run'
expect allow deny 'git remote -v'
expect allow deny 'git worktree list'
expect allow deny 'gh pr view 12'
expect allow deny 'gh pr list'
expect allow deny 'gh pr checkout 12'
expect allow deny 'gh pr checks 12'
expect allow deny 'gh issue view 3'
expect allow deny 'gh issue list'
expect allow deny 'gh repo view'
expect allow deny 'gh repo clone o/r'
expect allow deny 'gh api repos/o/r/pulls'
expect allow deny 'gh api -H "Accept: application/json" repos/o/r'
expect allow deny 'gh auth status'
expect allow deny 'gh run list'
expect allow deny 'npm test'
expect allow deny 'npm run verify'
expect allow deny 'docker build .'
expect allow deny 'ls -la'
expect allow deny 'cat hooks/guard-core.sh'
expect allow deny 'bash tools/verify-all.sh --fast'
expect allow deny 'bash hooks/selftest.sh'
expect allow deny 'grep -rn "commit" tools/'
expect allow deny 'rm -rf node_modules'
expect allow deny 'rm -rf tmp/.verify'
expect allow deny 'mygit commit'
# 1d. 合図の語。どこにあっても deny。前の退避路の値（honor）を渡しても deny で、合図で通す道は無い
expect deny deny 'APPROVE_GIT=1 git commit -m x'
expect deny deny 'git commit -m x # APPROVE_GIT=1'
expect deny deny 'export APPROVE_GIT=1; git push'
expect deny honor 'APPROVE_GIT=1 git commit -m x'
expect deny honor 'APPROVE_GIT=1 git push'
expect deny honor '  APPROVE_GIT=1 git push'
expect deny honor 'APPROVE_GIT=1 gh pr create --fill'
expect deny honor 'APPROVE_GIT=1 git reset --hard HEAD~1'
expect deny honor 'APPROVE_GIT=1 git status'
expect deny honor 'git status && APPROVE_GIT=1 git push'
expect deny honor 'echo APPROVE_GIT=1'
expect ask honor 'git commit -m x'
expect allow honor 'git status'
if [ "$(bash "$CORE" -- 'APPROVE_GIT=1 git push' | cut -f1)" = deny ]; then ok; else bad "判定: --signal を省いても、先頭の合図つきの push は deny"; fi

# 1e. 守りの設定（mode のファイル）への書き込みと削除 → deny。--signal の値（deny でも honor でも）は判定を変えない
expect deny deny 'printf ask > ~/.cursor/company-guard.mode'
expect deny deny 'echo deny > /Users/s-furutani/.cursor/company-guard.mode'
expect deny deny 'echo ask >> ~/.cursor/company-guard.mode'
expect deny deny 'tee ~/.cursor/company-guard.mode'
expect deny deny 'cp /tmp/x ~/.cursor/company-guard.mode'
expect deny deny 'mv /tmp/x ~/.cursor/company-guard.mode'
expect deny deny 'rm ~/.cursor/company-guard.mode'
expect deny deny 'rm -f /Users/s-furutani/.cursor/company-guard.mode'
expect deny deny 'sed -i "" s/deny/ask/ ~/.cursor/company-guard.mode'
expect deny deny 'truncate -s 0 ~/.cursor/company-guard.mode'
expect deny deny 'python3 -c "open(\"/Users/s-furutani/.cursor/company-guard.mode\",\"w\").write(\"ask\")"'
expect deny honor 'printf ask > ~/.cursor/company-guard.mode'
expect deny honor 'rm ~/.cursor/company-guard.mode'
# 読むだけは allow のまま
expect allow deny 'cat ~/.cursor/company-guard.mode'
expect allow deny 'ls -l ~/.cursor/company-guard.mode'
expect allow deny 'test -f ~/.cursor/company-guard.mode'
expect allow deny 'grep deny ~/.cursor/company-guard.mode'
# 1e-2. 名前と命令を崩した書き方（>|・&>、パス付きの命令名、グロブ、$ に入れた場所、; & ( の直後、親フォルダごと、root の置き場）→ deny
expect deny deny 'printf ask >| ~/.cursor/company-guard.mode'
expect deny deny 'printf ask &> ~/.cursor/company-guard.mode'
expect deny deny '/bin/rm ~/.cursor/company-guard.mode'
expect deny deny 'rm -rf ~/.cursor/company-guard.*'
expect deny deny 'rm ~/.cursor/company-guard.mod?'
# shellcheck disable=SC2016  # $f は判定本体に渡す文字列。わざと展開しない
expect deny deny 'f=~/.cursor/company-guard.mode; printf ask > $f'
# shellcheck disable=SC2016  # 同上
expect deny deny 'echo ask > $HOME/.cursor/company-guard.mode'
expect deny deny 'true;rm ~/.cursor/company-guard.mode'
expect deny deny 'true &rm ~/.cursor/company-guard.mode'
expect deny deny '(rm ~/.cursor/company-guard.mode)'
expect deny deny 'rm -rf ~/.cursor'
expect deny deny 'mv ~/.cursor ~/.cursor.bak'
expect deny deny 'chmod -R a+w ~/.cursor'
expect deny deny 'chown -R s-furutani /Users/s-furutani/.cursor'
expect deny deny 'chflags nouchg ~/.cursor/company-guard.mode'
expect deny deny 'cp /tmp/hooks.json ~/.cursor/hooks.json'
expect deny deny 'echo ask > /usr/local/etc/company-guard/mode'
expect deny deny 'sudo tee /usr/local/etc/company-guard/mode'
expect deny deny 'rm -rf /usr/local/etc/company-guard'
expect deny deny 'sudo chmod 777 /usr/local/etc/company-guard'
# 読みと、日常の命令は allow のまま（プロジェクトの中の .cursor/hooks.json は家のパスでないので対象外）
expect allow deny 'cat /usr/local/etc/company-guard/mode'
expect allow deny 'ls -l /usr/local/etc/company-guard/'
expect allow deny 'ls ~/.cursor'
expect allow deny 'cat ~/.cursor/hooks.json'
expect allow deny 'cat .cursor/hooks.json'
expect allow deny 'jq . .cursor/hooks.json'
expect allow deny 'cp .cursor/hooks.json /tmp/hooks.json.bak'
expect allow deny 'rm -rf /Users/s-furutani/My-Lab/.cursor/tmp'
expect allow deny 'grep -n company-guard hooks/lib.sh'
expect allow deny 'echo hi > tmp/out.txt'
expect allow deny 'sed -n 1,20p hooks/cursor-before-shell.sh'
expect allow deny 'rm -f /tmp/x/.cursor-cache'

# 1f. 符号化した命令。復号した結果をシェルに渡す 5 つの書き方 → ask
expect ask deny 'echo Z2l0IHB1c2g= | base64 -d | sh'
# shellcheck disable=SC2016  # $(...) は判定本体に渡す文字列。わざと展開しない
expect ask deny 'eval "$(echo Z2l0IHB1c2g= | base64 -d)"'
expect ask deny 'printf "\x67it push" | sh'
# shellcheck disable=SC2016  # 同上。符号化した命令を文字列のまま渡す
expect ask deny 'bash -c "$(printf %s Z2l0IHB1c2g= | base64 -D)"'
expect ask deny "python3 -c \"import os;os.system(bytes.fromhex('6769742070757368').decode())\""
# 復号だけ・eval だけ・python3 -c だけは allow のまま（平文の git push は上の 1a で ask を確かめている）
expect allow deny 'base64 -d payload.b64 > out.sh'
expect allow deny 'xxd -r payload.hex > out.bin'
expect allow deny 'python3 -c "print(1)"'
# shellcheck disable=SC2016  # eval だけ（復号なし）の確認。$(...) は文字列のまま渡す
expect allow deny 'eval "$(cat vars.sh)"'
# 1f-2. 広げた目印。シェルに渡す側（パス付きのシェル、env sh、$( )、` `、<( )、source、. file、xargs）と、
#       復号の側（base32、openssl -d、uudecode、8 進と \u と $'…' の逃げ文字）→ ask
expect ask deny 'echo Z2l0IHB1c2g= | base64 -d | /bin/sh'
expect ask deny 'echo Z2l0IHB1c2g= | base64 -d | env sh'
# shellcheck disable=SC2016  # $(...) と ` ` は判定本体に渡す文字列。わざと展開しない
expect ask deny '/bin/bash -c "$(echo Z2l0IHB1c2g= | base64 -d)"'
# shellcheck disable=SC2016  # 同上
expect ask deny '$(echo Z2l0IHB1c2g= | base64 -D)'
# shellcheck disable=SC2016  # 同上
expect ask deny 'echo "$(echo Z2l0IHB1c2g= | base64 -d)" | sh'
# shellcheck disable=SC2016  # 同上
expect ask deny '`echo Z2l0IHB1c2g= | base64 -d`'
expect ask deny 'bash <(echo Z2l0IHB1c2g= | base64 -d)'
expect ask deny 'base64 -d p.b64 > /tmp/r && source /tmp/r'
expect ask deny 'base64 -d p.b64 > /tmp/r; . /tmp/r'
expect ask deny 'echo Z2l0IHB1c2g= | base64 -d | xargs'
expect ask deny 'echo NRUXIIDQOVZWQ=== | base32 -d | sh'
expect ask deny 'echo U2FsdGVk | openssl enc -aes-256-cbc -d -k x | sh'
expect ask deny 'echo U2FsdGVk | openssl base64 -d | sh'
expect ask deny 'uudecode -p f.uu | sh'
expect ask deny "printf '\\147it push' | sh"
expect ask deny "printf '\\u0067it push' | sh"
expect ask deny "printf \$'\\147it push' | sh"
# 片方だけの日常の命令は allow のまま
# shellcheck disable=SC2016  # $(...) は文字列のまま渡す
expect allow deny 'echo "$(git status)"'
expect allow deny 'source ~/.zshrc'
expect allow deny '. ./env.sh'
expect allow deny 'git add . && git status'
expect allow deny 'find . -name "*.md" | xargs grep -l x'
expect allow deny '/bin/sh -c "ls -la"'
expect allow deny 'openssl rand -hex 16'
expect allow deny 'base32 -d x.b32 > out.bin'
expect allow deny 'uudecode -o out.bin in.uu'
expect allow deny "printf '\\u00e9\\n'"
expect allow deny "printf '\\033[1mx\\033[0m\\n'"
# shellcheck disable=SC2016  # $'\n' と $(...) は文字列のまま渡す
expect allow deny 'IFS=$'"'"'\n'"'"'; for f in $(ls); do echo $f; done'

# ---- 2. 接続口（端から端）
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
export CLAUDE_PROJECT_DIR="$T" CURSOR_PROJECT_DIR="$T"
export COMPANY_GUARD_VERIFY_CMD="false"
export COMPANY_GUARD_CURSOR_MODE=ask  # この Mac の ~/.cursor/company-guard.mode に左右されない。ファイルを読む道は 2d で HOME を差し替えて試す
export COMPANY_GUARD_MODE_FILE="$T/no-root/mode"  # この Mac の root の置き場（/usr/local/etc/company-guard）にも左右されない。置き場のある道は 2d-2 で差し替えて試す
OUT=""; RC=0
run() {  # run <接続口> <stdin の JSON> [引数...] → OUT と RC
  local script="$1" json="$2"; shift 2
  OUT="$(printf '%s' "$json" | bash "$HOOKS_DIR/$script" "$@" 2>"$T/err")"; RC=$?
}
has_out()   { printf '%s' "$OUT" | grep -Fq -- "$1"; }
lacks_out() { ! has_out "$1"; }
no_out()    { [ -z "$OUT" ]; }
is_json() { if command -v jq >/dev/null 2>&1; then printf '%s' "$OUT" | jq -e . >/dev/null 2>&1; else [ -n "$OUT" ]; fi; }
assert() {  # assert <説明> <条件のコマンド...>
  local desc="$1"; shift
  if "$@"; then ok; else bad "$desc (rc=$RC out=$(printf '%s' "$OUT" | head -c 160))"; fi
}
cj() { printf '{"session_id":"selftest-%s","cwd":"%s","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":%s}}' "$$" "$T" "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/^/"/' -e 's/$/"/')"; }

# 2a. Claude Code PreToolUse
run claude-pretooluse.sh "$(cj 'git commit -m x')"
assert "Claude PreToolUse: commit は ask" has_out '"permissionDecision":"ask"'
assert "Claude PreToolUse: 理由が付く" has_out 'permissionDecisionReason'
assert "Claude PreToolUse: 出力は JSON" is_json
run claude-pretooluse.sh "$(cj 'git status')"
assert "Claude PreToolUse: 読むだけは何も出さない" no_out
run claude-pretooluse.sh "$(cj 'APPROVE_GIT=1 git commit -m x')"
assert "Claude PreToolUse: 合図は deny" has_out '"permissionDecision":"deny"'
run claude-pretooluse.sh '{"tool_name":"Read","tool_input":{"file_path":"/x"}}'
assert "Claude PreToolUse: Bash 以外は何も出さない" no_out
mkdir -p "$T/.claude" && printf '{"hooks":{"PreToolUse":[{"hooks":[{"command":"hooks/claude-pretooluse.sh"}]}]}}' > "$T/.claude/settings.json"
run claude-pretooluse.sh "$(cj 'git commit -m x')" --global
assert "Claude PreToolUse --global: 判定は残す" has_out '"permissionDecision":"ask"'
assert "Claude PreToolUse --global: 理由は省く" lacks_out permissionDecisionReason
rm -rf "$T/.claude"

# 2a-2. Claude Code PreToolUse（Write・Edit の門）。HOME を一時の場所に差し替え、守りの設定の置き場も差し替えて試す
pj() { printf '{"session_id":"selftest-%s","cwd":"%s","hook_event_name":"PreToolUse","tool_name":"%s","tool_input":{"%s":"%s"}}' "$$" "$T" "$1" "${3:-file_path}" "$2"; }
MF="$T/etc/company-guard/mode"
mkdir -p "$T/.cursor" "$T/.claude/hooks" "$T/proj2"
edit() { HOME="$T" COMPANY_GUARD_MODE_FILE="$MF" run claude-preedit.sh "$(pj "$@")"; }
edit Write "$T/.cursor/company-guard.mode";        assert "preedit: ~/.cursor の mode のファイルは deny" has_out '"permissionDecision":"deny"'
assert "preedit: 理由が付く" has_out 'permissionDecisionReason'
assert "preedit: 出力は JSON" is_json
edit Edit "$T/.cursor/hooks.json";                  assert "preedit: ~/.cursor/hooks.json は deny" has_out '"permissionDecision":"deny"'
edit Write "$T/.claude/settings.json";              assert "preedit: ~/.claude/settings.json は deny" has_out '"permissionDecision":"deny"'
edit Write "$T/.claude/hooks/x.sh";                 assert "preedit: ~/.claude/hooks の下は deny" has_out '"permissionDecision":"deny"'
edit Write "$T/.claude/CLAUDE.md";                  assert "preedit: ~/.claude/CLAUDE.md（常時ルール）は deny" has_out '"permissionDecision":"deny"'
edit Write "$MF";                                   assert "preedit: root の置き場（まだ無くても）は deny" has_out '"permissionDecision":"deny"'
edit MultiEdit "$HOOKS_DIR/guard-core.sh";          assert "preedit: My-Lab の hooks/ は deny" has_out '"permissionDecision":"deny"'
edit Edit "$LAB_ROOT/.claude/settings.json";        assert "preedit: My-Lab の .claude/settings.json は deny" has_out '"permissionDecision":"deny"'
edit Edit "$LAB_ROOT/.cursor/hooks.json";           assert "preedit: My-Lab の .cursor/hooks.json は deny" has_out '"permissionDecision":"deny"'
edit NotebookEdit "$T/.cursor/x.ipynb" notebook_path; assert "preedit: NotebookEdit の notebook_path も見る" has_out '"permissionDecision":"deny"'
ln -s "$T/.cursor/company-guard.mode" "$T/proj2/link"
edit Write "$T/proj2/link";                         assert "preedit: mode のファイルを指すリンク（先がまだ無い）は deny" has_out '"permissionDecision":"deny"'
edit Write "$T/proj2/../.cursor/company-guard.mode"; assert "preedit: .. で隠したパスは deny" has_out '"permissionDecision":"deny"'
edit Write ".cursor/company-guard.mode";            assert "preedit: 相対パス（cwd が HOME）は deny" has_out '"permissionDecision":"deny"'
edit Write "$T/.CURSOR/company-guard.mode";         assert "preedit: 大文字小文字を変えたパス（APFS）は deny" has_out '"permissionDecision":"deny"'
edit Write "$T/proj2/README.md";                    assert "preedit: ふつうのファイルは何も出さない" no_out
edit Write "$LAB_ROOT/tmp/flow/x/design.md";        assert "preedit: My-Lab の tmp/flow は何も出さない" no_out
edit Edit "$LAB_ROOT/README.md";                    assert "preedit: My-Lab の README は何も出さない" no_out
edit Write "$T/.claude/agents/x.md";                assert "preedit: ~/.claude の下でも hooks と settings 以外は何も出さない" no_out
edit Write "$T/proj2/.cursor/hooks.json";           assert "preedit: 他のプロジェクトの .cursor/hooks.json は何も出さない" no_out
HOME="$T" run claude-preedit.sh '{"tool_name":"Read","tool_input":{"file_path":"'"$T"'/.cursor/company-guard.mode"}}'
assert "preedit: Read は何も出さない" no_out
printf '{"hooks":{"PreToolUse":[{"hooks":[{"command":"hooks/claude-preedit.sh"}]}]}}' > "$T/.claude/settings.json"
HOME="$T" run claude-preedit.sh "$(pj Write "$T/.cursor/company-guard.mode")" --global
assert "preedit --global: 判定は残す" has_out '"permissionDecision":"deny"'
assert "preedit --global: 理由は省く" lacks_out permissionDecisionReason
rm -rf "$T/.claude" "$T/.cursor" "$T/proj2"

# 2b. Claude Code Stop
SJ='{"session_id":"selftest-'"$$"'","cwd":"'"$T"'","hook_event_name":"Stop","stop_hook_active":false}'
COMPANY_GUARD_VERIFY_CMD=false run claude-stop.sh "$SJ"
assert "Claude Stop: 検証が FAIL なら block" has_out '"decision":"block"'
assert "Claude Stop: 出力は JSON" is_json
COMPANY_GUARD_VERIFY_CMD=true run claude-stop.sh "$SJ"
assert "Claude Stop: 検証が PASS なら何も出さない" no_out
SJA='{"session_id":"selftest-'"$$"'","cwd":"'"$T"'","hook_event_name":"Stop","stop_hook_active":true}'
COMPANY_GUARD_VERIFY_CMD=false run claude-stop.sh "$SJA"; COMPANY_GUARD_VERIFY_CMD=false run claude-stop.sh "$SJA"; COMPANY_GUARD_VERIFY_CMD=false run claude-stop.sh "$SJA"
assert "Claude Stop: 続きの指示は 3 回目まで block" has_out '"decision":"block"'
COMPANY_GUARD_VERIFY_CMD=false run claude-stop.sh "$SJA"
assert "Claude Stop: 4 回目は上限で止める" no_out
rm -f "$LAB_ROOT/tmp/.verify/stop-count-selftest-$$"

# 2c. Claude Code PostToolUse
run claude-postedit.sh '{"tool_name":"Write","tool_input":{"file_path":"/nonexistent/x.md"}}'
assert "Claude PostToolUse: 無いファイルは何もしない" [ "$RC" -eq 0 ]
if [ -f "$LAB_ROOT/tools/check-file.sh" ]; then
  mkdir -p "$LAB_ROOT/tmp/.verify"
  BAD="$LAB_ROOT/tmp/.verify/selftest-bad.md"
  printf '# 題\n\nこの文は要件を実現することができます。\n' > "$BAD"
  CLAUDE_PROJECT_DIR="$LAB_ROOT" run claude-postedit.sh "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$BAD\"}}"
  assert "Claude PostToolUse: 禁則語のある md は終了コード 2" [ "$RC" -eq 2 ]
  rm -f "$BAD"
fi

# 2d. Cursor beforeShellExecution
run cursor-before-shell.sh '{"command":"git commit -m x","cwd":"'"$T"'"}'
assert "Cursor before-shell: commit は ask" has_out '"permission":"ask"'
assert "Cursor before-shell: user_message が付く" has_out 'user_message'
assert "Cursor before-shell: 出力は JSON" is_json
run cursor-before-shell.sh '{"command":"git status","cwd":"'"$T"'"}'
assert "Cursor before-shell: 読むだけは allow" has_out '"permission":"allow"'
run cursor-before-shell.sh '{"command":"APPROVE_GIT=1 git commit -m x","cwd":"'"$T"'"}'
assert "Cursor before-shell(ask の設定): 合図は deny" has_out '"permission":"deny"'
COMPANY_GUARD_CURSOR_MODE=deny run cursor-before-shell.sh '{"command":"git commit -m x","cwd":"'"$T"'"}'
assert "Cursor before-shell(deny の設定): commit は deny" has_out '"permission":"deny"'
assert "Cursor before-shell(deny の設定): 合図の語を文に出さない" lacks_out 'APPROVE_GIT'
COMPANY_GUARD_CURSOR_MODE=deny run cursor-before-shell.sh '{"command":"APPROVE_GIT=1 git commit -m x","cwd":"'"$T"'"}'
assert "Cursor before-shell(deny の設定): 先頭に合図があっても commit は deny" has_out '"permission":"deny"'
COMPANY_GUARD_CURSOR_MODE=deny run cursor-before-shell.sh '{"command":"APPROVE_GIT=1 git push origin main","cwd":"'"$T"'"}'
assert "Cursor before-shell(deny の設定): 先頭に合図があっても push は deny" has_out '"permission":"deny"'
COMPANY_GUARD_CURSOR_MODE=deny run cursor-before-shell.sh '{"command":"git status","cwd":"'"$T"'"}'
assert "Cursor before-shell(deny の設定): 読むだけは allow" has_out '"permission":"allow"'
# mode のファイルへの書き込みは、設定が ask でも deny でも deny（判定本体が deny を返すため）
COMPANY_GUARD_CURSOR_MODE=ask  run cursor-before-shell.sh '{"command":"printf ask > ~/.cursor/company-guard.mode","cwd":"'"$T"'"}'
assert "Cursor before-shell(ask の設定): mode のファイルへの書き込みは deny" has_out '"permission":"deny"'
COMPANY_GUARD_CURSOR_MODE=deny run cursor-before-shell.sh '{"command":"rm ~/.cursor/company-guard.mode","cwd":"'"$T"'"}'
assert "Cursor before-shell(deny の設定): mode のファイルの削除は deny" has_out '"permission":"deny"'
COMPANY_GUARD_CURSOR_MODE=ask  run cursor-before-shell.sh '{"command":"cat ~/.cursor/company-guard.mode","cwd":"'"$T"'"}'
assert "Cursor before-shell(ask の設定): mode のファイルの読みは allow" has_out '"permission":"allow"'
mkdir -p "$T/.cursor"
COMPANY_GUARD_CURSOR_MODE='' HOME="$T" run cursor-before-shell.sh '{"command":"git commit -m x","cwd":"'"$T"'"}'
assert "Cursor before-shell(mode のファイルが無い): 既定の ask" has_out '"permission":"ask"'
printf 'deny\n' > "$T/.cursor/company-guard.mode"
COMPANY_GUARD_CURSOR_MODE='' HOME="$T" run cursor-before-shell.sh '{"command":"git commit -m x","cwd":"'"$T"'"}'
assert "Cursor before-shell(mode のファイルが deny): commit は deny" has_out '"permission":"deny"'
COMPANY_GUARD_CURSOR_MODE='' HOME="$T" run cursor-before-shell.sh '{"command":"APPROVE_GIT=1 git commit -m x","cwd":"'"$T"'"}'
assert "Cursor before-shell(mode のファイルが deny): 先頭に合図があっても deny" has_out '"permission":"deny"'
# 2d-2. root 所有の置き場（COMPANY_GUARD_MODE_FILE で差し替え）。あればそれだけを使い、壊れていれば deny に倒す（fail-closed）
MF="$T/etc/company-guard/mode"; MD="$T/etc/company-guard"
cmt() { COMPANY_GUARD_CURSOR_MODE='' HOME="$T" COMPANY_GUARD_MODE_FILE="$MF" run cursor-before-shell.sh '{"command":"git commit -m x","cwd":"'"$T"'"}'; }
lock()   { chmod 444 "$MF" 2>/dev/null; chmod 555 "$MD"; }   # root 所有と同じく、自分の権限では書けない形にする
unlock() { chmod 755 "$MD"; chmod 644 "$MF" 2>/dev/null; }
printf 'ask\n' > "$T/.cursor/company-guard.mode"            # 互換の側は ask と言わせておく
mkdir -p "$MD"
cmt; assert "Cursor(root の置き場: フォルダだけでファイルが無い): deny に倒す" has_out '"permission":"deny"'
assert "Cursor(root の置き場: ファイルが無い): 理由を言う" has_out 'ファイルが無い'
printf 'ask\n' > "$MF"
cmt; assert "Cursor(root の置き場: 自分の権限で書ける): deny に倒す" has_out '"permission":"deny"'
assert "Cursor(root の置き場: 自分の権限で書ける): 理由を言う" has_out '自分の権限で書ける'
lock
cmt; assert "Cursor(root の置き場: ask で書けない): ask。互換の側は読まない" has_out '"permission":"ask"'
unlock; printf 'deny\n' > "$MF"; printf 'ask\n' > "$T/.cursor/company-guard.mode"; lock
cmt; assert "Cursor(root の置き場: deny): 互換の側が ask でも deny" has_out '"permission":"deny"'
assert "Cursor(root の置き場: deny): 壊れた理由は付かない" lacks_out 'に倒す'
COMPANY_GUARD_CURSOR_MODE='' HOME="$T" COMPANY_GUARD_MODE_FILE="$MF" run cursor-before-shell.sh '{"command":"git status","cwd":"'"$T"'"}'
assert "Cursor(root の置き場: deny): 読むだけは allow のまま" has_out '"permission":"allow"'
unlock; printf 'maybe\n' > "$MF"; lock
cmt; assert "Cursor(root の置き場: 中身が deny でも ask でもない): deny に倒す" has_out '"permission":"deny"'
unlock; printf 'ask\n' > "$MF"; chmod 000 "$MF"; chmod 555 "$MD"
cmt; assert "Cursor(root の置き場: 読めない): deny に倒す" has_out '"permission":"deny"'
unlock; rm -f "$MF"; ln -s "$T/.cursor/company-guard.mode" "$MF"; chmod 555 "$MD"
cmt; assert "Cursor(root の置き場: リンク): deny に倒す" has_out '"permission":"deny"'
unlock; rm -rf "${T:?}/etc"
printf 'deny\n' > "$T/.cursor/company-guard.mode"
cmt; assert "Cursor(root の置き場が無い): 互換の ~/.cursor（deny）を読む" has_out '"permission":"deny"'
rm -rf "$T/.cursor"
run cursor-before-shell.sh '{"cwd":"'"$T"'"}'
assert "Cursor before-shell: command が無ければ allow の JSON" has_out '"permission":"allow"'
mkdir -p "$T/.cursor" && printf '{"version":1,"hooks":{"beforeShellExecution":[{"command":"hooks/cursor-before-shell.sh"}]}}' > "$T/.cursor/hooks.json"
run cursor-before-shell.sh '{"command":"git push","cwd":"'"$T"'"}' --global
assert "Cursor before-shell --global: 判定だけ返す" [ "$OUT" = '{"permission":"ask"}' ]
rm -rf "$T/.cursor"

# 2e. Cursor stop
run cursor-stop.sh '{"status":"aborted","loop_count":0}'
assert "Cursor stop: 中断なら {}" [ "$OUT" = '{}' ]
run cursor-stop.sh '{"status":"completed","loop_count":3}'
assert "Cursor stop: 上限なら {}" [ "$OUT" = '{}' ]
COMPANY_GUARD_VERIFY_CMD=false run cursor-stop.sh '{"status":"completed","loop_count":0}'
assert "Cursor stop: 検証が FAIL なら followup_message" has_out 'followup_message'
assert "Cursor stop: 出力は JSON" is_json
COMPANY_GUARD_VERIFY_CMD=true run cursor-stop.sh '{"status":"completed","loop_count":0}'
assert "Cursor stop: 検証が PASS なら {}" [ "$OUT" = '{}' ]

# 2f. Cursor afterFileEdit
run cursor-after-edit.sh '{"file_path":"/nonexistent/x.md","edits":[]}'
assert "Cursor after-edit: 無いファイルでも終了コード 0" [ "$RC" -eq 0 ]

# 2g. Stop の両接続口: 検証が通ったあと、ファイルを消すだけ・名前を変えるだけでも、次の Stop は検証を回す
# 印（last-pass）より新しいファイルは 1 本も無い場面なので、一覧（last-pass.list）の比較だけが変更を見つける
P="$T/proj"; mkdir -p "$P/src" "$P/tmp/.verify"
printf 'a\n' > "$P/src/a.txt"; printf 'b\n' > "$P/src/b.txt"; printf 'd\n' > "$P/src/d.txt"
touch -t 202001010000 "$P/src/a.txt" "$P/src/b.txt" "$P/src/d.txt"   # 印より確かに古い時刻にする
SJP='{"session_id":"selftest-'"$$"'","cwd":"'"$P"'","hook_event_name":"Stop","stop_hook_active":false}'
CJP='{"status":"completed","loop_count":0,"cwd":"'"$P"'"}'
# pass_stop: 検証の命令が印を書く（verify-all.sh と project-verify.sh が PASS で touch するのと同じ）。通った直後に接続口が一覧を書く
pass_stop() { CLAUDE_PROJECT_DIR="$P" CURSOR_PROJECT_DIR="$P" COMPANY_GUARD_VERIFY_CMD='touch tmp/.verify/last-pass' run "$@"; }
fail_stop() { CLAUDE_PROJECT_DIR="$P" CURSOR_PROJECT_DIR="$P" COMPANY_GUARD_VERIFY_CMD=false run "$@"; }
absent_line() { ! grep -qx -- "$1" "$2"; }   # absent_line <行> <ファイル> → その行が無ければ 0
pass_stop claude-stop.sh "$SJP"
assert "Claude Stop: 検証が通ると一覧 last-pass.list を書く" [ -f "$P/tmp/.verify/last-pass.list" ]
assert "Claude Stop: 一覧には印より古いファイルも載る" grep -qx './src/a.txt' "$P/tmp/.verify/last-pass.list"
assert "Claude Stop: 一覧に tmp/.verify の中は載らない" absent_line './tmp/.verify/last-pass' "$P/tmp/.verify/last-pass.list"
fail_stop claude-stop.sh "$SJP"
assert "Claude Stop: 何も変えていなければ検証を回さない" no_out
rm -f "$P/src/a.txt"
fail_stop claude-stop.sh "$SJP"
assert "Claude Stop: ファイルを消すだけでも検証を回す（FAIL なら block）" has_out '"decision":"block"'
pass_stop claude-stop.sh "$SJP"
mv "$P/src/b.txt" "$P/src/c.txt"
fail_stop claude-stop.sh "$SJP"
assert "Claude Stop: 名前を変えるだけでも検証を回す" has_out '"decision":"block"'
pass_stop claude-stop.sh "$SJP"
fail_stop claude-stop.sh "$SJP"
assert "Claude Stop: 一覧を書き直したあと、何も変えなければ回さない" no_out
rm -f "$P/tmp/.verify/last-pass.list"
fail_stop claude-stop.sh "$SJP"
assert "Claude Stop: 一覧が無ければ検証を回す（分からないときは回す）" has_out '"decision":"block"'
pass_stop cursor-stop.sh "$CJP"
assert "Cursor stop: 検証が通ると一覧 last-pass.list を書く" [ -f "$P/tmp/.verify/last-pass.list" ]
fail_stop cursor-stop.sh "$CJP"
assert "Cursor stop: 何も変えていなければ {}" [ "$OUT" = '{}' ]
rm -f "$P/src/c.txt"
fail_stop cursor-stop.sh "$CJP"
assert "Cursor stop: ファイルを消すだけでも followup_message" has_out 'followup_message'
pass_stop cursor-stop.sh "$CJP"
mv "$P/src/d.txt" "$P/src/e.txt"
fail_stop cursor-stop.sh "$CJP"
assert "Cursor stop: 名前を変えるだけでも followup_message" has_out 'followup_message'
rm -f "$LAB_ROOT/tmp/.verify/stop-count-selftest-$$"

if [ "$fail" -eq 0 ]; then verdict=PASS; else verdict=FAIL; fi
printf 'RESULT: %s hooks の自己試験 %d PASS / %d FAIL\n' "$verdict" "$pass" "$fail"
[ "$fail" -eq 0 ]
