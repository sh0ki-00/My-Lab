#!/usr/bin/env python3
"""data_tools — 既存の DB を読み取りだけで掴む道具と、データの辞書の検査。標準の python3（3.9 以上）と sqlite3 だけで動く。

使い方（同じディレクトリの .sh から呼ぶ）:
  snapshot  schema-snapshot.sh        実物の DB からスキーマを書き出し、ハッシュ値を出す。別の写しかマイグレーションの形と比べる
  profile   data-profile.sh           テーブルと列の集計を回し、クエリの記録に書く。辞書の下書きと罠の候補を出す
  query     data-query.sh             クエリを 1 本、読み取りだけで回し、クエリの記録に書く。依頼者が回した結果の取り込みも書く
  writers   writers-map.sh            コードの書き込む文と DB のトリガーから、テーブルごとの書き込む処理の候補を出す
  check     data-dictionary-check.sh  辞書・調査の文書・クエリの記録の検査。DB にはつながない
            --evidence-hash           git の無いプロジェクトの辞書の commit の欄の値（「git なし」、作った時刻、根拠のハッシュ値）を出す
  <種類> --selftest                  sqlite の一時 DB だけで、数秒の自己試験を回す
DB: sqlite は mode=ro の URI と query_only で開く。PostgreSQL と MySQL は、手元に psql・mysql があるときだけ呼び、
    読み取りだけのセッション（default_transaction_read_only、transaction_read_only）で回す。無ければ FAIL [道具が無い]。
    向き先は localhost・127.0.0.1・::1 かソケットだけで、ほかは回さない（FAIL [本番につながない]）。
    接続の値は道具が持たない。PostgreSQL は PG* の環境変数か ~/.pgpass、MySQL は --mysql-defaults の設定ファイルで渡す。
    設定ファイルから読むのは、向き先を確かめる host と socket の行だけ。
文: どの道具も、回す前に許す文の一覧（1 文だけの SELECT と WITH … SELECT、許す関数の一覧）で確かめる。
出力: FAIL <場所> [<決まり>] <内容> と道具ごとの行（QUERY、HASH、DIFF、CANDIDATE）、最後に RESULT: PASS|FAIL <道具> …。
      FAIL が 1 件でもあれば終了コード 1。使い方の誤りは 2。
"""
import argparse
import contextlib
import csv
import datetime
import fcntl
import hashlib
import io
import json
import math
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import xml.etree.ElementTree as ET

NAMES = {"snapshot": "schema-snapshot", "profile": "data-profile", "query": "data-query",
         "writers": "writers-map", "check": "data-dictionary-check"}
MAX_VALUES = 20        # 値の一覧を残す列の、値の種類の上限（改善提案書 5.2 節の線）
TIMEOUT_MS = 5000      # 文ごとの打ち切り
MAX_ROWS = 200         # 1 本のクエリで記録に残す行の上限
MAX_CELL = 2000        # 記録に残す 1 つの値の字の上限。超える値は残さない（長い値は件数か長さで数える）
MAX_AT = 1000          # メールの形を探す @ の数の上限。超えたら個人が分かる値として扱う
SAMPLE_OVER = 200000   # これより行の多いテーブルは標本で数える
SAMPLE_ROWS = 50000    # 標本の行の目安
CHUNK = 25             # 1 本の集計の文に入れる列の数
OPEN_MARKS = {
    "sqlite": "sqlite mode=ro query_only",
    "postgres": "psql default_transaction_read_only=on",
    "mysql": "mysql transaction_read_only=1",
    "import": "取り込み（依頼者が回した結果）",
}
NULL_MARK = "\u2400NULL\u2400"
LIT = "\u0001"  # 文字の値の置き場
QID = "\u0002"  # 引用した名前の置き場


class ToolError(Exception):
    def __init__(self, rule, detail):
        super().__init__(detail)
        self.rule, self.detail = rule, detail


class Report:
    def __init__(self, tool, target=""):
        self.tool, self.target, self.items, self.lines = tool, target, [], []

    def fail(self, where, rule, detail):
        self.items.append((where, rule, detail))

    def say(self, text):
        self.lines.append(text)

    def rules(self):
        return {x[1] for x in self.items}

    def show(self, summary=""):
        for t in self.lines:
            print(t)
        for where, rule, detail in self.items:
            print(f"FAIL {where + ' ' if where else ''}[{rule}] {detail}")
        tail = f"{summary}、FAIL {len(self.items)}" if summary else f"FAIL {len(self.items)}"
        target = f" {self.target}" if self.target else ""
        print(f"RESULT: {'FAIL' if self.items else 'PASS'} {self.tool}{target} ({tail})")
        return 1 if self.items else 0


# ---------------------------------------------------------------- 許す文の一覧
FORBIDDEN = set("""
INSERT UPDATE DELETE MERGE UPSERT TRUNCATE DROP ALTER CREATE GRANT REVOKE COPY INTO CALL EXECUTE EXEC LOCK ATTACH DETACH
PRAGMA VACUUM REINDEX LOAD OUTFILE DUMPFILE RETURNING NOTIFY LISTEN UNLISTEN PREPARE DEALLOCATE DECLARE HANDLER SAVEPOINT
REFRESH CLUSTER IMPORT UESCAPE
""".split())
ALLOWED_FUNCS = set("""
COUNT SUM AVG MIN MAX TOTAL GROUP_CONCAT STRING_AGG ARRAY_AGG JSON_AGG JSONB_AGG JSON_GROUP_ARRAY BOOL_AND BOOL_OR EVERY
BIT_AND BIT_OR STDDEV STDDEV_POP STDDEV_SAMP VARIANCE VAR_POP VAR_SAMP PERCENTILE_CONT PERCENTILE_DISC MODE ANY_VALUE MEDIAN
ROW_NUMBER RANK DENSE_RANK NTILE LAG LEAD FIRST_VALUE LAST_VALUE NTH_VALUE PERCENT_RANK CUME_DIST
COALESCE NULLIF IFNULL NVL IIF IF ISNULL GREATEST LEAST CAST CONVERT TYPEOF PG_TYPEOF
ABS ROUND FLOOR CEIL CEILING TRUNC SIGN MOD POWER POW SQRT EXP LN LOG LOG10 LOG2 DIV
LENGTH CHAR_LENGTH CHARACTER_LENGTH OCTET_LENGTH BIT_LENGTH LOWER UPPER INITCAP TRIM LTRIM RTRIM BTRIM SUBSTR SUBSTRING
REPLACE TRANSLATE INSTR POSITION STRPOS LOCATE LEFT RIGHT LPAD RPAD CONCAT CONCAT_WS REVERSE SPLIT_PART STARTS_WITH
REGEXP_REPLACE REGEXP_LIKE REGEXP_MATCHES REGEXP_SUBSTR REGEXP_INSTR REGEXP_COUNT ASCII UNICODE CHAR CHR HEX MD5 FORMAT PRINTF
DATE TIME DATETIME JULIANDAY STRFTIME UNIXEPOCH TIMEDIFF DATE_TRUNC DATE_PART DATE_BIN EXTRACT TO_CHAR TO_DATE TO_TIMESTAMP
TO_NUMBER AGE NOW MAKE_DATE MAKE_TIMESTAMP TIMEZONE DATE_FORMAT STR_TO_DATE YEAR MONTH DAY DAYOFMONTH DAYOFWEEK DAYOFYEAR
WEEKDAY WEEK WEEKOFYEAR QUARTER HOUR MINUTE SECOND LAST_DAY DATEDIFF TIMESTAMPDIFF TIMESTAMPADD DATE_ADD DATE_SUB ADDDATE
SUBDATE CONVERT_TZ FROM_UNIXTIME UNIX_TIMESTAMP CURDATE CURTIME
JSON_EXTRACT JSON_UNQUOTE JSON_TYPE JSON_LENGTH JSON_ARRAY_LENGTH JSON_VALID JSON_EACH JSON_TREE JSONB_TYPEOF JSON_TYPEOF
JSONB_ARRAY_LENGTH JSON_EXTRACT_PATH_TEXT JSONB_EXTRACT_PATH_TEXT JSON_OBJECT_KEYS JSONB_OBJECT_KEYS
ARRAY_LENGTH CARDINALITY UNNEST GENERATE_SERIES
PRAGMA_TABLE_INFO PRAGMA_TABLE_XINFO PRAGMA_INDEX_LIST PRAGMA_INDEX_INFO PRAGMA_FOREIGN_KEY_LIST
""".split())
# 括弧の前に置いてよい語（関数の呼び出しでない括弧）
PAREN_WORDS = set("""
IN EXISTS ANY ALL SOME OVER FILTER GROUP AS MATERIALIZED VALUES ROW ARRAY FROM JOIN ON USING AND OR NOT WHERE SELECT BY
HAVING WHEN THEN ELSE CASE LIKE ILIKE BETWEEN IS DISTINCT UNION EXCEPT INTERSECT LATERAL TO ESCAPE LIMIT OFFSET
VARCHAR CHARACTER VARYING NUMERIC DECIMAL TIMESTAMP FLOAT DOUBLE PRECISION INT INTEGER BIGINT SMALLINT TEXT
SYSTEM BERNOULLI REPEATABLE
""".split())
# 名前は英字に限らない（日本語の名前の関数や列も 1 つの名前として読む）。数字で始まる語は名前にしない
TOKEN_RX = re.compile(r"[^\W\d]\w*|[0-9]+(?:\.[0-9]+)?|\S")
NAME_RX = re.compile(r"[^\W\d]\w*")
LOCK_RX = re.compile(r"\bFOR (?:NO KEY |KEY )?(?:UPDATE|SHARE)\b")
# \n と \r のほかに、DB や道具が行の終わりと読む字。注釈の終わりの読み違いを防ぐため、文に入れない
ODD_BREAKS = "\v\f\x1c\x1d\x1e\x85  "


def is_name(t):
    return t == QID or bool(NAME_RX.fullmatch(t))


def short_sql(sql, n=60):
    s = re.sub(r"\s+", " ", sql).strip()
    return s if len(s) <= n else s[:n] + "…"


def scan_sql(sql):
    """文字の値と引用した名前を置き場の字に替え、注釈を外す。返り値は (本文, 文字の値の一覧, 問題の一覧, 引用した名前の一覧)。"""
    out, lits, probs, idents = [], [], [], []
    i, n = 0, len(sql)

    def bad(rule, msg):
        if (rule, msg) not in probs:
            probs.append((rule, msg))

    if "\\" in sql:
        # 文字の値の中でも落とす。MySQL は 'a\' の逆斜線を引用の外しと読み、値の終わりが標準の SQL とずれる
        bad("書き方", "逆斜線は使わない（文字の値の終わりを読み違える）")
    if any(c in sql for c in ODD_BREAKS):
        bad("書き方", "改行は \\n と \\r だけにする（\\v、\\f、U+2028 などは、DB によって注釈の終わりと読まれる）")
    if re.search(r"(?i)\bU&\s*['\"]", sql):
        bad("書き方", "U& の引用は使わない（文字や名前を符号で書くと、関数の名前を隠せる）")
    while i < n:
        ch = sql[i]
        if ch in "'\"`":
            j, buf, closed = i + 1, [], False
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:
                        buf.append(ch)
                        j += 2
                        continue
                    closed = True
                    break
                buf.append(sql[j])
                j += 1
            if not closed:
                bad("書き方", "引用が閉じていない")
                break
            if ch == "'":
                lits.append("".join(buf))
                out.append(f" {LIT} ")
            else:
                idents.append("".join(buf))
                out.append(f" {QID} ")
            i = j + 1
            continue
        if sql.startswith("--", i):
            if i + 2 < n and not sql[i + 2].isspace():
                bad("書き方", "-- の直後に空白が無い（MySQL では注釈にならず、文の続きとして読まれる）")
            # PostgreSQL は \r でも注釈を終える。短い方で終えて、後ろの文を見落とさない
            while i < n and sql[i] not in "\n\r":
                i += 1
            continue
        if sql.startswith("/*", i):
            bad("書き方", "/* */ の注釈は使わない（MySQL は /*! */ の中を文として回す）")
            i += 2
            continue
        if ch == "#":
            bad("書き方", "# は使わない（MySQL では注釈の始まり）")
        elif ch == "$":
            bad("書き方", "$ は使わない（ドルの引用と変数）")
        out.append(ch)
        i += 1
    return "".join(out), lits, probs, idents


def close_paren(toks, k):
    depth = 0
    for j in range(k, len(toks)):
        if toks[j] == "(":
            depth += 1
        elif toks[j] == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    return None


def parse_with(toks, k):
    """WITH 名前 [(列…)] AS (…) [, …] を読む。返り値は (名前の列の一覧を開く括弧の位置, 本体の位置)。読めなければ (None, None)。"""
    cols = set()
    k += 1
    if k < len(toks) and toks[k] == "RECURSIVE":
        k += 1
    while True:
        if k >= len(toks) or not is_name(toks[k]):
            return None, None
        k += 1
        if k < len(toks) and toks[k] == "(":
            cols.add(k)
            k = close_paren(toks, k)
            if k is None:
                return None, None
        if k >= len(toks) or toks[k] != "AS":
            return None, None
        k += 1
        if k < len(toks) and toks[k] == "NOT":
            k += 1
        if k < len(toks) and toks[k] == "MATERIALIZED":
            k += 1
        if k >= len(toks) or toks[k] != "(":
            return None, None
        k = close_paren(toks, k)
        if k is None:
            return None, None
        if k < len(toks) and toks[k] == ",":
            k += 1
            continue
        return cols, k


def check_select(sql):
    """許す文の一覧（1 文だけの SELECT と WITH … SELECT、許す関数）で確かめる。返り値は (問題の一覧, 文字の値, 語の列)。"""
    text, lits, probs, _ = scan_sql(sql or "")
    norm = re.sub(r"\s+", " ", text).strip().upper()
    body = [p.strip() for p in norm.split(";") if p.strip()]
    if not body:
        return probs + [("一覧の外の文", "文が無い")], lits, []
    if len(body) > 1:
        probs.append(("1 文だけ", f"文が {len(body)} つある。; で区切らず、1 文だけにする"))
    toks = TOKEN_RX.findall(body[0])
    k = 0
    while k < len(toks) and toks[k] == "(":
        k += 1
    head = toks[k] if k < len(toks) else ""
    cte_cols = set()
    if head == "WITH":
        cols, main = parse_with(toks, k)
        if cols is None:
            probs.append(("一覧の外の文", "WITH の形が読めない（WITH 名前 AS (…) SELECT … の形にする）"))
        else:
            cte_cols = cols
            while main < len(toks) and toks[main] == "(":
                main += 1
            if main >= len(toks) or toks[main] != "SELECT":
                probs.append(("一覧の外の文", "WITH の後の本体が SELECT ではない"))
    elif head != "SELECT":
        probs.append(("一覧の外の文", f"許す文は SELECT と WITH … SELECT だけ（「{short_sql(sql, 40)}」）"))
    words = {t for t in toks if NAME_RX.fullmatch(t)}
    bad_words = sorted(words & FORBIDDEN)
    if bad_words:
        probs.append(("一覧の外の語", f"{', '.join(bad_words)} は読み取りの文に使わない"))
    if LOCK_RX.search(" ".join(toks)):
        probs.append(("行のロック", "FOR UPDATE と FOR SHARE は行をロックする"))
    if ":=" in text:
        probs.append(("変数への代入", ":= で値を書き換えない"))
    for idx, t in enumerate(toks):
        if t != "(" or idx == 0 or idx in cte_cols:
            continue
        prev = toks[idx - 1]
        if prev == LIT:
            probs.append(("関数の呼び出し", "文字の値の直後に括弧がある（UESCAPE や型の書き方で、名前を隠した関数を呼ぶ形を防ぐ）"))
            continue
        if not is_name(prev) or prev in ALLOWED_FUNCS or prev in PAREN_WORDS:
            continue
        if idx >= 2 and toks[idx - 2] == "AS":
            continue  # 別名の列の一覧（AS g(x)）
        name = "引用した名前" if prev == QID else prev.lower()
        probs.append(("関数の呼び出し", f"{name}(…) は許す関数の一覧の外（外へ書き出す関数と、状態を変える関数を防ぐ）"))
    seen, out = set(), []
    for p in probs:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out, lits, toks


def _cond_scan(sql):
    """絞り込みの比べを拾う。返り値は [(列の名前（小文字）, 値, 種類)]。種類は lit（文字の値）か ident（"…" の引用）。
    sqlite は列に無い "…" を文字の値と読むので、引用の側も拾い、列の名前かどうかは辞書と照らす側で決める。
    lower(status) = 'x' のように関数で包んだ列は、括弧の中の最初の列の名前を使う。"""
    _, lits, toks = check_select(sql)
    idents = scan_sql(sql or "")[3]
    pos, names, n, m = {}, {}, 0, 0
    for i, t in enumerate(toks):
        if t == LIT:
            pos[i] = lits[n] if n < len(lits) else ""
            n += 1
        elif t == QID:
            names[i] = idents[m] if m < len(idents) else ""
            m += 1

    def col_at(i):
        """i の語が名前ならその名前（大文字）。"status" のように引用した名前は中身を使う。"""
        if 0 <= i < len(toks):
            if toks[i] == QID:
                return names.get(i, "").upper() or None
            if NAME_RX.fullmatch(toks[i]) and toks[i] not in PAREN_WORDS:
                return toks[i]
        return None

    def col_before(i):
        """比べの左の列。o.status の最後の部分か、関数で包んだ列（lower(o.status)）の中の列。"""
        if col_at(i):
            return col_at(i)
        if 0 <= i < len(toks) and toks[i] == ")":
            depth, j = 0, i
            while j >= 0:
                depth += 1 if toks[j] == ")" else -1 if toks[j] == "(" else 0
                if depth == 0:
                    break
                j -= 1
            if j < 1 or toks[j - 1] not in VALUE_FUNCS:
                return None  # typeof(x) = 'text' のような、値を変える関数の比べは条件の値に数えない
            for k in range(j + 1, i):
                c = col_at(k)
                if c and c not in ALLOWED_FUNCS and not (k + 1 < len(toks) and toks[k + 1] in ("(", ".")):
                    return c
        return None

    def col_after(j):
        k = j
        while col_at(k + 2) and k + 1 < len(toks) and toks[k + 1] == ".":
            k += 2  # o.flag のような名前は、最後の部分を列の名前にする
        if col_at(k) and not (k + 1 < len(toks) and toks[k + 1] == "("):
            return col_at(k)
        if k < len(toks) and k + 1 < len(toks) and toks[k + 1] == "(":
            end = close_paren(toks, k + 1)
            return col_before(end - 1) if end else None
        return None

    out = []
    for i, t in enumerate(toks):
        if t in ("=", "!", "<", ">") and i + 1 < len(toks):
            j = i + 1
            if toks[i:i + 2] in (["!", "="], ["<", ">"]):
                j = i + 2
            elif t in ("<", ">", "!"):
                continue
            if i >= 1 and toks[i - 1] == "=" or (j < len(toks) and toks[j] == "="):
                continue
            left = col_before(i - 1)
            if j < len(toks) and left:
                if toks[j] == LIT:
                    out.append((left.lower(), pos[j], "lit"))
                elif toks[j] == QID and not (j + 1 < len(toks) and toks[j + 1] in (".", "(")):
                    out.append((left.lower(), names.get(j, ""), "ident"))
            if i >= 1 and toks[i - 1] == LIT and j < len(toks):
                right = col_after(j)
                if right:
                    out.append((right.lower(), pos[i - 1], "lit"))
        if t == "IN" and i >= 1 and i + 1 < len(toks) and toks[i + 1] == "(":
            col = col_before(i - 2) if toks[i - 1] == "NOT" else col_before(i - 1)
            if not col:
                continue
            end = close_paren(toks, i + 1) or len(toks)
            for j in range(i + 2, end - 1):
                if toks[j] == LIT:
                    out.append((col.lower(), pos[j], "lit"))
                elif toks[j] == QID:
                    out.append((col.lower(), names.get(j, ""), "ident"))
    return out


def condition_values(sql):
    """絞り込みで、名前と比べている文字の値を拾う。返り値は [(列の名前（小文字）, 値)]。"""
    return [(c, v) for c, v, kind in _cond_scan(sql) if kind == "lit"]


def condition_idents(sql):
    """比べの右に置いた "…" の引用。列の名前でなければ、sqlite は文字の値として読む。返り値は [(列の名前（小文字）, 引用の中身)]。"""
    return [(c, v) for c, v, kind in _cond_scan(sql) if kind == "ident"]


# ---------------------------------------------------------------- 個人が分かる値
PII_NAME = re.compile(
    r"(e_?mail|mail_?addr|phone|^tel$|^tel_|_tel$|telephone|mobile|^fax|address|^addr|_addr$|zip_?code|^zip$|postal|post_?code|"
    r"birth|^dob$|first_?name|last_?name|full_?name|family_?name|given_?name|middle_?name|real_?name|kana|furigana|"
    r"password|passwd|pass_?hash|^pwd$|secret|token|api_?key|^ip$|^ip_|_ip$|ip_?addr|card_?(no|num)|credit|ssn|"
    r"my_?number|passport|licen[cs]e_?(no|num)|account_?(no|num)|bank|iban|gender|note|memo|comment|remark|message|^body$|"
    r"inquiry|owner|author|assignee|recipient|sender|contact|"
    r"氏名|姓名|住所|電話|携帯|メール|生年月日|誕生日|郵便番号|ふりがな|フリガナ|カナ|パスワード|暗証|口座|カード番号|"
    r"備考|メモ|問い?合わ?せ|担当者|宛名|宛先|連絡先|性別)", re.I)
