#!/usr/bin/env node
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const { chromium } = require('playwright');
const [project, requestedCheck] = process.argv.slice(2);
const labels = {
  startup: 'Open the generated web app',
  'local-import': 'Import songs from a nested local folder',
};
assert(project && (!requestedCheck || Object.hasOwn(labels, requestedCheck)),
  'Provide a project path and, optionally, startup or local-import.');
const root = await realpath(project);
const origin = 'http://127.0.0.1:49154';
const mediaTypes = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
  '.mjs': 'text/javascript', '.json': 'application/json',
};
const fixtureNames = ['demo-tone-alpha.wav', 'demo-tone-beta.wav'];
const result = [];
const pageErrors = [];

function quietTone() {
  const sampleRate = 16_000;
  const frames = sampleRate * 3;
  const wave = Buffer.alloc(44 + frames * 2);
  wave.write('RIFF', 0);
  wave.writeUInt32LE(wave.length - 8, 4);
  wave.write('WAVEfmt ', 8);
  wave.writeUInt32LE(16, 16);
  wave.writeUInt16LE(1, 20);
  wave.writeUInt16LE(1, 22);
  wave.writeUInt32LE(sampleRate, 24);
  wave.writeUInt32LE(sampleRate * 2, 28);
  wave.writeUInt16LE(2, 32);
  wave.writeUInt16LE(16, 34);
  wave.write('data', 36);
  wave.writeUInt32LE(frames * 2, 40);
  for (let frame = 0; frame < frames; frame++) {
    const sample = Math.round(2_600 * Math.sin(2 * Math.PI * 196 * frame / sampleRate));
    wave.writeInt16LE(sample, 44 + frame * 2);
  }
  return wave;
}

async function check(id, operation) {
  try {
    const pendingReason = await operation();
    result.push({ id, name: labels[id], ok: true,
      ...(pendingReason && { pending: true, reason: pendingReason }) });
    return true;
  } catch (error) {
    result.push({ id, name: labels[id], ok: false, code: error.code ?? 'verification-error', error: error.message });
    return false;
  }
}

function requireCheck(condition, code, message) {
  if (!condition) throw Object.assign(new Error(message), { code });
}

const browser = await chromium.launch({
  channel: 'chrome',
  headless: true,
  chromiumSandbox: true,
});
try {
  const context = await browser.newContext({ serviceWorkers: 'block' });
  await context.routeWebSocket('**/*', socket => socket.close());
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin || request.method() !== 'GET') return route.abort();
    try {
      const resource = url.pathname === '/' ? '/index.html' : decodeURIComponent(url.pathname);
      const filename = await realpath(path.resolve(root, '.' + resource));
      if (!filename.startsWith(root + path.sep)) throw new Error('Outside the project');
      return await route.fulfill({ body: await readFile(filename),
        contentType: mediaTypes[path.extname(filename)] ?? 'application/octet-stream' });
    } catch {
      return route.fulfill({ status: 404, body: 'Not found' });
    }
  });
  const page = await context.newPage();
  page.setDefaultTimeout(5_000);
  page.on('pageerror', error => pageErrors.push(error.message));

  async function openPage() {
    const response = await page.goto(`${origin}/`);
    requireCheck(response?.status() === 200, 'page-load', 'The generated page did not load');
    requireCheck((await page.locator('body').innerText()).trim(), 'page-empty', 'The generated page is empty');
    const styled = await page.evaluate(() => Array.from(document.styleSheets).some(sheet =>
      sheet.href && new URL(sheet.href).origin === location.origin && sheet.cssRules.length > 0));
    requireCheck(styled, 'stylesheet', 'The entry page must load a nonempty local stylesheet.');
    requireCheck(!pageErrors.length, 'page-script', pageErrors.join('\n'));
  }

  async function verifyLocalImport() {
    let directory;
    try {
      try {
        directory = await mkdtemp(path.join(tmpdir(), 'playlist-import-'));
        await mkdir(path.join(directory, 'nested'));
        await writeFile(path.join(directory, fixtureNames[0]), quietTone());
        await writeFile(path.join(directory, 'nested', fixtureNames[1]), quietTone());
      } catch (error) {
        return `Could not prepare a synthetic audio file${error.code ? ` (${error.code})` : ''}.`;
      }
      const input = page.locator('input[type="file"][webkitdirectory], input[type="file"][directory]').first();
      requireCheck(await input.count(), 'folder-picker', 'The page has no folder selection input');
      await input.setInputFiles(directory);
      for (const name of ['alpha', 'beta']) {
        const title = page.getByText(new RegExp('demo[- _]+tone[- _]+' + name, 'i')).filter({ visible: true }).first();
        const filename = fixtureNames[name === 'alpha' ? 0 : 1];
        const imported = await title.waitFor({ state: 'visible' }).then(() => true, () => false);
        requireCheck(imported, 'folder-import', 'The page did not show ' + filename + ' after selecting its folder. ' +
          pageErrors.join(' '));
      }
      requireCheck(!pageErrors.length, 'page-script', pageErrors.join('\n'));
    } finally {
      if (directory) await rm(directory, { recursive: true, force: true });
    }
  }

  if (requestedCheck === 'local-import') {
    await check(requestedCheck, async () => {
      await openPage();
      return verifyLocalImport();
    });
  } else if (await check('startup', openPage)) {
    await check('local-import', verifyLocalImport);
  }
} finally {
  await browser.close();
}

const passed = result.every(check => check.ok);
console.log(JSON.stringify({ passed, result }));
if (!passed) process.exitCode = 1;
