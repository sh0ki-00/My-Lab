#!/usr/bin/env bash
# hooks/selftest.sh — hooks の自己試験。
# 1) 判定本体に、承認が要る操作・取り消せない操作・読むだけの操作・合図の語を流し、判定表どおりかを見る。
#    commit 文・PR 文・Issue 文の現場の語の言い換え（改善提案書の W-4）と、クラウドにつなぐコマンド（S-7）も見る。
# 2) hooks に両ツールの形の JSON を流し、端から端で正しい形の出力が出るかを見る。
#    返答の言い換えの差し戻し（W-3）と、終わりの検証をそのセッションの文書だけにすること（V-1〜V-3 の hooks の側）も見る。
# 使い方: bash hooks/selftest.sh   → 1 件でも落ちれば終了コード 1。C と ja_JP.UTF-8 の 2 つの文字の設定で回す（tools/verify-all.sh の 6）
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
# expect_at <root> <期待> <コマンド> → プロジェクトの root を渡して判定を見る。My-Lab の中の相対パス（hooks/ ほか）の判定は root で変わる
expect_at() {
  local root="$1" want="$2" cmd="$3" got
  got="$(COMPANY_GUARD_PROJECT_ROOT="$root" bash "$CORE" -- "$cmd" | cut -f1)"
  if [ "$got" = "$want" ]; then ok; else bad "判定(root=$root): 期待 $want / 実際 $got : $cmd"; fi
}
# expect_fake_lab <期待> <コマンド> → My-Lab が家の下（~/my-lab-selftest）にあるものとして判定を見る。~ と $HOME からの書き方を試すため
expect_fake_lab() {
  local want="$1" cmd="$2" got
  got="$(LAB_ROOT="$HOME/my-lab-selftest" COMPANY_GUARD_PROJECT_ROOT="$HOME/my-lab-selftest" bash "$CORE" -- "$cmd" | cut -f1)"
  if [ "$got" = "$want" ]; then ok; else bad "判定(家の下の My-Lab): 期待 $want / 実際 $got : $cmd"; fi
}
export COMPANY_GUARD_PROJECT_ROOT="$LAB_ROOT"   # 1 の判定は My-Lab の中で動いているものとして見る（hooks は自分の root で上書きする）

# ---- 1. 判定表
# 1a. 承認 2（外に出る操作）→ ask
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
# 1e-3. 大文字小文字（APFS では RM も /bin/rm、~/.Cursor も同じ場所）とグロブ（* ? [ {）で崩した書き方 → deny。読みと他の名前の下は allow
expect deny deny 'RM ~/.cursor/company-guard.mode'
expect deny deny 'rm ~/.Cursor/company-guard.mode'
expect deny deny 'Rm -rf /Users/s-furutani/.CURSOR'
expect deny deny 'rm ~/.c*/company-g*'
expect deny deny 'rm -rf ~/.[c]ursor/hooks.js*n'
expect deny deny 'rm ~/.?ursor/company-g*'
expect deny deny 'rm -rf ~/{.cursor,.claude}/hooks.js*n'
expect deny deny 'cp /tmp/x /Users/*/.c*/hooks.json'
expect deny deny 'rm -rf /U*/s-furutani/.cursor/hooks.json'
# shellcheck disable=SC2016  # $HOME は判定本体に渡す文字列。わざと展開しない
expect deny deny 'mv $HOME/.c*/hooks.json /tmp/'
expect deny deny 'rm ~/.claude/sett*'
expect deny deny 'rm -rf ~/.claude/h*/'
expect deny deny 'chmod -R a+w ~/.[c]laude'
expect deny deny 'printf ask > ~/.c*/company-g*'
expect deny deny 'rm -rf /usr/local/etc/company-g*'
expect deny deny 'echo ask > /usr/local/etc/comp*/mode'
expect allow deny 'ls ~/.c*/'
expect allow deny 'cat ~/.c*/company-guard.mode'
expect allow deny 'ls /usr/local/etc/*'
expect allow deny 'rm -rf ~/.cache/*'
expect allow deny 'rm -rf ~/Downloads/*.tmp'
expect allow deny 'chmod 600 ~/.ssh/*'
expect allow deny 'rm ~/*.log'
expect allow deny 'rm -rf tmp/.verify/*'
expect allow deny 'cp tmp/flow/*/design.md /tmp/'

