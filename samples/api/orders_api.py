#!/usr/bin/env python3
"""orders_api — 見本の注文 API（架空の EC サイトの管理画面）。python3 の標準（http.server と sqlite3）だけで動く。

契約: skills/backend/examples/openapi-order-list.json（OpenAPI 3.1）。この実装は契約のとおりに動く。
  GET  /v1/orders              注文一覧。件数・群ごとの件数・ビューごとの件数・利用者・サーバーの時刻を同じ応答に入れる。
                               起点の送り（after。絞り込みと結びつく）、since（重ね幅つき。起点の送りで全件をたどれる）
  GET  /v1/orders/{orderId}    注文詳細。同じ宛先の過去の注文 2 件、荷物の大きさと割れ物の指定
  POST /v1/orders/ship         出荷指示。Idempotency-Key 必須。行ごとの結果。先に済の行は ORDER_ALREADY_SHIPPED
  POST /v1/orders/cancel       取り消し。Idempotency-Key 必須。出荷指示済みの行は ORDER_CANCEL_NOT_ALLOWED。書けた行が 0 件なら 409
認可: Authorization: Bearer <鍵>。鍵は見本の作り物で、API を作るたびに乱数で作る（api.token_for(利用者の id) で引く）。
      利用者の id から鍵は作れない。鍵の期限は 12 時間（架空）。運営担当者（operator）と閲覧者（viewer）。
      閲覧者の書き込みは 403。他の店の注文は 404 で隠す。判定はサーバー側で資源 1 件ごと（店の id を全部の問い合わせに入れる）。
ログ: 1 要求 1 行の JSON の要約を標準エラーに出す。問い合わせの文字列・氏名・住所・鍵・冪等キーの値は書かない。
      要求から来る値は決まった語にしてから書く（メソッドは METHODS の語か OTHER、経路は型だけ）。
      予期しない例外も 500 にして 1 行を書き、接続を切らない。
保存: 時刻は UTC の ISO 8601、金額は円の整数。取り消しの正は旧い印 is_cancelled の 1 つだけで、意味を変えない。
      status に 'cancelled' は書かない（表の制約が断る）。契約の status の 'cancelled' は、読むときに is_cancelled から作る
      （未出荷の行だけ。出荷のあとに印が立った行は済のまま読み、cancelledAt で知らせる）。
      新 API の書き込みは is_cancelled を条件に入れる（出荷指示は is_cancelled = 0 の行だけ、取り消しは is_cancelled を 1 にする）。
      旧 API の書き込みは何も変えない。移行は意味を変えない足し算だけ（ADDITIONS。列、トリガー、索引）で、段の表も段の門も無い。
      足した物は移行のあいだ外さない。戻すのは新 API の機能フラグと、新 API の書き込み（writes_enabled）だけ。
      見本の表は、移行の前の表（LEGACY_SCHEMA）に ADDITIONS の sqlite の文を全部流した形。本番の文は ADDITIONS の pg にある。
      画面に見えうる行が変わるたびに changed_at を DB のトリガーが進め、since はこれで数える（2 日より前に出荷した済の行の一括と、
      値の変わらない書き込みは進めない。印の立て下ろしは必ず進める）。取り消しの人と時刻もトリガーだけが書き、印を立てた取引の値を持つ。
      トリガーは ENABLE ALWAYS で、複製の適用と取り込み（session_replication_role が replica）でも動く。読みは印が立っていれば列の値を返す
      （xmin に頼らない。セーブポイントの中の書き込みと、表の写し直しのあとも消えない）。
      新 API は、書いた行をトリガーがその取引で印したか（stamped_xid）を書いたあとの読みで確かめ、印が無ければ全部を戻して 503 にする。
      servedAt は DB の時計で、まだコミットしていない書き手の取引の始まりより後にしない。読みの取引の写しが決まる前に、取引の外の文で取る。
      要求の取引の最初の文で、鍵のハッシュを取引の設定 app.key_hash に置く（本番の RLS が店を引く値）。since は直近 15 分（架空）まで。起点は API の鍵で署名し、日付（日本時間）に結びつける。
      読みは列を名前で並べる（表に列を足しても、準備済みの文の結果の形が変わらない）。
      鍵は端末ごとに sessions の 1 行で、ほかの端末の鍵を失効させない。DB の利用者の権限の正は samples/api/db-access.json。
HTTP: 要求の行・見出し・本文の全体を、最初の 1 バイトから 5 秒で読み終えない要求は 400 にして接続を切る（recv 1 回ごとではない）。
      応答も全体を 5 秒で書き終えなければ、何も書き足さずに切る。Transfer-Encoding の付いた要求も 400。同時の接続は 64 まで。
      上限に達したら、要求を読み終えていない接続か応答を書き終えていない接続のうち最も古いものを切って席を空ける
      （黙った接続と、応答を読まない接続で席を埋めて止めさせない）。API の lock を待つ時間も 8 秒の打ち切りに入れる。
      利用者ごとの同時の要求は 8 本（架空）までで、超えた要求は lock を待たずに 503（lock を待つ接続で席を埋めさせない）。
      数える単位は確かめた鍵の利用者（鍵を何本発行しても 8 本）。写しに無い鍵は、API の lock の外の読みだけの接続で sessions を引いて確かめ、写しに足す。GET と POST のほかのメソッドと、http.server が自分で断る誤り
      （壊れた要求の行、長すぎる URI、多すぎる見出し）も、エラーの 4 点・no-store・要約のログの 1 行を通す。
使い方: make_api(n_orders) で API を作り、api.handle(method, path, headers, body) で呼ぶ。make_server(api, host, port) で HTTP に載せる。
        n_orders が 29 なら見本の画面と同じ 29 行。少なければ先頭から n 行、多ければ作り物の注文を足す（乱数の種は固定）。
"""
import base64
import datetime as dt
import hashlib
import hmac
import http.server
import io
import json
import pathlib
import random
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
SEED = HERE / "seed-orders.json"
JST = dt.timezone(dt.timedelta(hours=9))
SCENE = dt.datetime(2026, 11, 6, 9, 52, tzinfo=JST)  # 見本の画面の場面。時計はここから実時間で進む
PAGE_DEFAULT, PAGE_MAX = 24, 100
IDEM_KEEP_HOURS = 24
DEADLINE_S = 8.0  # API 自身の打ち切り（実装計画の要望 7）
TOKEN_PREFIX = "sample-token-"  # 見本の作り物の鍵の頭。続きは API を作るたびの乱数。本物の鍵はここに置かない
TOKEN_HOURS = 12  # 鍵の期限（架空）
SINCE_OVERLAP_S = 10.0  # since の重ね幅（DB の時計の粒と、読みの取引の始まりから文までの差の余裕）。遅れてコミットする長い取引は、
# servedAt をその取引の始まりより後にしないこと（SERVED_SQL）で拾う。旧 API と移行の利用者に取引の上限は掛けない（db-access.json の sinceOverlap）
MAX_BODY = 16384  # 書き込みの本文の上限（バイト）。100 件の注文番号は 1.2KB ほど
KEY_RX = re.compile(r"[A-Za-z0-9_-]{8,64}")
ID_RX = re.compile(r"[0-9]{6,12}")  # 注文番号。全店で 1 つの主キーなので、6 桁で尽きないよう 12 桁まで受ける
LIMIT_RX = re.compile(r"[0-9]{1,3}")
LEN_RX = re.compile(r"[0-9]{1,9}")
TS_RX = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")
Q_MAX = 64
WRITE_TIMEOUT_S = 5.0  # 応答 1 つを書き終える時間の上限（全体で 1 つ。send 1 回ごとではない）
SINCE_WINDOW_S = 900.0  # since に受ける最も古い時刻（いまから 15 分前。架空）。画面は 30 秒ごとに呼ぶ。古い since は 400 で、画面は一覧を読み直す
METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "-")  # ログに書くメソッドの語。ほかは OTHER
READ_TIMEOUT_S = 5.0  # 要求 1 つを読み終える時間の上限（最初の 1 バイトから、要求の行・見出し・本文の全体）と、次の要求を待つ時間の上限
MAX_CONN = 64  # 同時の接続の上限。超えた接続は読まずに切り、ログに 1 行
PER_KEY_INFLIGHT = 8  # 利用者ごとの同時の要求の上限（架空）。超えた要求は lock を待たずに 503。確かめた鍵はその利用者ごとに数え
# （端末ごとに鍵を何本発行しても、1 人で 8 本）、作り物の鍵と鍵の無い要求は 1 つの単位にまとめて数える（毎回違う作り物の鍵で上限を抜けさせない）
ZERO_TRACE, ZERO_SPAN = "0" * 32, "0" * 16  # W3C Trace Context で無効な値
GROUPS = ["action", "late", "ready", "pending"]
VIEWS = ("today", "mine", "pending-all", "shipped")
FILTER_KEYS = ("view", "status", "staff", "carrier", "payment", "q", "since")  # 起点はこの条件と結びつく

# エラーの表。コード → (状態番号, 分類, 原因, 対処)。画面仕様の 8 コードのうち OFFLINE は端末の側で決めるので API に無い。
# 一括の 3 コードは画面仕様の表と同じ文で、{n} と {m} に件数を入れる。1 件だけの文は ERRORS_ONE にある。
# ORDER_CANCEL_NOT_ALLOWED の対処だけは画面仕様と違う。出荷指示を戻す API が無いので、できない操作を指示しない（計画の未確定 5）
ERRORS = {
    "ORDER_LIST_UPSTREAM_SLOW": (503, "upstream", "注文一覧を読み込めませんでした", "しばらく待ってから、もう一度読み込んでください"),
    "ORDER_LIST_INTERNAL": (500, "internal", "問題が発生し、注文一覧を表示できませんでした", "お問い合わせ番号を添えて、お問い合わせください"),
    "ORDER_SHIP_PARTIAL": (409, "conflict", "{n} 件のうち {m} 件を出荷指示にできませんでした", "残った {m} 件を選び直して、もう一度出荷指示してください"),
    "ORDER_ALREADY_SHIPPED": (409, "conflict", "{n} 件のうち {m} 件は、ほかの担当者が先に出荷指示していました",
                              "先に押した人の検印を付けたので、出荷指示をやり直す必要はありません"),
    "ORDER_CANCEL_NOT_ALLOWED": (409, "conflict", "{n} 件のうち {m} 件は出荷指示済みのため、取り消せませんでした",
                                 "出荷指示済みの注文の取り消しは、店の責任者に相談してください"),
    "ORDER_NOT_FOUND": (404, "not_found", "この注文は見つかりませんでした", "注文番号を確かめて、一覧から開き直してください"),
    "ORDER_DETAIL_UPSTREAM_SLOW": (503, "upstream", "この注文を読み込めませんでした", "一覧に戻って、もう一度開いてください"),
    "AUTH_REQUIRED": (401, "auth", "利用者を確かめられませんでした", "もう一度ログインしてください"),
    "FORBIDDEN_ROLE": (403, "permission", "この操作の権限がありません", "運営担当者に依頼してください"),
    "INVALID_REQUEST": (400, "validation", "要求の形が契約と違います", "契約のとおりに直して送ってください"),
    "IDEMPOTENCY_KEY_REQUIRED": (400, "validation", "冪等キーがありません", "冪等キーを付けて送ってください"),
    "IDEMPOTENCY_KEY_MISMATCH": (422, "validation", "同じ冪等キーで違う内容が送られました", "新しい冪等キーで送り直してください"),
    "ORDER_WRITE_INTERNAL": (500, "internal", "問題が発生し、変更を保存できませんでした", "お問い合わせ番号を添えて、お問い合わせください"),
    # 何も書かずに断った書き込み（利用者ごとの同時の要求の上限、lock と行の鍵の待ちの打ち切り）。冪等キーも取らないので、同じキーで送り直せる
    "ORDER_WRITE_UNAVAILABLE": (503, "upstream", "いまは変更を受け付けられませんでした", "しばらく待ってから、同じ操作をもう一度してください"),
    # 新 API の書き込みを止めた（戻し。機能フラグで画面を旧 API に戻した）。送り直しても通らないので、画面を読み込み直させて旧画面に移す
    "ORDER_WRITE_DISABLED": (503, "upstream", "この画面からの変更は、いま止めています", "画面を読み込み直してから、もう一度操作してください"),
}
ERRORS_ONE = {  # 1 件だけのときの原因の文（画面仕様のとおり）
    "ORDER_ALREADY_SHIPPED": "この注文は、ほかの担当者が先に出荷指示していました",
    "ORDER_CANCEL_NOT_ALLOWED": "この注文は出荷指示済みのため、取り消せません",
}

