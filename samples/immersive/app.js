// samples/immersive/app.js — 没入のサンプル「深海の探査日誌」（架空）の舞台と進行。
// 見せ場「潜る」（演出 ID scene-start-login）を、ledger.json（拍の台帳）から Web Animations API で組む。
// 進行は状態の機械 1 つ（machine と表 T）で持ち、動きの終わりのイベントは待たない。終わりは台帳の時刻で決める。
// 場面は URL のハッシュ（#panel）に置く。戻るとき（計器盤から海面へ）は View Transitions で灯を戻す。
// 背景の canvas（scene.js）は最初の描画のあとに読む。間に合わないときも、灯の動きと短い版は app.js だけで走る。
// 台帳（ledger.json）が読めないときは演出を出さず、スタートで計器盤へ移り、1 つ目の入力欄に焦点を入れる（入口を止めない）。
// 押す前に準備し、押したら走らせるだけにする（skills/frontend/references/immersive.md の 5 節の決まり 1）。
//   海面にいる間に、次に押したときの版の動きを idle（まだ効かない）のまま組み、灯の位置・曲線のトークン・背景の量の表も先に読む。
//   押したら、動きに開始の時刻を入れ、場面の属性を替えるだけにする。
// 試験の約束: window.__scene に seek(ms)・play()・skip()・reset()・ledger を置く。seek は何度呼んでも同じ絵になる。

const root = document.documentElement;
const q = (s) => document.querySelector(s);
const qa = (s) => Array.from(document.querySelectorAll(s));

const el = {
  sea: q('.sea'),
  surface: q('#surface'),
  panelScene: q('#panel'),
  start: q('#start'),
  startCore: q('.start .lamp-core'),
  startGlow: q('.start .lamp-glow'),
  startLamp: q('.start .lamp'),
  powerLamp: q('.power .lamp'),
  power: q('.power'),
  powerLabel: q('#power-label'),
  flight: q('.flight'),
  email: q('#email'),
  password: q('#password'),
  form: q('#login'),
  status: q('.status'),
  calm: q('.calm'),
};

// 台帳の el の名前と、動かす要素
const SELECT = {
  'start-core': '.start .lamp-core',
  'start-glow': '.start .lamp-glow',
  flight: '.flight',
  'flight-arc': '.flight-arc',
  'flight-core': '.flight .lamp-core',
  'flight-glow': '.flight .lamp-glow',
  title: '.surface-text',
  surface: '#surface',
  panel: '.panel',
  'panel-text': '.panel-text',
  'panel-scene': '#panel',
  'field-1': '.field[data-field="1"]',
  'field-2': '.field[data-field="2"]',
  'field-3': '.field[data-field="3"]',
  ground: '.ground',
};

// 誤りの文（何が起きたかと、どうすればよいかの 2 文）
const MESSAGES = {
  emailEmpty: 'メールアドレスが空です。登録したアドレスを入れてください。',
  emailForm: 'メールアドレスの形になっていません。@ の前後を確かめてください。',
  passwordEmpty: 'パスワードが空です。登録したパスワードを入れてください。',
};

const KEY_DIVES = 'deep-log:dives';
const KEY_CALM = 'deep-log:calm';
const appTitle = document.title;
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');

// 保存は利用者ごとの便利のためだけ。読めない環境（プライベートの窓など）でも画面は動く
const keep = (area) => ({
  get(k) {
    try {
      return window[area].getItem(k);
    } catch {
      return null;
    }
  },
  set(k, v) {
    try {
      window[area].setItem(k, v);
    } catch {
      /* 保存できなくても続ける */
    }
  },
  del(k) {
    try {
      window[area].removeItem(k);
    } catch {
      /* 同上 */
    }
  },
});
const session = keep('sessionStorage');
const local = keep('localStorage');

