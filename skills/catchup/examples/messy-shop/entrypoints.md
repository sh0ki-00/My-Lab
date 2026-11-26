# 入口: messy-shop

> **3 行でわかる要約**
> 1. messy-shop の画面と API のルート、夜の処理、外とのつながりを並べた節です。
> 2. ルートは 14 本で、そのうち 1 本は注釈の中にあり動いていません。夜の処理は 3 つで、cron の設定はサーバーにあります。
> 3. 書き込むテーブルの列で、依頼が触るルートと処理を探してください。

## 1. 画面と API

ルートは 14 本あり、お店の管理画面が 9 本、お客様の画面が 4 本、決済会社からの知らせが 1 本です。管理画面のうちレポートの 1 本は、ルートの行が注釈になっていて動きません。

| ルート | 処理 | 書き込むテーブル | 根拠 |
|---|---|---|---|
| /admin/ | トップ。月次の表（daily_stats）と会員の数を出す | なし | F-019、app/stats.py:5-11 |
| /admin/orders | 注文一覧。削除の印が 2 つとも無い注文だけを出す | なし | F-020、app/orders.py:84 |
| /admin/order | 注文の明細。送料の行も品物の 1 行として出る | なし | F-021、app/orders.py:75-80、Q-044 |
| /admin/order/cancel | キャンセル。決済の行を消し、status を canceled にする | payments、orders | F-022、app/orders.py:47-50 |
| /admin/order/delete | 削除。deleted_at を書く | orders | F-023、app/orders.py:53-55 |
| /admin/orders/bulk | 一括の削除。is_deleted を 1 にする | orders | F-024、app/views.py:93-99 |
| /admin/products | 品物の一覧。is_active が 1 の品物だけを出す | なし | F-025、app/views.py:104 |
| /admin/newsletter | お知らせのメールの相手の数。mail_ok が 1 の会員 | なし | F-026、app/mail_report.py:19-21 |
| /admin/reports | レポート。ルートの行が注釈で、動いていない | なし | F-027、app/views.py:113 |
| /shop/register | 会員登録。mail_ok を 1 か 0 で書く | customers | F-028、app/customers.py:7-13 |
| /shop/order | 注文。注文と明細を書き、在庫を減らす。トリガーが送料の行を足す | orders、order_items、products | F-029、app/orders.py:16-30、Q-045 |
| /shop/reserve | 予約。注文を書いてから reserved にする | orders、order_items、products | F-030、app/preorder.py:6-9 |
| /shop/mypage/mail | お知らせのメールの設定 | customers | F-031、app/customers.py:16-18 |
| /pay/notify | 決済会社からの入金の知らせ。決済の行を書き、paid にする | payments、orders | F-032、app/orders.py:33-44 |

## 2. 定時の処理とコマンド

夜の処理は jobs.py から名前で呼び、cron の設定はサーバーにあります。発売の日の処理は、呼ぶ所が見つかりません。

| 処理 | すること | 書き込むテーブル | 根拠 |
|---|---|---|---|
| jobs.py の stats | 前の日（日本時間）の注文の数と売上を daily_stats に書く | daily_stats | app/batch_nightly.py:12-21、Q-052 |
| jobs.py の stock_alert | 在庫が 5 より少ない品物を返す | なし | app/batch_nightly.py:24-26 |
| jobs.py の carrier | 運送会社の CSV を取り込み、出荷の行と状態を書く | shipments、orders | app/batch_carrier.py:10-30、Q-038 |
| mail_report.py の weekly | この 7 日の注文の数と売上を出す。月曜の朝に cron が回す | なし | app/mail_report.py:33-37 |
| reports.py の年の集計 | 年の売上と、売れた品物の個数を出す | なし | app/reports.py:1-3、app/reports.py:96-101 |
| preorder.py の release | 予約を入金待ちに戻す。呼ぶ所は見つからない | orders | app/preorder.py:12-18 |
| cron の設定 | サーバーにあり、このリポジトリには無い | なし | app/MEMO.txt:9 |

## 3. 外とのつながり

外とのつながりは 3 つで、2 つは外から届き、1 つは外へ送ります。

| つながり | 向き | 根拠 |
|---|---|---|
| 決済会社からの入金の知らせ（/pay/notify） | 外から届く | F-040、app/views.py:167-176 |
| 運送会社の CSV。置き場は環境変数 CARRIER_CSV_DIR | 外から届く（ファイル） | F-041、app/config.py:13、app/batch_carrier.py:11 |
| お知らせのメールと毎週のメール。送る関数は呼ぶ側が渡す | 外へ送る | app/mail_report.py:24-30、app/mail_report.py:34 |
