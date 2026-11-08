---
name: git-pr
description: 差分を読まなくても「何を・なぜ・どう確かめたか」が分かる PR 文を書く。題名は Conventional Commits の型（fix・feat など）と命令形で 60 字以内、3 行の要約、関連 Issue、背景と目的、変えたこと、方針（採用と却下の表）、影響、検証（実行した事実だけ）、レビューの観点、リリースと戻し方、用語。1 つの PR は 1 つの目的、400 行を超えたら分ける。tmp/PR_<番号>.md に書いて止まり、PR の作成は社長の承認を得てから行う。Use when writing or updating a pull request description, requesting review, or before merging. Triggers: PR, PR 文, プルリク, プルリクエスト, レビュー依頼, マージ前, PR を書いて, 説明文.
---

# git-pr — 差分を読まなくても、何を・なぜ・どう確かめたかが分かる PR

## いつ使うか

変更を PR（プルリクエスト。差分をレビューしてもらう依頼）にするときに使う。既にある PR の説明文を直す場面、レビューを頼む前、マージ（取り込み）の前も同じである。PR の文は何年も後に何百人もが読む記録になるので、差分だけでは分からない「なぜ」を残す。

## 先に読むもの

- `references/pr-form.md`（型と、節ごとの根拠。Google のコードレビューの指針、Kubernetes の PR の型、Conventional Commits）。
- `templates/pr-template.md`（雛形。My-Lab では `.github/pull_request_template.md` と同じ中身）。
- `examples/pr-example.md`（完成例。注文一覧を、画面に出す分だけ読む作りに変える PR）。
- `.company/rules/writing.md` と `.company/rules/evidence-and-safety.md`。他のプロジェクトでは `tmp/.company/rules/`。

## 判断の観点

1. 1 つか。1 つの PR は 1 つの目的に絞る。整理のための変更（名前の付け替え、移動）は別の PR にする。差分が 400 行を超えたら分ける。
2. 差分に無いことを書いているか。何を変えたかは差分にある。なぜその案か、何を却下したか、何に影響するかは差分に無いので、ここに書く。
3. 証拠があるか。検証の節は、実行したコマンドと出た値だけを書く。「動くはず」は書かない。`verify-all.sh --full` の記録（`docs/verify/<日付>.md`）を指す。
4. 戻せるか。リリースの段階・見る指標・止める基準・戻す手順と所要時間が書けないなら、出せる状態ではない。
5. 読み手が探さずに済むか。レビュアーが重点的に見る所と読む順、利用者・データ・性能・セキュリティ・互換・他のチームへの影響を、本文に置く。

## 手順

1. 差分を読み直し、目的が 1 つか、400 行以内かを見る。終わりの印: 目的が 1 文で言え、`git diff --stat` の合計が 400 行以内（超えるなら分割の案を書く）。
2. 題名を決める。型（feat・fix・docs・refactor・perf・test・build・ci・chore）、対象、命令形の 1 文で 60 字以内。終わりの印: `fix(admin-orders): 〜を〜に変える` の形になっている。
3. `templates/pr-template.md` を `tmp/PR_<番号>.md` に写し、上から埋める。関連 Issue は `Closes #番号`。方針の表には却下した案と理由を必ず書く。終わりの印: `<…>` が 1 つも無い。
4. 検証を回し、結果を書く。`bash tools/verify-all.sh --full`（他のプロジェクトでは `bash tmp/tools/project-verify.sh --full`）と、完了の条件ごとの確認。終わりの印: 検証の表の全行に、コマンドと出た値がある。
5. `scripts/pr-check.sh <ファイル> --diff-lines <行数>` と `tools/check-file.sh <ファイル>` を通す。終わりの印: どちらも `RESULT: PASS`。
6. `skills/ja-fluent/scripts/fluency-check.sh <ファイル>` を通し、文の運びを直す。終わりの印: `RESULT: PASS`。
7. 別コンテキスト（Claude Code は `editor`、Cursor は新しいチャット）に PR 文だけを渡し、「何を・なぜ・どう確かめたか・どこを見るか」の 4 問に答えさせる。終わりの印: 4 問とも PR 文だけで正答。
8. ファイルのパスを報告して止まる。PR の作成（`gh pr create`）と push は、社長の承認を得てから行う。

## 出力と受け渡し

| 成果物 | 置き場 | 渡す先 |
|---|---|---|
| PR 文 | `tmp/PR_<番号>.md` | 秘書が門で検査し、社長に出す。承認後に PR を作る |
| 分割の案（400 行超のとき） | PR 文の冒頭に「分割の案」の表 | 社長の判断 |

My-Lab では `.github/pull_request_template.md` が GitHub の作成画面に出る。他のプロジェクトでは雛形で書き、本文を貼る。コンフリクトを解消したなら、全件を「変えたこと」の表に開示する。

## 禁止

- 「AI が書いた範囲」の節を書くこと（社長の指示）。
- 実行していない検証を書くこと。「動くはず」「と思われる」を書くこと。
- 却下した案を書かずに、採用した案だけを書くこと。
- 2 つ以上の目的を 1 つの PR に入れること。整理のための変更を機能の変更に混ぜること。
- 関連 Issue のリンクだけを書き、要点を本文に書かないこと。リンク先は将来消える。
- 社長の承認なしに `gh pr create` と `git push` を実行すること。ファイルに書いて止まる。

## 提出前の確認

1. `bash skills/git-pr/scripts/pr-check.sh <ファイル> --diff-lines <行数>` が PASS（題名の型、関連 Issue、必須の節、却下した案、検証の証拠、戻し方、`<…>` の残り）。
2. `bash tools/check-file.sh <ファイル>` が PASS（文体、資料の型）。
3. `bash skills/ja-fluent/scripts/fluency-check.sh <ファイル>` が PASS。
4. 別コンテキストの読み手テスト 4 問に正答。
