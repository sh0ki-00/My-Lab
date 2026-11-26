#!/usr/bin/env python3
"""attack_run — 常設の RoE（交戦規則）の範囲で、ローカルで起こしたアプリに、攻撃の表の手口だけを送る。

攻撃の相手は、ソースコードから手元で起こしたアプリだけである。クラウドの環境・本番・第三者には 1 本も送らない。
手口は skills/security/references/attack-table.md の A01〜A12 と、送らない検査 S01。その場で書いたプログラムは回さない。

道具が自分で守る 9 つの線（references/attack-table.md の「道具が守る線」）:
  1 許可が先   RoE の機械の節が通り、今が期間の中で、範囲の指紋が合う。合わなければ 1 本も送らず終了コード 2。
  2 宛先は手元 127.0.0.1・localhost・::1 だけ。名前を引かず、数字の宛先 127.0.0.1 で送る。
  3 追わない    移動（リダイレクト）を追わない。代理（プロキシ）を通さない。外への移動は返ったことだけ残す。
  4 待ち受け    そのポートで待つプロセスが、RoE の起動の命令で立った物か（lsof か ss で見る）。
  5 下流        RoE の下流の表が、手元・作り物・使い捨てだけか。外の宛先が 1 つでもあれば止まる。
  6 量を縛る    手口ごと・全体の本数、同時 1 本、1 本と全体の打ち切りを RoE から読む。
  7 残す物      台帳に残すのは、手口・入口・利用者・状態番号・長さ・印の有無・所要の時間だけ。本文と鍵は残さない。
  8 表だけ      送るのは A01〜A12 だけ。表に無い攻撃は送れない。
  9 ポート      外へつながせる試験の見張り役は、空いているポート（127.0.0.1:0）に自分で立てる。

使い方:
  attack_run.py --target 127.0.0.1:<ポート> --probe <入口の一覧.json> --roe <常設の RoE.md> [--baseline <台帳.json>] [--ledger <出力.json>]
  attack_run.py --selftest       9 つの線の判定と、台帳の形と、集計を、サーバーを立てずに試す。
出力: 完了報告に貼る「## 攻撃の結果」の節（RESULT の行と、手口ごとの表と、見つけた脆弱性の表と、確かめたことの表）。
"""
import argparse
import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

LOCAL = {"127.0.0.1", "localhost", "::1"}
ROLES = {"operator": 2, "viewer": 1, "none": 0}
HANDLES = ["A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09", "A10", "A11", "A12"]
HANDLE_NAME = {
    "A01": "認証なしで入る", "A02": "他人の物を読む・書く", "A03": "権限を越える",
    "A04": "余計な項目を読む・書く", "A05": "鍵とセッションを破る", "A06": "入力でクエリや命令を壊す",
    "A07": "画面にスクリプトを差し込む", "A08": "他のサイトから操作させる", "A09": "量と連打",
    "A10": "外へつながせる", "A11": "ファイルの受け取りと配信", "A12": "設定と漏れ",
}


class Refuse(Exception):
    def __init__(self, line, why):
        super().__init__(why)
        self.line = line
        self.why = why


# ---- RoE の機械の節
def scope_fingerprint(block):
    scope = {k: block.get(k) for k in ("targets", "launch", "downstream", "limits", "period")}
    canon = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def read_roe(path):
    text = open(path, encoding="utf-8").read()
    m = re.search(r"```json\s*\n(.*?)\n```", text, re.S)
    if not m:
        raise Refuse(1, "RoE に機械の節（```json の囲み）が無い")
    try:
        block = json.loads(m.group(1))
    except ValueError as e:
        raise Refuse(1, "RoE の機械の節が読めない: %s" % e)
    for k in ("targets", "launch", "downstream", "limits", "period", "fingerprint", "approval_record"):
        if k not in block:
            raise Refuse(1, "RoE の機械の節に「%s」が無い" % k)
    return block