PERSON_TABLE = re.compile(r"(user|customer|member|account|person|people|staff|employee|contact|profile|client|patient|"
                          r"student|guest|buyer|seller|recipient|sender|owner|"
                          r"顧客|会員|利用者|ユーザー?|社員|従業員|職員|担当|客|患者|学生|生徒|購入者|受取人|送り主|連絡先)", re.I)
NAME_LIKE = {"username", "user_name", "nickname", "display_name", "screen_name", "ニックネーム"}
PERSON_NAME = {"name", "名前", "なまえ"}  # 人の表のときだけ個人情報らしい名前とする（品物の name は数える）
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PHONE_RX = re.compile(r"(?<![\d-])(?:0\d{1,4}[- ]\d{1,4}[- ]\d{3,4}|0\d{1,4}\(\d{1,4}\)\d{3,4}|0[5789]0\d{8}|"
                      r"\+\d{1,3}[- ]?\d{1,4}[- ]?\d{2,4}[- ]?\d{3,4})(?![\d-])")
# 全角の数字と線、全角の空白を半角にそろえてから、電話番号の形を探す
WIDE = str.maketrans("０１２３４５６７８９－ー‐−–—（）　", "0123456789------() ")
AGG_SAFE = {"COUNT", "SUM", "AVG", "TOTAL"}  # 中の列の値を出さない集計
VALUE_FUNCS = {"LOWER", "UPPER", "TRIM", "LTRIM", "RTRIM", "BTRIM", "COALESCE", "IFNULL", "NVL", "CAST", "CONVERT"}  # 値をほぼ保つ関数
RATIO_NAME = re.compile(r"(pct|percent|ratio|rate|share|割合|率|比)", re.I)


def pii_like(table, column):
    c = (column or "").lower()
    if PII_NAME.search(c) or c in NAME_LIKE:
        return True
    return c in PERSON_NAME and bool(table) and bool(PERSON_TABLE.search(table))


def pii_shapes(text):
    """メールと電話番号の形の数。長い値でも時間が字の数に比例するよう、メールは @ の前後だけを照らす。"""
    n = 0
    if "@" in text:
        ats = [m.start() for m in re.finditer("@", text)]
        if len(ats) > MAX_AT:
            return len(ats)
        for p in ats:
            lo = max(0, p - 128)
            seg = text[lo:p + 256]
            if any(m.start() <= p - lo < m.end() for m in EMAIL_RX.finditer(seg)):
                n += 1
    return n + len(PHONE_RX.findall(text.translate(WIDE)))


def pii_hits(rows):
    return sum(pii_shapes(v) for r in rows for v in r if isinstance(v, str))


def long_cells(rows):
    return sum(1 for r in rows for v in r if isinstance(v, str) and len(v) > MAX_CELL)


STOP_FROM = {"WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "UNION", "EXCEPT", "INTERSECT", "ON", "USING", "JOIN", "LEFT",
             "RIGHT", "INNER", "OUTER", "FULL", "CROSS", "NATURAL", "WINDOW", "OFFSET", "FETCH", "SELECT", "TABLESAMPLE"}


def sql_words(sql):
    """文の語の並び。引用した名前は中身（大文字）にする。返り値は [(語, 名前か)]。"""
    _, _, toks = check_select(sql)
    idents = scan_sql(sql or "")[3]
    out, m = [], 0
    for t in toks:
        if t == QID:
            out.append(((idents[m] if m < len(idents) else "").upper(), True))
            m += 1
        else:
            out.append((t, t != LIT and bool(NAME_RX.fullmatch(t))))
    return out


def sql_sources(words):
    """FROM と JOIN の表と別名。返り値は ({別名か表の名前（小文字）: 表の名前（小文字）}, [表の名前（小文字）])。"""
    alias, tables, i, n = {}, [], 0, len(words)
    while i < n:
        w = words[i][0]
        i += 1
        if w not in ("FROM", "JOIN"):
            continue
        from_clause = w == "FROM"
        while i < n:
            if words[i][0] in ("LATERAL", "ONLY"):
                i += 1
                continue
            if not words[i][1]:
                break  # 副問い合わせ。中の FROM は別に拾う
            name = words[i][0]
            while i + 2 < n and words[i + 1][0] == "." and words[i + 2][1]:
                i += 2
                name = words[i][0]
            i += 1
            tables.append(name.lower())
            alias.setdefault(name.lower(), name.lower())
            if i < n and words[i][0] == "AS":
                i += 1
            if i < n and words[i][1] and words[i][0] not in STOP_FROM:
                alias[words[i][0].lower()] = name.lower()
                i += 1
            if from_clause and i < n and words[i][0] == ",":
                i += 1
                continue
            break
    return alias, tables


def pii_in_projection(sql):
    """SELECT と FROM の間で、個人情報らしい列を集計の外で出す所。返り値は ([列の名前], * を出すか)。
    COUNT・SUM・AVG・TOTAL の中と、IS NULL の比べは値を出さないので数えない。別名（AS の後ろ）も数えない。"""
    words = sql_words(sql)
    alias, tables = sql_sources(words)
    stack, inside = [], []
    for k, (w, isname) in enumerate(words):
        inside.append([words[j - 1][0] if j > 0 else "" for j in stack])  # 囲む関数の名前
        if w == "(":
            stack.append(k)
        elif w == ")" and stack:
            stack.pop()
    # 括弧ごとに、問い合わせの括弧か関数の括弧かを持つ。関数の括弧は、開いた所の射影かどうかを引き継ぐ
    ctx, proj = [["query", False]], []
    for k, (w, isname) in enumerate(words):
        if w == "(":
            nxt = words[k + 1][0] if k + 1 < len(words) else ""
            ctx.append(["query", False] if nxt in ("SELECT", "WITH") else ["func", ctx[-1][1]])
            proj.append(False)
            continue
        if w == ")":
            if len(ctx) > 1:
                ctx.pop()
            proj.append(False)
            continue
        top = ctx[-1]
        if top[0] == "query":
            if w == "SELECT":
                top[1] = True
                proj.append(False)
                continue
            if w in ("FROM", "WHERE", "GROUP", "HAVING", "ORDER", "LIMIT", "UNION", "EXCEPT", "INTERSECT", "WINDOW"):
                top[1] = False
        proj.append(top[1])
    shown, star = [], False
    for k, (w, isname) in enumerate(words):
        if not proj[k]:
            continue
        safe = any(f in AGG_SAFE for f in inside[k])
        if w == "*" and not safe and (k == 0 or words[k - 1][0] in ("SELECT", ",", ".", "DISTINCT", "ALL")):
            star = True
            continue
        if not isname or safe:
            continue
        if k + 1 < len(words) and words[k + 1][0] in ("(", "."):
            continue  # 関数の名前か、表の別名
        if k > 0 and words[k - 1][0] == "AS":
            continue  # 列の別名
        if k + 1 < len(words) and words[k + 1][0] == "IS":
            continue  # IS NULL の比べは、値を出さない
        qual = words[k - 2][0].lower() if k >= 2 and words[k - 1][0] == "." else ""
        cands = [alias.get(qual, qual)] if qual else (tables or [None])
        if any(pii_like(t, w) for t in cands):
            shown.append(w.lower())
    return shown, star


def pii_problems(sql, cols, rows):
    """記録に残せない結果の理由。返り値は [理由]（空なら残してよい）。"""
    out = []
    shapes = pii_hits(rows) + pii_shapes(sql or "")
    if shapes:
        out.append(f"結果か文に、メールか電話番号の形が {shapes} 個ある")
    try:
        shown, star = pii_in_projection(sql or "")
    except Exception:  # 読めない文は、許す文の検査が別に落とす
        shown, star = [], False
    if shown:
        out.append(f"個人情報らしい列（{', '.join(sorted(set(shown)))}）を、COUNT などの集計の外で出す")
    _, tables = sql_sources(sql_words(sql or ""))
    for k, c in enumerate(cols or []):
        vals = [r[k] for r in rows if k < len(r) and r[k] is not None]
        text = any(isinstance(v, str) and not re.fullmatch(r"-?\d+(\.\d+)?", v) for v in vals)
        # 名前だけで決まる列（email、電話、氏名）は文字の値で、表で決まる列（人の表の name）は * の展開のときに見る
        if (pii_like(None, str(c)) and text) or (star and vals and any(pii_like(t, str(c)) for t in (tables or [None]))):
            out.append(f"結果の列 {c} は個人情報らしい名前で、値がある")
    if long_cells(rows):
        out.append(f"{MAX_CELL} 字を超える値が {long_cells(rows)} 個ある（長い値は残さない）")
    return out


# ---------------------------------------------------------------- DB
def plain(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f"<BLOB {len(bytes(v))} バイト>"
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return str(v)
    return v


def number_or_text(s):
    if s is None:
        return None
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    return s


def qi(name, kind="sqlite"):
    if kind == "mysql":
        return "`" + name.replace("`", "``") + "`"
    return '"' + name.replace('"', '""') + '"'


def qs(text):
    return "'" + text.replace("'", "''") + "'"


def open_sqlite(target):
    """sqlite を読み取り専用で開く。URI を渡されたときは mode=ro だけを許す。返り値は (接続, 開き方の印, ファイル名)。"""
    s = str(target)
    if s.startswith("file:"):
        parts = urllib.parse.urlsplit(s)
        params = urllib.parse.parse_qs(parts.query)
        mode = (params.get("mode") or [""])[0]
        if mode != "ro":
            raise ToolError("読み取りだけ", f"読み取り専用でない開き方（mode={mode or '指定なし'}）。mode=ro で開く")
        uri, name = s, pathlib.Path(urllib.parse.unquote(parts.path)).name
    else:
        p = pathlib.Path(s).expanduser()
        if not p.is_file():
            raise ToolError("DB が無い", f"{s} が無い")
        p = p.resolve()
        uri, name = "file:" + urllib.parse.quote(str(p)) + "?mode=ro", p.name
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2.0, isolation_level=None)
        conn.execute("PRAGMA query_only = ON")
        on = conn.execute("PRAGMA query_only").fetchone()[0]
        conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as e:
        raise ToolError("DB のエラー", f"sqlite の DB として開けない（{e}）")
    if on != 1:
        raise ToolError("読み取りだけ", "query_only が効かない")
    return conn, OPEN_MARKS["sqlite"], name


class SqliteEngine:
    kind = "sqlite"

    def __init__(self, target=None, timeout_ms=TIMEOUT_MS, conn=None, label=""):
        if conn is not None:
            self.conn, self.open_mark, self.label = conn, OPEN_MARKS["sqlite"], label
        else:
            self.conn, self.open_mark, self.label = open_sqlite(target)
        self.timeout_ms = timeout_ms

    def run(self, sql, max_rows=MAX_ROWS):
        probs, _, _ = check_select(sql)
        if probs:
            raise ToolError("読み取りだけ", "; ".join(f"[{r}] {m}" for r, m in probs))
        deadline = time.monotonic() + self.timeout_ms / 1000.0
        self.conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        try:
            cur = self.conn.execute(sql)
            cols = [d[0] for d in (cur.description or [])]
            rows = cur.fetchmany(max_rows + 1) if max_rows else cur.fetchall()
        except sqlite3.OperationalError as e:
            if "interrupt" in str(e):
                raise ToolError("打ち切り", f"{self.timeout_ms}ms を超えた（{short_sql(sql, 40)}）")
            raise ToolError("DB のエラー", str(e).split("\n")[0])
        except sqlite3.Error as e:
            raise ToolError("DB のエラー", str(e).split("\n")[0])
        finally:
            self.conn.set_progress_handler(None, 0)
        truncated = bool(max_rows) and len(rows) > max_rows
        if truncated:
            rows = rows[:max_rows]
        return cols, [[plain(v) for v in r] for r in rows], truncated


LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1", "[::1]"}


def _host_ok(host):
    return all(h.strip().lower() in LOCAL_HOSTS or h.strip().startswith(("/", "@")) for h in str(host).split(","))


def local_target(kind, database="", defaults="", environ=None):
    """PostgreSQL と MySQL の向き先が手元（localhost、127.0.0.1、::1、ソケット）かを見る。
    返り値は (問題の文, MySQL に渡す host)。問題が無ければ文は空。秘密の値（パスワード）は読まない。"""
    env = os.environ if environ is None else environ
    if kind == "postgres":
        if env.get("PGSERVICE") or env.get("PGSERVICEFILE") or re.search(r"(?i)\bservice\s*=", database or ""):
            return "PGSERVICE（接続の名前）では向き先を確かめられない。PGHOST に手元の向き先を渡す", ""
        hosts = [env.get("PGHOST", ""), env.get("PGHOSTADDR", "")]
        db = database or ""
        if "://" in db:
            parts = urllib.parse.urlsplit(db)
            hosts.append(parts.netloc.rsplit("@", 1)[-1].split(":")[0] if parts.netloc else "")
            q = urllib.parse.parse_qs(parts.query)
            hosts += q.get("host", []) + q.get("hostaddr", [])
        elif "=" in db:
            hosts += [m.group(2).strip("'") for m in re.finditer(r"(?i)\b(host|hostaddr)\s*=\s*('[^']*'|\S+)", db)]
        bad = [h for h in hosts if h and not _host_ok(h)]
        if bad:
            return f"向き先 {', '.join(bad)} は手元ではない。AI は手元の DB だけを読む（本番の数は依頼者が回して --import）", ""
        return "", ""
    host = env.get("MYSQL_HOST", "")
    if defaults:
        try:
            for line in pathlib.Path(defaults).read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.match(r"^\s*host\s*=\s*['\"]?([^'\"#;\s]+)", line, re.I)  # host の行だけを読む
                if m:
                    host = m.group(1)
        except OSError as e:
            return f"設定ファイルを読めず、向き先を確かめられない（{e.strerror}）", ""
    if not _host_ok(host):
        return f"向き先 {host} は手元ではない。AI は手元の DB だけを読む（本番の数は依頼者が回して --import）", ""
    return "", host or "localhost"


def env_for_db(env):
    """DB に道具でつなぐときの環境の名前。本番の名前は、依頼者が回した結果の取り込み（--import）だけに使う。"""
    if "本番" in (env or "") and "写し" not in env:
        raise ToolError("環境の名前", f"「{env}」は本番の名前。AI は本番につながない。本番の数は依頼者が回し、--import で取り込む")


class CliEngine:
    """psql か mysql を呼ぶ。接続の値は道具が持たず、PG* の環境変数か MySQL の設定ファイルに任せる。"""

    def __init__(self, kind, timeout_ms=TIMEOUT_MS, database="", defaults="", path=None, environ=None):
        self.kind, self.timeout_ms, self.database, self.defaults = kind, timeout_ms, database, defaults
        self.environ = dict(os.environ if environ is None else environ)
        why, self.host = local_target(kind, database, defaults, self.environ)
        if why:
            raise ToolError("本番につながない", why)
        exe = "psql" if kind == "postgres" else "mysql"
        found = shutil.which(exe, path=path)
        if not found:
            raise ToolError("道具が無い", f"{exe} が入っていない（SKIP は FAIL と同じ）。{exe} がある所で回すか、"
                            "集計のクエリを依頼者に渡し、結果を data-query.sh --import で取り込む")
        self.exe, self.open_mark = found, OPEN_MARKS[kind]
        self.label = database or kind
        if kind == "mysql" and not database:
            raise ToolError("使い方", "MySQL は --database でスキーマの名前を渡す")

    def run(self, sql, max_rows=MAX_ROWS):
        probs, _, _ = check_select(sql)
        if probs:
            raise ToolError("読み取りだけ", "; ".join(f"[{r}] {m}" for r, m in probs))
        env = dict(self.environ)
        if self.kind == "postgres":
            opts = f"-c default_transaction_read_only=on -c statement_timeout={self.timeout_ms}"
            env["PGOPTIONS"] = (env.get("PGOPTIONS", "") + " " + opts).strip()
            env.setdefault("PGCONNECT_TIMEOUT", "5")
            cmd = [self.exe, "-X", "-q", "--csv", "-P", "null=" + NULL_MARK, "-v", "ON_ERROR_STOP=1"]
            if self.database:
                cmd += ["-d", self.database]
            cmd += ["-c", sql]
        else:
            # 設定ファイルはこの 1 本だけを読ませ（ほかの my.cnf の host を拾わない）、確かめた向き先をコマンドで渡す
            cmd = [self.exe, "--defaults-file=" + self.defaults] if self.defaults else [self.exe, "--no-defaults"]
            cmd += ["--host=" + self.host, "--xml", "--batch", "--database=" + self.database,
                    f"--init-command=SET SESSION transaction_read_only = 1, SESSION max_execution_time = {self.timeout_ms}",
                    "-e", sql]
        try:
            p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=self.timeout_ms / 1000.0 + 15)
        except subprocess.TimeoutExpired:
            raise ToolError("打ち切り", f"{self.timeout_ms}ms を超えた（{short_sql(sql, 40)}）")
        if p.returncode != 0:
            raise ToolError("DB のエラー", (p.stderr.strip().split("\n") or [""])[0][:200])
        if self.kind == "postgres":
            table = list(csv.reader(io.StringIO(p.stdout)))
            cols = table[0] if table else []
            rows = [[None if v == NULL_MARK else number_or_text(v) for v in r] for r in table[1:]]
        else:
            cols, rows = [], []
            if "<!DOCTYPE" in p.stdout or "<!ENTITY" in p.stdout:
                # mysql の --xml は DTD を出さない。値は &lt; に替わるので、宣言があれば読まずに止める（外部の実体と膨張を防ぐ）
                raise ToolError("DB のエラー", "mysql の出力に DTD か実体の宣言がある。読まずに止めた")
            root = ET.fromstring(p.stdout) if p.stdout.strip() else None
            nil = "{http://www.w3.org/2001/XMLSchema-instance}nil"
            for row in (root.findall("row") if root is not None else []):
                fields = row.findall("field")
                if not cols:
                    cols = [f.get("name", "") for f in fields]
                rows.append([None if f.get(nil) == "true" else number_or_text(f.text or "") for f in fields])
        truncated = bool(max_rows) and len(rows) > max_rows
        return cols, rows[:max_rows] if truncated else rows, truncated


def make_engine(args):
    engine = getattr(args, "engine", None) or "sqlite"
    if engine == "sqlite":
        if not getattr(args, "db", None):
            raise ToolError("使い方", "--db に sqlite のファイルを渡す（PostgreSQL と MySQL は --engine）")
        return SqliteEngine(args.db, args.timeout_ms)
    return CliEngine(engine, args.timeout_ms, getattr(args, "database", "") or "", getattr(args, "mysql_defaults", "") or "")


def add_db_args(ap):
    ap.add_argument("--db", help="sqlite のファイル（URI なら mode=ro だけ）")
    ap.add_argument("--engine", choices=["sqlite", "postgres", "mysql"], default="sqlite")
    ap.add_argument("--database", default="", help="PostgreSQL の DB の名前か、MySQL のスキーマの名前（値に秘密を入れない）")
    ap.add_argument("--pg-schema", default="public")
    ap.add_argument("--mysql-defaults", default="", help="MySQL の接続の設定ファイル（中身は道具が読まない）")
    ap.add_argument("--timeout-ms", type=int, default=TIMEOUT_MS)


# ---------------------------------------------------------------- クエリの記録
def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def rec_hash(rec):
    body = {k: v for k, v in rec.items() if k != "hash"}
    s = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def new_record(engine_kind, open_mark, env, tool, purpose, sql, cols, rows, truncated, meta=None):
    rec = {"id": None, "env": env, "at": now_iso(), "engine": engine_kind, "open": open_mark, "tool": tool,
           "purpose": purpose or "", "sql": sql, "columns": cols, "rows": rows, "row_count": len(rows),
           "truncated": truncated}
    rec.update(meta or {})
    return rec


def append_records(log_path, recs):
    """番号（Q-001 の形の続き番号）を振り、ハッシュ値を付けて記録に足す。同時に書いても重ならないようロックする。"""
    p = pathlib.Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            last = 0
            for line in f.read().splitlines():
                try:
                    rid = str(json.loads(line).get("id", ""))
                except (ValueError, AttributeError):
                    continue
                m = re.fullmatch(r"Q-(\d+)", rid)
                if m:
                    last = max(last, int(m.group(1)))
            for rec in recs:
                last += 1
                rec["id"] = f"Q-{last:03d}"
                rec["hash"] = rec_hash(rec)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return recs


