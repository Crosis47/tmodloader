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
    let profiles = [], sequence = 0;
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
      if (url.pathname === '/api/profiles') {
        if (route.request().method() === 'POST') {
          const body = route.request().postDataJSON();
          if (body.action === 'save') profiles.push({id: String(++sequence), name: body.name, mods: body.source === 'running' ? running.TMOD_MODS : staged.TMOD_MODS});
          if (body.action === 'rename') profiles.find(p => p.id === body.id).name = body.name;
          if (body.action === 'delete') { assert.equal(body.confirm, true); profiles = profiles.filter(p => p.id !== body.id); }
          if (body.action === 'stage') { staged.TMOD_MODS = profiles.find(p => p.id === body.id).mods; pending = true; }
        }
        data = {profiles, revision: 'revision', catalog_revision: 'catalog', running: running.TMOD_MODS, staged: staged.TMOD_MODS, editable, pending, busy: false};
      }
      if (url.pathname === '/api/apply') { assert.equal(route.request().postDataJSON().confirm, true); applies++; running = {...staged}; pending = false; job = {kind: 'apply', state: 'success', stage: 'health', started: new Date().toISOString(), detail: 'Healthy'}; data = job; }
      await route.fulfill({json: data});
    });
    await page.goto('http://worlds.test/');
    await page.locator('#token').fill('test-token'); await page.getByRole('button', {name: 'Connect', exact: true}).click();
    await page.getByRole('button', {name: 'Mod profiles', exact: true}).click();
    await page.locator('#profile-name').fill('Vanilla'); await page.locator('#profile-save').click();
    await page.getByRole('heading', {name: 'Vanilla', exact: true}).waitFor();
    await page.getByRole('button', {name: 'Load profile', exact: true}).click();
    await page.locator('#confirmation').waitFor(); await page.locator('#confirm-cancel').click();
    assert.equal(applies, 0); assert.equal(pending, true);
    await page.locator('#profiles-apply').click(); await page.locator('#confirm-go').click();
    await page.getByRole('button', {name: 'Return to dashboard', exact: true}).click();
    assert.equal(applies, 1);
    await page.getByRole('textbox', {name: 'Name for Vanilla'}).fill('Renamed');
    await page.getByRole('textbox', {name: 'Name for Vanilla'}).evaluate(input => input.setSelectionRange(1, 4));
    await page.evaluate(() => refreshProfiles(true));
    assert.deepEqual(await page.getByRole('textbox', {name: 'Name for Vanilla'}).evaluate(input => [input === document.activeElement, input.value, input.selectionStart, input.selectionEnd]), [true, 'Renamed', 1, 4]);
    await page.getByRole('textbox', {name: 'Name for Vanilla'}).evaluate(input => input.blur());
    await page.evaluate(() => refreshProfiles(true));
    assert.equal(await page.getByRole('textbox', {name: 'Name for Vanilla'}).inputValue(), 'Renamed');

    await page.getByRole('button', {name: 'Rename', exact: true}).click();
    await page.getByRole('heading', {name: 'Renamed', exact: true}).waitFor();
    await page.getByRole('button', {name: 'Delete', exact: true}).click(); await page.locator('#confirm-cancel').click();
    assert.equal(profiles.length, 1);
    editable = false; await page.locator('#profiles-refresh').click();
    await page.locator('#profiles-status').filter({hasText: 'Enable web-managed'}).waitFor();
    assert.equal(await page.getByRole('button', {name: 'Load profile', exact: true}).isDisabled(), true);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    console.log('Profiles save, load, cancel, apply, rename, delete cancellation and read-only/mobile checks passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
