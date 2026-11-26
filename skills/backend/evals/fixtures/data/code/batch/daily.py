"""Nightly batch for the evaluation sample. It still writes the old status value."""


def close_stale_orders(cur):
    cur.execute("UPDATE orders SET status = 'cancel' WHERE status = 'pending' AND created_at < date('now', '-30 day')")
