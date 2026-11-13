#!/usr/bin/env bash
# skills/ja-professor/scripts/explain-check.sh <ファイル> [--profile explain|short|report] [--reader <reader-profile.md>]
#   教授の解説の型の検査。見る範囲は「解説」を含む ## 見出しの節。無ければファイル全体。
#   explain（既定）: ①答えの位置（「答え」の節が範囲の最初の 8 行以内。最初の 2 文に、はい・いいえ・数値・名前があり、前置きが無い）
#                   ②問いの言い直し（答えの前に「ですね」「の件」「(1)」などの行。番号つきの問いと答えの数が合う）
#                   ③用語の初出（explain-jargon.txt の語が、括弧の説明か用語の表か読み手の記録のどれかで説明されている）
#                   ④例がある ⑤英単語の裸出し（english-allow.txt に無く、括弧の説明も用語の表も無い 3 文字以上の英単語）
#                   ⑦専門語の密度（1 段落に初出の専門語が 3 つ以上で FAIL、全体で 9 語以上は WARN）
#                   ⑧確認の問い（最後の節に「？」か「か。」の文が 1 つ。2 つ以上は WARN） ⑨雛形の <…> の残り
#                   WARN: 仕組みの節に理由の語が無い、比喩が 3 回以上、誤った前提の否定が無い、読み手が次にすることが無い、本文 40 行超
#   short: 文が 3 つ以内、表と図が無い。①②④⑦⑧は見ない。  report: ⑧の代わりに「次にすること」を必須にし、②④は見ない。
#   一文の長さと文末は tools/check-ja.sh、文の中の運びは skills/ja-fluent/scripts/fluency-check.sh が見る。
# 使い方: explain-check.sh <ファイル> [--profile …] [--reader …]   /   explain-check.sh --selftest
# 出力: FAIL/WARN <ファイル>:<行> [<決まり>] <内容>、RESULT: PASS|FAIL explain-check。FAIL が 1 件でもあれば終了コード 1。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

