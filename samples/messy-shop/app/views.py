"""画面。ROUTES の表で、道から処理を引く。お店の管理画面（/admin）と、お客様の画面（/shop）と、決済会社からの知らせ（/pay）。"""
import html

import config
import customers
import db
import mail_report
import orders
import preorder
import reports
import stats
from models import ORDER_STATUSES, STATUS_LABELS

ROUTES = {}


def route(path):
    def deco(fn):
        ROUTES[path] = fn
        return fn

    return deco


def page(title, body):
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>"
        + html.escape(title + " | " + config.SHOP_NAME)
        + "</title></head><body><h1>"
        + html.escape(title)
        + "</h1>"
        + body
        + "</body></html>"
    )


def table(head, rows):
    out = "<table><tr>" + "".join("<th>%s</th>" % html.escape(str(h)) for h in head) + "</tr>"
    for r in rows:
        out += "<tr>" + "".join("<td>%s</td>" % html.escape(str(c)) for c in r) + "</tr>"
    return out + "</table>"


def yen(n):
    return "{:,} 円".format(n or 0)


# ---- お店の管理画面


@route("/admin/")
def dashboard(params):
    rows = [(r["ym"], r["orders"], yen(r["sales"])) for r in stats.month_table()]
    body = "<p>会員 %d 人</p>" % customers.count_members()
    body += "<h2>月次</h2>" + table(["月", "注文", "売上"], rows)
    return page("トップ", body)


@route("/admin/orders")
def order_list(params):
    st = params.get("status")
    if st not in ORDER_STATUSES:
        st = None
    rows = []
    for o in orders.list_orders(st, int(params.get("page", 0))):
        rows.append((o["id"], o["created_at"], STATUS_LABELS.get(o["status"], o["status"]), yen(o["total"])))
    return page("注文", table(["番号", "日時", "状態", "合計"], rows))


@route("/admin/order")
def order_detail(params):
    o = orders.get_order(int(params["id"]))
    items = [(i["name"], i["qty"], yen(i["unit_price"])) for i in orders.get_items(o["id"])]
    body = table(["品物", "個数", "単価"], items)
    body += "<p>送料 %s　合計 %s</p>" % (yen(o["shipping_fee"]), yen(o["total"]))
    if orders.is_paid(o):
        body += "<p>入金済み</p>"
    return page("注文 %d" % o["id"], body)


@route("/admin/order/cancel")
def order_cancel(params):
    orders.cancel_order(int(params["id"]))
    return order_list({})


@route("/admin/order/delete")
def order_delete(params):
    orders.delete_order(int(params["id"]))
    return order_list({})


@route("/admin/orders/bulk")
def order_bulk(params):
    """一覧で選んだ注文をまとめて操作する。"""
    ids = [int(x) for x in params.get("ids", "").split(",") if x]
    if ids and params.get("op") == "delete":
        db.exe("UPDATE orders SET is_deleted = 1 WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
    return order_list({})


@route("/admin/products")
def product_list(params):
    rows = db.q("SELECT sku, name, price, stock FROM products WHERE is_active = 1 ORDER BY sku")
    return page("品物", table(["SKU", "名前", "単価", "在庫"], [tuple(r) for r in rows]))


@route("/admin/newsletter")
def newsletter(params):
    return page("お知らせのメール", "<p>送る相手 %d 人</p>" % len(mail_report.newsletter_targets()))


# @route("/admin/reports")  2025-04 にトップの表へ移した
def report_page(params):
    ym = params.get("ym", "")
    rows = [
        ("売上", yen(reports.monthly_sales(ym))),
        ("注文", reports.monthly_orders(ym)),
        ("出荷", reports.shipped_count(ym)),
        ("キャンセル（全部）", reports.cancel_count()),
    ]
    return page("レポート " + ym, table(["項目", "値"], rows))


# ---- お客様の画面


@route("/shop/register")
def shop_register(params):
    if customers.find_by_email(params["email"]):
        return page("このメールはもう登録されています", "")
    customers.register(params)
    return page("登録しました", "")


@route("/shop/order")
def shop_order(params):
    """カートの中身で注文する。items は「品物の id:個数」をコンマでつないだもの。"""
    items = []
    for part in params.get("items", "").split(","):
        if not part:
            continue
        pid, n = part.split(":")
        p = db.q1("SELECT * FROM products WHERE id = ? AND is_active = 1", (int(pid),))
        if p:
            items.append((p, int(n)))
    oid = orders.place_order(int(params["customer_id"]), items, params.get("pay_method", "card"))
    return page("ご注文ありがとうございます", "<p>注文番号 %d</p>" % oid)


@route("/shop/reserve")
def shop_reserve(params):
    p = db.q1("SELECT * FROM products WHERE id = ?", (int(params["product_id"]),))
    oid = preorder.reserve(int(params["customer_id"]), p, int(params.get("qty", 1)), params.get("pay_method", "card"))
    return page("予約しました", "<p>注文番号 %d</p>" % oid)


@route("/shop/mypage/mail")
def shop_mail(params):
    customers.set_mail(int(params["customer_id"]), params.get("mail_ok") == "1")
    return page("設定を変えました", "")


# ---- 決済会社からの知らせ


@route("/pay/notify")
def pay_notify(params):
    orders.pay(
        int(params["order_id"]),
        params["method"],
        int(params["amount"]),
        params["paid_at"],
        int(params.get("giftcard", 0)),
    )
    return "ok"


def handle(path, params):
    fn = ROUTES.get(path)
    if fn is None:
        return 404, page("見つかりません", "")
    return 200, fn(params)
