#!/usr/bin/env bash
# skills/ja-fluent/scripts/fluency-check.sh <ファイル>... — 文の運びの機械検査（references/flow-rules.md の 2 節）。
#   FAIL: 読点 4 つ以上、「の」3 連続、「することができる／ことが可能／ことになる／ことにより」、受身の文末 3 文連続、二重否定、
#         「〜を行う／〜を実施する」が 1 文書に 3 回以上、「が、」が 1 文に 2 回、翻訳調の型のうち FAIL 印のもの
#   WARN: 同じ格助詞が読点を挟まず 2 回、「こと」が 1 文に 2 回、受身が本文の 30% 超、主語「は」が 30 字目以降、「〜し、」3 回、
#         カタカナ語（katakana.txt）、カタカナが本文の 20% 超、翻訳調の型（WARN 印）、漢字 6 字以上の連続（allow-kanji.txt は除く）
#   見ないもの: 見出し、表、コード、frontmatter、注釈、<!-- check:off --> 〜 <!-- check:on --> の区間、<!-- ja-ok --> の行。
#   一文の長さ・文末の連続・調・禁則語は tools/check-ja.sh が見る。
# 使い方: fluency-check.sh <ファイル>... [--profile doc|answer]   /   fluency-check.sh --selftest
# 出力: FAIL/WARN <ファイル>:<行> [<決まり>] <内容>、info の 1 行、RESULT: PASS|FAIL fluency-check。FAIL が 1 件でもあれば終了コード 1。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

