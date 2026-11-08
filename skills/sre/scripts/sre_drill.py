#!/usr/bin/env python3
"""sre_drill — 手元の見本の API（samples/api の写し）を当番の命令で扱う道具と、Runbook の訓練。標準の python3 だけで動く。

使い方: sre_drill.py api copy|start [--orders N]|stop|status|probe [--count N] [--threshold-ms 50]|tally [--last N]|pid|rebuild
            環境の変数: API_DIR（写しの置き場。既定 tmp/flow/stage5/api）、RUN（ログと pid。既定 tmp/flow/stage5/run）、
                        PORT（既定 8080）、SRC（正本。既定 samples/api）、KEYS（鍵の file。既定 RUN/keys.txt）。
                        写しが samples/ の中なら断る（正本で壊さない）
            pid の記録（RUN/api.pid）が無くても、PORT で待ち受ける写しの server.py を見つけて扱う（手で立てた API も止められる）。
            鍵は KEYS、RUN/keys.txt、RUN/keys.* の順に探す。rebuild は正本の 4 つの file と決めた設定で写しを作り直す
            start は、動いている API に道具の鍵で入れない（鍵が無いか 401）とき、道具で立て直して鍵を作り直す（REKEY）
        sre_drill.py drill <runbook.md>... [--keep] [--only table|outside|alt]
            Runbook の「原因の見分け方」の表の原因ごとに、使い捨ての写しで障害を起こし、Runbook のコードだけで直るかを確かめる:
            正常の確かめ → 注入 → 症状（probe が BAD）→「確かめる命令」の出力に表の印 →「直す命令」の原因の節 →
            「直ったことの確かめ」が終了コード 0 → probe が GOOD。注入は使い捨ての写しと 127.0.0.1 の空いたポートだけに向ける
            Runbook ごとに 2 件を足す。表の外（outside）と、出題役が道具の外の起動の命令で立てた別の起動（alt。鍵は
            RUN/drill-<PORT>.out で、道具は読まない）。「直ったことの確かめ」は道具の命令（sample-api.sh probe・status・
            tally・pid）だけに限り、外れた Runbook は訓練せずに [確かめの道具] で落とす
        sre_drill.py <api|drill> --selftest
        sre_drill.py hammer --threads N    （訓練の注入の部品。KEYS の鍵で一覧を連打する一括の道具の写し）
出力: 行ごとの結果と MEASURE、最後に RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
鍵: 見本の server.py が起動のたびに乱数で作る作り物の鍵を、RUN/keys.txt（権限 600）に受け、stop で消す。
    道具が立てたら、RUN/keys.* に残った古い鍵の file を消し、鍵の置き場を KEYS の 1 つにする。
"""
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
SKILL = HERE.parent
ROOT = SKILL.parent.parent
SAMPLES = ROOT / "samples"
AGREED_ORDERS = 29  # 決めた起動の設定（見本の画面と同じ 29 行）
THRESHOLD_MS = 50.0  # 遅さの SLI の閾値（架空。SLO 定義書と同じ値）
FILES = ("orders_api.py", "server.py", "seed-orders.json", "db-access.json")
ANCHOR = '        self.conn.execute("COMMIT")\n        self.lock, self.log_lock = '


def env():
    def path(name, default):
        v = os.environ.get(name) or default
        p = pathlib.Path(v)
        return (p if p.is_absolute() else pathlib.Path.cwd() / p).resolve()
    e = {"API_DIR": path("API_DIR", str(ROOT / "tmp/flow/stage5/api")), "RUN": path("RUN", str(ROOT / "tmp/flow/stage5/run")),
         "SRC": path("SRC", str(SAMPLES / "api")), "PORT": int(os.environ.get("PORT") or 8080)}
    e["KEYS"] = path("KEYS", str(e["RUN"] / "keys.txt"))
    if SAMPLES.resolve() in (e["API_DIR"], *e["API_DIR"].parents) or SAMPLES.resolve() in (e["RUN"], *e["RUN"].parents):
        print(f"REFUSE API_DIR と RUN は samples/ の外の写しにする（{e['API_DIR']}）")
        sys.exit(2)
    return e


def alive(pid):
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    stat = ps(pid, "stat")
    return bool(stat) and "Z" not in stat  # 止めた子のプロセスの残り（ゾンビ）と、消えたばかりのプロセスは動いていないとみる


def ps(pid, field):
    r = subprocess.run(["ps", "-o", f"{field}=", "-p", str(pid)], capture_output=True, text=True)
    return r.stdout.strip()


def short(cmd):
    """命令の行を、解釈系の長いパスを除いて見せる"""
    head, _, rest = cmd.partition(" ")
    rest = re.sub(r"\S*/(server\.py)", r"\1", rest)
    return f"{os.path.basename(head)} {rest}"[:100]


def read_pid(f):
    try:
        return int(f.read_text().strip())
    except (OSError, ValueError):
        return None


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def keys_path(e):
    """鍵の file。KEYS（既定 RUN/keys.txt）に無ければ、RUN/keys.* のうち鍵の行がある最初の file"""
    run = e["RUN"]
    cands = [e.get("KEYS") or run / "keys.txt", run / "keys.txt"] + (sorted(run.glob("keys*")) if run.is_dir() else [])
    for f in cands:
        try:
            if "u-takagi:" in f.read_text(encoding="utf-8", errors="replace"):
                return f
        except OSError:
            pass
    return None


def key_works(e):
    """道具の鍵の置き場の鍵で、動いている API に入れるか。鍵が無いか 401 のときだけ False（遅い・500・応えないは鍵の問題でない）"""
    k = key(e)
    if not k:
        return False
    req = urllib.request.Request(f"http://127.0.0.1:{e['PORT']}/v1/orders", headers={"Authorization": f"Bearer {k}"})
    try:
        with urllib.request.urlopen(req, timeout=2.0) as r:
            r.read()
        return True
    except urllib.error.HTTPError as x:
        return x.code != 401
    except (OSError, urllib.error.URLError):
        return True


