#!/usr/bin/env bash
# tools/project-verify.sh [--fast|--full] — 他のプロジェクト（tmp/ に写した版）で、そのプロジェクトの検証の命令を見つけて全部回す。
#   見つけ方: package.json の scripts、Makefile の lint/test/build、go.mod、pyproject.toml か requirements.txt、Cargo.toml、
#   tests/ の test_*.py（pytest が回らなければ python3 -m unittest discover -s tests）。
#   加えて、AI が tmp/ に書いた文書（tmp/flow/**/*.md、tmp/ISSUE_*.md、tmp/PR_*.md）を check-file.sh と check-refs.sh で検査する。
#   --fast: lint・typecheck・単体テストと文書。--full: build・e2e と、gitleaks・trivy（入っていれば）も。
#   root は、このファイルの場所から決める（<root>/tmp/tools/project-verify.sh → <root>。My-Lab の tools/ にあるときは My-Lab）。
# 出力: 命令ごとの RESULT 行と、最後に RESULT: PASS|FAIL|WARN project-verify。1 つでも FAIL なら終了コード 1。
#   プロジェクトの検証の命令（上の見つけ方の 1〜5）が 1 つも無ければ、文書の検査が通っても PASS にせず、
#   RESULT: WARN project-verify（回す検証の命令が無い）を出して終了コード 3 にする。
# 記録: <root>/tmp/.verify/last-fast.txt（--full なら last-full.txt）に、日時と命令ごとの RESULT 行と最後の RESULT 行を書く。
#       My-Lab の中で回したときは、verify-all.sh の記録を上書きしないよう project-verify-last-<mode>.txt に書く。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
if [ "$(basename "$(dirname "$HERE")")" = "tmp" ]; then ROOT="$(cd "$HERE/../.." && pwd -P)"; RECORD_PREFIX="last"; else ROOT="$(cd "$HERE/.." && pwd -P)"; RECORD_PREFIX="project-verify-last"; fi
cd "$ROOT" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
MODE="fast"
case "${1:-}" in --full) MODE="full" ;; --fast|"") MODE="fast" ;; *) echo "使い方: project-verify.sh [--fast|--full]"; exit 2 ;; esac
fail=0; ran=0
STARTED="$(date '+%Y-%m-%d %H:%M:%S')"
SUMMARY=""

run() {  # run <名前> <コマンド...>
  local name="$1"; shift
  local out rc line
  ran=$((ran + 1))
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then
    line="RESULT: PASS $name"
  else
    fail=$((fail + 1))
    printf '%s\n' "$out" | tail -15 | sed "s|^|FAIL $name: |"
    line="RESULT: FAIL $name (rc=$rc)"
  fi
  printf '%s\n' "$line"
  SUMMARY="$SUMMARY$line"$'\n'
}

finish() {  # finish <最後の RESULT 行> <終了コード> → 出力し、tmp/.verify/last-<mode>.txt に記録して終える
  printf '%s\n' "$1"
  if mkdir -p "$ROOT/tmp/.verify" 2>/dev/null; then
    { printf '日時: %s（終了 %s）\n' "$STARTED" "$(date '+%Y-%m-%d %H:%M:%S')"
      printf '命令: bash tmp/tools/project-verify.sh --%s\n' "$MODE"
      printf '%s' "$SUMMARY"
      printf '%s\n' "$1"; } > "$ROOT/tmp/.verify/$RECORD_PREFIX-$MODE.txt"
  fi
  exit "$2"
}

# 1. package.json の scripts
if [ -f package.json ]; then
  PM="npm"; [ -f pnpm-lock.yaml ] && PM="pnpm"; [ -f yarn.lock ] && PM="yarn"
  has_script() { node -e 'const p=require(process.cwd()+"/package.json"); process.exit(p.scripts && p.scripts[process.argv[1]] ? 0 : 1)' "$1" 2>/dev/null; }
  for s in lint typecheck type-check check; do has_script "$s" && run "$PM run $s" "$PM" run -s "$s"; done
  if has_script test:unit; then run "$PM run test:unit" "$PM" run -s test:unit; elif has_script test; then run "$PM run test" "$PM" run -s test; fi
  if [ "$MODE" = "full" ]; then
    has_script build && run "$PM run build" "$PM" run -s build
    for s in test:e2e e2e; do has_script "$s" && run "$PM run $s" "$PM" run -s "$s"; done
  fi
fi
# 2. Makefile
if [ -f Makefile ]; then
  for t in lint test; do grep -qE "^$t:" Makefile && run "make $t" make "$t"; done
  [ "$MODE" = "full" ] && grep -qE '^build:' Makefile && run "make build" make build
fi
# 3. Go
if [ -f go.mod ] && command -v go >/dev/null 2>&1; then
  run "go vet" go vet ./...
  run "go test" go test ./...
fi
# 4. Python
if [ -f pyproject.toml ] || [ -f requirements.txt ]; then
  command -v ruff >/dev/null 2>&1 && run "ruff check" ruff check .
  if command -v pytest >/dev/null 2>&1 && { [ -d tests ] || ls test_*.py >/dev/null 2>&1; }; then run "pytest" pytest -q; PY_TESTED=1; fi
fi
# 4b. Python の標準の unittest（pytest が回らず、tests/ に test_*.py があるとき）
if [ -z "${PY_TESTED:-}" ] && [ -d tests ] && [ -n "$(find tests -name 'test_*.py' -type f 2>/dev/null | head -1)" ]; then
  run "python3 -m unittest discover" python3 -m unittest discover -s tests
fi
# 5. Rust
if [ -f Cargo.toml ] && command -v cargo >/dev/null 2>&1; then
  run "cargo test" cargo test --quiet
fi
proj_ran=$ran  # ここまでがプロジェクト自身の検証の命令。0 なら最後に WARN にする
# 6. AI が書いた文書
docs="$( { find tmp/flow -name '*.md' -type f 2>/dev/null; ls tmp/ISSUE_*.md tmp/PR_*.md 2>/dev/null; } | sort -u)"
if [ -n "$docs" ]; then
  # shellcheck disable=SC2086
  run "check-file（tmp の文書 $(printf '%s\n' "$docs" | wc -l | tr -d ' ') 本）" bash "$HERE/check-file.sh" $docs
  # shellcheck disable=SC2086
  run "check-refs（tmp の文書 $(printf '%s\n' "$docs" | wc -l | tr -d ' ') 本）" bash "$HERE/check-refs.sh" $docs
fi
# 7. 秘密と依存（full。入っていれば）
if [ "$MODE" = "full" ]; then
  command -v gitleaks >/dev/null 2>&1 && run "gitleaks" gitleaks dir . --no-banner --redact --exit-code 1
  command -v trivy >/dev/null 2>&1 && run "trivy fs" trivy fs --scanners vuln --severity HIGH,CRITICAL --exit-code 1 --skip-dirs node_modules,tmp --quiet .
fi

if [ "$fail" -eq 0 ] && [ "$proj_ran" -eq 0 ]; then
  others=""; [ "$ran" -gt 0 ] && others="。文書などの検査 $ran 件は PASS"
  finish "RESULT: WARN project-verify --$MODE (回す検証の命令が無い。package.json・Makefile・go.mod・pyproject.toml・requirements.txt・Cargo.toml・tests/test_*.py を見た$others)" 3
fi
if [ "$fail" -eq 0 ]; then verdict=PASS; rc=0; else verdict=FAIL; rc=1; fi
finish "$(printf 'RESULT: %s project-verify --%s (%d 件中 FAIL %d)' "$verdict" "$MODE" "$ran" "$fail")" "$rc"