run() {  # run <ファイル>...
  python3 -I - "$HERE" "$@" <<'PY'
import pathlib
import re
import sys

here = pathlib.Path(sys.argv[1])
files = sys.argv[2:]


def load_pairs(name, ncol):
    rows = []
    p = here / name
    if not p.exists():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        cells = line.split("\t")
        while len(cells) < ncol:
            cells.append("")
        rows.append(cells[:ncol])
    return rows


KATAKANA = load_pairs("katakana.txt", 2)
ALLOW_KATA = {r[0] for r in load_pairs("allow-katakana.txt", 1)}
TRANS = [(re.compile(r[0]), r[1], r[2].strip() or "WARN") for r in load_pairs("translationese.txt", 3)]
ALLOW_KANJI = [r[0] for r in load_pairs("allow-kanji.txt", 1)]

CODE_SPAN = re.compile(r"`[^`\n]*`")
URL = re.compile(r"https?://\S+")
TAG = re.compile(r"<[^<>\n]{1,120}>")
PASSIVE_END = re.compile(r"(され|られ|われ)(る|た|て|ます|ました|ません|ています|ていました|ている|ていた)[。！？]?$")
DOUBLE_NEG = re.compile(r"ないわけでは(ない|ありません)|なくは(ない|ありません)|ないことは(ない|ありません)|ないとは言え(ない|ません)|なくも(ない|ありません)|ないでは(ない|ありません)|ないことも(ない|ありません)")
REDUNDANT_FAIL = re.compile(r"することができ|ことが可能|ことになる|ことにより|ことによって")
SURU_VERB = re.compile(r"を(行う|行い|行っ|実施)")
NOUNISH = "一-鿿々ァ-ヺーA-Za-z0-9"
NO_RUN = re.compile(rf"(?:[{NOUNISH}]+の){{3}}[{NOUNISH}]")
KANJI_RUN = re.compile(r"[一-鿿々]{6,}")
KATA_CHAR = re.compile(r"[ァ-ヺー]")


def prose_lines(text):
    """検査する行（行番号, 文字列）。表・見出し・コード・注釈・frontmatter・check:off の区間を外す。"""
    out = []
    lines = text.split("\n")
    fm_end = -1
    if lines and lines[0].strip() == "---":
        for j in range(1, min(len(lines), 80)):
            if lines[j].strip() == "---":
                fm_end = j
                break
    in_code = in_comment = skipping = False
    for i, raw in enumerate(lines):
        no = i + 1
        s = raw.strip()
        if i <= fm_end:
            continue
        if in_comment:
            if "-->" in s:
                in_comment = False
            continue
        if in_code:
            if s.startswith("```"):
                in_code = False
            continue
        ms = CODE_SPAN.sub("", s)  # コードの中に書かれた印は印と見ない
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
            continue
        if not s or s.startswith("#") or s.startswith("|") or re.match(r"^(-{3,}|\*{3,})$", s) or s.startswith("!["):
            continue
        if "禁則語" in s:  # 禁則語を名指しで列挙する行は、語そのものを書く必要があるので見ない
            continue
        s = re.sub(r"^(>\s?)+", "", s)
        s = re.sub(r"^([-*+]|\d+[.)])\s+", "", s)
        s = CODE_SPAN.sub("X", s)
        s = URL.sub("X", s)
        s = TAG.sub("X", s)
        s = re.sub(r"\*\*|__", "", s)
        if s.strip():
            out.append((no, s.strip()))
    return out


def sentences(text):
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in "。！？":
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def count_ten(sentence):
    """読点の数。括弧の中は数えない。名詞の並列（ひらがなを含まない 8 字以内の語が 2 つ以上「、」で続く）は 1 つに数える。"""
    s = re.sub(r"（[^）]*）|\([^)]*\)", "", sentence)
    s = re.sub(rf"(?:[{NOUNISH}・]{{1,8}}、){{2,}}", "、", s)
    s = re.sub(r"、+", "、", s)
    return s.count("、")


def check(name):
    try:
        text = pathlib.Path(name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"FAIL {name} [読めない] {e}")
        return 1, 0
    fails, warns = [], []
    total = passive = 0
    suru = 0
    consecutive_passive = 0
    kata_chars = 0
    all_chars = 0
    ten_total = 0
    koto_total = 0
    for no, line in prose_lines(text):
        all_chars += len(re.sub(r"\s", "", line))
        kata_chars += len(KATA_CHAR.findall(line))
        for s in sentences(line):
            total += 1
            n_ten = count_ten(s)
            ten_total += n_ten
            if n_ten >= 4:
                fails.append((no, "読点", f"1 文に読点が {n_ten} つ。3 つまでにし、文を切る: {s[:30]}…"))
            m = NO_RUN.search(s)
            if m:
                fails.append((no, "助詞の連続", f"「の」が 3 つ続く: {m.group(0)}"))
            for p in ("は", "が", "に", "で", "を"):
                for clause in s.split("、"):
                    if len(re.findall(rf"(?<![ぁ-ん]){p}(?![ぁ-ん])", clause)) >= 2 and p in ("は", "が", "を"):
                        warns.append((no, "同じ助詞", f"「{p}」が読点を挟まず 2 回: {clause[:30]}"))
                        break
            n_koto = len(re.findall(r"こと", s))
            koto_total += n_koto
            if REDUNDANT_FAIL.search(s):
                fails.append((no, "冗長", f"「{REDUNDANT_FAIL.search(s).group(0)}」。動詞 1 語で言う: {s[:30]}…"))
            elif n_koto >= 2:
                warns.append((no, "こと", f"「こと」が 1 文に {n_koto} 回: {s[:30]}…"))
            if PASSIVE_END.search(s):
                passive += 1
                consecutive_passive += 1
                if consecutive_passive == 3:
                    fails.append((no, "受身", "受身の文末が 3 文続く。動作主を書いて能動にする"))
            else:
                consecutive_passive = 0
            m = DOUBLE_NEG.search(s)
            if m:
                fails.append((no, "二重否定", f"「{m.group(0)}」。肯定か否定かを 1 つに決める"))
            m = re.search(r"(?<![ぁ-んァ-ヺ])は(?![ぁ-ん])", s)
            if m and m.start() > 30 and not s.startswith(("ただ", "なお", "また")):
                warns.append((no, "語順", f"主語の「は」が {m.start() + 1} 字目。主語を頭に置く: {s[:30]}…"))
            if len(re.findall(r"が、", s)) >= 2:
                fails.append((no, "接続助詞", f"「が、」が 1 文に 2 回。文を切る: {s[:30]}…"))
            if len(re.findall(r"し、", s)) >= 3:
                warns.append((no, "中止法", f"「〜し、」が 3 回。文を切る: {s[:30]}…"))
            suru += len(SURU_VERB.findall(s))
            for rx, repl, level in TRANS:
                m = rx.search(s)
                if m:
                    (fails if level == "FAIL" else warns).append((no, "翻訳調", f"「{m.group(0)}」→ {repl}"))
            for word, repl in KATAKANA:
                if word in s and word not in ALLOW_KATA:
                    warns.append((no, "カタカナ語", f"「{word}」→ {repl}"))
            for m in KANJI_RUN.finditer(s):
                if not any(a in m.group(0) for a in ALLOW_KANJI):
                    warns.append((no, "漢字の連続", f"漢字が {len(m.group(0))} 字続く: {m.group(0)}"))
    if suru >= 3:
        fails.append((0, "冗長", f"「〜を行う／〜を実施する」が {suru} 回。動詞 1 語にする"))
    if total >= 5 and passive / total > 0.3:
        warns.append((0, "受身", f"受身の文末が {passive}/{total} 文（{passive / total:.0%}）。30% 以内にする"))
    if all_chars >= 100 and kata_chars / all_chars > 0.2:
        warns.append((0, "カタカナ語", f"カタカナが本文の {kata_chars / all_chars:.0%}。20% 以内にする"))
    for no, rule, detail in fails:
        print(f"FAIL {name}:{no} [{rule}] {detail}" if no else f"FAIL {name} [{rule}] {detail}")
    for no, rule, detail in warns:
        print(f"WARN {name}:{no} [{rule}] {detail}" if no else f"WARN {name} [{rule}] {detail}")
    if total:
        print(f"info {name}: 文 {total}、読点の平均 {ten_total / total:.1f}、受身 {passive / total:.0%}、カタカナ {kata_chars / max(all_chars, 1):.0%}、「こと」 {koto_total / total:.2f}/文")
    verdict = "PASS" if not fails else "FAIL"
    print(f"RESULT: {verdict} fluency-check {name} (FAIL {len(fails)}、WARN {len(warns)})")
    return len(fails), len(warns)


rc = 0
for f in files:
    if f.startswith("--"):
        continue
    nf, _ = check(f)
    if nf:
        rc = 1
sys.exit(rc)
PY
}

