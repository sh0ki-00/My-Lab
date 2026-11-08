#!/usr/bin/env python3
"""security_check — 侵入テストの報告・RoE（交戦規則）・検知の行列の欠けを落とす。

使い方: security_check.py report [--roe <RoE.md>] <報告.md>...  発見ごとの 5 点（何ができてしまうか・再現の手順・直し方・再検証・重さと採点の根拠）
        security_check.py roe <RoE.md>...         範囲・許可・連絡先・期間・止める条件・やらないこと
        security_check.py matrix <行列.md>...     攻撃の段階ごとの ログ・検知・通知・検証
        security_check.py <report|roe|matrix> --selftest
--roe を渡すと、報告を RoE の範囲の表（宛先と写しの置き場の列）と突き合わせる。
  RoE の範囲外: 再現・再検証の命令の宛先（host と port）が、範囲の表に無い。
  再検証の写し: 再検証の宛先が、再現の宛先と別の写しを立てる宛先になっている（直した写しを確かめていない）。
  試験の置き場: 名を挙げた試験の file が、再現の宛先の写しの外にあるか、無いか、名を挙げた試験の関数が無い。
  立てる写し: 再現の準備で立てる file の置き場が、RoE がその port に書いた写しと違う。
  RoE の範囲: RoE が読めないか、範囲の表に宛先か写しの置き場の列が無い。
出力: FAIL <ファイル>:<行> [<決まり>] <内容>、最後に RESULT: PASS|FAIL <検査> (…)。1 件でも FAIL なら終了コード 1。
決まりの根拠: skills/security/references/ の five-points-and-retest.md、roe-and-scope.md、detection-matrix.md。
"""
import datetime as dt
import os
import pathlib
import re
import shutil
import sys
import tempfile

PLACEHOLDER = re.compile(r"<[^<>\n]{1,80}>")
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}
URL_RX = re.compile(r"https?://(\[[0-9a-fA-F:]+\]|[A-Za-z0-9._-]+)")
DATE_RX = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
BASE_METRICS = ["AV", "AC", "AT", "PR", "UI", "VC", "VI", "VA", "SC", "SI", "SA"]
# 再現と再検証の命令に置かない書き方。攻撃のコードを報告に書かない決まり（ペルソナの禁止）を機械で見る。
ATTACK_CODE = [
    (re.compile(r"python3?\s+(-\w+\s+)*-c\b|node\s+-e\b|perl\s+-e\b|ruby\s+-e\b"), "その場で書いたプログラム"),
    (re.compile(r"<<-?\s*['\"]?\w+"), "埋め込みの文書"),
    (re.compile(r"\beval\b|base64\s+(-d|--decode)|/dev/tcp/"), "隠した命令"),
    (re.compile(r"\b(sqlmap|hydra|nikto|metasploit|msfconsole|msfvenom)\b"), "攻撃の道具の呼び出し"),
]
MAX_CMD_LINES = 12


def strip_md(s: str) -> str:
    return s.strip().strip("|").strip()


def parse(text: str):
    """行ごとに (行番号, 種類, 本文, 見出しの深さ) を返す。種類は heading・fence・code・table・text・blank。"""
    out, in_fence = [], False
    for no, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append((no, "fence", line, 0))
        elif in_fence:
            out.append((no, "code", line, 0))
        elif re.match(r"^#{1,6}\s", line):
            out.append((no, "heading", line.lstrip("#").strip(), len(line) - len(line.lstrip("#"))))
        elif line.lstrip().startswith("|"):
            out.append((no, "table", line, 0))
        elif line.strip():
            out.append((no, "text", line, 0))
        else:
            out.append((no, "blank", line, 0))
    return out


def sections(lines, level):
    """深さ level の見出しごとに、その下の行（より深い見出しを含む）を集める。"""
    secs, cur = [], None
    for item in lines:
        no, kind, body, lv = item
        if kind == "heading" and lv <= level:
            cur = {"title": body, "no": no, "lines": []} if lv == level else None
            if cur is not None:
                secs.append(cur)
        elif cur is not None:
            cur["lines"].append(item)
    return secs


def has_content(lines) -> bool:
    for _no, kind, body, _lv in lines:
        if kind in ("text", "table", "code") and body.strip() and not PLACEHOLDER.search(body):
            if kind == "table" and re.fullmatch(r"[|\s:-]+", body):
                continue
            return True
    return False


