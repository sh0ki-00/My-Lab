"""注文の処理。"""
import config
import db
from models import GIFT_METHOD, STATUS_CANCELED, STATUS_PAID, STATUS_PENDING, STATUS_SHIPPED


def calc(items):
    """items は [(商品の行, 個数)]。小計・税・合計・送料を返す。"""
    subtotal = sum(p["price"] * n for p, n in items)
    tax = int(subtotal * config.TAX_RATE)
    total = subtotal + tax  # total は税込み
    shipping = 0 if total >= config.FREE_SHIPPING_OVER else config.SHIPPING_FEE
    return subtotal, tax, total, shipping


def place_order(customer_id, items, pay_method):
    subtotal, tax, total, shipping = calc(items)
    now = db.jst_now()
    oid = db.exe(
        "INSERT INTO orders (customer_id, status, total, tax, shipping_fee, pay_method, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (customer_id, STATUS_PENDING, total, tax, shipping, pay_method, now, now),
    )
    for p, n in items:
        db.exe(
            "INSERT INTO order_items (order_id, product_id, qty, unit_price) VALUES (?, ?, ?, ?)",
            (oid, p["id"], n, p["price"]),
        )
        db.exe("UPDATE products SET stock = stock - ? WHERE id = ?", (n, p["id"]))
    return oid


def pay(order_id, method, amount, paid_at, giftcard=0):
    """決済会社から知らせが来たとき。paid_at は決済会社の時刻をそのまま入れる。"""
    if giftcard:
        db.exe(
            "INSERT INTO payments (order_id, method, amount, paid_at) VALUES (?, ?, ?, ?)",
            (order_id, GIFT_METHOD, giftcard, paid_at),
        )
    db.exe(
        "INSERT INTO payments (order_id, method, amount, paid_at) VALUES (?, ?, ?, ?)",
        (order_id, method, amount - giftcard, paid_at),
    )
    db.exe("UPDATE orders SET status = ?, updated_at = ? WHERE id = ?", (STATUS_PAID, db.jst_now(), order_id))


def cancel_order(order_id):
    # 返金したら決済の行は消す
    db.exe("DELETE FROM payments WHERE order_id = ?", (order_id,))
    db.exe("UPDATE orders SET status = ?, updated_at = ? WHERE id = ?", (STATUS_CANCELED, db.jst_now(), order_id))


def delete_order(order_id):
    now = db.jst_now()
    db.exe("UPDATE orders SET deleted_at = ?, updated_at = ? WHERE id = ?", (now, now, order_id))


def mark_shipped(order_id):
    """出荷のボタン。"""
    now = db.jst_now()
    db.exe(
        "UPDATE orders SET status = ?, shipped_at = ?, updated_at = ? WHERE id = ?",
        (STATUS_SHIPPED, now, now, order_id),
    )


def is_paid(order):
    return order["status"] == STATUS_PAID


def get_order(order_id):
    return db.q1("SELECT * FROM orders WHERE id = ?", (order_id,))


def get_items(order_id):
    return db.q(
        "SELECT p.sku, p.name, i.qty, i.unit_price FROM order_items i"
        " JOIN products p ON p.id = i.product_id WHERE i.order_id = ? ORDER BY i.id",
        (order_id,),
    )


def list_orders(status=None, page=0):
    sql = "SELECT * FROM orders WHERE is_deleted = 0 AND deleted_at IS NULL"
    args = []
    if status:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args += [config.PAGE_SIZE, page * config.PAGE_SIZE]
    return db.q(sql, args)
