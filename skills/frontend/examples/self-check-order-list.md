# 自己点検票: 管理画面の注文一覧（第 1 段階の見本）

> **3 行でわかる要約**
> 1. 実装計画「管理画面の注文一覧」の第 1 段階にあたる、見本アプリ（`samples/app`）の自己点検票です。2026-11-07 13:27 の版を、幅 1,280px ほか 4 幅で測りました。
> 2. 点検は 24 項目で、充足 20、未確認 4 です。書体の見え方を足すと、未確認は 5 件です。初期表示は 0.32 秒で、画面のずれは 0 でした（10Mbps・CPU 等速の 1 回。予算の 4G 相当とは条件が違います）。
> 3. 17 周目の直しは測って合いました。暗い版の群の帯は、縞と 1.60 対 1、紙面と 1.44 対 1 です。検索欄とチップは下線だけの記入欄です。デザイナーはこの票と忠実度の表を見て監修してください。

| 項目 | 内容 |
|---|---|
| 測った日 | 2026-11-07。13:31〜13:32 に gate と実測が回った。13:36〜13:40 に、フロントエンドが直した所と焦点の隠れを測り直した |
| 対象 | `samples/app` の 4 ファイル。index.html は 13:27 の版。tokens.css と app.css は 13:26、app.js は 12:19 の版。未 commit の作業ツリー |
| 条件 | Lighthouse は幅 1280、回線 10Mbps（往復 40ms）、CPU 等速、1 回。Playwright は幅 1280（高さ 360〜970）、640、412、320。配信は localhost の HTTP で、圧縮なし |
| 出どころ | tmp/flow/stage3/ の 5 ファイル。gate-output.txt は 13:31。measure.json と sample-app-test.txt は 13:32。fidelity.txt と ai-look.txt も 13:32 |
| 測り直し | 焦点の隠れは measure-focus-4widths.mjs で測った。17 周目の直しは Playwright で同じ見本を開いて測った。面と線の色、記入欄の形、伝票、済の帯、金額の見出し、上の帯の 6 つ。止まり先、押せる部品、主ボタン、横幅、開いた行の線も数え直した |
| 測り直していない所 | 紙面と伝票の下の余白 16px は 13:00 の測り。17 周目の直しの対象外の部品 |
| 計画 | `frontend-plan-order-list.md` の第 1 段階（見本） |

## 点検

点検は 24 項目で、判定は充足か未確認の 2 択です。結果には、測った数字か検査の PASS だけを書きます。静的な見本なので、道具の設定が無い 6 段は未確認とし、理由を添えます。6 段は型・lint・単体・build・束・依存です。比は、ブラウザの計算値（16 進に丸める前）から求めました。計画書の比とは、丸めの分だけ 0.05 まで違います。