# 移行の前の表（旧 API が読み書きしている形）。取り消しの正は is_cancelled で、移行のあとも同じ意味のまま持つ。
# status に 'cancelled' は無い（取り消しで status は動かない。決済の通知は取り消し中の決済待ちも出荷可に移す）
LEGACY_SCHEMA = """
CREATE TABLE shops (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE users (id TEXT PRIMARY KEY, shop_id TEXT NOT NULL REFERENCES shops(id), name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('operator','viewer')));
CREATE TABLE customers (id INTEGER PRIMARY KEY, shop_id TEXT NOT NULL, name TEXT NOT NULL, postal TEXT, address TEXT);
CREATE TABLE orders (id TEXT PRIMARY KEY, shop_id TEXT NOT NULL REFERENCES shops(id), customer_id INTEGER NOT NULL REFERENCES customers(id),
  status TEXT NOT NULL CHECK (status IN ('action','ready','pending','shipped','delivered')),
  alert TEXT, amount_yen INTEGER NOT NULL CHECK (amount_yen >= 0), carrier TEXT NOT NULL, payment TEXT NOT NULL,
  staff_id TEXT REFERENCES users(id), ordered_at TEXT NOT NULL, ship_due TEXT NOT NULL,
  shipped_by TEXT REFERENCES users(id), shipped_at TEXT, note TEXT, parcel TEXT, fragile INTEGER NOT NULL DEFAULT 0,
  is_cancelled INTEGER NOT NULL DEFAULT 0 CHECK (is_cancelled IN (0, 1)));
CREATE TABLE order_items (order_id TEXT NOT NULL REFERENCES orders(id), line INTEGER NOT NULL, name TEXT NOT NULL,
  qty INTEGER NOT NULL, amount_yen INTEGER NOT NULL, tax_rate INTEGER NOT NULL, PRIMARY KEY (order_id, line));
CREATE TABLE order_events (order_id TEXT NOT NULL REFERENCES orders(id), at TEXT NOT NULL, kind TEXT NOT NULL, actor TEXT);
CREATE INDEX order_events_order ON order_events (order_id, at);
"""

# 変化の記録（changed_at）と取り消しの人と時刻（cancelled_at・cancelled_by）は、トリガーだけが書く。API の文は書かない。
# トリガーは書いた取引の番号（stamped_xid。本番は pg_current_xact_id()、見本は xact_id()）も行に残す。新 API は書いた行のこの番号を確かめる。
# 見本の sqlite は AFTER のトリガーで書き直す（本番は BEFORE で NEW を変える）。トリガーの文には、足した時刻（feed_since）を印として入れる。
# トリガーは移行のあいだ外さない。それでも外された場合に備え、since は鍵を読む文でトリガーの有無とその時刻を読み、無ければ 503、
# 足した時刻より前の since は 400 にする（トリガーの無かったあいだの変化を取りこぼさせない。画面は一覧を読み直す）
FEED_TRIGGERS = ("orders_touch", "orders_touch_insert", "orders_cancel_stamp")
FEED_SINCE_SAMPLE = "2026-11-05T00:00:00.000000Z"  # 見本の DB でトリガーを足した時刻（架空。見本の場面より前）
# 前も後も 2 日より前（今日の始まりの 2 日前）に出荷した済か配達済みの行の書き込みと、値の変わらない書き込みは、changed_at を進めない。
# 旧 API の一括（過去の済の行の配達済みへの移しや、列の一括の直し）で since をあふれさせない。2 日の幅は、本番で出荷の時刻の型と字の形
# （timestamp、時差の無い字、DateStyle）を読み違えても、今日と昨日の出荷を「過去」と判じないための幅。印の立て下ろしは必ず進める
# （前の日に出荷した行に客の取り消しが立ったら、since で画面に届ける）
_DAY0 = "strftime('%Y-%m-%dT%H:%M:%S.000000Z', date(now_utc(), '+9 hours', '-2 days'), '-9 hours')"
_SEEN_COLS = ("shop_id", "customer_id", "status", "alert", "amount_yen", "carrier", "payment", "staff_id", "ordered_at", "ship_due",
              "shipped_by", "shipped_at", "note", "parcel", "fragile", "is_cancelled")


def _old_row(p):  # 2 日より前に出荷した済か配達済みの行
    return f"({p}.status IN ('shipped','delivered') AND COALESCE({p}.shipped_at, '') < {_DAY0})"


def feed_sqlite(feed_since):
    """段 2 の見本の文（sqlite）。feed_since はトリガーを足した時刻で、トリガーの文に印として入る"""
    mark = f"/* feed_since={feed_since} */"
    changed = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in _SEEN_COLS)
    return [f"CREATE TRIGGER orders_touch AFTER UPDATE ON orders {mark} WHEN NEW.changed_at IS OLD.changed_at AND ({changed})"
            f" AND (NEW.is_cancelled IS NOT OLD.is_cancelled OR NOT ({_old_row('OLD')} AND {_old_row('NEW')})) BEGIN UPDATE orders SET changed_at = now_utc(), stamped_xid = xact_id()"
            " WHERE id = NEW.id; END",
            f"CREATE TRIGGER orders_touch_insert AFTER INSERT ON orders {mark} WHEN NEW.changed_at IS NULL"
            f" AND (NEW.is_cancelled = 1 OR NOT {_old_row('NEW')})"
            " BEGIN UPDATE orders SET changed_at = now_utc(), stamped_xid = xact_id() WHERE id = NEW.id; END",
            # 印を立てたら、時刻を今にし、人を要求の鍵（app.key_hash）から引く。旧 API は鍵を置かないので人は null。印を下ろしたら両方を消す
            f"CREATE TRIGGER orders_cancel_stamp AFTER UPDATE OF is_cancelled ON orders {mark} WHEN NEW.is_cancelled IS NOT OLD.is_cancelled"
            " BEGIN UPDATE orders SET cancelled_at = CASE WHEN NEW.is_cancelled = 1 THEN now_utc() END,"
            " cancelled_by = CASE WHEN NEW.is_cancelled = 1 THEN (SELECT s.user_id FROM sessions s"
            " WHERE s.token_sha256 = current_setting('app.key_hash')) END, stamped_xid = xact_id() WHERE id = NEW.id; END"]


# トリガーの有無と足した時刻を読む部分の問い合わせ（since だけが使う）。鍵を読む文に入れるので、問い合わせの数は増えない。
# 本番は FEED_PG（pg_trigger と、段 2 の取引で付けた注釈）。見本は sqlite_master のトリガーの文の印
FEED_SQL = ("(SELECT CASE WHEN COUNT(*) = 3 AND MIN(f) = MAX(f) THEN MIN(f) END FROM (SELECT substr(sql, instr(sql, 'feed_since=') + 11, 27) AS f"
            " FROM sqlite_master WHERE type = 'trigger' AND name IN ('orders_touch', 'orders_touch_insert', 'orders_cancel_stamp')"
            " AND instr(sql, 'feed_since=') > 0))")
FEED_PG = ("(SELECT obj_description(t.oid, 'pg_trigger') FROM pg_trigger t WHERE t.tgrelid = 'public.orders'::regclass"
           " AND t.tgname = 'orders_before_write' AND t.tgenabled = 'A')")
# servedAt。まだコミットしていない orders の書き手の取引の始まりより後にしない（長い取引が遅れてコミットした行も、次の since に入る）。
# 書き手に取引の上限を掛けずに済む。読みの取引を始める前に、取引の外の 1 つの文で読む（写しが決まってから horizon を読むと、
# そのあいだにコミットした取引が、写しにも horizon にも出ない）。本番は SERVED_PG、見本は write_horizon()（試験が開いた取引を写す）。
# 関数 orders_write_horizon の定義はインフラの samples/infra/db/roles.sql の 1 つだけ（持ち主、指紋、書き手の一覧もそこで決まる）
SERVED_SQL = "COALESCE(MIN(now_utc(), write_horizon()), now_utc())"
SERVED_PG = "SELECT least(statement_timestamp(), public.orders_write_horizon())"
# 取り消しの人と時刻の読み。印が立っていれば列の値を返す。行の xmin とは比べない（第 12 回）。セーブポイントの中の書き込みは xmin が
# 子の取引の番号になり、表の写し直し（pg_dump からの復元、論理複製での入れ替え）では xmin が変わるので、比べると正しく書いた値まで null にし、
# 次の書き込みでトリガーが消していた。素通りの書き手は、トリガーを ENABLE ALWAYS にして無くした（replica の取り込みでも動く）
# 新 API が、書いた行をトリガーがこの取引で印したかを確かめる式（本番）。見本は stamped_xid = xact_id()
STAMPED_PG = "o.stamped_xid = pg_current_xact_id()::xid"
# users の行の制限（本番の RLS）。鍵のハッシュから引いた店の利用者だけ。鍵の利用者もこの店にいるので、鍵の引き当ては 0 行にならない。
# 注文の 3 列からの EXISTS（行ごとに店の注文をなめる）にしない（第 10 回の高 15）
USERS_POLICY_PG = "shop_id::text = public.app_key_shop()"
# 冪等キーを先に取る文。同じキーの 2 本目は 1 本目のコミットを待ち、誤りを出さずに 0 行を返す（取引を戻さず、鍵のハッシュも消えない。
# DB のログに主キーの重複の誤りと冪等キーの値も出ない）。
# 書き込みの取引で店の古いキーを消さない（第 12 回。消した行の鍵で、同じ店の関係の無い書き込みが 1 本目のコミットを待っていた）。
# 古いキーは掃除の仕事（purge_expired。本番は別の利用者）が取引の外で消し、読みは保持の期間の中のキーだけを見る。
# 保持の期間を過ぎた同じキーの行が残っていれば、RECLAIM_SQL でその 1 行（自分の店・自分・同じキー）だけを消してから取り直す
CLAIM_SQL = "INSERT INTO idempotency VALUES (?, ?, ?, ?, 0, '', ?) ON CONFLICT DO NOTHING RETURNING key"
RECLAIM_SQL = "DELETE FROM idempotency WHERE shop_id = ? AND user_id = ? AND key = ? AND created_at < ?"

# インフラの roles.sql が RLS を有効にする前に流す確かめ。表の持ち主でも BYPASSRLS でもなく、orders の表を読み書きする利用者に、
# 全行の方針（USING (true)）と、明示の CONNECT が無ければ止める。無いまま有効にすると、旧 API の取り消しと決済が黙って 0 行になる。
# 書き手は列の単位の権限（GRANT UPDATE (is_cancelled) ON orders）でも見つける（has_any_column_privilege。第 12 回の重大）
RLS_PREFLIGHT_PG = """DO $$
DECLARE r record;
BEGIN
  -- 1. 表を読み書きする役割に、全行の方針があるか。除くのは orders_api（店の方針を持つ）、既定の役割と rds の役割（名前が pg_ か rds で始まる）、
  --    上の権限、BYPASSRLS、表の持ち主とその一員（RLS を受けない）。既定の役割を付けた利用者（バックアップなど）は除かない
  FOR r IN
    SELECT c.relname, g.rolname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
    CROSS JOIN pg_roles g
    WHERE c.relname = ANY (ARRAY['orders', 'order_items', 'order_events', 'customers', 'users', 'sessions', 'idempotency'])
      AND g.rolname <> 'orders_api' AND g.rolname !~ '^(pg_|rds)' AND NOT g.rolsuper AND NOT g.rolbypassrls
      AND NOT pg_has_role(g.oid, c.relowner, 'USAGE')
      AND (has_any_column_privilege(g.oid, c.oid, 'SELECT') OR has_any_column_privilege(g.oid, c.oid, 'INSERT')
           OR has_any_column_privilege(g.oid, c.oid, 'UPDATE') OR has_any_column_privilege(g.oid, c.oid, 'REFERENCES')
           OR has_table_privilege(g.oid, c.oid, 'DELETE') OR has_table_privilege(g.oid, c.oid, 'TRUNCATE'))
      AND NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid AND p.polpermissive AND p.polcmd = '*'
                      AND (g.oid = ANY (p.polroles)) AND pg_get_expr(p.polqual, p.polrelid) = 'true')
  LOOP
    RAISE EXCEPTION 'role % uses table % without an all-rows policy; enabling RLS would turn its reads and writes into 0 rows', r.rolname, r.relname;
  END LOOP;
  -- 2. この DB を使う入れる役割に、PUBLIC からでない CONNECT があるか。使う役割は、public の表のどれかに権限を持つ役割（既定の役割を通す
  --    バックアップを含む）と、監視の役割（pg_monitor の一員）。DB の持ち主は既定の CONNECT を持つ
  FOR r IN
    SELECT g.rolname FROM pg_roles g
    WHERE g.rolcanlogin AND NOT g.rolsuper AND g.rolname !~ '^(pg_|rds)'
      AND (pg_has_role(g.oid, 'pg_monitor', 'MEMBER')
           OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
                      WHERE c.relkind IN ('r', 'p') AND (has_any_column_privilege(g.oid, c.oid, 'SELECT')
                                                         OR has_any_column_privilege(g.oid, c.oid, 'INSERT')
                                                         OR has_any_column_privilege(g.oid, c.oid, 'UPDATE')
                                                         OR has_table_privilege(g.oid, c.oid, 'DELETE'))))
      AND NOT EXISTS (SELECT 1 FROM pg_database d, aclexplode(coalesce(d.datacl, acldefault('d', d.datdba))) a
                      WHERE d.datname = current_database() AND a.privilege_type = 'CONNECT' AND a.grantee <> 0
                        AND pg_has_role(g.oid, a.grantee, 'MEMBER'))
  LOOP
    RAISE EXCEPTION 'role % uses this database but has no explicit CONNECT; revoking CONNECT from PUBLIC would lock it out', r.rolname;
  END LOOP;
END
$$"""

