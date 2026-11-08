#!/usr/bin/env python3
"""db_grants_check — データベースの権限の正本（バックエンドの db-access.json）と、利用者づくりの SQL（db/roles.sql）の突き合わせ。

使い方: db_grants_check.py <db-access.json> <roles.sql>   /   db_grants_check.py --selftest
見るもの:
  1. 表ごとの権限。select は表の SELECT、insert と update は列の単位の INSERT と UPDATE（列の集合が一致）、delete は表の DELETE。
     正本に無い表への権限、ON ALL TABLES のような一括の権限、列を書かない INSERT と UPDATE は、一覧の外として落とす。
  2. 行の制限。店は、API が自由に書ける値（app.shop_id）では決めない。DB の側で、要求の鍵のハッシュ（app.key_hash）から引く。
     token の表（sessions、users）は RLS を有効にし、鍵のハッシュが合う行だけを見せる（直に app.key_hash で絞るか、別の token の表を通す）。
       店では絞らない（店を決める前に引くため）。見たことのない鍵のハッシュは読めないので、他の店の鍵を書いても 0 行になる。
       正本の via（例: orders.staff_id）にある道は、方針がその表と列を通して見せること（無いと担当の名前の結合が 0 行になる）。
     shop_id の表は RLS を有効にし、shop_id の列を、token の表から引いた店と比べる方針があること。
       店を引くのは、方針の中の副問い合わせか、同じ SQL で作る関数（token の表を app.key_hash で絞る本文）のどちらでもよい。
     parent の表は RLS を有効にし、親の表（of）を key の列で結ぶ方針があること（親の行の制限に従う）。none の表は権限が 0。
     all の表（店のデータを持たない表。例: 移行の段の 1 行）は、店の制限を掛けず、書く権限を持たせない（select だけ）。
     app.shop_id と、全店を見る値（shop_scope）に触れる方針は落とす。
  3. SQL の最後の検査が使う一覧（want、want_table、want_cols、want_rls）が、正本と同じであること。
  4. 実行中の文を見せる見方（pg_stat_activity）を PUBLIC から取り上げていること。同じ利用者の別の接続の文から、鍵のハッシュを拾わせない。
  5. DB の中の正本との突き合わせが、移行の後と毎時に回る形であること。関数の EXECUTE を PUBLIC から外し（今ある関数と、これから作る関数）、
     手続き guard.check_all が public の表の一覧・関数（SECURITY DEFINER と既定の PUBLIC の EXECUTE）・規則（pg_rewrite）・
     orders_api の実際の列の権限・方針と関数の指紋を比べ、pg_cron が毎時それを呼ぶこと。指紋は取る所と比べる所で同じ関数
     （search_path を固定した guard.current_fingerprints）を使うこと。移行の DDL を許す型に絞る事象のトリガーと、移行の行の書き込みを
     止める文のトリガーと、移行の表の書き直しを止める事象のトリガー（table_rewrite）があり、orders_api の search_path を public に固定していること。
     大きなオブジェクトを作る関数の EXECUTE を PUBLIC から外し、突き合わせがその件数と、列の単位でしか権限を持たない書き手を数えること。
  6. 正本の otherRoles（旧い書き手）と同じ一覧 other_roles があり、明示の CONNECT と USAGE と、全行の方針（FOR ALL の USING (true)）を
     付けていること。方針が無い書き手は、RLS で読みが 0 行、UPDATE が黙って 0 行になる。
  7. 正本の sinceOverlap に書き手の取引の上限（writerTransactionLimitS）が無ければ、書き手に DB の側の上限を掛けていないこと。
     正本が orders_write_horizon を求めるなら、SECURITY DEFINER で時刻だけを返し、書き手（移行の外）を全部見て、orders_api に渡すこと。
出力: FAIL <場所> [<決まり>] <内容>、最後に RESULT: PASS|FAIL db-grants-check <対象> (表 N、FAIL N)。1 件でも FAIL なら終了コード 1。
"""
import json
import pathlib
import re
import shutil
import sys
import tempfile