| # | 観点 | 確かめたこと | 結果 | 判定 |
|---|---|---|---|---|
| 1 | 表示 | 行数、群と件数、絞り込み、空の案内、済の開閉 | 見えている行は 23 行で、群の見出しは 6 本。`要対応 3件`、`出荷遅れ 2件`、`出荷可 10件`、`決済待ち 3件`。`出荷指示の直後 5件`、`済 377件`。決済待ちに `今日出荷の分・全体 12件`。sample-app-test の unit が PASS | 充足 |
| 2 | トークン | 部品の CSS の生の色・px・書体名 | token-lint 0 件（gate の「トークン」の段が PASS） | 充足 |
| 3 | 動き | 縮小版の無い動き、transition: all | motion-lint 0 件。行の色の transition は 0.08s、減らす設定で 0s（measure.json） | 充足 |
| 4 | 忠実度と面の色 | 実装の 16 進と ms が計画の集合に収まるか。選んだ行、縞、群の帯の地 | fidelity-check PASS。選んだ行は明 #CDD8E8、暗 #3F5466。縞は台紙で、明 #E5F0ED、暗 #0E1714。群の帯は明 #B8C9C5、暗 #2F3D38 | 充足 |
| 5 | 群の帯の離れ | 暗い版で、群の帯が上下の行と溶けないか | 暗い版の群の帯は、縞と 1.60、紙面と 1.44、選んだ行と 1.45 対 1。明るい版は縞と 1.48、紙面と 1.72、選んだ行と 1.20 対 1 | 充足 |
| 6 | AI らしさ | 既定の見た目の数 | ai-look-check 0 件、帯 clean | 充足 |
| 7 | キーボード | 全部の操作に Tab で届くか。主ボタンとキーの印の数 | 幅 1280 で Tab の止まり先は 55 か所。主ボタンは 3 行を選んだ姿で帯の `3件を出荷指示`（120×44px）の 1 個。選択を 0 件にすると、伝票の `この1件を出荷指示`（294×44px）だけになった。キーの印（kbd）は 0 個 | 充足 |
| 8 | 焦点の見え方 | 枠の太さ・色・位置、固定の帯と見出しに隠れないか | outline は solid 2px、藍 rgb(47, 92, 158)、offset 2px。幅 1280 の scroll-padding の上は 144px。焦点の中心が隠れた回数は、幅 1280 の 110 回で 0、640 の 92 回で 0。412 と 320 は各 90 回で 0 | 充足 |
| 9 | 押せる領域 | 見えている押せる部品の大きさ | チェックは囲む label で測った。幅 1280 で 55 個、640 で 46 個、412 と 320 で各 45 個。最小はどの幅も 44×44px で、44px 未満は 0。行は 902×45px（44px に罫線 1px）。検索欄は 220×44px | 充足 |
| 10 | 拡大とリフロー | 幅 640・412・320 で横スクロールが出ないか。列を隠す順 | scrollWidth は幅 640 で 640、412 で 412、320 で 320 で、どれも表示域と同じ。幅 1280 では 9 列すべてが並ぶ。幅 640 では支払い・担当・受注日時を隠して 6 列（measure.json の cols640） | 充足 |
| 11 | 初期表示（LCP） | Lighthouse の 1 回 | 0.32 秒（321.6ms）。最初の描画も 0.32 秒、ブロック時間 0ms | 充足 |
| 12 | 画面のずれ（CLS） | 同上 | 0 | 充足 |
| 13 | 操作の応答 | Playwright で「佐藤」の入力と状態の選択を送り、event の duration の最大を見た | 最大 24ms。16ms を超えた event は 13 件（measure.json）。予算の 200ms の内側 | 充足 |
| 14 | 転送量 | Lighthouse の resource-summary | 合計 56.8KB（58,166 バイト）。HTML 23.5KB（24,047 バイト）。CSS 29.0KB（2 ファイル、29,654 バイト）。JS 4.4KB（4,465 バイト）。どれも圧縮なし。外部 0 件、書体 0、画像 0 | 充足 |
| 15 | axe（アクセシビリティの自動検査の道具） | 明るい版と暗い版 | 明るい版で違反 0（確認 49 項目）、暗い版で違反 0（49 項目） | 充足 |
| 16 | Lighthouse の点 | 性能、アクセシビリティ、ベストプラクティス | 100、100、100。基準は sample-app-test の 90 以上 | 充足 |
| 17 | 読み上げ | 読み上げソフトが読む名前（アクセシビリティの木）。表の名前、検印、検索と状態のラベル、件数 | sample-app-test の a11y-names が PASS。名前を持つ検印は 11 個で、`出荷指示済み、11月6日 09:52、坂口` の形。伝票の検印の欄は、見えない字の「まだ押していない」を持つ | 充足 |
| 18 | 列と担当なしと太字 | 列の幅、担当なしの字の比、行の太字 | 列は 9 本で合計 902px、氏名は 174px。見えている 23 行のうち 11 行が「担当なし」。明るい版は #3B514B で、縞 7.31、紙面 8.52 対 1。暗い版は #B1C5BE で、縞 10.07、紙面 9.03 対 1。太字は注文番号 23、札 5、検印 5 だけ | 充足 |
| 19 | 罫と記入欄の形 | 群の線、縦罫、検索欄とチップの形 | 群の帯の線は下の端の墨 2px の 1 本で、上下の枠は 0。暗い版の縦罫は #3B4A45 で、横の罫線 #53655F より弱い。検索欄とチップは上の枠 0、下線 1px、角 0、地なし。下線は紙面と 3.99 対 1（暗い版 4.27） | 充足 |
| 20 | 伝票、済の帯、金額 | 伝票の固定と中身。済の帯の字。円の書き方。開いた行の線 | 伝票の見出しは上から 120px で、100〜582px 送ると 27px に残る。番号は 16px、担当なしは墨、空の欄の円は罫の色の破線、欄の見出しの帯は 0。済の帯の見える字は検印・`377件`・「開く」で、間は 12px。表の円は 0 で、伝票の金額 6 つは円つき | 充足 |
| 21 | 型と lint | tsc、eslint | gate が SKIP | 未確認（tsconfig.json と eslint の設定が無い静的な見本） |
| 22 | 単体テストと build | npm test、npm run build | gate が SKIP | 未確認（package.json が無い。振る舞いは 1 番の sample-app-test で代えた） |
| 23 | 初期表示の JS の上限 | size-limit（gate の「束」の段） | gate が SKIP | 未確認（設定が無い。JS は 4.4KB（圧縮なし）で、上限 170KB の内側であることは 14 番で見た） |
| 24 | 依存 | npm audit | gate が SKIP | 未確認（package-lock.json が無く、見本は依存を持たない） |

