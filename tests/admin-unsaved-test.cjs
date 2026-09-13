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
    let posts = 0, saved = '8';
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
      if (url.pathname === '/api/settings') {
        if (route.request().method() === 'POST') saved = route.request().postDataJSON().settings.TMOD_MAXPLAYERS;
        data = {mode:'web',pending:false,revision:'r',staged:{TMOD_MAXPLAYERS:saved},running:{TMOD_MAXPLAYERS:'8'},compose_only:{},fields:{TMOD_MAXPLAYERS:{group:'server',label:'Maximum players',help:'Player limit'}},groups:[{id:'server',title:'Server',description:''}],ranges:{TMOD_MAXPLAYERS:[1,255]},choices:{}};
      }
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
    await page.getByRole('button',{name:'Configuration',exact:true}).click();
    const input = page.locator('[name="TMOD_MAXPLAYERS"]');
    await input.fill('10');
    assert.equal(await page.locator('.setting-unsaved').count(),1);
    await page.getByRole('button',{name:'Review unsaved settings',exact:true}).waitFor();
    await input.fill('8');
    assert.equal(await page.locator('.setting-unsaved').count(),0);
    await input.fill('12');
    await page.locator('#save-settings').click();
    await page.locator('.setting-unsaved').waitFor({state:'detached'});
    assert.equal(saved,'12');
    assert.equal(await page.locator('.setting-staged').count(),1);
    await page.getByText('Saved · waiting to apply',{exact:true}).waitFor();
    await input.fill('15');
    assert.equal(await page.locator('.setting-staged.setting-unsaved').count(),1);
    await input.fill('12');
    assert.equal(await page.locator('.setting-unsaved').count(),0);
    await input.fill('8'); await page.locator('#save-settings').click();
    await page.locator('.setting-staged').waitFor({state:'detached'});
    assert.deepEqual(errors,[]);
    console.log('Settings card highlight, unsaved banner, revert and save clearing passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
