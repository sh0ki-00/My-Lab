#!/usr/bin/env python3
"""backend_check — バックエンドの成果物と実装の検査。標準の python3 だけで動く。

使い方: backend_check.py contract <契約.json>                 1 版の契約の決まり（エラーの 4 点、冪等キー、認可、一覧の起点の送り）
        backend_check.py contract <旧版.json> <新版.json>      2 版の比較で、契約を壊す変更を落とす
        backend_check.py plan <設計と実装計画.md>              計画の節と表（契約、認可、冪等、エラー、移行と版と段の表、問い合わせ、p99、観測、流出経路、テスト、段階、未確定）
        backend_check.py queries [--app <module.py>] [--plan <計画.md> | --budget-ms <ms>] [--sizes 24,400] [--requests 200]
                                                              件数の違うデータで API を動かし、1 要求の SQL の数が件数に比例しないことと p99 を確かめる
        backend_check.py <種類> --selftest
出力: FAIL <場所> [<決まり>] <内容>、MEASURE <実測>、最後に RESULT: PASS|FAIL <検査名> <対象> (FAIL n)。1 件でも FAIL なら終了コード 1。
"""
import contextlib
import copy
import http.client
import importlib.util
import io
import json
import math
import pathlib
import re
import sys
import tempfile
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
SKILL = HERE.parent
ROOT = SKILL.parent.parent
EX = SKILL / "examples"
FIX = SKILL / "evals" / "fixtures"
CONTRACT = EX / "openapi-order-list.json"
CONTRACT_V2 = EX / "openapi-order-list-v2-breaking.json"
PLAN = EX / "backend-plan-order-list.md"
APP = ROOT / "samples" / "api" / "orders_api.py"
N1_APP = FIX / "n1_orders_api.py"
NAMES = {"contract": "contract-check", "plan": "backend-plan-check", "queries": "query-count-check"}
WRITE = ("post", "put", "patch", "delete")
METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
ERROR_FIELDS = {"category", "cause", "action", "traceId"}
EXITS = ["公開設定", "権限の持たせすぎ", "ログへの混入", "他人の ID での閲覧", "依存部品", "放置された複製"]


class Report:
    def __init__(self, check, name):
        self.check, self.name, self.items, self.notes = check, name, [], []

    def fail(self, where, rule, detail):
        self.items.append((where, rule, detail))

    def note(self, text):
        self.notes.append(text)

    def rules(self):
        return {x[1] for x in self.items}

    def show(self):
        for n in self.notes:
            print(f"MEASURE {n}")
        for where, rule, detail in self.items:
            print(f"FAIL {self.name}{':' + str(where) if where else ''} [{rule}] {detail}")
        print(f"RESULT: {'PASS' if not self.items else 'FAIL'} {self.check} {self.name} (FAIL {len(self.items)})")
        return not self.items


# ---- 契約（OpenAPI 3.1 の JSON）
def resolve(doc, s, depth=0):
    while isinstance(s, dict) and "$ref" in s and depth < 20:
        ref = s["$ref"]
        if not ref.startswith("#/"):
            return {}
        node = doc
        for part in ref[2:].split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        s, depth = node, depth + 1
    return s if isinstance(s, dict) else {}


def types(s):
    t = s.get("type")
    return tuple(sorted(t)) if isinstance(t, list) else (t,) if t else ()


def ops(doc):
    out = {}
    for path, item in (doc.get("paths") or {}).items():
        for m, op in (item or {}).items():
            if m in METHODS and isinstance(op, dict):
                out[(m, path)] = (op, [resolve(doc, p) for p in (item.get("parameters") or []) + (op.get("parameters") or [])])
    return out


def json_schema(doc, holder):
    c = (holder or {}).get("content") or {}
    media = c.get("application/json") or next(iter(c.values()), {})
    return resolve(doc, (media or {}).get("schema") or {})


def has_error_fields(doc, s, depth=0):
    s = resolve(doc, s)
    if depth > 4 or not s:
        return False
    if ERROR_FIELDS <= set(s.get("required") or []):
        return True
    return any(has_error_fields(doc, p, depth + 1) for p in (s.get("properties") or {}).values())


