#!/usr/bin/env bash
# deploy.sh <プロジェクトのパス> — この一式（skills/・.company/・tools/・samples/）をそのプロジェクトの tmp/ に写し、git に入らないようにする。
# 社長が手でコピーするのと中身は同じ。加えて git が読む exclude に、写した tmp/ だけを外す行を足す（直下なら /tmp/）。
# worktree では、git が読む共通の .git/info/exclude に足す。tmp/DEPLOYED.md には、日時と正本の場所と常時ルールの貼り先と、git でしたことを書く。
# samples/ は、写した skills の参照と自己試験（見本を使う検査）が写した先でも通るように写す。__pycache__ は写さない。
# 常時ルール（~/.claude/CLAUDE.md、Cursor の User Rules）には書き込まない。貼る本文は tmp/cursor-user-rule.md、Claude Code の接続の説明は tmp/claude-code.md に写すだけ。
# 使い方: ./deploy.sh /path/to/project   前に写した印（tmp/DEPLOYED.md）があれば、tmp/skills などを新しい版で置き換える。tmp/ の他の中身は触らない。
# 何も変えずに止める: 写す先が正本（My-Lab）かその中、tmp がリンクか正本そのもの、.git の中、
#   印が無いのに tmp/skills・tmp/.company・tmp/tools・tmp/samples のどれかがある、tmp/ の下に git が追跡中のファイルがある。
# exclude に足しても tmp/ が git から外れないときは、その 1 行だけを足して、写さずに止める。
set -eu
unset CDPATH  # CDPATH があると、cd が別の場所へ移り、移った先を出力に混ぜる
# パスは /bin/pwd -P でそろえる。bash 3.2 の組み込みの pwd -P は、大文字小文字の違う綴り（APFS では同じ場所）をそのまま返し、正本かどうかの比較が外れる
phys_pwd() { /bin/pwd -P 2>/dev/null || pwd -P; }
LAB="$(cd -- "$(dirname -- "$0")" && phys_pwd)"
DEST="${1:-}"
[ -n "$DEST" ] || { echo "使い方: deploy.sh <プロジェクトのパス>"; exit 2; }
[ -d "$DEST" ] || { echo "FAIL deploy: ${DEST} が無い"; exit 1; }
DEST="$(cd -- "$DEST" && phys_pwd)"

