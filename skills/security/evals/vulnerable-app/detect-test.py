#!/usr/bin/env python3
"""detect-test — 検知力の試験（S-3・S-6）。わざと穴を空けた見本に攻撃を送り、次の 3 つを確かめる。

  S-3: 穴のある版で、仕込んだ 12 件を全部見つける。ふさいだ版（--fixed）では 0 件。
  S-6: 送った本数と、アプリのログに届いた本数が同じ。
サーバーを立てるので、evals/run.sh（--full）から呼ぶ。scripts の --selftest（軽い）とは別。
使い方: detect-test.py   → PASS なら終了コード 0
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SKILL = HERE.parent.parent
ROOT = SKILL.parent.parent
APP = str(HERE / "app.py")
PROBE = str(HERE / "probe.json")
ATTACK = str(SKILL / "scripts" / "attack_run.py")
sys.path.insert(0, str(SKILL / "scripts"))
import attack_run as ar  # noqa: E402


def start(fixed, up, log):
    up.mkdir(parents=True, exist_ok=True)
    cmd = ["python3", APP] + (["--fixed"] if fixed else []) + ["--uploads", str(up), "--log", str(log)]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    port = int(re.search(r":(\d+)", p.stdout.readline()).group(1))
    p.stdout.readline()
    return p, port


def write_roe(tmp, log):
    block = {"targets": ["127.0.0.1"], "launch": "python3 %s" % APP,
             "downstream": [{"name": "DB", "where": "in-memory", "mode": "disposable"},
                            {"name": "log", "where": "disposable", "log": str(log)}],
             "limits": {"per_handle": 30, "max_total": 500, "per_request_timeout": 3, "total_timeout": 60},
             "period": {"from": "2000-01-01", "to": "2999-01-01"}, "approval_record": "A-16",
             "requester_quote": "進めて"}
    block["fingerprint"] = ar.scope_fingerprint(block)
    path = tmp / "roe.md"
    path.write_text("# 常設の RoE（試験）\n\n```json\n" + json.dumps(block, ensure_ascii=False, indent=1) + "\n```\n", encoding="utf-8")
    return str(path)


def one(fixed, tmp):
    up = tmp / ("fixed" if fixed else "vuln") / "up"
    log = tmp / ("fixed" if fixed else "vuln") / "requests.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    p, port = start(fixed, up, log)
    led = tmp / ("fixed" if fixed else "vuln") / "ledger.json"
    try:
        out = subprocess.run(["python3", "-I", ATTACK, "--target", "127.0.0.1:%d" % port,
                              "--probe", PROBE, "--roe", write_roe(tmp, log), "--ledger", str(led),
                              "--repo", str(ROOT)], capture_output=True, text=True, timeout=120)
    finally:
        p.terminate()
        p.wait()
    led_d = json.loads(led.read_text()) if led.exists() else {"found": [], "rows": []}
    delivered = sum(1 for _ in open(log, encoding="utf-8")) if log.exists() else -1
    return led_d, delivered, out.stdout


def main():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("PASS" if cond else "FAIL") + " detect-test " + name)
        if not cond:
            ok = False
    with tempfile.TemporaryDirectory(prefix="detect-") as t:
        tmp = pathlib.Path(t)
        vuln, v_deliv, _ = one(False, tmp)
        fixed, f_deliv, _ = one(True, tmp)
        v_found = vuln.get("found", [])
        f_found = fixed.get("found", [])
        check("穴のある版で 12 件を見つける（検出力 %d/12）" % len(v_found), len(v_found) == 12)
        check("ふさいだ版で 0 件（残り %s）" % f_found, len(f_found) == 0)
        check("穴のある版: 送った本数 %d と届いた本数 %d が同じ" % (len(vuln.get("rows", [])), v_deliv),
              len(vuln.get("rows", [])) == v_deliv and v_deliv > 0)
        check("ふさいだ版: 送った本数 %d と届いた本数 %d が同じ" % (len(fixed.get("rows", [])), f_deliv),
              len(fixed.get("rows", [])) == f_deliv and f_deliv > 0)
        # 線 7: 台帳に秘密や余計な欄が無い（attack-check で見る）
        for tag in ("vuln", "fixed"):
            led = tmp / tag / "ledger.json"
            chk = subprocess.run(["python3", "-I", str(SKILL / "scripts" / "attack_check.py"), str(led)],
                                 capture_output=True, text=True)
            check("%s の台帳が attack-check を通る（線 7）" % tag, chk.returncode == 0)
    print("RESULT: %s detect-test" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