selftest() {
  local t rc=0
  t="$(mktemp -d)"
  printf '# 題\n\n今の注文一覧は、注文を 1 回取ったあと、顧客と配送先を注文ごとに 1 回ずつ取りに行きます。直し方は、まとめて取ることです。問い合わせは 3 回で済みます。\n' > "$t/good.md"
  printf '# 題\n\n本機能においては、注文、顧客、配送先、在庫、履歴、集計の取得が、注文ごとに、個別に、順番に、実行されます。\n' > "$t/ten.md"
  printf '# 題\n\n本年の当課の取組の中心の課題は、注文一覧の表示です。\n' > "$t/no.md"
  printf '# 題\n\n関連データを一括で取得することが可能です。\n' > "$t/redundant.md"
  printf '# 題\n\n取得が実行されます。判定が行われます。結果が保存されます。表示が更新されます。\n' > "$t/passive.md"
  printf '# 題\n\nこの案を使えないわけではないので、検討します。\n' > "$t/dneg.md"
  printf '# 題\n\n検証を行う。確認を実施する。集計を行う。\n' > "$t/suru.md"
  printf '# 題\n\n速いが、高いが、使いやすい案です。\n' > "$t/ga.md"
  printf '# 題\n\n一覧の取得によってクエリが発行されます。\n' > "$t/trans.md"
  printf '# 題\n\nユーザーのステータスを見ます。\n' > "$t/kata.md"
  run "$t/good.md" | grep -q '^RESULT: PASS' || { echo "FAIL selftest: 正例が落ちた"; rc=1; }
  for pair in "ten:読点" "no:助詞の連続" "redundant:冗長" "passive:受身" "dneg:二重否定" "suru:冗長" "ga:接続助詞" "trans:翻訳調"; do
    f="${pair%%:*}"; rule="${pair#*:}"
    run "$t/$f.md" | grep -q "^FAIL .*\[$rule\]" || { echo "FAIL selftest: 負例「${rule}」（${f}）が通った"; rc=1; }
  done
  run "$t/kata.md" | grep -q '^WARN .*\[カタカナ語\]' || { echo "FAIL selftest: カタカナ語の WARN が出ない"; rc=1; }
  rm -rf "$t"
  if [ "$rc" -eq 0 ]; then echo "RESULT: PASS fluency-check --selftest (10 例)"; else echo "RESULT: FAIL fluency-check --selftest"; fi
  return $rc
}

case "${1:-}" in
  --selftest) selftest ;;
  "") echo "使い方: fluency-check.sh <ファイル>... [--profile doc|answer] | --selftest"; exit 2 ;;
  *) run "$@" ;;
esac
