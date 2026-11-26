#!/usr/bin/env python3
"""vulnerable-app — 攻撃の道具の検知力を測るためだけの、わざと穴を空けた見本の API。

これは試験の的である。本番にも、ふつうの見本にも使わない。次の 3 つを必ず守る。
  1. 待ち受けは 127.0.0.1 だけ。外からは届かない。
  2. 中のデータは起動のたびに作り直す、使い捨ての作り物。個人の情報も本物の鍵も入れない。
  3. --fixed を付けると、12 の穴が全部ふさがる。attack_run.py が、ふさいだ版で穴 0 件になることを確かめる。

穴は A01〜A12 の手口に 1 つずつ対応する（skills/security/references/attack-table.md）。
  A01 認証なし: GET /orders が、鍵なしでも一覧を返す。
  A02 他人の物:  GET /orders/<id> が、持ち主を見ずに返す（番号を変えると他店が読める）。
  A03 役割越え:  POST /orders/<id>/note を、閲覧者（viewer）も通す。
  A04 余計な項目: GET /users/<id> が、応答に token と password_hash を混ぜる。
  A05 鍵が推せる: 鍵が "token-<利用者>" の形で、推して作れる。
  A06 注入:      GET /search?q= が、q を文字列で連結して SQL に渡す。
  A07 差し込み:  GET /inquiries が、保存した本文を素の HTML として出す。
  A08 別サイト:  POST /orders/<id>/note が、別の Origin からの要求を断らない。
  A09 連打:      POST /login に回数の制限が無い。
  A10 外へ:      POST /fetch-preview が、渡された URL へ無条件でつなぐ。
  A11 ファイル:  POST /upload が、名前の "../" を許し、置き場の外に書く。
  A12 設定と漏れ: 例外の本文に内部の値（例外の文）が出る。GET /debug が設定を返す。

使い方: python3 app.py [--fixed] [--port N] [--uploads DIR]
  起動すると、標準出力に「LISTENING 127.0.0.1:<ポート>」を 1 行出す（呼ぶ側がポートを知るため）。
  要求ごとに、使い捨ての記録を <uploads の親>/requests.log に 1 行の JSON で書く（届いた本数の突き合わせに使う）。
  make_app(fixed) でも作れる（handle(method, path, headers, body) を持つ。試験が直に呼ぶ）。
"""
import argparse
import html
import http.server
import json
import os
import pathlib
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.request

ROLES = {"operator": 2, "viewer": 1}