def code_blocks(lines):
    blocks, cur = [], None
    for no, kind, body, _lv in lines:
        if kind == "fence":
            if cur is None:
                cur = []
            else:
                blocks.append(cur)
                cur = None
        elif kind == "code" and cur is not None:
            cur.append((no, body))
    return blocks


def table_rows(lines):
    rows = []
    for no, kind, body, _lv in lines:
        if kind != "table" or re.fullmatch(r"[|\s:-]+", body):
            continue
        rows.append((no, [strip_md(c) for c in body.strip().strip("|").split("|")]))
    return rows


def outside_hosts(text: str):
    return [h for h in URL_RX.findall(text) if h.lower() not in LOOPBACK]


def check_commands(tag, label, blocks, issues, at=0):
    cmds = [(no, b) for blk in blocks for no, b in blk if b.strip() and not b.strip().startswith("#")]
    if not cmds:
        issues.append((at, label, f"{tag} の{label}に命令の囲み（```bash）が無い"))
        return
    if len(cmds) > MAX_CMD_LINES:
        issues.append((cmds[0][0], "攻撃コード", f"{tag} の{label}が {len(cmds)} 行。{MAX_CMD_LINES} 行以内の要求の命令にし、プログラムを書かない"))
    for no, b in cmds:
        for rx, name in ATTACK_CODE:
            if rx.search(b):
                issues.append((no, "攻撃コード", f"{tag} の{label}に{name}がある。要求の命令だけを書く"))
        for h in outside_hosts(b):
            issues.append((no, "範囲外の宛先", f"{tag} の{label}が {h} に向いている。RoE の範囲（手元の 127.0.0.1）だけに向ける"))


# ---- RoE の範囲と報告の突き合わせ（--roe） ----
URL_HP_RX = re.compile(r"(https?)://(\[[0-9a-fA-F:]+\]|[A-Za-z0-9._-]+)(?::(\d+))?")
PATH_RX = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]*)+")
TEST_FILE_RX = re.compile(r"(?:^|/)(test\w*|\w+_test)\.py$")
SERVE_RX = re.compile(r"(\S+\.py)\b.*--port[ =](\d+)")


def hostports(text: str):
    """宛先を host:port の形にそろえる。localhost は 127.0.0.1、port の無い URL は 80 か 443。"""
    out = []
    for scheme, host, port in URL_HP_RX.findall(text):
        h = host.lower().strip("[]")
        h = "127.0.0.1" if h == "localhost" else h
        out.append(f"{h}:{port or (443 if scheme == 'https' else 80)}")
    return out


def norm(p: str) -> str:
    return os.path.normpath(p.strip().strip("`'\"")).rstrip("/")


def parse_roe_scope(text: str):
    """RoE の範囲の表から [(宛先の集合, 写しの置き場の集合)] を返す。読めないときは (None, 理由)。"""
    s = next((x for x in sections(parse(text), 2) if x["title"].startswith("範囲")), None)
    if s is None:
        return None, "RoE に「## 範囲」の節が無い"
    rows = table_rows(s["lines"])
    head = rows[0][1] if rows else []
    di = next((i for i, c in enumerate(head) if "宛先" in c), None)
    pi = next((i for i, c in enumerate(head) if "置き場" in c), None)
    if di is None or pi is None or len(rows) < 2:
        return None, "RoE の範囲の表に「宛先」と「写しの置き場」の列が無い。宛先ごとに、立てる写しの置き場を書く"
    scope = []
    for _no, cells in rows[1:]:
        dest = cells[di] if di < len(cells) else ""
        place = cells[pi] if pi < len(cells) else ""
        ticks = re.findall(r"`([^`]+)`", place)
        copies = {norm(p) for p in (ticks or PATH_RX.findall(place)) if "/" in p}
        scope.append((set(hostports(dest)), copies))
    return scope, None


def under(path: str, copy: str, bases) -> bool:
    p = norm(path)
    if os.path.isabs(p):
        return any(p.startswith(os.path.normpath(os.path.join(str(b), copy)) + os.sep) for b in bases)
    return p.startswith(copy + "/")


def locate(path: str, bases):
    p = norm(path)
    if os.path.isabs(p):
        return pathlib.Path(p) if pathlib.Path(p).is_file() else None
    for b in bases:
        q = pathlib.Path(b) / p
        if q.is_file():
            return q
    return None


