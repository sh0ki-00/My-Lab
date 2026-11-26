# 完成例の作り方: messy-shop でキャッチアップを回した記録

> **3 行でわかる要約**
> 1. 完成例の地図（messy-shop/）を作るために、2026-11-26 に回したコマンドと結果の記録です。
> 2. 道具はどれも PASS で、地図の検査は節 7、古い節 0、入口 58 行で通りました。
> 3. 地図の数を確かめ直すときは、2 節のコマンドを上から回し、RESULT の行を比べてください。

## 1. 目的

この記録は、完成例の数が実際に回した結果であることを、読み手が確かめるためのものです。題材は、罠を仕込んだ通販のサンプル samples/messy-shop です。

キャッチアップ（作業の前にプロジェクトを掴むこと）の側に渡したのは、app/ のコードと、build.py で作った DB だけです。問いと正答と採点の物は、道具の --exclude で読まない所にしました。

| 項目 | 内容 |
|---|---|
| 回した日 | 2026-11-26（記録の時刻は 10:56 から 11:01） |
| プロジェクトの直下 | samples/messy-shop |
| DB | build.py で、作業の場所（リポジトリの外）に作った sqlite の shop.db |
| 環境の名前 | 手元の作り物（build.py で作った DB） |
| 地図の置き場 | messy-shop/（データの節は backend のスキルの完成例） |

## 2. 回したコマンドと結果

コマンドは、My-Lab の直下で回しました。作業の場所のパスは、手元の一時の場所なので「（作業の場所）」と書いています。

| 順 | すること | コマンド | 結果 |
|---|---|---|---|
| 1 | 事実を拾う | bash skills/catchup/scripts/catchup-facts.sh --root samples/messy-shop --exclude answers --exclude questions.md --exclude build.py --exclude score.py --exclude README.md --out skills/catchup/examples/messy-shop/facts.jsonl | RESULT: PASS（事実 48、F-001〜F-048）。同じ引数の 1 回目は 0.09 秒 |
| 2 | DB を作る | python3 samples/messy-shop/build.py （作業の場所）/shop.db | テーブル 7 つ。orders 9152 行、order_items 20874 行ほか。0.64 秒 |
| 3 | スキーマを書き出す | bash skills/backend/scripts/schema-snapshot.sh --db （作業の場所）/shop.db --env 手元の作り物（build.py で作った DB） --out skills/catchup/examples/messy-shop/schema.json --from-migrations に 4 本の SQL | RESULT: PASS（テーブル 7、ずれ 1、ハッシュ値 74659ebc2c067f88）。ずれはトリガー trg_orders_after_insert |
| 4 | 全部のテーブルを集計する | bash skills/backend/scripts/data-profile.sh --db （作業の場所）/shop.db --env （同上） --log skills/catchup/examples/messy-shop/queries.jsonl --draft （作業の場所）/data-draft.md | RESULT: PASS（テーブル 7、クエリ 39、打ち切り 0）。罠の候補 16 行 |
| 5 | 書き込む処理を挙げる | bash skills/backend/scripts/writers-map.sh --code （作業の場所。app/ の写しと shop.db だけ） --schema skills/catchup/examples/messy-shop/schema.json | RESULT: PASS（テーブル 7、書き込む処理 24、不明 0） |
| 6 | クエリを 1 本ずつ回す | bash skills/backend/scripts/data-query.sh を 23 回。目的は --purpose に書いた | Q-040〜Q-062。どれも RESULT: PASS |
| 7 | データの節を検査する | bash skills/backend/scripts/data-dictionary-check.sh skills/backend/examples/data-dictionary-messy-shop.md --root samples/messy-shop | RESULT: PASS（辞書 1、記録 62 本、FAIL 0） |
| 8 | 鮮度を記録する | bash skills/catchup/scripts/map-check.sh --stamp --root samples/messy-shop skills/catchup/examples/messy-shop | RESULT: PASS（節 7、根拠のファイル 16）。走査したファイル 19 本の一覧も記録。commit は 46cf84d |
| 9 | 地図を検査する | bash skills/catchup/scripts/map-check.sh --root samples/messy-shop skills/catchup/examples/messy-shop | RESULT: PASS（節 7、古い節 0、入口 58 行、FAIL 0） |

writers-map.sh には、app/ の写しだけを置いた作業の場所を渡しました。answers/ の中の SQL を、書き込む処理として拾わないためです。

査読のあとの直し（2026-11-26）で、順 1 と順 8 を回し直しました。事実の記録は、ルートの語に直した道具で作り直し、変わったのは F-033 と F-040 の文言だけです。鮮度の記録には、走査したファイルの一覧が加わりました。入口には、DB の読み取りの許可の行を足しています。

DB を読む 4 本の道具の時間は、同じ日に手元で測り直しました。作業の場所の shop.db に回した値で、記録は作業の場所に書いています。

| 道具 | かかった時間 | 結果 |
|---|---|---|
| schema-snapshot.sh | 0.08 秒 | RESULT: PASS（テーブル 7、ハッシュ値 74659ebc2c067f88） |
| data-profile.sh | 0.18 秒 | RESULT: PASS（テーブル 7、クエリ 39） |
| writers-map.sh（--code は samples/messy-shop/app） | 0.08 秒 | RESULT: PASS（書き込む処理 24、不明 0） |
| data-query.sh（状態ごとの件数の 1 本） | 0.08 秒 | RESULT: PASS（行 7） |

## 3. 読まなかった物と、読んだ順

読まなかったのは、サンプルの試験の材料です。問いを見てから地図を書くと、地図の効き目を測れなくなるからです。

| 物 | 扱い | 理由 |
|---|---|---|
| answers/ | 開いていない | 正答の置き場 |
| questions.md | 開いていない | 問い。地図を問いに合わせないため |
| build.py と score.py | 回しただけで、中身は読んでいない | DB の作り方と採点の方法 |
| README.md | 道具は読んでいない。この記録を書いた担当は、作業の前に読んだ | 罠があることだけが書かれ、罠の中身は無い |

読んだ順は、事実、DB、コードです。コードは、DB の集計と書き込む処理の候補を見たあとに、ルートと書き込む処理から読みました。

## 4. 最後の返答の例

依頼者への最後の返答は、次の 1 段落にしました。数は、上の結果と地図にある値です。

地図を tmp/catchup/ に作り、6 つの節の全部の行に根拠を付けました。テーブル 7 つとルート 14 本を読み、データとコードの食い違いを 11 件見つけています。大きい罠は、定数より 2 つ多い状態の値、2 つある削除の印、協定世界時で入っている時刻の 3 つです。地図の定義で数え直すと、トップの画面の 2026-09 の注文 223 件と売上 535,403 円に一致しました。開発の形と「売上」の定義は未確認なので、依頼者に 1 問ずつ伺います。ほかのセッションは、入口の 1 枚と、依頼が触る節だけを読みます。

## 5. 未確認

この記録で確かめていないことは、次の 2 つです。

| 未確認 | 理由 |
|---|---|
| この地図で 10 問に答えたときの点数（C-3） | 点数を測るのは、別のセッションの試験。この完成例は C-3 の題材で作ったので、C-3 の試験では渡さない（samples/messy-shop/README.md の 6 節） |
| 移した先の実物で、同じ時間で回るか | 実物のプロジェクトでは回していない |
