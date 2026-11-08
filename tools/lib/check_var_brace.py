"""全角の字の直前の変数を探す（シェルの台本用）。

macOS の bash は、UTF-8 の文字の設定（日本語でも英語でも）で、
「$名前」のすぐ後ろの全角の字の一部まで、変数の名前と読む。
set -u なら「unbound variable」で落ちる。${名前} と波括弧で囲めば、名前の終わりがはっきりする。

使い方: python3 -I tools/lib/check_var_brace.py <ファイル>...
        python3 -I tools/lib/check_var_brace.py --selftest
1 か所でも見つかれば、場所を FAIL の行で出し、終了コード 1 を返す。
"""
import re
import sys

PATTERN = re.compile(rb"\$[A-Za-z_][A-Za-z0-9_]*[\x80-\xff]")
MESSAGE = "全角の字の直前の変数は ${名前} と囲む（awk の $NF などは、間に空白か引用符を入れる）"

# 正例（見つけてはいけない）と負例（見つけるべき）
GOOD = [
    'echo "install: $f を書いた（退避: $f.bak.${STAMP}）"',
    'echo "$N 本ある"',
    'echo "値は $X."',
    'echo "全角の後ろの変数は $X"',
    "awk '{print $1、}'",
]
BAD = [
    'echo "install: $f を書いた（退避: $f.bak.$STAMP）"',
    'reason="作業を終える前の検証（$cmd）が FAIL"',
    'echo "$N本ある"',
    'msg="$_が"',
]


def find(lines):
    return [no for no, line in enumerate(lines, 1) if PATTERN.search(line)]


def selftest():
    ok = True
    for code in GOOD:
        if find([code.encode("utf-8")]):
            ok = False
            print("FAIL selftest: 正例が落ちた :: %s" % code)
    for code in BAD:
        if not find([code.encode("utf-8")]):
            ok = False
            print("FAIL selftest: 負例が通った :: %s" % code)
    print("RESULT: %s check-var-brace --selftest (%d 例)" % ("PASS" if ok else "FAIL", len(GOOD) + len(BAD)))
    return ok


def main(paths):
    found = 0
    for path in paths:
        with open(path, "rb") as fh:
            lines = fh.read().split(b"\n")
        for no in find(lines):
            print("FAIL %s:%d [変数の波括弧] %s" % (path, no, MESSAGE))
            found += 1
    return 1 if found else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(0 if selftest() else 1)
    sys.exit(main(sys.argv[1:]))
