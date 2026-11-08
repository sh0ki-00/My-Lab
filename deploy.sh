#!/usr/bin/env bash
# deploy.sh <プロジェクトのパス> — この一式（skills/・.company/・tools/・samples/）をそのプロジェクトの tmp/ に写し、git に入らないようにする。
# 社長が手でコピーするのと中身は同じ。加えて .git/info/exclude に tmp/ を足し、tmp/DEPLOYED.md に日時と正本の場所と常時ルールの貼り先を書く。
# samples/ は、写した skills の参照と自己試験（見本を使う検査）が写した先でも通るように写す。__pycache__ は写さない。
# 常時ルール（~/.claude/CLAUDE.md、Cursor の User Rules）には書き込まない。貼る本文は tmp/cursor-user-rule.md、Claude Code の接続の説明は tmp/claude-code.md に写すだけ。
# 使い方: ./deploy.sh /path/to/project   既に tmp/skills などがあれば新しい版で置き換える。tmp/ の他の中身は触らない。
set -eu
LAB="$(cd "$(dirname "$0")" && pwd -P)"
DEST="${1:-}"
[ -n "$DEST" ] || { echo "使い方: deploy.sh <プロジェクトのパス>"; exit 2; }
[ -d "$DEST" ] || { echo "FAIL deploy: $DEST が無い"; exit 1; }
DEST="$(cd "$DEST" && pwd -P)"
[ "$DEST" != "$LAB" ] || { echo "FAIL deploy: 正本（My-Lab）自身には写さない。root 直下のものをそのまま使う"; exit 1; }

mkdir -p "$DEST/tmp"
for d in skills .company tools samples; do
  [ -d "$LAB/$d" ] || { echo "FAIL deploy: 正本に $d/ が無い"; exit 1; }
  rm -rf "$DEST/tmp/${d:?}"
  cp -R "$LAB/$d" "$DEST/tmp/$d"
  find "$DEST/tmp/$d" -name '__pycache__' -type d -prune -exec rm -rf {} +
done
cp "$LAB/router/cursor-user-rule.md" "$DEST/tmp/cursor-user-rule.md"
cp "$LAB/router/claude-code.md" "$DEST/tmp/claude-code.md"
find "$DEST/tmp/tools" "$DEST/tmp/skills" "$DEST/tmp/samples" -name '*.sh' -exec chmod +x {} +

# git に入れない
EXCLUDE=""
if GIT_DIR="$(git -C "$DEST" rev-parse --git-dir 2>/dev/null)"; then
  case "$GIT_DIR" in /*) ;; *) GIT_DIR="$DEST/$GIT_DIR" ;; esac
  mkdir -p "$GIT_DIR/info"
  EXCLUDE="$GIT_DIR/info/exclude"
  grep -qx 'tmp/' "$EXCLUDE" 2>/dev/null || printf 'tmp/\n' >> "$EXCLUDE"
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
cat > "$DEST/tmp/DEPLOYED.md" <<EOF
# この tmp/ の写しについて

正本: $LAB

| 項目 | 内容 |
|---|---|
| 写した日時 | $NOW |
| 正本の場所 | \`$LAB\`（$VERSION） |
| 写したもの | \`tmp/skills/\`、\`tmp/.company/\`、\`tmp/tools/\`、\`tmp/samples/\`、\`tmp/cursor-user-rule.md\`、\`tmp/claude-code.md\` |
| git | \`tmp/\` を \`.git/info/exclude\` に足した。commit に入らない |

## 常時ルールの貼り先

常時ルールの本文は 1 つで、\`tmp/cursor-user-rule.md\` の「貼る本文（ここから）」から「貼る本文（ここまで）」までです。社長がツールごとに 1 回貼ります。AI は常時ルールに書き込みません。

| ツール | 貼り先 | 効く範囲 |
|---|---|---|
| Claude Code | \`~/.claude/CLAUDE.md\`（無ければ作る） | 全プロジェクト。接続の全体は \`tmp/claude-code.md\` の 2 節 |
| Cursor | Cursor Settings → Rules → User Rules | 全プロジェクト |

## 更新と検証

更新するときは、正本で \`./deploy.sh $DEST\` を回すか、同じものを手でコピーし直します。
作業を終える前の検証は \`bash tmp/tools/project-verify.sh --fast\` です。結果は \`tmp/.verify/last-fast.txt\` に残ります。hooks（Mac 全体に 1 回登録）が自動で回します。
\`tmp/tools/verify-all.sh\` は My-Lab の一式の検証なので、写した先では回さずに止まります。
EOF

echo "deploy: $DEST/tmp/ に skills・.company・tools・samples・cursor-user-rule.md・claude-code.md を写した（正本 $LAB、$VERSION）"
if [ -n "$EXCLUDE" ]; then
  echo "deploy: $EXCLUDE に tmp/ を足した"
  if git -C "$DEST" status --porcelain 2>/dev/null | grep -q 'tmp/'; then
    echo "FAIL deploy: git status に tmp/ が出る。.gitignore か exclude を確かめる"
    exit 1
  fi
else
  echo "deploy: git のリポジトリではないので exclude は書かなかった"
fi
echo "deploy: 次は常時ルールの本文（$DEST/tmp/cursor-user-rule.md）を、Claude Code は ~/.claude/CLAUDE.md に、Cursor は User Rules に貼る（社長の作業。貼り先は tmp/DEPLOYED.md）"
