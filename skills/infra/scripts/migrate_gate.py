#!/usr/bin/env python3
"""migrate_gate — 移行の SQL を、許す文の一覧で確かめる（止める物の一覧では書かない）。

使い方: migrate_gate.py <移行の SQL...>   /   migrate_gate.py --selftest
許す文（どれも足し算の DDL で、行を書かず、関数を呼ばない）:
  BEGIN、COMMIT、SET [LOCAL] lock_timeout か statement_timeout（値は数か文字の定数）
  CREATE TABLE <名前> (<列と制約>)、CREATE [UNIQUE] INDEX [CONCURRENTLY] <名前> ON <表> (<列>)
  ALTER TABLE <表> の ADD COLUMN、ADD CONSTRAINT（FOREIGN KEY と CHECK と UNIQUE と PRIMARY KEY、NOT VALID）、VALIDATE CONSTRAINT
落とすもの: 一覧の外の文の型（行の読み書き、COPY、規則、関数、トリガー、方針、権限、スキーマ、見方、役割、search_path、DO、消す文）、
  psql の命令（行の逆斜線。\\! と \\copy … to program は移行のタスクの中で命令を動かす）、ドルの引用、/* */ の注釈、引用した名前、
  関数の呼び出し（既定値の now() だけは許す）、定数でない既定値、ALTER TABLE の中の消す・変える・付け替える・止める操作。
  一覧の外の文は、別の承認 2 人の経路（利用者づくりの作業が持ち主の役割で流し、roles.sql が指紋を取り直す）へ回す。
DB の側でも、事象のトリガーと文のトリガーが同じ一覧を強制する（samples/infra/db/roles.sql）。この検査は PR の必須の検査と、移行のイメージを
押し込む前に回す。
出力: FAIL <file>:<文の番号> [<決まり>] <内容>、最後に RESULT: PASS|FAIL migrate-gate <対象> (文 N、FAIL N)。1 件でも FAIL なら終了コード 1。
"""
import pathlib
import re
import shutil
import sys
import tempfile

STARTS = [
    r"BEGIN", r"COMMIT",
    r"SET( LOCAL)? (LOCK_TIMEOUT|STATEMENT_TIMEOUT)( = | TO )(L|[0-9]+)",
    r"CREATE TABLE ",
    r"CREATE (UNIQUE )?INDEX ",
    r"ALTER TABLE ",
]
FORBIDDEN = {
    "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "COPY", "MERGE", "GRANT", "REVOKE", "FUNCTION", "PROCEDURE", "RULE",
    "TRIGGER", "POLICY", "SCHEMA", "ROLE", "OWNER", "SEARCH_PATH", "SECURITY", "EXECUTE", "CALL", "DO", "AS", "USING", "DISABLE",
    "ENABLE", "RENAME", "INHERITS", "INHERIT", "LIKE", "PARTITION", "TABLESPACE", "EXTENSION", "VIEW", "GENERATED", "WITH", "RETURNING",
    "LOCK", "VACUUM", "CLUSTER", "COMMENT", "SESSION", "AUTHORIZATION", "RESET", "NOTIFY", "LISTEN", "PREPARE", "IMPORT", "SERVER",
    "ATTACH", "DETACH", "DROP", "TEMP", "TEMPORARY", "UNLOGGED", "REPLICA", "FORCE", "OF", "INCLUDE", "WHERE", "SEQUENCE", "TYPE",
}
# 括弧の前に置いてよい語（関数の呼び出しでない括弧）。表の名前の後の括弧は、前の語で見分ける。
PAREN_OK = {"KEY", "CHECK", "IN", "UNIQUE", "NUMERIC", "DECIMAL", "VARCHAR", "CHAR", "VARYING", "AND", "OR", "NOT"}
PAREN_AFTER = {"REFERENCES", "ON", "TABLE", "EXISTS"}
DEFAULT_OK = re.compile(r"\bDEFAULT (L|-?[0-9]+(\.[0-9]+)?|NULL|TRUE|FALSE|NOW \( \)|CURRENT_TIMESTAMP)(?= |,|\)|$)")


