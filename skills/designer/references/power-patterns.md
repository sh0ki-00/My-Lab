# 超高機能 UI の 7 つの型

> **3 行でわかる要約**
> 1. 超高機能 UI の 7 つの型を、出典つきで並べた文書である。型は、密度・キーボード・コマンドパレット・インライン編集・多ペイン・一括操作・保存ビューである。
> 2. どの型も「速く片付く」ための機能であり、装飾ではない。用事に合う型だけを選び、計画書のレイアウトとキーボードの節に写す。
> 3. キーボードは製品の作法（J と K、Ctrl+K）と W3C の作法（矢印、Home と End、Tab の止まり先）の両方を持つ。

## 1. 7 つの型

型は 7 つで、どれも公開された製品か指針から取る。数値の目安は、出典のあるものと社内の決めごとを分けて書く。

| 型 | 中身 | 数値の目安 | 出典 |
|---|---|---|---|
| 密度 | 行高を詰めた表、見出し行と 1 列目の固定、1 画面に多くの行 | 行高 32〜40px（社内の決めごと。14px の文字に上下 9〜13px） | Linear の再設計（密度と階層を上げる） |
| キーボード | 1 文字キー（J と K、S、E）、2 キーの移動（G のあと O）、? で一覧 | 主要な用事がマウスなしで終わる | Superhuman、Linear、Notion、Figma |
| コマンドパレット | 1 つの入力欄に全操作を集め、横にキーを出して教える。あいまい一致と別名 | 画面の全操作が並ぶ | Superhuman、Raycast、Linear |
| インライン編集 | 一覧の上で値をその場で直す。Enter で確定、Esc で戻す | 狭い範囲の編集だけ。深い編集はペインへ | NN/g のデータ表 |
| 多ペイン | 一覧の右に詳細を開き、一覧を隠さない | ペインの幅 480px 前後（社内の決めごと） | NN/g の非モーダルのペイン |
| 一括操作 | チェック列で選び、表の上下の帯から操作する。取り消しを持つ | 取り消しの期限は置かない（WCAG 2.2 の 2.2.1） | NN/g、NN/g の 10 ヒューリスティクスの 3 |
| 保存ビュー | 絞り込みと並び順に名前を付けて保存し、URL で共有する | 毎朝の条件を入れ直させない | Linear の custom views、Stripe の検索 |

## 2. キーボードの決まり

製品の作法だけでは、目の見える人のキーで終わる。読み上げの利用者が表を移るのは矢印キーなので、W3C の APG（部品ごとのキーボード操作の作法集）の型を必ず重ねる。

| 決まり | 理由 | 出典 |
|---|---|---|
| Tab の止まり先は表全体で 1 つ。表の中は矢印、Home と End、Page Up と Page Down で移る | 読み上げの利用者の表の移動は矢印で決まる | APG の grid |
| コマンドパレットは combobox と dialog の型で作る | 焦点の戻し先と Esc の振る舞いが決まっている | APG の combobox と dialog |
| 1 文字キーは、表に焦点があるときだけ有効にし、設定でオフにできる | 音声入力で「出荷」と話すと S が発火する事故を防ぐ | WCAG 2.2 の 2.1.4 |
| Ctrl と Cmd を併記する | Mac の担当者が最初のキーで迷わない | Linear の文書の書き方 |
| 取り消しに期限を置かない。置くなら理由を書く | 反応の機会の期限も時間制限に数える | WCAG 2.2 の 2.2.1 |
| 焦点の枠は outline で描く | 強制カラーでは box-shadow が消える | MDN の forced-colors |

## 3. データ表の 4 つの用事

データ表は 4 つの用事で設計する。用事ごとに要る部品が違い、全部を 1 つの表に詰めると密度も速さも失う。

| 用事 | 要る部品 | 置き場 |
|---|---|---|
| 見つける | 検索、絞り込み、保存ビュー、1 列目の人が読める識別子 | 表の上の帯と 1 列目 |
| 比べる | 固定の見出し行、等幅の数字、右ぞろえの金額、並び替え | 表の中 |
| 1 行を見る、直す | 右ペイン、狭い範囲のインライン編集 | 一覧の右と、行の中 |
| 操作する | チェック列、一括操作の帯、取り消し | 表の上下の帯 |

## 4. 着地ページと読み物の型

この文書の型は管理画面とアプリのものである。着地ページとブランドサイトの型は、段階 3 の範囲に入れていない。見出しの書体の選び方、画像の扱い、余白のリズム、スクロールの演出の節度がそれである。依頼が来たら、計画書の「方向」で主題から決める。着地ページの既定（Hero、3 枚のカード、CTA）に落ちないことだけを守る。

| 場面 | 今の扱い |
|---|---|
| 着地ページ | 既定の型に落ちないことを `ai-look-check.sh` で見る。型の目録は第 2 版で足す |
| 読み物（記事、ヘルプ） | 本文 14〜16px、行間 1.5〜1.7、1 行 35〜45 字（社内の決めごと） |

## 付録: 出典

出典は、調査ブリーフの検証役が 2026-11-05 に本文を開いて確かめたものである。Linear の記事は密度と階層の方針の出典で、行高の数値は書いていない。

| # | 出典 | 使った節 |
|---|---|---|
| 1 | Linear「How we redesigned the Linear UI」 https://linear.app/now/how-we-redesigned-the-linear-ui | 1 |
| 2 | Linear「Navigating Linear」 https://linear.app/enablement/guides/navigating-linear 、「Custom views」 https://linear.app/docs/custom-views | 1 |
| 3 | Superhuman「How to build a remarkable command palette」 https://blog.superhuman.com/how-to-build-a-remarkable-command-palette/ | 1 |
| 4 | Raycast Manual「Action Panel」 https://manual.raycast.com/action-panel 、「Command Aliases & Hotkeys」 https://manual.raycast.com/command-aliases-and-hotkeys | 1 |
| 5 | Notion「Keyboard shortcuts」 https://www.notion.com/help/keyboard-shortcuts 、Figma「Use shortcuts and quick actions」 https://help.figma.com/hc/en-us/articles/360040328653-Use-shortcuts-and-quick-actions | 1 |
| 6 | NN/g「Data Tables: Four Major User Tasks」 https://www.nngroup.com/articles/data-tables/ 、「10 Usability Heuristics」 https://www.nngroup.com/articles/ten-usability-heuristics/ | 1、3 |
| 7 | Stripe Docs「ダッシュボードで検索を実行する」 https://docs.stripe.com/dashboard/search | 1 |
| 8 | W3C APG「Grid」 https://www.w3.org/WAI/ARIA/apg/patterns/grid/ 、パターン一覧 https://www.w3.org/WAI/ARIA/apg/patterns/ | 2 |
| 9 | W3C「Understanding SC 2.1.4 Character Key Shortcuts」 https://www.w3.org/WAI/WCAG22/Understanding/character-key-shortcuts.html | 2 |
| 10 | MDN「forced-colors」 https://developer.mozilla.org/en-US/docs/Web/CSS/@media/forced-colors | 2 |