# 1g. hooks の登録と本体への Bash の書き込み・削除・移動・権限の変更 → deny（Write・Edit の門と同じ場所）。読みと検査は allow
#     1 の判定は My-Lab の中（COMPANY_GUARD_PROJECT_ROOT=LAB_ROOT）として見るので、hooks/ の相対パスも対象
expect deny deny 'cp x hooks/guard-core.sh'
expect deny deny 'cp x ./hooks/guard-core.sh'
expect deny deny 'cp x ../hooks/guard-core.sh'
expect deny deny 'cp x tmp/../hooks/guard-core.sh'
expect deny deny "cp x $LAB_ROOT/hooks/guard-core.sh"
expect deny deny "cp x $(printf '%s' "$LAB_ROOT/hooks/guard-core.sh" | tr '[:lower:]' '[:upper:]')"
expect deny deny 'cp -r /tmp/hooks-new/ hooks/'
expect deny deny 'cp x hooks/lib.sh && echo done'
expect deny deny 'echo x > hooks/lib.sh'
expect deny deny 'echo x >> hooks/lib.sh'
expect deny deny 'echo x >| hooks/lib.sh'
expect deny deny 'echo x &> hooks/lib.sh'
expect deny deny 'echo x >hooks/lib.sh'
expect deny deny 'cat /tmp/x | tee hooks/lib.sh'
expect deny deny 'tee -a hooks/lib.sh < /tmp/x'
expect deny deny 'mv hooks/lib.sh /tmp/'
expect deny deny 'mv hooks/a.sh hooks/b.sh'
expect deny deny 'mv hooks hooks2'
expect deny deny 'rm hooks/claude-preedit.sh'
expect deny deny 'rm -rf hooks'
expect deny deny 'RM -RF HOOKS'
expect deny deny '/bin/rm hooks/lib.sh'
expect deny deny 'true;rm hooks/lib.sh'
expect deny deny 'true && rm -f hooks/lib.sh'
expect deny deny '(rm hooks/lib.sh)'
expect deny deny 'ln hooks/guard-core.sh /tmp/x'
expect deny deny 'ln ~/.claude/settings.json /tmp/x'
expect deny deny 'ln -s ~/.claude/settings.json /tmp/x'
expect deny deny 'sed -i "" s/a/b/ hooks/lib.sh'
expect deny deny 'sed -i.bak s/a/b/ ~/.claude/settings.json'
expect deny deny 'sed -E -i s/a/b/ hooks/lib.sh'
expect deny deny 'sed s/a/b/ -i hooks/lib.sh'
expect deny deny 'perl -pi -e s/a/b/ hooks/lib.sh'
expect deny deny 'install -m 755 x hooks/x.sh'
expect deny deny 'dd if=/dev/zero of=hooks/lib.sh'
expect deny deny 'chmod 777 hooks/lib.sh'
expect deny deny 'chmod +x hooks/*.sh'
expect deny deny 'chmod -R a+w hooks'
expect deny deny 'chflags uchg hooks/lib.sh'
expect deny deny 'truncate -s 0 hooks/lib.sh'
expect deny deny 'patch hooks/lib.sh < /tmp/d'
expect deny deny 'echo {} > ~/.claude/settings.json'
expect deny deny 'echo x >> ~/.claude/CLAUDE.md'
expect deny deny 'echo x >> ~/.claude/claude.md'
expect deny deny 'cp x ~/.claude/hooks/y.sh'
expect deny deny 'rm -rf ~/.claude/hooks'
expect deny deny 'rm /Users/s-furutani/.claude/settings.json'
# shellcheck disable=SC2016  # $HOME と ${HOME} は判定本体に渡す文字列。わざと展開しない
expect deny deny 'cp x $HOME/.claude/CLAUDE.md'
# shellcheck disable=SC2016  # 同上
expect deny deny 'cp x ${HOME}/.claude/settings.json'
expect deny deny 'cp /tmp/s.json .claude/settings.json'
expect deny deny 'cp /tmp/h.json .cursor/hooks.json'
expect deny deny 'mv /tmp/h.json .cursor/hooks.json'
expect deny deny 'python3 -c "open(\"hooks/lib.sh\",\"w\").write(\"x\")"'
expect deny deny 'python3 -c "import os; open(\"hooks/lib.sh\",\"w\")"'
expect deny deny 'perl -e "open(F,\">hooks/lib.sh\")"'
expect deny deny 'node -e "require(\"fs\").writeFileSync(\"hooks/lib.sh\",\"x\")"'
expect deny deny 'git checkout main -- hooks/guard-core.sh'
expect deny deny 'git restore hooks/lib.sh'
# shellcheck disable=SC2016  # $f と $F は判定本体に渡す文字列。わざと展開しない
expect deny deny 'f=hooks/lib.sh; echo x > $f'
# shellcheck disable=SC2016  # 同上
expect deny deny 'f=~/.claude/settings.json; cp /tmp/x $f'
# shellcheck disable=SC2016  # 同上
expect deny deny "F=$LAB_ROOT/hooks/lib.sh; rm \$F"
# 家の下にある My-Lab（~/my-lab-selftest と見立てる）への、~ と $HOME からの書き方
expect_fake_lab deny 'cp x ~/my-lab-selftest/hooks/x.sh'
# shellcheck disable=SC2016  # $HOME は判定本体に渡す文字列。わざと展開しない
expect_fake_lab deny 'cp x $HOME/my-lab-selftest/hooks/x.sh'
expect_fake_lab deny 'cp x ~/My-Lab-Selftest/.claude/settings.json'
expect_fake_lab deny 'cp x hooks/x.sh'
expect_fake_lab allow 'cat ~/my-lab-selftest/hooks/x.sh'
# 読みと検査、写す元が hooks/、他の場所への書き込みは allow のまま
expect allow deny 'cat ~/.claude/settings.json'
expect allow deny 'git diff hooks/'
expect allow deny 'git diff -U3 -- hooks'
expect allow deny 'git log --oneline -- hooks/'
expect allow deny 'git add hooks/lib.sh'
expect allow deny 'ls ~/.claude/hooks'
expect allow deny 'ls -la ~/.claude/'
expect allow deny 'cp .cursor/hooks.json /tmp/'
expect allow deny 'cp .claude/settings.json /tmp/'
expect allow deny 'cp hooks/lib.sh /tmp/lib.sh'
expect allow deny 'cp -r hooks /tmp/hooks-backup'
expect allow deny 'cp -r hooks/ tmp/hooks-copy/'
expect allow deny 'echo x > tmp/hooks.log'
expect allow deny 'rm -f tmp/.verify/hooks.log'
expect allow deny 'rm -rf tmp/hooks'
expect allow deny 'ln -s ../skills .cursor/skills'
expect allow deny 'sed -n "/^if/p" hooks/lib.sh'
expect allow deny 'sed -E "s/(x)/\1/" hooks/lib.sh'
expect allow deny 'LC_ALL=C bash hooks/selftest.sh > tmp/out.txt 2>&1'
expect allow deny 'shellcheck -x -P . hooks/*.sh'
expect allow deny 'python3 -I tools/lib/check_var_brace.py hooks/*.sh'
expect allow deny 'bash tools/check-file.sh hooks/lib.sh'
expect allow deny 'grep -rn hooks docs/'
expect allow deny 'diff hooks/lib.sh /tmp/lib.sh'
expect allow deny 'wc -l hooks/*.sh'
expect allow deny 'jq . .claude/settings.json'
expect allow deny 'cat .cursor/hooks.json'
expect allow deny 'tar czf /tmp/h.tgz hooks'
expect allow deny 'rm -rf tmp/.verify && bash hooks/selftest.sh'
expect allow deny 'mkdir -p tmp/.verify; rm -f tmp/.verify/hooks.log; bash hooks/selftest.sh'
expect allow deny 'chmod +x .git/hooks/pre-commit'
expect allow deny 'chmod +x .husky/pre-commit'
expect allow deny 'git checkout -b fix/hooks-x'
# shellcheck disable=SC2016  # $OUT は判定本体に渡す文字列。わざと展開しない
expect allow deny 'cat hooks/lib.sh > $OUT'
# 他のプロジェクト（root が My-Lab の外）では、hooks/ と .claude/settings.json の相対パスは見ない。家と My-Lab の絶対パスは見る
expect_at / allow 'cp x hooks/guard-core.sh'
expect_at / allow 'mv hooks/useFoo.ts hooks/useBar.ts'
expect_at / allow 'rm -rf hooks'
expect_at / allow 'cp /tmp/s.json .claude/settings.json'
expect_at / deny "cp x $LAB_ROOT/hooks/guard-core.sh"
expect_at / deny 'echo {} > ~/.claude/settings.json'
expect_at / deny 'rm -rf ~/.claude/hooks'

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

# 1h. commit 文・PR 文・Issue 文の現場の語の言い換え（W-4）→ deny。3a の ask より先に返す。鉤括弧の中と、語の無い文は今までどおり ask
#     言い換えの語（git のブランチを指す漢字 1 字）は、hooks/ の中に字面で残さないため、UTF-8 の 3 バイト（E6 9E 9D）から作る
TW="$(printf '\346\236\235')"
expect deny deny "git commit -m \"作業用の${TW}を直す\""
expect deny deny "git commit --message=\"${TW}分かれを取り込む\""
expect deny deny "git -C /tmp/x commit -m \"作業用の${TW}を消す\""
expect deny deny "gh pr create --title \"${TW}の整理\" --body ok"
expect deny deny "gh pr review 12 --comment -b \"この${TW}は古い\""
expect deny deny "gh issue comment 3 --body \"作業用の${TW}で直しました\""
expect deny honor "git commit -m \"作業用の${TW}を直す\""
expect deny deny "git commit -m \"作業用の${TW}\" && aws s3 ls"
expect ask deny "git commit -m \"「${TW}」を「ブランチ」に直す\""
expect ask deny 'git commit -m "作業用のブランチで直す"'
expect ask deny 'gh issue create --title "ログイン画面の修正" --body "ブランチ fix/login で直す"'
expect ask deny 'gh pr create --fill'
expect allow deny "echo ${TW}分かれ"
expect allow deny 'gh pr view 12'
# マージの commit 文、タグの文、gh pr merge の題と本文、gh api で送る本文も見る
expect deny deny "git merge -m \"作業用の${TW}を取り込む\" feature"
expect deny deny "git merge --no-ff feature --message=\"作業用の${TW}\""
expect deny deny "git tag -a v1 -m \"作業用の${TW}を消す\""
expect deny deny "gh pr merge 12 --squash --subject \"作業用の${TW}\""
expect deny deny "gh pr merge 12 --squash -b \"作業用の${TW}を消す\""
expect deny deny "gh api repos/o/r/issues -f body=作業用の${TW}"
expect deny deny "gh release create v1 --notes \"作業用の${TW}\""
expect allow deny 'git merge feature'
expect allow deny 'git tag'
# 返答と命令の文では、ja-ok の印と、閉じない「やバッククォートで語を隠せない
expect deny deny "git commit -m \"作業用の${TW}を直す <!-- ja-ok -->\""
expect deny deny "git commit -m \"\`x 作業用の${TW}\""
expect deny deny "git commit -m \"「x 作業用の${TW}\""
# 履歴が分かれる様子の語は「分岐」に直させる
got="$(bash "$CORE" -- "git commit -m \"main から履歴が${TW}分かれした\"")"
case "$got" in deny*「分岐」に直して*) ok ;; *) bad "判定: 履歴の分かれる様子の語を「分岐」に直させない: ${got}" ;; esac

