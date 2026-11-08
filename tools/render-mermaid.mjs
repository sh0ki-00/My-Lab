#!/usr/bin/env node
// tools/render-mermaid.mjs <ファイル>... — Markdown の ```mermaid を実際にブラウザで描き、描けない図を落とす。
// Playwright の Chromium に node_modules/mermaid/dist/mermaid.min.js を読み込み、mermaid.parse と mermaid.render を呼ぶ。
// 出力: FAIL <ファイル>:<行> [描画] <内容> を並べ、最後に RESULT: PASS|FAIL render-mermaid (<n> 図)。1 件でも FAIL なら終了コード 1。
// node_modules は tools/../node_modules（My-Lab）か、tmp/DEPLOYED.md の「正本: <パス>」の下から探す。
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

function findNodeModules() {
  const candidates = [path.resolve(here, '..', 'node_modules')];
  const deployed = path.resolve(here, '..', 'DEPLOYED.md');
  if (fs.existsSync(deployed)) {
    const m = fs.readFileSync(deployed, 'utf8').match(/正本:\s*`?([^`\s]+)/);
    if (m) candidates.push(path.join(m[1], 'node_modules'));
  }
  return candidates.find(
    (c) => fs.existsSync(path.join(c, 'mermaid', 'dist', 'mermaid.min.js')) && fs.existsSync(path.join(c, 'playwright')),
  );
}

function extract(file) {
  const lines = fs.readFileSync(file, 'utf8').split('\n');
  const blocks = [];
  let fence = null;
  let cur = null;
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].trim();
    if (fence) {
      if (t.startsWith(fence)) {
        if (cur) blocks.push({ line: cur.line, code: cur.code.join('\n') });
        fence = null;
        cur = null;
      } else if (cur) {
        cur.code.push(lines[i]);
      }
      continue;
    }
    const m = t.match(/^(`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)/);
    if (m) {
      fence = m[1];
      cur = m[2].toLowerCase() === 'mermaid' ? { line: i + 1, code: [] } : null;
    }
  }
  return blocks;
}

async function main(files) {
  if (files.length === 0) {
    console.log('使い方: render-mermaid.mjs <ファイル>...');
    return 2;
  }
  const nm = findNodeModules();
  if (!nm) {
    console.log('FAIL render-mermaid [道具が無い] node_modules に mermaid と playwright が無い（My-Lab で npm install）');
    console.log('RESULT: FAIL render-mermaid (0 図)');
    return 1;
  }
  const require = createRequire(path.join(path.dirname(nm), 'noop.js'));
  const { chromium } = require('playwright');
  const browser = await chromium.launch();
  let total = 0;
  let failed = 0;
  try {
    const page = await browser.newPage();
    await page.setContent('<!doctype html><html><body><div id="c"></div></body></html>');
    await page.addScriptTag({ path: path.join(nm, 'mermaid', 'dist', 'mermaid.min.js') });
    await page.evaluate(() => window.mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' }));
    for (const file of files) {
      const blocks = extract(file);
      let fileFail = 0;
      for (let i = 0; i < blocks.length; i++) {
        total += 1;
        const r = await page.evaluate(
          async ({ id, code }) => {
            try {
              await window.mermaid.parse(code);
              const { svg } = await window.mermaid.render(id, code);
              const div = document.getElementById('c');
              div.innerHTML = svg;
              const root = div.querySelector('svg');
              if (!root) return { ok: false, err: 'svg が出ない' };
              const err = div.querySelector('.error-text, .error-icon');
              if (err) return { ok: false, err: (err.textContent || '描画エラー').trim().slice(0, 120) };
              const box = root.getBoundingClientRect();
              if (!(box.width > 0 && box.height > 0)) return { ok: false, err: `大きさが 0（${box.width}x${box.height}）` };
              return { ok: true, len: svg.length };
            } catch (e) {
              return { ok: false, err: String((e && e.message) || e).split('\n')[0].slice(0, 160) };
            }
          },
          { id: `m${total}`, code: blocks[i].code },
        );
        if (!r.ok) {
          failed += 1;
          fileFail += 1;
          console.log(`FAIL ${file}:${blocks[i].line} [描画] ${r.err}`);
        }
      }
      console.log(`RESULT: ${fileFail ? 'FAIL' : 'PASS'} render-mermaid ${file} (${blocks.length} 図、${fileFail} 件)`);
    }
  } finally {
    await browser.close();
  }
  console.log(`RESULT: ${failed ? 'FAIL' : 'PASS'} render-mermaid (${total} 図、${failed} 件)`);
  return failed ? 1 : 0;
}

main(process.argv.slice(2)).then(
  (rc) => process.exit(rc),
  (e) => {
    console.log(`FAIL render-mermaid [実行] ${String((e && e.message) || e).split('\n')[0]}`);
    console.log('RESULT: FAIL render-mermaid (0 図)');
    process.exit(1);
  },
);