# 消す・作る前に、止める場面を全部確かめる。ここで止まるときは、何も変えていない
[ "$DEST" != "$LAB" ] || { echo "FAIL deploy: 正本（My-Lab）自身には写さない。root 直下のものをそのまま使う"; exit 1; }
case "$DEST/" in "$LAB"/*) echo "FAIL deploy: ${DEST} は正本（My-Lab）の中にある。正本の中には写さない"; exit 1 ;; esac
for d in skills .company tools samples; do
  [ -d "$LAB/$d" ] || { echo "FAIL deploy: 正本に $d/ が無い"; exit 1; }
done
if [ -L "$DEST/tmp" ]; then
  echo "FAIL deploy: ${DEST}/tmp はリンク。写すとリンク先の中身を消しうるので、写さない。ふつうのフォルダにしてから回す"
  exit 1
fi
if [ -e "$DEST/tmp" ] && [ ! -d "$DEST/tmp" ]; then echo "FAIL deploy: ${DEST}/tmp がフォルダでない。写さない"; exit 1; fi
[ "$DEST/tmp" != "$LAB" ] || { echo "FAIL deploy: ${DEST}/tmp が正本（My-Lab）そのもの。写すと正本を消すので、写さない"; exit 1; }
if [ ! -f "$DEST/tmp/DEPLOYED.md" ]; then
  FOUND=""
  for d in skills .company tools samples; do
    if [ -e "$DEST/tmp/$d" ] || [ -L "$DEST/tmp/$d" ]; then FOUND="${FOUND:+${FOUND}・}tmp/${d}"; fi
  done
  if [ -n "$FOUND" ]; then
    echo "FAIL deploy: ${DEST} に ${FOUND} がある。前に写した印（tmp/DEPLOYED.md）が無いので、消さずに止める。別の場所へ移してから、もう一度回す"
    exit 1
  fi
fi

# git が読む exclude と、写した tmp/ だけを外す行を決める
EXCLUDE=""; LINE=""; ADDED=""
INSIDE="$(git -C "$DEST" rev-parse --is-inside-work-tree 2>/dev/null || true)"
if [ "$INSIDE" = "false" ]; then echo "FAIL deploy: ${DEST} は git の作業ツリーの外（.git の中か、bare のリポジトリ）。プロジェクトのフォルダを渡す"; exit 1; fi
if [ "$INSIDE" = "true" ]; then
  # worktree では、共通の .git/info/exclude が返る（git が読むのはそこだけ）
  EXCLUDE="$(git -C "$DEST" rev-parse --path-format=absolute --git-path info/exclude 2>/dev/null || true)"
  case "$EXCLUDE" in
    /*) ;;
    *) # git 2.31 より前は --path-format を知らず、その字をそのまま出す。相対のパスを写す先から引く
      EXCLUDE="$(git -C "$DEST" rev-parse --git-path info/exclude)"
      case "$EXCLUDE" in /*) ;; *) EXCLUDE="$DEST/$EXCLUDE" ;; esac
      ;;
  esac
  # 先頭の / で、写した場所の tmp/ だけに効かせる（/ が無いと、どの階層の tmp/ も隠す）。リポジトリの下のフォルダなら /<そのフォルダ>/tmp/。
  # フォルダの名前の * ? [ \ は gitignore の記号なので、前に \ を付ける
  PREFIX="$(git -C "$DEST" rev-parse --show-prefix)"
  LINE="/$(printf '%s' "$PREFIX" | LC_ALL=C sed 's/[][*?\\]/\\&/g')tmp/"
  mkdir -p "$(dirname -- "$EXCLUDE")"
  if ! LC_ALL=C grep -qxF -- "$LINE" "$EXCLUDE" 2>/dev/null; then
    # 最後の行に改行が無ければ、先に改行を足す。無いまま足すと最後の行に続けて書き、その行の除外を壊す
    if [ -s "$EXCLUDE" ] && [ "$(tail -c 1 "$EXCLUDE" | wc -l | tr -d ' ')" -eq 0 ]; then printf '\n' >> "$EXCLUDE"; fi
    printf '%s\n' "$LINE" >> "$EXCLUDE"
    ADDED=1
  fi
  # 外れたかは git に聞く。git status の字を探すと、関係ない行で落ち、未追跡を表示しない設定では外れていなくても通る
  if ! git -C "$DEST" check-ignore -q tmp/DEPLOYED.md; then
    echo "FAIL deploy: ${EXCLUDE} に ${LINE} の行はあるが、tmp/ が git から外れない（git check-ignore で確かめた）"
    echo "FAIL deploy: .gitignore の「!」で始まる行か、tmp/DEPLOYED.md が commit 済みでないかを確かめる。今回は何も写していない"
    exit 1
  fi
  # 追跡中（commit 済みか add 済み）のファイルには exclude が効かない。写すと次の commit に入るので、止める
  TRACKED="$(git -C "$DEST" ls-files -- tmp 2>/dev/null | head -1)"
  if [ -n "$TRACKED" ]; then
    echo "FAIL deploy: tmp/ の下に git が追跡中のファイルがある（例: ${TRACKED}）。exclude は追跡中のファイルには効かず、写した物が commit に入る"
    echo "FAIL deploy: 追跡を外してから（index から消す）、もう一度回す。今回は何も写していない"
    exit 1
  fi
fi

mkdir -p "$DEST/tmp"
for d in skills .company tools samples; do
  rm -rf "$DEST/tmp/${d:?}"
  cp -R "$LAB/$d" "$DEST/tmp/$d"
  find "$DEST/tmp/$d" -name '__pycache__' -type d -prune -exec rm -rf {} +
done
# 書く先がリンクでも、リンク先には書かない（リンクを外してから書く）
rm -f "$DEST/tmp/cursor-user-rule.md" "$DEST/tmp/claude-code.md"
cp "$LAB/router/cursor-user-rule.md" "$DEST/tmp/cursor-user-rule.md"
cp "$LAB/router/claude-code.md" "$DEST/tmp/claude-code.md"
find "$DEST/tmp/tools" "$DEST/tmp/skills" "$DEST/tmp/samples" -name '*.sh' -exec chmod +x {} +

if [ -z "$EXCLUDE" ]; then
  GITNOTE="git のリポジトリではないので、exclude には書いていない。git init したら、deploy をもう一度回す"
elif [ -n "$ADDED" ]; then
  GITNOTE="\`${LINE}\` を \`${EXCLUDE}\` に足した。写した tmp/ は commit に入らない（git check-ignore で確かめた）"
else
  GITNOTE="\`${LINE}\` は \`${EXCLUDE}\` に前からある。写した tmp/ は commit に入らない（git check-ignore で確かめた）"
fi

COMMIT="$(git -C "$LAB" rev-parse --short HEAD 2>/dev/null || echo "不明")"
# 写す範囲で、commit と中身が違うファイルの本数。-uall で未追跡のディレクトリを中のファイル 1 本ずつに開く
# （-uall が無いと、未追跡のディレクトリ 1 つが 1 行に数えられ、本数を表さない）
DIRTY="$(git -C "$LAB" status --porcelain -uall -- skills .company tools samples router 2>/dev/null | wc -l | tr -d ' ')"
if [ "$DIRTY" -gt 0 ]; then
  VERSION="commit $COMMIT に未 commit の変更を足した版（commit から足した・直した・消したファイルが $DIRTY 本。git status --porcelain -uall で数えた）。commit の番号だけでは中身を特定できない"
else
  VERSION="commit $COMMIT"
fi
NOW="$(date '+%Y-%m-%d %H:%M')"
rm -f "$DEST/tmp/DEPLOYED.md"
cat > "$DEST/tmp/DEPLOYED.md" <<EOF
# この tmp/ の写しについて

正本: $LAB

| 項目 | 内容 |
|---|---|
| 写した日時 | $NOW |
| 正本の場所 | \`$LAB\`（${VERSION}） |
| 写したもの | \`tmp/skills/\`、\`tmp/.company/\`、\`tmp/tools/\`、\`tmp/samples/\`、\`tmp/cursor-user-rule.md\`、\`tmp/claude-code.md\` |
| git | ${GITNOTE} |

## 常時ルールの貼り先

常時ルールの本文は 1 つで、\`tmp/cursor-user-rule.md\` の「貼る本文（ここから）」から「貼る本文（ここまで）」までです。社長がツールごとに 1 回貼ります。AI は常時ルールに書き込みません。

| ツール | 貼り先 | 効く範囲 |
|---|---|---|
| Claude Code | \`~/.claude/CLAUDE.md\`（無ければ作る） | 全プロジェクト。接続の全体は \`tmp/claude-code.md\` の 2 節 |
| Cursor | Cursor Settings → Rules → User Rules | 全プロジェクト |

## ファイルの道具で \`tmp/\` が見えないとき

この \`tmp/\` は git の無視の対象です。Cursor の AI は、git が無視するファイルをファイルを探す道具で読めないことがあります。AI は、無いと言う前にターミナルで \`ls -la tmp/.company\` を回し、あれば \`cat\` で読みます。

## 更新と検証

更新するときは、正本で \`./deploy.sh $DEST\` を回すか、同じものを手でコピーし直します。
作業を終える前の検証は \`bash tmp/tools/project-verify.sh --fast\` です。結果は \`tmp/.verify/last-fast.txt\` に残ります。hooks（Mac 全体に 1 回登録）が自動で回します。
作業の終わりの検証は、AI が \`tmp/\` に書いた文書だけを見ます。プロジェクトの lint や試験も回すなら、\`tmp/verify-commands.txt\` に 1 行 1 命令で書きます（例: \`pnpm run lint\`）。
\`tmp/tools/verify-all.sh\` は My-Lab の一式の検証なので、写した先では回さずに止まります。
EOF

echo "deploy: ${DEST}/tmp/ に skills・.company・tools・samples・cursor-user-rule.md・claude-code.md を写した（正本 ${LAB}、${VERSION}）"
if [ -z "$EXCLUDE" ]; then
  echo "deploy: git のリポジトリではないので exclude は書かなかった。git init したら、deploy をもう一度回す"
else
  if [ -n "$ADDED" ]; then echo "deploy: ${EXCLUDE} に ${LINE} を足した"; else echo "deploy: ${EXCLUDE} に ${LINE} は前からある"; fi
  echo "deploy: 写した tmp/ が git から外れたことを、git check-ignore で確かめた"
  if LC_ALL=C grep -qxF 'tmp/' "$EXCLUDE"; then
    echo "deploy: ${EXCLUDE} には、先頭に / の無い tmp/ の行もある。どの階層の tmp/ も隠す。前の版の deploy.sh が書いた行なら、消してよい"
  fi
fi
echo "deploy: 次は常時ルールの本文（$DEST/tmp/cursor-user-rule.md）を、Claude Code は ~/.claude/CLAUDE.md に、Cursor は User Rules に貼る（社長の作業。貼り先は tmp/DEPLOYED.md）"
