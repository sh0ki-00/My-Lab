#!/usr/bin/env python3
"""catchup_tools — キャッチアップの道具。標準の python3（3.9 以上）と git だけで動く。

使い方（同じディレクトリの .sh から呼ぶ）:
  facts  catchup-facts.sh   プロジェクトの事実（言語と版、ディレクトリ、commit の作者の数、入口、DB、文書、UI の部品）を
                            機械で拾い、表に出す。--out を渡すと、事実の記録（JSON Lines。F-001 の形の番号とハッシュ値）に足す
  check  map-check.sh       地図（既定は tmp/catchup/）の検査。入口の 1 枚の長さと節の案内（C-7）、DB の読み取りの許可の欄、
                            基準の数字の一致（C-5）、全部の表の行の根拠、データの節（data-dictionary-check.sh を呼ぶ）、追記の候補、
                            鮮度（根拠のファイルが変わった節と、走査したファイルが増えたか消えた節を落とす。C-2）
         map-check.sh --fresh   鮮度だけを見て、節ごとに SECTION <節> 新しい|古い を出す（ふつうのセッションが回す）
         map-check.sh --stamp   地図を作り終えたときに、commit と根拠のファイルのハッシュ値を stamp.json に記録する
  <種類> --selftest         一時のディレクトリだけで、数秒の自己試験を回す
決まり: プロジェクトのファイルは読むだけ。書くのは --out の事実の記録と、--stamp の stamp.json だけで、どちらもプロジェクトの
        tmp/ の下か外に置く。.env などの設定はキーの名前だけを拾い、値は出さない。コマンドと cron の行は、秘密になりうる値を
        伏せてから写す。commit の作者は数だけを出し、名前とメールは出さない。
出力: 事実の表、FAIL <場所> [<決まり>] <内容>、SECTION と INFO の行、最後に RESULT: PASS|FAIL <道具> …。
      FAIL が 1 件でもあれば終了コード 1。使い方の誤りは 2。
"""
import argparse
import contextlib
import datetime
import fcntl
import fnmatch
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
NAMES = {"facts": "catchup-facts", "check": "map-check"}
SECTIONS = [("構成と動かし方", "stack.md"), ("開発の形", "team.md"), ("入口", "entrypoints.md"),
            ("データ", "data.md"), ("語彙", "vocabulary.md"), ("罠", "traps.md")]
INBOX = ("追記の候補", "inbox.md")
DATA = "データ"
INDEX_SECTION = "入口の 1 枚"        # 入口の 1 枚の表の根拠も、節と同じく鮮度を見る
PERMIT = "DB の読み取りの許可"       # 入口の冒頭の表の欄。許可した日と相手と範囲か、「無い」
INDEX_FILE, STAMP_FILE, FACTS_FILE, QUERIES_FILE = "index.md", "stamp.json", "facts.jsonl", "queries.jsonl"
INDEX_MAX = 80          # 入口の 1 枚の行の上限（C-7）
INBOX_STATES = ("未処理", "反映済み", "見送り")
MAX_FILES = 20000       # 走査するファイルの上限。超えた分は「読んでいない」と事実に書く
MAX_BYTES = 1000000     # 中身を読むファイルの大きさの上限
CAP = 30                # 種類ごとに出す事実の上限（ルートは ROUTE_CAP）
ROUTE_CAP = 300
GIT_TIMEOUT = 20
DICT_CHECK = HERE.parent.parent / "backend" / "scripts" / "data-dictionary-check.sh"
KIND_ORDER = ["読んだ範囲", "言語", "ディレクトリ", "版", "フレームワーク", "コマンド", "試験", "履歴", "画面と API",
              "定時の処理", "外とのつながり", "設定の口", "DB", "文書", "決まり", "UI の部品"]


class Report:
    def __init__(self, tool, target=""):
        self.tool, self.target, self.items, self.lines = tool, target, [], []

    def fail(self, where, rule, detail):
        self.items.append((where, rule, detail))

    def say(self, text):
        self.lines.append(text)

    def rules(self):
        return {x[1] for x in self.items}

    def show(self, summary=""):
        for t in self.lines:
            print(t)
        for where, rule, detail in self.items:
            print(f"FAIL {where + ' ' if where else ''}[{rule}] {detail}")
        tail = f"{summary}、FAIL {len(self.items)}" if summary else f"FAIL {len(self.items)}"
        target = f" {self.target}" if self.target else ""
        print(f"RESULT: {'FAIL' if self.items else 'PASS'} {self.tool}{target} ({tail})")
        return 1 if self.items else 0


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def rec_hash(rec):
    """記録のハッシュ値。backend の data_tools.py のクエリの記録と同じ作り方（hash を除いた JSON の SHA-256）。"""
    body = {k: v for k, v in rec.items() if k != "hash"}
    s = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git(root, *args):
    """読むだけの git を呼ぶ。失敗か git が無ければ None。"""
    try:
        p = subprocess.run(["git", "-C", str(root)] + list(args), capture_output=True, text=True,
                           timeout=GIT_TIMEOUT, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0", LC_ALL="C"))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def git_head(root):
    """(commit の短い値, 説明)。git の作業ツリーでなければ ("無い", 理由)。"""
    inside = (git(root, "rev-parse", "--is-inside-work-tree") or "").strip()
    if inside != "true":
        return "無い", "git の作業ツリーではない"
    head = (git(root, "rev-parse", "--short", "HEAD") or "").strip()
    return (head, "") if head else ("無い", "commit が 0 本")


# ---------------------------------------------------------------- 事実を拾う（catchup-facts）
SKIP_DIRS = {"node_modules", "vendor", ".git", "tmp", "dist", "build", ".next", ".nuxt", "coverage", "__pycache__",
             ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode", "target",
             ".gradle", ".terraform", "bower_components", ".cache", ".parcel-cache", ".svelte-kit", "Pods",
             "DerivedData", ".dart_tool", ".turbo"}
KEEP_HIDDEN = {".github", ".gitlab", ".circleci", ".husky"}
SKIP_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}  # OS が置くファイル。数に入れない
LANG = {".py": "python", ".php": "php", ".rb": "ruby", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
        ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript", ".go": "go", ".java": "java", ".kt": "kotlin",
        ".kts": "kotlin", ".scala": "scala", ".rs": "rust", ".cs": "c#", ".swift": "swift", ".dart": "dart",
        ".ex": "elixir", ".exs": "elixir", ".vue": "vue", ".svelte": "svelte", ".sql": "sql", ".sh": "shell",
        ".html": "html", ".css": "css", ".scss": "scss", ".erb": "erb", ".twig": "twig"}
CODE_EXT = {".py", ".php", ".rb", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".go", ".java", ".kt", ".kts", ".scala",
            ".rs", ".cs", ".swift", ".dart", ".ex", ".exs", ".vue", ".svelte"}
COMMENT_START = ("#", "//", "/*", "*", "--", "<!--", ";")
VERSION_FILES = {".python-version": "python", ".nvmrc": "node", ".node-version": "node", ".ruby-version": "ruby",
                 ".go-version": "go", ".java-version": "java", "runtime.txt": "実行環境"}
JS_FW = {"next", "react", "vue", "nuxt", "svelte", "@sveltejs/kit", "astro", "express", "@nestjs/core", "fastify", "koa",
         "hono", "@remix-run/node", "typescript", "vite", "webpack", "tailwindcss", "prisma", "@prisma/client", "typeorm",
         "sequelize", "knex", "mongoose", "jest", "vitest", "@playwright/test", "cypress", "@angular/core", "electron",
         "react-native", "expo"}
PHP_FW = {"php", "laravel/framework", "symfony/framework-bundle", "slim/slim", "cakephp/cakephp", "phpunit/phpunit"}
PY_FW = {"django", "flask", "fastapi", "sqlalchemy", "celery", "alembic", "pydantic", "starlette", "tornado", "bottle",
         "pyramid", "pytest"}
