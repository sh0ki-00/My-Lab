"""運送会社の CSV を取り込む。"""
import csv
import glob
import os

import config
import db


def job_carrier(path=None):
    files = [path] if path else sorted(glob.glob(os.path.join(config.CARRIER_CSV_DIR, "*.csv")))
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row["event"] == "picked":
                    db.exe(
                        "INSERT INTO shipments (order_id, carrier, tracking_no, shipped_on) VALUES (?, ?, ?, ?)",
                        (row["order_id"], row["carrier"], row["tracking_no"], row["date"]),
                    )
                    db.exe(
                        "UPDATE orders SET status = 'shipped', updated_at = ? WHERE id = ?",
                        (db.jst_now(), row["order_id"]),
                    )
                elif row["event"] == "delivered":
                    db.exe("UPDATE shipments SET delivered_on = ? WHERE order_id = ?", (row["date"], row["order_id"]))
                    db.exe(
                        "UPDATE orders SET status = 'delivered', updated_at = ? WHERE id = ?",
                        (db.jst_now(), row["order_id"]),
                    )
        os.rename(f, f + ".done")