const timelineNow = () => {
  const t = document.timeline ? document.timeline.currentTime : null;
  return typeof t === 'number' ? t : performance.now();
};
const token = (name) => getComputedStyle(root).getPropertyValue(name).trim();
const frames = (n) =>
  new Promise((resolve) => {
    let left = n;
    const step = () => {
      left -= 1;
      if (left <= 0) resolve();
      else requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });

// ---- 状態
const machine = { state: 'boot' };
let ledger = null;
let dive = null; // 走っている見せ場（動きの束と、時刻の原点）
let armed = null; // 押す前に組んでおく見せ場（動きは idle のまま）
let lastVersion = null;
let sea = null; // 背景のエンジン。scene.js を読むまで null
let seaMod = null;
let seaTl = null; // 版ごとの背景の量の表。scene.js を読んだときに 1 回だけ作る
let calm = false; // 背景の動きを止めているか
let seaClock = { mode: 'surface', origin: 0, clock0: 0, travel0: 0, tl: null };
let pendingStart = false;
let resolveSea;
const seaReady = new Promise((resolve) => {
  resolveSea = resolve;
});
// 準備の終わり。背景（scene.js）を読み、次に押したときの版を組み終えたら解決する。背景を読めないときも解決する
let resolvePrepared;
const prepared = new Promise((resolve) => {
  resolvePrepared = resolve;
});

// 曲線のトークンは、台帳を読んだときに 1 回だけ読む（押したあとに getComputedStyle を呼ばない）
const easeText = {};
const ease = (name) => (name === 'linear' ? 'linear' : easeText[name] || token(ledger.tokens.ease[name]));
const curves = {};
const curveOf = (name) => {
  if (!curves[name]) curves[name] = seaMod.parseCurve(ease(name));
  return curves[name];
};

// 焦点を動かした手段。入力欄をポインターで押したときだけ data-modality="pointer" を置き、焦点の輪が 120ms で灯る。
// キーボードとスクリプトからの移しは 0ms で、属性を外す（無いときは書き換えないので、スタートを押した瞬間に属性が変わらない）
const setModality = (pointer) => {
  if (pointer && root.dataset.modality !== 'pointer') root.dataset.modality = 'pointer';
  else if (!pointer && root.dataset.modality) delete root.dataset.modality;
};
const focusBy = (node) => {
  setModality(false);
  node.focus({ preventScroll: true });
};

// ---- 背景の量（深さ・溶け込み・速さ・流れた距離・時計）を、時刻から決める
function seaStateAt(now) {
  const c = seaClock;
  const t = Math.max(0, now - c.origin);
  if (c.mode === 'dive' && c.tl) {
    const s = c.tl.at(t);
    return {
      depth: s.depth,
      mix: s.mix,
      speed: calm ? 0 : s.speed,
      travel: c.travel0 + (calm ? 0 : s.travel),
      clock: c.clock0 + (calm ? 0 : t),
    };
  }
  const deep = c.mode !== 'surface';
  const speed = c.mode === 'panel' ? ledger.ambient.panel_speed : 1;
  const run = calm ? 0 : t;
  return { depth: deep ? 1 : 0, mix: 0, speed: calm ? 0 : speed, travel: c.travel0 + speed * run, clock: c.clock0 + run };
}
// 今の量を引き継いで、時計の原点を置き直す（粒が跳ばない）
function rebase(mode, now, extra = {}) {
  const cur = seaStateAt(now);
  seaClock = { mode, origin: now, clock0: cur.clock, travel0: cur.travel, tl: null, ...extra };
}
function renderSea(now) {
  if (sea) sea.renderAt(seaStateAt(now));
}
function onFrame(now) {
  if (machine.state === 'diving' && dive && now - dive.t0 >= dive.total) send('END');
  return seaStateAt(now);
}
// 背景を動かし続けるのは、見せ場の間と、止めていない待機の間だけ
function syncLoop() {
  if (!sea) return;
  const live = machine.state === 'diving' || ((machine.state === 'surface' || machine.state === 'panel') && !calm);
  if (live) {
    sea.start(onFrame);
  } else {
    sea.stop();
    if (machine.state !== 'seeking') renderSea(timelineNow());
  }
}

// ---- 場面
function setScene(scene, version) {
  root.dataset.scene = scene;
  if (version) root.dataset.version = version;
  else delete root.dataset.version;
  el.surface.inert = scene !== 'surface';
  el.panelScene.inert = scene !== 'panel';
  document.title = scene === 'panel' ? (ledger ? ledger.title : `ログイン ・ ${appTitle}`) : appTitle;
}

// ---- 台帳が読めないとき。演出なしで場面を替える（状態は plain-surface と plain の 2 つ）
function openWithoutScene() {
  setScene('panel');
  if (location.hash !== '#panel') history.pushState(null, '', '#panel');
  machine.state = 'plain';
  focusBy(el.email);
}
function closeWithoutScene(focus = true) {
  setScene('surface');
  machine.state = 'plain-surface';
  if (focus) focusBy(el.start);
}

function chooseVersion() {
  if (reduce.matches) return 'reduced';
  if (Number(session.get(KEY_DIVES) || 0) >= 1) return 'short';
  if (!sea) return 'short'; // 背景の準備が間に合わない
  return 'full';
}

// 押した合図の今の姿（押しながら始めたとき、灯が跳ばないように、見せ場をここから始める）
function pressLook() {
  const read = (node) => {
    const cs = getComputedStyle(node);
    const m = cs.transform && cs.transform !== 'none' ? new DOMMatrixReadOnly(cs.transform) : null;
    return { scale: m ? Math.hypot(m.a, m.b) : 1, opacity: Number(cs.opacity) };
  };
  return { core: read(el.startCore), glow: read(el.startGlow) };
}

// ---- 見せ場を組む（台帳の track 1 本が、動き 1 本）
function center(node) {
  const r = node.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width };
}
function arcFrames(tr, geo) {
  // 2 次のベジェ曲線を、道のりの長さで等間隔に拾う（監修記録の指摘 12）。曲線（easing）は動き全体に掛けるので、
  // 灯の速さは道のりに沿って曲線のとおりに変わる。媒介変数で等間隔に拾うと、曲がりの強い所で速さが偏る
  const dx = geo.power.x - geo.start.x;
  const dy = geo.power.y + tr.land_below_px - geo.start.y;
  const cx = dx * tr.bend[0];
  const cy = dy * tr.bend[1];
  const at = (p) => ({ x: 2 * (1 - p) * p * cx + p * p * dx, y: 2 * (1 - p) * p * cy + p * p * dy });
  const fine = tr.samples * 16;
  const lens = [0];
  let prev = at(0);
  for (let i = 1; i <= fine; i += 1) {
    const cur = at(i / fine);
    lens.push(lens[i - 1] + Math.hypot(cur.x - prev.x, cur.y - prev.y));
    prev = cur;
  }
  const total = lens[fine];
  const out = [];
  let j = 0;
  for (let i = 0; i <= tr.samples; i += 1) {
    const want = (total * i) / tr.samples;
    while (j < fine - 1 && lens[j + 1] < want) j += 1;
    const seg = lens[j + 1] - lens[j];
    const f = seg > 0 ? Math.min(1, Math.max(0, (want - lens[j]) / seg)) : 0;
    const p = i === tr.samples ? 1 : (j + f) / fine;
    const pt = at(p);
    out.push({ offset: i / tr.samples, transform: `translate(${pt.x.toFixed(2)}px, ${pt.y.toFixed(2)}px)` });
  }
  return out;
}
function keyFrames(tr) {
  return tr.keys.map((k) => {
    const f = { offset: k.o, transform: `translateY(${k.y}px)` };
    if (k.ease) f.easing = ease(k.ease);
    return f;
  });
}
function pairFrames(tr, look) {
  const out = [{}, {}];
  const scale = tr.scale ? [look ? look.scale : tr.scale[0], tr.scale[1]] : null;
  const opacity = tr.opacity ? [look ? look.opacity : tr.opacity[0], tr.opacity[1]] : null;
  for (let i = 0; i < 2; i += 1) {
    const parts = [];
    if (tr.y) parts.push(`translateY(${tr.y[i]}px)`);
    if (scale) parts.push(`scale(${scale[i]})`);
    if (parts.length) out[i].transform = parts.join(' ');
    if (opacity) out[i].opacity = opacity[i];
    if (tr.blur) out[i].filter = `blur(${tr.blur[i]}px)`;
  }
  return out;
}
function placeFlight(geo) {
  el.flight.style.left = `${(geo.start.x - geo.start.w / 2).toFixed(2)}px`;
  el.flight.style.top = `${(geo.start.y - geo.start.w / 2).toFixed(2)}px`;
}
function clearFlight() {
  el.flight.style.removeProperty('left');
  el.flight.style.removeProperty('top');
}
function teardown() {
  if (!dive) return;
  clearTimeout(dive.timer);
  for (const a of dive.anims) a.cancel();
  if (dive.resolve) dive.resolve('replaced');
  dive = null;
  if (!armed) clearFlight();
}
function disarm() {
  if (!armed) return;
  for (const a of armed.anims) a.cancel();
  armed = null;
  if (!dive) clearFlight();
}
// 動きは idle のまま組む（new Animation）。idle の動きは要素に効かないので、押す前の画面を変えない。
// 走らせるときは startTime を入れ、seek のときは pause() のあと currentTime を入れる
function buildDive(version) {
  const v = ledger.versions[version];
  const geo = { start: center(el.startLamp), power: center(el.powerLamp) };
  if (version === 'full') placeFlight(geo);
  const anims = [];
  const press = [];
  for (const beat of v.beats) {
    for (const tr of beat.tracks || []) {
      if (tr.engine) continue; // 背景の拍は scene.js が描く
      const nodes = qa(SELECT[tr.el]);
      let kf;
      if (tr.path === 'arc') kf = arcFrames(tr, geo);
      else if (tr.keys) kf = keyFrames(tr);
      else kf = pairFrames(tr, null);
      const easing = tr.keys ? 'linear' : ease(tr.ease);
      nodes.forEach((node, i) => {
        const a = new Animation(new KeyframeEffect(node, kf, { delay: tr.at_ms, duration: tr.ms, fill: 'both', easing }), document.timeline);
        a.id = nodes.length > 1 ? `${tr.id}#${i + 1}` : tr.id;
        anims.push(a);
        if (tr.press) press.push({ a, tr, part: tr.el.endsWith('core') ? 'core' : 'glow' });
      });
    }
  }
  const d = {
    version,
    total: v.total_ms,
    focusAt: v.focus_ms,
    anims,
    press,
    tl: seaTl ? seaTl[version] : null,
    t0: 0,
    at: 0,
    timer: 0,
    resolve: null,
    done: null,
  };
  d.done = new Promise((resolve) => {
    d.resolve = resolve;
  });
  return d;
}
// 海面にいる間に、次に押したときの版を組んでおく。版・灯の位置・背景の準備が変わったら組み直す
function prepare(force = false) {
  if (machine.state !== 'surface' || !ledger) return;
  const version = chooseVersion();
  if (armed && armed.version === version && !force) return;
  disarm();
  armed = buildDive(version);
}