def check_rules(doc, r):
    schemes = (doc.get("components") or {}).get("securitySchemes") or {}
    top = doc.get("security")
    for (m, path), (op, params) in ops(doc).items():
        name = f"{m.upper()} {path}"
        sec = op.get("security", top)
        if not schemes or not sec or not any(isinstance(x, dict) and x for x in sec):
            r.fail(name, "認可", "認可の方式（securitySchemes と security）が無い。資源 1 件ごとにサーバーで判定する前提を契約に書く")
        resp = op.get("responses") or {}
        errs = [c for c in resp if re.fullmatch(r"[45]\d\d|[45]XX|default", str(c))]
        if not errs:
            r.fail(name, "エラーの 4 点", "4xx か 5xx の応答が無い")
        for c in errs:
            if not has_error_fields(doc, json_schema(doc, resolve(doc, resp[c]))):
                r.fail(name, "エラーの 4 点", f"{c} の本文に分類・原因・対処・追跡番号（category, cause, action, traceId）が揃っていない")
        if m in WRITE and not any(p.get("in") == "header" and str(p.get("name", "")).lower() == "idempotency-key" and p.get("required") for p in params):
            r.fail(name, "冪等キー", "書き込みに必須の Idempotency-Key のヘッダーが無い")
        ok = json_schema(doc, resolve(doc, resp.get("200") or resp.get("206") or {}))
        items = resolve(doc, (ok.get("properties") or {}).get("items") or {})
        if m == "get" and not path.rstrip("/").endswith("}") and "array" in types(items):  # 1 件の取得（/{id}）は一覧でない
            q = {p.get("name"): p for p in params if p.get("in") == "query"}
            if not ({"after", "cursor"} & set(q)):
                r.fail(name, "起点の送り", "一覧に起点の引数（after か cursor）が無い")
            if {"offset", "page"} & set(q):
                r.fail(name, "起点の送り", "一覧に offset か page がある。上限のない OFFSET の送りにしない")
            lim = resolve(doc, (q.get("limit") or {}).get("schema") or {})
            if "maximum" not in lim:
                r.fail(name, "起点の送り", "limit に上限（maximum）が無い")
            if "nextCursor" not in (ok.get("properties") or {}):
                r.fail(name, "起点の送り", "応答に次の起点（nextCursor）が無い")


def walk_props(doc, s, prefix, out, depth=0):
    """応答の欄を 'a.b[].c' の形で集める。値は (型, 列挙値)。"""
    s = resolve(doc, s)
    if depth > 8 or not s:
        return
    out[prefix or "(本文)"] = (types(s), s.get("enum"))
    for k, v in (s.get("properties") or {}).items():
        walk_props(doc, v, f"{prefix}.{k}" if prefix else k, out, depth + 1)
    if "items" in s:
        walk_props(doc, s["items"], f"{prefix}[]", out, depth + 1)


def body_required(doc, s, prefix="", depth=0, out=None):
    out = {} if out is None else out
    s = resolve(doc, s)
    if depth > 6 or not s:
        return out
    req = set(s.get("required") or [])
    for k, v in (s.get("properties") or {}).items():
        v2 = resolve(doc, v)
        out[f"{prefix}{k}"] = (k in req, types(v2), v2.get("enum"))
        body_required(doc, v2, f"{prefix}{k}.", depth + 1, out)
    return out


def enum_lost(old, new):
    if not old:
        return []
    if new is None:
        return []
    return [v for v in old if v not in new]


