#!/usr/bin/env bash
# skills/documents/scripts/shape-check.sh [--kind 種類] [--theirs] <ファイル> — 手順書・運用設計書・調査報告・仕様書・要件定義書・ポストモーテムの形の検査を束ねる。
#   1) 雛形の印: 〈…〉が残っていれば FAIL（雛形を埋めずに出すのを止める）。
#   2) 種類: 表題の先頭「種類:」か、表題の末尾の語（「〜手順書」「〜運用設計書」「〜調査報告書」「〜仕様書」「〜要件定義書」「〜ポストモーテム」）か、--kind で決める。
#      どれも無ければ FAIL。相手の形に合わせて表題に種類が無いときは --kind で渡す。check-doc には表題に種類を足した写しを渡し、元のファイルは変えない。
#   3) 型: tools/lib/check_doc.py。手順書・運用設計書・要件定義書・ポストモーテムは現場の文書の型（表題の直下の文書情報の表、必須の節、表の列と語の決まり）で見る。
#      調査報告・仕様書は資料の型（要約、導入の文、図と表、用語、必須の節、表の列の決まり）で見る。--theirs のときは「必須の節」と「文書情報」を見ない（相手の節構成が正本）。
#   4) 文体: tools/lib/check_ja.py。文の運び: skills/ja-fluent/scripts/fluency-check.sh（あれば）。
# 道具は 3 つ上の tools/ から探す（My-Lab なら tools/、写した先なら tmp/tools/）。無ければ FAIL（SKIP は FAIL と同じ）。
# 使い方: shape-check.sh [--kind 種類] [--theirs] <ファイル>   /   shape-check.sh --selftest
# 出力: 束ねた検査の FAIL・WARN・RESULT 行と、最後に RESULT: PASS|FAIL shape-check <ファイル>。FAIL が 1 件でもあれば終了コード 1。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
ROOT="$(cd "$HERE/../../.." && pwd -P)" || exit 1
TOOLS="$ROOT/tools"
FLUENCY="$ROOT/skills/ja-fluent/scripts/fluency-check.sh"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
KINDS="手順書・運用設計書・調査報告・仕様書・要件定義書・ポストモーテム"
fail=0

title_of() {  # title_of <ファイル> → 表題（# を除く）
  grep -m1 '^# ' "$1" | sed 's/^# *//'
}

kind_of() {  # kind_of <表題> → 種類か -。先頭の「種類:」を優先し、無ければ表題の末尾の語で見る。「調査報告書」は「調査報告」に揃える
  printf '%s\n' "$1" | python3 -I -c 'import re, sys
t = sys.stdin.read().strip()
pat = r"(手順書|運用設計書|調査報告書?|仕様書|要件定義書|ポストモーテム)"
m = re.match("^" + pat + r"\s*[:：]", t) or re.search(pat + "$", t)
print(m.group(1).replace("調査報告書", "調査報告") if m else "-")'
}

run_tool() {  # run_tool <コマンド...> → FAIL・WARN・RESULT の行を出し、落ちたら fail を増やす
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  printf '%s\n' "$out" | grep -E '^(FAIL|WARN|RESULT:)'
  [ "$rc" -eq 0 ] || fail=$((fail + 1))
  return 0
}

