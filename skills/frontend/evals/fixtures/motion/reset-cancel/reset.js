// 負例の相方: 自分で作った動きを取り消すだけの cancel()。CSS の回り続ける動きは止めない。
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
let a = null;

document.querySelector('.reset').addEventListener('click', () => {
  if (a) a.cancel();
  a = reduce.matches ? null : document.querySelector('.frame').animate([{ opacity: 0 }, { opacity: 1 }], 200);
});
