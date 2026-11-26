"""夜の処理。"""
import datetime

import db

DAY_SQL = (
    "SELECT COUNT(*), COALESCE(SUM(total + shipping_fee), 0) FROM orders"
    " WHERE date(created_at, '+9 hours') = ? AND status != 'canceled' AND deleted_at IS NULL"
)


def job_stats(day=None):
    """前の日の数をまとめて daily_stats に書く。"""
    if day is None:
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        day = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    n, sales = db.q1(DAY_SQL, (day,))
    db.exe(
        "INSERT OR REPLACE INTO daily_stats (day, orders, sales, updated_at) VALUES (?, ?, ?, ?)",
        (day, n, sales, db.jst_now()),
    )


def job_stock_alert():
    """在庫が少ない品物を店長に知らせる（いまは画面に出すだけ）。"""
    return db.q("SELECT sku, name, stock FROM products WHERE is_active = 1 AND stock < 5 ORDER BY stock")
