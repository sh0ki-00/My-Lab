#!/usr/bin/env node
// samples/immersive/check.mjs — 没入のサンプル「深海の探査日誌」（架空）の確かめ。
//   使い方: node samples/immersive/check.mjs [--out <ディレクトリ>]   /   node samples/immersive/check.mjs --selftest
//   --selftest: 台帳（ledger.json）とトークンとファイルの検査だけ。ブラウザもサーバーも起こさず、数秒で終わる。
//   既定: 上に加えて、127.0.0.1 の空きポートで小さな静的サーバーを立て、入っている Playwright の Chromium で開いて確かめる。
//         コンソールのエラー、外への要求、台帳と動きの突き合わせ、seek の再現、5 つの条件、縮小版、飛ばす、2 回目、
//         素材の遅れ、台帳が読めないとき、URL の場面、動きを止める、点滅、コントラスト、axe（アクセシビリティ検査）、幅 375、方向の 3 案。
//   --out: 100ms ごとのフレームと、方向の 3 案の画面を PNG で書き出す。
//   出力: PASS|FAIL|INFO immersive [観点] 内容 を並べ、最後に RESULT: PASS|FAIL immersive-check。FAIL が 1 件でもあれば終了コード 1。
//   サーバーとブラウザは、成否によらず必ず止める。新しい依存は入れない（作業ツリーの node_modules の Playwright と axe を読む）。
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import zlib from 'node:zlib';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const tally = { pass: 0, fail: 0 };
const pass = (kind, msg) => {
  tally.pass += 1;
  console.log(`PASS immersive [${kind}] ${msg}`);
};
const fail = (kind, msg) => {
  tally.fail += 1;
  console.log(`FAIL immersive [${kind}] ${msg}`);
};
const info = (kind, msg) => console.log(`INFO immersive [${kind}] ${msg}`);
const judge = (ok, kind, msg) => (ok ? pass(kind, msg) : fail(kind, msg));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex').slice(0, 16);
const pad = (n) => String(n).padStart(4, '0');
const r1 = (n) => Math.round(n * 10) / 10;

// 演出計画書（skills/designer/examples/motion-plan-dive-log.md）の時刻ごとの表。台帳の初回の版が、これを写しているかを見る
const PLAN = [
  [0, '入り', 120],
  [120, '入り', 880],
  [160, '見せ場', 640],
  [200, '見せ場', 400],
  [200, '見せ場', 700],
  [800, '収まり', 400],
  [900, '収まり', 400],
  [1100, '収まり', 180],
  [1400, '収まり', 0],
];
const GUARDS = ['動きを減らす設定', '飛ばす手段', '2 回目以降', '素材が間に合わないとき', '終わりの焦点', '環境の動き', '点滅と音'];
const DOM_ELS = ['start-core', 'start-glow', 'flight', 'flight-arc', 'flight-core', 'flight-glow', 'title', 'surface', 'panel', 'panel-text', 'panel-scene', 'field-1', 'field-2', 'field-3', 'ground'];
const PAGE_FILES = ['index.html', 'app.js', 'scene.js', 'tokens.css', 'app.css', 'ledger.json'];
const DIRECTIONS = ['a', 'b', 'c'];