def load_log(path):
    """返り値は ([(行の番号, 記録)], [(行の番号, 読めない理由)])。"""
    recs, errs = [], []
    for no, line in enumerate(pathlib.Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError as e:
            errs.append((no, f"JSON として読めない（{e}）"))
            continue
        if not isinstance(obj, dict):
            errs.append((no, "1 行が 1 つの JSON の物ではない"))
            continue
        recs.append((no, obj))
    return recs, errs


def env_required(env):
    if not (env or "").strip():
        raise ToolError("環境の名前", "--env に環境の名前（手元の作り物、本番の写し（時点）、検証環境、本番の集計の書き出し）を渡す")


def show_result(cols, rows, limit=20):
    out = ["\t".join(str(c) for c in cols)]
    for r in rows[:limit]:
        out.append("\t".join("NULL" if v is None else str(v) for v in r))
    if len(rows) > limit:
        out.append(f"…（ほか {len(rows) - limit} 行。全部は記録にある）")
    return out


# ---------------------------------------------------------------- 形の写し（schema-snapshot）
def norm_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def shape_sqlite(eng):
    tables, views, triggers = {}, {}, {}
    _, rows, _ = eng.run("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                         "ORDER BY type, name", max_rows=0)
    sqls = {}
    for typ, name, tbl, sql in rows:
        if typ == "table":
            tables[name] = {"columns": [], "indexes": [], "foreign_keys": [],
                            "without_rowid": bool(re.search(r"WITHOUT\s+ROWID", sql or "", re.I))}
            sqls[name] = sql or ""
            if re.match(r"\s*CREATE\s+VIRTUAL\s+TABLE", sql or "", re.I):
                tables[name]["virtual"] = True  # 印は持つ表だけに付け、ふつうの表の形のハッシュ値を変えない
        elif typ == "view":
            views[name] = norm_ws(sql)
        elif typ == "trigger":
            triggers[name] = {"table": tbl, "sql": norm_ws(sql)}
    virtuals = [n for n in tables if tables[n].get("virtual")]
    for name in tables:
        owner = next((v for v in virtuals if name != v and name.startswith(v + "_")), None)
        if owner:
            tables[name]["shadow_of"] = owner  # 全文検索などの影の表。中身は元の表の値の写し
    for name in sorted(tables):
        t = tables[name]
        # table_xinfo は生成列と隠れ列も返す（table_info は返さない）。hidden は 0 でない列にだけ書く
        _, cols, _ = eng.run(f'SELECT name, type, "notnull", dflt_value, pk, hidden FROM pragma_table_xinfo({qs(name)}) '
                             "ORDER BY cid", max_rows=0)
        t["columns"] = []
        for c in cols:
            col = {"name": c[0], "type": norm_ws(c[1]).upper(), "notnull": bool(c[2]), "default": c[3], "pk": c[4]}
            if c[5]:
                col["hidden"] = c[5]
            t["columns"].append(col)
        if any(c.get("hidden") for c in t["columns"]) and not t.get("virtual"):
            t["sql"] = norm_ws(sqls.get(name))  # 生成列の式も形に入れ、式が変われば形のハッシュ値も変わる
        _, idx, _ = eng.run(f'SELECT name, "unique", origin, partial FROM pragma_index_list({qs(name)}) ORDER BY name', max_rows=0)
        for iname, uniq, origin, partial in idx:
            _, icols, _ = eng.run(f"SELECT name FROM pragma_index_info({qs(iname)}) ORDER BY seqno", max_rows=0)
            t["indexes"].append({"name": iname, "unique": bool(uniq), "origin": origin, "partial": bool(partial),
                                 "columns": [c[0] for c in icols]})
        _, fks, _ = eng.run(f'SELECT "table", "from", "to", on_update, on_delete FROM pragma_foreign_key_list({qs(name)}) '
                            "ORDER BY id, seq", max_rows=0)
        t["foreign_keys"] = [{"column": f[1], "ref_table": f[0], "ref_column": f[2], "on_update": f[3], "on_delete": f[4]}
                             for f in fks]
    return {"tables": tables, "views": views, "triggers": triggers}


def shape_cli(eng, schema):
    """PostgreSQL と MySQL の形を information_schema から読む。"""
    pg = eng.kind == "postgres"
    sch = qs(schema if pg else eng.database)
    tables, views, triggers = {}, {}, {}
    _, rows, _ = eng.run("SELECT c.table_name, c.column_name, c.data_type, c.is_nullable, c.column_default "
                         "FROM information_schema.columns c JOIN information_schema.tables t "
                         "ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
                         f"WHERE c.table_schema = {sch} AND t.table_type = 'BASE TABLE' "
                         "ORDER BY c.table_name, c.ordinal_position", max_rows=0)
    for tname, cname, dtype, nullable, default in rows:
        t = tables.setdefault(tname, {"columns": [], "indexes": [], "foreign_keys": [], "without_rowid": False})
        t["columns"].append({"name": cname, "type": norm_ws(str(dtype)).upper(), "notnull": nullable == "NO",
                             "default": None if default is None else str(default), "pk": 0})
    _, rows, _ = eng.run("SELECT k.table_name, k.column_name, k.ordinal_position FROM information_schema.table_constraints c "
                         "JOIN information_schema.key_column_usage k ON k.constraint_name = c.constraint_name "
                         "AND k.table_schema = c.table_schema AND k.table_name = c.table_name "
                         f"WHERE c.table_schema = {sch} AND c.constraint_type = 'PRIMARY KEY'", max_rows=0)
    for tname, cname, pos in rows:
        for c in tables.get(tname, {}).get("columns", []):
            if c["name"] == cname:
                c["pk"] = int(pos or 1)
    if pg:
        _, rows, _ = eng.run("SELECT tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name "
                             "FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu "
                             "ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
                             "JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name "
                             f"AND ccu.table_schema = tc.table_schema WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = {sch} "
                             "ORDER BY 1, 2", max_rows=0)
        _, idx, _ = eng.run(f"SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = {sch} ORDER BY 1, 2", max_rows=0)
        for tname, iname, idef in idx:
            if tname in tables:
                tables[tname]["indexes"].append({"name": iname, "definition": norm_ws(idef)})
    else:
        _, rows, _ = eng.run("SELECT table_name, column_name, referenced_table_name, referenced_column_name "
                             f"FROM information_schema.key_column_usage WHERE table_schema = {sch} "
                             "AND referenced_table_name IS NOT NULL ORDER BY 1, 2", max_rows=0)
        _, idx, _ = eng.run("SELECT table_name, index_name, non_unique, column_name FROM information_schema.statistics "
                            f"WHERE table_schema = {sch} ORDER BY 1, 2, seq_in_index", max_rows=0)
        for tname, iname, non_unique, cname in idx:
            if tname in tables:
                cur = [i for i in tables[tname]["indexes"] if i["name"] == iname]
                if cur:
                    cur[0]["columns"].append(cname)
                else:
                    tables[tname]["indexes"].append({"name": iname, "unique": str(non_unique) == "0", "columns": [cname]})
    for tname, cname, rt, rc in rows:
        if tname in tables:
            tables[tname]["foreign_keys"].append({"column": cname, "ref_table": rt, "ref_column": rc})
    _, trg, _ = eng.run("SELECT event_object_table, trigger_name, event_manipulation, action_timing, action_statement "
                        f"FROM information_schema.triggers WHERE trigger_schema = {sch} ORDER BY 2, 3", max_rows=0)
    for tname, name, event, timing, stmt in trg:
        triggers.setdefault(name, {"table": tname, "sql": f"{timing} {event} ON {tname} {norm_ws(stmt)}"})
    _, vw, _ = eng.run(f"SELECT table_name, view_definition FROM information_schema.views WHERE table_schema = {sch}", max_rows=0)
    for name, definition in vw:
        views[name] = norm_ws(definition)
    return {"tables": tables, "views": views, "triggers": triggers}


def read_shape(eng, schema="public"):
    return shape_sqlite(eng) if eng.kind == "sqlite" else shape_cli(eng, schema)


def shape_hash(shape):
    s = json.dumps(shape, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def shape_from_migrations(paths):
    """マイグレーションの SQL（sqlite で流せる素の SQL）をメモリの DB に流し、形を作る。ファイルへ書き出す文は流さない。"""
    conn = sqlite3.connect(":memory:")
    deny_funcs = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}

    def auth(action, a1, a2, db, src):
        if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and (a2 or "").lower() in deny_funcs:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(auth)
    for p in paths:
        text = pathlib.Path(p).read_text(encoding="utf-8")
        if re.search(r"\b(ATTACH|VACUUM)\b|load_extension|writefile", text, re.I):
            raise ToolError("マイグレーション", f"{p} に ATTACH・VACUUM・load_extension・writefile がある（ファイルに書き出せる）")
        try:
            conn.executescript(text)
        except sqlite3.Error as e:
            raise ToolError("マイグレーション", f"{p} を流せない（{e}）")
    # 認可の関数は外さない（python 3.10 までは None で外せず、全部を断る）。断るのは ATTACH と書き出す関数だけなので、形は読める
    return shape_sqlite(SqliteEngine(conn=conn, label="migrations"))


def diff_shapes(a, b, la="実物", lb="比べる形"):
    out = []
    ta, tb = a.get("tables", {}), b.get("tables", {})
    for t in sorted(set(ta) - set(tb)):
        out.append(f"テーブル {t}: {la}にだけある")
    for t in sorted(set(tb) - set(ta)):
        out.append(f"テーブル {t}: {lb}にだけある")
    for t in sorted(set(ta) & set(tb)):
        ca = {c["name"]: c for c in ta[t]["columns"]}
        cb = {c["name"]: c for c in tb[t]["columns"]}
        for c in [x for x in ca if x not in cb]:
            out.append(f"列 {t}.{c}: {la}にだけある")
        for c in [x for x in cb if x not in ca]:
            out.append(f"列 {t}.{c}: {lb}にだけある")
        for c in [x for x in ca if x in cb]:
            for key in ("type", "notnull", "default", "pk", "hidden"):
                if ca[c].get(key) != cb[c].get(key):
                    out.append(f"列 {t}.{c}: {key} が違う（{la} {ca[c].get(key)!r}、{lb} {cb[c].get(key)!r}）")
        ia = {json.dumps({k: v for k, v in i.items() if k != "name"}, sort_keys=True) for i in ta[t].get("indexes", [])}
        ib = {json.dumps({k: v for k, v in i.items() if k != "name"}, sort_keys=True) for i in tb[t].get("indexes", [])}
        if ia != ib:
            out.append(f"テーブル {t}: インデックスが違う（{la}にだけ {len(ia - ib)} 個、{lb}にだけ {len(ib - ia)} 個）")
        fa = {json.dumps(f, sort_keys=True) for f in ta[t].get("foreign_keys", [])}
        fb = {json.dumps(f, sort_keys=True) for f in tb[t].get("foreign_keys", [])}
        if fa != fb:
            out.append(f"テーブル {t}: 外部キーが違う（{la}にだけ {len(fa - fb)} 個、{lb}にだけ {len(fb - fa)} 個）")
    for kind in ("triggers", "views"):
        word = "トリガー" if kind == "triggers" else "ビュー"
        xa, xb = a.get(kind, {}), b.get(kind, {})
        for n in sorted(set(xa) - set(xb)):
            out.append(f"{word} {n}: {la}にだけある")
        for n in sorted(set(xb) - set(xa)):
            out.append(f"{word} {n}: {lb}にだけある")
        for n in sorted(set(xa) & set(xb)):
            if xa[n] != xb[n]:
                out.append(f"{word} {n}: 定義が違う")
    return out


def run_snapshot(argv):
    ap = argparse.ArgumentParser(prog="schema-snapshot.sh")
    add_db_args(ap)
    ap.add_argument("--out", help="スキーマの写し（JSON）の置き場")
    ap.add_argument("--env", default="", help="環境の名前")
    ap.add_argument("--compare", help="比べる別の写し（JSON）")
    ap.add_argument("--from-migrations", nargs="+", help="マイグレーションの SQL（sqlite で流せる素の SQL。並べた順に流す）")
    ap.add_argument("--expect-hash", default="", help="辞書の鮮度の欄のハッシュ値。違えば FAIL")
    args = ap.parse_args(argv)
    rep = Report(NAMES["snapshot"])
    try:
        env_for_db(args.env)
        eng = make_engine(args)
        rep.target = eng.label
        shape = read_shape(eng, args.pg_schema)
    except ToolError as e:
        rep.fail("", e.rule, e.detail)
        return rep.show()
    h = shape_hash(shape)
    rep.say(f"HASH {h}")
    rep.say(f"MEASURE テーブル {len(shape['tables'])}、列 {sum(len(t['columns']) for t in shape['tables'].values())}、"
            f"トリガー {len(shape['triggers'])}、ビュー {len(shape['views'])}")
    if args.out:
        doc = {"tool": NAMES["snapshot"], "engine": eng.kind, "source": eng.label, "env": args.env, "at": now_iso(),
               "hash": h, "shape": shape}
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        rep.say(f"OUT {args.out}")
    diffs = []
    try:
        if args.compare:
            other = json.loads(pathlib.Path(args.compare).read_text(encoding="utf-8"))
            diffs += diff_shapes(shape, other.get("shape", other), "実物", "比べる写し")
        if args.from_migrations:
            diffs += diff_shapes(shape, shape_from_migrations(args.from_migrations), "実物", "マイグレーション")
    except ToolError as e:
        rep.fail("", e.rule, e.detail)
    except (OSError, ValueError) as e:
        rep.fail("", "比べる形", f"読めない（{e}）")
    for d in diffs:
        rep.say(f"DIFF {d}")
    exp = args.expect_hash.strip().lower()
    if exp and not (len(exp) >= 12 and h.startswith(exp)):
        rep.fail("", "ハッシュ値", f"今の DB の形（{h[:16]}）が、辞書の鮮度の欄（{exp[:16]}）と違う。辞書の節を読み直す")
    return rep.show(f"テーブル {len(shape['tables'])}、ずれ {len(diffs)}、ハッシュ値 {h[:16]}")


# ---------------------------------------------------------------- 集計（data-profile）
TIME_NAME = re.compile(r"(_at|_on|_date|_time|_ts|^date|^time|timestamp|^created$|^updated$)$", re.I)
LAST_WRITE = re.compile(r"^(created|updated|modified|inserted|changed)(_?(at|on|date|time|ts))?$", re.I)
MONEY_NAME = re.compile(r"(amount|price|total|fee|cost|subtotal|payment|charge)", re.I)
PAIR_PREFIX = re.compile(r"^(is_|has_|was_|flg_|flag_)")
PAIR_SUFFIX = re.compile(r"(_at|_on|_date|_time|_ts|_flag|_flg|_yn)$")


def type_class(decl, kind):
    t = (decl or "").upper()
    if any(k in t for k in ("INT", "REAL", "FLOA", "DOUB", "NUM", "DEC", "SERIAL", "MONEY")):
        return "number"
    if "DATE" in t or "TIME" in t:
        return "time"
    if "BOOL" in t:
        return "bool"
    if any(k in t for k in ("BLOB", "BYTEA", "BINARY")):
        return "blob"
    if "JSON" in t:
        return "json"
    if not t and kind == "sqlite":
        return "any"
    return "text"


def textish(cls, decl, kind):
    if kind == "sqlite":
        return cls in ("text", "any", "time")
    t = (decl or "").upper()
    return "CHAR" in t or "TEXT" in t


def fmt_num(v):
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def md_cell(v):
    return str(v).replace("|", "\\|").replace("\n", " ")


def value_token(v):
    if v is None:
        return "NULL"
    s = str(v)
    if s == "":
        return "''"
    s = s.replace("|", "\\|")
    return f"`` {s} ``" if "`" in s else f"`{s}`"


def stem_of(name):
    return PAIR_SUFFIX.sub("", PAIR_PREFIX.sub("", name.lower()))


def plural_forms(word):
    w = word.lower()
    out = [w]
    if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou":
        out.append(w[:-1] + "ies")
    elif w.endswith(("s", "x", "z", "ch", "sh")):
        out.append(w + "es")
    else:
        out.append(w + "s")
    return out


def run_profile(argv):
    ap = argparse.ArgumentParser(prog="data-profile.sh")
    add_db_args(ap)
    ap.add_argument("--env", default="", help="環境の名前（必須）")
    ap.add_argument("--log", required=True, help="クエリの記録（JSON Lines）")
    ap.add_argument("--tables", default="", help="集計するテーブル（カンマ区切り）。無ければ全部")
    ap.add_argument("--draft", default="", help="辞書の下書き（Markdown）の置き場。無ければ標準出力")
    ap.add_argument("--sample-over", type=int, default=SAMPLE_OVER)
    ap.add_argument("--max-values", type=int, default=MAX_VALUES)
    args = ap.parse_args(argv)
    rep = Report(NAMES["profile"])
    try:
        env_required(args.env)
        env_for_db(args.env)
        eng = make_engine(args)
        rep.target = eng.label
        shape = read_shape(eng, args.pg_schema)
    except ToolError as e:
        rep.fail("", e.rule, e.detail)
        return rep.show()
    names = sorted(shape["tables"])
    if args.tables:
        want = [t.strip() for t in args.tables.split(",") if t.strip()]
        for t in want:
            if t not in shape["tables"]:
                rep.fail("", "テーブル", f"{t} は DB に無い")
        names = [t for t in names if t in want]
    draft = profile_tables(eng, shape, names, args, rep)
    if args.draft:
        pathlib.Path(args.draft).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.draft).write_text(draft, encoding="utf-8")
        rep.say(f"OUT {args.draft}")
    else:
        rep.say(draft.rstrip("\n"))
    return rep.show(f"テーブル {len(names)}、クエリ {rep.queries}、打ち切り {rep.skipped}")


def profile_tables(eng, shape, names, args, rep):
    kind = eng.kind
    rep.queries, rep.skipped = 0, 0
    dict_rows, cands, ranges = [], [], []

    def q(sql, purpose, meta, max_rows=MAX_ROWS):
        cols, rows, trunc = eng.run(sql, max_rows=max_rows)
        if pii_hits(rows) or long_cells(rows):
            return cols, rows, None  # 個人が分かる値の形か、長い値がある結果は残さない
        rec = new_record(kind, eng.open_mark, args.env, NAMES["profile"], purpose, sql, cols, rows, trunc, meta)
        append_records(args.log, [rec])
        rep.queries += 1
        return cols, rows, rec["id"]

    tables = shape["tables"]
    for t in names:
        # 仮想表の隠れ列（hidden 1）は数えない。生成列（hidden 2 と 3）は、ふつうの列と同じに数える
        cols = [c for c in tables[t]["columns"] if c.get("hidden") != 1]
        opaque = bool(tables[t].get("virtual") or tables[t].get("shadow_of"))
        try:
            _, rows, cid = q(f"SELECT COUNT(*) AS {qi('rows', kind)} FROM {qi(t, kind)}", f"{t} の行の数",
                             {"kind": "count", "table": t})
        except ToolError as e:
            rep.skipped += 1
            ranges.append((t, "-", "0", f"{e.rule}（{e.detail}）"))
            continue
        n = rows[0][0] or 0
        sampled, every, pct = None, max(2, math.ceil(n / SAMPLE_ROWS)), max(0.01, round(100.0 * SAMPLE_ROWS / max(n, 1), 2))
        if n > args.sample_over:
            if kind == "sqlite" and not tables[t].get("without_rowid"):
                sampled = f"rowid が {every} の倍数の行"
            elif kind == "postgres":
                sampled = f"TABLESAMPLE SYSTEM {pct}%"
            else:
                sampled = f"先頭の {SAMPLE_ROWS} 行（偏りうる）"

        def source(alias=None, t=t, sampled=sampled, every=every, pct=pct):
            name = qi(alias or "s", kind)
            if sampled is None:
                return qi(t, kind) + (f" AS {name}" if alias else "")
            if kind == "sqlite" and sampled.startswith("rowid"):
                return f"(SELECT * FROM {qi(t, kind)} WHERE rowid % {every} = 0) AS {name}"
            if kind == "postgres":
                return f"{qi(t, kind)} AS {name} TABLESAMPLE SYSTEM ({pct}) REPEATABLE (7)"
            return f"(SELECT * FROM {qi(t, kind)} LIMIT {SAMPLE_ROWS}) AS {name}"

        src = source()
        meta_base = {"table": t, "sampled": sampled}
        stats, stat_ids, failed = {}, [], False
        for k in range(0, len(cols), CHUNK):
            part = cols[k:k + CHUNK]
            exprs = []
            for c in part:
                cls = type_class(c["type"], kind)
                qc = qi(c["name"], kind)

                def al(suffix, name=c["name"]):
                    return qi(f"{name}:{suffix}", kind)

                exprs.append(f"COUNT({qc}) AS {al('nonnull')}")
                if cls not in ("json", "blob"):
                    exprs.append(f"COUNT(DISTINCT {qc}) AS {al('distinct')}")
                if textish(cls, c["type"], kind):
                    exprs.append(f"SUM(CASE WHEN {qc} = '' THEN 1 ELSE 0 END) AS {al('empty')}")
                if cls in ("number", "any"):
                    exprs.append(f"SUM(CASE WHEN {qc} = 0 THEN 1 ELSE 0 END) AS {al('zero')}")
                if kind == "sqlite":
                    for ty in ("integer", "real", "text", "blob"):
                        exprs.append(f"SUM(CASE WHEN typeof({qc}) = '{ty}' THEN 1 ELSE 0 END) AS {al(ty)}")
            sql = f"SELECT COUNT(*) AS {qi('rows', kind)}, " + ", ".join(exprs) + f" FROM {src}"
            try:
                scols, srows, sid = q(sql, f"{t} の列の集計", dict(meta_base, kind="stats", columns=[c["name"] for c in part]))
            except ToolError as e:
                rep.skipped += 1
                ranges.append((t, str(len(cols)), str(k), f"{e.rule}（{e.detail}）"))
                failed = True
                break
            stat_ids.append(sid)
            for name, v in zip(scols, srows[0]):
                stats[name] = v or 0
            for c in part:
                stats[c["name"] + ":sid"] = sid
            stats["rows"] = srows[0][0] or 0
        if failed:
            continue
        base = stats.get("rows", n)
        info = {}
        for c in cols:
            name = c["name"]
            cls = type_class(c["type"], kind)
            g = {s: stats.get(f"{name}:{s}", 0) or 0 for s in
                 ("nonnull", "distinct", "empty", "zero", "integer", "real", "text", "blob")}
            g["cls"], g["pii"], g["nulls"], g["sid"] = cls, pii_like(t, name) or opaque, base - g["nonnull"], stats.get(name + ":sid")
            g["opaque"] = opaque
            if kind == "sqlite" and cls == "any" and g["nonnull"] and g["integer"] + g["real"] == g["nonnull"]:
                g["cls"] = "number"
            info[name] = g
        # 値の一覧
        for c in cols:
            name, g = c["name"], info[c["name"]]
            g["values"], g["values_id"], g["why"] = None, None, ""
            if g["opaque"]:
                g["why"] = "件数だけ（仮想表か、その影の表。中身は元の表の値の写し）"
            elif g["pii"]:
                g["why"] = "件数だけ（個人情報らしい名前）"
            elif g["cls"] in ("blob", "json"):
                g["why"] = "件数だけ（バイナリか JSON）"
            elif g["nonnull"] == 0:
                g["why"] = "すべて空"
            elif g["distinct"] > args.max_values:
                g["why"] = f"件数だけ（{args.max_values + 1} 種類以上）"
            else:
                qc = qi(name, kind)
                sql = (f"SELECT {qc} AS {qi('value', kind)}, COUNT(*) AS {qi('n', kind)} FROM {src} "
                       f"GROUP BY {qc} ORDER BY COUNT(*) DESC, {qc}")
                try:
                    _, vrows, vid = q(sql, f"{t}.{name} の値の一覧", dict(meta_base, kind="values", column=name),
                                      max_rows=args.max_values + 5)
                except ToolError as e:
                    g["why"] = f"件数だけ（{e.rule}）"
                    continue
                if vid is None:
                    g["why"] = "件数だけ（値の形が個人情報らしいか、長い値がある）"
                else:
                    g["values"], g["values_id"] = vrows, vid
        # 最小と最大
        mm_cols = [c["name"] for c in cols if not info[c["name"]]["pii"] and info[c["name"]]["nonnull"]
                   and (info[c["name"]]["cls"] in ("number", "time", "bool") or TIME_NAME.search(c["name"]))]
        mm, mm_id = {}, None
        if mm_cols:
            exprs = []
            for name in mm_cols:
                qc = qi(name, kind)
                exprs.append(f"MIN({qc}) AS {qi(name + ':min', kind)}, MAX({qc}) AS {qi(name + ':max', kind)}")
            try:
                mcols, mrows, mm_id = q("SELECT " + ", ".join(exprs) + f" FROM {src}", f"{t} の最小と最大",
                                        dict(meta_base, kind="minmax", columns=mm_cols))
                mm = dict(zip(mcols, mrows[0])) if mm_id else {}
            except ToolError:
                mm, mm_id = {}, None
        last = [(str(mm.get(f"{x}:max")), x) for x in mm_cols if LAST_WRITE.match(x) and mm.get(f"{x}:max") is not None]
        if last:
            v, x = max(last)
            rep.say(f"MEASURE {t} の最後の書き込み {v}（{x} の最大、{mm_id}）")
        # 罠の候補
        for c in cols:
            name, g = c["name"], info[c["name"]]
            where, sid = f"{t}.{name}", g["sid"]
            if base and g["nonnull"] == 0:
                cands.append(f"型 2（書かれない列）: {where} は {fmt_num(base)} 行すべて空（{sid}）")
            if kind == "sqlite" and sum(1 for k2 in ("integer", "real", "text") if g[k2]) > 1:
                cands.append(f"型 10（型のゆれ）: {where} に integer {g['integer']}、real {g['real']}、text {g['text']} が混ざる（{sid}）")
            if g["empty"] and g["nulls"]:
                cands.append(f"型 10（型のゆれ）: {where} に空文字 {fmt_num(g['empty'])} 行と NULL {fmt_num(g['nulls'])} 行が混ざる（{sid}）")
            if TIME_NAME.search(name) and ((kind == "sqlite" and g["text"]) or
                                           (kind != "sqlite" and re.search(r"WITHOUT TIME ZONE|^DATETIME$", c["type"]))):
                cands.append(f"型 8（時刻の境目）: {where} は時差を持たない形で保存（{sid}）。月の境目の前後 9 時間を数える")
            if g["zero"] and MONEY_NAME.search(name):
                cands.append(f"型 9（試しのデータ）: {where} が 0 の行が {fmt_num(g['zero'])} 行（{sid}）。試しの注文かを 1 問で聞く")
        groups = {}
        for c in cols:
            groups.setdefault(stem_of(c["name"]), []).append(c["name"])
        for stem, members in sorted(groups.items()):
            if len(members) < 2:
                continue
            a, b = members[0], members[1]

            def ex(x):
                if info[x]["values"] is not None:
                    return qi(x, kind)
                return f"CASE WHEN {qi(x, kind)} IS NULL THEN 'NULL' ELSE '値あり' END"

            sql = (f"SELECT {ex(a)} AS {qi(a, kind)}, {ex(b)} AS {qi(b, kind)}, COUNT(*) AS {qi('n', kind)} "
                   f"FROM {src} GROUP BY 1, 2 ORDER BY 3 DESC")
            try:
                _, _, pid = q(sql, f"{t}.{a} と {t}.{b} の組み合わせ", dict(meta_base, kind="pair", columns=[a, b]), max_rows=50)
                if pid:
                    cands.append(f"型 3（二重の置き場）: {t}.{a} と {t}.{b} は名前が似ている。組み合わせの件数は {pid}")
            except ToolError:
                pass
        fks = [(f["column"], f["ref_table"], f["ref_column"] or "id", "宣言") for f in tables[t].get("foreign_keys", [])]
        declared = {f[0] for f in fks}
        for c in cols:
            m = re.fullmatch(r"(\w+)_id", c["name"])
            if not m or c["name"] in declared:
                continue
            parents = [p for p in plural_forms(m.group(1)) if p in tables and p != t
                       and any(x["name"] == "id" for x in tables[p]["columns"])]
            if len(parents) == 1:
                fks.append((c["name"], parents[0], "id", "名前からの推定"))
        for col, pt, pc, how in fks:
            if pt not in tables:
                continue
            sql = (f"SELECT COUNT(*) AS {qi('orphans', kind)} FROM {source('c0')} "
                   f"WHERE {qi('c0', kind)}.{qi(col, kind)} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {qi(pt, kind)} AS {qi('p0', kind)} "
                   f"WHERE {qi('p0', kind)}.{qi(pc, kind)} = {qi('c0', kind)}.{qi(col, kind)})")
            try:
                _, orow, oid = q(sql, f"{t}.{col} の孤児の行（{pt}.{pc}、{how}）",
                                 dict(meta_base, kind="orphans", column=col, parent=f"{pt}.{pc}"))
            except ToolError:
                continue
            if oid and orow and orow[0][0]:
                cands.append(f"型 7（孤児の行）: {t}.{col} の {fmt_num(orow[0][0])} 行に {pt}.{pc} が無い（{oid}、外部キーは{how}）")
        # 辞書の下書きの行
        mark = "実測（標本）" if sampled else "実測"
        for c in cols:
            name, g = c["name"], info[c["name"]]
            share = f"{100.0 * g['nulls'] / base:.1f}%" if base else "0%"
            head = f"全 {fmt_num(n)} 行（{cid}）から標本 {fmt_num(base)} 行。そのうち" if sampled else f"{fmt_num(base)} 行のうち"
            real = f"{head}空 {fmt_num(g['nulls'])} 行（{share}）、値 {fmt_num(g['distinct'])} 種類（{g['sid']}）"
            if g["empty"]:
                real += f"、空文字 {fmt_num(g['empty'])} 行"
            if name in mm_cols and mm_id:
                real += f"、最小 {md_cell(mm.get(name + ':min'))}、最大 {md_cell(mm.get(name + ':max'))}（{mm_id}）"
            if g["values"] is not None:
                vals = "、".join(f"{value_token(r[0])} {fmt_num(r[1])} 件" for r in g["values"]) + f"（{g['values_id']}）"
            else:
                vals = g["why"]
            dict_rows.append(f"| {t}.{name} | <コードの上の意味（ファイル:行）> | {real} | {vals} | <T-番号か、なし> | {mark} |")
        ranges.append((t, str(len(cols)), str(len(cols)), "標本で数えた（" + sampled + "）" if sampled else "なし"))
    lines = ["## データの辞書（下書き）", "",
             "data-profile.sh が数えた値です。コードの上の意味と食い違いの列を埋め、辞書のテンプレートに写してください。", "",
             "| テーブルと列 | コードの上の意味 | 実データ | 値の一覧 | 食い違い | 裏づけ |", "|---|---|---|---|---|---|"]
    lines += dict_rows
    lines += ["", "## 罠の候補", "", "機械で拾った候補です。どれも、コードと照らしてから食い違いの一覧に書きます。", ""]
    lines += [f"- {c}" for c in cands] or ["- なし"]
    lines += ["", "## 読んだ範囲（下書き）", "", "テーブルごとの列の数と、集計した列の数です。", "",
              "| 対象 | 全体の数 | 読んだ数 | 読んでいない理由 |", "|---|---|---|---|"]
    lines += [f"| {t} の列 | {a} | {b} | {md_cell(r)} |" for t, a, b, r in ranges]
    for c in cands:
        rep.say(f"CANDIDATE {c}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- クエリ 1 本（data-query）
def run_query(argv):
    ap = argparse.ArgumentParser(prog="data-query.sh")
    add_db_args(ap)
    ap.add_argument("--env", default="", help="環境の名前（必須）")
    ap.add_argument("--log", required=True, help="クエリの記録（JSON Lines）")
    ap.add_argument("--sql", default="", help="回す文")
    ap.add_argument("--file", default="", help="回す文のファイル")
    ap.add_argument("--purpose", default="", help="何の数か")
    ap.add_argument("--max-rows", type=int, default=MAX_ROWS)
    ap.add_argument("--import", dest="import_csv", default="",
                    help="依頼者が本番で回した結果（CSV、1 行目は列の名前）。DB にはつながず、文と結果を記録に書く")
    args = ap.parse_args(argv)
    rep = Report(NAMES["query"])
    try:
        env_required(args.env)
        sql = args.sql or (pathlib.Path(args.file).read_text(encoding="utf-8") if args.file else "")
        probs, _, _ = check_select(sql)
        if probs:
            for rule, msg in probs:
                rep.fail("", rule, msg)
            return rep.show("回していない")
        if args.import_csv:
            with open(args.import_csv, encoding="utf-8", newline="") as f:
                table = list(csv.reader(f))
            cols = table[0] if table else []
            rows = [[number_or_text(v) for v in r] for r in table[1:]]
            truncated = len(rows) > args.max_rows
            rows = rows[:args.max_rows]
            kind, mark, label = "import", OPEN_MARKS["import"], pathlib.Path(args.import_csv).name
        else:
            env_for_db(args.env)
            eng = make_engine(args)
            cols, rows, truncated = eng.run(sql, max_rows=args.max_rows)
            kind, mark, label = eng.kind, eng.open_mark, eng.label
        rep.target = label
    except ToolError as e:
        rep.fail("", e.rule, e.detail)
        return rep.show("記録に書いていない")
    except (OSError, ValueError) as e:
        rep.fail("", "読めない", str(e))
        return rep.show("記録に書いていない")
    # 個人情報らしい列は、COUNT などの集計の中でだけ通す。別名を付けても、元の列と表で判定する
    for why in pii_problems(sql, cols, rows):
        rep.fail("", "個人が分かる値", f"{why}。値は出さず、記録にも書かない。件数で数える文に直す")
    if rep.items:
        return rep.show("記録に書いていない")
    rec = new_record(kind, mark, args.env, NAMES["query"], args.purpose, sql.strip(), cols, rows, truncated)
    append_records(args.log, [rec])
    rep.say(f"QUERY {rec['id']} 環境={args.env} 行={len(rows)}{'（打ち切り）' if truncated else ''} ハッシュ値={rec['hash'][:16]}")
    for line in show_result(cols, rows):
        rep.say(line)
    return rep.show(f"{rec['id']}、行 {len(rows)}")


# ---------------------------------------------------------------- 書き込む処理（writers-map）
CODE_EXT = {".php", ".py", ".rb", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".java", ".kt", ".kts", ".scala",
            ".cs", ".sql", ".ex", ".exs", ".rs", ".erb"}
SKIP_DIRS = {"node_modules", "vendor", ".git", "tmp", "dist", "build", ".next", ".nuxt", "coverage", "__pycache__", ".venv",
             "venv", "target", "obj", "storage", "log", "logs", ".claude", ".cursor"}
# 表の名前。引用（"…"、`…`、[…]）の中は空白と英字以外の字も許し、引用の無い名前も日本語の字を許す。前の schema. は外す
T = (r"(?:(?:\"[^\"\n]+\"|`[^`\n]+`|\[[^\]\n]+\]|[^\W\d]\w*)\s*\.\s*)?"
     r"(?:\"(?P<tq>[^\"\n]+)\"|`(?P<tb>[^`\n]+)`|\[(?P<ts>[^\]\n]+)\]|(?P<table>[^\W\d]\w*))")
SQL_WRITES = [
    (re.compile(r"\bINSERT\s+(?:OR\s+\w+\s+|IGNORE\s+)?INTO\s+" + T, re.I), "INSERT"),
    (re.compile(r"\bREPLACE\s+INTO\s+" + T, re.I), "REPLACE"),
    (re.compile(r"\bUPDATE\s+(?:ONLY\s+)?" + T + r"(?:\s+(?:AS\s+)?\w+)?\s+SET\b", re.I), "UPDATE"),
    (re.compile(r"\bDELETE\s+FROM\s+(?:ONLY\s+)?" + T, re.I), "DELETE"),
    (re.compile(r"\bMERGE\s+INTO\s+" + T, re.I), "MERGE"),
    (re.compile(r"\bTRUNCATE\s+(?:TABLE\s+)?" + T, re.I), "TRUNCATE"),
]
BUILDER_WRITES = [  # 表の名前を文字で渡す書き方
    re.compile(r"DB::table\(\s*['\"](?P<table>\w+)['\"]\s*\)(?:(?!;).){0,400}?->\s*(?P<op>insert\w*|update\w*|upsert|delete|increment|"
               r"decrement|truncate)\s*\(", re.S),
    re.compile(r"\b(?:knex|db|trx)\(\s*['\"](?P<table>\w+)['\"]\s*\)(?:(?!;).){0,400}?\.\s*(?P<op>insert|update|del|delete|upsert|"
               r"increment|decrement|truncate)\s*\(", re.S),
    re.compile(r"queryInterface\.(?P<op>bulkInsert|bulkUpdate|bulkDelete|upsert)\(\s*['\"](?P<table>\w+)['\"]"),
]
MODEL_WRITES = [  # モデルの名前から表を引く書き方
    re.compile(r"\b(?P<model>[A-Z][A-Za-z0-9]*)\s*(?:\.|::)\s*(?P<op>create!?|insert(?:_all!?)?|upsert(?:_all)?|update(?:_all|_column|_columns)?|"
               r"delete(?:_all)?|destroy(?:_all)?|bulkCreate|bulkUpdate|findOrCreate|firstOrCreate|updateOrCreate|updateOrInsert|"
               r"increment|decrement|forceDelete|truncate)\s*[(!]"),
    re.compile(r"\b(?P<model>[A-Z][A-Za-z0-9]*)\.objects\b(?:\.\w+\([^()]*\))*\.(?P<op>create|bulk_create|bulk_update|update|delete|"
               r"get_or_create|update_or_create)\s*\("),
    re.compile(r"\b(?P<model>[A-Z][A-Za-z0-9]*)::\w+\((?:(?!;).){0,300}?->\s*(?P<op>update|delete|increment|decrement|forceDelete)\s*\(",
               re.S),
    re.compile(r"\b(?P<model>[A-Z][A-Za-z0-9]*)\.(?:where|find_by|find|all|joins|includes|unscoped|filter)\b[^\n;]{0,300}?"
               r"\.(?P<op>update_all|update|delete_all|destroy_all|destroy|delete|upsert_all|insert_all|increment|decrement)\b\s*[(!]?"),
    re.compile(r"\bquery\(\s*(?P<model>[A-Z]\w*)\s*\)[^\n;]{0,300}?\.(?P<op>update|delete)\s*\("),
    re.compile(r"\bprisma\.(?P<model>\w+)\.(?P<op>create|createMany|update|updateMany|upsert|delete|deleteMany)\s*\("),
    re.compile(r"getRepository\(\s*(?P<model>[A-Z]\w*)\s*\)\s*\.\s*(?P<op>save|insert|update|delete|remove|upsert|softDelete|"
               r"increment|decrement)\s*\("),
    re.compile(r"\b(?P<op>insert|update|delete)\(\s*(?P<model>[A-Z]\w*)\s*\)"),
]
INSTANCE_WRITE = re.compile(r"[$@]?\b(?P<var>[a-z][a-z0-9_]*)\s*(?:->|\.)\s*(?P<op>save|update|delete|destroy|increment|decrement|touch)\b\s*[(!]")
TABLE_DECL = [
    (re.compile(r"protected\s+\$table\s*=\s*['\"](\w+)['\"]"), -1),
    (re.compile(r"self\.table_name\s*=\s*['\"](\w+)['\"]"), -1),
    (re.compile(r"\bdb_table\s*=\s*['\"](\w+)['\"]"), -1),
    (re.compile(r"__tablename__\s*=\s*['\"](\w+)['\"]"), -1),
    (re.compile(r"tableName\s*:\s*['\"](\w+)['\"]"), -1),
    (re.compile(r"@Entity\(\s*(?:\{\s*name\s*:\s*)?['\"](\w+)['\"]"), 1),
    (re.compile(r"@Table\(\s*name\s*=\s*\"(\w+)\""), 1),
]
CLASS_RX = re.compile(r"\bclass\s+([A-Z]\w*)")
SCHEDULE_RX = re.compile(r"(->(?:daily|hourly|everyMinute|everyFiveMinutes|everyTenMinutes|everyFifteenMinutes|everyThirtyMinutes|"
                         r"weekly|monthly|cron)\s*\(|@Scheduled\b|crontab|beat_schedule|Sidekiq::Cron|node-cron|"
                         r"schedule\.(?:every|scheduleJob)\b|\bCronJob\b|@periodic_task|add_job\()", re.I)
WEBHOOK_RX = re.compile(r"(webhook|notify_url|callback_url|/hooks?/|/callbacks?/)", re.I)
TRIGGER_EVENT = re.compile(r"\b(BEFORE|AFTER|INSTEAD\s+OF)\s+(INSERT|UPDATE|DELETE)\b", re.I)


def table_of(m):
    """SQL_WRITES の当たりから、表の名前（引用の中身か、引用の無い名前）を返す。"""
    return next(g for g in (m.group("tq"), m.group("tb"), m.group("ts"), m.group("table")) if g)


def snake(name):
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name)
    return s.lower()


def model_tables(model, known, explicit):
    if model in explicit:
        return explicit[model], "宣言"
    sn = snake(model)
    parts = sn.split("_")
    cands = plural_forms(sn) + ["_".join(parts[:-1] + [p]) for p in plural_forms(parts[-1])] + [model]
    for c in cands:
        if c in known:
            return c, "名前"
    return (plural_forms(sn)[-1], "推定") if not known else (None, "")


def code_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            p = pathlib.Path(dirpath) / fn
            if p.suffix.lower() in CODE_EXT or fn in ("crontab",) or fn.endswith(".cron"):
                if not fn.endswith((".min.js", ".map")):
                    try:
                        if p.stat().st_size <= 512 * 1024:
                            yield p
                    except OSError:
                        continue


def scan_writers(root, known):
    """返り値は (書き込む処理の一覧, 定時の処理と外からの通知の候補)。書き込む処理は (表, 場所, 種類, 抜粋, 表の決め方)。"""
    root = pathlib.Path(root)
    texts = {}
    for p in code_files(root):
        try:
            texts[p] = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    explicit = {}
    for p, text in texts.items():
        classes = [(m.start(), m.group(1)) for m in CLASS_RX.finditer(text)]
        for rx, direction in TABLE_DECL:
            for m in rx.finditer(text):
                if direction < 0:
                    before = [c for c in classes if c[0] < m.start()]
                    cls = before[-1][1] if before else None
                else:
                    after = [c for c in classes if c[0] > m.start()]
                    cls = after[0][1] if after else None
                if cls:
                    explicit[cls] = m.group(1)
    writes, others = [], []
    for p, text in texts.items():
        rel = str(p.relative_to(root))
        starts = [0] + [m.end() for m in re.finditer("\n", text)]

        def line_of(pos):
            lo, hi = 0, len(starts) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if starts[mid] <= pos:
                    lo = mid
                else:
                    hi = mid - 1
            return lo + 1

        def excerpt(m):
            return short_sql(text[m.start():m.end()], 60)

        seen = set()
        for rx, op in SQL_WRITES:
            for m in rx.finditer(text):
                tb = table_of(m)
                if tb.upper() in ("SET", "INTO", "FROM", "TABLE", "ONLY", "SELECT"):
                    continue
                key = (tb.lower(), line_of(m.start()), op)
                if key not in seen:
                    seen.add(key)
                    writes.append((tb, f"{rel}:{key[1]}", op, excerpt(m), "SQL"))
        for rx in BUILDER_WRITES:
            for m in rx.finditer(text):
                ln = line_of(m.start())
                key = (m.group("table").lower(), ln, m.group("op"))
                if key not in seen:
                    seen.add(key)
                    writes.append((m.group("table"), f"{rel}:{ln}", m.group("op"), excerpt(m), "表の名前"))
        for rx in MODEL_WRITES:
            for m in rx.finditer(text):
                model = m.group("model")
                if model in ("DB", "Schema", "Route", "Log", "Cache", "Session", "Auth", "JSON", "Object", "Array", "Math",
                             "Date", "Promise", "Response", "Request", "File", "Storage", "Config"):
                    continue
                if model[0].islower():
                    model = model[0].upper() + model[1:]
                tb, how = model_tables(model, known, explicit)
                ln = line_of(m.start())
                if tb is None:
                    writes.append(("（表の分からない書き込み）", f"{rel}:{ln}", m.group("op"), excerpt(m), f"モデル {model}"))
                    continue
                key = (tb.lower(), ln, m.group("op"))
                if key not in seen:
                    seen.add(key)
                    writes.append((tb, f"{rel}:{ln}", m.group("op"), excerpt(m), f"モデル {model}（{how}）"))
        if known:
            for m in INSTANCE_WRITE.finditer(text):
                var = m.group("var")
                tb = next((c for c in plural_forms(var) if c in known and c != var), None)
                if not tb:
                    continue
                ln = line_of(m.start())
                key = (tb.lower(), ln, m.group("op"))
                if key not in seen:
                    seen.add(key)
                    writes.append((tb, f"{rel}:{ln}", m.group("op"), excerpt(m), f"変数 {var}（名前からの推定）"))
        for rx, word in ((SCHEDULE_RX, "定時の処理"), (WEBHOOK_RX, "外からの通知")):
            for m in rx.finditer(text):
                others.append((word, f"{rel}:{line_of(m.start())}", short_sql(m.group(0), 40)))
    return writes, others


def trigger_writes(shape):
    out = []
    for name, tr in sorted(shape.get("triggers", {}).items()):
        sql = tr.get("sql", "")
        ev = TRIGGER_EVENT.search(sql)
        event = f"{ev.group(2).upper()}" if ev else "書き込み"
        body = re.split(r"\bBEGIN\b", sql, maxsplit=1, flags=re.I)
        body = body[1] if len(body) > 1 else sql
        found = False
        for rx, op in SQL_WRITES:
            for m in rx.finditer(body):
                found = True
                out.append((table_of(m), f"トリガー {name}（{tr.get('table')} への {event} で動く）", op,
                            short_sql(body[m.start():m.end()], 60), "トリガー"))
        if not found:
            out.append((tr.get("table") or "（不明）", f"トリガー {name}（{tr.get('table')} への {event} で動く。書く先は読めていない）",
                        "不明", short_sql(sql, 60), "トリガー"))
    return out


def run_writers(argv):
    ap = argparse.ArgumentParser(prog="writers-map.sh")
    add_db_args(ap)
    ap.add_argument("--code", required=True, help="コードの置き場（プロジェクトの直下か、読む範囲のディレクトリ）")
    ap.add_argument("--schema", default="", help="スキーマの写し（schema-snapshot.sh の --out）")
    ap.add_argument("--tables", default="", help="見るテーブル（カンマ区切り）")
    args = ap.parse_args(argv)
    rep = Report(NAMES["writers"], args.code)
    shape = {"tables": {}, "triggers": {}}
    try:
        if not pathlib.Path(args.code).is_dir():
            raise ToolError("使い方", f"{args.code} はディレクトリではない")
        if args.schema:
            doc = json.loads(pathlib.Path(args.schema).read_text(encoding="utf-8"))
            shape = doc.get("shape", doc)
        elif args.db or args.engine != "sqlite":
            shape = read_shape(make_engine(args), args.pg_schema)
    except ToolError as e:
        rep.fail("", e.rule, e.detail)
        return rep.show()
    except (OSError, ValueError) as e:
        rep.fail("", "読めない", str(e))
        return rep.show()
    known = {t.lower(): t for t in shape.get("tables", {})}
    writes, others = scan_writers(args.code, set(known))
    writes += trigger_writes(shape)
    want = {t.strip().lower() for t in args.tables.split(",") if t.strip()}
    by_table = {}
    for tb, where, op, ex, how in writes:
        key = known.get(tb.lower(), tb)
        if want and key.lower() not in want:
            continue
        by_table.setdefault(key, []).append((where, op, ex, how))
    tables = sorted(set(known.values()) | set(by_table)) if not want else sorted(set(by_table) | {known.get(w, w) for w in want})
    lines = ["## 書き込む処理の表（下書き）", "",
             "writers-map.sh が拾った候補です。生きている証拠（直近の書き込み、経路の登録）を確かめて、状態を書き換えてください。", "",
             "| テーブル | 書き込む処理 | 書く列と条件 | 生きている証拠 | 状態 |", "|---|---|---|---|---|"]
    unknown = 0
    for t in tables:
        rows = by_table.get(t, [])
        if not rows:
            unknown += 1
            lines.append(f"| {t} | 不明 | | | 書き込む処理が見つからない。定時の処理、手作業、ほかのリポジトリを探す |")
            continue
        for where, op, ex, how in rows:
            lines.append(f"| {t} | {md_cell(where)}（{op}、{md_cell(how)}） | {md_cell(ex)} | 未確認 | 候補 |")
    lines += ["", "## 定時の処理と外からの通知の候補", "", "書き込む処理を探す手がかりです。中身を読んで、書く表を確かめます。", ""]
    lines += [f"- {w}: {where}（{md_cell(ex)}）" for w, where, ex in others[:50]] or ["- なし"]
    if len(others) > 50:
        lines.append(f"- ほか {len(others) - 50} か所")
    rep.say("\n".join(lines))
    return rep.show(f"テーブル {len(tables)}、書き込む処理 {sum(len(v) for v in by_table.values())}、不明 {unknown}")


# ---------------------------------------------------------------- 検査（data-dictionary-check）
CELL_SPLIT = re.compile(r"(?<!\\)\|")
HEADING_RX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
QREF_RX = re.compile(r"\bQ-\d+\b")
TREF_RX = re.compile(r"\bT-\d+\b")
HEAR_RX = re.compile(r"聞き取り[（(]?\s*(\d{4}-\d{2}-\d{2})")
# 根拠の「ファイル:行」。拡張子の無い決まった名前（Dockerfile ほか）と、点で始まる名前（.python-version）も読む。
# 空白や引用の字を含むパスは「`パス`:行」と書く。catchup の catchup_tools.py と同じ形にそろえる
BARE_FILES = (r"(?:Dockerfile|Containerfile|Makefile|GNUmakefile|makefile|Procfile|Gemfile|Rakefile|Jenkinsfile|Vagrantfile|"
              r"Brewfile|Pipfile|Caddyfile|Justfile|Taskfile|crontab|LICENSE|README)")
PATH_PART = r"(?<![\w.\-/])(?:[\w.\-]+/)*(?:[\w\-][\w.\-]*\.[A-Za-z]\w*|\.[A-Za-z][\w.\-]*|" + BARE_FILES + r"(?![\w.\-]))"
LINE_PART = r"(?::(?P<a>\d+)(?:[-–〜](?P<b>\d+))?|\s*の\s*(?P<c>\d+)(?:\s*[〜-]\s*(?P<d>\d+))?\s*行)"
EVIDENCE_RX = re.compile(r"(?P<path>" + PATH_PART + r")" + LINE_PART)
TICK_EVIDENCE_RX = re.compile(r"`(?P<path>[^`\n]+)`" + LINE_PART)
PLACEHOLDER_RX = re.compile(r"<[^<>|`\n]{1,80}>")
VALUE_ITEM_RX = re.compile(r"(``\s(?P<b>.*?)\s``|`(?P<a>[^`]*)`|(?P<null>NULL)|(?P<empty>''))\s*(?P<n>\d{1,3}(?:,\d{3})+|\d+)?\s*件?")
BACKING = ("実測", "実測（標本）", "コードからの推定", "推定", "聞き取り")
FRESH_KEYS = ("commit", "スキーマのハッシュ値", "集計の時刻", "環境の名前")
# git の無いプロジェクトの辞書の commit の欄。「git なし」と、作った時刻と、根拠のファイルのハッシュ値を書く。
# 値は --evidence-hash が出す。検査は根拠のファイルからハッシュ値を作り直して比べ、変わっていれば [鮮度] で落とす
NOGIT = "git なし"
NOGIT_RX = re.compile(r"git\s*なし")
NOGIT_HASH_RX = re.compile(r"根拠のハッシュ値\s*[:：]?\s*`?([0-9a-f]{12,64})(?![0-9a-f])")
RECORD_KEYS = ("id", "env", "at", "engine", "open", "sql", "columns", "rows", "hash")
# 数として数えない所。どの節でも外すのは、URL、注釈、ファイルと行、番号、日付と時刻、節や問いの番号、数え方の語（か所ほか）
EXCLUDE_NUM = [
    r"https?://\S+", r"<!--.*?-->",
    PATH_PART + r"(?::\d+(?:[-–〜]\d+)?|\s*の\s*\d+(?:\s*[〜-]\s*\d+)?\s*行)",
    r"[A-Za-z][A-Za-z0-9_]*-\d+(?:-\d+)*", r"#\d+",
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?",
    r"\d{4}\s*年(?:\s*\d{1,2}\s*月)?(?:\s*\d{1,2}\s*日)?", r"\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?",
    r"\d{1,2}:\d{2}(?::\d{2})?", r"\d{1,2}\s*時(?!間)(?:\s*\d{1,2}\s*分)?", r"\b\d{1,2}/\d{1,2}\b",
    r"\d+\s*(?:か所|箇所|ファイル|画面|経路|章|節|段階|問|版|番目|番|号|行目)",
    r"(?:第|段階|順|手順|表|図)\s*\d+", r"\b[A-Za-z]+\d+[A-Za-z0-9]*\b", r"\d+(?:\.\d+)+\s*節",
]
# 結論の節の外だけで外す所。バッククォートの中と、単独の「N 日」と、時間の長さ。結論では、これらも照らす
EXCLUDE_LOOSE = [r"`[^`]*`", r"\d{1,2}\s*日", r"\d+\s*(?:時間|分|秒|週|か月|ヶ月)"]
EXCLUDE_NUM_RX = re.compile("|".join(f"(?:{p})" for p in EXCLUDE_NUM))
EXCLUDE_LOOSE_RX = re.compile("|".join(f"(?:{p})" for p in EXCLUDE_LOOSE + EXCLUDE_NUM))
NUM_RX = re.compile(r"(?<![A-Za-z0-9_.,])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?:\s*(万|億))?(?:\s*(%|％|割))?(?!\d)")
# 漢数字の数。結論に書くと照らせないので、算用数字で書かせる
KANJI_NUM_RX = re.compile(r"[〇一二三四五六七八九十百千万億]+\s*(?:件|円|人|個|行|本|回|倍|割|%|％|パーセント|ポイント)")


def split_cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in CELL_SPLIT.split(s)]


