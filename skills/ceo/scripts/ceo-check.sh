#!/usr/bin/env bash
# skills/ceo/scripts/ceo-check.sh <事業判断メモ.md> — 事業判断メモの検査。
#   必須の節（目的・顧客・観点・判断・KPI・やらないこと・未確定・次の一歩）。目的は 1 文。5 つの観点の全行に判定（強い／中／弱い）と根拠、
#   収益性に回収期間の式。判断は やる／やらない／保留 で言い切る。可逆性に戻せる／戻せない。費用に最短・最長・上限。
#   KPI は主指標 1 つ、入力指標 1 つ以上、全行に目標の数字・期限・測り方。やらないこと 2 行以上（理由と再検討の条件）。
#   未確定の決め方と期限。社長への問いは 1 つ。数字に架空か出典の断り。60 行以内（空行を除く）、40 行未満は WARN。図が無ければ WARN。
#   --board を付けると優先順位表の検査（RICE の 4 列と点の計算、順位 1 は 1 つ、点の順と違う行は理由に「止まる」）。
# 使い方: ceo-check.sh <ファイル> [--board]   /   ceo-check.sh --selftest
# 出力: FAIL <ファイル>:<行> [<決まり>] <内容> と、最後に RESULT: PASS|FAIL ceo-check。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