def test_refs(line: str):
    """命令の 1 行から、名を挙げた試験の (file, [関数名]) を拾う。"""
    toks = line.split()
    for i, raw in enumerate(toks):
        t = raw.strip("'\"")
        path = t.split("::")[0]
        if TEST_FILE_RX.search(path):
            rest = " ".join([t[len(path):]] + toks[i + 1:])
            yield path, re.findall(r"\btest_\w+", rest)


def check_against_roe(lines, findings_cmds, scope, bases):
    """findings_cmds: [(tag, 再現の命令 [(行, 本文)], 再検証の命令 [(行, 本文)])]。"""
    issues = []
    all_hp = set().union(*(hp for hp, _c in scope)) if scope else set()
    all_copies = set().union(*(c for _hp, c in scope)) if scope else set()

    def copies_for(hp):
        return set().union(*[c for h, c in scope if hp in h]) if scope else set()

    prep = next((s for s in sections(lines, 2) if "準備" in s["title"]), None)
    if prep:
        for blk in code_blocks(prep["lines"]):
            for no, b in blk:
                for m in SERVE_RX.finditer(b):
                    hp = f"127.0.0.1:{m.group(2)}"
                    if hp not in all_hp:
                        issues.append((no, "RoE の範囲外", f"再現の準備が {hp} に立てている。RoE の範囲の表に無い宛先"))
                    elif not any(under(m.group(1), c, bases) for c in copies_for(hp)):
                        issues.append((no, "立てる写し", f"再現の準備が {hp} に {os.path.dirname(norm(m.group(1)))} を立てている。RoE がこの宛先に書いた写しは {'・'.join(sorted(copies_for(hp))) or 'なし'}"))
    for tag, repro, retest in findings_cmds:
        for label, cmds in (("再現の手順", repro), ("再検証", retest)):
            for no, b in cmds:
                for hp in hostports(b):
                    if hp not in all_hp:
                        issues.append((no, "RoE の範囲外", f"{tag} の{label}の宛先 {hp} が RoE の範囲の表に無い。範囲の表の宛先だけに向ける"))
        target = set().union(*[copies_for(hp) for _no, b in repro for hp in hostports(b) if hp in all_hp]) if repro else set()
        if not target:
            target = set().union(*[copies_for(hp) for _no, b in retest for hp in hostports(b) if hp in all_hp]) if retest else set()
        target = target or all_copies
        for no, b in retest:
            for hp in hostports(b):
                if hp in all_hp and not (copies_for(hp) & target):
                    issues.append((no, "再検証の写し", f"{tag} の再検証の宛先 {hp} は、RoE で {'・'.join(sorted(copies_for(hp)))} を立てる宛先。"
                                                     f"再現の宛先の写し {'・'.join(sorted(target))} を直して立てた宛先に向ける"))
        for label, cmds in (("再現の手順", repro), ("再検証", retest)):
            for no, b in cmds:
                for path, names in test_refs(b):
                    if "$" in path:
                        issues.append((no, "試験の置き場", f"{tag} の{label}の試験 {path} が変数を含み、置き場を確かめられない。RoE の写しからのパスで書く"))
                        continue
                    if not any(under(path, c, bases) for c in target):
                        issues.append((no, "試験の置き場", f"{tag} の{label}の試験 {norm(path)} が、直す写し {'・'.join(sorted(target))} の外にある"))
                        continue
                    f = locate(path, bases)
                    if f is None:
                        issues.append((no, "試験の置き場", f"{tag} の{label}の試験 {norm(path)} が無い"))
                        continue
                    body = f.read_text(encoding="utf-8", errors="replace")
                    for name in names:
                        if not re.search(rf"\bdef {name}\b", body):
                            issues.append((no, "試験の置き場", f"{tag} の{label}の試験 {name} が {norm(path)} に無い"))
    return issues


# ---- report ----
FIVE = [("何ができてしまうか", "何ができてしまうか"), ("再現", "再現の手順"), ("直し方", "直し方"),
        ("再検証", "再検証"), ("重さ", "重さと採点の根拠")]


def cmd_lines(blocks):
    return [(no, b) for blk in blocks for no, b in blk if b.strip() and not b.strip().startswith("#")]


