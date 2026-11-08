#!/usr/bin/env bash
# 資格を借りる job の terraform の本体を、repo に固定した版と SHA-256 で取る（setup-terraform を使わない）。
#   置き場: repo の tools/ci/（org/github.tf の ci_tools）。版と指紋の正は tools/ci/pinned-tools.json で、持ち主はセキュリティ。
#   資格を借りる step より前に回す。取った zip の SHA-256 が固定の値と違うか、固定の値がまだ印のままなら、job を落とす。
#   外の部品（setup-terraform）は、動くときに取る本体を固めないので使わない（設計書の攻撃者の目「資格を借りる部品」と未確定 7）。
# 使い方: bash tools/ci/fetch-terraform.sh <置き場のディレクトリ>   /   bash fetch-terraform.sh --selftest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
pins="${PINNED_TOOLS:-$here/pinned-tools.json}"

check_pin() {
  # 固定の値が 64 桁の 16 進でなければ止める（印のまま、空、形の外）。
  printf '%s' "$1" | grep -Eq '^[0-9a-f]{64}$'
}

if [ "${1:-}" = "--selftest" ]; then
  bad=0
  check_pin "$(printf 'a%.0s' $(seq 64))" || { echo "FAIL fetch-terraform: 64 桁の指紋を通さない"; bad=1; }
  if check_pin "REPLACE_WITH_THE_PUBLISHED_SHA256_OF_THE_ZIP"; then echo "FAIL fetch-terraform: 印の指紋を通す"; bad=1; fi
  if check_pin ""; then echo "FAIL fetch-terraform: 空の指紋を通す"; bad=1; fi
  tmp="$(mktemp -d)"; printf 'zip' > "$tmp/t.zip"
  want="$(sha256sum "$tmp/t.zip" 2>/dev/null | cut -c1-64 || shasum -a 256 "$tmp/t.zip" | cut -c1-64)"
  got="$( (sha256sum "$tmp/t.zip" 2>/dev/null || shasum -a 256 "$tmp/t.zip") | cut -c1-64)"
  [ "$want" = "$got" ] || { echo "FAIL fetch-terraform: 指紋の計算が合わない"; bad=1; }
  rm -rf "$tmp"
  echo "RESULT: $([ "$bad" = 0 ] && echo PASS || echo FAIL) fetch-terraform --selftest (4 例)"
  exit "$bad"
fi

dest="${1:?置き場のディレクトリを渡す}"
url="$(jq -r .terraform.url "$pins")"
want="$(jq -r .terraform.sha256 "$pins")"
check_pin "$want" || { echo "::error title=道具の固定::pinned-tools.json の terraform の SHA-256 が 64 桁でない（置き換え前の印）"; exit 1; }
case "$url" in https://releases.hashicorp.com/terraform/*) ;; *) echo "::error title=道具の固定::terraform の取り出し元が決めた置き場の外"; exit 1 ;; esac
mkdir -p "$dest"
curl -fsSL --proto '=https' --tlsv1.2 -o "$dest/terraform.zip" "$url"
got="$(sha256sum "$dest/terraform.zip" | cut -c1-64)"
[ "$got" = "$want" ] || { echo "::error title=道具の固定::terraform の zip の SHA-256 が固定の値と違う"; exit 1; }
unzip -q -o "$dest/terraform.zip" terraform -d "$dest"
rm -f "$dest/terraform.zip"
"$dest/terraform" version
