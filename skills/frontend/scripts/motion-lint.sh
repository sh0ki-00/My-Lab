#!/usr/bin/env bash
# skills/frontend/scripts/motion-lint.sh <ディレクトリかファイル...> — 動きと音の守りの検査。
#   css: transition か animation の動きを、prefers-reduced-motion: reduce の分岐が同じセレクタ（か * ）で上書きしていなければ FAIL。
#        時間をトークンで書いた動きは、そのトークンを縮小版の分岐で書き換えていれば通す。定義が対象に無いトークンは FAIL。
#        transition: all も FAIL。許可リストは motion-allow.txt（transition はカンマで分けた全部が当たるときだけ通す）。
#   js・ts・jsx・tsx と html の script: element.animate、Web Animations、View Transitions、requestAnimationFrame で style を
#        変える動き、motion の部品と JSX の属性に、同じモジュールの縮小版の分岐（prefers-reduced-motion か ReducedMotion の名前）が
#        無ければ FAIL。html では script の中だけで探す。requestAnimationFrame で canvas を描くエンジンは、同じモジュールに
#        cancelAnimationFrame（止める関数）があれば、縮小版の判断を呼ぶ側に任せて通す（縮小版で止まるかは motion-measure の項目 6 が測る）。
#        500ms を超える動き（長さを定数で書いたら、同じファイルの const などを引く）は、飛ばす手段（finish()、skipTransition()、
#        skip の関数。skipWaiting() は数えない）が同じモジュールか、そこから読み込むファイルに無ければ FAIL。
#   音: Audio、AudioContext、音か映像の play() は、消音の手段（mute の名前。CSS の --muted と要素の muted 属性は数えない）が
#        同じモジュールか、そこから読み込むファイルに無ければ FAIL。audio の autoplay と、muted の無い video の autoplay は FAIL。
#   回り続ける動き（infinite、iterations: Infinity、controls の無い video の autoplay と loop）は、止める手段（animation-play-state:
#        paused、pause()、cancel()、cancelAnimationFrame()）が同じファイルか、そこから読み込むファイルに無ければ FAIL。
#        CSS の動きは、JavaScript の animationPlayState か getAnimations() からの pause()・cancel() でも止められる。
#   注釈の中の語は数えない。ビルドの出力（dist、build など）、.min.js、試験のコード（tests/ などと *.test.*）、
#   1 行目が #! の Node のスクリプトは読まない。
# 使い方: motion-lint.sh <ディレクトリ>   /   motion-lint.sh --selftest
# 判定の本体は frontend_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: motion-lint.sh <ディレクトリかファイル...> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/frontend_check.py" motion "$@" ;;
esac