def listeners(port):
    r = subprocess.run(["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True)
    return [int(x) for x in r.stdout.split()]


def in_copy(pid, e):
    """pid が写し（API_DIR）の server.py か。命令の相対パスは、そのプロセスの作業ディレクトリから解く"""
    cmd = ps(pid, "command")
    tok = next((x for x in cmd.split() if x.endswith("server.py")), None)
    if not tok:
        return False
    f = pathlib.Path(tok)
    if not f.is_absolute():
        r = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True)
        cwd = next((x[1:] for x in r.stdout.splitlines() if x.startswith("n")), None)
        if not cwd:
            return False
        f = pathlib.Path(cwd) / f
    try:
        return f.resolve().parent == e["API_DIR"].resolve()
    except OSError:
        return False


def find_api(e):
    """写しの API の pid と、見つけた道（record=RUN/api.pid、listen=PORT の待ち受け）。無ければ (None, None)"""
    pid = read_pid(e["RUN"] / "api.pid")
    if pid and alive(pid) and "server.py" in ps(pid, "command"):
        return pid, "record"
    for lp in listeners(e["PORT"]):
        if in_copy(lp, e):
            return lp, "listen"
    return None, None


# ---- api
def api_copy(e):
    e["API_DIR"].mkdir(parents=True, exist_ok=True)
    for f in FILES:
        shutil.copy2(e["SRC"] / f, e["API_DIR"] / f)
    print(f"COPIED {len(FILES)} 個 {e['SRC']} → {e['API_DIR']}")
    return 0


def api_start(e, orders=AGREED_ORDERS, wait_s=90):
    run = e["RUN"]
    run.mkdir(parents=True, exist_ok=True)
    pidf = run / "api.pid"
    old, how = find_api(e)
    if old and key_works(e):
        pidf.write_text(str(old))
        print(f"ALREADY pid={old}" + ("（pid の記録が無かったので待ち受けから見つけ、api.pid に書いた）" if how == "listen" else ""))
        return 0
    if old:
        print(f"REKEY pid={old} に道具の鍵（KEYS・RUN/keys.*）で入れない。道具の外で立てた API とみて、道具で立て直し、鍵を作り直す")
        api_stop(e)
    keys = e["KEYS"]
    keys.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(keys, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    log = open(run / "api.log", "a", encoding="utf-8")
    p = subprocess.Popen([sys.executable, str(e["API_DIR"] / "server.py"), "--port", str(e["PORT"]), "--orders", str(orders)],
                         stdin=subprocess.DEVNULL, stdout=fd, stderr=log, cwd=str(e["API_DIR"]), start_new_session=True)
    os.close(fd)
    log.close()
    pidf.write_text(str(p.pid))
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        if "u-kobayashi:" in keys.read_text(encoding="utf-8", errors="replace"):
            stale = [f for f in sorted(run.glob("keys*")) if f.is_file() and f.resolve() != keys.resolve()
                     and "u-takagi:" in f.read_text(encoding="utf-8", errors="replace")]
            for f in stale:  # 鍵の置き場を KEYS の 1 つにする。古い起動の鍵は、この起動では使えない
                f.unlink(missing_ok=True)
            print(f"STARTED pid={p.pid} port={e['PORT']} orders={orders} keys={keys}"
                  + (f"（古い鍵の file {len(stale)} 個を消した）" if stale else ""))
            return 0
        if p.poll() is not None:
            break
        time.sleep(0.1)
    if p.poll() is None:
        p.kill()
    pidf.unlink(missing_ok=True)
    keys.unlink(missing_ok=True)
    print(f"FAILED 起動できなかった（終了コード {p.poll()}）。ログの最後:")
    for line in tail_errors(run / "api.log", 3):
        print(f"  {line}")
    if listeners(e["PORT"]):
        print(f"HINT port={e['PORT']} を別のプロセスが待ち受けている。status の LISTEN の行を見る")
    return 1


def api_stop(e):
    pidf, keys = e["RUN"] / "api.pid", e["KEYS"]
    pid, how = find_api(e)
    if pid:
        os.kill(pid, signal.SIGCONT)
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            if not alive(pid):
                break
            time.sleep(0.1)
        if alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        print(f"STOPPED pid={pid}" + ("（pid の記録が無く、待ち受けから見つけた）" if how == "listen" else ""))
    else:
        print("STOPPED（動いている API は無かった）")
    pidf.unlink(missing_ok=True)
    keys.unlink(missing_ok=True)
    return 0


def tail_errors(log, n):
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
    except OSError:
        return []
    return [x for x in lines if x.strip() and not x.startswith("{")][-n:]


def api_status(e):
    run, port = e["RUN"], e["PORT"]
    pid, how = find_api(e)
    rec = read_pid(run / "api.pid")
    args = ""
    if pid is None and rec is not None:
        print(f"API pid={rec} state=dead（記録の pid は動いていない）")
    elif pid is None:
        print(f"API state=none（pid の記録も、port={port} で待ち受ける写しの server.py も無い）")
    else:
        stat, args = ps(pid, "stat"), ps(pid, "command")
        src = "record" if how == "record" else "listen（pid の記録が無く、待ち受けから見つけた）"
        print(f"API pid={pid} state={'stopped' if 'T' in stat else 'running'} stat={stat} from={src} command={short(args)}")
        m = re.search(r"--orders\s+(\d+)", args)
        n = int(m.group(1)) if m else AGREED_ORDERS
        print(f"CONFIG orders={n} agreed={AGREED_ORDERS} {'same' if n == AGREED_ORDERS else 'differ'}")
    pids = listeners(port)
    if not pids:
        print(f"LISTEN port={port} none")
    for lp in pids:
        print(f"LISTEN port={port} pid={lp} ours={'yes' if lp == pid else 'no'} command={short(ps(lp, 'command'))}")
    for f in FILES[:3]:
        mine, src = e["API_DIR"] / f, e["SRC"] / f
        if not os.access(mine, os.R_OK):
            print(f"FILE {f} unreadable")
        else:
            print(f"FILE {f} {'same' if sha(mine) == sha(src) else 'differ'}")
    print(seed_line(e))
    k = keys_path(e)
    print(f"KEYS {'file=' + str(k) if k else 'none（KEYS・RUN/keys.txt・RUN/keys.* に鍵の行が無い。probe は 401 になる。start が道具で立て直して鍵を作り直す）'}")
    for line in tail_errors(run / "api.log", 2):
        print(f"LOG {line[:160]}")
    return 0


def json_diff(a, b, path=""):
    """2 つの JSON の違う値を (場所, 写しの値, 正本の値) で返す。id のある辞書の並びは id で突き合わせる"""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            out += json_diff(a.get(k), b.get(k), f"{path}.{k}" if path else str(k))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if all(isinstance(x, dict) and "id" in x for x in a + b):
            ia, ib = {str(x["id"]): x for x in a}, {str(x["id"]): x for x in b}
            out = []
            for i in list(ib) + [i for i in ia if i not in ib]:
                out += json_diff(ia.get(i), ib.get(i), f"{path}[{i}]")
            return out
        if len(a) == len(b):
            return [d for i, (x, y) in enumerate(zip(a, b)) for d in json_diff(x, y, f"{path}[{i}]")]
    return [] if a == b else [(path, a, b)]


def seed_line(e):
    """写しの seed-orders.json を、読めるか・JSON か・正本と同じ中身かで 1 行にする。印は SEED ok か SEED bad"""
    mine, src = e["API_DIR"] / "seed-orders.json", e["SRC"] / "seed-orders.json"
    if not mine.exists():
        return "SEED bad reason=missing（写しに seed-orders.json が無い）"
    if not os.access(mine, os.R_OK):
        return f"SEED bad reason=unreadable mode={oct(mine.stat().st_mode & 0o777)}"
    try:
        a = json.loads(mine.read_text(encoding="utf-8"))
    except ValueError as x:
        return f"SEED bad reason=json（JSON として読めない: {str(x)[:60]}）"
    try:
        b = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "SEED unknown（正本 SRC の seed-orders.json が読めない）"
    diff = json_diff(a, b)
    if not diff:
        return "SEED ok（正本と同じ中身）"
    shown = " ".join(f"{w}={json.dumps(m, ensure_ascii=False)}（正本 {json.dumps(s, ensure_ascii=False)}）" for w, m, s in diff[:3])
    return f"SEED bad reason=content changed={len(diff)} {shown}"


def key(e, user="u-takagi"):
    f = keys_path(e)
    try:
        m = re.search(rf"{user}: (\S+)", f.read_text(encoding="utf-8")) if f else None
        return m.group(1) if m else None
    except OSError:
        return None


def probe(e, count=10, threshold_ms=THRESHOLD_MS, timeout=2.0, quiet=False):
    k = key(e)
    codes, durs = {}, []
    for _ in range(count):
        req = urllib.request.Request(f"http://127.0.0.1:{e['PORT']}/v1/orders", headers={"Authorization": f"Bearer {k}"} if k else {})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                r.read()
                c = r.status
        except urllib.error.HTTPError as x:
            c = x.code
        except (OSError, urllib.error.URLError):
            c = 0
        d = (time.monotonic() - t0) * 1000
        codes[c] = codes.get(c, 0) + 1
        if c == 200:
            durs.append(d)
    ok = codes.get(200, 0)
    slow = sum(1 for d in durs if d > threshold_ms)
    durs.sort()
    p = (lambda q: f"{durs[min(len(durs) - 1, int(q * len(durs)))]:.1f}ms" if durs else "-")
    good = ok == count and slow <= count // 10
    if not quiet:
        print(f"PROBE n={count} ok={ok} slow={slow}（{threshold_ms:g}ms 超え） codes={','.join(f'{c}:{n}' for c, n in sorted(codes.items()))}"
              f" p50={p(0.5)} p90={p(0.9)} {'GOOD' if good else 'BAD'}")
        if not k and codes.get(401):
            print("HINT 道具の鍵の置き場（KEYS・RUN/keys.*）に鍵が無い。道具の外で立てた API なら、sample-api.sh start が"
                  "道具で立て直して鍵を作り直す。別の置き場の鍵は読まない")
    return good


def api_tally(e, last=100):
    try:
        lines = (e["RUN"] / "api.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        print("TALLY ログが無い")
        return 0
    recs = []
    for x in lines[::-1]:
        if len(recs) >= last:
            break
        if x.startswith("{"):
            try:
                recs.append(json.loads(x))
            except ValueError:
                pass

    def count(key, rows):
        c = {}
        for r in rows:
            v = r.get(key)
            if v is not None:
                c[v] = c.get(v, 0) + 1
        return " ".join(f"{k}={n}" for k, n in sorted(c.items(), key=lambda kv: -kv[1])) or "-"
    bad = [r for r in recs if r.get("status") != 200]
    durs = sorted(r.get("durMs", 0) for r in recs if r.get("status") == 200)
    print(f"TALLY n={len(recs)} status {count('status', recs)}")
    print(f"CODE {count('code', bad)}")
    print(f"EXC {count('exc', bad)}")
    print(f"REJECT {count('reject', bad)}")
    print(f"BAD_USER {count('user', bad)}")
    if durs:
        print(f"DUR p50={durs[len(durs) // 2]:.1f}ms p99={durs[min(len(durs) - 1, int(0.99 * len(durs)))]:.1f}ms "
              f"rows={count('rows', [r for r in recs if r.get('status') == 200])}")
    return 0


def api_pid(e):
    pid, how = find_api(e)
    if not pid:
        print(f"写しの API が見つからない（RUN/api.pid にも port={e['PORT']} の待ち受けにも無い）", file=sys.stderr)
        return 1
    print(pid)
    return 0


def api_rebuild(e):
    """正本の 4 つの file と決めた設定で、写しを作り直して立て直す。違う file は消さずに RUN/broken/<時刻>/ へ退避する"""
    missing = [f for f in FILES if not (e["SRC"] / f).is_file()]
    if missing:
        print(f"REFUSE 正本 {e['SRC']} に {', '.join(missing)} が無い。作り直さずに 2 番手を呼ぶ")
        return 2
    keep = e["RUN"] / "broken" / time.strftime("%Y%m%d-%H%M%S")
    keep.mkdir(parents=True, exist_ok=True)
    old = sys.stdout
    for name, fn in (("status.txt", api_status), ("tally.txt", api_tally)):
        with open(keep / name, "w", encoding="utf-8") as out:
            sys.stdout = out
            try:
                fn(e)
            finally:
                sys.stdout = old
    api_stop(e)
    e["API_DIR"].mkdir(parents=True, exist_ok=True)
    moved = []
    for f in FILES:
        mine = e["API_DIR"] / f
        if mine.exists():
            try:
                same = sha(mine) == sha(e["SRC"] / f)
            except OSError:
                same = False
            if same:
                continue
            os.replace(mine, keep / f)
            moved.append(f)
        shutil.copy2(e["SRC"] / f, mine)
        mine.chmod(0o644)
    print(f"REBUILT 正本 {e['SRC']} から写しを作り直した（入れ替え {len(moved)} 個: {', '.join(moved) or 'なし'}）。"
          f"退避と直す前の status・tally: {keep}")
    return api_start(e, AGREED_ORDERS)


def api_main(args):
    if args == ["--selftest"]:
        return 0 if api_selftest() else 1
    if not args:
        print(__doc__)
        return 2
    e = env()
    cmd, rest = args[0], args[1:]
    opt = dict(zip(rest[::2], rest[1::2]))
    if cmd == "copy":
        return api_copy(e)
    if cmd == "start":
        return api_start(e, int(opt.get("--orders", AGREED_ORDERS)))
    if cmd == "stop":
        return api_stop(e)
    if cmd == "status":
        return api_status(e)
    if cmd == "probe":
        return 0 if probe(e, int(opt.get("--count", 10)), float(opt.get("--threshold-ms", THRESHOLD_MS))) else 1
    if cmd == "tally":
        return api_tally(e, int(opt.get("--last", 100)))
    if cmd == "pid":
        return api_pid(e)
    if cmd == "rebuild":
        return api_rebuild(e)
    print(f"知らない命令: {cmd}")
    return 2


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def scratch_env(base):
    e = {"API_DIR": base / "api", "RUN": base / "run", "SRC": SAMPLES / "api", "PORT": free_port()}
    e["KEYS"] = e["RUN"] / "keys.txt"
    for f in FILES:
        (e["API_DIR"]).mkdir(parents=True, exist_ok=True)
        shutil.copy2(e["SRC"] / f, e["API_DIR"] / f)
    return e


def api_selftest():
    ok = True

    def expect(label, cond):
        nonlocal ok
        if not cond:
            ok = False
            print(f"FAIL selftest sample-api: {label}")
    with tempfile.TemporaryDirectory() as tmp:
        e = scratch_env(pathlib.Path(tmp))
        quiet = open(os.devnull, "w")
        old = sys.stdout
        sys.stdout = quiet
        try:
            started = api_start(e) == 0
            good = probe(e, 5)
            seed_ok = seed_line(e).startswith("SEED ok")
            # 手で立てた API と同じ形: pid の記録を消し、鍵を別の名前に置く
            (e["RUN"] / "api.pid").unlink()
            e["KEYS"].rename(e["RUN"] / "keys.out")
            found = find_api(e)[1] == "listen"
            moved_key = probe(e, 3)
            api_stop(e)
            after = probe(e, 2, timeout=0.5)
            gone = find_api(e)[0] is None and not listeners(e["PORT"])
            (e["RUN"] / "keys.out").unlink(missing_ok=True)
            (e["API_DIR"] / "seed-orders.json").chmod(0)
            failed = api_start(e) == 1
            unread = "reason=unreadable" in seed_line(e)
            (e["API_DIR"] / "seed-orders.json").chmod(0o644)
            inject_seed(e)
            api_start(e)
            content = "reason=content" in seed_line(e) and not probe(e, 3)
            rebuilt = api_rebuild(e) == 0 and probe(e, 5) and seed_line(e).startswith("SEED ok")
            kept = list((e["RUN"] / "broken").glob("*/seed-orders.json"))
            api_stop(e)
            # 2026-11-08 の 2 回目の訓練と同じ形: 出題役が道具の外の起動の命令で立て、鍵は RUN/drill-<PORT>.out（道具は読まない）
            hand, _ = hand_launch(e)
            alt_bad = not probe(e, 2) and key(e) is None
            (e["RUN"] / "keys.old").write_text("u-takagi: stale\nu-kobayashi: stale\n", encoding="utf-8")
            rekey = api_start(e) == 0
            new_pid = find_api(e)[0]
            hand.wait(timeout=10)
            rekeyed = rekey and new_pid not in (None, hand.pid)
            alt_good = probe(e, 5)
            one_place = keys_path(e) == e["KEYS"] and not (e["RUN"] / "keys.old").exists()
            kept_pid = api_start(e) == 0 and find_api(e)[0] == new_pid
            api_stop(e)
        finally:
            for lp in listeners(e["PORT"]):  # 途中で落ちても、この試験が立てた写しの API を残さない
                if in_copy(lp, e):
                    os.kill(lp, signal.SIGKILL)
            sys.stdout = old
            quiet.close()
        expect("正例: 写しが起動しない", started)
        expect("正例: 起動した写しで probe が GOOD でない", good)
        expect("正例: 正本と同じシードが SEED ok にならない", seed_ok)
        expect("正例: pid の記録が無い API を待ち受けから見つけない", found)
        expect("正例: 鍵が keys.out にあるとき probe が GOOD でない", moved_key)
        expect("正例: pid の記録が無い API を stop で止められない", gone)
        expect("負例: 止めた後の probe が BAD でない", not after)
        expect("負例: 読めないシードで起動が FAILED にならない", failed)
        expect("負例: 読めないシードが SEED bad reason=unreadable にならない", unread)
        expect("負例: 中身の壊れたシードが SEED bad reason=content と probe の BAD にならない", content)
        expect("正例: rebuild のあとで probe が GOOD と SEED ok にならない", rebuilt)
        expect("正例: rebuild が壊れたシードを RUN/broken/ に残さない", bool(kept))
        expect("負例: 道具の外で立てた API（鍵は drill-<PORT>.out）で、道具が鍵を見つけるか probe が GOOD になる", alt_bad)
        expect("正例: 道具の外で立てた API を、start が道具で立て直さない（REKEY）", rekeyed)
        expect("正例: 道具で立て直したあと、probe が GOOD でない", alt_good)
        expect("正例: 立て直したあと、鍵の置き場が KEYS の 1 つにならない（古い RUN/keys.* が残る）", one_place)
        expect("負例: 道具の鍵で入れる API を、start が立て直してしまう", kept_pid)
    r = subprocess.run([sys.executable, "-I", __file__, "api", "status"], capture_output=True, text=True,
                       env=dict(os.environ, API_DIR=str(SAMPLES / "api")))
    expect("負例: samples/ の中の写しを断らない", r.returncode == 2 and "REFUSE" in r.stdout)
    print(f"RESULT: {'PASS' if ok else 'FAIL'} sample-api --selftest (18 例)")
    return ok


# ---- hammer（訓練の注入の部品）
def hammer_main(args):
    e = env()
    n = int(dict(zip(args[::2], args[1::2])).get("--threads", 12))
    (e["RUN"] / "batch.pid").write_text(str(os.getpid()))
    k = key(e)

    def loop():
        while True:
            req = urllib.request.Request(f"http://127.0.0.1:{e['PORT']}/v1/orders", headers={"Authorization": f"Bearer {k}"})
            try:
                urllib.request.urlopen(req, timeout=5).read()
            except (OSError, urllib.error.URLError):
                time.sleep(0.01)
    for _ in range(n):
        threading.Thread(target=loop, daemon=True).start()
    while True:
        time.sleep(1)


# ---- drill
def md_sections(text):
    out, head, buf, fence = {}, None, [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            if head:
                out[head] = buf
            head, buf = line[3:].strip(), []
        elif head:
            buf.append(line)
    if head:
        out[head] = buf
    return out


def blocks(lines):
    out, buf, fence = [], [], False
    for line in lines:
        if line.startswith("```"):
            if fence:
                out.append("\n".join(buf))
                buf = []
            fence = not fence
            continue
        if fence:
            buf.append(line)
    return out


def sub_sections(lines):
    out, head, buf = {}, None, []
    fence = False
    for line in lines:
        if line.startswith("```"):
            fence = not fence
        if not fence and line.startswith("### "):
            if head:
                out[head] = buf
            head, buf = line[4:].strip(), []
        elif head:
            buf.append(line)
    if head:
        out[head] = buf
    return out


def find(secs, key):
    return next((v for k, v in secs.items() if key in k), None)


def parse_runbook(path):
    secs = md_sections(path.read_text(encoding="utf-8"))
    table = [x.strip() for x in (find(secs, "原因の見分け方") or []) if x.strip().startswith("|")]
    causes = []
    if len(table) >= 3:
        head = [c.strip() for c in table[0].strip("|").split("|")]
        for row in table[2:]:
            cells = dict(zip(head, [c.strip() for c in row.strip("|").split("|")]))
            cid = re.match(r"(C\d+)", next((v for k, v in cells.items() if "原因" in k), ""))
            mark = re.findall(r"`([^`]+)`", next((v for k, v in cells.items() if "印" in k), ""))
            if cid:
                causes.append((cid.group(1), mark))
    fixes = {re.match(r"(C\d+)", k).group(1): blocks(v) for k, v in sub_sections(find(secs, "直す命令") or []).items() if re.match(r"C\d+", k)}
    out = find(secs, OUTSIDE)
    return {"prep": "\n".join(blocks(find(secs, "準備") or [])), "triage": blocks(find(secs, "確かめる命令") or []),
            "fixes": fixes, "verify": blocks(find(secs, "直ったことの確かめ") or []), "causes": causes,
            "outside": blocks(out or []), "outside_text": "\n".join(out or [])}


def patch(e, stmt):
    p = e["API_DIR"] / "orders_api.py"
    t = p.read_text(encoding="utf-8")
    if t.count(ANCHOR) != 1:
        raise RuntimeError("壊れた版の注入の目印が見本に無い（samples/api が変わった）")
    p.write_text(t.replace(ANCHOR, ANCHOR.split("\n")[0] + f'\n        self.conn.execute("{stmt}")\n' + ANCHOR.split("\n")[1]), encoding="utf-8")


def inject_seed(e):
    """シードの中身を壊す。注文 584117（無ければ状態 action の最初の注文）の shipDue の先頭に半角の空白を足す（2026-11-08 の当番役の訓練と同じ壊れ）"""
    f = e["API_DIR"] / "seed-orders.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    o = next((x for x in d["orders"] if str(x.get("id")) == "584117"), None) or next(x for x in d["orders"] if x.get("status") == "action")
    o["shipDue"] = " " + o["shipDue"]
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return o["id"]


def hand_launch(e, orders=AGREED_ORDERS, out_name=None):
    """出題役が道具の外の起動の命令で立てた形。server.py を直に立て、鍵は RUN/<out_name>（既定 drill-<PORT>.out）に出す。
    ログは RUN/api.log。pid の記録と KEYS は残さない。戻り値は (プロセス, 鍵の file)"""
    run = e["RUN"]
    run.mkdir(parents=True, exist_ok=True)
    out = run / (out_name or f"drill-{e['PORT']}.out")
    (run / "api.pid").unlink(missing_ok=True)
    e["KEYS"].unlink(missing_ok=True)
    with open(out, "w", encoding="utf-8") as fo, open(run / "api.log", "a", encoding="utf-8") as fl:
        os.chmod(out, 0o600)
        p = subprocess.Popen([sys.executable, str(e["API_DIR"] / "server.py"), "--port", str(e["PORT"]), "--orders", str(orders)],
                             stdin=subprocess.DEVNULL, stdout=fo, stderr=fl, cwd=str(e["API_DIR"]), start_new_session=True)
    for _ in range(900):
        if "u-kobayashi:" in out.read_text(encoding="utf-8", errors="replace") or p.poll() is not None:
            break
        time.sleep(0.1)
    return p, out


def spawn(cmd, e, extra_env=None):
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True, env=dict(os.environ, **(extra_env or {})))


def inject(cid, variant, e, kids, launch=None, keyfile=None):
    """障害を使い捨ての写しに起こす。launch は立て直しの手（既定は道具の start、別の起動では出題役の命令）。戻り値は注入の説明"""
    launch = launch or api_start
    silent = open(os.devnull, "w")
    old, sys.stdout = sys.stdout, silent
    try:
        if cid == "C1":
            api_stop(e)
            empty = e["RUN"] / "empty"
            empty.mkdir(exist_ok=True)
            kids.append(spawn([sys.executable, "-m", "http.server", str(e["PORT"]), "--bind", "127.0.0.1", "--directory", str(empty)], e))
            for _ in range(50):
                with socket.socket() as s:
                    if s.connect_ex(("127.0.0.1", e["PORT"])) == 0:
                        break
                time.sleep(0.1)
            launch(e)
            return "別のプロセスがポートを取ったあとで API を立て直した"
        if cid == "C2" and variant == 0:
            api_stop(e)
            (e["API_DIR"] / "seed-orders.json").chmod(0)
            launch(e)
            return "シードの file の権限を 000 にして立て直した"
        if cid == "C2":
            api_stop(e)
            oid = inject_seed(e)
            launch(e)
            return f"シードの注文 {oid} の shipDue の先頭に空白を足して立て直した"
        if cid == OUTSIDE:
            api_stop(e)
            oid = inject_seed(e)
            p, _ = hand_launch(e, out_name="keys.out")
            kids.append(p)
            return f"2026-11-08 の当番役の訓練と同じ形（シードの注文 {oid} の中身が壊れ、pid の記録なし、鍵は keys.out）で手で立てた"
        if cid == "C3":
            api_stop(e)
            patch(e, "DROP TABLE customers" if variant == 0 else "DELETE FROM sessions")
            launch(e)
            return "壊れた版（" + ("表 customers が欠ける" if variant == 0 else "鍵の表 sessions が空") + "）を出して立て直した"
        if cid == "C4":
            os.kill(find_api(e)[0], signal.SIGSTOP)
            return "API のプロセスを SIGSTOP で止めた（端末の Ctrl-Z と同じ）"
        if cid == "C5":
            kids.append(spawn([sys.executable, "-I", __file__, "hammer", "--threads", "12"], e,
                              {"API_DIR": str(e["API_DIR"]), "RUN": str(e["RUN"]), "PORT": str(e["PORT"]), "KEYS": str(keyfile or e["KEYS"])}))
            for _ in range(50):
                if (e["RUN"] / "batch.pid").exists():
                    break
                time.sleep(0.1)
            time.sleep(1.0)
            end = time.monotonic() + 10  # 機械が混むと、断りが出るまで遅れる。ログに断りが出るまで待つ
            while time.monotonic() < end:
                try:
                    if "too_many_inflight" in "".join((e["RUN"] / "api.log").read_text(encoding="utf-8", errors="replace")
                                                      .splitlines(True)[-200:]):
                        break
                except OSError:
                    pass
                time.sleep(0.2)
            return "同じ利用者の鍵で 12 本を同時に連打する一括の道具を動かした"
        if cid in ("C6", "C7"):
            api_stop(e)
            n = 50000 if cid == "C6" else 35000
            launch(e, n)
            return f"--orders {n} で立て直した"
    finally:
        sys.stdout = old
        silent.close()
    raise KeyError(cid)


VARIANTS = {"C2": 2, "C3": 2}
OUTSIDE = "どれにも合わない"


class _Stop(Exception):
    """訓練の前提か注入が崩れたので、その原因の訓練をここで止める"""


def sh(block, prep, e, timeout=180):
    envs = dict(os.environ, API_DIR=str(e["API_DIR"]), RUN=str(e["RUN"]), PORT=str(e["PORT"]), SRC=str(e["SRC"]),
                SRE=str(HERE))
    r = subprocess.run(["bash", "-c", prep + "\n" + block], cwd=str(ROOT), capture_output=True, text=True, env=envs, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


TOOL_CHECK = re.compile(r'^(?:bash\s+)?"?\$\{?SRE\}?/sample-api\.sh"?\s+(probe|status|tally|pid)(?:\s|$)')


def verify_fails(rb, book):
    """「直ったことの確かめ」が Runbook の道具の命令（sample-api.sh probe・status・tally・pid）だけで、probe を含むか。
    2026-11-08 の 2 回目の訓練では、出題役の確かめの命令が道具と別の置き場の鍵を読み、当番役は Runbook の外の立て直しをした"""
    cmds = [c.strip() for b in book["verify"] for line in b.splitlines()
            if line.strip() and not line.strip().startswith(("#", ":", "export ")) for c in re.split(r"&&|\|\||;|\|", line)]
    bad = [c for c in cmds if c and not TOOL_CHECK.match(c)]
    out = []
    if bad:
        out.append(("確かめの道具", f"{rb.name}: 「## 直ったことの確かめ」に道具の外の命令「{bad[0][:70]}」がある。"
                    "sample-api.sh の probe と status だけにする（出題役の命令と、別の置き場の鍵は使わない）"))
    if not any((m := TOOL_CHECK.match(c)) and m.group(1) == "probe" for c in cmds):
        out.append(("確かめの道具", f"{rb.name}: 「## 直ったことの確かめ」に sample-api.sh probe が無い"))
    return out


def drill_one(rb, cid, marks, variant, keep, results, alt=False):
    tag = (f"{rb.name} {cid if cid != OUTSIDE else '表の外'}" + (f"-{variant + 1}" if VARIANTS.get(cid, 1) > 1 and not alt else "")
           + ("-別の起動" if alt else ""))
    fails = []
    base = pathlib.Path(tempfile.mkdtemp(prefix="sre-drill-"))
    kids = []
    e = scratch_env(base)
    pe, launch = e, None  # pe は出題役から見た写し（症状の確かめに使う鍵の置き場）
    silent = open(os.devnull, "w")
    try:
        old, sys.stdout = sys.stdout, silent
        try:
            if alt:  # 出題役が道具の外の起動の命令で立てる。鍵は RUN/drill-<PORT>.out で、道具はこの置き場を読まない
                p, out_keys = hand_launch(e)
                kids.append(p)
                pe = dict(e, KEYS=out_keys)

                def launch(e2, orders=AGREED_ORDERS):
                    kids.append(hand_launch(e2, orders)[0])
            else:
                api_start(e)
        finally:
            sys.stdout = old
        if not probe(pe, 5, quiet=True):
            fails.append(("前提", "注入の前に probe が GOOD でない"))
            raise _Stop()
        what = inject(cid, variant, e, kids, launch, pe["KEYS"])
        if alt:
            what += "（出題役が道具の外の命令で立て、鍵は道具の読まない drill-<PORT>.out）"
        t0 = time.monotonic()
        # 最初は 4 回見る。BAD が出なければ 20 回ずつ 2 度まで見る（連打の断りは、要求の一部にしか出ない）
        if probe(pe, 4, timeout=1.0, quiet=True) and all(probe(pe, 20, timeout=1.0, quiet=True) for _ in range(2)):
            fails.append(("注入", f"{what}のに、probe が BAD にならない（症状が出ない）"))
            raise _Stop()
        book = parse_runbook(rb)
        out = ""
        for b in book["triage"]:
            out += sh(b, book["prep"], e)[1]
        if cid == OUTSIDE:
            fix = book["outside"]
            if not fix:
                fails.append(("表の外", f"「## {OUTSIDE}とき」の節か、作り直す命令のコードが無い"))
            if "2 番手" not in book["outside_text"]:
                fails.append(("表の外", f"「## {OUTSIDE}とき」に 2 番手へ知らせる手が無い"))
        else:
            fix = book["fixes"].get(cid, [])
            miss = [m for m in marks if m not in out]
            if not marks or miss:
                fails.append(("見分け", f"確かめる命令の出力に印 {miss or '（表に印が無い）'} が出ない"))
            if not fix:
                fails.append(("直す命令", f"「## 直す命令」に「### {cid}」の節かコードが無い"))
        for b in fix:
            sh(b, book["prep"], e)
        rcs = [sh(b, book["prep"], e)[0] for b in book["verify"]]
        if not rcs or any(rcs):
            fails.append(("復旧", f"直ったことの確かめの終了コードが {rcs}"))
        elif not probe(e, 20, quiet=True):
            fails.append(("復旧", "直す命令のあとも probe が BAD"))
        secs = time.monotonic() - t0
        results.append(f"{tag}: {what}。症状が出てから直ったことの確かめまで {secs:.1f} 秒")
    except _Stop:
        pass
    except Exception as x:  # noqa: BLE001 — 訓練の途中の誤りも FAIL の 1 行にする
        fails.append(("訓練", f"{type(x).__name__}: {x}"))
    finally:
        silent.close()
        for k in kids:
            if k.poll() is None:
                k.kill()
        old, sys.stdout = sys.stdout, open(os.devnull, "w")
        try:
            pid = find_api(e)[0]
            if pid and alive(pid):
                os.kill(pid, signal.SIGCONT)
            api_stop(e)
            bp = read_pid(e["RUN"] / "batch.pid")
            if bp and alive(bp) and "hammer" in ps(bp, "command"):
                os.kill(bp, signal.SIGKILL)
        finally:
            sys.stdout.close()
            sys.stdout = old
        if keep:
            print(f"KEEP {tag} {base}")
        else:
            shutil.rmtree(base, ignore_errors=True)
    return [(r, f"{tag}: {d}") for r, d in fails]


KINDS = ("table", "outside", "alt")


def drill(paths, keep=False, quiet=False, kinds=KINDS):
    """kinds: table（表の原因ごと）、outside（表の外の 1 件）、alt（表の最後の原因を、出題役の別の起動で起こす 1 件）"""
    all_fails, results, n = [], [], 0
    for p in paths:
        rb = pathlib.Path(p).resolve()
        if not rb.is_file():
            all_fails.append(("無い", f"{p} が無い"))
            continue
        book = parse_runbook(rb)
        if not book["causes"]:
            all_fails.append(("見分け", f"{rb.name} の「原因の見分け方」に C 番号の原因の表が無い"))
        static = verify_fails(rb, book)
        if static:  # 確かめが道具の外なら、当番役は Runbook の外の手を要る。訓練せずに落とす
            all_fails += static
            continue
        cases = [(cid, marks, v, False) for cid, marks in book["causes"] for v in range(VARIANTS.get(cid, 1)) if "table" in kinds]
        if "outside" in kinds:
            cases.append((OUTSIDE, [], 0, False))
        if "alt" in kinds and book["causes"]:
            cases.append((*book["causes"][-1], 0, True))
        for cid, marks, v, alt in cases:
            n += 1
            all_fails += drill_one(rb, cid, marks, v, keep, results, alt)
    if not quiet:
        for r in results:
            print(f"MEASURE {r}")
        for rule, d in all_fails:
            print(f"FAIL [{rule}] {d}")
        print(f"RESULT: {'PASS' if not all_fails else 'FAIL'} runbook-drill ({n} 件の訓練、FAIL {len(all_fails)})")
    return all_fails


SELF_RB = """# Runbook: 見本

## 準備

```sh
: "${{SRE:=skills/sre/scripts}}"
```

## 確かめる命令

```sh
bash "$SRE/sample-api.sh" status
```

## 原因の見分け方

| 原因 | 印 |
|---|---|
| C4 止まったプロセス | `{mark}` |

## 直す命令

### C4 止まったプロセス

```sh
{fix}
```

## 直ったことの確かめ

```sh
{verify}
```

{outside}
"""
VERIFY_OK = 'bash "$SRE/sample-api.sh" probe --count 4 && bash "$SRE/sample-api.sh" status'
# 2026-11-08 の 2 回目の訓練の出題役の確かめと同じ形: 道具と別の置き場（drill-<PORT>.out）から鍵を読んで一覧を呼ぶ
VERIFY_SETTER = ('curl -fsS -o /dev/null -H "Authorization: Bearer $(sed -n \'s/.*u-takagi: //p\' "$RUN/drill-$PORT.out")"'
                 ' "http://127.0.0.1:$PORT/v1/orders"')
OUTSIDE_OK = """## どれにも合わないとき

正本から写しを作り直し、2 番手へ知らせる。

```sh
bash "$SRE/sample-api.sh" rebuild
```
"""


def drill_selftest():
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        cont = 'kill -CONT "$(bash "$SRE/sample-api.sh" pid)"'
        fix = cont + '\nbash "$SRE/sample-api.sh" start'  # 続きを動かし、道具の鍵で入れなければ道具で立て直す
        # 各行: 名前、印、直す命令、表の外の節、直ったことの確かめ、回す訓練の種類、落ちるべき決まり（正例は None）
        cases = [("正例（表・表の外・別の起動）", "state=stopped", fix, OUTSIDE_OK, VERIFY_OK, KINDS, None),
                 ("直さない Runbook", "state=stopped", "true", OUTSIDE_OK, VERIFY_OK, ("table",), "復旧"),
                 ("印の誤った Runbook", "state=gone", fix, OUTSIDE_OK, VERIFY_OK, ("table",), "見分け"),
                 ("表の外の手が無い Runbook", "state=stopped", fix, "", VERIFY_OK, ("outside",), "表の外"),
                 ("2 番手へ知らせない Runbook", "state=stopped", fix, OUTSIDE_OK.replace("、2 番手へ知らせる", ""), VERIFY_OK,
                  ("outside",), "表の外"),
                 ("別の起動のあと道具で立て直さない Runbook", "state=stopped", cont, OUTSIDE_OK, VERIFY_OK, ("alt",), "復旧"),
                 ("出題役の命令で別の置き場の鍵を読んで確かめる Runbook", "state=stopped", fix, OUTSIDE_OK, VERIFY_SETTER, KINDS,
                  "確かめの道具"),
                 ("確かめに probe が無い Runbook", "state=stopped", fix, OUTSIDE_OK, 'bash "$SRE/sample-api.sh" status', KINDS,
                  "確かめの道具")]
        for i, (label, mark, fx, outside, verify, kinds, rule) in enumerate(cases):
            p = pathlib.Path(tmp) / f"rb{i}.md"
            p.write_text(SELF_RB.format(mark=mark, fix=fx, outside=outside, verify=verify), encoding="utf-8")
            fails = drill([p], quiet=True, kinds=kinds)
            rules = {r for r, _ in fails}
            if rule is None and fails:
                ok = False
                print(f"FAIL selftest runbook-drill: 正例「{label}」が落ちた: {fails}")
            if rule is not None and rule not in rules:
                ok = False
                print(f"FAIL selftest runbook-drill: 負例「{label}」が [{rule}] で落ちない: {fails}")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} runbook-drill --selftest ({len(cases)} 例)")
    return ok


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "api":
        return api_main(argv[1:])
    if argv[0] == "hammer":
        return hammer_main(argv[1:])
    if argv[0] == "drill":
        args = argv[1:]
        if args == ["--selftest"]:
            return 0 if drill_selftest() else 1
        keep = "--keep" in args
        kinds = KINDS
        if "--only" in args:
            i = args.index("--only")
            kinds = tuple(args[i + 1:i + 2])
            args = args[:i] + args[i + 2:]
            if not kinds or kinds[0] not in KINDS:
                print(f"--only は {'|'.join(KINDS)} のどれか")
                return 2
        paths = [a for a in args if a != "--keep"]
        if not paths:
            print(__doc__)
            return 2
        return 1 if drill(paths, keep, kinds=kinds) else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
