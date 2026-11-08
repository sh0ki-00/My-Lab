#!/usr/bin/env python3
"""n1_orders_api — わざと N+1 にした見本の API の写し（query-count-check の負例）。

samples/api/orders_api.py を元に、2 か所だけを行ごとの問い合わせに変えた。
  一覧: 行ごとに明細の件数を引き直す（行の数だけ SELECT が増える）
  出荷指示: 1 件ずつ UPDATE する（件数だけ UPDATE が増える）
本番の形にしてはいけない例。evals と自己試験だけが使う。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "samples" / "api"))
import orders_api  # noqa: E402


class N1Api(orders_api.OrdersApi):
    def _row(self, r):
        out = super()._row(r)
        out["itemCount"] = self.q("SELECT COUNT(*) AS n FROM order_items WHERE order_id = ?", (r["id"],))[0]["n"]
        return out

    def _apply(self, user, ids, sql_set, from_status, kind, at):
        done = set()
        for i in ids:
            done |= super()._apply(user, [i], sql_set, from_status, kind, at)
        return done


def make_api(n_orders=29, log=None, deadline_s=orders_api.DEADLINE_S):
    return N1Api(n_orders, log, deadline_s)


make_server = orders_api.make_server