20 番の残りも測りました。開いた行は墨の線で囲み、左 6px、上下 2px です。強制カラーでは影が消え、Highlight の border に替わりました。今いるタブの上端の線も、強制カラーで 4px の Highlight です。金額の見出し `金額（円）` は高さ 44px の 1 段で、字詰め（palt）は使っていません。上の帯の項目は、幅 1,280px で 1 段に並びました。

Lighthouse（Google の性能測定）は幅 1280・回線 10Mbps・CPU 等速で 1 回です。Playwright（ブラウザの自動操作の道具）は幅 1280・640・412・320 で測りました。数字は見本の条件での値として読んでください。実装計画の予算の条件（4G 相当、CPU 4 倍遅く、3 回の中央値）とは違います。

## ゲートの出力

frontend-gate.sh の full 版は 2026-11-07 13:31 に回りました。見本アプリの実測は 13:32 です。場所は My-Lab の最上位のフォルダです。下は tmp/flow/stage3/ の出力の写しです。SKIP の 6 段は、点検の 21〜24 番に理由を写しました。

```text
$ bash skills/frontend/scripts/frontend-gate.sh --full samples/app
[SKIP] 型        tsconfig.json が無い
[SKIP] lint       eslint の設定が無い
[SKIP] 単体     package.json に test が無い
[SKIP] build      package.json に build が無い
[SKIP] 束        size-limit の設定が無い
[PASS] トークン RESULT: PASS token-lint samples/app (FAIL 0、WARN 0)
[PASS] 動き     RESULT: PASS motion-lint samples/app (FAIL 0、WARN 0)
[PASS] 画面     RESULT: PASS sample-app-test (0 件)
[SKIP] 依存     package-lock.json が無い
RESULT: PASS frontend-gate samples/app (PASS 3、FAIL 0、SKIP 6)

$ node tools/sample-app-test.mjs
RESULT: PASS unit (行数・絞り込み・件数・空の案内・済の開閉・キーボード・固定の帯の余白・幅 640 と 320)
RESULT: PASS a11y-names (表の名前、検印 11 個の名前、検索と状態のラベル、件数の読み上げ)
RESULT: PASS axe (違反 0、確認 49 項目)
RESULT: PASS lighthouse (性能 100、アクセシビリティ 100、ベストプラクティス 100)
RESULT: PASS sample-app-test (0 件)

$ bash skills/designer/scripts/fidelity-check.sh skills/designer/examples/design-plan-order-list.md samples/app/tokens.css samples/app/app.css samples/app/index.html
RESULT: PASS fidelity-check skills/designer/examples/design-plan-order-list.md (FAIL 0、WARN 0)

$ bash skills/designer/scripts/ai-look-check.sh samples/app --plan skills/designer/examples/design-plan-order-list.md
AI らしさ: 0 件、帯 clean（0〜1 clean、2〜3 mild、4〜6 sloppy、7 以上 terminal。pixelslop の区分）
RESULT: PASS ai-look-check samples/app (FAIL 0、WARN 0)

暗い版の axe（Playwright の colorScheme: dark で同じ検査。出力は tmp/flow/stage3/measure.json）
"dark_axe_violations": 0, "dark_axe_passes": 49

$ node tmp/flow/stage3/measure-focus-4widths.mjs（フロントエンドの測り直し）
w1280x360 checked 110 covered 0 / w640x400 checked 92 covered 0 / w412x823 checked 90 covered 0 / w320x568 checked 90 covered 0
```

