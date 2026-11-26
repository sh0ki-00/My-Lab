"""予約の注文（2026-09 から）。発売の日まで入金を待つ。"""
import db
import orders


def reserve(customer_id, product, qty, pay_method):
    oid = orders.place_order(customer_id, [(product, qty)], pay_method)
    db.exe("UPDATE orders SET status = 'reserved' WHERE id = ?", (oid,))
    return oid


def release(product_id):
    """発売の日。予約を入金待ちに戻して、入金のお願いのメールを送る。"""
    db.exe(
        "UPDATE orders SET status = 'pending', updated_at = ?"
        " WHERE status = 'reserved' AND id IN (SELECT order_id FROM order_items WHERE product_id = ?)",
        (db.jst_now(), product_id),
    )
