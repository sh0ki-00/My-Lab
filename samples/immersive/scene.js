// samples/immersive/scene.js — 背景の canvas のエンジン（水とマリンスノーと、真上から差す弱い光）。
// 時刻と乱数の種を外から受け取り、始める（start）・止める（stop）・指定の状態を 1 フレーム描く（renderAt）の 3 つを持つ。
// 同じ状態を渡せば、何度描いても同じ絵になる（Math.random を使わない）。色はトークン、拍の時刻と量は台帳（ledger.json）から読む。
// app.js が最初の描画のあとに読み込む。間に合わないときも、舞台と前景は app.js だけで動く。
// canvas は画面の半分の解像度で描き、CSS で画面いっぱいに引き伸ばす（SCALE）。水と光の帯はなめらかな階調なので見た目は変わらず、
// 粒はわずかにやわらかくなる。全画素で描くと、CPU を 4 倍遅くした条件で 1 フレームに約 11ms かかり、押した直後のフレームが
// 50ms を超えていた（2026-11-26 のトレース。tmp/flow/team-improvement/stage2/measure.md の 8 節）。
const SCALE = 0.5;

// ---- 曲線: tokens.css の cubic-bezier(...) を関数にする
export function cubicBezier(x1, y1, x2, y2) {
  const bx = (t) => 3 * (1 - t) * (1 - t) * t * x1 + 3 * (1 - t) * t * t * x2 + t * t * t;
  const by = (t) => 3 * (1 - t) * (1 - t) * t * y1 + 3 * (1 - t) * t * t * y2 + t * t * t;
  const dx = (t) => 3 * (1 - t) * (1 - t) * x1 + 6 * (1 - t) * t * (x2 - x1) + 3 * t * t * (1 - x2);
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let t = x;
    for (let i = 0; i < 8; i += 1) {
      const err = bx(t) - x;
      const d = dx(t);
      if (Math.abs(err) < 1e-6) return by(t);
      if (Math.abs(d) < 1e-6) break;
      t -= err / d;
    }
    let lo = 0;
    let hi = 1;
    t = x;
    for (let i = 0; i < 40; i += 1) {
      const v = bx(t);
      if (Math.abs(v - x) < 1e-6) break;
      if (v < x) lo = t; else hi = t;
      t = (lo + hi) / 2;
    }
    return by(t);
  };
}

export function parseCurve(text) {
  const m = /cubic-bezier\(([^)]+)\)/.exec(text || '');
  if (!m) return (x) => x;
  const [x1, y1, x2, y2] = m[1].split(',').map(Number);
  return cubicBezier(x1, y1, x2, y2);
}

// ---- 拍の台帳から、背景の量（深さ・溶け込み・流れる速さ・流れた距離）を時刻の関数にする
export function seaTimeline(ledger, version, curveOf) {
  const v = ledger.versions[version];
  const tracks = v.beats.flatMap((b) => (b.tracks || []).filter((t) => t.engine === 'sea'));
  const by = {};
  for (const name of ['depth', 'mix', 'speed']) {
    by[name] = tracks.filter((t) => t.param === name).sort((a, b) => a.at_ms - b.at_ms);
  }
  const start = { depth: 0, mix: 0, speed: 1 };
  const value = (name, at) => {
    let val = start[name];
    for (const t of by[name]) {
      if (at < t.at_ms) break;
      const p = t.ms > 0 ? Math.min(1, (at - t.at_ms) / t.ms) : 1;
      val = t.from + (t.to - t.from) * curveOf(t.ease)(p);
    }
    return val;
  };
  // 流れた距離は、速さを 2ms の刻みで足し上げる（刻みが固定なので、同じ時刻なら同じ値）。
  // 刻みごとの足し上げは、台帳を読んだときに 1 回だけ表にしておき、フレームごとには表を引いて端数の 1 刻みだけを足す
  // （押したあとのフレームで、0ms から足し直さない。足す順が同じなので、値は足し直したときと同じ）
  const STEP = 2;
  const settled = Math.max(0, ...by.speed.map((t) => t.at_ms + t.ms));
  const sums = [0];
  for (let t = 0; t + STEP <= settled; t += STEP) sums.push(sums[sums.length - 1] + value('speed', t + STEP / 2) * STEP);
  const integrate = (at) => {
    const k = Math.min(sums.length - 1, Math.floor(at / STEP));
    const t = k * STEP;
    const h = at - t;
    return h > 0 ? sums[k] + value('speed', t + h / 2) * h : sums[k];
  };
  const settledTravel = integrate(settled);
  const endSpeed = value('speed', settled);
  const travel = (at) => (at <= settled ? integrate(Math.max(0, at)) : settledTravel + endSpeed * (at - settled));
  return {
    total: v.total_ms,
    endSpeed,
    at(ms) {
      return { depth: value('depth', ms), mix: value('mix', ms), speed: value('speed', ms), travel: travel(ms) };
    },
  };
}

