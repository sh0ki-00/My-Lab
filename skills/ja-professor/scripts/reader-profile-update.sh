#!/usr/bin/env bash
# skills/ja-professor/scripts/reader-profile-update.sh [--file <reader-profile.md>] [--known <語>]... [--stuck <語>]...
#   読み手の記録に、知っている語とつまずいた語を日付つきで足す。文の解釈はしない（引数で語を受ける）。
#   ファイルが無ければ templates/reader-profile.md から作る。重複は足さない。表の列数（3 列）が崩れていれば FAIL。
# 使い方: reader-profile-update.sh --known ORM --stuck 索引   /   reader-profile-update.sh --selftest
# 出力: 足した語の一覧と RESULT: PASS|FAIL reader-profile-update。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
TEMPLATE="$HERE/../templates/reader-profile.md"

update() {  # update <ファイル> <known の一覧（改行区切り）> <stuck の一覧>
  python3 -I - "$1" "$2" "$3" "$TEMPLATE" <<'PY'
import datetime
import pathlib
import re
import shutil
import sys

path, known, stuck, template = pathlib.Path(sys.argv[1]), [w for w in sys.argv[2].split("\n") if w], [w for w in sys.argv[3].split("\n") if w], pathlib.Path(sys.argv[4])
if not path.exists():
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(template, path)
lines = path.read_text(encoding="utf-8").split("\n")
today = datetime.date.today().isoformat()
added = []
fails = []

def section_rows(title):
    start = next((i for i, l in enumerate(lines) if l.startswith("## ") and title in l), None)
    if start is None:
        return None, None, []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    rows = [i for i in range(start, end) if lines[i].startswith("|")]
    return start, end, rows

for title, words in (("知っている語", known), ("つまずいた語", stuck)):
    start, end, rows = section_rows(title)
    if start is None:
        fails.append(f"「## {title}」の節が無い")
        continue
    existing = {lines[i].strip("|").split("|")[0].strip() for i in rows[2:]}
    for i in rows:
        if len(lines[i].strip().strip("|").split("|")) != 3:
            fails.append(f"{i + 1} 行目: 表の列数が 3 でない")
    placeholder = [i for i in rows[2:] if "まだ無い" in lines[i]]
    insert_at = rows[-1] + 1 if rows else end
    for w in words:
        if w in existing:
            continue
        new = f"| {w} | {today} | 確認の問いの答え |"
        if placeholder:
            lines[placeholder[0]] = new
            placeholder = []
        else:
            lines.insert(insert_at, new)
            insert_at += 1
        added.append(f"{title}: {w}")
        existing.add(w)
    if title == "知っている語":
        # つまずいた語に同じ語があれば、知っている語へ移る（つまずきが解けた）
        pass

if not fails:
    path.write_text("\n".join(lines), encoding="utf-8")
for a in added:
    print(f"足した: {a}")
for f in fails:
    print(f"FAIL {path} [記録] {f}")
print(f"RESULT: {'PASS' if not fails else 'FAIL'} reader-profile-update {path} (足した {len(added)} 語)")
sys.exit(1 if fails else 0)
PY
}

selftest() {
  local t rc=0
  t="$(mktemp -d)"
  update "$t/reader-profile.md" "ORM" "索引" >/dev/null || { echo "FAIL selftest: 新規の記録に足せない"; rc=1; }
  if ! { grep -q '^| ORM |' "$t/reader-profile.md" && grep -q '^| 索引 |' "$t/reader-profile.md"; }; then echo "FAIL selftest: 2 語が表に無い"; rc=1; fi
  update "$t/reader-profile.md" "ORM" "" | grep -q '足した 0 語' || { echo "FAIL selftest: 重複を足した"; rc=1; }
  printf '# x\n\n## 知っている語\n\n| 語 | 日 |\n|---|---|\n| a | b |\n\n## つまずいた語\n\n| 語 | 日 | 出 |\n|---|---|---|\n' > "$t/broken.md"
  update "$t/broken.md" "x" "" | grep -q '^FAIL' || { echo "FAIL selftest: 列数の崩れが通った"; rc=1; }
  rm -rf "$t"
  if [ "$rc" -eq 0 ]; then echo "RESULT: PASS reader-profile-update --selftest (3 例)"; else echo "RESULT: FAIL reader-profile-update --selftest"; fi
  return $rc
}

file="tmp/flow/professor/reader-profile.md"; known=""; stuck=""
case "${1:-}" in --selftest) selftest; exit $? ;; "") echo "使い方: reader-profile-update.sh [--file <記録>] [--known <語>]... [--stuck <語>]..."; exit 2 ;; esac
while [ $# -gt 0 ]; do
  case "$1" in
    --file) file="${2:-}"; shift 2 ;;
    --known) known="${known}${known:+$'\n'}${2:-}"; shift 2 ;;
    --stuck) stuck="${stuck}${stuck:+$'\n'}${2:-}"; shift 2 ;;
    *) echo "使い方: reader-profile-update.sh [--file <記録>] [--known <語>]... [--stuck <語>]..."; exit 2 ;;
  esac
done
update "$file" "$known" "$stuck"
