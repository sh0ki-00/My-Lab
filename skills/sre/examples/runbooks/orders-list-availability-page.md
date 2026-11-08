# Runbook: 注文一覧の可用性の呼び出し（OrdersListAvailabilityPage）

> **3 行でわかる要約**
> 1. 注文一覧の API が失敗を返し、可用性のエラーバジェットが速く減っているときに、当番が開く手順書です。
> 2. 原因は 4 つに分けて見分けます。ポートの取り合い、シードの壊れ（権限か中身）、壊れた版、止まったプロセスです。
> 3. 印で原因の節を選んで直します。どの印にも合わなければ、正本から写しを作り直して 2 番手へ知らせてください。

| 項目 | 内容 |
|---|---|
| 通知 | `OrdersListAvailabilityPage`（呼び出し。夜でも当番を起こす） |
| 条件 | 1 時間と 5 分の失敗率が 1.44% 超え、または 6 時間と 30 分の失敗率が 0.6% 超え |
| SLO 定義書 | `../slo-order-list.md` |
| 対象 | 見本の API の写し（samples/api を写したもの）。本番の命令は人が出し、AI は流さない |
| 数値 | 目標・閾値・時刻はすべて架空 |
| 訓練 | `../../scripts/runbook-drill.sh` が 4 つの原因（シードと壊れた版は 2 通りずつ）、表の外の 1 件、別の起動の 1 件を使い捨ての写しで起こし、この手順で直るかを確かめる |

## 用語

この節は、手順に出る略語と道具の名前をまとめます。2 回目からは説明を省きます。

| 用語 | 意味 |
|---|---|
| SLO | 利用者に約束する信頼性の目標。ここでは 30 日で 99.9% の要求が成功すること |
| SLI | 目標を測る数。ここでは有効な要求のうち 200 を返した割合 |
| エラーバジェット | 目標の外に出てよい失敗の量。30 日で要求の 0.1% |
| Runbook | 当番の手順書。通知 1 つに 1 本 |
| 外形の確かめ（probe） | 利用者と同じ道で一覧を呼ぶ確かめ。`sample-api.sh probe` |
| 写し | 正本の samples/api を tmp/flow/stage5/api に写した見本。障害はここにだけ起こす |
| 正本 | 写しの元の samples/api。照らす相手で、ここは直さない |
| 2 番手 | 当番の次に呼ぶ SRE。表の外の手を使ったら必ず知らせる |

## 準備

この節は、命令が使う変数を決めます。どの命令の前にも、次の 2 行を流してください。値を変えなければ、作業場の直下で写しを扱います。

```sh
: "${API_DIR:=tmp/flow/stage5/api}" "${RUN:=tmp/flow/stage5/run}" "${PORT:=8080}" "${SRC:=samples/api}" "${SRE:=skills/sre/scripts}" "${KEYS:=$RUN/keys.txt}"
export API_DIR RUN PORT SRC SRE KEYS
```

写しがまだ無いときは、`bash "$SRE/sample-api.sh" copy` と `bash "$SRE/sample-api.sh" start` で作って立てます。鍵は起動のたびに作る作り物で、`$KEYS` に権限 600 で置かれ、止めると消えます。

手で立てた API でも、道具はそのまま使えます。pid の記録が無ければ、道具が PORT で待ち受ける写しの server.py を見つけます。鍵が `$KEYS` に無ければ `$RUN/keys.*` を探し、見つけた置き場を status の KEYS の行に出します。

道具は、それ以外の置き場の鍵を読みません。出題役や別の人が道具の外の命令で立て、鍵を別の file に出した API でも、確かめは道具で行います。直す節の最後の `sample-api.sh start` は、道具の鍵で入れないと分かると、道具で立て直して鍵を `$KEYS` に作り直します（REKEY の行）。渡された起動の命令や、別の置き場の鍵を読む確かめの命令は使いません。

| 変数 | 既定の値 | 意味 |
|---|---|---|
| API_DIR | tmp/flow/stage5/api | 見本の API の写し |
| RUN | tmp/flow/stage5/run | 要約のログ・pid・退避した file の置き場 |
| PORT | 8080 | 写しが 127.0.0.1 で待ち受けるポート |
| SRC | samples/api | 正本。版と file を照らす相手で、ここは直さない |
| SRE | skills/sre/scripts | 当番の道具 |
| KEYS | $RUN/keys.txt | 作り物の鍵の file。無ければ道具が $RUN/keys.* を探す |

