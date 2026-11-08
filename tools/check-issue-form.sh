#!/usr/bin/env bash
# tools/check-issue-form.sh <.github/ISSUE_TEMPLATE/*.yml> — GitHub の Issue フォームの検査。
#   name・description・body がある。各要素に type があり、markdown 以外には id と label がある。id が重ならない。
#   必須（validations.required: true）が 3 つ以上ある。dropdown に options がある。
#   ruby で YAML を JSON にし、python で見る（どちらも macOS にある）。
set -u
f="${1:-}"
[ -f "$f" ] || { echo "使い方: check-issue-form.sh <yml>"; exit 2; }
command -v ruby >/dev/null 2>&1 || { echo "FAIL $f [道具が無い] ruby が無い"; exit 1; }
json="$(ruby -ryaml -rjson -e 'puts YAML.load_file(ARGV[0]).to_json' "$f" 2>&1)" || { echo "FAIL $f [yaml] 読めない: $json"; exit 1; }
printf '%s' "$json" | python3 -I -c '
import json, sys
name = sys.argv[1]
d = json.load(sys.stdin)
issues = []
for k in ("name", "description", "body"):
    if not d.get(k):
        issues.append(f"{k} が無い")
ids = []
required = 0
for i, el in enumerate(d.get("body") or [], 1):
    t = el.get("type")
    if t not in ("markdown", "textarea", "input", "dropdown", "checkboxes"):
        issues.append(f"要素 {i}: type「{t}」は使えない")
        continue
    if t == "markdown":
        continue
    if not el.get("id"):
        issues.append(f"要素 {i}: id が無い")
    else:
        ids.append(el["id"])
    if not (el.get("attributes") or {}).get("label"):
        issues.append(f"要素 {i}: label が無い")
    if t == "dropdown" and not (el.get("attributes") or {}).get("options"):
        issues.append(f"要素 {i}: dropdown に options が無い")
    if (el.get("validations") or {}).get("required") is True:
        required += 1
    if t == "checkboxes":
        required += sum(1 for o in (el.get("attributes") or {}).get("options", []) if o.get("required") is True)
dup = {x for x in ids if ids.count(x) > 1}
if dup:
    issues.append(f"id が重なる: {sorted(dup)}")
if required < 3:
    issues.append(f"必須の項目が {required} 個。3 個以上にする")
for x in issues:
    print(f"FAIL {name} [issue-form] {x}")
verdict = "PASS" if not issues else "FAIL"
print(f"RESULT: {verdict} check-issue-form {name} ({len(issues)} 件、必須 {required} 個)")
sys.exit(1 if issues else 0)
' "$f"
