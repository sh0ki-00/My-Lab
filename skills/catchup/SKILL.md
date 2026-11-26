---
name: catchup
description: 移した先のプロジェクトの構成・データ・語彙・罠を、依頼者が「キャッチアップして」「キャッチアップを更新して」と頼んだ専用のセッションでだけ掴み、根拠つきの地図（tmp/catchup/ の入口の 1 枚と 6 つの節）に残す。言語と版・ディレクトリ・commit の作者の数・入口のルートは catchup-facts.sh が機械で拾い、DB は backend のデータの道具で実物から読み、コードは最後に読む。プロジェクトのコードとデータは書き換えない。地図は map-check.sh で検査し（入口は 80 行以内で全部の節への案内、表の全部の行に根拠、根拠のファイルが変わった節と、ファイルが増えたか消えた節は古い）、--stamp で鮮度を記録する。ふつうの依頼のセッションは入口と触る節を読むだけで、地図を書き換えず、気づいた食い違いを inbox.md に 1 行足す。Use only when the requester explicitly asks to catch up on a project or to update the catch-up map; never run it during ordinary implementation, investigation or fix sessions, which only read tmp/catchup/index.md. Triggers: キャッチアップ, キャッチアップして, キャッチアップを更新して, キャッチアップをやり直して, プロジェクトの地図.
---

# catchup — 専用のセッションでプロジェクトを掴み、ほかのセッションが読む地図を残す

## いつ使うか

依頼者が「キャッチアップして」「キャッチアップを更新して」と頼んだときだけ使う。移した直後の初回と、頼まれたときの更新の 2 つで、どちらも専用のセッションで回す。ふつうの依頼（実装、調査、修正）のセッションでは回さない。

| セッション | すること | 地図 |
|---|---|---|
| キャッチアップ（初回） | 事実と DB を全部のテーブルに機械で回し、構成と入口も拾う | 作る |
| キャッチアップ（更新） | 古い節と、追記の候補が触る節だけを読み直す | 直す |
| ふつうの依頼 | 入口の 1 枚と、依頼が触る節だけを読む | 読むだけ |
| 調査の依頼 | 上に加えて、触るテーブルの集計を回し直し、辞書との差を見る | 読むだけ |

地図が無いか古いときも、ふつうのセッションは勝手に始めず、最初の返答で 1 行伝えて依頼をそのまま進める。キャッチアップの依頼にほかの依頼が混ざっていたら、キャッチアップだけを回し、残りは別のセッションに分ける。

承認の門は、取りまとめ役の決まり（`skills/secretary/references/approval-rules.md`）のとおりに通す。依頼の文に承認の言葉（お願い、やって など）があれば、受付票 1 枚の軽い道で進める。「キャッチアップして」だけなら、1 行で「進めてよいか」を聞き返す。DB の読み取りの許可は、手順 1 で別に聞く。

## 先に読むもの

- `references/procedure.md`（初回と更新の手順、ふつうのセッションの 1 行、止めて聞く所、最後の返答の型）
- `references/map-rules.md`（置き場とファイル、6 つの節、入口の 1 枚、根拠、鮮度、追記の候補、検査の決まりの名前）
- `skills/backend/references/existing-data.md`（データの節。掴む順、問いの種類で裁く、罠の 10 の型、DB を読む線）
- `templates/`（入口の 1 枚と 5 つの節と追記の候補）。データの節は `skills/backend/templates/data-dictionary.md` を写す
- `examples/messy-shop/`（完成例の地図）と `examples/messy-shop-run.md`（回したコマンドと結果）。データの節の完成例は `skills/backend/examples/data-dictionary-messy-shop.md`
- C-3 の試験で messy-shop を地図にするセッションは、同じ題材の完成例（`examples/messy-shop/`、`examples/messy-shop-run.md`、`skills/backend/examples/data-dictionary-messy-shop.md`）を開かない。`references/procedure.md` の 8 節の例の列も同じ題材の結果なので、セッションに渡す写しで伏せる。試験の分け方は `samples/messy-shop/README.md` の 6 節にある
- `.company/rules/evidence-and-safety.md`（証拠と安全の決まり）

## 判断の観点

1. 事実に近い物から読んだか。機械で拾える事実は catchup-facts.sh、データは実物の DB、コードは最後に読む。
2. 表の全部の行に根拠があるか。推測で埋めた行は無いか。分からないことは「不明」「未確認」と書いたか。
3. 読むだけだったか。プロジェクトのコードとデータ、設定の値、本番の DB に触れていないか。
4. 入口の 1 枚だけで、ふつうのセッションが次に開く節を選べるか。80 行以内か。
5. 次のセッションが古さに気づけるか。stamp.json を記録し、入口の commit と合っているか。

## 手順

初回は次の 8 つで、`references/procedure.md` の 3 節の 12 の順をまとめたもの。道具は移した先では `tmp/skills/` の下にある。