## 症状

この節は、利用者に何が見えているかを書きます。運営担当者の画面には「注文一覧を読み込めませんでした」か「もう一度ログインしてください」が出て、一覧が空になります。

| 見えるもの | 利用者への影響 |
|---|---|
| 一覧の要求が 500 か 503 を返す | 画面に誤りの文と、お問い合わせ番号が出る |
| 一覧の要求が 401 を返す | 正しくログインしても、ログインし直すよう促される |
| 応答が来ない、つながらない | 画面が読み込み中のまま、2 秒の打ち切りで誤りの文になる |

呼び出しは、1 時間で 2% か 6 時間で 5% の予算を使う速さで鳴ります。速い方は、そのまま続くと 50 時間で予算を使い切ります。

## 確かめる命令

この節の命令は読むだけで、何も変えません。上から順に流し、出力をそのまま記録に貼ります。

```sh
bash "$SRE/sample-api.sh" probe --count 5
bash "$SRE/sample-api.sh" status
bash "$SRE/sample-api.sh" tally --last 50
tail -n 5 "$RUN/api.log"
```

| 命令 | 分かること |
|---|---|
| `sample-api.sh probe` | 利用者と同じ道で、状態番号と時間。GOOD なら利用者には見えていない |
| `sample-api.sh status` | プロセスの状態、ポートの持ち主、写しと正本の差、シードの中身の照合（SEED）、鍵の置き場、ログの最後の誤り |
| `sample-api.sh tally` | 要約のログの、状態番号・コード・例外の名前・断りの理由の数 |
| `tail` | 起動に失敗したときの例外の 1 行 |

## 原因の見分け方

この節は、確かめる命令の出力に出る印から、直す節を選ぶ表です。印が 2 つ出たときは、上の行から順に直します。

| 原因 | 見えるもの | 印（確かめる命令の出力） | 直す節 |
|---|---|---|---|
| C1 ポートの取り合い | probe が 404 か 000。ログに `Address already in use` | `ours=no` | C1 |
| C2 シードの壊れ | API が無くログに `PermissionError`（権限）。または一覧と詳細の一部だけが 500 で、例外が ValueError（中身） | `SEED bad` | C2 |
| C3 壊れた版 | 500（例外 OperationalError、表が欠ける）か、全員の 401（鍵の表が空） | `orders_api.py differ` | C3 |
| C4 止まったプロセス | probe が 000。プロセスはあるのに応えない | `state=stopped` | C4 |

SEED の行は、写しの seed-orders.json を正本と中身で照らした結果です。権限だけでなく値の違いも、`SEED bad reason=content` と場所と値で出ます。どの印も出ないときは、表の外の原因です。「どれにも合わないとき」の節へ進みます。

## 直す命令

この節は、原因ごとの直し方です。選んだ節の命令だけを流し、ほかの節には手を出しません。

### C1 ポートの取り合い

ポートを、API でないプロセスが待ち受けています。持ち主を見て、server.py でなければ止め、API を立て直します。

```sh
pid=$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN | head -n 1)
ps -o pid=,command= -p "$pid"
ps -o command= -p "$pid" | grep -q 'server.py' || kill "$pid"
sleep 1
bash "$SRE/sample-api.sh" start
```

### C2 シードの壊れ

起動のときに読む seed-orders.json の権限が外れたか、中身が正本と違います。DB はメモリーの上にあり、起動のたびに seed から作り直します。そこで、壊れた seed を退避し、正本の seed に入れ替えてから立て直します。

```sh
mkdir -p "$RUN/broken"
mv "$API_DIR/seed-orders.json" "$RUN/broken/seed-orders.json.$(date +%H%M%S)"
bash "$SRE/sample-api.sh" stop
cp "$SRC/seed-orders.json" "$API_DIR/seed-orders.json"
chmod 644 "$API_DIR/seed-orders.json"
bash "$SRE/sample-api.sh" start
```

### C3 壊れた版

写しの版が正本と違い、表が欠けるか鍵の表が空です。壊れた版を記録のために取っておき、正本の版に戻して立て直します。

