#!/usr/bin/env node
// skills/frontend/scripts/motion-measure.mjs — 没入の型の演出を、画面なしのブラウザで 12 項目測って判定する。
//   対象のページは window.__scene（ledger、play()、seek(ms)、skip()、reset()。任意で ready）を持つ約束にする。
//   約束と台帳の形は skills/frontend/references/immersive.md の 6 節。
//   CPU を等速と 4 倍遅く（CDP の Emulation.setCPUThrottlingRate）の 2 条件で 3 回ずつ回し、項目ごとに悪い側を採る。
//   測った値は記録の JSON に残し、判定は記録だけから出す。記録は --judge で判定し直せる。
// 使い方:
//   node motion-measure.mjs --config <設定.json> [--default-dir <置き場>] [--runs <回数>] [--record <記録.json>]
//   node motion-measure.mjs --dir <置き場> --scene <演出の ID> [--path /] [--runs <回数>] [--record <記録.json>]
//   node motion-measure.mjs --url <http://127.0.0.1:…/> --scene <演出の ID> [...]
//   node motion-measure.mjs --judge <記録.json> [--allow-fictional]   ブラウザを使わず、記録を判定する。
//        架空の記録（browser.fictional）は合格にしない。判定の試験だけ --allow-fictional で許す
//   node motion-measure.mjs <--config か --dir か --url と --scene> --frames <置き場>
//        監修のフレームを撮る。seek(ms, 版) で時刻を止め、初回は 0ms から total_ms まで 100ms ごと、2 回目の短い版も 100ms ごと、
//        縮小版は 0ms・半ば・終わり、ほかに静止の画面と飛ばしたときを 1 枚ずつ PNG で書き、一覧を frames.json に残す
//   node motion-measure.mjs --selftest              組み込みの記録の正例と負例で判定を試す（ブラウザもサーバーも使わない）
// 出力: 落ちた項目の理由を FAIL motion-measure [<番号> <名前>] … の行で出し、項目ごとに 1 行の
//       RESULT: PASS|FAIL motion-measure <番号> <名前>: <数字> を出す。続けて描画の方式と記録の置き場、
//       最後に RESULT: PASS|FAIL motion-measure <演出の ID> (PASS n、FAIL m。…)。1 項目でも FAIL なら終了コード 1、設定の誤りは 2。
// 外のネットワークには出ない。対象は 127.0.0.1・localhost・[::1] だけで、ページが外へ出す要求（HTTP と WebSocket）は止めて数える。
//   Service Worker は止め、ブラウザには届かない代理（127.0.0.1:9）を渡すので、route の外の通信も外へ出ない。
// 記録の置き場は .json で終え、hooks・.claude・.cursor・.git を含めない。設定のファイルの record は、設定の置き場か tmp/.verify の下だけ。
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import zlib from 'node:zlib';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const KIT = path.resolve(HERE, '..', '..', '..');
// 移した先（<プロジェクト>/tmp/skills/…）では、一式の置き場が tmp そのもの。記録は tmp/.verify に置く
export const VERIFY_DIR = path.basename(KIT) === 'tmp' && fs.existsSync(path.join(KIT, 'DEPLOYED.md')) ? path.join(KIT, '.verify') : path.join(KIT, 'tmp', '.verify');
// ブラウザに渡す代理。127.0.0.1 の 9 番（discard）には何も待っていないので、route の外の通信はここで止まる。ループバックは代理を通らない
export const PROXY = { server: 'http://127.0.0.1:9', bypass: '127.0.0.1,localhost,[::1],*.localhost' };
const BAD_SEGMENTS = new Set(['hooks', '.claude', '.cursor', '.git']);

// 予算（案）。最初のサンプルで測って決め直す。値と理由は references/performance-budget.md の「演出の予算」
export const BUDGET = {
  first_frame_ms: 100,
  frame_long_ms: 50,
  frame_slow_ms: 25,
  frame_slow_ratio: 0.05,
  beat_tolerance_ms: 20,
  props: ['transform', 'opacity'],
  skip_ms: 300,
  flash_per_second: 3,
  sound_tolerance_ms: 20,
  initial_js_kb: 170,
  deferred_kb: 600,
  deferred_js_kb: 170,
  ready_ms: 3000,
  ambient_wait_ms: 5000,
  flash_step_ms: 33,
};
export const ITEMS = [
  [1, '最初のフレーム'],
  [2, '拍と長さ'],
  [3, 'フレームの間隔'],
  [4, '長いフレームの原因'],
  [5, '動かす属性'],
  [6, '縮小版'],
  [7, '飛ばす'],
  [8, '焦点と読み上げ'],
  [9, '5 秒を超える動き'],
  [10, '音'],
  [11, '閃光'],
  [12, 'アセットと準備'],
];
const CPUS = [1, 4];
const CONFIG_KEYS = new Set(['scene', 'dir', 'url', 'path', 'viewport', 'record']);
const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.avif': 'image/avif', '.woff2': 'font/woff2',
  '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg', '.wav': 'audio/wav', '.mp4': 'video/mp4', '.webm': 'video/webm',
};

// ---- 小さな道具
const round = (v) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v * 10) / 10 : v);
const kb = (bytes) => Math.round((bytes / 1024) * 10) / 10;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const cpuName = (cpu) => (cpu === 1 ? 'CPU 等速' : `CPU ${cpu} 倍遅い条件`);
const condName = (r) => `${cpuName(r.cpu)}の ${r.run} 回目`;
const maxBy = (list, f) => list.reduce((a, b) => (a === null || f(b) > f(a) ? b : a), null);

export function isLocalHost(hostname) {
  const h = hostname.replace(/^\[|\]$/g, '').toLowerCase();
  return h === '127.0.0.1' || h === 'localhost' || h === '::1' || h.endsWith('.localhost');
}

// 書き込み先の誤り。null なら書いてよい。roots を渡すと、その下だけを許す（設定のファイルに書いた record）。
// hooks などの名前は、プロジェクトの根（一式の置き場か、移した先ではその 1 つ上）の直下で見る。根の外は絶対パスのどの段でも見る
const PROJECT = path.basename(KIT) === 'tmp' && fs.existsSync(path.join(KIT, 'DEPLOYED.md')) ? path.dirname(KIT) : KIT;
export function writeProblem(p, { json = true, roots = null } = {}) {
  const abs = path.resolve(p);
  const rel = path.relative(PROJECT, abs);
  const outside = rel.startsWith('..') || path.isAbsolute(rel);
  const parts = outside ? abs.split(path.sep) : rel.split(path.sep).slice(0, 1);
  if (json && !/\.json$/i.test(abs)) return `記録の置き場は .json で終える: ${p}`;
  if (parts.some((s) => BAD_SEGMENTS.has(s))) return `書き込み先に hooks・.claude・.cursor・.git を含めない: ${p}`;
  if (roots && !roots.some((r) => abs === r || abs.startsWith(`${path.resolve(r)}${path.sep}`))) {
    return `設定の record は、設定の置き場（${roots[0]}）か ${VERIFY_DIR} の下だけ: ${p}`;
  }
  return null;
}

// 外へ出る通信を止めて数える。HTTP は route、WebSocket は routeWebSocket で見る。counter.external に数え、
// counter.requests があれば全部の要求も数える。ローカルの WebSocket はサーバーへつなぎ、そのまま通す
export async function guardContext(context, counter = null) {
  await context.route('**/*', (route) => {
    if (counter && typeof counter.requests === 'number') counter.requests += 1;
    let u;
    try { u = new URL(route.request().url()); } catch (e) { return route.abort(); }
    if (u.protocol === 'data:' || u.protocol === 'blob:' || isLocalHost(u.hostname)) return route.continue();
    if (counter) counter.external += 1;
    return route.abort();
  });
  await context.routeWebSocket(/.*/, (ws) => {
    let local = false;
    try { local = isLocalHost(new URL(ws.url()).hostname); } catch (e) { local = false; }
    if (local) {
      ws.connectToServer();
      return;
    }
    if (counter) counter.external += 1;
    ws.close();
  });
}

// ---- 台帳の別の形をそろえる
// 拍を versions.full.beats に置き、拍ごとに tracks（要素ごとの動き）を持つ形も読む。
// 長さは versions.full・short・reduced の total_ms、終わりの title は focus.title からも取る。
export function normalizeLedger(raw) {
  if (!raw || typeof raw !== 'object') return raw;
  const L = { ...raw };
  const V = raw.versions && typeof raw.versions === 'object' ? raw.versions : null;
  if (L.total_ms === undefined && V && V.full) L.total_ms = V.full.total_ms;
  if (L.short_ms === undefined && V && V.short) L.short_ms = V.short.total_ms;
  if (L.reduced === undefined && V && V.reduced) L.reduced = { ms: V.reduced.total_ms };
  if (L.title === undefined && L.focus && typeof L.focus.title === 'string') L.title = L.focus.title;
  if (!Array.isArray(L.beats) && V && V.full && Array.isArray(V.full.beats)) {
    L.beats = V.full.beats.flatMap((b) => {
      // tracks が空の拍（焦点だけを入れる拍など）は、動きを持たないので数えない
      const tracks = Array.isArray(b.tracks) ? b.tracks : [b];
      return tracks.map((t) => ({
        at_ms: typeof t.at_ms === 'number' ? t.at_ms : b.at_ms,
        target: t.id || t.el || b.target || b.id,
        ms: typeof t.ms === 'number' ? t.ms : b.ms,
        props: t.props || b.props,
        engine: t.engine || b.engine,
        sound: t.sound || b.sound,
      }));
    });
  }
  return L;
}

// ---- 判定（記録だけを読む。ブラウザを使わない）
function matches(anim, target) {
  if (!target) return false;
  // 同じ拍で要素が複数あると、WAAPI の id は「拍の名前#1」のように番号が付く
  if ((anim.keys || []).some((k) => k === target || k.startsWith(`${target}#`))) return true;
  return typeof anim.pseudo === 'string' && anim.pseudo.includes(`(${target})`);
}

const specOk = (s) => !!(s && (s.selector || (s.role && s.name)));
// 動きの呼び名。拍の名前が無い動き（CSS の transition など）は、要素と種類で呼ぶ
const animLabel = (a) => (a.keys || []).find((k) => !(a.props || []).includes(k)) || a.pseudo || `${a.el || '要素の分からない'} の ${a.kind || '動き'}`;
const specName = (s) => (s ? (s.role && s.name ? `${s.role}「${s.name}」` : s.selector || '') : 'なし');

// 回ごとに、拍と動きを組にする。同じ名前の動きが複数あれば、計画の時刻に近い方
function beatMatches(run, beats) {
  const found = new Map();
  for (const b of beats) {
    const cands = (run.animations || []).filter((a) => matches(a, b.target) && typeof a.start_ms === 'number');
    if (cands.length) found.set(b, cands.reduce((x, y) => (Math.abs(y.start_ms - b.at_ms) < Math.abs(x.start_ms - b.at_ms) ? y : x)));
  }
  return found;
}

