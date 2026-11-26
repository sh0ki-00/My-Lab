// 負例: requestAnimationFrame で style を書き換えて動かし、縮小版の分岐が無い。
const layer = document.querySelector('.layer');
let start = 0;

function tick(now) {
  if (!start) start = now;
  const y = ((now - start) / 40) % 120;
  layer.style.transform = `translateY(${-y}px)`;
  requestAnimationFrame(tick);
}

requestAnimationFrame(tick);
