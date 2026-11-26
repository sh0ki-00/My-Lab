"""DB の小さな道具。"""
import datetime
import sqlite3

import config

_conn = None


def conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH)
        _conn.row_factory = sqlite3.Row
    return _conn


def jst_now():
    """いまの日時（日本時間）を '2024-04-01 12:34:56' の形で返す。"""
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def q(sql, args=()):
    return conn().execute(sql, args).fetchall()


def q1(sql, args=()):
    return conn().execute(sql, args).fetchone()


def exe(sql, args=()):
    cur = conn().execute(sql, args)
    conn().commit()
    return cur.lastrowid