// 最初の拍（計画の時刻が最も早い拍）が、押してから計画より何 ms 遅れて始まったか。拍どうしの時刻は、このずれを引いて比べる
function anchorOffset(found) {
  let first = null;
  for (const [b, a] of found) if (!first || b.at_ms < first[0].at_ms) first = [b, a];
  return first ? Math.max(0, first[1].start_ms - first[0].at_ms) : 0;
}

function allowedProps(ledger, anim) {
  const beat = (ledger.beats || []).find((b) => !b.engine && matches(anim, b.target));
  const list = (beat && beat.props) || ledger.allowed_props || BUDGET.props;
  const set = new Set(list);
  if (set.has('transform')) ['translate', 'rotate', 'scale'].forEach((p) => set.add(p));
  return set;
}

export function flashesPerSecond(series, step) {
  // WCAG 2.2 の 2.3.1 の一般の閃光を、明るさ（0〜1）の列で数える。反対向きの変化 2 回で 1 回。暗い側が 0.8 未満で、差が 0.1 以上
  const times = [];
  let ref = series[0];
  let dir = 0;
  for (let i = 1; i < series.length; i++) {
    const v = series[i];
    const d = v - ref;
    if (Math.abs(d) >= 0.1 && Math.min(v, ref) < 0.8) {
      const nd = Math.sign(d);
      if (nd !== dir) {
        times.push(i * step);
        dir = nd;
      }
      ref = v;
    } else if ((dir > 0 && v > ref) || (dir < 0 && v < ref)) {
      ref = v;
    }
  }
  let best = 0;
  for (let i = 0; i < times.length; i++) {
    let j = i;
    while (j < times.length && times[j] - times[i] < 1000) j++;
    best = Math.max(best, Math.floor((j - i) / 2));
  }
  return best;
}

function normSnapshot(text, ledger) {
  const meta = [ledger.ambient && ledger.ambient.stop && ledger.ambient.stop.name, ledger.sound && ledger.sound.mute && ledger.sound.mute.name].filter(Boolean);
  return String(text || '')
    .split('\n')
    .filter((l) => l.trim() && !meta.some((m) => l.includes(`"${m}"`)))
    .join('\n');
}

function blocker(rec) {
  if (rec.fatal) return rec.fatal;
  if (!rec.contract || !rec.contract.found) return 'window.__scene が無い';
  if ((rec.contract.missing || []).includes('ledger')) return 'window.__scene.ledger が無い';
  const L = normalizeLedger(rec.ledger) || {};
  const id = L.id || L.transition;
  if (rec.target && rec.target.scene && id !== rec.target.scene) return `演出の ID が違う（設定 ${rec.target.scene}、台帳 ${id || 'なし'}）`;
  if (!specOk(L.trigger)) return '台帳に trigger（押す要素の role と name か、selector）が無い';
  if (!(L.total_ms > 0)) return '台帳に total_ms（か versions.full.total_ms）が無い';
  if (!Array.isArray(rec.runs) || rec.runs.filter((r) => !r.error).length === 0) return `測れた回が無い${rec.runs && rec.runs[0] && rec.runs[0].error ? `（${rec.runs[0].error}）` : ''}`;
  return null;
}

