const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    let running = {TMOD_WORLDNAME: 'Original', TMOD_MODS: ''}, staged = {...running};
    let pending = false, editable = true, applies = 0, job = {state: 'idle'}, lastStage;
    await page.route('http://worlds.test/**', async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith('/api/')) {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({body: fs.readFileSync(path.join(__dirname, '../web', name)), contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      }
      let data = {};
      const config = () => ({mode: editable ? 'web' : 'env', pending, running, staged, revision: 'revision', compose_only: {}, fields: {}, groups: [], choices: {}, ranges: {}});
      if (url.pathname === '/api/settings') data = config();
      if (url.pathname === '/api/status') data = {healthy: true, version: 'test', job, backups: {operation: {}, archives: [], count: 0, bytes: 0, free_bytes: 0, warnings: []}};
      if (url.pathname === '/api/recovery') data = {operation: {}, interrupted: false, originals: [], guidance: ''};
      if (url.pathname === '/api/worlds') data = {worlds: ['Original', 'Other'].map(name => ({name, bytes: 123456, mod_bytes: 1234, has_mod_data: true, modified: new Date().toISOString(), can_select: true, selected: name === running.TMOD_WORLDNAME})), configured: running.TMOD_WORLDNAME, healthy: true, editable, busy: false, warnings: [], detail: 'Saved worlds.', free_bytes: 1234567890, revision: 'revision', pending, staged_name: staged.TMOD_WORLDNAME};
      if (url.pathname === '/api/worlds/stage') { lastStage = route.request().postDataJSON(); pending = true; staged = {...staged, TMOD_WORLDNAME: lastStage.name, ...lastStage.creation}; data = config(); }
      if (url.pathname === '/api/apply') { assert.equal(route.request().postDataJSON().confirm, true); applies++; running = {...staged}; pending = false; job = {kind: 'apply', state: 'success', stage: 'health', started: new Date().toISOString(), detail: 'Healthy'}; data = job; }
      await route.fulfill({json: data});
    });
    await page.goto('http://worlds.test/');
    await page.locator('#token').fill('test-token'); await page.getByRole('button', {name: 'Connect', exact: true}).click();
    await page.getByRole('button', {name: 'Worlds', exact: true}).click();
    await page.getByRole('button', {name: 'Switch to Other', exact: true}).click();
    await page.locator('#confirmation').waitFor(); assert.equal(lastStage.action, 'switch');
    await page.locator('#confirm-cancel').click(); assert.equal(applies, 0);
    await page.locator('#world-draft').filter({hasText: 'Other'}).waitFor();
    await page.locator('#world-apply').click(); await page.locator('#confirm-go').click();
    await page.getByRole('button', {name: 'Return to dashboard', exact: true}).click();
    await page.locator('#worlds-refresh').click();
    await page.locator('#world-current').filter({hasText: 'Other'}).waitFor(); assert.equal(applies, 1);
    await page.locator('#world-create-name').fill('NewWorld');
    await page.locator('#world-create-evil').selectOption('crimson');
    await page.locator('#world-create').click(); await page.locator('#confirmation').waitFor();
    assert.equal(lastStage.action, 'create'); assert.equal(lastStage.creation.TMOD_WORLDEVIL, 'crimson');
    await page.locator('#confirm-cancel').click(); assert.equal(applies, 1);
    editable = false; await page.locator('#worlds-refresh').click();
    await page.locator('#worlds-status').filter({hasText: 'Enable web-managed'}).waitFor();
    assert.equal(await page.locator('#world-create').isDisabled(), true);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    console.log('World page staged switch, cancellation, confirmed apply, creation options and read-only mode passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