// ---- 状態の機械。表 T に無い組み合わせの合図は捨てる
function startDive(data = {}) {
  const version = chooseVersion();
  if (!armed || armed.version !== version) prepare(true); // ふつうは押す前に組んである
  dive = armed;
  armed = null;
  // 押し込みの途中で離したとき、灯が跳ばないように、押した合図の拍だけを今の姿から始める
  if (data.press) for (const p of dive.press) p.a.effect.setKeyframes(pairFrames(p.tr, data.press[p.part]));
  el.start.classList.remove('is-pressing');
  setScene('diving', version);
  const t0 = timelineNow();
  for (const a of dive.anims) a.startTime = t0;
  dive.t0 = t0;
  lastVersion = version;
  if (dive.tl) rebase('dive', t0, { tl: dive.tl });
  else seaClock = { mode: 'dive', origin: t0, clock0: seaClock.clock0, travel0: seaClock.travel0, tl: null };
  machine.state = 'diving';
  const d = dive;
  dive.timer = setTimeout(() => {
    if (dive === d && machine.state === 'diving') send('END');
  }, dive.total);
  syncLoop();
  session.set(KEY_DIVES, String(Number(session.get(KEY_DIVES) || 0) + 1));
  // 履歴の書き込みは次の仕事に回す（押した瞬間の仕事を減らす。画面の絵は変えない）。その間に海面へ戻されていたら書かない
  setTimeout(() => {
    if (location.hash !== '#panel' && (machine.state === 'diving' || machine.state === 'panel')) history.pushState(null, '', '#panel');
  }, 0);
}

