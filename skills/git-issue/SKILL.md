---
name: git-issue
description: 初めて見る人が質問せずに着手できる Issue 文を書く。題名は直し方ではなく症状、3 行の要約、背景と目的、起きていること（不具合は再現手順・期待する結果・実際の結果・頻度・環境）、確認方法つきの完了の条件、やらないこと、手がかり、用語、未確定の順。1 つの Issue に 1 つの問題、優先度は書かない。tmp/ISSUE_<日付>_<件名>.md に書いて止まり、起票は社長の承認を得てから行う。Use when creating or updating GitHub issues or tickets, turning review findings or postmortem actions into tickets, or splitting large work into child issues. Triggers: Issue, イシュー, チケット, 起票, チケットを切る, 課題を作る, タスク化, 子 Issue, GitHub issue.
---

# git-issue — 初めて見る人が、質問せずに着手できる Issue

## いつ使うか

不具合・機能の要望・調査の依頼を GitHub の Issue にするときに使う。レビューや障害の振り返りで出た対応をチケットにする場面、大きな仕事を子 Issue に分ける場面も同じである。既にある Issue を、読んで着手できる形に直すときにも使う。

## 先に読むもの

- `references/issue-form.md`（型と、節ごとの根拠。Mozilla のバグ報告の指針と GitHub の Issue フォーム）。
- `templates/issue-template.md`（Markdown の雛形）。GitHub のフォーム（`templates/*.yml`）は、リポジトリに置けるときだけ使う。
- `examples/issue-example.md`（完成例。注文一覧で期間を 1 年にすると 9 秒かかる不具合）。
- `.company/rules/writing.md` と `.company/rules/documents.md`。他のプロジェクトでは `tmp/.company/rules/`。

## 判断の観点

1. 読み手は誰か。新人、運用の担当、他のチームの人が、質問せずに着手できるか。知っている前提で書かない。
2. 症状か、直し方か。題名と「起きていること」は症状を書く。直し方の見当は「手がかり」に、見当（未確認）と印を付けて分ける。
3. 終わりが判定できるか。完了の条件は 1 行 1 条件で、全行に「誰が何をすれば判定できるか」がある。判定できない条件は書き直す。
4. 1 つか。1 つの Issue に 1 つの問題。2 つ目が混ざったら、別の Issue にする。
5. 数字は本物か。件数や時間は出どころと日付を書く。架空なら「架空」と 1 文で書く。優先度は書かない。

## 手順

1. 材料を集める。誰が、どの場面で、何に困っているか。件数と時間と出どころ。不具合なら、自分で再現して手順と頻度と環境を記録する。終わりの印: 背景の表と再現の記録が手元にある。
2. 題名を決める。起きている症状を 60 字以内で。終わりの印: 題名に「直す」「修正」の語が無い。
3. `templates/issue-template.md` を `tmp/ISSUE_<日付>_<件名>.md` に写し、上から埋める。`<…>` を 1 つも残さない。終わりの印: 全節に本文があり、完了の条件の全行に確認方法がある。
4. `scripts/issue-check.sh <ファイル>` と `tools/check-file.sh <ファイル>`（他のプロジェクトでは `tmp/tools/check-file.sh`）を通す。終わりの印: どちらも `RESULT: PASS`。
5. `skills/ja-fluent/scripts/fluency-check.sh <ファイル>` を通し、文の運びを直す。終わりの印: `RESULT: PASS`。
6. 別コンテキスト（Claude Code は `editor`、Cursor は新しいチャット）に Issue だけを渡し、「何をすれば終わりか」「最初に何をするか」を答えさせる。終わりの印: 2 問とも Issue の文だけで正答。
7. ファイルのパスを報告して止まる。起票（`gh issue create`）は社長の承認を得てから行う。

## 出力と受け渡し

| 成果物 | 置き場 | 渡す先 |
|---|---|---|
| Issue 文 | `tmp/ISSUE_<日付>_<件名>.md` | 秘書が門で検査し、社長に出す。承認後に起票 |
| 子 Issue の一覧 | 親の Issue 文の「手がかり」の下に表で | 同上 |

My-Lab では `.github/ISSUE_TEMPLATE/` のフォームが GitHub の新規作成の画面に出る。他のプロジェクトではフォームを置けないので、Markdown の雛形で書き、本文を貼る。

## 禁止

- 優先度（優先度、P0、高優先、緊急度）を書くこと。優先は社長が決める。
- 題名に直し方を書くこと。症状を書く。
- 確認方法の無い完了の条件を書くこと。
- 見当を事実のように書くこと。見当は「見当（未確認）」と印を付ける。
- 2 つ以上の問題を 1 つの Issue に入れること。
- 社長の承認なしに `gh issue create` を実行すること。ファイルに書いて止まる。

## 提出前の確認

1. `bash skills/git-issue/scripts/issue-check.sh <ファイル>` が PASS（必須の節、確認方法、優先度の語、不具合の 4 点、`<…>` の残り）。
2. `bash tools/check-file.sh <ファイル>` が PASS（文体、資料の型）。
3. `bash skills/ja-fluent/scripts/fluency-check.sh <ファイル>` が PASS。
4. 別コンテキストの読み手テスト 2 問に正答。
