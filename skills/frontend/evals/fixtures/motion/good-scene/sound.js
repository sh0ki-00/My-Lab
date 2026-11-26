// 正例: 音は操作のあとで鳴らし、消音のスイッチを動きとは別に持つ。最初は消音で始める。
let muted = true;
let ctx = null;

export function toggleMute() {
  muted = !muted;
}

export function tap() {
  if (muted) return;
  ctx = ctx || new AudioContext();
  const osc = ctx.createOscillator();
  osc.connect(ctx.destination);
  osc.start();
  osc.stop(ctx.currentTime + 0.12);
}

document.querySelector('.mute').addEventListener('click', toggleMute);