# 移行の段。どれも意味を変えない足し算で、旧 API の書き込みの結果を変えない（試験 test_additive_steps_keep_every_legacy_writer_working と、
# PostgreSQL で列の型を変えて流す test_pg_added_objects_never_change_legacy_writers）。
# 足した物（列、表、トリガー、索引）は移行のあいだ外さない。戻すのは新 API の機能フラグと、新 API の書き込みだけ（back）。
# 足す物は旧い書き手を変えない形に限る。旧い書き手の文を断らない（外部キーと CHECK を足さない。users への外部キーは ON DELETE CASCADE）、
# 列の型を前提にしない（トリガーは行と値を字にして比べ、時刻は読めるときだけ読む。どこで失敗しても書き込みを止めない）、
# 旧い書き手の値を書き換えない（トリガーが書くのは足した 4 列だけ）。
# pg は本番（PostgreSQL）の文。runAs は流す利用者で、どの段も orders の今の持ち主（段 0 で調べる。旧 API の側）が流す。
# 表の定義を変える文は 1 つの取引に入れ、lock_timeout は SET LOCAL で取引の中だけに置く（セッションに残さない）。
# 索引は取引の外の CONCURRENTLY で、lock_timeout と statement_timeout を 0 に戻してから流す（長い旧い取引の終わりを待ち、INVALID を残さない。
# IF NOT EXISTS は INVALID の索引を黙って残すので使わない）。sqlite は見本が流す同じ意味の文。
# stop は止めたときの状態、back は戻し方、verify は確かめ方（計画の「データと移行」の表と同じ）
_PG_STAMP = """CREATE OR REPLACE FUNCTION orders_before_write() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
  now_c timestamptz := clock_timestamp();
  -- 過去の済の境。今日（日本時間）の始まりの 2 日前。出荷の時刻の型と字の形（timestamp、時差の無い字、DateStyle）を読み違えても、
  -- 今日と昨日の出荷を過去と判じない幅
  edge timestamptz := (date_trunc('day', clock_timestamp() AT TIME ZONE 'Asia/Tokyo') AT TIME ZONE 'Asia/Tokyo') - interval '2 days';
  k text := current_setting('app.key_hash', true);
  replica boolean := current_setting('session_replication_role') = 'replica';
  same boolean;
  marked boolean := NEW.is_cancelled::text IN ('1', 'true');
  flipped boolean := false;
  settled boolean := false;
BEGIN
  -- 列の型を前提にしない。行は字にして比べ（等しさの演算子の無い型の列があっても比べられる。足した列を書く前に比べる）、
  -- 印と状態と時刻も字で読む（印が整数でも boolean でも、時刻が文字でも timestamp でも timestamptz でも、書き込みを止めない）
  IF TG_OP = 'UPDATE' THEN
    -- 論理複製の適用（replica）が、元の DB のトリガーの書いた値を運んできた行は、そのまま入れる。運んでいない replica の書き手
    -- （取り込み）は、ふつうの書き手と同じに扱う（トリガーは ENABLE ALWAYS なので、replica でも動く）
    IF replica AND (NEW.cancelled_at IS DISTINCT FROM OLD.cancelled_at OR NEW.cancelled_by IS DISTINCT FROM OLD.cancelled_by
                    OR NEW.changed_at IS DISTINCT FROM OLD.changed_at) THEN
      RETURN NEW;
    END IF;
    same := NEW::text = OLD::text;
    flipped := NEW.is_cancelled::text IS DISTINCT FROM OLD.is_cancelled::text;
    IF flipped THEN
      -- 印を立てた取引で、時刻と人（要求の鍵から引く。旧 API は鍵を置かないので null）を書く。下ろしたら両方を消す
      NEW.cancelled_at := CASE WHEN marked THEN now_c END;
      NEW.cancelled_by := CASE WHEN marked AND k <> '' THEN (SELECT s.user_id FROM public.sessions s WHERE s.token_sha256 = k) END;
    ELSIF marked THEN
      -- 印が変わらなければ、印を立てた取引の値を引き継ぐ（書き手がこの 2 列に書いても上書きする）。xmin とは比べない
      NEW.cancelled_at := OLD.cancelled_at; NEW.cancelled_by := OLD.cancelled_by;
    ELSE
      NEW.cancelled_at := NULL; NEW.cancelled_by := NULL;
    END IF;
    IF NOT same AND NOT flipped AND OLD.status::text IN ('shipped', 'delivered') AND NEW.status::text IN ('shipped', 'delivered') THEN
      BEGIN  -- 前も後も 2 日より前に出荷した行。読めないときと、どこかで失敗したときは進める側にする
        settled := OLD.shipped_at::text::timestamptz < edge AND NEW.shipped_at::text::timestamptz < edge;
      EXCEPTION WHEN OTHERS THEN settled := false;
      END;
    END IF;
    NEW.changed_at := CASE WHEN same OR coalesce(settled, false) THEN OLD.changed_at ELSE now_c END;
  ELSE
    IF replica AND (NEW.cancelled_at IS NOT NULL OR NEW.cancelled_by IS NOT NULL OR NEW.changed_at IS NOT NULL) THEN
      RETURN NEW;  -- 論理複製の初めの写し（COPY）が運んできた値
    END IF;
    NEW.cancelled_at := CASE WHEN marked THEN now_c END;
    NEW.cancelled_by := CASE WHEN marked AND k <> '' THEN (SELECT s.user_id FROM public.sessions s WHERE s.token_sha256 = k) END;
    IF NOT marked AND NEW.status::text IN ('shipped', 'delivered') THEN
      BEGIN
        settled := NEW.shipped_at::text::timestamptz < edge;
      EXCEPTION WHEN OTHERS THEN settled := false;
      END;
    END IF;
    NEW.changed_at := CASE WHEN coalesce(settled, false) THEN NULL ELSE now_c END;
  END IF;
  NEW.stamped_xid := pg_current_xact_id()::xid;  -- この取引のトリガーが通った。新 API は書いたあとに確かめる（トリガーが止められていないか）
  RETURN NEW;
END $$"""
_PG_FEED_NOTE = ("DO $$ BEGIN EXECUTE format('COMMENT ON TRIGGER orders_before_write ON orders IS %L',"
                 " to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')); END $$")
_KEEP = "外さない（移行が終わるまで残す）。戻すのは新 API の機能フラグと、新 API の書き込み（止めると 503）だけ"
ADDITIONS = [
    {"step": "1", "runAs": "owner", "what": "列 cancelled_at・cancelled_by・changed_at・stamped_xid と、表 sessions・idempotency を足す",
     "pg": ["BEGIN", "SET LOCAL lock_timeout = '2s'",
            "ALTER TABLE orders ADD COLUMN cancelled_at timestamptz, ADD COLUMN cancelled_by text, ADD COLUMN changed_at timestamptz,"
            " ADD COLUMN stamped_xid xid",
            "CREATE TABLE sessions (token_sha256 text PRIMARY KEY, user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
            " expires_at timestamptz NOT NULL)",
            "CREATE INDEX sessions_user ON sessions (user_id)",
            "CREATE TABLE idempotency (shop_id text NOT NULL, user_id text NOT NULL, key text NOT NULL, request_sha256 text NOT NULL,"
            " status int NOT NULL, body text NOT NULL, created_at timestamptz NOT NULL, PRIMARY KEY (shop_id, user_id, key))",
            "CREATE INDEX idempotency_created ON idempotency (created_at)", "COMMIT"],
     "sqlite": ["ALTER TABLE orders ADD COLUMN cancelled_at TEXT",
                "ALTER TABLE orders ADD COLUMN cancelled_by TEXT",
                "ALTER TABLE orders ADD COLUMN changed_at TEXT",
                "ALTER TABLE orders ADD COLUMN stamped_xid INTEGER",
                "CREATE TABLE sessions (token_sha256 TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
                " expires_at TEXT NOT NULL)",
                "CREATE INDEX sessions_user ON sessions (user_id)",
                "CREATE TABLE idempotency (shop_id TEXT NOT NULL, user_id TEXT NOT NULL, key TEXT NOT NULL, request_sha256 TEXT NOT NULL,"
                " status INTEGER NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (shop_id, user_id, key))",
                "CREATE INDEX idempotency_created ON idempotency (created_at)"],
     "stop": "安全。足した列は null のまま誰も読まない。列の数に頼る読み手と書き手は、段 0 の 4 つ目で先に直す",
     "back": _KEEP + "。列を消すのは、旧い書き手を全部移したあとの別の計画",
     "verify": "列の定義を information_schema で読む。旧 API の書き込みの試験と、列の数に頼る読み手（段 0 の調べ）の試験を流す"},
    {"step": "2", "runAs": "owner", "what": "changed_at を進め、取り消しの人と時刻と、書いた取引の番号を書くトリガーを、足した時刻の注釈と 1 つの取引で足す",
     "pg": ["BEGIN", "SET LOCAL lock_timeout = '2s'", _PG_STAMP,
            "CREATE TRIGGER orders_before_write BEFORE INSERT OR UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION orders_before_write()",
            # replica の取り込みと論理複製の適用でも動かす（素通りの書き手を作らない）
            "ALTER TABLE orders ENABLE ALWAYS TRIGGER orders_before_write",
            _PG_FEED_NOTE, "COMMIT"],
     "sqlite": feed_sqlite(FEED_SINCE_SAMPLE),
     "stop": "安全。足した 4 列だけを書き、旧い列と書き込みの成否を変えない。列の型を前提にせず、判じられない時刻は changed_at を進める側にする。"
             "ENABLE ALWAYS なので、replica の取り込みと論理複製の適用でも動く",
     "back": _KEEP,
     "verify": "検証の環境で 1 行を書き、changed_at と stamped_xid が進むことを読む。トリガーの注釈に時刻があり、tgenabled が A。旧 API の書き込みの試験を流す"},
    {"step": "3", "runAs": "owner", "what": "一覧・since・過去の注文・出荷のあとの取り消しの索引を足す",
     "pg": ["SET lock_timeout = 0", "SET statement_timeout = 0",
            "CREATE INDEX CONCURRENTLY orders_today ON orders (shop_id, status, ship_due, ordered_at, id)",
            "CREATE INDEX CONCURRENTLY orders_shipped ON orders (shop_id, status, shipped_at)",
            "CREATE INDEX CONCURRENTLY orders_changed ON orders (shop_id, changed_at)",
            "CREATE INDEX CONCURRENTLY orders_customer ON orders (customer_id, ordered_at)",
            "CREATE INDEX CONCURRENTLY orders_marked ON orders (shop_id, is_cancelled, status, ship_due)"],
     "sqlite": ["CREATE INDEX orders_today ON orders (shop_id, status, ship_due, ordered_at, id)",
                "CREATE INDEX orders_shipped ON orders (shop_id, status, shipped_at)",
                "CREATE INDEX orders_changed ON orders (shop_id, changed_at)",
                "CREATE INDEX orders_customer ON orders (customer_id, ordered_at)",
                "CREATE INDEX orders_marked ON orders (shop_id, is_cancelled, status, ship_due)"],
     "stop": "安全。作りかけの索引は INVALID のまま使われない。長い旧い取引の終わりを待つ（書き込みは止めない）",
     "back": _KEEP + "。作りかけで止めた INVALID の索引だけは、DROP INDEX CONCURRENTLY で消してから流し直す（同じ名前があると CREATE は失敗して止まる）",
     "verify": "pg_index の indisvalid が 5 つとも true。作る時間と書き込みの p99 を見る"},
]
SCHEMA = LEGACY_SCHEMA + "".join(s + ";\n" for step in ADDITIONS for s in step["sqlite"])
# 読む列は名前で並べる。表に列を足しても、準備済みの文の結果の形が変わらない（SELECT o.* を使わない）
ORDER_COLS = ("id", "shop_id", "customer_id", "status", "alert", "amount_yen", "carrier", "payment", "staff_id", "ordered_at", "ship_due",
              "shipped_by", "shipped_at", "is_cancelled", "cancelled_by", "cancelled_at", "note", "parcel", "fragile", "changed_at")


def cols(alias=""):
    return ", ".join(alias + c for c in ORDER_COLS)


# 行が今どの保存ビューに入るか（呼び手から見て）。取消の行はどのビューにも入らない。今日出荷と自分の担当は、今日の済の行も入る
# 出荷したあとに旧 API が印を立てた行（旧 API の取り消しの文は status を条件に持たない）は、取消でなく済のまま数え、済のビューに残す。
# 荷物は出ていくので、画面から消すと誰も止められない。前の日までに出荷した行も、出荷済み（shipped）のあいだは今日の済のビューに残す
# （第 12 回。夕方の出荷指示を翌朝に倉庫が出す運用で、夜の取り消しを朝の画面に出す）。行の cancelledAfterShip で知らせる
SHIPPED_SEEN = "(o.shipped_at >= :day_start OR o.is_cancelled = 1)"  # 済のビューに入る済の行（今日の出荷と、出荷のあとに取り消された行）
IN_VIEWS_SQL = ("CASE WHEN o.ship_due <= :today AND ((o.status IN ('action','ready','pending') AND o.is_cancelled = 0)"
                f" OR (o.status = 'shipped' AND {SHIPPED_SEEN})) THEN 1 ELSE 0 END AS in_today,"
                " CASE WHEN o.ship_due <= :today AND o.staff_id = :me AND ((o.status IN ('action','ready','pending') AND o.is_cancelled = 0)"
                f" OR (o.status = 'shipped' AND {SHIPPED_SEEN})) THEN 1 ELSE 0 END AS in_mine,"
                " CASE WHEN o.is_cancelled = 0 AND o.status = 'pending' THEN 1 ELSE 0 END AS in_pending,"
                f" CASE WHEN o.status = 'shipped' AND {SHIPPED_SEEN} THEN 1 ELSE 0 END AS in_shipped")