check() {  # check <ファイル> <種類|-> <theirs 0|1>
  local f="$1" kind="$2" theirs="$3" title target tmpd="" out rc n dropped verdict
  fail=0
  if [ ! -f "$f" ]; then
    printf 'FAIL %s [無い] ファイルが無い\nRESULT: FAIL shape-check %s\n' "$f" "$f"
    return 1
  fi
  # 1) 雛形の印
  while IFS= read -r n; do
    [ -n "$n" ] || continue
    fail=$((fail + 1))
    printf 'FAIL %s:%s [雛形の印] 〈…〉が残っている。中身を埋めるか、行ごと消す\n' "$f" "$n"
  done < <(grep -n '〈' "$f" | cut -d: -f1 | head -5)
  # 2) 種類
  title="$(title_of "$f")"
  [ "$kind" = "-" ] && kind="$(kind_of "$title")"
  if [ "$kind" = "-" ]; then
    fail=$((fail + 1))
    printf 'FAIL %s:1 [種類] 表題から種類が読めない。先頭を「種類: 件名」にするか、末尾を「〜手順書」「〜運用設計書」のように種類の語で終える。相手の形なら --kind 種類 を付ける（種類は %s）\n' "$f" "$KINDS"
  fi
  # 3) 型。表題に種類が無いとき（--kind で渡したとき）は、種類を足した写しを check-doc に渡す
  target="$f"
  if [ "$kind" != "-" ] && [ "$(kind_of "$title")" = "-" ]; then
    tmpd="$(mktemp -d)"
    target="$tmpd/$(basename "$f")"
    n="$(grep -n -m1 '^# ' "$f" | cut -d: -f1)"
    { printf '# %s: %s\n' "$kind" "$title"; tail -n +"$((n + 1))" "$f"; } > "$target"
  fi
  if [ -f "$TOOLS/lib/check_doc.py" ]; then
    out="$(python3 -I "$TOOLS/lib/check_doc.py" "$target" 2>&1)"; rc=$?
    [ -n "$tmpd" ] && out="$(printf '%s\n' "$out" | sed "s|$target|$f|g")"
    if [ "$theirs" -eq 1 ]; then
      dropped="$(printf '%s\n' "$out" | grep -c -E '\[(必須の節|文書情報)\]')"
      out="$(printf '%s\n' "$out" | grep '^FAIL ' | grep -v -E '\[(必須の節|文書情報)\]')"
      n="$(printf '%s\n' "$out" | grep -c '^FAIL ')"
      verdict=FAIL; rc=1
      if [ "$n" -eq 0 ]; then verdict=PASS; rc=0; fi
      out="$(printf '%s\n' "$out")
RESULT: $verdict check-doc $f ($n 件、相手の形なので必須の節と文書情報の $dropped 件は見ない)"
    fi
    printf '%s\n' "$out" | grep -E '^(FAIL|RESULT:)'
    [ "$rc" -eq 0 ] || fail=$((fail + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s [道具が無い] %s が無い（SKIP は FAIL と同じ）\n' "$f" "$TOOLS/lib/check_doc.py"
  fi
  [ -n "$tmpd" ] && rm -rf "$tmpd"
  # 4) 文体と文の運び
  if [ -f "$TOOLS/lib/check_ja.py" ]; then
    run_tool python3 -I "$TOOLS/lib/check_ja.py" "$f"
  else
    fail=$((fail + 1))
    printf 'FAIL %s [道具が無い] %s が無い（SKIP は FAIL と同じ）\n' "$f" "$TOOLS/lib/check_ja.py"
  fi
  [ -f "$FLUENCY" ] && run_tool bash "$FLUENCY" "$f"
  if [ "$fail" -eq 0 ]; then
    printf 'RESULT: PASS shape-check %s (%s)\n' "$f" "$kind"
    return 0
  fi
  printf 'RESULT: FAIL shape-check %s (%s 件)\n' "$f" "$fail"
  return 1
}

selftest() {
  local t rc=0
  t="$(mktemp -d)"
  python3 -I - "$t" <<'PY'
import pathlib
import sys

t = pathlib.Path(sys.argv[1])
good = """# 見本の作業 手順書

| 項目 | 内容 |
|---|---|
| 作業名 | 見本の作業 |
| 対象システム | 見本 |
| 作業者 / 確認者 | 秘書 / 社長 |
| 承認 | 社長 |
| 版 | 1.0（2026-11-11） |

## 1. 目的

見本の作業を、同じ順で誰でもできるようにする。本番では使わない。

## 2. 前提条件

- 作業用の場所がある。
- 読む権限と書く権限がある。

## 3. 注意事項

- 1 行を足すだけで、既存の行は消さない。

## 4. 事前確認

| # | 確認項目 | 確認方法 | 期待結果 |
|---|---|---|---|
| 1 | 作業用の場所 | `pwd` | 作業用の場所が返る |

## 5. 作業手順

### 5-1. 読む

1. ファイルを開く。
   - 期待結果: 中身が出る。
2. 1 行を書き足す。
   - 期待結果: 行数が 1 つ増える。

## 6. 異常時の処置

### 6-1. 判断

| 兆候 | 処置 |
|---|---|
| 開けない | 場所を確かめ、5-1 の 1 へ戻る |

### 6-2. 切り戻し

1. 足した行を消す。
   - 期待結果: 行数が元に戻る。

## 7. 作業記録

```text
- 実施日時:
- 実施者 / 確認者:
- 結果:
```
"""
(t / "good.md").write_text(good, encoding="utf-8")
(t / "prefix.md").write_text(good.replace("# 見本の作業 手順書", "# 手順書: 見本の作業", 1), encoding="utf-8")
(t / "hole.md").write_text(good.replace("見本の作業を、同じ順で", "〈誰〉が、同じ順で"), encoding="utf-8")
(t / "nokind.md").write_text(good.replace("# 見本の作業 手順書", "# 見本の作業", 1), encoding="utf-8")
(t / "opener.md").write_text(good.replace("見本の作業を、同じ順で誰でもできるようにする。", "この節では、見本の作業を誰でもできるようにする。"), encoding="utf-8")
reasons = "許可の正は設定ファイルである。\n\n優先度 6 が国外の遮断で、優先度 7 が許可以外の遮断である。\n\nだから、許可は優先度 0 に入れる。\n\n"
(t / "reasons.md").write_text(good.replace("### 5-1. 読む\n", reasons + "### 5-1. 読む\n"), encoding="utf-8")
(t / "theirs.md").write_text(good.replace("## 7. 作業記録", "## 7. 実施結果"), encoding="utf-8")
(t / "noexpect.md").write_text(good.replace("   - 期待結果: 行数が 1 つ増える。\n", ""), encoding="utf-8")
table = good[good.index("| 項目 | 内容 |"):good.index("## 1. 目的")]
(t / "notable.md").write_text(good.replace(table, ""), encoding="utf-8")
PY
  check "$t/good.md" - 0 >/dev/null || { echo "FAIL selftest: 正例（末尾が手順書）が落ちた"; check "$t/good.md" - 0 | grep '^FAIL'; rc=1; }
  check "$t/prefix.md" - 0 >/dev/null || { echo "FAIL selftest: 正例（先頭が手順書:）が落ちた"; check "$t/prefix.md" - 0 | grep '^FAIL'; rc=1; }
  check "$t/hole.md" - 0 | grep -q '\[雛形の印\]' || { echo "FAIL selftest: 雛形の印が通った"; rc=1; }
  check "$t/nokind.md" - 0 | grep -q '\[種類\]' || { echo "FAIL selftest: 種類の無い表題が通った"; rc=1; }
  check "$t/nokind.md" 手順書 0 >/dev/null || { echo "FAIL selftest: --kind を付けた表題が落ちた"; check "$t/nokind.md" 手順書 0 | grep '^FAIL'; rc=1; }
  check "$t/opener.md" - 0 | grep -q '\[禁則語\]' || { echo "FAIL selftest: 「この節では」が通った"; rc=1; }
  check "$t/reasons.md" - 0 | grep -q '\[手順の形\]' || { echo "FAIL selftest: 手順の中の理由の段落が通った"; rc=1; }
  check "$t/theirs.md" - 0 | grep -q '\[必須の節\]' || { echo "FAIL selftest: 相手の節の名前が、印なしで通った"; rc=1; }
  check "$t/theirs.md" - 1 >/dev/null || { echo "FAIL selftest: --theirs を付けても落ちた"; check "$t/theirs.md" - 1 | grep '^FAIL'; rc=1; }
  check "$t/noexpect.md" - 0 | grep -q '\[期待結果\]' || { echo "FAIL selftest: 期待結果の無い操作が通った"; rc=1; }
  check "$t/notable.md" - 0 | grep -q '\[文書情報\]' || { echo "FAIL selftest: 文書情報の表が無いのに通った"; rc=1; }
  check "$t/notable.md" - 1 >/dev/null || { echo "FAIL selftest: 相手の形（文書情報なし）が --theirs でも落ちた"; check "$t/notable.md" - 1 | grep '^FAIL'; rc=1; }
  rm -rf "$t"
  if [ "$rc" -eq 0 ]; then echo "RESULT: PASS shape-check --selftest (12 例)"; else echo "RESULT: FAIL shape-check --selftest"; fi
  return $rc
}

usage() { echo "使い方: shape-check.sh [--kind 種類] [--theirs] <ファイル> | --selftest（種類は ${KINDS}）"; }

kind="-"; theirs=0; file=""
[ "${1:-}" = "--selftest" ] && { selftest; exit $?; }
while [ $# -gt 0 ]; do
  case "$1" in
    --kind) kind="${2:-}"; shift 2 ;;
    --kind=*) kind="${1#--kind=}"; shift ;;
    --theirs) theirs=1; shift ;;
    -h|--help) usage; exit 2 ;;
    *) file="$1"; shift ;;
  esac
done
[ -n "$file" ] || { usage; exit 2; }
case "$kind" in
  調査報告書) kind="調査報告" ;;
  -|手順書|運用設計書|調査報告|仕様書|要件定義書|ポストモーテム) ;;
  *) echo "FAIL [種類] --kind は $KINDS のどれか（${kind}）"; exit 2 ;;
esac
check "$file" "$kind" "$theirs"