def check_report(text: str, scope=None, bases=()):
    """scope は parse_roe_scope の結果（--roe のときだけ）。bases は試験の file を探す起点。"""
    issues, cmds_by_finding = [], []
    lines = parse(text)
    h2 = sections(lines, 2)
    for key in ("要約", "範囲", "発見"):
        if not any(key in s["title"] for s in h2):
            issues.append((0, "必須の節", f"「## {key}」の節が無い"))
    found = next((s for s in h2 if "発見" in s["title"]), None)
    findings = [s for s in sections(found["lines"], 3) if re.match(r"F-\d+", s["title"])] if found else []
    if found and not findings:
        issues.append((found["no"], "発見", "「### F-1: 題」の形の発見が無い"))
    for f in findings:
        tag = f["title"].split(":")[0].split("：")[0].strip()
        subs = sections(f["lines"], 4)
        cmds = {k: cmd_lines(code_blocks(s["lines"])) for k in ("再現", "再検証")
                for s in [next((x for x in subs if x["title"].startswith(k)), None)] if s}
        cmds_by_finding.append((tag, cmds.get("再現", []), cmds.get("再検証", [])))
        for key, label in FIVE:
            sub = next((s for s in subs if s["title"].startswith(key)), None)
            if sub is None:
                issues.append((f["no"], label, f"{tag} に「#### {label}」が無い"))
                continue
            if not has_content(sub["lines"]):
                issues.append((sub["no"], label, f"{tag} の{label}が空か穴埋めのまま"))
                continue
            body = "\n".join(b for _n, _k, b, _l in sub["lines"])
            if key == "何ができてしまうか" and "証拠" not in body:
                issues.append((sub["no"], label, f"{tag} の{label}に証拠（応答・ログの抜粋か試験の名）が無い"))
            if key in ("再現", "再検証"):
                check_commands(tag, label, code_blocks(sub["lines"]), issues, sub["no"])
            if key == "再検証" and not re.search(r"期待[^\n]*`[^`]+`", body):
                issues.append((sub["no"], label, f"{tag} の{label}に合否の分かる期待の値（期待: `404` の形）が無い"))
            if key == "重さ":
                if not re.search(r"CVSS:4\.0/", body):
                    issues.append((sub["no"], label, f"{tag} に CVSS:4.0/… の文字列が無い"))
                if not re.search(r"点数[^0-9\n]{0,12}\d", body) or not re.search(r"重さ[^A-Za-z\n]{0,12}(None|Low|Medium|High|Critical)", body):
                    issues.append((sub["no"], label, f"{tag} に「点数: x.x」と「重さ: High」の形が無い"))
                covered = set()
                for _no, cells in table_rows(sub["lines"])[1:]:
                    if len(cells) >= 2 and cells[1] and not PLACEHOLDER.search(cells[1]):
                        covered |= {m for m in BASE_METRICS if re.search(rf"(?<![A-Z]){m}(?![A-Z])", cells[0])}
                miss = [m for m in BASE_METRICS if m not in covered]
                if miss:
                    issues.append((sub["no"], "採点の根拠", f"{tag} の根拠の表に {'・'.join(miss)} の理由が無い"))
    if scope is not None:
        issues += check_against_roe(lines, cmds_by_finding, scope, bases)
    return issues, len(findings)


# ---- roe ----
ROE_KEYS = ["範囲", "許可", "連絡先", "期間", "止める条件", "やらないこと"]


