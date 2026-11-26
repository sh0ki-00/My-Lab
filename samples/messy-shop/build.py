#!/usr/bin/env python3
"""build — messy-shop の DB（sqlite）を、決まった乱数の種で作る。

使い方: python3 build.py <作る DB のパス> [--force]
  作る先は、このディレクトリの外（作業の場所か一時の場所）にする。リポジトリに DB を入れないため、中を指したら止める。
  同じパスにファイルがあれば止める。--force を付けると作り直す。
表の形は app/migrations/ の SQL を番号の順に流して作る。行は、2023-01 から 2026-10 までの店の動きを作り物で並べる。
名前・メール・住所・金額・追跡番号は、すべて作り物。同じ種なら、何度作っても同じ行になる。
夜の集計の表（daily_stats）は、app/batch_nightly.py の DAY_SQL をそのまま回して埋める。
python3 の標準（sqlite3）だけで動く。3.9 以上。数秒で終わる。
"""
import argparse
import ast
import bisect
import datetime as dt
import os
import pathlib
import random
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE / "app"
SEED = 20261126

JST = dt.timezone(dt.timedelta(hours=9))
UTC = dt.timezone.utc
ONE_DAY = dt.timedelta(days=1)


def jst(y, mo, d, h=0, mi=0, s=0):
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=JST)


def at(day, h=0, mi=0):
    return dt.datetime(day.year, day.month, day.day, h, mi, tzinfo=JST)