# 1i. クラウドにつなぐコマンド（S-7）→ 設定によらず ask。読むだけのコマンドも含む。terraform と tofu は fmt・validate と help・version だけ通す
expect ask deny 'aws s3 ls'
expect ask deny 'terraform apply'
expect allow deny 'terraform fmt -check'
expect ask deny 'kubectl get pods'
expect ask honor 'aws s3 ls'
expect ask deny 'AWS s3 ls'
expect ask deny 'Terraform apply'
expect allow deny 'TERRAFORM fmt -check'
expect ask deny 'git push origin main && terraform apply'
expect ask deny 'AWS_PROFILE=dev aws sts get-caller-identity'
expect ask deny 'sh -c "aws s3 ls"'
expect ask deny '/usr/local/bin/aws s3 ls'
expect ask deny 'echo ok | xargs aws s3 ls'
expect ask deny 'cd infra && terraform plan'
expect ask deny 'terraform fmt && terraform apply'
expect ask deny 'terraform -chdir=infra plan'
expect ask deny 'terraform init'
expect ask deny 'tofu init'
expect allow deny 'terraform -chdir=infra fmt -check'
expect allow deny 'terraform validate'
expect allow deny 'tofu version'
expect allow deny 'terraform -help'
expect allow deny 'terraform --help'
# 1i の続き: 命令の置き換えと改行の中の命令も、別の命令として見る。副命令の前に値を別の語で取るオプションがあれば通さない
# shellcheck disable=SC2016  # $( ) と ` は判定に渡す字面。展開しない
expect ask deny 'terraform fmt $(terraform apply -auto-approve)'
# shellcheck disable=SC2016  # $( ) と ` は判定に渡す字面。展開しない
expect ask deny 'terraform fmt `terraform apply -auto-approve`'
expect ask deny $'terraform fmt\nterraform apply'
expect ask deny 'terraform fmt <(terraform plan)'
expect ask deny 'terraform fmt terraform apply'
expect ask deny 'cdk --app init deploy'
expect ask deny 'sam --region local deploy'
expect allow deny 'terraform fmt -recursive modules'
expect allow deny 'terraform -chdir=infra validate'
expect ask deny 'sam deploy --guided'
expect ask deny 'sam logs -n fn'
expect allow deny 'sam build'
expect allow deny 'sam local invoke'
expect ask deny 'npx cdk deploy'
expect ask deny 'npx aws-cdk@2 destroy'
expect ask deny './node_modules/.bin/cdk diff'
expect ask deny 'cdk bootstrap'
expect ask deny 'pulumi preview'
expect ask deny 'helm list'
expect ask deny 'eksctl get cluster'
expect ask deny 'gcloud config list'
expect ask deny 'gsutil ls'
expect ask deny 'bq ls'
expect ask deny 'az account show'
expect ask deny 'doctl account get'
# 呼び方を変えた形: パスの最後の名前、$( ) と ` ` の中の which、python -m、docker run の像（版つきも）
expect ask deny '/usr/local/aws-cli/aws s3 ls'
# shellcheck disable=SC2016  # $(...) と ` ` は判定本体に渡す文字列。わざと展開しない
expect ask deny '$(which aws) s3 ls'
# shellcheck disable=SC2016  # 同上
expect ask deny '`which aws` s3 ls'
expect ask deny 'python3 -m awscli s3 ls'
expect ask deny 'docker run --rm -v ~/.aws:/root/.aws amazon/aws-cli s3 ls'
# shellcheck disable=SC2016  # $PWD は判定本体に渡す文字列。わざと展開しない
expect ask deny 'docker run --rm -v $PWD:/w -w /w hashicorp/terraform:1.9 apply -auto-approve'
# shellcheck disable=SC2016  # 同上
expect allow deny 'docker run --rm -v $PWD:/w -w /w hashicorp/terraform:1.9 fmt -check'
# 一覧に足した道具。副命令で分ける名前は、通す副命令のほかを確認にする
expect ask deny 'terragrunt apply'
expect ask deny 'terragrunt run-all plan'
expect allow deny 'terragrunt hclfmt'
expect ask deny 'cdktf deploy'
expect allow deny 'cdktf synth'
expect ask deny 'packer build x.pkr.hcl'
expect allow deny 'packer fmt .'
expect ask deny 'serverless deploy'
expect ask deny 'sls deploy'
expect ask deny 'npx sst deploy'
expect ask deny 'amplify push'
expect ask deny 'copilot deploy'
expect ask deny 'eb deploy'
expect ask deny 'firebase deploy'
expect ask deny 'wrangler deploy'
expect ask deny 'flyctl deploy'
expect ask deny 'vercel --prod'
expect ask deny 'helmfile apply'
expect ask deny 'skaffold run'
expect ask deny 'oc apply -f x.yaml'
expect ask deny 'argocd app sync x'
expect ask deny 's3cmd ls'
expect ask deny 'rclone ls s3:bucket'
expect ask deny 'sam package --s3-bucket b'
expect ask deny 'sam publish'
expect ask deny 'sam remote invoke fn'
expect ask deny 'sam pipeline bootstrap'
expect ask deny 'sam list stack-outputs --stack-name s'
expect allow deny 'sam --version'
expect ask deny 'cdk watch'
expect ask deny 'cdk gc'
expect ask deny 'cdk rollback'
expect ask deny 'cdk drift'
expect ask deny 'npx cdk list'
expect ask deny 'npx cdk synth'
expect allow deny 'npx cdk --version'
expect allow deny 'cdk init app --language typescript'
# パスの最後の名前は、ディレクトリでも ask（cd terraform と同じく、取りこぼさない側に倒す）
expect ask deny 'cd infra/aws && ls'
# パスの途中の名前、隠しの名前、名前の一部だけのもの、包みのスクリプト（網の外）は allow。今の deny（hooks/ への書き込み）は deny のまま
expect allow deny 'cat infra/terraform/main.tf'
expect allow deny 'ls ~/.aws'
expect allow deny 'grep -rn aws_s3_bucket infra/'
expect allow deny 'cat docs/helm-chart.md'
expect allow deny 'echo butterfly web docker'
expect allow deny 'ls src/eb.ts'
expect allow deny 'npm run deploy'
expect deny deny 'aws s3 ls; rm -rf hooks'

