#!/usr/bin/env bash
# shellcheck disable=SC2329  # 場面の関数は、名前を組み立てて呼ぶ（下の「実行」）
# tools/tests/deploy-test.sh [<deploy.sh>] — deploy.sh の試験。使い捨ての場所だけで回し、本物の My-Lab と HOME には触れない。
#   引数で試す deploy.sh を選べる（既定は My-Lab の deploy.sh）。直す前の版と比べるときに使う。
#   場面ごとに、偽の正本（deploy.sh の写しと小さな一式）と偽の HOME と写す先を作る。写す先の git も使い捨て。
#   確かめること: tmp がリンクか正本そのもの・正本の中・.git の中・印（tmp/DEPLOYED.md）の無い自前の tmp/tools などでは、何も変えずに止まる。
#   exclude は git が読む所（worktree なら共通の .git/info/exclude）に、写した tmp/ だけを外す行で足し、改行の無い最後の行を壊さない。
#   外れたかは git check-ignore で確かめ、DEPLOYED.md の git の行にはしたことを書く。先頭が - のパスと CDPATH でも、渡した場所に写す。
#   写した直後に印（tmp/.verify/last-pass）と一覧を置き、前からある tmp/ の文書を検証の範囲外にする。
#   場面は全部、LANG=C と LANG=ja_JP.UTF-8 の 2 通りで回す。bash は社長の機械と同じ /bin/bash（3.2）を使う。
# 出力: 場面ごとに PASS <場面> [<LANG>] か FAIL <場面> [<LANG>] <理由>。最後に RESULT 行。1 件でも FAIL なら終了コード 1。
set -u
unset CDPATH
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
NAME="deploy-test"
RUN_PATH="/opt/homebrew/bin:/usr/bin:/bin"   # deploy.sh に渡す PATH
REAL_HOME="${HOME:-}"
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)" || exit 1
SUT="${1:-$HERE/../../deploy.sh}"
total=0; failed=0

abort() {  # abort <理由> → 試験を回せない。FAIL と RESULT を出して止める
  printf 'FAIL %s %s\n' "$NAME" "$1"
  printf 'RESULT: FAIL %s (%d 件中 FAIL %d)\n' "$NAME" "$((total + 1))" "$((failed + 1))"
  exit 1
}
[ -f "$SUT" ] || abort "試す deploy.sh が無い（${SUT}）。My-Lab で回す"
command -v git >/dev/null 2>&1 || abort "git が入っていない"
REAL_GIT="$(command -v git)"
locale -a 2>/dev/null | grep -qx 'ja_JP.UTF-8' || abort "文字の設定 ja_JP.UTF-8 が無い（SKIP は FAIL と同じ）"
T="$(mktemp -d "${TMPDIR:-/tmp}/deploy-test.XXXXXX")" || abort "一時ディレクトリを作れない"
trap 'rm -rf "$T"' EXIT
T="$(cd -- "$T" && pwd -P)" || abort "一時ディレクトリに入れない"   # /var と /private/var の別名をそろえる
case "$T" in "$REAL_HOME"|/) abort "一時ディレクトリが HOME か / を指す（${T}）" ;; esac
if git -C "$T" rev-parse --is-inside-work-tree >/dev/null 2>&1; then abort "一時ディレクトリ（${T}）が git のリポジトリの中にある。TMPDIR を変えて回す"; fi
export GIT_CEILING_DIRECTORIES="$T"   # 一時ディレクトリより上のリポジトリを、git に探させない