RB_FW = {"rails", "sinatra", "hanami", "rspec", "rspec-rails"}
PY_ROUTE = re.compile(r"""@(?:[A-Za-z_]\w*\.)*(route|get|post|put|patch|delete|head|options|api_route|websocket)\(\s*[rbuf]?['"]([^'"]*)['"]""")
DJANGO = re.compile(r"""\b(?:re_)?path\(\s*r?['"]([^'"]*)['"]""")
LARAVEL = re.compile(r"""Route::(get|post|put|patch|delete|any|match|resource|apiResource|view|redirect)\(\s*(?:\[[^\]]*\]\s*,\s*)?['"]([^'"]*)['"]""")
RAILS = re.compile(r"""^\s*(get|post|put|patch|delete|resources?|root|match)\b\s*\(?\s*['":]?([\w/:.\-{}*]*)""")
JS_ROUTE = re.compile(r"""\b(?:app|router|server|api|routes?|fastify|hono)\.(get|post|put|patch|delete|all|use|route|options|head)\(\s*['"`](/[^'"`]*)['"`]""")
GO_ROUTE = re.compile(r"""\b(?:HandleFunc|Handle|GET|POST|PUT|PATCH|DELETE|Any)\(\s*"(/[^"]*)\"""")
JAVA_ROUTE = re.compile(r"""@(Get|Post|Put|Delete|Patch|Request)Mapping\(\s*(?:(?:value|path)\s*=\s*)?\{?\s*"([^"]*)\"""")
PY_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(")
INBOUND = re.compile(r"(?i)(notify|webhook|callback|hook|ipn|/events?\b)")
MAIN_RX = re.compile(r"""^\s*if\s+__name__\s*==\s*['"]__main__['"]\s*:""")
SCHED_RX = re.compile(r"""(\$schedule->(?:command|job|call|exec)\(|@(?:shared_task|periodic_task)\b|@\w+\.task\b|beat_schedule|cron\.schedule\(|@Scheduled\b)""")
CRON_LINE = re.compile(r"^\s*([\d*/,\-]+\s+){4}[\d*/,\-]+\s+\S")
GHA_CRON = re.compile(r"""^\s*-?\s*cron:\s*['"]?([^'"#]+)""")
NAME_BATCH = re.compile(r"(?i)(batch|jobs?\b|jobs?[_.]|cron|tasks?[_.]|worker|schedul|nightly|daily|hourly|queue)")
HTTP_OUT = re.compile(r"\b(requests\.(?:get|post|put|patch|delete|request)\(|urllib\.request|urlopen\(|httpx\.|aiohttp\.|fetch\(|axios[.(]|Http::|GuzzleHttp|curl_init|http\.Get\(|HttpClient|RestTemplate|WebClient|Net::HTTP|Faraday|HTTParty)")
MAIL_RX = re.compile(r"\b(smtplib|send_mail\(|EmailMessage|Mail::|Mailer\b|nodemailer|ActionMailer)")
ENV_RXS = [re.compile(r"""os\.environ(?:\.get)?\(?\s*\[?\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
           re.compile(r"""os\.getenv\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
           re.compile(r"""process\.env\.([A-Za-z_][A-Za-z0-9_]*)"""),
           re.compile(r"""process\.env\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
           re.compile(r"""\benv\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
           re.compile(r"""\bENV\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
           re.compile(r"""\bgetenv\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]""")]
ENV_KEY = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
DB_KEY = re.compile(r"(?i)(?:^|_)(DB|DATABASE|SQL|SQLITE|PG|POSTGRES|POSTGRESQL|MYSQL|MARIADB|REDIS|MONGO|MONGODB|DSN)(?:_|$)")
DB_LIB = re.compile(r"\b(sqlite3\.connect|create_engine\(|psycopg2?\b|pymysql\b|mysql\.connector|MySQLdb|DB::|new\s+PDO|PDO\(|ActiveRecord::|Sequelize\(|knex\(|PrismaClient|mongoose\.connect|MongoClient|gorm\.Open|sql\.Open\()")
DB_CONF = re.compile(r"^(database\.yml|database\.php|knexfile\.(js|ts)|ormconfig\.(js|ts|json)|schema\.prisma|settings\.py)$")
MIGRATION_TAILS = ("alembic/versions", "prisma/migrations", "database/migrations", "db/migrate")
SCHEMA_FILES = {"schema.prisma", "schema.rb", "structure.sql", "schema.sql"}
SQLITE_EXT = {".sqlite", ".sqlite3", ".db", ".db3", ".s3db"}
TEST_FILE = [re.compile(p) for p in (r"^test_.*\.py$", r"_test\.(py|go|exs)$", r"\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs)$",
                                     r"Test\.(php|java|kt)$", r"_spec\.rb$", r"Tests?\.cs$")]
TEST_CONF = {"pytest.ini", "tox.ini", "conftest.py", "phpunit.xml", "phpunit.xml.dist", ".rspec", "karma.conf.js", "noxfile.py"}
TEST_CONF_RX = re.compile(r"^(jest|vitest|playwright|cypress)\.config\.(js|ts|mjs|cjs|mts)$")
DOC_EXT = {".md", ".mdx", ".txt", ".rst", ".adoc"}
DOC_GUESS = [(re.compile(r"(?i)^readme"), "説明"), (re.compile(r"(?i)^contributing"), "決まり（貢献の手順）"),
             (re.compile(r"(?i)^changelog"), "変更の記録"), (re.compile(r"(?i)^(memo|notes?|todo)\b|メモ"), "メモ"),
             (re.compile(r"(?i)runbook|procedure|手順"), "手順書の候補"), (re.compile(r"(?i)spec|仕様"), "仕様書の候補"),
             (re.compile(r"(?i)design|architecture|設計"), "設計書の候補"),
             (re.compile(r"(?i)postmortem|incident|ポストモーテム|障害"), "ポストモーテムの候補"),
             (re.compile(r"(?i)requirement|要件"), "要件定義書の候補"), (re.compile(r"(?i)investigation|調査"), "調査報告書の候補"),
             (re.compile(r"(?i)\badr\b|decision"), "決定の記録")]
LINT_FILES = re.compile(r"^(\.editorconfig|\.eslintrc.*|eslint\.config\.(js|mjs|cjs|ts)|\.prettierrc.*|prettier\.config\.(js|cjs|mjs)|"
                        r"\.rubocop\.yml|phpcs\.xml(\.dist)?|\.golangci\.ya?ml|\.stylelintrc.*|biome\.json|\.flake8|ruff\.toml|"
                        r"\.pre-commit-config\.yaml|\.markdownlint.*)$")
UI_DIRS = {"components", "views", "templates", "layouts", "partials", "widgets", "ui", "pages", "screens"}
STYLE_EXT = {".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".astro"}
CSS_VAR = re.compile(r"(?<![\w-])--[A-Za-z0-9_-]+\s*:")


# コマンドの行を写すときに伏せる値。KEY=値 の値、URL の利用者とパスワード、-u 利用者:パスワード、Bearer と Basic の後ろ、
# --password・--token などの後ろ、-p の直後。地図に秘密の値を入れない（改善提案書の 5.2 節の順 0）
HIDDEN = "（伏せた）"
REDACT = [
    (re.compile(r"(?<![\w-])([A-Za-z_][A-Za-z0-9_]*)=(?:'[^']*'|\"[^\"]*\"|\S+)"), r"\1=" + HIDDEN),
    (re.compile(r"\b([A-Za-z][\w+.-]*://)[^/\s@'\"]+@"), r"\1" + HIDDEN + "@"),
    (re.compile(r"(?i)\b(Bearer|Basic|Token)\s+[A-Za-z0-9._~+/=:-]+"), r"\1 " + HIDDEN),
    (re.compile(r"(?i)(?<!\S)(-u|--user|--password|--passwd|--pass|--token|--api-key|--apikey|--secret|-H|--header)"
                r"(\s+|=)(?:'[^']*'|\"[^\"]*\"|\S+)"), r"\1\2" + HIDDEN),
    (re.compile(r"(?<!\S)-p(?=\S)(?:'[^']*'|\"[^\"]*\"|\S+)"), "-p" + HIDDEN),
]


def redact(text):
    """コマンドや設定の行から、秘密になりうる値を伏せる。名前（キー、コマンド）は残す。"""
    s = str(text)
    for rx, rep in REDACT:
        s = rx.sub(rep, s)
    return s


def ext(rel):
    return pathlib.PurePosixPath(rel).suffix.lower()


def base(rel):
    return rel.rsplit("/", 1)[-1]


def excluded(rel, patterns):
    for p in patterns:
        p = p.strip().strip("/")
        if p and (rel == p or rel.startswith(p + "/") or fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(base(rel), p)):
            return True
    return False


def walk(root, max_files, exclude=()):
    files, over = [], 0
    for d, dirs, names in os.walk(root):
        rel_d = os.path.relpath(d, root).replace(os.sep, "/")
        rel_d = "" if rel_d == "." else rel_d + "/"
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and (not x.startswith(".") or x in KEEP_HIDDEN)
                         and not excluded(rel_d + x, exclude))
        for n in sorted(names):
            rel = rel_d + n
            if n in SKIP_FILES or excluded(rel, exclude):
                continue
            if len(files) >= max_files:
                over += 1
                continue
            files.append(rel)
    return files, over


class Tree:
    def __init__(self, root, files):
        self.root, self.files, self.cache, self.unread = pathlib.Path(root), files, {}, set()

    def text(self, rel):
        if rel in self.cache:
            return self.cache[rel]
        p, t = self.root / rel, None
        try:
            if not p.is_symlink() and p.stat().st_size <= MAX_BYTES:
                data = p.read_bytes()
                if b"\0" not in data[:8192]:
                    t = data.decode("utf-8", errors="replace")
        except OSError:
            t = None
        if t is None:
            self.unread.add(rel)
        self.cache[rel] = t
        return t

    def lines(self, rel):
        t = self.text(rel)
        return t.splitlines() if t is not None else []

    def code(self):
        return [f for f in self.files if ext(f) in CODE_EXT]


class Facts:
    def __init__(self):
        self.items = []

    def add(self, kind, item, value, source="", line=0, command=""):
        self.items.append({"kind": kind, "item": str(item), "value": str(value), "source": source,
                           "line": int(line or 0), "command": command})

    def of(self, kind):
        return [f for f in self.items if f["kind"] == kind]


def commented(line):
    return line.lstrip().startswith(COMMENT_START)


def c_scope(t, F, over, exclude, max_files):
    F.add("読んだ範囲", "走査したファイル", f"{len(t.files)} 本", command="ディレクトリを走査（node_modules、vendor、.git、tmp などの "
          f"{len(SKIP_DIRS)} 種類と、隠しディレクトリを除く）")
    if over:
        F.add("読んだ範囲", "上限で読んでいないファイル", f"{over} 本", command=f"--max-files {max_files}")
    if exclude:
        F.add("読んだ範囲", "読まない所（--exclude）", "、".join(exclude), command="--exclude")


def c_lang(t, F):
    counts = {}
    for f in t.files:
        lang = LANG.get(ext(f))
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    for lang, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:CAP]:
        F.add("言語", lang, f"{n} 本", command="拡張子で数えた")
    if not counts:
        F.add("言語", "コードのファイル", "0 本", command="拡張子で数えた")


def c_dirs(t, F):
    top, root_files = {}, []
    for f in t.files:
        if "/" in f:
            d = f.split("/", 1)[0]
            top[d] = top.get(d, 0) + 1
        else:
            root_files.append(f)
    for d, n in sorted(top.items())[:CAP]:
        F.add("ディレクトリ", d + "/", f"{n} 本", command="直下のディレクトリごとに、下にあるファイルを数えた")
    if len(top) > CAP:
        F.add("ディレクトリ", "ほかのディレクトリ", f"{len(top) - CAP} 個", command="直下のディレクトリを数えた")
    shown = "、".join(root_files[:8]) + ("ほか" if len(root_files) > 8 else "")
    F.add("ディレクトリ", "直下のファイル", f"{len(root_files)} 本" + (f"（{shown}）" if root_files else ""),
          command="直下のファイルを数えた")


def dep_lines(lines, names, rx):
    for i, s in enumerate(lines, 1):
        m = rx.match(s)
        if m and m.group(1).lower() in names:
            yield i, m.group(1), (m.group(2) or "").strip()


def c_versions(t, F):
    found = 0
    for f in t.files:
        b = base(f)
        lines = None
        if b in VERSION_FILES:
            for i, s in enumerate(t.lines(f), 1):
                if s.strip() and not s.strip().startswith("#"):
                    F.add("版", VERSION_FILES[b], redact(s.strip())[:60], f, i)
                    found += 1
                    break
        elif b == ".tool-versions":
            for i, s in enumerate(t.lines(f), 1):
                parts = s.split()
                if len(parts) >= 2 and not s.startswith("#"):
                    F.add("版", parts[0], parts[1], f, i)
                    found += 1
        elif b == "go.mod":
            for i, s in enumerate(t.lines(f), 1):
                m = re.match(r"^go\s+(\S+)", s)
                if m:
                    F.add("版", "go", m.group(1), f, i)
                    found += 1
                m = re.search(r"github\.com/(gin-gonic/gin|labstack/echo\S*|gofiber/fiber\S*)\s+(\S+)", s)
                if m:
                    F.add("フレームワーク", m.group(1), m.group(2), f, i)
        elif b == "pyproject.toml" or b == "setup.cfg":
            lines = t.lines(f)
            for i, s in enumerate(lines, 1):
                m = re.search(r"""(?:requires-python|python_requires)\s*=\s*['"]?([^'"\n]+)""", s) or \
                    re.match(r"""^\s*python\s*=\s*['"]([^'"]+)""", s)
                if m:
                    F.add("版", "python", m.group(1).strip(), f, i)
                    found += 1
            for i, name, ver in dep_lines(lines, PY_FW, re.compile(r"""^\s*['"]?([A-Za-z][\w-]*)\s*(?:\[[^\]]*\])?\s*['"]?\s*(?:=\s*['"]?|([<>=!~]=?[^'",]*))""")):
                F.add("フレームワーク", name, ver or "版の指定なし", f, i)
        elif re.fullmatch(r"requirements.*\.txt", b):
            for i, name, ver in dep_lines(t.lines(f), PY_FW, re.compile(r"""^\s*([A-Za-z][\w-]*)\s*(?:\[[^\]]*\])?\s*([<>=!~]=?\s*\S+)?""")):
                F.add("フレームワーク", name, ver or "版の指定なし", f, i)
        elif b == "package.json":
            lines = t.lines(f)
            for i, s in enumerate(lines, 1):
                m = re.match(r"""^\s*"node"\s*:\s*"([^"]*)\"""", s)
                if m:
                    F.add("版", "node", m.group(1), f, i)
                    found += 1
            for i, name, ver in dep_lines(lines, JS_FW, re.compile(r"""^\s*"([@\w./-]+)"\s*:\s*"([^"]*)\"""")):
                F.add("フレームワーク", name, ver, f, i)
        elif b == "composer.json":
            for i, name, ver in dep_lines(t.lines(f), PHP_FW, re.compile(r"""^\s*"([\w./-]+)"\s*:\s*"([^"]*)\"""")):
                if name == "php":
                    F.add("版", "php", ver, f, i)
                    found += 1
                else:
                    F.add("フレームワーク", name, ver, f, i)
        elif b == "Gemfile":
            for i, s in enumerate(t.lines(f), 1):
                m = re.match(r"""^\s*ruby\s+['"]([^'"]+)""", s)
                if m:
                    F.add("版", "ruby", m.group(1), f, i)
                    found += 1
                m = re.match(r"""^\s*gem\s+['"]([\w-]+)['"]\s*(?:,\s*['"]([^'"]+))?""", s)
                if m and m.group(1) in RB_FW:
                    F.add("フレームワーク", m.group(1), m.group(2) or "版の指定なし", f, i)
        elif b.startswith("Dockerfile"):
            for i, s in enumerate(t.lines(f), 1):
                m = re.match(r"^\s*FROM\s+(\S+)", s, re.I)
                if m:
                    F.add("版", "コンテナの土台", m.group(1), f, i)
                    found += 1
        elif b in ("pom.xml", "build.gradle", "build.gradle.kts"):
            for i, s in enumerate(t.lines(f), 1):
                if "spring-boot" in s:
                    F.add("フレームワーク", "spring-boot", s.strip()[:60], f, i)
                    break
    if not found:
        F.add("版", "言語の版", "設定ファイルに書かれていない", command="名前で探した（.python-version、package.json、go.mod、"
              "composer.json、Gemfile、pyproject.toml、Dockerfile ほか）")


def json_entries(lines, key):
    """package.json や composer.json の "key": { ... } の中の "名前": "値" を、行の番号つきで返す。"""
    out, inside, depth = [], False, 0
    item = re.compile(r'"([^"]+)"\s*:\s*("((?:[^"\\]|\\.)*)"|\[)')
    for i, s in enumerate(lines, 1):
        if not inside:
            m = re.search(r'"%s"\s*:\s*\{' % re.escape(key), s)
            if not m:
                continue
            inside, depth, s = True, 0, s[m.end() - 1:]
        for m in item.finditer(s):
            if depth <= 1 and m.group(1) != key:
                out.append((i, m.group(1), m.group(3) if m.group(3) is not None else "（複数のコマンド）"))
        depth += s.count("{") - s.count("}")
        if depth <= 0:
            inside = False
    return out


def c_commands(t, F):
    n = 0
    for f in t.files:
        b = base(f)
        if b == "package.json":
            for i, name, cmd in json_entries(t.lines(f), "scripts")[:CAP]:
                F.add("コマンド", f"npm run {name}", redact(cmd)[:80], f, i)
                n += 1
        elif b == "composer.json":
            for i, name, cmd in json_entries(t.lines(f), "scripts")[:CAP]:
                F.add("コマンド", f"composer {name}", redact(cmd)[:80], f, i)
                n += 1
        elif b in ("Makefile", "makefile", "GNUmakefile"):
            k = 0
            for i, s in enumerate(t.lines(f), 1):
                m = re.match(r"^([A-Za-z0-9][\w./-]*)\s*:(?!=)", s)
                if m and k < 20:
                    F.add("コマンド", f"make {m.group(1)}", "Makefile の的", f, i)
                    k += 1
                    n += 1
        elif b == "Procfile":
            for i, s in enumerate(t.lines(f), 1):
                m = re.match(r"^([\w-]+)\s*:\s*(.+)$", s)
                if m:
                    F.add("コマンド", f"Procfile の {m.group(1)}", redact(m.group(2).strip())[:80], f, i)
                    n += 1
        elif re.fullmatch(r"(docker-)?compose(\.[\w-]+)?\.ya?ml", b):
            inside = False
            for i, s in enumerate(t.lines(f), 1):
                if re.match(r"^services:\s*$", s):
                    inside = True
                    continue
                if inside and re.match(r"^\S", s):
                    inside = False
                m = re.match(r"^  ([\w.-]+):\s*$", s) if inside else None
                if m:
                    F.add("コマンド", f"compose のサービス {m.group(1)}", "docker compose up で起きる", f, i)
                    n += 1
        elif b in ("manage.py", "artisan") and "/" not in f:
            F.add("コマンド", {"manage.py": "python manage.py", "artisan": "php artisan"}[b], "フレームワークの入口", f, 1)
            n += 1
    if not n:
        F.add("コマンド", "起動とテストのコマンド", "設定に書かれていない", command="package.json の scripts、Makefile、Procfile、"
              "compose、manage.py、artisan を探した")


def c_tests(t, F):
    tests = [f for f in t.files if any(rx.search(base(f)) for rx in TEST_FILE)]
    F.add("試験", "試験のファイル", f"{len(tests)} 本", command="名前で数えた（test_*.py、*.test.ts、*Test.php、*_spec.rb など）")
    dirs = {}
    for f in tests:
        d = f.rsplit("/", 1)[0] + "/" if "/" in f else "（直下）"
        dirs[d] = dirs.get(d, 0) + 1
    for d, n in sorted(dirs.items(), key=lambda x: (-x[1], x[0]))[:10]:
        F.add("試験", d, f"{n} 本", command="試験のファイルの置き場ごとに数えた")
    for f in t.files:
        b = base(f)
        if b in TEST_CONF or TEST_CONF_RX.match(b):
            F.add("試験", "試験の設定", b, f, 1)
        elif b == "pyproject.toml":
            for i, s in enumerate(t.lines(f), 1):
                if s.strip().startswith("[tool.pytest"):
                    F.add("試験", "試験の設定", "pyproject.toml の pytest の節", f, i)


def count_authors(emails):
    """メールの一覧から、作者の数を返す（大文字小文字をそろえ、[bot] を除く）。名前とメールは外に出さない。"""
    seen = set()
    for e in emails:
        e = e.strip().lower()
        if e and "[bot]" not in e:
            seen.add(e)
    return len(seen)


def team_style(a1, aall):
    if a1 >= 2:
        return "チーム"
    if a1 == 1:
        return "個人"
    if aall >= 2:
        return "チーム（この 1 年の commit は無い）"
    if aall == 1:
        return "個人（この 1 年の commit は無い）"
    return "不明（この場所の commit が無い）"


def c_git(t, F, exclude):
    root = t.root
    head, why = git_head(root)
    if why == "git の作業ツリーではない":
        F.add("履歴", "commit", f"無い（{why}）", command="git rev-parse --is-inside-work-tree")
        F.add("履歴", "開発の形", "不明（git の履歴が無い）", command="この 1 年の commit の作者の数で決める（2 人以上ならチーム）")
        return
    F.add("履歴", "commit", head if not why else f"無い（{why}）", command="git rev-parse --short HEAD")
    branch = (git(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    if branch:
        F.add("履歴", "ブランチ", "HEAD（どのブランチにも乗っていない）" if branch == "HEAD" else branch,
              command="git rev-parse --abbrev-ref HEAD")
    year = (git(root, "log", "--since=1.year", "--format=%aE", "--", ".") or "").splitlines()
    every = (git(root, "log", "--format=%aE%x09%cs", "--", ".") or "").splitlines()
    mails = [x.split("\t")[0] for x in every]
    dates = [x.split("\t")[1] for x in every if "\t" in x]
    a1, aall = count_authors(year), count_authors(mails)
    F.add("履歴", "この 1 年の commit", f"{len(year)} 本", command="git log --since=1.year --format=%aE -- .")
    F.add("履歴", "この 1 年の作者", f"{a1} 人", command="git log --since=1.year --format=%aE -- .（数だけ。[bot] を除く）")
    F.add("履歴", "全期間の作者", f"{aall} 人", command="git log --format=%aE -- .（数だけ。[bot] を除く）")
    if dates:
        F.add("履歴", "最後の commit の日", dates[0], command="git log --format=%cs -- .")
        F.add("履歴", "最初の commit の日", dates[-1], command="git log --format=%cs -- .")
    prefix = (git(root, "rev-parse", "--show-prefix") or "").strip()
    changed = 0
    for s in (git(root, "status", "--porcelain", "--untracked-files=all", "--", ".") or "").splitlines():
        path = s[3:].split(" -> ")[-1].strip('"')
        rel = path[len(prefix):] if prefix and path.startswith(prefix) else path
        if rel.startswith("tmp/") or excluded(rel, exclude):
            continue
        changed += 1
    F.add("履歴", "commit していない変更", f"{changed} 本", command="git status --porcelain --untracked-files=all -- .（tmp/ と --exclude を除く）")
    F.add("履歴", "開発の形", team_style(a1, aall), command="この 1 年の作者が 2 人以上ならチーム、1 人なら個人。0 人なら全期間の作者で決める")


def route_name(lines, i):
    for s in lines[i:i + 4]:
        m = PY_DEF.match(s)
        if m:
            return m.group(1)
    return ""


def c_routes(t, F):
    found, dead = [], 0
    for f in t.code():
        b, e = base(f), ext(f)
        lines = t.lines(f)
        for i, s in enumerate(lines, 1):
            hits = []
            if e == ".py":
                hits += [(m.group(1), m.group(2)) for m in PY_ROUTE.finditer(s)]
                if b == "urls.py":
                    hits += [("path", m.group(1)) for m in DJANGO.finditer(s)]
            elif e == ".php":
                hits += [(m.group(1), m.group(2)) for m in LARAVEL.finditer(s)]
            elif e == ".rb" and f.endswith("config/routes.rb"):
                m = RAILS.match(s)
                if m:
                    hits.append((m.group(1), m.group(2)))
            elif e in (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"):
                hits += [(m.group(1), m.group(2)) for m in JS_ROUTE.finditer(s)]
            elif e == ".go":
                hits += [("", m.group(1)) for m in GO_ROUTE.finditer(s)]
            elif e in (".java", ".kt"):
                hits += [(m.group(1), m.group(2)) for m in JAVA_ROUTE.finditer(s)]
            for method, path in hits:
                note = "注釈の中（動いていない）" if commented(s) else ""
                dead += 1 if note else 0
                name = route_name(lines, i) if e == ".py" else ""
                label = (method.upper() + " " if method and method.lower() not in ("route", "path", "api_route") else "") + (path or "/")
                found.append((label, "、".join(x for x in (name, note) if x) or "処理の名前はルートの定義の中", f, i))
    if any('"next"' in (t.text(f) or "") for f in t.files if base(f) == "package.json"):
        for f in t.files:
            m = re.match(r"^(?:src/)?app/(?:(.*)/)?(page|route)\.(tsx|ts|jsx|js|mdx)$", f)
            m2 = re.match(r"^(?:src/)?pages/(.+)\.(tsx|ts|jsx|js|mdx)$", f)
            if m:
                path = "/" + "/".join(p for p in (m.group(1) or "").split("/") if p and not p.startswith("("))
                found.append((path, "ファイルの置き場で決まるルート（" + m.group(2) + "）", f, 1))
            elif m2 and not base(f).startswith("_"):
                path = "/" + re.sub(r"(^|/)index$", "", m2.group(1))
                found.append((path, "ファイルの置き場で決まるルート（pages）", f, 1))
    for label, value, f, i in found[:ROUTE_CAP]:
        F.add("画面と API", label, value, f, i)
    if len(found) > ROUTE_CAP:
        F.add("画面と API", "ほかのルート", f"{len(found) - ROUTE_CAP} 本", command="上限まで出した")
    F.add("画面と API", "ルートの数", f"{len(found)} 本（注釈の中 {dead} 本）" if found else "0 本（決まった書き方が見つからない）",
          command="ルートを決める書き方を拾った（@route、@app.get、urls.py、Route::get、routes.rb、app.get、HandleFunc、@GetMapping、Next.js の置き場）")
    return [(label, f, i) for label, value, f, i in found if INBOUND.search(label) and "注釈" not in value]


def c_batch(t, F):
    n = 0
    for f in t.files:
        b, e = base(f), ext(f)
        if e == ".py":
            for i, s in enumerate(t.lines(f), 1):
                if MAIN_RX.match(s):
                    F.add("定時の処理", f"python {f}", "コマンドの入口（__main__）", f, i)
                    n += 1
        if e in CODE_EXT:
            for i, s in enumerate(t.lines(f), 1):
                m = SCHED_RX.search(s)
                if m and not commented(s):
                    F.add("定時の処理", "定時か非同期の処理の候補", redact(s.strip())[:60], f, i)
                    n += 1
            if NAME_BATCH.search(b):
                F.add("定時の処理", f, "名前からの候補（中身を読んで確かめる）", f, 1)
                n += 1
        if b == "crontab" or e == ".cron" or "/cron.d/" in "/" + f:
            for i, s in enumerate(t.lines(f), 1):
                if CRON_LINE.match(s) and not commented(s):
                    F.add("定時の処理", "cron の行", redact(s.strip())[:60], f, i)
                    n += 1
        if f.startswith(".github/workflows/") and e in (".yml", ".yaml"):
            for i, s in enumerate(t.lines(f), 1):
                m = GHA_CRON.match(s)
                if m:
                    F.add("定時の処理", "CI の定時の実行", m.group(1).strip(), f, i)
                    n += 1
    if not n:
        F.add("定時の処理", "定時の処理の候補", "見つからない", command="__main__、$schedule、@shared_task、cron、"
              "CI の schedule、名前（batch、job、cron ほか）で探した")


def c_external(t, F, inbound):
    for label, f, i in inbound[:CAP]:
        F.add("外とのつながり", f"外からの知らせ {label}", "ルートの名前からの候補", f, i)
    for rx, what in ((HTTP_OUT, "外への HTTP"), (MAIL_RX, "メールを送る")):
        k = 0
        for f in t.code():
            for i, s in enumerate(t.lines(f), 1):
                m = rx.search(s)
                if m and not commented(s) and k < 15:
                    F.add("外とのつながり", what, m.group(1).rstrip("("), f, i)
                    k += 1
    if not F.of("外とのつながり"):
        F.add("外とのつながり", "外とのつながりの候補", "見つからない", command="外からの知らせのルートの名前、外への HTTP、メールを探した")


def c_env(t, F):
    seen = {}
    for f in t.code():
        for i, s in enumerate(t.lines(f), 1):
            for rx in ENV_RXS:
                for m in rx.finditer(s):
                    seen.setdefault(m.group(1), (f, i))
    env_files = [f for f in t.files if base(f).startswith(".env")]
    keys = {}
    for f in env_files:
        for i, s in enumerate(t.lines(f), 1):
            m = ENV_KEY.match(s)
            if m and not s.lstrip().startswith("#"):
                keys.setdefault((m.group(1), f), i)
    db_names = []
    for name, (f, i) in sorted(seen.items()):
        if DB_KEY.search(name):
            db_names.append((name, "コードが読む環境変数（値は出さない）", f, i))
        elif len(F.of("設定の口")) < CAP:
            F.add("設定の口", name, "コードが読む環境変数（値は出さない）", f, i)
    for (name, f), i in sorted(keys.items()):
        if DB_KEY.search(name):
            db_names.append((name, f"{base(f)} のキー（値は読まない）", f, i))
        elif len(F.of("設定の口")) < CAP:
            F.add("設定の口", name, f"{base(f)} のキー（値は読まない）", f, i)
    if not F.of("設定の口") and not db_names:
        F.add("設定の口", "環境変数と .env のキー", "見つからない", command="os.environ、process.env、env()、ENV[]、.env のキーを探した")
    return db_names


def c_db(t, F, db_names):
    for name, value, f, i in db_names[:CAP]:
        F.add("DB", f"接続の設定の口 {name}", value, f, i)
    for f in t.files:
        if ext(f) in SQLITE_EXT:
            try:
                with open(t.root / f, "rb") as fh:
                    head = fh.read(16)
                size = (t.root / f).stat().st_size
            except OSError:
                continue
            if head == b"SQLite format 3\x00":
                F.add("DB", f"sqlite のファイル {f}", f"{max(1, size // 1024)} KB", command="先頭の 16 バイトで sqlite と確かめた")
    mig = {}
    for f in t.files:
        d = f.rsplit("/", 1)[0] if "/" in f else ""
        if base(d) in ("migrations", "migrate") or d.endswith(MIGRATION_TAILS):
            mig[d] = mig.get(d, 0) + 1
    for d, n in sorted(mig.items())[:CAP]:
        F.add("DB", f"マイグレーション {d}/", f"{n} 本", command="マイグレーションの置き場のファイルを数えた")
    for f in t.files:
        b = base(f)
        if b in SCHEMA_FILES:
            F.add("DB", "スキーマのファイル", f, f, 1)
        elif DB_CONF.match(b):
            lines = t.lines(f)
            hit = next((i for i, s in enumerate(lines, 1) if re.search(r"DATABASES\s*=|datasource\s+\w+|default:|connections", s)), 0)
            if b != "settings.py" or hit:
                F.add("DB", "DB の設定のファイル", f"{b}（値は読まない）", f, hit or 1)
    k = 0
    for f in t.code():
        for i, s in enumerate(t.lines(f), 1):
            m = DB_LIB.search(s)
            if m and not commented(s) and k < 10:
                F.add("DB", "DB につなぐ所", m.group(1).rstrip("("), f, i)
                k += 1
    if not F.of("DB"):
        F.add("DB", "DB の手がかり", "見つからない", command="sqlite のファイル、マイグレーション、スキーマ、DB の設定、DB につなぐ書き方を探した")


def c_docs(t, F):
    docs = [f for f in t.files if ext(f) in DOC_EXT]
    F.add("文書", "文書のファイル", f"{len(docs)} 本", command="拡張子で数えた（.md、.txt、.rst ほか）")
    k = 0
    for f in docs:
        b = base(f)
        guess = next((g for rx, g in DOC_GUESS if rx.search(b)), "")
        if guess and k < CAP:
            F.add("文書", f, guess, f, 1)
            k += 1
    for f in t.files:
        if f.startswith(".github/") and re.search(r"(?i)(pull_request_template|issue_template)", f):
            F.add("文書", f, "PR か Issue の型", f, 1)
        elif LINT_FILES.match(base(f)):
            F.add("決まり", base(f), "書き方の決まりの設定", f, 1)
        elif base(f) == "pyproject.toml":
            for i, s in enumerate(t.lines(f), 1):
                if re.match(r"^\[tool\.(ruff|black|isort|flake8|mypy)", s.strip()):
                    F.add("決まり", s.strip(), "書き方の決まりの設定", f, i)
    if not F.of("決まり"):
        F.add("決まり", "書き方の決まりの設定", "見つからない", command=".editorconfig、eslint、prettier、ruff、rubocop などを探した")


def c_ui(t, F):
    dirs = {}
    for f in t.files:
        parts = f.split("/")[:-1]
        for k, p in enumerate(parts):
            if p in UI_DIRS:
                d = "/".join(parts[:k + 1]) + "/"
                dirs[d] = dirs.get(d, 0) + 1
                break
    for d, n in sorted(dirs.items(), key=lambda x: (-x[1], x[0]))[:15]:
        F.add("UI の部品", d, f"{n} 本", command="components、views、templates などの置き場のファイルを数えた")
    per, total = [], 0
    for f in t.files:
        if ext(f) in STYLE_EXT:
            lines = t.lines(f)
            hits = [i for i, s in enumerate(lines, 1) if CSS_VAR.search(s)]
            if hits:
                per.append((len(hits), f, hits[0]))
                total += len(hits)
    for n, f, i in sorted(per, reverse=True)[:5]:
        F.add("UI の部品", f"CSS の変数 {f}", f"{n} 個", f, i)
    for f in t.files:
        b = base(f)
        if re.match(r"^tailwind\.config\.(js|cjs|mjs|ts)$", b) or b in ("tokens.json", "components.json") or \
                re.match(r"^theme\.(js|ts|json)$", b):
            F.add("UI の部品", "値の置き場", b, f, 1)
    if not F.of("UI の部品"):
        F.add("UI の部品", "部品と値", "見つからない", command="components、views、templates の置き場、CSS の変数（--名前:）、"
              "tailwind.config を探した")


def collect_facts(root, max_files=MAX_FILES, exclude=()):
    files, over = walk(root, max_files, exclude)
    t = Tree(root, files)
    F = Facts()
    c_scope(t, F, over, list(exclude), max_files)
    c_lang(t, F)
    c_dirs(t, F)
    c_versions(t, F)
    c_commands(t, F)
    c_tests(t, F)
    c_git(t, F, exclude)
    inbound = c_routes(t, F)
    c_batch(t, F)
    c_external(t, F, inbound)
    db_names = c_env(t, F)
    c_db(t, F, db_names)
    c_docs(t, F)
    c_ui(t, F)
    code_read = len([f for f in t.code() if f in t.cache and t.cache[f] is not None])
    F.add("読んだ範囲", "中身を読んだコードのファイル", f"{code_read} 本", command="拡張子で選んだコードのファイル")
    F.add("読んだ範囲", "中身を読めなかったファイル", f"{len(t.unread)} 本（1 MB より大きいか、文字でないか、リンク）",
          command="読もうとしたファイルのうち")
    order = {k: n for n, k in enumerate(KIND_ORDER)}
    return sorted(F.items, key=lambda r: order.get(r["kind"], len(order)))


def evidence_text(rec):
    if rec.get("source") and rec.get("line"):
        return f"{rec['source']}:{rec['line']}"
    return rec.get("command") or rec.get("source") or ""


def md_cell(v):
    return str(v).replace("|", "\\|").replace("\n", " ")


def append_facts(log_path, recs):
    """番号（F-001 の形の続き番号）を振り、ハッシュ値を付けて記録に足す。前の番号は消さない。"""
    p = pathlib.Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            last = 0
            for line in f.read().splitlines():
                try:
                    m = re.fullmatch(r"F-(\d+)", str(json.loads(line).get("id", "")))
                except (ValueError, AttributeError):
                    continue
                if m:
                    last = max(last, int(m.group(1)))
            for rec in recs:
                last += 1
                rec["id"] = f"F-{last:03d}"
                rec["hash"] = rec_hash(rec)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return recs


def inside(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def run_facts(argv):
    ap = argparse.ArgumentParser(prog="catchup-facts.sh")
    ap.add_argument("--root", default=".", help="プロジェクトの直下")
    ap.add_argument("--out", default="", help="事実の記録（JSON Lines）。tmp/catchup/facts.jsonl のように tmp/ の下に置く")
    ap.add_argument("--exclude", action="append", default=[], help="読まない所（直下からのパスか、名前の型）。何度でも渡せる")
    ap.add_argument("--max-files", type=int, default=MAX_FILES)
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)
    rep = Report(NAMES["facts"], args.root)
    if not root.is_dir():
        rep.fail(args.root, "無い", "プロジェクトの直下が無い")
        return rep.show()
    if args.out:
        out = pathlib.Path(args.out)
        if inside(out, root) and not inside(out, root / "tmp"):
            rep.fail(args.out, "書く場所", "事実の記録は、プロジェクトの tmp/ の下（tmp/catchup/facts.jsonl）か、プロジェクトの外に置く")
            return rep.show()
    recs = collect_facts(root, args.max_files, [x for x in args.exclude if x.strip()])
    at = now_iso()
    for r in recs:
        r.update({"tool": NAMES["facts"], "at": at})
    if args.out:
        append_facts(args.out, recs)
    print("| 番号 | 種類 | 項目 | 値 | 根拠 |")
    print("|---|---|---|---|---|")
    for r in recs:
        print(f"| {r.get('id', '-')} | {md_cell(r['kind'])} | {md_cell(r['item'])} | {md_cell(r['value'])} | {md_cell(evidence_text(r))} |")
    if not args.out:
        rep.say("INFO 番号は --out で記録したときに付く。地図の根拠に使うときは --out tmp/catchup/facts.jsonl で回す")
    return rep.show(f"事実 {len(recs)}、記録 {args.out or 'なし'}")


# ---------------------------------------------------------------- 地図の検査（map-check）
HEADING_RX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
CELL_SPLIT = re.compile(r"(?<!\\)\|")
PLACEHOLDER_RX = re.compile(r"<[^<>|`\n]{1,80}>")
COMMENT_RX = re.compile(r"<!--.*?-->", re.S)
# 根拠の「ファイル:行」。拡張子の無い決まった名前（Dockerfile ほか）と、点で始まる名前（.python-version）も読む。
# 空白や引用の字を含むパスは「`パス`:行」と書く。backend の data_tools.py と同じ形にそろえる
BARE_FILES = (r"(?:Dockerfile|Containerfile|Makefile|GNUmakefile|makefile|Procfile|Gemfile|Rakefile|Jenkinsfile|Vagrantfile|"
              r"Brewfile|Pipfile|Caddyfile|Justfile|Taskfile|crontab|LICENSE|README)")
PATH_PART = r"(?<![\w.\-/])(?:[\w.\-]+/)*(?:[\w\-][\w.\-]*\.[A-Za-z]\w*|\.[A-Za-z][\w.\-]*|" + BARE_FILES + r"(?![\w.\-]))"
LINE_PART = r"(?::(?P<a>\d+)(?:[-–〜](?P<b>\d+))?|\s*の\s*(?P<c>\d+)(?:\s*[〜-]\s*(?P<d>\d+))?\s*行)"
EVIDENCE_RX = re.compile(r"(?P<path>" + PATH_PART + r")" + LINE_PART)
TICK_EVIDENCE_RX = re.compile(r"`(?P<path>[^`\n]+)`" + LINE_PART)
QREF_RX = re.compile(r"\bQ-\d+\b")
FREF_RX = re.compile(r"\bF-\d+\b")
HEAR_RX = re.compile(r"聞き取り[（(]?\s*(\d{4}-\d{2}-\d{2})")
LINK_RX = re.compile(r"\]\(([^)\s]+)\)")
TICK_RX = re.compile(r"`([^`\s]+)`")
DATE_RX = re.compile(r"\d{4}-\d{2}-\d{2}")
HEX_RX = re.compile(r"\b[0-9a-f]{7,40}\b")


def evidence_refs(text):
    """根拠の「ファイル:行」を拾う。返り値は [(パス, 最初の行, 最後の行)]。`パス`:行 の形は、空白を含むパスも読む。"""
    blank = TICK_EVIDENCE_RX.sub(lambda m: " " * len(m.group(0)), text)
    out = []
    for m in list(TICK_EVIDENCE_RX.finditer(text)) + list(EVIDENCE_RX.finditer(blank)):
        rel = m.group("path").strip()
        if rel.startswith(("http", "www.")) or re.fullmatch(r"[\d.]+", rel):
            continue
        first = int(m.group("a") or m.group("c"))
        out.append((rel, first, int(m.group("b") or m.group("d") or first)))
    return out


def inside_root(root, rel):
    try:
        (root / rel).resolve().relative_to(pathlib.Path(root).resolve())
        return True
    except ValueError:
        return False


def split_cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in CELL_SPLIT.split(s)]


def md_tables(lines):
    tabs, heading, i, in_code = [], "", 0, False
    while i < len(lines):
        s = lines[i]
        if s.strip().startswith("```"):
            in_code = not in_code
            i += 1
            continue
        if in_code:
            i += 1
            continue
        m = HEADING_RX.match(s)
        if m:
            heading = m.group(2)
            i += 1
            continue
        if s.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            header = split_cells(s)
            rows, j = [], i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append((j + 1, split_cells(lines[j])))
                j += 1
            tabs.append({"heading": heading, "header": header, "rows": rows, "line": i + 1})
            i = j
            continue
        i += 1
    return tabs


def header_info(tabs):
    info = {}
    for t in tabs:
        if len(t["header"]) >= 2 and t["header"][0] == "項目" and t["header"][1] == "内容":
            for no, cells in t["rows"]:
                if cells and cells[0] not in info:
                    info[cells[0]] = (cells[1] if len(cells) > 1 else "", no)
    return info


def load_jsonl(path):
    """返り値は ({番号: 記録}, [(行, 理由)])。"""
    by_id, errs = {}, []
    for no, line in enumerate(pathlib.Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError as e:
            errs.append((no, f"JSON として読めない（{e}）"))
            continue
        if isinstance(obj, dict) and obj.get("id"):
            by_id.setdefault(obj["id"], obj)
    return by_id, errs


def link_target(cell_text):
    m = LINK_RX.search(cell_text)
    if m:
        return m.group(1)
    m = TICK_RX.search(cell_text)
    if m and m.group(1).endswith(".md"):
        return m.group(1)
    m = re.search(r"[\w./-]+\.md\b", cell_text)
    return m.group(0) if m else ""


def holes(path, lines, rep, label):
    text = COMMENT_RX.sub(lambda m: "\n" * m.group(0).count("\n"), "\n".join(lines))
    found = [(no, m.group(0)) for no, s in enumerate(text.split("\n"), 1) for m in PLACEHOLDER_RX.finditer(s)]
    for no, h in found[:5]:
        rep.fail(f"{path}:{no}", "テンプレートの穴", f"{label}の {h} が埋まっていない")
    if len(found) > 5:
        rep.fail(str(path), "テンプレートの穴", f"ほか {len(found) - 5} か所")


class MapCtx:
    def __init__(self, map_dir, root, rep):
        self.map_dir, self.root, self.rep = map_dir, root, rep
        self.facts, self.queries = None, None
        self.files_by_section = {}

    def log(self, kind, info):
        attr = "facts" if kind == "F" else "queries"
        if getattr(self, attr) is None:
            key = "事実の記録" if kind == "F" else "クエリの記録"
            name = FACTS_FILE if kind == "F" else QUERIES_FILE
            val = info.get(key, ("", 0))[0]
            m = re.search(r"[\w./-]+\.jsonl", val)
            p = self.map_dir / (m.group(0) if m else name)
            if p.is_file():
                by_id, errs = load_jsonl(p)
                for no, why in errs:
                    self.rep.fail(f"{p}:{no}", "記録の形", why)
                setattr(self, attr, (p, by_id))
            else:
                setattr(self, attr, (p, None))
        return getattr(self, attr)


def row_evidence(ctx, info, path, no, text, section):
    """表の行の根拠を確かめ、見つけた根拠の数を返す。ファイルの根拠は、節ごとの鮮度の対象に足す。"""
    files = ctx.files_by_section.setdefault(section, set())
    n = 0
    for rel, line, last in evidence_refs(text):
        n += 1
        p = ctx.root / rel
        if not inside_root(ctx.root, rel):
            ctx.rep.fail(f"{path}:{no}", "根拠の実在", f"根拠 {rel} がプロジェクトの直下（{ctx.root}）の外を指す")
            continue
        if not p.is_file():
            ctx.rep.fail(f"{path}:{no}", "根拠の実在", f"根拠のファイル {rel} が無い（プロジェクトの直下は {ctx.root}）")
            continue
        total = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        if line < 1 or last > total:
            ctx.rep.fail(f"{path}:{no}", "根拠の実在", f"{rel} の {last} 行が無い（{total} 行のファイル）")
            continue
        files.add(rel)
    for kind, rx in (("Q", QREF_RX), ("F", FREF_RX)):
        for rid in rx.findall(text):
            n += 1
            lp, by_id = ctx.log(kind, info)
            rec = by_id.get(rid) if by_id else None
            if rec is None:
                ctx.rep.fail(f"{path}:{no}", "根拠の実在", f"{rid} が記録 {lp.name} に無い")
                continue
            if rec.get("hash") != rec_hash(rec):
                ctx.rep.fail(f"{path}:{no}", "ハッシュ値", f"{rid} の記録が、道具の書いたあとに変わった（ハッシュ値が合わない）")
            if kind == "F" and rec.get("source") and rec.get("line"):
                if (ctx.root / rec["source"]).is_file():
                    files.add(rec["source"])
                else:
                    ctx.rep.fail(f"{path}:{no}", "根拠の実在", f"{rid} の根拠のファイル {rec['source']} が無い")
    n += len(HEAR_RX.findall(text))
    return n


def check_section(ctx, info, name, path):
    rep = ctx.rep
    lines = path.read_text(encoding="utf-8").split("\n")
    h1 = next((s for s in lines if s.startswith("# ")), "")
    if name not in h1:
        rep.fail(f"{path}:1", "節の表題", f"表題（# の行）に節の名前「{name}」が無い")
    holes(path, lines, rep, f"節「{name}」")
    rows = 0
    for t in md_tables(lines):
        for no, cells in t["rows"]:
            rows += 1
            if not row_evidence(ctx, info, path, no, " ".join(cells), name):
                rep.fail(f"{path}:{no}", "根拠", "表の行に根拠が無い（ファイルと行、クエリの番号、事実の番号、聞き取りの日付のどれか）")
    if not rows:
        rep.fail(str(path), "根拠", f"節「{name}」に表の行が無い。主張は、根拠と一緒に表の行に書く")
    return rows


_DICT_CACHE = {}


def data_files(root, lines):
    """データの節の表が根拠に挙げた、直下の中のファイル（鮮度の対象）。根拠の検査そのものは data-dictionary-check.sh が持つ。"""
    out = set()
    for t in md_tables(lines):
        for _, cells in t["rows"]:
            for rel, _, _ in evidence_refs(" ".join(cells)):
                if inside_root(root, rel) and (root / rel).is_file():
                    out.add(rel)
    return out


def check_data(ctx, path):
    rep = ctx.rep
    lines = path.read_text(encoding="utf-8").split("\n")
    h1 = next((s for s in lines if s.startswith("# ")), "")
    if DATA not in h1:
        rep.fail(f"{path}:1", "節の表題", f"表題（# の行）に節の名前「{DATA}」が無い")
    files = ctx.files_by_section.setdefault(DATA, set())
    files |= data_files(ctx.root, lines)
    if not DICT_CHECK.is_file():
        rep.fail(str(path), "道具が無い", f"データの節を見る {DICT_CHECK} が無い（backend のスキルを写す）")
        return
    key = (file_sha(path), str(ctx.root))
    if key not in _DICT_CACHE:
        p = subprocess.run(["bash", str(DICT_CHECK), str(path), "--root", str(ctx.root)], capture_output=True, text=True,
                           timeout=120)
        _DICT_CACHE[key] = (p.returncode, p.stdout + p.stderr)
    rc, out = _DICT_CACHE[key]
    if rc != 0:
        bad = [s[5:] for s in out.splitlines() if s.startswith("FAIL ")]
        for s in bad[:10] or [out.strip().splitlines()[-1] if out.strip() else "終了コードが 0 でない"]:
            rep.fail(str(path), "データの節", s)
        if len(bad) > 10:
            rep.fail(str(path), "データの節", f"ほか {len(bad) - 10} 件（data-dictionary-check.sh を回して見る）")


def check_inbox(ctx, info, path):
    rep = ctx.rep
    lines = path.read_text(encoding="utf-8").split("\n")
    holes(path, lines, rep, "追記の候補")
    names = [n for n, _ in SECTIONS]
    tab = next((t for t in md_tables(lines) if all(any(k in h for h in t["header"]) for k in ("日付", "節", "状態"))), None)
    if tab is None:
        rep.fail(str(path), "追記の候補", "追記の候補の表（日付、節、気づいたこと、根拠、状態）が無い")
        return 0
    h = tab["header"]
    kd, ks, kst = (next(k for k, x in enumerate(h) if w in x) for w in ("日付", "節", "状態"))
    waiting = 0
    for no, cells in tab["rows"]:
        get = (lambda k: cells[k] if k < len(cells) else "")
        if not DATE_RX.search(get(kd)):
            rep.fail(f"{path}:{no}", "追記の候補", "日付（2026-11-26 の形）が無い")
        if get(ks).strip() not in names:
            rep.fail(f"{path}:{no}", "追記の候補", f"節「{get(ks)}」は 6 つの節（{'、'.join(names)}）のどれでもない")
        state = get(kst).strip()
        if not state.startswith(INBOX_STATES):
            rep.fail(f"{path}:{no}", "追記の候補", f"状態「{state}」。{'、'.join(INBOX_STATES)}のどれかで始める")
        waiting += 1 if state.startswith("未処理") else 0
        text = " ".join(cells)
        if not (evidence_refs(text) or QREF_RX.search(text) or FREF_RX.search(text) or HEAR_RX.search(text)
                or re.search(r"tmp/[\w./-]+", text)):
            rep.fail(f"{path}:{no}", "追記の候補", "根拠（ファイルと行、クエリの番号、事実の番号、聞き取りの日付、tmp/ の文書）が無い")
    if waiting:
        rep.say(f"INFO 追記の候補が {waiting} 件、未処理。次のキャッチアップ（更新）で地図に入れる")
    return waiting


def index_commit(info):
    val = info.get("commit", ("", 0))[0]
    m = HEX_RX.search(val)
    if m:
        return m.group(0)
    return "無い" if "無い" in val else ""


def same_commit(a, b):
    if a == "無い" or b == "無い":
        return a == b
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


CONFIG_NAMES = {"package.json", "composer.json", "Gemfile", "go.mod", "pyproject.toml", "setup.cfg", "setup.py", "Makefile",
                "makefile", "GNUmakefile", "Procfile", "manage.py", "artisan", "pom.xml", "build.gradle", "build.gradle.kts",
                "crontab", ".tool-versions"}


def tree_sections(rel):
    """増えたか消えたファイルが当たる節。コードは入口・データ・構成、マイグレーションは データ、設定は構成と入口、文書は開発の形。"""
    b, e, dirs = base(rel), ext(rel), rel.split("/")[:-1]
    out = set()
    if e in CODE_EXT:
        out |= {"入口", DATA, "構成と動かし方"}
    if e == ".sql" or e in SQLITE_EXT or b in SCHEMA_FILES or DB_CONF.match(b) or any(d in ("migrations", "migrate") for d in dirs):
        out.add(DATA)
    if (b in CONFIG_NAMES or b in VERSION_FILES or b.startswith("Dockerfile") or re.fullmatch(r"requirements.*\.txt", b)
            or re.fullmatch(r"(docker-)?compose(\.[\w-]+)?\.ya?ml", b) or e == ".cron" or rel.startswith(".github/workflows/")):
        out |= {"構成と動かし方", "入口"}
    if e in DOC_EXT or LINT_FILES.match(b) or e in STYLE_EXT or any(d in UI_DIRS for d in dirs):
        out.add("開発の形")
    return out


def facts_exclude(ctx, info):
    """最後の catchup-facts.sh の回で、--exclude に渡した所。走査したファイルの一覧を、同じ範囲で作るために使う。"""
    _, by_id = ctx.log("F", info)
    recs = list((by_id or {}).values())
    if not recs:
        return []
    last = max(str(r.get("at", "")) for r in recs)
    hit = [r for r in recs if str(r.get("at", "")) == last and r.get("kind") == "読んだ範囲"
           and str(r.get("item", "")).startswith("読まない所")]
    return [x for x in str(hit[0].get("value", "")).split("、") if x.strip()] if hit else []


def numbers_of(rec):
    out = []
    for r in (rec or {}).get("rows", []):
        for v in (r if isinstance(r, list) else []):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(float(v))
            elif isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v.strip()):
                out.append(float(v))
    return out


NUM_ONLY = re.compile(r"(?<![\w.,-])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?:\s*(万|億))?")


def first_number(text):
    """表の値の最初の数（番号、日付、ファイルの行を外す）。無ければ None。"""
    t = re.sub(r"\b[QFT]-\d+\b", " ", text)
    t = re.sub(r"\d{4}-\d{2}(?:-\d{2})?", " ", t)
    t = EVIDENCE_RX.sub(" ", TICK_EVIDENCE_RX.sub(" ", t))
    m = NUM_ONLY.search(t)
    if not m:
        return None
    return float(m.group(1).replace(",", "") + (m.group(2) or "")) * {"万": 1e4, "億": 1e8}.get(m.group(3), 1)


def check_index_baselines(ctx, info, index, t):
    """入口の基準の数字の表（C-5）。「一致」の行は、画面の値と数えた値が等しく、どちらも出どころの数と合う。"""
    hs = t["header"]
    km = next((k for k, h in enumerate(hs) if "一致" in h), None)
    kc = next((k for k, h in enumerate(hs) if "数えた" in h), None)
    kb = next((k for k, h in enumerate(hs) if k not in (km, kc) and ("集計の値" in h or "基準の値" in h)), None)
    if km is None or kc is None or kb is None:
        return
    _, by_q = ctx.log("Q", info)
    for no, cells in t["rows"]:
        base_v, counted, verdict = (cells[k] if k < len(cells) else "" for k in (kb, kc, km))
        if not verdict.strip().startswith("一致") or verdict.strip().startswith("一致しない"):
            continue
        b, c = first_number(base_v), first_number(counted)
        if b is None or c is None or abs(b - c) > 1e-9:
            ctx.rep.fail(f"{index}:{no}", "基準の数字", f"「一致」と書いたが、基準の値（{base_v}）と数えた値（{counted}）が違う")
            continue
        for val, need_q, label in ((base_v, False, "基準の値"), (counted, True, "数えた値")):
            qids = QREF_RX.findall(val)
            if not qids and (need_q or ("依頼の文" not in val and not HEAR_RX.search(val))):
                ctx.rep.fail(f"{index}:{no}", "基準の数字", f"{label}（{val}）に出どころ（クエリの番号{'' if need_q else '、依頼の文、聞き取り'}）が無い")
            elif qids and by_q is not None and not any(abs(v - b) < 1e-9 for q in qids for v in numbers_of(by_q.get(q))):
                ctx.rep.fail(f"{index}:{no}", "基準の数字", f"{label}（{val}）の数が、{', '.join(qids)} の結果に無い")


def freshness(ctx, info, sections, stamp):
    """節ごとに、根拠のファイルが地図を作ったときから変わっていないかを見る。走査したファイルが増えたか消えたときも、
    当たる節を古いとする（新しいルートやマイグレーションを、根拠のファイルの比べだけでは見落とすため）。返り値は古い節の名前の一覧。"""
    rep, old = ctx.rep, []
    files = stamp.get("files", {})
    commit = stamp.get("commit", "")
    tree, moved = stamp.get("tree"), {}
    if not isinstance(tree, dict) or not isinstance(tree.get("files"), list):
        rep.fail(str(ctx.map_dir / STAMP_FILE), "鮮度", "stamp.json に走査したファイルの一覧が無い（前の版の記録）。"
                 "節を読み直してから map-check.sh --stamp で記録し直す")
    else:
        now, _ = walk(ctx.root, MAX_FILES, tree.get("exclude", []))
        before, now = set(tree["files"]), set(now)
        for rel in sorted(now ^ before):
            for name in tree_sections(rel):
                moved.setdefault(name, []).append((rel, "増えた" if rel in now else "消えた"))
    for name, _ in sections:
        changed = []
        for rel, how in moved.get(name, []):
            changed.append(f"{rel}（{how}）")
            if len(changed) <= 5:
                rep.fail(str(ctx.map_dir / STAMP_FILE), "古い", f"節「{name}」に当たるファイル {rel} が、地図を作った commit {commit} の"
                         f"あとに{how}。この節を読み直す")
        if len(changed) > 5:
            rep.fail(str(ctx.map_dir / STAMP_FILE), "古い", f"節「{name}」に当たる、増えたか消えたファイルがほか {len(changed) - 5} 本")
        for rel in sorted(ctx.files_by_section.get(name, set())):
            rec = files.get(rel)
            p = ctx.root / rel
            if rec is None:
                rep.fail(str(ctx.map_dir / STAMP_FILE), "鮮度", f"節「{name}」の根拠 {rel} が、地図を作ったときの記録に無い。"
                         "節を書き足したら map-check.sh --stamp で記録し直す")
                continue
            if not p.is_file():
                changed.append(rel)
                rep.fail(str(ctx.map_dir / STAMP_FILE), "古い", f"節「{name}」の根拠 {rel} が消えた（地図は commit {commit} のとき）")
            elif file_sha(p) != rec.get("sha256"):
                changed.append(rel)
                rep.fail(str(ctx.map_dir / STAMP_FILE), "古い", f"節「{name}」の根拠 {rel} が、地図を作った commit {commit} のあとに"
                         "変わった。この節を読み直す")
        if changed:
            old.append(name)
            rep.say(f"SECTION {name} 古い（{'、'.join(changed)}）")
        else:
            rep.say(f"SECTION {name} 新しい")
    return old


def resolve_root(map_dir, root_arg):
    if root_arg:
        return pathlib.Path(root_arg).resolve()
    md = map_dir.resolve()
    if md.name == "catchup" and md.parent.name == "tmp":
        return md.parent.parent
    return None


def run_check(argv):
    ap = argparse.ArgumentParser(prog="map-check.sh")
    ap.add_argument("map", nargs="?", default="tmp/catchup", help="地図の置き場（既定は tmp/catchup）")
    ap.add_argument("--root", default="", help="プロジェクトの直下（地図が <直下>/tmp/catchup にあれば要らない）")
    ap.add_argument("--fresh", action="store_true", help="鮮度だけを見る")
    ap.add_argument("--stamp", action="store_true", help="検査を通したら、commit と根拠のハッシュ値を stamp.json に記録する")
    args = ap.parse_args(argv)
    map_dir = pathlib.Path(args.map)
    rep = Report(NAMES["check"] + (" --stamp" if args.stamp else " --fresh" if args.fresh else ""), args.map)
    if not map_dir.is_dir():
        rep.fail(args.map, "無い", "地図の置き場が無い。キャッチアップがまだなら、最初の返答で 1 行伝えて依頼を進める")
        return rep.show()
    root = resolve_root(map_dir, args.root)
    if root is None or not root.is_dir():
        rep.fail(args.map, "使い方", "--root でプロジェクトの直下を渡す（地図が <直下>/tmp/catchup に無いとき）")
        return rep.show()
    ctx = MapCtx(map_dir, root, rep)
    index = map_dir / INDEX_FILE
    if not index.is_file():
        rep.fail(str(index), "入口", "入口の 1 枚 index.md が無い")
        return rep.show()
    lines = index.read_text(encoding="utf-8").split("\n")
    n_lines = len(index.read_text(encoding="utf-8").splitlines())
    tabs = md_tables(lines)
    info = header_info(tabs)
    nav = next((t for t in tabs if any("節" in h for h in t["header"]) and any("ファイル" in h for h in t["header"])), None)
    kf = next((k for k, h in enumerate(nav["header"]) if "ファイル" in h), 1) if nav else 1
    paths = {}
    for name, _ in SECTIONS + [INBOX]:
        row = next(((no, c) for no, c in (nav["rows"] if nav else []) if c and c[0].strip("`* ") == name), None)
        if row is None:
            rep.fail(str(index), "節の案内", f"入口の節の表（節、ファイルの列）に「{name}」への案内が無い")
            continue
        no, cells = row
        target = link_target(cells[kf] if kf < len(cells) else "")
        p = (map_dir / target) if target else None
        if p is None or not p.is_file():
            rep.fail(f"{index}:{no}", "節の案内", f"「{name}」のファイル {target or '（無し）'} が無い")
            continue
        paths[name] = p
    stamp_path = map_dir / STAMP_FILE
    if not args.fresh:
        if n_lines > INDEX_MAX:
            rep.fail(str(index), "入口の長さ", f"{n_lines} 行。{INDEX_MAX} 行以内にし、詳しい中身は節のファイルへ移す")
        holes(index, lines, rep, "入口")
        for key in ("commit", "作った日"):
            val, no = info.get(key, ("", 0))
            if not val.strip():
                rep.fail(f"{index}:{no}", "入口", f"冒頭の表（項目、内容）に「{key}」が無い")
        made = info.get("作った日", ("", 0))
        if made[0] and not DATE_RX.search(made[0]):
            rep.fail(f"{index}:{made[1]}", "入口", "作った日に日付（2026-11-26 の形）が無い")
        if info.get("commit") and not index_commit(info):
            rep.fail(f"{index}:{info['commit'][1]}", "入口", "commit が 7〜40 字の 16 進でも「無い」でもない")
        perm, pno = info.get(PERMIT, ("", 0))
        if not perm.strip():
            rep.fail(f"{index}:{pno}", "入口", f"冒頭の表に「{PERMIT}」が無い（許可した日と相手と範囲。読める DB が無ければ「無い」）")
        elif not DATE_RX.search(perm) and "無い" not in perm:
            rep.fail(f"{index}:{pno}", "入口", f"「{PERMIT}」に、許可した日（2026-11-26 の形）か「無い」が無い")
        for t in tabs:
            if t is nav or (len(t["header"]) >= 2 and t["header"][0] == "項目" and t["header"][1] == "内容"):
                continue
            for no, cells in t["rows"]:
                text = " ".join(cells)
                found_ev = row_evidence(ctx, info, index, no, text, INDEX_SECTION)  # 案内のある行も、根拠は鮮度の対象にする
                if not link_target(text) and not found_ev:
                    rep.fail(f"{index}:{no}", "根拠", "入口の表の行に、節への案内も根拠も無い")
            check_index_baselines(ctx, info, index, t)
        rows = 0
        for name, _ in SECTIONS:
            if name not in paths:
                continue
            if name == DATA:
                check_data(ctx, paths[name])
            else:
                rows += check_section(ctx, info, name, paths[name])
        if INBOX[0] in paths:
            check_inbox(ctx, info, paths[INBOX[0]])
    else:
        # 鮮度だけを見る。節と入口の 1 枚の根拠のファイルを、検査の FAIL を出さずに集める
        quiet = Report("quiet")
        sub = MapCtx(map_dir, root, quiet)
        for t in tabs:
            if t is nav or (len(t["header"]) >= 2 and t["header"][0] == "項目" and t["header"][1] == "内容"):
                continue
            for no, cells in t["rows"]:
                row_evidence(sub, info, index, no, " ".join(cells), INDEX_SECTION)
        for name, _ in SECTIONS:
            if name not in paths:
                continue
            sec_lines = paths[name].read_text(encoding="utf-8").split("\n")
            if name == DATA:
                sub.files_by_section.setdefault(DATA, set()).update(data_files(root, sec_lines))
                continue
            for t in md_tables(sec_lines):
                for no, cells in t["rows"]:
                    row_evidence(sub, info, paths[name], no, " ".join(cells), name)
        ctx.files_by_section.update(sub.files_by_section)
        ctx.facts, ctx.queries = sub.facts, sub.queries
    if args.stamp:
        if rep.items:
            rep.say("INFO 検査が通るまで stamp.json は書かない")
            return rep.show("記録しなかった")
        head, why = git_head(root)
        ic = index_commit(info)
        if not same_commit(ic, head):
            rep.fail(f"{index}:{info.get('commit', ('', 0))[1]}", "鮮度", f"入口の commit「{ic or '（無し）'}」が、今の HEAD「{head}」と違う。入口を直してから記録する")
            return rep.show("記録しなかった")
        allf = sorted(set().union(*ctx.files_by_section.values()) if ctx.files_by_section else set())
        exclude = facts_exclude(ctx, info)
        tree, _ = walk(root, MAX_FILES, exclude)
        stamp = {"tool": NAMES["check"], "at": now_iso(), "commit": head,
                 "files": {rel: {"sha256": file_sha(root / rel), "lines": len((root / rel).read_text(encoding="utf-8", errors="replace").splitlines())}
                           for rel in allf},
                 "sections": {name: sorted(ctx.files_by_section.get(name, set())) for name, _ in SECTIONS + [(INDEX_SECTION, "")]},
                 "tree": {"exclude": exclude, "files": tree}}
        stamp["hash"] = rec_hash(stamp)
        stamp_path.write_text(json.dumps(stamp, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        rep.say(f"STAMP 根拠のファイル {len(allf)} 本のハッシュ値と、走査したファイル {len(tree)} 本の一覧と、commit {head} を "
                f"{stamp_path} に記録した")
        return rep.show(f"節 {len(paths)}、根拠のファイル {len(allf)}")
    if not stamp_path.is_file():
        rep.fail(str(stamp_path), "鮮度", "stamp.json が無い。地図を作り終えたら map-check.sh --stamp で記録する")
        return rep.show()
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except ValueError as e:
        rep.fail(str(stamp_path), "鮮度", f"stamp.json が読めない（{e}）")
        return rep.show()
    if stamp.get("hash") != rec_hash(stamp):
        rep.fail(str(stamp_path), "鮮度", "stamp.json が、道具の書いたあとに変わった（ハッシュ値が合わない）")
    if not same_commit(index_commit(info), str(stamp.get("commit", ""))):
        rep.fail(f"{index}:{info.get('commit', ('', 0))[1]}", "鮮度", f"入口の commit と stamp.json の commit（{stamp.get('commit')}）が違う")
    old = freshness(ctx, info, [s for s in SECTIONS if s[0] in paths] + [(INDEX_SECTION, INDEX_FILE)], stamp)
    summary = f"節 {len(paths)}、古い節 {len(old)}"
    if not args.fresh:
        summary += f"、入口 {n_lines} 行"
    return rep.show(summary)


# ---------------------------------------------------------------- 自己試験
def capture(fn, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            rc = fn(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 2
    return rc, buf.getvalue()


def write(p, text):
    p = pathlib.Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


FAKE_VALUE = "not-a-real-value-42"  # .env の値のサンプル。出力に出ないことを確かめる
# コマンドの行に書かれた秘密の値のサンプル（どれも作り物）。事実の表にも facts.jsonl にも出ないことを確かめる
FAKE_SECRETS = ["S3cretPassw0rdFAKE", "ghp_FAKEFAKEFAKE0000", "sk_" "live_FAKEFAKE1234", "Hunter2PassFAKE", "rootpassFAKE"]
SECRET_PROJECT = {
    "package.json": '{\n  "name": "s",\n  "scripts": {\n'
                    '    "dev": "DATABASE_URL=postgres://admin:S3cretPassw0rdFAKE@db.internal:5432/shop next dev",\n'
                    '    "hook": "curl -H \\"Authorization: Bearer ghp_FAKEFAKEFAKE0000\\" https://example.invalid"\n  }\n}\n',
    "Procfile": "web: SECRET_KEY=sk_" "live_FAKEFAKE1234 gunicorn app:app\n",
    "cron.d/nightly": "0 3 * * * curl -u admin:" "Hunter2PassFAKE https://example.invalid/run && mysql -uroot -prootpassFAKE x\n",
}
SAMPLE_PROJECT = {
    "package.json": '{\n  "name": "x",\n  "scripts": {\n    "dev": "next dev",\n    "test": "vitest run"\n  },\n'
                    '  "dependencies": {\n    "next": "14.2.3",\n    "react": "18.3.1"\n  },\n  "engines": {\n    "node": ">=20"\n  }\n}\n',
    ".env": f"DB_HOST=localhost\nDB_PASSWORD={FAKE_VALUE}\nAPP_NAME={FAKE_VALUE}\n",
    "app/views.py": 'import os\nimport requests\n\nROOT = os.environ.get("SHOP_DB", "x")\n\n\n@route("/admin/")\ndef dashboard(p):\n'
                    '    return requests.get("https://example.invalid")\n\n\n# @route("/admin/old")\ndef old(p):\n    return 1\n\n\n'
                    '@route("/pay/notify")\ndef notify(p):\n    return 1\n',
    "app/jobs.py": 'import sys\n\n\ndef run():\n    return 1\n\n\nif __name__ == "__main__":\n    run()\n',
    "app/migrations/001_init.sql": "CREATE TABLE a (id INTEGER);\n",
    "tests/test_views.py": "def test_x():\n    assert True\n",
    "README.md": "# x\n",
    "node_modules/x/index.js": 'app.get("/hidden-node", f)\n',
    "tmp/skills/x.py": '@route("/hidden-tmp")\ndef x(p):\n    return 1\n',
    "secret/keep.py": '@route("/hidden-exclude")\ndef y(p):\n    return 1\n',
    "app/.DS_Store": "x",
}


def make_project(base_dir):
    for rel, text in SAMPLE_PROJECT.items():
        write(base_dir / rel, text)
    conn = sqlite3.connect(str(base_dir / "data.sqlite3"))
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()


def selftest_facts(tmp, results):
    proj = tmp / "proj"
    make_project(proj)
    out = tmp / "out" / FACTS_FILE
    rc, text = capture(run_facts, ["--root", str(proj), "--out", str(out), "--exclude", "secret"])
    by_id, _ = load_jsonl(out)
    recs = list(by_id.values())

    def has(kind, item_part, value_part="", src=""):
        return any(r["kind"] == kind and item_part in r["item"] and value_part in r["value"] and src in evidence_text(r) for r in recs)

    checks = [
        ("正例が通る", rc == 0),
        ("ルートと処理の名前", has("画面と API", "/admin/", "dashboard", "app/views.py:7")),
        ("注釈の中のルート", has("画面と API", "/admin/old", "注釈の中")),
        ("外からの知らせ", has("外とのつながり", "/pay/notify")),
        ("外への HTTP", has("外とのつながり", "外への HTTP", "requests.get")),
        ("コマンドの入口", has("定時の処理", "python app/jobs.py", "__main__", "app/jobs.py:8")),
        ("DB の設定のキー", has("DB", "DB_PASSWORD", "値は読まない", ".env:2")),
        ("コードが読む DB の環境変数", has("DB", "SHOP_DB", "", "app/views.py:4")),
        ("DB でない設定のキー", has("設定の口", "APP_NAME")),
        ("sqlite のファイル", has("DB", "data.sqlite3", "KB")),
        ("マイグレーション", has("DB", "app/migrations/", "1 本")),
        ("試験のファイル", has("試験", "試験のファイル", "1 本")),
        ("フレームワークと版", has("フレームワーク", "next", "14.2.3", "package.json:8")),
        ("node の版", has("版", "node", ">=20")),
        ("npm のコマンド", has("コマンド", "npm run dev", "next dev", "package.json:4")),
        ("git の外", has("履歴", "commit", "無い")),
        ("値を出さない", FAKE_VALUE not in text and FAKE_VALUE not in out.read_text(encoding="utf-8")),
        ("node_modules と tmp を読まない", "hidden-node" not in text and "hidden-tmp" not in text),
        ("--exclude を読まない", "hidden-exclude" not in text and has("読んだ範囲", "読まない所", "secret")),
        ("OS が置くファイルは数えない", has("読んだ範囲", "走査したファイル", "8 本")),
        ("番号とハッシュ値", all(re.fullmatch(r"F-\d{3}", r["id"]) and r["hash"] == rec_hash(r) for r in recs) and "F-001" in by_id),
        ("作者は数だけ", count_authors(["a@x", "A@x ", "dependabot[bot]@users.noreply.github.com", "b@y"]) == 2
         and team_style(2, 2) == "チーム" and team_style(1, 3) == "個人" and team_style(0, 0).startswith("不明")),
    ]
    n1 = len(by_id)
    capture(run_facts, ["--root", str(proj), "--out", str(out)])
    by2, _ = load_jsonl(out)
    checks.append(("2 回目は番号を続ける", len(by2) > n1 and f"F-{n1 + 1:03d}" in by2 and by2["F-001"] == by_id["F-001"]))
    rc_bad, _ = capture(run_facts, ["--root", str(proj), "--out", str(proj / "facts.jsonl")])
    checks.append(("プロジェクトの中（tmp/ の外）には書かない", rc_bad == 1 and not (proj / "facts.jsonl").exists()))
    sec = tmp / "secret-proj"
    for rel, body in SECRET_PROJECT.items():
        write(sec / rel, body)
    sec_out = tmp / "secret-out" / FACTS_FILE
    rc_s, text_s = capture(run_facts, ["--root", str(sec), "--out", str(sec_out)])
    both = text_s + sec_out.read_text(encoding="utf-8")
    leaked = [s for s in FAKE_SECRETS if s in both]
    checks.append(("コマンドの行の秘密の値を伏せる（package.json、Procfile、cron）", rc_s == 0 and not leaked and HIDDEN in both
                   and "next dev" in both and "gunicorn app:app" in both))
    if leaked:
        print(f"FAIL selftest: 伏せていない値 {leaked}")
    for name, ok in checks:
        results.append((f"facts {name}", ok))
    return proj, out


MAP_FILES = {
    "index.md": """# プロジェクトの地図: サンプル

> **3 行でわかる要約**
> 1. 自己試験のサンプルの地図です。
> 2. 根拠は app/a.py の行と事実の番号です。
> 3. 依頼が触る節だけを開きます。

| 項目 | 内容 |
|---|---|
| commit | 無い（git の作業ツリーではない） |
| 作った日 | 2026-11-26 |
| DB の読み取りの許可 | 無い（読める DB が無い） |

## 節の案内

| 節 | ファイル | 中身 |
|---|---|---|
| 構成と動かし方 | [stack.md](stack.md) | 言語 |
| 開発の形 | [team.md](team.md) | 形 |
| 入口 | [entrypoints.md](entrypoints.md) | ルート |
| データ | [data.md](data.md) | 辞書 |
| 語彙 | [vocabulary.md](vocabulary.md) | 語 |
| 罠 | [traps.md](traps.md) | 罠 |
| 追記の候補 | [inbox.md](inbox.md) | 候補 |

## 先に知っておく罠

| 罠 | 案内 |
|---|---|
| 古いルートが注釈に残る | [traps.md](traps.md)、app/idx.py:1 |
""",
    "stack.md": "# 構成と動かし方: サンプル\n\n| 項目 | 内容 | 根拠 |\n|---|---|---|\n| 言語 | python | {F_LANG} |\n| 入口 | ルートの定義 | app/a.py:2 |\n",
    "team.md": "# 開発の形: サンプル\n\n| 項目 | 内容 | 根拠 |\n|---|---|---|\n| 形 | 不明 | {F_STYLE} |\n",
    "entrypoints.md": "# 入口: サンプル\n\n| ルート | 処理 | 根拠 |\n|---|---|---|\n| /a | a | app/a.py の 2 行 |\n",
    "vocabulary.md": "# 語彙: サンプル\n\n| 依頼者の語 | 名前 | 根拠 |\n|---|---|---|\n| 注文 | orders | 聞き取り（2026-11-26、依頼者） |\n",
    "traps.md": "# 罠: サンプル\n\n| 罠 | 根拠 |\n|---|---|\n| 古いルートが注釈に残る | app/a.py:5 |\n",
    "inbox.md": "# 追記の候補: サンプル\n\n| 日付 | 節 | 気づいたこと | 根拠 | 状態 |\n|---|---|---|---|---|\n"
                "| 2026-11-27 | 入口 | /b が増えた | app/a.py:8 | 未処理 |\n",
    "data.md": """# データの辞書: サンプル

> **3 行でわかる要約**
> 1. 読める DB が無いサンプルの辞書です。
> 2. データの主張は、全部コードからの推定です。
> 3. 自己試験の正例に使います。

| 項目 | 内容 |
|---|---|
| commit | 0a1b2c3（架空） |
| スキーマのハッシュ値 | 無い（読める DB が無い） |
| 集計の時刻 | 2026-11-26 10:00 |
| 環境の名前 | 無い（読める DB が無い） |

## 1. データの辞書

| テーブルと列 | コードの上の意味 | 実データ | 値の一覧 | 食い違い | 裏づけ |
|---|---|---|---|---|---|
| orders.status | 注文の状態（app/a.py:2） | 読める DB が無い | 件数だけ | なし | コードからの推定 |

## 2. 書き込む処理の表

| テーブル | 書き込む処理 | 書く列と条件 | 生きている証拠 | 状態 |
|---|---|---|---|---|
| orders | app/a.py:3 | status | 未確認 | 候補 |

## 3. 食い違いの一覧

| 番号 | 食い違い | コード側の根拠 | データ側の根拠 | いまの状態 | これからの振る舞い | あるべき姿 | 確かめた日 |
|---|---|---|---|---|---|---|---|
| T-01 | なし | app/a.py:2 | なし | なし | なし | 未決 | 2026-11-26 |

## 4. 語彙と基準の数字

| 依頼者の語 | 条件の文 | 基準の値 | 数えた値 | 一致 | 確かめた日 |
|---|---|---|---|---|---|
| 注文 | status を問わない | 無い | 数えていない | 未確認（読める DB が無い） | 2026-11-26 |

## 5. 読んだ範囲

| 対象 | 全体の数 | 読んだ数 | 読んでいない理由 |
|---|---|---|---|
| コードのファイル | 1 | 1 | なし |

## 6. クエリの記録

読める DB が無いので、記録はありません。

## 7. 対象外のテーブル

| テーブル | 理由 |
|---|---|
| （なし） | 読める DB が無い |
""",
}


def make_map(proj, facts_path):
    by_id, _ = load_jsonl(facts_path)
    f_lang = next(k for k, r in by_id.items() if r["kind"] == "言語")
    f_style = next(k for k, r in by_id.items() if r["kind"] == "履歴" and r["item"] == "開発の形")
    write(proj / "app" / "a.py", "".join(f"line{i} = {i}\n" for i in range(1, 11)))
    write(proj / "app" / "idx.py", "IDX = 1\n")
    mdir = proj / "tmp" / "catchup"
    for rel, text in MAP_FILES.items():
        write(mdir / rel, text.replace("{F_LANG}", f_lang).replace("{F_STYLE}", f_style))
    shutil.copy(facts_path, mdir / FACTS_FILE)
    return mdir, f_lang


def tamper(path, rid):
    """記録の 1 件の値だけを変え、ハッシュ値は元のままにする（手で書き換えた記録の見本）。"""
    out = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec.get("id") == rid:
            rec["value"] = rec["value"] + "（書き換えた）"
        out.append(json.dumps(rec, ensure_ascii=False))
    pathlib.Path(path).write_text("\n".join(out) + "\n", encoding="utf-8")


def selftest_map(tmp, proj, facts_path, results):
    mdir, f_lang = make_map(proj, facts_path)
    rc, out = capture(run_check, [str(mdir)])
    results.append(("map stamp.json が無いと [鮮度]", rc == 1 and "[鮮度]" in out))
    rc, out = capture(run_check, ["--stamp", str(mdir)])
    results.append(("map --stamp が記録する", rc == 0 and (mdir / STAMP_FILE).is_file()))
    rc, out = capture(run_check, [str(mdir)])
    results.append(("map 正例が通る（既定の直下は tmp/ の親）", rc == 0 and "SECTION 入口 新しい" in out))
    if rc != 0:
        print(out)
    pristine = {p.name: p.read_text(encoding="utf-8") for p in mdir.iterdir() if p.is_file()}
    app_a = (proj / "app" / "a.py").read_text(encoding="utf-8")
    app_idx = (proj / "app" / "idx.py").read_text(encoding="utf-8")
    made = []  # 負例のために足したファイル。次の負例の前に消す

    def case(name, rule, edit, extra=(), expect_rc=1, also="", absent=""):
        for fname, text in pristine.items():
            (mdir / fname).write_text(text, encoding="utf-8")
        (proj / "app" / "a.py").write_text(app_a, encoding="utf-8")
        (proj / "app" / "idx.py").write_text(app_idx, encoding="utf-8")
        while made:
            made.pop().unlink()
        edit()
        rc2, out2 = capture(run_check, list(extra) + [str(mdir)])
        ok = (rc2 == expect_rc and (f"[{rule}]" in out2 if rule else True) and (also in out2)
              and not (absent and absent in out2))
        results.append((f"map {name}", ok))
        if not ok:
            print(out2)

    def sub(fname, old, new):
        return lambda: (mdir / fname).write_text(pristine[fname].replace(old, new, 1), encoding="utf-8")

    def add(rel, text, then=None):
        def go():
            write(proj / rel, text)
            made.append(proj / rel)
            if then:
                then()
        return go

    case("入口が 81 行で [入口の長さ]", "入口の長さ", lambda: (mdir / INDEX_FILE).write_text(pristine[INDEX_FILE] + "補足です。\n" * 60, encoding="utf-8"))
    case("罠への案内が無いと [節の案内]", "節の案内", sub(INDEX_FILE, "| 罠 | [traps.md](traps.md) | 罠 |\n", ""))
    case("根拠の無い行で [根拠]", "根拠", sub("traps.md", "app/a.py:5", "コードを読んだ"))
    case("行が無いと [根拠の実在]", "根拠の実在", sub("entrypoints.md", "app/a.py の 2 行", "app/a.py の 99 行"))
    case("事実の番号が無いと [根拠の実在]", "根拠の実在", sub("team.md", "| 不明 | F-", "| 不明 | F-9"))
    case("事実の記録を書き換えると [ハッシュ値]", "ハッシュ値", lambda: tamper(mdir / FACTS_FILE, f_lang))
    case("節の表題が違うと [節の表題]", "節の表題", sub("traps.md", "# 罠: サンプル", "# わな: サンプル"))
    case("テンプレートの穴で [テンプレートの穴]", "テンプレートの穴", sub("stack.md", "| python |", "| <言語> |"))
    case("追記の候補の状態で [追記の候補]", "追記の候補", sub("inbox.md", "| 未処理 |", "| あとで |"))
    case("入口の commit が違うと [鮮度]", "鮮度", sub(INDEX_FILE, "無い（git の作業ツリーではない）", "0a1b2c3d"))
    case("記録に無い根拠で [鮮度]", "鮮度", sub("traps.md", "app/a.py:5", "app/jobs.py:4"))
    case("根拠のファイルが変わると [古い]", "古い",
         lambda: (proj / "app" / "a.py").write_text(app_a.replace("line9 = 9", "line9 = 99"), encoding="utf-8"),
         also="SECTION 罠 古い")
    case("--fresh は鮮度だけを見る", "古い",
         lambda: (proj / "app" / "a.py").write_text(app_a + "# 足した\n", encoding="utf-8"), extra=["--fresh"],
         also="SECTION 構成と動かし方 古い")
    case("--fresh は新しい地図で通る", "", lambda: None, extra=["--fresh"], expect_rc=0, also="SECTION 語彙 新しい")
    case("データの節が落ちると [データの節]", "データの節", sub("data.md", "| コードからの推定 |", "| 実測 |"))
    case("--stamp は落ちる地図を記録しない", "根拠", sub("traps.md", "app/a.py:5", "コードを読んだ"), extra=["--stamp"],
         also="記録しなかった")
    # 査読のあとに足した負例
    case("DB の読み取りの許可の欄が無いと [入口]", "入口", sub(INDEX_FILE, "| DB の読み取りの許可 | 無い（読める DB が無い） |\n", ""))
    case("入口の 1 枚の根拠が変わると [古い]", "古い", lambda: (proj / "app" / "idx.py").write_text("IDX = 2\n", encoding="utf-8"),
         also="SECTION 入口の 1 枚 古い")
    case("ルートのファイルが増えると [古い]（根拠に挙げていなくても）", "古い",
         add("app/refunds.py", '@route("/admin/refund")\ndef refund(p):\n    return 1\n'), also="SECTION 入口 古い")
    case("--fresh も増えたファイルで入口を古いとする", "古い", add("app/refunds.py", "X = 1\n"), extra=["--fresh"],
         also="SECTION 入口 古い")
    case("マイグレーションが増えるとデータの節を古いとする", "古い", add("app/migrations/002_refunds.sql", "CREATE TABLE r (id INTEGER);\n"),
         also="SECTION データ 古い")
    case("文書が増えても入口は新しいまま", "古い", add("docs/note.md", "# メモ\n"), also="SECTION 入口 新しい")
    old_stamp = json.loads((mdir / STAMP_FILE).read_text(encoding="utf-8"))

    def no_tree():
        s = {k: v for k, v in old_stamp.items() if k not in ("tree", "hash")}
        s["hash"] = rec_hash(s)
        (mdir / STAMP_FILE).write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")

    case("走査したファイルの一覧の無い stamp.json は [鮮度]", "鮮度", no_tree, also="走査したファイルの一覧が無い")
    (mdir / STAMP_FILE).write_text(json.dumps(old_stamp, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    case("直下の外を指す根拠は [根拠の実在]", "根拠の実在",
         add("../outside.txt", "x\ny\n", sub("traps.md", "app/a.py:5", "../outside.txt:2")), also="の外を指す")
    case("拡張子の無い Dockerfile:1 を根拠に読む（記録に無いので [鮮度]）", "鮮度",
         add("Dockerfile", "FROM python:3.12\n", sub("stack.md", "app/a.py:2", "Dockerfile:1")), absent="[根拠]")
    case("空白を含むパスは `パス`:行 で読む（記録に無いので [鮮度]）", "鮮度",
         add("app/空白 の.py", "x = 1\n", sub("stack.md", "app/a.py:2", "`app/空白 の.py`:1")), absent="[根拠")
    case("入口の基準の数字が「一致」なのに違うと [基準の数字]", "基準の数字",
         lambda: (mdir / INDEX_FILE).write_text(pristine[INDEX_FILE] + "\n## 基準の数字\n\n| 基準の数字 | 画面の集計の値 | 地図の定義で数えた値 | 一致 |\n"
                                                "|---|---|---|---|\n| 注文 | 6 件（依頼の文） | 7 件（" + f_lang + "） | 一致 |\n", encoding="utf-8"))
    # git の無いプロジェクト: 入口の commit は「無い」、データの節の commit は「git なし」と作った時刻と根拠のハッシュ値
    p = subprocess.run(["bash", str(DICT_CHECK), "--evidence-hash", str(mdir / "data.md"), "--root", str(proj)],
                       capture_output=True, text=True, timeout=120)
    m = re.search(r"^VALUE (.+)$", p.stdout, re.M)
    nogit = m.group(1) if m else "git なし（値が出なかった）"
    results.append(("map データの節の --evidence-hash が値を出す", m is not None))
    case("git の無い地図は、データの節の commit が「git なし」の形なら通る", "", sub("data.md", "| commit | 0a1b2c3（架空） |", f"| commit | {nogit} |"),
         expect_rc=0, also="SECTION データ 新しい")
    case("「git なし」の根拠のハッシュ値が合わないと [データの節]", "データの節",
         sub("data.md", "| commit | 0a1b2c3（架空） |", "| commit | " + re.sub(r"ハッシュ値 [0-9a-f]+", "ハッシュ値 " + "0" * 16, nogit) + " |"),
         also="ハッシュ値が合わない")
    case("後片付けのあとは正例に戻る", "", lambda: None, expect_rc=0, also="SECTION 入口の 1 枚 新しい")
    results.append(("map --stamp で stamp を書き換えない", json.loads((mdir / STAMP_FILE).read_text(encoding="utf-8"))
                    .get("hash") == rec_hash(json.loads((mdir / STAMP_FILE).read_text(encoding="utf-8")))))
    for fname, text in pristine.items():
        (mdir / fname).write_text(text, encoding="utf-8")
    (proj / "app" / "a.py").write_text(app_a, encoding="utf-8")
    other = tmp / "elsewhere"
    shutil.copytree(mdir, other)
    rc, out = capture(run_check, [str(other)])
    results.append(("map tmp/catchup の外では --root を求める", rc == 1 and "[使い方]" in out))
    rc, out = capture(run_check, ["--root", str(proj), str(other)])
    results.append(("map --root を渡すと通る", rc == 0))


def selftest(kind):
    results = []
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        proj, facts_path = selftest_facts(tmp, results)
        if kind == "check":
            selftest_map(tmp, proj, facts_path, results)
    bad = [n for n, ok in results if not ok]
    for n in bad:
        print(f"FAIL selftest: {n}")
    tool = NAMES[kind]
    print(f"RESULT: {'PASS' if not bad else 'FAIL'} {tool} --selftest ({len(results)} 例、FAIL {len(bad)})")
    return 1 if bad else 0


def main(argv):
    if not argv or argv[0] not in ("facts", "check"):
        print("使い方: catchup_tools.py facts|check [引数...] | <種類> --selftest")
        return 2
    kind, rest = argv[0], argv[1:]
    if rest == ["--selftest"]:
        return selftest(kind)
    return run_facts(rest) if kind == "facts" else run_check(rest)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