export function judge(rec) {
  const items = [];
  const add = (no, ok, detail, fails = []) => items.push({ no, name: ITEMS[no - 1][1], ok, detail, fails });
  const stop = blocker(rec);
  if (stop) {
    for (const [no] of ITEMS) add(no, false, `測れない（${stop}）`, [stop]);
    return { items, ok: false };
  }
  const L = normalizeLedger(rec.ledger);
  const runs = rec.runs.filter((r) => !r.error);
  const broken = rec.runs.filter((r) => r.error);
  const brokenNote = broken.length ? `。測れなかった回 ${broken.length}（${broken[0].error}）` : '';

  // 1 最初のフレーム
  {
    const bad = runs.filter((r) => typeof r.first_frame_ms !== 'number');
    if (bad.length || broken.length) {
      add(1, false, `測れない回がある（${bad.length ? condName(bad[0]) : broken[0].error}）`, ['押してからのフレームの記録が無い回がある']);
    } else {
      const w = maxBy(runs, (r) => r.first_frame_ms);
      const ok = w.first_frame_ms <= BUDGET.first_frame_ms;
      add(1, ok, `押してから最大 ${round(w.first_frame_ms)}ms（${condName(w)}。予算 ${BUDGET.first_frame_ms}ms）`, ok ? [] : [`${condName(w)}: ${round(w.first_frame_ms)}ms`]);
    }
  }
  // 2 拍と長さ
  {
    const beats = (L.beats || []).filter((b) => !b.engine);
    const engine = (L.beats || []).length - beats.length;
    const fails = [];
    let worst = 0;
    let lag = 0;
    if (!beats.length) fails.push('測れる拍が無い（台帳の拍がすべてエンジンの拍か、拍が無い）');
    for (const r of runs) {
      const found = beatMatches(r, beats);
      for (const b of beats) if (!found.has(b)) fails.push(`${condName(r)}: 拍「${b.target}」の動きが無い`);
      const offset = anchorOffset(found);
      lag = Math.max(lag, offset);
      if (offset > BUDGET.first_frame_ms) fails.push(`${condName(r)}: 最初の拍が、押してから ${round(offset)}ms 遅れて始まる（予算 ${BUDGET.first_frame_ms}ms）`);
      for (const [b, best] of found) {
        const dStart = Math.abs(best.start_ms - offset - b.at_ms);
        const dLen = typeof b.ms === 'number' && typeof best.ms === 'number' ? Math.abs(best.ms - b.ms) : 0;
        worst = Math.max(worst, dStart, dLen);
        if (dStart > BUDGET.beat_tolerance_ms || dLen > BUDGET.beat_tolerance_ms) {
          fails.push(`${condName(r)}: 拍「${b.target}」の始まり ${round(best.start_ms - offset)}ms（計画 ${b.at_ms}ms）、長さ ${round(best.ms)}ms（計画 ${b.ms ?? '－'}ms）`);
        }
      }
    }
    if (broken.length) fails.push(`測れなかった回がある（${broken[0].error}）`);
    const note = engine ? `。エンジンの拍 ${engine} 本は getAnimations で見えないので数えない` : '';
    add(2, fails.length === 0, fails.length ? `${fails.length} 件の差${note}` : `拍 ${beats.length} 本が全部走り、最初の拍に合わせた時刻と長さの差は最大 ${round(worst)}ms（許容 ±${BUDGET.beat_tolerance_ms}ms）。最初の拍は押してから最大 ${round(lag)}ms${note}`, fails);
  }
  // 3 フレームの間隔
  {
    const fails = [];
    const parts = [];
    for (const cpu of CPUS) {
      const rs = runs.filter((r) => r.cpu === cpu);
      if (!rs.length) {
        fails.push(`${cpuName(cpu)}の回が無い`);
        continue;
      }
      let worst = null;
      for (const r of rs) {
        const f = r.frames || [];
        if (f.length < 5) {
          fails.push(`${condName(r)}: フレームの記録が ${f.length} 個しかない`);
          continue;
        }
        const long = f.filter((d) => d > BUDGET.frame_long_ms).length;
        const ratio = f.filter((d) => d > BUDGET.frame_slow_ms).length / f.length;
        const s = { r, long, ratio, max: Math.max(...f), n: f.length };
        if (long > 0) fails.push(`${condName(r)}: ${BUDGET.frame_long_ms}ms 超 ${long} 個（最大 ${round(s.max)}ms）`);
        if (ratio > BUDGET.frame_slow_ratio) fails.push(`${condName(r)}: ${BUDGET.frame_slow_ms}ms 超が ${(ratio * 100).toFixed(1)}%`);
        if (!worst || long > worst.long || (long === worst.long && ratio > worst.ratio)) worst = s;
      }
      if (worst) parts.push(`${cpuName(cpu)}: 最大 ${round(worst.max)}ms、${BUDGET.frame_slow_ms}ms 超 ${(worst.ratio * 100).toFixed(1)}%、${BUDGET.frame_long_ms}ms 超 ${worst.long}（${worst.n} 個）`);
    }
    add(3, fails.length === 0 && !broken.length, `${parts.join('。')}${brokenNote}`, broken.length ? [...fails, `測れなかった回がある（${broken[0].error}）`] : fails);
  }
  // 4 長いフレームの原因
  {
    if (rec.loaf_supported === false) {
      add(4, false, '測れない（このブラウザに Long Animation Frames の記録が無い）', ['LoAF が無い']);
    } else {
      const all = runs.flatMap((r) => (r.loaf || []).map((e) => ({ ...e, r })));
      const causes = all
        .flatMap((e) => (e.scripts || []).map((s) => `${s.source ? path.basename(s.source) : '不明'} の ${s.fn || s.invoker || '処理'} ${s.ms}ms（${condName(e.r)}）`))
        .slice(0, 3);
      const fails = all.map((e) => `${condName(e.r)}: ${round(e.ms)}ms のフレーム${(e.scripts || []).length ? `。原因 ${(e.scripts || []).map((s) => `${s.source ? path.basename(s.source) : '不明'} ${s.ms}ms`).join('、')}` : ''}`);
      if (broken.length) fails.push(`測れなかった回がある（${broken[0].error}）`);
      add(4, fails.length === 0, all.length ? `${all.length} 件。最大 ${round(Math.max(...all.map((e) => e.ms)))}ms。${causes.join('、') || '原因のスクリプトは記録に無い'}` : `${BUDGET.frame_long_ms}ms を超えたフレーム 0 件${brokenNote}`, fails);
    }
  }
  // 5 動かす属性
  {
    const seen = new Map();
    const fails = [];
    for (const r of runs) {
      for (const a of r.animations || []) {
        const key = `${(a.keys || []).join('/')}${a.pseudo || ''}:${(a.props || []).join(',')}`;
        if (seen.has(key)) continue;
        seen.set(key, a);
        const allow = allowedProps(L, a);
        const out = (a.props || []).filter((p) => !allow.has(p));
        if (out.length) fails.push(`${animLabel(a)} が ${out.join('、')} を動かす`);
      }
    }
    const props = [...new Set([...seen.values()].flatMap((a) => a.props || []))];
    add(5, fails.length === 0, fails.length ? `台帳で許した外の属性: ${fails.length} 本` : `動き ${seen.size} 本の属性は ${props.join('、') || 'なし'} で、どれも台帳で許した属性`, fails);
  }
  // 6 縮小版
  {
    const R = rec.reduced;
    if (!R || R.error) {
      add(6, false, `測れない（${R ? R.error : '縮小版の記録が無い'}）`, ['縮小版の記録が無い']);
    } else {
      const moving = (R.animations || []).filter((a) => a.moves);
      const base = runs.find((r) => typeof r.end_snapshot === 'string');
      const same = base ? normSnapshot(R.end_snapshot, L) === normSnapshot(base.end_snapshot, L) : false;
      const focusOk = L.focus ? R.focus_ok === true : true;
      const fails = [];
      if (moving.length) fails.push(`位置の動き ${moving.length} 本: ${moving.slice(0, 3).map(animLabel).join('、')}`);
      if (!base) fails.push('比べる終わりの状態（通常の回）の記録が無い');
      else if (!same) fails.push('終わりの状態が通常の回と違う（読み上げの木が違う）');
      if (!focusOk) fails.push('縮小版で、終わりの焦点が台帳の要素に入らない');
      const still = R.still_diff_px;
      if (typeof still !== 'number') fails.push('縮小版の終わりのあとに、画面が止まったかを測っていない');
      else if (still > 0) fails.push(`縮小版で、終わったあとも画面が動く（1 秒あけた 2 枚の差 ${still}px）`);
      add(6, fails.length === 0, `位置の動き ${moving.length} 本。動き ${(R.animations || []).length} 本。終わりの状態は${same && focusOk ? '通常の回と同じ' : '通常の回と違う'}。終わったあとの 2 枚の差 ${typeof still === 'number' ? still : '－'}px`, fails);
    }
  }
  // 7 飛ばす
  {
    const fails = [];
    let worst = null;
    for (const r of runs) {
      const s = r.skip;
      if (!s || typeof s.end_ms !== 'number') {
        fails.push(`${condName(r)}: キーを押しても終わりの状態に着かない${s && s.error ? `（${s.error}）` : ''}`);
        continue;
      }
      if (!worst || s.end_ms > worst.skip.end_ms) worst = r;
      if (s.end_ms > BUDGET.skip_ms) fails.push(`${condName(r)}: ${round(s.end_ms)}ms`);
    }
    if (broken.length) fails.push(`測れなかった回がある（${broken[0].error}）`);
    const w = worst ? worst.skip : null;
    add(7, fails.length === 0, w ? `${round(w.pressed_at_ms ?? w.at_ms)}ms の時点で ${w.key} を押し、最大 ${round(w.end_ms)}ms で終わりの状態（${condName(worst)}。予算 ${BUDGET.skip_ms}ms）` : '終わりの状態に着いた回が無い', fails);
  }
  // 8 焦点と読み上げ
  {
    const fails = [];
    if (!specOk(L.focus)) fails.push('台帳に focus（終わりに焦点を置く要素の role と name か、selector）が無い');
    for (const r of runs) {
      const e = r.end || {};
      if (specOk(L.focus) && e.focus_ok !== true) fails.push(`${condName(r)}: 焦点が ${specName(L.focus)} に無い（${e.active || '不明'}）`);
      if (L.title && !String(e.title || '').includes(L.title)) fails.push(`${condName(r)}: title が「${e.title}」（台帳の「${L.title}」を含まない）`);
      for (const i of e.inert || []) if (!['absent', 'inert', 'hidden'].includes(i.state)) fails.push(`${condName(r)}: ${i.selector} が操作と読み上げを受けたまま（${i.state}）`);
    }
    if (broken.length) fails.push(`測れなかった回がある（${broken[0].error}）`);
    const parts = [];
    if (specOk(L.focus)) parts.push(`焦点は ${specName(L.focus)}`);
    if (L.title) parts.push(`title は「${L.title}」`);
    if ((L.inert || []).length) parts.push(`${L.inert.join('、')} は操作と読み上げを受けない`);
    add(8, fails.length === 0, fails.length ? `${fails.length} 件の食い違い` : parts.join('。'), fails);
  }
  // 9 5 秒を超える動き
  {
    const A = rec.ambient;
    if (!A || A.error) {
      add(9, false, `測れない（${A ? A.error : '記録が無い'}）`, ['5 秒を超える動きの記録が無い']);
    } else if (!A.moving) {
      add(9, true, `5 秒待ったあと、1 秒あけた 2 枚の差 0px。止める操作は要らない`);
    } else if (!A.stop_found) {
      add(9, false, `5 秒を超えて動く（2 枚の差 ${A.diff_px}px）のに、止める操作が無い`, [`止める操作が見つからない（台帳の ambient.stop: ${specName(A.stop)}）`]);
    } else {
      const ok = A.diff_after_stop_px === 0;
      add(9, ok, `5 秒を超えて動く（差 ${A.diff_px}px）。${specName(A.stop)} を押したあとの 2 枚の差 ${A.diff_after_stop_px}px`, ok ? [] : [`止めたあとも ${A.diff_after_stop_px}px 動く`]);
    }
  }
  // 10 音
  {
    const fails = [];
    const before = runs.reduce((s, r) => s + ((r.sound && r.sound.before_input) || 0), 0);
    const calls = runs.flatMap((r) => (r.sound && r.sound.calls) || []);
    const beats = (L.beats || []).filter((b) => b.sound);
    if (before > 0) fails.push(`操作の前に ${before} 回鳴らした`);
    let worst = 0;
    if (calls.length || beats.length) {
      const M = rec.sound_muted;
      if (!M || !M.mute_found) fails.push(`鳴らすのに、消音の手段が無い（台帳の sound.mute）${M && M.error ? `（${M.error}）` : ''}`);
      else if (M.calls > 0) fails.push(`消音のあとに ${M.calls} 回鳴らした`);
      // 音は押した時刻から測る。押した合図の音は押した瞬間に鳴らし、絵のフレームの遅れには合わせない
      for (const r of runs) {
        for (const b of beats) {
          const cs = ((r.sound && r.sound.calls) || []).filter((c) => typeof c.at_ms === 'number');
          const best = cs.length ? Math.min(...cs.map((c) => Math.abs(c.at_ms - b.at_ms))) : null;
          if (best === null) fails.push(`${condName(r)}: 拍「${b.target}」の音が鳴らない`);
          else {
            worst = Math.max(worst, best);
            if (best > BUDGET.sound_tolerance_ms) fails.push(`${condName(r)}: 拍「${b.target}」の音が ${round(best)}ms ずれる`);
          }
        }
      }
    }
    const muted = rec.sound_muted && rec.sound_muted.mute_found ? `、消音で ${rec.sound_muted.calls} 回` : '';
    const beatNote = beats.length ? `。拍との差は最大 ${round(worst)}ms（許容 ±${BUDGET.sound_tolerance_ms}ms）` : '。台帳の拍に音は無い';
    const detail = calls.length || beats.length ? `鳴らす命令 ${calls.length} 回、操作の前 ${before} 回${muted}${beatNote}` : `鳴らす命令 0 回（音の無い演出）。操作の前 ${before} 回`;
    add(10, fails.length === 0, detail, fails);
  }
  // 11 閃光
  {
    const F = rec.flash;
    if (!F || F.error || !Array.isArray(F.luminance) || F.luminance.length < 2) {
      add(11, false, `測れない（${F && F.error ? F.error : '明るさの記録が無い'}）`, ['閃光の記録が無い']);
    } else {
      const tiles = F.luminance[0].length;
      let max = 0;
      for (let t = 0; t < tiles; t++) max = Math.max(max, flashesPerSecond(F.luminance.map((row) => row[t]), F.step_ms));
      const ok = max <= BUDGET.flash_per_second;
      add(11, ok, `明るさの反転は 1 秒に最大 ${max} 回（${F.luminance.length} 枚を ${F.step_ms}ms ごと、${tiles} 区画。上限 ${BUDGET.flash_per_second} 回）`, ok ? [] : [`1 秒に ${max} 回`]);
    }
  }
  // 12 アセットと準備
  {
    const A = rec.assets;
    if (!A || A.error) {
      add(12, false, `測れない（${A ? A.error : 'アセットの記録が無い'}）`, ['アセットの記録が無い']);
    } else {
      const sum = (f) => kb((A.list || []).filter(f).reduce((s, x) => s + (x.br_bytes || 0), 0));
      const isJs = (x) => x.type === 'script' || /\.m?js(\?|$)/.test(x.url || '');
      const initJs = sum((x) => x.phase === 'initial' && isJs(x));
      const defAll = sum((x) => x.phase === 'deferred');
      const defJs = sum((x) => x.phase === 'deferred' && isJs(x));
      const readies = runs.map((r) => r.ready_ms);
      const ready = readies.every((v) => typeof v === 'number') ? Math.max(...readies) : null;
      const fails = [];
      if (initJs > BUDGET.initial_js_kb) fails.push(`初期表示の JS ${initJs}KB（予算 ${BUDGET.initial_js_kb}KB）`);
      if (defAll > BUDGET.deferred_kb) fails.push(`演出のアセット ${defAll}KB（予算 ${BUDGET.deferred_kb}KB）`);
      if (defJs > BUDGET.deferred_js_kb) fails.push(`演出の JS ${defJs}KB（予算 ${BUDGET.deferred_js_kb}KB）`);
      if ((A.external || 0) > 0) fails.push(`外への要求 ${A.external} 件（止めて数えた）`);
      if (ready === null) fails.push('準備の完了を測れない回がある');
      else if (ready > BUDGET.ready_ms) fails.push(`準備に ${round(ready / 1000)} 秒（予算 ${BUDGET.ready_ms / 1000} 秒）`);
      add(12, fails.length === 0, `初期表示の JS ${initJs}KB、演出のアセット ${defAll}KB（うち JS ${defJs}KB。brotli 後）、外への要求 ${A.external || 0} 件、準備 ${ready === null ? '－' : round(ready / 1000)} 秒`, fails);
    }
  }
  return { items, ok: items.every((i) => i.ok) };
}

function renderLine(rec) {
  const b = rec.browser || {};
  if (b.fictional) return '描画: 架空の記録（判定の試験用。ブラウザでは測っていない）';
  const gl = b.webgl_renderer ? `WebGL は ${b.webgl_renderer}${b.software ? '（ソフトウェア描画）' : ''}` : 'WebGL は使えない';
  return `描画: 画面なしのブラウザ（Chromium ${b.version || '不明'}、headless）で測った。${gl}。GPU での滑らかさは未確認`;
}

// 架空の記録（判定の試験用）は、allowFictional を渡したときだけ合格にできる。測っていない記録で PASS を出さない
export function report(rec, recordPath, print = console.log, { allowFictional = false } = {}) {
  const res = judge(rec);
  for (const it of res.items) {
    if (!it.ok) for (const f of it.fails.slice(0, 4)) print(`FAIL motion-measure [${it.no} ${it.name}] ${f}`);
    print(`RESULT: ${it.ok ? 'PASS' : 'FAIL'} motion-measure ${it.no} ${it.name}: ${it.detail}`);
  }
  const n = res.items.filter((i) => i.ok).length;
  const runs = rec.runs ? rec.runs.length : 0;
  const fictional = Boolean((rec.browser || {}).fictional);
  print(renderLine(rec));
  if (recordPath) print(`記録: ${recordPath}${rec.note ? `（${rec.note}）` : ''}`);
  if (fictional && !allowFictional) print('FAIL motion-measure [記録] 架空の記録（browser.fictional）は合格にしない。判定の試験だけ --allow-fictional で許す');
  const scene = (rec.target && rec.target.scene) || '不明';
  const how = fictional ? '架空の記録' : `${CPUS.length} 条件で計 ${runs} 回の悪い側。画面なしのブラウザ`;
  const ok = res.ok && (!fictional || allowFictional);
  print(`RESULT: ${ok ? 'PASS' : 'FAIL'} motion-measure ${scene} (PASS ${n}、FAIL ${res.items.length - n}。${how})`);
  return ok;
}