function finish() {
  // 飛ばしたときも、終わったときも、同じ最後の状態（静止の計器盤）に置く
  const d = dive;
  if (d) {
    clearTimeout(d.timer);
    for (const a of d.anims) a.cancel();
  }
  dive = null;
  clearFlight();
  root.classList.remove('is-seeking');
  setScene('panel');
  rebase('panel', timelineNow());
  machine.state = 'panel';
  focusBy(el.email);
  if (d && d.resolve) d.resolve('panel');
  syncLoop();
}

function abortDive() {
  // 見せ場の途中で「戻る」を押した。動きを捨てて海面へ
  teardown();
  setScene('surface');
  rebase('surface', timelineNow());
  machine.state = 'surface';
  syncLoop();
  prepare(true);
}

function goBack() {
  // 計器盤から海面へ（移動の格）。View Transitions が灯を電源ランプからスタートの札へ戻す
  machine.state = 'returning';
  const update = () => {
    setScene('surface');
    rebase('surface', timelineNow());
    renderSea(timelineNow());
    focusBy(el.start);
  };
  const done = () => {
    if (machine.state !== 'returning') return;
    machine.state = 'surface';
    syncLoop();
    prepare(true);
  };
  if (typeof document.startViewTransition !== 'function') {
    update();
    done();
    return;
  }
  const vt = document.startViewTransition(update);
  vt.ready.catch(() => {});
  vt.updateCallbackDone.catch(() => {});
  vt.finished.then(done, done);
}