// ---- 台帳とトークン（ブラウザなし）
function rootTokens(css) {
  // :root の宣言と、prefers-reduced-motion の中の :root の宣言を分けて読む
  const plain = {};
  const reduced = {};
  const media = /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{\s*:root\s*\{([^}]*)\}/m.exec(css);
  const rest = media ? css.replace(media[0], '') : css;
  const read = (text, into) => {
    for (const m of text.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) into[m[1]] = m[2].trim();
  };
  const top = /:root\s*\{([^}]*)\}/m.exec(rest.replace(/\/\*[\s\S]*?\*\//g, ''));
  if (top) read(top[1], plain);
  if (media) read(media[1].replace(/\/\*[\s\S]*?\*\//g, ''), reduced);
  return { plain, reduced };
}

function checkLedger(ledger, css) {
  const tok = rootTokens(css);
  const versions = ['full', 'short', 'reduced'];
  judge(versions.every((v) => ledger.versions && ledger.versions[v]), '台帳', `版が 3 つある（${versions.join('・')}）`);
  const ids = new Set();
  let badTrack = '';
  for (const v of versions) {
    const ver = ledger.versions[v];
    for (const b of ver.beats) {
      for (const t of b.tracks || []) {
        if (ids.has(t.id)) badTrack ||= `${t.id} が重複`;
        ids.add(t.id);
        if (t.engine) {
          if (t.engine !== 'sea' || !['depth', 'mix', 'speed'].includes(t.param)) badTrack ||= `${t.id} の背景の量が不明`;
        } else if (!DOM_ELS.includes(t.el)) badTrack ||= `${t.id} の el「${t.el}」が不明`;
        if (t.ease && !(t.ease in ledger.tokens.ease)) badTrack ||= `${t.id} の曲線「${t.ease}」がトークンに無い`;
        if (t.at_ms + t.ms > ver.total_ms) badTrack ||= `${t.id} が版の長さ ${ver.total_ms}ms を超える`;
        if (t.at_ms < b.at_ms) badTrack ||= `${t.id} が拍 ${b.id} より前に始まる`;
      }
    }
  }
  judge(!badTrack, '台帳', badTrack || `動きの行（track）${ids.size} 本の名前・対象・曲線・長さが揃っている`);

  // 計画の表と同じか
  const full = ledger.versions.full;
  const rows = full.beats.map((b) => [b.at_ms, b.phase, b.ms]);
  const same = rows.length === PLAN.length && rows.every((r, i) => r[0] === PLAN[i][0] && r[1] === PLAN[i][1] && r[2] === PLAN[i][2]);
  judge(same, '計画との一致', same ? `初回の版の拍 ${rows.length} 行が、演出計画の時刻・段・長さと同じ` : `拍の行が演出計画と違う: ${JSON.stringify(rows)}`);
  judge(full.beats[0].at_ms === 0, '計画との一致', '最初の拍が 0ms で始まる');

  // トークンとの突き合わせ
  const ms = (s) => (s ? parseFloat(s) : NaN);
  judge(ms(tok.plain['--duration-scene']) === full.total_ms, 'トークン', `--duration-scene ${tok.plain['--duration-scene']} と初回の版 ${full.total_ms}ms`);
  judge(ms(tok.plain['--duration-scene-repeat']) === ledger.versions.short.total_ms, 'トークン', `--duration-scene-repeat ${tok.plain['--duration-scene-repeat']} と短い版 ${ledger.versions.short.total_ms}ms`);
  judge(ms(tok.reduced['--duration-scene']) === ledger.versions.reduced.total_ms, 'トークン', `動きを減らす設定の --duration-scene ${tok.reduced['--duration-scene']} と縮小版 ${ledger.versions.reduced.total_ms}ms`);
  // 演出計画書のトークンの表（拍の長さと縮小版の長さ）と、台帳の拍の長さ
  const beatTokens = Object.entries(ledger.tokens.beats || {}).map(([id, name]) => [name, (full.beats.find((b) => b.id === id) || {}).ms]);
  beatTokens.push([ledger.tokens.reduced_ms, ledger.versions.reduced.total_ms]);
  const offBeat = beatTokens.filter(([name, want]) => !name || ms(tok.plain[name]) !== want);
  judge(beatTokens.length >= 4 && offBeat.length === 0, 'トークン', offBeat.length ? `台帳と違う: ${offBeat.map(([n, w]) => `${n} ${tok.plain[n] || '無い'}（台帳 ${w}ms）`).join('・')}` : `演出計画書の拍のトークン ${beatTokens.map(([n, w]) => `${n} ${w}ms`).join('・')} が台帳の長さと同じ`);
  const b8 = full.beats.find((b) => b.id === 'b8');
  const gaps = b8.tracks.slice(1).map((t, i) => t.at_ms - b8.tracks[i].at_ms);
  judge(ms(tok.plain['--stagger']) === b8.stagger_ms && gaps.every((g) => g === b8.stagger_ms), 'トークン', `--stagger ${tok.plain['--stagger']} と入力欄のずれ ${gaps.join('・')}ms`);
  const easeMissing = Object.values(ledger.tokens.ease).filter((name) => !tok.plain[name]);
  judge(easeMissing.length === 0, 'トークン', easeMissing.length ? `曲線のトークンが無い: ${easeMissing.join('・')}` : `曲線 ${Object.keys(ledger.tokens.ease).length} つがトークンにある`);

  // 長さの枠（提案書 6.2 節の格）
  judge(full.total_ms >= 600 && full.total_ms <= 1400, '長さの枠', `初回 ${full.total_ms}ms（見せ場の枠 600〜1,400ms）`);
  judge(ledger.versions.short.total_ms <= 600, '長さの枠', `短い版 ${ledger.versions.short.total_ms}ms（600ms 以下）`);
  judge(ledger.versions.reduced.total_ms <= 150, '長さの枠', `縮小版 ${ledger.versions.reduced.total_ms}ms（150ms の溶け込み）`);
  judge(versions.every((v) => ledger.versions[v].focus_ms === ledger.versions[v].total_ms), '長さの枠', '終わりの焦点は、どの版も最後の時刻に入る');

  // ただのスライドでない（5 つの条件）
  const phases = ['入り', '見せ場', '収まり'];
  const first = phases.map((p) => Math.min(...full.beats.filter((b) => b.phase === p).map((b) => b.at_ms)));
  judge(first.every((t) => Number.isFinite(t)) && first[0] <= first[1] && first[1] <= first[2], '5 つの条件', `段が 3 つ（入り ${first[0]}ms、見せ場 ${first[1]}ms、収まり ${first[2]}ms から）`);
  const named = new Set(ledger.layers.map((l) => l.name));
  const moving = new Set(full.beats.filter((b) => (b.tracks || []).length).flatMap((b) => b.layer.split('と')).filter((n) => named.has(n)));
  judge(moving.size >= 3, '5 つの条件', `動く層が ${moving.size}（奥から ${ledger.layers.filter((l) => moving.has(l.name)).map((l) => l.name).join('・')}）`);
  const arc = full.beats.flatMap((b) => b.tracks || []).find((t) => t.path === 'arc');
  const sharedBeat = full.beats.find((b) => b.shared);
  judge(Boolean(ledger.shared && sharedBeat && arc && arc.to === 'power-lamp'), '5 つの条件', `共有要素: ${ledger.shared.from} → ${ledger.shared.to}（拍 ${sharedBeat && sharedBeat.id}）`);
  const tracks = full.beats.flatMap((b) => b.tracks || []);
  const overlaps = [];
  for (const a of tracks) for (const b of tracks) if (b.at_ms > a.at_ms && b.at_ms < a.at_ms + a.ms) overlaps.push(`${a.id}→${b.id}`);
  judge(overlaps.length > 0, '5 つの条件', `動きの重なり ${overlaps.length} 組（例: ${overlaps.slice(0, 3).join('、')}）`);
  const conds = ledger.guards.map((g) => g.condition);
  const lack = GUARDS.filter((g) => !conds.includes(g));
  judge(lack.length === 0, '5 つの条件', lack.length ? `守りの行が無い: ${lack.join('・')}` : `守りの表が ${conds.length} 行（${conds.join('・')}）`);

  // 場面をまたぐ灯が、盤と同じ動きで乗る（数の食い違いを落とす）
  const b7 = full.beats.find((b) => b.id === 'b7');
  const panelKeys = b7.tracks.find((t) => t.id === 'b7.panel').keys;
  const rideKeys = b7.tracks.find((t) => t.id === 'b7.ride').keys;
  const rideOk = arc.land_below_px === panelKeys[0].y && rideKeys.every((k, i) => k.y === panelKeys[i].y - arc.land_below_px && k.o === panelKeys[i].o);
  judge(rideOk, '共有要素', `灯は盤の ${panelKeys[0].y}px 下に降り、盤と同じ 3 点（${rideKeys.map((k) => k.y).join('・')}px）で乗る`);
  const peak = Math.min(...panelKeys.map((k) => k.y));
  judge(panelKeys[0].y === 48 && peak === -6, '計画との一致', `計器盤は下から ${panelKeys[0].y}px 上がり、${-peak}px 行き過ぎて戻る`);

  // 環境の動きの守り
  const periods = [...ledger.ambient.period_ms, ...ledger.ambient.shafts.period_ms];
  judge(Math.min(...periods) >= 4000, '環境の動き', `揺れの周期は最短 ${Math.min(...periods)}ms（4 秒以上）`);
  const stop = ledger.ambient.stop || {};
  judge(Boolean(stop.name) && ledger.ambient.flash_max_per_s <= 3, '環境の動き', `止める操作「${stop.name}」、点滅の上限 1 秒に ${ledger.ambient.flash_max_per_s} 回`);

  // 計測の約束（skills/frontend/references/immersive.md の 6.2）で計測のスクリプトが読む鍵
  const spec = (s) => Boolean(s && (s.selector || (s.role && s.name)));
  const contract = { id: /^[\w.-]+$/.test(ledger.id || ''), trigger: spec(ledger.trigger), focus: spec(ledger.focus), title: Boolean(ledger.title), inert: Array.isArray(ledger.inert) && ledger.inert.length > 0, stop: spec(stop) };
  const lackKeys = Object.keys(contract).filter((k) => !contract[k]);
  judge(lackKeys.length === 0, '計測の約束', lackKeys.length ? `台帳に無い鍵: ${lackKeys.join('・')}` : `id「${ledger.id}」、押す要素「${ledger.trigger.name}」、焦点「${ledger.focus.name}」、終わりの title「${ledger.title}」、inert ${ledger.inert.join('・')}`);
  const domTracks = versions.flatMap((v) => ledger.versions[v].beats.flatMap((b) => (b.tracks || []).filter((t) => !t.engine)));
  const noProps = domTracks.filter((t) => !Array.isArray(t.props) || !t.props.length).map((t) => t.id);
  const blurAt = domTracks.filter((t) => (t.props || []).includes('filter') && t.el !== 'title').map((t) => t.id);
  const reducedMove = ledger.versions.reduced.beats.flatMap((b) => b.tracks || []).filter((t) => !t.engine && (t.props || []).some((p) => p !== 'opacity')).map((t) => t.id);
  judge(!noProps.length && !blurAt.length && !reducedMove.length, '計測の約束', noProps.length || blurAt.length || reducedMove.length ? `props の欠け ${noProps.join('・') || 'なし'}、題字の外の filter ${blurAt.join('・') || 'なし'}、縮小版の位置の動き ${reducedMove.join('・') || 'なし'}` : `動きの行 ${domTracks.length} 本に、動かしてよい属性（props）がある。filter は題字だけ、縮小版は opacity だけ`);
}

// ---- ファイル（ブラウザなし）
function checkFiles() {
  const all = [...PAGE_FILES, ...DIRECTIONS.map((d) => `directions/${d}.html`)];
  const missing = all.filter((f) => !fs.existsSync(path.join(here, f)));
  judge(missing.length === 0, 'ファイル', missing.length ? `無い: ${missing.join('・')}` : `${all.length} 本ある`);
  if (missing.length) return;
  const text = Object.fromEntries(all.map((f) => [f, fs.readFileSync(path.join(here, f), 'utf8')]));
  const external = all.filter((f) => /\b(?:https?:)?\/\/[a-z0-9.-]+\.[a-z]{2,}/i.test(text[f].replace(/<!--[\s\S]*?-->/g, '')));
  judge(external.length === 0, '外の素材', external.length ? `外の URL を書いている: ${external.join('・')}` : '外の URL を 1 本も書いていない（書体・画像・スクリプトは外から読まない）');
  const sound = all.filter((f) => /AudioContext|<audio|<video|new Audio\(/.test(text[f]));
  judge(sound.length === 0, '音', sound.length ? `音か映像のコードがある: ${sound.join('・')}` : '音と映像のコードが 0 行（音は入れない）');
  const imports = [...text['app.js'].matchAll(/import\s*\(\s*['"]([^'"]+)['"]\s*\)|from\s+['"]([^'"]+)['"]/g)].map((m) => m[1] || m[2]);
  judge(imports.every((s) => s === './scene.js'), '依存', `app.js が読むのは ${imports.join('・') || 'なし'} だけ（ライブラリなし）`);
  const scripted = DIRECTIONS.filter((d) => /<script|@keyframes|animation\s*:|transition\s*:/.test(text[`directions/${d}.html`]));
  judge(scripted.length === 0, '方向の 3 案', scripted.length ? `動きかスクリプトがある: ${scripted.join('・')}` : '3 案とも静止画（スクリプトと動きが 0）');
  const gz = (f) => zlib.gzipSync(fs.readFileSync(path.join(here, f))).length;
  const first = ['index.html', 'app.js', 'tokens.css', 'app.css', 'ledger.json'].reduce((s, f) => s + gz(f), 0);
  const lateJs = gz('scene.js');
  info('大きさ', `圧縮後（gzip）: 初期 ${r1(first / 1024)}KB（うち JS ${r1(gz('app.js') / 1024)}KB）、遅れて読む scene.js ${r1(lateJs / 1024)}KB`);
  judge(gz('app.js') <= 170 * 1024 && first + lateJs <= 600 * 1024, '大きさ', '初期表示の JS は 170KB 以内、演出の素材は合計 600KB 以内');
}

// ---- PNG を読む（点滅の検査で、画面の明るさを数えるため。zlib だけで読む）
function decodePng(buf) {
  let pos = 8;
  let width = 0;
  let height = 0;
  let depth = 0;
  let type = 0;
  let interlace = 0;
  const idat = [];
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos);
    const name = buf.toString('ascii', pos + 4, pos + 8);
    const data = buf.subarray(pos + 8, pos + 8 + len);
    if (name === 'IHDR') {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      depth = data[8];
      type = data[9];
      interlace = data[12];
    } else if (name === 'IDAT') idat.push(data);
    else if (name === 'IEND') break;
    pos += 12 + len;
  }
  if (depth !== 8 || interlace !== 0 || (type !== 2 && type !== 6)) throw new Error(`読めない PNG（深さ ${depth}、型 ${type}）`);
  const bpp = type === 6 ? 4 : 3;
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = width * bpp;
  const out = Buffer.alloc(height * stride);
  for (let y = 0; y < height; y += 1) {
    const filter = raw[y * (stride + 1)];
    const src = y * (stride + 1) + 1;
    const row = y * stride;
    const prev = row - stride;
    for (let x = 0; x < stride; x += 1) {
      const a = x >= bpp ? out[row + x - bpp] : 0;
      const b = y > 0 ? out[prev + x] : 0;
      const c = y > 0 && x >= bpp ? out[prev + x - bpp] : 0;
      let v = raw[src + x];
      if (filter === 1) v += a;
      else if (filter === 2) v += b;
      else if (filter === 3) v += (a + b) >> 1;
      else if (filter === 4) {
        const p = a + b - c;
        const pa = Math.abs(p - a);
        const pb = Math.abs(p - b);
        const pc = Math.abs(p - c);
        v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      }
      out[row + x] = v & 255;
    }
  }
  return { width, height, bpp, data: out };
}
const LINEAR = Array.from({ length: 256 }, (_, c) => {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
});
const linear = (c) => LINEAR[c];
// 画面を 4×3 の区画に分け、区画ごとの明るさ（相対輝度の平均）を返す
function tileLuminance(png) {
  const cols = 4;
  const rows = 3;
  const out = [];
  for (let ty = 0; ty < rows; ty += 1) {
    for (let tx = 0; tx < cols; tx += 1) {
      let sum = 0;
      let n = 0;
      for (let y = Math.floor((ty * png.height) / rows); y < Math.floor(((ty + 1) * png.height) / rows); y += 4) {
        for (let x = Math.floor((tx * png.width) / cols); x < Math.floor(((tx + 1) * png.width) / cols); x += 4) {
          const i = (y * png.width + x) * png.bpp;
          sum += 0.2126 * linear(png.data[i]) + 0.7152 * linear(png.data[i + 1]) + 0.0722 * linear(png.data[i + 2]);
          n += 1;
        }
      }
      out.push(sum / n);
    }
  }
  return out;
}
// 明るさの向きが 0.1 以上変わった回数を数え、1 秒の窓の中の最大を返す（WCAG 2.2 の 2.3.1 の一般閃光の考え方を簡略にしたもの）
function flashCount(series, stepMs) {
  let worst = 0;
  let biggest = 0;
  const tiles = series[0].length;
  for (let k = 0; k < tiles; k += 1) {
    const flips = [];
    let hi = series[0][k];
    let lo = series[0][k];
    let dir = 0; // 0 はまだ向きが無い、-1 は暗くなる途中、1 は明るくなる途中
    series.forEach((frame, i) => {
      const v = frame[k];
      biggest = Math.max(biggest, Math.abs(v - series[0][k]));
      if (dir <= 0) lo = Math.min(lo, v);
      if (dir >= 0) hi = Math.max(hi, v);
      if (dir >= 0 && hi - v >= 0.1 && v < 0.8) {
        flips.push(i * stepMs);
        dir = -1;
        lo = v;
      } else if (dir <= 0 && v - lo >= 0.1 && lo < 0.8) {
        flips.push(i * stepMs);
        dir = 1;
        hi = v;
      }
    });
    for (const t of flips) worst = Math.max(worst, flips.filter((u) => u >= t && u < t + 1000).length);
  }
  return { flashes: Math.floor(worst / 2), flips: worst, biggest };
}

// ---- ページの中で使う小道具
async function waitScene(page) {
  await page.evaluate(() => window.__scene.ready);
  await page.evaluate(() => window.__scene.seaReady);
}
async function seek(page, ms, version) {
  await page.evaluate(([m, v]) => window.__scene.seek(m, v), [ms, version]);
}
// 押した時刻と、灯が最初に動いたフレーム、見せ場が始まったフレーム、計器盤に着いたフレームを記録する
async function installProbe(page) {
  await page.evaluate(() => {
    const p = { press: [], keys: [], click: null, firstLamp: null, firstDive: null, panelAt: null, frames: [] };
    window.__probe = p;
    const start = document.querySelector('.start .lamp-core').getBoundingClientRect();
    document.addEventListener('pointerdown', (e) => p.press.push(e.timeStamp), true);
    document.addEventListener('keydown', (e) => p.keys.push(e.timeStamp), true);
    document.addEventListener('click', (e) => {
      if (!p.click && e.target.closest && e.target.closest('#start')) p.click = e.timeStamp;
    }, true);
    const lamp = () => {
      const full = document.documentElement.dataset.version === 'full' && document.documentElement.dataset.scene === 'diving';
      return document.querySelector(full ? '.flight .lamp-core' : '.start .lamp-core').getBoundingClientRect();
    };
    // フレームの記録は rAF の時刻（フレームの始まり）、変化に気づいた時刻は performance.now()（入力を処理したあと）で取る
    const loop = (t) => {
      p.frames.push(t);
      const now = performance.now();
      if ((p.press.length || p.keys.length) && p.firstLamp === null) {
        const r = lamp();
        if (Math.abs(r.width - start.width) > 0.05 || Math.abs(r.left - start.left) > 0.5 || Math.abs(r.top - start.top) > 0.5) p.firstLamp = now;
      }
      if (p.click !== null && p.firstDive === null && document.getAnimations().some((a) => a.id && a.playState === 'running' && a.currentTime > 0)) {
        p.firstDive = now;
        // 走り出したフレームで、動きの一覧を控える（短い版や縮小版は、あとから読むと終わっている）
        p.anims = document.getAnimations().filter((a) => a.id).map((a) => {
          const tm = a.effect.getTiming();
          const props = new Set();
          for (const k of a.effect.getKeyframes()) for (const q of Object.keys(k)) if (!['offset', 'computedOffset', 'easing', 'composite'].includes(q)) props.add(q);
          return { id: a.id, end: tm.delay + tm.duration, props: [...props] };
        });
      }
      if (p.panelAt === null && document.documentElement.dataset.scene === 'panel') p.panelAt = now;
      if (p.frames.length < 900) requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  });
}
async function canvasHash(page) {
  return page.evaluate(() => {
    const c = document.querySelector('.sea');
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let h = 2166136261;
    for (let i = 0; i < d.length; i += 7) h = Math.imul(h ^ d[i], 16777619);
    return h >>> 0;
  });
}
async function liveAnimations(page) {
  return page.evaluate(() => document.getAnimations().filter((a) => a.id).length);
}
async function rects(page) {
  return page.evaluate(() => {
    const r = (s) => {
      const b = document.querySelector(s).getBoundingClientRect();
      return [b.left, b.top, b.width, b.height];
    };
    return { panel: r('.panel'), power: r('.power .lamp-core'), f1: r('.field[data-field="1"]'), f3: r('.field[data-field="3"]'), title: r('.panel-title') };
  });
}
const rectGap = (a, b) => Math.max(...Object.keys(a).flatMap((k) => a[k].map((v, i) => Math.abs(v - b[k][i]))));
async function pressStart(page, holdMs = 60) {
  const box = await page.locator('#start').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await sleep(holdMs);
  await page.mouse.up();
}

function serve(root) {
  const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8' };
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      let p = decodeURIComponent(new URL(req.url, 'http://local').pathname);
      if (p === '/') p = '/index.html';
      const file = path.join(root, path.normalize(p));
      if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
        res.writeHead(404);
        res.end();
        return;
      }
      res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' });
      fs.createReadStream(file).pipe(res);
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

// ---- ブラウザで確かめる
async function checkBrowser(ledger, out) {
  let chromium;
  let AxeBuilder;
  try {
    ({ chromium } = require('playwright'));
    ({ AxeBuilder } = require('@axe-core/playwright'));
  } catch (e) {
    fail('道具が無い', `playwright と @axe-core/playwright が読めない: ${String(e.message).split('\n')[0]}`);
    return;
  }
  if (out) fs.mkdirSync(out, { recursive: true });
  const save = (name, buf) => out && fs.writeFileSync(path.join(out, name), buf);
  const server = await serve(here);
  const origin = `http://127.0.0.1:${server.address().port}`;
  const requests = [];
  const errors = [];
  const watch = (page, label) => {
    page.on('console', (m) => {
      if (m.type() === 'error') errors.push(`${label}: ${m.text()}`);
    });
    page.on('pageerror', (e) => errors.push(`${label}: ${e.message}`));
    page.on('request', (r) => requests.push(r.url()));
  };
  let browser = null;
  try {
    browser = await chromium.launch();
    // ---- 既定の設定（1280×800、動きを減らす設定なし）
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, reducedMotion: 'no-preference' });
    const page = await ctx.newPage();
    watch(page, '既定');
    await page.goto(`${origin}/index.html`);
    await waitScene(page);

    // 計測の約束: 押す要素と止める操作が、役割と名前で 1 つに決まる
    const byRole = async (s) => page.getByRole(s.role, { name: s.name, exact: true }).count();
    const tCount = await byRole(ledger.trigger);
    const sCount = await byRole(ledger.ambient.stop);
    judge(tCount === 1 && sCount === 1, '計測の約束', `海面で、役割と名前で 1 つに決まる: ${ledger.trigger.role}「${ledger.trigger.name}」${tCount}、${ledger.ambient.stop.role}「${ledger.ambient.stop.name}」${sCount}`);

    // 台帳と動きの突き合わせ（版ごと）
    for (const version of ['full', 'short']) {
      const seen = await page.evaluate(async (v) => {
        await window.__scene.seek(0, v);
        return document.getAnimations().filter((a) => a.id).map((a) => {
          const t = a.effect.getTiming();
          const props = new Set();
          for (const k of a.effect.getKeyframes()) for (const p of Object.keys(k)) if (!['offset', 'computedOffset', 'easing', 'composite'].includes(p)) props.add(p);
          return { id: a.id, delay: t.delay, duration: t.duration, props: [...props] };
        });
      }, version);
      const want = ledger.versions[version].beats.flatMap((b) => (b.tracks || []).filter((t) => !t.engine));
      const miss = [];
      for (const tr of want) {
        const got = seen.filter((a) => a.id === tr.id || a.id.startsWith(`${tr.id}#`));
        if (!got.length) miss.push(`${tr.id} が無い`);
        for (const a of got) if (a.delay !== tr.at_ms || a.duration !== tr.ms) miss.push(`${a.id} ${a.delay}+${a.duration}ms（台帳 ${tr.at_ms}+${tr.ms}ms）`);
      }
      const extra = seen.filter((a) => !want.some((tr) => a.id === tr.id || a.id.startsWith(`${tr.id}#`)));
      judge(!miss.length && !extra.length, '台帳と実装', miss.length || extra.length ? `${version}: ${[...miss, ...extra.map((a) => `${a.id} が台帳に無い`)].slice(0, 4).join('、')}` : `${version}: 動き ${seen.length} 本が、台帳の ${want.length} 行と開始と長さまで同じ（差 0ms）`);
      const allowedOf = (a) => (want.find((tr) => a.id === tr.id || a.id.startsWith(`${tr.id}#`)) || {}).props || [];
      const badProps = seen.filter((a) => a.props.some((p) => !allowedOf(a).includes(p)) || (a.props.includes('filter') && !/\.title$/.test(a.id)));
      judge(!badProps.length, '動かす属性', badProps.length ? `${version}: ${badProps.map((a) => `${a.id}=${a.props.join('+')}`).join('、')}` : `${version}: どの動きも台帳の props の内側。transform と opacity が主で、filter（ぼかし）は題字の 1 層だけ`);
    }
    const sea = await page.evaluate(async () => {
      const at = (ms) => window.__scene.seaState(ms, 'full');
      return { d0: (await at(0)).depth, d1000: (await at(1000)).depth, s160: (await at(160)).speed, s800: (await at(800)).speed, s1200: (await at(1200)).speed };
    });
    const seaOk = sea.d0 === 0 && Math.abs(sea.d1000 - 1) < 1e-9 && Math.abs(sea.s160 - 1) < 1e-9 && Math.abs(sea.s800 - 3) < 1e-9 && Math.abs(sea.s1200 - 0.5) < 1e-9;
    judge(seaOk, '台帳と実装', `背景: 深さ 0ms ${sea.d0}・1000ms ${r1(sea.d1000)}、速さ 160ms ${r1(sea.s160)}・800ms ${r1(sea.s800)}・1200ms ${r1(sea.s1200)} 倍`);

    // seek の再現: 順を変え、reset し、読み込み直しても、同じ時刻なら同じ絵
    const steps = Array.from({ length: 15 }, (_, i) => i * 100);
    const shot = {};
    for (const ms of steps) {
      await seek(page, ms, 'full');
      const buf = await page.screenshot();
      shot[ms] = sha(buf);
      save(`full-${pad(ms)}.png`, buf);
    }
    const unique = new Set(Object.values(shot)).size;
    judge(unique === steps.length, 'seek の再現', `100ms ごとの 15 枚のフレームが、どれも違う絵（${unique} 種類）`);
    const shuffled = [1400, 700, 0, 1300, 200, 900, 100, 1100, 500, 300, 1200, 600, 800, 400, 1000];
    const differ = [];
    for (const ms of shuffled) {
      await seek(page, ms, 'full');
      if (sha(await page.screenshot()) !== shot[ms]) differ.push(ms);
    }
    await page.evaluate(() => window.__scene.reset());
    for (const ms of [700, 0, 1400]) {
      await seek(page, ms, 'full');
      if (sha(await page.screenshot()) !== shot[ms]) differ.push(`reset 後 ${ms}`);
    }
    await page.reload();
    await waitScene(page);
    for (const ms of [1100, 300]) {
      await seek(page, ms, 'full');
      if (sha(await page.screenshot()) !== shot[ms]) differ.push(`読み込み直し後 ${ms}`);
    }
    judge(differ.length === 0, 'seek の再現', differ.length ? `違う絵になった時刻: ${differ.join('・')}` : '順を変えた 15 回、reset 後の 3 回、読み込み直し後の 2 回で、画面の全画素が同じ');

    // play(): seek のあとでも、押す前の状態から押したときと同じ道で流し、終わりで計器盤に着く
    await seek(page, 700, 'full');
    const played = await page.evaluate(async () => {
      const t0 = performance.now();
      await window.__scene.play();
      return { ms: performance.now() - t0, state: window.__scene.state, version: window.__scene.version, active: document.activeElement && document.activeElement.id };
    });
    judge(played.state === 'panel' && played.version === 'full' && played.active === 'email' && Math.abs(played.ms - ledger.versions.full.total_ms) <= 100, '試験の約束', `seek(700) のあとの play() は海面から ${played.version} の版で流れ、${r1(played.ms)}ms で計器盤に着く。焦点 ${played.active}`);
    await page.evaluate(() => window.__scene.reset());

    // 5 つの条件を、動いている絵で見る
    const pos = async (ms) =>
      page.evaluate(async (m) => {
        await window.__scene.seek(m, 'full');
        const c = (s) => {
          const b = document.querySelector(s).getBoundingClientRect();
          return { x: b.left + b.width / 2, y: b.top + b.height / 2, w: b.width };
        };
        return { title: c('.title'), lamp: c('.flight .lamp-core'), panel: c('.panel') };
      }, ms);
    const a400 = await pos(400);
    const h400 = await canvasHash(page);
    const a500 = await pos(500);
    const h500 = await canvasHash(page);
    const dTitle = a500.title.y - a400.title.y;
    const dLamp = Math.hypot(a500.lamp.x - a400.lamp.x, a500.lamp.y - a400.lamp.y);
    judge(h400 !== h500 && Math.abs(dTitle) > 1 && dLamp > 1 && Math.abs(Math.abs(dTitle) - dLamp) > 1, '5 つの条件', `400→500ms で 3 層が違う速さで動く: 背景が変わり、題字 ${r1(dTitle)}px、灯 ${r1(dLamp)}px`);
    const path5 = [];
    for (let ms = 200; ms <= 900; ms += 50) path5.push((await pos(ms)).lamp);
    const [p0, pN] = [path5[0], path5[path5.length - 1]];
    const len = Math.hypot(pN.x - p0.x, pN.y - p0.y);
    const bulge = Math.max(...path5.map((p) => Math.abs((pN.x - p0.x) * (p0.y - p.y) - (p0.x - p.x) * (pN.y - p0.y)) / len));
    judge(bulge >= 20, '共有要素', `灯は弧を描く（弦から最大 ${r1(bulge)}px 離れる。まっすぐなら 0px）`);
    const before = await pos(1399);
    await seek(page, 1400, 'full');
    const after = await page.evaluate(() => {
      const b = document.querySelector('.power .lamp-core').getBoundingClientRect();
      return { x: b.left + b.width / 2, y: b.top + b.height / 2, w: b.width, active: document.activeElement && document.activeElement.id, title: document.title };
    });
    const handoff = Math.hypot(before.lamp.x - after.x, before.lamp.y - after.y);
    judge(handoff <= 0.5 && Math.abs(before.lamp.w - after.w) <= 0.1, '共有要素', `1,399ms の灯と、最後の電源ランプの差 ${r1(handoff)}px（大きさの差 ${r1(Math.abs(before.lamp.w - after.w))}px）`);
    judge(after.active === 'email' && after.title === ledger.title, '終わりの焦点', `1,400ms で焦点は ${after.active}、title は「${after.title}」（台帳の title と同じ）`);

    // コントラスト: 題字と海面の字は、背景の水（canvas の画素）と比べる。盤の字は計算した色で比べる
    await seek(page, 0, 'full');
    const surface = await page.evaluate(() => {
      const canvas = document.querySelector('.sea');
      const ctx = canvas.getContext('2d');
      const dpr = canvas.width / canvas.getBoundingClientRect().width;
      const lin = (c) => {
        const s = c / 255;
        return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      const lum = (r, g, b) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
      const ratio = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      const out = {};
      for (const sel of ['.title', '.lede', '.logline']) {
        const node = document.querySelector(sel);
        const r = node.getBoundingClientRect();
        const img = ctx.getImageData(Math.floor(r.left * dpr), Math.floor(r.top * dpr), Math.ceil(r.width * dpr), Math.ceil(r.height * dpr)).data;
        const ls = [];
        for (let i = 0; i < img.length; i += 4) ls.push(lum(img[i], img[i + 1], img[i + 2]));
        ls.sort((x, y) => x - y);
        const fg = lum(...getComputedStyle(node).color.match(/[\d.]+/g).slice(0, 3).map(Number));
        out[sel] = { p995: ratio(fg, ls[Math.floor(ls.length * 0.995)]), worst: ratio(fg, ls[ls.length - 1]) };
      }
      return out;
    });
    judge(surface['.title'].p995 >= 4.5 && surface['.lede'].p995 >= 4.5 && surface['.logline'].p995 >= 4.5, 'コントラスト', `海面の字と背景の水（明るい側 0.5% の画素を除く）: 題字 ${r1(surface['.title'].p995)}、説明 ${r1(surface['.lede'].p995)}、小見出し ${r1(surface['.logline'].p995)} 対 1（最も明るい粒の上でも ${r1(Math.min(surface['.title'].worst, surface['.lede'].worst, surface['.logline'].worst))} 対 1）`);
    await seek(page, 1400, 'full');
    const panelC = await page.evaluate(() => {
      const lin = (c) => {
        const s = c / 255;
        return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      const lum = (css) => {
        const [r, g, b] = css.match(/[\d.]+/g).slice(0, 3).map(Number);
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
      };
      const ratio = (a, b) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);
      const cs = (s) => getComputedStyle(document.querySelector(s));
      const panel = cs('.panel').backgroundColor;
      return {
        見出し: ratio(cs('.panel-title').color, panel),
        補助: ratio(cs('.panel-lede').color, panel),
        ラベル: ratio(cs('.field label').color, panel),
        入力の字: ratio(cs('#email').color, cs('#email').backgroundColor),
        入力の枠: ratio(cs('#password').borderTopColor, panel),
        ボタン: ratio(cs('.board').color, cs('.board').backgroundColor),
        焦点の輪: ratio(cs('#email').outlineColor, panel),
        スタート: ratio(cs('.start').color, cs('.start').backgroundColor),
        止める: ratio(cs('.calm').color, cs('.calm').backgroundColor),
      };
    });
    const textOk = ['見出し', '補助', 'ラベル', '入力の字', 'ボタン', 'スタート', '止める'].every((k) => panelC[k] >= 4.5);
    const partOk = panelC['入力の枠'] >= 3 && panelC['焦点の輪'] >= 3;
    judge(textOk && partOk, 'コントラスト', `字（4.5 以上）と部品（3 以上）: ${Object.entries(panelC).map(([k, v]) => `${k} ${r1(v)}`).join('、')}（対 1）`);

    // 通しで流す: マウスで押して、灯が動くまで・見せ場が始まるまで・終わりまでを測る
    await page.evaluate(() => window.__scene.reset());
    await installProbe(page);
    await pressStart(page);
    await page.waitForFunction(() => window.__scene.state === 'panel', null, { timeout: 5000 });
    await sleep(80);
    const live = await page.evaluate(() => ({
      p: window.__probe,
      version: window.__scene.version,
      active: document.activeElement && document.activeElement.id,
      title: document.title,
      hash: location.hash,
      inert: [...document.querySelectorAll(window.__scene.ledger.inert.join(','))].every((n) => n.inert),
    }));
    const lampMs = live.p.firstLamp - live.p.press[0];
    const diveMs = live.p.firstDive - live.p.click;
    const total = live.p.panelAt - live.p.click;
    judge(live.version === 'full', '通し', `初回は ${live.version} の版`);
    judge(lampMs >= 0 && lampMs <= 100, '押してすぐ動く', `押してから灯が動くまで ${r1(lampMs)}ms（100ms 以内）`);
    judge(diveMs >= 0 && diveMs <= 100, '押してすぐ動く', `指を離して（click）から見せ場が動き出すまで ${r1(diveMs)}ms（100ms 以内）`);
    judge(Math.abs(total - ledger.versions.full.total_ms) <= 100, '通し', `click から計器盤に着くまで ${r1(total)}ms（台帳 ${ledger.versions.full.total_ms}ms、差は 100ms 以内）`);
    judge(live.active === 'email' && live.title === ledger.title && live.hash === '#panel' && live.inert, '終わりの焦点', `焦点 ${live.active}、title「${live.title}」、URL ${live.hash}、${ledger.inert.join('・')} は inert`);
    const gaps = [];
    for (let i = 1; i < live.p.frames.length; i += 1) if (live.p.frames[i] > live.p.click && live.p.frames[i] <= live.p.panelAt) gaps.push(live.p.frames[i] - live.p.frames[i - 1]);
    if (gaps.length) info('フレームの間隔', `メインスレッドの rAF の間隔: ${gaps.length} フレーム、最大 ${r1(Math.max(...gaps))}ms、50ms 超 ${gaps.filter((g) => g > 50).length}、25ms 超 ${r1((100 * gaps.filter((g) => g > 25).length) / gaps.length)}%（ヘッドレスの Chromium。CPU を遅くした条件は測っていない）`);
    judge((await liveAnimations(page)) === 0, '通し', '終わったあとに見せ場の動きが残っていない');
    const focusBox = page.getByRole(ledger.focus.role, { name: ledger.focus.name, exact: true });
    const fCount = await focusBox.count();
    const fActive = fCount === 1 && (await focusBox.evaluate((n) => n === document.activeElement));
    judge(fActive, '計測の約束', `計器盤で ${ledger.focus.role}「${ledger.focus.name}」が ${fCount} つに決まり、焦点がそこにある`);
    const liveRects = await rects(page);
    await seek(page, 1400, 'full');
    const seekRects = await rects(page);
    judge(rectGap(liveRects, seekRects) <= 0.5, '最後のフレーム', `通しの終わりと seek(1400) の位置の差 ${r1(rectGap(liveRects, seekRects))}px（盤・電源ランプ・入力欄・見出し）`);
    await seek(page, 1399, 'full');
    const near = await rects(page);
    judge(rectGap(near, seekRects) <= 0.5, '最後のフレーム', `1,399ms と静止の画面の差 ${r1(rectGap(near, seekRects))}px（終わったあとに部品が跳ばない）`);

    // 飛ばす（キー）: Enter で始め、300ms で字のキーを押す
    await page.evaluate(() => window.__scene.reset());
    await page.focus('#start');
    await page.keyboard.press('Enter');
    await sleep(300);
    await installProbe(page);
    await page.keyboard.press('k');
    await page.waitForFunction(() => window.__scene.state === 'panel', null, { timeout: 3000 });
    await sleep(60);
    const byKey = await page.evaluate(() => ({ p: window.__probe, active: document.activeElement && document.activeElement.id, value: document.querySelector('#email').value }));
    const keyMs = byKey.p.panelAt - byKey.p.keys[0];
    judge(keyMs >= 0 && keyMs <= 100, '飛ばす', `途中で字のキーを押してから最後の状態まで ${r1(keyMs)}ms（100ms 以内）`);
    judge(byKey.active === 'email' && byKey.value === 'k', '飛ばす', `焦点 ${byKey.active}、先に打った字「${byKey.value}」が 1 つ目の入力欄に入った`);
    judge((await liveAnimations(page)) === 0, '飛ばす', '飛ばしたあとに見せ場の動きが残っていない');

    // 飛ばす（押す）: 何も無い所を押す。送信しない、焦点は入力欄
    await page.evaluate(() => window.__scene.reset());
    await pressStart(page, 30);
    await sleep(300);
    await installProbe(page);
    await page.mouse.move(60, 120);
    await page.mouse.down();
    await page.mouse.up();
    await page.waitForFunction(() => window.__scene.state === 'panel', null, { timeout: 3000 });
    await sleep(60);
    const byPointer = await page.evaluate(() => ({ p: window.__probe, active: document.activeElement && document.activeElement.id, status: document.querySelector('.status').textContent }));
    const ptrMs = byPointer.p.panelAt - byPointer.p.press[0];
    judge(ptrMs >= 0 && ptrMs <= 100 && byPointer.active === 'email' && byPointer.status === '', '飛ばす', `途中でどこかを押してから最後の状態まで ${r1(ptrMs)}ms。焦点 ${byPointer.active}、送信 0 回`);

    // 2 回目: 戻る（View Transitions）で海面へ帰り、もう一度押すと 600ms の短い版
    await page.evaluate(() => window.__scene.reset());
    await pressStart(page, 30);
    await page.waitForFunction(() => window.__scene.state === 'panel', null, { timeout: 4000 });
    // 戻るの間に、灯の View Transitions（::view-transition-group(lamp)）の動きが走ったかを見る
    await page.evaluate(() => {
      window.__vt = { lamp: false, root: false };
      const look = () => {
        for (const a of document.getAnimations()) {
          const pe = (a.effect && a.effect.pseudoElement) || '';
          if (pe.includes('view-transition-group(lamp)')) window.__vt.lamp = true;
          if (pe.includes('view-transition-new(root)')) window.__vt.root = true;
        }
        if (window.__scene.state !== 'surface') requestAnimationFrame(look);
      };
      requestAnimationFrame(look);
      history.back();
    });
    await page.waitForFunction(() => window.__scene.state === 'surface', null, { timeout: 3000 });
    const back = await page.evaluate(() => ({ active: document.activeElement && document.activeElement.id, hash: location.hash, vt: window.__vt, api: typeof document.startViewTransition === 'function' }));
    judge(back.active === 'start' && back.hash === '' && back.vt.lamp && back.vt.root, '戻る', `ブラウザの戻るで海面へ。View Transitions で灯（${back.vt.lamp ? 'lamp の群れが動いた' : 'lamp の群れが無い'}）と場面（${back.vt.root ? '溶け込みあり' : '溶け込みなし'}）を戻す。焦点は ${back.active}`);
    await installProbe(page);
    await pressStart(page, 30);
    await page.waitForFunction(() => window.__scene.state === 'panel', null, { timeout: 3000 });
    await sleep(60);
    const second = await page.evaluate(() => ({ p: window.__probe, version: window.__scene.version }));
    const secondEnd = second.p.anims ? Math.max(...second.p.anims.map((a) => a.end)) : NaN;
    judge(second.version === 'short' && secondEnd === ledger.versions.short.total_ms, '2 回目', `2 回目は ${second.version} の版で、動きは ${secondEnd}ms で終わる`);
    info('2 回目', `click から計器盤に着くまで ${r1(second.p.panelAt - second.p.click)}ms`);

    // 点滅: 33ms ごとに巻いて撮り、区画ごとの明るさの向きの変わり目を数える
    for (const [version, totalMs] of [['full', ledger.versions.full.total_ms], ['short', ledger.versions.short.total_ms]]) {
      const series = [];
      for (let ms = 0; ms <= totalMs; ms += 33) {
        await seek(page, ms, version);
        series.push(tileLuminance(decodePng(await page.screenshot())));
      }
      const f = flashCount(series, 33);
      judge(f.flashes <= ledger.ambient.flash_max_per_s, '点滅', `${version}: 1 秒の窓で閃光 ${f.flashes} 回（向きの変わり目 ${f.flips}、明るさの最大の差 ${r1(f.biggest * 100)}%。上限 3 回）`);
    }
    for (let ms = 0; ms <= ledger.versions.short.total_ms; ms += 100) {
      await seek(page, ms, 'short');
      save(`short-${pad(ms)}.png`, await page.screenshot());
    }

    // URL の場面: #panel で開くと、最初から計器盤（ハッシュだけの移動にならないよう、問い合わせの部分を変えて読み込み直す）
    await page.goto(`${origin}/index.html?direct=1#panel`);
    await waitScene(page);
    const direct = await page.evaluate(() => ({ state: window.__scene.state, active: document.activeElement && document.activeElement.id }));
    judge(direct.state === 'panel' && direct.active === 'email', 'URL の場面', `#panel で開くと ${direct.state}（見せ場なし）、焦点 ${direct.active}`);

    // 動きを止める: 背景は動き続け、押すと止まり、もう一度押すと動く
    await sleep(100);
    const m1 = await canvasHash(page);
    await sleep(400);
    const m2 = await canvasHash(page);
    await page.click('.calm');
    const pressed = await page.getAttribute('.calm', 'aria-pressed');
    const m3 = await canvasHash(page);
    await sleep(700);
    const m4 = await canvasHash(page);
    await page.click('.calm');
    await sleep(400);
    const m5 = await canvasHash(page);
    judge(m1 !== m2 && pressed === 'true' && m3 === m4 && m4 !== m5, '動きを止める', `動いている（400ms で絵が変わる）→「背景の動きを止める」で 700ms 同じ絵 → もう一度押すと動く`);

    // axe: 海面と計器盤の静止の画面
    for (const [label, prep] of [
      ['海面', async () => page.evaluate(() => window.__scene.reset())],
      ['計器盤', async () => page.evaluate(async () => { await window.__scene.reset(); window.__scene.play(); await window.__scene.skip(); })],
    ]) {
      await prep();
      await sleep(100);
      const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
      judge(r.violations.length === 0, 'axe', `${label}: 違反 ${r.violations.length} 件${r.violations.length ? `（${r.violations.map((v) => v.id).join('・')}）` : ''}、判定できず ${r.incomplete.length} 件${r.incomplete.length ? `（${r.incomplete.map((v) => v.id).join('・')}）` : ''}`);
    }
    await ctx.close();

    // ---- 動きを減らす設定
    const rctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, reducedMotion: 'reduce' });
    const rpage = await rctx.newPage();
    watch(rpage, '縮小版');
    await rpage.goto(`${origin}/index.html`);
    await waitScene(rpage);
    const rStart = await rpage.evaluate(() => ({ calm: window.__scene.calm, pressed: document.querySelector('.calm').getAttribute('aria-pressed'), token: getComputedStyle(document.documentElement).getPropertyValue('--duration-scene').trim() }));
    judge(rStart.calm && rStart.pressed === 'true' && rStart.token === `${ledger.versions.reduced.total_ms}ms`, '縮小版', `背景の粒子は最初から止めてある（aria-pressed ${rStart.pressed}）。--duration-scene は ${rStart.token}`);
    const rh1 = await canvasHash(rpage);
    await sleep(500);
    judge(rh1 === (await canvasHash(rpage)), '縮小版', '海面の背景は 500ms 同じ絵（粒子は動かない）');
    await installProbe(rpage);
    const box = await rpage.locator('#start').boundingBox();
    await rpage.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await rpage.mouse.down();
    const pressedCore = await rpage.evaluate(() => getComputedStyle(document.querySelector('.start .lamp-core')).transform);
    await rpage.mouse.up();
    await rpage.waitForFunction(() => window.__scene.state === 'panel', null, { timeout: 2000 });
    await sleep(60);
    const rLive = await rpage.evaluate(() => ({ p: window.__probe, version: window.__scene.version, active: document.activeElement && document.activeElement.id }));
    const rList = rLive.p.anims || [];
    const onlyFade = rList.length > 0 && rList.every((a) => a.props.length === 1 && a.props[0] === 'opacity');
    const rMax = rList.length ? Math.max(...rList.map((a) => a.end)) : NaN;
    judge(rLive.version === 'reduced' && onlyFade && rMax === ledger.versions.reduced.total_ms && pressedCore === 'none' && rLive.active === 'email', '縮小版', `版 ${rLive.version}: 動き ${rList.length} 本がどれも opacity だけで ${rMax}ms。押しても灯の大きさは変わらない（${pressedCore}）。焦点 ${rLive.active}`);
    const rs = [];
    for (const ms of [0, 50, 75, 100, 150]) {
      await seek(rpage, ms, 'reduced');
      const buf = await rpage.screenshot();
      rs.push(sha(buf));
      if (ms % 50 === 0) save(`reduced-${pad(ms)}.png`, buf);
    }
    await seek(rpage, 75, 'reduced');
    judge(sha(await rpage.screenshot()) === rs[2], 'seek の再現', '縮小版でも、同じ時刻なら同じ絵（75ms を 2 回）');
    const rSeries = [];
    for (let ms = 0; ms <= 150; ms += 25) {
      await seek(rpage, ms, 'reduced');
      rSeries.push(tileLuminance(decodePng(await rpage.screenshot())));
    }
    const rf = flashCount(rSeries, 25);
    judge(rf.flashes === 0, '点滅', `reduced: 閃光 ${rf.flashes} 回（明るさの最大の差 ${r1(rf.biggest * 100)}%）`);
    await rpage.evaluate(() => window.__scene.reset());
    await rpage.click('#start');
    await rpage.waitForFunction(() => window.__scene.state === 'panel', null, { timeout: 2000 });
    await rpage.evaluate(() => history.back());
    await rpage.waitForFunction(() => window.__scene.state === 'surface', null, { timeout: 2000 });
    judge(true, '縮小版', '縮小版でも、戻るで海面へ帰れる（灯の名前を外し、溶け込みだけにする）');
    await rctx.close();

    // ---- 素材の遅れ: scene.js を 1.5 秒遅らせても、押してすぐ灯が動き、短い版で進む
    const lctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, reducedMotion: 'no-preference' });
    const lpage = await lctx.newPage();
    watch(lpage, '素材の遅れ');
    await lpage.route('**/scene.js', async (route) => {
      await sleep(1500);
      await route.continue();
    });
    await lpage.goto(`${origin}/index.html`, { waitUntil: 'domcontentloaded' });
    // ready は背景の準備まで待つので、ここでは台帳を読んで海面に着いたところで押す（利用者が背景より先に押す場面）
    await lpage.waitForFunction(() => window.__scene && window.__scene.state === 'surface', null, { timeout: 5000 });
    const loadedEarly = await lpage.evaluate(() => window.__scene.seaLoaded);
    await installProbe(lpage);
    await pressStart(lpage, 40);
    await lpage.waitForFunction(() => window.__scene.state === 'panel', null, { timeout: 3000 });
    await sleep(60);
    const late = await lpage.evaluate(() => ({ p: window.__probe, version: window.__scene.version }));
    const lateLamp = late.p.firstLamp - late.p.press[0];
    const lateDive = late.p.firstDive - late.p.click;
    judge(!loadedEarly && late.version === 'short' && lateLamp >= 0 && lateLamp <= 100 && lateDive >= 0 && lateDive <= 100, '素材の遅れ', `背景が未着のまま押すと、灯は ${r1(lateLamp)}ms で動き、見せ場は ${r1(lateDive)}ms で ${late.version} の版として動き出す`);
    await lpage.evaluate(() => window.__scene.ready);
    const arrived = await lpage.evaluate(() => window.__scene.seaLoaded && document.querySelector('.sea').classList.contains('is-ready'));
    judge(arrived, '素材の遅れ', '背景はあとから届き、計器盤の場面のまま描き始める');
    await lctx.close();

    // ---- 台帳が読めないとき: ledger.json が 404 でも、演出なしで計器盤へ進み、1 つ目の入力欄に焦点が入る。
    //      404 のコンソールのエラーは想定どおりなので、全体のエラーの数には入れない（例外だけを数える）
    const fctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, reducedMotion: 'no-preference' });
    const fpage = await fctx.newPage();
    const fallbackErrors = [];
    fpage.on('pageerror', (e) => fallbackErrors.push(e.message));
    await fpage.route('**/ledger.json', (route) => route.fulfill({ status: 404, body: '' }));
    await fpage.goto(`${origin}/index.html`);
    await fpage.evaluate(() => window.__scene.ready);
    await fpage.click('#start');
    await fpage.waitForFunction(() => document.documentElement.dataset.scene === 'panel', null, { timeout: 3000 }).catch(() => {});
    const fb = await fpage.evaluate(() => ({
      scene: document.documentElement.dataset.scene,
      active: document.activeElement && document.activeElement.id,
      title: document.title,
      hash: location.hash,
    }));
    judge(fb.scene === 'panel' && fb.active === 'email' && fb.hash === '#panel' && fallbackErrors.length === 0, '台帳が読めないとき', `ledger.json が 404 でも、スタートで ${fb.scene} の場面へ進み、焦点は ${fb.active}、title は「${fb.title}」（例外 ${fallbackErrors.length} 件）`);
    await fctx.close();

    // ---- 幅 375（電話）: 横にはみ出さず、触って始められる
    const pctx = await browser.newContext({ viewport: { width: 375, height: 812 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, reducedMotion: 'no-preference' });
    const ppage = await pctx.newPage();
    watch(ppage, '幅 375');
    await ppage.goto(`${origin}/index.html`);
    await waitScene(ppage);
    const phone = async () =>
      ppage.evaluate(() => {
        const r = (s) => document.querySelector(s).getBoundingClientRect();
        const s = r('#start');
        const c = r('.calm');
        const overlap = !(s.right <= c.left || c.right <= s.left || s.bottom <= c.top || c.bottom <= s.top);
        return { scroll: document.documentElement.scrollWidth, panel: r('.panel'), title: r('.title'), overlap };
      });
    await sleep(500); // 背景の溶け込み（400ms）が終わってから撮る
    const ph1 = await phone();
    save('phone-surface.png', await ppage.screenshot());
    await seek(ppage, 500, 'full');
    save('phone-full-0500.png', await ppage.screenshot());
    await ppage.evaluate(() => window.__scene.reset());
    await ppage.tap('#start');
    await ppage.waitForFunction(() => window.__scene.state === 'panel', null, { timeout: 4000 });
    await sleep(60);
    save('phone-panel.png', await ppage.screenshot());
    const ph2 = await phone();
    judge(ph1.scroll <= 375 && ph2.scroll <= 375 && ph2.panel.left >= 0 && ph2.panel.right <= 375 && ph1.title.left >= 0 && ph1.title.right <= 375 && !ph1.overlap, '幅 375', `横幅 ${ph1.scroll}px・${ph2.scroll}px（375 以内）。題字と計器盤は画面の内側、止めるボタンとスタートは重ならない。触って始められる`);
    await pctx.close();

    // ---- 方向の 3 案（静止画）
    const dctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
    const dpage = await dctx.newPage();
    watch(dpage, '方向の 3 案');
    for (const d of DIRECTIONS) {
      for (const [w, h] of [[1280, 800], [375, 812]]) {
        await dpage.setViewportSize({ width: w, height: h });
        await dpage.goto(`${origin}/directions/${d}.html`);
        await sleep(50);
        const st = await dpage.evaluate(() => ({
          anims: document.getAnimations().length,
          scroll: document.documentElement.scrollWidth,
          h1: document.querySelector('h1') && document.querySelector('h1').textContent.trim(),
          start: document.querySelector('button') && document.querySelector('button').textContent.trim(),
          name: document.querySelector('.note-name') && document.querySelector('.note-name').textContent.trim(),
        }));
        save(`direction-${d}-${w}.png`, await dpage.screenshot());
        judge(st.anims === 0 && st.scroll <= w && st.h1 === '深海の探査日誌' && st.start === '潜航を始める', '方向の 3 案', `${d}（${w}px）: ${st.name}。動き ${st.anims}、横幅 ${st.scroll}px、題字と「${st.start}」がある`);
      }
    }
    await dctx.close();

    // ---- 全体: 外への要求とコンソールのエラー
    const outside = requests.filter((u) => !u.startsWith(origin) && !u.startsWith('data:'));
    judge(outside.length === 0, '外への要求', `要求 ${requests.length} 件がすべて ${origin} の中（外は ${outside.length} 件${outside.length ? `: ${outside.slice(0, 3).join('・')}` : ''}）`);
    judge(errors.length === 0, 'コンソール', errors.length ? `エラー ${errors.length} 件: ${errors.slice(0, 3).join(' / ')}` : 'コンソールのエラーと捕まえていない例外が 0 件（全部の画面と操作を通して）');
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (typeof server.closeAllConnections === 'function') server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
    info('後片付け', 'ブラウザとサーバーを止めた');
  }
}

async function main() {
  const args = process.argv.slice(2);
  const selftest = args.includes('--selftest');
  const at = args.indexOf('--out');
  const out = at >= 0 && args[at + 1] ? path.resolve(args[at + 1]) : null;
  const ledger = JSON.parse(fs.readFileSync(path.join(here, 'ledger.json'), 'utf8'));
  checkLedger(ledger, fs.readFileSync(path.join(here, 'tokens.css'), 'utf8'));
  checkFiles();
  if (!selftest) await checkBrowser(ledger, out);
  if (out && !selftest) info('記録', `フレームと画面: ${out}`);
  console.log(`RESULT: ${tally.fail ? 'FAIL' : 'PASS'} immersive-check${selftest ? ' --selftest' : ''} (PASS ${tally.pass}、FAIL ${tally.fail})`);
  return tally.fail ? 1 : 0;
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (e) => {
    console.log(`FAIL immersive [実行] ${String(e && e.stack ? e.stack : e).split('\n').slice(0, 3).join(' ')}`);
    console.log('RESULT: FAIL immersive-check');
    process.exitCode = 1;
  },
);
