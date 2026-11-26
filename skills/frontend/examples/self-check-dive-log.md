# 自己点検票: 深海の探査日誌のスタートとログイン（没入の型の見本）

> **3 行でわかる要約**
> 1. 実装計画「深海の探査日誌のスタートとログイン」の動くサンプル（`samples/immersive`）の自己点検票です。題材は架空のアプリで、2026-11-26 19:12 に測りました。
> 2. 点検は 26 項目で、充足 21、未確認 5 です。演出の 12 項目はすべて充足で、最初の 1 画面は LCP 1,352ms、CLS 0 でした。2 回目の監修の指摘 N1〜N4 を入れたあとの値です。
> 3. 同じ測りを 3 回続けると、3 回とも PASS でした。51ms の長いフレームは、この 3 回に出ませんでした。原因は直していません。デザイナーは撮ったフレームで監修し、取りまとめ役は未確認の節と合わせて判定してください。

| 項目 | 内容 |
|---|---|
| 測った日 | 2026-11-26。19:11〜19:13 に immersive-test を 3 回続けて回し、この票の数字は 3 回目（19:12:23 から）の値 |
| 対象 | `samples/immersive` の 7 ファイル（index.html、app.css、tokens.css、app.js、scene.js、ledger.json、check.mjs）。未 commit の作業ツリー |
| 条件 | Chromium 156.0.8078.4 の画面なし、描画はソフトウェア（SwiftShader）。幅 1,280px。CPU 等速と 4 倍遅くの 2 条件で 3 回ずつ、悪い側を採る。Lighthouse（Google の性能測定）は既定のモバイル条件で 1 回 |
| 計画 | `frontend-plan-dive-log.md`（同じ examples にある） |
| 画面の型 | 没入の型。実装計画から写した |
| 演出の記録 | tmp/.verify/immersive-measure.json（回すたびに書き直す） |
| フレームの一覧 | tmp/flow/team-improvement/stage2/frames.json（frames 50 枚、directions 3 枚。戻るの縮小版 4 枚は同じ手順の小さなスクリプトで足した） |

## 点検

点検は 26 項目で、判定は充足か未確認の 2 択です。15〜26 は演出の 12 項目で、motion-measure と同じ順です。結果には、測った数字か検査の PASS だけを書きます。静的なサンプルなので、道具の設定が無い 4 段は未確認とし、理由を添えます。

| # | 観点 | 確かめたこと | 結果 | 判定 |
|---|---|---|---|---|
| 1 | コンソール | 海面・潜る・戻る・2 回目・飛ばす・#panel・縮小版・方向の 3 案を通す | エラー 0 件 | 充足 |
| 2 | 外への要求 | 同じ通しで、外へ出る要求を止めて数える | 止めた要求 0 件（要求は全部で 21 件） | 充足 |
| 3 | 初期表示（LCP） | Lighthouse 12.8.2 の 1 回 | 1,352ms（予算 2,500ms） | 充足 |
| 4 | 画面のずれ（CLS） | 同上 | 0（予算 0.1） | 充足 |
| 5 | トークン | token-lint | 生の値 0 件 | 充足 |
| 6 | 動き | motion-lint | 0 件 | 充足 |
| 7 | 台帳と演出計画 | 台帳の初回の版と、演出計画書の時刻ごとの表 | 拍 9 行の時刻・段・長さ・曲線が同じ。初回 1,400ms、2 回目 600ms | 充足 |
| 8 | 忠実度 | fidelity-check に演出計画書を添える | PASS（FAIL 0、WARN 0） | 充足 |
| 9 | AI らしさ | ai-look-check --plan | 0 件、帯 clean | 充足 |
| 10 | 型と lint | tsc、eslint | gate が SKIP | 未確認（tsconfig.json と eslint の設定が無い静的なサンプル） |
| 11 | 単体テストと build | npm test、npm run build | gate が SKIP | 未確認（package.json が無い） |
| 12 | 初期表示の JS の上限 | size-limit（gate の「束」の段） | gate が SKIP | 未確認（設定が無い。初期表示の JS は 26 番で 11.8KB と測った） |
| 13 | 自動検査（axe） | 5 状態と撮る幅 | 回していない | 未確認（サンプルに axe の実行の仕組みが無い。gate の「画面」の段が SKIP） |
| 14 | 操作の応答（INP） | 押す・飛ばす | 最初のフレーム 48ms、飛ばして 11.1ms で終わりの状態（15 と 21 番） | 充足 |
| 15 | 演出の最初のフレーム | motion-measure の 1。押してから最初のフレームまで | 48ms（CPU 4 倍遅い条件の 1 回目。予算 100ms） | 充足 |
| 16 | 演出の拍と長さ | motion-measure の 2。台帳の拍との差 | 拍 12 本、差は最大 2.6ms（許容 ±20ms） | 充足 |
| 17 | 演出のフレームの間隔 | motion-measure の 3。CPU 等速と 4 倍遅い条件 | どちらも最大 16.8ms、25ms 超 0.0%、50ms 超 0 個（94 個） | 充足 |
| 18 | 長いフレームの原因 | motion-measure の 4。LoAF の記録 | 50ms を超えたフレーム 0 件 | 充足 |
| 19 | 動かす属性 | motion-measure の 5。台帳で許した属性か | 動き 19 本、台帳の外 0 本 | 充足 |
| 20 | 縮小版 | motion-measure の 6。動きを減らす設定で同じ操作 | 位置の動き 0 本、動き 3 本。終わりの状態は通常の回と同じ（差 0px） | 充足 |
| 21 | 飛ばす | motion-measure の 7。途中でキーを押す | 205.6ms で Enter、11.1ms で終わりの状態（予算 300ms） | 充足 |
| 22 | 焦点と読み上げ | motion-measure の 8。終わりの焦点、title、去った場面 | PASS。焦点 textbox「メールアドレス」、title「ログイン ・ 深海の探査日誌」、#surface は操作と読み上げを受けない | 充足 |
| 23 | 5 秒を超える動き | motion-measure の 9。止める操作のあとの 2 枚 | 止める前の差 7,388px、止めたあとの差 0px | 充足 |
| 24 | 音 | motion-measure の 10。操作の前、消音、拍との差 | 鳴らす命令 0 回（音の無い演出）、操作の前 0 回 | 充足 |
| 25 | 閃光 | motion-measure の 11。明るさの反転 | 1 秒に最大 0 回（上限 3 回。43 枚を 33ms ごと、16 区画） | 充足 |
| 26 | 演出のアセットと準備 | motion-measure の 12。brotli 後の大きさと準備の秒 | 初期表示の JS 11.8KB、演出のアセット 0KB、外への要求 0 件、準備 0 秒 | 充足 |