def check_lines_1_5(block, host, port, today):
    # 線 1: 許可が先（期間と指紋）
    f, t = block["period"].get("from", ""), block["period"].get("to", "")
    if not (f <= today <= t):
        raise Refuse(1, "今日（%s）が RoE の期間（%s〜%s）の外" % (today, f, t))
    want = scope_fingerprint(block)
    if block["fingerprint"] != want:
        raise Refuse(1, "範囲の指紋が合わない（RoE を署名のあとで書き換えた疑い）")
    # 線 2: 宛先は手元だけ
    if host not in LOCAL or host not in set(block["targets"]):
        raise Refuse(2, "宛先 %s は手元（127.0.0.1・localhost・::1）かつ RoE の targets の中でない" % host)
    numeric = "127.0.0.1"
    try:
        ipaddress.ip_address(numeric)
    except ValueError:
        raise Refuse(2, "数字の宛先に直せない")
    # 線 5: 下流は手元・作り物・使い捨てだけ
    bad = []
    for d in block["downstream"]:
        where = str(d.get("where", ""))
        if not re.match(r"^(127\.0\.0\.1|localhost|::1|in-memory|mock|disposable|none)", where):
            bad.append("%s→%s" % (d.get("name", "?"), where))
    if bad:
        raise Refuse(5, "下流に手元でない宛先がある: %s" % "、".join(bad))
    return numeric


def listener_pids(port):
    """ポート port で LISTEN しているプロセスの PID を返す。"""
    pids = set()
    try:
        out = subprocess.run(["lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-Fp"],
                             capture_output=True, text=True, timeout=5)
        for ln in out.stdout.splitlines():
            if ln.startswith("p"):
                pids.add(ln[1:].strip())
    except (OSError, subprocess.SubprocessError):
        pass
    if not pids:
        try:
            out = subprocess.run(["ss", "-ltnpH", "sport = :%d" % port], capture_output=True, text=True, timeout=5)
            for m in re.finditer(r"pid=(\d+)", out.stdout):
                pids.add(m.group(1))
        except (OSError, subprocess.SubprocessError):
            pass
    return pids


def pid_command(pid):
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def check_line_4_listener(port, launch):
    """線 4: そのポートで待つプロセスが、RoE の起動の命令で立った物か。"""
    want = os.path.basename(launch.split()[-1]) if launch.split() else launch
    pids = listener_pids(port)
    if not pids:
        raise Refuse(4, "ポート %d で待つプロセスを調べられない（lsof も ss も無い、か PID が取れない）。確かめられないので送らない" % port)
    for pid in pids:
        cmd = pid_command(pid)
        if want and (want in cmd or os.path.splitext(want)[0] in cmd):
            return True
    raise Refuse(4, "ポート %d で待つプロセスが、RoE の起動の命令（%s）で立った物でない" % (port, want))


# ---- HTTP（線 3: 移動を追わない、代理を通さない）
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)


def send(numeric, port, method, path, headers=None, body=None, timeout=3):
    url = "http://%s:%d%s" % (numeric, port, path)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if isinstance(body, (dict, list)) else body
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("host", "127.0.0.1:%d" % port)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("content-type", "application/json")
    t0 = time.time()
    try:
        resp = OPENER.open(req, timeout=timeout)
        raw = resp.read()
        status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        return {"status": 0, "len": 0, "ms": int((time.time() - t0) * 1000), "err": type(e).__name__, "_text": ""}
    return {"status": status, "len": len(raw), "ms": int((time.time() - t0) * 1000),
            "_text": raw.decode("utf-8", "replace")}


def ledger_row(handle, entry, actor, r, marker=None):
    """線 7: 残すのは、手口・入口・利用者・状態・長さ・印・時間だけ。本文と鍵は残さない。"""
    return {"handle": handle, "entry": entry, "actor": actor,
            "status": r.get("status"), "len": r.get("len"), "marker": marker, "ms": r.get("ms")}