# ---- 部品
L=""; BOX=""; FH=""; OUT=""; RC=0; REASON=""
mklab() {  # mklab <置き場> → 偽の正本。deploy.sh の写しと、写す一式の小さな見本
  local d="$1"
  mkdir -p "$d/skills/s1/scripts" "$d/skills/s1/__pycache__" "$d/.company" "$d/tools" "$d/samples/app" "$d/router" || return 1
  printf '# s1\n' > "$d/skills/s1/SKILL.md"
  printf 'echo s1\n' > "$d/skills/s1/scripts/run.sh"
  printf 'x\n' > "$d/skills/s1/__pycache__/a.pyc"
  printf '# 全社\n' > "$d/.company/CLAUDE.md"
  printf 'echo t\n' > "$d/tools/t.sh"
  printf 'a\n' > "$d/samples/app/README.md"
  printf '# 貼る本文\n' > "$d/router/cursor-user-rule.md"
  printf '# 接続\n' > "$d/router/claude-code.md"
  cp "$HERE/../project-verify.sh" "$d/tools/project-verify.sh"   # deploy.sh が写した直後に --baseline で呼ぶ本物
  cp "$SUT" "$d/deploy.sh"
}
# dep_in <作業ディレクトリ> <足す環境の 1 語（空なら無し）> <deploy.sh> <引数...> → OUT と RC。環境は空にし、HOME と PATH と LANG だけを渡す
dep_in() {
  local cwd="$1" extra="$2" script="$3"; shift 3
  OUT="$(cd -- "$cwd" && env -i HOME="$FH" PATH="$RUN_PATH" LANG="$L" GIT_CEILING_DIRECTORIES="$T" ${extra:+"$extra"} /bin/bash "$script" "$@" 2>&1)"; RC=$?
}
dep() { dep_in "$BOX" "" "$BOX/lab/deploy.sh" "$@"; }   # dep <引数...> → 場面の偽の正本の deploy.sh を回す
g() { HOME="$FH" git "$@" >/dev/null 2>&1; }             # 足場を作る git。出力は捨てる
need() {  # need <理由> <コマンド...> → コマンドが失敗したら、理由を残して 1 を返す
  local why="$1"; shift
  if "$@"; then return 0; fi
  REASON="$why"; return 1
}
failed_line() { printf '%s\n' "$OUT" | grep -q '^FAIL deploy'; }
no_failed_line() { ! failed_line; }
fail_says() { printf '%s\n' "$OUT" | grep '^FAIL deploy' | grep -qF -- "$1"; }
said() { printf '%s\n' "$OUT" | grep -qF -- "$1"; }
first_fail() {  # 理由に添える 1 行。FAIL の行が無ければ最後の行
  local l; l="$(printf '%s\n' "$OUT" | grep -m1 '^FAIL')"
  [ -n "$l" ] || l="$(printf '%s\n' "$OUT" | tail -1)"
  printf '%s' "$l"
}
ignored() { HOME="$FH" git -C "$1" check-ignore -q "$2"; }   # ignored <リポジトリ> <パス> → git から外れていれば 0
not_ignored() {  # not_ignored <リポジトリ> <パス> → 外れていなければ 0（git の失敗は 0 にしない）
  local rc; HOME="$FH" git -C "$1" check-ignore -q "$2"; rc=$?; [ "$rc" -eq 1 ]
}
no_untracked_tmp() { ! HOME="$FH" git -C "$1" status --porcelain -uall 2>/dev/null | grep -q '^?? tmp/'; }
count() { local n; n="$(LC_ALL=C grep -cxF -- "$1" "$2" 2>/dev/null)"; printf '%s' "${n:-0}"; }   # count <行> <ファイル> → 同じ行の数
sum() { cksum < "$1" 2>/dev/null || echo "無い"; }
nfiles() { find "$1" -type f 2>/dev/null | wc -l | tr -d ' '; }
absent() { [ ! -e "$1" ] && [ ! -L "$1" ]; }
not_grep() { ! grep -q -- "$1" "$2"; }