function seekTo({ ms, version, force = false }) {
  const v = version || (dive && machine.state === 'seeking' ? dive.version : reduce.matches ? 'reduced' : 'full');
  root.classList.add('is-seeking');
  el.start.classList.remove('is-pressing');
  disarm();
  if (force || !dive || dive.version !== v || machine.state !== 'seeking') {
    teardown();
    dive = buildDive(v);
  }
  clearTimeout(dive.timer);
  const at = Math.max(0, ms);
  dive.at = at;
  seaClock = { mode: 'dive', origin: 0, clock0: 0, travel0: 0, tl: dive.tl };
  if (at >= dive.total) {
    // 最後の状態。動きは消さずに終わりの姿で止め、層の作りを他の時刻と揃える（消すと縁の画素がわずかに変わる）
    setScene('panel');
    for (const a of dive.anims) {
      a.pause();
      a.currentTime = dive.total;
    }
    focusBy(el.email);
  } else {
    setScene('diving', v);
    for (const a of dive.anims) {
      a.pause();
      a.currentTime = at;
    }
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
  }
  machine.state = 'seeking';
  if (sea) {
    sea.stop();
    sea.renderAt(seaStateAt(at));
  }
}

function setCalm(on, remember = true) {
  if (seaClock.mode !== 'dive') rebase(seaClock.mode, timelineNow());
  calm = on;
  el.calm.setAttribute('aria-pressed', String(on));
  if (remember) local.set(KEY_CALM, on ? '1' : '0');
  syncLoop();
}

// ---- 誤りの状態と送信中の姿
function setError(input, text) {
  const field = input.closest('.field');
  const out = document.getElementById(input.getAttribute('aria-describedby'));
  if (text) {
    field.dataset.invalid = '';
    input.setAttribute('aria-invalid', 'true');
    out.textContent = text;
  } else {
    delete field.dataset.invalid;
    input.removeAttribute('aria-invalid');
    out.textContent = '';
  }
}
// 電源ランプの姿。受付中は光の輪が灯り、送信中は輪を消して受け付けを止めたことを示す
function setPower(state) {
  el.power.dataset.power = state;
  el.powerLabel.textContent = state === 'busy' ? '送信中' : '受付中';
}
function clearForm() {
  el.form.reset();
  setError(el.email, '');
  setError(el.password, '');
  setPower('ready');
  el.status.textContent = '';
}

function resetAll() {
  teardown();
  disarm();
  root.classList.remove('is-seeking');
  el.start.classList.remove('is-pressing');
  session.del(KEY_DIVES);
  local.del(KEY_CALM);
  clearForm();
  setScene('surface');
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  calm = reduce.matches;
  el.calm.setAttribute('aria-pressed', String(calm));
  seaClock = { mode: 'surface', origin: timelineNow(), clock0: 0, travel0: 0, tl: null };
  if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
  delete root.dataset.modality;
  lastVersion = null;
  machine.state = 'surface';
  syncLoop();
  prepare(true);
}

// 状態ごとに、受け付ける合図と行き先。HASH は URL のハッシュが変わったとき（戻る・進む・手で書き換え）
const T = {
  surface: {
    START: startDive,
    SEEK: seekTo,
    RESET: resetAll,
    HASH: (d) => d.want === 'panel' && startDive({}),
  },
  diving: {
    SKIP: finish,
    END: finish,
    SEEK: seekTo,
    RESET: resetAll,
    HASH: (d) => d.want === 'surface' && abortDive(),
  },
  panel: {
    SEEK: seekTo,
    RESET: resetAll,
    HASH: (d) => d.want === 'surface' && goBack(),
  },
  returning: { SEEK: seekTo, RESET: resetAll },
  seeking: { SEEK: seekTo, SKIP: finish, RESET: resetAll },
  'plain-surface': { HASH: (d) => d.want === 'panel' && openWithoutScene() },
  plain: { HASH: (d) => d.want === 'surface' && closeWithoutScene() },
};
function send(type, data = {}) {
  const handler = T[machine.state] && T[machine.state][type];
  if (!handler) return false;
  handler(data);
  return true;
}