check() {  # check <ファイル> [--board]
  python3 -I - "$@" <<'PY'
import re
import sys

args = sys.argv[1:]
mode = "board" if "--board" in args else "judgment"
args = [a for a in args if a != "--board"]
name = args[0]
try:
    text = open(name, encoding="utf-8").read()
except OSError as e:
    print(f"FAIL {name} [読めない] {e}")
    print(f"RESULT: FAIL ceo-check {name}")
    sys.exit(1)

issues = []
warns = []
lines = []
has_mermaid = False
in_comment = in_code = False
for i, l in enumerate(text.split("\n"), 1):
    s = l.strip()
    if in_comment:
        in_comment = "-->" not in s
        continue
    if s.startswith("<!--"):
        in_comment = "-->" not in s[4:]
        continue
    if s.startswith("```"):
        if not in_code and "mermaid" in s:
            has_mermaid = True
        in_code = not in_code
        continue
    if not in_code:
        lines.append((i, l))
body = "\n".join(l for _, l in lines)
total = len([l for l in text.split("\n") if l.strip()])


def fail(no, rule, detail):
    issues.append((no, rule, detail))


def tables():
    out, cur, section = [], None, ""
    for no, l in lines:
        s = l.strip()
        if s.startswith("#"):
            section, cur = s.lstrip("#").strip(), None
            continue
        if not s.startswith("|"):
            cur = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cur is None:
            cur = {"section": section, "header": cells, "rows": [], "no": no}
            out.append(cur)
        elif all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        else:
            cur["rows"].append((no, cells))
    return out


TABLES = tables()


def section(key):
    idx = next((k for k, (_, l) in enumerate(lines) if re.match(r"^##\s", l) and key in l), None)
    if idx is None:
        return None
    end = next((j for j in range(idx + 1, len(lines)) if re.match(r"^##\s", lines[j][1])), len(lines))
    return lines[idx:end]


def section_table(key):
    return next((t for t in TABLES if key in t["section"]), None)


def prose(sec):
    return "".join(l for _, l in sec[1:] if l.strip() and not l.strip().startswith(("|", "#", ">")))


def col(t, key):
    return next((k for k, c in enumerate(t["header"]) if key in c), None)


def cell(cells, k):
    return cells[k] if k is not None and len(cells) > k else ""


def holes():
    for no, l in lines:
        if re.search(r"<[^>]*>", l) and not re.search(r"<br\s*/?>", l):
            fail(no, "雛形の穴", "<…> が残っている")


title = next((l[2:].strip() for _, l in lines if l.startswith("# ")), "")

if mode == "judgment":
    if not title.startswith("事業判断メモ"):
        fail(1, "表題", "「# 事業判断メモ: 件名」で始める")
    if total > 60:
        fail(0, "行数", f"{total} 行（空行を除く）。60 行以内にし、詳細は参照に置く")
    elif total < 40:
        warns.append((0, "行数", f"{total} 行。40 行未満は節が薄い"))
    for key in ("目的", "顧客", "観点", "判断", "KPI", "やらないこと", "未確定", "次の一歩"):
        if section(key) is None:
            fail(0, "必須の節", f"「## {key}」が無い")
    sec = section("目的")
    if sec is not None:
        n = len([s for s in re.split(r"[。！？]", prose(sec)) if s.strip()])
        if n != 1:
            fail(sec[0][0], "目的", f"{n} 文。目的は 1 文にする")
    t = section_table("観点")
    if t is None:
        if section("観点") is not None:
            fail(0, "観点", "表（観点 | 判定 | 根拠）が無い")
    else:
        kj, kg = col(t, "判定"), col(t, "根拠")
        if kj is None or kg is None:
            fail(t["no"], "観点", "表に「判定」と「根拠」の列が要る")
        names = {cells[0]: (no, cells) for no, cells in t["rows"] if cells}
        for want in ("市場性", "収益性", "実現性", "差別化", "拡張性"):
            if want not in names:
                fail(t["no"], "観点", f"「{want}」の行が無い。5 つの観点を空にしない")
        for key, (no, cells) in names.items():
            j, g = cell(cells, kj), cell(cells, kg)
            if j not in ("強い", "中", "弱い"):
                fail(no, "判定", f"「{j}」。判定は 強い／中／弱い の 3 段にする")
            if not g:
                fail(no, "観点", f"{key} の根拠が空")
            if key == "収益性" and not (re.search(r"[÷/]", g) and "か月" in g):
                fail(no, "収益性", "回収期間の式（費用 ÷ 月の効果 = n か月）を根拠に書く")
    t = section_table("判断")
    if t is None:
        if section("判断") is not None:
            fail(0, "判断", "表（項目 | 内容）が無い")
    else:
        rows = {cells[0]: (no, cells[1] if len(cells) > 1 else "") for no, cells in t["rows"] if cells}

        def row(key):
            return next(((no, v) for k, (no, v) in rows.items() if key in k), (None, None))

        no, v = row("判断")
        if v is None:
            fail(t["no"], "判断", "「判断」の行が無い")
        elif not re.match(r"^(やる|やらない|保留)", v):
            fail(no, "判断", "「やる」「やらない」「保留」のどれかで言い切る。選択肢だけ並べない")
        no, v = row("優先度")
        if v is None or not v.strip():
            fail(no or t["no"], "優先度", "優先度と、1 位の理由（今やらないと何が止まるか）を書く")
        no, v = row("可逆性")
        if v is None:
            fail(t["no"], "可逆性", "「決定の可逆性」の行が無い")
        elif not re.search(r"戻せる|戻せない", v):
            fail(no, "可逆性", "戻せる決定と戻せない決定を分け、戻せない決定の送り先（設計書）を書く")
        no, v = row("費用")
        if v is None:
            fail(t["no"], "費用", "「費用と期間」の行が無い")
        else:
            for word in ("最短", "最長", "上限"):
                if word not in v:
                    fail(no, "費用", f"「{word}」が無い。最短・最長・上限で書く")
    if re.search(r"上限を超え[^。]{0,12}期間を(延|伸)ば", body):
        fail(0, "費用", "上限を超えたら期間ではなく範囲を削る")
    t = section_table("KPI")
    if t is None:
        if section("KPI") is not None:
            fail(0, "KPI", "表（指標 | 種類 | 今の値 | 目標 | 期限 | 測り方）が無い")
    else:
        pos = {k: col(t, k) for k in ("種類", "今の値", "目標", "期限", "測り方")}
        for k, p in pos.items():
            if p is None:
                fail(t["no"], "KPI", f"表に「{k}」の列が無い")
        kinds = [cell(cells, pos["種類"]) for _, cells in t["rows"]]
        if sum(1 for k in kinds if k.startswith("主指標")) != 1:
            fail(t["no"], "KPI", f"主指標の行が {sum(1 for k in kinds if k.startswith('主指標'))} 行。1 行にする")
        if not any("入力指標" in k for k in kinds):
            fail(t["no"], "KPI", "入力指標（担当者が自分で動かせる指標）を 1 行以上入れる")
        for no, cells in t["rows"]:
            if not re.search(r"\d", cell(cells, pos["目標"])):
                fail(no, "KPI", "目標に数字が無い。「速く」「使いやすく」は測れない")
            if not re.search(r"\d|末|まで", cell(cells, pos["期限"])):
                fail(no, "KPI", "期限が無い（日付か「末」「まで」）")
            if not cell(cells, pos["測り方"]).strip():
                fail(no, "KPI", "測り方（誰が、何で、いつ測るか）が空")
    t = section_table("やらないこと")
    if t is None:
        if section("やらないこと") is not None:
            fail(0, "やらないこと", "表（やらないこと | 理由 | 再検討の条件）が無い")
    else:
        kr, kc = col(t, "理由"), col(t, "再検討")
        if kr is None or kc is None:
            fail(t["no"], "やらないこと", "表に「理由」と「再検討の条件」の列が要る")
        if len(t["rows"]) < 2:
            fail(t["no"], "やらないこと", f"{len(t['rows'])} 行。2 行以上書く")
        for no, cells in t["rows"]:
            if not cell(cells, kr).strip() or not cell(cells, kc).strip():
                fail(no, "やらないこと", "理由か再検討の条件が空")
    t = section_table("未確定")
    if t is None:
        if section("未確定") is not None:
            fail(0, "未確定", "表（# | 内容 | 決め方 | 期限）が無い。無ければ「なし」の 1 行")
    else:
        kd, ke = col(t, "決め方"), col(t, "期限")
        if kd is None or ke is None:
            fail(t["no"], "未確定", "表に「決め方」と「期限」の列が要る")
        for no, cells in t["rows"]:
            if not cell(cells, kd).strip() or not cell(cells, ke).strip():
                fail(no, "未確定", "決め方か期限が空。未確定を理由に判断を止めない")
    sec = section("次の一歩")
    if sec is not None:
        q = len(re.findall(r"か。|？|お願いします|伺います", prose(sec)))
        if q > 1:
            fail(sec[0][0], "問い", f"社長への問いが {q} つ。「承認するか」の 1 つに絞る")
    if "ご判断ください" in body and not re.search(r"やる|やらない|保留|承認", body):
        fail(0, "丸投げ", "「ご判断ください」で終わらず、判断を言い切る")
    if re.search(r"\d", body) and not re.search(r"架空|出典|実測|受付票", body):
        fail(0, "数字の根拠", "数字の出どころ（架空／出典／実測／受付票の事実）を書く")
    if not has_mermaid:
        warns.append((0, "図", "図が無い。範囲と効きを 1 枚で示す図があると読みやすい（表だけでも可）"))
    holes()
else:
    if not title.startswith("優先順位表"):
        fail(1, "表題", "「# 優先順位表: 件名」で始める")
    t = next((t for t in TABLES if col(t, "順位") is not None), None)
    if t is None:
        fail(0, "表", "表（候補 | 届く人数 | 1 人への効き | 確信度 | 費用 | 点 | 順位 | 理由 | 後回しの条件）が無い")
    else:
        pos = {k: col(t, k) for k in ("候補", "届く人数", "効き", "確信度", "費用", "点", "順位", "理由", "後回し")}
        for k, p in pos.items():
            if p is None:
                fail(t["no"], "表", f"表に「{k}」の列が無い")
        if all(p is not None for p in pos.values()):
            ranks = []
            parsed = []
            for no, cells in t["rows"]:
                def num(k):
                    m = re.search(r"\d+(?:\.\d+)?", cell(cells, pos[k]).replace(",", ""))
                    return float(m.group(0)) if m else None
                reach, impact, conf, effort, score = num("届く人数"), num("効き"), num("確信度"), num("費用"), num("点")
                rank = num("順位")
                if None in (reach, impact, conf, effort, score, rank):
                    fail(no, "点", "届く人数・効き・確信度・費用・点・順位は数字で書く")
                    continue
                if conf not in (100, 80, 50):
                    fail(no, "確信度", f"{conf:g}%。確信度は 100／80／50% の 3 段")
                expect = reach * impact * (conf / 100) / effort if effort else 0
                if abs(expect - score) > max(0.05 * expect, 0.05):
                    fail(no, "点", f"点 {score:g} が 届く人数 × 効き × 確信度 ÷ 費用 = {expect:.1f} と合わない")
                if not cell(cells, pos["理由"]).strip():
                    fail(no, "理由", "順位の理由が空。今やらないと何が止まるかを書く")
                if rank != 1 and not cell(cells, pos["後回し"]).strip():
                    fail(no, "後回し", "2 位以下には後回しの条件（いつ再検討するか）を書く")
                ranks.append(rank)
                parsed.append((rank, score, "止ま" in cell(cells, pos["理由"]), no))
            if ranks.count(1) != 1:
                fail(t["no"], "順位", f"順位 1 が {ranks.count(1)} 行。1 位は 1 つに決める")
            ordered = sorted((p for p in parsed if not p[2]), key=lambda p: p[0])
            for a, b in zip(ordered, ordered[1:]):
                if a[1] < b[1]:
                    fail(b[3], "順位", "点の順と違う。点より上に置く候補は、理由に「今やらないと〜が止まる」を書く")
    holes()

for no, rule, detail in issues:
    where = f"{name}:{no}" if no else name
    print(f"FAIL {where} [{rule}] {detail}")
for no, rule, detail in warns:
    where = f"{name}:{no}" if no else name
    print(f"WARN {where} [{rule}] {detail}")
verdict = "PASS" if not issues else "FAIL"
print(f"RESULT: {verdict} ceo-check {name} (FAIL {len(issues)}、WARN {len(warns)})")
sys.exit(0 if not issues else 1)
PY
}

