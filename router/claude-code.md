# Claude Code への接続

Claude Code は、My-Lab の中では `CLAUDE.md`（`AGENTS.md` を取り込む 1 行）と `.claude/` を読み、他のプロジェクトでは `~/.claude/CLAUDE.md` と Mac 全体の hooks（コマンドの直前と編集の直後に走る検査）を使う。
この文書は、どこに何を登録し、どう確かめるかだけを書く。判定の中身は `hooks/guard-core.sh`、検証の中身は `tools/verify-all.sh` にある。
この文書が指す `hooks/`・`.claude/`・`router/` は正本（My-Lab）にだけある。移した先の `tmp/` には写さない。

## 1. My-Lab の中

| 何 | どこ | 役目 |
|---|---|---|
| 常時ルール | `CLAUDE.md` → `AGENTS.md` | 秘書の起動、読む順、返答の書き方、守りの表 |
| 承認の規則 | `.claude/settings.json` の `permissions.ask` | `git commit`・`git push`・Issue と PR の作成を確認ダイアログにする（2 重の守りの 1 つ目） |
| hooks | `.claude/settings.json` の `hooks` | `PreToolUse`（Bash は判定本体で ask/deny。Write・Edit は守りの設定と hooks の登録なら deny）、`PostToolUse`（直したファイルの検査）、`Stop`（返答の言い換えの書き直しと、`verify-all.sh --fast`。検証は Write・Edit で書いたセッションだけ。FAIL なら終われない） |
| スキル | `.claude/skills` → `../skills` | `/名前` で呼べる |
| サブエージェント | `.claude/agents/` | 役割の仕事と、別コンテキストの添削（`editor`） |

承認の流れは 2 重である。hooks の判定本体が「ask」を返し、同じコマンドを `permissions.ask` も捕まえる。どちらか一方が外れても、もう一方が確認ダイアログを出す。社長が承認したものだけが実行される。

## 2. 他のプロジェクト（Mac 全体に 1 回登録）

`./install.sh` が `~/.claude/settings.json` に、この正本の hooks を `--global` 付きで登録する。登録する前に退避ファイル（`settings.json.bak.<日時>`）を作り、旧 cradle の登録は外し、他の設定は残す。常時ルール（`~/.claude/CLAUDE.md`）には書き込まない。

| hooks | 他のプロジェクトでの働き |
|---|---|
| `hooks/claude-pretooluse.sh --global` | どのプロジェクトでも `git commit` などを ask にする。commit 文・PR 文・Issue 文の git の語の言い換えは deny、クラウドにつなぐコマンドは ask にする。プロジェクト自身の登録があるときは、理由を省いて判定だけ返す（確認の文が 2 回出ない） |
| `hooks/claude-preedit.sh --global` | どのプロジェクトでも、Write・Edit で `~/.cursor/`・`~/.claude/settings.json`・`~/.claude/hooks/`・`~/.claude/CLAUDE.md`・守りの設定の置き場（`/usr/local/etc/company-guard/`）・My-Lab の `hooks/` と登録を書かせない（deny） |
| `hooks/claude-postedit.sh --global` | `tmp/tools/check-file.sh` があれば、直したファイルを検査する |
| `hooks/claude-stop.sh --global` | 返答に git の語の言い換えがあれば、検証より先に書き直させる（書き直しと検証の差し戻しを合わせて 3 回まで）。`tmp/tools/project-verify.sh` があれば、そのセッションが Write・Edit で書いた文書だけを渡して回す。何も書いていないセッションと、文書が 0 本で `tmp/verify-commands.txt` も無いときは回さない |

作業の終わりの検証は、hooks とは別に AI が自分で回す。命令は `bash tmp/tools/project-verify.sh --fast <このセッションで書いた文書>` で、引数で渡した文書だけを検査する。何も検査しない回は WARN（終了コード 3）で終わる。Bash のコマンドで書いた文書も、自分で引数に入れる。終わりの検証と添削には、ほかのセッションが書いた文書を入れない（開いて検査しない）。

常時ルールの本文は、`router/cursor-user-rule.md`（移した先では `tmp/cursor-user-rule.md`）の「貼る本文」と同じものを `~/.claude/CLAUDE.md` に社長が貼る。Claude Code は `~/.claude/CLAUDE.md` を全プロジェクトで読む。

読む順の 4 つ目は、プロジェクトの地図の入口 tmp/catchup/index.md（キャッチアップで作る）である。あれば読み、依頼が触る節のファイルだけを開き、地図は書き換えない。地図が無いか、触る節が古い（`bash tmp/skills/catchup/scripts/map-check.sh --fresh` の SECTION の行）ときは、最初の返答で 1 行伝え、依頼はそのまま進める。キャッチアップは、頼まれたときだけ `tmp/skills/catchup/SKILL.md` で回す。

## 3. 確かめ方

1. `bash hooks/selftest.sh` が `RESULT: PASS` を出す（判定表と、両ツールの hooks の端から端）。
2. Claude Code で `/hooks` を開き、`PreToolUse`（Bash と Edit の 2 本）・`PostToolUse`・`Stop` に `hooks/claude-*.sh` が見える。
3. Claude Code に「`git status` を実行して」と頼むと止まらず、「`git commit` して」と頼むと確認ダイアログが出る。承認しなければ実行されない。
4. 文書を 1 つ直して終えると、`verify-all.sh --fast` が自動で回る。FAIL を仕込めば、Claude Code が「直してから終える」と続ける。

## 4. 外し方

`~/.claude/settings.json` を退避ファイルから戻す。`.claude/settings.json` はリポジトリの中なので、消せば My-Lab の中の登録が外れる。
