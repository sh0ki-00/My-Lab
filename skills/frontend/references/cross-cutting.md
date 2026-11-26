# 横断事項: 動き、国際化、安全、型と道具、トークン

> **3 行でわかる要約**
> 1. 画面のどの部品にも効く 5 つの決まりを、計画の段階で決めて表に書く文書である。
> 2. 動きは縮小版を持ち、文言は表から取り、HTML は無害化する。型は境界で確かめ、値はトークンで参照する。
> 3. 5 つとも機械で落とす。motion-lint、token-lint と、計画書にある横断事項の表の検査である。

## 動き

動きは、応答の動きと場面の演出の 2 種類に分ける。応答の動き（押した、選んだ、開いたへの返事）は、どの型でも場面ごとに ms と曲線を決める。上限は、今の型と既存に合わせる型で 300ms 未満、没入の型で 200ms までである。場面の演出（場面から場面へ移る間の振り付け）は没入の型だけが使う。決まりの全文と、デザイナーの 4 つの区分との対応は `immersive.md` にある。

| 動きの種類 | 使える型 | 長さ | 縮小版（prefers-reduced-motion のとき） |
|---|---|---|---|
| 応答の動き | すべての型 | 今の型と既存に合わせる型は 300ms 未満、没入の型は 200ms まで | 0ms。位置の動きを残さない |
| 場面の演出 | 没入の型だけ | 300ms で縛らない。飛ばせる、縮小版がある、入力を失わない、最初のフレームが 100ms 以内、の 4 つで縛る | 位置の動かない溶け込みにしてよい。終わりの状態は同じにする |

縮小版の分岐は、動きのあるセレクタを同じセレクタで上書きする。分岐の条件は prefers-reduced-motion（動きを減らす設定）である。transition: all は、動かすつもりの無い属性まで動かすので使わない。時間はトークン（--duration-*）で参照し、縮小版はトークンの側で書き換える。

| 決まり | 機械の検査 | 落ちる例 |
|---|---|---|
| 動きのあるセレクタを、縮小版の分岐が同じセレクタか * で上書きする | motion-lint | transition: transform 240ms に縮小版が無い。分岐が無関係のセレクタだけを上書きしている |
| 時間のトークンは、縮小版の分岐の中で書き換える | motion-lint | --duration-2: 240ms を、prefers-reduced-motion: reduce の中で書き換えていない |
| transition: all を書かない | motion-lint | transition: all 0.3s |
| 色だけの transition は縮小版が無くてもよい | motion-allow.txt | transition: background-color 80ms（カンマで分けた全部が色か透明度のときだけ通る） |
| JavaScript の動きは、同じモジュールに縮小版の分岐を持つ。canvas のエンジンは、止める関数を持てば判断を呼ぶ側に任せてよい | motion-lint。縮小版で止まるかは motion-measure の項目 6 | element.animate や、requestAnimationFrame で style を書き換える動きに、prefers-reduced-motion が無い |
| 500ms を超える JavaScript の動きには、同じモジュールに飛ばす手段を置く | motion-lint | 1,400ms の animate があるのに、finish() も skip の関数も無い。別のファイルの skipWaiting() は数えない |
| 音は同じモジュールに消音の手段を持ち、自動再生しない | motion-lint | AudioContext に消音のスイッチが無い。色のトークン --muted と video の muted 属性は消音と数えない。audio の autoplay。muted の無い video の autoplay |
| 回り続ける動きには、同じファイルに止める手段を置く | motion-lint | infinite の animation に、animation-play-state: paused も pause() も無い。別のファイルの関係の無い cancel() では通さない |

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

場面の演出の行と、JavaScript・音・回り続ける動きの決まりは、2026-11-26 に足した社内の決めである。決まりの全文は `immersive.md` にある。WCAG 2.2 の 2.2.2 と 1.4.2 の本文は開いておらず、手元の知識で書いた。
