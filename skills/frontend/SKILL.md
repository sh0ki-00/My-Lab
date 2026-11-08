---
name: frontend
description: デザイン計画書・トークン・画面仕様を受け取り、性能予算（LCP 2.5 秒・INP 200ms・CLS 0.1 と初期表示の JS 170KB）とアクセシビリティ（axe 違反 0、キーボードで完結）の内側で、計画どおりに画面を実装する。実装計画を 14 節（構成・状態・データ取得・エラー・性能予算・テスト・アクセシビリティ・忠実度・横断事項ほか）で書き、トークン以外の生の値と縮小版の無い動きを機械で落とし、実装後は測った数字だけで自己点検票を書く。検査は frontend-gate.sh の 1 コマンドで束ねる。Use when planning or implementing a screen, component, form or client-side state; when setting performance budgets or front-end CI gates; when writing a self-check with measured numbers; and when checking an implementation against design tokens. Triggers: フロントエンド, 画面実装, 画面を作って, コンポーネント, 部品, フォーム, 状態管理, 実装計画, 性能予算, LCP, INP, CLS, バンドル, JS の大きさ, 自己点検票, アクセシビリティ, a11y, キーボード操作, トークンで描く, 忠実度の報告, React, Next.js, Vue, Playwright.
---

# frontend — 計画どおりの画面を、予算とアクセシビリティの内側で実装し、数字で証明する

## いつ使うか

秘書の受付票で依頼の型が「実装（画面）」のとき。デザイン計画書・トークン・画面仕様を受け取って画面を作るとき。既存の画面の性能やアクセシビリティを直すときや、性能予算と CI の検査を決めるときにも使う。見た目の方向や色を決めるのはデザイナーの仕事で、このスキルでは決めない。

## 先に読むもの

- `.company/frontend/CLAUDE.md`（ペルソナ）と `.company/DELIVERY.md`。
- デザイナーの引き渡し `tmp/flow/<件名>/design-plan.md`、`tmp/flow/<件名>/tokens.css`、`tmp/flow/<件名>/screen-spec.md`。無ければ秘書に戻し、計画書の無い画面を作らない。
- バックエンドの契約（エラーコードの表と応答時間）。無ければ上限を仮置きにし、未確定に書く。
- `references/architecture-and-state.md`（動く場所、状態の置き場、取得、2 文のエラー）、`references/performance-budget.md`（3 指標と JS の上限、測定条件）、`references/a11y-and-testing.md`（APG の型、手動 5 項目、1 対 1 のテスト）、`references/cross-cutting.md`（動き・国際化・安全・型・トークン）。
- `templates/`（実装計画、自己点検票、Lighthouse CI と size-limit の設定）、`examples/`（注文一覧の実装計画と、見本アプリの自己点検票）。

## 判断の観点

1. 予算の内側か。LCP 2.5 秒・INP 200ms・CLS 0.1 と、初期表示の JS 170KB。測定条件を添えて比べる。
2. 状態の置き場は 1 か所か。URL・サーバー由来・画面の操作・フォームで分け、同じ値を 2 か所に持たない。
3. 役割と名前で操作できるか。APG の型から選び、マウスなしで用事が終わるか。
4. 計画どおりか。トークン以外の値、縮小版の無い動き、連結した文言、無害化なしの HTML を書いていないか。
5. 数字で証明したか。測った値と検査の出力だけを書き、「速いはず」「ほぼ同じ」を書かない。

## 手順

