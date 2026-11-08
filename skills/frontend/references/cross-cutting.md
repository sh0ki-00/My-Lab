# 横断事項: 動き、国際化、安全、型と道具、トークン

> **3 行でわかる要約**
> 1. 画面のどの部品にも効く 5 つの決まりを、計画の段階で決めて表に書く文書である。
> 2. 動きは縮小版を持ち、文言は表から取り、HTML は無害化する。型は境界で確かめ、値はトークンで参照する。
> 3. 5 つとも機械で落とす。motion-lint、token-lint と、計画書にある横断事項の表の検査である。

## 動き

動きは場面ごとに ms と曲線を決め、どれも 300ms 未満にする。prefers-reduced-motion（動きを減らす設定）のときは 0ms にし、位置の動きを残さない。transition: all は、動かすつもりの無い属性まで動かすので使わない。時間はトークン（--duration-*）で参照し、縮小版はトークンの側で 0ms に上書きする。

| 決まり | 機械の検査 | 落ちる例 |
|---|---|---|
| 時間を数字で書いた指定には、同じファイルに縮小版を置く | motion-lint | transition: transform 240ms で、prefers-reduced-motion が無い |
| transition: all を書かない | motion-lint | transition: all 0.3s |
| 時間はトークンで参照する | motion-lint は通す。token-lint の対象外 | transition: transform var(--duration-2) |
| 色だけの transition は縮小版が無くてもよい | motion-allow.txt | transition: background-color 80ms |

## 国際化

画面の言葉は国際化の表（ja.json、en.json）から取り、部品の中に日本語の文字列を書かない。文は連結せず、ICU 形式（複数形と選択を書ける文言の形式）で 1 文を 1 つの鍵にする。日付・数・金額は Intl で書式化し、toFixed や getFullYear と区切り文字の連結で組み立てない。

| 決まり | 確かめ方 | 落ちる例 |
|---|---|---|
| 部品に日本語の文字列を書かない | grep で i18n の外の日本語リテラルを探す | const label = "出荷指示" |
| 文を連結しない | 鍵の数と文の数が同じ | count + " 件" |
| Intl で書式化する | toFixed、getFullYear、locale 無しの toLocaleDateString を grep | d.getFullYear() + "/" |
| 複数形は ICU の plural | en の文に plural がある | "{count} orders" だけ |

管理画面が日本語だけでも、表に分ける。文言の修正が部品の修正と分かれ、デザイナーの言葉の表と 1 対 1 になる。

## 安全

ブラウザ側の安全は 4 つの穴を塞ぐ。穴は、無害化していない HTML の挿入・文字列からのコード生成・ブラウザに出る鍵・CSP の欠落である。CSP は、読み込みと実行を制限する HTTP ヘッダーである。

| 決まり | 落ちる例 | 直し方 |
|---|---|---|
| 無害化なしの HTML を入れない | dangerouslySetInnerHTML、.innerHTML = | DOMPurify.sanitize を通すか、文字列として描く |
| 文字列からコードを作らない | eval(、new Function( | 書かない。設定は JSON で読む |
| 鍵をブラウザに出さない | NEXT_PUBLIC_ で始まる名前に SECRET、KEY、TOKEN | サーバー側だけで読む。server-only |
| CSP を置く | ヘッダーが無い | report-only で違反報告を 3 日見て、0 なら enforce |

秘密情報（API の鍵、トークン）をコード・ログ・会話に書かない。gitleaks（秘密情報の漏れを探す道具）が CI で落とす。

## 型と道具

型は境界で確かめる。API の応答は zod（型のとおりかを実行時に確かめる道具）で検証し、検証を通った値だけを部品に渡す。tsc は strict にする。eslint は strictTypeChecked と jsx-a11y の strict で、警告 0 で通す。テストは vitest と Playwright（ブラウザの自動操作の道具）で書く。

| 道具 | 設定 | 検査の段 |
|---|---|---|
| tsc | strict、noUncheckedIndexedAccess | frontend-gate.sh の「型」 |
| eslint | strictTypeChecked、jsx-a11y strict、max-warnings 0 | 「lint」 |
| zod | API の応答と URL のクエリを parse | 単体テスト |
| vitest、Playwright | テストの対応表の 1 対 1 | 「単体」と端から端まで |
| size-limit | 初期表示の JS の上限 | 「束」 |

道具が無いプロジェクトでは、frontend-gate.sh が SKIP と理由を出す。導入は提案し、承認を得てから入れる。

## トークン

色・大きさ・余白・書体・時間は、デザイナーの tokens.css の変数だけで参照する。部品の CSS に生の 16 進、px（0 と 1px を除く）、書体名を書かない。トークンの定義は CSS 変数か、Design Tokens 形式（W3C のコミュニティグループが定める JSON）で受け取る。

| 決まり | 機械の検査 | 落ちる例 |
|---|---|---|
| 色は var(--…) | token-lint | color: #1a1a1a、rgb(…)、white |
| 大きさと余白は var(--…) | token-lint | padding: 16px |
| 書体は var(--font-…) | token-lint | font-family: Inter |
| 1px の罫線と 0 は生でよい | token-lint の規則 | border: 1px solid var(--rule) は通る |
| トークンの定義は tokens を含む名前のファイルに置く | token-lint の対象外 | tokens.css、tokens-order-list.css |

トークンに無い値が要るときは、部品に書かずにデザイナーへ返し、計画書とトークンに足してもらう。

## 付録: 出典

出典は、調査ブリーフの検証役が 2026-11-05 に本文を開いて確かめたものである。

| 出典 | 使った節 |
|---|---|
| WCAG 2.2「2.3.3 Animation from Interactions」、MDN「prefers-reduced-motion」 | 動き |
| ICU「MessageFormat」、MDN「Intl」 | 国際化 |
| OWASP「DOM based XSS Prevention Cheat Sheet」、MDN「Content Security Policy」 | 安全 |
| typescript-eslint「strict-type-checked」、eslint-plugin-jsx-a11y README | 型と道具 |
| W3C Design Tokens Community Group「Design Tokens Format Module」（2025.10） | トークン |
