// 正例: element.animate の見せ場。縮小版の分岐と、どのキーでも終わりの状態へ進める関数を持つ。
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
const frame = document.querySelector('.frame');
let running = [];

export function enter() {
  const keyframes = reduce.matches
    ? [{ opacity: 0 }, { opacity: 1 }]
    : [{ transform: 'translateY(48px)', opacity: 0 }, { transform: 'none', opacity: 1 }];
  running = [frame.animate(keyframes, { duration: reduce.matches ? 150 : 1400, fill: 'forwards' })];
}

export function skip() {
  for (const a of running) a.finish();
}

document.addEventListener('keydown', skip);
document.querySelector('.start').addEventListener('click', enter);
document.querySelector('.stop').addEventListener('click', () => document.body.classList.toggle('is-still'));