# ---- 場面: 消す前・作る前に止める（locale-5、deploy-2）
case_tmp_link_to_lab() {  # tmp が正本へのリンク → 正本の skills/ を消さずに止まる
  local P="$BOX/proj" n ex
  mkdir -p "$P" && g init -q "$P" && ln -s "$BOX/lab" "$P/tmp" || return 1
  n="$(nfiles "$BOX/lab")"; ex="$(sum "$P/.git/info/exclude")"
  dep "$P"
  need "正本の skills/ が消えた（rc=${RC}）" [ -f "$BOX/lab/skills/s1/SKILL.md" ] || return 1
  need "正本のファイルの数が ${n} から $(nfiles "$BOX/lab") に変わった" [ "$(nfiles "$BOX/lab")" = "$n" ] || return 1
  need "止まるのに exclude を変えた" [ "$(sum "$P/.git/info/exclude")" = "$ex" ] || return 1
  need "rc=${RC}（1 のはず）" [ "$RC" -eq 1 ] || return 1
  need "FAIL の行に「リンク」が無い: $(first_fail)" fail_says 'リンク' || return 1
}
case_tmp_link_shared() {  # tmp がプロジェクトの外の共用の置き場へのリンク → リンク先を消さずに止まる
  local P="$BOX/proj" S="$BOX/shared"
  mkdir -p "$P" "$S/tools" "$S/samples" && g init -q "$P" || return 1
  printf 'x\n' > "$S/tools/keep.sh"; printf 'y\n' > "$S/samples/keep.csv"; ln -s "$S" "$P/tmp"
  dep "$P"
  need "リンク先の tools/keep.sh が消えた（rc=${RC}）" [ -f "$S/tools/keep.sh" ] || return 1
  need "リンク先の samples/keep.csv が消えた（rc=${RC}）" [ -f "$S/samples/keep.csv" ] || return 1
  need "リンク先に skills/ を写した" absent "$S/skills" || return 1
  need "リンク先に DEPLOYED.md を書いた" absent "$S/DEPLOYED.md" || return 1
  need "rc=${RC}（1 のはず）" [ "$RC" -eq 1 ] || return 1
  need "FAIL の行が無い" failed_line || return 1
}
case_own_tmp_tools() {  # 印の無い tmp/ に自前の tools と samples がある → 名前を示し、消さずに止まる
  local P="$BOX/proj" ex
  mkdir -p "$P/tmp/tools" "$P/tmp/samples" "$P/tmp/cache" && g init -q "$P" || return 1
  printf 'echo hi\n' > "$P/tmp/tools/seed-db.sh"; printf 'data\n' > "$P/tmp/samples/orders-2026-10.csv"; printf 'c\n' > "$P/tmp/cache/x"
  ex="$(sum "$P/.git/info/exclude")"
  dep "$P"
  need "自前の tmp/tools/seed-db.sh が消えた（rc=${RC}）" [ -f "$P/tmp/tools/seed-db.sh" ] || return 1
  need "自前の tmp/samples/orders-2026-10.csv が消えた（rc=${RC}）" [ -f "$P/tmp/samples/orders-2026-10.csv" ] || return 1
  need "止まるのに tmp/skills を写した" absent "$P/tmp/skills" || return 1
  need "止まるのに DEPLOYED.md を書いた" absent "$P/tmp/DEPLOYED.md" || return 1
  need "止まるのに exclude を変えた" [ "$(sum "$P/.git/info/exclude")" = "$ex" ] || return 1
  need "rc=${RC}（1 のはず）" [ "$RC" -eq 1 ] || return 1
  need "FAIL の行に tmp/tools の名前が無い: $(first_fail)" fail_says 'tmp/tools' || return 1
  need "FAIL の行に tmp/samples の名前が無い: $(first_fail)" fail_says 'tmp/samples' || return 1
}
case_tmp_is_lab() {  # 写す先の tmp が正本そのもの（印の DEPLOYED.md もある）→ 正本を消さずに止まる
  local P="$BOX/proj" n
  mkdir -p "$P" && g init -q "$P" && mklab "$P/tmp" || return 1
  printf '# 前の写し\n' > "$P/tmp/DEPLOYED.md"
  n="$(nfiles "$P/tmp")"
  dep_in "$BOX" "" "$P/tmp/deploy.sh" "$P"
  need "正本の skills/ が消えた（rc=${RC}）" [ -f "$P/tmp/skills/s1/SKILL.md" ] || return 1
  need "正本のファイルの数が ${n} から $(nfiles "$P/tmp") に変わった" [ "$(nfiles "$P/tmp")" = "$n" ] || return 1
  need "rc=${RC}（1 のはず）" [ "$RC" -eq 1 ] || return 1
  need "FAIL の行が無い" failed_line || return 1
}
case_dest_inside_lab() {  # 正本自身と、正本の中のフォルダには写さない
  mkdir -p "$BOX/lab/work/proj" || return 1
  dep "$BOX/lab"
  need "正本自身で rc=${RC}（1 のはず）" [ "$RC" -eq 1 ] || return 1
  dep "$BOX/lab/work/proj"
  need "正本の中に tmp/ を作った（rc=${RC}）" absent "$BOX/lab/work/proj/tmp" || return 1
  need "正本の中で rc=${RC}（1 のはず）" [ "$RC" -eq 1 ] || return 1
  need "正本の中で FAIL の行が無い" failed_line || return 1
}
case_inside_git_dir() {  # .git の中を渡す → 写さずに止まる
  local P="$BOX/proj" ex
  mkdir -p "$P" && g init -q "$P" || return 1
  ex="$(sum "$P/.git/info/exclude")"
  dep "$P/.git"
  need ".git の中に tmp/ を作った（rc=${RC}）" absent "$P/.git/tmp" || return 1
  need "止まるのに exclude を変えた" [ "$(sum "$P/.git/info/exclude")" = "$ex" ] || return 1
  need "rc=${RC}（1 のはず）" [ "$RC" -eq 1 ] || return 1
  need "FAIL の行が無い" failed_line || return 1
}
case_redeploy() {  # 印があれば新しい版で置き換え、tmp/ の他の中身は残す（止める確かめが、ふつうの更新を止めない）
  local P="$BOX/proj"
  mkdir -p "$P/tmp/cache" && g init -q "$P" || return 1
  printf 'c\n' > "$P/tmp/cache/x"
  dep "$P"
  need "1 回目 rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  printf 'old\n' > "$P/tmp/skills/stale.txt"
  dep "$P"
  need "2 回目 rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "前の版の tmp/skills/stale.txt が残った" absent "$P/tmp/skills/stale.txt" || return 1
  need "tmp/skills/s1/SKILL.md が無い" [ -f "$P/tmp/skills/s1/SKILL.md" ] || return 1
  need "tmp/ の他の中身（tmp/cache/x）が消えた" [ -f "$P/tmp/cache/x" ] || return 1
  need "__pycache__ まで写った" [ -z "$(find "$P/tmp" -name __pycache__)" ] || return 1
}

