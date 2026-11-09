#!/usr/bin/env bash
# install.sh [--dry-run] [--remove-old-links] — この Mac に 1 回だけ行う接続。
#   1) ~/.claude/settings.json と ~/.cursor/hooks.json に、この正本の hooks（--global）を登録する。
#      旧 cradle の登録（cradle-guard-*.sh）と、自分の古い登録（置き場は問わない）は外す。他の設定はそのまま残す。
#      2 つの中身を先に作って確かめる。どちらかが読めなければ、何も書かずに止まる。空か空白だけのファイルは {} とみなす。
#      書き換える前に <ファイル>.bak.<日時>.<番号> を作る。中身が変わらなければ、書き換えも退避もしない。
#      登録する命令のパスは、空白や記号があるときだけ引用符で囲む。~/.cursor が無ければ Cursor の登録は飛ばす（作らない）。
#   2) --remove-old-links: ~/.claude/skills/ と ~/.claude/hooks/、~/.cursor/hooks/ の、旧 cradle-skills の skills/ と hooks/ を指すリンクを外す（実体は消さない）。
#   常時ルール（~/.claude/CLAUDE.md、Cursor の User Rules、~/.cursor/rules）には書き込まない。本文は router/ にあり、社長が貼る。
#   --dry-run は、書き込む内容と外すリンクを表示するだけで何も変えない。
set -eu
unset CDPATH
LAB="$(cd -- "$(dirname -- "$0")" && pwd -P)"
H="$LAB/hooks"
DRY=0; RM_LINKS=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --remove-old-links) RM_LINKS=1 ;;
    *) echo "使い方: install.sh [--dry-run] [--remove-old-links]"; exit 2 ;;
  esac
done
command -v jq >/dev/null 2>&1 || { echo "FAIL install: jq が要る（brew install jq）"; exit 1; }
for x in claude-pretooluse claude-postedit claude-stop cursor-before-shell cursor-after-edit cursor-stop; do
  [ -f "$H/$x.sh" ] || { echo "FAIL install: ${H}/${x}.sh が無い。何も書き換えていない（リンク経由なら、正本の install.sh を直に回す）"; exit 1; }
done
CL="$HOME/.claude/settings.json"
CU="$HOME/.cursor/hooks.json"
STAMP="$(date +%Y%m%d-%H%M%S)"

# jq の共通の部品。q は空白や記号のあるパスだけを引用符で囲む（記号の無いパスは、今までの登録と同じ字面になる）。
# top は空か空白だけの入力を {} とみなし、1 つの object でなければ止める。
# shellcheck disable=SC2016  # $h と $n は jq の変数
JQ_LIB='
  def q: if test("[^A-Za-z0-9_./@%+=:,-]") then @sh else . end;
  def cmd($n): "bash " + (($h + "/" + $n) | q) + " --global";
  def top: if length == 0 then {} elif length == 1 and (.[0] | type) == "object" then .[0] else error("最上位が 1 つの object でない") end;'

src() {  # src <ファイル> → jq に読ませるファイル。無ければ /dev/null（{} とみなす）。ふつうのファイルでなければ失敗
  if [ -f "$1" ]; then printf '%s\n' "$1"
  elif [ -e "$1" ] || [ -L "$1" ]; then echo "install: ${1} はふつうのファイルでない" >&2; return 1
  else printf '%s\n' /dev/null; fi
}