def check_roe(text: str):
    issues = []
    secs = sections(parse(text), 2)
    for key in ROE_KEYS:
        s = next((x for x in secs if x["title"].startswith(key)), None)
        if s is None:
            issues.append((0, key, f"「## {key}」の節が無い"))
            continue
        if not has_content(s["lines"]):
            issues.append((s["no"], key, f"{key}が空か穴埋めのまま"))
            continue
        body = "\n".join(b for _n, _k, b, _l in s["lines"])
        rows = table_rows(s["lines"])
        items = [b for _n, k, b, _l in s["lines"] if k == "text" and re.match(r"^\s*(\d+\.|[-*])\s", b)]
        if key == "範囲":
            head = rows[0][1] if rows else []
            oi = next((i for i, c in enumerate(head) if "所有" in c), None)
            if not rows or oi is None or len(rows) < 2:
                issues.append((s["no"], key, "範囲の表（対象と所有の確認の列）が無い"))
            else:
                for no, cells in rows[1:]:
                    line = " | ".join(cells)
                    owned = oi < len(cells) and cells[oi] not in ("", "-", "なし") and not PLACEHOLDER.search(cells[oi])
                    if not owned:
                        issues.append((no, "所有の確認", f"対象「{cells[0]}」に所有の確認が無い"))
                    for h in outside_hosts(line):
                        if not owned:
                            issues.append((no, "範囲外の宛先", f"{h} は手元でなく、所有の確認も無い"))
        elif key == "許可":
            if not re.search(r"署名", body) or not DATE_RX.search(body):
                issues.append((s["no"], key, "許可に署名した人と日付（2026-11-08 の形）が無い"))
        elif key == "連絡先":
            if len(rows) < 3:
                issues.append((s["no"], key, "連絡先の表が 2 人に満たない（実施する人と、止める判断をする人）"))
        elif key == "期間":
            ds = [dt.date(int(y), int(m), int(d)) for y, m, d in DATE_RX.findall(body)]
            if len(ds) < 2:
                issues.append((s["no"], key, "期間に始まりと終わりの日付が無い"))
            elif ds[1] < ds[0]:
                issues.append((s["no"], key, f"終わり {ds[1]} が始まり {ds[0]} より前"))
        elif key == "止める条件":
            if len(items) < 2:
                issues.append((s["no"], key, "止める条件が 2 つに満たない（箇条で書く）"))
        elif key == "やらないこと":
            if len(items) < 3:
                issues.append((s["no"], key, "やらないことが 3 つに満たない（箇条で書く）"))
            for word, why in (("本番", "本番での試験"), ("第三者", "第三者の資産への到達")):
                if word not in body:
                    issues.append((s["no"], key, f"やらないことに{why}が無い"))
    return issues, len(secs)


# ---- matrix ----
MATRIX_COLS = ["段階", "ログ", "検知", "通知", "検証"]


def check_matrix(text: str):
    issues = []
    lines = parse(text)
    rows = table_rows(lines)
    head_i = next((i for i, (_no, c) in enumerate(rows) if all(any(k in x for x in c) for k in MATRIX_COLS)), None)
    if head_i is None:
        return [(0, "行列", "段階・ログ・検知・通知・検証の列がそろった表が無い")], 0
    head = rows[head_i][1]
    idx = {k: next(i for i, x in enumerate(head) if k in x) for k in MATRIX_COLS}
    body = []
    for no, cells in rows[head_i + 1:]:
        if len(cells) != len(head):
            break
        body.append((no, cells))
    if len(body) < 4:
        issues.append((rows[head_i][0], "行列", f"段階が {len(body)} 行。入口から持ち出しまで 4 段階以上にする"))
    for no, cells in body:
        name = cells[idx["段階"]]
        for k in MATRIX_COLS:
            v = cells[idx[k]]
            if not v or v in ("-", "—") or PLACEHOLDER.search(v):
                issues.append((no, k, f"段階「{name}」の{k}が空か穴埋めのまま"))
        if "`" not in cells[idx["検証"]]:
            issues.append((no, "検証", f"段階「{name}」の検証に、合否の分かる命令（`…`）が無い"))
    return issues, len(body)


CHECKS = {"report": ("report-check", check_report, "発見"), "roe": ("roe-check", check_roe, "節"), "matrix": ("report-check --matrix", check_matrix, "段階")}


# ---- selftest ----
GOOD_FINDING = """### F-1: 例の発見

#### 何ができてしまうか

閲覧の権限の人が、他の店の注文を読めます。証拠は応答の抜粋です。

#### 再現の手順

手元の見本で 1 回だけ要求を送ります。

```bash
curl -s -H "Authorization: Bearer $KEY_OP" http://127.0.0.1:18080/v1/orders/700001
```

#### 直し方

店の id を全部の問い合わせに入れます。

#### 再検証

直したあとに同じ要求を送ります。

```bash
curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $KEY_OP" http://127.0.0.1:18080/v1/orders/700001
```

期待: `404`

#### 重さと採点の根拠

採点は `CVSS:4.0/AV:N/AC:L/AT:N/PR:L/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N` で、点数: 7.1、重さ: High です。

| 値 | 根拠 |
|---|---|
| AV・AC・AT | 網から、条件なしに届く |
| PR・UI | 鍵は要る。相手の操作は要らない |
| VC・VI・VA | 他の店の注文が読める。書けない |
| SC・SI・SA | 他の仕組みには及ばない |
"""
GOOD_REPORT = "# 報告\n\n## 要約\n\n要約の文です。\n\n## 範囲\n\n範囲の文です。\n\n## 発見\n\n発見の文です。\n\n" + GOOD_FINDING
GOOD_ROE = """# RoE

## 範囲

対象の表です。

| 対象 | 宛先 | 所有の確認 |
|---|---|---|
| 見本の API | http://127.0.0.1:18080 | 社長のリポジトリの写し |

## 許可

社長の署名: 社長（2026-11-08）

## 連絡先

連絡先の表です。

| 役 | 人 | 連絡の手段 |
|---|---|---|
| 実施 | セキュリティ | 作業場の連絡 |
| 止める判断 | 社長 | 秘書を通す |

## 期間

2026-11-08 から 2026-11-09 まで。

## 止める条件

- 範囲の外への要求が 1 本でも出た。
- 見本のデータが壊れた。

## やらないこと

- 本番での試験。
- 第三者の資産に向けること。
- 負荷をかけて止める試験。
"""
GOOD_MATRIX = """# 行列

| 段階 | ログ | 検知 | 通知 | 検証 |
|---|---|---|---|---|
| 入口 | 401 の行 | 5 分に 20 本 | 当番に知らせる | `bash a.sh` |
| 権限 | 403 の行 | 1 本で | 当番に知らせる | `bash b.sh` |
| 横移動 | 404 の行 | 5 分に 30 本 | 当番に知らせる | `bash c.sh` |
| 持ち出し | 行数 | 1 分に 500 行 | 当番に知らせる | `bash d.sh` |
"""


