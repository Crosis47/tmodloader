// Browser-level recovery flow against deterministic API responses.
// Run with Playwright installed and a Chromium browser available.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    const archive = 'tmod-backup-20260912T100000Z-test';
    const preview = {archive, sha256: 'a'.repeat(64), created: '20260912T100000Z', worlds: ['Recovery.wld'], required_bytes: 1000, free_bytes: 90000, replaces: 'Worlds, mods, logs and settings. Current credentials are preserved.'};
    let posts = 0, pending = true;
    let job = {state: 'idle'}, healthy = true, interrupted = false, restores = 0;
    await page.route('http://recovery.test/**', async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith('/api/')) {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({body: fs.readFileSync(path.join(__dirname, '../web', name)), contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      }
      if (route.request().method() === 'POST') posts++;
      let data = {};
      if (url.pathname === '/api/worlds') data = {configured:'Adventure',healthy:true,worlds:[{}],free_bytes:1000,warnings:[]};
      if (url.pathname === '/api/players') data = {available:true,players:[{name:'Test Player'}],updated:new Date().toISOString(),activity:[]};
      if (url.pathname === '/api/profiles') data = {profiles:[],running:''};
      if (url.pathname === '/api/playthroughs') data = {playthroughs:[],running:{}};
      if (url.pathname === '/api/settings') data = {mode: 'env', pending, staged: {TMOD_MODS: ''}, running: {}, compose_only: {}, fields: {}, groups: [], ranges: {}, choices: {}};
      if (url.pathname === '/api/status') data = {healthy, version: 'test', job, backups: {operation: {}, archives: [{name: archive, bytes: 100}], count: 1, bytes: 100, free_bytes: 90000, warnings: []}};
      if (url.pathname === '/api/recovery') data = {operation: {}, interrupted, originals: ['before-restore-1234567890abcdef1234567890abcdef'], guidance: 'Original data is retained for manual rollback.'};
      if (url.pathname === '/api/recovery/preview') job = {kind: 'preview', state: 'success', preview, started: new Date().toISOString()};
      if (url.pathname === '/api/recovery/restore') {
        assert.equal(route.request().postDataJSON().sha256, preview.sha256);
        restores++; job = {kind: 'restore', state: 'running', stage: 'restoring', detail: 'Staging verified files.'}; healthy = false;
      }
      if (url.pathname === '/api/recovery/retry') { job = {kind: 'retry', state: 'success', stage: 'health', detail: 'Game server is healthy.'}; healthy = true; }
      await route.fulfill({json: data});
    });
    await page.goto('http://recovery.test/');
    await page.locator('#token').fill('test-token'); await page.getByRole('button', {name: 'Connect', exact: true}).click();
    await page.locator('#overview-world').filter({hasText:'Adventure'}).waitFor();
    await page.locator('#overview-players').filter({hasText:'Test Player'}).waitFor();
    assert.equal(await page.locator('#overview #backup, #overview #archives, #overview #recovery-restore, #overview input, #overview select').count(), 0);
    await page.locator('#attention-banner').waitFor();
    assert.equal(await page.locator('#overview-settings').evaluate(el => el.classList.contains('pending-highlight')), true);
    await page.getByRole('button', {name:'Review saved changes',exact:true}).click();
    assert.equal(await page.locator('#settings').isVisible(), true);
    assert.equal(posts, 0);
    await page.getByRole('button', {name:'Overview',exact:true}).click();
    pending = false;
    await page.locator('#refresh').click();
    await page.locator('#attention-banner').waitFor({state:'hidden'});
    assert.equal(posts, 0);
    await page.getByRole('button', {name: 'Backups & recovery', exact: true}).click();
    assert.equal(await page.locator('#backup').isVisible(), true);
    assert.equal(await page.locator('#archives').isVisible(), true);
    assert.equal(await page.locator('#recovery-preview').isVisible(), true);
    await page.locator('#backup').click(); await page.locator('#confirm-cancel').click(); assert.equal(posts, 0);
    await page.getByRole('button', {name:'Overview',exact:true}).click();
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    console.log('Overview read-only summaries, refresh, combined backup controls, cancellation and mobile layout passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