# ---- 場面: exclude の書き先と書く形（locale-4、deploy-3、locale-6、deploy-6）
case_exclude_no_newline() {  # exclude の最後の行に改行が無い → その行を壊さず、新しい行として足す
  local P="$BOX/proj" X
  mkdir -p "$P" && g init -q "$P" || return 1
  X="$P/.git/info/exclude"
  printf '*.log' > "$X"; printf 's\n' > "$P/debug.log"
  dep "$P"
  need "rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "*.log の行が壊れた（exclude: $(tr '\n' '|' < "$X")）" [ "$(count '*.log' "$X")" -eq 1 ] || return 1
  need "/tmp/ の行が無い（exclude: $(tr '\n' '|' < "$X")）" [ "$(count '/tmp/' "$X")" -eq 1 ] || return 1
  need "隠れていた debug.log が git に見える" ignored "$P" debug.log || return 1
  need "写した tmp/ が git から外れない" ignored "$P" tmp/DEPLOYED.md || return 1
}
case_anchored_line() {  # 足す行は先頭が / の /tmp/。下の階層の tmp/ は隠さない。2 回回しても重ならない
  local P="$BOX/proj" X
  mkdir -p "$P/test/fixtures/tmp" && g init -q "$P" || return 1
  X="$P/.git/info/exclude"
  : > "$X"; printf 'c\n' > "$P/test/fixtures/tmp/case1.txt"
  dep "$P"
  need "1 回目 rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "空の exclude が /tmp/ の 1 行にならない（exclude: $(tr '\n' '|' < "$X")）" [ "$(cat "$X")" = "/tmp/" ] || return 1
  need "下の階層の test/fixtures/tmp/case1.txt まで隠れた" not_ignored "$P" test/fixtures/tmp/case1.txt || return 1
  need "写した tmp/ が git から外れない" ignored "$P" tmp/DEPLOYED.md || return 1
  dep "$P"
  need "2 回目 rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "2 回目で /tmp/ の行が重なった" [ "$(count '/tmp/' "$X")" -eq 1 ] || return 1
}
case_old_line_kept() {  # 前の版が書いた先頭に / の無い tmp/ の行は消さずに残し、/tmp/ を足して知らせる
  local P="$BOX/proj" X
  mkdir -p "$P" && g init -q "$P" || return 1
  X="$P/.git/info/exclude"
  printf 'tmp/\n' >> "$X"
  dep "$P"
  need "rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "前の版の tmp/ の行が消えた" [ "$(count 'tmp/' "$X")" -eq 1 ] || return 1
  need "/tmp/ の行が無い" [ "$(count '/tmp/' "$X")" -eq 1 ] || return 1
  need "前の版の行が残ることを知らせない" said '先頭に / の無い tmp/ の行' || return 1
}
case_worktree() {  # git worktree → git が読む共通の .git/info/exclude に書く
  local M="$BOX/main" W="$BOX/wt"
  mkdir -p "$M" && g init -q "$M" || return 1
  need "git worktree add --orphan が使えない（git 2.42 以上が要る）" g -C "$M" worktree add -q --orphan -b wt "$W" || return 1
  dep "$W"
  need "rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "共通の exclude に /tmp/ が無い" [ "$(count '/tmp/' "$M/.git/info/exclude")" -eq 1 ] || return 1
  need "worktree の tmp/ が git から外れない" ignored "$W" tmp/DEPLOYED.md || return 1
  need "worktree の git status に tmp/ が出る" no_untracked_tmp "$W" || return 1
  need "DEPLOYED.md に共通の exclude の場所が無い" grep -qF "$M/.git/info/exclude" "$W/tmp/DEPLOYED.md" || return 1
}
case_repo_subfolder() {  # リポジトリの下のフォルダ → /<フォルダ>/tmp/ を書き、別の階層の tmp/ は見えたまま
  local M="$BOX/mono" X
  mkdir -p "$M/packages/web" "$M/scripts/tmp" && g init -q "$M" || return 1
  X="$M/.git/info/exclude"
  printf 's\n' > "$M/scripts/tmp/fixture.txt"
  dep "$M/packages/web"
  need "rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "exclude に /packages/web/tmp/ が無い（exclude の最後: $(tail -1 "$X")）" [ "$(count '/packages/web/tmp/' "$X")" -eq 1 ] || return 1
  need "写した packages/web/tmp/ が git から外れない" ignored "$M" packages/web/tmp/DEPLOYED.md || return 1
  need "別の階層の scripts/tmp/fixture.txt まで隠れた" not_ignored "$M" scripts/tmp/fixture.txt || return 1
}
case_special_name() {  # フォルダの名前に空白・日本語・[ ] * ? がある → その場所の tmp/ だけを外す
  local M="$BOX/repo" D
  D="$M/My Project 日本語/a[1]*?"
  mkdir -p "$D" "$M/My Project 日本語/a1x/tmp" && g init -q "$M" || return 1
  printf 's\n' > "$M/My Project 日本語/a1x/tmp/f.txt"
  dep "$D"
  need "rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "写した tmp/ が git から外れない" ignored "$D" tmp/DEPLOYED.md || return 1
  need "名前の似た別のフォルダの tmp/ まで隠れた" not_ignored "$M" "My Project 日本語/a1x/tmp/f.txt" || return 1
}
case_old_git_fallback() {  # --path-format を知らない古い git でも、git が読む exclude に書く
  local M="$BOX/mono" B="$BOX/bin"
  local RUN_PATH="$BOX/bin:$RUN_PATH"   # dep_in はこの PATH を使う
  mkdir -p "$M/packages/web" "$B" && g init -q "$M" || return 1
  cat > "$B/git" <<EOF
#!/bin/bash
# 古い git の形をまねる: --path-format=absolute は字のまま 1 行目に出し、残りを本物の git に渡す
args=()
for a in "\$@"; do
  if [ "\$a" = "--path-format=absolute" ]; then echo "\$a"; echo x >> "$B/hit"; else args+=("\$a"); fi
done
exec "$REAL_GIT" "\${args[@]}"
EOF
  chmod +x "$B/git"
  dep "$M/packages/web"
  need "rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "古い git の形を通っていない（--path-format を使わない）" [ -s "$B/hit" ] || return 1
  need "exclude に /packages/web/tmp/ が無い" [ "$(count '/packages/web/tmp/' "$M/.git/info/exclude")" -eq 1 ] || return 1
  need "写した packages/web/tmp/ が git から外れない" ignored "$M" packages/web/tmp/DEPLOYED.md || return 1
}

