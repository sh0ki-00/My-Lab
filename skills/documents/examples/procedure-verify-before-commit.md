# My-Lab 検証から commit 承認まで 作業手順書

| 項目 | 内容 |
|---|---|
| 作業名 | 直したファイルの検査、全体の検証、完了報告、commit の承認伺い |
| 対象システム | My-Lab（作業ブランチ） |
| 対象の部品 | 直したファイル、`docs/verify/` の記録、`tmp/flow/<件名>/completion-report.md` |
| 作業区分 | 定期（作業を終えて commit の承認を伺うたび） |
| 作業者 / 確認者 | 秘書か役割 / 社長 |
| 承認 | 社長。チャットの言葉（「承認」「進めて」「OK」「それでいこう」） |
| 所要時間 | 未実測（`verify-all.sh --full` だけは 2026-11-10 の記録で 231 秒） |
| 影響範囲 | 利用者には無い。書くのは `docs/verify/` の記録と `tmp/` の完了報告だけ |
| 関係者と連絡経路 | 社長（チャット） |
| 様式 | My-Lab に既存の手順書が無いので、`templates/procedure.md` の雛形を使った |
| 版 | 1.1（2026-11-11。資料の型から現場の文書の型に直した） |

## 1. 目的

commit の承認を伺う前に、直したファイルの検査と全体の検証を回し、記録と完了報告を残す。検証を回さずに「完了」と書かず、範囲外のファイルにも手を出さない。写した先の検証は `tmp/tools/project-verify.sh` が受け持つので、この手順書は My-Lab だけで使う。

## 2. 前提条件

- 作業ブランチにいる（main ではない）。
- 承認伺いに書いた、直すファイルの一覧がある。
- 検証に使う道具が入っている。jq、node、python3、shellcheck（シェルの台本の検査）、gitleaks（秘密の漏れの検査）、trivy（依存の穴の検査）、semgrep（コードの決まりの検査）の 7 つ。
- 文字の設定 ja_JP.UTF-8 がある。
- hooks（コマンドの直前と編集の直後に走る検査）が入っている。

## 3. 注意事項

- 直すのは、承認伺いの一覧にある自分が変えたファイルだけ。触っていないファイルの FAIL は直さず、完了報告の「未確認」に書く（`.company/CLAUDE.md` の 4 節と 7 節）。
- `--fast` の記録は `tmp/.verify/` に残るだけで、commit の承認には `docs/verify/` の記録が要る。だから 5-2 は `--full` で回す（`skills/verify/SKILL.md` の手順 1）。
- `FAIL` の行の `[道具が無い]` は、道具が無いことによる SKIP である。PASS と数えると、検査していない物を「確認済み」と書いてしまう。FAIL と同じに扱う（`skills/verify/SKILL.md` の判断の観点 2）。
- FAIL の行は `FAIL <ファイル>:<行> [<決まり>] <内容>` の形で、[ ] の中が落ちた決まりの名前である。決まりごとの直し方は `skills/verify/references/checks.md` の 2 節にある。
- gitleaks・trivy・semgrep の FAIL にはファイル名が無い。`tmp/.verify/` の gitleaks.err、trivy.out、semgrep.out を読んで、自分の変更かを決める。
- 測っていない数値と、実行していない検証の結果は書かない。
- commit、push、Issue と PR の作成は、社長の承認の言葉が出るまで行わない。

## 4. 事前確認

| # | 確認項目 | 確認方法 | 期待結果 |
|---|---|---|---|
| 1 | 作業ブランチ | `git branch --show-current` | main 以外の名前が返る |
| 2 | 道具 7 つ | `command -v jq node python3 shellcheck gitleaks trivy semgrep` | 7 行返る |
| 3 | 文字の設定 | `locale -a` | ja_JP.UTF-8 の行が出る |
| 4 | hooks の自己試験 | `bash hooks/selftest.sh` | 最後の行が `RESULT: PASS hooks の自己試験` で始まる |

## 5. 作業手順

### 5-1. 直したファイルを検査する

1. 直したファイルの一覧を出す。
   ```sh
   git status --short
   ```
   - 期待結果: 出た行が、承認伺いの一覧のファイルだけ。知らないファイルがあれば 6-1 の 1 へ。
2. 直したファイルを 1 本ずつ検査する。
   ```sh
   bash tools/check-file.sh <ファイル>
   ```
   - 期待結果: `RESULT:` の行が全部 PASS。`[道具が無い]` があれば 6-1 の 4 へ、それ以外の FAIL は 6-1 の 2 へ。

