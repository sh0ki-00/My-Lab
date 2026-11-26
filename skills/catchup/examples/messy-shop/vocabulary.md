# 語彙: messy-shop

> **3 行でわかる要約**
> 1. 画面に出る語と、コードとデータの名前を結びつけた節です。
> 2. 依頼者の語はまだ聞いていないので、どの行も「未確認」です。「売上」は数える場所ごとに定義が 3 つあります。
> 3. 数の語が出る依頼では、どの場所の数かを先に決め、2 節の条件で数えてください。

## 1. 依頼者の語と名前

依頼者にはまだ聞いていないので、依頼者の語の列には画面の語を入れ、コードとデータの名前に結びつけました。確かめた相手の列は「未確認」です。

| 依頼者の語 | コードとデータの名前 | 根拠 | 確かめた相手 |
|---|---|---|---|
| 注文 | orders の 1 行 | app/views.py:67 | 未確認（コードの文言から） |
| 会員 | customers の 1 行。会員の数は全部の行を数える | app/views.py:54、app/customers.py:25-27 | 未確認（コードの文言から） |
| 品物 | products の 1 行。送料の行のための SHIP も 1 行ある | app/views.py:105、Q-044 | 未確認（コードの文言から） |
| 入金待ち、入金済み、発送済み、配達済み、キャンセル | status の pending、paid、shipped、delivered、canceled | app/models.py:18-24 | 未確認（コードの文言から） |
| 予約 | status の reserved。表示の名前は無い | app/preorder.py:1、app/preorder.py:8 | 未確認（コードの文言から） |
| 送料 | orders.shipping_fee。合計には入れない | app/models.py:39、app/config.py:9 | 未確認（コードの文言から） |
| 削除 | deleted_at か is_deleted のどちらかがある注文 | app/orders.py:55、app/views.py:98、Q-023 | 未確認（コードの文言から） |
| 出荷 | shipments の行。orders.shipped_at は使われていない | app/batch_carrier.py:17、Q-017 | 未確認（コードの文言から） |
| お知らせのメール | customers.mail_ok が 1 の会員に送る | app/mail_report.py:19-21 | 未確認（コードの文言から） |

## 2. 数の定義

数の語は、数える場所ごとに条件が違います。トップの画面で見える数は、データの節の 4 節で再現しました。

| 語 | 数える場所 | 条件 | 値 | 根拠 |
|---|---|---|---|---|
| 売上 | トップの画面（夜の処理） | 日本時間の日で数える。canceled を除き、deleted_at が空。合計と送料の和 | 2026-09 は 535,403 円 | app/batch_nightly.py:7-8、Q-060 |
| 売上 | レポートの画面（ルートは注釈の中） | 協定世界時の月で数える。paid、shipped、delivered だけ。合計だけ | 2026-09 は 347,996 円 | app/reports.py:16-17、Q-060 |
| 売上 | 毎週のメール | canceled と pending を除き、is_deleted が 0。合計と送料の和 | 同じ条件で 2026-09 を数えると 536,996 円 | app/mail_report.py:13-14、Q-060 |
| 注文 | トップの画面 | 売上と同じ条件の件数 | 2026-09 は 223 件 | app/batch_nightly.py:7-8、Q-051 |
| キャンセル | レポートの画面 | status が canceled だけ。cancel は数えない | 全期間で 457 件 | app/reports.py:55、Q-018 |
| 年の売上 | reports.py の年の集計 | 決済の行と結合して足す。ギフト券の注文を 2 回数える | 2025 年は 4,690,686 円。重ならない数え方なら 4,108,929 円 | app/reports.py:26-29、Q-057 |