def md_tables(lines):
    tabs, heading, i, in_code = [], "", 0, False
    while i < len(lines):
        s = lines[i]
        if s.strip().startswith("```"):
            in_code = not in_code
            i += 1
            continue
        if in_code:
            i += 1
            continue
        m = HEADING_RX.match(s)
        if m:
            heading = m.group(2)
            i += 1
            continue
        if s.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            header = split_cells(s)
            rows, j = [], i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append((j + 1, split_cells(lines[j])))
                j += 1
            tabs.append({"heading": heading, "header": header, "rows": rows, "line": i + 1})
            i = j
            continue
        i += 1
    return tabs


def col_index(header, *names):
    for name in names:
        for k, h in enumerate(header):
            if h == name:
                return k
    for name in names:
        for k, h in enumerate(header):
            if name in h:
                return k
    return None


def cell(cells, k):
    return cells[k] if k is not None and k < len(cells) else ""


def find_table(tabs, *must):
    for t in tabs:
        if all(col_index(t["header"], m) is not None for m in must):
            return t
    return None


def header_info(tabs):
    info = {}
    for t in tabs:
        if len(t["header"]) >= 2 and t["header"][0] == "項目" and t["header"][1] == "内容":
            for no, cells in t["rows"]:
                if cells and cells[0] not in info:
                    info[cells[0]] = (cell(cells, 1), no)
    return info