// ---- 入力
// 焦点を動かす手段を控える。入力欄をポインターで押したときだけ pointer にする（そのときだけ焦点の輪が 120ms で灯る）
document.addEventListener('pointerdown', (e) => setModality(Boolean(e.target.closest && e.target.closest('.field input'))), true);
document.addEventListener('keydown', () => setModality(false), true);
el.start.addEventListener('pointerdown', (e) => {
  if (e.button === 0 && machine.state === 'surface') el.start.classList.add('is-pressing');
});
el.start.addEventListener('keydown', (e) => {
  if ((e.key === 'Enter' || e.key === ' ') && !e.repeat && machine.state === 'surface') el.start.classList.add('is-pressing');
});
for (const type of ['pointercancel', 'pointerleave', 'blur']) {
  el.start.addEventListener(type, () => {
    if (machine.state === 'surface') el.start.classList.remove('is-pressing');
  });
}
el.start.addEventListener('click', () => {
  if (machine.state === 'boot') {
    pendingStart = true;
    return;
  }
  if (machine.state === 'plain-surface') {
    openWithoutScene();
    return;
  }
  send('START', { press: pressLook() });
});

// 見せ場の途中は、どのキーでも、どこを押しても飛ばす。字のキーは、そのまま 1 つ目の入力欄に入る
document.addEventListener(
  'keydown',
  (e) => {
    if (machine.state !== 'diving' || e.repeat) return;
    if (e.key === 'Tab' || e.key === 'Enter' || e.key === ' ') e.preventDefault();
    send('SKIP');
  },
  true,
);
document.addEventListener(
  'pointerdown',
  (e) => {
    if (machine.state !== 'diving') return;
    e.preventDefault(); // 焦点を入力欄に残す
    send('SKIP');
  },
  true,
);

// 乗船する: 空の欄と形の誤りを、欄の下の文と警告灯の枠で示す。誤りが無ければ送信中の姿にする（サンプルなので送信はしない）
el.form.addEventListener('submit', (e) => {
  e.preventDefault();
  const email = el.email.value.trim();
  setError(el.email, !email ? MESSAGES.emailEmpty : el.email.validity.typeMismatch ? MESSAGES.emailForm : '');
  setError(el.password, el.password.value ? '' : MESSAGES.passwordEmpty);
  const bad = [el.email, el.password].find((n) => n.getAttribute('aria-invalid') === 'true');
  if (bad) {
    setPower('ready');
    el.status.textContent = '';
    focusBy(bad);
    return;
  }
  setPower('busy');
  el.status.textContent = 'サンプルなので、送信はしません。入力を直すと受付中に戻ります。';
});
for (const input of [el.email, el.password]) {
  input.addEventListener('input', () => {
    if (input.getAttribute('aria-invalid') === 'true') setError(input, '');
    if (el.power.dataset.power === 'busy') {
      setPower('ready');
      el.status.textContent = '';
    }
  });
}
el.calm.addEventListener('click', () => setCalm(!calm));
window.addEventListener('popstate', () => send('HASH', { want: location.hash === '#panel' ? 'panel' : 'surface' }));
window.addEventListener('hashchange', () => send('HASH', { want: location.hash === '#panel' ? 'panel' : 'surface' }));
window.addEventListener('resize', () => {
  if (sea) sea.resize();
  if (machine.state === 'diving') send('SKIP');
  else if (machine.state === 'seeking' && dive) seekTo({ ms: dive.at, version: dive.version, force: true });
  else {
    renderSea(timelineNow());
    prepare(true); // 灯の位置が変わったので組み直す
  }
});
reduce.addEventListener('change', () => {
  if (reduce.matches && !calm) setCalm(true, false);
  prepare();
});

