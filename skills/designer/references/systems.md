# 数値の体系と WCAG 2.2 AA の見た目側

> **3 行でわかる要約**
> 1. 型・色・余白と密度・動きの 4 つの体系を数値で持ち、見た目側の WCAG 2.2 AA の 10 項目を、計画書で書く値と確かめ方にした文書である。
> 2. 下限は好みではなく標準で決める。文字は 4.5 対 1、部品は 3 対 1、文字の大きさは 12px 以上である。動きは 300ms 未満、押せる領域は PC で 24px、片手で 44px である。
> 3. 数値には出典のあるものと社内の決めごとがある。表で分けて書き、出典の無い数値を出典つきに見せない。

## 1. 型（書体）

書体は 1 家族 2〜3 役にし、階層は大きさと太さで作る。細い字と小さい字は長時間の作業で疲れる。

| 項目 | 値 | 出典か社内の決め |
|---|---|---|
| 役 | 本文、見出し、数字（等幅）の 2〜3 役。4 役以上は理由を書く | 社内の決め |
| 大きさの段 | 12、14、16、20、24px | 社内の決め（Material 3 の type scale を参考に 5 段へ） |
| 下限 | 補助の文字 12px。Apple の最小は iOS で 11pt、macOS で 10pt | Apple HIG、社内の決め |
| 太さ | 400 と 700 を主にする。300 以下は使わない | Apple HIG（細い太さを避ける） |
| 行間 | 1.5 | 社内の決め（WCAG 1.4.12 の間隔の試験にも耐える） |
| 数字 | 等幅数字（font-variant-numeric: tabular-nums） | Vercel の指針、Rauno Freiberg の指針 |

## 2. 色

色は知覚的に均等な色空間（Lab か LCH）で段を作り、段の差でコントラストを保証する。目で合わせた色は、色相ごとに明るさの感じ方がずれる。

| 項目 | 値 | 出典か社内の決め |
|---|---|---|
| 名前つきの色 | 4〜6 色。残りは導出（color-mix）で書く | 社内の決め（Linear は 3 変数からテーマを生成） |
| 本文の文字 | 4.5 対 1 以上 | WCAG 2.2 の 1.4.3 |
| 部品、大きい文字、焦点の枠 | 3 対 1 以上 | WCAG 2.2 の 1.4.11 |
| 装飾の線 | 対象外。ただし行の区切りは罫線に頼らない | WCAG 2.2 の 1.4.11 |
| 計算 | WCAG 2 の式で計算し、目で判定しない。`skills/designer/scripts/contrast-check.sh` | WCAG 2.2、Stripe の配色の記事 |
| ダーク版 | 反転ではなく、同じ名前を暗い側の色で上書きし、全組を計算し直す | 社内の決め |
| 強制カラー | 焦点の枠と印は outline と border で描く。box-shadow は消える | MDN の forced-colors |

## 3. 余白と密度

余白は 4px の倍数、密度は用事で決める。情報の塊は 1 画面に 7 つ以内に収める。

| 項目 | 値 | 出典か社内の決め |
|---|---|---|
| 余白の単位 | 4px の倍数（4、8、12、16、24） | 社内の決め |
| 表の行高 | 32〜40px。14px の文字なら 36px | 社内の決め |
| 情報の塊 | 1 画面に 7 つ以内 | 社内の決め |
| 角丸 | 2 段（部品 4px、面 8px） | 社内の決め |
| 影 | 1 光源で同じ比率の層。色は背景の色相で染める | Josh Comeau の影の記事 |
| 固定の帯 | scroll-padding で焦点を隠さない | WCAG 2.2 の 2.4.11 |

## 4. 動き

動きは意味のある場面だけに置き、キーボード起点と高頻度の操作は動かさない。時間と曲線はトークンで持つ。

| 項目 | 値 | 出典か社内の決め |
|---|---|---|
| 長さ | 300ms 未満。段は 80、120、180ms | Emil Kowalski（300ms 未満）、社内の決め（段） |
| 曲線 | 入りは ease-out。標準は cubic-bezier(0.2, 0, 0, 1) | Emil Kowalski、Material 3 の standard |
| 出る動き | 入りより短くする | 社内の決め |
| 動かす属性 | transform と opacity だけ。transition に all は使わない | Emil Kowalski、Vercel の指針 |
| 減らす設定 | prefers-reduced-motion で全部 0ms か不透明度だけ | MDN、WCAG 2.2 の 2.3.3（AAA だが社内で採る） |
| キーボード起点 | 0ms | Rauno Freiberg の指針 |
| 読み込み表示 | 150ms 待ってから出し、300ms は消さない | Vercel の指針 |