# ---- 2. hooks（端から端）
T="$(mktemp -d)"
cleanup() {  # 一時の場所と、My-Lab の tmp/.verify に書いた、この自己試験の分の記録を消す（本物のセッションの記録は消さない）
  local v="$LAB_ROOT/tmp/.verify"
  rm -rf "$T"
  rm -f "$v/stop-count-selftest-$$" "$v"/stop-count-selftest-*-"$$" "$v"/terms-selftest-*-"$$" \
        "$v/sessions/selftest-$$.start" "$v/sessions/selftest-$$.files"
}
trap cleanup EXIT
export CLAUDE_PROJECT_DIR="$T" CURSOR_PROJECT_DIR="$T"
export COMPANY_GUARD_VERIFY_CMD="false"
export COMPANY_GUARD_CURSOR_MODE=ask  # この Mac の ~/.cursor/company-guard.mode に左右されない。ファイルを読む道は 2d で HOME を差し替えて試す
export COMPANY_GUARD_MODE_FILE="$T/no-root/mode"  # この Mac の root の置き場（/usr/local/etc/company-guard）にも左右されない。置き場のある道は 2d-2 で差し替えて試す
OUT=""; RC=0
run() {  # run <hooks> <stdin の JSON> [引数...] → OUT と RC
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
CLAUDE_PROJECT_DIR="$LAB_ROOT" run claude-pretooluse.sh "$(cj 'cp x hooks/guard-core.sh')"
assert "Claude PreToolUse(My-Lab の中): hooks/ への cp は deny" has_out '"permissionDecision":"deny"'
run claude-pretooluse.sh "$(cj 'cp x hooks/guard-core.sh')"
assert "Claude PreToolUse(他のプロジェクト): hooks/ への cp は何も出さない" no_out
run claude-pretooluse.sh "$(cj 'ln ~/.claude/settings.json /tmp/x')"
assert "Claude PreToolUse: ~/.claude/settings.json へのハードリンクは deny" has_out '"permissionDecision":"deny"'
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
# 最後の名前（basename）だけ大文字にした書き方。real_path はフォルダは本当の綴りに直すが、最後の名前は打たれたまま返すので、比較で小文字にそろえる
printf '{}\n' > "$T/.claude/settings.json"
edit Write "$T/.claude/SETTINGS.JSON";              assert "preedit: ある settings.json の最後の名前だけ大文字にしても deny" has_out '"permissionDecision":"deny"'
edit Edit "$T/.claude/Settings.json";               assert "preedit: Settings.json も deny" has_out '"permissionDecision":"deny"'
edit Edit "$T/.claude/CLAUDE.MD";                   assert "preedit: CLAUDE.MD は deny" has_out '"permissionDecision":"deny"'
edit Write "$T/.Claude/Hooks/x.sh";                 assert "preedit: ~/.Claude/Hooks の下は deny" has_out '"permissionDecision":"deny"'
edit Edit "$LAB_ROOT/.claude/SETTINGS.json";        assert "preedit: My-Lab の .claude/SETTINGS.json は deny" has_out '"permissionDecision":"deny"'
edit Edit "$LAB_ROOT/.cursor/HOOKS.JSON";           assert "preedit: My-Lab の .cursor/HOOKS.JSON は deny" has_out '"permissionDecision":"deny"'
edit Write "$(printf '%s' "$HOOKS_DIR/GUARD-CORE.SH" | tr '[:lower:]' '[:upper:]')"; assert "preedit: My-Lab の hooks/ を全部大文字にしても deny" has_out '"permissionDecision":"deny"'
# ハードリンク。別の名前から同じ中身を書き換える道は、パスの比較では見分けられないので、名前が 2 つ以上のファイルは deny
ln "$T/.claude/settings.json" "$T/proj2/alias.json"
edit Edit "$T/proj2/alias.json";                    assert "preedit: ~/.claude/settings.json のハードリンクは deny" has_out '"permissionDecision":"deny"'
assert "preedit: ハードリンクの理由を言う" has_out 'ハードリンク'
rm -f "$T/proj2/alias.json"
printf 'a\n' > "$T/proj2/one.txt"
edit Edit "$T/proj2/one.txt";                       assert "preedit: 名前が 1 つのふつうのファイルは何も出さない" no_out
ln "$T/proj2/one.txt" "$T/proj2/two.txt"
edit Edit "$T/proj2/two.txt";                       assert "preedit: 守りの外でも名前が 2 つあるファイルは deny" has_out '"permissionDecision":"deny"'
rm -f "$T/proj2/two.txt"
edit Edit "$T/proj2/one.txt";                       assert "preedit: リンクを外せば書ける" no_out
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
# 印（stop_hook_active）を送らない呼び手（Claude Code 形式の hooks を Cursor が回すとき）でも、回数だけで止まる
rm -f "$LAB_ROOT/tmp/.verify/stop-count-selftest-$$"
SJN='{"session_id":"selftest-'"$$"'","cwd":"'"$T"'","hook_event_name":"Stop"}'
COMPANY_GUARD_VERIFY_CMD=false run claude-stop.sh "$SJN"; COMPANY_GUARD_VERIFY_CMD=false run claude-stop.sh "$SJN"; COMPANY_GUARD_VERIFY_CMD=false run claude-stop.sh "$SJN"
assert "Claude Stop（印なし）: 続きの指示は 3 回目まで block" has_out '"decision":"block"'
COMPANY_GUARD_VERIFY_CMD=false run claude-stop.sh "$SJN"
assert "Claude Stop（印なし）: 4 回目は上限で止める" no_out
COMPANY_GUARD_VERIFY_CMD=false run claude-stop.sh "$SJ"
assert "Claude Stop: 上限のあとの新しい依頼（印が false）は、また block" has_out '"decision":"block"'
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
MP="$T/etc"   # 置き場の親。root 所有の /usr/local/etc に当たる
lock()   { chmod 444 "$MF" 2>/dev/null; chmod 555 "$MD" "$MP"; }   # root 所有と同じく、ファイル・置き場・親のどれも自分の権限では書けない形にする
unlock() { chmod 755 "$MP" "$MD"; chmod 644 "$MF" 2>/dev/null; }
printf 'ask\n' > "$T/.cursor/company-guard.mode"            # 互換の側は ask と言わせておく
mkdir -p "$MD"
cmt; assert "Cursor(root の置き場: フォルダだけでファイルが無い): deny に倒す" has_out '"permission":"deny"'
assert "Cursor(root の置き場: ファイルが無い): 理由を言う" has_out 'ファイルが無い'
printf 'ask\n' > "$MF"
cmt; assert "Cursor(root の置き場: 自分の権限で書ける): deny に倒す" has_out '"permission":"deny"'
assert "Cursor(root の置き場: 自分の権限で書ける): 理由を言う" has_out '自分の権限で書ける'
chmod 444 "$MF"; chmod 555 "$MD"                            # ファイルと置き場は書けないが、親は書ける（置き場ごと移せる）
cmt; assert "Cursor(root の置き場: 親フォルダが自分の権限で書ける): deny に倒す" has_out '"permission":"deny"'
assert "Cursor(root の置き場: 親フォルダが書ける): 理由を言う" has_out '置き場の親'
lock
cmt; assert "Cursor(root の置き場: ask で書けない): ask。互換の側は読まない" has_out '"permission":"ask"'
unlock; printf 'deny\n' > "$MF"; printf 'ask\n' > "$T/.cursor/company-guard.mode"; lock
cmt; assert "Cursor(root の置き場: deny): 互換の側が ask でも deny" has_out '"permission":"deny"'
assert "Cursor(root の置き場: deny): 壊れた理由は付かない" lacks_out 'に倒す'
COMPANY_GUARD_CURSOR_MODE='' HOME="$T" COMPANY_GUARD_MODE_FILE="$MF" run cursor-before-shell.sh '{"command":"git status","cwd":"'"$T"'"}'
assert "Cursor(root の置き場: deny): 読むだけは allow のまま" has_out '"permission":"allow"'
unlock; printf 'maybe\n' > "$MF"; lock
cmt; assert "Cursor(root の置き場: 中身が deny でも ask でもない): deny に倒す" has_out '"permission":"deny"'
unlock; printf 'ask\n' > "$MF"; chmod 000 "$MF"; chmod 555 "$MD" "$MP"
cmt; assert "Cursor(root の置き場: 読めない): deny に倒す" has_out '"permission":"deny"'
assert "Cursor(root の置き場: 読めない): 理由を言う" has_out '読めない'
unlock; rm -f "$MF"; ln -s "$T/.cursor/company-guard.mode" "$MF"; chmod 555 "$MD" "$MP"
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

# 2g. Stop の両 hooks: 検証が通ったあと、ファイルを消すだけ・名前を変えるだけでも、次の Stop は検証を回す
# 印（last-pass）より新しいファイルは 1 本も無い場面なので、一覧（last-pass.list）の比較だけが変更を見つける
P="$T/proj"; mkdir -p "$P/src" "$P/tmp/.verify"
printf 'a\n' > "$P/src/a.txt"; printf 'b\n' > "$P/src/b.txt"; printf 'd\n' > "$P/src/d.txt"
touch -t 202001010000 "$P/src/a.txt" "$P/src/b.txt" "$P/src/d.txt"   # 印より確かに古い時刻にする
SJP='{"session_id":"selftest-'"$$"'","cwd":"'"$P"'","hook_event_name":"Stop","stop_hook_active":false}'
CJP='{"status":"completed","loop_count":0,"cwd":"'"$P"'"}'
# pass_stop: 検証の命令が印を書く（verify-all.sh と project-verify.sh が PASS で touch するのと同じ）。通った直後に hooks が一覧を書く
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

# 2h. commit 文・PR 文・Issue 文の言い換え（W-4）を、hooks の端から端で。-F・--file・--body-file のファイルの中身も見る
#     言い換えの語は 1h と同じく ${TW}（UTF-8 の 3 バイトから作った字）で書く
printf '本文: 作業用の%sで直しました。\n' "$TW" > "$T/body.md"
printf '本文: 作業用のブランチで直しました。\n' > "$T/ok.md"
expect_at "$T" deny 'gh pr create --title x --body-file body.md'
expect_at "$T" deny "gh pr edit 12 --body-file $T/body.md"
expect_at "$T" deny 'git commit -F body.md'
expect_at "$T" deny 'git commit --file=body.md'
expect_at "$T" deny 'gh issue create --title x -F "body.md"'
expect_at "$T" ask 'gh pr create --title x --body-file ok.md'
expect_at "$T" ask 'git commit -F -'
expect_at "$T" ask 'gh issue create --title x --body-file missing.md'
got="$(COMPANY_GUARD_PROJECT_ROOT="$T" bash "$CORE" -- 'gh issue create --title x --body-file missing.md')"
case "$got" in ask*'本文のファイル（missing.md）を読めず'*) ok ;; *) bad "判定: 読めない本文のファイルを確認の理由に書かない: ${got}" ;; esac
# 本文を渡す書き方（$(cat)、<、cat |、まとめた短いオプション、key=@<ファイル>、逃がした空白）と、作業場所（cwd、cd、git -C）からの読み先
mkdir -p "$T/sub" "$T/日本語 dir"
printf '本文: 作業用の%sで直しました。\n' "$TW" > "$T/sub/msg.md"
printf '本文: 作業用の%sで直しました。\n' "$TW" > "$T/日本語 dir/本文 1.md"
# expect_cwd <作業場所> <期待> <コマンド> → hooks が入力の cwd を渡したものとして判定を見る（root は ${T}）
expect_cwd() {
  local cwd="$1" want="$2" cmd="$3" got
  got="$(COMPANY_GUARD_CWD="$cwd" COMPANY_GUARD_PROJECT_ROOT="$T" bash "$CORE" -- "$cmd" | cut -f1)"
  if [ "$got" = "$want" ]; then ok; else bad "判定(cwd=$cwd): 期待 $want / 実際 $got : $cmd"; fi
}
# shellcheck disable=SC2016  # $(cat …) は判定本体に渡す文字列。わざと展開しない
expect_cwd "$T" deny 'git commit -m "$(cat body.md)"'
expect_cwd "$T" deny 'git commit -F - < body.md'
expect_cwd "$T" deny 'cat body.md | gh pr create --title x --body-file -'
expect_cwd "$T" deny 'git commit -aF body.md'
expect_cwd "$T" deny 'gh api repos/o/r/issues -F body=@body.md'
expect_cwd "$T" deny 'gh pr merge 12 --body-file body.md'
expect_cwd "$T" deny 'git commit -F 日本語\ dir/本文\ 1.md'
expect_cwd "$T" deny 'git commit -F "日本語 dir/本文 1.md"'
expect_cwd "$T/sub" deny 'git commit -F msg.md'
expect_cwd "$T" deny 'cd sub && git commit -F msg.md'
expect_cwd "$T" deny 'git -C sub commit -F msg.md'
expect_cwd "$T" ask 'git commit -F msg.md'
expect_cwd "$T/sub" ask 'git commit -F ../ok.md'
# < と cat | の先は、本文を標準入力から読む命令のときだけ読む。本文でないファイルの語では止めない
expect_cwd "$T" ask 'git commit -m ok && cat body.md | grep x'
expect_cwd "$T" ask 'git commit -m ok < body.md'
expect_cwd "$T" deny 'git commit --file=- < body.md'
# -F の多い長い命令でも、走査は 1 回ずつ（時間が -F の数に比例して伸びない）。前の作りでは 4500 個で 13 秒かかった
big="gh pr create --title t --body \"$(i=0; while [ "$i" -lt 4500 ]; do printf '説明 -F x '; i=$((i + 1)); done)\""
t0=$(date +%s); got="$(COMPANY_GUARD_PROJECT_ROOT="$T" bash "$CORE" -- "$big" | cut -f1)"; t1=$(date +%s)
if [ "$got" = ask ] && [ $((t1 - t0)) -le 6 ]; then ok; else bad "判定(長い命令): 期待 ask で 6 秒以内 / 実際 $got で $((t1 - t0)) 秒"; fi
run claude-pretooluse.sh "$(cj "git commit -m \"作業用の${TW}を直す\"")"
assert "Claude PreToolUse: commit 文の言い換えは deny" has_out '"permissionDecision":"deny"'
assert "Claude PreToolUse: 直す語を言う" has_out '「ブランチ」に直してから、もう一度実行してください'
run cursor-before-shell.sh "$(printf '{"command":"git commit -m 作業用の%sを直す","cwd":"%s"}' "$TW" "$T")"
assert "Cursor before-shell: commit 文の言い換えは deny" has_out '"permission":"deny"'
assert "Cursor before-shell: 言い換えの deny は止まらせず、直させる" lacks_out '止まって'
run claude-pretooluse.sh "$(cj 'terraform apply')"
assert "Claude PreToolUse: クラウドにつなぐコマンドは ask" has_out '"permissionDecision":"ask"'
assert "Claude PreToolUse: クラウドの理由を言う" has_out 'そのたびに承認を得て回す'
# Claude Code の入力の cwd を判定本体に渡し、-F の相対パスを命令の作業場所から読む
run claude-pretooluse.sh "$(printf '{"session_id":"selftest-%s","cwd":"%s","tool_name":"Bash","tool_input":{"command":"git commit -F msg.md"}}' "$$" "$T/sub")"
assert "Claude PreToolUse: 入力の cwd から -F のファイルを読み、言い換えは deny" has_out '"permissionDecision":"deny"'
run cursor-before-shell.sh "$(printf '{"command":"git commit -F msg.md","cwd":"%s"}' "$T/sub")"
assert "Cursor before-shell: 入力の cwd から -F のファイルを読み、言い換えは deny" has_out '"permission":"deny"'
COMPANY_GUARD_CURSOR_MODE=deny run cursor-before-shell.sh '{"command":"kubectl get pods","cwd":"'"$T"'"}'
assert "Cursor before-shell(deny の設定): クラウドにつなぐコマンドは deny" has_out '"permission":"deny"'
# 正本（My-Lab の tools/lib/check_ja.py）が無い置き場の hooks は、数えずに今までどおり ask
NOLAB="$T/nolab"; mkdir -p "$NOLAB" && cp -R "$HOOKS_DIR" "$NOLAB/hooks"
got="$(bash "$NOLAB/hooks/guard-core.sh" -- "git commit -m \"作業用の${TW}を直す\"" | cut -f1)"
if [ "$got" = ask ]; then ok; else bad "判定(正本が無い): 期待 ask / 実際 $got"; fi