run() {  # run <ファイル> <profile> <reader-profile か空>
  python3 -I - "$HERE" "$1" "$2" "$3" <<'PY'
import pathlib
import re
import sys

here, name, profile, reader = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
try:
    text = pathlib.Path(name).read_text(encoding="utf-8")
except (OSError, UnicodeDecodeError) as e:
    print(f"FAIL {name} [読めない] {e}")
    print(f"RESULT: FAIL explain-check {name}")
    sys.exit(1)

fails, warns = [], []
F = lambda no, rule, detail: fails.append((no, rule, detail))
W = lambda no, rule, detail: warns.append((no, rule, detail))

# ---- 一覧
jargon = []
for line in (here / "explain-jargon.txt").read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.startswith("#"):
        continue
    forms = line.split("\t")[0].split("|")
    jargon.append((forms[0], forms))
allow = {l.strip().lower() for l in (here / "english-allow.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
known = set()
if reader:
    try:
        sec = None
        for l in pathlib.Path(reader).read_text(encoding="utf-8").splitlines():
            if l.startswith("## "):
                sec = l
            elif sec and "知っている語" in sec and l.startswith("|") and not re.match(r"^\|\s*(語|-{3,})", l):
                known.add(l.strip("|").split("|")[0].strip())
    except OSError:
        W(0, "読み手の記録", f"{reader} が読めない")

# ---- 行の分類（注釈・コード・check:off の区間を外す）
Line = lambda no, raw, kind, txt: (no, raw, kind, txt)
rows = []
in_code = in_comment = skipping = False
for i, raw in enumerate(text.split("\n"), 1):
    s = raw.strip()
    if in_comment:
        if "-->" in s:
            in_comment = False
        continue
    if in_code:
        if s.startswith("```"):
            in_code = False
        continue
    ms = re.sub(r"`[^`\n]*`", "", s)  # コードの中に書かれた印は印と見ない
    if re.search(r"<!--\s*(check|ja-lint):off\s*-->", ms):
        skipping = True
        continue
    if re.search(r"<!--\s*(check|ja-lint):on\s*-->", ms):
        skipping = False
        continue
    if skipping or re.search(r"<!--\s*(ja-ok|ja-lint:ignore)\s*-->", ms):
        continue
    if s.startswith("<!--"):
        if "-->" not in s[4:]:
            in_comment = True
        continue
    if s.startswith("```"):
        in_code = True
        rows.append(Line(i, raw, "fence", s))
        continue
    if not s:
        rows.append(Line(i, raw, "blank", ""))
    elif s.startswith("#"):
        rows.append(Line(i, raw, "heading", re.sub(r"^#+\s*", "", s)))
    elif s.startswith("|"):
        rows.append(Line(i, raw, "table", s))
    else:
        t = re.sub(r"^(>\s?)+", "", s)
        t = re.sub(r"^([-*+]|\d+[.)])\s+", "", t)
        rows.append(Line(i, raw, "prose", t))

# ---- 範囲: 「解説」を含む ## の節。無ければ全体
start = next((k for k, r in enumerate(rows) if r[2] == "heading" and r[1].lstrip().startswith("## ") and "解説" in r[3]), None)
if start is None:
    scope = rows
    scope_start_no = rows[0][0] if rows else 1
else:
    end = next((k for k in range(start + 1, len(rows)) if rows[k][2] == "heading" and rows[k][1].lstrip().startswith("## ")), len(rows))
    scope = rows[start + 1:end]
    scope_start_no = rows[start][0]

def clean(t):
    t = re.sub(r"`[^`\n]*`", " X ", t)
    t = re.sub(r"https?://\S+", " X ", t)
    return t

prose = [(no, clean(t)) for no, raw, kind, t in scope if kind == "prose"]
tables_in_scope = [r for r in scope if r[2] == "table"]
fences_in_scope = [r for r in scope if r[2] == "fence" and "mermaid" in r[3]]

# 用語の表（見出しに「用語」を含む節の表。ファイル全体から）
glossary_terms = set()
sec = ""
for no, raw, kind, t in rows:
    if kind == "heading":
        sec = t
    elif kind == "table" and "用語" in sec:
        cells = [c.strip() for c in t.strip("|").split("|")]
        if cells and cells[0] and not re.fullmatch(r":?-{3,}:?", cells[0]) and cells[0] not in ("用語", "語"):
            glossary_terms.add(cells[0])
            if len(cells) >= 3 and cells[2] and not re.fullmatch(r":?-{3,}:?", cells[2]):
                for w in re.split(r"[\s/、,]+", cells[2]):
                    if w:
                        glossary_terms.add(w)

def glossed_at(t, m):
    after = t[m.end():m.end() + 40]
    before = t[:m.start()]
    inside = before.count("（") > before.count("）")
    return bool(re.match(r"\s*[（(]|とは", after)) or inside

all_text_lines = [(no, clean(t)) for no, raw, kind, t in rows if kind in ("prose", "table")]

def term_regex(forms):
    alts = []
    for f in forms:
        if re.fullmatch(r"[A-Za-z0-9+/.\- ]+", f):
            alts.append(rf"(?<![A-Za-z0-9+/]){re.escape(f)}(?![A-Za-z0-9+/])")
        else:
            alts.append(re.escape(f))
    return re.compile("|".join(alts))

# ---- 雛形の穴
for no, t in prose:
    if re.search(r"<[^>]*>", t) and not re.search(r"<br\s*/?>", t):
        F(no, "雛形の穴", "<…> が残っている")

# ---- ① 答えの位置、② 問いの言い直し
PREFACE = re.compile(r"について説明します|以下に|ご説明し|まず、|最初に、|説明させて")
ans_idx = next((k for k, r in enumerate(scope) if r[2] in ("heading", "prose") and re.match(r"^(\*\*)?答え", r[3])), None)
if profile in ("explain", "report"):
    if ans_idx is None:
        F(scope_start_no, "答えの位置", "「### 答え」の節が無い。問いの言い直しの直後に置く")
    else:
        before = [r for r in scope[:ans_idx] if r[2] in ("prose", "table", "heading") and r[2] != "heading" or (r[2] == "heading")]
        nonblank_before = [r for r in scope[:ans_idx] if r[2] != "blank"]
        if len(nonblank_before) > 8:
            F(scope[ans_idx][0], "答えの位置", f"答えが範囲の {len(nonblank_before) + 1} 行目から始まる。8 行以内に置く")
        ans_prose = []
        for r in scope[ans_idx + 1:]:
            if r[2] == "heading":
                break
            if r[2] == "prose":
                ans_prose.append(clean(r[3]))
        first2 = "".join(re.findall(r"[^。！？]*[。！？]", "".join(ans_prose))[:2]) or "".join(ans_prose)
        if not re.search(r"[0-9０-９]|はい|いいえ|できます|できません|ではありません|原因は|理由は|要ります|要りません", first2) or PREFACE.search(first2):
            F(scope[ans_idx][0], "答えの位置", "答えの最初の 2 文に、はい・いいえ・数値・名前のどれかを入れ、前置きを置かない")
        if profile == "explain":
            pre_prose = [clean(r[3]) for r in scope[:ans_idx] if r[2] == "prose"]
            restate = [t for t in pre_prose if re.search(r"ですね|の件|ご質問は|お尋ね|問いは|\(1\)|（1）|①", t) and not PREFACE.search(t)]
            if not restate:
                F(scope_start_no, "問いの言い直し", "答えの前に、問いを言い直す行（「ご質問は 2 点ですね。(1) …」）が無い")
            else:
                nq = max(len(re.findall(r"\(\d\)|（\d）", t)) for t in restate)
                na = len(set(re.findall(r"\(\d\)|（\d）", " ".join(ans_prose))))
                if nq >= 2 and na < nq:
                    F(scope[ans_idx][0], "問いの言い直し", f"問いの番号 {nq} 個に対し、答えの番号が {na} 個。同じ番号で答える")

# ---- ③ 用語の初出、⑦ 密度
first_in_scope = {}
for name0, forms in jargon:
    if name0 in known or any(f in known for f in forms):
        continue
    rx = term_regex(forms)
    if any(rx.fullmatch(g) or any(rx.fullmatch(f) for f in [g]) for g in glossary_terms) or any(f in glossary_terms for f in forms):
        continue
    gloss_no = None
    for no, t in all_text_lines:
        for m in rx.finditer(t):
            if glossed_at(t, m):
                gloss_no = no
                break
        if gloss_no:
            break
    first = next(((no, t) for no, t in prose if rx.search(t)), None)
    if first is None:
        continue
    first_in_scope[name0] = first[0]
    if gloss_no is None or gloss_no > first[0]:
        F(first[0], "用語の初出", f"「{name0}」に括弧の説明が無い（用語の表に載せるか、初出で（…）を付ける）")

if profile == "explain":
    paragraph = []
    para_counts = []
    for no, raw, kind, t in scope:
        if kind == "prose":
            paragraph.append(no)
        elif paragraph:
            para_counts.append(paragraph)
            paragraph = []
    if paragraph:
        para_counts.append(paragraph)
    for nos in para_counts:
        n = sum(1 for term, no in first_in_scope.items() if no in nos)
        if n >= 3:
            F(nos[0], "専門語の密度", f"1 段落に初出の専門語が {n} つ。1 段落に 1 つにする")
    if len(first_in_scope) >= 9 and not glossary_terms:
        W(scope_start_no, "専門語の密度", f"初出の専門語が {len(first_in_scope)} 語。用語の表を置く")

# ---- ④ 例、⑤ 英単語
if profile == "explain":
    if not any(re.search(r"例えば|たとえば|例えるなら|例[:：（]|例）", t) for _, t in prose) and not any(r[2] == "heading" and "例" in r[3] for r in scope):
        F(scope_start_no, "例", "例が無い。業務の場面と数字で 1 つ書く（架空なら「架空」と添える）")
for no, t in prose:
    for m in re.finditer(r"(?<![A-Za-z0-9/\-+.])[A-Za-z][A-Za-z+\-/]{2,}(?![A-Za-z0-9/\-+])", t):
        w = m.group(0)
        if w.lower() in allow or w in glossary_terms or w.rstrip("s") in glossary_terms:
            continue
        tail = t[m.end():m.end() + 30]
        if "（" in tail.split("。")[0] or t[:m.start()].count("（") > t[:m.start()].count("）"):
            continue
        F(no, "英単語の裸出し", f"「{w}」。日本語にするか、初出で括弧の説明を付けるか、用語の表に載せる")

# ---- ⑧ 確認の問い、次にすること、WARN
last_heading = max((k for k, r in enumerate(scope) if r[2] == "heading"), default=-1)
tail_prose = [clean(r[3]) for r in scope[last_heading + 1:] if r[2] == "prose"] if last_heading >= 0 else [t for _, t in prose[-8:]]
questions = sum(len(re.findall(r"[^。！？]*(か。|？)", t)) for t in tail_prose)
if profile == "explain":
    if questions == 0:
        F(scope[-1][0] if scope else scope_start_no, "確認の問い", "最後の節に、確認の問い（「一番分かりにくかった所はどこでしょうか」）が無い")
    elif questions >= 2:
        W(scope[-1][0], "確認の問い", f"問いが {questions} つ。1 つにする")
next_step = any(re.search(r"進めて|ください|お願いします|次に|お知らせ|教えて", t) for t in prose[-6:] and [t for _, t in prose[-6:]])
if profile == "report" and not next_step:
    F(scope[-1][0] if scope else scope_start_no, "次にすること", "読み手が次にすることを末尾に 1 文書く")
elif profile == "explain" and not next_step:
    W(scope[-1][0] if scope else scope_start_no, "次にすること", "読み手が次にすることが末尾に無い")
if profile == "explain":
    mech = None
    for k, r in enumerate(scope):
        if r[2] == "heading" and "仕組み" in r[3]:
            mech = k
    if mech is not None:
        body = []
        for r in scope[mech + 1:]:
            if r[2] == "heading":
                break
            if r[2] == "prose":
                body.append(r[3])
        if not re.search(r"なぜ|ので|ため|から|原因", "".join(body)):
            W(scope[mech][0], "仕組み", "仕組みの節に理由の語（なぜ・ので・ため・から・原因）が無い")
    metaphors = sum(len(re.findall(r"例えるなら|のようなもの|に似て|たとえると", t)) for _, t in prose)
    if metaphors >= 3:
        W(scope_start_no, "比喩", f"比喩の語が {metaphors} 回。比喩は 1 つの考えにだけ使う")
    if not any(re.search(r"ではありません|ではない|わけではありません|ません。", t) for _, t in prose):
        W(scope_start_no, "誤解の否定", "読み手が持っていそうな誤った前提を否定する 1 行が無い")
    n_lines = len(prose)
    if n_lines > 60:
        W(scope_start_no, "長さ", f"本文が {n_lines} 行。40 行までにし、超えるなら講義（ファイル）に分ける")
    elif n_lines > 40:
        W(scope_start_no, "長さ", f"本文が {n_lines} 行。40 行までを目安にする")

# ---- short
if profile == "short":
    n_sent = sum(len(re.findall(r"[。！？]", t)) for _, t in prose)
    if n_sent > 3:
        F(scope_start_no, "短答", f"文が {n_sent} つ。短答は 3 文以内")
    if tables_in_scope or fences_in_scope:
        F(scope_start_no, "短答", "短答に表か図がある。文だけにする")

for no, rule, detail in fails:
    print(f"FAIL {name}:{no} [{rule}] {detail}")
for no, rule, detail in warns:
    print(f"WARN {name}:{no} [{rule}] {detail}")
verdict = "PASS" if not fails else "FAIL"
print(f"RESULT: {verdict} explain-check {name} --profile {profile} (FAIL {len(fails)}、WARN {len(warns)}、本文 {len(prose)} 行)")
sys.exit(0 if not fails else 1)
PY
}

selftest() {
  local rc=0 ex="$HERE/../examples" fx="$HERE/../evals/fixtures"
  run "$ex/example-n-plus-one.md" explain "" | grep -q '^RESULT: PASS' || { echo "FAIL selftest: 完成例 N+1 が落ちた"; rc=1; }
  out="$(run "$fx/bad-ai-answer.txt" explain "")"
  n="$(printf '%s\n' "$out" | grep -c '^FAIL')"
  [ "$n" -ge 4 ] || { echo "FAIL selftest: 理解できない回答の FAIL が $n 件（4 件以上を期待）"; rc=1; }
  run "$HERE/../templates/explanation.md" explain "" | grep -q '^RESULT: FAIL' || { echo "FAIL selftest: 穴埋めのままの雛形が通った"; rc=1; }
  run "$ex/example-short-answer.md" short "" | grep -q '^RESULT: PASS' || { echo "FAIL selftest: 短答の完成例が落ちた"; rc=1; }
  run "$ex/example-n-plus-one.md" short "" | grep -q '\[短答\]' || { echo "FAIL selftest: 解説を短答として通した"; rc=1; }
  if [ "$rc" -eq 0 ]; then echo "RESULT: PASS explain-check --selftest (5 例)"; else echo "RESULT: FAIL explain-check --selftest"; fi
  return $rc
}

case "${1:-}" in
  --selftest) selftest ;;
  "") echo "使い方: explain-check.sh <ファイル> [--profile explain|short|report] [--reader <reader-profile.md>] | --selftest"; exit 2 ;;
  *)
    file="$1"; shift
    profile="explain"; reader=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --profile) profile="${2:-explain}"; shift 2 ;;
        --reader) reader="${2:-}"; shift 2 ;;
        *) echo "使い方: explain-check.sh <ファイル> [--profile …] [--reader …]"; exit 2 ;;
      esac
    done
    run "$file" "$profile" "$reader"
    ;;
esac
