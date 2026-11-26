"""数字のまとめ。レポートの画面と、年の集計（税理士さんに渡す）で使う。

年の集計は、年に 1 回、手で python3 reports.py <年> を回す。
"""
import sys

import db
from models import SALES_STATUSES, STATUS_CANCELED

_SALES_IN = "(" + ", ".join("'%s'" % s for s in SALES_STATUSES) + ")"


def monthly_sales(ym):
    """月の売上（税込み）。ym は '2026-09' の形。"""
    row = db.q1(
        "SELECT COALESCE(SUM(total), 0) FROM orders"
        " WHERE status IN " + _SALES_IN + " AND substr(created_at, 1, 7) = ?",
        (ym,),
    )
    return row[0]


def yearly_sales(year):
    """年の売上。決済が済んだ注文だけを数える。"""
    row = db.q1(
        "SELECT COALESCE(SUM(o.total), 0) FROM orders o"
        " JOIN payments p ON p.order_id = o.id"
        " WHERE strftime('%Y', o.created_at) = ?",
        (str(year),),
    )
    return row[0]


def monthly_orders(ym):
    """月の注文の数。"""
    return db.q1("SELECT COUNT(*) FROM orders WHERE substr(created_at, 1, 7) = ?", (ym,))[0]


def daily_orders(ym):
    """日ごとの注文の数。"""
    return db.q(
        "SELECT substr(created_at, 1, 10) AS d, COUNT(*) AS n FROM orders"
        " WHERE substr(created_at, 1, 7) = ? GROUP BY d ORDER BY d",
        (ym,),
    )


def shipped_count(ym):
    """月の出荷の数。"""
    return db.q1("SELECT COUNT(*) FROM orders WHERE substr(shipped_at, 1, 7) = ?", (ym,))[0]


def cancel_count():
    """キャンセルの数。"""
    return db.q1("SELECT COUNT(*) FROM orders WHERE status = ?", (STATUS_CANCELED,))[0]


def deleted_count():
    """削除した注文の数。"""
    return db.q1("SELECT COUNT(*) FROM orders WHERE deleted_at IS NOT NULL")[0]


def items_sold(year):
    """年に売れた品物の個数。"""
    row = db.q1(
        "SELECT COALESCE(SUM(i.qty), 0) FROM order_items i"
        " JOIN orders o ON o.id = i.order_id"
        " WHERE o.status IN " + _SALES_IN + " AND strftime('%Y', o.created_at) = ?",
        (str(year),),
    )
    return row[0]


def top_products(year, limit=10):
    """よく売れた品物。"""
    return db.q(
        "SELECT p.sku, p.name, SUM(i.qty) AS n FROM order_items i"
        " JOIN orders o ON o.id = i.order_id JOIN products p ON p.id = i.product_id"
        " WHERE o.status IN " + _SALES_IN + " AND strftime('%Y', o.created_at) = ?"
        " GROUP BY p.id ORDER BY n DESC LIMIT ?",
        (str(year), limit),
    )


def top_customers(ym, limit=10):
    """その月によく買ってくれた会員。"""
    return db.q(
        "SELECT o.customer_id, c.name, SUM(o.total) AS amount FROM orders o"
        " JOIN customers c ON c.id = o.customer_id"
        " WHERE o.status IN " + _SALES_IN + " AND substr(o.created_at, 1, 7) = ?"
        " GROUP BY o.customer_id ORDER BY amount DESC LIMIT ?",
        (ym, limit),
    )


if __name__ == "__main__":
    year = sys.argv[1]
    print("売上", yearly_sales(year))
    print("品物の個数", items_sold(year))
    for row in top_products(year):
        print(tuple(row))