# --roe の自己試験。写しは 2 つ（lab-a は直す写し、lab-b は別の写し）。18080 と 18081 は lab-a、18082 は lab-b。
ROE_SCOPE = """# RoE

## 範囲

| 対象 | 宛先 | 写しの置き場 | 所有の確認 |
|---|---|---|---|
| 穴のある写し | http://127.0.0.1:18080 | `lab-a/api/` | 社長のリポジトリの写し |
| 直した写し | http://127.0.0.1:18081 | `lab-a/api/` | 社長のリポジトリの写し |
| 別の写し | http://127.0.0.1:18082 | `lab-b/api/` | 社長のリポジトリの写し |
"""
PREP = "## 再現の準備\n\n```bash\npython3 -I lab-a/api/server.py --port 18080 > \"$TMPDIR/k.txt\" &\n```\n\n## 発見"
TEST_CMD = "python3 -I lab-a/api/test_orders_api.py OrdersApiTest.test_detail_is_404\n```\n\n期待"
GOOD_ROE_REPORT = (GOOD_REPORT.replace("## 発見", PREP, 1)
                   .replace("'%{http_code}' -H \"Authorization: Bearer $KEY_OP\" http://127.0.0.1:18080/v1/orders/700001\n```\n\n期待",
                            "'%{http_code}' -H \"Authorization: Bearer $KEY_OP\" http://127.0.0.1:18081/v1/orders/700001\n" + TEST_CMD))
TEST_FILE = "class OrdersApiTest:\n    def test_detail_is_404(self):\n        pass\n"


