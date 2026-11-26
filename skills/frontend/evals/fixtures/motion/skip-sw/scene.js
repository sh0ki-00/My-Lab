// 負例: 1,400ms の見せ場。縮小版の分岐はあるが、飛ばす手段が同じモジュールに無い。
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
const frame = document.querySelector('.frame');

document.querySelector('.start').addEventListener('click', () => {
  const motion = reduce.matches
    ? [{ opacity: 0 }, { opacity: 1 }]
    : [{ transform: 'translateY(48px)', opacity: 0 }, { transform: 'none', opacity: 1 }];
  frame.animate(motion, { duration: reduce.matches ? 150 : 1400, fill: 'forwards' });
});