### 5-2. 全体の検証を回し、記録を残す

1. 全体の検証を `--full` で回す。
   ```sh
   bash tools/verify-all.sh --full
   ```
   - 期待結果: `RESULT: PASS verify-all --full` で始まる行が出て、次の行に記録のパスが出る。FAIL は 6-1 の 2 か 3 へ。
2. 今日の記録が `docs/verify/` に書かれたことを確かめる。
   ```sh
   ls docs/verify/ | tail -n 1
   ```
   - 期待結果: 今日の日付のファイル名が出る。出なければ 6-1 の 5 へ。

### 5-3. 完了報告を書き、承認を伺う

1. 完了報告を `skills/verify/templates/completion-report.md` の型で書く。
   - 期待結果: `tmp/flow/<件名>/completion-report.md` に、受け入れ条件ごとの確認コマンドと結果の対がある。
2. 完了報告を report-check（完了報告の形の検査）に通す。
   ```sh
   bash skills/verify/scripts/report-check.sh tmp/flow/<件名>/completion-report.md
   ```
   - 期待結果: `RESULT: PASS report-check` で始まる行が出る。FAIL は 6-1 の 6 へ。
3. 完了報告のパスと次の文面をチャットに貼り、commit の承認を伺う。数値は記録から写し、測っていない数値は書かない。
   ```text
   ## 検証の結果
   - 完了報告: tmp/flow/<件名>/completion-report.md
   - 回した命令: bash tools/verify-all.sh --full
   - 結果: RESULT: で始まる行をそのまま貼る（記録は docs/verify/<日付>.md）
   - 直したファイル: 承認伺いの一覧と同じ
   - 未確認: 無し（あれば、ファイルと FAIL の行）
   ```
   - 期待結果: 社長の言葉に「承認」「進めて」「OK」「それでいこう」のどれかがある。無ければ commit せずに待つ。

### 5-4. 片付け

1. 作業中に `tmp/` の外へ作った一時ファイルを消す。`tmp/flow/` の成果物と `tmp/.verify/` の記録は残す。
   ```sh
   git status --short
   ```
   - 期待結果: 承認伺いの一覧に無いファイルが出ない。出たら、自分が作ったものだけを消して、この 1 をやり直す。

## 6. 異常時の処置

### 6-1. 判断

| 番号 | 兆候 | 処置 |
|---|---|---|
| 1 | `git status` に知らないファイルが出る | 自分の変更でなければ触らず、名前を控えて 5-3 の 1 で「未確認」に書く。自分の変更で承認の範囲外なら 6-2 へ |
| 2 | 自分が直したファイルで FAIL | FAIL の行が指す場所を直し、5-1 の 2 へ。3 回直しても通らなければ、検査の誤りを疑って社長に伺う |
| 3 | 触っていないファイルで FAIL | 直さない。ファイルと FAIL の行を控えて 5-2 の 2 へ進み、5-3 の 1 で「未確認」に写す。文面の結果は `RESULT: FAIL` のまま貼る |
| 4 | `FAIL` の行に `[道具が無い]` がある | FAIL と同じに扱う。道具の名前を社長に伝えて止まる |
| 5 | 今日の記録のファイルが出ない | `tmp/.verify/verify-full.log` の末尾を読む。FAIL があれば 2 か 3 へ。無ければ 5-2 の 1 へ戻って回し直す |
| 6 | 完了報告の report-check が FAIL | FAIL の行の [ ] が指す所（表題、要約、受け入れ条件、直したこと、未確認、検証の記録、根拠、推測の語）を直し、5-3 の 2 へ |

### 6-2. 切り戻し

1. 承認の範囲外で変えた、追跡中のファイルを元に戻す。
   ```sh
   git restore <ファイル>
   ```
   - 期待結果: `git status --short` にそのファイルの行が出ない。
2. 承認の範囲外で作った新しいファイル（`??` の行）を消す。
   - 期待結果: `git status --short` に `??` の行が出ない。消したら 5-1 の 1 へ戻る。

## 7. 作業記録

```text
- 実施日時:
- 実施者 / 確認者:
- 対象ブランチと件名:
- 直したファイル:
- check-file の結果: RESULT: の行を貼る
- verify-all --full の結果: RESULT: の行と docs/verify/<日付>.md のパス
- 完了報告: tmp/flow/<件名>/completion-report.md
- 承認の言葉（原文）:
- 異常と処置:
```
