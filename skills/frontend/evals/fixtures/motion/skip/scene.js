// 負例: 縮小版の分岐はあるが、1,400ms の見せ場を飛ばす手段（終わりの状態へ進める関数）が無い。
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
const frame = document.querySelector('.frame');

export function enter() {
  const motion = reduce.matches
    ? [{ opacity: 0 }, { opacity: 1 }]
    : [{ transform: 'translateY(48px)', opacity: 0 }, { transform: 'none', opacity: 1 }];
  return frame.animate(motion, { duration: reduce.matches ? 150 : 1400, fill: 'forwards' });
}
