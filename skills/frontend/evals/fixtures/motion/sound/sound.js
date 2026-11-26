// 負例: Web Audio で音を鳴らすが、消音の手段（動きとは別のスイッチ）が無い。
const ctx = new AudioContext();

export function tap() {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  gain.gain.value = 0.2;
  osc.connect(gain).connect(ctx.destination);
  osc.start();
  osc.stop(ctx.currentTime + 0.12);
}