# 2i. 返答の言い換え（W-3）。Claude Code の Stop は、検証より先に返答（last_assistant_message）を見る。
#     書き直しと検証の差し戻しは、合わせて 1 つの依頼で 3 回まで（Cursor の loop_count と同じ数え方）
WT="$T/w3"; mkdir -p "$WT"
WS="selftest-w3-$$"
BR="作業用の${TW}を切りました。"
wj() {  # wj <stop_hook_active> <返答（JSON の文字列の中身）> → Stop の入力
  printf '{"session_id":"%s","cwd":"%s","hook_event_name":"Stop","stop_hook_active":%s,"last_assistant_message":"%s"}' "$WS" "$WT" "$1" "$2"
}
w3() { CLAUDE_PROJECT_DIR="$WT" CURSOR_PROJECT_DIR="$WT" COMPANY_GUARD_VERIFY_CMD="$1" run claude-stop.sh "$(wj "$2" "$3")"; }   # w3 <検証の命令> <印> <返答>
w3 true false "$BR"
assert "Claude Stop: 返答に語があれば block" has_out '"decision":"block"'
assert "Claude Stop: 返答の語を言う" has_out "返答に「${TW}」がありました。git の語は言い換えません。"
assert "Claude Stop: 直す語を言う" has_out '「ブランチ」に直して、返答を書き直してください。'
assert "Claude Stop: 返答の差し戻しも JSON" is_json
w3 true true "$BR"; assert "Claude Stop: 返答の差し戻しは 2 回目も block" has_out '"decision":"block"'
w3 true true "$BR"; assert "Claude Stop: 返答の差し戻しは 3 回目も block" has_out '"decision":"block"'
w3 true true "$BR"
assert "Claude Stop: 3 回のあとは差し戻さない" lacks_out '"decision"'
assert "Claude Stop: 3 回のあとは、語が残ったことを画面に出す" has_out '"systemMessage"'
assert "Claude Stop: 画面の文に直す語がある" has_out '「ブランチ」と書きます'
assert "Claude Stop: 画面の文も JSON" is_json
w3 true false "$BR"; assert "Claude Stop: 新しい依頼（印が false）では、また block" has_out '"decision":"block"'
w3 true false 'ブランチを切りました。'; assert "Claude Stop: 語の無い返答は何も出さない" no_out
w3 true false "「${TW}」とは書かず、ブランチと書きます。"
assert "Claude Stop: 鉤括弧の中だけなら通す" no_out
w3 true false "例:\\n\`\`\`\\ngit checkout ${TW}\\n\`\`\`"
assert "Claude Stop: 3 つのバッククォートの囲みの中は数えない" no_out
w3 false false "$BR"
assert "Claude Stop: 検証が落ちる場面でも、先に返答を書き直させる" has_out '返答に'
assert "Claude Stop: 返答の差し戻しでは検証の文を出さない" lacks_out '検証（'
w3 false true 'ブランチを切りました。'
assert "Claude Stop: 書き直したあとに検証が落ちれば、検証で block" has_out '作業を終える前の検証'
w3 false true "$BR"
assert "Claude Stop: 3 回目までは、また返答を書き直させる" has_out '"decision":"block"'
w3 false true "$BR"
assert "Claude Stop: 書き直しと検証を合わせて 3 回で止める（0 に戻して回し続けない）" lacks_out '"decision"'
assert "Claude Stop: 上限で止めるとき、語が残ったことを画面に出す" has_out '"systemMessage"'
w3 false true "$BR"
assert "Claude Stop: 上限で止めたあとの Stop は、新しい数え始め" has_out '"decision":"block"'
w3 true false 'ブランチを切りました。'
# 入力に last_assistant_message が無ければ、会話の記録（transcript_path の JSONL）の最後の返答を見る
TR="$T/transcript.jsonl"
tj() { printf '{"session_id":"%s","cwd":"%s","hook_event_name":"Stop","stop_hook_active":false,"transcript_path":"%s"}' "$WS" "$WT" "$1"; }
tline() { printf '{"type":"%s","message":{"role":"%s","content":[{"type":"text","text":"%s"}]}}\n' "$1" "$1" "$2"; }
{ tline user 'x'; tline assistant "前の返答の${TW}"
  printf '{"type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"ok"}]}}\n'
  tline assistant '直しました。'; tline assistant "$BR"; } > "$TR"