def path_in(value):
    for tok in re.findall(r"`([^`]+)`", value) + value.split():
        tok = tok.strip("`（）()、。")
        if re.search(r"[\w\-]\.(jsonl|json|md)$", tok):
            return tok
    return ""


def resolve(base_dir, root, value):
    if not value:
        return None
    for cand in (pathlib.Path(value), base_dir / value, root / value):
        if cand.exists():
            return cand
    return base_dir / value


def find_root(start):
    p = pathlib.Path(start).resolve()
    for d in [p] + list(p.parents):
        if (d / ".git").exists():
            return d
    return pathlib.Path.cwd()


def section_lines(lines, word):
    out, level, inside, in_code = [], 0, False, False
    for no, s in enumerate(lines, 1):
        if s.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = HEADING_RX.match(s)
        if m:
            lv = len(m.group(1))
            if inside and lv <= level:
                inside = False
            if not inside and lv >= 2 and word in m.group(2):
                inside, level = True, lv
            continue
        if inside:
            out.append((no, s))
    return out


def disp_round(x, k):
    q = 10 ** k
    return math.copysign(math.floor(abs(x) * q + 0.5) / q, x)


def _blank(m):
    return " " * len(m.group(0))


def strip_conditions(text):
    """推奨が変わる条件の閾値は、データの数ではない。文の「変わる条件」から後ろだけを外し、前の数は照らす。"""
    out = []
    for s in re.split(r"(?<=[。！？])", text):
        k = s.find("変わる条件")
        out.append(s if k < 0 else s[:k] + " " * (len(s) - k))
    return "".join(out)


def parse_numbers(text, strict=False):
    """日付と番号を外して、数を拾う。返り値は [(見た目, 値, 小数の桁, 倍率, 割合か)]。
    strict（結論の節）では、バッククォートの中の数と、単独の「N 日」と時間の長さも数える。"""
    t = re.sub(r"^\s*(?:[-*]\s+)?(?:\d+[.)]\s+)?", " ", text)
    t = strip_conditions(t)
    t = TICK_EVIDENCE_RX.sub(_blank, t)
    if strict:
        t = EXCLUDE_NUM_RX.sub(_blank, t.replace("`", " "))
    else:
        t = EXCLUDE_LOOSE_RX.sub(_blank, t)
    out = []
    for m in NUM_RX.finditer(t):
        digits, frac, unit, pct = m.group(1), m.group(2) or "", m.group(3), m.group(4)
        v = float(digits.replace(",", "") + frac)
        k = len(frac) - 1 if frac else 0
        mult = {"万": 1e4, "億": 1e8}.get(unit, 1)
        if pct == "割":
            v, pct = v * 10, "%"
        out.append((m.group(0).strip(), v, k, mult, bool(pct)))
    return out


def numeric_values(rec):
    vals = []
    for r in rec.get("rows", []):
        for v in r:
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                vals.append(float(v))
            elif isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v.strip()):
                vals.append(float(v))
    return vals


def column_sums(rec):
    rows = rec.get("rows", [])
    if not rows:
        return []
    sums = []
    for k in range(len(rows[0])):
        col = [r[k] for r in rows if k < len(r)]
        if col and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in col if v is not None):
            nums = [float(v) for v in col if v is not None]
            if nums:
                sums.append(sum(nums))
    return sums


def ratio_values(rec):
    """割合の列（pct、rate、ratio、割合、率 などの名前）の値。割合の数（%）は、この値か計算の行とだけ比べる。"""
    cols, out = rec.get("columns", []), []
    for r in rec.get("rows", []):
        for k, v in enumerate(r):
            if k >= len(cols) or not RATIO_NAME.search(str(cols[k])) or isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                out.append(float(v))
            elif isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v.strip()):
                out.append(float(v))
    return out


def matches(num, v):
    """割合でない数が、値 v と表示の桁で合うか。割合（%）は生の数と比べない（3 件を 3% と書いても通さない）。"""
    _, d, k, mult, pct = num
    if pct:
        return False
    return abs(disp_round(v / mult, k) - d) < 1e-9


def pct_matches(num, v):
    """割合の数が、割合の列の値 v（0.03 か 3）と合うか。"""
    _, d, k, _, _ = num
    return any(abs(disp_round(c, k) - d) < 1e-9 for c in (v, v * 100))


def supported(num, direct, ratios):
    if num[4]:
        return any(pct_matches(num, v) for v in ratios)
    return any(matches(num, v) for v in direct)


def derivable(num, base):
    """計算の行の数が、結果の数の和・差・比・割合で出るか。割合の数は、比と増減の割合だけから出す。"""
    _, d, k, _, pct = num
    if not pct and any(matches(num, b) for b in base):
        return True
    for i, a in enumerate(base):
        for j, b in enumerate(base):
            if i == j:
                continue
            if pct:
                if b and any(abs(disp_round(c, k) - d) < 1e-9 for c in (a / b * 100, (a - b) / b * 100)):
                    return True
                continue
            cands = [a + b, a - b]
            if b:
                cands += [a / b, a / b * 100, (a - b) / b * 100]
            if any(matches(num, c) for c in cands):
                return True
    return False


def parse_value_list(text):
    items = {}
    for m in VALUE_ITEM_RX.finditer(text):
        if m.group("null"):
            key = None
        elif m.group("empty"):
            key = ""
        else:
            key = m.group("b") if m.group("b") is not None else m.group("a")
            if re.fullmatch(r"Q-\d+", key or ""):
                continue
        n = m.group("n")
        items[key] = int(n.replace(",", "")) if n else None
    return items


class Ctx:
    def __init__(self, root, log=None, schema=None, dict_path=None):
        self.root, self.log, self.schema, self.dict_path = root, log, schema, dict_path
        self.logs = {}
        self.dcols = set()  # 辞書に載った全部の列。"…" の引用が列の名前か文字の値かを決める

    def load(self, path, rep, where):
        key = str(pathlib.Path(path).resolve())
        if key not in self.logs:
            if not pathlib.Path(path).is_file():
                rep.fail(where, "根拠の実在", f"クエリの記録 {path} が無い")
                self.logs[key] = None
            else:
                recs, errs = load_log(path)
                self.logs[key] = {"path": path, "recs": recs, "errs": errs, "checked": False,
                                  "by_id": {r.get("id"): r for _, r in recs}}
        return self.logs[key]


def check_log(log, rep):
    if log is None or log["checked"]:
        return
    log["checked"] = True
    name = log["path"]
    for no, why in log["errs"]:
        rep.fail(f"{name}:{no}", "記録の形", why)
    ids = {}
    for no, rec in log["recs"]:
        where = f"{name}:{no}"
        rid = rec.get("id")
        missing = [k for k in RECORD_KEYS if k not in rec]
        if missing:
            rep.fail(where, "記録の形", f"{rid or '番号の無い記録'} に {', '.join(missing)} が無い。記録は道具が書き、手で書かない")
        if rid in ids:
            rep.fail(where, "番号", f"{rid} が {ids[rid]} 行目と重なる")
        ids.setdefault(rid, no)
        if not str(rec.get("env", "")).strip():
            rep.fail(where, "環境の名前", f"{rid} に環境の名前が無い")
        if rec.get("hash") != rec_hash(rec):
            rep.fail(where, "ハッシュ値", f"{rid} の文か結果が、道具が書いた後で変わった（ハッシュ値が合わない）")
        if rec.get("open") not in OPEN_MARKS.values():
            rep.fail(where, "読み取りだけ", f"{rid} は読み取り専用でない開き方（{rec.get('open')!r}）。道具の決まった開き方で回す")
        for rule, msg in check_select(rec.get("sql", ""))[0]:
            rep.fail(where, "読み取りだけ", f"{rid}: [{rule}] {msg}")
        for why in pii_problems(rec.get("sql", ""), rec.get("columns", []), rec.get("rows", [])):
            rep.fail(where, "行のコピー", f"{rid}: {why}。件数だけを残す")
        env = str(rec.get("env", ""))
        if rec.get("engine") != "import" and "本番" in env and "写し" not in env:
            rep.fail(where, "環境の名前", f"{rid} の環境「{env}」は本番。本番の数は依頼者が回し、--import で取り込む")


def doc_pii(path, lines, rep):
    for no, s in enumerate(lines, 1):
        n = pii_shapes(s)
        if n:
            rep.fail(f"{path}:{no}", "行のコピー", f"メールか電話番号の形の字が {n} 個ある。行を写さず、件数だけを書く")


def check_conditions(path, cited, by_id, dvalues, rep, dcols=None):
    """挙げたクエリの絞り込みの値が、辞書の値の一覧にあるかを見る。
    status = "x" の "…" は、辞書にその名前の列が無ければ、sqlite と同じく文字の値として照らす。"""
    known = {c.lower() for _, c in (dcols or set())} | {c.lower() for _, c in dvalues}
    for qid, no in cited:
        rec = by_id.get(qid)
        if not rec:
            continue
        sql = rec.get("sql", "")
        words = {w.lower() for w in re.findall(r"[^\W\d]\w*", sql)}
        pairs = condition_values(sql) + [(c, v) for c, v in condition_idents(sql) if v.lower() not in known]
        for colname, value in pairs:
            if re.fullmatch(r"-?\d+(\.\d+)?", value) or re.match(r"\d{4}-\d{2}-\d{2}", value) or value == "":
                continue
            for (t, c), vals in dvalues.items():
                if c.lower() != colname or t.lower() not in words:
                    continue
                if value not in {("" if k is None else str(k)) for k in vals}:
                    rep.fail(f"{path}:{no}", "条件の値", f"{qid} の条件の値「{value}」が、辞書の {t}.{c} の値の一覧に無い")


def dictionary_values(lines):
    tabs = md_tables(lines)
    dt = find_table(tabs, "テーブルと列", "実データ")
    out = {}
    if not dt:
        return out
    kc, kv = col_index(dt["header"], "テーブルと列"), col_index(dt["header"], "値の一覧")
    for _, cells in dt["rows"]:
        name = cell(cells, kc).strip("` ")
        if "." not in name:
            continue
        vals = parse_value_list(cell(cells, kv))
        if vals:
            t, c = name.split(".", 1)
            out[(t, c)] = vals
    return out


def dictionary_columns(lines):
    """辞書の全部の列（値の一覧の無い列も含む）。返り値は {(表, 列)}。"""
    dt = find_table(md_tables(lines), "テーブルと列", "実データ")
    if not dt:
        return set()
    kc = col_index(dt["header"], "テーブルと列")
    names = (cell(c, kc).strip("` ") for _, c in dt["rows"])
    return {tuple(n.split(".", 1)) for n in names if "." in n}


