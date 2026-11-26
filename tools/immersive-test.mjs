#!/usr/bin/env node
// tools/immersive-test.mjs — 没入のサンプル（samples/immersive）の計測の判定。全体の検証の 10 番から --full のときだけ呼ぶ。
//   計測の本体は skills/frontend/scripts/motion-measure.mjs（12 項目。CPU 等速と 4 倍遅くの 2 条件で 3 回ずつ、悪い側を採る）。
//   その 12 項目の合否をそのまま要点にし、1 項目でも落ちたら FAIL にする。4 倍遅い条件も判定に入れる。
//   4 倍遅い条件の合格の線と測る機械はまだ決まっていない（performance-budget.md の演出の予算）。4 倍遅い条件の回だけで
//   落ちた項目は INFO の行でも名指し、決まるまでは FAIL のまま出す。
//   ほかの要点: コンソールのエラーと外への要求（HTTP と WebSocket）を、別に開いた画面で海面・潜る・戻る・2 回目・飛ばす・
//   #panel・縮小版・方向の 3 案を通して数える。最初の 1 画面の LCP と CLS を Lighthouse で測る。
//   台帳の初回の版と演出計画書（skills/designer/examples/motion-plan-dive-log.md）の時刻ごとの表の一致を見る（ブラウザなし）。
// 使い方: node tools/immersive-test.mjs [--record <記録.json>] [--shots <置き場>]   /   node tools/immersive-test.mjs --selftest
//   --record: 計測の記録の置き場。既定は tmp/.verify/immersive-measure.json。回すたびに消してから測り、前の回の記録を読まない
//   --shots: 判定のあとに、監修の材料を PNG で書く（リポジトリの外に置く）。<置き場>/frames に、seek で撮る初回・短い版・縮小版と、
//            本当に押して撮る静止の画面・飛ばしたとき・背景を止める前後・焦点・ホバーと押し込み・誤りの状態・送信中・戻る・素材の遅れ、
//            幅 375px と強制カラーの計器盤。<置き場>/directions に方向の 3 案。撮った条件の一覧は <置き場>/frames.json。
//            移した先のプロジェクトでは、motion-measure.sh の --frames で撮る
//   --selftest: 架空の記録で要点の判定を試し、台帳と演出計画書の表の突き合わせを試す。ブラウザもサーバーも使わない
// 出力: FAIL immersive-test [<観点>] <内容>、要点ごとの RESULT: PASS|FAIL immersive-test <観点>: <数字>、INFO の行、
//       最後に RESULT: PASS|FAIL immersive-test (…)。1 件でも FAIL なら終了コード 1、使い方の誤りは 2。
//   計測の子が設定の誤りや時間切れで止まったとき、記録が今回の計測のものでないとき、架空の記録のときは FAIL にする。
//   サーバーとブラウザは、成否によらず必ず止める。サーバーは 127.0.0.1 の空きポートで、外のネットワークには出ない。
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const sampleDir = process.env.IMMERSIVE_DIR ? path.resolve(process.env.IMMERSIVE_DIR) : path.join(root, 'samples', 'immersive');
const measureScript = path.join(root, 'skills', 'frontend', 'scripts', 'motion-measure.mjs');
const planPath = path.join(root, 'skills', 'designer', 'examples', 'motion-plan-dive-log.md');
// 移した先（<プロジェクト>/tmp/tools）では、一式の置き場が tmp そのもの。記録は tmp/.verify に置く（motion-measure と同じ決め方）
const verifyDir = path.basename(root) === 'tmp' && fs.existsSync(path.join(root, 'DEPLOYED.md')) ? path.join(root, '.verify') : path.join(root, 'tmp', '.verify');
const require = createRequire(import.meta.url);
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8' };
const EASE = { 標準: 'standard', 去る: 'leave', 着く: 'arrive', 収まる: 'settle' };
const DIRECTIONS = ['a', 'b', 'c'];
// 最初の 1 画面の予算（performance-budget.md の 3 指標。INP は押す操作が要るので、計測の項目 1 が受け持つ）
const LCP_MS = 2500;
const CLS_MAX = 0.1;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const pad = (n) => String(n).padStart(4, '0');

// ---- 演出計画書の時刻ごとの表と、台帳の初回の版の突き合わせ（ブラウザなし）
const msOf = (s) => {
  const m = /(\d{1,3}(?:,\d{3})+|\d+)\s*ms/.exec(s || '');
  return m ? Number(m[1].replace(/,/g, '')) : null;
};
const cellsOf = (line) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());

