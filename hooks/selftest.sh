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
# 1d. 合図の語。Claude Code（deny）では常に deny。Cursor の退避路（honor）では先頭だけ allow
expect deny deny 'APPROVE_GIT=1 git commit -m x'
expect deny deny 'git commit -m x # APPROVE_GIT=1'
expect deny deny 'export APPROVE_GIT=1; git push'
expect allow honor 'APPROVE_GIT=1 git commit -m x'
expect allow honor 'APPROVE_GIT=1 git push'
expect allow honor '  APPROVE_GIT=1 git push'
expect deny honor 'git status && APPROVE_GIT=1 git push'
expect deny honor 'echo APPROVE_GIT=1'
expect ask honor 'git commit -m x'
expect allow honor 'git status'

# ---- 2. 接続口（端から端）
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
export CLAUDE_PROJECT_DIR="$T" CURSOR_PROJECT_DIR="$T"
export COMPANY_GUARD_VERIFY_CMD="false"
unset COMPANY_GUARD_CURSOR_MODE
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
COMPANY_GUARD_CURSOR_MODE=deny run cursor-before-shell.sh '{"command":"APPROVE_GIT=1 git commit -m x","cwd":"'"$T"'"}'
assert "Cursor before-shell(deny の設定): 先頭の合図は allow" has_out '"permission":"allow"'
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

if [ "$fail" -eq 0 ]; then verdict=PASS; else verdict=FAIL; fi
printf 'RESULT: %s hooks の自己試験 %d PASS / %d FAIL\n' "$verdict" "$pass" "$fail"
[ "$fail" -eq 0 ]