// ---- 計測（ブラウザ）
// ページの中で動く道具。ページのスクリプトより先に入れ、入力・フレーム・動き・音・LoAF を記録する
function probe() {
  const W = window;
  if (W.__motionMeasure) return;
  const st = {
    armed: false, t0: null, frames: [], last: null, anims: new Map(), events: [], loaf: [], sound: [],
    rafFirst: null, keyT: null, focusT: null, zeroT: null, doneT: null, lastMut: 0, fcp: null, lcp: null,
    sceneAt: null, readyAt: null, readyKind: 'none', loafSupported: false,
  };
  const POS = new Set(['transform', 'translate', 'rotate', 'scale', 'top', 'left', 'right', 'bottom', 'inset', 'margin', 'margin-top', 'margin-left', 'margin-right', 'margin-bottom', 'width', 'height', 'offset-distance', 'offset-path', 'x', 'y', 'background-position']);
  const kebab = (p) => p.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
  const now = () => performance.now();
  const log = (kind, at) => {
    const active = !!(navigator.userActivation && navigator.userActivation.hasBeenActive);
    st.sound.push({ t: now(), at: at === undefined ? now() : at, kind, active });
  };
  try {
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function (...args) {
      if (!this.muted && this.volume > 0) log('media.play');
      return play.apply(this, args);
    };
  } catch (e) { /* 無い環境では記録しない */ }
  try {
    const proto = W.AudioScheduledSourceNode && W.AudioScheduledSourceNode.prototype;
    if (proto) {
      const start = proto.start;
      proto.start = function (when, ...rest) {
        try {
          const lead = Math.max(0, (when || 0) - this.context.currentTime) * 1000;
          log('audio.start', now() + lead);
        } catch (e) { log('audio.start'); }
        return start.call(this, when, ...rest);
      };
    }
  } catch (e) { /* 無い環境では記録しない */ }
  const observe = (type, opts, cb) => {
    try {
      new PerformanceObserver((list) => list.getEntries().forEach(cb)).observe({ type, buffered: true, ...opts });
      return true;
    } catch (e) { return false; }
  };
  st.loafSupported = (PerformanceObserver.supportedEntryTypes || []).includes('long-animation-frame');
  observe('event', { durationThreshold: 16 }, (e) => st.events.push({ name: e.name, start: e.startTime, dur: e.duration }));
  if (st.loafSupported) {
    observe('long-animation-frame', {}, (e) => st.loaf.push({
      start: e.startTime, ms: e.duration,
      scripts: (e.scripts || []).slice(0, 5).map((s) => ({ source: s.sourceURL || '', fn: s.sourceFunctionName || '', invoker: s.invoker || '', ms: Math.round(s.duration) })),
    }));
  }
  observe('largest-contentful-paint', {}, (e) => { st.lcp = e.startTime; });
  observe('paint', {}, (e) => { if (e.name === 'first-contentful-paint') st.fcp = e.startTime; });
  // __scene が置かれた時刻と、ready が解決した時刻を取る
  let scene;
  try {
    Object.defineProperty(W, '__scene', {
      configurable: true, enumerable: true,
      get() { return scene; },
      set(v) {
        scene = v;
        st.sceneAt = now();
        if (v && v.ready && typeof v.ready.then === 'function') {
          st.readyKind = 'promise';
          v.ready.then(() => { st.readyAt = now(); }, () => { st.readyAt = now(); });
        } else st.readyAt = st.sceneAt;
      },
    });
  } catch (e) { /* 置けなければ、ready() の中で待つ */ }
  W.addEventListener('pointerdown', (e) => {
    if (!st.armed || st.t0 !== null) return;
    st.t0 = e.timeStamp;
    requestAnimationFrame((t) => { st.rafFirst = t - e.timeStamp; });
  }, true);
  W.addEventListener('keydown', (e) => { if (st.armed && st.t0 !== null && st.keyT === null) st.keyT = e.timeStamp; }, true);
  W.addEventListener('focusin', () => { st.focusT = now(); }, true);
  // DOM の最後の書き換えの時刻。終わりの状態（inert、hidden、title など）が落ち着いたかを見る。style の属性は動きなので数えない
  try {
    new MutationObserver((list) => {
      if (list.some((m) => !(m.type === 'attributes' && m.attributeName === 'style'))) st.lastMut = now();
    }).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
  } catch (e) { /* 見られなければ、動きが止んだ時刻だけで決める */ }
  const finiteRunning = () => document.getAnimations().filter((a) => {
    if (a.playState !== 'running') return false;
    try { return Number.isFinite(a.effect.getComputedTiming().endTime); } catch (e) { return false; }
  }).length;
  const describe = (a) => {
    const eff = a.effect || {};
    const tgt = eff.target || null;
    let kf = [];
    try { kf = eff.getKeyframes(); } catch (e) { kf = []; }
    const skip = new Set(['offset', 'computedOffset', 'easing', 'composite']);
    const keys = [...new Set(kf.flatMap((k) => Object.keys(k)).filter((p) => !skip.has(p)))];
    const props = keys.map(kebab);
    const moves = keys.some((k) => POS.has(kebab(k)) && new Set(kf.map((f) => String(f[k] === undefined ? '' : f[k]))).size > 1);
    let timing = {};
    let comp = {};
    try { timing = eff.getTiming(); comp = eff.getComputedTiming(); } catch (e) { /* 時刻の無い動き */ }
    const pseudo = eff.pseudoElement || '';
    const names = [tgt && tgt.id, tgt && tgt.dataset && tgt.dataset.beat, a.id, a.animationName, a.transitionProperty];
    const m = /\(([^)]+)\)/.exec(pseudo);
    if (m) names.push(m[1]);
    return {
      keys: [...new Set(names.filter(Boolean))], pseudo, props, moves, delay: timing.delay || 0,
      el: tgt ? `${tgt.tagName.toLowerCase()}${tgt.id ? `#${tgt.id}` : ''}${tgt.classList && tgt.classList[0] ? `.${tgt.classList[0]}` : ''}` : '',
      kind: a.constructor && a.constructor.name ? a.constructor.name : 'Animation',
      ms: Number.isFinite(comp.activeDuration) ? comp.activeDuration : null,
      infinite: comp.activeDuration === Infinity || timing.iterations === Infinity, start: null, anim: a,
    };
  };
  const capture = () => {
    for (const a of document.getAnimations()) {
      if (!st.anims.has(a)) {
        if (st.anims.size >= 200) break;
        st.anims.set(a, describe(a));
      }
      const r = st.anims.get(a);
      if (r && r.start === null && a.startTime !== null) r.start = a.startTime + r.delay;
    }
  };
  const loop = (t) => {
    if (!st.armed) return;
    if (st.last !== null) st.frames.push([t, t - st.last]);
    st.last = t;
    capture();
    if (finiteRunning() === 0) { if (st.zeroT === null) st.zeroT = now(); } else st.zeroT = null;
    requestAnimationFrame(loop);
  };
  W.__motionMeasure = {
    async ready(timeout) {
      const begin = now();
      while (!W.__scene && now() - begin < timeout) await new Promise((r) => setTimeout(r, 25));
      const s = W.__scene;
      if (!s) return { found: false, missing: ['__scene'] };
      // 台帳を ready のあとで読み込むページがあるので、ready を待ってから中身を確かめる
      if (s.ready && typeof s.ready.then === 'function') {
        st.readyKind = 'promise';
        await Promise.race([s.ready.then(() => { if (st.readyAt === null || st.readyAt < st.sceneAt) st.readyAt = now(); }, () => {}), new Promise((r) => setTimeout(r, timeout))]);
      }
      const missing = [];
      if (!s.ledger || typeof s.ledger !== 'object') missing.push('ledger');
      for (const k of ['play', 'seek', 'skip', 'reset']) if (typeof s[k] !== 'function') missing.push(k);
      if (st.readyAt === null) st.readyAt = st.sceneAt === null ? now() : st.sceneAt;
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      let ledger = null;
      try { ledger = JSON.parse(JSON.stringify(s.ledger)); } catch (e) { missing.push('ledger'); }
      return {
        found: true, missing, ready: st.readyKind, ready_ms: st.readyAt - (st.fcp || 0), fcp: st.fcp, lcp: st.lcp,
        ledger, loaf_supported: st.loafSupported,
      };
    },
    arm() {
      Object.assign(st, { armed: true, t0: null, frames: [], last: null, anims: new Map(), rafFirst: null, keyT: null, zeroT: null, doneT: null });
      requestAnimationFrame(loop);
    },
    // 終わり: min ms が過ぎ、長さのある動きが全部止み、DOM の書き換えが 150ms 止んだ（2 秒待っても止まなければ、そこで終わりとみなす）
    ended(min) {
      const t = now();
      if (st.t0 === null || t - st.t0 < min || st.zeroT === null) return false;
      if (t - st.lastMut < 150 && t - st.t0 < min + 2000) return false;
      if (st.doneT === null) st.doneT = t;
      return true;
    },
    // 飛ばした後の終わり: キーのあと、動きが止み、DOM の書き換えが止んだ。終わりの時刻は、そのうち遅い方
    skipped() {
      const t = now();
      if (st.keyT === null || st.zeroT === null) return false;
      if (t - st.lastMut < 150 && t - st.keyT < 2000) return false;
      st.doneT = Math.max(st.keyT, st.zeroT, st.lastMut > st.keyT ? st.lastMut : 0);
      return true;
    },
    times() { return { t0: st.t0, keyT: st.keyT, focusT: st.focusT, doneT: st.doneT, zeroT: st.zeroT }; },
    collect() {
      st.armed = false;
      const t0 = st.t0;
      const rel = (v) => (v === null || t0 === null ? null : Math.round((v - t0) * 10) / 10);
      const frames = st.frames.filter(([t]) => t0 !== null && t >= t0).map(([, d]) => Math.round(d * 10) / 10);
      const animations = [...st.anims.values()].map((r) => ({
        keys: r.keys, pseudo: r.pseudo, el: r.el, kind: r.kind, props: r.props, moves: r.moves, start_ms: rel(r.start),
        ms: r.ms === null ? null : Math.round(r.ms * 10) / 10, infinite: r.infinite,
      }));
      const ev = st.events.filter((e) => t0 !== null && e.start >= t0 - 1 && e.start <= t0 + 100 && ['pointerdown', 'pointerup', 'click', 'mousedown', 'mouseup'].includes(e.name));
      const first = ev.length ? Math.max(...ev.map((e) => e.dur)) : st.rafFirst;
      const end = st.doneT === null ? now() : st.doneT;
      const loaf = st.loaf.filter((e) => t0 !== null && e.start + e.ms >= t0 && e.start <= end).map((e) => ({ ms: Math.round(e.ms), scripts: e.scripts }));
      const calls = st.sound.filter((c) => t0 !== null && c.t >= t0).map((c) => ({ at_ms: rel(c.at), kind: c.kind }));
      const before = st.sound.filter((c) => t0 === null || c.t < t0 || !c.active).length;
      return {
        first_frame_ms: first === null ? null : Math.round(first * 10) / 10, first_frame_source: ev.length ? 'event-timing' : 'raf',
        frames, animations, loaf, sound: { before_input: before, calls },
      };
    },
    soundCount() { return st.sound.length; },
    webgl() {
      try {
        const gl = document.createElement('canvas').getContext('webgl');
        if (!gl) return null;
        const ext = gl.getExtension('WEBGL_debug_renderer_info');
        return String(ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
      } catch (e) { return null; }
    },
  };
}