```sh
mkdir -p "$RUN/broken"
cp "$API_DIR/orders_api.py" "$API_DIR/server.py" "$RUN/broken/"
bash "$SRE/sample-api.sh" stop
cp "$SRC/orders_api.py" "$SRC/server.py" "$API_DIR/"
bash "$SRE/sample-api.sh" start
```

### C4 止まったプロセス

API のプロセスが一時停止しています（起動した端末で Ctrl-Z を押したときと同じ）。続きを動かせば、たまった要求から応えます。最後の start は、道具の鍵で入れる API ならそのままにし、入れなければ道具で立て直します。

```sh
ps -o pid=,stat=,command= -p "$(bash "$SRE/sample-api.sh" pid)"
kill -CONT "$(bash "$SRE/sample-api.sh" pid)"
bash "$SRE/sample-api.sh" start
```

## どれにも合わないとき

この節は、印が 1 つも出ないとき、または選んだ節のあとも直ったことの確かめが通らないときの手です。正本の 4 つの file と決めた設定（件数 29）から写しを作り直し、立て直します。触るのは写しと、写しの server.py だけです。

```sh
bash "$SRE/sample-api.sh" rebuild
bash "$SRE/sample-api.sh" status
```

rebuild は、正本と違う file を消さずに `$RUN/broken/<時刻>/` へ移します。直す前の status と tally もそこに残ります。`REFUSE` か `FAILED` で終わったら、それ以上は触らずに 2 番手を呼びます。`HINT` の行でポートを別のプロセスが持つと分かれば、C1 の節へ戻ります。

そのあと、直ったかどうかに関わらず、SRE の 2 番手へ知らせます。知らせる文は次の型で、REBUILT の行に出た退避先を添えます。

> OrdersListAvailabilityPage は Runbook の表の外でした。正本から写しを作り直し、直ったことの確かめは〈通った／通らない〉です。退避先は〈REBUILT の行のパス〉です。表に足す印の案は〈SEED や FILE の行〉です。

## 直ったことの確かめ

この節の命令が終了コード 0 で終われば、利用者の道は戻っています。probe が 20 回とも 200 で、遅さも閾値の内なら GOOD です。確かめは道具の probe と status だけで行い、出題役の命令や別の置き場の鍵は使いません。

```sh
bash "$SRE/sample-api.sh" probe --count 20 && bash "$SRE/sample-api.sh" status
```

| 確かめ | 合格 |
|---|---|
| probe | 20 回とも 200、50 ms 超えが 2 回以下、最後に GOOD |
| status | `state=running`、`ours=yes`、3 つの FILE が `same`、`SEED ok` |
| 通知 | 5 分の失敗率が閾値を下回り、呼び出しが自然に閉じる |

## 戻し方

この節は、直した操作が悪い方へ動いたときの戻し方です。戻すのは当番の操作だけで、障害の前の壊れた状態には戻しません。

| 原因 | 当番の操作 | 戻し方 |
|---|---|---|
| C1 | 別のプロセスを止めた | そのプロセスの持ち主に知らせ、別のポートで立て直してもらう |
| C2 | 正本の seed に入れ替えた | `$RUN/broken/` に残した seed が調べる材料。読める範囲を狭めたいときは `chmod 640` にし、status を見る |
| C3 | 正本の版に戻した | `$RUN/broken/` に残した版が、調べる材料。戻すのは版の作り手が直した版だけ |
| C4 | 続きを動かした。道具の外で立てた API なら、道具で立て直した | 戻す操作は無い。止めた人と端末を聞き、道具の start で立てる手に直す |
| 表の外 | 写しを正本から作り直した | `$RUN/broken/<時刻>/` が調べる材料。戻すのは、作り手が直した file だけ |

## 記録と受け渡し

この節は、直したあとの仕事です。止血のあとで、障害の記録を `../incident-20261106-order-list-500.md` の形で書き、処置に担当・期限・完了条件を付けます。

| 渡す先 | 何を |
|---|---|
| 秘書 | 影響の時間、使ったエラーバジェット、次の処置の 3 点 |
| バックエンド | C3 の壊れた版と C2 の壊れた seed の値、要約のログの該当の行 |
| インフラ | C1 と C2 の起き方（ポートの割り当てと file の権限の決め方） |
| SRE の 2 番手 | 表の外の手を使ったときの退避先と、表に足す印と訓練の注入の案 |