def selftest_roe_report():
    """--roe の突き合わせを、写しの file を置いた一時のディレクトリで試す。"""
    cases = [
        ("RoE の写しにそろった報告", GOOD_ROE_REPORT, ROE_SCOPE, []),
        ("localhost も 127.0.0.1 と同じ宛先", GOOD_ROE_REPORT.replace("http://127.0.0.1:18081", "http://localhost:18081"), ROE_SCOPE, []),
        ("再検証の宛先が RoE に無い port", GOOD_ROE_REPORT.replace("127.0.0.1:18081", "127.0.0.1:18083"), ROE_SCOPE, ["RoE の範囲外"]),
        ("再検証の宛先が別の写し", GOOD_ROE_REPORT.replace("127.0.0.1:18081", "127.0.0.1:18082"), ROE_SCOPE, ["再検証の写し"]),
        ("試験が別の写しにある", GOOD_ROE_REPORT.replace("lab-a/api/test_orders_api.py", "lab-b/api/test_orders_api.py"), ROE_SCOPE, ["試験の置き場"]),
        ("試験の関数が写しに無い", GOOD_ROE_REPORT.replace("OrdersApiTest.test_detail_is_404", "OrdersApiTest.test_only_in_samples"), ROE_SCOPE, ["試験の置き場"]),
        ("試験の file が写しに無い", GOOD_ROE_REPORT.replace("lab-a/api/test_orders_api.py", "lab-a/api/test_missing.py"), ROE_SCOPE, ["試験の置き場"]),
        ("再現の準備が別の写しを立てる", GOOD_ROE_REPORT.replace("lab-a/api/server.py", "lab-b/api/server.py"), ROE_SCOPE, ["立てる写し"]),
        ("RoE に写しの置き場の列が無い", GOOD_ROE_REPORT, ROE_SCOPE.replace("写しの置き場", "場所"), ["RoE の範囲"]),
    ]
    bad = 0
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="security-check-roe-"))
    try:
        for d in ("lab-a/api", "lab-b/api"):
            (tmp / d).mkdir(parents=True)
        (tmp / "lab-a/api/test_orders_api.py").write_text(TEST_FILE, encoding="utf-8")
        (tmp / "lab-b/api/test_orders_api.py").write_text(TEST_FILE, encoding="utf-8")
        for title, report, roe, want in cases:
            scope, why = parse_roe_scope(roe)
            got = sorted({rule for _no, rule, _msg in check_report(report, scope, [tmp])[0]}) if scope is not None else ["RoE の範囲"]
            ok = got == sorted(set(want))
            bad += 0 if ok else 1
            print(f"{'PASS' if ok else 'FAIL'} report-check --roe {title}（期待 {want or 'なし'}、実際 {got or 'なし'}）")
        (tmp / "roe.md").write_text(ROE_SCOPE, encoding="utf-8")
        (tmp / "report.md").write_text(GOOD_ROE_REPORT, encoding="utf-8")
        rc = run("report", [str(tmp / "report.md")], quiet=True, roe=str(tmp / "roe.md"))
        bad += 0 if rc == 0 else 1
        print(f"{'PASS' if rc == 0 else 'FAIL'} report-check --roe ファイルから読む（期待 0、実際 {rc}）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return bad, len(cases) + 1


def selftest(which):
    name, fn, _unit = CHECKS[which]
    if which == "report":
        cases = [
            ("5 点のそろった報告", GOOD_REPORT, []),
            ("何ができてしまうかが無い", GOOD_REPORT.replace("#### 何ができてしまうか", "#### 説明"), ["何ができてしまうか"]),
            ("証拠の無い主張", GOOD_REPORT.replace("証拠は応答の抜粋です。", "たぶん読めます。"), ["何ができてしまうか"]),
            ("再現が文だけ", re.sub(r"(#### 再現の手順\n\n.*?\n\n)```bash\n.*?```\n", r"\1", GOOD_REPORT, flags=re.S), ["再現の手順"]),
            ("直し方が穴埋め", GOOD_REPORT.replace("店の id を全部の問い合わせに入れます。", "<直し方>"), ["直し方"]),
            ("再検証に期待の値が無い", GOOD_REPORT.replace("期待: `404`", "確かめます。"), ["再検証"]),
            ("採点の根拠が欠ける", GOOD_REPORT.replace("| SC・SI・SA | 他の仕組みには及ばない |\n", ""), ["採点の根拠"]),
            ("CVSS の文字列が無い", GOOD_REPORT.replace("`CVSS:4.0/AV:N/AC:L/AT:N/PR:L/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N`", "見立て"), ["重さと採点の根拠"]),
            ("外の宛先に向けた再現", GOOD_REPORT.replace("http://127.0.0.1:18080/v1/orders/700001\n```\n\n#### 直し方",
                                                  "https://shop.example.com/v1/orders/700001\n```\n\n#### 直し方"), ["範囲外の宛先"]),
            ("再現にプログラムを書く", GOOD_REPORT.replace("curl -s -H", "python3 -c 'import x' ; curl -s -H", 1), ["攻撃コード"]),
            ("発見の節が無い", GOOD_REPORT.replace("## 発見", "## 見つけたこと"), ["必須の節"]),
        ]
    elif which == "roe":
        cases = [
            ("6 項目のそろった RoE", GOOD_ROE, []),
            ("範囲が外の宛先で所有の確認が無い", GOOD_ROE.replace("| 見本の API | http://127.0.0.1:18080 | 社長のリポジトリの写し |",
                                                         "| 店の本番 | https://shop.example.com | |"), ["所有の確認", "範囲外の宛先"]),
            ("許可に署名が無い", GOOD_ROE.replace("社長の署名: 社長（2026-11-08）", "口頭で了承"), ["許可"]),
            ("連絡先が 1 人", GOOD_ROE.replace("| 止める判断 | 社長 | 秘書を通す |\n", ""), ["連絡先"]),
            ("期間が逆", GOOD_ROE.replace("2026-11-08 から 2026-11-09", "2026-11-09 から 2026-11-08"), ["期間"]),
            ("止める条件が 1 つ", GOOD_ROE.replace("- 見本のデータが壊れた。\n", ""), ["止める条件"]),
            ("やらないことに本番が無い", GOOD_ROE.replace("- 本番での試験。", "- 夜間の試験。"), ["やらないこと"]),
            ("期間の節が無い", GOOD_ROE.replace("## 期間", "## 日程"), ["期間"]),
        ]
    else:
        cases = [
            ("4 段階のそろった行列", GOOD_MATRIX, []),
            ("通知が空", GOOD_MATRIX.replace("| 1 本で | 当番に知らせる |", "| 1 本で | - |"), ["通知"]),
            ("検証が命令でない", GOOD_MATRIX.replace("`bash d.sh`", "目で見る"), ["検証"]),
            ("段階が 3 つ", GOOD_MATRIX.replace("| 持ち出し | 行数 | 1 分に 500 行 | 当番に知らせる | `bash d.sh` |\n", ""), ["行列"]),
            ("検知の列が無い", GOOD_MATRIX.replace("| 検知 ", "| 見張り "), ["行列"]),
        ]
    bad = 0
    for title, text, want in cases:
        got = sorted({rule for _no, rule, _msg in fn(text)[0]})
        ok = got == sorted(set(want))
        bad += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} {name} {title}（期待 {want or 'なし'}、実際 {got or 'なし'}）")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="security-check-"))
    try:  # ファイルの入口も 1 回通す
        p = tmp / "a.md"
        p.write_text(cases[0][1], encoding="utf-8")
        rc = run(which, [str(p)], quiet=True)
        bad += 0 if rc == 0 else 1
        print(f"{'PASS' if rc == 0 else 'FAIL'} {name} ファイルから読む（期待 0、実際 {rc}）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    n = len(cases) + 1
    if which == "report":
        b, k = selftest_roe_report()
        bad, n = bad + b, n + k
    print(f"RESULT: {'PASS' if bad == 0 else 'FAIL'} {name} --selftest ({n} 例)")
    return 0 if bad == 0 else 1


def ancestors(p: pathlib.Path):
    p = p.resolve()
    return [p] + list(p.parents)


def run(which, files, quiet=False, roe=None):
    name, fn, unit = CHECKS[which]
    fails, total = 0, 0
    scope, roe_issue = None, None
    if roe is not None:
        rp = pathlib.Path(roe)
        if not rp.is_file():
            roe_issue = f"--roe の {roe} が無い"
        else:
            scope, why = parse_roe_scope(rp.read_text(encoding="utf-8"))
            roe_issue = None if scope is not None else f"{why}（{roe}）"
    for f in files:
        p = pathlib.Path(f)
        if not p.is_file():
            print(f"FAIL {f}:0 [ファイル] 無い")
            fails += 1
            continue
        if roe_issue:
            if not quiet:
                print(f"FAIL {f}:0 [RoE の範囲] {roe_issue}")
            fails += 1
        if which == "report":
            bases = []
            for b in [pathlib.Path.cwd()] + ancestors(p.parent) + (ancestors(pathlib.Path(roe).parent) if roe else []):
                if b not in bases:
                    bases.append(b)
            issues, n = check_report(p.read_text(encoding="utf-8"), scope, bases)
        else:
            issues, n = fn(p.read_text(encoding="utf-8"))
        total += n
        for no, rule, msg in issues:
            if not quiet:
                print(f"FAIL {f}:{no} [{rule}] {msg}")
        fails += len(issues)
    if not quiet:
        print(f"RESULT: {'PASS' if fails == 0 else 'FAIL'} {name} ({unit} {total}、FAIL {fails})")
    return 0 if fails == 0 else 1


def main(argv):
    if not argv or argv[0] not in CHECKS:
        print(__doc__)
        return 2
    which, rest = argv[0], argv[1:]
    if rest[:1] == ["--selftest"]:
        return selftest(which)
    roe = None
    if "--roe" in rest:
        i = rest.index("--roe")
        if which != "report" or i + 1 >= len(rest):
            print(__doc__)
            return 2
        roe = rest[i + 1]
        rest = rest[:i] + rest[i + 2:]
    if not rest:
        print(__doc__)
        return 2
    return run(which, rest, roe=roe)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