## 5. 見た目側の WCAG 2.2 AA

見た目で決まる達成基準を 10 項目にし、計画書で書く値と確かめ方を揃える。振る舞い側（拡大、リフロー、読み上げ、時間切れ、ステータスメッセージ）は画面仕様で見る。

| 達成基準 | 計画書で書く値 | 確かめ方 |
|---|---|---|
| 1.4.1 色の使用 | 色だけで伝える要素の数（0） | 白黒で印刷して読める |
| 1.4.3 コントラスト（最低限） | 文字の全組の最小の比 | `contrast-check.sh` |
| 1.4.11 非テキストのコントラスト | 部品と焦点の枠の比 | `contrast-check.sh` |
| 1.4.12 テキストの間隔 | 間隔を広げて欠ける要素の数（0） | 間隔を変える CSS を当てる |
| 1.4.13 ホバーまたはフォーカスで表示されるコンテンツ | Esc で消え、乗せても消えず、焦点を外すまで残る要素の数 | 要素ごとに 3 条件を試す |
| 2.1.4 文字キーのショートカット | オフにできる 1 文字キーの数 | 設定を切ってキーを押す |
| 2.4.7 フォーカスの可視化 | 枠の見えない要素の数（0）。outline で描く | Tab で全要素を通す。強制カラーでも見る |
| 2.4.11 フォーカスの非遮蔽（最低限） | 固定の帯に隠れる要素の数（0） | 帯の近くの要素に Tab で入る |
| 2.5.8 ターゲットのサイズ（最低限） | 最小の押せる領域（PC で 24px、片手で 44px） | DOM の寸法を測る |
| 2.3.3 動きの抑制（AAA。社内で採る） | 減らす設定で残る動きの数（0） | 設定を有効にして全場面を見る |

## 6. 押せる領域の決め

押せる領域は、入力の手段で下限を分ける。WCAG 2.2 の 2.5.8 の 24px は AA の下限で、Vercel の指針も PC では 24px、モバイルでは 44px を求める。

| 画面 | 下限 | 理由 |
|---|---|---|
| PC のポインタ前提の画面 | 24px 四方 | WCAG 2.2 の 2.5.8 と Vercel の指針 |
| 片手で使う画面（スマートフォン） | 44px 四方 | Apple HIG と Vercel の指針 |
| 両方で使う画面 | 幅で切り替える。狭い幅で 44px | 社内の決め |

## 付録: 出典

出典は、調査ブリーフの検証役が 2026-11-05 に本文を開いて確かめたものである。WCAG 2.2 は 2023-10-05 に勧告になり、2024-12-12 に改訂版が出た。

| # | 出典 | 使った節 |
|---|---|---|
| 1 | W3C「WCAG 2.2」 https://www.w3.org/TR/WCAG22/ 、2.5.8 と 2.4.11 の Understanding | 2、3、5、6 |
| 2 | Stripe「Designing accessible color systems」 https://stripe.com/blog/accessible-color-systems | 2 |
| 3 | Linear「How we redesigned the Linear UI」 https://linear.app/now/how-we-redesigned-the-linear-ui | 2 |
| 4 | Apple HIG「Typography」 https://developer.apple.com/design/human-interface-guidelines/typography 、「Motion」 https://developer.apple.com/design/human-interface-guidelines/motion | 1、4、6 |
| 5 | Material Components「Motion」 https://github.com/material-components/material-components-android/blob/master/docs/theming/Motion.md 、「Typography」 https://github.com/material-components/material-components-android/blob/master/docs/theming/Typography.md | 1、4 |
| 6 | Emil Kowalski「Great animations」 https://emilkowal.ski/ui/great-animations | 4 |
| 7 | Rauno Freiberg「Invisible Details of Interaction Design」 https://rauno.me/craft/interaction-design 、「interfaces」 https://github.com/raunofreiberg/interfaces | 1、4 |
| 8 | Vercel Labs「web-interface-guidelines」 https://github.com/vercel-labs/web-interface-guidelines | 1、4、6 |
| 9 | Josh Comeau「Designing Beautiful Shadows in CSS」 https://www.joshwcomeau.com/css/designing-shadows/ | 3 |
| 10 | MDN「prefers-reduced-motion」 https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion 、「forced-colors」 https://developer.mozilla.org/en-US/docs/Web/CSS/@media/forced-colors 、「font-variant-numeric」 https://developer.mozilla.org/en-US/docs/Web/CSS/font-variant-numeric | 1、2、4 |