// 画像の比較と明るさ。about:blank のページで、PNG と JPEG を canvas に描いて数える
async function pixelDiff(helper, a, b) {
  return helper.evaluate(async ([x, y]) => {
    const load = async (b64) => createImageBitmap(await (await fetch(`data:image/png;base64,${b64}`)).blob());
    const [p, q] = [await load(x), await load(y)];
    if (p.width !== q.width || p.height !== q.height) return p.width * p.height;
    const read = (img) => {
      const c = new OffscreenCanvas(img.width, img.height);
      const g = c.getContext('2d');
      g.drawImage(img, 0, 0);
      return g.getImageData(0, 0, img.width, img.height).data;
    };
    const [d1, d2] = [read(p), read(q)];
    let n = 0;
    for (let i = 0; i < d1.length; i += 4) if (d1[i] !== d2[i] || d1[i + 1] !== d2[i + 1] || d1[i + 2] !== d2[i + 2]) n++;
    return n;
  }, [a.toString('base64'), b.toString('base64')]);
}

async function tileLuminance(helper, shots) {
  return helper.evaluate(async (list) => {
    const lin = (c) => { const s = c / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
    const out = [];
    for (const b64 of list) {
      const img = await createImageBitmap(await (await fetch(`data:image/jpeg;base64,${b64}`)).blob());
      const w = 64;
      const h = 40;
      const c = new OffscreenCanvas(w, h);
      const g = c.getContext('2d');
      g.drawImage(img, 0, 0, w, h);
      const d = g.getImageData(0, 0, w, h).data;
      const tiles = new Array(16).fill(0);
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          const i = (y * w + x) * 4;
          const l = 0.2126 * lin(d[i]) + 0.7152 * lin(d[i + 1]) + 0.0722 * lin(d[i + 2]);
          tiles[Math.floor(y / (h / 4)) * 4 + Math.floor(x / (w / 4))] += l;
        }
      }
      out.push(tiles.map((s) => Math.round((s / ((w / 4) * (h / 4))) * 1000) / 1000));
    }
    return out;
  }, shots.map((s) => s.toString('base64')));
}

function serve(dir) {
  const root = path.resolve(dir);
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      let p = '/';
      try { p = decodeURIComponent(new URL(req.url, 'http://local').pathname); } catch (e) { p = '/'; }
      if (p.endsWith('/')) p += 'index.html';
      const file = path.resolve(root, `.${path.normalize(p)}`);
      const rel = path.relative(root, file);
      if (rel.startsWith('..') || path.isAbsolute(rel) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
        res.writeHead(404);
        res.end();
        return;
      }
      res.writeHead(200, { 'content-type': TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream', 'cache-control': 'no-store' });
      fs.createReadStream(file).pipe(res);
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

function loadPlaywright() {
  const require = createRequire(import.meta.url);
  return require('playwright');
}

async function openPage(browser, url, cfg, { cpu = 1, reduced = false, assets = null } = {}) {
  // Service Worker は route を通らずに要求を出せるので止める
  const context = await browser.newContext({ viewport: cfg.viewport, reducedMotion: reduced ? 'reduce' : 'no-preference', serviceWorkers: 'block' });
  await guardContext(context, assets);
  await context.addInitScript(probe);
  const page = await context.newPage();
  if (assets) {
    page.on('response', (resp) => {
      const u = resp.url();
      if (assets.closed || !/^https?:/.test(u)) return;
      assets.pending.push(resp.body().then((body) => {
        assets.bodies.set(u, { type: resp.request().resourceType(), bytes: body.length, br_bytes: zlib.brotliCompressSync(body).length });
      }, () => {}));
    });
  }
  const cdp = await context.newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: cpu });
  await page.goto(url, { waitUntil: 'load', timeout: 20000 });
  return { context, page };
}

// 台帳の要素の指し方は 2 つ: role と name（読み上げの木で探す）か、selector（CSS のセレクタ）
const byRole = (page, spec) => (spec.selector ? page.locator(spec.selector) : page.getByRole(spec.role, { name: spec.name, exact: true })).first();

// 押す: 人と同じく、先にポインターを要素の上へ動かし、2 フレーム待ってから押して離す。locator.click は押す直前に
// Playwright の台本をページで回すので、CPU を 4 倍遅くした条件では、その仕事の遅れが押した直後のフレームに乗る
// （2026-11-26 のトレースで、11〜12ms の台本が押す 25〜30ms 前に走り、押した直後のフレームが 53〜73ms になった。
// 先に動かして 2 フレーム待つと、同じ見本で 12 回中 0 回。判定の線は変えていない）
async function press(page, spec) {
  const loc = byRole(page, spec);
  await loc.waitFor({ state: 'visible', timeout: 5000 });
  await loc.scrollIntoViewIfNeeded({ timeout: 5000 });
  const box = await loc.boundingBox();
  if (!box) throw new Error(`押す要素 ${specName(spec)} の位置が取れない`);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.evaluate(() => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res))));
  await page.mouse.down();
  await page.mouse.up();
}

async function focusOn(page, spec, waitMs) {
  if (!spec) return null;
  const until = Date.now() + waitMs;
  for (;;) {
    const ok = await byRole(page, spec).evaluate((el) => el === document.activeElement).catch(() => false);
    if (ok || Date.now() > until) return ok;
    await sleep(20);
  }
}

async function activeName(page) {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return 'body';
    return `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}「${(el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 20)}」`;
  }).catch(() => '不明');
}

async function oneRun(browser, url, cfg, ledger, cpu, run, extra) {
  const r = { cpu, run };
  let context;
  try {
    const opened = await openPage(browser, url, cfg, { cpu, assets: extra.assets });
    context = opened.context;
    const { page } = opened;
    const ready = await page.evaluate((ms) => window.__motionMeasure.ready(ms), 10000);
    if (extra.onReady) await extra.onReady(page, ready);
    if (!ready.found || ready.missing.includes('ledger')) throw new Error('window.__scene か ledger が無い');
    ledger = ledger || normalizeLedger(ready.ledger);
    r.ready_ms = Math.max(0, Math.round(ready.ready_ms));
    await page.evaluate(() => window.__motionMeasure.arm());
    await press(page, ledger.trigger);
    await page.waitForFunction((min) => window.__motionMeasure.ended(min), ledger.total_ms, { polling: 'raf', timeout: ledger.total_ms + 8000 });
    Object.assign(r, await page.evaluate(() => window.__motionMeasure.collect()));
    r.end = {
      focus_ok: await focusOn(page, ledger.focus, 500),
      active: await activeName(page),
      title: await page.title(),
      inert: [],
    };
    for (const selector of ledger.inert || []) {
      const state = await page.evaluate((sel) => {
        const el = document.querySelector(sel);
        if (!el) return 'absent';
        if (el.closest('[inert]')) return 'inert';
        const cs = getComputedStyle(el);
        if (el.hidden || cs.display === 'none' || cs.visibility === 'hidden') return 'hidden';
        return el.closest('[aria-hidden="true"]') ? 'aria-hidden' : 'live';
      }, selector).catch(() => 'error');
      r.end.inert.push({ selector, state });
    }
    if (extra.snapshot) r.end_snapshot = await page.locator('body').ariaSnapshot().catch(() => '');
    if (extra.onEnd) await extra.onEnd(page);
    // 飛ばす: 最初の状態に戻し、もう一度押して、途中でキーを押す
    const skip = ledger.skip || {};
    const key = skip.key || 'Enter';
    const at = typeof skip.at_ms === 'number' ? skip.at_ms : 200;
    r.skip = { key, at_ms: at, end_ms: null };
    try {
      await page.evaluate(() => window.__scene.reset());
      await page.evaluate(() => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res))));
      await page.evaluate(() => window.__motionMeasure.arm());
      await press(page, ledger.trigger);
      await sleep(at);
      await page.keyboard.press(key);
      await page.waitForFunction(() => window.__motionMeasure.skipped(), null, { polling: 'raf', timeout: 3000 });
      const focused = await focusOn(page, ledger.focus, 1000);
      const t = await page.evaluate(() => window.__motionMeasure.times());
      r.skip.pressed_at_ms = Math.round((t.keyT - t.t0) * 10) / 10;
      if (focused !== false) {
        const endT = Math.max(t.doneT, t.focusT !== null && t.focusT > t.keyT ? t.focusT : 0);
        r.skip.end_ms = Math.round((endT - t.keyT) * 10) / 10;
      } else r.skip.error = '焦点が台帳の要素に入らない';
      await page.evaluate(() => window.__motionMeasure.collect());
    } catch (e) {
      r.skip.error = String(e.message || e).split('\n')[0];
    }
  } catch (e) {
    r.error = String(e.message || e).split('\n')[0];
  } finally {
    if (context) await context.close().catch(() => {});
  }
  return r;
}