CLAUDE_PROJECT_DIR="$WT" COMPANY_GUARD_VERIFY_CMD=true run claude-stop.sh "$(tj "$TR")"
assert "Claude Stop: 返答が入力に無ければ、記録の最後の返答で block" has_out '"decision":"block"'
{ tline user 'x'; tline assistant "前の返答の${TW}"
  printf '{"type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"ok"}]}}\n'
  tline assistant 'ブランチを切りました。'
  printf '{"type":"assistant","isSidechain":true,"message":{"role":"assistant","content":[{"type":"text","text":"%s"}]}}\n' "$BR"; } > "$TR"
CLAUDE_PROJECT_DIR="$WT" COMPANY_GUARD_VERIFY_CMD=true run claude-stop.sh "$(tj "$TR")"
assert "Claude Stop: 記録の、最後の返答より前の語と、ほかの会話の行は数えない" no_out
CLAUDE_PROJECT_DIR="$WT" COMPANY_GUARD_VERIFY_CMD=true run claude-stop.sh "$(tj "$T/no-such-transcript.jsonl")"
assert "Claude Stop: 記録が無ければ、何も言わずに通す" no_out
w3 true false "作業用の${TW}を切りました。<!-- ja-ok -->"
assert "Claude Stop: 返答の中の ja-ok の印では、語を隠せない" has_out '"decision":"block"'
w3 true false "main から履歴が${TW}分かれしました。"
assert "Claude Stop: 履歴の分かれる様子の語は「分岐」に直させる" has_out '「分岐」に直して、返答を書き直してください。'
w3 true false 'ブランチを切りました。'
OUT="$(wj false "$BR" | CLAUDE_PROJECT_DIR="$WT" COMPANY_GUARD_VERIFY_CMD=true bash "$NOLAB/hooks/claude-stop.sh" 2>"$T/err")"; RC=$?
assert "Claude Stop(正本が無い): 数えずに通す" no_out
# 回数の記録（tmp/.verify）を書けない置き場の hooks は、差し戻し続けず、語が残ったことを画面に出して通す
ROLAB="$T/rolab"; mkdir -p "$ROLAB/tmp" && cp -R "$HOOKS_DIR" "$ROLAB/hooks" && ln -s "$LAB_ROOT/tools" "$ROLAB/tools" && : > "$ROLAB/tmp/.verify"
OUT="$(wj false "$BR" | CLAUDE_PROJECT_DIR="$WT" COMPANY_GUARD_VERIFY_CMD=true bash "$ROLAB/hooks/claude-stop.sh" 2>"$T/err")"; RC=$?
assert "Claude Stop(回数を記録できない): 差し戻しを繰り返さない" lacks_out '"decision"'
assert "Claude Stop(回数を記録できない): 語が残ったことを画面に出す" has_out '"systemMessage"'
rm -f "$LAB_ROOT/tmp/.verify/stop-count-$WS"
# Cursor: afterAgentResponse が印を書き、stop が読んで消し、followup_message で書き直させる。回数は loop_count の上限で縛る
CW="selftest-cw-$$"; CM="$LAB_ROOT/tmp/.verify/terms-$CW"
cr() { printf '{"conversation_id":"%s","hook_event_name":"afterAgentResponse","text":"%s","workspace_roots":["%s"]}' "$1" "$2" "$WT"; }
cs() { printf '{"conversation_id":"%s","hook_event_name":"stop","status":"%s","loop_count":%s,"workspace_roots":["%s"]}' "$1" "$2" "$3" "$WT"; }
cw() { CLAUDE_PROJECT_DIR="$WT" CURSOR_PROJECT_DIR="$WT" COMPANY_GUARD_VERIFY_CMD=true run "$@"; }
cw cursor-after-response.sh "$(cr "$CW" "$BR")"
assert "Cursor after-response: 何も出さない" no_out
assert "Cursor after-response: 終了コード 0" [ "$RC" -eq 0 ]
assert "Cursor after-response: 語があれば印を書く" [ -f "$CM" ]
cw cursor-stop.sh "$(cs "$CW" completed 0)"
assert "Cursor stop: 印があれば followup_message で書き直させる" has_out '"followup_message"'
assert "Cursor stop: 返答の語と直す語を言う" has_out "返答に「${TW}」がありました。git の語は言い換えません。「ブランチ」に直して"
assert "Cursor stop: 書き直しの指示も JSON" is_json
assert "Cursor stop: 読んだ印を消す" [ ! -e "$CM" ]
cw cursor-stop.sh "$(cs "$CW" completed 1)"
assert "Cursor stop: 書き直したあと（印が無い）は {}" [ "$OUT" = '{}' ]
cw cursor-after-response.sh "$(cr "$CW" "「${TW}」とは書かず、ブランチと書きます。")"
assert "Cursor after-response: 鉤括弧の中だけなら印を書かない" [ ! -e "$CM" ]
cw cursor-after-response.sh "$(cr "$CW" "$BR")"
cw cursor-stop.sh "$(cs "$CW" completed 3)"
assert "Cursor stop: 上限（loop_count 3）なら、語があっても {}" [ "$OUT" = '{}' ]
assert "Cursor stop: 上限でも印を消す（次の依頼に持ち越さない）" [ ! -e "$CM" ]
cw cursor-after-response.sh "$(cr "$CW" "$BR")"
cw cursor-stop.sh "$(cs "$CW" aborted 0)"
assert "Cursor stop: 中断でも印を消す" [ ! -e "$CM" ]
cw cursor-after-response.sh "$(cr "a/../b-$$" "$BR")"
assert "Cursor after-response: 会話の名前の / は _ にして、tmp/.verify の中に書く" [ -f "$LAB_ROOT/tmp/.verify/terms-a_.._b-$$" ]
rm -f "$LAB_ROOT/tmp/.verify/terms-a_.._b-$$"