def evidence_refs(text):
    """根拠の「ファイル:行」を拾う。返り値は [(パス, 最初の行, 最後の行)]。`パス`:行 の形は、空白を含むパスも読む。"""
    found = list(TICK_EVIDENCE_RX.finditer(text)) + list(EVIDENCE_RX.finditer(TICK_EVIDENCE_RX.sub(_blank, text)))
    out = []
    for m in found:
        rel = m.group("path").strip()
        if rel.startswith(("http", "www.")) or re.fullmatch(r"[\d.]+", rel):
            continue
        first = int(m.group("a") or m.group("c"))
        out.append((rel, first, int(m.group("b") or m.group("d") or first)))
    return out


def check_evidence(path, no, text, root, rep):
    """根拠のファイルと行が、直下の中に実在するかを見る。返り値は見つけた根拠の数。"""
    n = 0
    for rel, line, last in evidence_refs(text):
        n += 1
        p = root / rel
        try:
            p.resolve().relative_to(pathlib.Path(root).resolve())
        except ValueError:
            rep.fail(f"{path}:{no}", "根拠の実在", f"根拠 {rel} が直下（{root}）の外を指す。根拠はプロジェクトの中のファイルだけにする")
            continue
        if not p.is_file():
            rep.fail(f"{path}:{no}", "根拠の実在", f"根拠のファイル {rel} が無い（直下は {root}）")
            continue
        try:
            total = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            total = 0
        if line < 1 or last > total:
            rep.fail(f"{path}:{no}", "根拠の実在", f"{rel} の {last} 行が無い（{total} 行のファイル）")
    return n


def repo_head(root):
    """直下が git の作業ツリーで commit があれば、HEAD の短い値を返す。git が無い、作業ツリーでない、commit が 0 本なら ""。
    読むだけの git rev-parse を呼ぶ。外から渡された GIT_DIR などは外し、直下の場所だけで決める。"""
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
    env.update(GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
    try:
        p = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                           timeout=10, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    head = p.stdout.strip()
    return head if p.returncode == 0 and re.fullmatch(r"[0-9a-f]{4,64}", head) else ""


def evidence_digest(lines, root):
    """辞書の表（冒頭の項目と内容の表を除く）が根拠に挙げた、直下の中のファイルから作るハッシュ値。git の無いプロジェクトの鮮度に使う。
    ファイルごとに中身の SHA-256 を取り、パスの順に「パス<TAB>値」の行を並べた全体の SHA-256 にする。消えたファイルは「無い」と並べる。
    返り値は (ハッシュ値の 16 進, ファイルの一覧)。直下の外を指す根拠は数えない（[根拠の実在] で別に落ちる）。"""
    base = pathlib.Path(root).resolve()
    files = set()
    for t in md_tables(lines):
        if len(t["header"]) >= 2 and t["header"][0] == "項目" and t["header"][1] == "内容":
            continue
        for _, cells in t["rows"]:
            for rel, _, _ in evidence_refs(" ".join(cells)):
                try:
                    files.add((base / rel).resolve().relative_to(base).as_posix())
                except (ValueError, OSError):
                    continue
    h = hashlib.sha256()
    for rel in sorted(files):
        p = base / rel
        try:
            digest = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "無い"
        except OSError:
            digest = "読めない"
        h.update(f"{rel}\t{digest}\n".encode("utf-8"))
    return h.hexdigest(), sorted(files)


def check_nogit(path, lines, commit, root, rep):
    """「git なし」の commit の欄。作った時刻と根拠のハッシュ値があり、直下が git の作業ツリーでなく、
    根拠のファイルから作り直したハッシュ値と合うときだけ通す。commit の比べと同じく、辞書を作ったあとの変化を見つけるため。"""
    val, no = commit
    where = f"{path}:{no}"
    if not NOGIT_RX.search(val):
        rep.fail(where, "鮮度", f"根拠のハッシュ値を書いた commit の欄に、「{NOGIT}」の印が無い（16 進の commit と混ぜない）")
    if not re.search(r"\d{4}-\d{2}-\d{2}", val):
        rep.fail(where, "鮮度", f"「{NOGIT}」の commit の欄に、作った時刻（2026-11-26T10:12:00+09:00 の形）が無い")
    head = repo_head(root)
    if head:
        rep.fail(where, "鮮度", f"直下（{root}）は git の作業ツリーで、HEAD は {head}。「{NOGIT}」ではなく、"
                 "git rev-parse --short HEAD の値を書く")
    m = NOGIT_HASH_RX.search(val)
    if not m:
        rep.fail(where, "鮮度", f"「{NOGIT}」の commit の欄に、根拠のハッシュ値（12〜64 字の 16 進）が無い。"
                 "値は data-dictionary-check.sh --evidence-hash が出す")
        return
    digest, files = evidence_digest(lines, root)
    if not files:
        rep.fail(where, "鮮度", "表に根拠のファイルと行が無く、根拠のハッシュ値で古さを見られない。根拠のファイルと行を書く")
    elif not digest.startswith(m.group(1)):
        rep.fail(where, "鮮度", f"根拠のファイル {len(files)} 本のどれかが、辞書を作ったあとに変わったか消えた（根拠のハッシュ値が合わない）。"
                 "根拠の行を読み直して辞書を直してから、--evidence-hash で値を出し直す")


def check_qrefs(path, no, text, by_id, rep, log_name):
    for qid in QREF_RX.findall(text):
        if qid not in by_id:
            rep.fail(f"{path}:{no}", "根拠の実在", f"クエリの番号 {qid} が記録 {log_name} に無い")


def check_number_cells(path, tabs, by_id, rep):
    """数の列と、クエリの番号か計算を持つ行は、結果か計算で出る数だけにする。"""
    calc_ok = []
    for t in tabs:
        kn = next((k for k, h in enumerate(t["header"]) if h in ("数", "数えた値", "件数")), None)
        for no, cells in t["rows"]:
            text = " ".join(cells)
            qids = [q for q in QREF_RX.findall(text) if q in by_id]
            is_calc = "計算" in text
            if kn is None or (not qids and not is_calc):
                continue
            nums = parse_numbers(cell(cells, kn))
            if not nums:
                continue
            recs = [by_id[q] for q in qids]
            direct = [v for r in recs for v in numeric_values(r)]
            ratios = [v for r in recs for v in ratio_values(r)]
            base = direct + [s for r in recs for s in column_sums(r)]
            for num in nums:
                if supported(num, direct, ratios):
                    continue
                if is_calc and derivable(num, base):
                    calc_ok.append(num)
                    continue
                how = "計算の行の" if is_calc else "表の"
                rep.fail(f"{path}:{no}", "数字の出どころ", f"{how}「{num[0]}」が、{', '.join(qids) or 'クエリ'} の結果{'から出ない（和・差・比・割合で確かめた）' if is_calc else 'に無い'}")
    return calc_ok


def check_dictionary(path, lines, ctx, rep):
    tabs = md_tables(lines)
    base_dir = pathlib.Path(path).resolve().parent
    info = header_info(tabs)
    holes = [(no, m.group(0)) for no, s in enumerate(lines, 1) for m in PLACEHOLDER_RX.finditer(s)]
    for no, h in holes[:5]:
        rep.fail(f"{path}:{no}", "テンプレートの穴", f"{h} が埋まっていない")
    if len(holes) > 5:
        rep.fail(path, "テンプレートの穴", f"ほか {len(holes) - 5} か所")
    for key in FRESH_KEYS:
        val, no = info.get(key, ("", 0))
        if not val.strip():
            rep.fail(f"{path}:{no}", "鮮度", f"冒頭の表に「{key}」が無い（鮮度は commit、スキーマのハッシュ値、集計の時刻、環境の名前の 4 つ）")
        elif PLACEHOLDER_RX.search(val):
            rep.fail(f"{path}:{no}", "鮮度", f"冒頭の表の「{key}」が埋まっていない")
    root = ctx.root or find_root(base_dir)
    commit = info.get("commit", ("", 0))
    if commit[0] and not PLACEHOLDER_RX.search(commit[0]):
        if NOGIT_RX.search(commit[0]) or "根拠のハッシュ値" in commit[0]:
            check_nogit(path, lines, commit, root, rep)
        elif not re.search(r"\b[0-9a-f]{7,40}\b", commit[0]):
            rep.fail(f"{path}:{commit[1]}", "鮮度", f"commit が 7〜40 字の 16 進ではない。git の無いプロジェクトなら「{NOGIT}」と"
                     "作った時刻と根拠のハッシュ値を書く（値は --evidence-hash が出す）")
    when = info.get("集計の時刻", ("", 0))
    if when[0] and not PLACEHOLDER_RX.search(when[0]) and not re.search(r"\d{4}-\d{2}-\d{2}", when[0]):
        rep.fail(f"{path}:{when[1]}", "鮮度", "集計の時刻に日付（2026-11-26 の形）が無い")
    env = info.get("環境の名前", ("", 0))[0]
    no_db = "無い" in env
    required = [("データの辞書", ("テーブルと列", "実データ")), ("書き込む処理の表", ("書き込む処理",)),
                ("食い違いの一覧", ("番号", "食い違い")), ("語彙と基準の数字", ("依頼者の語",)),
                ("読んだ範囲", ("読んでいない理由",))]
    found = {}
    for label, must in required:
        found[label] = find_table(tabs, *must)
        if not found[label]:
            rep.fail(path, "必須の節", f"「{label}」の表が無い（6 つの記録はテンプレート data-dictionary.md の形）")
    if not any("クエリの記録" in s for s in lines if s.startswith("#")):
        rep.fail(path, "必須の節", "「クエリの記録」の節が無い")
    log = None
    lp = path_in(info.get("クエリの記録", ("", 0))[0]) or ctx.log
    if lp:
        log = ctx.load(resolve(base_dir, root, lp), rep, path)
    elif not no_db:
        rep.fail(path, "根拠の実在", "クエリの記録のパスが無い（冒頭の表の「クエリの記録」か --log）")
    check_log(log, rep)
    by_id = log["by_id"] if log else {}
    log_name = log["path"] if log else "（無し）"
    snap = None
    sp = path_in(info.get("スキーマの写し", ("", 0))[0]) or ctx.schema
    if sp:
        spath = resolve(base_dir, root, sp)
        try:
            snap = json.loads(pathlib.Path(spath).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            rep.fail(path, "根拠の実在", f"スキーマの写し {sp} が読めない（{e}）")
    elif not no_db:
        rep.fail(path, "辞書の網羅", "スキーマの写しのパスが無い（冒頭の表の「スキーマの写し」か --schema）")
    if snap is not None:
        shape = snap.get("shape", {})
        if snap.get("hash") != shape_hash(shape):
            rep.fail(path, "ハッシュ値", "スキーマの写しが、道具が書いた後で変わった（ハッシュ値が合わない）")
        hv, hno = info.get("スキーマのハッシュ値", ("", 0))
        hx = (re.search(r"[0-9a-f]{12,64}", hv) or [None])[0] if hv else None
        if hv and not PLACEHOLDER_RX.search(hv) and not (hx and str(snap.get("hash", "")).startswith(hx)):
            rep.fail(f"{path}:{hno}", "ハッシュ値", f"冒頭のハッシュ値が、スキーマの写し（{str(snap.get('hash', ''))[:16]}）と違う")
    dt = found["データの辞書"]
    dvalues = dictionary_values(lines)
    if dt:
        h = dt["header"]
        kc, kv, kd, kb, kr = (col_index(h, "テーブルと列"), col_index(h, "値の一覧"), col_index(h, "食い違い"),
                              col_index(h, "裏づけ"), col_index(h, "実データ"))
        ledger = found["食い違いの一覧"]
        tids = set()
        if ledger:
            kt = col_index(ledger["header"], "番号")
            tids = {cell(c, kt).strip() for _, c in ledger["rows"]}
        values_rec = {}
        for _, rec in (log["recs"] if log else []):
            if rec.get("kind") == "values" and rec.get("table") and rec.get("column"):
                values_rec[(rec["table"].lower(), rec["column"].lower())] = rec
        covered = set()
        for no, cells in dt["rows"]:
            name = cell(cells, kc).strip("` ")
            where = f"{path}:{no}"
            table, column = (name.split(".", 1) + [""])[:2]
            covered.add(table.lower())
            backing = cell(cells, kb).strip()
            if kb is None or backing not in BACKING:
                rep.fail(where, "裏づけ", f"{name} の裏づけが「{backing}」。実測、実測（標本）、コードからの推定、聞き取りのどれかを書く")
            row_text = " ".join(cells)
            if backing.startswith("実測"):
                if no_db:
                    rep.fail(where, "裏づけ", f"{name} は実測だが、環境の名前が「無い」")
                elif not QREF_RX.search(cell(cells, kr)):
                    rep.fail(where, "裏づけ", f"{name} は実測なのに、実データにクエリの番号が無い")
            check_qrefs(path, no, row_text, by_id, rep, log_name)
            if not check_evidence(path, no, row_text, root, rep) and not QREF_RX.search(row_text) and "不明" not in row_text:
                rep.fail(where, "根拠", f"{name} の行に根拠が無い（コードの上の意味にファイルと行、実データにクエリの番号。"
                         "分からなければ「不明」と理由）")
            for tid in TREF_RX.findall(cell(cells, kd)):
                if tid not in tids:
                    rep.fail(where, "食い違いの一覧", f"{tid} が食い違いの一覧に無い")
            listed = parse_value_list(cell(cells, kv))
            if column and pii_like(table, column) and listed:
                rep.fail(where, "個人が分かる値", f"{name} は個人情報らしい列。値の一覧を書かず、件数だけにする")
            rec = values_rec.get((table.lower(), column.lower()))
            if rec and column:
                got = {(None if r[0] is None else str(r[0])): r[1] for r in rec.get("rows", []) if r}
                if not listed:
                    rep.fail(where, "値の一覧", f"{name} は値が {MAX_VALUES} 種類以下（{rec['id']}）なのに、値の一覧が無い")
                for v, n in got.items():
                    if v not in listed:
                        rep.fail(where, "値の一覧", f"{rec['id']} の値「{'NULL' if v is None else v}」が辞書の {name} に無い")
                    elif listed[v] is not None and listed[v] != n:
                        rep.fail(where, "値の一覧", f"{name} の「{v}」の件数が {listed[v]}。{rec['id']} では {n}")
                for v in listed:
                    if v not in got:
                        rep.fail(where, "値の一覧", f"辞書の {name} の値「{'NULL' if v is None else v}」が {rec['id']} に無い")
        if snap is not None:
            skip = set()
            for t in tabs:
                if "対象外" in t["heading"]:
                    kt = col_index(t["header"], "テーブル")
                    skip |= {cell(c, kt if kt is not None else 0).strip("` ").lower() for _, c in t["rows"]}
            wt = found["書き込む処理の表"]
            written = set()
            if wt:
                kwt = col_index(wt["header"], "テーブル")
                written = {cell(c, kwt if kwt is not None else 0).strip("` ").lower() for _, c in wt["rows"]}
            for t in sorted(snap.get("shape", {}).get("tables", {})):
                if t.lower() in skip:
                    continue
                if t.lower() not in covered:
                    rep.fail(path, "辞書の網羅", f"テーブル {t} が、辞書にも対象外の一覧にも無い")
                if wt and t.lower() not in written:
                    rep.fail(path, "書き込む処理", f"テーブル {t} の行が、書き込む処理の表に無い（見つからなければ「不明」と理由を書く）")
    # 表の行ごとの根拠。データの節の主張も、ほかの節と同じく、ファイルと行かクエリの番号で裏づける
    need = {"書き込む処理の表": "ファイルと行、トリガーの名前、クエリの番号、「不明」と理由",
            "食い違いの一覧": "コード側かデータ側の根拠（ファイルと行か、クエリの番号）",
            "語彙と基準の数字": "クエリの番号、ファイルと行、聞き取りの日付、依頼の文"}
    for label in ("書き込む処理の表", "食い違いの一覧", "語彙と基準の数字", "読んだ範囲"):
        t = found[label]
        if not t:
            continue
        for no, cells in t["rows"]:
            text = " ".join(cells)
            check_qrefs(path, no, text, by_id, rep, log_name)
            n_ev = check_evidence(path, no, text, root, rep) + len(QREF_RX.findall(text))
            if label not in need or n_ev:
                continue
            if label == "書き込む処理の表":
                kw = col_index(t["header"], "書き込む処理")
                unknown = "不明" in cell(cells, kw) and any(x.strip() for k2, x in enumerate(cells) if k2 not in (0, kw))
                if "トリガー" in cell(cells, kw) or unknown:
                    continue
            if label == "語彙と基準の数字" and (HEAR_RX.search(text) or "依頼の文" in text or (no_db and "未確認" in text)):
                continue
            rep.fail(f"{path}:{no}", "根拠", f"{label}の行に根拠が無い（{need[label]}）")
    rng = found["読んだ範囲"]
    if rng:
        ka, kb2, kr = col_index(rng["header"], "全体の数"), col_index(rng["header"], "読んだ数"), col_index(rng["header"], "読んでいない理由")
        for no, cells in rng["rows"]:
            a = re.sub(r"[^\d]", "", cell(cells, ka))
            b = re.sub(r"[^\d]", "", cell(cells, kb2))
            reason = cell(cells, kr).strip()
            if a and b and int(b) < int(a) and reason in ("", "なし", "-"):
                rep.fail(f"{path}:{no}", "読んだ範囲", "読んでいない所があるのに、理由が無い")
    voc = found["語彙と基準の数字"]
    if voc:
        check_number_cells(path, [voc], by_id, rep)
        check_baselines(path, voc, by_id, rep, no_db)
    doc_pii(path, lines, rep)
    cited = [(q, no) for no, s in enumerate(lines, 1) for q in QREF_RX.findall(s)]
    ctx.dcols |= dictionary_columns(lines)
    check_conditions(path, cited, by_id, dvalues, rep, ctx.dcols)
    return dvalues


def first_number(text):
    nums = parse_numbers(text)
    return nums[0][1] * nums[0][3] if nums else None


def check_baselines(path, voc, by_id, rep, no_db):
    """C-5: 語彙と基準の数字の表。行が 1 つ以上あり、「一致」の行は基準の値と数えた値が等しく、基準の値に出どころがある。
    読める DB があるなら、一致の行が 1 つ以上あるか、基準の値のある全部の行に差の理由（T か Q の番号）がある。"""
    h = voc["header"]
    kb, kc, km = col_index(h, "基準の値"), col_index(h, "数えた値"), col_index(h, "一致")
    if not voc["rows"]:
        rep.fail(path, "基準の数字", "語彙と基準の数字の表に行が無い。基準の数字を 1 つ以上数え直す")
        return
    good, reasons, based = 0, 0, 0
    for no, cells in voc["rows"]:
        where = f"{path}:{no}"
        base, counted, verdict = cell(cells, kb), cell(cells, kc), cell(cells, km).strip()
        b, c = first_number(base), first_number(counted)
        if c is not None and not QREF_RX.search(counted) and "計算" not in counted:
            rep.fail(where, "数字の出どころ", f"数えた値（{counted}）に、クエリの番号も計算の行も無い")
        if b is None:
            continue  # 語彙だけの行
        based += 1
        qids = [q for q in QREF_RX.findall(base) if q in by_id]
        if qids:
            recs = [by_id[q] for q in qids]
            direct = [v for r in recs for v in numeric_values(r)]
            ratios = [v for r in recs for v in ratio_values(r)]
            for num in parse_numbers(base):
                if not supported(num, direct, ratios):
                    rep.fail(where, "数字の出どころ", f"基準の値の「{num[0]}」が、{', '.join(qids)} の結果に無い")
        has_src = bool(qids) or bool(evidence_refs(base)) or "依頼の文" in base or bool(HEAR_RX.search(base))
        if verdict.startswith("一致") and not verdict.startswith("一致しない"):
            if not has_src:
                rep.fail(where, "基準の数字", "「一致」と書いたが、基準の値に出どころ（クエリの番号、ファイルと行、依頼の文、聞き取り）が無い")
            elif c is None or abs(b - c) > 1e-9:
                rep.fail(where, "基準の数字", f"「一致」と書いたが、基準の値（{base}）と数えた値（{counted}）が違う")
            else:
                good += 1
        elif TREF_RX.search(verdict) or QREF_RX.search(verdict):
            reasons += 1
    if not no_db and not good and (not based or reasons < based):
        rep.fail(path, "基準の数字", "一致した基準の数字が無く、差の理由（T か Q の番号）の無い行がある。基準の数字を 1 つ以上再現する")


def check_report(path, lines, ctx, rep, dvalues):
    tabs = md_tables(lines)
    base_dir = pathlib.Path(path).resolve().parent
    root = ctx.root or find_root(base_dir)
    info = header_info(tabs)
    env = next((v for k, (v, _) in info.items() if "環境" in k), "")
    no_db = "無い" in env
    lp = path_in(info.get("クエリの記録", ("", 0))[0]) or ctx.log
    log = ctx.load(resolve(base_dir, root, lp), rep, path) if lp else None
    if not lp and not no_db:
        rep.fail(path, "数字の出どころ", "クエリの記録が無い（冒頭の表の「クエリの記録」か --log）")
    check_log(log, rep)
    by_id = log["by_id"] if log else {}
    cited = [(q, no) for no, s in enumerate(lines, 1) for q in QREF_RX.findall(s)]
    for q, no in cited:
        if log and q not in by_id:
            rep.fail(f"{path}:{no}", "根拠の実在", f"クエリの番号 {q} が記録 {log['path']} に無い")
    calc_ok = check_number_cells(path, tabs, by_id, rep)
    concl = section_lines(lines, "結論")
    if not concl:
        rep.fail(path, "数字の出どころ", "結論の節が無い")
    recs = [by_id[q] for q, _ in cited if q in by_id]
    direct = [v for r in recs for v in numeric_values(r)]
    ratios = [v for r in recs for v in ratio_values(r)]
    text_all = "\n".join(lines)
    if not no_db:
        for no, s in concl:
            # 結論はバッククォートの中の数と、単位の付いた数も照らす（外すのは日付、番号、ファイルの行など）
            for num in parse_numbers(s, strict=True):
                if supported(num, direct, ratios) or any(abs(c[1] - num[1]) < 1e-9 and c[2:] == num[2:] for c in calc_ok):
                    continue
                rep.fail(f"{path}:{no}", "数字の出どころ", f"結論の「{num[0]}」が、挙げたクエリの結果にも計算の行にも無い")
            for m in KANJI_NUM_RX.finditer(s):
                rep.fail(f"{path}:{no}", "数字の出どころ", f"結論の「{m.group(0)}」は漢数字で、照らせない。算用数字で書き、クエリの結果と照らす")
    backs = []
    for t in tabs:
        kb = col_index(t["header"], "裏づけ")
        if kb is not None:
            backs += [cell(c, kb) for _, c in t["rows"]]
    concl_text = " ".join(s for _, s in concl)
    if not backs and "実測" not in concl_text and "推定" not in concl_text:
        rep.fail(path, "裏づけ", "主張ごとの裏づけ（実測か、コードからの推定か）が無い")
    if no_db and any(b.startswith("実測") for b in backs):
        rep.fail(path, "裏づけ", "環境の名前が「無い」のに、実測と書いた行がある")
    if not no_db and recs and backs and all("推定" in b for b in backs):
        rep.fail(path, "裏づけ", "読める DB があるのに、裏づけが全部「推定」。いまの状態の問いは実測で答える")
    if "検算" not in text_all:
        rep.fail(path, "検算", "検算の行（別の経路で同じ数を出す）も、検算が未確認の理由も無い")
    if not dvalues and ctx.dict_path:
        dlines = pathlib.Path(ctx.dict_path).read_text(encoding="utf-8").split("\n")
        dvalues, ctx.dcols = dictionary_values(dlines), ctx.dcols | dictionary_columns(dlines)
    if not dvalues:
        dp = path_in(info.get("データの辞書", ("", 0))[0])
        dfile = resolve(base_dir, root, dp) if dp else None
        if dfile and dfile.is_file():
            dlines = dfile.read_text(encoding="utf-8").split("\n")
            dvalues, ctx.dcols = dictionary_values(dlines), ctx.dcols | dictionary_columns(dlines)
    if dvalues:
        check_conditions(path, cited, by_id, dvalues, rep, ctx.dcols)
    elif any(condition_values(by_id[q].get("sql", "")) for q, _ in cited if q in by_id):
        rep.fail(path, "条件の値", "絞り込みの値を照らす辞書が無い（--dict か、冒頭の表の「データの辞書」）")
    doc_pii(path, lines, rep)


def run_evidence_hash(args):
    """git の無いプロジェクトで、辞書の commit の欄に書く値を出す。根拠のファイルと行を書き終えてから回し、VALUE の行を写す。
    git の作業ツリーでは出さない（commit の欄には HEAD を書く）。"""
    rep = Report(NAMES["check"] + " --evidence-hash", " ".join(args.files))
    n = 0
    for f in args.files:
        p = pathlib.Path(f)
        if not p.is_file() or p.suffix != ".md":
            rep.fail(f, "無い", "辞書（.md）が無い")
            continue
        lines = p.read_text(encoding="utf-8").split("\n")
        root = pathlib.Path(args.root).resolve() if args.root else find_root(p.resolve().parent)
        head = repo_head(root)
        if head:
            rep.fail(f, "鮮度", f"直下（{root}）は git の作業ツリーで、HEAD は {head}。commit の欄には、この値を書く")
            continue
        digest, files = evidence_digest(lines, root)
        if not files:
            rep.fail(f, "鮮度", "表に根拠のファイルと行が無く、根拠のハッシュ値を作れない")
            continue
        n += len(files)
        for rel in files:
            rep.say(f"FILE {rel}")
        rep.say(f"VALUE {NOGIT}（{now_iso()}、根拠のハッシュ値 {digest[:16]}）")
    return rep.show(f"根拠のファイル {n} 本")


def run_check(argv):
    ap = argparse.ArgumentParser(prog="data-dictionary-check.sh")
    ap.add_argument("files", nargs="+", help="辞書（.md）、調査の文書（結論の節を持つ .md）、クエリの記録（.jsonl）")
    ap.add_argument("--log", default="", help="クエリの記録（文書の冒頭の表に無いとき）")
    ap.add_argument("--schema", default="", help="スキーマの写し（辞書の冒頭の表に無いとき）")
    ap.add_argument("--dict", default="", help="調査の文書の条件の値を照らす辞書")
    ap.add_argument("--root", default="", help="根拠のファイルを探す直下（無ければ文書から上へ .git を探す）")
    ap.add_argument("--evidence-hash", action="store_true",
                    help="git の無いプロジェクトの辞書の commit の欄に書く値（「git なし」、今の時刻、根拠のハッシュ値）を出す。検査はしない")
    args = ap.parse_args(argv)
    if args.evidence_hash:
        return run_evidence_hash(args)
    rep = Report(NAMES["check"], " ".join(args.files))
    ctx = Ctx(pathlib.Path(args.root).resolve() if args.root else None, args.log or None, args.schema or None,
              args.dict or None)
    dicts, reports, logs = [], [], []
    for f in args.files:
        p = pathlib.Path(f)
        if not p.is_file():
            rep.fail(f, "無い", "ファイルが無い")
            continue
        if f.endswith(".jsonl"):
            logs.append(f)
            continue
        lines = p.read_text(encoding="utf-8").split("\n")
        is_dict = find_table(md_tables(lines), "テーブルと列", "実データ") is not None
        is_report = bool(section_lines(lines, "結論")) or any(HEADING_RX.match(s) and "結論" in s for s in lines)
        if not is_dict and not is_report:
            rep.fail(f, "文書の種類", "辞書の表（テーブルと列、実データ）も、結論の節も無い")
        if is_dict:
            dicts.append((f, lines))
        if is_report and not is_dict:
            reports.append((f, lines))
    dvalues = {}
    for f, lines in dicts:
        dvalues.update(check_dictionary(f, lines, ctx, rep))
    for f, lines in reports:
        check_report(f, lines, ctx, rep, dict(dvalues))
    for f in logs:
        check_log(ctx.load(f, rep, f), rep)
    n_recs = sum(len(v["recs"]) for v in ctx.logs.values() if v)
    return rep.show(f"辞書 {len(dicts)}、調査の文書 {len(reports)}、記録 {n_recs} 本")


# ---------------------------------------------------------------- 自己試験
SELFTEST_SQL = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT, created_at TEXT NOT NULL);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), status TEXT NOT NULL,
  total INTEGER NOT NULL, contact TEXT, deleted_at TEXT, is_deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE orders_old (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT);
