const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    let configured = false, rejectKey = true, failDependencies = false, saves = 0;
    let staged = {TMOD_MODS: '3'}, running = {TMOD_MODS: '3'};
    const item = {id: '1', title: 'Main mod', description: '', url: 'https://steamcommunity.com/sharedfiles/filedetails/?id=1'};
    const dependency = {id: '2', title: 'Required library'};
    await page.route('http://workshop.test/**', async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith('/api/')) {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({body: fs.readFileSync(path.join(__dirname, '../web', name)), contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      }
      let data = {};
      if (url.pathname === '/api/settings') {
        if (route.request().method() === 'POST') { staged = {...staged, ...route.request().postDataJSON().settings}; saves++; }
        data = {mode: 'web', pending: saves > 0, running, staged, revision: 'revision', workshop_search: configured, compose_only: {}, fields: {}, groups: [], choices: {}, ranges: {}};
      }
      if (url.pathname === '/api/status') data = {healthy: true, version: 'test', job: {state: 'idle'}, backups: {operation: {}, archives: [], count: 0, bytes: 0, free_bytes: 0, warnings: []}};
      if (url.pathname === '/api/recovery') data = {operation: {}, interrupted: false, originals: [], guidance: ''};
      if (url.pathname === '/api/workshop/key') {
        assert.equal(route.request().postDataJSON().key, 'a'.repeat(32));
        if (rejectKey) return route.fulfill({status: 400, json: {error: 'Steam rejected key'}});
        configured = true; data = {saved: true};
      }
      if (url.pathname === '/api/workshop') data = {items: [item], total: 1};
      if (url.pathname === '/api/workshop/lookup') data = item;
      if (url.pathname === '/api/workshop/dependencies') {
        if (failDependencies) return route.fulfill({status: 400, json: {error: 'Dependency unavailable'}});
        data = {checked: configured, items: configured ? [dependency, {id: '3', title: 'Already selected'}] : [], excluded: configured ? [{id: '4', title: 'Client helper'}] : []};
      }
      await route.fulfill({json: data});
    });
    await page.goto('http://workshop.test/');
    await page.locator('#token').fill('test-token'); await page.getByRole('button', {name: 'Connect', exact: true}).click();
    await page.getByRole('button', {name: 'Workshop', exact: true}).click();
    assert.equal(await page.locator('#workshop-key-form').isVisible(), true);
    assert.equal(await page.locator('#search-form').isVisible(), false);
    await page.locator('#lookup').fill('1'); await page.locator('#lookup-form button').click();
    await page.getByRole('button', {name: 'Add to selection', exact: true}).click();
    await page.locator('#confirmation').waitFor();
    assert.match(await page.locator('#confirm-title').textContent(), /unavailable/);
    await page.locator('#confirm-cancel').click(); assert.equal(saves, 0);
    await page.locator('#workshop-key').fill('a'.repeat(32)); await page.locator('#workshop-key-save').click();
    await page.locator('#message').filter({hasText: 'Steam rejected key'}).waitFor();
    assert.equal(await page.locator('#search-form').isVisible(), false);
    rejectKey = false; await page.locator('#workshop-key-save').click();
    await page.locator('#search-form').waitFor();
    assert.equal(await page.locator('#workshop-key-form').isVisible(), false);
    assert.equal(await page.locator('#workshop-key').inputValue(), '');
    await page.locator('#search-button').click();
    await page.getByRole('button', {name: 'Add to selection', exact: true}).click();
    await page.locator('#confirmation').waitFor();
    const listing = await page.locator('#confirm-diff').textContent();
    assert.match(listing, /Required library/); assert.match(listing, /Client helper/); assert.doesNotMatch(listing, /Already selected/);
    assert.equal(await page.locator('#confirm-go').textContent(), 'Add');
    await page.locator('#confirm-cancel').click(); assert.equal(saves, 0);
    await page.getByRole('button', {name: 'Add to selection', exact: true}).click();
    await page.locator('#confirm-go').click();
    await page.getByRole('button', {name: 'Remove from selection', exact: true}).waitFor();
    assert.equal(staged.TMOD_MODS, '3,1,2'); assert.equal(saves, 1);
    await page.getByRole('button', {name: 'Remove from selection', exact: true}).click();
    await page.getByRole('button', {name: 'Add to selection', exact: true}).waitFor();
    failDependencies = true;
    await page.getByRole('button', {name: 'Add to selection', exact: true}).click();
    await page.locator('#message').filter({hasText: 'Dependency unavailable'}).waitFor();
    assert.equal(saves, 2); assert.equal(staged.TMOD_MODS, '3,2');
    await page.locator('#workshop-key-change').click();
    assert.equal(await page.locator('#workshop-key-form').isVisible(), true);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    console.log('Workshop key, dependency review, cancellation, failure, and mobile tests passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