# 2j. 終わりの検証の範囲（改善提案書 13 章の V-1〜V-3 の hooks の側）。移した先の形の一時フォルダで、セッションを書き分ける
#     道具は My-Lab の tools/ を tmp/tools に写して、本物の project-verify.sh と check-file.sh で回す
absent_in() { ! grep -q -- "$1" "$2"; }   # absent_in <文字> <ファイル> → その文字が無ければ 0
good_doc() {  # good_doc <ファイル> → 文体と資料の型の検査を通る文書（tools/tests/deployed-checks-test.sh の見本と同じ中身）
  printf '# 調査の覚え書き\n\n> **3 行でわかる要約**\n> 1. これは配置の試験で使う見本の文書です。\n> 2. 文体と資料の型の検査を通ることを確かめます。\n> 3. 次に、検査の結果を見ます。\n\n## 1. 目的\n\n写した道具が文書を検査できることを確かめます。短い文書なので、図と表は要りません。\n' > "$1"
}
bad_doc() { printf '# Note\n\nThis service handles order intake for the shop and stores every order in PostgreSQL for later reporting.\n' > "$1"; }
if [ -f "$LAB_ROOT/tools/project-verify.sh" ] && [ -f "$LAB_ROOT/tools/check-file.sh" ]; then
  D="$T/deployed"; SD="$D/tmp/.verify/sessions"; VF="$D/tmp/.verify/last-fast.txt"
  mkdir -p "$D/tmp/flow/mine" "$D/tmp/flow/other" "$D/tmp/flow/cu" && cp -R "$LAB_ROOT/tools" "$D/tmp/tools"
  printf '# この tmp/ の写しについて\n\n正本: %s\n' "$LAB_ROOT" > "$D/tmp/DEPLOYED.md"
  dep()    { CLAUDE_PROJECT_DIR="$D" CURSOR_PROJECT_DIR="$D" COMPANY_GUARD_VERIFY_CMD='' run "$@"; }
  pre_c()  { dep claude-pretooluse.sh "$(printf '{"session_id":"%s","cwd":"%s","tool_name":"Bash","tool_input":{"command":"ls"}}' "$1" "$D")"; }
  post_c() { dep claude-postedit.sh "$(printf '{"session_id":"%s","cwd":"%s","tool_name":"Write","tool_input":{"file_path":"%s"}}' "$1" "$D" "$2")"; }
  stop_c() { dep claude-stop.sh "$(printf '{"session_id":"%s","cwd":"%s","stop_hook_active":false}' "$1" "$D")"; }
  SA="selftest-va-$$"; SB="selftest-vb-$$"; SC="selftest-vc-$$"
  pre_c "$SA"
  assert "セッションの記録: pre の hooks が始まりの印を置く" [ -f "$SD/$SA.start" ]
  touch -t 202001010000 "$SD/$SA.start"   # A の始まりを確かに古くする。B の文書も、A の印より新しい
  : > "$SD/selftest-old-$$.start"; printf 'tmp/flow/old.md\n' > "$SD/selftest-old-$$.files"
  touch -t 202001010000 "$SD/selftest-old-$$.start" "$SD/selftest-old-$$.files"   # 14 日より古いセッションの記録
  pre_c "$SB"; bad_doc "$D/tmp/flow/other/draft.md"; post_c "$SB" "$D/tmp/flow/other/draft.md"
  assert "セッションの記録: post の hooks が、書いたファイルを root からの相対パスで足す" grep -qx 'tmp/flow/other/draft.md' "$SD/$SB.files"
  good_doc "$D/tmp/flow/mine/report.md"; post_c "$SA" "$D/tmp/flow/mine/report.md"; post_c "$SA" "$D/tmp/flow/mine/report.md"
  assert "セッションの記録: 同じファイルは重ねない" [ "$(grep -c . "$SD/$SA.files")" -eq 1 ]
  stop_c "$SA"
  assert "V-1: 別のセッションの落ちる文書があっても、自分の文書が通れば Stop は何も言わない" no_out
  assert "V-1: 検証は、自分の文書を渡して回った" grep -q 'tmp/flow/mine/report.md' "$VF"
  assert "V-1: 別のセッションの文書は渡さない" absent_in 'draft.md' "$VF"
  assert "記録の掃除: 14 日より古いセッションの記録（.start）を消す" [ ! -e "$SD/selftest-old-$$.start" ]
  assert "記録の掃除: 14 日より古いセッションの記録（.files）を消す" [ ! -e "$SD/selftest-old-$$.files" ]
  assert "記録の掃除: .start が古くても、.files が新しいセッションの記録は残す" [ -f "$SD/$SA.start" ]
  rm -f "$VF"; stop_c "$SA"
  assert "自分の文書が通ったあと、何も変えていなければ検証を回し直さない" [ ! -e "$VF" ]
  pre_c "$SC"   # 何も書かないセッション（始まりの印は古くしない。14 日より古い印は、記録の掃除が消す）
  mkdir -p "$D/tmp/flow/loose" && bad_doc "$D/tmp/flow/loose/note.md"   # Bash のコマンドか人の手で書いた文書（どのセッションの記録にも無い）
  touch -t 203001010000 "$D/tmp/flow/loose/note.md"   # どのセッションの始まりの印よりも、確かに新しくする
  assert "記録に無い文書を置いた（この先の試験の前提）" [ -f "$D/tmp/flow/loose/note.md" ]
  stop_c "$SA"
  assert "記録に無い文書は、始まりの印より新しくても渡さない（Bash で書いた文書は AI が手で渡す）" no_out
  assert "記録に無い文書だけが増えても、検証を回し直さない" [ ! -e "$VF" ]
  bad_doc "$D/tmp/flow/mine/bad.md"; post_c "$SA" "$D/tmp/flow/mine/bad.md"
  stop_c "$SA"
  assert "V-3: 自分の文書が落ちれば block" has_out '"decision":"block"'
  assert "V-3: 差し戻しの文は、このセッションで書いた文書の検査" has_out 'このセッションで書いた文書の検査'
  assert "V-3: 落ちた自分の文書の名前を出す" has_out 'tmp/flow/mine/bad.md'
  assert "V-3: 別のセッションの文書の名前は出さない" lacks_out 'draft.md'
  assert "V-3: 記録に無い文書の名前は出さない" lacks_out 'loose/note.md'
  assert "V-3: 範囲外の文を出さない" lacks_out '範囲外'
  assert "何も書かないセッションの始まりの印が、掃除で消えずに残る（この先の試験の前提）" [ -f "$SD/$SC.start" ]
  rm -f "$VF"; stop_c "$SC"
  assert "V-2: 何も書いていないセッションは、ほかの文書が始まりの印より新しくても、何も言わない" no_out
  assert "V-2: 何も書いていないセッションは、検証を回さない" [ ! -e "$VF" ]
  stop_c "selftest-vn-$$"
  assert "V-2: 記録が 1 つも無いセッションも、検証を回さない" [ ! -e "$VF" ]
  # Cursor: before-shell が始まりの印、after-edit が書いたファイルの記録、stop が会話の文書だけを渡す
  pre_u()  { dep cursor-before-shell.sh "$(printf '{"conversation_id":"%s","command":"ls","cwd":"%s","workspace_roots":["%s"]}' "$1" "$D" "$D")"; }
  post_u() { dep cursor-after-edit.sh "$(printf '{"conversation_id":"%s","file_path":"%s","workspace_roots":["%s"]}' "$1" "$2" "$D")"; }
  stop_u() { dep cursor-stop.sh "$(printf '{"conversation_id":"%s","status":"completed","loop_count":0,"workspace_roots":["%s"]}' "$1" "$D")"; }
  SU="selftest-vu-$$"
  pre_u "$SU"
  assert "Cursor before-shell: 始まりの印を置く" [ -f "$SD/$SU.start" ]
  good_doc "$D/tmp/flow/cu/note.md"; post_u "$SU" "$D/tmp/flow/cu/note.md"
  assert "Cursor after-edit: 書いたファイルを足す" grep -qx 'tmp/flow/cu/note.md' "$SD/$SU.files"
  stop_u "$SU"
  assert "Cursor stop(V-1): ほかの落ちる文書があっても、自分の文書が通れば {}" [ "$OUT" = '{}' ]
  bad_doc "$D/tmp/flow/cu/bad.md"; post_u "$SU" "$D/tmp/flow/cu/bad.md"
  stop_u "$SU"
  assert "Cursor stop(V-3): 自分の文書が落ちれば followup_message" has_out '"followup_message"'
  assert "Cursor stop(V-3): 差し戻しの文は、このセッションで書いた文書の検査" has_out 'このセッションで書いた文書の検査'
  assert "Cursor stop(V-3): 落ちた自分の文書の名前を出す" has_out 'tmp/flow/cu/bad.md'
  assert "Cursor stop(V-3): ほかのセッションの文書の名前は出さない" lacks_out 'mine/bad.md'
  # 命令のファイル（tmp/verify-commands.txt）: 何も書いていないセッションでは回さない（改善提案書 13.2 の「何も回さず、何も読まない」）。
  #   Write・Edit で書いたセッションでは、文書が 0 本でも今までどおり回し、何も変わっていなければ回し直さない
  D2="$T/deployed-cmds"; mkdir -p "$D2/tmp" "$D2/src" && cp -R "$LAB_ROOT/tools" "$D2/tmp/tools"
  printf 'printf x >> %s\n' "$T/d2-calls.txt" > "$D2/tmp/verify-commands.txt"
  dep2() { CLAUDE_PROJECT_DIR="$D2" CURSOR_PROJECT_DIR="$D2" COMPANY_GUARD_VERIFY_CMD='' run "$@"; }
  SQ='{"session_id":"selftest-vq-'"$$"'","cwd":"'"$D2"'","stop_hook_active":false}'
  dep2 claude-stop.sh "$SQ"
  assert "移した先: 何も書いていないセッションは、命令のファイルがあっても回さない" [ ! -e "$T/d2-calls.txt" ]
  assert "移した先: 何も書いていないセッションは、何も言わない" no_out
  printf 'x = 1\n' > "$D2/src/app.py"
  dep2 claude-postedit.sh "$(printf '{"session_id":"selftest-vq-%s","cwd":"%s","tool_name":"Write","tool_input":{"file_path":"%s"}}' "$$" "$D2" "$D2/src/app.py")"
  dep2 claude-stop.sh "$SQ"
  assert "移した先: 書いたセッションは、文書が 0 本でも、命令のファイルがあれば回す" [ "$(cat "$T/d2-calls.txt" 2>/dev/null)" = x ]
  assert "移した先: 命令が通れば何も言わない" no_out
  dep2 claude-stop.sh "$SQ"
  assert "移した先: 何も変わっていなければ、命令を回し直さない" [ "$(cat "$T/d2-calls.txt" 2>/dev/null)" = x ]
  printf 'y\n' > "$D2/new.txt"; touch -t 203001010000 "$D2/new.txt"
  dep2 claude-stop.sh "$SQ"
  assert "移した先: ファイルが変われば、命令を回す" [ "$(cat "$T/d2-calls.txt" 2>/dev/null)" = xx ]
  printf 'false\n' > "$D2/tmp/verify-commands.txt"; printf 'z\n' > "$D2/new2.txt"; touch -t 203001010000 "$D2/new2.txt"
  dep2 claude-stop.sh "$SQ"
  assert "移した先: 落ちたのが命令だけなら、今までの差し戻しの文" has_out '作業を終える前の検証（bash tmp/tools/project-verify.sh --fast）が FAIL'
  assert "移した先: 落ちたのが命令だけなら、文書の検査とは言わない" lacks_out 'このセッションで書いた文書の検査'
  # deploy.sh を回し直す前の、引数を見ない古い project-verify.sh（冒頭に「[--] [<ファイル>...]」が無い）。文書を渡さず、前の文で差し戻す
  D4="$T/deployed-old"; mkdir -p "$D4/tmp/flow/mine" && cp -R "$LAB_ROOT/tools" "$D4/tmp/tools"
  printf '# この tmp/ の写しについて\n\n正本: %s\n' "$LAB_ROOT" > "$D4/tmp/DEPLOYED.md"
  cat > "$D4/tmp/tools/project-verify.sh" <<'OLDPV'
