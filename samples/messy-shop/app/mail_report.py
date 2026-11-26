"""メール。店長への毎週の数字と、お客様へのお知らせ。"""
import datetime
import sys

import db
from customers import MAIL_OK


def weekly_numbers():
    """店長に送る、この 7 日の数字。"""
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    return db.q1(
        "SELECT COUNT(*), COALESCE(SUM(total + shipping_fee), 0) FROM orders"
        " WHERE created_at >= ? AND status NOT IN ('pending', 'canceled') AND is_deleted = 0",
        (since,),
    )


def newsletter_targets():
    """お知らせのメールを送る相手。"""
    return db.q("SELECT id, email FROM customers WHERE mail_ok = ?", (MAIL_OK,))


def send_newsletter(subject, body, send):
    """send(宛先, 件名, 本文) で 1 通ずつ送る。"""
    n = 0
    for row in newsletter_targets():
        send(row["email"], subject, body)
        n += 1
    return n


if __name__ == "__main__":
    # 月曜の朝に cron が回し、出した字を店長にメールする
    if sys.argv[1:] == ["weekly"]:
        n, sales = weekly_numbers()
        print("この 7 日の注文 %d 件、売上 %s 円" % (n, "{:,}".format(sales)))
