// 正例: canvas の背景のエンジン。始める・止める・指定の時刻を描くの 3 つを持ち、縮小版の判断は呼ぶ側に任せる。
export function createEngine(canvas) {
  const g = canvas.getContext('2d');
  let raf = 0;
  let t = 0;
  function drawAt(ms) {
    g.clearRect(0, 0, canvas.width, canvas.height);
    g.fillRect((ms / 40) % canvas.width, 0, 2, 2);
  }
  function tick(now) {
    t = now;
    drawAt(t);
    raf = requestAnimationFrame(tick);
  }
  return {
    start() { if (!raf) raf = requestAnimationFrame(tick); },
    stop() { cancelAnimationFrame(raf); raf = 0; },
    drawAt,
  };
}
