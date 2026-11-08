#!/usr/bin/env node
// tools/sample-app-test.mjs — 見本アプリ（samples/app）の実測（仕様書 9.4 節の 10）。
//   型: node --check。単体テスト: 画面の振る舞い（行数、絞り込み、件数の表示、キーボード、コンソールのエラー）。
//   読み上げ: アクセシビリティの木の名前（表、検印、ラベル、件数）。axe: 違反 0。Lighthouse: 性能 90 以上、アクセシビリティ 90 以上。Lighthouse の結果は tmp/.verify/lighthouse.json に残す。
//   出力: FAIL sample-app [<観点>] <内容> と、最後に RESULT: PASS|FAIL sample-app-test。1 件でも FAIL なら終了コード 1。
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
// 既定は samples/app。SAMPLE_APP_DIR を渡すと、別の案のフォルダ（tmp/flow/stage3/variants/ など）を同じ検査にかける
const appDir = process.env.SAMPLE_APP_DIR ? path.resolve(process.env.SAMPLE_APP_DIR) : path.join(root, 'samples', 'app');
const require = createRequire(import.meta.url);
let fail = 0;
const bad = (kind, msg) => {
  fail += 1;
  console.log(`FAIL sample-app [${kind}] ${msg}`);
};
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml' };

function serve() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      let p = decodeURIComponent(new URL(req.url, 'http://local').pathname);
      if (p === '/') p = '/index.html';
      const file = path.join(appDir, path.normalize(p));
      if (!file.startsWith(appDir) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
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

async function main() {
  if (!fs.existsSync(path.join(appDir, 'index.html'))) {
    bad('見本', `${appDir}/index.html が無い`);
    console.log('RESULT: FAIL sample-app-test');
    return 1;
  }
  for (const f of fs.readdirSync(appDir).filter((n) => n.endsWith('.js'))) {
    try {
      execFileSync(process.execPath, ['--check', path.join(appDir, f)], { stdio: 'pipe' });
    } catch (e) {
      bad('型', `${f}: ${String(e.stderr || e.message).split('\n')[0]}`);
    }
  }
  let chromium;
  let AxeBuilder;
  let lighthouse;
  let chromeLauncher;
  try {
    ({ chromium } = require('playwright'));
    ({ AxeBuilder } = require('@axe-core/playwright'));
    lighthouse = (await import('lighthouse')).default;
    chromeLauncher = await import('chrome-launcher');
  } catch (e) {
    bad('道具が無い', `playwright・@axe-core/playwright・lighthouse が入っていない（npm install）: ${String(e.message).split('\n')[0]}`);
    console.log('RESULT: FAIL sample-app-test');
    return 1;
  }

  const server = await serve();
  const url = `http://127.0.0.1:${server.address().port}/`;
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => {
      if (m.type() === 'error') errors.push(m.text());
    });
    await page.goto(url, { waitUntil: 'load' });

    if (!/注文一覧/.test(await page.title())) bad('単体', 'title に「注文一覧」が無い');
    const rows = await page.locator('#orders tbody tr[data-status]').count();
    if (rows !== 29) bad('単体', `行数 ${rows}（29 を期待。未出荷の 18、出荷指示の直後の 5、畳んだ済の 6）`);
    if ((await page.textContent('#count')).trim() !== '') bad('単体', '絞り込みが無いのに、件数の字が出ている');
    await page.fill('#q', '佐藤');
    const byText = await page.locator('#orders tbody tr[data-status]:visible').count();
    if (byText !== 2) bad('単体', `「佐藤」で絞った行数 ${byText}（2 を期待）`);
    if ((await page.textContent('#count')).trim() !== '2件') bad('単体', `件数の表示が「${(await page.textContent('#count')).trim()}」（2件を期待）`);
    await page.fill('#q', '存在しない顧客');
    if (await page.locator('#empty').isHidden()) bad('単体', '0 件のときに空の案内が出ない');
    await page.fill('#q', '');
    await page.selectOption('#st', 'ready');
    const byStatus = await page.locator('#orders tbody tr[data-status]:visible').count();
    const paid = await page.locator('#orders tbody tr[data-status="ready"]').count();
    if (byStatus !== paid) bad('単体', `状態で絞った行数 ${byStatus}（${paid} を期待）`);
    if (await page.locator('.done-head button').count()) {
      // 監修 8 回目の指摘 1 の回帰: 「済」に絞ると開き、そのあとも押して閉じられる
      const doneToggle = page.locator('.done-head button');
      await page.selectOption('#st', 'done');
      if ((await doneToggle.getAttribute('aria-expanded')) !== 'true') bad('単体', '状態で「済」に絞っても、済の群が開かない');
      await doneToggle.click();
      if ((await doneToggle.getAttribute('aria-expanded')) !== 'false' || !(await page.locator('#done-rows').isHidden())) bad('単体', '「済」に絞ったあと、済の群を閉じられない');
    }
    await page.selectOption('#st', '');
    await page.reload({ waitUntil: 'load' });
    await page.keyboard.press('Tab');
    const first = await page.evaluate(() => document.activeElement && (document.activeElement.className || document.activeElement.id));
    if (first !== 'skip') bad('単体', `最初の Tab で「表へ移る」に届かない（${first}）`);
    await page.keyboard.press('Enter');
    const afterSkip = await page.evaluate(() => document.activeElement && document.activeElement.id);
    if (afterSkip !== 'orders') bad('単体', `「表へ移る」で表に移らない（${afterSkip}）`);
    if (errors.length) bad('単体', `コンソールのエラー: ${errors[0]}`);
    // 焦点が固定の見出しの裏に入らない（WCAG 2.2 の 2.4.11）: scroll-padding-top が、上に固定した帯と見出しの下端に届く
    const stickyPad = async (pg, w) => {
      const r = await pg.evaluate(() => {
        const sticky = (el) => getComputedStyle(el).position === 'sticky' && el.getBoundingClientRect().height > 0;
        const tops = [...document.querySelectorAll('.toolbar, #orders thead th, #orders tr.group th, #orders tr.group')].filter(sticky);
        const bottoms = [...document.querySelectorAll('.bulkbar')].filter(sticky);
        const html = getComputedStyle(document.documentElement);
        return {
          need: Math.round(Math.max(0, ...tops.map((el) => (parseFloat(getComputedStyle(el).top) || 0) + el.getBoundingClientRect().height))),
          have: parseFloat(html.scrollPaddingTop) || 0,
          needBottom: Math.round(Math.max(0, ...bottoms.map((el) => (parseFloat(getComputedStyle(el).bottom) || 0) + el.getBoundingClientRect().height))),
          haveBottom: parseFloat(html.scrollPaddingBottom) || 0,
        };
      });
      if (r.have + 1 < r.need) bad('単体', `幅 ${w} で scroll-padding-top ${r.have}px が、固定の帯と見出しの ${r.need}px に足りない`);
      if (r.haveBottom + 1 < r.needBottom) bad('単体', `幅 ${w} で scroll-padding-bottom ${r.haveBottom}px が、下に固定した一括操作の帯の ${r.needBottom}px に足りない`);
    };
    await stickyPad(page, 1280);
    {
      // 監修 8 回目の指摘 2 の回帰: 幅 640 で列を隠しても、見出し行が表の右端まで届く
      const narrow = await browser.newContext({ viewport: { width: 640, height: 400 } });
      const p2 = await narrow.newPage();
      await p2.goto(url, { waitUntil: 'load' });
      const gap = await p2.evaluate(() => {
        const t = document.querySelector('#orders').getBoundingClientRect();
        const ths = [...document.querySelectorAll('#orders thead th')].filter((th) => th.getBoundingClientRect().width > 0);
        return Math.round(t.right - Math.max(...ths.map((th) => th.getBoundingClientRect().right)));
      });
      if (gap > 1) bad('単体', `幅 640 で見出し行が表の右端より ${gap}px 手前で切れる`);
      await stickyPad(p2, 640);
      await narrow.close();
      // 監修 9 回目の指摘 2 の回帰: 幅 320 で一括操作の帯が 2 段に折れても、下の余白が足りる
      const phone = await browser.newContext({ viewport: { width: 320, height: 568 } });
      const p3 = await phone.newPage();
      await p3.goto(url, { waitUntil: 'load' });
      await stickyPad(p3, 320);
      // 監修 9 回目の指摘 6 の回帰: 2 段の一覧（幅 320）でも axe の違反 0（列の見出しが空にならない）
      const axe320 = await new AxeBuilder({ page: p3 }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']).analyze();
      for (const v of axe320.violations.slice(0, 3)) bad('axe', `幅 320: ${v.id}: ${v.help}（${v.nodes.length} 箇所）`);
      await phone.close();
    }
    if (fail === 0) console.log('RESULT: PASS unit (行数・絞り込み・件数・空の案内・済の開閉・キーボード・固定の帯の余白・幅 640 と 320)');

    // 読み上げ: 読み上げソフトが読む名前（アクセシビリティの木）を確かめる。人の耳の代わりの自動の検査（承認記録 A-5）。
    const tree = await page.locator('body').ariaSnapshot();
    const before = fail;
    if (!/table "[^"]+"/.test(tree)) bad('読み上げ', '表に名前（caption）が無い');
    const toggle = page.getByRole('button', { name: /^済\s*\d+件\s*開く$/ });
    if (await page.locator('.done-head').count() && !(await toggle.count())) bad('読み上げ', '畳んだ済の群の見出しが「済 N 件 開く」と読まれない');
    if (await toggle.count()) {
      if ((await toggle.getAttribute('aria-expanded')) !== 'false') bad('読み上げ', '畳んだ済の群が、閉じていると読まれない');
      await toggle.click();
      if ((await page.getByRole('button', { name: /^済\s*\d+件\s*閉じる$/ }).getAttribute('aria-expanded')) !== 'true') bad('読み上げ', '済の群を開いても、開いたと読まれない');
    }
    const seals = await page.locator('tr[data-status] .seal').count();
    const named = await page.getByRole('img', { name: /^出荷指示済み、/ }).count();
    if (seals && named !== seals) bad('読み上げ', `検印 ${seals} 個のうち、意味の名前で読まれるのは ${named} 個`);
    if (!/searchbox "検索"/.test(tree)) bad('読み上げ', '検索欄の名前が「検索」で読まれない');
    if (!/combobox "状態"/.test(tree)) bad('読み上げ', '状態の選択の名前が「状態」で読まれない');
    const live = await page.locator('#count').getAttribute('aria-live');
    if (live !== 'polite') bad('読み上げ', '件数の変化が読み上げに伝わらない（aria-live が無い）');
    if (fail === before) console.log(`RESULT: PASS a11y-names (表の名前、検印 ${named} 個の名前、検索と状態のラベル、件数の読み上げ)`);

    const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']).analyze();
    if (axe.violations.length) {
      for (const v of axe.violations.slice(0, 5)) bad('axe', `${v.id}: ${v.help}（${v.nodes.length} 箇所）`);
    } else {
      console.log(`RESULT: PASS axe (違反 0、確認 ${axe.passes.length} 項目)`);
    }
    await context.close();
  } finally {
    await browser.close();
  }

  try {
    const chrome = await chromeLauncher.launch({
      chromePath: chromium.executablePath(),
      chromeFlags: ['--headless=new', '--no-first-run', '--disable-gpu'],
    });
    try {
      const result = await lighthouse(url, {
        port: chrome.port,
        output: 'json',
        logLevel: 'error',
        onlyCategories: ['performance', 'accessibility', 'best-practices'],
        formFactor: 'desktop',
        screenEmulation: { mobile: false, width: 1280, height: 940, deviceScaleFactor: 1, disabled: false },
        throttling: { rttMs: 40, throughputKbps: 10240, cpuSlowdownMultiplier: 1, requestLatencyMs: 0, downloadThroughputKbps: 0, uploadThroughputKbps: 0 },
      });
      const cats = result.lhr.categories;
      const perf = Math.round(cats.performance.score * 100);
      const a11y = Math.round(cats.accessibility.score * 100);
      const bp = Math.round(cats['best-practices'].score * 100);
      if (perf < 90) bad('Lighthouse', `性能 ${perf}（90 以上を期待）`);
      if (a11y < 90) bad('Lighthouse', `アクセシビリティ ${a11y}（90 以上を期待）`);
      console.log(`RESULT: ${perf >= 90 && a11y >= 90 ? 'PASS' : 'FAIL'} lighthouse (性能 ${perf}、アクセシビリティ ${a11y}、ベストプラクティス ${bp})`);
      fs.mkdirSync(path.join(root, 'tmp', '.verify'), { recursive: true });
      fs.writeFileSync(path.join(root, 'tmp', '.verify', 'lighthouse.json'), JSON.stringify(result.lhr, null, 1));
    } finally {
      await chrome.kill();
    }
  } catch (e) {
    bad('Lighthouse', `実行できない: ${String(e.message || e).split('\n')[0]}`);
  }
  server.close();
  console.log(`RESULT: ${fail ? 'FAIL' : 'PASS'} sample-app-test (${fail} 件)`);
  return fail ? 1 : 0;
}

main().then(
  (rc) => process.exit(rc),
  (e) => {
    console.log(`FAIL sample-app [実行] ${String(e.message || e).split('\n')[0]}`);
    console.log('RESULT: FAIL sample-app-test');
    process.exit(1);
  },
);
