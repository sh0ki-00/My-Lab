# 教授の解説の型

> **3 行でわかる要約**
> 1. 社長の問いに答える解説の 8 段と、段ごとの根拠をまとめた参考資料です。8 段は、問いの言い直し・答え・全体像・用語・仕組み・例・手順・確認の問いです。
> 2. 問いの型で 4 段（短答・解説・講義・作業報告）から選び、解説の本文は 40 行までにします。
> 3. 書くときは `templates/explanation.md` を写し、`scripts/explain-check.sh` で型を機械で確かめます。

## 1. 8 段の順と根拠

読み手は上から読み、答えが見えないと読むのをやめます。だから答えを先に置き、理由と例を後ろに続けます。

| # | 段 | 書くこと | 根拠 |
|---|---|---|---|
| 1 | 問いの言い直し | 「ご質問は 2 点ですね。(1) …、(2) …」。2 通りに読めるなら、どちらと解釈したかを書く | 文化庁『公用文作成の考え方』（読み手が知りたいことを想像して書く） |
| 2 | 答え | 問いの番号ごとに、はい・いいえ・数値・名前を含む 1〜2 文。前置きを置かない | 同（結論は早めに示し、続けて理由や詳細）、Microsoft（Get to the point fast） |
| 3 | 全体像 | 今と直した後の対比など、部品と関係を 1 枚で。図は描画できる画面だけ、端末では表か 3 行の文 | Sweller の認知負荷理論（図と文を離さない） |
| 4 | 用語 | 初出の専門語を、意味と正式な語（英語）の表に。正式な語は調べる手がかり | 公用文（専門用語は言い換えるか説明を付ける）、Julia Evans（専門語は検索の手がかり） |
| 5 | 仕組み | なぜそうなるかを 1 段落。読み手が持っていそうな誤った前提を 1 行で否定する | Diátaxis（解説は理解のための文書）、CMU（既有知識は助けにも妨げにもなる） |
| 6 | 例 | 業務の場面と数字で。架空なら「架空」と書く。比喩は 1 つの考えにだけ | Sweller（完成した例から学ぶ）、Feynman（身近な例で照らす） |
| 7 | 手順 | 案の比較と推奨 1 つ、番号つきの手順、承認の一言 | 秘書の型（選択肢だけ並べて終わらない） |
| 8 | 確認の問い | 「一番分かりにくかった所は」を 1 つだけ。答えで次の水準を決める | Angelo と Cross の「最も曖昧な点」、Bloom の形成的テスト |

## 2. 4 段の選び方

同じ内容を二重に出すと害になるので（Sweller の冗長の効果）、問いの型で長さを決めます。

| 段 | 選ぶ合図 | 長さ | 検査 |
|---|---|---|---|
| 短答 | 「一言で」「短く」「要るの？」 | 3 文以内。図も表も無し | `explain-check.sh --profile short` |
| 解説 | 「なぜ」「どうして」「仕組み」「違い」「分からない」 | 本文 40 行まで（表・図・見出し・空行を除く）。60 行で WARN | `explain-check.sh` |
| 講義 | 「資料にして」「まとめて」 | `.company/rules/documents.md` の型でファイルに。解説の節を「## 解説」にする | `explain-check.sh` と `check-doc.sh` |
| 作業報告 | 作業を終えたとき | 答え（何が変わったか 1 文）、全体像（変えた場所の表）、仕組み（なぜそう変えたか）、確認（読み手が次にすること）。証拠の対は `skills/verify` の完了報告の型 | `explain-check.sh --profile report` |

## 3. 長さの数え方

解説の本文の行は、表・図・見出し・空行を除いて数えます。`examples/example-n-plus-one.md` の解説は、この数え方で 17 行です。

## 4. 出典

型の根拠にした一次情報です。URL は 2026-11-05 に開いて中身を確かめました。

| 出典 | 確かめた内容 | URL |
|---|---|---|
| 文化審議会『公用文作成の考え方』2022 | 結論は早めに、専門用語の 3 通りの扱い、外来語、一文を短く | https://www.bunka.go.jp/seisaku/bunkashingikai/kokugo/hokoku/pdf/93651301_01.pdf |
| Sweller ほか, Cognitive Architecture and Instructional Design: 20 Years Later, 2019 | 完成した例、図と文を離さない、上級者への逆効果、冗長 | https://link.springer.com/article/10.1007/s10648-019-09465-5 |
| Diátaxis, Explanation | 解説は理解のための文書。背景、設計の理由、制約、例 | https://diataxis.fr/explanation/ |
| Julia Evans, Patterns in confusing explanations, 2021 | 分かりにくい説明の 13 の型 | https://jvns.ca/blog/confusing-explanations/ |
| D. Goodstein, Richard P. Feynman, Teacher, Physics Today, 1989 | 新入生の水準に落とせない説明は理解していない。身近な例 | https://aip.brightspotcdn.com/PTO.v42.i2.70_1.online.pdf |
| CMU Eberly Center, Principles of Learning | 既有知識は助けにも妨げにもなる | https://www.cmu.edu/teaching/principles/learning.html |