def check_diff(a, b, r):
    oa, ob = ops(a), ops(b)
    for key, (op, params) in oa.items():
        name = f"{key[0].upper()} {key[1]}"
        if key not in ob:
            r.fail(name, "操作の削除", "旧版にある操作が新版に無い。壊すなら版（/v2）を分ける")
            continue
        op2, params2 = ob[key]
        pa = {(p.get("in"), p.get("name")): p for p in params}
        pb = {(p.get("in"), p.get("name")): p for p in params2}
        for k, p in pb.items():
            if p.get("required") and not (pa.get(k) or {}).get("required"):
                r.fail(name, "必須の入力の追加", f"{k[0]} の {k[1]} が必須になった")
        for k, p in pa.items():
            if k in pb:
                sa, sb = resolve(a, p.get("schema") or {}), resolve(b, pb[k].get("schema") or {})
                if types(sa) != types(sb):
                    r.fail(name, "型の変更", f"{k[0]} の {k[1]} の型が {types(sa)} から {types(sb)} に変わった")
                for v in enum_lost(sa.get("enum"), sb.get("enum")):
                    r.fail(name, "列挙値の削除", f"{k[0]} の {k[1]} から {v!r} が消えた")
        ba = body_required(a, json_schema(a, resolve(a, op.get("requestBody") or {})))
        bb = body_required(b, json_schema(b, resolve(b, op2.get("requestBody") or {})))
        for k, (req, t, e) in bb.items():
            if req and not ba.get(k, (False,))[0]:
                r.fail(name, "必須の入力の追加", f"本文の {k} が必須になった")
            if k in ba:
                if ba[k][1] != t:
                    r.fail(name, "型の変更", f"本文の {k} の型が {ba[k][1]} から {t} に変わった")
                for v in enum_lost(ba[k][2], e):
                    r.fail(name, "列挙値の削除", f"本文の {k} から {v!r} が消えた")
        ra, rb = op.get("responses") or {}, op2.get("responses") or {}
        for code in ra:
            if code not in rb:
                r.fail(name, "状態番号の削除", f"応答の {code} が消えた")
                continue
            if not str(code).startswith("2"):
                continue
            pa_, pb_ = {}, {}
            walk_props(a, json_schema(a, resolve(a, ra[code])), "", pa_)
            walk_props(b, json_schema(b, resolve(b, rb[code])), "", pb_)
            for k, (t, e) in pa_.items():
                if k not in pb_:
                    r.fail(name, "応答の欄の削除", f"{code} の {k} が消えた")
                    continue
                if t and pb_[k][0] and t != pb_[k][0]:
                    r.fail(name, "型の変更", f"{code} の {k} の型が {t} から {pb_[k][0]} に変わった")
                for v in enum_lost(e, pb_[k][1]):
                    r.fail(name, "列挙値の削除", f"{code} の {k} から {v!r} が消えた")