async function measure(cfg) {
  const rec = {
    tool: 'motion-measure', version: 1, measured_at: new Date().toISOString(),
    target: { scene: cfg.scene, url: cfg.url || null, dir: cfg.dir || null },
    browser: {}, viewport: cfg.viewport, budget: BUDGET, contract: null, ledger: null, loaf_supported: null,
    runs: [], reduced: null, ambient: null, sound_muted: null, flash: null, assets: null,
  };
  let server = null;
  let browser = null;
  try {
    let url = cfg.url;
    if (cfg.dir) {
      server = await serve(cfg.dir);
      url = `http://127.0.0.1:${server.address().port}${cfg.path || '/'}`;
    }
    rec.target.url = url;
    let chromium;
    try {
      ({ chromium } = loadPlaywright());
    } catch (e) {
      rec.fatal = `Playwright が無い（一式の node_modules を使う）: ${String(e.message).split('\n')[0]}`;
      return rec;
    }
    browser = await chromium.launch({ headless: true, proxy: PROXY });
    rec.browser = { name: 'chromium', version: browser.version(), headless: true };
    // 1 回目のページで、約束と台帳を読む
    const assets = { external: 0, pending: [], bodies: new Map() };
    let ledger = null;
    const first = await oneRun(browser, url, cfg, null, 1, 1, {
      assets,
      snapshot: true,
      onReady: async (page, ready) => {
        rec.contract = { found: ready.found, missing: ready.missing || [], ready: ready.ready || 'none' };
        rec.loaf_supported = ready.loaf_supported === undefined ? null : ready.loaf_supported;
        // 記録には、そろえた台帳を残す。元の形が違えば、元の台帳も残す
        ledger = normalizeLedger(ready.ledger || null);
        rec.ledger = ledger;
        if (ready.ledger && JSON.stringify(ready.ledger) !== JSON.stringify(ledger)) rec.ledger_raw = ready.ledger;
        const renderer = await page.evaluate(() => window.__motionMeasure.webgl());
        rec.browser.webgl_renderer = renderer;
        rec.browser.software = renderer ? /swiftshader|llvmpipe|software/i.test(renderer) : null;
        assets.fcp = ready.fcp;
        assets.lcp = ready.lcp;
        const id = ledger && (ledger.id || ledger.transition);
        if (!ready.found) throw new Error('window.__scene が無い');
        if (id !== cfg.scene) throw new Error(`演出の ID が違う（設定 ${cfg.scene}、台帳 ${id || 'なし'}）`);
        if (!specOk(ledger.trigger)) throw new Error('台帳に trigger（role と name か、selector）が無い');
        if (!(ledger.total_ms > 0)) throw new Error('台帳に total_ms（か versions.full.total_ms）が無い');
      },
      onEnd: async (page) => {
        const entries = await page.evaluate(() => performance.getEntriesByType('resource').map((e) => ({ name: e.name, start: e.startTime })));
        assets.entries = entries;
        assets.closed = true;  // 2 回目の再生（飛ばすの試験）で頼んだ物は数えない
      },
    });
    rec.runs.push(first);
    if (first.error) return rec;  // 約束か台帳が欠けている。残りの回も同じ理由で測れない
    // アセット: LCP より前に頼んだ物を初期、後の物を演出の分として、brotli 後の大きさで数える
    await Promise.allSettled(assets.pending);
    const startOf = new Map((assets.entries || []).map((e) => [e.name, e.start]));
    const lcp = typeof assets.lcp === 'number' ? assets.lcp : null;
    rec.assets = {
      lcp_ms: lcp === null ? null : Math.round(lcp), fcp_ms: assets.fcp === null ? null : Math.round(assets.fcp), external: assets.external,
      list: [...assets.bodies.entries()].map(([u, b]) => {
        const start = startOf.has(u) ? startOf.get(u) : null;
        const phase = start === null || lcp === null || start <= lcp ? 'initial' : 'deferred';
        return { url: u.replace(url.replace(/\/[^/]*$/, ''), ''), type: b.type, bytes: b.bytes, br_bytes: b.br_bytes, phase, start_ms: start === null ? null : Math.round(start) };
      }),
    };
    if (lcp === null) rec.assets.error = 'LCP が記録されない';
    for (const cpu of CPUS) {
      for (let run = 1; run <= cfg.runs; run++) {
        if (cpu === 1 && run === 1) continue;
        rec.runs.push(await oneRun(browser, url, cfg, ledger, cpu, run, {}));
      }
    }
    // 縮小版
    rec.reduced = await (async () => {
      let context;
      try {
        const o = await openPage(browser, url, cfg, { reduced: true });
        context = o.context;
        const { page } = o;
        const ready = await page.evaluate((ms) => window.__motionMeasure.ready(ms), 10000);
        if (!ready.found) throw new Error('window.__scene が無い');
        await page.evaluate(() => window.__motionMeasure.arm());
        await press(page, ledger.trigger);
        // 拍の間に動きの無い時間があっても途中で止めないよう、焦点が入るのを待ってから、動きが止むのを待つ
        const min = ledger.reduced && typeof ledger.reduced.ms === 'number' ? ledger.reduced.ms : 0;
        await page.waitForFunction((m) => window.__motionMeasure.ended(m), min, { polling: 'raf', timeout: ledger.total_ms + 8000 });
        const focus_ok = await focusOn(page, ledger.focus, ledger.total_ms + 2000);
        await page.waitForFunction(() => window.__motionMeasure.ended(0), null, { polling: 'raf', timeout: ledger.total_ms + 8000 });
        await sleep(100);
        const got = await page.evaluate(() => window.__motionMeasure.collect());
        const endSnapshot = await page.locator('body').ariaSnapshot().catch(() => '');
        // 終わったあとも画面が動いていないか。canvas の動きは getAnimations に出ないので、絵で比べる
        const a = await page.screenshot({ type: 'png' });
        await sleep(1000);
        const b = await page.screenshot({ type: 'png' });
        const still = await pixelDiff(await context.newPage(), a, b);
        return { animations: got.animations, focus_ok, end_snapshot: endSnapshot, still_diff_px: still };
      } catch (e) {
        return { error: String(e.message || e).split('\n')[0] };
      } finally {
        if (context) await context.close().catch(() => {});
      }
    })();
    // 5 秒を超える動き、閃光、消音: 等速の 1 ページで続けて測る
    {
      let context;
      try {
        const o = await openPage(browser, url, cfg, {});
        context = o.context;
        const { page } = o;
        await page.evaluate((ms) => window.__motionMeasure.ready(ms), 10000);
        const helper = await context.newPage();
        // 閃光: 時刻を巻いて撮り、区画ごとの明るさを並べる
        try {
          await page.evaluate(() => window.__scene.reset());
          const shots = [];
          for (let t = 0; t <= ledger.total_ms; t += BUDGET.flash_step_ms) {
            await page.evaluate((ms) => window.__scene.seek(ms), t);
            await page.evaluate(() => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res))));
            shots.push(await page.screenshot({ type: 'jpeg', quality: 80 }));
          }
          rec.flash = { step_ms: BUDGET.flash_step_ms, luminance: await tileLuminance(helper, shots) };
        } catch (e) {
          rec.flash = { error: String(e.message || e).split('\n')[0] };
        }
        // 5 秒を超える動き: 終わりの状態へ進めて 5 秒待ち、1 秒あけた 2 枚を比べる
        try {
          await page.evaluate(async () => { await window.__scene.reset(); await window.__scene.play(); await window.__scene.skip(); });
          await sleep(BUDGET.ambient_wait_ms);
          const a = await page.screenshot({ type: 'png' });
          await sleep(1000);
          const b = await page.screenshot({ type: 'png' });
          const diff = await pixelDiff(helper, a, b);
          const stop = ledger.ambient && ledger.ambient.stop ? ledger.ambient.stop : null;
          rec.ambient = { moving: diff > 0, diff_px: diff, stop, stop_found: false, diff_after_stop_px: null };
          if (diff > 0 && stop) {
            const loc = byRole(page, stop);
            rec.ambient.stop_found = (await loc.count()) > 0;
            if (rec.ambient.stop_found) {
              await loc.click({ force: true, timeout: 5000 });
              await sleep(300);
              const c = await page.screenshot({ type: 'png' });
              await sleep(1000);
              const d = await page.screenshot({ type: 'png' });
              rec.ambient.diff_after_stop_px = await pixelDiff(helper, c, d);
            }
          }
        } catch (e) {
          rec.ambient = { error: String(e.message || e).split('\n')[0] };
        }
      } catch (e) {
        const msg = String(e.message || e).split('\n')[0];
        rec.flash = rec.flash || { error: msg };
        rec.ambient = rec.ambient || { error: msg };
      } finally {
        if (context) await context.close().catch(() => {});
      }
    }
    // 消音: 鳴らす演出だけ。消音の操作を押してから演出を流し、鳴らす命令を数える
    const sounds = rec.runs.some((r) => r.sound && r.sound.calls && r.sound.calls.length) || (ledger.beats || []).some((b) => b.sound);
    if (sounds) {
      let context;
      const mute = ledger.sound && ledger.sound.mute ? ledger.sound.mute : null;
      try {
        if (!mute) throw new Error('台帳に sound.mute が無い');
        const o = await openPage(browser, url, cfg, {});
        context = o.context;
        const { page } = o;
        await page.evaluate((ms) => window.__motionMeasure.ready(ms), 10000);
        const loc = byRole(page, mute);
        if ((await loc.count()) === 0) throw new Error(`消音の操作 ${specName(mute)} が無い`);
        await loc.click({ force: true, timeout: 5000 });
        const before = await page.evaluate(() => window.__motionMeasure.soundCount());
        await page.evaluate(() => window.__motionMeasure.arm());
        await press(page, ledger.trigger);
        await page.waitForFunction((min) => window.__motionMeasure.ended(min), ledger.total_ms, { polling: 'raf', timeout: ledger.total_ms + 8000 });
        await page.evaluate(() => window.__motionMeasure.collect());
        const after = await page.evaluate(() => window.__motionMeasure.soundCount());
        rec.sound_muted = { mute_found: true, calls: after - before };
      } catch (e) {
        rec.sound_muted = { mute_found: false, calls: null, error: String(e.message || e).split('\n')[0] };
      } finally {
        if (context) await context.close().catch(() => {});
      }
    }
  } catch (e) {
    rec.fatal = rec.fatal || `計測が止まった: ${String(e.message || e).split('\n')[0]}`;
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) server.close();
  }
  return rec;
}

// ---- 監修のフレーム（--frames）。seek(ms, 版) で時刻を止めて撮るので、同じ時刻なら何度撮っても同じ絵になる
const pad4 = (n) => String(n).padStart(4, '0');
export function frameTimes(total, step = 100) {
  const out = [];
  for (let t = 0; t <= total; t += step) out.push(t);
  if (out[out.length - 1] !== total) out.push(total);
  return out;
}

async function captureFrames(cfg, dir) {
  const index = {
    tool: 'motion-measure', kind: 'frames', measured_at: new Date().toISOString(),
    target: { scene: cfg.scene, url: cfg.url || null, dir: cfg.dir || null }, viewport: cfg.viewport, step_ms: 100, browser: {}, frames: [],
  };
  let server = null;
  let browser = null;
  try {
    let url = cfg.url;
    if (cfg.dir) {
      server = await serve(cfg.dir);
      url = `http://127.0.0.1:${server.address().port}${cfg.path || '/'}`;
    }
    index.target.url = url;
    const { chromium } = loadPlaywright();
    browser = await chromium.launch({ headless: true, proxy: PROXY });
    index.browser = { name: 'chromium', version: browser.version(), headless: true };
    fs.mkdirSync(dir, { recursive: true });
    const shoot = async (page, name, meta) => {
      await page.evaluate(() => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res))));
      fs.writeFileSync(path.join(dir, name), await page.screenshot({ type: 'png' }));
      index.frames.push({ file: name, ...meta });
    };
    const open = async (reduced) => {
      const o = await openPage(browser, url, cfg, { reduced });
      const ready = await o.page.evaluate((ms) => window.__motionMeasure.ready(ms), 10000);
      if (!ready.found || ready.missing.includes('ledger') || ready.missing.includes('seek') || ready.missing.includes('reset')) {
        throw new Error(`window.__scene の約束が欠けている（${ready.found ? ready.missing.join('・') : '__scene'}）`);
      }
      const L = normalizeLedger(ready.ledger);
      const id = L.id || L.transition;
      if (id !== cfg.scene) throw new Error(`演出の ID が違う（設定 ${cfg.scene}、台帳 ${id || 'なし'}）`);
      if (!(L.total_ms > 0)) throw new Error('台帳に total_ms（か versions.full.total_ms）が無い');
      return { ...o, L };
    };
    let ledger;
    {
      const { context, page, L } = await open(false);
      ledger = L;
      await page.evaluate(() => window.__scene.reset());
      for (const t of frameTimes(L.total_ms)) {
        await page.evaluate((ms) => window.__scene.seek(ms, 'full'), t);
        await shoot(page, `full-${pad4(t)}.png`, { version: 'full', at_ms: t });
      }
      if (L.short_ms > 0) {
        await page.evaluate(() => window.__scene.reset());
        for (const t of frameTimes(L.short_ms)) {
          await page.evaluate((ms) => window.__scene.seek(ms, 'short'), t);
          await shoot(page, `short-${pad4(t)}.png`, { version: 'short', at_ms: t });
        }
      }
      // 静止の画面: 本物の入力で押し、終わってから 1 秒あとの 1 枚
      if (specOk(L.trigger)) {
        await page.evaluate(() => window.__scene.reset());
        await page.evaluate(() => window.__motionMeasure.arm());
        await press(page, L.trigger);
        await page.waitForFunction((min) => window.__motionMeasure.ended(min), L.total_ms, { polling: 'raf', timeout: L.total_ms + 8000 });
        await page.evaluate(() => window.__motionMeasure.collect());
        await sleep(1000);
        await shoot(page, 'still.png', { version: 'full', at_ms: null, note: '終わってから 1 秒あと' });
        // 飛ばしたとき: 途中でキーを押し、300ms あとの 1 枚
        const skip = L.skip || {};
        const key = skip.key || 'Enter';
        const at = typeof skip.at_ms === 'number' ? skip.at_ms : 200;
        await page.evaluate(() => window.__scene.reset());
        await page.evaluate(() => window.__motionMeasure.arm());
        await press(page, L.trigger);
        await sleep(at);
        await page.keyboard.press(key);
        await sleep(BUDGET.skip_ms);
        await page.evaluate(() => window.__motionMeasure.collect());
        await shoot(page, 'skip.png', { version: 'full', at_ms: null, note: `${at}ms で ${key} を押し、${BUDGET.skip_ms}ms あと` });
      }
      await context.close();
    }
    if (ledger.reduced && ledger.reduced.ms > 0) {
      const { context, page } = await open(true);
      const r = ledger.reduced.ms;
      await page.evaluate(() => window.__scene.reset());
      for (const t of [...new Set([0, Math.round(r / 2), r])]) {
        await page.evaluate((ms) => window.__scene.seek(ms, 'reduced'), t);
        await shoot(page, `reduced-${pad4(t)}.png`, { version: 'reduced', at_ms: t });
      }
      await context.close();
    }
    fs.writeFileSync(path.join(dir, 'frames.json'), `${JSON.stringify(index, null, 1)}\n`);
    return { index, error: null };
  } catch (e) {
    return { index, error: String(e.message || e).split('\n')[0] };
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) server.close();
  }
}