# 自分の登録は、置き場ではなく接続口の名前で見分ける（移した・改名した・別の clone の古い登録も外す）。[\x27"] は、パスを囲む単一か二重の引用符
new_claude() {  # 既存の設定を読み、旧 cradle と自分の古い登録を外し、自分の登録を足す
  local s; s="$(src "$CL")" || return 1
  jq -s --arg h "$H" "$JQ_LIB"'
    def mine($c): ($c | test("cradle-guard")) or ($c | test("/hooks/claude-(pretooluse|postedit|stop)\\.sh[\\x27\"]?\\s+--global$"));
    def clean(ev): ((.hooks // {})[ev] // [])
      | map(.hooks |= map(select(mine(.command // "") | not)) | select((.hooks | length) > 0));
    top
    | .hooks = (.hooks // {})
    | .hooks.PreToolUse  = clean("PreToolUse")  + [{matcher: "Bash", hooks: [{type: "command", command: cmd("claude-pretooluse.sh"), timeout: 20}]}]
    | .hooks.PostToolUse = clean("PostToolUse") + [{matcher: "Edit|Write|MultiEdit|NotebookEdit", hooks: [{type: "command", command: cmd("claude-postedit.sh"), timeout: 120}]}]
    | .hooks.Stop        = clean("Stop")        + [{hooks: [{type: "command", command: cmd("claude-stop.sh"), timeout: 600}]}]' < "$s"
}

new_cursor() {
  local s; s="$(src "$CU")" || return 1
  jq -s --arg h "$H" "$JQ_LIB"'
    def mine($c): ($c | test("cradle-guard")) or ($c | test("/hooks/cursor-(before-shell|after-edit|stop)\\.sh[\\x27\"]?\\s+--global$"));
    def clean(ev): ((.hooks // {})[ev] // []) | map(select(mine(.command // "") | not));
    top
    | .version = 1 | .hooks = (.hooks // {})
    | .hooks.beforeShellExecution = clean("beforeShellExecution") + [{command: cmd("cursor-before-shell.sh"), failClosed: true, timeout: 20}]
    | .hooks.afterFileEdit        = clean("afterFileEdit")        + [{command: cmd("cursor-after-edit.sh"), timeout: 120}]
    | .hooks.stop                 = clean("stop")                 + [{command: cmd("cursor-stop.sh"), timeout: 600, loop_limit: 3}]' < "$s"
}

valid() {  # valid <中身> → 1 つの JSON の object なら 0
  printf '%s\n' "$1" | jq -e -s 'length == 1 and (.[0] | type == "object")' >/dev/null 2>&1
}

fail_read() {  # fail_read <ファイル> → FAIL を出して止まる
  echo "FAIL install: ${1} を読めない（JSON の object でないか、形が想定と違う）。どのファイルも書き換えていない"
  exit 1
}

write() {  # write <ファイル> <中身>。中身が今と同じなら書かない。元のファイルがあれば、書く前に退避する
  local f="$1" body="$2" bak
  if [ -f "$f" ] && printf '%s\n' "$body" | cmp -s - "$f"; then
    if [ "$DRY" = 1 ]; then
      printf -- '--- %s（書き込まない。今の中身と同じ）\n%s\n' "$f" "$body"
    else
      echo "install: ${f} は今の中身と同じ。書き換えも退避もしていない"
    fi
    return 0
  fi
  if [ "$DRY" = 1 ]; then
    printf -- '--- %s（書き込まない）\n%s\n' "$f" "$body"
    return 0
  fi
  mkdir -p "$(dirname "$f")"
  if [ -f "$f" ]; then
    bak="$f.bak.${STAMP}.$$"
    cp "$f" "$bak"
    printf '%s\n' "$body" > "$f"
    echo "install: ${f} を書いた。退避: ${bak}"
  else
    printf '%s\n' "$body" > "$f"
    echo "install: ${f} を書いた。退避: なし（元のファイルが無かった）"
  fi
}

# 2 つの中身を先に作り、両方を確かめてから書く。代入の形にするのは、jq の失敗を set -e より先に拾うため
CURSOR=1; [ -d "$HOME/.cursor" ] || CURSOR=0
if ! BODY_CL="$(new_claude)" || ! valid "$BODY_CL"; then fail_read "$CL"; fi
BODY_CU=""
if [ "$CURSOR" = 1 ]; then
  if ! BODY_CU="$(new_cursor)" || ! valid "$BODY_CU"; then fail_read "$CU"; fi
fi
write "$CL" "$BODY_CL"
if [ "$CURSOR" = 1 ]; then
  write "$CU" "$BODY_CU"
else
  echo "install: ${HOME}/.cursor が無い。Cursor の登録は飛ばした（Cursor を入れたら、もう一度回す）"
fi

# 旧リンク: 旧 cradle-skills の skills/ と hooks/ を指すものだけ。. で始まる名前も見る
NL=0; NG=0; LINKS=(); TARGETS=()
for d in "$HOME/.claude/skills" "$HOME/.claude/hooks" "$HOME/.cursor/hooks"; do
  if [ -L "$d" ]; then
    echo "WARN install: ${d} そのものがリンク（-> $(readlink "$d")）。中は調べず、外さない"
    continue
  fi
  [ -d "$d" ] || continue
  for l in "$d"/* "$d"/.[!.]* "$d"/..?*; do
    [ -L "$l" ] || continue
    t="$(readlink "$l")" || continue
    case "$t" in
      */cradle-skills/skills/*|*/cradle-skills/hooks/*|*/cradle-skills/skills|*/cradle-skills/hooks)
        LINKS+=("$l"); TARGETS+=("$t"); NL=$((NL + 1)) ;;
    esac
  done
done
if [ "$NL" -gt 0 ]; then
  i=0
  if [ "$DRY" = 1 ]; then
    while [ "$i" -lt "$NL" ]; do echo "install: 外す予定: ${LINKS[i]} -> ${TARGETS[i]}"; i=$((i + 1)); done
    if [ "$RM_LINKS" = 1 ]; then
      echo "install: --dry-run なので、旧 cradle-skills を指すリンク ${NL} 本は外していない"
    else
      echo "install: 旧 cradle-skills を指すリンクが ${NL} 本ある。外すときは ./install.sh --remove-old-links"
    fi
  elif [ "$RM_LINKS" = 1 ]; then
    OK=0
    while [ "$i" -lt "$NL" ]; do
      if rm -f -- "${LINKS[i]}"; then
        OK=$((OK + 1)); echo "install: 外した: ${LINKS[i]} -> ${TARGETS[i]}"
      else
        NG=$((NG + 1)); echo "FAIL install: 外せない: ${LINKS[i]} -> ${TARGETS[i]}"
      fi
      i=$((i + 1))
    done
    if [ "$NG" -eq 0 ]; then
      echo "install: 旧 cradle-skills を指すリンク ${NL} 本を外した（実体は消していない）"
    else
      echo "FAIL install: 旧 cradle-skills を指すリンク ${NL} 本のうち、${OK} 本を外し、${NG} 本を外せなかった（実体は消していない）"
    fi
  else
    echo "install: 旧 cradle-skills を指すリンクが ${NL} 本ある。外すときは ./install.sh --remove-old-links（一覧は --dry-run で出る）"
  fi
elif [ "$RM_LINKS" = 1 ]; then
  echo "install: 外す旧リンクは無い"
fi

echo "install: 常時ルールには書き込まない。Cursor の User Rules には router/cursor-user-rule.md、~/.claude/CLAUDE.md には router/claude-code.md の本文を社長が貼る"
echo "install: 確認は bash $LAB/hooks/selftest.sh と、Claude Code の /hooks"
[ "$NG" -eq 0 ] || exit 1
