#!/usr/bin/env python3
"""restore_drill — バックアップから復元し、所要時間を実測する訓練（sqlite3。外の物には頼らない）。

手順: 1 合成（架空の注文を N 行、種を固定して作る） 2 基準（行数と中身の指紋 sha256） 3 バックアップ（オンラインの複製と目録）
      4 事故（元のデータベースを消す） 5 復元と照合（指紋の確認 → 復元 → 整合の検査 → 行数 → 中身）。5 の秒を復元の実測とする。
使い方: restore_drill.py [--rows N] [--seed S] [--rto 秒] [--json <記録の置き場>]   /   restore_drill.py --selftest
出力: INFO と PASS/FAIL の行、最後に RESULT: PASS|FAIL restore-drill (行 N、復元 X 秒、…)。1 件でも FAIL なら終了コード 1。
注意: 測るのは手元の sqlite3 での手順の時間で、クラウドのデータベースの復元時間ではない。本番相当は検証環境で同じ手順を測る。
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import random
import shutil
import sqlite3
import sys
import tempfile
import time

STATUSES = ["未出荷"] * 6 + ["要対応", "出荷指示済み", "出荷済み", "取消済み"]
CARRIERS = ["ヤマト", "佐川", "日本郵便"]
PAYMENTS = ["カード", "代引き", "後払い", "銀行振込"]
STAFF = ["高木", "森", "石井", "小野", "上田", None]
FAMILY = ["北川", "大塚", "中島", "山本", "佐藤", "鈴木", "田中", "伊藤", "渡辺", "小林"]
GIVEN = ["修", "美咲", "ゆかり", "健", "陽子", "翔", "愛", "誠", "真央", "大輔"]
SCHEMA = """
CREATE TABLE orders (
  id INTEGER PRIMARY KEY,
  order_no TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  customer TEXT NOT NULL,
  amount INTEGER NOT NULL,
  carrier TEXT NOT NULL,
  payment TEXT NOT NULL,
  staff TEXT,
  ordered_at TEXT NOT NULL
);
CREATE INDEX orders_status_ordered ON orders (status, ordered_at);
"""


def synth(path, rows, seed):
    rnd = random.Random(seed)
    base = datetime.datetime(2026, 10, 1, 0, 0)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    batch = []
    for i in range(1, rows + 1):
        at = base + datetime.timedelta(minutes=rnd.randrange(0, 60 * 24 * 37))
        batch.append((i, f"{500000 + i}", rnd.choice(STATUSES), f"{rnd.choice(FAMILY)} {rnd.choice(GIVEN)}",
                      rnd.randrange(980, 48000), rnd.choice(CARRIERS), rnd.choice(PAYMENTS), rnd.choice(STAFF),
                      at.strftime("%Y-%m-%d %H:%M")))
        if len(batch) == 5000:
            con.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)", batch)
            batch = []
    if batch:
        con.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)", batch)
    con.commit()
    con.close()


def fingerprint(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    h = hashlib.sha256()
    n = 0
    for row in con.execute("SELECT * FROM orders ORDER BY id"):
        h.update(repr(row).encode("utf-8"))
        n += 1
    con.close()
    return n, h.hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def online_copy(src, dst):
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    s.backup(d)
    d.close()
    s.close()


def drill(rows, seed, rto, fault=None, out=print):
    """訓練を 1 回回す。fault は自己試験用（tamper: 複製の中身を変える、loss: 復元で 1 行落とす、missing: 複製が無い）。"""
    work = pathlib.Path(tempfile.mkdtemp(prefix="restore-drill-"))
    fails = []

    def fail(rule, msg):
        fails.append(rule)
        out(f"FAIL restore-drill [{rule}] {msg}")

    try:
        live, bdir = work / "live" / "orders.db", work / "backup"
        live.parent.mkdir()
        bdir.mkdir()
        t0 = time.perf_counter()
        synth(live, rows, seed)
        t_synth = time.perf_counter() - t0
        n0, d0 = fingerprint(live)
        out(f"INFO 合成 {n0} 行（種 {seed}）{t_synth:.2f} 秒")

        t0 = time.perf_counter()
        bfile = bdir / "orders-backup.db"
        online_copy(live, bfile)
        manifest = {"rows": n0, "digest": d0, "file_sha256": file_sha(bfile), "taken_at": datetime.datetime.now().isoformat(timespec="seconds")}
        (bdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        t_backup = time.perf_counter() - t0
        size_mb = bfile.stat().st_size / 1e6
        out(f"INFO バックアップ {size_mb:.1f} MB {t_backup:.2f} 秒")

        if fault == "tamper":
            con = sqlite3.connect(bfile)
            con.execute("UPDATE orders SET amount = amount + 1 WHERE id = 1")
            con.commit()
            con.close()
            manifest["file_sha256"] = file_sha(bfile)  # 目録ごと書き換えられた場合。中身の照合でしか見つからない
            (bdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        if fault == "missing":
            bfile.unlink()

        # 事故: 元のデータベースを消す
        shutil.rmtree(live.parent)
        out("INFO 事故 元のデータベースを消した")

        # 復元と照合（ここからが実測）
        t0 = time.perf_counter()
        restored = work / "restored" / "orders.db"
        restored.parent.mkdir()
        if not bfile.exists():
            fail("バックアップが無い", f"{bfile.name} が見つからない")
            elapsed = time.perf_counter() - t0
        else:
            man = json.loads((bdir / "manifest.json").read_text(encoding="utf-8"))
            if file_sha(bfile) != man["file_sha256"]:
                fail("バックアップの指紋", "複製のファイルの sha256 が目録と違う")
            online_copy(bfile, restored)
            con = sqlite3.connect(restored)
            if fault == "loss":
                con.execute("DELETE FROM orders WHERE id = (SELECT MAX(id) FROM orders)")
                con.commit()
            ic = con.execute("PRAGMA integrity_check").fetchone()[0]
            con.close()
            if ic != "ok":
                fail("整合", f"integrity_check が {ic}")
            n1, d1 = fingerprint(restored)
            elapsed = time.perf_counter() - t0
            if n1 != n0:
                fail("行数", f"復元 {n1} 行、元 {n0} 行")
            else:
                out(f"PASS restore-drill [行数] {n1} 行が元と一致")
            if d1 != d0:
                fail("中身", "中身の指紋（sha256）が元と違う")
            else:
                out(f"PASS restore-drill [中身] 指紋 {d1[:12]}… が元と一致")
        if rto is not None and elapsed > rto:
            fail("RTO", f"復元 {elapsed:.2f} 秒が目標 {rto:g} 秒を超えた")
        rto_note = f"、RTO 目標 {rto:g} 秒" if rto is not None else ""
        verdict = "PASS" if not fails else "FAIL"
        out(f"RESULT: {verdict} restore-drill (行 {n0}、バックアップ {t_backup:.2f} 秒、復元と照合 {elapsed:.2f} 秒{rto_note})")
        record = {"rows": n0, "seed": seed, "synth_sec": round(t_synth, 3), "backup_sec": round(t_backup, 3),
                  "restore_sec": round(elapsed, 3), "backup_mb": round(size_mb, 1), "result": verdict, "fails": fails,
                  "measured_at": datetime.datetime.now().isoformat(timespec="seconds"),
                  "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version}
        return not fails, fails, record
    finally:
        shutil.rmtree(work, ignore_errors=True)


def selftest():
    checks = []
    sink = []
    ok, fails, _ = drill(2000, 7, None, out=sink.append)
    checks.append((ok, f"正例（2000 行）が落ちた: {sink[-3:]}"))
    ok, fails, _ = drill(2000, 7, None, fault="tamper", out=sink.append)
    checks.append((not ok and "中身" in fails, f"複製の中身を変えても通った: {fails}"))
    ok, fails, _ = drill(2000, 7, None, fault="loss", out=sink.append)
    checks.append((not ok and "行数" in fails, f"復元で行が欠けても通った: {fails}"))
    ok, fails, _ = drill(2000, 7, None, fault="missing", out=sink.append)
    checks.append((not ok and "バックアップが無い" in fails, f"複製が無くても通った: {fails}"))
    ok, fails, _ = drill(2000, 7, 0.0, out=sink.append)
    checks.append((not ok and "RTO" in fails, f"RTO 0 秒を超えても通った: {fails}"))
    good = True
    for passed, msg in checks:
        if not passed:
            good = False
            print(f"FAIL selftest restore-drill: {msg}")
    print(f"RESULT: {'PASS' if good else 'FAIL'} restore-drill --selftest ({len(checks)} 例)")
    return good


def main(argv):
    if argv and argv[0] == "--selftest":
        return 0 if selftest() else 1
    ap = argparse.ArgumentParser(prog="restore-drill.sh", add_help=True)
    ap.add_argument("--rows", type=int, default=100000)
    ap.add_argument("--seed", type=int, default=20261107)
    ap.add_argument("--rto", type=float, default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    if a.rows < 1:
        print("FAIL restore-drill [引数] --rows は 1 以上")
        return 2
    ok, _, record = drill(a.rows, a.seed, a.rto)
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        pathlib.Path(a.json).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"INFO 記録 {a.json}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