3 回続けた計測の結果は、次の表のとおりです。3 回とも PASS で、18 番の長いフレームは 0 件でした。合格の線は変えていません。

| 回 | 始めた時刻 | 負荷（1 分の平均） | 結果 | 17 番（フレームの間隔、4 倍遅い条件） | 18 番（長いフレーム） |
|---|---|---|---|---|---|
| 1 | 19:11:06 | 3.91 | PASS | 最大 33.3ms、50ms 超 0 個 | 0 件 |
| 2 | 19:11:45 | 4.68 | PASS | 最大 33.3ms、50ms 超 0 個 | 0 件 |
| 3 | 19:12:23 | 5.30 | PASS | 最大 16.8ms、50ms 超 0 個 | 0 件 |

前の日の測りでは、6 回に 1 回ほど、押した直後に 51ms の長いフレームが出ました。原因は、自分の層を持たない要素が動き出すときのブラウザの待ちです。今回の 3 回には出ませんでしたが、原因は直していないので、未確認の節に残します。分け方の記録は、件名のフォルダの part-frontend-2.md にあります。

26 番の演出のアセットは、1 回目は 3.5KB で、2 回目と 3 回目は 0KB でした。初期表示の JS も 8.3KB と 11.8KB で違います。背景のスクリプトを、初期表示の内と外のどちらで数えたかの差と読めますが、確かめていません。

## ゲートの出力

frontend-gate.sh の fast 版は、2026-11-26 19:13 に回しました。場所は作業ツリーの最上位のフォルダです。--plan を付けない回なので、演出の段は下の「演出の計測」に分けて貼ります。SKIP の段は、点検の 10〜13 番に理由を写しました。

```text
$ bash skills/frontend/scripts/frontend-gate.sh --fast samples/immersive
[SKIP] 型        tsconfig.json が無い
[SKIP] lint       eslint の設定が無い
[SKIP] 単体     package.json に test が無い
[SKIP] build      package.json に build が無い
[SKIP] 束        size-limit の設定が無い
[PASS] トークン RESULT: PASS token-lint samples/immersive (FAIL 0、WARN 0)
[PASS] 動き     RESULT: PASS motion-lint samples/immersive (FAIL 0、WARN 0)
[SKIP] 画面     axe と Lighthouse の実行の仕組みが無い（tools/sample-app-test.mjs の型で用意する）
[SKIP] 依存     --full のときだけ回す
RESULT: PASS frontend-gate samples/immersive (PASS 2、FAIL 0、SKIP 7)
```

## 演出の計測

3 回目の immersive-test が書いた記録を、判定し直した出力です。motion-measure の --judge は、ブラウザを使いません。測ったのは画面なしのブラウザで、描画はソフトウェアです。GPU のある画面での滑らかさは確かめていません。

