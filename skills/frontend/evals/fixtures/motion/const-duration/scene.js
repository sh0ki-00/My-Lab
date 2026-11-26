// 負例: 長さを定数（LONG = 2400）で書いた見せ場。縮小版の分岐はあるが、飛ばす手段が無い。
const LONG = 2400;
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
const frame = document.querySelector('.frame');

document.querySelector('.start').addEventListener('click', () => {
  const motion = reduce.matches ? [{ opacity: 0 }, { opacity: 1 }] : [{ transform: 'translateY(48px)' }, { transform: 'none' }];
  frame.animate(motion, { duration: LONG, fill: 'forwards' });
});