// ---- 設定
function parseArgs(argv) {
  const a = { runs: 3 };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const v = argv[i + 1];
    if (['--config', '--dir', '--default-dir', '--url', '--scene', '--path', '--runs', '--record', '--judge', '--frames'].includes(k)) {
      if (v === undefined || v.startsWith('--')) {
        a.unknown = `${k}（値が無い）`;
        break;
      }
      a[k.slice(2).replace('-', '_')] = v;
      i++;
    } else if (k === '--selftest') a.selftest = true;
    else if (k === '--allow-fictional') a.allow_fictional = true;
    else a.unknown = k;
  }
  return a;
}

export function loadConfig(args) {
  const errors = [];
  let file = {};
  let base = process.cwd();
  if (args.config) {
    try {
      file = JSON.parse(fs.readFileSync(args.config, 'utf8'));
      base = path.dirname(path.resolve(args.config));
    } catch (e) {
      return { errors: [`設定 ${args.config} を読めない: ${String(e.message).split('\n')[0]}`] };
    }
    for (const k of Object.keys(file)) if (!CONFIG_KEYS.has(k)) errors.push(`設定に知らない鍵「${k}」がある（使える鍵: ${[...CONFIG_KEYS].join('、')}）`);
  }
  const cfg = {
    scene: args.scene || file.scene,
    url: args.url || file.url || null,
    dir: args.dir ? path.resolve(args.dir) : file.dir ? path.resolve(base, file.dir) : null,
    path: args.path || file.path || '/',
    viewport: file.viewport || { width: 1280, height: 800 },
    runs: Number(args.runs || 3),
    record: args.record ? path.resolve(args.record) : file.record ? path.resolve(base, file.record) : null,
  };
  if (!cfg.url && !cfg.dir && args.default_dir) cfg.dir = path.resolve(args.default_dir);
  if (!cfg.scene || !/^[\w.-]+$/.test(cfg.scene)) errors.push('演出の ID（scene）が無いか、英数字・点・ハイフン・下線の外の字を含む');
  if (cfg.url && cfg.dir) errors.push('url と dir の両方がある。どちらか 1 つにする');
  if (!cfg.url && !cfg.dir) errors.push('対象が無い。url（起こしてあるサーバー）か dir（静的なファイルの置き場）を書く');
  if (cfg.url) {
    try {
      const u = new URL(cfg.url);
      if (!/^https?:$/.test(u.protocol) || !isLocalHost(u.hostname)) errors.push(`url は 127.0.0.1・localhost・[::1] だけ（外のネットワークには出ない）: ${cfg.url}`);
    } catch (e) {
      errors.push(`url が読めない: ${cfg.url}`);
    }
  }
  if (cfg.dir && !(fs.existsSync(cfg.dir) && fs.statSync(cfg.dir).isDirectory())) errors.push(`dir が無い: ${cfg.dir}`);
  if (!/^\//.test(cfg.path)) errors.push(`path は / で始める: ${cfg.path}`);
  const vp = cfg.viewport;
  if (!vp || !Number.isInteger(vp.width) || !Number.isInteger(vp.height) || vp.width < 200 || vp.height < 200 || vp.width > 4000 || vp.height > 4000) errors.push('viewport は width と height を 200〜4000 の整数で書く');
  if (!Number.isInteger(cfg.runs) || cfg.runs < 1 || cfg.runs > 10) errors.push('runs は 1〜10 の整数');
  // 記録の置き場: 設定のファイルの record は、設定の置き場か tmp/.verify の下だけ（gate が自動で読む設定から、外へ書かせない）
  if (cfg.record) {
    const problem = writeProblem(cfg.record, { roots: !args.record && file.record ? [base, VERIFY_DIR] : null });
    if (problem) errors.push(problem);
  }
  if (args.frames) {
    const problem = writeProblem(args.frames, { json: false });
    if (problem) errors.push(problem);
  }
  if (!cfg.record && cfg.scene) cfg.record = path.join(VERIFY_DIR, `motion-measure-${cfg.scene}.json`);
  return { cfg, errors };
}

// ---- 自己試験（ブラウザもサーバーも使わない）
export function sampleRecord() {
  const ledger = {
    id: 'start-to-login', total_ms: 1400, short_ms: 600,
    trigger: { role: 'button', name: 'スタート' },
    focus: { role: 'textbox', name: 'メールアドレス', at_ms: 1100 },
    title: 'ログイン', inert: ['#title-scene'],
    skip: { key: 'Enter', at_ms: 200 }, reduced: { kind: 'fade', ms: 150 },
    ambient: { stop: { role: 'button', name: '背景の動きを止める' } },
    sound: { mute: { role: 'button', name: '音を消す' } },
    beats: [
      { at_ms: 0, target: 'start-button', ms: 120, props: ['transform', 'opacity'] },
      { at_ms: 120, target: 'particles', ms: 600, engine: 'background' },
      { at_ms: 200, target: 'title', ms: 400, props: ['transform', 'opacity'] },
      { at_ms: 900, target: 'login-frame', ms: 400, props: ['transform', 'opacity'] },
    ],
  };
  const frames = Array.from({ length: 84 }, (_, i) => (i % 40 === 0 ? 21 : 16.7));
  const animations = [
    { keys: ['start-button'], pseudo: '', props: ['transform', 'opacity'], moves: true, start_ms: 2, ms: 120, infinite: false },
    { keys: ['title'], pseudo: '', props: ['transform', 'opacity'], moves: true, start_ms: 203, ms: 400, infinite: false },
    { keys: ['login-frame'], pseudo: '', props: ['transform', 'opacity'], moves: true, start_ms: 905, ms: 400, infinite: false },
  ];
  const runs = CPUS.flatMap((cpu) => [1, 2, 3].map((run) => ({
    cpu, run, ready_ms: cpu === 1 ? 900 : 1900, first_frame_ms: cpu === 1 ? 24 : 40, first_frame_source: 'event-timing',
    frames: [...frames], loaf: [], animations: animations.map((a) => ({ ...a })),
    sound: { before_input: 0, calls: [] },
    end: { focus_ok: true, active: 'input#email「」', title: 'ログイン', inert: [{ selector: '#title-scene', state: 'inert' }] },
    skip: { key: 'Enter', at_ms: 200, pressed_at_ms: 201, end_ms: cpu === 1 ? 90 : 140 },
  })));
  runs[0].end_snapshot = '- heading "ログイン" [level=1]\n- textbox "メールアドレス"\n- button "背景の動きを止める"';
  const smooth = Array.from({ length: 43 }, (_, i) => Array.from({ length: 16 }, () => Math.round((0.05 + i * 0.002) * 1000) / 1000));
  return {
    tool: 'motion-measure', version: 1, note: '架空の記録。判定の試験用で、測った値ではない',
    measured_at: '2026-11-26T00:00:00.000Z', target: { scene: 'start-to-login', url: 'http://127.0.0.1:0/', dir: null },
    browser: { name: 'chromium', version: '架空', headless: true, fictional: true, webgl_renderer: null, software: null },
    viewport: { width: 1280, height: 800 }, budget: BUDGET,
    contract: { found: true, missing: [], ready: 'promise' }, ledger, loaf_supported: true, runs,
    reduced: { animations: [{ keys: ['login-frame'], pseudo: '', props: ['opacity'], moves: false, start_ms: 1, ms: 150, infinite: false }], focus_ok: true, end_snapshot: '- heading "ログイン" [level=1]\n- textbox "メールアドレス"', still_diff_px: 0 },
    ambient: { moving: true, diff_px: 5120, stop: ledger.ambient.stop, stop_found: true, diff_after_stop_px: 0 },
    sound_muted: null,
    flash: { step_ms: 33, luminance: smooth },
    assets: {
      lcp_ms: 420, fcp_ms: 380, external: 0,
      list: [
        { url: '/index.html', type: 'document', bytes: 6200, br_bytes: 2100, phase: 'initial', start_ms: null },
        { url: '/app.js', type: 'script', bytes: 31000, br_bytes: 9800, phase: 'initial', start_ms: 40 },
        { url: '/scene.js', type: 'script', bytes: 52000, br_bytes: 15800, phase: 'deferred', start_ms: 520 },
      ],
    },
  };
}

// 項目ごとに 1 つだけ落とす変更。自己試験と evals の負例（fixtures/measure/bad.json）が使う
export const BREAKS = {
  1: (r) => { r.runs[4].first_frame_ms = 180; },
  2: (r) => { r.runs[1].animations[1].start_ms = 263; },
  3: (r) => { r.runs[4].frames[10] = 68; },
  4: (r) => { r.runs[5].loaf = [{ ms: 72, scripts: [{ source: 'http://127.0.0.1:0/scene.js', fn: 'tick', invoker: 'FrameRequestCallback', ms: 61 }] }]; },
  5: (r) => { r.runs[0].animations.push({ keys: ['login-frame'], pseudo: '', props: ['left'], moves: true, start_ms: 905, ms: 400, infinite: false }); },
  6: (r) => { r.reduced.animations[0].moves = true; r.reduced.animations[0].props = ['transform', 'opacity']; },
  7: (r) => { r.runs[2].skip.end_ms = 900; },
  8: (r) => { r.runs[1].end.focus_ok = false; },
  9: (r) => { r.ambient.stop_found = false; r.ambient.diff_after_stop_px = null; },
  10: (r) => { r.runs[0].sound.before_input = 1; r.runs[0].sound.calls = [{ at_ms: -300, kind: 'audio.start' }]; r.sound_muted = { mute_found: true, calls: 0 }; },
  11: (r) => { r.flash.luminance = r.flash.luminance.map((row, i) => row.map((v, t) => (t === 5 ? (i % 2 ? 0.9 : 0.1) : v))); },
  12: (r) => { r.assets.list[2].br_bytes = 900 * 1024; },
};

export function brokenRecord(nos) {
  const r = sampleRecord();
  for (const no of nos) BREAKS[no](r);
  return r;
}

function selftest() {
  const checks = [];
  const quiet = (rec, allowFictional = true) => {
    const lines = [];
    const ok = report(rec, null, (l) => lines.push(l), { allowFictional });
    return { ok, out: lines.join('\n') };
  };
  const good = quiet(sampleRecord());
  checks.push([good.ok && (good.out.match(/^RESULT: PASS motion-measure \d+ /gm) || []).length === 12, `正例の記録が 12 項目 PASS にならない:\n${good.out}`]);
  // 架空の記録は、試験の許しが無ければ 12 項目が通っても合格にしない
  const fict = quiet(sampleRecord(), false);
  checks.push([!fict.ok && fict.out.includes('[記録] 架空の記録') && /^RESULT: FAIL motion-measure start-to-login /m.test(fict.out), `架空の記録が --allow-fictional なしで合格になった:\n${fict.out.slice(-300)}`]);
  // 書き込み先: 設定の record は設定の置き場か tmp/.verify の下だけ。hooks などと、.json でない名前は断る
  const cfgBase = path.join(HERE, 'cfgdir');
  checks.push([writeProblem(path.join(cfgBase, '../../escaped-by-config/rec.json'), { roots: [cfgBase, VERIFY_DIR] }) !== null, '設定の置き場の外への record を断らない']);
  checks.push([writeProblem(path.join(cfgBase, 'rec.json'), { roots: [cfgBase, VERIFY_DIR] }) === null, '設定の置き場の中の record を断った']);
  checks.push([writeProblem(path.join(VERIFY_DIR, 'motion-measure-a.json'), { roots: [cfgBase, VERIFY_DIR] }) === null, 'tmp/.verify の record を断った']);
  checks.push([['hooks/rec.json', '.claude/rec.json', '.cursor/rec.json', '.git/rec.json', 'tmp/rec.txt'].every((p) => writeProblem(path.join(PROJECT, p)) !== null), 'プロジェクトの直下の hooks・.claude・.cursor・.git か、.json でない record を断らない']);
  checks.push([writeProblem(path.join(path.dirname(PROJECT), 'other', '.claude', 'rec.json')) !== null, 'プロジェクトの外の .claude の下を断らない']);
  checks.push([writeProblem(path.join(PROJECT, 'tmp', 'flow', 'x', 'frames'), { json: false }) === null && writeProblem(path.join(PROJECT, 'hooks', 'frames'), { json: false }) !== null, 'フレームの置き場の判定が違う']);
  checks.push([parseArgs(['--judge']).unknown !== undefined && parseArgs(['--record', '--judge', 'x.json']).unknown !== undefined, '値の無い引数を誤りにしない']);
  checks.push([JSON.stringify(frameTimes(150)) === '[0,100,150]' && frameTimes(1400).length === 15 && frameTimes(600).length === 7, 'フレームの時刻（100ms ごと、終わりを含む）が違う']);
  for (const [no, name] of ITEMS) {
    const res = judge(brokenRecord([no]));
    const failed = res.items.filter((i) => !i.ok).map((i) => i.no);
    checks.push([failed.length === 1 && failed[0] === no, `項目 ${no}（${name}）だけを落とす記録で、落ちた項目が ${failed.join('、') || 'なし'}`]);
  }
  const all = judge(brokenRecord(ITEMS.map(([no]) => no)));
  checks.push([all.items.every((i) => !i.ok), '全部を落とす記録で、通った項目がある']);
  const none = sampleRecord();
  none.contract = { found: false, missing: ['__scene'] };
  const nr = quiet(none);
  checks.push([!nr.ok && (nr.out.match(/^RESULT: FAIL motion-measure \d+ .*window\.__scene が無い/gm) || []).length === 12, '約束の無いページで、12 項目が「__scene が無い」で落ちない']);
  // 台帳の別の形: 拍を versions.full.beats の tracks に置き、要素を selector で指し、title を focus.title に置く
  const alt = sampleRecord();
  const L0 = alt.ledger;
  alt.ledger = {
    id: L0.id, trigger: { selector: '#start' }, focus: { selector: '#email', title: 'ログイン' },
    inert: L0.inert, skip: L0.skip, ambient: L0.ambient, sound: L0.sound,
    versions: {
      full: { total_ms: 1400, beats: L0.beats.map((b, i) => ({ id: `b${i + 1}`, at_ms: b.at_ms, ms: b.ms, tracks: [{ id: b.target, at_ms: b.at_ms, ms: b.ms, props: b.props, engine: b.engine }] })) },
      reduced: { total_ms: 150 },
    },
  };
  for (const r of alt.runs) for (const a of r.animations) if (a.keys[0] === 'title') a.keys = ['title#1'];
  const altRes = judge(alt);
  checks.push([altRes.ok, `versions と tracks の形の台帳で 12 項目 PASS にならない: ${altRes.items.filter((i) => !i.ok).map((i) => `${i.no} ${i.fails[0]}`).join('、')}`]);
  const moving = sampleRecord();
  moving.reduced.still_diff_px = 1200;
  const movingFails = judge(moving).items.filter((i) => !i.ok).map((i) => i.no);
  checks.push([movingFails.length === 1 && movingFails[0] === 6, `縮小版で背景が動き続ける記録が、項目 6 だけで落ちない（${movingFails.join('、') || 'なし'}）`]);
  const silent = sampleRecord();
  silent.ledger.beats[0].sound = 'tap';
  checks.push([!judge(silent).items[9].ok, '拍に音があるのに鳴らない記録が、音の項目で落ちない']);
  checks.push([flashesPerSecond([0.1, 0.9, 0.1, 0.9, 0.1, 0.9, 0.1, 0.9, 0.1], 100) === 4, '閃光の数え方: 100ms ごとの 8 回の反転を 1 秒に 4 回と数えない']);
  checks.push([flashesPerSecond([0.85, 0.95, 0.85, 0.95, 0.85], 33) === 0, '閃光の数え方: 暗い側が 0.8 以上の変化を数えた']);
  const ext = loadConfig({ url: 'https://example.com/', scene: 'a' });
  checks.push([ext.errors.some((e) => e.includes('127.0.0.1')), '外の URL の設定が誤りにならない']);
  const okCfg = loadConfig({ dir: HERE, scene: 'start-to-login' });
  checks.push([okCfg.errors.length === 0, `正しい設定が誤りになる: ${okCfg.errors.join('、')}`]);
  checks.push([isLocalHost('[::1]') && isLocalHost('app.localhost') && !isLocalHost('127.0.0.1.example.com'), 'ローカルの名前の見分けが違う']);
  checks.push([isLocalHost(new URL('ws://127.0.0.1:9/').hostname) && !isLocalHost(new URL('ws://192.0.2.1:9/').hostname), 'WebSocket の URL のローカルの見分けが違う']);
  let ok = true;
  for (const [passed, msg] of checks) {
    if (!passed) {
      ok = false;
      console.log(`FAIL selftest motion-measure: ${msg}`);
    }
  }
  console.log(`RESULT: ${ok ? 'PASS' : 'FAIL'} motion-measure --selftest (${checks.length} 例。ブラウザなし)`);
  return ok;
}

async function main(argv) {
  const args = parseArgs(argv);
  if (args.unknown) {
    console.log(`FAIL motion-measure [使い方] 知らない引数 ${args.unknown}`);
    console.log('RESULT: FAIL motion-measure 使い方');
    return 2;
  }
  if (args.selftest) return selftest() ? 0 : 1;
  if (args.judge) {
    let rec;
    try {
      rec = JSON.parse(fs.readFileSync(args.judge, 'utf8'));
    } catch (e) {
      console.log(`FAIL motion-measure [記録] ${args.judge} を読めない: ${String(e.message).split('\n')[0]}`);
      console.log('RESULT: FAIL motion-measure 記録');
      return 2;
    }
    return report(rec, args.judge, console.log, { allowFictional: Boolean(args.allow_fictional) }) ? 0 : 1;
  }
  const { cfg, errors } = loadConfig(args);
  if (errors.length) {
    for (const e of errors) console.log(`FAIL motion-measure [設定] ${e}`);
    console.log(`RESULT: FAIL motion-measure ${(cfg && cfg.scene) || '設定'} (設定の誤り ${errors.length} 件。ブラウザは起こしていない)`);
    return 2;
  }
  if (args.frames) {
    const dir = path.resolve(args.frames);
    const { index, error } = await captureFrames(cfg, dir);
    if (error) console.log(`FAIL motion-measure [フレーム] ${error}`);
    const kinds = ['full', 'short', 'reduced'].map((v) => `${v} ${index.frames.filter((f) => f.version === v && f.at_ms !== null).length}`).join('、');
    console.log(`フレーム: ${index.frames.length} 枚（${kinds}、ほかに静止の画面と飛ばしたとき）。${index.browser.version ? `Chromium ${index.browser.version}、画面なし、` : ''}${cfg.viewport.width} × ${cfg.viewport.height}`);
    console.log(`RESULT: ${error ? 'FAIL' : 'PASS'} motion-measure frames ${cfg.scene} (${index.frames.length} 枚。${dir}/frames.json)`);
    return error ? 1 : 0;
  }
  const rec = await measure(cfg);
  try {
    fs.mkdirSync(path.dirname(cfg.record), { recursive: true });
    fs.writeFileSync(cfg.record, `${JSON.stringify(rec, null, 1)}\n`);
  } catch (e) {
    console.log(`FAIL motion-measure [記録] ${cfg.record} に書けない: ${String(e.message).split('\n')[0]}`);
  }
  const rel = path.relative(process.cwd(), cfg.record);
  return report(rec, rel && !rel.startsWith('..') ? rel : cfg.record) ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const timer = setTimeout(() => {
    console.log('FAIL motion-measure [時間] 300 秒で終わらない');
    console.log('RESULT: FAIL motion-measure 時間切れ');
    process.exit(1);
  }, 300000);
  timer.unref();
  main(process.argv.slice(2)).then(
    (rc) => process.exit(rc),
    (e) => {
      console.log(`FAIL motion-measure [実行] ${String(e.message || e).split('\n')[0]}`);
      console.log('RESULT: FAIL motion-measure 実行');
      process.exit(1);
    },
  );
}