def split_top(text):
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_sql(text, role):
    """GRANT・RLS・方針・検査の一覧を読む。EXECUTE '…' の中の文も読む（'' は ' に戻す）。"""
    body = "\n".join(re.sub(r"--.*$", "", line) for line in text.split("\n")).replace("''", "'")
    grants, bulk = {}, []
    for m in re.finditer(r"\bGRANT\s+(.+?)\s+ON\s+(ALL\s+\w+\s+IN\s+SCHEMA\s+\w+|(?:TABLE\s+)?(?:public\.)?\w+)\s+TO\s+([\w,\s]+?)(?=['\";])", body, re.I):
        privs, target, to = m.group(1), m.group(2), [x.strip() for x in m.group(3).split(",")]
        if role not in to:
            continue
        if re.match(r"ALL\s", target, re.I):
            bulk.append(m.group(0))
            continue
        if re.match(r"(SCHEMA|DATABASE)\b", privs.split()[-1], re.I):
            continue
        tbl = re.sub(r"^(TABLE\s+)?(public\.)?", "", target, flags=re.I)
        g = grants.setdefault(tbl, {"table": set(), "cols": {}})
        for item in split_top(privs):
            mm = re.match(r"(\w+)\s*(?:\((.*)\))?$", item.strip())
            if not mm:
                continue
            priv = mm.group(1).upper()
            if mm.group(2) is None:
                g["table"].add(priv)
            else:
                g["cols"].setdefault(priv, set()).update(c.strip().strip('"') for c in mm.group(2).split(","))
    rls = {m.group(1) for m in re.finditer(r"ALTER\s+TABLE\s+(?:public\.)?(\w+)\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY", body, re.I)}
    policies = {}
    for m in re.finditer(r"CREATE\s+POLICY\s+(\w+)\s+ON\s+(?:public\.)?(\w+)\s+(.*?)'?;", body, re.I | re.S):
        policies.setdefault(m.group(2), []).append(m.group(3))
    functions = {}
    for m in re.finditer(r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?(\w+)\s*\(.*?\$fn\$(.*?)\$fn\$", body, re.I | re.S):
        functions[m.group(1)] = m.group(2)
    arrays = {}
    for m in re.finditer(r"\b(want(?:_table|_cols|_rls)?)\s+text\[\]\s*:=\s*ARRAY\[(.*?)\]", body, re.S):
        arrays[m.group(1)] = set(re.findall(r"'([^']*)'", m.group(2)))
    return grants, bulk, rls, policies, arrays, functions


KEY_SETTING = "current_setting('app.key_hash'"


def check(json_path, sql_path):
    fails = []

    def fail(where, rule, msg):
        fails.append(f"FAIL {where} [{rule}] {msg}")

    try:
        spec = json.loads(pathlib.Path(json_path).read_text(encoding="utf-8"))
        sql = pathlib.Path(sql_path).read_text(encoding="utf-8")
    except (OSError, ValueError) as e:
        return [f"FAIL {json_path} [読めない] {e}"], 0
    role, tables = spec.get("role", "orders_api"), spec.get("tables", {})
    grants, bulk, rls, policies, arrays, functions = parse_sql(sql, role)
    if not re.search(r"REVOKE\s+SELECT\s+ON\s+pg_catalog\.pg_stat_activity\s+FROM\s+PUBLIC", sql, re.I):
        fail(sql_path, "実行中の文", "pg_stat_activity を PUBLIC から取り上げていない。同じ利用者の別の接続の文から鍵のハッシュを拾える")
    for b in bulk:
        fail(sql_path, "一覧の外", f"一括の権限「{b.strip()[:80]}」。表と列を 1 つずつ名指しする")
    want_table, want_cols, want_rls = set(), set(), set()
    token_tables = [t for t, v in tables.items() if (v.get("rows") or {}).get("by") == "token"]
    via_token = re.compile(rf"FROM\s+(?:public\.)?({'|'.join(map(re.escape, token_tables)) or '(?!)'})\b", re.I)
    # 店を引く関数: 本文が token の表を読み、鍵のハッシュで絞る関数だけ。方針がこの名前を呼べば、token の表から引いたとみなす。
    shop_fns = [n for n, b in functions.items() if via_token.search(b) and KEY_SETTING in b]

    def from_token(pol):
        return bool(via_token.search(pol)) or any(re.search(rf"\b{re.escape(n)}\s*\(", pol) for n in shop_fns)
    for tbl, t in tables.items():
        g = grants.get(tbl, {"table": set(), "cols": {}})
        if t.get("select"):
            want_table.add(f"{tbl}:SELECT")
        if t.get("delete"):
            want_table.add(f"{tbl}:DELETE")
        for priv in ("SELECT", "DELETE"):
            has, want = priv in g["table"], f"{tbl}:{priv}" in want_table
            if has != want:
                fail(f"{sql_path}:{tbl}", "表の権限", f"{priv} が正本と違う（正本 {'あり' if want else 'なし'}、SQL {'あり' if has else 'なし'}）")
        for priv in ("INSERT", "UPDATE"):
            want = set(t.get(priv.lower()) or [])
            want_cols.update(f"{tbl}:{priv}:{c}" for c in want)
            if priv in g["table"]:
                fail(f"{sql_path}:{tbl}", "列の権限", f"{priv} を表の単位で渡している。列を名指しする（正本 {sorted(want) or 'なし'}）")
            have = g["cols"].get(priv, set())
            if have != want:
                fail(f"{sql_path}:{tbl}", "列の権限", f"{priv} の列が正本と違う（足りない {sorted(want - have)}、多い {sorted(have - want)}）")
        for priv in g["table"] - {"SELECT", "DELETE", "INSERT", "UPDATE"}:
            fail(f"{sql_path}:{tbl}", "表の権限", f"正本に無い操作 {priv}")
        for priv in set(g["cols"]) - {"INSERT", "UPDATE"}:
            fail(f"{sql_path}:{tbl}", "列の権限", f"正本に無い列の操作 {priv}")
        rows = t.get("rows") or {}
        by = rows.get("by")
        pol = " ".join(policies.get(tbl, []))
        if by in ("shop_id", "parent", "token"):
            want_rls.add(tbl)
            if tbl not in rls:
                fail(f"{sql_path}:{tbl}", "行の制限", f"RLS が有効でない（正本の rows は {by}）")
            if not pol or not re.search(rf"\bTO\s+{role}\b", pol, re.I):
                fail(f"{sql_path}:{tbl}", "行の制限", f"{role} に掛かる方針が無い")
            elif by == "shop_id" and not (re.search(r"\bshop_id\b", pol) and from_token(pol)):
                fail(f"{sql_path}:{tbl}", "行の制限", "方針が shop_id の列を、鍵の表（token）から引いた店と比べていない")
            elif by == "parent":
                parent, key = rows.get("of"), rows.get("key")
                if not (re.search(rf"FROM\s+(?:public\.)?{parent}\b", pol, re.I) and re.search(rf"\b{key}\b", pol)):
                    fail(f"{sql_path}:{tbl}", "行の制限", f"方針が親の表 {parent} を {key} で結んでいない")
            elif by == "token":
                others = [t for t in token_tables if t != tbl]
                ok_key = KEY_SETTING in pol or any(re.search(rf"FROM\s+(?:public\.)?{re.escape(o)}\b", pol, re.I) for o in others)
                if not ok_key:
                    fail(f"{sql_path}:{tbl}", "行の制限", "鍵の表が、鍵のハッシュ（app.key_hash）の合う行だけを見せていない")
                if re.search(r"\bshop_id\b", pol):
                    fail(f"{sql_path}:{tbl}", "行の制限", "鍵で 1 行を引く表に店の制限を掛けている（店を決める前の引き当てが 0 行になる）")
                for via in rows.get("via") or []:
                    vt, _, vc = via.partition(".")
                    if not (re.search(rf"FROM\s+(?:public\.)?{re.escape(vt)}\b", pol, re.I) and re.search(rf"\b{re.escape(vc)}\b", pol)):
                        fail(f"{sql_path}:{tbl}", "行の制限", f"正本の via の道 {via} を方針が通していない（その道の結合が 0 行になる）")
        elif by == "all":
            if t.get("insert") or t.get("update") or t.get("delete"):
                fail(f"{json_path}:{tbl}", "正本の形", "rows.by が all の表に書く権限がある。店の制限の無い表は読むだけにする")
        elif by == "none":
            if g["table"] or g["cols"]:
                fail(f"{sql_path}:{tbl}", "表の権限", "正本の rows が none の表に権限がある")
        else:
            fail(f"{json_path}:{tbl}", "正本の形", f"rows.by「{by}」を知らない（shop_id・parent・token・all・none）")
    for tbl in sorted(set(grants) - set(tables)):
        fail(f"{sql_path}:{tbl}", "一覧の外", f"正本に無い表 {tbl} に権限がある")
    for tbl, ps in policies.items():
        if any("current_setting('app.shop_id'" in p for p in ps):
            fail(f"{sql_path}:{tbl}", "行の制限", "方針が API の書ける値 app.shop_id で店を決めている。店は鍵のハッシュから DB の側で引く")
        if any("shop_scope" in p for p in ps):
            fail(f"{sql_path}:{tbl}", "行の制限", "方針が全店を見る値（shop_scope）に触れている。正本に全店を見る役割は無い")
    for name, want in (("want", set(tables)), ("want_table", want_table), ("want_cols", want_cols), ("want_rls", want_rls)):
        have = arrays.get(name)
        if have is None:
            fail(sql_path, "最後の検査", f"最後の検査の一覧 {name} が無い")
        elif have != want:
            fail(sql_path, "最後の検査", f"一覧 {name} が正本と違う（足りない {sorted(want - have)}、多い {sorted(have - want)}）")
    check_guard(spec, sql, json_path, sql_path, fail)
    return fails, len(tables)


GUARD_RULES = [
    (r"REVOKE\s+EXECUTE\s+ON\s+ALL\s+FUNCTIONS\s+IN\s+SCHEMA\s+public\s+FROM\s+PUBLIC", "関数の権限",
     "public の関数から PUBLIC の EXECUTE を外していない（関数の EXECUTE は既定で PUBLIC に付く）"),
    (r"ALTER\s+DEFAULT\s+PRIVILEGES\s+FOR\s+ROLE\s+\w+\s+REVOKE\s+EXECUTE\s+ON\s+FUNCTIONS\s+FROM\s+PUBLIC", "関数の権限",
     "これから作る関数の PUBLIC の EXECUTE を外していない"),
    (r"CREATE\s+OR\s+REPLACE\s+PROCEDURE\s+guard\.check_all\s*\(", "突き合わせ", "突き合わせの手続き guard.check_all が無い（移行の後と毎時に回す）"),
    (r"cron\.schedule\s*\([^;]*CALL\s+guard\.check_all\(\)", "突き合わせ", "毎時の突き合わせ（cron.schedule で guard.check_all）が無い"),
    (r"\bprosecdef\b", "突き合わせ", "突き合わせが SECURITY DEFINER の関数を数えていない"),
    (r"acldefault\('f'", "突き合わせ", "突き合わせが関数の既定の PUBLIC の EXECUTE を数えていない"),
    (r"guard\.fingerprints", "突き合わせ", "突き合わせが方針と関数の指紋を比べていない"),
    (r"relkind\s+IN\s+\('r'", "突き合わせ", "突き合わせが public の表の一覧（写しの表）を数えていない"),
    (r"INSERT\s+INTO\s+guard\.fingerprints[^;]*guard\.current_fingerprints\(\)", "突き合わせ",
     "指紋を、比べる所と同じ関数（search_path を固定した guard.current_fingerprints）で取っていない。方針の文字は search_path で変わる"),
    (r"guard\.current_fingerprints\(\)\s+\w+\s+FULL\s+JOIN\s+guard\.fingerprints", "突き合わせ",
     "突き合わせが、取ったときと同じ関数（guard.current_fingerprints）で指紋を比べていない"),
    (r"\bpg_rewrite\b", "突き合わせ", "突き合わせが規則（pg_rewrite）を数えていない。規則は持ち主の権限で動き RLS を受けない"),
    (r"has_column_privilege\(\s*'orders_api'", "突き合わせ",
     "突き合わせが orders_api の実際の列の権限（一員の役割を通した付与を含む）を比べていない"),
    (r"CREATE\s+EVENT\s+TRIGGER\s+\w+\s+ON\s+ddl_command_start", "移行の一覧", "移行の DDL を許す型に絞る事象のトリガーが無い"),
    (r"FOR\s+EACH\s+STATEMENT\s+EXECUTE\s+FUNCTION\s+guard\.no_migrate_dml", "移行の一覧", "移行の行の書き込みを止める文のトリガーが無い"),
    (r"ALTER\s+ROLE\s+orders_api\s+SET\s+search_path\s*=\s*public\b", "スキーマ",
     "orders_api の search_path を public に固定していない（同じ名のスキーマで表を隠せる）"),
    (r"CREATE\s+EVENT\s+TRIGGER\s+\w+\s+ON\s+table_rewrite", "移行の一覧",
     "移行の表の書き直し（型の付け直しの USING）を止める事象のトリガー（table_rewrite）が無い。行の値を DML なしで書き換えられる"),
    (r"REVOKE\s+EXECUTE\s+ON\s+FUNCTION\s[^;]*\bpg_catalog\.lo_from_bytea\b[^;]*FROM\s+PUBLIC", "表の外の置き場",
     "大きなオブジェクトを作る関数（lo_from_bytea など）の EXECUTE を PUBLIC から外していない。表の外に写しを置ける"),
    (r"\bpg_largeobject_metadata\b", "表の外の置き場", "突き合わせが大きなオブジェクトの件数を数えていない"),
    (r"has_any_column_privilege\(", "書き手", "突き合わせが、列の単位でしか権限を持たない書き手を数えていない"),
    (r"\bpg_inherits\b", "移行の一覧",
     "突き合わせが表の継承と区分け（pg_inherits）を数えていない。子の表を親の表から読ませると、子の表の行の制限が掛からない"),
    (r"\bpg_attrdef\b[^;]*\bpg_constraint\b|\bpg_constraint\b[^;]*\bpg_attrdef\b", "移行の一覧",
     "突き合わせが列（名前・型・既定値）と制約を指紋に入れていない。定数の既定値と制約の式で、他の店の行を写せる"),
    (r"REVOKE\s+USAGE\s+ON\s+LANGUAGE\s+plpgsql\s+FROM\s+PUBLIC", "移行の一覧",
     "plpgsql の USAGE を PUBLIC から外していない。移行の接続が DO で文を組み立てられる"),
]
LIMIT_SETTINGS = r"(statement_timeout|transaction_timeout|idle_in_transaction_session_timeout)"


def check_guard(spec, sql, json_path, sql_path, fail):
    """突き合わせの形（5）、旧い書き手（6）、取引の上限と書き手の始まり（7）。"""
    body = "\n".join(re.sub(r"--.*$", "", line) for line in sql.split("\n")).replace("''", "'")
    for pat, rule, msg in GUARD_RULES:
        if not re.search(pat, body, re.I | re.S):
            fail(sql_path, rule, msg)
    others = {k for k, v in (spec.get("otherRoles") or {}).items() if (v or {}).get("rows") == "all"}
    lists = [set(re.findall(r"'([^']*)'", m.group(1))) for m in re.finditer(r"\bother_roles\s+text\[\]\s*:=\s*ARRAY\[(.*?)\]", body, re.S)]
    if others or lists:
        if not lists:
            fail(sql_path, "書き手", f"旧い書き手の一覧 other_roles が無い（正本の otherRoles {sorted(others)}）")
        for have in lists:
            if have != others:
                fail(sql_path, "書き手", f"一覧 other_roles が正本の otherRoles と違う（足りない {sorted(others - have)}、多い {sorted(have - others)}）")
        if not re.search(r"CREATE\s+POLICY\s+other_roles_all\b[^;]*FOR\s+ALL[^;]*USING\s*\(true\)", body, re.I):
            fail(sql_path, "書き手", "旧い書き手の全行の方針（other_roles_all、FOR ALL の USING (true)）が無い")
        for what in (r"CONNECT\s+ON\s+DATABASE\s+\w+", r"USAGE\s+ON\s+SCHEMA\s+public"):
            if not re.search(rf"GRANT\s+{what}\s+TO\s+%I", body, re.I):
                fail(sql_path, "書き手", f"旧い書き手に明示の {what.split(chr(92))[0]} を付けていない")
    so = spec.get("sinceOverlap") or {}
    limited = re.findall(rf"ALTER\s+ROLE\s+(\S+)\s+SET\s+{LIMIT_SETTINGS}", body, re.I)
    if so and "writerTransactionLimitS" not in so:
        for r, k in limited:
            fail(sql_path, "取引の上限", f"正本は書き手に DB の側の取引の上限を掛けない（{r} の {k}）")
    if "orders_write_horizon" in str(so.get("horizon", "")):
        m = re.search(r"FUNCTION\s+(?:public\.)?orders_write_horizon\s*\(\)(.*?)\$hz\$(.*?)\$hz\$", body, re.I | re.S)
        writers = [w for w in (so.get("writers") or {}) if w != "migration"]
        if not m:
            fail(sql_path, "書き手の始まり", "正本の求める orders_write_horizon が無い")
        else:
            if "SECURITY DEFINER" not in m.group(1).upper():
                fail(sql_path, "書き手の始まり", "orders_write_horizon が SECURITY DEFINER でない（orders_api は pg_stat_activity を読めない）")
            if re.search(r"\bquery\b", m.group(2)):
                fail(sql_path, "書き手の始まり", "orders_write_horizon が文（query）を読む。時刻だけを返す")
            for w in writers:
                if f"'{w}'" not in m.group(2):
                    fail(sql_path, "書き手の始まり", f"orders_write_horizon が書き手 {w} を見ていない")
        if not re.search(r"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+(?:public\.)?orders_write_horizon\(\)\s+TO\s+orders_api", body, re.I):
            fail(sql_path, "書き手の始まり", "orders_write_horizon の EXECUTE を orders_api に渡していない")
        # 見方の中の関数の EXECUTE は呼ぶ側（持ち主 orders_horizon）で確かめられる。PUBLIC から外したら、持ち主へ明示で付ける。
        if re.search(r"REVOKE\s+EXECUTE\s+ON\s+FUNCTION\s+pg_catalog\.pg_stat_get_activity\(integer\)\s+FROM\s+PUBLIC", body, re.I) and not re.search(
                r"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+pg_catalog\.pg_stat_get_activity\(integer\)\s+TO\s+orders_horizon", body, re.I):
            fail(sql_path, "書き手の始まり", "pg_stat_get_activity を PUBLIC から外したのに orders_horizon に付けていない（一覧の要求が全部誤りになる）")


def report(json_path, sql_path):
    fails, n = check(json_path, sql_path)
    for f in fails:
        print(f)
    print(f"RESULT: {'PASS' if not fails else 'FAIL'} db-grants-check {sql_path} (表 {n}、FAIL {len(fails)})")
    return 0 if not fails else 1


GOOD_JSON = {
    "role": "orders_api",
    "tables": {
        "orders": {"select": True, "insert": [], "update": ["status"], "delete": False, "rows": {"by": "shop_id"}},
        "order_events": {"select": True, "insert": ["order_id", "kind"], "update": [], "delete": False,
                         "rows": {"by": "parent", "of": "orders", "key": "order_id"}},
        "sessions": {"select": True, "insert": [], "update": [], "delete": False, "rows": {"by": "token"}},
        "users": {"select": True, "insert": [], "update": [], "delete": False, "rows": {"by": "token"}},
        "shops": {"select": False, "insert": [], "update": [], "delete": False, "rows": {"by": "none"}},
    },
}
GOOD_SQL = """REVOKE SELECT ON pg_catalog.pg_stat_activity FROM PUBLIC;
DO $$
DECLARE
  want text[] := ARRAY['orders', 'order_events', 'sessions', 'users', 'shops'];
  want_table text[] := ARRAY['orders:SELECT', 'order_events:SELECT', 'sessions:SELECT', 'users:SELECT'];
  want_cols text[] := ARRAY['orders:UPDATE:status', 'order_events:INSERT:order_id', 'order_events:INSERT:kind'];
  want_rls text[] := ARRAY['orders', 'order_events', 'sessions', 'users'];
BEGIN
  EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM orders_api';
  EXECUTE 'GRANT SELECT ON public.orders TO orders_api';
  EXECUTE 'GRANT UPDATE (status) ON public.orders TO orders_api';
  EXECUTE 'GRANT SELECT ON public.order_events TO orders_api';
  EXECUTE 'GRANT INSERT (order_id, kind) ON public.order_events TO orders_api';
  EXECUTE 'GRANT SELECT ON public.sessions TO orders_api';
  EXECUTE 'GRANT SELECT ON public.users TO orders_api';
  EXECUTE 'ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY';
  EXECUTE 'ALTER TABLE public.order_events ENABLE ROW LEVEL SECURITY';
  EXECUTE 'ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY';
  EXECUTE 'ALTER TABLE public.users ENABLE ROW LEVEL SECURITY';
  EXECUTE 'CREATE POLICY key_only ON public.sessions FOR ALL TO orders_api USING (token_sha256 = current_setting(''app.key_hash'', true))';
  EXECUTE 'CREATE POLICY key_only ON public.users FOR ALL TO orders_api USING (EXISTS (SELECT 1 FROM public.sessions s WHERE s.user_id = users.id))';
  EXECUTE 'CREATE POLICY shop_isolation ON public.orders FOR ALL TO orders_api USING (shop_id::text = (SELECT u.shop_id::text FROM public.sessions s JOIN public.users u ON u.id = s.user_id))';
  EXECUTE 'CREATE POLICY shop_isolation ON public.order_events FOR ALL TO orders_api USING (EXISTS (SELECT 1 FROM public.orders p WHERE p.id = order_events.order_id))';
END
$$;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE orders_migrate REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
CREATE OR REPLACE PROCEDURE guard.check_all() LANGUAGE plpgsql AS $chk$ BEGIN PERFORM 1 FROM pg_proc WHERE prosecdef; PERFORM acldefault('f', 10);
  PERFORM 1 FROM guard.fingerprints; PERFORM 1 FROM pg_class WHERE relkind IN ('r', 'p'); END $chk$;
SELECT cron.schedule('g', '7 * * * *', 'CALL guard.check_all()');
ALTER ROLE orders_api SET search_path = public;
CREATE EVENT TRIGGER g1 ON ddl_command_start EXECUTE FUNCTION guard.migrate_ddl_gate();
DO $$ BEGIN EXECUTE 'CREATE TRIGGER g BEFORE INSERT ON public.orders FOR EACH STATEMENT EXECUTE FUNCTION guard.no_migrate_dml()';
  PERFORM 1 FROM pg_rewrite; PERFORM has_column_privilege('orders_api', 1, 1, 'SELECT');
  PERFORM count(*) FROM guard.current_fingerprints() cur FULL JOIN guard.fingerprints f USING (kind, name);
  INSERT INTO guard.fingerprints (kind, name, fp) SELECT f.kind, f.name, f.fp FROM guard.current_fingerprints() f; END $$;
CREATE EVENT TRIGGER g2 ON table_rewrite EXECUTE FUNCTION guard.migrate_no_rewrite();
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_from_bytea(oid, bytea) FROM PUBLIC;
DO $$ BEGIN PERFORM count(*) FROM pg_largeobject_metadata; PERFORM has_any_column_privilege(10, 1, 'UPDATE'); END $$;
DO $$ BEGIN PERFORM count(*) FROM pg_inherits; PERFORM count(*) FROM pg_attrdef d, pg_constraint k; END $$;
REVOKE USAGE ON LANGUAGE plpgsql FROM PUBLIC;
"""
OTHER_SQL = """DO $$
DECLARE
  other_roles text[] := ARRAY['legacy_api'];
  w text;
BEGIN
  FOREACH w IN ARRAY other_roles LOOP
    EXECUTE format('GRANT CONNECT ON DATABASE orders TO %I', w);
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', w);
    EXECUTE format('CREATE POLICY other_roles_all ON public.orders AS PERMISSIVE FOR ALL TO %I USING (true) WITH CHECK (true)', w);
  END LOOP;
END
$$;
"""
HORIZON_SQL = """CREATE OR REPLACE FUNCTION public.orders_write_horizon() RETURNS timestamptz LANGUAGE sql STABLE SECURITY DEFINER AS $hz$
  SELECT min(a.xact_start) FROM pg_catalog.pg_stat_activity a WHERE a.usename IN ('orders_api', 'legacy_api') AND a.backend_xid IS NOT NULL $hz$;
GRANT EXECUTE ON FUNCTION public.orders_write_horizon() TO orders_api;
REVOKE EXECUTE ON FUNCTION pg_catalog.pg_stat_get_activity(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_stat_get_activity(integer) TO orders_horizon;
"""


def selftest():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="db-grants-"))
    results = []
    try:
        def run_case(name, sql, spec=GOOD_JSON, want_ok=False, want_rule=""):
            j, q = tmp / "a.json", tmp / "a.sql"
            j.write_text(json.dumps(spec), encoding="utf-8")
            q.write_text(sql, encoding="utf-8")
            fails, _ = check(str(j), str(q))
            ok = (not fails) if want_ok else (bool(fails) and any(f"[{want_rule}]" in f for f in fails))
            results.append((ok, f"{name}: {fails[:3]}"))

        run_case("正例が通らない", GOOD_SQL, want_ok=True)
        run_case("一括の権限が落ちない", GOOD_SQL.replace("'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM orders_api'",
                 "'GRANT SELECT ON ALL TABLES IN SCHEMA public TO orders_api'"), want_rule="一覧の外")
        run_case("列の足りない UPDATE が落ちない", GOOD_SQL, spec={**GOOD_JSON, "tables": {**GOOD_JSON["tables"], "orders": {
            **GOOD_JSON["tables"]["orders"], "update": ["status", "shipped_at"]}}}, want_rule="列の権限")
        run_case("表の単位の INSERT が落ちない", GOOD_SQL.replace("GRANT INSERT (order_id, kind) ON", "GRANT INSERT ON"), want_rule="列の権限")
        run_case("正本に無い表の権限が落ちない", GOOD_SQL.replace("END\n$$;", "  EXECUTE 'GRANT SELECT ON public.customers TO orders_api';\nEND\n$$;"),
                 want_rule="一覧の外")
        run_case("none の表の権限が落ちない", GOOD_SQL.replace("END\n$$;", "  EXECUTE 'GRANT SELECT ON public.shops TO orders_api';\nEND\n$$;"),
                 want_rule="表の権限")
        run_case("店の列の RLS の欠けが落ちない", GOOD_SQL.replace("  EXECUTE 'ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY';\n", ""),
                 want_rule="行の制限")
        run_case("親の表を通さない方針が落ちない", GOOD_SQL.replace("FROM public.orders p WHERE p.id = order_events.order_id", "FROM public.shops s"),
                 want_rule="行の制限")
        run_case("全店を見る値が落ちない", GOOD_SQL.replace("ON u.id = s.user_id))'",
                 "ON u.id = s.user_id) OR current_setting(''app.shop_scope'', true) = ''all'')'"), want_rule="行の制限")
        run_case("API の書ける店の値（app.shop_id）で絞る方針が落ちない", GOOD_SQL.replace(
                 "(SELECT u.shop_id::text FROM public.sessions s JOIN public.users u ON u.id = s.user_id)", "current_setting(''app.shop_id'', true)"),
                 want_rule="行の制限")
        run_case("鍵の表への店の制限が落ちない", GOOD_SQL.replace("s.user_id = users.id))'", "s.user_id = users.id) AND users.shop_id IS NOT NULL)'"),
                 want_rule="行の制限")
        run_case("鍵の表の RLS の欠けが落ちない", GOOD_SQL.replace("  EXECUTE 'ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY';\n", ""),
                 want_rule="行の制限")
        run_case("鍵のハッシュで絞らない鍵の表が落ちない", GOOD_SQL.replace("USING (token_sha256 = current_setting(''app.key_hash'', true))", "USING (true)"),
                 want_rule="行の制限")
        run_case("最後の検査の一覧の食い違いが落ちない", GOOD_SQL.replace("'orders:UPDATE:status', ", ""), want_rule="最後の検査")
        run_case("pg_stat_activity を取り上げない SQL が落ちない", GOOD_SQL.replace("REVOKE SELECT ON pg_catalog.pg_stat_activity FROM PUBLIC;\n", ""),
                 want_rule="実行中の文")
        via_json = {**GOOD_JSON, "tables": {**GOOD_JSON["tables"], "users": {**GOOD_JSON["tables"]["users"],
                    "rows": {"by": "token", "via": ["sessions.user_id", "orders.staff_id"]}}}}
        run_case("正本の via の道を通さない users の方針が落ちない", GOOD_SQL, spec=via_json, want_rule="行の制限")
        run_case("via の道を通す users の方針と、店を引く関数が通らない", GOOD_SQL.replace(
                 "WHERE s.user_id = users.id))'", "WHERE s.user_id = users.id) OR EXISTS (SELECT 1 FROM public.orders o WHERE o.staff_id = users.id))'").replace(
                 "(SELECT u.shop_id::text FROM public.sessions s JOIN public.users u ON u.id = s.user_id)", "public.key_shop()").replace(
                 "BEGIN\n", "BEGIN\n  EXECUTE 'CREATE OR REPLACE FUNCTION public.key_shop() RETURNS text LANGUAGE sql STABLE SECURITY DEFINER AS $fn$ "
                 "SELECT u.shop_id::text FROM public.sessions s JOIN public.users u ON u.id = s.user_id WHERE s.token_sha256 = current_setting(''app.key_hash'', true) $fn$';\n", 1),
                 spec=via_json, want_ok=True)
        run_case("鍵で絞らない関数で店を引く方針が落ちない", GOOD_SQL.replace(
                 "(SELECT u.shop_id::text FROM public.sessions s JOIN public.users u ON u.id = s.user_id)", "public.key_shop()").replace(
                 "BEGIN\n", "BEGIN\n  EXECUTE 'CREATE OR REPLACE FUNCTION public.key_shop() RETURNS text LANGUAGE sql AS $fn$ SELECT max(shop_id::text) FROM public.shops $fn$';\n", 1),
                 want_rule="行の制限")
        all_json = {**GOOD_JSON, "tables": {**GOOD_JSON["tables"], "stage": {"select": True, "insert": [], "update": ["n"], "delete": False,
                    "rows": {"by": "all"}}}}
        run_case("店の制限の無い表（all）に書く権限がある正本が落ちない", GOOD_SQL, spec=all_json, want_rule="正本の形")
        run_case("DELETE の多すぎが落ちない", GOOD_SQL.replace("END\n$$;", "  EXECUTE 'GRANT DELETE ON public.orders TO orders_api';\nEND\n$$;"),
                 want_rule="表の権限")
        run_case("関数の PUBLIC の EXECUTE を外さない SQL が落ちない", GOOD_SQL.replace("REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;\n", ""),
                 want_rule="関数の権限")
        run_case("突き合わせの手続きが無い SQL が落ちない", GOOD_SQL.replace("CREATE OR REPLACE PROCEDURE guard.check_all()", "CREATE OR REPLACE PROCEDURE guard.other()"),
                 want_rule="突き合わせ")
        run_case("毎時の突き合わせが無い SQL が落ちない", GOOD_SQL.replace("SELECT cron.schedule('g', '7 * * * *', 'CALL guard.check_all()');\n", ""),
                 want_rule="突き合わせ")
        run_case("指紋を別の search_path で取る SQL が落ちない", GOOD_SQL.replace(
                 "SELECT f.kind, f.name, f.fp FROM guard.current_fingerprints() f", "SELECT 'policy', policyname, qual FROM pg_policies"),
                 want_rule="突き合わせ")
        run_case("規則を数えない突き合わせが落ちない", GOOD_SQL.replace("PERFORM 1 FROM pg_rewrite; ", ""), want_rule="突き合わせ")
        run_case("移行の行の書き込みを止めない SQL が落ちない", GOOD_SQL.replace("guard.no_migrate_dml()", "guard.other()"), want_rule="移行の一覧")
        run_case("表の書き直しを止めない SQL が落ちない", GOOD_SQL.replace("ON table_rewrite", "ON ddl_command_end"), want_rule="移行の一覧")
        run_case("大きなオブジェクトを作れる SQL が落ちない", GOOD_SQL.replace("REVOKE EXECUTE ON FUNCTION pg_catalog.lo_from_bytea(oid, bytea) FROM PUBLIC;\n", ""),
                 want_rule="表の外の置き場")
        run_case("列の権限だけの書き手を数えない SQL が落ちない", GOOD_SQL.replace("PERFORM has_any_column_privilege(10, 1, 'UPDATE'); ", ""),
                 want_rule="書き手")
        run_case("継承を数えない突き合わせが落ちない", GOOD_SQL.replace("PERFORM count(*) FROM pg_inherits; ", ""), want_rule="移行の一覧")
        run_case("既定値と制約を指紋に入れない突き合わせが落ちない", GOOD_SQL.replace("PERFORM count(*) FROM pg_attrdef d, pg_constraint k; ", ""),
                 want_rule="移行の一覧")
        run_case("DO を移行に残す SQL が落ちない", GOOD_SQL.replace("REVOKE USAGE ON LANGUAGE plpgsql FROM PUBLIC;\n", ""), want_rule="移行の一覧")
        run_case("search_path を固定しない SQL が落ちない", GOOD_SQL.replace("ALTER ROLE orders_api SET search_path = public;\n", ""),
                 want_rule="スキーマ")
        other_json = {**GOOD_JSON, "otherRoles": {"legacy_api": {"connect": True, "schemaUsage": True, "rows": "all"}},
                      "sinceOverlap": {"writers": {"orders_api": "", "legacy_api": "", "migration": ""},
                                       "horizon": "orders_write_horizon()"}}
        run_case("旧い書き手と書き手の始まりがある SQL が通らない", GOOD_SQL + OTHER_SQL + HORIZON_SQL, spec=other_json, want_ok=True)
        run_case("旧い書き手の全行の方針が無い SQL が落ちない", GOOD_SQL + HORIZON_SQL, spec=other_json, want_rule="書き手")
        run_case("書き手の始まりの関数が無い SQL が落ちない", GOOD_SQL + OTHER_SQL, spec=other_json, want_rule="書き手の始まり")
        run_case("書き手を見落とす書き手の始まりが落ちない", GOOD_SQL + OTHER_SQL + HORIZON_SQL.replace(", 'legacy_api'", ""), spec=other_json,
                 want_rule="書き手の始まり")
        run_case("書き手の始まりの持ち主から pg_stat_get_activity を取り上げたままの SQL が落ちない", GOOD_SQL + OTHER_SQL + HORIZON_SQL.replace(
                 "GRANT EXECUTE ON FUNCTION pg_catalog.pg_stat_get_activity(integer) TO orders_horizon;\n", ""), spec=other_json, want_rule="書き手の始まり")
        run_case("正本に無い取引の上限が落ちない", GOOD_SQL + OTHER_SQL + HORIZON_SQL + "ALTER ROLE legacy_api SET statement_timeout = '8s';\n",
                 spec=other_json, want_rule="取引の上限")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = True
    for passed, msg in results:
        if not passed:
            ok = False
            print(f"FAIL selftest db-grants-check: {msg}")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} db-grants-check --selftest ({len(results)} 例)")
    return 0 if ok else 1


def main(argv):
    if argv[:1] == ["--selftest"]:
        return selftest()
    if len(argv) != 2:
        print(__doc__)
        return 2
    return report(argv[0], argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