class App:
    def __init__(self, fixed=False, uploads=None, logpath=None):
        self.fixed = bool(fixed)
        self.uploads = pathlib.Path(uploads) if uploads else pathlib.Path(tempfile.mkdtemp(prefix="vuln-up-"))
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.logpath = pathlib.Path(logpath) if logpath else self.uploads.parent / "requests.log"
        self.lock = threading.Lock()
        self.login_hits = {}
        self._build()

    # ---- 作り物のデータ（使い捨て）
    def _build(self):
        self.users = {
            "op_a": {"pw": "pw-op-a", "role": "operator", "shop": "A", "email": "op-a@example.test", "name": "担当 A"},
            "op_b": {"pw": "pw-op-b", "role": "operator", "shop": "B", "email": "op-b@example.test", "name": "担当 B"},
            "view_a": {"pw": "pw-view-a", "role": "viewer", "shop": "A", "email": "view-a@example.test", "name": "閲覧 A"},
        }
        # 鍵: 穴のある版は推せる形、ふさいだ版は乱数。token -> 利用者
        self.tokens = {}
        for uid in self.users:
            tok = "token-" + uid if not self.fixed else "t_" + os.urandom(16).hex()
            self.tokens[tok] = uid
            self.users[uid]["pw_hash"] = "sha256$" + os.urandom(8).hex()
        self.inquiries = []
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE TABLE orders (id TEXT PRIMARY KEY, shop TEXT, customer TEXT, address TEXT, note TEXT)")
        rows = [
            ("o1", "A", "山田", "東京都 A 区 1-1", ""),
            ("o2", "A", "佐藤", "東京都 A 区 2-2", ""),
            ("o3", "B", "鈴木", "大阪府 B 市 3-3", ""),
            ("o4", "B", "田中", "大阪府 B 市 4-4", ""),
        ]
        self.db.executemany("INSERT INTO orders VALUES (?,?,?,?,?)", rows)
        self.db.commit()

    def _user_of(self, headers):
        auth = headers.get("authorization") or headers.get("Authorization") or ""
        tok = auth[7:] if auth.lower().startswith("bearer ") else ""
        uid = self.tokens.get(tok)
        return uid, (self.users.get(uid) if uid else None)

    def _log(self, method, path, status):
        rec = {"t": round(time.time(), 3), "m": method, "p": path.split("?")[0], "s": status}
        try:
            with open(self.logpath, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ---- 入口の割り当て
    def handle(self, method, path, headers, body):
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        raw = path
        qpath = path.split("?", 1)
        p = qpath[0]
        query = qpath[1] if len(qpath) > 1 else ""
        try:
            status, payload, extra = self._route(method, p, query, headers, body or b"")
        except Exception as e:  # noqa: BLE001  わざと: A12 で内部の値を漏らす版を試す
            if self.fixed:
                status, payload, extra = 500, {"error": "internal"}, {}
            else:
                status, payload, extra = 500, {"error": "internal", "detail": repr(e)}, {}
        self._log(method, raw, status)
        return status, payload, extra

    def _route(self, method, p, query, headers, body):
        parts = [x for x in p.split("/") if x]
        if method == "POST" and p == "/login":
            return self._login(body)
        if method == "GET" and p == "/orders":
            return self._orders_list(headers)
        if method == "GET" and len(parts) == 2 and parts[0] == "orders":
            return self._order_detail(headers, parts[1])
        if method == "POST" and len(parts) == 3 and parts[0] == "orders" and parts[2] == "note":
            return self._order_note(headers, parts[1], body)
        if method == "GET" and len(parts) == 2 and parts[0] == "users":
            return self._user_info(headers, parts[1])
        if method == "GET" and p == "/search":
            return self._search(headers, query)
        if method == "POST" and p == "/inquiry":
            return self._inquiry_add(body)
        if method == "GET" and p == "/inquiries":
            return self._inquiry_list()
        if method == "POST" and p == "/fetch-preview":
            return self._fetch_preview(headers, body)
        if method == "POST" and p == "/upload":
            return self._upload(headers, body)
        if method == "GET" and p == "/debug":
            return self._debug(headers)
        return 404, {"error": "not_found"}, {}

    # ---- 入口ごと
    def _login(self, body):
        # A09: 穴のある版は回数を数えない
        if self.fixed:
            now = time.time()
            with self.lock:
                self.login_hits = {k: v for k, v in self.login_hits.items() if now - v[1] < 60}
                cnt, t0 = self.login_hits.get("ip", (0, now))
                self.login_hits["ip"] = (cnt + 1, t0)
            if cnt + 1 > 10:
                return 429, {"error": "too_many"}, {}
        data = _jbody(body)
        uid = data.get("user")
        u = self.users.get(uid)
        if not u or data.get("password") != u["pw"]:
            return 401, {"error": "bad_login"}, {}
        tok = next(t for t, x in self.tokens.items() if x == uid)
        return 200, {"token": tok}, {}

    def _orders_list(self, headers):
        uid, u = self._user_of(headers)
        # A01: 穴のある版は鍵を見ない
        if self.fixed and not u:
            return 401, {"error": "auth_required"}, {}
        shop = u["shop"] if u else "A"
        cur = self.db.execute("SELECT id, customer FROM orders WHERE shop = ?", (shop,))
        return 200, {"orders": [{"id": r[0], "customer": r[1]} for r in cur.fetchall()]}, {}

    def _order_detail(self, headers, oid):
        uid, u = self._user_of(headers)
        if not u:
            return 401, {"error": "auth_required"}, {}
        cur = self.db.execute("SELECT id, shop, customer, address FROM orders WHERE id = ?", (oid,))
        row = cur.fetchone()
        if not row:
            return 404, {"error": "not_found"}, {}
        # A02: 穴のある版は持ち主を見ない
        if self.fixed and row[1] != u["shop"]:
            return 404, {"error": "not_found"}, {}
        return 200, {"id": row[0], "shop": row[1], "customer": row[2], "address": row[3]}, {}

    def _order_note(self, headers, oid, body):
        uid, u = self._user_of(headers)
        if not u:
            return 401, {"error": "auth_required"}, {}
        # A03: 穴のある版は役割を見ない（閲覧者も書ける）
        if self.fixed and ROLES.get(u["role"], 0) < ROLES["operator"]:
            return 403, {"error": "forbidden"}, {}
        # A08: 穴のある版は Origin を見ない
        if self.fixed:
            origin = headers.get("origin", "")
            if origin and not origin.startswith("http://127.0.0.1") and not origin.startswith("http://localhost"):
                return 403, {"error": "bad_origin"}, {}
        cur = self.db.execute("SELECT id, shop FROM orders WHERE id = ?", (oid,))
        row = cur.fetchone()
        if not row:
            return 404, {"error": "not_found"}, {}
        if row[1] != u["shop"]:
            return 404, {"error": "not_found"}, {}
        data = _jbody(body)
        self.db.execute("UPDATE orders SET note = ? WHERE id = ?", (str(data.get("note", "")), oid))
        self.db.commit()
        return 200, {"ok": True, "id": oid}, {}

    def _user_info(self, headers, uid_q):
        uid, u = self._user_of(headers)
        if not u:
            return 401, {"error": "auth_required"}, {}
        t = self.users.get(uid_q)
        if not t:
            return 404, {"error": "not_found"}, {}
        out = {"id": uid_q, "role": t["role"], "shop": t["shop"], "email": t["email"], "name": t["name"]}
        # A04: 穴のある版は鍵とハッシュも返す
        if not self.fixed:
            out["password_hash"] = t["pw_hash"]
            out["token"] = next(tk for tk, x in self.tokens.items() if x == uid_q)
        return 200, out, {}

    def _search(self, headers, query):
        uid, u = self._user_of(headers)
        if not u:
            return 401, {"error": "auth_required"}, {}
        q = _qval(query, "q")
        with self.lock:
            # A06: 穴のある版は q を文字列で連結する
            if self.fixed:
                cur = self.db.execute(
                    "SELECT id, customer FROM orders WHERE shop = ? AND customer LIKE ?",
                    (u["shop"], "%" + q + "%"),
                )
                rows = cur.fetchall()
            else:
                sql = ("SELECT id, customer FROM orders WHERE shop = '%s' AND customer LIKE '%%%s%%'"
                       % (u["shop"], q))
                rows = self.db.execute(sql).fetchall()
        return 200, {"orders": [{"id": r[0], "customer": r[1]} for r in rows]}, {}

    def _inquiry_add(self, body):
        data = _jbody(body)
        iid = "i%d" % (len(self.inquiries) + 1)
        self.inquiries.append({"id": iid, "body": str(data.get("body", ""))})
        return 200, {"ok": True, "id": iid}, {}

    def _inquiry_list(self):
        items = []
        for it in self.inquiries:
            # A07: 穴のある版は本文を素のまま埋める
            body = it["body"] if not self.fixed else html.escape(it["body"])
            items.append("<li>%s</li>" % body)
        page = "<!doctype html><html><body><ul>%s</ul></body></html>" % "".join(items)
        return 200, page, {"content-type": "text/html; charset=utf-8"}

    def _fetch_preview(self, headers, body):
        uid, u = self._user_of(headers)
        if not u:
            return 401, {"error": "auth_required"}, {}
        data = _jbody(body)
        url = str(data.get("url", ""))
        # A10: 穴のある版は、渡された URL へ無条件でつなぐ
        if self.fixed:
            return 400, {"error": "fetch_disabled"}, {}
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:  # noqa: S310  わざと: SSRF の的
                return 200, {"fetched": True, "status": resp.status}, {}
        except Exception as e:  # noqa: BLE001
            return 200, {"fetched": False, "detail": repr(e)[:80]}, {}

    def _upload(self, headers, body):
        uid, u = self._user_of(headers)
        if not u:
            return 401, {"error": "auth_required"}, {}
        data = _jbody(body)
        name = str(data.get("filename", "f"))
        content = str(data.get("content", ""))
        # A11: 穴のある版は "../" を許し、置き場の外に書く
        if self.fixed:
            name = os.path.basename(name)
            if not name or name.startswith("."):
                return 400, {"error": "bad_name"}, {}
        dest = (self.uploads / name)
        try:
            dest_resolved = dest.resolve()
            inside = str(dest_resolved).startswith(str(self.uploads.resolve()))
            dest_resolved.parent.mkdir(parents=True, exist_ok=True)
            dest_resolved.write_text(content[:200], encoding="utf-8")
        except OSError as e:
            return 400, {"error": "write_failed", "detail": repr(e)[:60]}, {}
        return 200, {"ok": True, "stored": str(dest_resolved), "inside_uploads": inside}, {}

    def _debug(self, headers):
        # A12: 穴のある版は設定を返す
        if self.fixed:
            return 404, {"error": "not_found"}, {}
        return 200, {"tokens": list(self.tokens.keys()), "uploads": str(self.uploads), "fixed": self.fixed}, {}


def _jbody(body):
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def _qval(query, key):
    for pair in query.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            if k == key:
                return urllib.parse.unquote_plus(v)
    return ""


import urllib.parse  # noqa: E402  _qval の下に置く（読みの順のため）


def make_app(fixed=False, uploads=None, logpath=None):
    return App(fixed=fixed, uploads=uploads, logpath=logpath)


def make_handler(app):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _run(self, method):
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else b""
            status, payload, extra = app.handle(method, self.path, dict(self.headers.items()), body)
            if isinstance(payload, str):
                data = payload.encode("utf-8")
                ctype = extra.get("content-type", "text/plain; charset=utf-8")
            else:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                ctype = "application/json; charset=utf-8"
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(data)))
            for k, v in extra.items():
                if k != "content-type":
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._run("GET")

        def do_POST(self):
            self._run("POST")

        def do_PUT(self):
            self._run("PUT")

        def do_DELETE(self):
            self._run("DELETE")

        def log_message(self, *a):
            pass
    return H


def make_server(app, port=0):
    handler = make_handler(app)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    return httpd


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixed", action="store_true")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--uploads", default=None)
    ap.add_argument("--log", default=None)
    args = ap.parse_args(argv)
    app = make_app(fixed=args.fixed, uploads=args.uploads, logpath=args.log)
    httpd = make_server(app, args.port)
    host, port = httpd.server_address[0], httpd.server_address[1]
    # 待ち受けが 127.0.0.1 でなければ、何も開かずに止まる（二重の守り）
    if host not in ("127.0.0.1",):
        httpd.server_close()
        print("ABORT: 127.0.0.1 以外には待ち受けない (%s)" % host, file=sys.stderr)
        return 2
    print("LISTENING 127.0.0.1:%d" % port, flush=True)
    print("LOG %s" % app.logpath, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