1. 入力を読む。計画書の引き渡しの表、画面仕様の要素・5 状態・エラー・権限、契約のエラー表。終わりの印: 画面の仕事と 5 状態が 1 文ずつ書けた。
2. 構成を決める。部品ごとに動く場所（サーバー・ブラウザ・両方）と理由を表にする。終わりの印: ブラウザで動く部品を数えて言える。
3. 状態の置き場を決める。出どころで分け、重複 0。派生の値は描画中に計算する。
4. データ取得とエラーを決める。要求ごとに打ち切りの時間と失敗時。打ち切りは予算から引かず、API の打ち切りから決める。エラーは画面仕様のコードと 1 対 1。
5. 性能予算を書く。3 指標と JS の上限に、測り方と測定条件を添える。`templates/lighthouserc.json` と `templates/size-limit.json` を写す。
6. テストの対応表を書く。受け入れ条件 1 件にテスト 1 本、レベルとサイズ。不安定の 5 要因の固定法。
7. アクセシビリティと忠実度、横断事項（動き・国際化・安全・型・トークン）を表にする。
8. 検査を通す。`scripts/frontend-plan-check.sh <実装計画>` と `tools/check-file.sh`。終わりの印: 両方 PASS。秘書が `editor` で読み手テスト（フロントエンドからは呼べない）。
9. 承認のあとで実装する。トークンの変数だけで描き、動きはトークンの時間で書く。段階ごとに `scripts/frontend-gate.sh --fast <ディレクトリ>` を回し、赤のまま次へ進まない。
10. 測る。`scripts/frontend-gate.sh --full <ディレクトリ>`、見本アプリなら `tools/sample-app-test.mjs`。デザイナーの検査 2 つ（fidelity-check と ai-look-check --plan）も回す。
11. 自己点検票を書く（`templates/self-check.md`）。結果は測った数字か PASS、判定は充足か未確認、ゲートの出力を貼る。終わりの印: `scripts/self-check.sh <自己点検票>` が PASS。
12. デザイナーに監修を頼む。忠実度の報告（ずれの数、トークン外の値 0、帯 clean）を添える。指摘は採否と理由を記録して直す。

## 出力と受け渡し

| 成果物 | 置き場 | 渡す先 |
|---|---|---|
| 実装計画 | `tmp/flow/<件名>/frontend-plan.md` | 秘書（承認伺いに構成・予算・段階の 3 点を写す）、バックエンド（API への要望） |
| 性能予算と検査の設定 | リポジトリの lighthouserc.json、size-limit.json、テスト | CI |
| 実装 | リポジトリ | デザイナー（監修）、SRE（利用者側の計測） |
| 自己点検票と忠実度の報告 | `tmp/flow/<件名>/frontend-self-check.md` | デザイナー（監修の依頼）、秘書（判定と証拠） |

秘書には、要約 10 行以内・未解決の対立・承認が要る判断の 3 つを `skills/secretary/templates/reply-from-role.md` の型で返す。承認が要るのは、予算の値、道具の導入、段階の分け方である。

## 禁止

- 予算を決めずに実装を始める。測定条件の無い数字を書く。「速いはず」「見た目はほぼ同じ」と書く。
- 生の色・px・書体名を部品に書く。縮小版の無い動き。transition: all。
- 同じ値を 2 か所に持つ。副作用で派生の状態を作る。文字列を連結した文言。
- 無害化なしの innerHTML。eval と new Function。鍵をブラウザに出す。
- 受け入れ条件と結ばないテスト。getByTestId。不安定なテストを再実行で誤魔化す。
- 他の役割の判断を代行する。承認のない commit・push・Issue と PR の作成。

## 提出前の確認

1. `scripts/frontend-plan-check.sh <実装計画>` と `tools/check-file.sh` が PASS。
2. `scripts/frontend-gate.sh --full <ディレクトリ>` が PASS（SKIP の段は理由を自己点検票に写す）。
3. `scripts/token-lint.sh` と `scripts/motion-lint.sh` が 0 件。デザイナーの fidelity-check が PASS、ai-look-check の帯が clean。
4. `scripts/self-check.sh <自己点検票>` が PASS。判定は充足か未確認だけで、結果に数字がある。
5. 秘書に返す 3 つ（要約・未解決の対立・承認が要る判断）が `skills/secretary/scripts/reply-check.sh` を通る。