# ---- 場面: 外れたかは git に聞く。DEPLOYED.md にはしたことを書く（locale-7、deploy-7）
case_unrelated_tmp_paths() {  # パスに tmp/ を含む別の変更（src/tmp/ の直し、.tmp/、mytmp/）があっても FAIL にしない
  local P="$BOX/proj"
  mkdir -p "$P/src/tmp" "$P/.tmp" "$P/mytmp" && g init -q "$P" || return 1
  printf 'a\n' > "$P/src/tmp/cache.json"; g -C "$P" add src/tmp/cache.json; printf 'b\n' >> "$P/src/tmp/cache.json"
  printf 'x\n' > "$P/.tmp/build.log"; printf 'y\n' > "$P/mytmp/note.txt"
  dep "$P"
  need "rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "FAIL の行が出た: $(first_fail)" no_failed_line || return 1
}
case_not_excluded_stops() {  # 未追跡を表示しない設定で、.gitignore が tmp/ を戻す → 外れていないので、写さずに止まる
  local P="$BOX/proj"
  mkdir -p "$P" && g init -q "$P" && g -C "$P" config status.showUntrackedFiles no || return 1
  printf '!/tmp/\n' > "$P/.gitignore"
  dep "$P"
  need "外れていないのに rc=${RC}（1 のはず）" [ "$RC" -eq 1 ] || return 1
  need "FAIL の行が無い" failed_line || return 1
  need "外れていないのに tmp/skills を写した" absent "$P/tmp/skills" || return 1
}
case_not_git() {  # git でない置き場 → exclude に書かず、DEPLOYED.md に git init のあとで回し直すと書く
  local P="$BOX/proj"
  mkdir -p "$P" || return 1
  dep "$P"
  need "rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "DEPLOYED.md の git の行に git init の案内が無い" grep -q '^| git |.*git init' "$P/tmp/DEPLOYED.md" || return 1
  need "git でないのに、DEPLOYED.md が exclude に足したと書く" not_grep '^| git |.*足した' "$P/tmp/DEPLOYED.md" || return 1
}
case_deployed_row() {  # git の置き場 → DEPLOYED.md の git の行に、足した行と exclude の場所をそのまま書く
  local P="$BOX/proj" X
  mkdir -p "$P" && g init -q "$P" || return 1
  X="$P/.git/info/exclude"
  dep "$P"
  need "rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "DEPLOYED.md の git の行に「/tmp/ を ${X} に足した」が無い" grep -qF "| git | \`/tmp/\` を \`${X}\` に足した" "$P/tmp/DEPLOYED.md" || return 1
  dep "$P"
  need "2 回目 rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "2 回目の DEPLOYED.md の git の行に「前からある」が無い" grep -qF "| git | \`/tmp/\` は \`${X}\` に前からある" "$P/tmp/DEPLOYED.md" || return 1
}

# ---- 場面: 先頭が - のパスと CDPATH（locale-8 の deploy.sh の分）
case_leading_dash() {  # 先頭が - の相対パスでも写す
  mkdir -p "$BOX/-proj" && g init -q "$BOX/-proj" || return 1
  dep_in "$BOX" "" "$BOX/lab/deploy.sh" -proj
  need "rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "-proj/tmp/DEPLOYED.md が無い" [ -f "$BOX/-proj/tmp/DEPLOYED.md" ] || return 1
}
case_cdpath() {  # CDPATH があっても、渡した場所に写す。正本の場所も CDPATH に引かれない
  local H="$BOX/here" O="$BOX/there"
  mkdir -p "$H/proj" "$O/proj" "$O/lab" && g init -q "$H/proj" && g init -q "$O/proj" && mv "$BOX/lab" "$H/lab" || return 1
  dep_in "$H" "CDPATH=$O" lab/deploy.sh proj
  need "rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "渡した here/proj に写っていない" [ -f "$H/proj/tmp/DEPLOYED.md" ] || return 1
  need "CDPATH の先の there/proj に写した" absent "$O/proj/tmp" || return 1
  need "CDPATH の先に別のフォルダができた" [ "$(find "$O" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')" -eq 2 ] || return 1
}
case_home_untouched() {  # HOME の下に何も書かない
  local P="$BOX/proj"
  mkdir -p "$P" && g init -q "$P" || return 1
  dep "$P"
  need "rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "HOME の下に何か書いた" [ -z "$(find "$FH" -mindepth 1 -print)" ] || return 1
}

# ---- 場面: 写した時点の印（2026-11-11 の引き戻しの輪の直し）
case_baseline() {  # 写した直後に印（tmp/.verify/last-pass）と一覧を置く。前からある tmp/ の文書は、写した先の検証で範囲外になる
  local P="$BOX/proj" V
  mkdir -p "$P/tmp/flow/old" && g init -q "$P" || return 1
  printf '# Old\n\nThis note was written before the deploy.\n' > "$P/tmp/flow/old/note.md"
  dep "$P"
  V="$P/tmp/.verify"
  need "rc=${RC}: $(first_fail)" [ "$RC" -eq 0 ] || return 1
  need "印 tmp/.verify/last-pass が無い" [ -f "$V/last-pass" ] || return 1
  need "一覧 tmp/.verify/last-pass.list が無い" [ -f "$V/last-pass.list" ] || return 1
  need "一覧に tmp/DEPLOYED.md が無い" grep -qxF './tmp/DEPLOYED.md' "$V/last-pass.list" || return 1
  need "一覧に前からある文書が無い" grep -qxF './tmp/flow/old/note.md' "$V/last-pass.list" || return 1
  need "印より新しいファイルがある" [ -z "$(find "$P" -newer "$V/last-pass" -type f -not -path '*/.git/*' -not -path '*/.verify/*' | head -1)" ] || return 1
  need "前からある文書が範囲外になると知らせない: $(printf '%s\n' "$OUT" | tail -1)" said '範囲外' || return 1
}

# ---- 実行
CASES="tmp_link_to_lab tmp_link_shared tmp_is_lab own_tmp_tools dest_inside_lab inside_git_dir redeploy
exclude_no_newline anchored_line old_line_kept worktree repo_subfolder special_name old_git_fallback
unrelated_tmp_paths not_excluded_stops not_git deployed_row leading_dash cdpath home_untouched baseline"
for L in C ja_JP.UTF-8; do
  for c in $CASES; do
    total=$((total + 1))
    BOX="$T/$L/$c"; FH="$BOX/home"; OUT=""; RC=0; REASON=""
    if mkdir -p "$BOX" "$FH" && mklab "$BOX/lab" && "case_$c"; then
      printf 'PASS %s [%s]\n' "$c" "$L"
    else
      failed=$((failed + 1))
      printf 'FAIL %s [%s] %s\n' "$c" "$L" "${REASON:-準備に失敗した}"
    fi
  done
done
if [ "$failed" -eq 0 ]; then printf 'RESULT: PASS %s (%d 件)\n' "$NAME" "$total"; exit 0; fi
printf 'RESULT: FAIL %s (%d 件中 FAIL %d)\n' "$NAME" "$total" "$failed"
exit 1
