# 性能予算: 3 指標と JS の上限、測り方

> **3 行でわかる要約**
> 1. 予算は Core Web Vitals（Chrome が定めた体感の 3 指標）の「良い」の閾値と、JS の転送量の上限で決める。
> 2. 測定条件（ビルド、回線、CPU、幅、回数、集計）を予算と一緒に書く。条件の無い数字は比べられない。
> 3. 超えたら CI（変更ごとに自動で検査する仕組み）が落ちる。本番では実利用者の 75 パーセンタイルを見る。

## 3 指標と閾値

閾値は Chrome が公開している「良い」の値で、社内の好みで動かさない。目標は閾値より内側に置き、余裕を持つ。

| 指標 | 何を測るか | 良い | 社内の目標 |
|---|---|---|---|
| LCP（初期表示） | 最も大きい要素が描かれるまでの時間 | 2.5 秒以内 | 1.8 秒 |
| INP（操作の応答） | 利用者の操作から次の描画までの時間。ページ中の最悪に近い値 | 200ms 以内 | 120ms |
| CLS（画面のずれ） | 読み込み中に要素が動いた量 | 0.1 以内 | 0.02 |

FID（最初の入力の遅れ）は 2024 年 3 月に INP に置き換わった。古い資料の FID の予算は INP に読み替える。

## 測定条件は予算の一部

同じ画面でも、回線と CPU と幅で値は数倍変わる。予算の表には測定条件の列を必ず置く。

| 条件 | 値 | 理由 |
|---|---|---|
| ビルド | 本番相当（minify、圧縮あり） | 開発ビルドは 2〜5 倍遅い |
| 回線 | 4G 相当。往復 150ms、下り 1.6Mbps | Lighthouse（Google の性能測定）の既定のモバイル条件 |
| CPU | 4 倍遅く | 同上 |
| 幅 | 1280 と 412 | PC と片手の端末の代表値 |
| 回数と集計 | 3 回。LCP と INP は中央値、CLS は最大 | 1 回の値はぶれる。CLS は悪い側を採る |
| 走らせ方 | Lighthouse CI の assert に `aggregationMethod` と閾値を書く | 人が目で見ない。超えたら落ちる |

見本アプリ（samples/app）は PC 向けの管理画面なので、幅 1350・回線 10Mbps・CPU 等速で測る。条件が違う数字は、別の表に分けて書く。

## JS の上限

web.dev の 170KB は、3G の回線で 5 秒以内に対話できるための、読み込み経路全体の目安である。社内の上限は「画面の初期表示の JS、brotli 圧縮後 170KB」と決める。size-limit（JS のファイルの大きさの上限を見る道具）で CI に置く。表の本体をサーバーで描けば、この上限に収まる。

| 対象 | 上限 | 測り方 |
|---|---|---|
| 初期表示の JS（画面を開いたときに読む JS） | 170KB（brotli 後） | size-limit の path に、初期表示で読む JS を指定 |
| 外部の要求 | 0 件 | Lighthouse の resource-summary:third-party:count |
| 書体 | 2 ファイル。合計の上限を計画書に書く | Lighthouse の resource-summary:font:size |
| 画像 | 一覧に画像を置かない | 同上の image:size が 0 |

## INP の測り方

INP は利用者の操作が要るので、Lighthouse の読み込み計測では出ない。Playwright（ブラウザの自動操作の道具）で主要な操作を送る。PerformanceObserver の event の記録から、操作ごとの duration の最大を取る。本番では web-vitals（Chrome と同じ定義で測るライブラリ）で送り、計測画面で 75 パーセンタイルを見る。

| 場 | 道具 | 何を取るか |
|---|---|---|
| 検査（lab） | Playwright。並び替え・絞り込み・面を開く操作を 3 回ずつ | event の duration の最大 |
| 本番（field） | web-vitals の onINP | 75 パーセンタイル。利用者の 4 人に 3 人がそれより速い |

## 書体は CLS を生まない読み込みにする

font-display: swap は、代替の字形から本来の字形に切り替わるときに行の幅が変わり、CLS を生む。optional なら間に合わなかった書体を諦め、ずれを作らない。代替の字形には size-adjust で幅を合わせる。日本語の書体はサブセット（使う字だけを切り出したファイル）にし、合計の上限を計画書に書く。

| 設定 | 選ぶとき | 注意 |
|---|---|---|
| font-display: optional | 本文の書体。ずれを 0 にしたい | 遅い回線では代替の字形で表示が終わる |
| font-display: swap と size-adjust | 書体が見た目の要で、必ず出したい | size-adjust で幅を合わせ、CLS を測って確かめる |
| 読み込まない | 管理画面で OS の書体で足りる | トークンの font-family に代替の列を書く |

## 付録: 出典

出典は、調査ブリーフの検証役が 2026-11-05 に本文を開いて確かめたものである。

| 出典 | 使った節 |
|---|---|
| web.dev「Largest Contentful Paint」「Interaction to Next Paint」「Cumulative Layout Shift」 | 3 指標と閾値 |
| web.dev「Performance budgets 101」「Your first performance budget」 | JS の上限 |
| Lighthouse CI Docs「Configuration」（assert、aggregationMethod） | 測定条件 |
| size-limit README | JS の上限 |
| web-vitals README（onINP、attribution） | INP の測り方 |
| web.dev「Best practices for fonts」、MDN「font-display」「size-adjust」 | 書体 |