def utc_text(t):
    return t.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def jst_iso(t):
    return t.astimezone(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


# 店の動きの節目（日本時間）
OPEN = jst(2023, 1, 4)
SNAPSHOT = jst(2026, 11, 1)  # この時点の DB を作る
CANCEL_V2 = jst(2024, 2, 1)  # 管理画面を作り直した
SITE_V2 = jst(2024, 4, 1)  # サイトを作り直した
GIFT_FROM = jst(2025, 1, 4)  # ギフト券の取り扱い
STATS_FROM = dt.date(2025, 4, 1)  # 夜の集計
SHIP_LINE = jst(2025, 7, 1)  # 経理の書き出しのため、業者が DB に直接足した
CAL_ADDED = jst(2026, 9, 10, 11)
PREORDER_FROM = dt.date(2026, 9, 15)
STAFF_AT = jst(2026, 10, 5, 10, 12)
NO_DELETE = (dt.date(2026, 7, 25), dt.date(2026, 9, 5))  # 夏の棚卸しで、注文を消す作業をしていない
MIDNIGHT_SALES = {dt.date(2024, 11, 1): 14, dt.date(2025, 12, 1): 22, dt.date(2026, 8, 1): 31}

SHIP_TRIGGER = """
CREATE TRIGGER trg_orders_after_insert AFTER INSERT ON orders
WHEN NEW.shipping_fee > 0
BEGIN
  INSERT INTO order_items (order_id, product_id, qty, unit_price)
  VALUES (NEW.id, (SELECT id FROM products WHERE sku = 'SHIP'), 1, NEW.shipping_fee);
END
"""

BASE = {2023: 4.2, 2024: 5.6, 2025: 6.6, 2026: 7.4}
SEASON = {1: 0.9, 2: 0.9, 3: 1.25, 4: 1.15, 5: 1.0, 6: 0.95, 7: 1.0, 8: 0.9, 9: 1.0, 10: 1.05, 11: 1.15, 12: 1.45}
WEEKDAY = [0.95, 0.95, 0.95, 1.0, 1.05, 1.15, 1.2]
HOURS = [3, 2, 1, 0.5, 0.3, 0.3, 0.6, 1.2, 1.8, 2.2, 2.6, 3, 4, 3.2, 2.8, 2.8, 3, 3.2, 3.6, 4.2, 5, 5.6, 5.2, 4.2]
P_NEW = {2023: 0.42, 2024: 0.33, 2025: 0.29, 2026: 0.26}

PRODUCTS = [
    # SKU、名前、税抜きの単価、売れやすさ
    ("PEN-001", "ゲルインクボールペン 黒", 150, 20),
    ("PEN-002", "ゲルインクボールペン 青", 150, 12),
    ("PEN-003", "3 色ボールペン", 400, 10),
    ("PEN-004", "万年筆 入門用", 2800, 3),
    ("PEN-005", "シャープペンシル 0.5", 500, 7),
    ("PEN-006", "蛍光ペン 5 色", 600, 8),
    ("NOTE-001", "方眼ノート A5", 300, 18),
    ("NOTE-002", "方眼ノート B5", 350, 10),
    ("NOTE-003", "無地ノート A5", 300, 9),
    ("NOTE-004", "ウィークリー手帳", 1600, 6),
    ("NOTE-005", "リングノート A6", 250, 8),
    ("NOTE-006", "糸かがりノート", 1200, 5),
    ("TAPE-001", "マスキングテープ 無地 5 巻", 450, 9),
    ("TAPE-002", "マスキングテープ 花", 280, 14),
    ("TAPE-003", "マスキングテープ ねこ", 280, 26),
    ("TAPE-004", "マスキングテープ 和柄", 280, 11),
    ("TAPE-005", "テープカッター", 900, 4),
    ("STK-001", "付箋 75mm", 200, 15),
    ("STK-002", "付箋 透明", 350, 9),
    ("STK-003", "付箋 3 種のセット", 500, 6),
    ("ENV-001", "封筒 洋形 10 枚", 380, 6),
    ("ENV-002", "一筆箋", 400, 8),
    ("ENV-003", "レターセット", 650, 7),
    ("ENV-004", "ポストカード 5 枚", 500, 6),
    ("POUCH-001", "ペンケース 帆布", 1800, 7),
    ("POUCH-002", "ペンケース 革", 4200, 3),
    ("POUCH-003", "ブックカバー 文庫", 2400, 4),
    ("POUCH-004", "ポーチ 小", 1500, 5),
    ("MUG-001", "マグカップ 白", 1600, 4),
    ("MUG-002", "マグカップ ねこ", 1900, 5),
    ("DESK-001", "デスクトレー", 2200, 3),
    ("DESK-002", "ブックスタンド", 1800, 3),
    ("DESK-003", "クリップ 50 個", 200, 7),
    ("DESK-004", "はさみ", 750, 5),
    ("DESK-005", "スティックのり", 120, 8),
    ("DESK-006", "消しゴム", 100, 10),
]

FAMILY = ["佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤", "吉田", "山田", "佐々木",
          "山口", "松本", "井上", "木村", "林", "斎藤", "清水", "山崎", "森", "池田", "橋本", "阿部", "石川", "山下",
          "中島", "石井", "小川", "前田", "岡田", "長谷川", "藤田", "後藤", "近藤", "村上", "遠藤", "青木", "坂本"]
GIVEN = ["翔", "蓮", "陽菜", "結衣", "大翔", "美咲", "健太", "彩", "優斗", "葵", "拓海", "結菜", "悠真", "莉子", "直樹",
         "真央", "亮", "舞", "誠", "由美", "修", "恵", "浩", "智子", "剛", "香織", "隆", "幸子", "学", "裕子"]
PREFS = [("東京都", 14), ("神奈川県", 9), ("大阪府", 8), ("埼玉県", 7), ("愛知県", 6), ("千葉県", 6), ("兵庫県", 4),
         ("北海道", 4), ("福岡県", 4), ("静岡県", 3), ("京都府", 2), ("広島県", 2), ("宮城県", 2), ("新潟県", 2),
         ("茨城県", 2), ("長野県", 1), ("岡山県", 1), ("熊本県", 1)]
DOMAINS = ["example.com", "example.jp", "example.net", "example.org"]
STAFF = [("テスト 一郎", "test1@komonoya.example"), ("テスト 花子", "test2@komonoya.example"),
         ("動作確認", "check@komonoya.example")]
CARRIERS = ["yamato", "sagawa", "japanpost"]

# 決まった日の注文（日、時、分、種類、だれ、品物）。だれは、お店の人の番号か、まとめて買う会員の番号
PLANNED = [
    (dt.date(2026, 10, 6), 10, 41, "test", 0, [("POUCH-002", 3), ("MUG-002", 2)]),
    (dt.date(2026, 10, 7), 11, 0, "zero", 2, [("PEN-001", 1)]),
    (dt.date(2026, 10, 7), 15, 2, "test", 0, [("POUCH-002", 3), ("MUG-002", 2)]),
    (dt.date(2026, 10, 8), 11, 20, "test", 0, [("POUCH-002", 3), ("MUG-002", 2)]),
    (dt.date(2026, 10, 8), 14, 20, "big", 0, [("POUCH-002", 4), ("MUG-002", 4)]),
    (dt.date(2026, 10, 8), 16, 20, "zero", 2, [("PEN-001", 1)]),
    (dt.date(2026, 10, 9), 10, 15, "test", 1, [("DESK-001", 3), ("POUCH-001", 2)]),
    (dt.date(2026, 10, 9), 14, 30, "test", 1, [("DESK-001", 3), ("POUCH-001", 2)]),
    (dt.date(2026, 10, 13), 16, 45, "test", 0, [("POUCH-002", 3), ("MUG-002", 2)]),
    (dt.date(2026, 10, 14), 10, 30, "zero", 2, [("PEN-001", 1)]),
    (dt.date(2026, 10, 14), 13, 10, "test", 0, [("POUCH-002", 3), ("MUG-002", 2)]),
    (dt.date(2026, 10, 15), 11, 5, "test", 1, [("DESK-001", 3), ("POUCH-001", 2)]),
    (dt.date(2026, 10, 15), 17, 5, "zero", 2, [("PEN-001", 1)]),
    (dt.date(2026, 10, 16), 11, 40, "big", 1, [("POUCH-002", 5), ("ENV-003", 10)]),
    (dt.date(2026, 10, 16), 15, 40, "test", 1, [("DESK-001", 3), ("POUCH-001", 2)]),
    (dt.date(2026, 10, 19), 10, 50, "test", 1, [("DESK-001", 3), ("POUCH-001", 2)]),
    (dt.date(2026, 10, 20), 17, 30, "test", 0, [("POUCH-002", 3), ("MUG-002", 2)]),
    (dt.date(2026, 10, 22), 19, 5, "big", 0, [("POUCH-003", 6)]),
    (dt.date(2026, 10, 23), 13, 15, "big", 2, [("DESK-001", 5), ("DESK-002", 5)]),
    (dt.date(2026, 10, 27), 20, 10, "big", 1, [("NOTE-006", 5)]),
    (dt.date(2026, 10, 29), 21, 30, "big", 2, [("MUG-001", 4)]),
]


def closed(day):
    """年末年始（12-31 から 1-3）は注文を受けない。"""
    return (day.month == 12 and day.day == 31) or (day.month == 1 and day.day <= 3)


def open_day(day):
    while closed(day):
        day += ONE_DAY
    return day


def day_sql():
    """夜の集計の文を、app/batch_nightly.py から読む（モジュールは動かさない）。"""
    tree = ast.parse((APP / "batch_nightly.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "DAY_SQL" for t in node.targets):
            return ast.literal_eval(node.value)
    raise SystemExit("FAIL build: app/batch_nightly.py に DAY_SQL が無い")


class Shop:
    def __init__(self, con, rng):
        self.con = con
        self.rng = rng
        self.n_cust = 0
        self.cust = []  # 普通に注文する会員の (id, 作った時刻)
        self.cum = []  # 選ばれやすさの累積
        self.staff = []
        self.big = {}
        self.prod = {}  # SKU → (id, 単価)
        self.pick_skus = [p[0] for p in PRODUCTS]
        self.pick_cum = []
        acc = 0
        for p in PRODUCTS:
            acc += p[3]
            self.pick_cum.append(acc)
        self.pref_names = [p[0] for p in PREFS]
        self.pref_weights = [p[1] for p in PREFS]
        self.pays = []
        self.ships = []

    # ---- 品物と会員
    def add_product(self, sku, name, price, stock, active, t):
        cur = self.con.execute(
            "INSERT INTO products (sku, name, price, stock, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (sku, name, price, stock, active, utc_text(t)),
        )
        self.prod[sku] = (cur.lastrowid, price)

    def add_customer(self, t, mail_ok, name=None, email=None, pickable=True, boost=1.0):
        rng = self.rng
        self.n_cust += 1
        cid = self.n_cust
        if name is None:
            name = rng.choice(FAMILY) + " " + rng.choice(GIVEN)
        if email is None:
            local = "".join(rng.choice("abcdefghijkmnoprstuwyz") for _ in range(rng.randint(3, 7)))
            email = "%s%d@%s" % (local, cid, rng.choice(DOMAINS))
        pref = "東京都" if not pickable else rng.choices(self.pref_names, weights=self.pref_weights)[0]
        cur = self.con.execute(
            "INSERT INTO customers (name, email, pref, mail_ok, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, email, pref, mail_ok, utc_text(t)),
        )
        assert cur.lastrowid == cid
        if pickable:
            self.cust.append((cid, t))
            self.cum.append((self.cum[-1] if self.cum else 0.0) + rng.lognormvariate(0, 1.1) * boost)
        return cid

    def signup(self, t):
        rng = self.rng
        if t < SITE_V2:
            mail_ok = "on" if rng.random() < 0.55 else ""
        else:
            mail_ok = 1 if rng.random() < 0.48 else 0
        return self.add_customer(t, mail_ok)

    def pick_customer(self, t):
        rng = self.rng
        if not self.cust or rng.random() < P_NEW[t.astimezone(JST).year]:
            return self.signup(t - dt.timedelta(minutes=rng.randint(2, 25)))
        r = rng.random() * self.cum[-1]
        return self.cust[bisect.bisect_right(self.cum, r)][0]

    def pick_items(self):
        rng = self.rng
        n = rng.choices([1, 2, 3, 4], weights=[45, 30, 15, 10])[0]
        chosen = []
        while len(chosen) < n:
            sku = self.pick_skus[bisect.bisect_right(self.pick_cum, rng.random() * self.pick_cum[-1])]
            if sku not in chosen:
                chosen.append(sku)
        return [(sku, rng.choices([1, 2, 3, 5], weights=[75, 17, 6, 2])[0]) for sku in chosen]

    # ---- 注文
    def add_order(self, t, cid, items, kind="normal", method=None):
        rng = self.rng
        lines = [(self.prod[sku][0], n, 0 if kind == "zero" else self.prod[sku][1]) for sku, n in items]
        subtotal = sum(n * price for _, n, price in lines)
        tax = subtotal * 10 // 100
        total = subtotal + tax if t >= SITE_V2 else subtotal
        ship = 0 if (kind == "zero" or subtotal + tax >= 5000) else 600
        if method is None:
            method = rng.choices(["card", "konbini", "bank"], weights=[70, 20, 10])[0]
        life = self.life(t, total, ship, method, kind)
        deleted = life.get("deleted")
        cur = self.con.execute(
            "INSERT INTO orders (customer_id, status, total, tax, shipping_fee, pay_method, is_deleted,"
            " created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, life["status"], total, tax, ship, method, life.get("is_deleted", 0), utc_text(t),
             utc_text(life["updated"]), utc_text(deleted) if deleted else None),
        )
        oid = cur.lastrowid
        for pid, n, price in lines:
            self.con.execute(
                "INSERT INTO order_items (order_id, product_id, qty, unit_price) VALUES (?, ?, ?, ?)",
                (oid, pid, n, price),
            )
        for m, amount, when in life.get("pays", []):
            self.pays.append((when, oid, m, amount))
        if "ship" in life:
            self.ships.append((oid,) + life["ship"])
        return oid

    def unpaid(self, t):
        rng = self.rng
        life = {"status": "pending", "updated": t}
        day = t.astimezone(JST).date()
        if SNAPSHOT - t < dt.timedelta(days=45) or NO_DELETE[0] <= day <= NO_DELETE[1]:
            return life
        if rng.random() >= 0.6:
            return life
        when = t + dt.timedelta(days=rng.uniform(14, 40))
        if when < SITE_V2:
            life.update(is_deleted=1, updated=when)  # 前の管理画面で消した
        elif rng.random() < 0.75:
            life.update(deleted=when, updated=when)  # 注文の画面で消した
        else:
            life["is_deleted"] = 1  # 一覧でまとめて消した
        return life

    def life(self, t, total, ship, method, kind):
        rng = self.rng
        if kind == "reserved":
            return {"status": "reserved", "updated": t}
        if kind in ("test", "zero"):
            paid = t + dt.timedelta(seconds=rng.randint(30, 90))
            return {"status": "paid", "updated": paid, "pays": [] if kind == "zero" else [("card", total + ship, paid)]}
        r = rng.random()
        if kind in ("normal", "sale") and r < 0.045:
            return self.unpaid(t)
        if kind in ("normal", "sale") and r < 0.105 and SNAPSHOT - t > dt.timedelta(days=5):
            when = t + dt.timedelta(minutes=rng.uniform(5, 72 * 60))
            return {"status": "cancel" if when < CANCEL_V2 else "canceled", "updated": when}
        if method == "card":
            paid = t + dt.timedelta(seconds=rng.randint(40, 300))
        elif method == "konbini":
            paid = t + dt.timedelta(minutes=rng.uniform(60, 48 * 60))
        else:
            paid = t + dt.timedelta(minutes=rng.uniform(180, 72 * 60))
        if paid >= SNAPSHOT:
            return {"status": "pending", "updated": t}
        gift = 0
        if t >= GIFT_FROM and total >= 1000 and rng.random() < 0.13:
            gift = min(rng.choice([500, 1000, 1000, 2000]), total)
        pays = ([("giftcard", gift, paid)] if gift else []) + [(method, total + ship - gift, paid)]
        sday = open_day(paid.astimezone(JST).date() + dt.timedelta(days=1 if rng.random() < 0.7 else 2))
        picked = at(sday + ONE_DAY, 2, 30) + dt.timedelta(seconds=rng.randint(5, 600))
        if picked >= SNAPSHOT:
            return {"status": "paid", "updated": paid, "pays": pays}
        dday = sday + dt.timedelta(days=rng.choice([1, 1, 2, 2, 3]))
        got = at(dday + ONE_DAY, 2, 30) + dt.timedelta(seconds=rng.randint(5, 600))
        carrier = rng.choices(CARRIERS, weights=[60, 25, 15])[0]
        tracking = "%012d" % rng.randrange(10 ** 11, 10 ** 12)
        if got < SNAPSHOT:
            return {"status": "delivered", "updated": got, "pays": pays, "ship": (carrier, tracking, sday, dday)}
        return {"status": "shipped", "updated": picked, "pays": pays, "ship": (carrier, tracking, sday, None)}

    # ---- 1 日ずつ
    def day_events(self, day, planned):
        rng = self.rng
        if closed(day):
            return []
        ev = []
        mu = BASE[day.year] * SEASON[day.month] * WEEKDAY[day.weekday()]
        for _ in range(max(0, int(round(rng.gauss(mu, mu ** 0.5))))):
            h = rng.choices(range(24), weights=HOURS)[0]
            ev.append((at(day, h) + dt.timedelta(seconds=rng.randint(0, 3599)), "normal", None))
        for _ in range(MIDNIGHT_SALES.get(day, 0)):
            ev.append((at(day) + dt.timedelta(seconds=rng.randint(5, 2 * 3600)), "sale", None))
        if day >= PREORDER_FROM:
            for _ in range(rng.choice([1, 2, 2, 3])):
                h = rng.choices(range(24), weights=HOURS)[0]
                ev.append((at(day, h) + dt.timedelta(seconds=rng.randint(0, 3599)), "reserved", None))
        if day == STAFF_AT.date():
            ev.append((STAFF_AT, "staff", None))
        for d, h, mi, kind, who, items in planned:
            if d == day:
                ev.append((at(day, h, mi) + dt.timedelta(seconds=rng.randint(0, 59)), kind, (who, items)))
        ev.sort(key=lambda e: (e[0], e[1]))
        return ev

    def big_buyer(self, who):
        if who not in self.big:
            pool = [cid for cid, t in self.cust if t < jst(2026, 1, 1) and cid not in self.big.values()]
            self.big[who] = self.rng.choice(pool)
        return self.big[who]

    def run(self):
        rng = self.rng
        start = jst(2023, 1, 3, 15)
        for sku, name, price, _w in PRODUCTS:
            self.add_product(sku, name, price, None, 1, start)
        imported = jst(2023, 1, 4, 10)
        for _ in range(150):
            self.add_customer(imported, None, boost=1.3)
        day = OPEN.date()
        while day < SNAPSHOT.date():
            if day == SHIP_LINE.date():
                self.add_product("SHIP", "送料", 600, None, 0, SHIP_LINE - dt.timedelta(minutes=5))
                self.con.execute(SHIP_TRIGGER)
            if day == CAL_ADDED.date():
                self.add_product("CAL-2027", "卓上カレンダー 2027", 1500, None, 1, CAL_ADDED)
            for t, kind, payload in self.day_events(day, PLANNED):
                if kind == "staff":
                    for name, email in STAFF:
                        self.staff.append(self.add_customer(t, 0, name=name, email=email, pickable=False))
                elif kind in ("normal", "sale"):
                    cid = self.pick_customer(t)
                    items = self.pick_items()
                    if kind == "sale":
                        items = [("POUCH-001", 1)] + [it for it in items[:1] if it[0] != "POUCH-001" and rng.random() < 0.4]
                    self.add_order(t, cid, items, kind)
                elif kind == "reserved":
                    cid = self.pick_customer(t)
                    self.add_order(t, cid, [("CAL-2027", rng.choice([1, 1, 1, 2]))], "reserved")
                elif kind in ("test", "zero"):
                    who, items = payload
                    self.add_order(t, self.staff[who], items, kind, method="card")
                elif kind == "big":
                    who, items = payload
                    self.add_order(t, self.big_buyer(who), items, "big", method="card")
            day += ONE_DAY
        self.finish()

    def finish(self):
        rng = self.rng
        con = self.con
        for when, oid, method, amount in sorted(self.pays, key=lambda p: (p[0], p[1])):
            con.execute(
                "INSERT INTO payments (order_id, method, amount, paid_at) VALUES (?, ?, ?, ?)",
                (oid, method, amount, jst_iso(when)),
            )
        for oid, carrier, tracking, sday, dday in sorted(self.ships, key=lambda s: (s[3], s[0])):
            con.execute(
                "INSERT INTO shipments (order_id, carrier, tracking_no, shipped_on, delivered_on) VALUES (?, ?, ?, ?, ?)",
                (oid, carrier, tracking, sday.isoformat(), dday.isoformat() if dday else None),
            )
        # サイトを作り直したあと、マイページでお知らせのメールの設定を変えた会員
        for cid, t in self.cust:
            if t < SITE_V2 and rng.random() < 0.12:
                con.execute("UPDATE customers SET mail_ok = ? WHERE id = ?", (1 if rng.random() < 0.5 else 0, cid))
        for sku in self.pick_skus + ["CAL-2027"]:
            con.execute("UPDATE products SET stock = ? WHERE id = ?", (rng.randint(0, 120), self.prod[sku][0]))
        sql = day_sql()
        day = STATS_FROM
        while day < SNAPSHOT.date() - ONE_DAY:
            n, sales = con.execute(sql, (day.isoformat(),)).fetchone()
            ran = at(day + ONE_DAY, 3) + dt.timedelta(seconds=rng.randint(1, 50))
            con.execute(
                "INSERT INTO daily_stats (day, orders, sales, updated_at) VALUES (?, ?, ?, ?)",
                (day.isoformat(), n, sales, utc_text(ran)),
            )
            day += ONE_DAY


def build(path):
    con = sqlite3.connect(str(path))
    try:
        for f in sorted((APP / "migrations").glob("*.sql")):
            con.executescript(f.read_text(encoding="utf-8"))
        con.execute("BEGIN")
        Shop(con, random.Random(SEED)).run()
        con.commit()
        counts = {}
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"):
            counts[name] = con.execute('SELECT COUNT(*) FROM "%s"' % name).fetchone()[0]
        return counts
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="messy-shop の DB（sqlite）を作る")
    ap.add_argument("out", help="作る DB のパス。このディレクトリの外にする")
    ap.add_argument("--force", action="store_true", help="同じパスにファイルがあれば作り直す")
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out).expanduser().resolve()
    # 大文字と小文字を区別しないファイルシステム（macOS の既定）でも止まるよう、実在する親を samefile で HERE と比べる
    inside = out == HERE or HERE in out.parents or any(
        p.exists() and os.path.samefile(str(p), str(HERE)) for p in [out] + list(out.parents))
    if inside:
        print("FAIL build: サンプルのディレクトリの中には作らない（リポジトリに DB を入れない）。外のパスを渡す", file=sys.stderr)
        return 2
    if out.exists() and not a.force:
        print("FAIL build: %s がもうある。作り直すなら --force を付ける" % out, file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.with_name(out.name + ".building")
    if work.exists():
        work.unlink()
    counts = build(work)
    if out.exists():
        out.unlink()
    work.rename(out)
    print("作った: %s（種 %d）" % (out, SEED))
    print("行の数: " + "、".join("%s %d" % kv for kv in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