1. 許可と読まない所を確かめる（順 1）。ローカルの DB の読み取りは、プロジェクトごとに 1 回、依頼者の許可を得る。終わりの印: 許可の日と相手か「無い」と、--exclude に渡す所が決まる。
2. 事実を拾う（順 2）。`scripts/catchup-facts.sh --root . --out tmp/catchup/facts.jsonl`。終わりの印: RESULT: PASS と F の番号の表。
3. DB を機械で読む（順 3〜6、掴む順 0〜3）。写し・集計・書き込む処理の道具を全部のテーブルに回す。終わりの印: 全部のテーブルが写しと集計にあり、テーブルごとに書き込む処理の候補か「不明」がある。
4. コードを読む（順 7）。ルートと定時の処理、書き込む処理の候補、画面の集計の文から読む。終わりの印: データの節の外の 5 つの節の表が埋まり、辞書では「コードの上の意味」の列が埋まる。
5. 基準の数字と食い違いを書く（順 8〜9、掴む順 4〜5）。画面の集計の文と地図の定義の文を data-query.sh で回す。終わりの印: 基準の数字が 1 つ以上一致するか、差の理由がある。
6. 地図を書く（順 10）。`templates/` を `tmp/catchup/` に写し、表の全部の行に根拠（ファイルと行、Q の番号、F の番号、聞き取りの日付）を書く。終わりの印: テンプレートの穴が 0。
7. 検査して記録する（順 11）。`scripts/map-check.sh` が通ったら `scripts/map-check.sh --stamp`。終わりの印: RESULT: PASS と STAMP の行。
8. 依頼者に返す（順 12。`references/procedure.md` の 8 節の型）。

更新は次の 5 つで、詳しくは `references/procedure.md` の 4 節にある。

1. `scripts/map-check.sh --fresh` で古い節を、inbox.md で未処理の候補を挙げる。
2. データの節があれば、schema-snapshot.sh の --expect-hash で DB の形を比べる。
3. `scripts/catchup-facts.sh` を同じ --out で回す（番号は前の続きになる）。
4. 古い節と、候補が触る節だけを読み直して直す。新しい節は書き換えない。
5. 候補の状態を反映済みか見送りに変え、入口の commit を今の HEAD にして、検査と --stamp を回す。git の無いプロジェクトでは、読み直したあとで、データの節に書く根拠のハッシュ値を --evidence-hash で出し直す。

## 出力と受け渡し

| 成果物 | 置き場 | 読む人 |
|---|---|---|
| 入口の 1 枚 | `tmp/catchup/index.md` | 全部のセッション（常時ルールの読む順の 4 つ目） |
| 5 つの節 | `tmp/catchup/` の stack.md、team.md、entrypoints.md、vocabulary.md、traps.md | 依頼が触るセッション |
| データの節 | `tmp/catchup/data.md` | 調査するセッションと、バックエンド |
| 事実とクエリの記録、スキーマの写し、stamp.json | `tmp/catchup/` | map-check.sh と data-dictionary-check.sh |
| 追記の候補 | `tmp/catchup/inbox.md` | ふつうのセッションが足し、更新のセッションが読む |
| 最後の返答 | チャット | 依頼者 |

開発の形（個人かチームか）と UI の部品は、画面の型を選ぶ役割に渡す。データの節と語彙の節は、調査の役割に渡す。地図の queries.jsonl に記録を足すのは、キャッチアップのセッションだけである。

git の無いプロジェクトでは、入口の commit を「無い」と書く。データの節の commit の欄には、「git なし」と作った時刻と根拠のハッシュ値を書く。値を出すのは `skills/backend/scripts/data-dictionary-check.sh --evidence-hash tmp/catchup/data.md --root .` である。根拠のファイルが変わると、検査はデータの節を [鮮度] で落とす。

## 禁止

- ふつうの依頼のセッションでキャッチアップを回す。頼まれていないのに地図を作るか、書き換える。
- プロジェクトのコードとデータと設定を書き換える。書き込みの文を DB に流す。AI が本番の DB につなぐ。本番の行を写す。
- .env などの秘密の値と、個人が分かる値を読んで地図に書く。commit の作者の名前とメールを書く。
- 根拠の無い行と、推測の数を書く。事実とクエリの記録と stamp.json を手で書く。
- 読み直していない節のために、--stamp を回すか、根拠のハッシュ値を出し直す。検査を緩めて通す。
- 調べる予定の問いを見てから地図を書く。C-3 の試験で、題材の完成例を読む。

## 提出前の確認

1. `scripts/map-check.sh` が PASS。入口は 80 行以内で、6 つの節と追記の候補への案内と、DB の読み取りの許可の欄がある。表の全部の行に根拠がある。
2. データの節が `skills/backend/scripts/data-dictionary-check.sh` を通る。map-check.sh からも呼ばれる。
3. stamp.json を --stamp で書き、SECTION の行が全部「新しい」。
4. 基準の数字が 1 つ以上一致するか、差の理由がデータの節の 4 節にある。
5. 地図の .md が `tools/check-file.sh` を通る（移した先では `tmp/tools/check-file.sh`）。
6. 最後の返答に、読んだ範囲と未確認と、ほかのセッションがすることを書いた。