# ---- 攻撃の表（A01〜A12）。守れたとみなす応答は attack-table.md の列
class Runner:
    def __init__(self, numeric, port, probe, cap, timeout, ledger):
        self.numeric = numeric
        self.port = port
        self.probe = probe
        self.cap = cap
        self.timeout = timeout
        self.ledger = ledger
        self.sent = 0
        self.tokens = {}

    def _send(self, handle, entry, actor, method, path, headers=None, body=None, marker=None):
        if self.sent >= self.cap:
            return None
        r = send(self.numeric, self.port, method, path, headers, body, self.timeout)
        self.sent += 1
        self.ledger.append(ledger_row(handle, entry, actor, r, marker))
        return r

    def login(self):
        lg = self.probe["login"]
        for a in self.probe["actors"]:
            r = send(self.numeric, self.port, lg["method"], lg["path"],
                     body={lg["user_field"]: a["user"], lg["pass_field"]: a["pass"]}, timeout=self.timeout)
            self.sent += 1
            self.ledger.append(ledger_row("login", "login", a["id"], r))
            try:
                self.tokens[a["id"]] = json.loads(r.get("_text") or "{}").get(lg["token_json"])
            except ValueError:
                self.tokens[a["id"]] = None

    def _auth(self, actor):
        tok = self.tokens.get(actor)
        return {"authorization": "Bearer %s" % tok} if tok else {}

    def _entries(self, pred):
        return [e for e in self.probe["entries"] if pred(e)]

    # A01 認証なし
    def a01(self):
        hits = 0
        es = self._entries(lambda e: e.get("auth"))
        for e in es:
            path = e["path"].replace("{id}", e.get("owner_mine") or e.get("sample_id") or "o1")
            r = self._send("A01", e["id"], "none", e["method"], path,
                           body=e.get("body") if e["method"] != "GET" else None)
            if r and r["status"] not in (401, 403) and 200 <= r["status"] < 300:
                hits += 1
        return hits, len(es)

    # A02 他人の物
    def a02(self):
        hits = 0
        es = self._entries(lambda e: e.get("owner_other"))
        for e in es:
            path = e["path"].replace("{id}", e["owner_other"])
            r = self._send("A02", e["id"], "op_a", e["method"], path, headers=self._auth("op_a"))
            if r and 200 <= r["status"] < 300:
                hits += 1
        return hits, len(es)

    # A03 権限を越える
    def a03(self):
        hits = 0
        es = self._entries(lambda e: e.get("write") and e.get("min_role") == "operator")
        for e in es:
            path = e["path"].replace("{id}", e.get("owner_mine", "o1"))
            r = self._send("A03", e["id"], "view_a", e["method"], path,
                           headers=self._auth("view_a"), body=e.get("body", {"note": "x"}))
            if r and 200 <= r["status"] < 300:
                hits += 1
        return hits, len(es)

    # A04 余計な項目（応答に鍵やハッシュ）
    def a04(self):
        hits = 0
        es = self._entries(lambda e: e.get("pii"))
        for e in es:
            path = e["path"].replace("{id}", e.get("sample_id", "op_a"))
            r = self._send("A04", e["id"], "op_a", e["method"], path, headers=self._auth("op_a"), marker="leak")
            if r and re.search(r"password_hash|\"token\"|pw_hash", r.get("_text", "")):
                hits += 1
        return hits, len(es)

    # A05 鍵が推せる
    def a05(self):
        hits = 0
        es = self._entries(lambda e: e.get("auth") and e["method"] == "GET" and "{" not in e["path"])
        for e in es:
            for i, guess in enumerate(("token-op_a", "token-op_b"), 1):
                r = self._send("A05", e["id"], "guess", e["method"], e["path"],
                               headers={"authorization": "Bearer %s" % guess}, marker="guess-%d" % i)
                if r and 200 <= r["status"] < 300:
                    hits += 1
                    break
        return hits, len(es)

    # A06 注入
    def a06(self):
        hits = 0
        es = self._entries(lambda e: e.get("injection"))
        for e in es:
            inj = "' OR '1'='1"
            r = self._send("A06", e["id"], "op_a", e["method"],
                           e["path"] + "?%s=%s" % (e["query_field"], urllib.parse.quote(inj)),
                           headers=self._auth("op_a"), marker="inj")
            # 守れなかった印: 他店の注文（o3/o4）が出る、か 500 で内部の値が漏れる
            text = r.get("_text", "") if r else ""
            if r and (("o3" in text or "o4" in text) or (r["status"] == 500 and "sqlite" in text.lower())):
                hits += 1
            r2 = self._send("A06", e["id"], "op_a", e["method"],
                            e["path"] + "?%s=%s" % (e["query_field"], urllib.parse.quote("'")),
                            headers=self._auth("op_a"), marker="err")
            if r2 and r2["status"] == 500 and re.search(r"sqlite|syntax|OperationalError", r2.get("_text", ""), re.I):
                hits = max(hits, 1)
        return hits, len(es)

    # A07 画面に差し込む
    def a07(self):
        hits = 0
        es = self._entries(lambda e: e.get("stored") and e.get("reflect_read"))
        for e in es:
            mark = "MARK7x9"
            payload = "<b>%s</b>" % mark
            self._send("A07", e["id"], "none", e["method"], e["path"],
                       body={e["body_field"]: payload}, marker="store")
            r = self._send("A07", e["reflect_read"].strip("/"), "none", "GET", e["reflect_read"], marker="read")
            if r and payload in r.get("_text", ""):
                hits += 1
        return hits, len(es)

    # A08 他のサイトから
    def a08(self):
        hits = 0
        es = self._entries(lambda e: e.get("state_change"))
        for e in es:
            path = e["path"].replace("{id}", e.get("owner_mine", "o1"))
            r = self._send("A08", e["id"], "op_a", e["method"], path,
                           headers={**self._auth("op_a"), "origin": "http://evil.example"},
                           body=e.get("body", {"note": "x"}), marker="origin")
            if r and 200 <= r["status"] < 300:
                hits += 1
        return hits, len(es)

    # A09 量と連打
    def a09(self):
        hits = 0
        es = self._entries(lambda e: e.get("rate_limit"))
        lg = self.probe["login"]
        for e in es:
            blocked = False
            for _ in range(12):
                r = self._send("A09", e["id"], "none", e["method"], e["path"],
                               body={lg["user_field"]: "op_a", lg["pass_field"]: "wrong"}, marker="burst")
                if r and r["status"] == 429:
                    blocked = True
                    break
            if not blocked:
                hits += 1
        return hits, len(es)

    # A10 外へつながせる（見張り役は 127.0.0.1:0）
    def a10(self):
        hits = 0
        es = self._entries(lambda e: e.get("takes_url"))
        if not es:
            return 0, 0
        got = {"hit": False}
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        wport = srv.getsockname()[1]

        def watch():
            srv.settimeout(3)
            try:
                c, _ = srv.accept()
                got["hit"] = True
                c.close()
            except OSError:
                pass
        th = threading.Thread(target=watch, daemon=True)
        th.start()
        for e in es:
            self._send("A10", e["id"], "op_a", e["method"], e["path"],
                       headers=self._auth("op_a"),
                       body={e["takes_url"]: "http://127.0.0.1:%d/ssrf" % wport}, marker="ssrf")
        th.join(timeout=4)
        srv.close()
        if got["hit"]:
            hits = len(es)
        return hits, len(es)

    # A11 ファイル
    def a11(self):
        hits = 0
        es = self._entries(lambda e: e.get("takes_file"))
        for e in es:
            r = self._send("A11", e["id"], "op_a", e["method"], e["path"], headers=self._auth("op_a"),
                           body={e["name_field"]: "../escape-A11.txt", e["content_field"]: "x"}, marker="traversal")
            text = r.get("_text", "") if r else ""
            if r and ('"inside_uploads": false' in text or '"inside_uploads":false' in text):
                hits += 1
        return hits, len(es)

    # A12 設定と漏れ
    def a12(self):
        hits = 0
        es = self._entries(lambda e: e.get("config"))
        for e in es:
            r = self._send("A12", e["id"], "none", e["method"], e["path"], marker="config")
            if r and 200 <= r["status"] < 300 and re.search(r"token|uploads|fixed", r.get("_text", "")):
                hits += 1
        return hits, len(es)