selftest() {
  local t rc=0 here good board
  here="$(cd "$(dirname "$0")" && pwd -P)"
  good="$here/../examples/judgment-order-list.md"
  board="$here/../examples/priority-board-order-list.md"
  t="$(mktemp -d)"
  check "$good" >/dev/null || { echo "FAIL selftest: 完成例（事業判断メモ）が落ちた"; rc=1; }
  check "$board" --board >/dev/null || { echo "FAIL selftest: 完成例（優先順位表）が落ちた"; rc=1; }
  sed -e 's/^| 差別化 | 弱い |/| 差別化 | やや弱い |/' "$good" > "$t/judge.md"
  check "$t/judge.md" | grep -q '\[判定\]' || { echo "FAIL selftest: 判定の 3 段以外が通った"; rc=1; }
  sed -e 's/^| 判断 | やる（/| 判断 | ご判断ください（/' "$good" > "$t/decision.md"
  check "$t/decision.md" | grep -q '\[判断\]' || { echo "FAIL selftest: 言い切らない判断が通った"; rc=1; }
  sed -e 's/| 主指標・約束 |/| 出力指標・約束 |/' "$good" > "$t/kpi.md"
  check "$t/kpi.md" | grep -q '\[KPI\]' || { echo "FAIL selftest: 主指標 0 行が通った"; rc=1; }
  grep -v '^| 注文詳細の作り直し\|^| 外部の注文管理' "$good" > "$t/no.md"
  check "$t/no.md" | grep -q '\[やらないこと\]' || { echo "FAIL selftest: やらないこと 1 行が通った"; rc=1; }
  { cat "$good"; for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do echo "補足の行です。"; done; } > "$t/long.md"
  check "$t/long.md" | grep -q '\[行数\]' || { echo "FAIL selftest: 60 行超が通った"; rc=1; }
  sed -e 's/÷ 15.1 万円 = 10〜12 か月で、目安の 12 か月以内に収まる/と 15.1 万円で 10〜12 月分/' "$good" > "$t/roi.md"
  check "$t/roi.md" | grep -q '\[収益性\]' || { echo "FAIL selftest: 回収期間の式の欠けが通った"; rc=1; }
  check "$here/../templates/judgment.md" | grep -q '\[雛形の穴\]' || { echo "FAIL selftest: 雛形（穴埋めのまま）が通った"; rc=1; }
  sed -e 's/| 15.0 |/| 1.5 |/' "$board" > "$t/score.md"
  check "$t/score.md" --board | grep -q '\[点\]' || { echo "FAIL selftest: 点の計算違いが通った"; rc=1; }
  sed -e 's/| 5.0 | 3 |/| 5.0 | 1 |/' "$board" > "$t/rank.md"
  check "$t/rank.md" --board | grep -q '\[順位\]' || { echo "FAIL selftest: 1 位が 2 つで通った"; rc=1; }
  rm -rf "$t"
  if [ "$rc" -eq 0 ]; then echo "RESULT: PASS ceo-check --selftest (11 例)"; else echo "RESULT: FAIL ceo-check --selftest"; fi
  return $rc
}

case "${1:-}" in
  --selftest) selftest ;;
  "") echo "使い方: ceo-check.sh <ファイル> [--board] | --selftest"; exit 2 ;;
  *) check "$@" ;;
esac