def statements(text):
    """注釈を外し、引用の外の ; で文に分ける。文字の定数は L に置き換える。"""
    out, cur, i, n = [], "", 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "'":
            j = i + 1
            while j < n:
                if text[j] == "'" and j + 1 < n and text[j + 1] == "'":
                    j += 2
                    continue
                if text[j] == "'":
                    break
                j += 1
            # 既定値に置いてよい文字の定数は、英小文字と数字と _ の 32 字まで（DB の guard.shape_problems と同じ形）。ほかは LX にして既定値で落とす。
            cur += " L " if re.fullmatch(r"[a-z0-9_]{0,32}", text[i + 1:j]) else " LX "
            i = j + 1
            continue
        if text.startswith("--", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == ";":
            out.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    out.append(cur)
    norm = []
    for s in out:
        s = re.sub(r"([(),=])", r" \1 ", s)
        s = re.sub(r"\s+", " ", s).strip().upper()
        s = s.replace(" = ", " = ")
        if s:
            norm.append(s)
    return norm


def check_text(text, where):
    fails = []

    def fail(k, rule, msg):
        fails.append(f"FAIL {where}:{k} [{rule}] {msg}")

    for lineno, line in enumerate(text.split("\n"), 1):
        if "\\" in line:
            fail(f"行{lineno}", "psql の命令", "逆斜線がある（\\! や \\copy … to program は移行のタスクの中で命令を動かす）")
        if "$" in line:
            fail(f"行{lineno}", "ドルの引用", "関数の本文か DO の塊（一覧の外。承認 2 人の経路へ）")
        if "/*" in line or '"' in line:
            fail(f"行{lineno}", "書き方", "/* */ の注釈か引用した名前（読み違えを避けるため使わない）")
    stmts = statements(text)
    for k, s in enumerate(stmts, 1):
        short = s[:70]
        if not any(re.match(p + (r"$" if p in ("BEGIN", "COMMIT") or p.startswith("SET") else ""), s) for p in STARTS):
            fail(k, "一覧の外の文", f"許す文の型ではない「{short}」")
            continue
        words = re.findall(r"[A-Z_][A-Z0-9_]*", s)
        bad = sorted(set(words) & FORBIDDEN)
        if s.startswith("SET"):
            bad = []
        if bad:
            fail(k, "一覧の外の語", f"{', '.join(bad)}「{short}」")
        if s.startswith("ALTER TABLE") and len(re.findall(r"\bALTER\b", s)) > 1:
            fail(k, "一覧の外の語", f"ALTER TABLE の中で列や制約を変える「{short}」")
        rest = DEFAULT_OK.sub(" ", s)
        if re.search(r"\bDEFAULT\b", rest):
            fail(k, "既定値", f"既定値が定数と now() の外（表を書き直すときに式が動く）「{short}」")
        toks = rest.split(" ")
        for idx, tok in enumerate(toks):
            if tok != "(" or idx == 0:
                continue
            prev = toks[idx - 1]
            prev2 = toks[idx - 2] if idx >= 2 else ""
            if not re.fullmatch(r"[A-Z_][A-Z0-9_.]*", prev):
                continue
            if prev in PAREN_OK or prev2 in PAREN_AFTER:
                continue
            fail(k, "関数の呼び出し", f"{prev}(…) は関数の呼び出し（関数は一覧の外）「{short}」")
    return fails, len(stmts)


def report(paths):
    fails, total = [], 0
    for p in paths:
        try:
            text = pathlib.Path(p).read_text(encoding="utf-8")
        except OSError as e:
            fails.append(f"FAIL {p} [読めない] {e}")
            continue
        f, n = check_text(text, p)
        fails += f
        total += n
    for f in fails:
        print(f)
    print(f"RESULT: {'PASS' if not fails else 'FAIL'} migrate-gate {' '.join(paths)} (文 {total}、FAIL {len(fails)})")
    return 0 if not fails else 1


GOOD = [
    ("段 1（列と表を足す）", """SET lock_timeout = '2s';
ALTER TABLE orders ADD COLUMN cancelled_at timestamptz, ADD COLUMN cancelled_by text, ADD COLUMN changed_at timestamptz;
CREATE TABLE sessions (token_sha256 text PRIMARY KEY, user_id text NOT NULL REFERENCES users(id), expires_at timestamptz NOT NULL);
CREATE INDEX sessions_user ON sessions (user_id);
CREATE TABLE idempotency (shop_id text NOT NULL, user_id text NOT NULL, key text NOT NULL, request_sha256 text NOT NULL,
 status int NOT NULL DEFAULT 0, body text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (shop_id, user_id, key));
"""),
    ("段 3（索引）", """SET statement_timeout = 0;
CREATE INDEX CONCURRENTLY orders_today ON orders (shop_id, status, ship_due, ordered_at, id);
CREATE UNIQUE INDEX CONCURRENTLY orders_parcel ON orders (parcel);
"""),
    ("段 4 と 4v（外部キーと確かめ）", """-- 外部キーは NOT VALID で足し、別の段で確かめる
SET lock_timeout = '2s';
ALTER TABLE orders ADD CONSTRAINT orders_cancelled_by_fk FOREIGN KEY (cancelled_by) REFERENCES users(id) NOT VALID;
ALTER TABLE orders ADD CONSTRAINT orders_flag_ck CHECK (fragile IN (0, 1)) NOT VALID;
ALTER TABLE orders VALIDATE CONSTRAINT orders_cancelled_by_fk;
"""),
]
BAD = [
    ("行を写す", "INSERT INTO customers SELECT id + 1000000, 'A', name, postal, address FROM customers WHERE shop_id <> 'A';", "一覧の外の文"),
    ("note に写す", "UPDATE orders SET note = 'x' WHERE shop_id = 'A';", "一覧の外の文"),
    ("トリガーの関数を書き換える", "CREATE OR REPLACE FUNCTION orders_before_write() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER AS $$ BEGIN RETURN NEW; END $$;", "ドルの引用"),
    ("規則", "CREATE RULE r AS ON UPDATE TO orders DO ALSO NOTHING;", "一覧の外の文"),
    ("rds_iam への付与", "GRANT UPDATE (shop_id) ON users TO rds_iam;", "一覧の外の文"),
    ("スキーマで隠す", "CREATE SCHEMA orders_api;", "一覧の外の文"),
    ("写しの表", "CREATE TABLE cust_copy AS SELECT * FROM customers;", "一覧の外の語"),
    ("既定値に長い定数（全店の氏名を組み立てた値）", "ALTER TABLE orders ADD COLUMN memo text DEFAULT 'Customer-B-fake/addr B';", "既定値"),
    ("既定値の関数で写す", "ALTER TABLE orders ADD COLUMN stash text DEFAULT query_to_xml('select 1', true, false, '');", "既定値"),
    ("索引の式で関数を呼ぶ", "CREATE INDEX x ON orders ((query_to_xml('select 1', true, false, '')));", "関数の呼び出し"),
    ("守りのトリガーを止める", "ALTER TABLE orders DISABLE TRIGGER guard_no_migrate_dml;", "一覧の外の語"),
    ("型を変えて書き直す", "ALTER TABLE orders ALTER COLUMN note TYPE text USING note || shop_id;", "一覧の外の語"),
    ("psql の命令", "\\! curl https://example.invalid\nCREATE INDEX a ON orders (id);", "psql の命令"),
    ("search_path を変える", "SET search_path = orders_api, public;", "一覧の外の文"),
    ("役割を変える", "SET ROLE orders_api;", "一覧の外の文"),
    ("DO の塊", "DO $x$ BEGIN PERFORM 1; END $x$;", "ドルの引用"),
    ("列を消す", "ALTER TABLE orders DROP COLUMN note;", "一覧の外の語"),
    ("行の制限を外す", "ALTER TABLE customers DISABLE ROW LEVEL SECURITY;", "一覧の外の語"),
    ("持ち主を変える", "ALTER TABLE customers OWNER TO orders_api;", "一覧の外の語"),
    ("COPY で読む", "COPY customers TO STDOUT;", "一覧の外の文"),
    ("引用した名前で語を隠す", 'CREATE TABLE "select" (a text);', "書き方"),
]


def selftest():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="migrate-gate-"))
    results = []
    try:
        for name, sql in GOOD:
            fails, _ = check_text(sql, name)
            results.append((not fails, f"正例が落ちた {name}: {fails[:2]}"))
        for name, sql, rule in BAD:
            fails, _ = check_text(sql, name)
            results.append((any(f"[{rule}]" in f for f in fails), f"負例が「{rule}」で落ちない {name}: {fails[:2]}"))
        f = tmp / "a.sql"
        f.write_text(GOOD[0][1], encoding="utf-8")
        results.append((report([str(f)]) == 0, "file の正例が通らない"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = True
    for passed, msg in results:
        if not passed:
            ok = False
            print(f"FAIL selftest migrate-gate: {msg}")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} migrate-gate --selftest ({len(results)} 例)")
    return 0 if ok else 1


def main(argv):
    if argv[:1] == ["--selftest"]:
        return selftest()
    if not argv:
        print(__doc__)
        return 2
    return report(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
