# 侵入テストの報告: 写しの負例（試験用）

> **3 行でわかる要約**
> 1. `report-check --roe bad-copy-roe.md` の負例です。5 点はそろっています。
> 2. 再検証の宛先と、名を挙げた試験と、立てる写しを、RoE の範囲の写しとわざとずらしています。
> 3. 検査が 4 つの決まりで名指しで落とすことを確かめます。

## 要約

穴を 3 件見つけました。

## 範囲と RoE

RoE の範囲の表の宛先だけを試しました。

## 再現の準備

RoE は 18080 に `samples/api/` を書いていますが、別の写しを立てています。

```bash
python3 -I tmp/flow/lab/api/server.py --port 18080 > "$TMPDIR/keys.txt" &
```

## 発見

発見は 3 件です。

### F-1: 再検証の宛先が RoE に無い

#### 何ができてしまうか

別の店の人が、ほかの店の注文を読めます。証拠は応答の抜粋です。

#### 再現の手順

```bash
curl -s -H "Authorization: Bearer $KEY_OP" http://127.0.0.1:18080/v1/orders/700001
```

#### 直し方

店の id を全部の問い合わせに入れます。

#### 再検証

```bash
curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $KEY_OP" http://127.0.0.1:18082/v1/orders/700001
```

期待: `404`

#### 重さと採点の根拠

採点は `CVSS:4.0/AV:N/AC:L/AT:N/PR:L/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N` で、点数: 7.1、重さ: High です。

| 値 | 根拠 |
|---|---|
| AV・AC・AT | 網から、条件なしに届く |
| PR・UI | 鍵は要る。相手の操作は要らない |
| VC・VI・VA | 他の店の注文が読める。書けない |
| SC・SI・SA | 他の仕組みには及ばない |

### F-2: 再検証が別の写しに向く

#### 何ができてしまうか

閲覧者が、取り消しを出せます。証拠は状態番号 200 です。

#### 再現の手順

```bash
curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $KEY_VIEWER" -H "Idempotency-Key: fx-0001" -d '{"orderIds":["583429"]}' http://127.0.0.1:18080/v1/orders/cancel
```

#### 直し方

書き込みの入口で役割を確かめます。

#### 再検証

```bash
curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $KEY_VIEWER" -H "Idempotency-Key: fx-0002" -d '{"orderIds":["583429"]}' http://127.0.0.1:18081/v1/orders/cancel
python3 -I tmp/flow/lab/api/test_orders_api.py OrdersApiTest.test_auth_and_roles
```

期待: `403`

#### 重さと採点の根拠

採点は `CVSS:4.0/AV:N/AC:L/AT:N/PR:L/UI:N/VC:N/VI:L/VA:N/SC:N/SI:N/SA:N` で、点数: 5.3、重さ: Medium です。

| 値 | 根拠 |
|---|---|
| AV・AC・AT | 網から、条件なしに届く |
| PR・UI | 閲覧者の鍵が要る。相手の操作は要らない |
| VC・VI・VA | 自分の店の注文の状態だけを変えられる |
| SC・SI・SA | 他の仕組みには及ばない |

### F-3: 名を挙げた試験が写しに無い

#### 何ができてしまうか

検索語がログに残ります。証拠はログの 1 行です。

#### 再現の手順

```bash
curl -s -o /dev/null -H "Authorization: Bearer $KEY_OP" "http://127.0.0.1:18080/v1/orders?q=marker"
```

#### 直し方

要約のログから絞り込みの値を外します。

#### 再検証

```bash
curl -s -o /dev/null -H "Authorization: Bearer $KEY_OP" "http://127.0.0.1:18080/v1/orders?q=marker"
python3 -I samples/api/test_orders_api.py OrdersApiTest.test_only_in_another_copy
```

期待: `RESULT: PASS`

#### 重さと採点の根拠

採点は `CVSS:4.0/AV:N/AC:L/AT:N/PR:L/UI:N/VC:L/VI:N/VA:N/SC:N/SI:N/SA:N` で、点数: 5.3、重さ: Medium です。

| 値 | 根拠 |
|---|---|
| AV・AC・AT | 網から、条件なしに届く |
| PR・UI | 鍵は要る。相手の操作は要らない |
| VC・VI・VA | ログを読める人に検索語が見える |
| SC・SI・SA | 他の仕組みには及ばない |