#!/bin/bash
# 前の版の形: 使い方は [--fast|--full|--baseline] で、引数の文書を見ずに tmp/ の文書を全部検査する
printf '%s\n' "$*" > "$(dirname "$0")/old-args.txt"
printf 'FAIL check-file（tmp の文書 2 本）: FAIL tmp/flow/other/draft.md:3 [英文]\n'
printf 'RESULT: FAIL check-file（tmp の文書 2 本） (rc=1)\n'
printf 'RESULT: FAIL project-verify --fast (2 件中 FAIL 1)\n'
exit 1
OLDPV
  good_doc "$D4/tmp/flow/mine/report.md"
  dep4() { CLAUDE_PROJECT_DIR="$D4" CURSOR_PROJECT_DIR="$D4" COMPANY_GUARD_VERIFY_CMD='' run "$@"; }
  dep4 claude-postedit.sh "$(printf '{"session_id":"selftest-vo-%s","cwd":"%s","tool_name":"Write","tool_input":{"file_path":"%s"}}' "$$" "$D4" "$D4/tmp/flow/mine/report.md")"
  dep4 claude-stop.sh "$(printf '{"session_id":"selftest-vo-%s","cwd":"%s","stop_hook_active":false}' "$$" "$D4")"
  assert "古い project-verify: 文書を引数で渡さない" [ "$(cat "$D4/tmp/tools/old-args.txt" 2>/dev/null)" = --fast ]
  assert "古い project-verify: 前の差し戻しの文を使う" has_out '作業を終える前の検証（bash tmp/tools/project-verify.sh --fast）が FAIL'
  assert "古い project-verify: ほかのセッションの文書の FAIL を、このセッションの文書と呼ばない" lacks_out 'このセッションで書いた文書の検査'
else
  bad "2j: My-Lab の tools/project-verify.sh と tools/check-file.sh が無い（SKIP は FAIL と同じ）"
fi

# 2k. My-Lab の形（tools/verify-all.sh と .company/）: Write・Edit で何も書いていないセッションでは verify-all を回さない。
#     ほかのセッションがあとで書いても、名前が取れなくても回さない（改善提案書 13.2）。書いていれば今までどおり回す
L2="$T/lab2"; mkdir -p "$L2/tools" "$L2/.company" "$L2/src"
printf '#!/bin/bash\nexit 0\n' > "$L2/tools/check-file.sh"
# shellcheck disable=SC2016  # $(cat …) は身代わりの verify-all.sh の中で展開する。ここでは展開しない
printf '#!/bin/bash\nprintf x >> %s\nexit "$(cat %s 2>/dev/null || echo 0)"\n' "$T/lab-calls.txt" "$T/lab-rc" > "$L2/tools/verify-all.sh"
labr() { CLAUDE_PROJECT_DIR="$L2" CURSOR_PROJECT_DIR="$L2" COMPANY_GUARD_VERIFY_CMD='' run "$@"; }
lj() { printf '{"session_id":"%s","cwd":"%s","tool_name":"Write","tool_input":{"file_path":"%s"},"stop_hook_active":false}' "$1" "$L2" "${2:-}"; }
LX="selftest-lx-$$"; LY="selftest-ly-$$"
labr claude-stop.sh "$(lj "$LX")"
assert "My-Lab: 何も書いていないセッションは verify-all を回さない" [ ! -e "$T/lab-calls.txt" ]
labr claude-preedit.sh "$(lj "$LX" "$L2/src/a.txt")"; printf 'a\n' > "$L2/src/a.txt"; labr claude-postedit.sh "$(lj "$LX" "$L2/src/a.txt")"
labr claude-stop.sh "$(lj "$LX")"
assert "My-Lab: 書いたセッションは、今までどおり verify-all を回す" [ "$(cat "$T/lab-calls.txt" 2>/dev/null)" = x ]
assert "My-Lab: verify-all が通れば何も言わない" no_out
touch -t 202001010000 "$L2/src/a.txt"
labr claude-pretooluse.sh "$(lj "$LY")"; labr claude-stop.sh "$(lj "$LY")"
assert "My-Lab: ほかのセッションが前に書いただけなら、回さない" [ "$(cat "$T/lab-calls.txt" 2>/dev/null)" = x ]
labr claude-preedit.sh "$(lj "$LX" "$L2/src/c.txt")"; printf 'c\n' > "$L2/src/c.txt"; labr claude-postedit.sh "$(lj "$LX" "$L2/src/c.txt")"
labr claude-stop.sh "$(lj "$LY")"
assert "My-Lab: ほかのセッションが、始まりの印のあとに書いても回さない" [ "$(cat "$T/lab-calls.txt" 2>/dev/null)" = x ]
assert "My-Lab: ほかのセッションの書き込みで、何も書いていないセッションを止めない" no_out
had_none=0; [ -e "$LAB_ROOT/tmp/.verify/stop-count-none" ] && had_none=1   # 名前の無いセッションの回数の記録。この試験で作ったときだけ消す
labr claude-stop.sh '{"cwd":"'"$L2"'","stop_hook_active":false}'
assert "My-Lab: セッションの名前が無ければ、回さない" [ "$(cat "$T/lab-calls.txt" 2>/dev/null)" = x ]
[ "$had_none" = 1 ] || rm -f "$LAB_ROOT/tmp/.verify/stop-count-none"
labr claude-stop.sh "$(lj "$LX")"
assert "My-Lab: 書いたセッションは、ファイルが変われば回す" [ "$(cat "$T/lab-calls.txt" 2>/dev/null)" = xx ]
printf '1' > "$T/lab-rc"; printf 'b\n' > "$L2/src/b.txt"; labr claude-postedit.sh "$(lj "$LX" "$L2/src/b.txt")"
labr claude-stop.sh "$(lj "$LX")"
assert "My-Lab: verify-all が落ちれば block" has_out '"decision":"block"'
assert "My-Lab: 差し戻しの文は今までどおり" has_out '作業を終える前の検証（bash tools/verify-all.sh --fast）が FAIL'

# 2l. セッションの記録は判定に響かない。記録の置き場が壊れていても、判定は今までどおり。ほかのプロジェクトには記録を置かない
D3="$T/broken"; mkdir -p "$D3/tmp/tools" "$D3/tmp/.verify" && : > "$D3/tmp/tools/check-file.sh" && : > "$D3/tmp/.verify/sessions"
CLAUDE_PROJECT_DIR="$D3" run claude-pretooluse.sh "$(cj 'git commit -m x')"
assert "記録が書けなくても、Claude の Bash の判定は ask のまま" has_out '"permissionDecision":"ask"'
CLAUDE_PROJECT_DIR="$D3" CURSOR_PROJECT_DIR="$D3" run cursor-before-shell.sh '{"conversation_id":"selftest-x","command":"git commit -m x","cwd":"'"$D3"'"}'
assert "記録が書けなくても、Cursor の判定は ask のまま" has_out '"permission":"ask"'
HOME="$T" CLAUDE_PROJECT_DIR="$D3" run claude-preedit.sh "$(pj Write "$T/.cursor/company-guard.mode")"
assert "記録が書けなくても、Write の門は deny のまま" has_out '"permissionDecision":"deny"'
assert "検証の道具の無いプロジェクトには、セッションの記録を置かない" [ ! -e "$T/tmp/.verify/sessions" ]

if [ "$fail" -eq 0 ]; then verdict=PASS; else verdict=FAIL; fi
printf 'RESULT: %s hooks の自己試験 %d PASS / %d FAIL\n' "$verdict" "$pass" "$fail"
[ "$fail" -eq 0 ]
