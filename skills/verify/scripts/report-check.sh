#!/usr/bin/env bash
# skills/verify/scripts/report-check.sh — 完了報告の検査。決まりの本文は references/report-format.md（攻撃の結果は 3 節）。
#   表題・3 行の要約・受け入れ条件の表（確認コマンドと結果）・「直したこと」「未確認」「検証の記録」の節、推測の語と根拠の無い「確認済み」を見る。
#   テンプレートの <…> は文書の全体で落とす（コードと HTML の注釈の中は見ない）。
#   「配るコードの変更」の欄は、要約の直下の項目の表の本文の行に 1 つだけ置く。「あり」なら、最初の節が「攻撃の結果」で、
#   スクリプト（attack-run.sh）の RESULT の行が文書に 1 本だけで PASS。手口の表・脆弱性の表・確かめたことの表の値が、RESULT の数と合う。
#   「なし」の報告に、攻撃の結果の節か RESULT の行が残っていれば落とす。注釈の中の行は数えない。
#   --base <基点> を付けると、git の差分から配るコードの有無を決めて欄と照らし、攻撃の記録の指紋と対象の版も今のリポジトリと照らす。
# 使い方: report-check.sh <報告.md> [--base <基点>]
#         report-check.sh --attack-only <報告.md> [--base <基点>]   門（gate-check）が呼ぶ。欄と攻撃の結果だけを見て、FAIL と WARN をタブ区切りで返す
#         report-check.sh --deploy-code <基点> [<ディレクトリ>]       差分のうち、配るコードのファイルを出す
#         report-check.sh --target-version [<ディレクトリ>]           対象の版（commit と、配るコードの未 commit の差分の sha256）を出す
#         report-check.sh --selftest
# 出力: FAIL|WARN <ファイル>:<行> [<決まり>] <内容> と、最後に RESULT: PASS|FAIL report-check。1 件でも FAIL なら終了コード 1。WARN は数えない。
# git は読むだけ（rev-parse、diff、ls-files）。selftest は git を呼ばず、差分を試験の値で差し替える。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
here="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
if [ "$#" -eq 0 ]; then
  echo "使い方: report-check.sh <報告.md> [--base <基点>] | --attack-only <報告.md> [--base <基点>] | --deploy-code <基点> [<ディレクトリ>] | --target-version [<ディレクトリ>] | --selftest"
  exit 2
fi
exec python3 -I - "$here" "$@" <<'PY'
import contextlib
import hashlib
import io
import os
import pathlib
import re
import signal
import subprocess
import sys
import tempfile

HERE = pathlib.Path(sys.argv[1])
SKILL = HERE.parent
USAGE = ("使い方: report-check.sh <報告.md> [--base <基点>] | --attack-only <報告.md> [--base <基点>] | "
         "--deploy-code <基点> [<ディレクトリ>] | --target-version [<ディレクトリ>] | --selftest")

# ---- 決まりの値（references/report-format.md の 3 節）
GUESS = ("動くはず", "通るはず", "と思われ", "おそらく", "はずです", "はずである")
FIELD = "配るコードの変更"
FIELD_LIKE = re.compile(r"^配る\s*コード")
SEP = re.compile(r":?-{3,}:?")
HOLE = re.compile(r"<[^<>\s][^<>\n]{0,79}>")
BR = re.compile(r"<br\s*/?>", re.I)
AUTOLINK = re.compile(r"^<(https?://|mailto:)")
CODE_SPAN = re.compile(r"`[^`\n]*`")
ATTACK = re.compile(r"^[\s>`]*RESULT:\s*(\S+)\s+attack-run(?![\w-])(.*)$")
NUMS = [
    ("入口", re.compile(r"入口\s*(\d+)\s*/\s*(\d+)")),
    ("リクエスト", re.compile(r"(?:リクエスト|要求)\s*(\d+)\s*本")),
    ("脆弱性", re.compile(r"(?<!前からある)脆弱性\s*(\d+)")),
    ("再攻撃", re.compile(r"再攻撃\s*(\d+)")),
    ("未実施", re.compile(r"未実施\s*(\d+)")),
    ("前からある脆弱性", re.compile(r"前からある脆弱性\s*(\d+)")),
]
NEEDED = ["入口", "リクエスト", "脆弱性", "未実施", "前からある脆弱性"]
CHECKED = ["対象の版", "届いた本数", "宛先", "接続先", "許可", "検出力", "確かめていないこと", "攻撃の記録"]
RESULT_CELL = re.compile(r"^(守れた|脆弱性\s*(\d+)\s*件|対象外\s*[。（(]\s*[^）)\s])")
NOTHING = {"", "無し", "なし", "-", "ー", "特になし", "ありません", "無い", "ない"}
IPV4 = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])")
HOSTNAME = re.compile(r"(?<![A-Za-z0-9.-])(?=[A-Za-z0-9.-]*[A-Za-z])[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![A-Za-z0-9.-])")
OUTSIDE_ZERO = re.compile(r"外[^。|]*?(?<!\d)0\s*本")
VERSION = re.compile(r"commit [0-9a-f]{7,40}、配るコードの差分(?:なし| \d+ ファイル（sha256 の先頭 12 桁 [0-9a-f]{12}）)")
FINGER = re.compile(r"sha256[^`|]*?([0-9a-f]{12,64})(?![0-9a-f])")

# 配るコードから外すファイル（3.1 節）。どれにも当たらないファイルは配るコードで、迷うファイルも配るコードに倒す
DOC_EXT = (".md", ".mdc", ".markdown", ".txt", ".rst", ".adoc")
DOC_NAMES = {"LICENSE", "NOTICE", "AUTHORS", "COPYING", "CHANGELOG", "CODEOWNERS"}
TEST_DIR = re.compile(r"(^|/)(tests?|__tests__|specs?|e2e|evals)/")
TEST_NAME = re.compile(r"^(test_.*\.py|.*_test\.\w+|.*\.(test|spec)\.\w+|.*Tests?\.(php|java|kt|swift|cs))$")
# My-Lab の一式。My-Lab のリポジトリ（skills/verify/scripts/report-check.sh と tools/verify-all.sh がある）でだけ外す
KIT_DIRS = ("skills/", "tools/", "hooks/", "router/", ".company/", ".claude/", ".cursor/", ".github/", "node_modules/")
KIT_FILES = {"deploy.sh", "install.sh", "package.json", "package-lock.json", "node_modules", ".gitignore", ".gitleaks.toml", ".semgrepignore"}


def excluded(path, home):
    """配るコードから外すなら理由の語、配るコードなら None を返す。"""
    p = path.strip("/")
    name = p.rsplit("/", 1)[-1]
    if p.split("/", 1)[0] in ("tmp", "docs"):
        return "置き場"
    if name.lower().endswith(DOC_EXT) or ("." not in name and name.upper() in DOC_NAMES):
        return "文書"
    if TEST_DIR.search(p) or TEST_NAME.match(name):
        return "テスト"
    if home and (p.startswith(KIT_DIRS) or p in KIT_FILES):
        return "一式"
    return None