# 出荷のあとに取り消された、前の日までの済の行（索引 orders_marked で引く。過去の済の行の量によらない）
LATE_MARK_ROWS = ("shop_id = :shop AND is_cancelled = 1 AND status = 'shipped' AND (shipped_at < :day_start OR shipped_at IS NULL)")
OUT_COLS = ORDER_COLS + ("customer_name", "staff_name", "shipped_name", "cancelled_name", "grp_rank", "next_key",
                         "in_today", "in_mine", "in_pending", "in_shipped")
# タブの件数。ビューごとに索引で引ける部分の問い合わせに分ける。今日出荷と自分の担当のタブは未出荷だけを数える
VIEW_COUNTS_SQL = ("(SELECT COUNT(*) FROM orders WHERE shop_id = :shop AND status IN ('action','ready','pending') AND is_cancelled = 0"
                   " AND ship_due <= :today) AS vc_today,"
                   " (SELECT COUNT(*) FROM orders WHERE shop_id = :shop AND status IN ('action','ready','pending') AND is_cancelled = 0"
                   " AND ship_due <= :today AND staff_id = :me) AS vc_mine,"
                   " (SELECT COUNT(*) FROM orders WHERE shop_id = :shop AND status = 'pending' AND is_cancelled = 0) AS vc_pending,"
                   " ((SELECT COUNT(*) FROM orders WHERE shop_id = :shop AND status = 'shipped' AND shipped_at >= :day_start)"
                   f" + (SELECT COUNT(*) FROM orders WHERE {LATE_MARK_ROWS})) AS vc_shipped")
VIEW_COUNT_COLS = "n.vc_today, n.vc_mine, n.vc_pending, n.vc_shipped"


def utc(local: str) -> str:
    """'2026-11-06 09:17'（日本時間）→ '2026-11-06T00:17:00Z'"""
    t = dt.datetime.strptime(local, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    return iso(t)


def iso(t: dt.datetime) -> str:
    """UTC の固定幅の文字列（マイクロ秒まで）。文字列の大小が時刻の前後と一致する"""
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def load_seed(conn, n_orders: int, tokens: dict, expires_at: str):
    """tokens に利用者ごとの作り物の鍵（乱数）を入れる。DB には鍵のハッシュだけを置く"""
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    conn.executemany("INSERT INTO shops VALUES (?, ?)", [(s["id"], s["name"]) for s in seed["shops"]])
    for u in seed["users"]:
        tokens[u["id"]] = TOKEN_PREFIX + secrets.token_urlsafe(24)
    conn.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", [(u["id"], u["shop"], u["name"], u["role"]) for u in seed["users"]])
    conn.executemany("INSERT INTO sessions VALUES (?, ?, ?)", [(token_hash(tokens[u["id"]]), u["id"], expires_at) for u in seed["users"]])
    rows = list(seed["orders"][:n_orders])
    rng = random.Random(20261106)
    staff = [None, None, "u-takagi", "u-mori", "u-ishii", "u-sakaguchi", "u-nomura"]
    for k in range(max(0, n_orders - len(rows))):  # 件数を増やす作り方: 作り物の注文を足す
        st = rng.choices(["ready", "action", "pending", "shipped"], [70, 10, 10, 10])[0]
        who = rng.choice(staff)
        r = {"id": str(600000 + k), "name": f"架空 顧客{k:04d}", "amount": rng.randrange(800, 40000), "carrier": rng.choice(["yamato", "sagawa", "japanpost"]),
             "payment": rng.choice(["card", "cod", "paypay", "konbini"]), "staff": who, "orderedAt": f"2026-11-0{rng.choice([4, 5, 6])} {rng.randrange(0, 9):02d}:{rng.randrange(60):02d}",
             "shipDue": rng.choice(["2026-11-05", "2026-11-06", "2026-11-06", "2026-11-06"]), "status": st,
             "alert": "address_problem" if st == "action" else None, "shippedBy": None, "shippedAt": None}
        if st == "shipped":
            r["shippedBy"], r["shippedAt"] = who or "u-takagi", "2026-11-06 09:0" + str(rng.randrange(10))
        rows.append(r)
    for r in seed["otherShopOrders"]:
        rows.append(dict(r, shop="s2", staff=None, alert=None, shippedBy=None, shippedAt=None))
    detail = seed["detail"]
    cust_of = {}
    for i, r in enumerate(rows, 1):
        d = detail.get(r["id"], {})
        conn.execute("INSERT INTO customers VALUES (?, ?, ?, ?, ?)", (i, r.get("shop", "s1"), r["name"], d.get("postal"), d.get("address")))
        cust_of[r["id"]] = i
        conn.execute("INSERT INTO orders (id, shop_id, customer_id, status, alert, amount_yen, carrier, payment, staff_id, ordered_at, ship_due,"
                     " shipped_by, shipped_at, note, parcel, fragile, changed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (r["id"], r.get("shop", "s1"), i, r["status"], r["alert"], r["amount"], r["carrier"], r["payment"], r["staff"],
                      utc(r["orderedAt"]), r["shipDue"], r["shippedBy"], utc(r["shippedAt"]) if r["shippedAt"] else None,
                      d.get("note"), d.get("parcel"), 1 if d.get("fragile") else 0, utc(r["shippedAt"] or r["orderedAt"])))
        items = d.get("items") or [{"name": "見本の商品", "qty": 1, "amount": r["amount"], "taxRate": 10}]
        conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?, ?)",
                         [(r["id"], n, it["name"], it["qty"], it["amount"], it["taxRate"]) for n, it in enumerate(items, 1)])
        hist = d.get("history") or [[r["orderedAt"], "ordered"]]
        conn.executemany("INSERT INTO order_events VALUES (?, ?, ?, NULL)", [(r["id"], utc(at), kind) for at, kind in hist])
    for p in seed["pastOrders"]:
        if p["sameCustomerAs"] in cust_of:
            conn.execute("INSERT INTO orders (id, shop_id, customer_id, status, amount_yen, carrier, payment, ordered_at, ship_due, changed_at)"
                         " VALUES (?, 's1', ?, 'delivered', ?, 'yamato', 'card', ?, ?, ?)",
                         (p["id"], cust_of[p["sameCustomerAs"]], p["amount"], utc(p["orderedAt"]), p["orderedAt"][:10], utc(p["orderedAt"])))


class Reply(Exception):
    def __init__(self, code, results=None, status=None):
        super().__init__(code)
        self.code, self.results, self.status = code, results, status


def b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode().rstrip("=")


def unb64(s: str):
    try:
        return json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))
    except Exception:  # noqa: BLE001 — 壊れた起点は 400 にする
        raise Reply("INVALID_REQUEST") from None