```text
$ node tools/immersive-test.mjs --shots tmp/flow/team-improvement/stage2   （3 回目。19:12:23〜19:13:13）
$ node skills/frontend/scripts/motion-measure.mjs --judge tmp/.verify/immersive-measure.json
RESULT: PASS motion-measure 1 最初のフレーム: 押してから最大 48ms（CPU 4 倍遅い条件の 1 回目。予算 100ms）
RESULT: PASS motion-measure 2 拍と長さ: 拍 12 本が全部走り、最初の拍に合わせた時刻と長さの差は最大 2.6ms（許容 ±20ms）。最初の拍は押してから最大 0ms。エンジンの拍 3 本は getAnimations で見えないので数えない
RESULT: PASS motion-measure 3 フレームの間隔: CPU 等速: 最大 16.8ms、25ms 超 0.0%、50ms 超 0（94 個）。CPU 4 倍遅い条件: 最大 16.8ms、25ms 超 0.0%、50ms 超 0（94 個）
RESULT: PASS motion-measure 4 長いフレームの原因: 50ms を超えたフレーム 0 件
RESULT: PASS motion-measure 5 動かす属性: 動き 19 本の属性は opacity、border-bottom-color、border-left-color、border-right-color、border-top-color、transform、filter で、どれも台帳で許した属性
RESULT: PASS motion-measure 6 縮小版: 位置の動き 0 本。動き 3 本。終わりの状態は通常の回と同じ。終わったあとの 2 枚の差 0px
RESULT: PASS motion-measure 7 飛ばす: 205.6ms の時点で Enter を押し、最大 11.1ms で終わりの状態（CPU 等速の 1 回目。予算 300ms）
RESULT: PASS motion-measure 8 焦点と読み上げ: 焦点は textbox「メールアドレス」。title は「ログイン ・ 深海の探査日誌」。#surface は操作と読み上げを受けない
RESULT: PASS motion-measure 9 5 秒を超える動き: 5 秒を超えて動く（差 7388px）。button「背景の動きを止める」 を押したあとの 2 枚の差 0px
RESULT: PASS motion-measure 10 音: 鳴らす命令 0 回（音の無い演出）。操作の前 0 回
RESULT: PASS motion-measure 11 閃光: 明るさの反転は 1 秒に最大 0 回（43 枚を 33ms ごと、16 区画。上限 3 回）
RESULT: PASS motion-measure 12 アセットと準備: 初期表示の JS 11.8KB、演出のアセット 0KB（うち JS 0KB。brotli 後）、外への要求 0 件、準備 0 秒
描画: 画面なしのブラウザ（Chromium 156.0.8078.4、headless）で測った。WebGL は ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (LLVM 10.0.0) (0x0000C0DE)), SwiftShader driver)（ソフトウェア描画）。GPU での滑らかさは未確認
RESULT: PASS motion-measure scene-start-login (PASS 12、FAIL 0。2 条件で計 6 回の悪い側。画面なしのブラウザ)
```

## 忠実度

デザイナーの検査 2 つと、フロントエンドの lint 2 つは、どれも 0 件でした。

| 検査 | 結果 |
|---|---|
| fidelity-check（--motion に演出計画書） | PASS（FAIL 0、WARN 0） |
| ai-look-check --plan | 0 件、帯 clean |
| token-lint | 0 件 |
| motion-lint | 0 件 |
| フレームと方向の 3 案 | 3 回目の --shots で 53 枚（frames 50 枚、directions 3 枚）。戻るの縮小版 4 枚（return-reduced-0000〜0150）を足し、一覧は frames.json |
| 戻るの字の重なり（指摘 N1） | 100ms のフレームで題字の画素 0、300ms で盤の字の画素 0。縮小版は 50ms で題字 0、100ms で盤の字 0 |
| 誤りの文と送信中の盤（指摘 N2） | 盤の上端は静止・誤りの状態・送信中のどれも 102px で、動き 0px |

## 未確認

未確認は、点検の 4 件と、環境の 4 件の計 8 件です。確かめたら、この票に書き足します。

| 項目 | 確かめていない理由 | 確かめ方 |
|---|---|---|
| 型と lint、単体と build、JS の上限 | 道具の設定が無い静的なサンプル | 本番の案件で設定を入れ、gate の段を PASS にする |
| axe（アクセシビリティの自動検査の道具） | サンプルに実行の仕組みが無い | sample-app-test.mjs の型で、5 状態と撮る幅に axe を回す |
| GPU のある画面での滑らかさと長いフレーム | 測ったのは画面なしのソフトウェア描画だけ。前の日に 6 回に 1 回ほど出た 51ms は、原因を直していない | 画面ありの Chrome で、同じ押し方を 10 回以上測る |
| Safari と Firefox | 測る道具を Chromium でしか回していない | Playwright（ブラウザの自動操作の道具）の webkit と firefox で同じ 12 項目を測る |
| 実機（スマートフォンと低い性能の PC） | 手元に測る機械が無い | 実機で押した直後のフレームを記録する |
| 演出のアセットの数え方の差 | 1 回目は 3.5KB、2 回目と 3 回目は 0KB。数えた範囲の差は確かめていない | 記録の assets の一覧を、回ごとに突き合わせる |

## 受け渡し

この票は 2 つの相手に渡します。

| 誰に | 何を | いつ |
|---|---|---|
| デザイナー | この票と、撮ったフレームと方向の 3 案（frames.json）。監修の依頼 | いま |
| 取りまとめ役 | 判定と証拠。3 回の計測の表、gate と motion-measure の出力、落ちた回の行 | いま |
