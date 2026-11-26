// 計測のスクリプト（scripts/motion-measure.mjs）を試す場面。window.__scene の約束（references/immersive.md の 6 節）を満たす最小の実装。
// スタートを押すと、題名の場面からログインの枠へ移る。拍の時刻と長さは台帳（ledger）から読み、実装と計測が同じ台帳を見る。題材と数値は架空。
const reduce = matchMedia('(prefers-reduced-motion: reduce)');
const $ = (s) => document.querySelector(s);
const startBtn = $('#start-button');
const title = $('#title');
const titleScene = $('#title-scene');
const login = $('#login-frame');
const email = $('#email');
const canvas = $('#particles');
const g = canvas.getContext('2d');
const ledger = {
  id: 'start-to-login', total_ms: 1400, short_ms: 600, title: 'ログイン', inert: ['#title-scene'],
  trigger: { role: 'button', name: 'スタート' },
  focus: { role: 'textbox', name: 'メールアドレス', at_ms: 1100 },
  skip: { key: 'Enter', at_ms: 200 },
  reduced: { kind: 'fade', ms: 150 },
  ambient: { stop: { role: 'button', name: '背景の動きを止める' } },
  sound: { mute: { role: 'button', name: '音を消す' } },
  beats: [
    { at_ms: 0, target: 'start-button', ms: 120, props: ['transform'], sound: 'tap' },
    { at_ms: 120, target: 'particles', ms: 600, engine: 'background' },
    { at_ms: 200, target: 'title', ms: 400, props: ['transform', 'opacity'] },
    { at_ms: 900, target: 'login-frame', ms: 400, props: ['transform', 'opacity'] },
  ],
};
const beat = (target) => ledger.beats.find((b) => b.target === target);
let state = 'idle';
let anims = [];
let timers = [];
let muted = false;
let still = reduce.matches;
let audio = null;
const dots = Array.from({ length: 80 }, (_, i) => ({ x: (i * 97) % 1280, y: (i * 53) % 800, r: 1 + (i % 3) }));
let engineT = 0;
let speed = 1;
let last = null;
let raf = 0;
const glow = getComputedStyle(document.documentElement).getPropertyValue('--glow').trim();

// 背景のエンジン: 時刻を受け取って 1 フレームを描く。始める・止める・指定の時刻を描く、の 3 つを持つ
function size() { canvas.width = innerWidth; canvas.height = innerHeight; }
function draw(t) {
  g.clearRect(0, 0, canvas.width, canvas.height);
  g.fillStyle = glow;
  for (const d of dots) {
    const y = (((d.y - t * 0.03) % canvas.height) + canvas.height) % canvas.height;
    g.beginPath();
    g.arc(d.x % canvas.width, y, d.r, 0, Math.PI * 2);
    g.fill();
  }
}
function tick(now) {
  if (last !== null) engineT += (now - last) * speed;
  last = now;
  draw(engineT);
  raf = requestAnimationFrame(tick);
}
function startLoop() { if (!still && !raf) { last = null; raf = requestAnimationFrame(tick); } }
function stopLoop() { cancelAnimationFrame(raf); raf = 0; }

// 進行は状態の機械 1 つで持ち、動きの終わりのイベントを待たない
function focusLogin() { login.inert = false; email.focus(); document.title = ledger.title; }
function done() { state = 'done'; titleScene.inert = true; titleScene.hidden = true; speed = 1; }
function play() {
  if (state !== 'idle') return;
  state = 'playing';
  login.hidden = false;
  if (reduce.matches) {
    titleScene.inert = true;
    anims = [login.animate([{ opacity: 0 }, { opacity: 1 }], { duration: ledger.reduced.ms, fill: 'both', id: 'login-frame' })];
    timers.push(setTimeout(() => { focusLogin(); done(); }, ledger.reduced.ms));
    return;
  }
  const press = beat('start-button');
  const leave = beat('title');
  const enter = beat('login-frame');
  const stream = beat('particles');
  speed = 3;
  timers.push(setTimeout(() => { speed = 1; }, stream.at_ms + stream.ms));
  anims = [
    startBtn.animate([{ transform: 'scale(1)' }, { transform: 'scale(0.96)' }, { transform: 'scale(1)' }], { duration: press.ms, delay: press.at_ms, id: 'start-button' }),
    title.animate([{ transform: 'none', opacity: 1 }, { transform: 'translateY(-120px)', opacity: 0 }], { duration: leave.ms, delay: leave.at_ms, fill: 'both', easing: 'ease-in', id: 'title' }),
    login.animate([{ transform: 'translateY(48px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: enter.ms, delay: enter.at_ms, fill: 'both', easing: 'cubic-bezier(0.2, 0, 0, 1)', id: 'login-frame' }),
  ];
  timers.push(setTimeout(focusLogin, ledger.focus.at_ms));
  timers.push(setTimeout(done, ledger.total_ms));
}
function skip() {
  if (state !== 'playing') return;
  for (const a of anims) a.finish();
  timers.forEach(clearTimeout);
  timers = [];
  focusLogin();
  done();
}
function reset() {
  for (const a of anims) a.cancel();
  anims = [];
  timers.forEach(clearTimeout);
  timers = [];
  state = 'idle';
  titleScene.inert = false;
  titleScene.hidden = false;
  login.hidden = true;
  login.inert = true;
  document.title = '深海の探査日誌';
  engineT = 0;
  speed = 1;
  startLoop();
}
function seek(ms) {
  if (state === 'idle') play();
  timers.forEach(clearTimeout);
  timers = [];
  for (const a of anims) { a.pause(); a.currentTime = ms; }
  state = 'seeking';
  stopLoop();
  draw(ms);
}

// 音: 押す前に用意し、押した瞬間に鳴らす。消音のスイッチは動きとは別に持つ
try { audio = new AudioContext(); } catch (e) { audio = null; }
startBtn.addEventListener('pointerdown', () => {
  if (muted || state !== 'idle' || !audio) return;
  try {
    audio.resume();
    const o = audio.createOscillator();
    const gn = audio.createGain();
    gn.gain.value = 0.05;
    o.connect(gn).connect(audio.destination);
    o.start();
    o.stop(audio.currentTime + 0.08);
  } catch (e) { /* 音を出せない環境では鳴らさない */ }
});
startBtn.addEventListener('click', play);
document.addEventListener('keydown', () => { if (state === 'playing') skip(); });
document.addEventListener('pointerdown', (e) => { if (state === 'playing' && e.target !== startBtn) skip(); });
$('#stop').addEventListener('click', (e) => {
  still = !still;
  e.currentTarget.setAttribute('aria-pressed', String(still));
  if (still) stopLoop(); else startLoop();
});
$('#mute').addEventListener('click', (e) => { muted = !muted; e.currentTarget.setAttribute('aria-pressed', String(muted)); });
addEventListener('resize', size);
size();
draw(0);
startLoop();
// 約束: ledger と 4 つの関数と、準備の完了を知らせる ready
window.__scene = { ledger, play, seek, skip, reset, ready: new Promise((r) => setTimeout(r, 150)) };