// ---- 乱数の種から決まる並び（mulberry32）
function random(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hexToRgb(hex) {
  const h = hex.trim().replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const lerp = (a, b, t) => a + (b - a) * t;
const rgb = (c, alpha = 1) => `rgb(${Math.round(c[0])} ${Math.round(c[1])} ${Math.round(c[2])} / ${alpha})`;
const mixRgb = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];

// ---- エンジン本体
// colors: { surface: [4 色], deep: [4 色], shaft, snow }（どれも #RRGGBB）。ambient: 台帳の ambient の節
export function createSea(canvas, { seed, colors, ambient }) {
  const ctx = canvas.getContext('2d', { alpha: false });
  const surface = colors.surface.map(hexToRgb);
  const deep = colors.deep.map(hexToRgb);
  const shaftRgb = hexToRgb(colors.shaft);
  const snowRgb = hexToRgb(colors.snow);
  const stops = ambient.water_stops;
  let w = 1;
  let h = 1;
  let dpr = 1;
  let flakes = [];

  function makeFlakes() {
    const next = random(seed);
    const count = Math.max(24, Math.round((w * h) / ambient.area_per_flake));
    const out = [];
    for (let i = 0; i < count; i += 1) {
      const z = 0.25 + 0.75 * next() * next(); // 遠い粒を多く、近い粒を少なく
      out.push({
        x: next() * w,
        y: next() * h,
        z,
        r: lerp(ambient.radius_px[0], ambient.radius_px[1], z),
        a: lerp(ambient.alpha[0], ambient.alpha[1], z),
        amp: lerp(1, ambient.wobble_px, z),
        period: lerp(ambient.period_ms[0], ambient.period_ms[1], next()),
        phase: next() * Math.PI * 2,
      });
    }
    return out;
  }

  function resize() {
    dpr = Math.min(2, window.devicePixelRatio || 1) * SCALE;
    const r = canvas.getBoundingClientRect();
    w = Math.max(1, Math.round(r.width));
    h = Math.max(1, Math.round(r.height));
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    flakes = makeFlakes();
  }

  function water(depth, alpha) {
    // 明るい帯は深さとともに上へ抜け、色は海面の版から深い所の版へ移る
    const top = -h * ambient.band_rise * depth;
    const g = ctx.createLinearGradient(0, top, 0, h);
    stops.forEach((p, i) => g.addColorStop(p, rgb(mixRgb(surface[i], deep[i], depth))));
    ctx.globalAlpha = alpha;
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
    ctx.globalAlpha = 1;
  }

  function shafts(clock, strength) {
    if (strength <= 0) return;
    const s = ambient.shafts;
    s.x.forEach((fx, i) => {
      const sway = Math.sin((clock / s.period_ms[i % s.period_ms.length]) * Math.PI * 2 + i * 1.7) * s.sway * w;
      const x0 = fx * w + sway;
      const len = h * s.length;
      const g = ctx.createLinearGradient(0, 0, 0, len);
      g.addColorStop(0, rgb(shaftRgb, s.alpha * strength));
      g.addColorStop(1, rgb(shaftRgb, 0));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.moveTo(x0 - (s.top_w * w) / 2, 0);
      ctx.lineTo(x0 + (s.top_w * w) / 2, 0);
      ctx.lineTo(x0 + s.slant * w + (s.bottom_w * w) / 2, len);
      ctx.lineTo(x0 + s.slant * w - (s.bottom_w * w) / 2, len);
      ctx.closePath();
      ctx.fill();
    });
  }

  function snow(travel, clock, speed) {
    const pad = 12;
    const span = h + pad * 2;
    const base = ambient.speed_px_per_ms;
    ctx.fillStyle = rgb(snowRgb);
    ctx.strokeStyle = rgb(snowRgb);
    ctx.lineCap = 'round';
    for (const f of flakes) {
      const shift = travel * base * (0.3 + 0.7 * f.z);
      const y = ((((f.y - shift) % span) + span) % span) - pad;
      const x = f.x + Math.sin((clock / f.period) * Math.PI * 2 + f.phase) * f.amp;
      ctx.globalAlpha = f.a;
      const streak = speed > 1.2 ? (speed - 1) * ambient.streak_px * f.z : 0;
      if (streak > 0.5) {
        ctx.lineWidth = f.r * 2;
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x, y + streak);
        ctx.stroke();
      } else {
        ctx.beginPath();
        ctx.arc(x, y, f.r, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
  }

  // 1 フレーム描く。state: { depth, mix, travel, clock, speed }。同じ state なら同じ絵
  function renderAt(state) {
    const depth = state.depth || 0;
    const mix = state.mix || 0;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    water(depth, 1);
    if (mix > 0) water(1, mix);
    shafts(state.clock || 0, (1 - depth) * (1 - mix));
    snow(state.travel || 0, state.clock || 0, state.speed || 0);
  }

  // 始める・止める。source(now) が、その時刻に描く state を返す
  let raf = 0;
  let source = null;
  const tick = (now) => {
    raf = 0;
    if (!source) return;
    const state = source(now);
    if (state) renderAt(state);
    if (source) raf = requestAnimationFrame(tick);
  };
  function start(fn) {
    source = fn;
    if (!raf) raf = requestAnimationFrame(tick);
  }
  function stop() {
    source = null;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  resize();
  return {
    renderAt,
    start,
    stop,
    resize,
    get running() {
      return source !== null;
    },
  };
}
