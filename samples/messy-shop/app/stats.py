"""トップの画面の数字。"""
import db


def month_table(limit=13):
    """月次の表。daily_stats を月ごとに足す。"""
    return db.q(
        "SELECT substr(day, 1, 7) AS ym, SUM(orders) AS orders, SUM(sales) AS sales FROM daily_stats"
        " GROUP BY ym ORDER BY ym DESC LIMIT ?",
        (limit,),
    )


def today_live():
    """（作りかけ）その場で数える版。"""
    return db.q1(
        "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM orders"
        " WHERE created_at >= date('now') AND status <> 'canceled'"
    )
