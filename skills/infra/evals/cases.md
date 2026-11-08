# infra の試験ケース

> **3 行でわかる要約**
> 1. infra の検査 7 本を、正例と負例で確かめる試験ケースの一覧です。
> 2. 実行は run.sh で、ケースごとに期待と実際を比べ、最後に RESULT の行を出します。
> 3. 規則を足したら、ここと run.sh と fixtures の負例を同時に足してください。

## ケース

この節は、ケースと期待の表です。どれも機械で判定できるものだけを置きます。

| # | ケース | 入力 | 期待 |
|---|---|---|---|
| 1 | 完成例の設計書 | examples/infra-design-order-list.md | arch-check が PASS |
| 2 | 雛形のままの設計書 | templates/infra-design.md | arch-check が「雛形の穴」で FAIL |
| 3 | 欠けのある設計書 | fixtures/bad-design.md | 6 本の柱・ネットワーク・IAM・秘密情報・暗号化・監査ログ・復元・目標と実測・環境の差・費用の幅・流出経路・信頼の根・攻撃者の目・推測で FAIL |
| 4 | 良い構成コード | fixtures/good-iac（.tf.in を .tf に写す） | iac-scan が PASS |
| 5 | 穴のある構成コード | fixtures/bad-iac（同上） | IAC-001〜012 と「例外の理由」と「境界の外」で FAIL |
| 6 | 見本の構成コード | samples/infra（あれば） | iac-scan が PASS |
| 7 | 見本を壊した構成コード | samples/infra の写しで、データベースを公開・22 番を全開・本番の保持を 1 日に | IAC-006・IAC-004・IAC-008 で FAIL |
| 8 | 復元の訓練 | restore-drill --rows 5000 --rto 60 | PASS で、行数と中身が一致 |
| 9 | 復元の目標を超える | restore-drill --rows 5000 --rto 0 | 「RTO」で FAIL |
| 10 | 計画の関所 | plan-gate --selftest（計画の JSON を 20 通り組み立てる） | 置き換えと削除とデータを消す変更と一覧の外の部品と前提の検査で止め、一覧の外の型と属性と来歴の無いダイジェストと構成の provisioner は ROUTE: guarded |
| 11 | データベースの権限 | db-grants-check --selftest（正例 3 つと負例 29 個） | 一括の権限、列の食い違い、正本の外の表、RLS の欠け、全店を見る値、via の道の欠け、店の制限の無い表への書き込み、鍵で絞らない関数、実行中の文の見方、最後の検査の一覧の食い違い、関数の PUBLIC の EXECUTE、突き合わせの手続きと毎時の予定の欠け、別の search_path で取る指紋、規則を数えない突き合わせ、移行の行の書き込みを止めるトリガーの欠け、search_path の固定の欠け、旧い書き手の全行の方針の欠け、書き手の始まりの関数の欠けと見落とし、正本に無い取引の上限で FAIL |
| 12 | 見本の権限と正本 | db-grants-check samples/api/db-access.json samples/infra/db/roles.sql（両方あれば） | PASS |
| 13 | 部品の一覧の差分 | deps-diff --selftest（lock の file を 7 通り組み立てる） | 変化なしは PASS、新しい部品・版の変更・消えた部品は知らせ、登録所の外の取り込み元・指紋の欠け・指紋だけの変更・新しい入れ時の命令で FAIL |
| 14 | 自前のコードの外へ移る処理 | egress-check --selftest（file を 13 通り組み立てる） | 同じ源への読みと部品の中は PASS、画面の移動・新しい窓・ビーコン・外の宛先への送り・組み立てた宛先・API の外への接続で FAIL |
| 15 | 見本の API の外への接続 | egress-check samples/api（あれば） | PASS |
| 16 | 移行の文の許す一覧 | migrate-gate --selftest（正例 3 つと負例 20 個） | 足し算の DDL の正例は PASS、行の写し・note への写し・トリガーの関数の書き換え・規則・rds_iam への付与・スキーマ・写しの表・既定値の関数・索引の式の関数・守りのトリガーの停止・型の書き直し・psql の命令・search_path と役割の変更・DO・列の削除・行の制限の停止・持ち主の変更・COPY・引用した名前で FAIL |
