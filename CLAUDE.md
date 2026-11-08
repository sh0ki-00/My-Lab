@AGENTS.md

# Claude Code だけの決まり

- `git commit`・`git push`・`gh pr create`・`gh issue create` は、hooks と `.claude/settings.json` の `permissions.ask` の二重で確認ダイアログになる。社長が承認したものだけが実行される。
- 役割の仕事はサブエージェント（`.claude/agents/`）に渡す。サブエージェントは会話の履歴を持たないので、依頼文に題材・入力ファイル・出力先を全部書く。
- 文書を出す前の添削と読み手テストは、`editor` サブエージェントに文書だけを渡す。書いた本人に添削させない。
- ファイルを直すと `hooks/claude-postedit.sh` がそのファイルの検査を回し、作業を終えるときは `hooks/claude-stop.sh` が `tools/verify-all.sh --fast` を回す。FAIL が出たら直してから終える。
- `hooks/` と `.claude/settings.json` は編集しない。直す必要があれば、差分を社長に示して止まる。
