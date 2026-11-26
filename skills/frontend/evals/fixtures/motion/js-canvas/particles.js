// 負例: requestAnimationFrame で canvas を描き続けるが、縮小版の分岐も、止める関数も無い。
const canvas = document.querySelector('canvas');
const g = canvas.getContext('2d');

function tick(now) {
  g.clearRect(0, 0, canvas.width, canvas.height);
  g.fillRect((now / 40) % canvas.width, 0, 2, 2);
  requestAnimationFrame(tick);
}

requestAnimationFrame(tick);
