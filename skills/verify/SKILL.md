---
name: verify
description: 作業の最後に検証を全部回し、結果を読み、FAIL を直し、証拠つきの完了報告を書く。tools/verify-all.sh（My-Lab）か tmp/tools/project-verify.sh（他のプロジェクト）の結果と docs/verify/<日付>.md の記録を、受け入れ条件ごとの確認コマンドと結果に対応づける。Use at the end of any implementation or document work, before writing 完了・確認済み・動作確認, before asking for commit approval, and whenever a verification FAILs. Triggers: 検証, verify, 完了報告, 確認済み, 動作確認, 証拠, FAIL を直す, commit の前.
---

# verify — 検証を回し、証拠つきの完了報告を書く

## いつ使うか

実装や文書の作業を終えるとき、「完了」「確認済み」「動作確認」と書く前、commit の承認を求める前、検証が FAIL したとき。hooks（コマンドの直前と編集の直後に走る検査）が自動で回した結果を読むときも使う。

## 先に読むもの

- `.company/rules/evidence-and-safety.md`（証拠の決まり）。他のプロジェクトでは `tmp/.company/rules/evidence-and-safety.md`。
- `references/checks.md`（11 種類の検証の読み方と、FAIL の直し方）。
- `references/report-format.md`（完了報告の型。受け入れ条件と確認コマンドと結果の対）。

## 判断の観点

1. 回したか。検証を回さずに「完了」と書くのが、最も多い失敗である。結果の行（`RESULT:`）が無ければ、回していない。
2. SKIP が無いか。道具が無いことによる SKIP は FAIL と同じに扱う。入れ直すか、社長に伝えて止まる。
3. 条件ごとに対になっているか。受け入れ条件 1 件に、確認コマンド 1 つと結果 1 行。対が無い条件は「未確認」に理由を付けて書く。
4. 直し方が原因に向いているか。検査を緩めて通すのは直したことにならない。検査が間違っているなら、その理由を記録に残して社長に伺う。
5. 記録を指しているか。報告は `docs/verify/<日付>.md` の記録を指す。他のプロジェクトでは `tmp/.verify/last-fast.txt` か `tmp/.verify/last-full.txt` を指す。

## 手順

1. 回す。My-Lab では `bash tools/verify-all.sh --fast`、commit の前は `--full`。他のプロジェクトでは `bash tmp/tools/project-verify.sh --fast`、commit の前は `--full`。終わりの印: `RESULT: PASS|FAIL verify-all` か `RESULT: … project-verify` の行が出る。
2. 読む。FAIL の行を上から順に `references/checks.md` の表に当て、原因の種類（文体・形式・図・スクリプト・配置・依存）を決める。終わりの印: FAIL ごとに直す場所が 1 つ決まる。
3. 直す。原因の場所を直し、その 1 ファイルを `tools/check-file.sh <ファイル>` で確かめ、手順 1 に戻る。終わりの印: 全体が PASS。3 回直しても通らないなら、検査の誤りか要件の矛盾を疑い、記録を付けて社長に伺う。
4. 対にする。受け入れ条件の表を作り、1 件ごとに確認コマンドと結果の抜粋を書く。確かめられない条件は「未確認（理由）」と書く。終わりの印: 表の全行に結果か理由がある。
5. 書く。`templates/completion-report.md` の型で `tmp/flow/<件名>/completion-report.md` に完了報告を書き、`scripts/report-check.sh <報告>` を通す。終わりの印: `RESULT: PASS report-check`。
6. 出す前に、別コンテキストに報告だけを渡し、読み手テストを受ける。My-Lab では `editor` サブエージェントに渡す。他のプロジェクトの Claude Code では組み込みの general-purpose サブエージェントに渡し、Cursor では読み手の役に切り替える。終わりの印: 判定が「出せる」。

## 出力と受け渡し

| 成果物 | 置き場 | 渡す先 |
|---|---|---|
| 検証の記録 | `docs/verify/<日付>.md`（`verify-all.sh --full` が自動で書く）。他のプロジェクトでは `tmp/.verify/last-fast.txt` と `tmp/.verify/last-full.txt`（`project-verify.sh` が書く） | 完了報告から指す |
| 完了報告 | `tmp/flow/<件名>/completion-report.md` | 秘書が門で検査し、社長に出す |
| 直した記録 | 完了報告の「直したこと」の表 | 次の作業の手がかり |

## 禁止

- 検証を回さずに「完了」「確認済み」「動作確認」と書くこと。
- SKIP を PASS と数えること。道具が無いなら FAIL と同じに扱う。
- 検査を緩めて通すこと。検査の誤りは記録に残して社長に伺う。
- 測っていない数値や、実行していない検証の結果を書くこと。「動くはず」「と思われる」を報告に書くこと。
- `git commit`・`git push`・Issue と PR の作成を、社長の承認なしに行うこと。報告はファイルに書いて止まる。

## 提出前の確認

1. `bash tools/verify-all.sh --fast`（他のプロジェクトでは `bash tmp/tools/project-verify.sh --fast`）が PASS。
2. `bash skills/verify/scripts/report-check.sh <完了報告>` が PASS。
3. 別コンテキストの読み手テスト（My-Lab では `editor`）で判定が「出せる」。残した指摘には理由を添える。