// ---- 背景（遅れて読む）
function loadSea() {
  import('./scene.js')
    .then((mod) => {
      seaMod = mod;
      const four = (kind) => [1, 2, 3, 4].map((i) => token(`--water-${kind}-${i}`));
      sea = mod.createSea(el.sea, {
        seed: ledger.ambient.seed,
        colors: { surface: four('surface'), deep: four('deep'), shaft: token('--shaft'), snow: token('--snow') },
        ambient: ledger.ambient,
      });
      // 版ごとの背景の量の表は、ここで 1 回だけ作る（押したあとに作らない）
      seaTl = {};
      for (const v of Object.keys(ledger.versions)) seaTl[v] = mod.seaTimeline(ledger, v, curveOf);
      if (dive && !dive.tl) {
        dive.tl = seaTl[dive.version];
        if (machine.state === 'diving') seaClock = { mode: 'dive', origin: dive.t0, clock0: 0, travel0: 0, tl: dive.tl };
      }
      renderSea(timelineNow());
      el.sea.classList.add('is-ready');
      resolveSea();
      syncLoop();
      prepare(true); // 背景が来たので、初回は full の版で組み直す
      resolvePrepared();
    })
    .catch((error) => {
      console.warn('背景（scene.js）を読めませんでした。前景と舞台だけで続けます。', error);
      resolvePrepared();
    });
}

function boot(data) {
  ledger = data;
  for (const [name, prop] of Object.entries(ledger.tokens.ease)) easeText[name] = token(prop);
  const initial = location.hash === '#panel' ? 'panel' : 'surface';
  calm = reduce.matches || local.get(KEY_CALM) === '1';
  el.calm.setAttribute('aria-pressed', String(calm));
  seaClock = { mode: initial, origin: timelineNow(), clock0: 0, travel0: 0, tl: null };
  setScene(initial);
  machine.state = initial;
  if (initial === 'panel') focusBy(el.email);
  if (pendingStart && initial === 'surface') send('START', { press: pressLook() });
  else prepare();
  // 背景は、最初の画面が出たあとに読む
  requestAnimationFrame(() => setTimeout(loadSea, 0));
}

// 台帳が読めないときは、演出なしで入口を開ける。背景の動きは台帳の値で描くので、止めたままにする
function bootWithoutLedger(error) {
  console.warn('台帳（ledger.json）を読めませんでした。演出なしで続けます。', error);
  calm = true;
  el.calm.setAttribute('aria-pressed', 'true');
  const initial = location.hash === '#panel' ? 'panel' : 'surface';
  if (initial === 'panel') openWithoutScene();
  else closeWithoutScene(false);
  if (pendingStart && initial === 'surface') openWithoutScene();
  resolvePrepared();
}

// 台帳を読み、背景を読み、次に押したときの版を組み終えたら解決する（試験の約束の ready。押す前の準備の終わり）
const booted = fetch('./ledger.json')
  .then((r) => {
    if (!r.ok) throw new Error(`ledger.json が読めない（${r.status}）`);
    return r.json();
  })
  .then(boot, bootWithoutLedger);
const ready = booted.then(() => prepared);

// ---- 試験の約束
async function seek(ms, version) {
  await ready;
  await seaReady;
  send('SEEK', { ms, version });
  await frames(2);
}
// play() は押す前の状態（海面）から、押したときと同じ道で始める。版の選び方（縮小版・2 回目・素材の遅れ）も同じ
async function play() {
  await ready;
  if (machine.state === 'diving' && dive) return dive.done;
  if (machine.state !== 'surface') {
    teardown();
    root.classList.remove('is-seeking');
    setScene('surface');
    rebase('surface', timelineNow());
    machine.state = 'surface';
  }
  send('START', {});
  return dive ? dive.done : undefined;
}
async function skip() {
  await ready;
  send('SKIP');
  await frames(1);
}
async function reset() {
  await ready;
  send('RESET');
  await frames(1);
}

window.__scene = {
  get ledger() {
    return ledger;
  },
  get state() {
    return machine.state;
  },
  get version() {
    return dive ? dive.version : lastVersion;
  },
  get seaLoaded() {
    return Boolean(sea);
  },
  get calm() {
    return calm;
  },
  ready,
  seaReady,
  seek,
  play,
  skip,
  reset,
  // 試験の助け: 台帳から決まる背景の量（深さ・溶け込み・速さ）を、その時刻で返す
  async seaState(ms, version = 'full') {
    await ready;
    await seaReady;
    return seaTl[version].at(ms);
  },
};