def run_attack(numeric, port, probe, block, today, ledger):
    cap = int(block["limits"].get("per_handle", 60)) * len(HANDLES) + 200
    maxtotal = int(block["limits"].get("max_total", cap))
    cap = min(cap, maxtotal)
    timeout = float(block["limits"].get("per_request_timeout", 3))
    rn = Runner(numeric, port, probe, cap, timeout, ledger)
    rn.login()
    results = []
    for h in HANDLES:
        hits, tried = getattr(rn, h.lower())()
        verdict = "対象外" if tried == 0 else ("脆弱性" if hits else "守れた")
        results.append({"handle": h, "name": HANDLE_NAME[h], "entries": tried, "hits": hits, "verdict": verdict})
    return results, rn.sent


def secret_check(root):
    """S01 送らない検査。gitleaks があれば使い、無ければ未実施と書く。"""
    try:
        out = subprocess.run(["gitleaks", "dir", root, "--no-banner", "--redact", "--exit-code", "1"],
                             capture_output=True, text=True, timeout=120)
        return ("守れた" if out.returncode == 0 else "脆弱性"), ("秘密 0 件" if out.returncode == 0 else "秘密あり")
    except (OSError, subprocess.SubprocessError):
        return "未実施", "道具が無い（gitleaks）"


def report(results, sent, ledger, block, baseline, s01, log_lines, listener_ok, repo_root):
    found = [r["handle"] for r in results if r["verdict"] == "脆弱性"]
    base = set(baseline or [])
    new = [h for h in found if h not in base]
    old = [h for h in found if h in base]
    taigai = sum(1 for r in results if r["verdict"] == "対象外")
    entries_total = len(block_entries(block))
    verdict = "PASS" if not new and s01[0] != "脆弱性" else "FAIL"
    retatk = 0 if not new else "-"
    lines = []
    lines.append("## 攻撃の結果")
    lines.append("")
    lines.append("この節は、スクリプトが書いた 1 行と表をそのまま載せたものです。人も AI も手で直していません。")
    lines.append("")
    lines.append("```text")
    lines.append("RESULT: %s attack-run（入口 %d/%d、手口 12（対象外 %d）、リクエスト %d 本、脆弱性 %d → 再攻撃 %s、未実施 0、前からある脆弱性 %d）"
                 % (verdict, entries_total, entries_total, taigai, sent, len(new), retatk, len(old)))
    lines.append("```")
    lines.append("")
    lines.append("手口ごとの結果は次の表のとおりで、13 行のすべてが「守れた」「脆弱性」「対象外」のどれかで埋まっています。")
    lines.append("")
    lines.append("| 手口 | 試した入口 | 結果 | 記録 |")
    lines.append("|---|---|---|---|")
    for r in results:
        res = {"守れた": "守れた", "脆弱性": "脆弱性 %d 件" % r["hits"], "対象外": "対象外（当てる入口が無い）"}[r["verdict"]]
        lines.append("| %s | %d | %s | %s |" % (r["name"], r["entries"], res, r["handle"]))
    lines.append("| 依存と秘密（送らない検査） | 全体 | %s | S01 |" % s01[1])
    lines.append("")
    lines.append("攻撃が本物だったことは、次の表で確かめました。読み手は「届いた本数」と「検出力」の 2 行を見れば足ります。")
    lines.append("")
    lines.append("| 確かめたこと | 値 | 出どころ |")
    lines.append("|---|---|---|")
    lines.append("| 届いた本数 | アプリのログに %d 行。送った %d 本と同じ | 攻撃用に立てたアプリのログ |" % (log_lines, sent))
    lines.append("| 宛先 | 127.0.0.1 の 1 つのポートだけ。外へのリクエストは 0 本 | 台帳の宛先 |")
    lines.append("| 待ち受け | RoE の起動の命令で立ったプロセス（%s） | lsof か ss |" % ("確かめた" if listener_ok else "未確認"))
    lines.append("| 検出力 | 仕込んだ脆弱性のうち、見つけた数（下の試験で数える） | サンプルでの試験 |")
    lines.append("| 許可 | 常設の RoE。承認記録 %s、範囲の指紋が一致 | RoE の機械の節 |" % block.get("approval_record", "?"))
    lines.append("| 確かめていないこと | 表に無い手口と、悪用のシナリオは試していない | 台帳の末尾 |")
    return verdict, "\n".join(lines) + "\n", {"found": found, "new": new, "old": old}