export function planTable(text) {
  // 「## 時刻ごとの表」の表を読む。列: 時刻 | 段 | レイヤーと対象 | 変化 | 長さと曲線 | 伝えること。表題の下の表から初回と 2 回目の長さも読む
  const lines = text.split('\n');
  const head = lines.slice(0, Math.max(0, lines.findIndex((l) => /^##\s/.test(l))));
  const lengthRow = head.find((l) => /^\|\s*長さ\s*\|/.test(l));
  const lengths = lengthRow ? [...cellsOf(lengthRow)[1].matchAll(/(\d{1,3}(?:,\d{3})+|\d+)\s*ms/g)].map((m) => Number(m[1].replace(/,/g, ''))) : [];
  const start = lines.findIndex((l) => /^##\s+時刻ごとの表/.test(l));
  if (start < 0) return { rows: null, lengths };
  const rows = [];
  let header = null;
  for (let i = start + 1; i < lines.length && !/^##\s/.test(lines[i]); i++) {
    if (!lines[i].trim().startsWith('|')) {
      if (rows.length) break;
      continue;
    }
    const cells = cellsOf(lines[i]);
    if (!header) {
      header = cells;
      continue;
    }
    if (cells.every((c) => /^:?-{3,}:?$/.test(c))) continue;
    const col = (name) => cells[header.findIndex((h) => h.includes(name))] || '';
    const len = col('長さ');
    const word = Object.keys(EASE).find((w) => len.includes(w));
    rows.push({ at: msOf(col('時刻')), phase: col('段'), ms: msOf(len), ease: word ? EASE[word] : null, target: col('レイヤー') });
  }
  return { rows, lengths };
}

export function comparePlan(plan, ledger) {
  // 返り値: 食い違いの一覧（空なら一致）
  const out = [];
  if (!plan.rows || !plan.rows.length) return ['演出計画書に「## 時刻ごとの表」の表が無い'];
  const full = ledger && ledger.versions && ledger.versions.full;
  if (!full || !Array.isArray(full.beats)) return ['台帳に versions.full.beats が無い'];
  if (plan.rows.length !== full.beats.length) out.push(`行の数が違う（計画書 ${plan.rows.length} 行、台帳 ${full.beats.length} 拍）`);
  plan.rows.forEach((row, i) => {
    const b = full.beats[i];
    if (!b) return;
    const diff = [];
    if (row.at !== b.at_ms) diff.push(`時刻 ${row.at}ms／${b.at_ms}ms`);
    if (row.phase !== b.phase) diff.push(`段 ${row.phase}／${b.phase}`);
    if (row.ms !== b.ms) diff.push(`長さ ${row.ms}ms／${b.ms}ms`);
    if ((row.ease || null) !== (b.ease || null)) diff.push(`曲線 ${row.ease || 'なし'}／${b.ease || 'なし'}`);
    if (diff.length) out.push(`${i + 1} 行目（${row.target}、台帳 ${b.id}）: ${diff.join('、')}（計画書／台帳）`);
  });
  const [first, second] = plan.lengths;
  if (first !== full.total_ms) out.push(`初回の長さ ${first ?? '－'}ms／${full.total_ms}ms（計画書／台帳）`);
  const short = ledger.versions.short;
  if (second !== undefined && (!short || second !== short.total_ms)) out.push(`2 回目の長さ ${second}ms／${short ? short.total_ms : '－'}ms（計画書／台帳）`);
  return out;
}

// ---- 記録の確かめ。前の回の記録と、架空の記録を判定に使わない
export function recordProblems(rec, started) {
  const out = [];
  const at = Date.parse((rec && rec.measured_at) || '');
  if (!(at >= started - 1000)) out.push(`記録の measured_at（${(rec && rec.measured_at) || 'なし'}）が今回の計測より前。前の回の記録は判定に使わない`);
  if (rec && rec.browser && rec.browser.fictional) out.push('架空の記録（browser.fictional）。測った記録だけを判定する');
  return out;
}

// ---- 要点の判定（記録と、画面の通しの結果だけを読む。ブラウザを使わない）
export function keyPoints(rec, pass, mm, screen = null) {
  // rec: motion-measure の記録。pass: { errors: [...], external: n, requests: n, flows: [...] }。mm: motion-measure の書き出し。
  // screen: 最初の 1 画面の結果 { ok, detail, fails }（測らなかったときは null）
  const { judge, BUDGET } = mm;
  const res = judge(rec);
  const runs = (rec.runs || []).filter((r) => !r.error);
  const slow = runs.filter((r) => r.cpu !== 1);
  const points = [];
  const add = (name, ok, detail, fails = []) => points.push({ name, ok, detail, fails });

  add('コンソール', pass.errors.length === 0, `エラー ${pass.errors.length} 件（${pass.flows.join('・')}）`, pass.errors.slice(0, 3));
  // 計測の 12 項目は motion-measure の判定をそのまま使う。CPU 等速と 4 倍遅い条件のどちらで落ちても FAIL
  for (const it of res.items) add(`${it.no} ${it.name}`, it.ok, it.detail, it.fails);
  add('外への要求（画面の通し）', pass.external === 0, `画面の通しで止めた外への要求 ${pass.external} 件（要求は全部で ${pass.requests} 件。WebSocket を含む）`, pass.external ? [`外への要求 ${pass.external} 件`] : []);
  if (screen) add('最初の 1 画面', screen.ok, screen.detail, screen.fails);

  const info = [];
  if (slow.length) {
    const ff = slow.map((r) => r.first_frame_ms).filter((v) => typeof v === 'number');
    const fr = slow.flatMap((r) => r.frames || []);
    info.push(`[4 倍遅い CPU] 最初のフレーム最大 ${ff.length ? Math.max(...ff) : '－'}ms、フレームの最大 ${fr.length ? Math.max(...fr) : '－'}ms、50ms 超 ${fr.filter((d) => d > BUDGET.frame_long_ms).length} 個（${slow.length} 回。判定に入れている）`);
  }
  const slowOnly = res.items.filter((i) => !i.ok && i.fails.length && i.fails.every((f) => f.includes('4 倍遅い')));
  if (slowOnly.length) {
    info.push(`[4 倍遅い CPU] 落ちた項目のうち ${slowOnly.map((i) => i.no).join('・')} は、4 倍遅い条件の回だけで落ちた。合格の線と測る機械は未確定で、依頼者が決めるまで FAIL のまま出す`);
  }
  return { points, info, ok: points.every((p) => p.ok) };
}

function print(points, extra, label) {
  for (const p of points) {
    if (!p.ok) for (const f of (p.fails.length ? p.fails : [p.detail]).slice(0, 4)) console.log(`FAIL immersive-test [${p.name}] ${f}`);
    console.log(`RESULT: ${p.ok ? 'PASS' : 'FAIL'} immersive-test ${p.name}: ${p.detail}`);
  }
  for (const l of extra) console.log(`INFO immersive-test ${l}`);
  const n = points.filter((p) => !p.ok).length;
  console.log(`RESULT: ${n ? 'FAIL' : 'PASS'} immersive-test (要点 ${points.length} つ、FAIL ${n}。${label})`);
  return n === 0;
}

// ---- ブラウザ
function serve(dir) {
  const base = path.resolve(dir);
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      let p = '/';
      try {
        p = decodeURIComponent(new URL(req.url, 'http://local').pathname);
      } catch {
        p = '/';
      }
      if (p.endsWith('/')) p += 'index.html';
      const file = path.resolve(base, `.${path.normalize(p)}`);
      const rel = path.relative(base, file);
      if (rel.startsWith('..') || path.isAbsolute(rel) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
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

async function newPage(browser, opts, pass, label, mm) {
  // 外への要求は HTTP と WebSocket の両方を止めて数える（motion-measure と同じ守り）。Service Worker は止める
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, serviceWorkers: 'block', ...opts });
  await mm.guardContext(context, pass);
  const page = await context.newPage();
  page.on('console', (m) => {
    if (m.type() === 'error') pass.errors.push(`${label}: ${m.text()}`);
  });
  page.on('pageerror', (e) => pass.errors.push(`${label}: ${e.message}`));
  return { context, page };
}

const stateIs = (page, want, timeout = 5000) => page.waitForFunction((s) => window.__scene && window.__scene.state === s, want, { timeout });
const ready = (page) => page.evaluate(async () => {
  await window.__scene.ready;
  await window.__scene.seaReady;
});

// 画面の通し: コンソールのエラーと外への要求を数える
async function walk(browser, origin, mm) {
  const pass = { errors: [], external: 0, requests: 0, flows: [] };
  {
    const { context, page } = await newPage(browser, { reducedMotion: 'no-preference' }, pass, '既定', mm);
    await page.goto(`${origin}/`, { waitUntil: 'load' });
    await ready(page);
    pass.flows.push('海面');
    await page.click('#start');
    await stateIs(page, 'panel');
    pass.flows.push('潜る');
    await page.evaluate(() => history.back());
    await stateIs(page, 'surface');
    pass.flows.push('戻る');
    await page.click('#start');
    await stateIs(page, 'panel');
    pass.flows.push('2 回目');
    await page.evaluate(() => window.__scene.reset());
    await page.click('#start');
    await sleep(200);
    await page.keyboard.press('Enter');
    await stateIs(page, 'panel');
    pass.flows.push('飛ばす');
    const direct = await context.newPage();
    direct.on('console', (m) => {
      if (m.type() === 'error') pass.errors.push(`#panel: ${m.text()}`);
    });
    direct.on('pageerror', (e) => pass.errors.push(`#panel: ${e.message}`));
    await direct.goto(`${origin}/#panel`, { waitUntil: 'load' });
    await ready(direct);
    await stateIs(direct, 'panel');
    pass.flows.push('#panel');
    await context.close();
  }
  {
    const { context, page } = await newPage(browser, { reducedMotion: 'reduce' }, pass, '縮小版', mm);
    await page.goto(`${origin}/`, { waitUntil: 'load' });
    await ready(page);
    await page.click('#start');
    await stateIs(page, 'panel');
    pass.flows.push('縮小版');
    await context.close();
  }
  {
    const { context, page } = await newPage(browser, {}, pass, '方向の 3 案', mm);
    for (const d of DIRECTIONS) await page.goto(`${origin}/directions/${d}.html`, { waitUntil: 'load' });
    pass.flows.push('方向の 3 案');
    await context.close();
  }
  return pass;
}

// 最初の 1 画面: Lighthouse の既定のモバイル条件（4G 相当、CPU 4 倍遅く、幅 412）で 1 回測り、LCP と CLS で判定する。
// ブラウザには届かない代理を渡すので、ループバックの外へは出ない
async function firstScreen(origin, outFile, mm) {
  let chromium;
  let lighthouse;
  let chromeLauncher;
  try {
    ({ chromium } = require('playwright'));
    lighthouse = (await import('lighthouse')).default;
    chromeLauncher = await import('chrome-launcher');
  } catch (e) {
    const why = `lighthouse か chrome-launcher が読めない: ${String(e.message).split('\n')[0]}`;
    return { ok: false, detail: `測れない（${why}）`, fails: [why] };
  }
  let chrome = null;
  try {
    chrome = await chromeLauncher.launch({
      chromePath: chromium.executablePath(),
      chromeFlags: ['--headless=new', '--no-first-run', '--disable-gpu', `--proxy-server=${mm.PROXY.server}`],
    });
    const result = await lighthouse(`${origin}/`, { port: chrome.port, output: 'json', logLevel: 'error', onlyCategories: ['performance'] });
    const lhr = result.lhr;
    const a = lhr.audits;
    const lcp = Math.round(a['largest-contentful-paint'].numericValue);
    const cls = Math.round(a['cumulative-layout-shift'].numericValue * 1000) / 1000;
    const t = lhr.configSettings.throttling;
    const w = lhr.configSettings.screenEmulation.width;
    if (outFile) fs.writeFileSync(outFile, `${JSON.stringify(lhr, null, 1)}\n`);
    const fails = [];
    if (!(lcp <= LCP_MS)) fails.push(`LCP ${lcp}ms（予算 ${LCP_MS}ms）`);
    if (!(cls <= CLS_MAX)) fails.push(`CLS ${cls}（予算 ${CLS_MAX}）`);
    const cond = `Lighthouse ${lhr.lighthouseVersion} の既定のモバイル条件。往復 ${t.rttMs}ms、下り ${Math.round(t.throughputKbps / 100) / 10}Mbps、CPU ${t.cpuSlowdownMultiplier} 倍遅く、幅 ${w}px で 1 回`;
    return { ok: fails.length === 0, detail: `LCP ${lcp}ms、CLS ${cls}（予算 ${LCP_MS}ms と ${CLS_MAX}。${cond}）`, fails };
  } catch (e) {
    const why = `Lighthouse を回せない: ${String(e.message || e).split('\n')[0]}`;
    return { ok: false, detail: `測れない（${why}）`, fails: [why] };
  } finally {
    if (chrome) await Promise.resolve(chrome.kill()).catch(() => {});
  }
}

// 監修の材料: seek で撮るフレーム、本当に押して撮るフレーム、方向の 3 案。一覧（frames.json）に撮った条件を残す。
// 撮るもの（監修記録の完成例 design-review-dive-log.md のフレームの一覧と同じ条件。監修のたびに手で撮らなくて済む）:
//   seek: 初回の 0ms から終わりまで 100ms ごと（full-）、2 回目以降の短い版の 0ms から終わりまで 100ms ごとと 250ms（short-）、
//         動きを減らす設定の 0ms・半ば・終わり（reduced-）
//   押して: 静止の画面（終わって 400ms 後）、飛ばしたとき（500ms で字のキー k の前とあと）、背景を止める前後の 1 秒あけた 2 枚ずつ、
//         Tab の焦点（スタート・パスワード・乗船する）、乗船するのホバーと押し込み、誤りの状態、送信中の姿、
//         戻る（View Transitions）の 0ms から 400ms まで 100ms ごと、素材が間に合わないとき（scene.js を遅らせ、押して 100・300・700ms。実時間）
//   画面の条件: 幅 375px の計器盤、強制カラーの計器盤（焦点つき）
async function shots(browser, origin, out, mm, ledger) {
  const frames = path.join(out, 'frames');
  const dirs = path.join(out, 'directions');
  fs.mkdirSync(frames, { recursive: true });
  fs.mkdirSync(dirs, { recursive: true });
  const written = [];
  const list = [];
  const sink = { errors: [], external: 0, requests: 0, flows: [] };
  const take = async (page, dir, name, how) => {
    const file = path.join(dir, name);
    fs.writeFileSync(file, await page.screenshot());
    written.push(file);
    list.push({ file: path.relative(out, file), how, at: new Date().toISOString() });
  };
  const seekTo = (page, ms, version) => page.evaluate(([t, v]) => window.__scene.seek(t, v), [ms, version]);
  const twoFrames = (page) => page.evaluate(() => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res))));
  const center = async (page, sel) => {
    const b = await page.locator(sel).boundingBox();
    return [b.x + b.width / 2, b.y + b.height / 2];
  };
  const full = ledger.versions.full.total_ms;
  const short = ledger.versions.short.total_ms;
  const reduced = ledger.versions.reduced.total_ms;
  // seek: 初回と 2 回目以降
  {
    const { context, page } = await newPage(browser, { reducedMotion: 'no-preference' }, sink, '撮影', mm);
    await page.goto(`${origin}/`, { waitUntil: 'load' });
    await ready(page);
    for (let ms = 0; ms <= full; ms += 100) {
      await seekTo(page, ms, 'full');
      await take(page, frames, `full-${pad(ms)}.png`, `初回 ${ms}ms（seek）`);
    }
    const times = [];
    for (let ms = 0; ms <= short; ms += 100) times.push(ms);
    times.push(250);
    for (const ms of times.sort((a, b) => a - b)) {
      await seekTo(page, ms, 'short');
      await take(page, frames, `short-${pad(ms)}.png`, `2 回目以降の短い版 ${ms}ms（seek）`);
    }
    await context.close();
  }
  // seek: 動きを減らす設定
  {
    const { context, page } = await newPage(browser, { reducedMotion: 'reduce' }, sink, '撮影の縮小版', mm);
    await page.goto(`${origin}/`, { waitUntil: 'load' });
    await ready(page);
    for (const ms of [0, Math.round(reduced / 2), reduced]) {
      await seekTo(page, ms, 'reduced');
      await take(page, frames, `reduced-${pad(ms)}.png`, `動きを減らす設定 ${ms}ms（seek）`);
    }
    await context.close();
  }
  // 本当に押して撮る
  {
    const { context, page } = await newPage(browser, { reducedMotion: 'no-preference' }, sink, '撮影の操作', mm);
    await page.goto(`${origin}/`, { waitUntil: 'load' });
    await ready(page);
    await sleep(500); // 背景の canvas が溶け込む 400ms を待つ
    // Tab の焦点: スタート
    await page.keyboard.press('Tab');
    await twoFrames(page);
    await take(page, frames, 'key-start-focus.png', '海面で Tab を 1 回（スタートの焦点）');
    // 静止の画面: ポインターで押し、終わって 400ms 後
    await page.evaluate(() => window.__scene.reset());
    const start = await center(page, '#start');
    await page.mouse.move(...start);
    await twoFrames(page);
    await page.mouse.down();
    await page.mouse.up();
    await stateIs(page, 'panel');
    await sleep(400);
    await take(page, frames, 'still.png', '押して終わってから 400ms 後（静止の画面）');
    // 背景を止める前後: 1 秒あけた 2 枚ずつ
    await page.mouse.move(4, 4);
    await take(page, frames, 'calm-off-1.png', '止める前の 1 枚目');
    await sleep(1000);
    await take(page, frames, 'calm-off-2.png', '止める前の 2 枚目（1 秒後）');
    await page.click('.calm');
    await page.mouse.move(4, 4);
    await sleep(300);
    await take(page, frames, 'calm-on-1.png', '「背景の動きを止める」を押して 300ms 後');
    await sleep(1000);
    await take(page, frames, 'calm-on-2.png', '止めたあとの 2 枚目（1 秒後）');
    await page.click('.calm');
    // Tab の焦点: パスワードと乗船する
    await page.focus('#email');
    await page.keyboard.press('Tab');
    await twoFrames(page);
    await take(page, frames, 'key-password-focus.png', 'メールアドレスから Tab（パスワードの焦点）');
    await page.keyboard.press('Tab');
    await twoFrames(page);
    await take(page, frames, 'key-board-focus.png', 'もう 1 回 Tab（乗船するの焦点）');
    // 乗船するのホバーと押し込み。離すと送信になり、欄が空なので誤りの状態になる
    const board = await center(page, '.board');
    await page.mouse.move(...board);
    await sleep(200);
    await take(page, frames, 'board-hover.png', '乗船するにポインターを置いて 200ms 後（ホバー）');
    await page.mouse.down();
    await sleep(150);
    await take(page, frames, 'board-press.png', '乗船するを押したまま 150ms 後（押し込み）');
    await page.mouse.up();
    await page.mouse.move(4, 4);
    await sleep(300);
    await take(page, frames, 'error-panel.png', '空のまま乗船するを押して 300ms 後（誤りの状態）');
    // 送信中の姿: 形の正しい架空の値を入れて押す（サンプルなので送信はしない）
    await page.fill('#email', 'observer@example.com');
    await page.fill('#password', 'sample-only');
    await page.click('.board');
    await page.mouse.move(4, 4);
    await sleep(300);
    await take(page, frames, 'busy-panel.png', '架空の値を入れて乗船するを押して 300ms 後（送信中）');
    // 戻る（View Transitions）: 動きを止めて 100ms ごとに巻いて撮る
    const vt = await page.evaluate(async () => {
      history.back();
      for (let i = 0; i < 120; i += 1) {
        await new Promise((res) => requestAnimationFrame(res));
        const list = document.getAnimations().filter((a) => ((a.effect && a.effect.pseudoElement) || '').startsWith('::view-transition'));
        if (list.length) {
          list.forEach((a) => a.pause());
          window.__vtShots = list;
          return list.length;
        }
      }
      return 0;
    });
    if (vt) {
      for (let ms = 0; ms <= 400; ms += 100) {
        await page.evaluate((t) => window.__vtShots.forEach((a) => { a.currentTime = t; }), ms);
        await twoFrames(page);
        await take(page, frames, `return-${pad(ms)}.png`, `戻る（View Transitions）${ms}ms（動きを止めて巻いた）`);
      }
      await page.evaluate(() => window.__vtShots.forEach((a) => a.finish()));
    } else {
      sink.errors.push('撮影の操作: 戻るの View Transitions の動きが見つからない');
    }
    await stateIs(page, 'surface');
    // 飛ばしたとき: 押して 500ms で字のキー k
    await page.evaluate(() => window.__scene.reset());
    await page.mouse.move(...start);
    await twoFrames(page);
    await page.mouse.down();
    await page.mouse.up();
    await sleep(500);
    await take(page, frames, 'skip-0500-before.png', '押して約 500ms（字のキーの前）');
    await page.keyboard.press('k');
    await stateIs(page, 'panel');
    await sleep(300);
    await take(page, frames, 'skip-after.png', '字のキー k で飛ばして 300ms 後');
    await context.close();
  }
  // 素材が間に合わないとき: scene.js を 1.5 秒遅らせ、海面に着いたら押す（実時間なので、撮るたびに少し違う）
  {
    const { context, page } = await newPage(browser, { reducedMotion: 'no-preference' }, sink, '撮影の素材の遅れ', mm);
    await page.route('**/scene.js', async (route) => {
      await sleep(1500);
      await route.continue();
    });
    await page.goto(`${origin}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => window.__scene && window.__scene.state === 'surface', null, { timeout: 5000 });
    const start = await center(page, '#start');
    await page.mouse.move(...start);
    await page.mouse.down();
    await page.mouse.up();
    const t0 = Date.now();
    for (const ms of [100, 300, 700]) {
      await sleep(Math.max(0, ms - (Date.now() - t0)));
      await take(page, frames, `late-${pad(ms)}.png`, `背景が未着のまま押して約 ${ms}ms（実時間）`);
    }
    await context.close();
  }
  // 幅 375px の計器盤
  {
    const { context, page } = await newPage(browser, { reducedMotion: 'no-preference', viewport: { width: 375, height: 812 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true }, sink, '撮影の幅 375', mm);
    await page.goto(`${origin}/#panel`, { waitUntil: 'load' });
    await ready(page);
    await stateIs(page, 'panel');
    await sleep(500);
    await take(page, frames, 'narrow-panel.png', '幅 375px で #panel を開き 500ms 後');
    await context.close();
  }
  // 強制カラーの計器盤（焦点はメールアドレスの欄）
  {
    const { context, page } = await newPage(browser, { reducedMotion: 'no-preference', forcedColors: 'active' }, sink, '撮影の強制カラー', mm);
    await page.goto(`${origin}/#panel`, { waitUntil: 'load' });
    await ready(page);
    await stateIs(page, 'panel');
    await sleep(500);
    await take(page, frames, 'forced-colors-panel.png', '強制カラーで #panel を開き 500ms 後');
    await context.close();
  }
  // 方向の 3 案
  {
    const { context, page } = await newPage(browser, {}, sink, '撮影の方向', mm);
    for (const d of DIRECTIONS) {
      await page.goto(`${origin}/directions/${d}.html`, { waitUntil: 'load' });
      await sleep(50);
      await take(page, dirs, `direction-${d}.png`, `方向の案 ${d.toUpperCase()}（静止画）`);
    }
    await context.close();
  }
  fs.writeFileSync(path.join(out, 'frames.json'), `${JSON.stringify({ tool: 'immersive-test --shots', taken_at: new Date().toISOString(), viewport: { width: 1280, height: 800 }, files: list }, null, 1)}\n`);
  return { written, sink, frames: written.filter((f) => f.startsWith(`${frames}${path.sep}`)).length, directions: written.filter((f) => f.startsWith(`${dirs}${path.sep}`)).length };
}

// ---- 本体
async function loadMeasure() {
  return import(pathToFileURL(measureScript).href);
}

function staticPoint() {
  // 台帳と演出計画書の表（ブラウザなし）
  const ledger = JSON.parse(fs.readFileSync(path.join(sampleDir, 'ledger.json'), 'utf8'));
  const plan = planTable(fs.readFileSync(planPath, 'utf8'));
  const diff = comparePlan(plan, ledger);
  const rows = plan.rows ? plan.rows.length : 0;
  return {
    ledger,
    point: {
      name: '台帳と演出計画',
      ok: diff.length === 0,
      detail: diff.length ? `${diff.length} 件の食い違い` : `初回の版の拍 ${rows} 行が、演出計画書の時刻・段・長さ・曲線と同じ。初回 ${plan.lengths[0].toLocaleString('en-US')}ms、2 回目 ${plan.lengths[1] ?? '－'}ms`,
      fails: diff,
    },
  };
}

function stop(kind, msg, label) {
  console.log(`FAIL immersive-test [${kind}] ${msg}`);
  console.log(`RESULT: FAIL immersive-test ${label}`);
}

async function main(args) {
  const known = new Set(['--record', '--shots', '--selftest']);
  for (let i = 0; i < args.length; i++) {
    if (!known.has(args[i])) {
      stop('使い方', `知らない引数 ${args[i]}`, '使い方');
      return 2;
    }
    if (args[i] !== '--selftest') {
      if (!args[i + 1] || args[i + 1].startsWith('--')) {
        stop('使い方', `${args[i]} のあとに置き場が無い`, '使い方');
        return 2;
      }
      i++;
    }
  }
  const opt = (k) => (args.includes(k) ? path.resolve(args[args.indexOf(k) + 1]) : null);
  let mm;
  try {
    mm = await loadMeasure();
  } catch (e) {
    stop('道具が無い', `${path.relative(root, measureScript)} を読めない: ${String(e.message).split('\n')[0]}`, '道具');
    return 1;
  }
  if (args.includes('--selftest')) return selftest(mm) ? 0 : 1;

  const record = opt('--record') || path.join(verifyDir, 'immersive-measure.json');
  const out = opt('--shots');
  const problem = mm.writeProblem(record) || (out ? mm.writeProblem(out, { json: false }) : null);
  if (problem) {
    stop('使い方', problem, '使い方');
    return 2;
  }
  let stat;
  try {
    stat = staticPoint();
  } catch (e) {
    stop('台帳と演出計画', `読めない: ${String(e.message).split('\n')[0]}`, '台帳');
    return 1;
  }
  const scene = stat.ledger.id;
  // 計測: motion-measure を既定の回数（2 条件 × 3 回）で回す（子のプロセス。時間切れは motion-measure の 300 秒）。
  // 記録は先に消し、今回の計測が書いた物だけを読む
  fs.mkdirSync(path.dirname(record), { recursive: true });
  fs.rmSync(record, { force: true });
  const started = Date.now();
  const child = spawnSync(process.execPath, [measureScript, '--dir', sampleDir, '--scene', String(scene), '--record', record], { cwd: root, encoding: 'utf8', timeout: 320000 });
  const measured = String(child.stdout || '').split('\n').filter((l) => l.trim());
  if (child.error || ![0, 1].includes(child.status)) {
    for (const l of measured.filter((x) => x.startsWith('FAIL ')).slice(0, 5)) console.log(`INFO immersive-test [motion-measure] ${l}`);
    const why = child.error ? String(child.error.message).split('\n')[0] : `終了コード ${child.status === null ? `なし（${child.signal}）` : child.status}`;
    stop('計測', `motion-measure が測り終えずに止まった（${why}）`, '計測');
    return 1;
  }
  let rec = null;
  try {
    rec = JSON.parse(fs.readFileSync(record, 'utf8'));
  } catch (e) {
    for (const l of measured.slice(-5)) console.log(`INFO immersive-test [motion-measure] ${l}`);
    stop('計測', `記録 ${record} を読めない: ${String(e.message).split('\n')[0]}`, '計測');
    return 1;
  }
  const bad = recordProblems(rec, started);
  if (bad.length) {
    stop('計測', bad.join('。'), '計測');
    return 1;
  }
  // 画面の通しと最初の 1 画面（と、頼まれたら撮影）
  let chromium;
  try {
    ({ chromium } = require('playwright'));
  } catch (e) {
    stop('道具が無い', `playwright が読めない: ${String(e.message).split('\n')[0]}`, '道具');
    return 1;
  }
  const server = await serve(sampleDir);
  const origin = `http://127.0.0.1:${server.address().port}`;
  let browser = null;
  let pass = { errors: [], external: 0, requests: 0, flows: [] };
  let shot = null;
  let screen = null;
  try {
    browser = await chromium.launch({ headless: true, proxy: mm.PROXY });
    try {
      pass = await walk(browser, origin, mm);
    } catch (e) {
      pass.errors.push(`画面の通しが止まった: ${String(e.message || e).split('\n')[0]}`);
    }
    await browser.close().catch(() => {});
    browser = null;
    screen = await firstScreen(origin, path.join(path.dirname(record), 'immersive-lighthouse.json'), mm);
    if (out) {
      browser = await chromium.launch({ headless: true, proxy: mm.PROXY });
      shot = await shots(browser, origin, out, mm, stat.ledger);
    }
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (typeof server.closeAllConnections === 'function') server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
  const kp = keyPoints(rec, pass, mm, screen);
  const extra = [...kp.info, `[記録] ${path.relative(root, record).startsWith('..') ? record : path.relative(root, record)}`];
  if (shot) extra.push(`[撮影] ${shot.written.length} 枚を ${out} に書いた（frames ${shot.frames} 枚、directions ${shot.directions} 枚。一覧は frames.json）${shot.sink.errors.length ? `。撮影中のエラー ${shot.sink.errors.length} 件: ${shot.sink.errors.slice(0, 2).join(' / ')}` : ''}`);
  const runs = (rec.runs || []).length;
  const browserLine = `${rec.browser && rec.browser.version ? `Chromium ${rec.browser.version}、画面なし` : '画面なしのブラウザ'}。計測は 2 条件で計 ${runs} 回`;
  return print([...kp.points, stat.point], extra, browserLine) ? 0 : 1;
}

// ---- 自己試験（ブラウザもサーバーも使わない）
function selftest(mm) {
  const checks = [];
  const okPass = () => ({ errors: [], external: 0, requests: 30, flows: ['海面', '潜る'] });
  const okScreen = () => ({ ok: true, detail: 'LCP 900ms、CLS 0（架空）', fails: [] });
  const failed = (rec, pass, screen = okScreen()) => keyPoints(rec, pass, mm, screen).points.filter((p) => !p.ok).map((p) => p.name);
  // 正例: 架空の記録は要点が全部通る
  checks.push([failed(mm.sampleRecord(), okPass()).length === 0, `架空の正例で落ちた要点: ${failed(mm.sampleRecord(), okPass()).join('、')}`]);
  // 12 項目: どれか 1 つを壊すと、その項目だけが落ちる
  for (const [no, name] of mm.ITEMS) {
    const got = failed(mm.brokenRecord([no]), okPass());
    checks.push([got.length === 1 && got[0] === `${no} ${name}`, `項目 ${no}（${name}）だけを壊した記録で、落ちた要点が ${got.join('、') || 'なし'}`]);
  }
  {
    const got = failed(mm.brokenRecord(mm.ITEMS.map(([no]) => no)), okPass());
    checks.push([got.length === 12, `12 項目を全部壊した記録で、落ちた要点が ${got.length} つ`]);
  }
  // 画面の通しと最初の 1 画面
  {
    const p = okPass();
    p.errors.push('既定: TypeError');
    const got = failed(mm.sampleRecord(), p);
    checks.push([got.length === 1 && got[0] === 'コンソール', `コンソールのエラーだけの通しで、落ちた要点が ${got.join('、') || 'なし'}`]);
  }
  {
    const p = okPass();
    p.external = 2;
    const got = failed(mm.sampleRecord(), p);
    checks.push([got.length === 1 && got[0] === '外への要求（画面の通し）', `外への要求だけの通しで、落ちた要点が ${got.join('、') || 'なし'}`]);
  }
  {
    const got = failed(mm.sampleRecord(), okPass(), { ok: false, detail: 'LCP 3100ms（架空）', fails: ['LCP 3100ms（予算 2500ms）'] });
    checks.push([got.length === 1 && got[0] === '最初の 1 画面', `LCP の超過で、落ちた要点が ${got.join('、') || 'なし'}`]);
  }
  // 4 倍遅い条件だけの 50ms 超でも落ち、INFO で 4 倍遅い条件の回だけだと名指す
  {
    const rec = mm.sampleRecord();
    rec.runs[4].frames[10] = 68;
    const kp = keyPoints(rec, okPass(), mm, okScreen());
    const p3 = kp.points.find((p) => p.name === '3 フレームの間隔');
    checks.push([!kp.ok && p3 && !p3.ok && kp.info.some((l) => l.includes('4 倍遅い条件の回だけ')), '4 倍遅い条件だけの 50ms 超で、要点が落ちないか、INFO で名指さない']);
  }
  // 約束の無いページ（測れない）では、12 項目が全部落ちる
  {
    const rec = mm.sampleRecord();
    rec.contract = { found: false, missing: ['__scene'] };
    const got = failed(rec, okPass());
    checks.push([mm.ITEMS.every(([no, name]) => got.includes(`${no} ${name}`)), `約束の無いページで落ちない項目がある（落ちたのは ${got.join('、')}）`]);
  }
  // 記録の確かめ: 前の回の記録と、架空の記録
  checks.push([recordProblems({ measured_at: '2026-11-26T00:00:00.000Z', browser: { version: '1' } }, Date.parse('2026-11-26T01:00:00.000Z')).length === 1, '前の回の記録を判定に使う']);
  checks.push([recordProblems(mm.sampleRecord(), 0).some((p) => p.includes('架空')), '架空の記録を判定に使う']);
  checks.push([recordProblems({ measured_at: new Date().toISOString(), browser: { version: '1' } }, Date.now() - 5000).length === 0, '今回の記録を断った']);
  checks.push([recordProblems({}, 0).length === 1, 'measured_at の無い記録を判定に使う']);
  // 台帳と演出計画書の表: 今の 2 つは一致し、片方を変えると食い違いが出る
  try {
    const ledger = JSON.parse(fs.readFileSync(path.join(sampleDir, 'ledger.json'), 'utf8'));
    const text = fs.readFileSync(planPath, 'utf8');
    const plan = planTable(text);
    checks.push([plan.rows && plan.rows.length === 9 && plan.lengths[0] === 1400, `演出計画書の表を読めない（${plan.rows ? plan.rows.length : 0} 行、初回 ${plan.lengths[0]}ms）`]);
    checks.push([comparePlan(plan, ledger).length === 0, `今の台帳と演出計画書が食い違う: ${comparePlan(plan, ledger).join(' / ')}`]);
    const moved = JSON.parse(JSON.stringify(ledger));
    moved.versions.full.beats[2].ms = 600;
    checks.push([comparePlan(plan, moved).some((d) => d.includes('長さ 640ms／600ms')), '台帳の拍の長さを変えても、食い違いが出ない']);
    const eased = JSON.parse(JSON.stringify(ledger));
    eased.versions.full.beats[6].ease = 'standard';
    checks.push([comparePlan(plan, eased).some((d) => d.includes('曲線 settle／standard')), '台帳の拍の曲線を変えても、食い違いが出ない']);
    const shifted = planTable(text.replace('| 160ms | 見せ場 |', '| 180ms | 見せ場 |'));
    checks.push([comparePlan(shifted, ledger).some((d) => d.includes('時刻 180ms／160ms')), '計画書の時刻を変えても、食い違いが出ない']);
    checks.push([comparePlan(planTable('# 演出計画書: 空\n'), ledger)[0].includes('時刻ごとの表'), '表の無い計画書が誤りにならない']);
  } catch (e) {
    checks.push([false, `台帳か演出計画書を読めない: ${String(e.message).split('\n')[0]}`]);
  }
  let ok = true;
  for (const [passed, msg] of checks) {
    if (!passed) {
      ok = false;
      console.log(`FAIL selftest immersive-test: ${msg}`);
    }
  }
  console.log(`RESULT: ${ok ? 'PASS' : 'FAIL'} immersive-test --selftest (${checks.length} 例。ブラウザなし)`);
  return ok;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const timer = setTimeout(() => {
    console.log('FAIL immersive-test [時間] 480 秒で終わらない');
    console.log('RESULT: FAIL immersive-test 時間切れ');
    process.exit(1);
  }, 480000);
  timer.unref();
  main(process.argv.slice(2)).then(
    (rc) => process.exit(rc),
    (e) => {
      console.log(`FAIL immersive-test [実行] ${String(e.message || e).split('\n')[0]}`);
      console.log('RESULT: FAIL immersive-test 実行');
      process.exit(1);
    },
  );
}