class OrdersApi:
    # 書き込みの 2 つの文（SET と、書く行の条件）。取り消しは旧 API と同じ印 is_cancelled を立てるだけで、status は動かさない。
    # 出荷指示は is_cancelled = 0 の行だけを書く。旧 API の文は変えない（計画の「版と段の表」）
    # 取り消しの人と時刻は書かない（トリガーが印の立て下ろしで、要求の鍵から人を引いて書く）。書いた行をトリガーが印したかは、書いたあとの読みで確かめる
    SHIP_SQL = ("status = 'shipped', shipped_by = ?, shipped_at = ?", "status IN ('ready') AND is_cancelled = 0")
    CANCEL_SQL = ("is_cancelled = 1", "status IN ('action','ready','pending') AND is_cancelled = 0")

    def __init__(self, n_orders=29, log=None, deadline_s=DEADLINE_S):
        self.t0 = time.monotonic()
        # メモリーの上の DB を 2 つの接続で共有する。self.conn は要求の取引（API の lock の中）、self.auth_conn は鍵の確かめの読みだけ
        # （lock の外。数える単位を決めるため）。本番は接続の池から別の接続を取る
        uri = f"file:orders-{secrets.token_hex(8)}?mode=memory&cache=shared"
        self.conn = sqlite3.connect(uri, uri=True, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function("now_utc", 0, self._stamp)  # トリガーが使う時計。本番は DB の時計
        # 取引の中だけの設定（本番の set_config(…, true) と current_setting の写し）。要求の取引が終わると消す
        self.settings, self.auth_settings = {}, {}
        self.open_writers = {}  # まだコミットしていない orders の書き手の取引の始まり（本番は pg_stat_activity。試験が写す）
        self.xact = 0  # 取引の番号（本番は pg_current_xact_id()）。要求の取引を始めるたびに進める
        self.writes_enabled = True  # 戻しの切り替え。偽なら新 API の書き込みを 503 で断る（足した列とトリガーは外さない）
        self._settings_fns(self.conn, self.settings)
        self.conn.create_function("write_horizon", 0, lambda: min(self.open_writers.values()) if self.open_writers else None)
        self.conn.create_function("xact_id", 0, lambda: self.xact)
        self.conn.executescript(SCHEMA)
        self.auth_conn = sqlite3.connect(uri, uri=True, check_same_thread=False, isolation_level=None)
        self._settings_fns(self.auth_conn, self.auth_settings)
        self.auth_lock = threading.Lock()
        self.tokens = {}
        self.conn.execute("BEGIN")
        load_seed(self.conn, n_orders, self.tokens, iso(self.now() + dt.timedelta(hours=TOKEN_HOURS)))
        self.conn.execute("COMMIT")
        self.lock, self.log_lock = threading.Lock(), threading.Lock()
        self.inflight, self.inflight_lock = {}, threading.Lock()  # 確かめた鍵の利用者ごとの処理中と待ちの要求の数。ほかは "-"
        # 確かめた鍵のハッシュ → (期限, 利用者の id)。lock を取らずに読める写しで、数える単位を決めるだけに使う（認可は _auth が要求の取引の中で
        # DB で行う）。写しに無い鍵は _known が auth_conn で sessions を引いて足す。ログインのサービスが DB に直に書いた鍵も、立て直したプロセスでも数えられる
        exp0 = iso(self.now() + dt.timedelta(hours=TOKEN_HOURS))
        self.known = {token_hash(t): (exp0, uid) for uid, t in self.tokens.items()}
        self.log = log if log is not None else sys.stderr
        # 起点の署名の鍵。見本は API を作るたびの乱数で、本物の鍵はファイルに置かない（本番は秘密の置き場から読む。計画の未確定 12）
        self.cursor_key = secrets.token_bytes(32)
        self.deadline_s = deadline_s
        self.deadline = float("inf")
        self.sql, self._last_stmt = 0, None
        self.conn.set_trace_callback(self._trace)

    @staticmethod
    def _settings_fns(conn, store):
        def set_config(name, value, is_local):
            store[name] = value
            return value
        conn.create_function("set_config", 3, set_config)
        conn.create_function("current_setting", -1, lambda name, *missing_ok: store.get(name))

    def _known(self, h):
        """鍵のハッシュが今の時点で確かめた鍵なら、その利用者の id を返す（ほかは None）。写しに無ければ、API の lock の外で sessions を
        1 行引き、あれば写しに足す。作り物の鍵は毎回ここで引くが、索引で 1 行を引く読みだけで、API の lock も要求の席も使わない"""
        now = self._stamp()
        with self.inflight_lock:
            got = self.known.get(h)
            if got and got[0] > now:
                return got[1]
        try:
            with self.auth_lock:  # 本番の RLS の下でも引けるよう、鍵のハッシュを取引の設定に置いてから引く
                try:
                    self.auth_conn.execute("BEGIN")
                    self.auth_conn.execute("SELECT set_config('app.key_hash', ?, 1)", (h,))
                    row = self.auth_conn.execute("SELECT expires_at, user_id FROM sessions WHERE token_sha256 = current_setting('app.key_hash')"
                                                 " AND expires_at > ?", (now,)).fetchone()
                finally:
                    if self.auth_conn.in_transaction:
                        self.auth_conn.execute("COMMIT")
                    self.auth_settings.clear()
        except sqlite3.Error:  # 引けないとき（ログインの書き込みと重なった）は、確かめていない鍵として数える
            return None
        if row is None:
            return None
        with self.inflight_lock:
            if len(self.known) > 100000:  # 写しは期限の切れたものから捨てる
                self.known = {k: v for k, v in self.known.items() if v[0] > now}
            self.known[h] = (row[0], row[1])
        return row[1]

    def token_for(self, user_id: str) -> str:
        """見本の作り物の鍵。試験と手元の確かめだけが使う"""
        return self.tokens[user_id]

    def login(self, user_id: str) -> str:
        """ログインの写し。端末ごとに新しい鍵を作り、sessions に 1 行を足す。ほかの端末の鍵は残る（本番はログインのサービスが書く）"""
        token = TOKEN_PREFIX + secrets.token_urlsafe(24)
        with self.lock, self.auth_lock:  # 共有の DB の sessions を書くあいだ、鍵の確かめの読みを待たせる
            exp = iso(self.now() + dt.timedelta(hours=TOKEN_HOURS))
            self.conn.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token_hash(token), user_id, exp))
        with self.inflight_lock:
            self.known[token_hash(token)] = (exp, user_id)
        return token

    def purge_expired(self):
        """保持の期間（24 時間）を過ぎた冪等キーを全店で消す。server.py が 10 分ごとに呼ぶ。書き込みの取引では消さない（同じ店の書き込みを
        消した行の鍵で並ばせない）。全店にまたがるので、本番は API の DB の利用者ではなく掃除の仕事が別の利用者で、短い取引で流す（計画の未確定 8）"""
        with self.lock:
            self.conn.execute("DELETE FROM idempotency WHERE created_at < ?", (self._idem_cutoff(),))

    def _idem_cutoff(self) -> str:
        return iso(self.now() - dt.timedelta(hours=IDEM_KEEP_HOURS))

    # ---- 共通
    def _trace(self, stmt):
        if stmt in ("COMMIT", "ROLLBACK"):  # 取引の中だけの設定（本番の set_config(…, true)）は、取引の終わりで消える
            self.settings.clear()
        # トリガーの発火は、親の文と同じ文字列で行ごとに届く。続けて同じ文字列が来たら数えない（値の違う N+1 は数える）
        if stmt == self._last_stmt:
            return
        self._last_stmt = stmt
        if stmt.lstrip().upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            self.sql += 1

    def now(self) -> dt.datetime:
        return SCENE.astimezone(dt.timezone.utc) + dt.timedelta(seconds=time.monotonic() - self.t0)

    def today(self) -> str:
        return self.now().astimezone(JST).strftime("%Y-%m-%d")

    def q(self, sql, args=()):
        if time.monotonic() > self.deadline:  # 打ち切りは問い合わせの前でも見る
            raise sqlite3.OperationalError("interrupted: deadline")
        return self.conn.execute(sql, args).fetchall()

    def reject(self, status, method, reason):
        """HTTP の入口が要求を読めずに断った場面（壊れた要求の行、長すぎる URI、多すぎる見出し、読み込みの時間切れ）。
        ほかの応答と同じ経路で、エラーの 4 点・no-store・要約のログの 1 行を作る。reason は決まった語だけで、要求の中身は入れない"""
        return self.handle(method or "-", "", {}, b"", body_ok=False, reject=(status, reason))

    def note_busy(self, reason="too_many_connections"):
        """同時の接続の上限で切った接続。応答は書かず、要約のログに 1 行だけ残す。
        reason は too_many_connections（新しい接続を切った）、evicted_unread（要求を読み終えていない古い接続を切って席を空けた）、
        evicted_unsent（応答を書き終えていない古い接続を切って席を空けた）、write_timeout（応答を 5 秒で書き終えずに切った）"""
        with self.log_lock:  # API の lock は取らない（重い要求の処理中も、受け付けの糸を止めない）
            self.log.write(json.dumps({"ts": self._stamp(), "traceId": None, "reqId": secrets.token_hex(8), "method": "-", "route": "unknown",
                                       "status": 503, "code": None, "reject": reason}) + "\n")

    def handle(self, method, path, headers=None, body=b"", body_ok=True, reject=None):
        """1 要求を処理し、(状態番号, 見出し, 本文の bytes) を返す。1 要求 1 行の要約をログに書く。
        body_ok が偽なら（Content-Length が負か上限を超えた、本文が時間内に届かない）、本文を読まずに 400 にする。
        reject は入口が断った場面の (状態番号, 理由の語)。"""
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        tp = headers.get("traceparent", "")
        m = re.match(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$", tp)
        valid = m is not None and m.group(1) != "ff" and m.group(2) != ZERO_TRACE and m.group(3) != ZERO_SPAN  # W3C の無効な値は使わない
        trace = m.group(2) if valid else secrets.token_hex(16)
        req_id = secrets.token_hex(8)  # 追跡番号は呼び手と共有されうるので、1 要求ごとの番号を API が別に作る
        method = method if method in METHODS else "OTHER"  # 要求の行から来る語は、決まった語にしてからログに書く
        start = time.monotonic()  # 打ち切りの時計は lock を待つ前に始める。待ちも 8 秒に入る
        ctx = {"route": "unknown", "user": None, "shop": None, "role": None, "rows": None, "replayed": False}
        # 利用者ごとの同時の要求の上限。1 人が lock の待ちを積み、接続の席を処理中のまま埋めさせない。DB を読む前に、見出しの値で数える
        # 数える単位は確かめた鍵の利用者（鍵を端末ごとに何本発行しても、1 人で 8 本。第 12 回）。確かめは _known が lock の外で sessions を引く。
        # 確かめていない鍵（作り物の鍵、期限切れ）と、鍵の形でない見出しは 1 つの単位 "-" にまとめる。毎回違う作り物の鍵を付けても、
        # "-" の 8 本を超えない。ログインのサービスが書いた正しい鍵は、写しに無くても自分の単位で数える
        # 鍵の無い相手の量そのものは、前に置くインフラの IP ごとの上限（rate-per-ip）が止める前提で、API は席を埋めさせないだけ
        km = re.match(r"^Bearer\s+(\S+)$", headers.get("authorization", ""))
        h = hashlib.sha256(km.group(1).encode()).hexdigest() if km else None
        bucket = (self._known(h) if h else None) or "-"
        with self.inflight_lock:
            busy = self.inflight.get(bucket, 0) >= PER_KEY_INFLIGHT
            if not busy:
                self.inflight[bucket] = self.inflight.get(bucket, 0) + 1
        if busy:
            ctx["route"], ctx["reject"] = self._match(method, path)[0], "too_many_inflight"
            return self._unavailable(method, trace, req_id, start, ctx)
        try:
            return self._handle_locked(method, path, headers, body, body_ok, reject, trace, req_id, start, ctx)
        finally:
            with self.inflight_lock:
                self.inflight[bucket] -= 1
                if not self.inflight[bucket]:
                    del self.inflight[bucket]

    def _unavailable(self, method, trace, req_id, start, ctx):
        """何もせずに断る 503。読みは 2 つの SLOW のコード、書き込みは ORDER_WRITE_UNAVAILABLE"""
        code = ("ORDER_DETAIL_UPSTREAM_SLOW" if ctx["route"] == "/v1/orders/{orderId}" else "ORDER_LIST_UPSTREAM_SLOW") \
            if method == "GET" else "ORDER_WRITE_UNAVAILABLE"
        status, payload, _ = self._error(code, trace)
        return self._finish(status, payload, code, trace, req_id, method, start, 0, ctx)

    def _handle_locked(self, method, path, headers, body, body_ok, reject, trace, req_id, start, ctx):
        if not self.lock.acquire(timeout=max(0.0, start + self.deadline_s - time.monotonic())):
            ctx["route"], ctx["exc"] = self._match(method, path)[0], "LockWaitTimeout"
            return self._unavailable(method, trace, req_id, start, ctx)
        try:
            self.sql, self._last_stmt = 0, None
            self.deadline = deadline = start + self.deadline_s
            self.conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
            try:
                if reject:
                    ctx["reject"] = reject[1]
                    raise Reply("INVALID_REQUEST", status=reject[0])
                if not body_ok:
                    ctx["reject"] = "bad_body"
                    raise Reply("INVALID_REQUEST")
                status, payload = self._route(method, path, headers, body, ctx)
                code = payload.get("error", {}).get("code") if isinstance(payload, dict) else None
            except Reply as r:
                status, payload, code = self._error(r.code, trace, r.results, status=r.status)
            except Exception as e:  # noqa: BLE001 — 予期しない例外も 500 か 503 にして、応答とログの 1 行を必ず残す
                if self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
                # 打ち切り（本番は statement_timeout と lock_timeout。SQLSTATE 57014 と 55P03）で止めた書き込みは、全部を戻して何も書いていない。
                # 冪等キーも戻るので、503 の ORDER_WRITE_UNAVAILABLE で同じキーの送り直しを促す（第 12 回。問い合わせを求めない）
                slow = isinstance(e, sqlite3.OperationalError) and "interrupt" in str(e)
                code = ("ORDER_DETAIL_UPSTREAM_SLOW" if ctx["route"] == "/v1/orders/{orderId}" else "ORDER_LIST_UPSTREAM_SLOW") if slow and method == "GET" \
                    else "ORDER_WRITE_UNAVAILABLE" if slow and method == "POST" \
                    else ("ORDER_WRITE_INTERNAL" if method == "POST" else "ORDER_LIST_INTERNAL")
                status, payload, _ = self._error(code, trace)
                ctx["exc"] = type(e).__name__
            finally:
                self.conn.set_progress_handler(None, 0)
                if self.conn.in_transaction:  # 途中で断った読みの取引も残さない
                    self.conn.execute("ROLLBACK")
                self.settings.clear()  # 取引の設定（鍵のハッシュ）を次の要求に残さない
            sql = self.sql
        finally:
            self.lock.release()
        return self._finish(status, payload, code, trace, req_id, method, start, sql, ctx)

    def _finish(self, status, payload, code, trace, req_id, method, start, sql, ctx):
        """応答の本文と見出しを作り、要約のログを 1 行書く。ログの値は決まった語と数だけ"""
        if isinstance(payload, dict) and "error" in payload:
            payload["error"]["traceId"] = trace
        out = json.dumps(payload, ensure_ascii=False).encode()
        line = {"ts": self.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "traceId": trace, "reqId": req_id, "method": method, "route": ctx["route"],
                "status": status, "code": code, "durMs": round((time.monotonic() - start) * 1000, 2), "sql": sql,
                "rows": ctx["rows"], "user": ctx["user"], "shop": ctx["shop"], "role": ctx["role"], "idemReplayed": ctx["replayed"]}
        if "exc" in ctx:  # 例外の種類の名前だけ。中身と traceback は書かない
            line["exc"] = ctx["exc"]
        if "reject" in ctx:  # 入口で断った理由の語だけ。要求の行と見出しの中身は書かない
            line["reject"] = ctx["reject"]
        with self.log_lock:
            self.log.write(json.dumps(line, ensure_ascii=False) + "\n")
        hdr = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-Trace-Id": trace, "X-Request-Id": req_id}
        if ctx["replayed"]:
            hdr["Idempotent-Replayed"] = "true"
        return status, hdr, out

    def _error(self, code, trace, results=None, status=None, n=0, m=0):
        st, cat, cause, action = ERRORS[code]
        if m == 1 and n == 1 and code in ERRORS_ONE:
            cause = ERRORS_ONE[code]
        cause, action = cause.format(n=n, m=m), action.format(n=n, m=m)
        st = status or st
        body = {"error": {"code": code, "category": cat, "cause": cause, "action": action, "traceId": trace}}
        if results is not None:
            body["results"] = results
        return st, body, code

    def _auth(self, headers, ctx):
        m = re.match(r"^Bearer\s+(\S+)$", headers.get("authorization", ""))
        if not m:
            raise Reply("AUTH_REQUIRED")
        # 取引の最初の文で、鍵のハッシュを取引の設定に置く（本番の RLS は、店をこの値から DB の側で引く）。値は束ねて渡し、文に書かない。
        # 鍵の表はこの設定で引くので、置き忘れは 401 として表に出る。同じ文で、変化の記録のトリガーの有無と足した時刻（feed_since）も読む
        self.q("SELECT set_config('app.key_hash', ?, 1)", (token_hash(m.group(1)),))
        rows = self.q(f"SELECT u.id, u.shop_id, u.name, u.role, {FEED_SQL} AS feed_since FROM sessions t JOIN users u ON u.id = t.user_id"
                      " WHERE t.token_sha256 = current_setting('app.key_hash') AND t.expires_at > ?", (self._stamp(),))
        if not rows:
            raise Reply("AUTH_REQUIRED")
        u = rows[0]
        ctx.update(user=u["id"], shop=u["shop_id"], role=u["role"])
        return u

    @staticmethod
    def _match(method, path):
        """(経路の型, 注文番号か None, 問い合わせの文字列)。経路の型は決まった語だけで、ログにはこれを書く"""
        url = urllib.parse.urlsplit(path)
        p = url.path.rstrip("/")
        if method == "GET" and p == "/v1/orders":
            return "/v1/orders", None, url.query
        if method == "POST" and p in ("/v1/orders/ship", "/v1/orders/cancel"):
            return p, None, url.query
        m = re.match(r"^/v1/orders/([^/]+)$", p)
        if method == "GET" and m:
            return "/v1/orders/{orderId}", m.group(1), url.query
        return "unknown", None, url.query

    def _route(self, method, path, headers, body, ctx):
        route, oid, query = self._match(method, path)
        ctx["route"] = route
        served = None
        if route == "/v1/orders":  # servedAt は、読みの取引の写しが決まる前に、取引の外の文で取る（本番は SERVED_PG）
            served = self.q(f"SELECT {SERVED_SQL}")[0][0]
        if route != "unknown":  # 鍵を読む文から、要求の全部の文を 1 つの取引で流す（本番は読みが READ ONLY の REPEATABLE READ）
            self.xact += 1
            self.conn.execute("BEGIN IMMEDIATE" if method == "POST" else "BEGIN")
        if route == "/v1/orders":
            try:  # 空の値と壊れた組（= の無い引数）も捨てずに読み、list_orders で 400 にする
                pairs = urllib.parse.parse_qsl(query, keep_blank_values=True, strict_parsing=True) if query else []
            except ValueError:
                raise Reply("INVALID_REQUEST") from None
            return self.list_orders(self._auth(headers, ctx), pairs, ctx, served)
        if route in ("/v1/orders/ship", "/v1/orders/cancel"):
            return self.write(self._auth(headers, ctx), route.rsplit("/", 1)[1], headers, body, ctx)
        if route == "/v1/orders/{orderId}":
            return self.detail(self._auth(headers, ctx), oid, ctx)
        raise Reply("INVALID_REQUEST")

    # ---- 一覧
    def _row(self, r):
        # 取り消しの正は is_cancelled の 1 つだけ。契約の status の 'cancelled' は、ここで is_cancelled から作る（DB の status には書かない）。
        # 取り消しの人と時刻は、DB のトリガーが印の立て下ろしでそろえる（印を立てた取引の値。印が立っている行だけ返す）
        # 出荷のあとに印が立った行（旧 API の取り消しは status を条件に持たない）は、済のまま返し、cancelledAfterShip で知らせる。
        # 時刻の無い取り消し（トリガーを足す前の旧 API）は null で返す（あとの書き込みの時刻を取消の日時にしない）
        def ref(uid, name):  # 名前を引けない利用者（店の外など）は、人を分からないとして null
            return {"id": uid, "name": name} if uid and name else None
        marked = r["is_cancelled"] == 1
        cancelled = marked and r["status"] in ("action", "ready", "pending")
        status = "cancelled" if cancelled else r["status"]
        late = status == "ready" and r["ship_due"] < self.today()
        group = "late" if late else status
        due = dt.date.fromisoformat(r["ship_due"])
        out = {"orderId": r["id"], "status": status, "group": group, "alert": r["alert"], "customerName": r["customer_name"],
               "amountYen": r["amount_yen"], "carrier": r["carrier"], "payment": r["payment"],
               "staff": ref(r["staff_id"], r["staff_name"]),
               "orderedAt": r["ordered_at"], "shipDue": r["ship_due"],
               "lateDays": (dt.date.fromisoformat(self.today()) - due).days if late else 0,
               "shippedBy": ref(r["shipped_by"], r["shipped_name"]), "shippedAt": r["shipped_at"],
               "cancelledAt": r["cancelled_at"] if marked else None,
               "cancelledBy": ref(r["cancelled_by"], r["cancelled_name"]) if marked else None,
               "cancelledAfterShip": marked and not cancelled}
        if "in_today" in r.keys():  # 行が今どの保存ビューに入るか（呼び手から見て）。since の行を画面が置き直す・外すのに使う
            out["inViews"] = [v for v, k in (("today", "in_today"), ("mine", "in_mine"), ("pending-all", "in_pending"), ("shipped", "in_shipped"))
                              if r[k]]
        return out

    def _sign(self, obj) -> str:
        body = b64(obj)
        return body + "." + hmac.new(self.cursor_key, body.encode(), hashlib.sha256).hexdigest()[:32]

    def _cursor(self, one, sort):
        """起点を読み、署名と型と範囲を確かめる。起点は API の鍵で署名し、並びと絞り込みに結びつく。条件を変えたら 400 にする。
        一覧の起点は日付（日本時間）にも結びつく。日付が変わると遅れの群が変わるので、前の日の起点は 400 にし、画面は先頭から読み直す"""
        body, _, mac = one["after"].partition(".")
        want = hmac.new(self.cursor_key, body.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(mac.encode(), want.encode()):  # 画面で組み立てた起点と、書き換えた起点
            raise Reply("INVALID_REQUEST")
        cur = unb64(body)
        ok = isinstance(cur, dict) and cur.get("s") == sort and cur.get("f") == self._filter_hash(one) \
            and isinstance(cur.get("i"), str) and ID_RX.fullmatch(cur["i"]) is not None \
            and cur.get("d") == (None if sort == "since" else self.today())
        if ok and sort == "next":  # next の時刻は、群ごとの向きをそろえたマイクロ秒の整数（済の群は出荷指示の新しい順）
            ok = type(cur.get("g")) is int and 0 <= cur["g"] <= 4 and type(cur.get("t")) is int and abs(cur["t"]) < 10 ** 17
        elif ok:
            ok = isinstance(cur.get("t"), str) and TS_RX.fullmatch(cur["t"]) is not None
            if ok and sort == "since":  # since の送りは、最初の頁の servedAt を持ち回る
                ok = isinstance(cur.get("w"), str) and TS_RX.fullmatch(cur["w"]) is not None
        if not ok:
            raise Reply("INVALID_REQUEST")
        return {"cg": cur.get("g"), "ct": cur["t"], "ci": cur["i"], "cw": cur.get("w")}

    @staticmethod
    def _filter_hash(one):
        pairs = sorted((k, one[k]) for k in FILTER_KEYS if k in one)
        return hashlib.sha256(json.dumps(pairs, ensure_ascii=False).encode()).hexdigest()[:16]

    def _next_cursor(self, one, sort, last, first_served=None):
        t = {"-shippedAt": "shipped_at", "since": "changed_at", "next": "next_key"}.get(sort, "ordered_at")
        cur = {"s": sort, "f": self._filter_hash(one), "t": last[t], "i": last["id"]}
        if sort == "next":
            cur["g"] = last["grp_rank"]
        if sort == "since":
            cur["w"] = first_served
        if sort != "since":
            cur["d"] = self.today()
        return self._sign(cur)

    def list_orders(self, user, pairs, ctx, served):
        one = dict(pairs)
        allowed = {"view", "status", "staff", "carrier", "payment", "q", "sort", "limit", "after", "since"}
        # 契約に無い引数、同じ引数の重ね、空の値は、黙って捨てずに 400（since= を変化の分でない応答で返さない）
        if set(one) - allowed or len(one) != len(pairs) or "" in one.values():
            raise Reply("INVALID_REQUEST")
        lim = one.get("limit", str(PAGE_DEFAULT))
        if not LIMIT_RX.fullmatch(lim) or not 1 <= int(lim) <= PAGE_MAX:  # 全角やほかの文字の数字は受けない
            raise Reply("INVALID_REQUEST")
        limit = int(lim)
        view = one.get("view", "today")
        if view not in VIEWS:
            raise Reply("INVALID_REQUEST")
        today = self.today()
        base = (f"SELECT {cols('o.')}, c.name AS customer_name, s.name AS staff_name, sb.name AS shipped_name, cb.name AS cancelled_name,"
                " CASE WHEN o.status = 'action' THEN 0 WHEN o.status = 'ready' AND o.ship_due < :today THEN 1"
                " WHEN o.status = 'ready' THEN 2 WHEN o.status = 'pending' THEN 3 ELSE 4 END AS grp_rank,"
                # 群の中の並びの鍵。未出荷の群は受注の古い順、済の群は出荷指示の新しい順なので、済だけ符号を逆にする
                " CASE WHEN o.status = 'shipped' THEN -(CAST(strftime('%s', o.shipped_at) AS INTEGER) * 1000000 + CAST(substr(o.shipped_at, 21, 6) AS INTEGER))"
                " ELSE CAST(strftime('%s', o.ordered_at) AS INTEGER) * 1000000 + CAST(substr(o.ordered_at, 21, 6) AS INTEGER) END AS next_key,"
                f" {IN_VIEWS_SQL}"
                " FROM {src} o JOIN customers c ON c.id = o.customer_id LEFT JOIN users s ON s.id = o.staff_id"
                " LEFT JOIN users sb ON sb.id = o.shipped_by LEFT JOIN users cb ON cb.id = o.cancelled_by WHERE o.shop_id = :shop")
        args = {"shop": user["shop_id"], "today": today, "limit": limit + 1, "me": user["id"],
                "day_start": iso(dt.datetime.fromisoformat(today + "T00:00:00+09:00"))}
        out_cols = ", ".join(OUT_COLS)
        p_cols = ", ".join("p." + c for c in OUT_COLS)
        if "since" in one:  # 指定の時刻より後に変わった行（要望 5。済、取消、取り消しの戻し、受注、決済）。changed_at の順に起点で送る
            if set(one) & {"sort", "view", "status", "staff", "carrier", "payment", "q"}:  # 黙って無視せず断る
                raise Reply("INVALID_REQUEST")
            try:
                t = dt.datetime.fromisoformat(one["since"].replace("Z", "+00:00"))
                if t.tzinfo is None:  # 時差の無い時刻は、機械の地方時と読まずに断る
                    raise ValueError("naive")
                if t < self.now() - dt.timedelta(seconds=SINCE_WINDOW_S):  # 窓より古い since は断る。店の全履歴をたどらせない
                    raise ValueError("too old")
                if user["feed_since"] is None:  # 変化の記録のトリガーが無い（計画は外さないが、外された場合）。変化を数えられないので、読み直しを待たせる
                    raise Reply("ORDER_LIST_UPSTREAM_SLOW")
                if iso(t) < user["feed_since"]:  # トリガーを足し直す前の since。無かったあいだの変化を取りこぼすので、一覧を読み直させる
                    raise ValueError("before the feed")
                args["since"] = iso(t - dt.timedelta(seconds=SINCE_OVERLAP_S))  # 重ね幅。画面は注文番号で重複を除く
            except (ValueError, OverflowError):  # 窓より古い時刻と、古すぎて重ね幅を引けない時刻も、入力の誤りとして 400
                raise Reply("INVALID_REQUEST") from None
            keyset = ""
            if "after" in one:
                args.update(self._cursor(one, "since"))
                keyset = " WHERE (changed_at, id) > (:ct, :ci)"
            # 変わった行は、どの書き手の変更でも DB が進める changed_at で数える（旧 API の取り消しの戻しも当たる）。
            # 行はビューで絞らず、店の中で変わった全部を返す。行ごとの inViews で、画面は今のビューに置き直すか外す
            inner = f"SELECT {out_cols}, COUNT(*) OVER () AS n_all FROM ({base.format(src='orders')} AND o.changed_at > :since)"
            page = f"SELECT {out_cols}, n_all FROM ({inner}){keyset} ORDER BY changed_at, id LIMIT :limit"
            # タブの件数は行と同じ文で取る。0 行でも 1 行が返るよう、件数の 1 行に行を左から結ぶ。servedAt は取引の前に読んだ値
            args["served"] = served
            rows = self.q(f"SELECT n.served_at, {VIEW_COUNT_COLS}, {p_cols}, p.n_all FROM (SELECT :served AS served_at, {VIEW_COUNTS_SQL}) n"
                          f" LEFT JOIN ({page}) p ON 1 = 1 ORDER BY p.changed_at, p.id", args)
            # 送りの 2 頁目からは、最初の頁の servedAt を返す。送りに時間がかかっても、最初の頁のあとにコミットした行を次の since が拾う
            served, vc = args.get("cw") or rows[0]["served_at"], self._view_counts(rows[0])
            rows = [r for r in rows if r["id"] is not None]
            more = len(rows) > limit
            rows = rows[:limit]
            items = [self._row(r) for r in rows]
            ctx["rows"] = len(items)
            self.conn.execute("COMMIT")
            return 200, {"items": items, "total": rows[0]["n_all"] if rows else 0, "viewCounts": vc, "me": self._me(user), "servedAt": served,
                         "nextCursor": self._next_cursor(one, "since", rows[-1], served) if more else None}
        sort = one.get("sort", "-shippedAt" if view == "shipped" else "next")
        if sort not in ("next", "orderedAt", "-orderedAt", "-shippedAt") or (sort == "-shippedAt" and view != "shipped"):
            raise Reply("INVALID_REQUEST")
        # 今日出荷と自分の担当は、未出荷の 4 群のあとに今日の済の行を続ける（画面の直後の群と済の群。一覧の要求は 1 回のまま）
        # 今日出荷と自分の担当の行は、未出荷の行と今日の済の行を別々の索引で引いて足す（UNION ALL）。済の行は出荷指示の時刻で引くので、
        # 過去に済になった行（配達済みへ移らないまま溜まる行）の量によらない。OR で 1 つにまとめると、統計の無い DB は店の全部の行をなめる
        # 取消の行（未出荷で is_cancelled = 1）は、どのビューにも出さず、どの件数にも数えない。出荷のあとに印が立った行は済のまま残す
        # 済の行は、今日の出荷と、出荷のあとに取り消された前の日までの行（LATE_MARK_ROWS）を、別々の索引で引いて足す
        shipped_src = (f"SELECT {cols()} FROM orders WHERE shop_id = :shop AND status = 'shipped' AND shipped_at >= :day_start{{due}}"
                       f" UNION ALL SELECT {cols()} FROM orders WHERE {LATE_MARK_ROWS}")  # 出荷予定日の条件は外の条件で掛ける（索引 orders_marked で引かせる）
        src = (f"(SELECT {cols()} FROM orders WHERE shop_id = :shop AND status IN ('action','ready','pending') AND is_cancelled = 0"
               f" AND ship_due <= :today UNION ALL {shipped_src.format(due=' AND ship_due <= :today')})") if view in ("today", "mine") \
            else f"({shipped_src.format(due='')})" if view == "shipped" else "orders"
        base = base.format(src=src)
        today_rows = ["o.ship_due <= :today",
                      f"((o.status IN ('action','ready','pending') AND o.is_cancelled = 0) OR (o.status = 'shipped' AND {SHIPPED_SEEN}))"]
        conds = {"today": today_rows, "mine": today_rows + ["o.staff_id = :me"],  # 自分の担当はビューの条件で、候補には出さない
                 "pending-all": ["o.status = 'pending'", "o.is_cancelled = 0"],
                 "shipped": ["o.status = 'shipped'", SHIPPED_SEEN]}[view]
        f = {}
        if view == "mine" and "staff" in one:  # 自分の担当の条件を上書きさせない
            raise Reply("INVALID_REQUEST")
        if "status" in one:
            if one["status"] not in GROUPS:
                raise Reply("INVALID_REQUEST")
            args["status"] = one["status"]
            f["status"] = ("CASE WHEN o.status = 'ready' AND o.ship_due < :today THEN 'late' ELSE o.status END = :status")
        if "staff" in one:
            v = one["staff"]
            f["staff"] = "o.staff_id IS NULL" if v == "none" else "o.staff_id = :me" if v == "me" else "o.staff_id = :staff"
            args["staff"] = v
        for k in ("carrier", "payment"):
            if k in one:
                f[k], args[k] = f"o.{k} = :{k}", one[k]
        if "q" in one:
            if not 1 <= len(one["q"]) <= Q_MAX:
                raise Reply("INVALID_REQUEST")
            qe = one["q"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")  # % と _ は字として探す
            f["q"], args["q"] = "(o.id LIKE :q || '%' ESCAPE '\\' OR c.name LIKE '%' || :q || '%' ESCAPE '\\')", qe
        where = " AND ".join(conds + list(f.values()))
        order = {"next": "grp_rank, next_key, id", "orderedAt": "ordered_at, id", "-orderedAt": "ordered_at DESC, id DESC",
                 "-shippedAt": "shipped_at DESC, id DESC"}[sort]
        keyset = ""
        if "after" in one:  # 起点の送り。最後の行の（群・時刻・番号）の次から
            args.update(self._cursor(one, sort))
            keyset = {"next": " WHERE (grp_rank, next_key, id) > (:cg, :ct, :ci)", "orderedAt": " WHERE (ordered_at, id) > (:ct, :ci)",
                      "-orderedAt": " WHERE (ordered_at, id) < (:ct, :ci)", "-shippedAt": " WHERE (shipped_at, id) < (:ct, :ci)"}[sort]
        # servedAt は取引の前に読んだ値（写しが決まる前の DB の時計と、書き手の取引の始まり）。0 行でも 1 行が返るよう、時刻の 1 行に行を左から結ぶ。
        # 一覧の文は 1 つの読みの取引で流す（本番は READ ONLY の REPEATABLE READ）。行と件数が同じ時点を見る
        args["served"] = served
        porder = ", ".join("p." + part.strip() for part in order.split(","))
        rows = self.q(f"SELECT n.served_at, {p_cols} FROM (SELECT :served AS served_at) n LEFT JOIN"
                      f" (SELECT {out_cols} FROM ({base} AND {where}){keyset} ORDER BY {order} LIMIT :limit) p ON 1 = 1 ORDER BY {porder}", args)
        served = rows[0]["served_at"]
        rows = [r for r in rows if r["id"] is not None]
        more = len(rows) > limit
        rows = rows[:limit]
        items = [self._row(r) for r in rows]
        nxt = self._next_cursor(one, sort, rows[-1]) if more else None
        # 件数は同じ応答に入れる（要望 1）。条件に当たる件数と群ごとの件数を 1 回、ビューごとの件数を 1 回で数える
        # 済の群の件数（shippedToday）も同じ問い合わせで数える。この応答の条件に当たる今日の済の行の数で、行と食い違わない
        groups, total, shipped_here = {g: 0 for g in GROUPS}, 0, 0
        for r in self.q(f"SELECT CASE WHEN o.status = 'ready' AND o.ship_due < :today THEN 'late' ELSE o.status END AS g, COUNT(*) AS n"
                        f" FROM {src} o JOIN customers c ON c.id = o.customer_id WHERE o.shop_id = :shop AND {where} GROUP BY g", args):
            total += r["n"]
            if r["g"] in groups:
                groups[r["g"]] = r["n"]
            elif r["g"] == "shipped":
                shipped_here = r["n"]
        # ビューごとの件数。1 つの SQL の中で、ビューごとに索引で引ける部分の問い合わせに分ける（過去の配達済みの行をなめない）
        vc = self._view_counts(self.q(f"SELECT {VIEW_COUNTS_SQL}", args)[0])
        out = {"items": items, "total": total, "counts": {**groups, "shippedToday": shipped_here},
               "viewCounts": vc,
               "me": self._me(user), "servedAt": served, "nextCursor": nxt}
        if total == 0 and f:  # 空のときは、条件を 1 つ外した候補の件数（1 回の問い合わせ）
            sums = ", ".join(f"SUM(CASE WHEN {' AND '.join([v2 for k2, v2 in f.items() if k2 != k] or ['1'])} THEN 1 ELSE 0 END) AS \"{k}\"" for k in f)
            r = self.q(f"SELECT {sums} FROM {src} o JOIN customers c ON c.id = o.customer_id WHERE o.shop_id = :shop AND {' AND '.join(conds)}", args)[0]
            out["suggestions"] = [{"withoutFilter": k, "total": r[k] or 0} for k in f]
        self.conn.execute("COMMIT")
        ctx["rows"] = len(items)
        return 200, out

    @staticmethod
    def _view_counts(r):
        return {"today": r["vc_today"], "mine": r["vc_mine"], "pending-all": r["vc_pending"], "shipped": r["vc_shipped"]}

    def _me(self, user):
        # 1 文字キーは、この版の API で動く操作だけ。担当の付け替え（A）と出荷予定日の更新（E）は API が無いので返さない
        keys = {"S": "ship", "P": "print"} if user["role"] == "operator" else {}
        return {"id": user["id"], "name": user["name"], "role": user["role"], "keys": keys}

    def _stamp(self):
        return iso(self.now())

    # ---- 詳細
    def detail(self, user, order_id, ctx):
        if not ID_RX.fullmatch(order_id or ""):  # 契約の形（6〜12 桁の数字）に合わない番号は 400。無い注文の 404 と分ける
            raise Reply("INVALID_REQUEST")
        rows = self.q(f"SELECT {cols('o.')}, c.name AS customer_name, c.postal, c.address, s.name AS staff_name, sb.name AS shipped_name,"
                      " cb.name AS cancelled_name, 9 AS grp_rank FROM orders o JOIN customers c ON c.id = o.customer_id"
                      " LEFT JOIN users s ON s.id = o.staff_id LEFT JOIN users sb ON sb.id = o.shipped_by"
                      " LEFT JOIN users cb ON cb.id = o.cancelled_by WHERE o.id = ? AND o.shop_id = ?", (order_id, user["shop_id"]))
        if not rows:  # 他の店の注文も「見つからない」で返し、存在を教えない
            raise Reply("ORDER_NOT_FOUND")
        r = rows[0]
        out = self._row(r)
        out.update(postal=r["postal"], address=r["address"], note=r["note"], parcel={"size": r["parcel"], "fragile": bool(r["fragile"])})
        out["items"] = [{"name": i["name"], "qty": i["qty"], "amountYen": i["amount_yen"], "taxRate": i["tax_rate"]}
                        for i in self.q("SELECT name, qty, amount_yen, tax_rate FROM order_items WHERE order_id = ? ORDER BY line", (order_id,))]
        out["pastOrders"] = [{"orderId": p["id"], "orderedAt": p["ordered_at"], "amountYen": p["amount_yen"]} for p in self.q(
            "SELECT id, ordered_at, amount_yen FROM orders WHERE customer_id = ? AND shop_id = ? AND id <> ? ORDER BY ordered_at DESC LIMIT 2",
            (r["customer_id"], user["shop_id"], order_id))]
        out["history"] = [{"at": e["at"], "kind": e["kind"]} for e in self.q(
            "SELECT at, kind FROM order_events WHERE order_id = ? ORDER BY at DESC LIMIT 5", (order_id,))]
        self.conn.execute("COMMIT")
        ctx["rows"] = 1
        return 200, out

    # ---- 書き込み（出荷指示と取り消し）
    def write(self, user, op, headers, body, ctx):
        if user["role"] != "operator":
            raise Reply("FORBIDDEN_ROLE")
        key = headers.get("idempotency-key", "")
        if not KEY_RX.fullmatch(key):
            raise Reply("IDEMPOTENCY_KEY_REQUIRED")
        try:
            data = json.loads(body or b"null")
        except (ValueError, RecursionError):  # 入れ子の深い本文も入力の誤り。500 にしない
            raise Reply("INVALID_REQUEST") from None
        ids = data.get("orderIds") if isinstance(data, dict) else None
        if not isinstance(ids, list) or not 1 <= len(ids) <= PAGE_MAX or not all(isinstance(i, str) and ID_RX.fullmatch(i) for i in ids):
            raise Reply("INVALID_REQUEST")
        ids = list(dict.fromkeys(ids))
        if not self.writes_enabled:  # 戻し（新 API の書き込みを止め、画面を旧 API に戻した）。何も書かず、冪等キーも取らない。
            raise Reply("ORDER_WRITE_DISABLED")  # 送り直しでは通らないので、画面を読み込み直させる（機能フラグで旧画面が開く）
        digest = hashlib.sha256(f"{op}\n{json.dumps(sorted(ids))}".encode()).hexdigest()
        lookup = ("SELECT request_sha256, status, body FROM idempotency WHERE shop_id = ? AND user_id = ? AND key = ? AND created_at >= ?",
                  (user["shop_id"], user["id"], key, self._idem_cutoff()))
        try:  # 取引は _route が鍵を読む前に始めている（BEGIN IMMEDIATE）。保持の期間を過ぎたキーは、ここでは消さない（purge_expired）
            prev = self.q(*lookup)
            if prev:
                self.conn.execute("COMMIT")
                return self._replay(prev[0], digest, ctx)
            # 注文の行を読む前に、冪等キーを先に取る。行の鍵で待つ DB でも、同じキーの 2 本目はここで 1 本目のコミットを待ち、
            # 誤りを出さずに 0 行を返す（ON CONFLICT DO NOTHING）。取引を戻さないので、鍵のハッシュ（app.key_hash）を置いたまま
            # 1 本目の行を読み直せる（本番の RLS の下でも 0 行にならない）。DB のログに主キーの重複の誤りと冪等キーの値も出ない
            claim = (user["shop_id"], user["id"], key, digest, self._stamp())
            if not self.conn.execute(CLAIM_SQL, claim).fetchall():
                prev = self.q(*lookup)  # 別のプロセスが同じキーを先に取ってコミットした。先の応答を返す
                if prev:
                    self.conn.execute("COMMIT")
                    return self._replay(prev[0], digest, ctx)
                # 保持の期間を過ぎた同じキーの行が、掃除の前で残っていた。その 1 行だけを消して取り直す
                self.conn.execute(RECLAIM_SQL, (user["shop_id"], user["id"], key, self._idem_cutoff()))
                if not self.conn.execute(CLAIM_SQL, claim).fetchall():
                    raise RuntimeError("idempotency key held by another writer")
            status, payload = (self._ship if op == "ship" else self._cancel)(user, ids)
            ctx["rows"] = len(ids)
            self.conn.execute("UPDATE idempotency SET status = ?, body = ? WHERE shop_id = ? AND user_id = ? AND key = ?",
                              (status, json.dumps(payload, ensure_ascii=False), user["shop_id"], user["id"], key))
            self.conn.execute("COMMIT")
            return status, payload
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise

    @staticmethod
    def _replay(prev, digest, ctx):
        if prev["request_sha256"] != digest:
            raise Reply("IDEMPOTENCY_KEY_MISMATCH")
        ctx["replayed"] = True
        return prev["status"], json.loads(prev["body"])

    def _targets(self, user, ids):
        """書けなかった行を分けるための読み。UPDATE のあとに読むので、ほかの人が先にコミットした状態が見える"""
        marks = ",".join("?" * len(ids))
        # 取消は is_cancelled で決める（status は取り消しで動かない）。出荷のあとに印が立った行は済のまま（取り消せない）
        # stamped は、この取引で書いた行をトリガーが印したか（本番は STAMPED_PG）。書けた行に印が無ければ、書き込みを全部戻す
        rows = self.q("SELECT o.id, CASE WHEN o.is_cancelled = 1 AND o.status IN ('action','ready','pending') THEN 'cancelled' ELSE o.status END"
                      " AS status, o.shipped_by, o.shipped_at, o.cancelled_at, sb.name AS shipped_name, o.stamped_xid = xact_id() AS stamped FROM orders o"
                      f" LEFT JOIN users sb ON sb.id = o.shipped_by WHERE o.shop_id = ? AND o.id IN ({marks})", (user["shop_id"], *ids))
        return {r["id"]: r for r in rows}

    @staticmethod
    def _stamped(done, t):
        """書けた行を、トリガーがこの取引で印したか。印が無ければ（トリガーが外された、素通りの取引）、503 にして全部を戻す"""
        if any(not (t.get(i) and t[i]["stamped"]) for i in done):
            raise Reply("ORDER_WRITE_UNAVAILABLE")

    def _apply(self, user, ids, sql_set, cond, kind, at):
        """条件つきの UPDATE を先に流し、書けた行の番号を返す。1 つの文なので、書く行は全件か無し。
        読んでから書く形にしない。行の鍵で待つ DB（READ COMMITTED）では、ほかの人のコミットを待ったあとで条件を読み直すので、
        先に済になった行は 0 行として返り、500 にならない。SELECT … FOR UPDATE は要らない。
        cond は書く行の条件で、取り消しの印 is_cancelled = 0 を必ず持つ（旧 API が同時に取り消した行は、鍵を待ったあとの読み直しで外れる）"""
        marks = ",".join("?" * len(ids))
        done = [r[0] for r in self.conn.execute(
            f"UPDATE orders SET {sql_set} WHERE shop_id = ? AND id IN ({marks}) AND {cond} RETURNING id",
            ((user["id"], at)[:sql_set.count("?")] + (user["shop_id"], *ids))).fetchall()]
        if done:
            dm = ",".join("?" * len(done))
            self.conn.execute(f"INSERT INTO order_events (order_id, at, kind, actor) SELECT id, ?, ?, ? FROM orders WHERE shop_id = ? AND id IN ({dm})",
                              (at, kind, user["id"], user["shop_id"], *done))
        return set(done)

    def _ship(self, user, ids):
        at = self._stamp()
        done = self._apply(user, ids, *self.SHIP_SQL, "shipped", at)
        t = self._targets(user, ids)
        self._stamped(done, t)
        results = []
        for i in ids:
            r = t.get(i)
            if i in done:
                results.append({"orderId": i, "outcome": "shipped", "code": None, "shippedBy": {"id": user["id"], "name": user["name"]}, "shippedAt": at})
            elif r is None:
                results.append({"orderId": i, "outcome": "not_found", "code": "ORDER_NOT_FOUND"})
            elif r["status"] == "shipped":
                results.append({"orderId": i, "outcome": "already_shipped", "code": "ORDER_ALREADY_SHIPPED",
                                "shippedBy": {"id": r["shipped_by"], "name": r["shipped_name"]}, "shippedAt": r["shipped_at"]})
            else:
                results.append({"orderId": i, "outcome": "not_shippable", "code": "ORDER_SHIP_PARTIAL", "reason": r["status"]})
        summary = {k: sum(1 for x in results if x["outcome"] == k) for k in ("shipped", "already_shipped", "not_shippable", "not_found")}
        summary["requested"] = len(ids)
        if done:
            return 200, {"results": results, "summary": summary}
        code = "ORDER_ALREADY_SHIPPED" if summary["already_shipped"] == len(ids) else "ORDER_SHIP_PARTIAL"
        m = summary["already_shipped"] if code == "ORDER_ALREADY_SHIPPED" else len(ids) - summary["already_shipped"]
        st, body, _ = self._error(code, "", results, n=len(ids), m=m)
        body["summary"] = summary
        return st, body

    def _cancel(self, user, ids):
        at = self._stamp()
        done = self._apply(user, ids, *self.CANCEL_SQL, "cancelled", at)
        t = self._targets(user, ids)
        self._stamped(done, t)
        results = []
        for i in ids:
            r = t.get(i)
            if i in done:
                results.append({"orderId": i, "outcome": "cancelled", "code": None, "cancelledAt": r["cancelled_at"] or at})
            elif r is None:
                results.append({"orderId": i, "outcome": "not_found", "code": "ORDER_NOT_FOUND"})
            elif r["status"] == "cancelled":
                results.append({"orderId": i, "outcome": "already_cancelled", "code": None})
            else:  # 出荷指示済みと配達済み
                results.append({"orderId": i, "outcome": "not_allowed", "code": "ORDER_CANCEL_NOT_ALLOWED"})
        summary = {k: sum(1 for x in results if x["outcome"] == k) for k in ("cancelled", "already_cancelled", "not_allowed", "not_found")}
        summary["requested"] = len(ids)
        if done or summary["already_cancelled"] == len(ids):
            return 200, {"results": results, "summary": summary}
        # 書けた行が 0 件なら、全部が見つからないときも 409（契約のとおり。他の店の注文は行ごとの結果で返す）
        code = "ORDER_CANCEL_NOT_ALLOWED" if summary["not_allowed"] else "ORDER_NOT_FOUND"
        st, body, _ = self._error(code, "", results, status=409, n=len(ids), m=summary["not_allowed"])
        body["summary"] = summary
        return st, body


def make_api(n_orders=29, log=None, deadline_s=DEADLINE_S):
    return OrdersApi(n_orders, log, deadline_s)


class _Deadline(io.RawIOBase):
    """要求 1 つを読む時間の上限。最初の 1 バイトが届いてから、要求の行・見出し・本文の全体を limit_s で読み終える。
    socket の timeout は recv 1 回ごとの上限なので、recv のたびに残りの時間を入れ直す。次の要求を待つ間も limit_s で切る"""

    def __init__(self, sock, limit_s):
        super().__init__()
        self.sock, self.limit_s = sock, limit_s
        self.start()

    def start(self):
        self.deadline, self.got = None, 0

    def readable(self):
        return True

    def readinto(self, b):
        left = self.limit_s if self.deadline is None else self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("request deadline")
        self.sock.settimeout(left)
        n = self.sock.recv_into(b)
        if n and self.deadline is None:
            self.deadline = time.monotonic() + self.limit_s
        self.got += n
        return n


class _Server(http.server.ThreadingHTTPServer):
    """同時の接続に上限のある ThreadingHTTPServer。接続は 3 つの状態を持つ。reading（要求を読み終えていない）、working（API の処理中）、
    writing（応答を書いている）。上限に達したら、reading か writing の接続のうち、その状態に入ったのが最も古いものを切って席を空け、
    新しい接続を受ける。処理中の接続は切らない。書き込みの途中で切っても、書き込みの API は冪等キーで同じ応答を返し直せる。
    切れる接続が無いときだけ新しい接続を切る。どれもログに 1 行。黙った接続と応答を読まない接続を上限まで開いても、ほかの要求を止められない"""
    daemon_threads = True

    def __init__(self, addr, handler, api, max_conn):
        self.api, self.slots = api, threading.BoundedSemaphore(max_conn)
        self.live, self.live_lock = {}, threading.Lock()  # 接続ごとの Handler。状態と、その状態に入った時刻を持つ
        super().__init__(addr, handler)

    def _evict_unread(self):
        with self.live_lock:
            idle = [(h.state_since, id(h), h) for h in self.live.values() if h.state in ("reading", "writing") and not h.evicted]
            if not idle:
                return False
            victim = min(idle)[2]
            victim.evicted = True
            reason = "evicted_unread" if victim.state == "reading" else "evicted_unsent"
        try:
            victim.connection.shutdown(socket.SHUT_RDWR)  # 読みかけの recv と書きかけの send が戻り、その接続のスレッドが終わって席を返す
        except OSError:
            pass
        self.api.note_busy(reason)
        return True

    def process_request(self, request, client_address):
        # 席が無ければ、切れる接続を切って席を空ける。どの接続も処理中の瞬間なら、1 秒まで探し直す（処理中の要求はすぐ終わる。
        # 鍵ごとの上限を超えた要求は lock を待たずに 503 を返すので、lock を待って席を持つ接続は鍵ごとに PER_KEY_INFLIGHT 本まで）
        until = time.monotonic() + 1.0
        got = self.slots.acquire(blocking=False)
        while not got and time.monotonic() <= until:
            got = (self._evict_unread() and self.slots.acquire(timeout=0.2)) or self.slots.acquire(timeout=0.01)
        if not got:
            self.api.note_busy()
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def make_server(api, host="127.0.0.1", port=0, read_timeout_s=READ_TIMEOUT_S, max_conn=MAX_CONN):
    # http.server が自分で断る誤りの理由の語。応答とログには、この語だけを入れる（要求の行の中身は入れない）
    reasons = {400: "bad_request_line", 414: "uri_too_long", 431: "headers_too_large", 505: "bad_version"}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "orders-sample"
        sys_version = ""
        timeout = read_timeout_s  # 書く側の send 1 回ごとの上限。読む側は _Deadline が全体で見る

        def setup(self):
            super().setup()
            self.clock = _Deadline(self.connection, read_timeout_s)
            self.rfile = io.BufferedReader(self.clock, 65536)
            self.evicted = False
            self._enter("reading")
            with self.server.live_lock:
                self.server.live[id(self)] = self

        def _enter(self, state):
            self.state, self.state_since = state, time.monotonic()

        def finish(self):
            with self.server.live_lock:
                self.server.live.pop(id(self), None)
            try:
                super().finish()
            except OSError:  # 席を空けるために切った接続
                pass

        def handle_one_request(self):
            # http.server の handle_one_request と同じ順で読む。どの誤りも api を通し、4 点・no-store・ログの 1 行を残す。
            # メソッドは名前で分けず、GET と POST のほか（PUT、DELETE ほか）も api.handle に渡して 400 にする
            self.clock.start()
            self._enter("reading")  # 次の要求を読み終えるまでは、席を空けるために切られうる
            self.command, self.request_version, self.requestline = None, "HTTP/1.1", ""
            try:
                self.raw_requestline = self.rfile.readline(65537)
                if len(self.raw_requestline) > 65536:
                    self.send_error(414)
                    return
                if not self.raw_requestline:
                    self.close_connection = True
                    return
                if not self.parse_request() or self.evicted:
                    self.close_connection = True
                    return
                self._go()
            except TimeoutError:
                self.close_connection = True
                if self.clock.got and not self.evicted:  # 要求の途中で時間切れ（遅い要求の行や見出し）。黙った接続は何も書かずに切る
                    self._send(*api.reject(400, self.command, "slow_request"))
            except OSError:  # 相手が先に切った
                self.close_connection = True

        def send_error(self, code, message=None, explain=None):
            # http.server が自分で返す誤り（壊れた要求の行、長すぎる URI、多すぎる見出し）。HTML の既定の応答にしない。
            # message は要求の行を含むので、応答にもログにも使わない
            self.close_connection = True
            if self.evicted:  # 席を空けるために切った接続には書かない（ログは切ったときの 1 行）
                return
            self._send(*api.reject(code if 400 <= code < 500 else 400, self.command, reasons.get(code, f"http_{code}")))

        def _go(self):
            raw = self.headers.get("Content-Length") or "0"
            # 本文の長さは Content-Length の 1 つだけで決める。Transfer-Encoding（chunked ほか）と、Content-Length が 2 つある要求は、
            # 前に置く代理のサーバーと本文の切れ目の読み方が食い違う（要求の取り違え）ので、読まずに 400 にする
            ok = (self.headers.get("Transfer-Encoding") is None and len(self.headers.get_all("Content-Length") or []) <= 1
                  and LEN_RX.fullmatch(raw) is not None and int(raw) <= MAX_BODY)  # 負の値と上限超えも読まずに 400
            n = int(raw) if ok else 0
            try:
                body = self.rfile.read(n) if n else b""
            except TimeoutError:
                body, ok = b"", False
            if len(body) < n:  # 時間切れか、途中で切れた
                ok = False
            if not ok:
                self.close_connection = True  # 読んでいない本文が残るので、この接続は使い続けない
            if self.evicted:  # 本文を待つあいだに席を空けるために切った
                self.close_connection = True
                return
            self._enter("working")  # 要求を読み終えた。処理のあいだは切らない
            self._send(*api.handle(self.command, self.path, dict(self.headers.items()), body, body_ok=ok))

        def _send(self, st, hdr, out):
            """状態の行・見出し・本文を 1 回の sendall で書く。全体で WRITE_TIMEOUT_S（send 1 回ごとではない）。
            書き終えなければ接続を切り、何も書き足さない（同じ接続に 400 を重ねない）"""
            if self.request_version in ("HTTP/0.9", "", None):  # 要求の行が読めなくても、状態の行と見出しを書く
                self.request_version = "HTTP/1.1"
            self.send_response_only(st)
            self.send_header("Server", self.version_string())
            self.send_header("Date", self.date_time_string())
            for k, v in hdr.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(out)))
            if self.close_connection:
                self.send_header("Connection", "close")
            self._headers_buffer.append(b"\r\n")
            data = b"".join(self._headers_buffer) + (out if self.command != "HEAD" else b"")
            self._headers_buffer = []
            self._enter("writing")  # 応答を読まない相手には、席を空けるために切られうる
            try:
                self.connection.settimeout(WRITE_TIMEOUT_S)
                self.connection.sendall(data)
            except TimeoutError:  # 応答を読まない相手。何も書き足さずに切る
                self.close_connection = True
                if not self.evicted:
                    api.note_busy("write_timeout")
            except OSError:  # 相手が先に切った接続と、席を空けるために切った接続
                self.close_connection = True

        def log_request(self, *a):  # http.server の生のアクセスログ（問い合わせの文字列を含む）は出さない
            pass

        def log_message(self, *a):
            pass

    return _Server((host, port), Handler, api, max_conn)