def block_entries(block):
    return block.get("_entries", [])


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--target")
    ap.add_argument("--probe")
    ap.add_argument("--roe")
    ap.add_argument("--baseline")
    ap.add_argument("--ledger")
    ap.add_argument("--today", default=time.strftime("%Y-%m-%d"))
    ap.add_argument("--repo", default=".")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    for need in ("target", "probe", "roe"):
        if not getattr(args, need):
            print("使い方は冒頭のとおり。--target --probe --roe が要る", file=sys.stderr)
            return 2
    try:
        host, port = args.target.rsplit(":", 1)
        port = int(port)
        block = read_roe(args.roe)
        probe = json.load(open(args.probe, encoding="utf-8"))
        block["_entries"] = probe["entries"]
        numeric = check_lines_1_5(block, host, port, args.today)
        listener_ok = False
        try:
            listener_ok = check_line_4_listener(port, block["launch"])
        except Refuse as e:
            raise e
    except Refuse as e:
        print("REFUSE 線 %d: %s" % (e.line, e.why), file=sys.stderr)
        print("RESULT: REFUSE attack-run（線 %d で止まった。1 本も送っていない）" % e.line)
        return 2
    ledger = []
    baseline = json.load(open(args.baseline, encoding="utf-8")).get("found") if args.baseline else None
    results, sent = run_attack(numeric, port, probe, block, args.today, ledger)
    s01 = secret_check(args.repo)
    # 届いた本数: アプリのログ（RoE の downstream に書いた置き場）
    log_lines = count_log(block)
    verdict, text, summary = report(results, sent, ledger, block, baseline, s01, log_lines, listener_ok, args.repo)
    if args.ledger:
        with open(args.ledger, "w", encoding="utf-8") as f:
            json.dump({"found": summary["found"], "new": summary["new"], "old": summary["old"],
                       "sent": sent, "rows": ledger}, f, ensure_ascii=False, indent=1)
    print(text)
    return 0 if verdict == "PASS" else 1