def run_contract(args):
    if len(args) not in (1, 2):
        print("使い方: contract-check.sh <契約.json> [<新版.json>]")
        return 2
    docs = []
    for f in args:
        try:
            docs.append(json.loads(pathlib.Path(f).read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"FAIL {f} [読めない] {e}")
            print(f"RESULT: FAIL contract-check {f} (FAIL 1)")
            return 1
    r = Report("contract-check", " → ".join(args))
    if not str(docs[0].get("openapi", "")).startswith("3.1"):
        r.fail("", "版", "openapi が 3.1 でない")
    if len(docs) == 1:
        check_rules(docs[0], r)
    else:
        check_diff(docs[0], docs[1], r)
    return 0 if r.show() else 1


# ---- 設計と実装計画（Markdown）
def load_md(name):
    text = pathlib.Path(name).read_text(encoding="utf-8")
    lines, blocks, in_code, in_comment, lang, section = [], [], False, False, "", ""
    for i, l in enumerate(text.split("\n"), 1):
        s = l.strip()
        if in_comment:
            in_comment = "-->" not in s
            continue
        if not in_code and s.startswith("<!--"):
            in_comment = "-->" not in s[4:]
            continue
        if s.startswith("```"):
            if not in_code:
                lang = s[3:].strip()
                blocks.append({"lang": lang, "section": section, "no": i})
            in_code = not in_code
            continue
        if in_code:
            continue
        if re.match(r"^##\s", l):
            section = l.lstrip("#").strip()
        lines.append((i, l))
    return lines, blocks


def tables(lines):
    out, cur, section = [], None, ""
    for no, l in lines:
        s = l.strip()
        if s.startswith("#"):
            if s.startswith("## ") or s.startswith("# "):
                section = s.lstrip("#").strip()
            cur = None
            continue
        if not s.startswith("|"):
            cur = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cur is None:
            cur = {"section": section, "header": cells, "rows": [], "no": no}
            out.append(cur)
        elif all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        else:
            cur["rows"].append((no, cells))
    return out


def section_text(lines, key):
    idx = next((k for k, (_, l) in enumerate(lines) if re.match(r"^##\s", l) and key in l), None)
    if idx is None:
        return None
    end = next((j for j in range(idx + 1, len(lines)) if re.match(r"^##\s", lines[j][1])), len(lines))
    return "\n".join(l for _, l in lines[idx:end])


def col(t, key):
    return next((k for k, c in enumerate(t["header"]) if key in c), None)


def cell(cells, k):
    return cells[k] if k is not None and len(cells) > k else ""


PLAN_SECTIONS = ["背景", "契約", "認可", "冪等", "エラー", "データと移行", "問い合わせ", "性能予算", "観測", "流出経路", "テスト", "段階", "未確定"]


def table_in(ts, key, cols, r, rule):
    """節 key の表のうち、cols の列を全部持つ最初の表を返す。無ければ FAIL。"""
    cands = [t for t in ts if key in t["section"]]
    for t in cands:
        if all(col(t, c) is not None for c in cols):
            return t
    r.fail(cands[0]["no"] if cands else 0, rule, f"「{key}」の節に、列（{'・'.join(cols)}）を持つ表が無い")
    return None


def need_cells(t, cols, r, rule, pattern=None, what=""):
    for no, cells in t["rows"]:
        for c in cols:
            v = cell(cells, col(t, c))
            if not v.strip() or v.strip() in ("-", "—", "なし（未記入）"):
                r.fail(no, rule, f"「{cells[0] if cells else ''}」の{c}が空")
            elif pattern and c == cols[0] and not re.search(pattern, v):
                r.fail(no, rule, f"「{cells[0] if cells else ''}」の{c}に{what}が無い")


def check_plan(name, r):
    lines, blocks = load_md(name)
    ts = tables(lines)
    text = "\n".join(l for _, l in lines)
    title = next((l[2:].strip() for _, l in lines if l.startswith("# ")), "")
    if not title.startswith("設計と実装計画"):
        r.fail(1, "表題", "「# 設計と実装計画: 件名」で始める")
    for key in PLAN_SECTIONS:
        if section_text(lines, key) is None:
            r.fail(0, "必須の節", f"「## {key}」を含む節が無い")
    if "架空" not in text and "実測" not in text:
        r.fail(0, "数値", "数値が架空か実測かを書いていない")
    if section_text(lines, "契約") is not None:
        t = table_in(ts, "契約", ["操作", "成功", "エラー"], r, "契約")
        if t:
            if not any(re.search(r"(GET|POST|PUT|PATCH|DELETE)\s+/", " ".join(c)) for _, c in t["rows"]):
                r.fail(t["no"], "契約", "操作の行に「GET /…」の形のメソッドとパスが無い")
            need_cells(t, ["エラー"], r, "契約", r"[45]\d\d", "4xx か 5xx の状態番号")
        if not re.search(r"\.json|openapi", section_text(lines, "契約"), re.I):
            r.fail(0, "契約", "契約の本体（OpenAPI の JSON）への参照が無い")
    s = section_text(lines, "認可")
    if s is not None:
        table_in(ts, "認可", ["役割"], r, "認可")
        for want, why in (("403", "役割の無い書き込みの応答"), ("404", "他人の資源を隠す応答"), ("サーバー", "判定する場所")):
            if want not in s:
                r.fail(0, "認可", f"認可の節に「{want}」（{why}）が無い")
    s = section_text(lines, "冪等")
    if s is not None:
        if "冪等キー" not in s and "Idempotency-Key" not in s:
            r.fail(0, "冪等", "冪等キーの決めが無い")
        if not re.search(r"\d+\s*(時間|日|分)", s):
            r.fail(0, "冪等", "冪等キーを保持する期間が無い")
        if not re.search(r"違う(内容|本文)", s):
            r.fail(0, "冪等", "同じ鍵で違う内容が来たときの扱いが無い")
    if section_text(lines, "エラー") is not None:
        t = table_in(ts, "エラー", ["コード", "状態番号", "分類", "原因", "対処", "追跡番号"], r, "エラー")
        if t:
            if not t["rows"]:
                r.fail(t["no"], "エラー", "エラーの表に行が無い")
            need_cells(t, ["状態番号", "分類", "原因", "対処", "追跡番号"], r, "エラー", r"\d{3}", "3 桁の状態番号")
    if section_text(lines, "データと移行") is not None:
        t = table_in(ts, "データと移行", ["変更", "戻し方"], r, "移行")
        if t:
            need_cells(t, ["戻し方"], r, "移行")
            k = col(t, "変更")
            for no, cells in t["rows"]:
                v = cell(cells, k)
                if re.search(r"追加", v) and re.search(r"削除", v):
                    r.fail(no, "移行", "追加と削除を同じリリースに入れている。消すのは別のリリースにする")
                back = cell(cells, col(t, "戻し方"))
                if re.search(r"(写し|スナップショット|バックアップ)(（[^）]*）)?から戻す", back):
                    r.fail(no, "移行", "戻し方が消す前の写しから戻す形。写しのあとの書き込みが消えるので、消した列を足し直して写し直す")
            # 段が 3 つ以上ある移行は、版と段の表を持つ。行は移行のあいだに動きうる API の版、列は DB の段で、升ごとに受けるか断るか
            if len(t["rows"]) >= 3:
                vt = next((x for x in ts if "データと移行" in x["section"] and x["header"] and "版" in x["header"][0]
                           and sum("段" in c for c in x["header"][1:]) >= 2), None)
                if vt is None:
                    r.fail(t["no"], "移行", "版と段の表が無い。行に移行のあいだに動く API の版、列に DB の段を置き、升ごとに書き込みを受けるか断るかを書く")
                else:
                    for no, cells in vt["rows"]:
                        if not re.search(r"受け|断る|まだ無い", " ".join(cells[1:])):
                            r.fail(no, "移行", f"版と段の表の「{cells[0]}」に、受けるか断るかが無い")
    if section_text(lines, "問い合わせ") is not None:
        t = table_in(ts, "問い合わせ", ["操作", "問い合わせの数"], r, "問い合わせ")
        if t:
            need_cells(t, ["問い合わせの数"], r, "問い合わせ", r"\d", "数字")
        if "N+1" not in (section_text(lines, "問い合わせ") or ""):
            r.fail(0, "問い合わせ", "N+1（行ごとの問い合わせ）を作らない決めと、確かめ方が無い")
    if section_text(lines, "性能予算") is not None:
        t = table_in(ts, "性能予算", ["操作", "p99", "測定点"], r, "性能予算")
        if t:
            need_cells(t, ["p99", "測定点"], r, "性能予算", r"\d+(\.\d+)?\s*(ms|秒)", "ms か秒の数字")
    s = section_text(lines, "観測")
    if s is not None:
        table_in(ts, "観測", ["項目"], r, "観測")
        for want, why in (("1 要求 1 行", "要約のログの単位"), ("追跡番号", "要求をたどる印"), ("書かない", "ログに入れない個人情報と鍵")):
            if want not in s:
                r.fail(0, "観測", f"観測の節に「{want}」（{why}）が無い")
    if section_text(lines, "流出経路") is not None:
        if not any(b["lang"] == "mermaid" and "流出経路" in b["section"] for b in blocks):
            r.fail(0, "流出経路", "データの在りかと外に出うる経路の図（Mermaid）が無い")
        t = table_in(ts, "流出経路", ["出口", "守り", "確認方法"], r, "流出経路")
        if t:
            names = " ".join(cell(c, col(t, "出口")) for _, c in t["rows"])
            for e in EXITS:
                if e not in names:
                    r.fail(t["no"], "流出経路", f"出口「{e}」の行が無い")
            need_cells(t, ["守り", "確認方法"], r, "流出経路")
    if section_text(lines, "テスト") is not None:
        t = table_in(ts, "テスト", ["テスト", "レベル"], r, "テスト")
        if t:
            need_cells(t, ["テスト", "レベル"], r, "テスト")
    if section_text(lines, "段階") is not None:
        t = table_in(ts, "段階", ["段階", "止めたとき"], r, "段階")
        if t:
            need_cells(t, ["止めたとき"], r, "段階")
    for no, l in lines:
        bare = re.sub(r"<https?://[^>\s]+>|<br\s*/?>", "", l)  # 自動リンクと改行は穴でない
        if re.search(r"<[^>]*>", bare):
            r.fail(no, "雛形の穴", "<…> が残っている")


def run_plan(args):
    if len(args) != 1:
        print("使い方: backend-plan-check.sh <設計と実装計画>")
        return 2
    r = Report("backend-plan-check", args[0])
    check_plan(args[0], r)
    return 0 if r.show() else 1


# ---- 問い合わせの数と p99
def load_app(path):
    spec = importlib.util.spec_from_file_location(f"app_{abs(hash(str(path)))}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def budget_from_plan(plan):
    lines, _ = load_md(plan)
    for t in tables(lines):
        if "性能予算" not in t["section"] or col(t, "p99") is None:
            continue
        for _, cells in t["rows"]:
            if re.search(r"GET /v1/orders(?![/{A-Za-z])", " ".join(cells[:2])):
                m = re.search(r"(\d+(?:\.\d+)?)\s*(ms|秒)", cell(cells, col(t, "p99")))
                if m:
                    return float(m.group(1)) * (1000 if m.group(2) == "秒" else 1)
    return None


def measure(mod, n, requests):
    api = mod.make_api(n, log=io.StringIO())
    srv = mod.make_server(api, "127.0.0.1", 0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        hdr = {"Authorization": "Bearer " + api.token_for("u-takagi")}  # 見本の作り物の鍵（API を作るたびの乱数）

        def call(method, path, body=None, extra=None):
            h = dict(hdr, **(extra or {}))
            data = json.dumps(body).encode() if body is not None else None
            if data:
                h["Content-Type"] = "application/json"
            t0 = time.perf_counter()
            conn.request(method, path, body=data, headers=h)
            res = conn.getresponse()
            raw = res.read()
            return res.status, json.loads(raw or b"{}"), (time.perf_counter() - t0) * 1000, api.sql

        st, body, _, sql = call("GET", "/v1/orders?view=today&limit=100")
        rows = len(body.get("items") or [])
        ready = [i["orderId"] for i in body.get("items") or [] if i.get("group") in ("ready", "late")]
        times = []
        for _ in range(5):
            call("GET", "/v1/orders?view=today&limit=100")
        for _ in range(requests):
            times.append(call("GET", "/v1/orders?view=today&limit=100")[2])
        sst, _, _, ship_sql = call("POST", "/v1/orders/ship", {"orderIds": ready}, {"Idempotency-Key": f"measure-{n}-0001"}) if ready else (0, None, 0, 0)
        conn.close()
    finally:
        srv.shutdown()
        srv.server_close()
    times.sort()
    p = lambda q: times[max(0, math.ceil(q * len(times)) - 1)]  # noqa: E731 — 順位で数える（nearest-rank）
    return {"n": n, "status": st, "rows": rows, "sql": sql, "ship_ids": len(ready), "ship_status": sst, "ship_sql": ship_sql,
            "p50": p(0.50), "p99": p(0.99), "requests": len(times)}


def run_queries(args):
    opts = {"--app": str(APP), "--plan": None, "--budget-ms": None, "--sizes": "24,400", "--requests": "200"}
    it = iter(args)
    for a in it:
        if a not in opts:
            print(__doc__)
            return 2
        opts[a] = next(it, None)
    app = pathlib.Path(opts["--app"])
    r = Report("query-count-check", app.name)
    budget = float(opts["--budget-ms"]) if opts["--budget-ms"] else budget_from_plan(opts["--plan"]) if opts["--plan"] else None
    if budget is None:
        r.fail("", "予算", "p99 の予算が無い。--plan の性能予算の表に「GET /v1/orders」の p99 を書くか、--budget-ms で渡す")
    sizes = [int(x) for x in opts["--sizes"].split(",")]
    mod = load_app(app)
    res = [measure(mod, n, int(opts["--requests"])) for n in sizes]
    for m in res:
        r.note(f"件数 {m['n']}: 一覧の行 {m['rows']}、一覧の SQL {m['sql']}、出荷指示 {m['ship_ids']} 件の SQL {m['ship_sql']}、"
               f"一覧の p50 {m['p50']:.2f}ms・p99 {m['p99']:.2f}ms（{m['requests']} 回、127.0.0.1 の HTTP、送ってから読み終えるまで）")
        if m["status"] != 200:
            r.fail("", "応答", f"件数 {m['n']} の一覧が {m['status']}")
    lo, hi = res[0], res[-1]
    if lo["rows"] == hi["rows"]:
        r.fail("", "件数の差", f"行の数が同じ（{lo['rows']}）で、件数に比例するかを比べられない")
    elif hi["sql"] > lo["sql"]:
        r.fail("", "N+1", f"一覧の SQL が行 {lo['rows']} で {lo['sql']}、行 {hi['rows']} で {hi['sql']}。行の数に比例して増えている")
    if lo["ship_ids"] != hi["ship_ids"] and hi["ship_sql"] > lo["ship_sql"]:
        r.fail("", "N+1", f"出荷指示の SQL が {lo['ship_ids']} 件で {lo['ship_sql']}、{hi['ship_ids']} 件で {hi['ship_sql']}。件数に比例して増えている")
    if budget is not None:
        worst = max(m["p99"] for m in res)
        r.note(f"p99 の予算 {budget:.0f}ms、実測の最大 {worst:.2f}ms")
        if worst > budget:
            r.fail("", "p99", f"p99 {worst:.2f}ms が予算 {budget:.0f}ms を超えた")
    return 0 if r.show() else 1


# ---- 自己試験
def quiet(fn, args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(args)
    return rc, buf.getvalue()


def selftest(kind):
    checks = []
    if kind == "contract":
        rc, out = quiet(run_contract, [str(CONTRACT)])
        checks.append((rc == 0, f"完成例の契約が落ちた: {out[-300:]}"))
        rc, out = quiet(run_contract, [str(CONTRACT), str(CONTRACT)])
        checks.append((rc == 0, f"同じ版どうしの比較が落ちた: {out[-300:]}"))
        rc, out = quiet(run_contract, [str(CONTRACT), str(CONTRACT_V2)])
        for rule in ("操作の削除", "応答の欄の削除", "必須の入力の追加", "型の変更", "列挙値の削除", "状態番号の削除"):
            checks.append((f"[{rule}]" in out, f"壊す変更の 2 版目で「{rule}」が出ない"))
        doc = json.loads(CONTRACT.read_text(encoding="utf-8"))
        add = copy.deepcopy(doc)  # 足すだけの変更（任意の引数、応答の欄、状態番号）は壊さない
        add["paths"]["/v1/orders"]["get"]["parameters"].append({"name": "region", "in": "query", "schema": {"type": "string"}})
        add["components"]["schemas"]["OrderList"]["properties"]["region"] = {"type": "string"}
        add["paths"]["/v1/orders"]["get"]["responses"]["429"] = add["paths"]["/v1/orders"]["get"]["responses"]["400"]
        with tempfile.TemporaryDirectory() as tmp:
            pa = pathlib.Path(tmp) / "add.json"
            pa.write_text(json.dumps(add), encoding="utf-8")
            rc, out = quiet(run_contract, [str(CONTRACT), str(pa)])
            checks.append((rc == 0, f"足すだけの変更が落ちた: {out[-300:]}"))
            rc, out = quiet(run_contract, [str(FIX / "bad-contract.json")])
            for rule in ("エラーの 4 点", "冪等キー", "認可", "起点の送り"):
                checks.append((f"[{rule}]" in out, f"負例の契約で「{rule}」が出ない"))
    elif kind == "plan":
        rc, out = quiet(run_plan, [str(PLAN)])
        checks.append((rc == 0, f"完成例が落ちた: {out[-400:]}"))
        rc, out = quiet(run_plan, [str(FIX / "bad-plan.md")])
        for rule in ("契約", "認可", "冪等", "エラー", "移行", "問い合わせ", "性能予算", "観測", "流出経路", "テスト", "段階", "必須の節"):
            checks.append((f"[{rule}]" in out, f"負例で「{rule}」が出ない"))
        rc, out = quiet(run_plan, [str(SKILL / "templates" / "backend-plan.md")])
        checks.append(("[雛形の穴]" in out, "雛形（穴埋めのまま）が通った"))
        text = PLAN.read_text(encoding="utf-8")  # 移行の表の段 4 の戻し方を「写しから戻す」に変えた写しは落ちる
        cut = text.find("## データと移行")
        lines = text[cut:].split("\n") if cut >= 0 else []
        hdr = next((k for k, x in enumerate(lines) if x.startswith("|") and "戻し方" in x), None)
        row = next((k for k in range(hdr + 2, len(lines)) if lines[k].startswith("| 4 |")), None) if hdr is not None else None
        bad = text
        if row is not None:
            at = [c.strip() for c in lines[hdr].strip().strip("|").split("|")].index("戻し方")
            cells = lines[row].strip().strip("|").split("|")
            cells[at] = " 消す前の写しから戻す "
            lines[row] = "|" + "|".join(cells) + "|"
            bad = text[:cut] + "\n".join(lines)
        with tempfile.TemporaryDirectory() as tmp:
            pb = pathlib.Path(tmp) / "snapshot-plan.md"
            pb.write_text(bad, encoding="utf-8")
            rc, out = quiet(run_plan, [str(pb)])
        checks.append((bad != text and "[移行]" in out, "消す段の戻し方が写しから戻す形なのに通った"))
        nov = re.sub(r"\n### 版と段の表\n.*?(?=\n### |\n## )", "\n", text, count=1, flags=re.S)  # 版と段の表を抜いた写しは落ちる
        with tempfile.TemporaryDirectory() as tmp:
            pb = pathlib.Path(tmp) / "no-version-table.md"
            pb.write_text(nov, encoding="utf-8")
            rc, out = quiet(run_plan, [str(pb)])
        checks.append((nov != text and "版と段の表が無い" in out, "版と段の表の無い移行が通った"))
    elif kind == "queries":
        rc, out = quiet(run_queries, ["--app", str(APP), "--plan", str(PLAN), "--requests", "40"])
        checks.append((rc == 0, f"見本の API が落ちた: {out[-400:]}"))
        rc, out = quiet(run_queries, ["--app", str(N1_APP), "--budget-ms", "300", "--requests", "20"])
        checks.append(("[N+1]" in out, f"わざと N+1 にした写しが通った: {out[-400:]}"))
        rc, out = quiet(run_queries, ["--app", str(APP), "--budget-ms", "0.001", "--requests", "20"])
        checks.append(("[p99]" in out, "予算を超えた p99 が通った"))
    ok = all(p for p, _ in checks)
    for p, msg in checks:
        if not p:
            print(f"FAIL selftest {NAMES[kind]}: {msg}")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} {NAMES[kind]} --selftest ({len(checks)} 例)")
    return ok


def main(argv):
    if len(argv) < 2 or argv[0] not in NAMES:
        print(__doc__)
        return 2
    if argv[1] == "--selftest":
        return 0 if selftest(argv[0]) else 1
    return {"contract": run_contract, "plan": run_plan, "queries": run_queries}[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
