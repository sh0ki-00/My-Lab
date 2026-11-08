#!/usr/bin/env python3
"""test_orders_api — 見本の注文 API の試験。契約のとおりに動くか、認可・冪等・エラー・ログを確かめる。

使い方: python3 -I samples/api/test_orders_api.py   （skills/backend/evals/run.sh が呼ぶ）
応答の本文は、契約 skills/backend/examples/openapi-order-list.json の schema で確かめる（type・required・enum・items・$ref だけを見る小さな検証）。
"""
import base64
import http.client
import io
import json
import os
import select
import shutil
import socket
import sqlite3
import secrets
import subprocess
import threading
import time
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import orders_api  # noqa: E402

CONTRACT = json.loads((HERE.parent.parent / "skills" / "backend" / "examples" / "openapi-order-list.json").read_text(encoding="utf-8"))
OP = VIEWER = OTHER = None  # 鍵は API を作るたびの乱数なので、setUp で引く
TYPES = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "number": (int, float), "null": type(None)}


def resolve(s):
    while "$ref" in s:
        node = CONTRACT
        for part in s["$ref"][2:].split("/"):
            node = node[part]
        s = node
    return s


def validate(v, s, path="$"):
    s = resolve(s)
    errs = []
    ts = s.get("type")
    ts = ts if isinstance(ts, list) else [ts] if ts else []
    if ts and not any(isinstance(v, TYPES[t]) and not (t == "integer" and isinstance(v, bool)) for t in ts):
        return [f"{path}: 型 {type(v).__name__} が {ts} でない"]
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{path}: {v!r} が列挙値に無い")
    if isinstance(v, dict):
        for k in s.get("required", []):
            if k not in v:
                errs.append(f"{path}: 必須の {k} が無い")
        for k, sub in (s.get("properties") or {}).items():
            if k in v:
                errs += validate(v[k], sub, f"{path}.{k}")
    if isinstance(v, list) and "items" in s:
        for i, x in enumerate(v):
            errs += validate(x, s["items"], f"{path}[{i}]")
    return errs


def schema_of(path, method, status):
    resp = CONTRACT["paths"][path][method]["responses"][str(status)]
    return resp["content"]["application/json"]["schema"]


# ---- 旧 API と新 API が同じ注文に書くときの 4 つの決まり（計画の「版と段の表」と「書き手」。第 9 回の決め 5）
# 旧 API の文は移行の前のまま変えない。決済の通知は is_cancelled を条件に持たない（第 8 回の重大 1 の前提。段 0 の調べで確かめる）
LEGACY_SQL = {
    "old_cancel": "UPDATE orders SET is_cancelled = 1 WHERE id = ? AND is_cancelled = 0",
    "old_uncancel": "UPDATE orders SET is_cancelled = 0 WHERE id = ? AND is_cancelled = 1",
    "old_ship": "UPDATE orders SET status = 'shipped', shipped_by = 'u-sakaguchi', shipped_at = '2026-11-06T01:00:00.000000Z'"
                " WHERE id = ? AND status = 'ready' AND is_cancelled = 0",
    "old_pay": "UPDATE orders SET status = 'ready' WHERE id = ? AND status = 'pending'",
    "old_deliver": "UPDATE orders SET status = 'delivered' WHERE id = ? AND status = 'shipped'",
    "old_intake": "INSERT INTO orders (id, shop_id, customer_id, status, amount_yen, carrier, payment, ordered_at, ship_due)"
                  " VALUES (?, 's1', 1, 'pending', 1200, 'yamato', 'card', '2026-11-06T00:00:00.000000Z', '2026-11-06')",
}
# 移行の前の DB で、新 API の 2 つの書き込みと同じ意味の文（比べの正）
MODEL_NEW_SQL = {
    "new_cancel": "UPDATE orders SET is_cancelled = 1 WHERE id = ? AND status IN ('action','ready','pending') AND is_cancelled = 0",
    "new_ship": "UPDATE orders SET status = 'shipped' WHERE id = ? AND status = 'ready' AND is_cancelled = 0",
}
LEGACY_COLS = ("id", "shop_id", "customer_id", "status", "alert", "amount_yen", "carrier", "payment", "staff_id", "ordered_at", "ship_due",
               "shipped_by", "shipped_at", "note", "parcel", "fragile", "is_cancelled")


def legacy_db(additions=()):
    """移行の前の表（LEGACY_SCHEMA）に、足し算の段を additions まで流した DB。行は 5 つ"""
    c = sqlite3.connect(":memory:", isolation_level=None)
    c.create_function("now_utc", 0, lambda: "2026-11-06T01:00:00.000000Z")
    c.create_function("current_setting", -1, lambda *a: None)  # 旧 API は鍵のハッシュを置かない（取り消しの人は null）
    c.create_function("xact_id", 0, lambda: 1)  # 取引の番号の写し（本番は pg_current_xact_id()）
    c.executescript(orders_api.LEGACY_SCHEMA)
    c.execute("INSERT INTO shops VALUES ('s1', '見本の店')")
    c.execute("INSERT INTO users VALUES ('u-sakaguchi', 's1', '坂口', 'operator')")
    c.execute("INSERT INTO customers VALUES (1, 's1', '架空 顧客', NULL, NULL)")
    for oid, st in (("100001", "pending"), ("100002", "ready"), ("100003", "shipped"), ("100004", "pending"), ("100005", "action")):
        c.execute("INSERT INTO orders (id, shop_id, customer_id, status, amount_yen, carrier, payment, ordered_at, ship_due)"
                  " VALUES (?, 's1', 1, ?, 1000, 'yamato', 'card', '2026-11-05T00:00:00.000000Z', '2026-11-06')", (oid, st))
    for step in additions:
        for sql in step["sqlite"]:
            c.execute(sql)
    return c


def legacy_run(additions):
    """旧 API の書き手を一通り流し、書けた行の数、旧い列の値、旧い列の定義を返す"""
    c = legacy_db(additions)
    ops = {}
    for label, name, oid in (("old_cancel_pending", "old_cancel", "100001"), ("old_pay_cancelled", "old_pay", "100001"),
                             ("old_uncancel", "old_uncancel", "100001"), ("old_ship_after_uncancel", "old_ship", "100001"),
                             ("old_cancel_ready", "old_cancel", "100002"), ("old_ship_cancelled", "old_ship", "100002"),
                             ("old_cancel_after_ship", "old_cancel", "100003"), ("old_deliver_cancelled", "old_deliver", "100003"),
                             ("old_intake", "old_intake", "100006"), ("old_pay_new", "old_pay", "100006"),
                             ("old_pay", "old_pay", "100004"), ("old_cancel_action", "old_cancel", "100005")):
        ops[label] = c.execute(LEGACY_SQL[name], (oid,)).rowcount
    rows = [tuple(r) for r in c.execute(f"SELECT {', '.join(LEGACY_COLS)} FROM orders ORDER BY id")]
    cols = [tuple(r) for r in c.execute("PRAGMA table_info(orders)") if r[1] in LEGACY_COLS]
    return {"ops": ops, "rows": rows, "cols": cols}


# ---- 本番の形の SQL を、手元の PostgreSQL（使い捨ての容器）で流す（第 10 回からの決め）。容器が無ければ、その試験だけを飛ばす
PG_CONTAINER = os.environ.get("MYLAB_PG_CONTAINER", "mylab-pg-stage4")
PG_SEED = ("INSERT INTO shops VALUES ('s1', '見本の店');\nINSERT INTO users VALUES ('u-sakaguchi', 's1', '坂口', 'operator');\n"
           "INSERT INTO customers VALUES (1, 's1', '架空 顧客', NULL, NULL);\n"
           + "".join("INSERT INTO orders (id, shop_id, customer_id, status, amount_yen, carrier, payment, ordered_at, ship_due)"
                     f" VALUES ('{oid}', 's1', 1, '{st}', 1000, 'yamato', 'card', '2026-11-05T00:00:00.000000Z', '2026-11-06');\n"
                     for oid, st in (("100001", "pending"), ("100002", "ready"), ("100003", "shipped"), ("100004", "pending"),
                                     ("100005", "action"))))
LEGACY_OPS = (("old_cancel_pending", "old_cancel", "100001"), ("old_pay_cancelled", "old_pay", "100001"),
              ("old_uncancel", "old_uncancel", "100001"), ("old_ship_after_uncancel", "old_ship", "100001"),
              ("old_cancel_ready", "old_cancel", "100002"), ("old_ship_cancelled", "old_ship", "100002"),
              ("old_cancel_after_ship", "old_cancel", "100003"), ("old_deliver_cancelled", "old_deliver", "100003"),
              ("old_intake", "old_intake", "100006"), ("old_pay_new", "old_pay", "100006"),
              ("old_pay", "old_pay", "100004"), ("old_cancel_action", "old_cancel", "100005"))
ADDED_COLS = "ARRAY['cancelled_at', 'cancelled_by', 'changed_at', 'stamped_xid']"


def pg_ready():
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "exec", PG_CONTAINER, "pg_isready", "-U", "postgres"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def pg(sql, db="postgres", check=True):
    """psql に SQL を流し、(終了コード, 'R:' で始まる行の辞書, 標準エラー) を返す。R: の行は「R:名前=値」"""
    r = subprocess.run(["docker", "exec", "-i", PG_CONTAINER, "psql", "-X", "-q", "-A", "-t", "-U", "postgres", "-d", db,
                        "-v", "ON_ERROR_STOP=1"], input=sql, capture_output=True, text=True, timeout=300)
    if check and r.returncode:
        raise AssertionError(f"psql が止まった: {r.stderr[-600:]}")
    out = dict(line[2:].split("=", 1) for line in r.stdout.splitlines() if line.startswith("R:"))
    return r.returncode, out, r.stderr


def pg_db(name):
    pg(f"DROP DATABASE IF EXISTS {name} WITH (FORCE);\nCREATE DATABASE {name};")
    return name


def pg_legacy(variant, legacy_sql=None, seed=True):
    """移行の前の表を、列の型を変えた形で作る文と、旧 API の文。variant は text（見本の LEGACY_SCHEMA のまま。時刻を文字で持つ）、
    tstz（時刻を timestamptz で持つ）、odd（tstz に、等しさの演算子の無い json と point の列を足す）、bool（取り消しの印が boolean）"""
    s, sql = orders_api.LEGACY_SCHEMA, dict(legacy_sql or LEGACY_SQL)
    if variant in ("tstz", "odd"):
        s = s.replace("ordered_at TEXT NOT NULL", "ordered_at timestamptz NOT NULL").replace("shipped_at TEXT", "shipped_at timestamptz")
    if variant == "bool":
        s = s.replace("is_cancelled INTEGER NOT NULL DEFAULT 0 CHECK (is_cancelled IN (0, 1))", "is_cancelled boolean NOT NULL DEFAULT false")
        sql = {k: v.replace("is_cancelled = 1", "is_cancelled = true").replace("is_cancelled = 0", "is_cancelled = false") for k, v in sql.items()}
    rows = PG_SEED if seed else ""
    if variant == "odd":
        s += "ALTER TABLE orders ADD COLUMN extra json, ADD COLUMN spot point;\n"
        rows += "UPDATE orders SET extra = '{\"a\": 1}', spot = '(1,2)';\n" if seed else ""
    return s + rows, sql


def pg_additions():
    return "".join(s + ";\n" for step in orders_api.ADDITIONS for s in step["pg"])


def pg_legacy_run(db, sql):
    """旧 API の書き手 12 手を流し、書けた行の数と、旧い列の値と定義を返す"""
    ops = "".join(f"WITH x AS ({sql[name].replace('?', repr(oid))} RETURNING 1) SELECT 'R:{label}=' || count(*) FROM x;\n"
                  for label, name, oid in LEGACY_OPS)
    rows = (f"SELECT 'R:rows=' || jsonb_agg(to_jsonb(o) - {ADDED_COLS} ORDER BY o.id)::text FROM orders o;\n"
            "SELECT 'R:cols=' || string_agg(column_name || ' ' || data_type || ' ' || coalesce(column_default, '') || ' ' || is_nullable, ', '"
            f" ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name = 'orders' AND column_name <> ALL ({ADDED_COLS});\n")
    return pg(ops + rows, db)[1]


def four_rules(cls):
    """旧 API と新 API の書き込みを、同じ注文に 2 つずつ全部の順で流し（始めの状態 6 つ × 7 つの書き込みの順列）、続けて乱数の 300 手を流す。
    1 手ごとに、(a)〜(d) と、移行の前の DB と同じ結果かを確かめ、破れた手を返す。1 文の書き込みは行の鍵の中で条件を読み直すので、
    同時の書き込みは文の境の順のどれかになる（本番の READ COMMITTED）。ここでは文の境の順を全部流す"""
    import random
    api = cls(29, io.StringIO())
    hdr = {"Authorization": "Bearer " + api.token_for("u-takagi")}
    model = legacy_db()
    oid, n = "584205", [0]
    model.execute("INSERT INTO orders (id, shop_id, customer_id, status, amount_yen, carrier, payment, ordered_at, ship_due)"
                  " VALUES (?, 's1', 1, 'ready', 1000, 'yamato', 'card', '2026-11-05T00:00:00.000000Z', '2026-11-06')", (oid,))
    names = ["old_cancel", "old_uncancel", "old_ship", "old_pay", "old_deliver", "new_cancel", "new_ship"]
    bad = []

    def truth(c):
        return tuple(c.execute("SELECT status, is_cancelled FROM orders WHERE id = ?", (oid,)).fetchone())

    def read():
        st, _, out = api.handle("GET", f"/v1/orders/{oid}", hdr)
        return json.loads(out)["status"] if st == 200 else f"http {st}"

    def step(name, where):
        before, model_before = truth(api.conn), truth(model)
        if name.startswith("old_"):
            with api.lock:
                ok = api.conn.execute(LEGACY_SQL[name], (oid,)).rowcount == 1
        else:
            n[0] += 1
            st, _, out = api.handle("POST", f"/v1/orders/{name[4:]}", dict(hdr, **{"Idempotency-Key": f"rules-key-{n[0]:06d}"}),
                                    json.dumps({"orderIds": [oid]}).encode())
            ok = st == 200 and json.loads(out)["results"][0]["outcome"] in ("shipped", "cancelled")
        model.execute((LEGACY_SQL | MODEL_NEW_SQL)[name], (oid,))
        after, want, seen = truth(api.conn), truth(model), read()
        tag = f"{where} {name}: {before} → {after}"
        if after != want:
            bad.append(f"{tag}（移行の前なら {want}）")
        if before[1] and after[0] in ("shipped", "delivered") and before[0] not in ("shipped", "delivered"):
            bad.append(f"(a) 取り消した注文が出荷された {tag}")
        live = after[0] in ("action", "ready", "pending")
        if (before[1] and not after[1] and name != "old_uncancel") or (name in ("old_cancel", "new_cancel") and ok and not after[1]) \
                or (after[1] and live and seen != "cancelled"):
            bad.append(f"(b) 取り消しが黙って外れた {tag}（新 API の読み {seen}）")
        if (name == "old_uncancel" and ok and (after[1] or seen == "cancelled")) or (not before[1] and after[1] and "cancel" not in name) \
                or (not after[1] and seen != after[0]):
            bad.append(f"(c) 戻した取り消しが残った {tag}（新 API の読み {seen}）")
        if after[1] and not live and seen != after[0]:  # 出荷のあとに印が立った行を取消と読むと、済の群から消え、荷物を誰も止められない
            bad.append(f"(e) 出荷した注文が取消と読まれて済から消えた {tag}（新 API の読み {seen}）")
        if name == "old_pay" and model_before[0] == "pending" and (after[0] != "ready" or not ok):  # 移行の前なら移る決済が移らない
            bad.append(f"(d) 決済の移りが止まった {tag}")

    def reset(st, mark):
        for c, lock in ((api.conn, api.lock), (model, threading.Lock())):
            with lock:
                c.execute("UPDATE orders SET status = ?, is_cancelled = ?, shipped_by = NULL, shipped_at = NULL WHERE id = ?", (st, mark, oid))
    for st, mark in (("pending", 0), ("ready", 0), ("action", 0), ("shipped", 0), ("pending", 1), ("ready", 1)):
        for first in names:
            for second in names:
                reset(st, mark)
                step(first, f"[{st},{mark}]")
                step(second, f"[{st},{mark}] {first} の次")
    reset("pending", 0)
    rng = random.Random(20261107)
    starts = [("pending", 0), ("ready", 0), ("action", 0), ("pending", 1), ("ready", 1)]
    for i in range(300):
        if i % 12 == 0:  # 出荷済みと配達済みで止まらないよう、ときどき始めの状態に戻す
            reset(*rng.choice(starts))
        step(rng.choice(names + ["old_pay", "old_uncancel"]), f"乱数の {i} 手目")
    return bad


