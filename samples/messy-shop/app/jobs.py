"""夜の処理の入口。python3 jobs.py <名前> [引数...]"""
import importlib
import sys

MODULES = ["batch_nightly", "batch_carrier"]


def run(name, *args):
    for m in MODULES:
        fn = getattr(importlib.import_module(m), "job_" + name, None)
        if fn:
            return fn(*args)
    raise SystemExit("その名前の処理は無い: " + name)


if __name__ == "__main__":
    run(sys.argv[1], *sys.argv[2:])
