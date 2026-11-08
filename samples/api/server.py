#!/usr/bin/env python3
"""server — 見本の注文 API を HTTP で立てる入口。本体は orders_api.py（同じディレクトリ）。

使い方: python3 samples/api/server.py [--port 8080] [--orders 29]
  --orders: 注文の件数。29 で見本の画面と同じ 29 行、400 なら作り物の注文を足して 400 件。
鍵は見本の作り物で、立てるたびに乱数で作り、標準出力に一度だけ出す（127.0.0.1 の手元の確かめのため）。
要約のログは標準エラーに出すので、ログの置き場に標準エラーを集めても鍵は入らない。
Authorization: Bearer <出した鍵>。u-takagi は運営担当者、u-kobayashi は閲覧者。鍵の期限は 12 時間（架空）。
127.0.0.1 だけで待ち受ける。保持の期間を過ぎた冪等キーは、書き込みが無いあいだも 10 分ごとに消す。
"""
import argparse
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import orders_api  # noqa: E402

PURGE_EVERY_S = 600


def purge_loop(api, stop):
    while not stop.wait(PURGE_EVERY_S):
        api.purge_expired()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--orders", type=int, default=29)
    a = ap.parse_args()
    api = orders_api.make_api(a.orders)
    srv = orders_api.make_server(api, "127.0.0.1", a.port)
    stop = threading.Event()
    threading.Thread(target=purge_loop, args=(api, stop), daemon=True).start()
    print(f"見本の注文 API: http://127.0.0.1:{srv.server_address[1]}/v1/orders（{a.orders} 件）", file=sys.stderr)
    for uid in ("u-takagi", "u-kobayashi"):
        print(f"見本の鍵（作り物、この起動の間だけ）{uid}: {api.token_for(uid)}", flush=True)  # 標準出力。ログ（標準エラー）と混ぜない
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()


if __name__ == "__main__":
    main()