class OrdersApiTest(unittest.TestCase):
    def setUp(self, n=29):
        global OP, VIEWER, OTHER
        self.log = io.StringIO()
        self.api = orders_api.make_api(n, log=self.log)
        OP = self.auth("u-takagi")  # 運営担当者の高木
        VIEWER = self.auth("u-kobayashi")  # 閲覧者
        OTHER = self.auth("u-other")  # 別の店の運営担当者

    def auth(self, uid):
        return {"Authorization": "Bearer " + self.api.token_for(uid)}

    def call(self, method, path, headers=None, body=None, route=None):
        raw = json.dumps(body).encode() if body is not None else b""
        st, hdr, out = self.api.handle(method, path, headers or {}, raw)
        data = json.loads(out)
        errs = validate(data, schema_of(route or path.split("?")[0], method.lower(), st))
        self.assertEqual(errs, [], f"{method} {path} の {st} が契約と違う")
        return st, hdr, data

    def ship(self, ids, key, headers=None, op="ship"):
        return self.call("POST", f"/v1/orders/{op}", dict(headers or OP, **{"Idempotency-Key": key}), {"orderIds": ids})

    def test_list_has_counts_me_and_server_time(self):
        st, _, d = self.call("GET", "/v1/orders?limit=100", OP, route="/v1/orders")
        self.assertEqual(st, 200)
        self.assertEqual((d["total"], len(d["items"])), (29, 29))  # 見本の画面の未出荷 18 行と、今日の済の 11 行
        self.assertEqual(d["counts"], {"action": 3, "late": 2, "ready": 10, "pending": 3, "shippedToday": 11})
        self.assertEqual([i["group"] for i in d["items"][:6]], ["action"] * 3 + ["late"] * 2 + ["ready"])
        self.assertEqual(d["me"]["role"], "operator")
        self.assertIsNone(d["nextCursor"])

    def test_today_view_keeps_shipped_rows_below(self):
        """画面仕様の今日出荷: 出荷指示した行は、未出荷の 4 群の下に済の群として残る。一覧の要求は 1 回"""
        st, _, d = self.call("GET", "/v1/orders?limit=100", OP, route="/v1/orders")
        groups = [i["group"] for i in d["items"]]
        self.assertEqual(groups[18:], ["shipped"] * 11)
        self.assertNotIn("shipped", groups[:18])
        at = [i["shippedAt"] for i in d["items"][18:]]
        self.assertEqual(at, sorted(at, reverse=True))  # 済の群は出荷指示の新しい順
        self.ship(["584216"], "today-key-0001")
        _, _, d = self.call("GET", "/v1/orders?limit=100", OP, route="/v1/orders")
        self.assertEqual(d["items"][17]["orderId"], "584216")  # いま出荷指示した行が済の群の頭に来る（未出荷は 17 行に減る）
        self.assertEqual(d["viewCounts"]["today"], 17)  # タブの件数は未出荷だけ
        seen, after = [], ""
        for _ in range(10):
            _, _, p = self.call("GET", "/v1/orders?limit=7" + (f"&after={after}" if after else ""), OP, route="/v1/orders")
            seen += [i["orderId"] for i in p["items"]]
            after = p["nextCursor"]
            if not after:
                break
        self.assertEqual(seen, [i["orderId"] for i in d["items"]])  # 群の境と済の群をまたいでも、起点の送りで行を飛ばさない

    def test_cursor_never_skips_rows(self):
        seen, after = [], ""
        for _ in range(10):
            st, _, d = self.call("GET", "/v1/orders?limit=5" + (f"&after={after}" if after else ""), OP, route="/v1/orders")
            seen += [i["orderId"] for i in d["items"]]
            after = d["nextCursor"]
            if not after:
                break
        _, _, full = self.call("GET", "/v1/orders?limit=100", OP, route="/v1/orders")
        self.assertEqual(seen, [i["orderId"] for i in full["items"]])

    def test_sort_desc_and_empty_suggestions(self):
        _, _, d = self.call("GET", "/v1/orders?sort=-orderedAt&limit=3", OP, route="/v1/orders")
        times = [i["orderedAt"] for i in d["items"]]
        self.assertEqual(times, sorted(times, reverse=True))
        _, _, d = self.call("GET", "/v1/orders?carrier=seino&staff=none", OP, route="/v1/orders")
        self.assertEqual(d["total"], 0)
        self.assertEqual({s["withoutFilter"] for s in d["suggestions"]}, {"carrier", "staff"})

    def test_detail_and_other_shop_is_404(self):
        st, _, d = self.call("GET", "/v1/orders/584205", OP, route="/v1/orders/{orderId}")
        self.assertEqual((st, [p["orderId"] for p in d["pastOrders"]], d["parcel"]), (200, ["554968", "513662"], {"size": "100", "fragile": True}))
        st, _, d = self.call("GET", "/v1/orders/700001", OP, route="/v1/orders/{orderId}")
        self.assertEqual((st, d["error"]["code"]), (404, "ORDER_NOT_FOUND"))
        st, _, d = self.call("GET", "/v1/orders/584205", OTHER, route="/v1/orders/{orderId}")
        self.assertEqual((st, d["error"]["code"]), (404, "ORDER_NOT_FOUND"))

    def test_auth_and_roles(self):
        st, _, d = self.call("GET", "/v1/orders", {})
        self.assertEqual((st, d["error"]["code"]), (401, "AUTH_REQUIRED"))
        st, _, d = self.call("GET", "/v1/orders", VIEWER)
        self.assertEqual((st, d["me"]["keys"]), (200, {}))
        st, _, d = self.ship(["584205"], "viewer-key-0001", VIEWER)
        self.assertEqual((st, d["error"]["code"]), (403, "FORBIDDEN_ROLE"))
        st, _, d = self.ship(["584205"], "viewer-key-0002", VIEWER, op="cancel")
        self.assertEqual(st, 403)

    def test_ship_idempotent_and_row_results(self):
        st, _, d = self.ship(["584205", "583961", "582473"], "ship-key-0001")
        self.assertEqual(st, 200)
        self.assertEqual([r["outcome"] for r in d["results"]], ["shipped", "already_shipped", "not_shippable"])
        self.assertEqual(d["results"][1]["code"], "ORDER_ALREADY_SHIPPED")
        self.assertEqual(d["results"][1]["shippedBy"]["name"], "坂口")
        self.assertEqual(d["results"][2]["code"], "ORDER_SHIP_PARTIAL")
        st2, hdr, d2 = self.ship(["584205", "583961", "582473"], "ship-key-0001")
        self.assertEqual((st2, d2, hdr.get("Idempotent-Replayed")), (st, d, "true"))
        st, _, d = self.ship(["584216"], "ship-key-0001")
        self.assertEqual((st, d["error"]["code"]), (422, "IDEMPOTENCY_KEY_MISMATCH"))
        st, _, d = self.call("POST", "/v1/orders/ship", OP, {"orderIds": ["584216"]})
        self.assertEqual((st, d["error"]["code"]), (400, "IDEMPOTENCY_KEY_REQUIRED"))
        st, _, d = self.ship(["584205"], "ship-key-0002")
        self.assertEqual((st, d["error"]["code"]), (409, "ORDER_ALREADY_SHIPPED"))
        _, _, lst = self.call("GET", "/v1/orders", OP)
        self.assertEqual(lst["counts"]["shippedToday"], 12)

    def test_idempotency_keys_expire_after_24_hours(self):
        """保持の期間を過ぎたキーは再生に使わず、同じキーで送ると取り直す。消すのは掃除の仕事（purge_expired）で、書き込みの取引では消さない"""
        self.ship(["584216"], "old-key-0001")
        self.api.conn.execute("UPDATE idempotency SET created_at = '2026-11-05T00:00:00.000000Z'")
        self.ship(["584230"], "new-key-0001")
        keys = sorted(r["key"] for r in self.api.conn.execute("SELECT key FROM idempotency"))
        self.assertEqual(keys, ["new-key-0001", "old-key-0001"])
        st, hdr, d = self.ship(["584205"], "old-key-0001")  # 期限の切れた同じキー。前の応答を返さず、新しい要求として書く
        self.assertEqual((st, hdr.get("Idempotent-Replayed"), d["results"][0]["orderId"]), (200, None, "584205"))
        self.api.conn.execute("UPDATE idempotency SET created_at = '2026-11-05T00:00:00.000000Z' WHERE key = 'new-key-0001'")
        self.api.purge_expired()
        self.assertEqual([r["key"] for r in self.api.conn.execute("SELECT key FROM idempotency")], ["old-key-0001"])

    def test_since_returns_changed_rows(self):
        _, _, d = self.call("GET", "/v1/orders", OP)
        served = d["servedAt"]
        self.ship(["584216"], "ship-key-0003")
        _, _, ch = self.call("GET", f"/v1/orders?since={served}", OP, route="/v1/orders")
        self.assertIn("584216", [i["orderId"] for i in ch["items"]])  # 重ね幅（10 秒）の分、直前に済になった行も返る
        self.assertTrue(all(i["shippedAt"] or i["cancelledAt"] for i in ch["items"]))

    def test_cancel_not_allowed_for_shipped(self):
        st, _, d = self.ship(["584216", "583961"], "cancel-key-0001", op="cancel")
        self.assertEqual(st, 200)
        self.assertEqual([r["outcome"] for r in d["results"]], ["cancelled", "not_allowed"])
        self.assertEqual(d["results"][1]["code"], "ORDER_CANCEL_NOT_ALLOWED")
        st, _, d = self.ship(["583961"], "cancel-key-0002", op="cancel")
        self.assertEqual((st, d["error"]["code"]), (409, "ORDER_CANCEL_NOT_ALLOWED"))

    def test_deadline_returns_upstream_slow(self):
        self.api.deadline_s = 0
        st, _, d = self.call("GET", "/v1/orders", OP)
        self.assertEqual((st, d["error"]["code"]), (503, "ORDER_LIST_UPSTREAM_SLOW"))
        st, _, d = self.call("GET", "/v1/orders/584205", OP, route="/v1/orders/{orderId}")
        self.assertEqual((st, d["error"]["code"]), (503, "ORDER_DETAIL_UPSTREAM_SLOW"))

    def test_errors_carry_four_points(self):
        st, hdr, d = self.call("GET", "/v1/orders?limit=500", OP, route="/v1/orders")
        self.assertEqual(st, 400)
        self.assertEqual(set(d["error"]) >= {"category", "cause", "action", "traceId"}, True)
        self.assertEqual(d["error"]["traceId"], hdr["X-Trace-Id"])

    def test_one_line_log_without_personal_data(self):
        self.call("GET", "/v1/orders?q=松本", OP, route="/v1/orders")
        self.call("GET", "/v1/orders/584205", OP, route="/v1/orders/{orderId}")
        self.ship(["584205"], "log-key-0001")
        lines = self.log.getvalue().splitlines()
        self.assertEqual(len(lines), 3)
        for line in lines:
            rec = json.loads(line)
            self.assertEqual(set(rec) >= {"traceId", "route", "status", "durMs", "sql", "user"}, True)
        text = self.log.getvalue()
        for secret in ("松本", "大分市", "870-0021", "sample-token", "log-key-0001", "q="):
            self.assertNotIn(secret, text)


    # ---- 敵対的レビューの指摘（2026-11-07）を結んだ試験
    def test_cancel_with_no_written_rows_is_409(self):
        st, _, d = self.ship(["700001"], "cancel-nf-0001", op="cancel")  # 他の店の注文
        self.assertEqual((st, d["error"]["code"], d["results"][0]["outcome"]), (409, "ORDER_NOT_FOUND", "not_found"))
        st, _, d = self.ship(["700001", "583961"], "cancel-nf-0002", op="cancel")
        self.assertEqual((st, d["error"]["code"]), (409, "ORDER_CANCEL_NOT_ALLOWED"))

    def test_since_pages_all_changed_rows(self):
        self.setUp(400)
        _, _, d = self.call("GET", "/v1/orders?limit=100", OP, route="/v1/orders")
        t0 = d["servedAt"]
        ready = [r[0] for r in self.api.conn.execute("SELECT id FROM orders WHERE shop_id = 's1' AND status = 'ready' ORDER BY id LIMIT 60")]
        self.assertEqual(len(ready), 60)
        self.assertEqual(self.ship(ready, "since-key-0001", self.auth("u-mori"))[0], 200)
        seen, after, totals = [], "", set()
        for _ in range(10):
            _, _, ch = self.call("GET", f"/v1/orders?since={t0}" + (f"&after={after}" if after else ""), OP, route="/v1/orders")
            seen += [i["orderId"] for i in ch["items"]]
            totals.add(ch["total"])
            after = ch["nextCursor"]
            if not after:
                break
        self.assertTrue(set(ready) <= set(seen))  # 60 件がすべて届く（重ね幅の分、直前の済の行も混じる）
        self.assertEqual((len(seen), totals), (len(set(seen)), {len(seen)}))

    def test_tokens_cannot_be_made_from_user_ids(self):
        for uid in ("u-takagi", "u-other"):
            st, _, d = self.call("GET", "/v1/orders", {"Authorization": f"Bearer sample-token-{uid}"})
            self.assertEqual((st, d["error"]["code"]), (401, "AUTH_REQUIRED"))
        self.api.conn.execute("UPDATE sessions SET expires_at = '2026-11-05T00:00:00.000000Z' WHERE user_id = 'u-takagi'")
        self.assertEqual(self.call("GET", "/v1/orders", OP)[0], 401)  # 期限を過ぎた鍵

    def test_each_device_keeps_its_own_token(self):
        """ログインのたびに鍵を作っても、別の端末の鍵は失効しない。失効は端末の 1 行を消す"""
        a, b = self.api.login("u-takagi"), self.api.login("u-takagi")
        for t in (a, b):
            self.assertEqual(self.call("GET", "/v1/orders", {"Authorization": "Bearer " + t})[0], 200)
        self.api.conn.execute("DELETE FROM sessions WHERE token_sha256 = ?", (orders_api.token_hash(a),))
        self.assertEqual(self.call("GET", "/v1/orders", {"Authorization": "Bearer " + a})[0], 401)
        self.assertEqual(self.call("GET", "/v1/orders", {"Authorization": "Bearer " + b})[0], 200)

    def test_me_keys_only_for_existing_operations(self):
        _, _, d = self.call("GET", "/v1/orders", OP)
        self.assertEqual(d["me"]["keys"], {"S": "ship", "P": "print"})

    def test_bulk_error_texts_follow_screen_spec(self):
        st, _, d = self.ship(["583961"], "text-key-0001", op="cancel")
        self.assertEqual((st, d["error"]["cause"]), (409, "この注文は出荷指示済みのため、取り消せません"))
        self.assertNotIn("元に戻して", d["error"]["action"])  # 出荷指示を戻す API が無いので、その操作を指示しない
        st, _, d = self.ship(["583961", "583776"], "text-key-0002")
        self.assertEqual(d["error"]["cause"], "2 件のうち 2 件は、ほかの担当者が先に出荷指示していました")
        st, _, d = self.ship(["582473", "583961"], "text-key-0003")
        self.assertEqual((st, d["error"]["cause"]), (409, "2 件のうち 1 件を出荷指示にできませんでした"))

    def test_bad_cursor_and_inputs_are_400(self):
        def cur(**kw):
            return base64.urlsafe_b64encode(json.dumps(dict({"s": "next", "g": 1, "t": "x", "i": "1"}, **kw)).encode()).decode().rstrip("=")
        _, _, d = self.call("GET", "/v1/orders?limit=2", OP, route="/v1/orders")
        bad = [f"after={cur(g=[1])}", f"after={cur(g=10 ** 30)}", f"after={cur(g='a')}", f"carrier=yamato&after={d['nextCursor']}",
               "q=" + "あ" * 65, "since=2026-11-06T00:00:00", "limit=%D9%A5", "limit=%EF%BC%95", "view=shipped&sort=next&after=x",
               "sort=-shippedAt"]
        for qs in bad:
            st, _, e = self.call("GET", f"/v1/orders?{qs}", OP, route="/v1/orders")
            self.assertEqual((qs, st, e["error"]["code"]), (qs, 400, "INVALID_REQUEST"))
        _, _, d = self.call("GET", "/v1/orders?q=%25", OP, route="/v1/orders")  # % は字として探す
        self.assertEqual(d["total"], 0)

    def test_shipped_view_total_order_and_suggestions(self):
        _, _, d = self.call("GET", "/v1/orders?view=shipped&carrier=nonexistent", OP, route="/v1/orders")
        self.assertEqual((d["total"], [s["withoutFilter"] for s in d["suggestions"]]), (0, ["carrier"]))
        _, _, d = self.call("GET", "/v1/orders?view=shipped&limit=5", OP, route="/v1/orders")
        at = [i["shippedAt"] for i in d["items"]]
        self.assertEqual((d["total"], at), (11, sorted(at, reverse=True)))
        seen, after = [], ""
        for _ in range(5):
            _, _, p = self.call("GET", "/v1/orders?view=shipped&limit=4" + (f"&after={after}" if after else ""), OP, route="/v1/orders")
            seen += [i["orderId"] for i in p["items"]]
            after = p["nextCursor"]
            if not after:
                break
        self.assertEqual(len(set(seen)), 11)

    def test_view_counts_for_every_tab(self):
        _, _, d = self.call("GET", "/v1/orders", OP)
        self.assertEqual(d["viewCounts"], {"today": 18, "mine": 4, "pending-all": 3, "shipped": 11})

    def test_same_key_race_replays_first_answer(self):
        """別のプロセスが同じ冪等キーを先にコミットした場面。後の書き込みは全部戻して、先の応答を返す"""
        st, _, first = self.ship(["584216"], "race-key-0001")
        real_q, hidden = self.api.q, []

        def q(sql, args=()):
            if "FROM idempotency" in sql and not hidden:
                hidden.append(1)
                return []  # 先の行がまだ見えなかった
            return real_q(sql, args)
        self.api.q = q
        st2, hdr, again = self.ship(["584216"], "race-key-0001")
        self.assertEqual((st2, again, hdr.get("Idempotent-Replayed")), (st, first, "true"))
        n = self.api.conn.execute("SELECT COUNT(*) FROM order_events WHERE order_id = '584216' AND kind = 'shipped'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_key_is_claimed_before_reading_rows(self):
        """行の鍵で待つ DB でも同じキーの 2 本目が 500 にならないよう、注文の行を読む前に冪等キーを取る"""
        stmts = []

        def trace(stmt):
            stmts.append(stmt)
            self.api._trace(stmt)
        self.api.conn.set_trace_callback(trace)
        self.ship(["584216"], "claim-key-0001")
        self.api.conn.set_trace_callback(self.api._trace)
        claim = next(i for i, x in enumerate(stmts) if x.startswith("INSERT INTO idempotency"))
        read = next(i for i, x in enumerate(stmts) if x.startswith("SELECT o.id,") and "FROM orders o" in x)
        self.assertLess(claim, read)

    def test_input_edges_are_400(self):
        for qs in ("since=0001-01-01T00:00:00Z", "since=2026-11-06T00:00:00Z&status=pending", "since=2026-11-06T00:00:00Z&q=zzzz",
                   "since=2026-11-06T00:00:00Z&view=pending-all", "view=mine&staff=none"):
            st, _, e = self.call("GET", f"/v1/orders?{qs}", OP, route="/v1/orders")
            self.assertEqual((qs, st, e["error"]["code"]), (qs, 400, "INVALID_REQUEST"))
        self.assertNotIn("exc", self.log.getvalue())

    def test_invalid_traceparent_gets_a_new_trace_id(self):
        zero = "00-" + "0" * 32 + "-" + "0" * 16 + "-00"
        _, hdr, _ = self.call("GET", "/v1/orders", dict(OP, traceparent=zero))
        self.assertNotEqual(hdr["X-Trace-Id"], "0" * 32)
        good = "00-" + "ab" * 16 + "-" + "cd" * 8 + "-01"
        _, h1, _ = self.call("GET", "/v1/orders", dict(OP, traceparent=good))
        _, h2, _ = self.call("GET", "/v1/orders", dict(OP, traceparent=good))
        self.assertEqual((h1["X-Trace-Id"], h2["X-Trace-Id"]), ("ab" * 16, "ab" * 16))
        self.assertNotEqual(h1["X-Request-Id"], h2["X-Request-Id"])  # 追跡番号が同じでも、要求の番号で分けられる

    def test_http_refuses_chunked_slow_body_and_logs_other_methods(self):
        srv = orders_api.make_server(self.api, "127.0.0.1", 0, read_timeout_s=0.5)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        tok = OP["Authorization"]
        try:
            smuggled = b"GET /v1/orders?limit=1 HTTP/1.1\r\nHost: x\r\nAuthorization: " + tok.encode() + b"\r\n\r\n"
            req = (b"POST /v1/orders/ship HTTP/1.1\r\nHost: x\r\nAuthorization: " + tok.encode() + b"\r\nIdempotency-Key: te-key-0001\r\n"
                   b"Transfer-Encoding: chunked\r\n\r\n" + f"{len(smuggled):x}".encode() + b"\r\n" + smuggled + b"\r\n0\r\n\r\n")
            with socket.create_connection(("127.0.0.1", port), timeout=3) as s:
                s.sendall(req)
                got = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    got += chunk
            self.assertEqual(got.count(b"HTTP/1.1 "), 1)  # 応答は 1 つだけで、接続は切れる
            self.assertTrue(got.startswith(b"HTTP/1.1 400"))
            t0 = time.monotonic()
            with socket.create_connection(("127.0.0.1", port), timeout=3) as s:
                s.sendall(b"POST /v1/orders/ship HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n")
                first = s.recv(65536)
            self.assertTrue(first.startswith(b"HTTP/1.1 400"))
            self.assertLess(time.monotonic() - t0, 2.5)  # 本文が届かない接続は、読み込みの時間切れで切る
            n = len(self.log.getvalue().splitlines())
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("PUT", "/v1/orders", body=b"{}", headers=OP)
            res = conn.getresponse()
            self.assertEqual((res.status, json.loads(res.read())["error"]["code"]), (400, "INVALID_REQUEST"))
            conn.close()
            self.assertEqual(len(self.log.getvalue().splitlines()), n + 1)  # PUT も要約のログに 1 行
        finally:
            srv.shutdown()
            srv.server_close()

    def test_unexpected_exception_is_500_with_one_log_line(self):
        def boom(*a):
            raise OverflowError("x")
        self.api.list_orders = boom
        st, hdr, d = self.call("GET", "/v1/orders", OP)
        self.assertEqual((st, d["error"]["code"], d["error"]["traceId"]), (500, "ORDER_LIST_INTERNAL", hdr["X-Trace-Id"]))
        rec = json.loads(self.log.getvalue().splitlines()[-1])
        self.assertEqual((rec["status"], rec["exc"]), (500, "OverflowError"))

    def test_expired_keys_are_purged_without_writes(self):
        self.ship(["584216"], "old-key-0002")
        self.api.conn.execute("UPDATE idempotency SET created_at = '2026-11-05T00:00:00.000000Z'")
        self.api.purge_expired()  # server.py が 10 分ごとに呼ぶ
        self.assertEqual(self.api.conn.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0], 0)

    def test_http_rejects_bad_content_length(self):
        srv = orders_api.make_server(self.api, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            for length in ("-1", str(orders_api.MAX_BODY + 1)):
                conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=3)
                conn.putrequest("POST", "/v1/orders/ship")
                for k, v in dict(OP, **{"Idempotency-Key": "len-key-0001", "Content-Length": length}).items():
                    conn.putheader(k, v)
                conn.endheaders()
                res = conn.getresponse()
                self.assertEqual((length, res.status, json.loads(res.read())["error"]["code"]), (length, 400, "INVALID_REQUEST"))
                conn.close()
        finally:
            srv.shutdown()
            srv.server_close()


    # ---- 敵対的レビューの第 3 回の指摘（2026-11-07）を結んだ試験
    def test_since_reports_uncancel_by_old_api(self):
        """中: 旧 API の取り消しの戻しも since に出る。since は行が変わったら必ず動く印（changed_at）で数える"""
        self.ship(["584216"], "since-unc-0001", op="cancel")
        _, _, d = self.call("GET", "/v1/orders", OP)
        served = d["servedAt"]
        time.sleep(0.01)
        self.api.conn.execute("UPDATE orders SET is_cancelled = 0 WHERE id = '584216'")  # 旧 API の取り消しの戻し
        _, _, ch = self.call("GET", f"/v1/orders?since={served}", OP, route="/v1/orders")
        got = {i["orderId"]: i for i in ch["items"]}
        self.assertIn("584216", got)
        self.assertEqual((got["584216"]["status"], got["584216"]["cancelledAt"]), ("ready", None))

    def test_today_list_does_not_grow_with_shipped_history(self):
        """中: 過去に済になった行が溜まっても、今日出荷の一覧と件数は履歴の量に比例して遅くならない"""
        def median():
            ts = []
            for _ in range(15):
                t0 = time.perf_counter()
                self.call("GET", "/v1/orders", OP)
                ts.append(time.perf_counter() - t0)
            return sorted(ts)[7] * 1000
        base = median()
        rows = [(str(900000 + k), 1, f"2025-01-02T01:{k % 60:02d}:00.000000Z") for k in range(50000)]
        self.api.conn.execute("BEGIN")
        self.api.conn.executemany("INSERT INTO orders (id, shop_id, customer_id, status, amount_yen, carrier, payment, ordered_at, ship_due,"
                                  " shipped_by, shipped_at) VALUES (?, 's1', ?, 'shipped', 1000, 'yamato', 'card', ?, '2025-01-02',"
                                  " 'u-takagi', ?)", [(i, c, t, t) for i, c, t in rows])
        self.api.conn.execute("COMMIT")
        after = median()
        self.assertLess(after, max(4 * base, base + 2.0), f"履歴 50,000 行で中央値 {base:.2f}ms → {after:.2f}ms")

    def _serve(self, read_timeout_s=0.5):
        srv = orders_api.make_server(self.api, "127.0.0.1", 0, read_timeout_s=read_timeout_s)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    @staticmethod
    def _drip(port, parts, gap):
        """要求を parts に分け、gap 秒おきに送る。応答の全部と、最初の応答までの秒を返す"""
        t0 = time.monotonic()
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            for p in parts:
                if select.select([s], [], [], 0)[0]:  # 応答が来たら送るのをやめて読む（読まれない送りで接続をリセットさせない）
                    break
                try:
                    s.sendall(p)
                except OSError:
                    break
                time.sleep(gap)
            got = b""
            while True:
                try:
                    chunk = s.recv(65536)
                except OSError:
                    break
                if not chunk:
                    break
                got += chunk
        return got, time.monotonic() - t0

    def test_http_whole_request_has_one_deadline(self):
        """中: 時間切れは recv 1 回ごとではなく、要求の行・見出し・本文の全体で 1 つ。遅い本文も遅い見出しも 400 で切る"""
        port = self._serve(0.5)
        tok = OP["Authorization"].encode()
        body = b'{"orderIds":["584216"]}'
        head = (b"POST /v1/orders/ship HTTP/1.1\r\nHost: x\r\nAuthorization: " + tok + b"\r\nIdempotency-Key: drip-key-0001\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n")
        got, _ = self._drip(port, [head] + [body[i:i + 6] for i in range(0, len(body), 6)], 0.3)
        self.assertTrue(got.startswith(b"HTTP/1.1 400"), got[:40])
        lines = [b"GET /v1/orders HTTP/1.1\r\n", b"Host: x\r\n", b"Authorization: " + tok + b"\r\n", b"X-A: 1\r\n", b"\r\n"]
        got, _ = self._drip(port, lines, 0.3)
        self.assertTrue(got.startswith(b"HTTP/1.1 400"), got[:40])
        self.assertEqual(self.api.conn.execute("SELECT status FROM orders WHERE id = '584216'").fetchone()[0], "ready")

    def test_http_server_own_errors_carry_four_points_and_log(self):
        """低: http.server が自分で返す誤り（壊れた要求の行、長すぎる URI、多すぎる見出し）も、4 点・no-store・ログの 1 行を通す"""
        port = self._serve(2.0)
        reqs = [b"GARBAGE\r\n\r\n", b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\nHost: x\r\n\r\n",
                b"GET /v1/orders HTTP/1.1\r\nHost: x\r\n" + b"".join(b"X-%d: 1\r\n" % i for i in range(120)) + b"\r\n"]
        n = len(self.log.getvalue().splitlines())
        for raw in reqs:
            got, _ = self._drip(port, [raw], 0)
            head, _, body = got.partition(b"\r\n\r\n")
            self.assertRegex(head, rb"^HTTP/1\.1 4\d\d ", raw[:20])
            self.assertIn(b"Cache-Control: no-store", head)
            err = json.loads(body)["error"]
            self.assertEqual((set(err) >= {"category", "cause", "action", "traceId"}, err["code"]), (True, "INVALID_REQUEST"))
        lines = self.log.getvalue().splitlines()[n:]
        self.assertEqual(len(lines), 3)
        self.assertNotIn("GARBAGE", "".join(lines))  # 要求の行の中身はログに書かない

    def test_blank_and_repeated_query_values_are_400(self):
        """低: 空の値と、同じ引数の重ねを黙って捨てずに 400 にする"""
        for qs in ("since=", "q=", "after=", "limit=", "bogus=", "staff=", "carrier=", "view=", "bogus", "limit=5&limit=6"):
            st, _, e = self.call("GET", f"/v1/orders?{qs}", OP, route="/v1/orders")
            self.assertEqual((qs, st, e["error"]["code"]), (qs, 400, "INVALID_REQUEST"))

    def test_mine_suggestions_offer_only_filters_the_caller_set(self):
        """低: 自分の担当の暗黙の条件は候補に出さない（画面は引数で外せない）"""
        _, _, d = self.call("GET", "/v1/orders?view=mine&q=zzzz", OP, route="/v1/orders")
        self.assertEqual((d["total"], [s["withoutFilter"] for s in d["suggestions"]]), (0, ["q"]))

    def test_write_updates_before_reading_rows(self):
        """低: 書き込みは条件つきの UPDATE を先に流し、書けなかった行だけを後で読んで分ける。行の鍵で待つ DB でも、
        2 人目の出荷指示は 1 人目のコミットを待って 0 行になり、500 ではなく ORDER_ALREADY_SHIPPED になる"""
        stmts = []

        def trace(stmt):
            stmts.append(stmt)
            self.api._trace(stmt)
        self.api.conn.set_trace_callback(trace)
        self.ship(["584216", "583961"], "order-key-0001")
        self.api.conn.set_trace_callback(self.api._trace)
        upd = next(i for i, x in enumerate(stmts) if x.startswith("UPDATE orders SET"))
        reads = [i for i, x in enumerate(stmts) if x.startswith("SELECT") and "FROM orders o" in x]
        self.assertTrue(reads and all(i > upd for i in reads), "注文の行を UPDATE の前に読んでいる")
        st, _, d = self.ship(["584216"], "order-key-0002", self.auth("u-mori"))
        self.assertEqual((st, d["results"][0]["outcome"], d["results"][0]["shippedBy"]["id"]), (409, "already_shipped", "u-takagi"))

    def _capture(self):
        """API が DB に渡す文と引数を、置き換え引数を埋める前の形で控える"""
        api, calls = self.api, []

        class Spy:
            def __init__(self, conn):
                self._c = conn

            def execute(self, sql, args=()):
                calls.append((sql, args))
                return self._c.execute(sql, args)

            def __getattr__(self, k):
                return getattr(self._c, k)
        real = api.conn
        api.conn = Spy(real)
        self.addCleanup(setattr, api, "conn", real)
        return calls

    def _every_route(self, extra=()):
        self.call("GET", "/v1/orders?limit=5", OP, route="/v1/orders")
        _, _, d = self.call("GET", "/v1/orders?limit=2", OP, route="/v1/orders")
        self.call("GET", f"/v1/orders?limit=2&after={d['nextCursor']}", OP, route="/v1/orders")
        for qs in ("view=mine&q=zzzz", "view=shipped&carrier=yamato", "view=pending-all&payment=card&staff=none",
                   "status=late&staff=u-mori&q=58", f"since={d['servedAt']}", *extra):
            self.call("GET", f"/v1/orders?{qs}", OP, route="/v1/orders")
        self.call("GET", "/v1/orders/584205", OP, route="/v1/orders/{orderId}")
        self.ship(["584216", "583961", "582473", "700001"], "grant-key-0001")
        self.ship(["584216", "583961", "582473", "700001"], "grant-key-0001")  # 再生
        self.ship(["584230", "583961"], "grant-key-0002", op="cancel")
        self.ship(["583961"], "grant-key-0003", op="cancel")
        self.api.handle("POST", "/v1/orders/ship", dict(OP, **{"Idempotency-Key": "grant-key-0004"}), b"[" * 16000)  # 入れ子の深い本文

    def test_api_writes_only_its_own_tables(self):
        """DB の利用者の権限の根拠。API の流す SQL が samples/api/db-access.json の一覧（表・操作・列・行の絞り方）の外に出ない"""
        import re
        access = json.loads((HERE / "db-access.json").read_text(encoding="utf-8"))["tables"]
        cols = {t: [r[1] for r in self.api.conn.execute(f"PRAGMA table_info({t})")] for t in access}
        schema = {r[0] for r in self.api.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(schema, set(access))  # 一覧に無い表を作らない。一覧の表は全部ある
        for t, a in access.items():  # 一覧の列は表にある列だけ。トリガーだけが書く列は API の UPDATE に入れない
            self.assertTrue(set(a["insert"]) | set(a["update"]) | set(a.get("triggerColumns", [])) <= set(cols[t]), t)
            self.assertFalse(set(a["update"]) & set(a.get("triggerColumns", [])), t)
        calls = self._capture()
        self._every_route()
        bad = []
        for sql, _ in calls:
            s = " ".join(sql.split())
            if s.upper() in ("BEGIN", "BEGIN IMMEDIATE", "COMMIT", "ROLLBACK"):
                continue
            for t in set(re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", s)):
                if not access.get(t, {}).get("select"):
                    bad.append(f"読めない表 {t}: {s[:80]}")
            catalog = json.loads((HERE / "db-access.json").read_text(encoding="utf-8"))["catalogReads"]
            bad = [b for b in bad if not any(b.startswith(f"読めない表 {t}:") for t in catalog)]  # 既定で読める DB の目録（トリガーの有無）
            if any(access.get(t, {}).get("rows", {}).get("by") == "shop_id" for t in re.findall(r"\b(?:FROM|UPDATE)\s+(\w+)", s)) \
                    and not re.search(r"shop_id = [?:]", s):
                bad.append(f"店で絞らない文: {s[:80]}")
            m = re.match(r"INSERT INTO (\w+)\s*(?:\(([^)]*)\))?", s)
            if m:
                got = [c.strip() for c in m.group(2).split(",")] if m.group(2) else cols[m.group(1)]
                extra = set(got) - set(access.get(m.group(1), {}).get("insert", []))
                bad += [f"INSERT {m.group(1)} の列 {sorted(extra)}"] if extra else []
            m = re.match(r"UPDATE (\w+) SET (.*?) WHERE ", s)
            if m:
                got = {part.split("=")[0].strip() for part in m.group(2).split(",")}
                extra = got - set(access.get(m.group(1), {}).get("update", []))
                bad += [f"UPDATE {m.group(1)} の列 {sorted(extra)}"] if extra else []
            m = re.match(r"DELETE FROM (\w+)", s)
            if m and not access.get(m.group(1), {}).get("delete"):
                bad.append(f"DELETE {m.group(1)}")
            for t in set(re.findall(r"\b(?:FROM|JOIN|INTO)\s+(\w+)", s)):  # 親の表を通す表は、店で絞った注文の番号でだけ引く
                if access.get(t, {}).get("rows", {}).get("by") == "parent" and not re.search(
                        r"\border_id = \?|INSERT INTO \w+ \([^)]*\) SELECT id, .* FROM orders WHERE shop_id = \?", s):
                    bad.append(f"親の表を通さない文: {s[:80]}")
            if not re.match(r"(SELECT|WITH|INSERT|UPDATE|DELETE) ", s):
                bad.append(f"一覧に無い種類の文: {s[:40]}")
            for t in set(re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", s)):  # 店で絞れない表は、鍵のハッシュか、店で絞った注文の列から結ぶ道だけで読む
                rows = access.get(t, {}).get("rows", {})
                if rows.get("by") == "token":
                    via = [v.split(".") for v in rows.get("via", []) if not v.startswith("sessions.")]
                    if not ("token_sha256 = current_setting('app.key_hash')" in s or any(re.search(rf"\b{t} \w+ ON \w+\.id = o\.{col}\b", s) for _, col in via)):
                        bad.append(f"鍵でも注文の列からでもなく {t} を読む文: {s[:80]}")
            mark = json.loads((HERE / "db-access.json").read_text(encoding="utf-8"))["cancelMark"]["column"]
            if s.startswith("UPDATE orders") and f"{mark} = 0" not in s:  # 取り消しの正の印を条件に持たない書き込み
                bad.append(f"取り消しの印を見ない書き込み: {s[:80]}")
            live = len(re.findall(r"(?<!WHEN o\.)status (?:IN \('action','ready','pending'\)|IN \('ready'\)|= 'pending')", s))  # 並びの CASE は除く
            if live > len(re.findall(rf"{mark} = [01]", s)):  # 未出荷の状態で選ぶ読みと書きは、取り消しの印で取消済みを外す
                bad.append(f"取り消しの印を見ずに未出荷の行を選ぶ文: {s[:80]}")
        self.assertEqual(bad, [])
        self.assertTrue(any(s.startswith("UPDATE orders") for s, _ in calls))
        self.assertFalse(any(s.startswith("DELETE") for s, _ in calls))  # 書き込みの取引で店の冪等キーを消さない（第 12 回）

    def test_request_values_never_enter_sql_text(self):
        """乗っ取りへの答えの 1 つ目。要求の値は置き換え引数でだけ DB に渡り、SQL の文字列には入らない（注入を通さない作り）"""
        calls = self._capture()
        marks = ["zqmarkq", "zcarrierz", "zpaymentz", "u-zstaffz", "987654301", "987654302", "markerkey-0001"]
        for qs in (f"q={marks[0]}", f"carrier={marks[1]}&payment={marks[2]}&staff={marks[3]}"):
            self.call("GET", f"/v1/orders?{qs}", OP, route="/v1/orders")
        self.call("GET", f"/v1/orders/{marks[4]}", OP, route="/v1/orders/{orderId}")
        self.ship([marks[5]], marks[6])
        self._every_route(("q=%27%20OR%201%3D1%20--", "q=%25_%5C"))
        texts = " ".join(s for s, _ in calls)
        args = " ".join(str(a) for _, a in calls)
        for m in marks + ["OR 1=1"]:
            self.assertNotIn(m, texts)
        self.assertTrue(all(m in args for m in marks))

    # ---- 敵対的レビューの第 4 回の指摘（2026-11-07）を結んだ試験
    def test_since_server_time_comes_from_db_clock(self):
        """低: servedAt は changed_at と同じ DB の時計で取る（アプリの時計とのずれを since に持ち込まない）。0 行の since でも同じ。
        書き手の取引の長さは、上限を掛けずに servedAt の側（まだコミットしていない書き手の取引の始まり）で吸収する"""
        self.api.conn.create_function("now_utc", 0, lambda: "2026-11-06T01:00:00.000000Z")
        recent = orders_api.iso(self.api.now() - orders_api.dt.timedelta(seconds=60))  # since は直近 15 分の窓の中だけを受ける
        for qs in ("", f"?since={recent}", "?since=2026-12-01T00:00:00Z"):
            _, _, d = self.call("GET", "/v1/orders" + qs, OP, route="/v1/orders")
            self.assertEqual((qs, d["servedAt"]), (qs, "2026-11-06T01:00:00.000000Z"))
        ov = json.loads((HERE / "db-access.json").read_text(encoding="utf-8"))["sinceOverlap"]
        self.assertEqual(ov["overlapS"], orders_api.SINCE_OVERLAP_S)
        self.assertEqual(ov["apiTransactionLimitS"], orders_api.DEADLINE_S)
        self.assertIn("orders_write_horizon", ov["horizon"])  # 書き手の取引の長さは、上限でなく servedAt の側で吸収する

    def test_deeply_nested_body_is_400_not_500(self):
        """低: 入れ子の深い本文は RecursionError を 500 にせず、400 の INVALID_REQUEST にする。例外の名前もログに残らない"""
        for raw in (b"[" * 16000, b'{"orderIds":' + b"[" * 5000 + b"]" * 5000 + b"}"):
            st, _, out = self.api.handle("POST", "/v1/orders/ship", dict(OP, **{"Idempotency-Key": "deep-key-0001"}), raw)
            self.assertEqual((st, json.loads(out)["error"]["code"]), (400, "INVALID_REQUEST"))
        self.assertNotIn('"exc"', self.log.getvalue())

    def test_http_silent_connections_cannot_hold_every_slot(self):
        """低: 同時の接続の上限を、黙った接続と途中で黙る接続で埋めても、新しい要求は通る。上限に達したら、
        要求を読み終えていない接続のうち最も古いものを切って席を空ける（処理中の接続は切らない）。切った接続はログに 1 行"""
        srv = orders_api.make_server(self.api, "127.0.0.1", 0, read_timeout_s=2.0, max_conn=4)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        port, held = srv.server_address[1], []
        for i in range(4):
            s = socket.create_connection(("127.0.0.1", port), timeout=5)
            if i % 2:
                s.sendall(b"GET /v1/orders HTTP/1.1\r\n")  # 途中まで送って黙る
            held.append(s)
            self.addCleanup(s.close)
        time.sleep(0.2)
        for k in range(3):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/v1/orders", headers=OP)
            res = conn.getresponse()
            self.assertEqual((k, res.status), (k, 200))
            res.read()
            conn.close()
        recs = [json.loads(x) for x in self.log.getvalue().splitlines()]
        self.assertTrue(any(r.get("reject") == "evicted_unread" for r in recs))
        self.assertFalse(any(r.get("reject") == "too_many_connections" for r in recs))

    def test_shipped_today_count_follows_the_view(self):
        """低: counts.shippedToday は、この応答の条件に当たる今日の済の行の数で、済の群の行と total − 4 群に一致する。
        店全体の今日の済は viewCounts.shipped が持つ"""
        for qs in ("view=mine", "view=today", "view=pending-all", "view=shipped", "carrier=yamato"):
            _, _, d = self.call("GET", f"/v1/orders?{qs}&limit=100", OP, route="/v1/orders")
            rows = sum(1 for i in d["items"] if i["group"] == "shipped")
            four = sum(d["counts"][g] for g in orders_api.GROUPS)
            self.assertEqual((qs, d["counts"]["shippedToday"], d["total"] - four), (qs, rows, rows))
        c = self.api.conn
        rid = c.execute("SELECT id FROM orders WHERE shop_id = 's1' AND status = 'ready' ORDER BY id LIMIT 1").fetchone()[0]
        c.execute("UPDATE orders SET ship_due = '2026-11-09' WHERE id = ?", (rid,))
        _, _, before = self.call("GET", "/v1/orders?limit=100", OP, route="/v1/orders")
        self.assertEqual(self.ship([rid], "due-key-0001")[0], 200)
        _, _, d = self.call("GET", "/v1/orders?limit=100", OP, route="/v1/orders")
        self.assertNotIn(rid, [i["orderId"] for i in d["items"]])  # 出荷予定日が明日の行は、今日出荷のビューに出ない
        self.assertEqual(d["counts"]["shippedToday"], before["counts"]["shippedToday"])
        self.assertEqual(d["viewCounts"]["shipped"], before["viewCounts"]["shipped"] + 1)

    # ---- 敵対的レビューの第 5 回の指摘（2026-11-07）を結んだ試験
    def test_since_has_a_window_and_lock_wait_counts_toward_the_deadline(self):
        """高: since は直近の窓（SINCE_WINDOW_S）より古い時刻を 400 にし、店の全履歴をたどらせない。
        API の lock を待つ時間も打ち切りの 8 秒に入れる（重い要求を並べて、ほかの要求を後ろで待たせない）"""
        old = orders_api.iso(self.api.now() - orders_api.dt.timedelta(seconds=orders_api.SINCE_WINDOW_S + 60))
        for qs in ("since=2000-01-01T00:00:00Z&limit=1", f"since={old}"):
            st, _, e = self.call("GET", f"/v1/orders?{qs}", VIEWER, route="/v1/orders")
            self.assertEqual((qs, st, e["error"]["code"]), (qs, 400, "INVALID_REQUEST"))
        ok = orders_api.iso(self.api.now() - orders_api.dt.timedelta(seconds=60))
        self.assertEqual(self.call("GET", f"/v1/orders?since={ok}", VIEWER, route="/v1/orders")[0], 200)
        api = orders_api.make_api(29, log=io.StringIO(), deadline_s=0.3)
        api.lock.acquire()
        threading.Timer(1.5, api.lock.release).start()
        t0 = time.monotonic()
        st, _, out = api.handle("GET", "/v1/orders", {"Authorization": "Bearer " + api.token_for("u-kobayashi")})
        self.assertEqual((st, json.loads(out)["error"]["code"]), (503, "ORDER_LIST_UPSTREAM_SLOW"))
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_http_unread_responses_cannot_hold_every_slot(self):
        """中: 応答を読まない接続（要求を続けて送り、応答を読まない）で上限を埋めても、新しい要求は通る。応答を書き終えない接続も
        席を空けるために切れる。書き込みの時間切れのあとに 400 を書き足さない（ログに slow_request を残さない）"""
        self.setUp(400)
        srv = orders_api.make_server(self.api, "127.0.0.1", 0, read_timeout_s=2.0, max_conn=4)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        port = srv.server_address[1]
        req = ("GET /v1/orders?limit=100 HTTP/1.1\r\nHost: x\r\nAuthorization: " + VIEWER["Authorization"] + "\r\n\r\n").encode()
        for _ in range(4):
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
            s.connect(("127.0.0.1", port))
            s.setblocking(False)
            try:
                s.send(req * 40)
            except OSError:
                pass
            self.addCleanup(s.close)
        time.sleep(0.8)
        for k in range(3):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/v1/orders?limit=5", headers=VIEWER)
            res = conn.getresponse()
            self.assertEqual((k, res.status), (k, 200))
            res.read()
            conn.close()
        recs = [json.loads(x) for x in self.log.getvalue().splitlines()]
        self.assertFalse(any(r.get("reject") == "slow_request" for r in recs))

    def test_list_served_at_comes_from_the_rows_statement(self):
        """中（第 5 回）と中 4（第 10 回）: 一覧と since の servedAt は、読みの取引を始める前の 1 つの文で、DB の時計と書き手の取引の始まりから取る。
        行と件数の文は全部、そのあとの 1 つの読みの取引で流す（本番は READ ONLY の REPEATABLE READ）"""
        calls = self._capture()
        _, _, d = self.call("GET", "/v1/orders?limit=1", OP, route="/v1/orders")
        for qs in ("limit=5", "view=shipped", "q=zzzz", f"since={d['servedAt']}"):
            del calls[:]
            self.call("GET", f"/v1/orders?{qs}", OP, route="/v1/orders")
            sqls = [" ".join(s.split()) for s, _ in calls]
            clock = [i for i, s in enumerate(sqls) if "write_horizon()" in s]
            begin, commit = sqls.index("BEGIN"), sqls.index("COMMIT")
            self.assertEqual((qs, len(clock), clock[0] < begin), (qs, 1, True))
            body = [i for i, s in enumerate(sqls) if i not in clock and not s.startswith(("BEGIN", "COMMIT", "ROLLBACK"))]
            self.assertTrue(begin < min(body) and max(body) < commit, qs)
            self.assertFalse(any("now_utc()" in sqls[i] for i in body), qs)  # 取引の中で時計を読み直さない

    def test_log_method_is_a_known_word(self):
        """中: 要約のログのメソッドは決まった語だけ。鍵の無い相手が要求の行に長い文字列を入れても、ログの 1 行は短い"""
        st, _, out = self.api.handle("X" * 60000, "/v1/orders", {})
        line = self.log.getvalue().splitlines()[-1]
        self.assertEqual((st, json.loads(line)["method"]), (400, "OTHER"))
        self.assertLess(len(line), 1000)
        port = self._serve(2.0)
        got, _ = self._drip(port, [b"Y" * 60000 + b" /v1/orders HTTP/1.1\r\nHost: x\r\n\r\n"], 0)
        self.assertTrue(got.startswith(b"HTTP/1.1 400"), got[:40])
        line = self.log.getvalue().splitlines()[-1]
        self.assertEqual(json.loads(line)["method"], "OTHER")
        self.assertLess(len(line), 1000)

    def test_cursor_is_bound_to_the_day_and_since_covers_rows_moved_while_paging(self):
        """中: 起点は日付（日本時間）に結びつく。日付が変わると群が変わるので、前の日の起点は 400 で、画面は先頭から読み直す。
        送りのあいだに群が前に戻った行（決済待ちから出荷可へ）は、最初の頁の servedAt からの since で必ず届く"""
        _, _, p1 = self.call("GET", "/v1/orders?limit=5", OP, route="/v1/orders")
        moved = self.api.conn.execute("SELECT id FROM orders WHERE shop_id = 's1' AND status = 'pending' AND is_cancelled = 0 LIMIT 1").fetchone()[0]
        time.sleep(0.01)
        self.api.conn.execute("UPDATE orders SET status = 'ready' WHERE id = ?", (moved,))  # 群 3 から群 2 へ（起点より前）
        seen, after = [i["orderId"] for i in p1["items"]], p1["nextCursor"]
        while after:
            _, _, p = self.call("GET", f"/v1/orders?limit=5&after={after}", OP, route="/v1/orders")
            seen += [i["orderId"] for i in p["items"]]
            after = p["nextCursor"]
        _, _, ch = self.call("GET", f"/v1/orders?since={p1['servedAt']}", OP, route="/v1/orders")
        self.assertIn(moved, set(seen) | {i["orderId"] for i in ch["items"]})
        cur = p1["nextCursor"]
        self.api.t0 -= 15 * 3600  # 日本時間の日付をまたぐ
        op2 = {"Authorization": "Bearer " + self.api.login("u-takagi")}
        st, _, e = self.call("GET", f"/v1/orders?limit=5&after={cur}", op2, route="/v1/orders")
        self.assertEqual((st, e["error"]["code"]), (400, "INVALID_REQUEST"))

    def test_cursor_made_by_the_screen_is_400(self):
        """低: 起点は API の鍵で署名する。画面で組み立てた起点と、書き換えた起点は 400"""
        made = orders_api.b64({"s": "next", "f": orders_api.OrdersApi._filter_hash({"view": "today"}), "g": 3, "t": 0, "i": "000000"})
        st, _, e = self.call("GET", f"/v1/orders?view=today&after={made}", OP, route="/v1/orders")
        self.assertEqual((st, e["error"]["code"]), (400, "INVALID_REQUEST"))
        _, _, p = self.call("GET", "/v1/orders?limit=5", OP, route="/v1/orders")
        body, _, mac = p["nextCursor"].partition(".")
        cur = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        cur["i"] = "000000"
        st, _, _ = self.call("GET", f"/v1/orders?limit=5&after={orders_api.b64(cur)}.{mac}", OP, route="/v1/orders")
        self.assertEqual(st, 400)
        self.assertEqual(self.call("GET", f"/v1/orders?limit=5&after={p['nextCursor']}", OP, route="/v1/orders")[0], 200)


    # ---- 敵対的レビューの第 6 回の指摘（2026-11-07）を結んだ試験
    def test_http_one_key_cannot_take_every_slot_by_waiting_on_the_lock(self):
        """中: lock を待つ接続は処理中なので、席を空けるために切れない。閲覧者の鍵 1 本で多くの接続から要求を重ねても、
        鍵ごとの同時の要求の上限（PER_KEY_INFLIGHT）を超えた要求は待たずに 503 になり、ほかの利用者の要求は通る"""
        self.setUp(400)
        srv = orders_api.make_server(self.api, "127.0.0.1", 0, read_timeout_s=2.0, max_conn=16)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        port, stop = srv.server_address[1], threading.Event()
        req = ("GET /v1/orders?view=pending-all&limit=100 HTTP/1.1\r\nHost: x\r\nAuthorization: " + VIEWER["Authorization"] + "\r\n\r\n").encode()

        def flood():  # 接続を開いたまま、要求を 4 本ずつ重ねて送り、応答を読む。切られたら少し待って開き直す
            s = None
            while not stop.is_set():
                try:
                    if s is None:
                        s = socket.create_connection(("127.0.0.1", port), timeout=2)
                    s.sendall(req * 4)
                    got = b""
                    while got.count(b"HTTP/1.1 ") < 4 and not stop.is_set():
                        chunk = s.recv(65536)
                        if not chunk:
                            raise ConnectionResetError
                        got += chunk
                except OSError:
                    if s is not None:
                        s.close()
                    s = None
                    time.sleep(0.05)
            if s is not None:
                s.close()
        workers = [threading.Thread(target=flood, daemon=True) for _ in range(20)]
        for w in workers:
            w.start()
        self.addCleanup(stop.set)
        time.sleep(0.5)
        fails = 0
        for _ in range(10):
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                conn.request("GET", "/v1/orders?limit=5", headers=OP)
                res = conn.getresponse()
                res.read()
                fails += res.status != 200
                conn.close()
            except OSError:
                fails += 1
        stop.set()
        for w in workers:
            w.join(3)
        self.assertEqual(fails, 0)
        recs = [json.loads(x) for x in self.log.getvalue().splitlines()]
        self.assertTrue(any(r.get("reject") == "too_many_inflight" and r["status"] == 503 for r in recs))
        token = VIEWER["Authorization"].split()[1]  # 見出しの空白を変えても、同じ利用者として数える
        self.api.inflight["u-kobayashi"] = orders_api.PER_KEY_INFLIGHT
        for h in ("Bearer " + token, "Bearer   " + token, "Bearer\t" + token):
            self.assertEqual(self.api.handle("GET", "/v1/orders", {"Authorization": h})[0], 503)

    def test_rows_carry_who_cancelled(self):
        """低: 要望 5 の「した担当と日時」。取り消した行は cancelledBy と cancelledAt を一覧・詳細・since で返す"""
        _, _, d0 = self.call("GET", "/v1/orders?limit=1", OP, route="/v1/orders")
        self.assertEqual(self.ship(["584216"], "by-key-0001", op="cancel")[0], 200)
        _, _, d = self.call("GET", "/v1/orders/584216", OP, route="/v1/orders/{orderId}")
        self.assertEqual(d["cancelledBy"], {"id": "u-takagi", "name": d["cancelledBy"]["name"]})
        self.assertTrue(d["cancelledBy"]["name"] and d["cancelledAt"])
        _, _, ch = self.call("GET", f"/v1/orders?since={d0['servedAt']}", OP, route="/v1/orders")
        self.assertEqual({i["orderId"]: i["cancelledBy"]["id"] for i in ch["items"] if i["status"] == "cancelled"}, {"584216": "u-takagi"})
        _, _, d = self.call("GET", "/v1/orders?limit=100", OP, route="/v1/orders")
        self.assertTrue(all(i["cancelledBy"] is None for i in d["items"]))  # 取り消していない行は null

    # ---- 敵対的レビューの第 7 回の指摘（2026-11-07）を結んだ試験
    def test_made_up_keys_share_one_inflight_bucket(self):
        """低 11: 鍵ごとの同時の要求の上限は、確かめた鍵ごとに数える。作り物の鍵は、鍵の無い要求と同じ 1 つの単位にまとめるので、
        毎回違う鍵を付けても上限を抜けない。正しい利用者の要求は自分の単位で数える"""
        self.api.inflight["-"] = orders_api.PER_KEY_INFLIGHT
        st, _, out = self.api.handle("GET", "/v1/orders", {"Authorization": "Bearer sample-token-made-up-0001"})
        self.assertEqual((st, json.loads(out)["error"]["code"]), (503, "ORDER_LIST_UPSTREAM_SLOW"))
        self.assertEqual(self.api.handle("GET", "/v1/orders", OP)[0], 200)
        self.assertEqual(self.api.handle("GET", "/v1/orders", {"Authorization": "Bearer " + self.api.login("u-mori")})[0], 200)

    def test_contract_detail_carries_who_cancelled(self):
        """低 12: 契約の OrderDetail にも cancelledBy がある（契約から型を作る画面に、詳細の取り消した人が届く）"""
        props = CONTRACT["components"]["schemas"]["OrderDetail"]["properties"]
        self.assertIn("cancelledBy", props)
        self.assertEqual(props["cancelledBy"]["$ref"], "#/components/schemas/UserRef")

    # ---- 敵対的レビューの第 8 回の指摘（2026-11-07）と、第 9 回の決め（印を 1 つのまま、移行は足し算だけ）を結んだ試験
    def _legacy(self, name, oid, api=None):
        """旧 API の書き込み。旧 API は何も変えないので、移行の前の SQL のまま流す（書けた行の数を返す）"""
        api = api or self.api
        with api.lock:
            return api.conn.execute(LEGACY_SQL[name], (oid,)).rowcount

    def test_payment_on_a_cancelled_pending_order_survives_uncancel(self):
        """重大 1（第 8 回）: 取り消し中の決済待ちに決済が届いても、黙って 0 行にならない。取り消しを戻すと出荷可で、出荷できる。
        旧 API で取り消した注文も、新 API で取り消した注文も、移行の前と同じ結果になる"""
        c = self.api.conn
        for oid, how in (("581093", "old"), ("582787", "new")):
            if how == "old":
                self.assertEqual(self._legacy("old_cancel", oid), 1)
            else:
                self.assertEqual(self.ship([oid], f"pay-key-{oid}", op="cancel")[2]["results"][0]["outcome"], "cancelled")
            self.assertEqual(tuple(c.execute("SELECT status, is_cancelled FROM orders WHERE id = ?", (oid,)).fetchone()), ("pending", 1))
            self.assertEqual(self._legacy("old_pay", oid), 1)  # 決済の通知。条件に is_cancelled の無い旧 API の文
            self.assertEqual(self._legacy("old_uncancel", oid), 1)
            _, _, d = self.call("GET", f"/v1/orders/{oid}", OP, route="/v1/orders/{orderId}")
            self.assertEqual((how, d["status"], d["cancelledAt"]), (how, "ready", None))
            st, _, s = self.ship([oid], f"pay-ship-{oid}")
            self.assertEqual((how, st, s["results"][0]["outcome"]), (how, 200, "shipped"))

    def test_status_never_holds_cancelled_and_reads_build_it_from_the_mark(self):
        """第 9 回の決め 1〜3: DB の status に 'cancelled' を書かない。契約の status の 'cancelled' は、読むときに is_cancelled から作る"""
        c = self.api.conn
        self.assertEqual(self.ship(["584216"], "mark-key-0001", op="cancel")[0], 200)
        self.assertEqual(tuple(c.execute("SELECT status, is_cancelled FROM orders WHERE id = '584216'").fetchone()), ("ready", 1))
        _, _, d = self.call("GET", "/v1/orders/584216", OP, route="/v1/orders/{orderId}")
        self.assertEqual((d["status"], d["group"]), ("cancelled", "cancelled"))
        with self.assertRaises(sqlite3.IntegrityError):  # 表の制約が status の 'cancelled' を断る
            c.execute("UPDATE orders SET status = 'cancelled' WHERE id = '584205'")
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')")}
        self.assertFalse(names & {"migration_stage", "orders_cancel_old_to_new", "orders_refuse_ship_on_cancelled"})

    def test_old_and_new_writers_keep_the_four_rules(self):
        """第 9 回の決め 5: 旧 API と新 API が同じ注文に代わる代わる書いても、4 つが守られる。(a) 取り消した注文が出荷されない。
        (b) 取り消しが黙って外れない。(c) 戻した取り消しが黙って残らない。(d) 決済の移りが止まらない。
        どの順でも、結果は移行の前の DB（旧い表だけで、全部の書き込みを旧 API の文で流す）と同じになる。(e) 出荷のあとに印が立った行を取消と読まない。わざと穴を入れた写し 4 つでは落ちる"""
        self.assertEqual(four_rules(orders_api.OrdersApi), [])

        class ShipsCancelled(orders_api.OrdersApi):  # 出荷指示の条件に取り消しの印が無い
            SHIP_SQL = ("status = 'shipped', shipped_by = ?, shipped_at = ?", "status IN ('ready')")

        class SecondMark(orders_api.OrdersApi):  # 取り消しを別の印（cancelled_at）で持ち、旧い印を立てない
            CANCEL_SQL = ("cancelled_by = ?, cancelled_at = ?", "status IN ('action','ready','pending') AND cancelled_at IS NULL")

        class MovesStatus(orders_api.OrdersApi):  # 取り消しで status を動かす（決済待ちから外れ、決済の移りが黙って 0 行になる）
            CANCEL_SQL = ("is_cancelled = 1, status = 'action'", "status IN ('action','ready','pending') AND is_cancelled = 0")

        class HidesLateMark(orders_api.OrdersApi):  # 印が立てば済の行も取消と読む（出荷した荷物が画面から消える）
            def _row(self, r):
                out = super()._row(r)
                return dict(out, status="cancelled") if r["is_cancelled"] == 1 else out
        for hole in (ShipsCancelled, SecondMark, MovesStatus, HidesLateMark):
            self.assertNotEqual(four_rules(hole), [], f"穴を入れた写し {hole.__name__} が通った")

    def test_additive_steps_keep_every_legacy_writer_working(self):
        """高 2・高 8（第 8 回）: 移行は足し算だけで、どの段まで流しても、旧 API の書き手（取り消し、戻し、出荷、決済の通知、受注、配達済み）は
        移行の前と同じ結果になる。旧い列の定義と既存の行の値も変わらない。旧 API は止めないので、決済待ちから出荷可への移りも止まらない"""
        base = legacy_run([])
        self.assertEqual(base["ops"]["old_pay_cancelled"], 1)
        for k in range(1, len(orders_api.ADDITIONS) + 1):
            got = legacy_run(orders_api.ADDITIONS[:k])
            self.assertEqual((k, got), (k, base), f"段 {orders_api.ADDITIONS[k - 1]['step']} で旧 API の結果が変わった")

    def test_migration_steps_are_additive_and_index_builds_are_separate(self):
        """高 3・中 4・高 7・中 9（第 8 回）、中 11（第 10 回）と第 11 回の決め 1・2: 本番の移行の文は足し算だけ。列は消さず、行を書き直さず、
        表をなめて数えない。表の定義を変える文は 1 つの取引に入れ、lock_timeout は SET LOCAL で取引の中だけに置く（セッションに残さない）。
        索引は取引の外の CONCURRENTLY で、前に lock_timeout と statement_timeout を 0 に戻す（長い旧い取引を待ち、INVALID を残さない）。
        旧い書き手の文を断りうる物（足す列の外部キー、users を消す文を止める外部キー、CHECK）は足さない。status の CHECK は変えない。
        段ごとに、止めたとき・戻し方・確かめ方があり、戻し方は足した物を外さない"""
        import re
        for step in orders_api.ADDITIONS:
            for k in ("stop", "back", "verify"):
                self.assertTrue(step.get(k), f"段 {step['step']} の {k} が無い")
            texts = [" ".join(sql.split()).upper() for sql in step["pg"]]
            in_tx = False
            for k, s in enumerate(texts):
                self.assertIsNone(re.search(r"\bDROP\b|\bUPDATE ORDERS\b|\bDELETE FROM ORDERS\b|\bINSERT INTO ORDERS\b|COUNT\(|\bCHECK\b|RENAME|"
                                            r"ALTER COLUMN|SET NOT NULL|TYPE |FOREIGN KEY", s), s[:80])
                in_tx = {"BEGIN": True, "COMMIT": False}.get(s, in_tx)
                self.assertFalse(re.match(r"SET LOCK_TIMEOUT = '", s), f"セッションに残る lock_timeout: {s}")
                if s.startswith(("ALTER TABLE", "CREATE TRIGGER", "CREATE TABLE")):
                    self.assertTrue(in_tx and any(re.match(r"SET LOCAL LOCK_TIMEOUT", x) for x in texts[:k]), f"取引と lock_timeout の外: {s[:60]}")
                if s.startswith(("CREATE INDEX", "CREATE UNIQUE INDEX")) and " ON ORDERS " in s:
                    self.assertIn("CONCURRENTLY", s)
                    self.assertFalse(in_tx)
                    self.assertIn("SET LOCK_TIMEOUT = 0", texts[:k])
                    self.assertIn("SET STATEMENT_TIMEOUT = 0", texts[:k])
                if "ADD COLUMN" in s:
                    self.assertNotIn("REFERENCES", s)
                    self.assertNotIn("NOT NULL", s)
                    self.assertIsNone(re.search(r"DEFAULT [^,]*\(", s), s)  # 関数の既定値は行を書き直しうる
                if "REFERENCES USERS" in s:  # 足す表から users への外部キーは、旧い書き手の users の削除を断らない形にする
                    self.assertIn("ON DELETE CASCADE", s)
            self.assertFalse(in_tx, f"段 {step['step']} の取引が閉じていない")

    def test_inflight_bucket_knows_keys_the_login_service_wrote(self):
        """高 6（第 8 回）: ログインのサービスが sessions に直に書いた鍵も、確かめた鍵として自分の単位で数える。
        鍵の無い要求が共有の 8 本を埋めていても、正しい利用者の一覧は 503 にならない"""
        api = orders_api.make_api(29, log=io.StringIO())
        token = "sample-" + secrets.token_hex(16)  # 鍵の値はファイルに書かず、試すたびに作る
        with api.lock:
            api.conn.execute("INSERT INTO sessions VALUES (?, 'u-mori', ?)",
                             (orders_api.token_hash(token), orders_api.iso(api.now() + orders_api.dt.timedelta(hours=1))))
        hdr = {"Authorization": "Bearer " + token}
        self.assertEqual(api.handle("GET", "/v1/orders", hdr)[0], 200)
        api2 = orders_api.make_api(29, log=io.StringIO())  # 立て直したプロセス（写しの known は空）
        with api2.lock:
            api2.conn.execute("INSERT INTO sessions VALUES (?, 'u-mori', ?)",
                              (orders_api.token_hash(token), orders_api.iso(api2.now() + orders_api.dt.timedelta(hours=1))))
        api2.lock.acquire()  # 重い要求の代わり
        waiters = [threading.Thread(target=api2.handle, args=("GET", "/v1/orders", {}), daemon=True) for _ in range(orders_api.PER_KEY_INFLIGHT)]
        for w in waiters:
            w.start()
        for _ in range(200):
            if api2.inflight.get("-", 0) >= orders_api.PER_KEY_INFLIGHT:
                break
            time.sleep(0.005)
        self.assertEqual(api2.inflight.get("-", 0), orders_api.PER_KEY_INFLIGHT)
        got = []
        t = threading.Thread(target=lambda: got.append(api2.handle("GET", "/v1/orders", hdr)), daemon=True)
        t.start()
        t.join(0.3)
        self.assertTrue(t.is_alive(), "正しい鍵の要求が lock を待たずに 503 で返った")
        api2.lock.release()
        t.join(5)
        for w in waiters:
            w.join(5)
        self.assertEqual(got[0][0], 200)
        st, _, out = api2.handle("GET", "/v1/orders", {"Authorization": "Bearer sample-token-made-up-0002"})
        self.assertEqual(st, 401)  # 作り物の鍵は確かめに通らず、"-" で数えたうえで 401

    def test_reads_name_their_columns(self):
        """中 10（第 8 回）: 一覧・since・詳細は列を名前で読む。表に列を足しても、準備済みの文の結果の形は変わらない"""
        import re
        calls = self._capture()
        self._every_route()
        stars = [s for s, _ in calls if re.search(r"\b\w+\.\*|SELECT \*\s+FROM\s+(orders|order_items|customers|users)\b", " ".join(s.split()))]
        self.assertEqual(stars, [])
        self.api.conn.execute("ALTER TABLE orders ADD COLUMN extra_col TEXT")  # 足した列は応答に出ない
        _, _, d = self.call("GET", "/v1/orders/584205", OP, route="/v1/orders/{orderId}")
        self.assertNotIn("extra_col", json.dumps(d))

    def test_since_rows_say_which_views_they_belong_to(self):
        """中 11（第 8 回）: since の行は、今どのビューに入るか（inViews）を持つ。明日出荷の行は今日出荷に、ほかの担当の行は自分の担当に入らない。
        取消の行はどのビューにも入らない。タブの件数 viewCounts も since の応答に入り、一覧の値と同じ"""
        c = self.api.conn
        _, _, d0 = self.call("GET", "/v1/orders?limit=1", OP, route="/v1/orders")
        with self.api.lock:
            c.execute("UPDATE orders SET ship_due = '2026-11-09' WHERE id = '584205'")  # 明日以降の注文（受注の写し）
            c.execute("UPDATE orders SET staff_id = 'u-mori' WHERE id = '584230'")  # ほかの担当
        self.ship(["584216"], "views-key-0001", op="cancel")
        self.ship(["583865"], "views-key-0002")
        _, _, ch = self.call("GET", f"/v1/orders?since={d0['servedAt']}", OP, route="/v1/orders")
        got = {i["orderId"]: i["inViews"] for i in ch["items"]}
        self.assertEqual(got["584205"], [])
        self.assertEqual(got["584230"], ["today"])
        self.assertEqual(got["584216"], [])
        self.assertEqual(got["583865"], ["today", "mine", "shipped"])
        _, _, lst = self.call("GET", "/v1/orders?limit=1", OP, route="/v1/orders")
        self.assertEqual(ch["viewCounts"], lst["viewCounts"])

    def test_detail_rejects_ids_outside_the_contract_pattern(self):
        """低 12（第 8 回）: 詳細の注文番号が契約の形（6〜12 桁の数字）に合わなければ 400。無い注文の 404 と分ける"""
        for oid in ("abc", "1234567890123", "12345"):
            st, _, d = self.call("GET", f"/v1/orders/{oid}", OP, route="/v1/orders/{orderId}")
            self.assertEqual((oid, st, d["error"]["code"]), (oid, 400, "INVALID_REQUEST"))
        self.assertEqual(self.call("GET", "/v1/orders/999999", OP, route="/v1/orders/{orderId}")[0], 404)

    def test_who_cancelled_follows_the_mark(self):
        """旧 API が取り消しを戻してから取り消し直しても、前の取り消しの人と時刻を返さない。DB のトリガーが新しい列だけをそろえる"""
        c = self.api.conn
        self.assertEqual(self.ship(["584216"], "who-key-0001", op="cancel")[0], 200)
        first = c.execute("SELECT cancelled_at FROM orders WHERE id = '584216'").fetchone()[0]
        self.assertEqual(self._legacy("old_uncancel", "584216"), 1)
        self.assertEqual(tuple(c.execute("SELECT cancelled_by, cancelled_at FROM orders WHERE id = '584216'").fetchone()), (None, None))
        self.api.t0 -= 3600  # 1 時間進める
        self.assertEqual(self._legacy("old_cancel", "584216"), 1)
        _, _, d = self.call("GET", "/v1/orders/584216", OP, route="/v1/orders/{orderId}")
        self.assertEqual((d["status"], d["cancelledBy"]), ("cancelled", None))
        self.assertGreater(d["cancelledAt"], first)


    # ---- 敵対的レビューの第 9 回の指摘（2026-11-07）を結んだ試験
    def test_old_cancel_after_ship_keeps_the_parcel_in_sight(self):
        """重大（第 9 回）: 新 API で出荷指示した注文に、旧 API の取り消し（status の条件が無い）が印を立てても、行は済のまま見える。
        済のビューと件数から消えず、詳細は shipped と取り消しの時刻を返す。新 API の取り消しは already_cancelled でなく
        ORDER_CANCEL_NOT_ALLOWED。since も済のビューに置いたまま返す（荷物を止める判断ができる）"""
        _, _, v0 = self.call("GET", "/v1/orders?view=shipped&limit=100", OP, route="/v1/orders")
        self.assertEqual(self.ship(["581950"], "late-ship-0001")[0], 200)
        _, _, v1 = self.call("GET", "/v1/orders?view=shipped&limit=100", OP, route="/v1/orders")
        self.assertEqual(self._legacy("old_cancel", "581950"), 1)
        _, _, v2 = self.call("GET", "/v1/orders?view=shipped&limit=100", OP, route="/v1/orders")
        self.assertEqual((v2["total"], v2["viewCounts"]["shipped"]), (v1["total"], v1["viewCounts"]["shipped"]))
        self.assertEqual(v1["total"], v0["total"] + 1)
        row = {i["orderId"]: i for i in v2["items"]}["581950"]
        self.assertEqual((row["status"], row["group"], row["cancelledAfterShip"]), ("shipped", "shipped", True))
        self.assertIsNotNone(row["cancelledAt"])
        self.assertFalse(any(i["cancelledAfterShip"] for i in v2["items"] if i["orderId"] != "581950"))
        _, _, d = self.call("GET", "/v1/orders/581950", OP, route="/v1/orders/{orderId}")
        self.assertEqual((d["status"], d["shippedBy"]["id"], d["cancelledAt"] is not None, d["cancelledAfterShip"]), ("shipped", "u-takagi", True, True))
        st, _, c = self.ship(["581950"], "late-ship-0002", op="cancel")
        self.assertEqual((st, c["results"][0]["outcome"]), (409, "not_allowed"))
        _, _, ch = self.call("GET", f"/v1/orders?since={v1['servedAt']}", OP, route="/v1/orders")
        got = {i["orderId"]: i for i in ch["items"]}["581950"]
        self.assertEqual((got["status"], "shipped" in got["inViews"]), ("shipped", True))

    def _drop_feed(self):
        with self.api.lock:
            for name in orders_api.FEED_TRIGGERS:
                self.api.conn.execute(f"DROP TRIGGER {name}")

    def test_every_transaction_sets_the_key_hash_first(self):
        """高（第 9 回）: インフラの RLS は店を app.key_hash から DB の側で引く。API は要求の取引ごとに、最初の文で
        set_config('app.key_hash', 鍵のハッシュ, true) を束ねた値で流し、鍵の表は current_setting で引く（流し忘れは 401 で表に出る）。
        app.shop_id と app.shop_scope は書かない"""
        calls = self._capture()
        self._every_route()
        texts = [" ".join(s.split()) for s, _ in calls]
        bad = []
        for k, s in enumerate(texts):
            if s.upper().startswith("BEGIN"):
                nxt = texts[k + 1] if k + 1 < len(texts) else ""
                if not nxt.startswith("SELECT set_config('app.key_hash', ?, 1)"):
                    bad.append(f"取引の最初の文が鍵のハッシュを置かない: {nxt[:60]}")
            if "FROM sessions" in s and "current_setting('app.key_hash')" not in s:
                bad.append(f"鍵の表を current_setting で引かない: {s[:60]}")
            if "app.shop_id" in s or "app.shop_scope" in s:
                bad.append(f"店の値を置く文: {s[:60]}")
        self.assertEqual(bad, [])
        hashes = {a[0] for s, a in calls if s.startswith("SELECT set_config")}
        self.assertEqual(hashes, {orders_api.token_hash(OP["Authorization"].split()[1])})
        self.assertIsNone(self.api.settings.get("app.key_hash"))  # 取引の外には残さない

    def test_bulk_writes_on_old_rows_do_not_flood_since(self):
        """高・中（第 9 回）: 旧 API の一括（過去の済の行を配達済みへ移す、値の変わらない直し）は、どのビューにも入らない行か、
        何も変えない書き込みなので changed_at を進めない。since は今日の仕事の行の変化だけを数え、履歴の量によらない"""
        c = self.api.conn
        _, _, d0 = self.call("GET", "/v1/orders?limit=1", OP, route="/v1/orders")
        rows = [(str(900000 + k), f"2026-10-{1 + k % 28:02d}T01:00:00.000000Z") for k in range(20000)]
        with self.api.lock:
            c.execute("BEGIN")
            c.executemany("INSERT INTO orders (id, shop_id, customer_id, status, amount_yen, carrier, payment, ordered_at, ship_due,"
                          " shipped_by, shipped_at) VALUES (?, 's1', 1, 'shipped', 1000, 'yamato', 'card', ?, '2026-10-01', 'u-takagi', ?)",
                          [(i, t, t) for i, t in rows])
            c.execute("COMMIT")
            n = c.execute("UPDATE orders SET status = 'delivered' WHERE shop_id = 's1' AND status = 'shipped'"
                          " AND shipped_at < '2026-11-01T00:00:00.000000Z'").rowcount
            c.execute("UPDATE orders SET note = note WHERE shop_id = 's1'")  # 値の変わらない一括の直し
        self.assertEqual(n, 20000)
        t0 = time.perf_counter()
        _, _, ch = self.call("GET", f"/v1/orders?since={d0['servedAt']}&limit=100", OP, route="/v1/orders")
        ms = (time.perf_counter() - t0) * 1000
        self.assertLess(ch["total"], 50, "過去の行の一括が since に出た")
        self.assertLess(ms, 100.0)
        with self.api.lock:  # 今日の仕事の行の変化は出る
            c.execute("UPDATE orders SET staff_id = 'u-mori' WHERE id = '584230'")
        _, _, ch = self.call("GET", f"/v1/orders?since={d0['servedAt']}&limit=100", OP, route="/v1/orders")
        self.assertIn("584230", [i["orderId"] for i in ch["items"]])

    def test_since_does_not_need_a_time_limit_on_old_writers(self):
        """高（第 9 回）: 旧 API と移行の利用者に取引の上限を掛けない。servedAt を、まだコミットしていない書き手の取引の始まり
        （本番は orders_write_horizon()）より後にしないので、長い取引が遅れてコミットした行も、次の since に必ず入る"""
        c = self.api.conn
        start = orders_api.iso(self.api.now() - orders_api.dt.timedelta(seconds=40))  # 40 秒前から続く旧 API の取引
        self.api.open_writers["legacy-bulk"] = start
        _, _, d = self.call("GET", "/v1/orders?limit=1", OP, route="/v1/orders")
        self.assertLessEqual(d["servedAt"], start)
        with self.api.lock:  # その取引がいまコミットした（changed_at は取引の中で書いた時刻）
            c.execute("UPDATE orders SET is_cancelled = 1, changed_at = ? WHERE id = '584230'",
                      (orders_api.iso(self.api.now() - orders_api.dt.timedelta(seconds=39)),))
        del self.api.open_writers["legacy-bulk"]
        self.api.t0 -= 60
        _, _, ch = self.call("GET", f"/v1/orders?since={d['servedAt']}", OP, route="/v1/orders")
        self.assertIn("584230", [i["orderId"] for i in ch["items"]])
        ov = json.loads((HERE / "db-access.json").read_text(encoding="utf-8"))["sinceOverlap"]
        self.assertNotIn("writerTransactionLimitS", ov)
        for step in orders_api.ADDITIONS:  # 移行の索引と VALIDATE は打ち切らせず、INVALID の索引を黙って残さない
            text = " ".join(step["pg"]).upper()
            if "CONCURRENTLY" in text or "VALIDATE" in text:
                self.assertIn("SET STATEMENT_TIMEOUT = 0", text, step["step"])
            self.assertNotIn("CONCURRENTLY IF NOT EXISTS", text, step["step"])

    def test_since_pages_keep_the_first_served_at(self):
        """中（第 9 回）: since を起点で送るあいだ、全部の頁が最初の頁の servedAt を返す。送りが長くかかっても、最初の頁のあとに
        コミットした行（取引の始まりが最初の頁より前）は、次の since に入る"""
        self.setUp(400)
        c = self.api.conn
        _, _, d = self.call("GET", "/v1/orders?limit=1", OP, route="/v1/orders")
        ready = [r[0] for r in c.execute("SELECT id FROM orders WHERE shop_id = 's1' AND status = 'ready' AND is_cancelled = 0 ORDER BY id LIMIT 4")]
        self.assertEqual(self.ship(ready[:3], "pages-key-0001")[0], 200)
        _, _, p1 = self.call("GET", f"/v1/orders?since={d['servedAt']}&limit=1", OP, route="/v1/orders")
        with self.api.lock:
            c.execute("UPDATE orders SET is_cancelled = 1, changed_at = ? WHERE id = ?",
                      (orders_api.iso(orders_api.dt.datetime.fromisoformat(p1["servedAt"].replace("Z", "+00:00"))
                                      - orders_api.dt.timedelta(microseconds=1)), ready[3]))
        self.api.t0 -= 11
        served, after = [p1["servedAt"]], p1["nextCursor"]
        while after:
            _, _, p = self.call("GET", f"/v1/orders?since={d['servedAt']}&limit=1&after={after}", OP, route="/v1/orders")
            served.append(p["servedAt"])
            after = p["nextCursor"]
        self.assertEqual(set(served), {p1["servedAt"]})
        _, _, ch = self.call("GET", f"/v1/orders?since={served[-1]}", OP, route="/v1/orders")
        self.assertIn(ready[3], [i["orderId"] for i in ch["items"]])

    def test_cancelled_at_is_null_when_unknown(self):
        """低（第 9 回）: トリガーを足す前に旧 API が取り消した行（時刻の記録が無い）は、cancelledAt を null で返す。
        あとで旧 API の決済の通知が同じ行を書いても、取消の日時がその時刻にすり替わらない"""
        c = self.api.conn
        self.assertEqual(self._legacy("old_cancel", "581093"), 1)
        with self.api.lock:
            c.execute("UPDATE orders SET cancelled_at = NULL, cancelled_by = NULL WHERE id = '581093'")  # トリガーの前の取り消しの写し
        self.assertEqual(self._legacy("old_pay", "581093"), 1)
        _, _, d = self.call("GET", "/v1/orders/581093", OP, route="/v1/orders/{orderId}")
        self.assertEqual((d["status"], d["cancelledAt"], d["cancelledBy"]), ("cancelled", None, None))

    def test_plan_hands_over_rls_owner_positional_readers_and_side_effects(self):
        """重大・高・中（第 9 回、読んで見つけた指摘）: 計画と権限の一覧が、次の 4 つを持つ。
        (1) RLS を有効にしても旧い書き手が 0 行にならない決め（全行の方針と CONNECT。roles.sql の前に流す確かめの SQL）。
        (2) 段 1〜3 を流す利用者が表の持ち主であること。(3) 列の数に頼る読み手と書き手の調べ。
        (4) 旧 API の取り消しと出荷の、列のほかの仕事（返金、在庫、知らせ、倉庫）の調べと、段 4 の門"""
        access = json.loads((HERE / "db-access.json").read_text(encoding="utf-8"))
        others = access["otherRoles"]
        for w in access["sinceOverlap"]["writers"]:
            if w not in ("orders_api", "migration"):
                self.assertEqual((w, others[w]["connect"], others[w]["rows"]), (w, True, "all"))
        pre = " ".join(orders_api.RLS_PREFLIGHT_PG.split())
        for want in ("pg_policy", "rolbypassrls", "relowner", "CONNECT", "RAISE EXCEPTION"):
            self.assertIn(want, pre)
        roles = (HERE.parent / "infra" / "db" / "roles.sql").read_text(encoding="utf-8")
        plan = (HERE.parent.parent / "skills" / "backend" / "examples" / "backend-plan-order-list.md").read_text(encoding="utf-8")
        handover = plan[plan.index("## 受け渡し"):]
        for w in others:
            if w not in roles:  # roles.sql が旧い書き手を知らないあいだは、インフラへの渡しに名前がある
                self.assertIn(w, handover)
        for step in orders_api.ADDITIONS:
            self.assertEqual((step["step"], step.get("runAs")), (step["step"], "owner"))
        for want in ("pg_has_role", "'^(pg_|rds)'", "pg_monitor"):  # 既定の役割と rds を除き、持ち主の一員を除く。CONNECT は表を使う利用者と監視を見る
            self.assertIn(want, pre)
        stage0 = plan[plan.index("段 0 では"):plan.index("### 版と段の表")]
        for want in ("SELECT *", "COPY", "位置", "返金", "在庫", "倉庫", "表の持ち主", "session_replication_role"):
            self.assertIn(want, stage0)

    # ---- 敵対的レビューの第 10 回の指摘（2026-11-07）と、第 11 回の決め（足した物は外さない。戻すのは新 API だけ）を結んだ試験
    def test_new_api_writes_only_rows_the_trigger_stamped(self):
        """低 6（第 10 回）と決め 1: 新 API は、書いた行をトリガーがその取引で印したか（stamped_xid が今の取引の番号か）を、
        書いたあとの読みで確かめる。印が無ければ全部を戻して 503（冪等キーも取らない）。門を通ったあとでトリガーが外されても、
        人と時刻の無い取り消しをコミットしない。戻しは新 API の書き込みを止めるだけで、止めたあいだも一覧と詳細は読める"""
        c = self.api.conn
        self._drop_feed()
        for op in ("cancel", "ship"):
            st, _, e = self.ship(["581950"], f"feed-off-{op}-01", op=op)
            self.assertEqual((op, st, e["error"]["code"]), (op, 503, "ORDER_WRITE_UNAVAILABLE"))
        self.assertEqual(tuple(c.execute("SELECT status, is_cancelled FROM orders WHERE id = '581950'").fetchone()), ("ready", 0))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM idempotency WHERE key LIKE 'feed-off-%'").fetchone()[0], 0)
        self.setUp()
        self.api.writes_enabled = False  # 戻し: 新 API の書き込みを止める（足した列とトリガーは残す）
        st, _, e = self.ship(["581950"], "writes-off-01", op="cancel")
        self.assertEqual((st, e["error"]["code"]), (503, "ORDER_WRITE_DISABLED"))  # 送り直しでなく、画面の読み直しを促す（第 12 回）
        self.assertEqual(self.call("GET", "/v1/orders?limit=1", OP, route="/v1/orders")[0], 200)
        self.api.writes_enabled = True
        self.assertEqual(self.ship(["581950"], "writes-off-01", op="cancel")[0], 200)  # 止めたあいだは冪等キーを取らないので、同じキーで送り直せる

    def test_same_key_race_keeps_the_key_hash_and_raises_no_error(self):
        """高 9 と低 14（第 10 回）: 同じ冪等キーの 2 本目は、主キーの重複の誤りを起こさず（ON CONFLICT DO NOTHING）、取引を戻さずに、
        鍵のハッシュを置いたままの取引で 1 本目の行を読み直す。RLS の下でも 0 行にならず、DB のログに冪等キーの値が出ない"""
        st, _, first = self.ship(["584216"], "race-key-0002")
        real_q, seen, hidden = self.api.q, [], []

        def q(sql, args=()):
            if "FROM idempotency" in sql:
                seen.append(self.api.settings.get("app.key_hash"))
                if not hidden:
                    hidden.append(1)
                    return []  # 先の行がまだ見えなかった
            return real_q(sql, args)
        self.api.q = q
        calls = self._capture()
        st2, hdr, again = self.ship(["584216"], "race-key-0002")
        self.assertEqual((st2, again, hdr.get("Idempotent-Replayed")), (st, first, "true"))
        self.assertEqual((len(seen), all(seen)), (2, True), "読み直しの取引に鍵のハッシュが無い（RLS の下で 0 行になる）")
        texts = [" ".join(s.split()).upper() for s, _ in calls]
        self.assertNotIn("ROLLBACK", texts)
        claim = [s for s in texts if s.startswith("INSERT INTO IDEMPOTENCY")]
        self.assertTrue(claim and all("ON CONFLICT DO NOTHING" in s for s in claim), claim)

    def test_served_at_is_read_before_the_read_snapshot(self):
        """中 4（第 10 回）: servedAt（DB の時計と、まだコミットしていない書き手の取引の始まりの早い方）は、読みの取引の写しが決まる前に、
        取引の外の文で読む。写しが決まった直後に長い取引がコミットしても、servedAt はその取引の始まりより前なので、行は次の since に入る"""
        real = self.api.conn
        start_dt = self.api.now() - orders_api.dt.timedelta(seconds=40)
        self.api.open_writers["legacy-slow"] = orders_api.iso(start_dt)

        class Conn:  # 読みの取引が始まった瞬間に、長い取引がコミットする（その行は、この読みの写しには見えない）
            def execute(s, sql, args=()):
                if sql.startswith("BEGIN"):
                    self.api.open_writers.pop("legacy-slow", None)
                return real.execute(sql, args)

            def __getattr__(s, k):
                return getattr(real, k)
        self.api.conn = Conn()
        self.addCleanup(setattr, self.api, "conn", real)
        _, _, d = self.call("GET", "/v1/orders?limit=1", OP, route="/v1/orders")
        self.api.conn = real
        self.assertLessEqual(d["servedAt"], orders_api.iso(start_dt))
        with self.api.lock:  # その取引が書いた行（changed_at は取引の中で書いた時刻）
            real.execute("UPDATE orders SET is_cancelled = 1, changed_at = ? WHERE id = '584230'",
                         (orders_api.iso(start_dt + orders_api.dt.timedelta(seconds=1)),))
        self.api.t0 -= 60
        _, _, ch = self.call("GET", f"/v1/orders?since={d['servedAt']}", OP, route="/v1/orders")
        self.assertIn("584230", [i["orderId"] for i in ch["items"]])

    def test_plan_keeps_added_objects_and_hands_cancel_after_ship_to_the_screen(self):
        """重大 1・8、中 7、高 3、中 12、低 16（第 10 回）と第 11 回の決め 1: 足した列・トリガー・索引は移行のあいだ外さない（戻しの文が無い）。
        版と段の表に「段を戻したあと」の列は無く、戻しは新 API の機能フラグと書き込みの停止だけ。出荷のあとの取り消しは
        cancelledAfterShip で画面に渡し、画面仕様と実装計画が受け持つまで段 4 に進まない。orders_write_horizon の定義は roles.sql の 1 つだけ。
        文書の中の数（一覧の SQL の数、穴を入れた写しの数）が食い違わない"""
        import re
        plan = (HERE.parent.parent / "skills" / "backend" / "examples" / "backend-plan-order-list.md").read_text(encoding="utf-8")
        for step in orders_api.ADDITIONS:
            self.assertFalse(step.get("back_pg"), f"段 {step['step']} に外す文がある")
            self.assertIn("外さない", step["back"])
        vt = plan[plan.index("### 版と段の表"):]
        vt = vt[:vt.index("\n### ", 5)]
        head = next(line for line in vt.splitlines() if line.startswith("| 版"))
        self.assertNotIn("を戻したあと（トリガー無し）", head)
        self.assertIn("書き込みを止めた", head)
        for who in ("| フロントエンド |", "| デザイナー |"):
            row = next(line for line in plan[plan.index("## 受け渡し"):].splitlines() if line.startswith(who))
            self.assertIn("cancelledAfterShip", row, who)
        undecided = plan[plan.index("## 未確定"):plan.index("## 受け渡し")]
        self.assertRegex(undecided, r"cancelledAfterShip[^\n]*段 4")
        self.assertFalse(hasattr(orders_api, "WRITE_HORIZON_PG"))
        self.assertIn("samples/infra/db/roles.sql", plan[plan.index("orders_write_horizon"):][:400])
        goal = re.search(r"\| 一覧の SQL の数 \|[^|]*\| 件数によらず (\d+) 回", plan).group(1)
        table = re.search(r"\| `GET /v1/orders` \| (\d+) \|", plan).group(1)
        summary = re.search(r"一覧の SQL は件数によらず (\d+) 回", plan).group(1)
        self.assertEqual({goal, table, summary}, {table})
        holes = set(re.findall(r"穴を入れた写し(?:は)? ?(\d+) ?つ", plan))
        self.assertEqual(len(holes), 1, holes)
        for gone in ("DROP COLUMN", "DROP TRIGGER", "段 2 を戻したあと", "段 5"):
            self.assertNotIn(gone, plan)

    @unittest.skipUnless(pg_ready(), "手元の PostgreSQL の容器が無い")
    def test_pg_added_objects_never_change_legacy_writers(self):
        """高 2・中 10（第 10 回）と決め 2: 足した物（列、表、トリガー、索引）がある PostgreSQL で、旧 API の書き手 12 手を流す。
        列の型（時刻が文字か timestamptz か、等しさの演算子の無い json と point の列、boolean の印）によらず、どの文も断られず、
        書けた行の数と旧い列の値と定義が、足す前の DB と同じになる"""
        for variant in ("text", "tstz", "odd", "bool"):
            schema, sql = pg_legacy(variant)
            base = pg_db(f"be11_base_{variant}")
            pg(schema, base)
            want = pg_legacy_run(base, sql)
            db = pg_db(f"be11_add_{variant}")
            pg(schema, db)
            pg(pg_additions(), db)
            got = pg_legacy_run(db, sql)
            pg(f"DROP DATABASE {base} WITH (FORCE);\nDROP DATABASE {db} WITH (FORCE);")
            self.assertEqual((variant, got), (variant, want))

    @unittest.skipUnless(pg_ready(), "手元の PostgreSQL の容器が無い")
    def test_pg_who_cancelled_is_returned_only_when_the_trigger_saw_the_mark(self):
        """重大 1・8（第 10 回）、中 4・高 7（第 12 回）と決め 3: 取り消しの人と時刻は、正の印が立った取引でトリガーが書いた値を返す。
        セーブポイントの中の書き込み（ORM の入れ子、ドライバーの autosave）と pg_dump からの復元のあとも消えない。replica の取り込みが
        印を戻して立て直したら、前の人と時刻を返さず、立て直した取引の時刻と null の人にする（トリガーは ENABLE ALWAYS）。
        トリガーを止めた（DISABLE TRIGGER）取引では、新 API が書いた行の印（stamped_xid）の無さを見分ける"""
        db = pg_db("be12_who")
        schema, _ = pg_legacy("tstz")
        pg(schema + pg_additions(), db)

        def read(tag, oid="100004"):
            return (f"SELECT 'R:{tag}=' || coalesce(o.cancelled_by, 'null') || ',' || (o.cancelled_at IS NOT NULL) || ','"
                    f" || coalesce(to_char(o.cancelled_at, 'HH24:MI:SS.US'), '-') FROM orders o WHERE o.id = '{oid}';\n")
        new_cancel = ("BEGIN;\nSELECT set_config('app.key_hash', 'h-a', true);\nUPDATE orders SET is_cancelled = 1 WHERE id = '{oid}'"
                      " AND status IN ('action','ready','pending') AND is_cancelled = 0;\n")
        script = ("INSERT INTO sessions VALUES ('h-a', 'u-sakaguchi', now() + interval '1 hour');\n"
                  + new_cancel.format(oid="100004") + "COMMIT;\n" + read("new")
                  + "UPDATE orders SET note = 'n1' WHERE id = '100004';\n" + read("carry")
                  # 旧 API の決済の通知を、セーブポイントの中で流す（ORM の入れ子の取引の形）。そのあとセーブポイントの無い書き込み
                  + "BEGIN;\nSAVEPOINT s1;\nUPDATE orders SET status = 'ready' WHERE id = '100004' AND status = 'pending';\nRELEASE s1;\nCOMMIT;\n"
                  + read("savepoint") + "UPDATE orders SET note = 'n2' WHERE id = '100004';\n" + read("after_savepoint")
                  # 新 API の取り消しそのものをセーブポイントの中で流す
                  + "BEGIN;\nSELECT set_config('app.key_hash', 'h-a', true);\nSAVEPOINT s2;\nUPDATE orders SET is_cancelled = 1 WHERE id = '100005'"
                  " AND status IN ('action','ready','pending') AND is_cancelled = 0;\nRELEASE s2;\n"
                  f"SELECT 'R:stamped_in_savepoint=' || ({orders_api.STAMPED_PG}) FROM orders o WHERE o.id = '100005';\nCOMMIT;\n"
                  + "UPDATE orders SET note = 'n3' WHERE id = '100005';\n" + read("savepoint_cancel", "100005")
                  # replica の取り込みが印を戻して立て直す
                  + "SET session_replication_role = replica;\n"
                  "UPDATE orders SET is_cancelled = 0 WHERE id = '100004' AND is_cancelled = 1;\n" + read("replica_down")
                  + "UPDATE orders SET is_cancelled = 1 WHERE id = '100004' AND is_cancelled = 0;\n"
                  "RESET session_replication_role;\n" + read("replica_up")
                  + "UPDATE orders SET note = 'n4' WHERE id = '100004';\n" + read("after_replica")
                  + "SELECT 'R:tgenabled=' || tgenabled::text FROM pg_trigger WHERE tgname = 'orders_before_write';\n"
                  # トリガーを止めた取引の新 API の書き込み。印が無いので、新 API は 503 にして戻す
                  "BEGIN;\nALTER TABLE orders DISABLE TRIGGER orders_before_write;\nSELECT set_config('app.key_hash', 'h-a', true);\n"
                  "UPDATE orders SET status = 'shipped' WHERE id = '100002' AND status = 'ready' AND is_cancelled = 0;\n"
                  f"SELECT 'R:unstamped=' || coalesce(({orders_api.STAMPED_PG})::text, 'null') FROM orders o WHERE o.id = '100002';\nROLLBACK;\n")
        out = pg(script, db)[1]
        # 表の写し直し: pg_dump で別の DB に移し、移した先で 1 回書く
        dst = pg_db("be12_who_dst")
        dump = subprocess.run(["docker", "exec", PG_CONTAINER, "pg_dump", "-U", "postgres", db], capture_output=True, text=True, timeout=120)
        self.assertEqual(dump.returncode, 0, dump.stderr[-400:])
        pg(dump.stdout, dst)
        restored = pg(read("restored", "100005") + "UPDATE orders SET note = 'n5' WHERE id = '100005';\n" + read("restored_write", "100005"), dst)[1]
        pg(f"DROP DATABASE {db} WITH (FORCE);\nDROP DATABASE {dst} WITH (FORCE);")
        who = lambda k: out[k].rsplit(",", 1)[0]  # noqa: E731 — 人と、時刻の有無
        self.assertEqual(who("new"), "u-sakaguchi,true")
        self.assertEqual(out["carry"], out["new"])  # 印を変えない書き込みは、印を立てた取引の値を引き継ぐ
        self.assertEqual((out["savepoint"], out["after_savepoint"]), (out["new"], out["new"]))  # セーブポイントの中の書き込みでも消えない
        self.assertEqual(out["stamped_in_savepoint"], "true")
        self.assertEqual(who("savepoint_cancel"), "u-sakaguchi,true")
        self.assertEqual(who("replica_down"), "null,false")  # replica の取り込みでもトリガーが動き、戻した印の人と時刻を消す
        self.assertEqual(who("replica_up"), "null,true")  # 立て直した取引の時刻で、人は分からないので null。前の人を返さない
        self.assertNotEqual(out["replica_up"], out["new"])
        self.assertEqual(out["after_replica"], out["replica_up"])
        self.assertEqual(out["tgenabled"], "A")
        self.assertIn(out["unstamped"], ("false", "null"))  # 新 API はこれを見て 503 にし、取引を戻す
        self.assertEqual((restored["restored"], restored["restored_write"]), (out["savepoint_cancel"], out["savepoint_cancel"]))

    @unittest.skipUnless(pg_ready(), "手元の PostgreSQL の容器が無い")
    def test_pg_rls_preflight_passes_built_in_roles_and_owner_members(self):
        """中 5・低 13（第 10 回）: RLS の前の確かめは、全表を読み書きできる既定の役割（pg_read_all_data など）と rds の役割、
        表の持ち主の一員（RLS を受けない）では止まらない。全行の方針の無い旧い書き手、既定の役割を付けた利用者（バックアップ）、
        orders を読まないが CONNECT を PUBLIC から得ている監視の利用者では止まる"""
        db = pg_db("be11_pre")
        schema, _ = pg_legacy("tstz")
        tables = ("orders", "order_items", "order_events", "customers", "users", "sessions", "idempotency")
        roles = ("be11_mon", "be11_backup", "be11_mig", "be11_legacy", "be11_owner")
        pg("".join(f"DROP ROLE IF EXISTS {r};\n" for r in roles) + "CREATE ROLE be11_owner NOLOGIN;\nCREATE ROLE be11_legacy LOGIN;\n"
           "CREATE ROLE be11_mig LOGIN IN ROLE be11_owner;\n")
        pg(schema + pg_additions() + "".join(f"ALTER TABLE {t} OWNER TO be11_owner;\nGRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO be11_legacy;\n"
                                             f"CREATE POLICY other_roles_all ON {t} FOR ALL TO be11_legacy USING (true) WITH CHECK (true);\n"
                                             for t in tables)
           + f"GRANT CONNECT ON DATABASE {db} TO be11_legacy, be11_mig;\n", db)
        pre = orders_api.RLS_PREFLIGHT_PG + ";\n"
        results = {"ok": pg(pre, db, check=False)}
        pg("CREATE ROLE be11_backup LOGIN IN ROLE pg_read_all_data;\n", db)
        results["backup"] = pg(pre, db, check=False)
        pg(f"ALTER ROLE be11_backup BYPASSRLS;\nGRANT CONNECT ON DATABASE {db} TO be11_backup;\nCREATE ROLE be11_mon LOGIN IN ROLE pg_monitor;\n", db)
        results["monitor"] = pg(pre, db, check=False)
        pg(f"GRANT CONNECT ON DATABASE {db} TO be11_mon;\nDROP POLICY other_roles_all ON order_items;\n", db)
        results["policy"] = pg(pre, db, check=False)
        pg(f"DROP DATABASE {db} WITH (FORCE);\n" + "".join(f"DROP ROLE IF EXISTS {r};\n" for r in roles))
        self.assertEqual(results["ok"][0], 0, results["ok"][2])
        self.assertIn("be11_backup", results["backup"][2])
        self.assertIn("be11_mon", results["monitor"][2])
        self.assertIn("be11_legacy uses table order_items", results["policy"][2])

    @unittest.skipUnless(pg_ready(), "手元の PostgreSQL の容器が無い")
    def test_pg_same_key_race_under_rls_replays_without_an_error(self):
        """高 9・低 14（第 10 回）: 本番の RLS（idempotency は鍵のハッシュから引いた店で絞る）の下で、同じ冪等キーの 2 本が重なる。
        2 本目は 1 本目のコミットを待ち、誤りを出さずに 0 行を返し、同じ取引のまま 1 本目の行を読める（DB のログに重複の誤りが出ない）"""
        self.assertIn("ON CONFLICT DO NOTHING", orders_api.CLAIM_SQL)
        db = pg_db("be11_race")
        pg("DROP ROLE IF EXISTS be11_api;\nCREATE ROLE be11_api NOLOGIN;\n")
        pg(orders_api.LEGACY_SCHEMA + PG_SEED + pg_additions()
           + "INSERT INTO sessions VALUES ('h-a', 'u-sakaguchi', now() + interval '1 hour');\n"
           "CREATE FUNCTION app_key_shop() RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS"
           " $f$ SELECT u.shop_id::text FROM public.sessions s JOIN public.users u ON u.id = s.user_id"
           " WHERE s.token_sha256 = current_setting('app.key_hash', true) $f$;\n"
           "ALTER TABLE idempotency ENABLE ROW LEVEL SECURITY;\n"
           "CREATE POLICY shop_isolation ON idempotency FOR ALL TO be11_api USING (shop_id::text = app_key_shop());\n"
           "GRANT SELECT, INSERT, UPDATE ON idempotency TO be11_api;\n", db)
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1))
        claim_sql = orders_api.CLAIM_SQL.replace("?", "{}").format("'s1'", "'u-sakaguchi'", "'k-race-be11'", "'d1'", "now()")
        claim = ("SET ROLE be11_api;\nBEGIN;\nSELECT set_config('app.key_hash', 'h-a', true);\n"  # 見本の CLAIM_SQL をそのまま流す
                 f"WITH x AS ({claim_sql}) SELECT 'R:claimed=' || count(*) FROM x;\n")
        first = subprocess.Popen(["docker", "exec", "-i", PG_CONTAINER, "psql", "-X", "-q", "-A", "-t", "-U", "postgres", "-d", db,
                                  "-v", "ON_ERROR_STOP=1"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        first.stdin.write(claim + "SELECT pg_sleep(2);\nCOMMIT;\n")
        first.stdin.close()
        time.sleep(0.8)
        t0 = time.monotonic()
        _, second, err = pg(claim + "SELECT 'R:seen=' || count(*) FROM idempotency WHERE key = 'k-race-be11';\nCOMMIT;\n", db, check=False)
        waited = time.monotonic() - t0
        first_out = first.stdout.read()
        first.wait(timeout=60)
        logs = subprocess.run(["docker", "logs", "--since", since, PG_CONTAINER], capture_output=True, text=True, timeout=30)
        pg(f"DROP DATABASE {db} WITH (FORCE);\nDROP ROLE IF EXISTS be11_api;\n")
        self.assertIn("R:claimed=1", first_out)
        self.assertEqual((second, err.strip()), ({"claimed": "0", "seen": "1"}, ""))
        self.assertGreater(waited, 0.5)  # 2 本目は 1 本目のコミットを待った
        self.assertNotIn("k-race-be11", logs.stdout + logs.stderr)

    @unittest.skipUnless(pg_ready(), "手元の PostgreSQL の容器が無い")
    def test_pg_users_policy_by_shop_keeps_the_list_fast(self):
        """高 15（第 10 回）: users の行の制限を、注文の 3 列からの EXISTS（索引の無い列を行ごとになめる）でなく、店の列にする。
        過去の行 300,000 と今日の 400 行、店の外の利用者 51 人で、一覧と同じ形の文（users を 3 回結ぶ）が RLS の下でも速い"""
        db = pg_db("be11_users")
        pg("DROP ROLE IF EXISTS be11_api;\nCREATE ROLE be11_api NOLOGIN;\n")
        schema, _ = pg_legacy("tstz", seed=False)
        pg(schema + "INSERT INTO shops VALUES ('s1', 'a'), ('s2', 'b');\n"
           "INSERT INTO users SELECT 'u1-' || g, 's1', '利用者', 'operator' FROM generate_series(1, 33) g;\n"
           "INSERT INTO users SELECT 'u2-' || g, 's2', '利用者', 'operator' FROM generate_series(1, 51) g;\n"
           "INSERT INTO customers VALUES (1, 's1', '架空 顧客', NULL, NULL);\n"
           "INSERT INTO orders (id, shop_id, customer_id, status, amount_yen, carrier, payment, staff_id, ordered_at, ship_due, shipped_by, shipped_at)"
           " SELECT (100000 + g)::text, 's1', 1, 'delivered', 1000, 'yamato', 'card', 'u1-' || (g % 33 + 1), now() - interval '60 days',"
           " current_date - 60, 'u1-' || (g % 33 + 1), now() - interval '59 days' FROM generate_series(1, 300000) g;\n"
           "INSERT INTO orders (id, shop_id, customer_id, status, amount_yen, carrier, payment, staff_id, ordered_at, ship_due)"
           " SELECT (900000 + g)::text, 's1', 1, 'ready', 1000, 'yamato', 'card', 'u1-' || (g % 33 + 1), now() - interval '1 hour', current_date"
           " FROM generate_series(1, 400) g;\n" + pg_additions()
           + "INSERT INTO sessions VALUES ('h-a', 'u1-1', now() + interval '1 hour');\nANALYZE;\n"
           "CREATE FUNCTION app_key_shop() RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS"
           " $f$ SELECT u.shop_id::text FROM public.sessions s JOIN public.users u ON u.id = s.user_id"
           " WHERE s.token_sha256 = current_setting('app.key_hash', true) $f$;\n"
           "ALTER TABLE orders ENABLE ROW LEVEL SECURITY;\nALTER TABLE users ENABLE ROW LEVEL SECURITY;\nALTER TABLE customers ENABLE ROW LEVEL SECURITY;\n"
           "CREATE POLICY shop_isolation ON orders FOR ALL TO be11_api USING (shop_id::text = app_key_shop());\n"
           "CREATE POLICY shop_isolation ON customers FOR ALL TO be11_api USING (shop_id::text = app_key_shop());\n"
           f"CREATE POLICY shop_isolation ON users FOR ALL TO be11_api USING ({orders_api.USERS_POLICY_PG});\n"
           "GRANT SELECT ON orders, users, customers, sessions TO be11_api;\n"
           "CREATE FUNCTION be11_ms(q text) RETURNS float LANGUAGE plpgsql AS $f$ DECLARE j json; BEGIN"
           " EXECUTE 'EXPLAIN (ANALYZE, FORMAT JSON) ' || q INTO j; RETURN (j -> 0 ->> 'Execution Time')::float; END $f$;\n", db)
        q = ("SELECT o.id, s.name, sb.name, cb.name FROM orders o JOIN customers c ON c.id = o.customer_id"
             " LEFT JOIN users s ON s.id = o.staff_id LEFT JOIN users sb ON sb.id = o.shipped_by LEFT JOIN users cb ON cb.id = o.cancelled_by"
             " WHERE o.shop_id = 's1' AND o.status IN ('action','ready','pending') AND o.is_cancelled = 0 AND o.ship_due <= to_char(current_date, 'YYYY-MM-DD')"
             " ORDER BY o.ordered_at, o.id LIMIT 101")

        def measure():
            return pg("SET ROLE be11_api;\nBEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\nSELECT set_config('app.key_hash', 'h-a', true);\n"
                      f"SELECT 'R:rows=' || count(*) FROM ({q}) x;\n"
                      + "".join(f"SELECT 'R:ms{k}=' || be11_ms($q${q}$q$);\n" for k in range(3)) + "COMMIT;\n", db, check=False)
        new = measure()
        pg("DROP POLICY shop_isolation ON users;\nCREATE POLICY key_only ON users FOR ALL TO be11_api USING (EXISTS (SELECT 1 FROM sessions s"
           " WHERE s.user_id = users.id) OR EXISTS (SELECT 1 FROM orders o WHERE o.staff_id = users.id OR o.shipped_by = users.id"
           " OR o.cancelled_by = users.id));\n", db)  # 審査の指摘の形（注文の 3 列からの EXISTS）。比べのために測る
        old = measure()
        pg(f"DROP DATABASE {db} WITH (FORCE);\nDROP ROLE IF EXISTS be11_api;\n")
        self.assertEqual((new[0], old[0]), (0, 0), new[2] + old[2])
        self.assertEqual((new[1]["rows"], old[1]["rows"]), ("101", "101"))
        ms = {k: sorted(float(r[1][f"ms{i}"]) for i in range(3)) for k, r in (("店の列", new), ("注文の 3 列", old))}
        print("MEASURE 一覧の文の実行時間（RLS の下、3 回）: " + "、".join(f"{k} {', '.join(f'{m:.2f}' for m in v)} ms" for k, v in ms.items()),
              file=sys.stderr)
        self.assertLess(ms["店の列"][1], 50.0)

    @unittest.skipUnless(pg_ready(), "手元の PostgreSQL の容器が無い")
    def test_pg_index_build_waits_for_long_old_writers(self):
        """中 11（第 10 回）: 段 1 の lock_timeout は取引の中だけ（SET LOCAL）で、段 3 の索引作りは lock_timeout を 0 に戻してから流す。
        2 秒を超える旧 API の取引があっても、索引作りは打ち切られず、終わるのを待って INVALID を残さない"""
        import re
        db = pg_db("be11_cic")
        schema, _ = pg_legacy("tstz")
        steps = {s["step"]: "".join(x + ";\n" for x in s["pg"]) for s in orders_api.ADDITIONS}
        pg(schema + steps["1"] + steps["2"], db)
        names = re.findall(r"CONCURRENTLY (\w+) ON", steps["3"])
        slow = subprocess.Popen(["docker", "exec", "-i", PG_CONTAINER, "psql", "-X", "-q", "-U", "postgres", "-d", db],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        slow.stdin.write("BEGIN;\nUPDATE orders SET note = 'slow' WHERE id = '100001';\nSELECT pg_sleep(4);\nCOMMIT;\n")
        slow.stdin.close()
        time.sleep(0.8)
        rc, out, err = pg("SET lock_timeout = '2s';\n" + steps["3"]  # 前の段の文が同じセッションに 2 秒を残した場合も
                          + "SELECT 'R:valid=' || string_agg(c.relname || ':' || i.indisvalid, ',' ORDER BY c.relname) FROM pg_index i"
                          f" JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname IN ({', '.join(repr(n) for n in names)});\n", db, check=False)
        slow.wait(timeout=60)
        pg(f"DROP DATABASE {db} WITH (FORCE);")
        self.assertEqual(rc, 0, err)
        self.assertEqual((len(names), out["valid"].count(":true")), (5, 5), out["valid"])


    # ---- 敵対的レビューの第 12 回の指摘（2026-11-07）を結んだ試験
    @unittest.skipUnless(pg_ready(), "手元の PostgreSQL の容器が無い")
    def test_pg_rls_preflight_catches_column_privilege_writers(self):
        """重大（第 12 回）: 列の単位でしか権限を持たない旧い書き手（GRANT UPDATE (is_cancelled) ON orders）も、全行の方針が無ければ
        確かめで止まる。CONNECT の確かめからも漏れない。止めずに RLS を有効にすると、その取り消しは黙って 0 行になる（その形も確かめる）"""
        db = pg_db("be12_colpriv")
        schema, _ = pg_legacy("tstz")
        roles = ("be12_cancel", "be12_api")
        pg("".join(f"DROP ROLE IF EXISTS {r};\n" for r in roles) + "CREATE ROLE be12_cancel LOGIN;\nCREATE ROLE be12_api NOLOGIN;\n")
        pg(schema + pg_additions() + "GRANT SELECT (id, status, is_cancelled), UPDATE (is_cancelled) ON orders TO be12_cancel;\n"
           f"GRANT CONNECT ON DATABASE {db} TO be12_cancel;\n", db)
        pre = orders_api.RLS_PREFLIGHT_PG + ";\n"
        first = pg(pre, db, check=False)
        pg("CREATE POLICY other_roles_all ON orders FOR ALL TO be12_cancel USING (true) WITH CHECK (true);\n"
           f"REVOKE CONNECT ON DATABASE {db} FROM be12_cancel;\n", db)
        second = pg(pre, db, check=False)
        pg(f"GRANT CONNECT ON DATABASE {db} TO be12_cancel;\n", db)
        third = pg(pre, db, check=False)
        # 確かめを通さずに RLS を有効にした形（方針を外す）。列の権限の書き手の取り消しが、エラーなしで 0 行になる
        silent = pg("DROP POLICY other_roles_all ON orders;\nALTER TABLE orders ENABLE ROW LEVEL SECURITY;\n"
                    "CREATE POLICY shop_isolation ON orders FOR ALL TO be12_api USING (shop_id = 's1');\nSET ROLE be12_cancel;\n"
                    "WITH x AS (UPDATE orders SET is_cancelled = 1 WHERE id = '100002' AND is_cancelled = 0 RETURNING 1)"
                    " SELECT 'R:n=' || count(*) FROM x;\n", db, check=False)
        pg(f"DROP DATABASE {db} WITH (FORCE);\n" + "".join(f"DROP ROLE IF EXISTS {r};\n" for r in roles))
        self.assertIn("be12_cancel uses table orders", first[2])
        self.assertIn("role be12_cancel uses this database but has no explicit CONNECT", second[2])
        self.assertEqual(third[0], 0, third[2])
        self.assertEqual((silent[0], silent[1].get("n")), (0, "0"))

    def test_cancel_after_ship_on_an_earlier_day_reaches_the_screen(self):
        """高（第 12 回）: 前の日（と 5 日前）に出荷指示した行に、今日になって旧 API の取り消しが印を立てる。since に出て、行は今日出荷と
        済のビューに入り（inViews）、済のビューの一覧と件数にも残る。cancelledAfterShip が true。前の日の済の行は、印が無ければ済のビューに入らない"""
        c = self.api.conn
        rows = {"581950": "2026-11-05T14:00:00.000000Z", "582787": "2026-11-01T08:00:00.000000Z"}  # 前の日の 23:00 と、5 日前（日本時間）
        with self.api.lock:
            for oid, at in rows.items():
                c.execute("UPDATE orders SET status = 'shipped', shipped_by = 'u-takagi', shipped_at = ?, ship_due = '2026-11-05' WHERE id = ?", (at, oid))
                c.execute("UPDATE orders SET changed_at = ? WHERE id = ?", (at, oid))
        _, _, v0 = self.call("GET", "/v1/orders?view=shipped&limit=100", OP, route="/v1/orders")
        self.assertFalse(set(rows) & {i["orderId"] for i in v0["items"]})
        self.api.t0 -= 60
        _, _, d0 = self.call("GET", "/v1/orders?limit=1", OP, route="/v1/orders")
        self.api.t0 -= 60
        for oid in rows:
            self.assertEqual(self._legacy("old_cancel", oid), 1)
        self.api.t0 -= 1
        _, _, ch = self.call("GET", f"/v1/orders?since={d0['servedAt']}", OP, route="/v1/orders")
        got = {i["orderId"]: i for i in ch["items"]}
        for oid in rows:
            self.assertIn(oid, got, "前の日の出荷のあとの取り消しが since に出ない")
            self.assertEqual((got[oid]["status"], got[oid]["cancelledAfterShip"]), ("shipped", True))
            self.assertIn("shipped", got[oid]["inViews"])
            self.assertIn("today", got[oid]["inViews"])
        _, _, v1 = self.call("GET", "/v1/orders?view=shipped&limit=100", OP, route="/v1/orders")
        self.assertTrue(set(rows) <= {i["orderId"] for i in v1["items"] if i["cancelledAfterShip"]})
        self.assertEqual((v1["total"], v1["viewCounts"]["shipped"]), (v0["total"] + 2, v0["viewCounts"]["shipped"] + 2))
        _, _, t1 = self.call("GET", "/v1/orders?view=today&limit=100", OP, route="/v1/orders")
        self.assertTrue(set(rows) <= {i["orderId"] for i in t1["items"]})

    def test_rollback_sends_the_screen_back_and_plan_keeps_the_old_screen(self):
        """高（第 12 回）: 新 API の書き込みを止めた戻しのあいだは、ORDER_WRITE_DISABLED で画面の読み直しを促す（送り直しでは通らない）。
        計画は、機能フラグ admin_orders_v2 と旧画面を、新 API の戻しが要るあいだ消さない決めを持ち、12-25 の削除と食い違いを未確定にする"""
        self.api.writes_enabled = False
        st, _, e = self.ship(["581950"], "rollback-key-01", op="cancel")
        self.assertEqual((st, e["error"]["code"]), (503, "ORDER_WRITE_DISABLED"))
        self.assertIn("読み込み直して", e["error"]["action"])
        self.assertNotEqual(e["error"]["action"], orders_api.ERRORS["ORDER_WRITE_UNAVAILABLE"][3])
        plan = (HERE.parent.parent / "skills" / "backend" / "examples" / "backend-plan-order-list.md").read_text(encoding="utf-8")
        undecided = plan[plan.index("## 未確定"):plan.index("## 受け渡し")]
        self.assertRegex(undecided, r"admin_orders_v2[^\n]*12-25[^\n]*段 4")
        vt = plan[plan.index("### 版と段の表"):]
        self.assertIn("旧画面", vt[:vt.index("\n### ", 5)])
        self.assertIn("ORDER_WRITE_DISABLED", plan[plan.index("## エラー"):plan.index("## データと移行")])

    def test_write_does_not_purge_other_keys_in_its_transaction(self):
        """中（第 12 回）: 書き込みの取引は、その店の期限切れの冪等キーを消さない（消した行の鍵で、同じ店の関係の無い書き込みを並ばせない）"""
        with self.api.lock:
            self.api.conn.execute("INSERT INTO idempotency VALUES ('s1', 'u-mori', 'stale-key-0001', 'x', 200, '{}', '2026-11-05T00:00:00.000000Z')")
        calls = self._capture()
        self.assertEqual(self.ship(["584216"], "purge-key-0001")[0], 200)
        self.assertEqual([s for s, _ in calls if "DELETE" in s.upper()], [])
        with self.api.lock:  # 期限の切れた自分の同じキーは、その 1 行だけを消して取り直す（店のほかのキーは消さない）
            self.api.conn.execute("UPDATE idempotency SET created_at = '2026-11-05T00:00:00.000000Z' WHERE key = 'purge-key-0001'")
        calls.clear()
        st, hdr, d = self.ship(["584230"], "purge-key-0001")
        self.assertEqual((st, hdr.get("Idempotent-Replayed")), (200, None))
        dels = [a[:3] for s, a in calls if s.upper().startswith("DELETE")]
        self.assertEqual(dels, [("s1", "u-takagi", "purge-key-0001")])
        self.assertEqual(self.api.conn.execute("SELECT COUNT(*) FROM idempotency WHERE key = 'stale-key-0001'").fetchone()[0], 1)

    @unittest.skipUnless(pg_ready(), "手元の PostgreSQL の容器が無い")
    def test_pg_claim_does_not_wait_on_other_writers_of_the_shop(self):
        """中（第 12 回）: 同じ店の 1 本目の書き込みが行の鍵で止まっていても、2 本目の冪等キーの取り（CLAIM_SQL）は待たない。
        期限切れのキーが残っていても、取引の中で消さないので、消した行の鍵を待たない"""
        db = pg_db("be12_claim")
        pg(orders_api.LEGACY_SCHEMA + PG_SEED + pg_additions()
           + "INSERT INTO idempotency VALUES ('s1', 'u-sakaguchi', 'k-stale', 'x', 200, '{}', now() - interval '24 hours 1 minute');\n", db)

        def claim(key):
            return orders_api.CLAIM_SQL.replace("?", "{}").format("'s1'", "'u-sakaguchi'", f"'{key}'", "'d'", "now()")
        reclaim = orders_api.RECLAIM_SQL.replace("?", "{}").format("'s1'", "'u-sakaguchi'", "'k-stale'", "now() - interval '24 hours'")
        first = subprocess.Popen(["docker", "exec", "-i", PG_CONTAINER, "psql", "-X", "-q", "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1"],
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        first.stdin.write(f"BEGIN;\n{claim('k-first')};\nSELECT pg_sleep(3);\nCOMMIT;\n")
        first.stdin.close()
        time.sleep(0.8)
        rc, out, err = pg(f"SET statement_timeout = '1s';\nBEGIN;\nWITH x AS ({claim('k-second')}) SELECT 'R:second=' || count(*) FROM x;\n"
                          f"{reclaim};\nWITH x AS ({claim('k-stale')}) SELECT 'R:stale=' || count(*) FROM x;\nCOMMIT;\n", db, check=False)
        first.wait(timeout=60)
        pg(f"DROP DATABASE {db} WITH (FORCE);")
        self.assertEqual((rc, out), (0, {"second": "1", "stale": "1"}), err)  # 期限切れの同じキーは、その 1 行だけを取り直す

    @unittest.skipUnless(pg_ready(), "手元の PostgreSQL の容器が無い")
    def test_pg_old_settled_rows_do_not_flood_since_for_any_time_type(self):
        """高・低（第 12 回）: 出荷の時刻の型が timestamp（時差なし）でも、時差の無い字でも、timestamptz を DateStyle SQL で書く
        セッションでも、20 日前に出荷した済の行の一括は changed_at を進めない。印の立て下ろしは、何日前の出荷でも進める"""
        got = {}
        for variant in ("timestamp", "text_naive", "tstz_sql_style", "tstz"):
            schema, _ = pg_legacy("tstz", seed=False)
            if variant == "timestamp":
                schema = schema.replace("shipped_at timestamptz", "shipped_at timestamp")
            if variant == "text_naive":
                schema = schema.replace("shipped_at timestamptz", "shipped_at text")
            at = "to_char(now() - interval '20 days', 'YYYY-MM-DD HH24:MI:SS')" if variant == "text_naive" else "now() - interval '20 days'"
            style = "SET DateStyle = 'SQL, DMY';\n" if variant == "tstz_sql_style" else ""
            db = pg_db(f"be12_settled_{variant}")
            pg(schema + "INSERT INTO shops VALUES ('s1', 'a');\nINSERT INTO customers VALUES (1, 's1', '架空 顧客', NULL, NULL);\n"
               + pg_additions(), db)
            out = pg(style + "INSERT INTO orders (id, shop_id, customer_id, status, amount_yen, carrier, payment, ordered_at, ship_due, shipped_at)"
                     f" SELECT (500000 + g)::text, 's1', 1, 'shipped', 1000, 'yamato', 'card', now() - interval '21 days', '2026-10-01', {at}"
                     " FROM generate_series(1, 2000) g;\n"
                     "SELECT 'R:inserted=' || count(changed_at) FROM orders;\n"
                     "UPDATE orders SET status = 'delivered' WHERE status = 'shipped';\n"
                     "SELECT 'R:bulk=' || count(changed_at) FROM orders;\n"
                     "UPDATE orders SET is_cancelled = 1 WHERE id = '500001';\n"
                     "SELECT 'R:flip=' || count(changed_at) FROM orders;\n", db)[1]
            pg(f"DROP DATABASE {db} WITH (FORCE);")
            got[variant] = out
        self.assertEqual(got, {v: {"inserted": "0", "bulk": "0", "flip": "1"} for v in got})

    def test_write_cut_by_the_deadline_is_503_not_500(self):
        """中（第 12 回）: 書き込みが打ち切りで止まったら、何も書かずに戻したので 503 の ORDER_WRITE_UNAVAILABLE（同じキーで送り直せる）。
        500 の ORDER_WRITE_INTERNAL（お問い合わせ）にしない"""
        api = orders_api.make_api(2000, log=io.StringIO(), deadline_s=0.0005)
        hdr = {"Authorization": "Bearer " + api.token_for("u-takagi")}
        ids = [r[0] for r in api.conn.execute("SELECT id FROM orders WHERE shop_id = 's1' AND status = 'ready' AND is_cancelled = 0 LIMIT 50")]
        codes = []
        for k in range(5):
            st, _, out = api.handle("POST", "/v1/orders/ship", dict(hdr, **{"Idempotency-Key": f"deadline-key-{k:04d}"}),
                                    json.dumps({"orderIds": ids}).encode())
            codes.append((st, json.loads(out).get("error", {}).get("code")))
        self.assertNotIn((500, "ORDER_WRITE_INTERNAL"), codes)
        self.assertTrue(any(c == (503, "ORDER_WRITE_UNAVAILABLE") for c in codes), codes)

    def test_inflight_limit_counts_per_user_not_per_token(self):
        """中（第 12 回）: 同時の要求の上限は利用者ごとに数える。同じ人が端末ごとに鍵を何本発行しても、8 本を超えた要求は 503。ほかの人は通る"""
        tokens = [self.api.login("u-kobayashi") for _ in range(3)]
        self.api.inflight["u-kobayashi"] = orders_api.PER_KEY_INFLIGHT
        for t in tokens + [VIEWER["Authorization"].split()[1]]:
            st, _, out = self.api.handle("GET", "/v1/orders", {"Authorization": "Bearer " + t})
            self.assertEqual((st, json.loads(out)["error"]["code"]), (503, "ORDER_LIST_UPSTREAM_SLOW"))
        self.assertEqual(self.api.handle("GET", "/v1/orders", OP)[0], 200)

    def test_plan_answers_round_12_reading_findings(self):
        """中・低（第 12 回、読んで見つけた指摘）: 段 0 の 2 つ目（旧 API の出荷の文が印を条件に持つか）に、持たないときの決めと門がある。
        未確定 9 が、users に掛けた店の行の制限と食い違わない。IDEMPOTENCY_KEY_REQUIRED の対処の文が、計画・実装・契約で同じ（英語の見出しを出さない）。
        orders_write_horizon の書き手を名前で固定しない案をインフラに渡す。セーブポイントと表の写し直しで人と時刻が消えないことを書く"""
        plan = (HERE.parent.parent / "skills" / "backend" / "examples" / "backend-plan-order-list.md").read_text(encoding="utf-8")
        stage0 = plan[plan.index("段 0 では"):plan.index("### 版と段の表")]
        self.assertRegex(stage0, r"2 つ目[^\n]*持たなければ[^\n]*段 4 に進まない")
        nine = next(line for line in plan.splitlines() if line.startswith("| 9 |"))
        self.assertNotIn("店の行の制限を掛けない", nine)
        action = orders_api.ERRORS["IDEMPOTENCY_KEY_REQUIRED"][3]
        self.assertNotIn("Idempotency-Key", action)
        self.assertIn(f"| IDEMPOTENCY_KEY_REQUIRED | 400 | validation | 冪等キーがありません | {action} |", plan)
        self.assertIn("pg_locks", plan)
        self.assertIn("セーブポイント", plan)
        self.assertNotIn("セーブポイントの中の書き込みと、表を写し直したあとの行も null", plan)


if __name__ == "__main__":
    res = unittest.main(exit=False, verbosity=0).result
    ok = res.wasSuccessful()
    print(f"RESULT: {'PASS' if ok else 'FAIL'} samples/api の試験 ({res.testsRun - len(res.failures) - len(res.errors)}/{res.testsRun})")
    sys.exit(0 if ok else 1)
