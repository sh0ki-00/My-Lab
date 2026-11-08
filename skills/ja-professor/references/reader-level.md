# 読み手の見立て

> **3 行でわかる要約**
> 1. 解説を書く前に、読み手がどの語を知っているかで水準を見立て、その 1 段下の語で書く決まりです。
> 2. 役割（社長、新人）だけでは読み手を決められません。知っている語と知らない語の一覧（`reader-profile.md`）で決めます。
> 3. 目標は、中学校卒業程度の読み手が一度で読める文です。超える文には、用語の表と括弧の説明を付けます。

## 1. 3 つの水準

見立ては 3 つのどれかにし、見立てた水準の 1 段下の語で書きます。上級者に初心者向けの手当てをすると逆効果になるので、知っている語の説明は省きます。

| 水準 | 読み手の様子 | 書き方 |
|---|---|---|
| 語を知らない | 「N+1 って何」 | 用語の表を先に。例を 1 つ。手順は 3 つまで |
| 語は知るが仕組みを知らない | 「N+1 は聞いたが、なぜ起きるのか」 | 仕組みに重みを置く。用語の表は知らない語だけ |
| 仕組みを知り判断したい | 「案 A と B のどちらが良いか」 | 比較表と推奨を先に。仕組みは 1 段落 |

## 2. 見立ての問い

書く前に、3 つの問いに答えます。答えは解説の冒頭に 1 行だけ置き、残りは手元の記録に書きます。

1. 問いに出る語のうち、読み手が知らない語はどれか（`reader-profile.md` の「知っている語」に無い語）。
2. 読み手は、答えを聞いて何を決めるのか（承認、選択、理解だけ）。
3. 読み手が持っていそうな誤った前提は何か（例: 索引を足せば N+1 が直る）。仕組みの段で 1 行で否定する。

## 3. 読み手の記録

`tmp/flow/professor/reader-profile.md` に、知っている語と日付、つまずいた語、好む長さを表で持ちます。雛形は `templates/reader-profile.md` です。更新は `scripts/reader-profile-update.sh --known <語> --stuck <語>` で行い、文の解釈は人（エージェント）がします。90 日経った語は「要確認」に落とし、見立てに「ご存じなら読み飛ばしてください」を添えます。

## 4. 出典

見立ての決まりの根拠にした一次情報です。URL は 2026-11-05 に開いて中身を確かめました。

| 出典 | 確かめた内容 | URL |
|---|---|---|
| Google, Technical Writing One, Audience | 良い文書 = 読み手に必要な知識 − 読み手が既に持つ知識。役割だけでは不十分。知識の呪い | https://developers.google.com/tech-writing/one/audience |
| Sweller ほか 2019 | 初心者向けの手当ては上級者には逆効果（expertise reversal） | https://link.springer.com/article/10.1007/s10648-019-09465-5 |
| Wikipedia:Make technical articles understandable | 想定した読み手の 1 段下で書く。易しい部分を先に。単純化しすぎない | https://en.wikipedia.org/wiki/Wikipedia:Make_technical_articles_understandable |
| W3C WCAG 2.1, Understanding SC 3.1.5 Reading Level | 中等教育前期（中学校卒業程度）を超える文には補足を用意する | https://www.w3.org/WAI/WCAG21/Understanding/reading-level.html |
