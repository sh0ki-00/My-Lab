# 完了報告: 段階 0 の機械の層（hooks・検証の道具・配置）

> **3 行でわかる要約**
> 1. 段階 0 のうち、hooks（コマンドの直前と編集の直後に走る検査）、検証の道具、他のプロジェクトへの配置を作り終えました。
> 2. 受け入れ条件 7 件は全部に確認コマンドと結果があり、未確認は実機が要る 2 件です。
> 3. 記録と未確認の 2 件を見て、段階 0 の確認と、実機での確認をお願いします。

## 1. 受け入れ条件

7 件とも、2026-11-06 に My-Lab の root で実行した結果の抜粋です。

| # | 条件 | 確認コマンド | 結果 |
|---|---|---|---|
| 1 | 承認なしの commit・push・Issue と PR の作成が、判定本体で確認（ask）になり、合図の語を AI が付けると拒否になる | `bash hooks/selftest.sh` | `RESULT: PASS hooks の自己試験 158 PASS / 0 FAIL` |
| 2 | 使い捨てのリポジトリに `deploy.sh` を流すと `tmp/` に揃い、git に入らず、`install.sh` が常時ルールに書き込まない | `bash tools/placement-test.sh` | `RESULT: PASS placement-test (0 件)` |
| 3 | 見本アプリが、Lighthouse（Google の性能測定）の性能 90 以上、axe（アクセシビリティ検査）の違反 0 | `node tools/sample-app-test.mjs` | `RESULT: PASS axe (違反 0、確認 38 項目)`、`RESULT: PASS lighthouse (性能 100、アクセシビリティ 100、ベストプラクティス 96)` |
| 4 | 仕様書の図 10 枚が、ブラウザで実際に描ける | `node tools/render-mermaid.mjs docs/SPEC_20261106_company-skills.md` | `RESULT: PASS render-mermaid (10 図、0 件)` |
| 5 | すべての Markdown が、文体・資料の型・図の検査を通る | `bash tools/verify-all.sh --fast` | `RESULT: PASS 2 文体・資料・図 (1 秒)` |
| 6 | Issue のフォーム 3 つが、必須の項目を 3 個以上持ち、GitHub の形式として読める | `bash tools/check-file.sh .github/ISSUE_TEMPLATE/*.yml` | `check-issue-form … bug.yml (0 件、必須 9 個)`、`feature.yml (0 件、必須 6 個)`、`investigation.yml (0 件、必須 5 個)` |
| 7 | 試作スキル `verify` の試験ケースが、正例を通し負例を落とす | `bash skills/verify/evals/run.sh` | `RESULT: PASS evals verify (3/3)` |

## 2. 直したこと

検証の FAIL を 4 件直しました。どれも検査が見つけたもので、人の目では見落としていました。

| 場所 | 何を | なぜ |
|---|---|---|
| `tools/render-mermaid.mjs` | 描いた図の確認を、XML としての読み取りから、画面に置いて大きさを測る方法に変えた | 図の中の `<br/>` を XML の誤りと数え、正しい図 8 枚を落としていた |
| `tools/sample-app-test.mjs` | キーボードの試験を、画面を読み直してから最初の Tab を押す形にした | 直前の操作で焦点が選択欄に残り、試験の前提が崩れていた |
| `tools/placement-test.sh` | 配置の試験で使う見本の文書に、3 行の要約と目的の節を足した | 写した `check-file.sh` が、資料の型の検査で正しく落としていた |
| `tools/lib/check_ja.py` | 文末の 4 連続の数え方を、「〜ます」は直前の 1 字を含めて見る形にした | 「書きます」「足します」の違いを同じ文末と数え、仕様書を 12 か所で落としていた |

## 3. 未確認

2 件です。どちらも、社長の手元の実機でしか確かめられません。

| 条件 | 理由 | 確かめ方 |
|---|---|---|
| Cursor で `ask` と `stop` が効く | Cursor の hooks は、スクリプトからは呼べない | My-Lab を Cursor で開き、「commit して」で確認が出るか、文書を直して終えると検証が走るかを見る（README の 8 節） |
| Claude Code で commit が確認で止まり、承認で通る | commit は社長の承認が要るので、まだ 1 度も行っていない | 社長が最初の commit を承認する場面で、確認ダイアログが出ることを見る |

## 4. 検証の記録

`--full` の記録は `docs/verify/2026-11-06.md` にあります。hooks が自動で回した `--fast` の結果は `tmp/.verify/last-fast.txt`、各検証の詳しい出力は `tmp/.verify/verify-full.log` にあります。