## 忠実度

デザイナーの検査 2 つと、フロントエンドの lint 2 つの結果です。基準画像は 5 状態 × 幅 1,280px・640px・320px の 15 枚です。見本は成功の状態しか持たないので、第 2 段階から撮ります。

| 検査 | 結果 |
|---|---|
| fidelity-check | PASS（FAIL 0、WARN 0）。生の 16 進は tokens.css だけで、計画の色の集合に収まる |
| ai-look-check --plan | 0 件、帯 clean |
| token-lint | 0 件 |
| motion-lint | 0 件 |
| 基準画像 | 見本は成功の状態だけ。第 2 段階から、幅 1,280px・640px・320px で撮る |
| 配置の実測 | ずれ 1 件。表の面 902px で 9 列、氏名の列 174px。伝票の番号 16px、主ボタン 1 個、キーの印 0 個は計画どおり |
| 検索欄の幅 | 幅 1,280px で 220px。計画書の括弧書き「幅 1,280px では 192px」と違う。「220px まで、入らないときは縮む」の決まりには合う |
| 色の丸め | 暗い版の担当なしの字は、計算値を 16 進に直すと #B1C5BE。計画書は #B2C5BE。罫と墨の赤（143 と 212）の半分が 177.5 で、丸め方で 1 だけ違う |

## 未確認

未確認は 5 件です。点検の 4 件と、書体の見え方 1 件です。確かめたら、この票に書き足します。

| 項目 | 確かめていない理由 | 確かめ方 |
|---|---|---|
| 型と lint | tsconfig.json と eslint の設定が無い静的な見本 | 第 2 段階で設定を入れ、gate の型と lint を PASS にする |
| 単体テストと build | package.json が無い。振る舞いは sample-app-test で代えた | 第 2 段階で vitest と build を入れる |
| 初期表示の JS の上限 | size-limit の設定が無い。JS は 4.4KB（圧縮なし）で上限 170KB の内側 | 第 2 段階で size-limit を入れる |
| 依存 | package-lock.json が無く、見本は依存を持たない | 第 2 段階で npm audit を gate に通す |
| 書体（BIZ UDPGothic。モリサワの読みやすさ向けの書体）での見え方 | 指定は measure.json の font_family で、先頭が BIZ UDPGothic。実際に BIZ UDPGothic で描かれたかは確かめていない | 描いた書体を CDP（Chromium の開発者向けの窓口）で取り出し、書体の名前を見る |

## 受け渡し

この票は 2 つの相手に渡します。バックエンドには渡しません。第 1 段階は API を呼ばないからです。

| 誰に | 何を | いつ |
|---|---|---|
| デザイナー | この票、忠実度の表（配置のずれ 1 件、色の丸め 1 件）、監修の依頼 | いま |
| 取りまとめ役 | 判定と証拠。ゲートの出力、sample-app-test の出力、measure.json、焦点の測り直し | いま |