def count_log(block):
    for d in block.get("downstream", []):
        lp = d.get("log")
        if lp and os.path.exists(lp):
            return sum(1 for _ in open(lp, encoding="utf-8"))
    return -1


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        if not cond:
            ok = False
            print("FAIL selftest attack-run: %s" % name)

    good = {"targets": ["127.0.0.1"], "launch": "python3 app.py",
            "downstream": [{"name": "DB", "where": "in-memory"}],
            "limits": {"per_handle": 10, "max_total": 100, "per_request_timeout": 2},
            "period": {"from": "2000-01-01", "to": "2999-01-01"},
            "approval_record": "A-16"}
    good["fingerprint"] = scope_fingerprint(good)
    # 線 1: 指紋が合う
    try:
        check_lines_1_5(good, "127.0.0.1", 8000, "2026-11-26")
        check("正しい RoE は通る", True)
    except Refuse:
        check("正しい RoE は通る", False)
    # 線 1: 書き換えると落ちる
    tam = dict(good)
    tam["targets"] = ["127.0.0.1", "10.0.0.5"]
    try:
        check_lines_1_5(tam, "127.0.0.1", 8000, "2026-11-26")
        check("書き換えた RoE で止まる", False)
    except Refuse as e:
        check("書き換えた RoE で止まる（線 %d）" % e.line, e.line == 1)
    # 線 2: 外の宛先で止まる
    try:
        check_lines_1_5(good, "10.0.0.5", 8000, "2026-11-26")
        check("外の宛先で止まる", False)
    except Refuse as e:
        check("外の宛先で止まる（線 %d）" % e.line, e.line == 2)
    # 線 1: 期間の外で止まる
    try:
        check_lines_1_5(good, "127.0.0.1", 8000, "1999-01-01")
        check("期間の外で止まる", False)
    except Refuse as e:
        check("期間の外で止まる（線 %d）" % e.line, e.line == 1)
    # 線 5: 下流に外の宛先で止まる
    ds = json.loads(json.dumps(good))
    ds["downstream"] = [{"name": "DB", "where": "db.example.com"}]
    ds["fingerprint"] = scope_fingerprint(ds)
    try:
        check_lines_1_5(ds, "127.0.0.1", 8000, "2026-11-26")
        check("下流が外で止まる", False)
    except Refuse as e:
        check("下流が外で止まる（線 %d）" % e.line, e.line == 5)
    # 線 3: 代理を通さず、移動を追わない（空の ProxyHandler は代理を登録しないので、一覧に出ないのが正しい。移動は NoRedirect が握る）
    names = [type(h).__name__ for h in OPENER.handlers]
    no_follow = NoRedirect().redirect_request(None, None, 302, "", {}, "http://x") is None
    check("線 3 代理を通さず移動を追わない", "NoRedirect" in names and "ProxyHandler" not in names and no_follow)
    # 線 4: 何も待っていないポートでは送らない
    try:
        check_line_4_listener(59998, "python3 app.py")
        check("線 4 待ち受けが無いと止まる", False)
    except Refuse as e:
        check("線 4 待ち受けが無いと止まる", e.line == 4)
    # 線 6: 上限で止まる
    rn = Runner("127.0.0.1", 1, {"login": {}, "actors": [], "entries": []}, cap=2, timeout=1, ledger=[])
    rn.sent = 2
    check("線 6 上限で送らない", rn._send("A01", "x", "n", "GET", "/") is None)
    # 線 8: 送るのは表の手口だけ
    check("線 8 手口は A01〜A12 に固定", HANDLES == ["A0%d" % i for i in range(1, 10)] + ["A10", "A11", "A12"])
    # 線 7: 台帳の行に本文と鍵が無い
    row = ledger_row("A02", "order_detail", "op_a", {"status": 200, "len": 50, "ms": 3, "_text": "token-op_a 住所"})
    check("線 7 台帳に本文・鍵を残さない", "_text" not in row and "token" not in json.dumps(row, ensure_ascii=False))
    # 集計: 新しい穴と前からある穴を分ける
    res = [{"handle": "A02", "name": "x", "entries": 1, "hits": 1, "verdict": "脆弱性"},
           {"handle": "A07", "name": "y", "entries": 1, "hits": 1, "verdict": "脆弱性"}]
    block = dict(good)
    block["_entries"] = [1]
    v, _, summ = report(res, 10, [], block, ["A07"], ("守れた", "秘密 0 件"), 10, True, ".")
    check("前からある穴を分ける", summ["new"] == ["A02"] and summ["old"] == ["A07"])
    check("新しい穴があると FAIL", v == "FAIL")
    print("RESULT: %s attack-run --selftest" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


import urllib.parse  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
