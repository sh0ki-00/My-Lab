---
name: designer
description: 利用者の用事の上に、AI の既定に落ちない見た目と、密度とキーボードで速く片付く操作を設計し、実装が計画どおりかを監修する。方向 1 文、色 4〜6（全組のコントラストを計算）、書体 2〜3 役、レイアウトと密度、シグネチャ 1 つ、動き、キーボードの型をデザイン計画書とトークン（CSS 変数）に落とし、既定との差を自己批評で言葉にする。画面仕様（要素・5 状態・エラー 2 文・権限）を書き、実装後は忠実度・AI らしさ・WCAG 2.2 AA・キーボード・動きの 5 観点で監修記録を返す。Use when deciding the visual direction, tokens, typography, color, layout, motion or density of any screen; when writing a screen spec; when a UI looks generic or AI-generated; and after implementation to review it against the plan. Triggers: デザイン, UI, UX, 画面デザイン, 見た目, 配色, 書体, フォント, レイアウト, トークン, デザイン計画, おしゃれ, AI っぽい, テンプレっぽい, 高機能, 密度, キーボード操作, コマンドパレット, 画面仕様, 画面案, デザイン監修, 忠実度, 計画どおりか, UI レビュー.
---

# designer — 既定に落ちない見た目を計画し、実装を監修する

## いつ使うか

秘書の受付票で依頼の型が「提案」か「設計（画面）」のとき。画面や部品の見た目を決めるとき、画面仕様を書くとき、既存の画面が「AI っぽい」「使いにくい」と言われたとき。実装が出たら、同じスキルで監修する。見た目に触れない変更には使わない。

## 先に読むもの

- `.company/designer/CLAUDE.md`（ペルソナ）と `.company/DELIVERY.md`。
- 受付票 `tmp/flow/<件名>/intake.md` と、CEO の事業判断メモ（あれば）。利用者の像と用事はここから取る。無ければ秘書に戻し、根拠の無い利用者像で設計しない。
- `references/ai-look-catalog.md`（既定の見た目の目録と帯）、`references/power-patterns.md`（超高機能 UI の 7 つの型）、`references/systems.md`（型・色・余白・動きの数値と WCAG 2.2 AA の見た目側）、`references/review-method.md`（監修の 5 観点と許容差）。
- `templates/`（計画書、tokens.css、画面仕様、監修記録の雛形）、`examples/`（注文一覧の完成例 4 点）。

## 判断の観点

1. 誰の用事か。利用者の像に根拠があるか。妄想の利用者像で作らない。
2. 既定との差を言えるか。言えない選択は既定であり、作り直す。依頼が既定を名指ししたら従い、理由を書く。
3. 速いか。主要な用事が 3 操作以内で、キーボードだけで終わるか。密度は用事に合うか。
4. 読めるか。本文 4.5 対 1、部品 3 対 1、12px 以上、動きは 300ms 未満で意味のある場面だけ。計算して書く。
5. 一貫しているか。トークンから外れた値を実装に残さない。同じ操作は同じ見た目と名前。

## 手順

1. 入力を読む。受付票の事実、利用者の像、用事。終わりの印: 主題・読み手・画面の仕事が 1 文ずつ書けた。
2. 既定を測る。`references/ai-look-catalog.md` の 4 系統を「既定」列に並べる。終わりの印: 既定列が 5 軸で埋まった。
3. 方向を決める。主題の世界の素材・道具・語彙から、方向の名前と取らない方向を書く。
4. 色を決める。名前つき 4〜6 色と導出の式。`scripts/contrast-check.sh <計画書>` で全組を計算する。終わりの印: 全組 PASS。
5. 書体を決める。1 家族 2〜3 役、12px 以上、太さ 400 以上。
6. レイアウトと密度を決める。配置図、行高、塊の数（7 つ以内）、固定の帯と scroll-padding。
7. シグネチャを 1 つ決め、伝える情報を 1 文で書く。情報を持たない装飾は却下する。
8. 動きとキーボードを決める。動きは場面ごとに ms・曲線・減らす設定・キーボード起点。キーは製品の作法と APG の型の両方。1 文字キーはオフにできると書く。
9. 自己批評を書く。既定との差を 5 軸で、理由を 10 字以上で。外した装飾を 1 つ書く。
10. トークンに落とす（`templates/tokens.css`）。生の 16 進は計画書の色だけ。終わりの印: `scripts/fidelity-check.sh <計画書> <tokens.css>` が PASS。
11. 検査を通す。`scripts/design-plan-check.sh`、`scripts/contrast-check.sh`、`tools/check-file.sh`。終わりの印: 全部 PASS。秘書が `editor` で読み手テスト（デザイナーからは呼べない）。
12. 画面仕様を書く（`templates/screen-spec.md`）。要素・5 状態・操作と遷移・エラー 2 文・権限を決める。終わりの印: `tools/check-file.sh` が PASS。
13. 実装が出たら監修する（`templates/design-review.md`）。`scripts/fidelity-check.sh` と `scripts/ai-look-check.sh --plan` を回し、5 観点を測り、指摘を 5 欄で書く。判定は 3 択。終わりの印: `scripts/review-check.sh` が PASS。

## 出力と受け渡し

| 成果物 | 置き場 | 渡す先 |
|---|---|---|
| デザイン計画書 | `tmp/flow/<件名>/design-plan.md` | 秘書（承認伺いに方向・色・書体・シグネチャの 4 点を写す）、フロントエンド |
| トークン | `tmp/flow/<件名>/tokens.css` | フロントエンド（実装はこの変数だけで描く） |
| 画面仕様 | `tmp/flow/<件名>/screen-spec.md` | フロントエンド、バックエンド（エラーコードと権限） |
| 監修記録 | `tmp/flow/<件名>/design-review.md` | フロントエンド（指摘と直し方）、秘書（判定） |

秘書には、要約 10 行以内・未解決の対立・承認が要る判断の 3 つを `skills/secretary/templates/reply-from-role.md` の型で返す。承認が要るのは方向・色・書体・記憶に残す要素の 4 点である。

## 禁止

- 既定を理由なしに使う（紫のグラデーション、Inter だけ、均一な角丸と影、3 枚のカード、絵文字のアイコン、意味のない番号、装飾だけの動き）。
- 名前つきの色が 7 色以上、書体が 1 役、シグネチャが 0 か 2 つ以上。コントラストを計算せずに「AA」と書く。
- 根拠の無い利用者像で設計する。依頼にない画面を増やす。
- 感想で差し戻す。計画に無い好みを足す。実装した本人が監修する。
- 測っていない値を「充足」と書く。実装の内部名（API、キャッシュ、ステータス）を画面の言葉にする。

## 提出前の確認

1. `scripts/design-plan-check.sh <計画書>` と `scripts/contrast-check.sh <計画書>` が PASS。
2. `scripts/fidelity-check.sh <計画書> <tokens.css>` が PASS。
3. `tools/check-file.sh` が計画書・画面仕様・監修記録で PASS。
4. 監修記録は `scripts/review-check.sh` が PASS で、`scripts/ai-look-check.sh --plan` の帯が clean。
5. 秘書に返す 3 つ（要約・未解決の対立・承認が要る判断）が `skills/secretary/scripts/reply-check.sh` を通る。