CREATE TABLE events (id INTEGER PRIMARY KEY, order_id INTEGER, kind TEXT);
CREATE INDEX orders_status ON orders (status);
CREATE TRIGGER orders_event AFTER UPDATE OF status ON orders BEGIN INSERT INTO events (order_id, kind) VALUES (NEW.id, NEW.status); END;
INSERT INTO customers VALUES (1, 'A', 'a1@example.invalid', '2026-01-01'), (2, 'B', 'b2@example.invalid', '2026-02-01');
WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 30)
INSERT INTO orders (id, customer_id, status, total, contact, deleted_at, is_deleted, created_at)
SELECT n, CASE WHEN n = 30 THEN 9 ELSE 1 + n % 2 END,
  CASE WHEN n % 10 = 0 THEN 'cancel' WHEN n % 5 = 0 THEN 'canceled' WHEN n % 3 = 0 THEN 'shipped' ELSE 'paid' END,
  CASE WHEN n = 7 THEN 0 ELSE n * 100 END, CASE WHEN n = 1 THEN 'x@example.invalid' ELSE 'none' END, NULL, n % 4 = 0,
  printf('2026-10-%02d 10:00:00', n) FROM r;
INSERT INTO orders_old VALUES (1, 'paid', '2023-12-28');
"""


def make_db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(SELFTEST_SQL)
    conn.commit()
    conn.close()


def quiet(fn, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            code = fn(argv)
        except SystemExit as e:
            code = e.code
    return code, buf.getvalue()


GOOD_SQL = [
    "SELECT status, COUNT(*) FROM orders WHERE created_at >= '2026-10-01' GROUP BY status;",
    "WITH t AS (SELECT status FROM orders) SELECT status, COUNT(*) AS n FROM t GROUP BY status",
    "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 3) SELECT n FROM r",
    "SELECT COUNT(*) FILTER (WHERE status = 'x') FROM orders",
    'SELECT "update", "copy" FROM t',
    "SELECT ROW_NUMBER() OVER (PARTITION BY a ORDER BY b) FROM t",
    "SELECT CAST(total AS NUMERIC(10, 2)), strftime('%Y-%m', created_at) FROM orders -- 月ごと\n",
    "SELECT a FROM t WHERE NOT EXISTS (SELECT 1 FROM u WHERE u.id = t.id) AND b IN (SELECT c FROM v)",
    "SELECT x FROM generate_series(1, 3) AS g(x)",
]
BAD_SQL = [
    ("UPDATE orders SET status = 'x'", "一覧の外の文"),
    ("SELECT 1; DELETE FROM orders", "1 文だけ"),
    ("WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d", "一覧の外の語"),
    ("SELECT * INTO backup FROM orders", "一覧の外の語"),
    ("SELECT * FROM orders FOR UPDATE", "一覧の外の語"),
    ("SELECT * FROM orders FOR SHARE", "行のロック"),
    ("SELECT pg_read_file('/etc/hosts')", "関数の呼び出し"),
    ("SELECT lo_export(1, '/tmp/x')", "関数の呼び出し"),
    ("SELECT writefile('/tmp/x', status) FROM orders", "関数の呼び出し"),
    ("SELECT pg_catalog.set_config('default_transaction_read_only', 'off', false)", "関数の呼び出し"),
    ("SELECT nextval('orders_id_seq')", "関数の呼び出し"),
    ('SELECT "pg_read_file"(\'x\')', "関数の呼び出し"),
    ("SELECT pg_read_file('a') AS x", "関数の呼び出し"),
    ("SELECT * FROM users INTO OUTFILE '/tmp/u.csv'", "一覧の外の語"),
    ("SELECT /*!50000 1 */", "書き方"),
    ("SELECT 1 --x", "書き方"),
    ("SELECT 'a\\' , 1", "書き方"),
    ("SELECT $$x$$", "書き方"),
    ("SELECT @a := 1", "変数への代入"),
    ("PRAGMA writable_schema = 1", "一覧の外の文"),
    ("ATTACH DATABASE 'x' AS y", "一覧の外の文"),
    ("EXPLAIN ANALYZE DELETE FROM orders", "一覧の外の文"),
    ("WITH x AS (SELECT 1) DELETE FROM orders", "一覧の外の語"),
    # 査読で見つかった抜け。PostgreSQL は \r で注釈を終える。U& と UESCAPE、日本語の名前の関数、文字の値の後ろの括弧
    ("SELECT COUNT(*) AS n FROM orders -- x\r; DELETE FROM orders", "1 文だけ"),
    ("SELECT pg_read_file -- x\r('/etc/passwd')", "関数の呼び出し"),
    ("SELECT 1 -- x\x0b; DELETE FROM orders", "書き方"),
    ("SELECT 1 -- x ; DELETE FROM orders", "書き方"),
    ("SELECT U&\"pg_sleep\" UESCAPE '!' (10) AS n", "書き方"),
    ("SELECT U&\"pg_sleep\" UESCAPE '!' (10) AS n", "関数の呼び出し"),
    ("SELECT 書き込み(1)", "関数の呼び出し"),
    ("SELECT x FROM t WHERE a = 'b' (1)", "関数の呼び出し"),
]


def selftest_sql(results):
    for s in GOOD_SQL:
        probs, _, _ = check_select(s)
        results.append((not probs, f"許すはずの文が落ちた「{short_sql(s)}」: {probs[:2]}"))
    for s, rule in BAD_SQL:
        probs, _, _ = check_select(s)
        results.append((any(r == rule for r, _ in probs), f"「{rule}」で落ちるはずの文が通った「{short_sql(s)}」: {probs[:2]}"))
    got = condition_values("SELECT COUNT(*) FROM orders WHERE status = 'cancelled' AND kind IN ('a', 'b') AND 'x' = o.flag "
                           "AND \"state\" <> 'y' AND o.\"mode\" NOT IN ('z') AND created_at >= '2026-10-01'")
    want = [("status", "cancelled"), ("kind", "b"), ("flag", "x"), ("state", "y"), ("mode", "z")]
    results.append((all(w in got for w in want) and ("created_at", "2026-10-01") not in got, f"条件の値の拾い方が違う: {got}"))
    text = ("10 月のキャンセルは 81 件で、6% 増えた。Q-07 と 2026-11-26 10:12 と app/x.php:41 と OrderService.php の 88 行と 2 か所。"
            "推奨が変わる条件: 100 件を超えたら。")
    nums = [x[0] for x in parse_numbers(text)]
    results.append((nums == ["81", "6%"], f"結論の数の拾い方が違う（日付と番号は数えない）: {nums}"))
    selftest_review(results)


def selftest_review(results):
    """査読で見つかった抜けの負例（条件の値、個人情報、長い値、数字の出どころ、向き先、根拠のパス）。DB は使わない。"""
    got = condition_values("SELECT COUNT(*) FROM orders WHERE lower(status) = 'cancelled' AND typeof(total) = 'integer'")
    results.append((("status", "cancelled") in got and not any(c == "total" for c, _ in got), f"関数で包んだ列の条件の値: {got}"))
    got = condition_idents('SELECT COUNT(*) FROM orders o WHERE o.status = "cancelled" AND o.customer_id = "c"."id"')
    results.append((got == [("status", "cancelled")], f"\"…\" の条件の値: {got}"))
    rows_text = [["山田 太郎"]]
    cases = [("SELECT name AS n FROM customers", ["n"], rows_text, True),
             ("SELECT c.name FROM customers c", ["name"], rows_text, True),
             ("SELECT p.name, COUNT(*) AS n FROM order_items i JOIN products p ON p.id = i.product_id JOIN customers c "
              "ON c.id = i.customer_id GROUP BY p.name", ["name", "n"], [["マグ", 3]], False),
             ("SELECT replace(email, '@', ' at ') AS x FROM customers", ["x"], [["a at example.invalid"]], True),
             ("SELECT hex(email) AS x FROM customers", ["x"], [["6140"]], True),
             ("SELECT 氏名, 住所 FROM 顧客", ["氏名", "住所"], [["山田", "東京"]], True),
             ("SELECT phone AS p FROM members", ["p"], [[9012345678]], True),
             ("SELECT * FROM members", ["id", "phone"], [[1, 9012345678]], True),
             ("SELECT COUNT(email) AS email_count, SUM(CASE WHEN email IS NULL THEN 1 ELSE 0 END) AS no_mail FROM customers",
              ["email_count", "no_mail"], [[3, 1]], False),
             ("SELECT status, COUNT(*) AS n FROM orders WHERE customer_id IN (SELECT id FROM customers WHERE email IS NULL) "
              "GROUP BY status", ["status", "n"], [["paid", 3]], False),
             ("SELECT x FROM t", ["x"], [["０９０－１２３４－５６７８"]], True),
             ("SELECT x FROM t", ["x"], [["090 1234 5678"]], True)]
    for sql, cols, rows, bad in cases:
        why = pii_problems(sql, cols, rows)
        results.append((bool(why) == bad, f"個人情報の判定が違う（{'落とす' if bad else '通す'}はず）「{short_sql(sql, 50)}」: {why}"))
    t0 = time.monotonic()
    n = pii_shapes("x" * 200000) + pii_shapes("a@" * 2000)
    results.append((time.monotonic() - t0 < 1.0 and n > 0, f"長い値のメールの形を探すのに 1 秒を超えた（{time.monotonic() - t0:.2f} 秒）"))
    results.append((bool(pii_problems("SELECT x FROM t", ["x"], [["x" * (MAX_CELL + 1)]])), "長い値を記録に残した"))
    concl = [("キャンセルは `5` 件です。", ["5"]), ("4 件で、平均 12 日でした。", ["4", "12"]),
             ("5 件で、結論が変わる条件は 100 件です。", ["5"]), ("10 月 12 日の 3 時間で 7 件。", ["3", "7"])]
    for text, want in concl:
        nums = [x[0].split()[0] for x in parse_numbers(text, strict=True)]
        results.append((nums == want, f"結論の数の拾い方（strict）が違う「{text}」: {nums}"))
    results.append((bool(KANJI_NUM_RX.search("キャンセルは五件です。")) and not KANJI_NUM_RX.search("一覧と一致した"),
                    "漢数字の数の見つけ方が違う"))
    pct = parse_numbers("3% 増えた")[0]
    results.append((not supported(pct, [3.0], []) and supported(pct, [], [0.03]) and derivable(pct, [103.0, 100.0]),
                    "割合の数を、生の数と比べた（割合の列か、比の計算とだけ比べる）"))
    targets = [("postgres", "", "", {"PGHOST": "prod-db.example.invalid"}, True), ("postgres", "", "", {}, False),
               ("postgres", "", "", {"PGHOST": "/tmp"}, False), ("postgres", "postgres://u@db.example.invalid/x", "", {}, True),
               ("postgres", "host=127.0.0.1 dbname=x", "", {}, False), ("postgres", "", "", {"PGSERVICE": "prod"}, True),
               ("mysql", "x", "", {"MYSQL_HOST": "db.example.invalid"}, True), ("mysql", "x", "", {}, False)]
    for kind, database, defaults, env, bad in targets:
        why, _ = local_target(kind, database, defaults, env)
        results.append((bool(why) == bad, f"向き先の判定が違う（{kind} {database} {env}）: {why}"))
    try:
        env_for_db("本番")
        results.append((False, "本番の環境の名前で DB につなげた"))
    except ToolError as e:
        results.append((e.rule == "環境の名前", f"本番の環境の名前の落ち方が違う: {e.rule}"))
    refs = evidence_refs("Dockerfile:1 と `app/管理 画面.py`:2 と .python-version:1 と app/x.py の 3 行と ../../out.txt:2")
    want = [("app/管理 画面.py", 2, 2), ("Dockerfile", 1, 1), (".python-version", 1, 1), ("app/x.py", 3, 3), ("../../out.txt", 2, 2)]
    results.append((sorted(refs) == sorted(want), f"根拠のパスの拾い方が違う: {refs}"))


def selftest(kind):
    results = []
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="data-tools-"))
    try:
        db = tmp / "shop.db"
        make_db(db)
        log = tmp / "queries.jsonl"
        if kind in ("query", "check"):
            selftest_sql(results)
            conn, mark, _ = open_sqlite(db)
            try:
                conn.execute("CREATE TABLE w (a)")
                wrote = True
            except sqlite3.Error:
                wrote = False
            results.append((not wrote and mark == OPEN_MARKS["sqlite"], "読み取り専用で開いた接続に書けた"))
            try:
                open_sqlite(f"file:{db}?mode=rw")
                results.append((False, "mode=rw の開き方が通った"))
            except ToolError as e:
                results.append((e.rule == "読み取りだけ", f"mode=rw の落ち方が違う: {e.rule}"))
            try:
                CliEngine("postgres", path=str(tmp), environ={})  # 手元の PGHOST に左右されないよう、空の環境で見る
                results.append((False, "psql が無いのに通った"))
            except ToolError as e:
                results.append((e.rule == "道具が無い", f"psql が無いときの落ち方が違う: {e.rule}"))
            base = ["--db", str(db), "--env", "手元の作り物", "--log", str(log)]
            code, out = quiet(run_query, base + ["--sql", "SELECT status, COUNT(*) AS n FROM orders GROUP BY status ORDER BY n DESC"])
            results.append((code == 0 and "QUERY Q-001" in out, f"クエリが通らない: {out[-300:]}"))
            code, out = quiet(run_query, base + ["--sql", "UPDATE orders SET status = 'x'"])
            results.append((code == 1 and "[一覧の外の文]" in out, f"UPDATE が落ちない: {out[-200:]}"))
            code, out = quiet(run_query, base + ["--sql", "SELECT email FROM customers"])
            results.append((code == 1 and "[個人が分かる値]" in out and "example" not in out, f"個人情報の列が記録に入った: {out[-200:]}"))
            code, out = quiet(run_query, base + ["--sql", "SELECT COUNT(email) AS email_count FROM customers"])
            results.append((code == 0, f"個人情報らしい列の件数まで止めた: {out[-200:]}"))
            code, out = quiet(run_query, ["--db", f"file:{db}?mode=rwc", "--env", "x", "--log", str(log), "--sql", "SELECT 1"])
            results.append((code == 1 and "[読み取りだけ]" in out, f"mode=rwc が落ちない: {out[-200:]}"))
            slow = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 100000000) SELECT COUNT(*) FROM r"
            code, out = quiet(run_query, base + ["--timeout-ms", "50", "--sql", slow])
            results.append((code == 1 and "[打ち切り]" in out, f"打ち切りが効かない: {out[-200:]}"))
            csvf = tmp / "prod.csv"
            csvf.write_text("status,n\ncanceled,81\n", encoding="utf-8")
            code, out = quiet(run_query, ["--env", "本番の集計の書き出し", "--log", str(log), "--import", str(csvf),
                                          "--sql", "SELECT status, COUNT(*) AS n FROM orders GROUP BY status"])
            results.append((code == 0 and "QUERY Q-003" in out, f"取り込みが通らない: {out[-200:]}"))
            recs, errs = load_log(log)
            results.append((len(recs) == 3 and not errs and all(r["hash"] == rec_hash(r) for _, r in recs),
                            f"記録の数かハッシュ値が違う: {len(recs)} {errs}"))
        if kind in ("snapshot", "check"):
            snap = tmp / "schema.json"
            code, out = quiet(run_snapshot, ["--db", str(db), "--out", str(snap)])
            h = json.loads(snap.read_text(encoding="utf-8"))["hash"] if snap.exists() else ""
            results.append((code == 0 and f"HASH {h}" in out, f"写しが通らない: {out[-200:]}"))
            code2, out2 = quiet(run_snapshot, ["--db", str(db)])
            results.append((f"HASH {h}" in out2, "同じ DB でハッシュ値が変わった"))
            mig = tmp / "001.sql"
            mig.write_text(SELFTEST_SQL.split("INSERT INTO customers")[0].replace(" contact TEXT,", ""), encoding="utf-8")
            code, out = quiet(run_snapshot, ["--db", str(db), "--from-migrations", str(mig)])
            results.append((code == 0 and "DIFF 列 orders.contact: 実物にだけある" in out, f"マイグレーションとのずれが出ない: {out[-300:]}"))
            code, out = quiet(run_snapshot, ["--db", str(db), "--expect-hash", "0123456789abcdef"])
            results.append((code == 1 and "[ハッシュ値]" in out, "ハッシュ値の違いで落ちない"))
            bad = tmp / "002.sql"
            bad.write_text("ATTACH DATABASE 'x.db' AS x;", encoding="utf-8")
            code, out = quiet(run_snapshot, ["--db", str(db), "--from-migrations", str(bad)])
            results.append((code == 1 and "[マイグレーション]" in out, "ATTACH のあるマイグレーションが流れた"))
            # 生成列は table_xinfo で写しに入り、足すとハッシュ値が変わり、--compare がずれを出す
            gdb = tmp / "gen.db"
            conn = sqlite3.connect(str(gdb))
            conn.executescript("CREATE TABLE gen (a INTEGER, b INTEGER GENERATED ALWAYS AS (a * 2) VIRTUAL); INSERT INTO gen (a) VALUES (1);")
            conn.commit()
            gsnap = tmp / "gen.json"
            quiet(run_snapshot, ["--db", str(gdb), "--out", str(gsnap)])
            g1 = json.loads(gsnap.read_text(encoding="utf-8")) if gsnap.exists() else {}
            cols = [c["name"] for c in g1.get("shape", {}).get("tables", {}).get("gen", {}).get("columns", [])]
            conn.execute("ALTER TABLE gen ADD COLUMN c INTEGER GENERATED ALWAYS AS (a * 3) VIRTUAL")
            conn.commit()
            conn.close()
            code, out = quiet(run_snapshot, ["--db", str(gdb), "--compare", str(gsnap)])
            results.append((cols == ["a", "b"] and f"HASH {g1.get('hash')}" not in out and "DIFF 列 gen.c: 実物にだけある" in out,
                            f"生成列が写しに入らないか、足してもずれが出ない: {cols} {out[-300:]}"))
        if kind in ("profile", "check"):
            plog = tmp / "profile.jsonl"
            draft = tmp / "draft.md"
            code, out = quiet(run_profile, ["--db", str(db), "--env", "手元の作り物", "--log", str(plog), "--draft", str(draft)])
            text = draft.read_text(encoding="utf-8") if draft.exists() else ""
            recs = [r for _, r in load_log(plog)[0]] if plog.exists() else []
            vals = {(r.get("table"), r.get("column")) for r in recs if r.get("kind") == "values"}
            results.append((code == 0, f"集計が通らない: {out[-300:]}"))
            results.append((("orders", "status") in vals and ("customers", "email") not in vals and ("orders", "contact") not in vals,
                            f"値の一覧の選び方が違う: {sorted(vals)}"))
            results.append(("example" not in plog.read_text(encoding="utf-8") and "example" not in text, "個人が分かる値が記録か下書きに入った"))
            for want in ("型 2（書かれない列）: orders.deleted_at", "型 3（二重の置き場）: orders.deleted_at と orders.is_deleted",
                         "型 7（孤児の行）: orders.customer_id の 1 行", "型 9（試しのデータ）: orders.total"):
                results.append((want in out, f"罠の候補「{want}」が出ない"))
            results.append(("`canceled` 3 件" in text and "| orders.total |" in text, f"下書きの形が違う: {text[:300]}"))
            code, out = quiet(run_profile, ["--db", str(db), "--env", "x", "--log", str(tmp / "s.jsonl"), "--sample-over", "5",
                                            "--tables", "orders"])
            results.append((code == 0 and "実測（標本）" in out, "大きいテーブルの標本が効かない"))
            # 日本語の列の名前と、全文検索の影の表の値は、下書きにも記録にも出さない（値はどれも作り物）
            jdb = tmp / "ja.db"
            conn = sqlite3.connect(str(jdb))
            conn.executescript("CREATE TABLE 顧客 (id INTEGER PRIMARY KEY, 氏名 TEXT, 住所 TEXT, 電話 TEXT);"
                               "INSERT INTO 顧客 VALUES (1, '架空 一郎', '架空県架空市', '０９０－１２３４－５６７８'), (2, '架空 二郎', '架空県', '090 1234 5678');"
                               "CREATE TABLE shops (id INTEGER PRIMARY KEY, owner TEXT); INSERT INTO shops VALUES (1, '架空 三郎');"
                               "CREATE VIRTUAL TABLE docs USING fts5(body); INSERT INTO docs VALUES ('架空の問い合わせの本文');")
            conn.commit()
            conn.close()
            jlog, jdraft = tmp / "ja.jsonl", tmp / "ja.md"
            code, out = quiet(run_profile, ["--db", str(jdb), "--env", "手元の作り物", "--log", str(jlog), "--draft", str(jdraft)])
            both = (jdraft.read_text(encoding="utf-8") if jdraft.exists() else "") + (jlog.read_text(encoding="utf-8") if jlog.exists() else "")
            leaked = [w for w in ("架空 一郎", "架空県", "１２３４", "1234", "架空 三郎", "問い合わせの本文") if w in both]
            results.append((code == 0 and not leaked, f"日本語の列か影の表の値が、下書きか記録に出た: {leaked} {out[-200:]}"))
            code, out = quiet(run_profile, ["--db", str(db), "--env", "本番", "--log", str(tmp / "p.jsonl")])
            results.append((code == 1 and "[環境の名前]" in out, f"本番の環境の名前で集計が回った: {out[-200:]}"))
            if kind == "check":
                selftest_check(tmp, db, plog, draft, results)
        if kind == "writers":
            code_dir = tmp / "code"
            (code_dir / "app").mkdir(parents=True)
            (code_dir / "app" / "Order.php").write_text(
                "<?php\nclass Order extends Model {\n    protected $table = 'orders';\n}\n", encoding="utf-8")
            (code_dir / "app" / "OrderService.php").write_text(
                "<?php\nclass OrderService {\n  function cancel($id) {\n    DB::table('orders')->where('id', $id)->update(['status' => 'canceled']);\n"
                "    Order::create(['status' => 'paid']);\n  }\n}\n", encoding="utf-8")
            (code_dir / "batch.py").write_text("def run(cur):\n    cur.execute(\"DELETE FROM orders_old WHERE id = ?\", (1,))\n",
                                               encoding="utf-8")
            (code_dir / "close.rb").write_text("class Closer\n  def run\n    Event.where(kind: 'old').delete_all\n  end\nend\n",
                                               encoding="utf-8")
            (code_dir / "node_modules").mkdir()
            (code_dir / "node_modules" / "x.js").write_text("db.query('INSERT INTO customers VALUES (1)')\n", encoding="utf-8")
            code, out = quiet(run_writers, ["--code", str(code_dir), "--db", str(db)])
            for want in ("| orders | app/OrderService.php:4（update", "| orders | app/OrderService.php:5（create、モデル Order（宣言））",
                         "| orders_old | batch.py:2（DELETE", "| events | トリガー orders_event（orders への UPDATE で動く）",
                         "| events | close.rb:3（delete_all、モデル Event（名前））", "| customers | 不明 |"):
                results.append((want in out, f"書き込む処理「{want}」が出ない: {out[-600:]}"))
            results.append(("node_modules" not in out, "node_modules を読んだ"))
            # 日本語の表と、空白を含む引用の表も拾う
            ja = tmp / "ja-code"
            ja.mkdir()
            (ja / "app.py").write_text("def run(cur):\n    cur.execute(\"INSERT INTO 注文 (id) VALUES (1)\")\n"
                                       "    cur.execute('UPDATE \"order items\" SET qty = 2')\n    cur.execute(\"DELETE FROM empty_t\")\n",
                                       encoding="utf-8")
            jshape = tmp / "ja-shape.json"
            jshape.write_text(json.dumps({"shape": {"tables": {"注文": {"columns": []}, "order items": {"columns": []},
                                                               "empty_t": {"columns": []}}, "triggers": {}}}), encoding="utf-8")
            code, out = quiet(run_writers, ["--code", str(ja), "--schema", str(jshape)])
            for want in ("| 注文 | app.py:2（INSERT", "| order items | app.py:3（UPDATE", "| empty_t | app.py:4（DELETE"):
                results.append((want in out, f"日本語か引用の表「{want}」が出ない: {out[-400:]}"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = True
    for passed, msg in results:
        if not passed:
            ok = False
            print(f"FAIL selftest {NAMES[kind]}: {msg}")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} {NAMES[kind]} --selftest ({len(results)} 例)")
    return 0 if ok else 1


def selftest_check(tmp, db, plog, draft, results):
    """辞書と調査の文書を下書きから組み、正例が通り、わざと崩した例が決まりの名前で落ちることを見る。"""
    snap = tmp / "schema.json"
    quiet(run_snapshot, ["--db", str(db), "--out", str(snap)])
    h = json.loads(snap.read_text(encoding="utf-8"))["hash"]
    (tmp / "app").mkdir(exist_ok=True)
    (tmp / "app" / "Order.php").write_text("<?php\n// status は paid、shipped、canceled\nclass Order {}\n", encoding="utf-8")
    (tmp / ".git").mkdir(exist_ok=True)
    base = ["--db", str(db), "--env", "手元の作り物", "--log", str(plog)]
    quiet(run_query, base + ["--sql", "SELECT status, COUNT(*) AS n FROM orders WHERE status IN ('cancel', 'canceled') GROUP BY status ORDER BY status"])
    quiet(run_query, base + ["--sql", "SELECT COUNT(*) AS n FROM orders WHERE status LIKE 'cancel%'"])
    quiet(run_query, base + ["--sql", "SELECT COUNT(*) AS n FROM orders WHERE status = 'cancelled'"])
    recs = [r for _, r in load_log(plog)[0]]
    q_split, q_check, q_bad = recs[-3]["id"], recs[-2]["id"], recs[-1]["id"]
    rows = []
    for line in draft.read_text(encoding="utf-8").split("\n"):
        if line.startswith("| ") and "." in line.split("|")[1]:
            rows.append(line.replace("<コードの上の意味（ファイル:行）>", "app/Order.php:2").replace("<T-番号か、なし>", "なし"))
    status = next(r for r in rows if r.startswith("| orders.status |"))
    rows = [r.replace(status, status.replace("| なし |", "| T-01 |")) if r == status else r for r in rows]
    tables = sorted({r.split("|")[1].strip().split(".")[0] for r in rows})
    head = [
        "# データの辞書: サンプル", "", "| 項目 | 内容 |", "|---|---|", "| commit | a1b2c3d |", f"| スキーマのハッシュ値 | {h[:16]} |",
        "| 集計の時刻 | 2026-11-26 10:12 |", "| 環境の名前 | 手元の作り物 |", "| スキーマの写し | schema.json |",
        f"| クエリの記録 | {plog.name} |", "", "## 1. データの辞書", "", "辞書です。", "",
        "| テーブルと列 | コードの上の意味 | 実データ | 値の一覧 | 食い違い | 裏づけ |", "|---|---|---|---|---|---|"]
    tail = [
        "", "## 2. 書き込む処理の表", "", "表です。", "", "| テーブル | 書き込む処理 | 書く列と条件 | 生きている証拠 | 状態 |",
        "|---|---|---|---|---|", "| orders | app/Order.php:3 | status | 未確認 | 候補 |",
        "| customers | 不明 | name と email | 書き込む処理が見つからない | 候補 |",
        "| events | トリガー orders_event（orders への UPDATE で動く） | order_id と kind | 未確認 | 候補 |",
        "| orders_old | 不明 | 全部の列 | 書き込む処理が見つからない | 書かれない |", "",
        "## 3. 食い違いの一覧", "", "表です。", "", "| 番号 | 食い違い | コード側の根拠 | データ側の根拠 | いまの状態 | これからの振る舞い | あるべき姿 | 確かめた日 |",
        "|---|---|---|---|---|---|---|---|", f"| T-01 | cancel と canceled | app/Order.php:2 | {q_split} | 両方を数える | 未確認 | 未決 | 2026-11-26 |", "",
        "## 4. 語彙と基準の数字", "", "表です。", "", "| 依頼者の語 | 条件の文 | 基準の値 | 数えた値 | 一致 | 確かめた日 |",
        "|---|---|---|---|---|---|", f"| キャンセル | status が cancel か canceled | 6 件（依頼の文） | 6 件（{q_check}） | 一致 | 2026-11-26 |", "",
        "## 5. 読んだ範囲", "", "表です。", "", "| 対象 | 全体の数 | 読んだ数 | 読んでいない理由 |", "|---|---|---|---|",
        f"| テーブル | {len(tables)} | {len(tables)} | なし |", "", "## 6. クエリの記録", "", "道具が書きます。", ""]
    good = "\n".join(head + rows + tail)
    dic = tmp / "dictionary.md"
    report_lines = [
        "# 10 月のキャンセル", "", "| 項目 | 内容 |", "|---|---|", f"| クエリの記録 | {plog.name} |", "| データの辞書 | dictionary.md |",
        "| 環境の名前 | 手元の作り物 |", "", "## 集計の表", "", "数ごとの出どころです。", "", "| 数 | 何の数か | クエリ | 裏づけ |", "|---|---|---|---|",
        f"| 3 件 | canceled | {q_split} | 実測 |", f"| 6 件 | 合計 | 計算: {q_split} の n の合計 | 実測 |",
        f"| 6 件 | 検算: LIKE で数えた値 | {q_check} | 実測 |", "", "## 結論", "",
        "10 月のキャンセルは 6 件で、canceled が 3 件です。検算の値とも一致し、どれも実測です。", ""]
    rep_doc = tmp / "report.md"

    def run(dtext, rtext, files=None, extra=()):
        dic.write_text(dtext, encoding="utf-8")
        rep_doc.write_text(rtext, encoding="utf-8")
        return quiet(run_check, [str(x) for x in (files or [dic, rep_doc])] + list(extra))

    good_r = "\n".join(report_lines)
    code, out = run(good, good_r)
    results.append((code == 0, f"辞書と調査の文書の正例が落ちた: {out[-700:]}"))
    status_t = next(r for r in good.split("\n") if r.startswith("| orders.status |"))
    cases = [
        ("結論の数を 1 つ変える", good, good_r.replace("キャンセルは 6 件", "キャンセルは 7 件"), "数字の出どころ"),
        ("計算の行の数を変える", good, good_r.replace("| 6 件 | 合計", "| 8 件 | 合計"), "数字の出どころ"),
        ("辞書に無い値で絞る", good, good_r.replace(f"| 3 件 | canceled | {q_split}", f"| 0 件 | cancelled | {q_bad}"), "条件の値"),
        ("辞書から値を 1 つ消す", good.replace(status_t, re.sub(r"`cancel` \d+ 件、", "", status_t)), good_r, "値の一覧"),
        ("辞書からテーブルを 1 つ消す", "\n".join(r for r in good.split("\n") if not r.startswith("| orders_old.")), good_r, "辞書の網羅"),
        ("行番号を 1 万にする", good.replace("app/Order.php:3", "app/Order.php:10000"), good_r, "根拠の実在"),
        ("サンプルのメールを 1 つ書く", good.replace("| 未確認 | 候補 |", "| a1@example.invalid | 候補 |"), good_r, "行のコピー"),
        ("ハッシュ値を変える", good.replace(h[:16], "0" * 16), good_r, "ハッシュ値"),
        ("鮮度の欄を消す", good.replace("| commit | a1b2c3d |\n", ""), good_r, "鮮度"),
        ("裏づけを全部推定にする", good, good_r.replace("| 実測 |", "| コードからの推定 |").replace("どれも実測です", "どれも推定です"), "裏づけ"),
        ("検算を消す", good, good_r.replace("検算: LIKE で数えた値", "LIKE で数えた値").replace("検算の値とも一致し、", ""), "検算"),
        ("食い違いの番号が一覧に無い", good.replace("| T-01 | cancel と canceled", "| T-02 | cancel と canceled"), good_r, "食い違いの一覧"),
    ]
    for name, d, r, rule in cases:
        code, out = run(d, r)
        results.append((code == 1 and f"[{rule}]" in out, f"負例「{name}」が [{rule}] で落ちない: {out[-500:]}"))
    selftest_nogit(tmp, dic, good, good_r, run, results)
    lines = plog.read_text(encoding="utf-8").splitlines()
    forged = dict(json.loads(lines[-1]), id="Q-900", sql="UPDATE orders SET status = 'canceled' WHERE id = 1")
    forged["hash"] = rec_hash(forged)
    rw = dict(json.loads(lines[-1]), id="Q-901", open="sqlite mode=rwc")
    rw["hash"] = rec_hash(rw)
    edited = json.loads(lines[-2])
    edited["rows"] = [[7]]
    for name, extra_line, rule in (("UPDATE の文を記録に混ぜる", json.dumps(forged, ensure_ascii=False), "読み取りだけ"),
                                   ("読み取り専用でない開き方", json.dumps(rw, ensure_ascii=False), "読み取りだけ"),
                                   ("結果の数を 1 つ書き換える", json.dumps(edited, ensure_ascii=False), "ハッシュ値")):
        f = tmp / "forged.jsonl"
        f.write_text("\n".join(lines + [extra_line]) + "\n", encoding="utf-8")
        code, out = quiet(run_check, [str(f)])
        results.append((code == 1 and f"[{rule}]" in out, f"負例「{name}」が [{rule}] で落ちない: {out[-300:]}"))
    tpl = pathlib.Path(__file__).resolve().parent.parent / "templates" / "data-dictionary.md"
    if tpl.exists():
        code, out = quiet(run_check, [str(tpl)])
        results.append((code == 1 and "[テンプレートの穴]" in out, "テンプレートが穴埋めのまま通った"))


def selftest_nogit(tmp, dic, good, good_r, run, results):
    """git の無いプロジェクトの commit の欄（「git なし」と作った時刻と根拠のハッシュ値）。git の有無は repo_head を差し替えて決め、
    手元の一時の場所が git の中にあっても結果が変わらないようにする。根拠のファイルが変わると [鮮度] で落ち、緩めていないことを見る。"""
    real = globals()["repo_head"]
    src = tmp / "app" / "Order.php"
    body = src.read_text(encoding="utf-8")
    try:
        globals()["repo_head"] = lambda root: ""
        dic.write_text(good, encoding="utf-8")
        code, out = quiet(run_check, ["--evidence-hash", str(dic)])
        m = re.search(r"^VALUE (.+)$", out, re.M)
        results.append((code == 0 and m is not None and "FILE app/Order.php" in out, f"--evidence-hash が値を出さない: {out[-300:]}"))
        value = m.group(1) if m else f"{NOGIT}（2026-11-26T10:12:00+09:00、根拠のハッシュ値 {'0' * 16}）"
        nogit = good.replace("| commit | a1b2c3d |", f"| commit | {value} |")
        code, out = run(nogit, good_r)
        results.append((code == 0, f"「{NOGIT}」の形の正例が落ちた: {out[-500:]}"))
        src.write_text(body + "// 足した行\n", encoding="utf-8")
        code, out = run(nogit, good_r)
        results.append((code == 1 and "[鮮度]" in out and "ハッシュ値が合わない" in out, f"根拠のファイルが変わっても落ちない: {out[-300:]}"))
        src.write_text(body, encoding="utf-8")
        negs = [("根拠のハッシュ値が無い", re.sub(r"、根拠のハッシュ値 [0-9a-f]+", "", nogit), "根拠のハッシュ値（"),
                ("作った時刻が無い", re.sub(r"\d{4}-\d{2}-\d{2}T[\d:+\-]+、", "", nogit), "作った時刻"),
                ("「git なし」の印が無い（16 進と読ませない）", nogit.replace(f"| commit | {NOGIT}", "| commit | "), "の印が無い"),
                ("「無い」だけでは通さない（前と同じ）", good.replace("| commit | a1b2c3d |", "| commit | 無い（git が無い） |"), "16 進ではない")]
        for name, d, want in negs:
            code, out = run(d, good_r)
            results.append((code == 1 and "[鮮度]" in out and want in out, f"負例「{name}」が [鮮度] で落ちない: {out[-300:]}"))
        globals()["repo_head"] = lambda root: "abc1234"
        code, out = run(nogit, good_r)
        results.append((code == 1 and "[鮮度]" in out and "git の作業ツリー" in out, f"git の作業ツリーで「{NOGIT}」が通った: {out[-300:]}"))
        code, out = quiet(run_check, ["--evidence-hash", str(dic)])
        results.append((code == 1 and "VALUE" not in out, f"git の作業ツリーで --evidence-hash が値を出した: {out[-300:]}"))
    finally:
        globals()["repo_head"] = real
        src.write_text(body, encoding="utf-8")


def main(argv):
    if len(argv) < 1 or argv[0] not in NAMES:
        print(__doc__)
        return 2
    kind, rest = argv[0], argv[1:]
    if rest[:1] == ["--selftest"]:
        return selftest(kind)
    runner = {"snapshot": run_snapshot, "profile": run_profile, "query": run_query, "writers": run_writers, "check": run_check}[kind]
    return runner(rest)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