# ---- git（読むだけ）
class RepoError(Exception):
    pass


def git_run(start, args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    try:
        p = subprocess.run(["git", "-C", str(start)] + list(args), capture_output=True, timeout=60, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        raise RepoError(str(e))
    if p.returncode != 0:
        msg = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RepoError(msg[-1] if msg else f"git {args[0]} の終了コード {p.returncode}")
    return p.stdout


class Repo:
    """差分の数え方（3.1 節）: 基点から作業ツリーまでの差分（commit 済み・index・未 commit）と、追跡外の新しいファイル。"""

    def __init__(self, start, run=None):
        self.run = run or git_run
        out = self.run(str(start), ["rev-parse", "--show-toplevel"]).decode("utf-8", "surrogateescape").strip()
        if not out:
            raise RepoError("git のリポジトリの中でない")
        self.top = pathlib.Path(out)

    @classmethod
    def for_file(cls, name):
        """報告を置いたディレクトリのリポジトリ。報告はリポジトリの中（tmp/flow/ など）に置く。"""
        return cls(pathlib.Path(name).resolve().parent)

    def files(self, *args):
        out = self.run(str(self.top), list(args))
        return [x.decode("utf-8", "surrogateescape") for x in out.split(b"\0") if x]

    def changed(self, base):
        if not base or base.startswith("-"):
            raise RepoError(f"基点「{base}」は使えない")
        got = set(self.files("diff", "--name-only", "--no-renames", "-z", base, "--"))
        return sorted(got | set(self.files("ls-files", "--others", "--exclude-standard", "-z")))

    def changed_head(self):
        return self.changed("HEAD")

    def head(self):
        return self.run(str(self.top), ["rev-parse", "--verify", "HEAD"]).decode("ascii", "replace").strip()

    def home(self):
        return (self.top / "skills/verify/scripts/report-check.sh").is_file() and (self.top / "tools/verify-all.sh").is_file()

    def read(self, rel):
        p = self.top / rel
        return p.read_bytes() if p.is_file() else None


def target_version(repo):
    """対象の版。commit と、配るコードの未 commit の差分の sha256（パスの順に、パスと長さと中身を足す）。"""
    head = repo.head()
    home = repo.home()
    files = [f for f in repo.changed_head() if excluded(f, home) is None]
    if not files:
        return f"commit {head[:12]}、配るコードの差分なし"
    h = hashlib.sha256()
    for f in files:
        data = repo.read(f)
        h.update(f.encode("utf-8", "surrogateescape") + b"\0")
        h.update(b"-\0" if data is None else str(len(data)).encode() + b"\0" + data)
    return f"commit {head[:12]}、配るコードの差分 {len(files)} ファイル（sha256 の先頭 12 桁 {h.hexdigest()[:12]}）"


# ---- 文書
class Doc:
    """行ごとの (本文, 種類)。種類は text・fence・code・hidden（HTML の注釈の中）。コードブロックの中の注釈は注釈と見ない。"""

    def __init__(self, name, text):
        self.name = name
        self.v = []
        in_code = in_comment = False
        for raw in text.split("\n"):
            if in_comment:
                if "-->" in raw:
                    in_comment = False
                    rest = raw.split("-->", 1)[1]
                    self.v.append((rest, "text") if rest.strip() else (None, "hidden"))
                else:
                    self.v.append((None, "hidden"))
                continue
            if raw.strip().startswith("```"):
                in_code = not in_code
                self.v.append((raw, "fence"))
                continue
            if in_code:
                self.v.append((raw, "code"))
                continue
            t = re.sub(r"<!--.*?-->", "", raw)
            if "<!--" in t:
                t = t.split("<!--", 1)[0]
                in_comment = True
            self.v.append((t, "text") if t.strip() or not raw.strip() else (None, "hidden"))
        self.heads = [i for i, (t, k) in enumerate(self.v) if k == "text" and t.startswith("## ")]

    def section(self, key):
        """(何番目の節か, 見出しの行, 次の見出しの行)。無ければ None。"""
        at = next((n for n, i in enumerate(self.heads) if key in self.v[i][0]), None)
        if at is None:
            return None
        end = self.heads[at + 1] if at + 1 < len(self.heads) else len(self.v)
        return at, self.heads[at], end

    def tables(self, lo=0, hi=None):
        hi = len(self.v) if hi is None else hi
        out, cur = [], None
        for i in range(lo, hi):
            t, k = self.v[i]
            s = t.strip() if k == "text" and t else ""
            if not s.startswith("|"):
                cur = None
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cur is None:
                cur = {"header": cells, "no": i + 1, "rows": []}
                out.append(cur)
            elif all(SEP.fullmatch(c) for c in cells):
                continue
            else:
                cur["rows"].append((i + 1, cells))
        return out


def col(header, key):
    return next((i for i, h in enumerate(header) if key in h), None)


def has(table, key):
    return col(table["header"], key) is not None


def show(files, n=3):
    return "、".join(files[:n]) + (f" ほか {len(files) - n} 本" if len(files) > n else "")


def parse_nums(s):
    out = {}
    for key, rx in NUMS:
        m = rx.search(s)
        if m:
            out[key] = (int(m.group(1)), int(m.group(2))) if key == "入口" else int(m.group(1))
    return out


# ---- 検査
def check_basic(d, fail):
    title = next((t for t, k in d.v if k == "text" and t.startswith("# ")), "")
    if not title.startswith("# 完了報告:"):
        fail(1, "表題", "「# 完了報告: <件名>」で始める")
    quote = [t for t, k in d.v[:25] if k == "text" and t.startswith(">")]
    content = [l for l in quote if re.search(r"[。！？]\s*$", l.strip("> *"))]
    if len(content) != 3:
        fail(1, "要約", f"3 行の要約（引用ブロック）が {len(content)} 行")
    sec = d.section("受け入れ条件")
    if sec is None:
        fail(0, "受け入れ条件", "「## 受け入れ条件」の節が無い")
    else:
        tabs = d.tables(sec[1] + 1, sec[2])
        header = tabs[0]["header"] if tabs else None
        if not header or col(header, "確認") is None or col(header, "結果") is None:
            fail(sec[1] + 1, "受け入れ条件", "表の列に「確認コマンド」と「結果」が要る")
        elif not tabs[0]["rows"]:
            fail(sec[1] + 1, "受け入れ条件", "条件の行が無い")
        else:
            ci, ri = col(header, "確認"), col(header, "結果")
            for no, cells in tabs[0]["rows"]:
                if len(cells) <= max(ci, ri) or not cells[ci] or not cells[ri]:
                    fail(no, "受け入れ条件", "確認コマンドか結果が空")
                elif "<" in cells[ci] or "<" in cells[ri]:
                    fail(no, "受け入れ条件", "テンプレートの <…> が残っている")
    for key in ("直したこと", "未確認", "検証の記録"):
        if d.section(key) is None:
            fail(0, key, f"「## {key}」の節が無い")
    sec = d.section("未確認")
    if sec is not None:
        tabs = d.tables(sec[1] + 1, sec[2])
        ri = col(tabs[0]["header"], "理由") if tabs else None
        if ri is not None:
            for no, cells in tabs[0]["rows"]:
                if len(cells) <= ri or not cells[ri] or "<" in cells[ri]:
                    fail(no, "未確認", "理由が空か、テンプレートの <…> が残っている")
    sec = d.section("検証の記録")
    if sec is not None and not re.search(r"docs/verify/|\.verify/", "\n".join(t for t, _ in d.v[sec[1]:sec[2]] if t)):
        fail(sec[1] + 1, "検証の記録", "docs/verify/<日付>.md か tmp/.verify/ への参照が無い")
    for i, (t, k) in enumerate(d.v, 1):
        if k != "text":
            continue
        for w in GUESS:
            if w in t:
                fail(i, "推測の語", f"「{w}」。実行して結果を書くか、未確認に書く")
        if re.search(r"(確認済み|問題なし)", t) and "`" not in t and not t.startswith("|"):
            fail(i, "根拠", "「確認済み」「問題なし」には、確認コマンドと結果を添える")


def check_holes(d, fail, lo, hi, seen):
    for i in range(lo, hi):
        t, k = d.v[i]
        if k != "text" or i + 1 in seen:
            continue
        holes = [m.group(0) for m in HOLE.finditer(BR.sub("", CODE_SPAN.sub("", t))) if not AUTOLINK.match(m.group(0))]
        if holes:
            fail(i + 1, "テンプレートの穴", f"テンプレートの {holes[0][:24]} が残っている")
            seen.add(i + 1)


def check_attack(d, fail, warn, base, repo):
    """欄と攻撃の結果（3 節）。見た範囲 [(始め, 終わり)] を返す。"""
    spans = []
    first = d.heads[0] if d.heads else len(d.v)
    cands = []
    for t in d.tables():
        for no, cells, is_head in [(t["no"], t["header"], True)] + [(no, c, False) for no, c in t["rows"]]:
            name = cells[0].strip("`* ") if cells else ""
            if FIELD_LIKE.match(name):
                cands.append((no, name, cells, is_head))
    good = [c for c in cands if not c[3] and c[0] - 1 < first]
    field = good[0] if good else None
    for c in cands:
        if c is not field:
            fail(c[0], "配るコードの変更", "欄は、要約の直下にある項目の表の本文の行に 1 つだけ置く。表の見出しの行・節の中・2 つ目の欄は数えない")
    kind = None
    if field is not None:
        no, name, cells, _ = field
        spans.append((no - 1, no))
        value = cells[1].strip("`* ") if len(cells) > 1 else ""
        if name != FIELD:
            fail(no, "配るコードの変更", f"欄の名を「{FIELD}」にする（今は「{name[:20]}」）")
        kind = "あり" if value.startswith("あり") else "なし" if value.startswith("なし") else None
        if kind is None:
            fail(no, "配るコードの変更", f"欄の値を「あり」か「なし」で始める（今は「{value[:20]}」）")
    deploy, rp = None, None
    if base is not None:
        try:
            rp = repo if repo is not None else Repo.for_file(d.name)
            home = rp.home()
            deploy = [f for f in rp.changed(base) if excluded(f, home) is None]
        except RepoError as e:
            rp = None
            warn(0, "配るコードの変更", f"git の差分を読めない（{e}）。基点とリポジトリを確かめて回し直す")
    if field is None:
        if deploy:
            fail(0, "配るコードの変更", f"差分に配るコード（{show(deploy)}）があるのに、項目の表に「{FIELD}」の欄が無い。「あり」と書き、攻撃の結果の節を最初に置く")
        else:
            note = ("差分に配るコードは無い" if deploy is not None else "git の差分を読めなかった" if base is not None
                    else "git の差分とは照らしていない。--base <基点> で照らす")
            warn(0, "配るコードの変更", f"項目の表に「{FIELD}」の欄が無い。古い型として通す（{note}）")
        return spans
    if kind == "なし":
        if deploy:
            fail(field[0], "配るコードの変更", f"欄は「なし」だが、差分に配るコード（{show(deploy)}）がある。「あり」にして、攻撃の結果を載せる")
        elif base is None:
            warn(field[0], "配るコードの変更", "「なし」を git の差分と照らしていない。--base <基点> を付けて回す")
        left = [i for i in d.heads if "攻撃の結果" in d.v[i][0]]
        left += [i for i, (t, k) in enumerate(d.v) if k in ("text", "code") and ATTACK.match(t)]
        if left:
            fail(min(left) + 1, "攻撃の結果", "「なし」の報告に、攻撃の結果の節か RESULT の行が残っている。節を消すか、欄を「あり」にして攻撃を回す")
        return spans
    if kind == "あり":
        span = check_section(d, fail, warn, base, rp)
        if span:
            spans.append(span)
    return spans


def check_section(d, fail, warn, base, rp):
    sec = d.section("攻撃の結果")
    if sec is None:
        fail(0, "攻撃の結果", "配るコードの変更が「あり」なのに「## 攻撃の結果」の節が無い。スクリプト（attack-run.sh）が書いた節を、要約と項目の表のすぐ下に置く")
        return None
    at, start, end = sec
    if at != 0:
        fail(start + 1, "攻撃の結果", "攻撃の結果の節が先頭に無い。要約と項目の表のすぐ下（最初の節）に置く")
    found = [i for i, (t, k) in enumerate(d.v) if k in ("text", "code") and ATTACK.match(t)]
    inside = [i for i in found if start < i < end]
    if len(found) > 1:
        fail(found[1] + 1, "攻撃の結果", f"「RESULT: … attack-run」の行が {len(found)} 本ある。スクリプトの出力の 1 本だけを載せる")
    nums, result_line = {}, None
    if not inside:
        undone = any(k == "text" and "攻撃は未実施" in t for t, k in d.v[start:end])
        fail(start + 1, "攻撃の結果",
             "「攻撃は未実施」と書いてある。検査は緩めず FAIL のまま取りまとめ役に戻し、未実施のまま進めるかを依頼者に伺う" if undone
             else "スクリプトが書いた「RESULT: … attack-run」の行が節に無い。スクリプトの出力を手で直さずに貼る")
    else:
        i = inside[0]
        m = ATTACK.match(d.v[i][0])
        result_line = d.v[i][0].strip().strip("`").strip()
        if m.group(1) != "PASS":
            fail(i + 1, "攻撃の結果", f"攻撃の結果が {m.group(1)}。新しい脆弱性を直し、全部の攻撃を送り直して PASS にしてから出す")
        nums = parse_nums(m.group(2))
        lack = [k for k in NEEDED if k not in nums]
        if lack:
            fail(i + 1, "攻撃の結果", f"RESULT の行に、{'・'.join(lack)}の数が無い")
        if "入口" in nums and nums["入口"][0] != nums["入口"][1]:
            fail(i + 1, "攻撃の結果", f"入口の漏れがある（{nums['入口'][0]}/{nums['入口'][1]}）。全部の入口に送ってから出す")
        if nums.get("未実施"):
            fail(i + 1, "攻撃の結果", f"未実施が {nums['未実施']} ある。当てはまる手口を全部送ってから出す")
        if nums.get("脆弱性") and nums.get("再攻撃") != 0:
            fail(i + 1, "攻撃の結果", "新しい脆弱性が、直したあとの再攻撃で 0 件になっていない（「→ 再攻撃 0」が要る）")
    tabs = d.tables(start + 1, end)
    check_tables(d, fail, tabs, nums, start, end)
    rows = check_checked(fail, tabs, nums, start)
    if rows is None:
        return start, end
    if base is None:
        warn(start + 1, "攻撃の結果", "攻撃の記録と対象の版を、今のリポジトリと照らしていない。--base <基点> を付けて回す")
    elif rp is not None:
        check_record(rp, fail, warn, rows, result_line)
    return start, end


def check_tables(d, fail, tabs, nums, start, end):
    """手口ごとの表と、見つけた脆弱性の表。数は RESULT の行と合わせる。"""
    tech = next((t for t in tabs if has(t, "手口") and has(t, "結果")), None)
    if tech is None or not tech["rows"]:
        fail(start + 1, "攻撃の結果", "手口ごとの表（列は「手口」「試した入口」「送った本数」「結果」「記録」）が無い")
    else:
        h = tech["header"]
        ri, si = col(h, "結果"), col(h, "送った本数")
        if si is None:
            fail(tech["no"], "攻撃の結果", "手口の表に「送った本数」の列が無い")
        total, vulns, summable = 0, 0, si is not None
        for no, cells in tech["rows"]:
            if len(cells) < len(h):
                fail(no, "攻撃の結果", "手口の表の列が足りない")
                summable = False
                continue
            res = cells[ri]
            m = RESULT_CELL.match(res)
            if not m:
                fail(no, "攻撃の結果", f"結果「{res[:20]}」。「守れた」「脆弱性 n 件。直して 0 件」「対象外。理由」のどれかで書く（未実施と空は残さない）")
            elif m.group(2):
                vulns += int(m.group(2))
                if "直して 0 件" not in res and "前からある" not in res:
                    fail(no, "攻撃の結果", "直していない脆弱性の行がある。直して全部の攻撃を送り直すか、前からある脆弱性なら「前からある」と書いて直す承認を伺う")
            if si is not None:
                if re.fullmatch(r"\d+", cells[si]):
                    total += int(cells[si])
                else:
                    fail(no, "攻撃の結果", f"送った本数「{cells[si][:10]}」を数で書く")
                    summable = False
        if summable and "リクエスト" in nums and total != nums["リクエスト"]:
            fail(tech["no"], "攻撃の結果", f"手口の表の送った本数の合計 {total} 本が、RESULT の {nums['リクエスト']} 本と合わない")
        if "脆弱性" in nums and "前からある脆弱性" in nums and vulns != nums["脆弱性"] + nums["前からある脆弱性"]:
            fail(tech["no"], "攻撃の結果", f"手口の表の脆弱性 {vulns} 件が、RESULT の脆弱性と前からある脆弱性の和 {nums['脆弱性'] + nums['前からある脆弱性']} 件と合わない")
    want = nums["脆弱性"] + nums["前からある脆弱性"] if "脆弱性" in nums and "前からある脆弱性" in nums else None
    vt = next((t for t in tabs if has(t, "何ができてしまったか")), None)
    if want:
        if vt is None or len(vt["rows"]) != want:
            fail(vt["no"] if vt else start + 1, "攻撃の結果", f"見つけた脆弱性の表（番号・何ができてしまったか・重さ・直したあと）が {want} 行でない")
        else:
            wi = col(vt["header"], "重さ")
            for no, cells in vt["rows"]:
                if wi is None or len(cells) <= wi or not cells[wi]:
                    fail(no, "攻撃の結果", "脆弱性の重さが空。skills/security/scripts/cvss4.sh で点数と重さを出す")
    elif want == 0 and vt is not None and vt["rows"]:
        fail(vt["no"], "攻撃の結果", "RESULT の脆弱性は 0 件なのに、脆弱性の表に行がある")
    pre = nums.get("前からある脆弱性", 0)
    if pre and not any(k == "text" and not t.lstrip().startswith("|") and "前からある脆弱性" in t and "承認" in t for t, k in d.v[start:end]):
        fail(start + 1, "攻撃の結果", f"前からある脆弱性が {pre} 件ある。件数と重さを脆弱性の表に出し、直す承認を伺う 1 行（「前からある脆弱性 {pre} 件を直す承認をお願いします。」）を置く")


def check_checked(fail, tabs, nums, start):
    """確かめたことの表の 8 行。行の名 → (行番号, 値) を返す。表が無ければ None。"""
    ct = next((t for t in tabs if t["header"] and "確かめたこと" in t["header"][0]), None)
    if ct is None:
        fail(start + 1, "攻撃の結果", f"確かめたことの表（{'・'.join(CHECKED)}の行）が無い")
        return None
    rows = {}
    for no, cells in ct["rows"]:
        rows.setdefault(cells[0].strip("`* "), (no, cells[1].strip() if len(cells) > 1 else ""))
    lack = [k for k in CHECKED if k not in rows]
    if lack:
        fail(ct["no"], "攻撃の結果", f"確かめたことの表に、{'・'.join(lack)}の行が無い")
    for key in CHECKED:
        if key in rows and (not rows[key][1] or HOLE.search(CODE_SPAN.sub("", rows[key][1]))):
            fail(rows[key][0], "攻撃の結果", f"「{key}」の値が空か、テンプレートの <…> が残っている")
    if "届いた本数" in rows and "リクエスト" in nums:
        no, val = rows["届いた本数"]
        got = [int(x) for x in re.findall(r"\d+", val)]
        if len(got) < 2 or any(x != nums["リクエスト"] for x in got):
            fail(no, "攻撃の結果", f"届いた本数（{val[:30]}）が、送った {nums['リクエスト']} 本と合わない。アプリのログの行数と送った本数を、スクリプトの出力のまま載せる")
    if "検出力" in rows:
        no, val = rows["検出力"]
        got = [int(x) for x in re.findall(r"\d+", val)]
        if len(got) < 2 or len(set(got)) != 1 or got[0] == 0:
            fail(no, "攻撃の結果", f"検出力（{val[:30]}）が全部でない。仕込んだ脆弱性を全部見つけるまで、表に手口を足して回し直す")
    if "確かめていないこと" in rows:
        no, val = rows["確かめていないこと"]
        if val.rstrip("。").strip() in NOTHING:
            fail(no, "攻撃の結果", "「確かめていないこと」が空。表に無い手口と、試していない悪用のシナリオを書く")
    if "宛先" in rows:
        no, val = rows["宛先"]
        out = [x for x in IPV4.findall(val) if not x.startswith("127.")]
        out += [x for x in HOSTNAME.findall(val) if x.lower() != "localhost"]
        if out:
            fail(no, "攻撃の結果", f"宛先に手元でないもの（{'、'.join(out[:3])}）がある。送る先は 127.0.0.1・localhost・::1 だけ")
        if not OUTSIDE_ZERO.search(val):
            fail(no, "攻撃の結果", "宛先の行に、外へのリクエストが 0 本であることが無い")
    if "許可" in rows:
        no, val = rows["許可"]
        if "常設の RoE" not in val or not re.search(r"A-\d+", val):
            fail(no, "攻撃の結果", "許可の行に、常設の RoE と承認記録の番号（A-番号）が要る")
    if "対象の版" in rows and not VERSION.search(rows["対象の版"][1]):
        fail(rows["対象の版"][0], "攻撃の結果", "対象の版を「commit <hash>、配るコードの差分 …」の形で書く（report-check.sh --target-version の出力）")
    if "攻撃の記録" in rows:
        no, val = rows["攻撃の記録"]
        if not re.search(r"`[^`\s]+`", val) or not FINGER.search(val):
            fail(no, "攻撃の結果", "攻撃の記録の行に、記録のパス（` で囲む）と sha256 の先頭 12 桁が要る")
    return rows


def check_record(rp, fail, warn, rows, result_line):
    """--base のとき。対象の版を今の版と照らし、攻撃の記録の指紋と中身を照らす。"""
    m = VERSION.search(rows["対象の版"][1]) if "対象の版" in rows else None
    version = m.group(0) if m else None
    try:
        now = target_version(rp)
    except RepoError as e:
        warn(0, "攻撃の結果", f"今の版を読めない（{e}）")
        now = None
    if version and now and version != now:
        fail(rows["対象の版"][0], "攻撃の結果", f"対象の版が今の版（{now}）と違う。攻撃のあとで配るコードが変わったので、攻撃を回し直す")
    if "攻撃の記録" not in rows:
        return
    no, val = rows["攻撃の記録"]
    path, finger = re.search(r"`([^`\s]+)`", val), FINGER.search(val)
    if not path or not finger:
        return
    p = (rp.top / path.group(1)).resolve()
    try:
        p.relative_to(rp.top.resolve())
    except ValueError:
        fail(no, "攻撃の結果", f"攻撃の記録 {path.group(1)} がリポジトリの外を指す。記録は tmp/.verify/ の下に置く")
        return
    if not p.is_file():
        fail(no, "攻撃の結果", f"攻撃の記録 {path.group(1)} が無い。スクリプトの記録の無い結果は通さない")
        return
    data = p.read_bytes()
    if not hashlib.sha256(data).hexdigest().startswith(finger.group(1)):
        fail(no, "攻撃の結果", "攻撃の記録の sha256 が、報告の指紋と合わない（記録か報告が書き換わった）")
    body = data.decode("utf-8", "replace")
    if result_line and result_line not in body:
        fail(no, "攻撃の結果", "攻撃の記録に、報告の RESULT の行が無い")
    if version and version not in body:
        fail(no, "攻撃の結果", "攻撃の記録に、報告の対象の版が無い")


def check_report(name, base=None, repo=None, attack_only=False):
    """(FAIL の一覧, WARN の一覧) を返す。各要素は (行番号, 決まり, 内容)。"""
    fails, warns = [], []

    def fail(no, rule, detail):
        fails.append((no, rule, detail))

    def warn(no, rule, detail):
        warns.append((no, rule, detail))

    try:
        text = pathlib.Path(name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        fail(0, "読めない", f"{type(e).__name__}: {e}")
        return fails, warns
    d = Doc(name, text)
    if not attack_only:
        check_basic(d, fail)
    spans = check_attack(d, fail, warn, base, repo)
    seen = {no for no, _, _ in fails}
    for lo, hi in ([(0, len(d.v))] if not attack_only else spans):
        check_holes(d, fail, lo, hi, seen)
    return fails, warns


def emit(name, fails, warns, attack_only=False):
    if attack_only:
        for kind, items in (("FAIL", fails), ("WARN", warns)):
            for no, rule, detail in items:
                print(f"{kind}\t{no}\t{rule}\t{detail}")
        print(f"RESULT: {'PASS' if not fails else 'FAIL'} report-check --attack-only {name} ({len(fails)} 件)")
        return
    for kind, items in (("FAIL", fails), ("WARN", warns)):
        for no, rule, detail in items:
            print(f"{kind} {name}:{no} [{rule}] {detail}" if no else f"{kind} {name} [{rule}] {detail}")
    extra = f"、WARN {len(warns)} 件" if warns else ""
    print(f"RESULT: {'PASS' if not fails else 'FAIL'} report-check {name} ({len(fails)} 件{extra})")


def show_deploy(base, start):
    try:
        repo = Repo(start)
        files = repo.changed(base)
    except RepoError as e:
        print(f"FAIL [差分を読めない] {e}")
        return 2
    home = repo.home()
    deploy = [f for f in files if excluded(f, home) is None]
    if deploy:
        print(f"配るコードの変更: あり（{len(deploy)} ファイル）")
        for f in deploy:
            print(f"  {f}")
    else:
        print(f"配るコードの変更: なし（差分の {len(files)} ファイルは、どれも置き場・文書・テスト・一式）")
    return 0


# ---- 自己試験（git を呼ばない。差分は試験の値で差し替える）
GOOD = """# 完了報告: サンプル

> **3 行でわかる要約**
> 1. サンプルの作業を終えました。
> 2. 検証は全体 PASS で、未確認は 1 件です。
> 3. 記録を見て、次の段階の承認をお願いします。

## 1. 受け入れ条件

2 件とも確認コマンドがあります。

| # | 条件 | 確認コマンド | 結果 |
|---|---|---|---|
| 1 | 検査が通る | `bash tools/verify-all.sh --fast` | `RESULT: PASS verify-all --fast` |
| 2 | 図が描ける | `node tools/render-mermaid.mjs docs/x.md` | `RESULT: PASS render-mermaid (3 図、0 件)` |

## 2. 直したこと

直した所はありません。

## 3. 未確認

1 件です。

| 条件 | 理由 | 確かめ方 |
|---|---|---|
| Cursor で ask が効く | 実機が手元に無い | 依頼者が Cursor で `git status` と commit の依頼を試す |

## 4. 検証の記録

`docs/verify/2026-11-06.md`。2026-11-06 12:00 に `--full` を回した。
"""

RESULT_LINE = "RESULT: PASS attack-run（入口 3/3、手口 3、リクエスト 9 本、脆弱性 0、未実施 0、前からある脆弱性 0）"
VERSION_TEXT = "commit 3f2a91c0d4e1、配るコードの差分 2 ファイル（sha256 の先頭 12 桁 9c1e0b7a2f45）"
RECORD_CELL = "`tmp/.verify/attack-20261126-101500.json`（sha256 の先頭 12 桁 4b8e0f1a9c2d）"
FIELD_ROW = "| 配るコードの変更 | あり（API の 2 ファイル） |"
# 配るコードを変えた報告の正例（数値は架空）
ATTACK_REPORT = f"""# 完了報告: サンプル（配るコードの変更あり）

> **3 行でわかる要約**
> 1. サンプルの API に、店ごとの絞り込みを足しました。
> 2. 攻撃は入口 3 の全部に 3 の手口で 9 本を送り、脆弱性は 0 件でした。検証は全体 PASS です。
> 3. 記録を見て、commit の承認をお願いします。

| 項目 | 内容 |
|---|---|
{FIELD_ROW}

## 1. 攻撃の結果

スクリプトが書いた節です。数値は架空です。

```text
{RESULT_LINE}
```

| 手口 | 試した入口 | 送った本数 | 結果 | 記録 |
|---|---|---|---|---|
| 認証なしで入る | 3 | 3 | 守れた | A01 |
| 他人の物を読む・書く | 2 | 4 | 守れた | A02 |
| 権限を越える | 1 | 2 | 守れた | A03 |

脆弱性はありません。

| 確かめたこと | 値 | 出どころ |
|---|---|---|
| 対象の版 | {VERSION_TEXT} | 攻撃の記録の頭 |
| 届いた本数 | アプリのログに 9 行。送った 9 本と同じ | 攻撃用に立てたアプリのログ |
| 宛先 | 127.0.0.1 の 2 つのポートだけ。外へのリクエストは 0 本 | 攻撃の記録の宛先の列 |
| 接続先 | DB は攻撃用のテストデータ。メールはモック | 事前の確かめの出力 |
| 許可 | 常設の RoE。承認記録 A-000 で、範囲のハッシュ値が一致 | 常設の RoE の検査 |
| 検出力 | 仕込んだ脆弱性 3 件のうち、3 件を見つけた | サンプルでの試験 |
| 確かめていないこと | 表に無い手口は試していない | 攻撃の記録の末尾 |
| 攻撃の記録 | {RECORD_CELL} | attack-run |

## 2. 受け入れ条件

1 件です。

| # | 条件 | 確認コマンド | 結果 |
|---|---|---|---|
| 1 | 店で絞ると 2 件になる | `python3 -m unittest samples/api/test_orders_api.py` | `OK (12 tests)` |

## 3. 直したこと

直した所はありません。

## 4. 未確認

ありません。

## 5. 検証の記録

`docs/verify/2026-11-06.md`。2026-11-06 12:00 に `--full` を回した。
"""

VULN_TABLE = "| 番号 | 何ができてしまったか | 重さ | 直したあと |\n|---|---|---|---|\n| F-1 | {what} | 5.3（Medium） | {after} |"


def mut(src, old, new):
    if old not in src:
        raise ValueError(f"負例を作れない（「{old[:30]}」が無い）")
    return src.replace(old, new, 1)


def drop_section(src, head):
    a = src.index(head)
    return src[:a] + src[src.index("\n## ", a + 1) + 1:]


class FakeRepo(Repo):
    """試験用。基点からの差分と、HEAD からの差分を値で持つ。"""

    def __init__(self, top, since_base, since_head=None, home=False, head="0123456789abcdef0123456789abcdef01234567"):
        self.top = pathlib.Path(top)
        self._base, self._now = since_base, since_base if since_head is None else since_head
        self._home, self._head = home, head

    def changed(self, base):
        if base == "壊れた基点":
            raise RepoError("fatal: bad revision '壊れた基点'")
        return sorted(self._base)

    def changed_head(self):
        return sorted(self._now)

    def head(self):
        return self._head

    def home(self):
        return self._home


CLASS_CASES = [  # (パス, My-Lab か, 外す理由。配るコードなら None)
    ("src/app.py", False, None),
    ("docs/a.png", False, "置き場"),
    ("tmp/flow/x/completion-report.md", False, "置き場"),
    ("README.md", False, "文書"),
    ("LICENSE", False, "文書"),
    ("notice.py", False, None),
    ("tests/test_api.py", False, "テスト"),
    ("samples/api/test_orders_api.py", True, "テスト"),
    ("web/src/order.test.ts", False, "テスト"),
    ("app/Policies/OrderPolicyTest.php", False, "テスト"),
    ("skills/verify/scripts/report-check.sh", True, "一式"),
    ("skills/verify/scripts/report-check.sh", False, None),
    ("samples/api/server.py", True, None),
    ("package.json", True, "一式"),
    ("package.json", False, None),
    ("node_modules", True, "一式"),
]


def selftest():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    state = {"ok": True, "n": 0}

    def bad(msg):
        state["ok"] = False
        print(f"FAIL selftest: {msg}")

    def case(label, res, rule):
        """rule が None なら FAIL 0 件、文字列ならその決まりの FAIL があること。"""
        state["n"] += 1
        got = {r for _, r, _ in res[0]}
        if (rule is None and got) or (rule is not None and rule not in got):
            bad(f"{label}（期待 {rule or 'FAIL 0 件'}、検出 {sorted(got)}）")

    A = ATTACK_REPORT
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = pathlib.Path(tmpdir)

        def run(text, name="r.md", **kw):
            p = tmp / name
            p.write_text(text, encoding="utf-8")
            return check_report(str(p), **kw)

        try:
            no_sec = drop_section(A, "## 1. 攻撃の結果")
            none = mut(no_sec, FIELD_ROW, "| 配るコードの変更 | なし（文書だけ） |")
            body = A[A.index("## 1. 攻撃の結果\n") + len("## 1. 攻撃の結果\n"):A.index("## 2. 受け入れ条件")]
            hidden = mut(A, "## 1. 攻撃の結果\n" + body, "## 1. 攻撃の結果\n\n<!--\n" + body + "-->\n\n")
            fixed = mut(mut(mut(A, "脆弱性 0、未実施", "脆弱性 1 → 再攻撃 0、未実施"), "| 1 | 2 | 守れた | A03 |", "| 1 | 2 | 脆弱性 1 件。直して 0 件 | A03 |"),
                        "脆弱性はありません。", "見つけた脆弱性は 1 件です。\n\n" + VULN_TABLE.format(what="店員の役で、管理の設定を書き換えられた", after="同じ攻撃に 403 が返る"))
            pre_ok = mut(mut(mut(A, "前からある脆弱性 0", "前からある脆弱性 1"), "| 1 | 2 | 守れた | A03 |", "| 1 | 2 | 脆弱性 1 件。前からある | A03 |"),
                         "脆弱性はありません。", "前からある脆弱性 1 件を直す承認をお願いします。\n\n" + VULN_TABLE.format(what="店員の役で、管理の設定を読めた", after="前からある。直す承認を伺う"))
            format_cases = [
                ("正例（欄の無い古い型）", GOOD, None),
                ("テンプレートの穴（受け入れ条件）", mut(GOOD, "| `RESULT: PASS verify-all --fast` |", "| <結果> |"), "受け入れ条件"),
                ("テンプレートの穴（本文）", mut(GOOD, "直した所はありません。", "<直した件数を 1 文で>"), "テンプレートの穴"),
                ("URL の自動リンクは穴でない", mut(GOOD, "直した所はありません。", "直した所はありません。出典は <https://example.com/a> です。"), None),
                ("推測の語", mut(GOOD, "直した所はありません。", "直さなくても動くはずです。"), "推測の語"),
                ("未確認の節が無い", drop_section(GOOD, "## 3. 未確認"), "未確認"),
                ("攻撃の結果の正例", A, None),
                ("脆弱性を直した正例", fixed, None),
                ("前からある脆弱性の正例", pre_ok, None),
                ("「なし」の正例", none, None),
                ("攻撃の結果の節が無い", no_sec, "攻撃の結果"),
                ("RESULT の行が無い", mut(A, RESULT_LINE + "\n", ""), "攻撃の結果"),
                ("RESULT が FAIL", mut(A, "RESULT: PASS attack-run", "RESULT: FAIL attack-run"), "攻撃の結果"),
                ("攻撃の結果が先頭に無い", mut(A, "## 1. 攻撃の結果", "## 0. 前置き\n\n前置きです。\n\n## 1. 攻撃の結果"), "攻撃の結果"),
                ("手口の表が無い", mut(A, "| 手口 |", "| 項目 |"), "攻撃の結果"),
                ("確かめていないことの行が無い", mut(A, "| 確かめていないこと | 表に無い手口は試していない | 攻撃の記録の末尾 |\n", ""), "攻撃の結果"),
                ("欄の値が「あり」「なし」でない", mut(A, FIELD_ROW, "| 配るコードの変更 | 未定 |"), "配るコードの変更"),
                ("欄の名の誤り", mut(A, "| 配るコードの変更 |", "| 配るコード変更 |"), "配るコードの変更"),
                ("欄が表の見出しの行", mut(no_sec, "| 項目 | 内容 |\n|---|---|\n" + FIELD_ROW, "| 配るコードの変更 | あり |\n|---|---|\n| 対象 | API |"), "配るコードの変更"),
                ("欄が 2 つ", mut(A, FIELD_ROW, FIELD_ROW + "\n| 配るコードの変更 | なし |"), "配るコードの変更"),
                ("注釈の中の欄（見える欄は「あり」で節が無い）", mut(no_sec, "| 項目 | 内容 |", "<!--\n| 配るコードの変更 | なし |\n-->\n\n| 項目 | 内容 |"), "攻撃の結果"),
                ("注釈に隠した節の中身", hidden, "攻撃の結果"),
                ("RESULT の行が 2 本", mut(A, "```text\n", "```text\nRESULT: FAIL attack-run（脆弱性 1）\n"), "攻撃の結果"),
                ("結果が未実施", mut(A, "| 1 | 2 | 守れた | A03 |", "| 1 | 2 | 未実施 | A03 |"), "攻撃の結果"),
                ("結果が空", mut(A, "| 1 | 2 | 守れた | A03 |", "| 1 | 2 |  | A03 |"), "攻撃の結果"),
                ("直していない脆弱性", mut(fixed, "脆弱性 1 件。直して 0 件", "脆弱性 1 件。直していない"), "攻撃の結果"),
                ("再攻撃が 0 件でない", mut(fixed, "→ 再攻撃 0", "→ 再攻撃 1"), "攻撃の結果"),
                ("脆弱性の表の行が足りない", mut(fixed, VULN_TABLE.format(what="店員の役で、管理の設定を書き換えられた", after="同じ攻撃に 403 が返る"), ""), "攻撃の結果"),
                ("前からある脆弱性に承認の 1 行が無い", mut(pre_ok, "前からある脆弱性 1 件を直す承認をお願いします。\n\n", ""), "攻撃の結果"),
                ("未実施が残る", mut(A, "未実施 0", "未実施 2"), "攻撃の結果"),
                ("入口の漏れ", mut(A, "入口 3/3", "入口 2/3"), "攻撃の結果"),
                ("送った本数の合計が合わない", mut(A, "| 3 | 3 | 守れた | A01 |", "| 3 | 4 | 守れた | A01 |"), "攻撃の結果"),
                ("届いた本数が合わない", mut(A, "アプリのログに 9 行", "アプリのログに 2 行"), "攻撃の結果"),
                ("届いた本数の行が無い", mut(A, "| 届いた本数 | アプリのログに 9 行。送った 9 本と同じ | 攻撃用に立てたアプリのログ |\n", ""), "攻撃の結果"),
                ("検出力が全部でない", mut(A, "3 件のうち、3 件を見つけた", "3 件のうち、2 件を見つけた"), "攻撃の結果"),
                ("検出力の行が無い", mut(A, "| 検出力 | 仕込んだ脆弱性 3 件のうち、3 件を見つけた | サンプルでの試験 |\n", ""), "攻撃の結果"),
                ("確かめていないことが「無し」", mut(A, "| 確かめていないこと | 表に無い手口は試していない |", "| 確かめていないこと | 無し |"), "攻撃の結果"),
                ("手元でない宛先", mut(A, "127.0.0.1 の 2 つのポートだけ", "127.0.0.1 と 192.0.2.1 のポート"), "攻撃の結果"),
                ("名前の宛先", mut(A, "127.0.0.1 の 2 つのポートだけ", "api.staging.example.com のポート"), "攻撃の結果"),
                ("許可に承認記録が無い", mut(A, "承認記録 A-000 で、", ""), "攻撃の結果"),
                ("対象の版の形が違う", mut(A, VERSION_TEXT, "commit 3f2a91c（作業ツリーに変更なし）"), "攻撃の結果"),
                ("攻撃の記録の行が無い", mut(A, f"| 攻撃の記録 | {RECORD_CELL} | attack-run |\n", ""), "攻撃の結果"),
                ("攻撃の記録に指紋が無い", mut(A, "（sha256 の先頭 12 桁 4b8e0f1a9c2d）", ""), "攻撃の結果"),
                ("テンプレートの穴（攻撃の結果）", mut(A, "| 認証なしで入る | 3 | 3 | 守れた | A01 |", "| <手口> | 3 | 3 | 守れた | A01 |"), "テンプレートの穴"),
                ("攻撃は未実施", mut(A, "```text\n" + RESULT_LINE + "\n```\n", "攻撃は未実施。理由: アプリを手元で起こす手順が無い。\n"), "攻撃の結果"),
                ("「なし」に攻撃の結果の節が残る", mut(A, FIELD_ROW, "| 配るコードの変更 | なし（文書だけ） |"), "攻撃の結果"),
                ("「なし」に RESULT の行が残る", mut(none, "直した所はありません。", "直した所はありません。\n\n```text\n" + RESULT_LINE + "\n```"), "攻撃の結果"),
            ]
        except ValueError as e:
            bad(str(e))
            format_cases = []
        for label, text, rule in format_cases:
            case(label, run(text), rule)
        warns = [w for w in run(GOOD)[1] if w[1] == "配るコードの変更"]
        state["n"] += 1
        if len(warns) != 1:
            bad(f"欄の無い古い報告に、欄の WARN が {len(warns)} 行（期待 1 行）")
        # --base: 差分を FakeRepo で差し替える
        top = tmp / "repo"
        (top / "src").mkdir(parents=True)
        app = top / "src" / "app.py"
        app.write_text("print(1)\n", encoding="utf-8")
        base_cases = [
            ("差分に配るコード・欄が無い", GOOD, FakeRepo(top, ["src/app.py"]), "配るコードの変更"),
            ("差分は文書とテストだけ・欄が無い", GOOD, FakeRepo(top, ["docs/a.md", "tests/test_a.py", "README.md"]), None),
            ("差分に配るコード・「なし」", none, FakeRepo(top, ["src/app.py"]), "配るコードの変更"),
            ("My-Lab の一式だけ・「なし」", none, FakeRepo(top, ["skills/x/scripts/y.sh", "tools/lib/z.py"], home=True), None),
            ("ほかのプロジェクトの skills/・「なし」", none, FakeRepo(top, ["skills/x/y.py"]), "配るコードの変更"),
            ("My-Lab の samples/・「なし」", none, FakeRepo(top, ["samples/api/server.py"], home=True), "配るコードの変更"),
        ]
        for label, text, repo, rule in base_cases:
            case(label, run(text, base="main", repo=repo), rule)
        res = run(none, base="壊れた基点", repo=FakeRepo(top, []))
        case("差分を読めない（WARN にする）", res, None)
        if not any("差分を読めない" in w[2] for w in res[1]):
            bad("差分を読めないときに WARN が出ない")
        # 攻撃の記録と対象の版
        fk = FakeRepo(top, ["src/app.py"])
        ver = target_version(fk)
        rec = top / "tmp" / ".verify" / "attack-1.json"
        rec.parent.mkdir(parents=True)
        rec.write_text(f'{{"result": "{RESULT_LINE}", "target": "{ver}"}}\n', encoding="utf-8")
        fp = hashlib.sha256(rec.read_bytes()).hexdigest()[:12]
        cell = f"`tmp/.verify/attack-1.json`（sha256 の先頭 12 桁 {fp}）"
        good_rec = A.replace(VERSION_TEXT, ver).replace(RECORD_CELL, cell)
        rec2 = rec.with_name("attack-2.json")
        rec2.write_text(f'{{"target": "{ver}"}}\n', encoding="utf-8")
        cell2 = f"`tmp/.verify/attack-2.json`（sha256 の先頭 12 桁 {hashlib.sha256(rec2.read_bytes()).hexdigest()[:12]}）"
        record_cases = [
            ("記録と版が合う", good_rec, None),
            ("記録が無い", good_rec.replace("attack-1.json", "attack-0.json"), "攻撃の結果"),
            ("記録の指紋が違う", good_rec.replace(fp, "000000000000"), "攻撃の結果"),
            ("記録に RESULT の行が無い", good_rec.replace(cell, cell2), "攻撃の結果"),
            ("記録がリポジトリの外を指す", good_rec.replace("`tmp/.verify/attack-1.json`", "`../attack-1.json`"), "攻撃の結果"),
        ]
        for label, text, rule in record_cases:
            case(label, run(text, base="main", repo=fk), rule)
        app.write_text("print(2)\n", encoding="utf-8")
        case("攻撃のあとで配るコードが変わった", run(good_rec, base="main", repo=fk), "攻撃の結果")
        if VERSION.search(ver) is None:
            bad(f"target_version の出力「{ver}」が、対象の版の形に合わない")
        # git の出力の読み方（git は呼ばず、出力を差し替える）
        out = {
            ("rev-parse", "--show-toplevel"): b"/x/top\n",
            ("diff", "--name-only", "--no-renames", "-z", "main", "--"): b"src/app.py\0docs/a.md\0",
            ("ls-files", "--others", "--exclude-standard", "-z"): "web/画面.tsx\0".encode("utf-8"),
        }

        def fake_run(start, args):
            if tuple(args) in out:
                return out[tuple(args)]
            raise RepoError("fatal: bad revision")

        state["n"] += 3
        r = Repo("/x/top/sub", run=fake_run)
        if r.changed("main") != ["docs/a.md", "src/app.py", "web/画面.tsx"]:
            bad(f"git の出力の読み方: {r.changed('main')}")
        for b in ("-x", "nope"):
            try:
                r.changed(b)
                bad(f"基点「{b}」で RepoError にならない")
            except RepoError:
                pass
        for path, home, want in CLASS_CASES:
            state["n"] += 1
            if excluded(path, home) != want:
                bad(f"配るコードの見分け「{path}」（My-Lab={home}）→ {excluded(path, home)}（期待 {want}）")
        # 読めないファイル。RESULT の行を出して FAIL にする
        binf = tmp / "bin.md"
        binf.write_bytes(b"\xff\xfe# x\n")
        for label, target in (("UTF-8 でない", binf), ("ディレクトリ", tmp)):
            res = check_report(str(target))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                emit(str(target), *res)
            state["n"] += 1
            if "読めない" not in {r for _, r, _ in res[0]} or "RESULT: FAIL report-check" not in buf.getvalue():
                bad(f"{label}のファイルで、読めない FAIL と RESULT の行が出ない")
        # --attack-only: 欄と攻撃の結果だけを見て、タブ区切りで返す
        res = run(mut(no_sec, "直した所はありません。", "直さなくても動くはずです。"), attack_only=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            emit("r.md", *res, attack_only=True)
        lines = buf.getvalue().splitlines()
        state["n"] += 1
        if "推測の語" in {r for _, r, _ in res[0]} or not lines or not lines[0].startswith("FAIL\t") or not lines[-1].startswith("RESULT: FAIL"):
            bad(f"--attack-only の出力が違う: {lines[:2]}")
        # 完成例は通り、テンプレートは穴で落ちる
        ex = SKILL / "examples" / "completion-report-attack.md"
        tp = SKILL / "templates" / "completion-report.md"
        state["n"] += 2
        if not ex.is_file() or check_report(str(ex))[0]:
            bad(f"完成例 {ex.name} が落ちた: {check_report(str(ex))[0][:3] if ex.is_file() else '無い'}")
        if not tp.is_file() or "テンプレートの穴" not in {r for _, r, _ in check_report(str(tp))[0]}:
            bad("テンプレート（穴埋めのまま）が通った")
    print(f"RESULT: {'PASS' if state['ok'] else 'FAIL'} report-check --selftest ({state['n']} 例)")
    return state["ok"]


def main(argv):
    if not argv:
        print(USAGE)
        return 2
    if argv[0] == "--selftest":
        return 0 if selftest() else 1
    if argv[0] == "--deploy-code":
        if len(argv) < 2:
            print(USAGE)
            return 2
        return show_deploy(argv[1], argv[2] if len(argv) > 2 else ".")
    if argv[0] == "--target-version":
        try:
            print(target_version(Repo(argv[1] if len(argv) > 1 else ".")))
            return 0
        except RepoError as e:
            print(f"FAIL [版を読めない] {e}")
            return 2
    attack_only = argv[0] == "--attack-only"
    args = list(argv[1:] if attack_only else argv)
    base = None
    if "--base" in args:
        i = args.index("--base")
        if i + 1 >= len(args):
            print(USAGE)
            return 2
        base = args[i + 1]
        args = args[:i] + args[i + 2:]
    if len(args) != 1:
        print(USAGE)
        return 2
    fails, warns = check_report(args[0], base=base, attack_only=attack_only)
    emit(args[0], fails, warns, attack_only)
    return 0 if not fails else 1


sys.exit(main(sys.argv[2:]))
PY
