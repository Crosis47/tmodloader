const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    let defaults = {TMOD_JOURNEY_GODMODE: '0', TMOD_JOURNEY_TIME_SPEED: '1'}, overrides = {};
    let staged = {TMOD_WORLDNAME: 'Journey', TMOD_WORLDSIZE: '2', TMOD_DIFFICULTY: '3', TMOD_WORLDEVIL: 'crimson', ...defaults};
    const running = {...staged};
    let pending = false, applies = 0, saves = 0, failSave = false;
    const config = () => ({mode: 'web', pending, staged, running, revision: 'r', compose_only: {},
      fields: {TMOD_WORLDNAME: {group: 'world', label: 'World name'}, TMOD_JOURNEY_GODMODE: {group: 'journey', label: 'God mode'}, TMOD_JOURNEY_TIME_SPEED: {group: 'journey', label: 'Time speed'}},
      groups: [{id: 'world', title: 'World configuration'}, {id: 'journey', title: 'Journey permissions'}], choices: {}, ranges: {}});
    const worlds = ['Journey', 'Classic', 'Unknown'].map(name => ({name, bytes: 100, mod_bytes: 0, modified: '2026-09-16T00:00:00Z', selected: name === 'Journey', can_select: true,
      metadata: name === 'Unknown' ? {available: false} : {available: true, title: name, difficulty: name, size: 'Small', width: 4200, height: 1200, evil: 'Crimson', seed: '123', spawn: {x: 1, y: 2}, dungeon: {x: 3, y: 4}, world_id: 1}}));
    await page.route('http://journey.test/**', async route => {
      const url = new URL(route.request().url()), post = route.request().method() === 'POST';
      if (!url.pathname.startsWith('/api/')) {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({body: fs.readFileSync(path.join(__dirname, '../web', name)), contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      }
      let data = {};
      if (url.pathname === '/api/settings') data = config();
      if (url.pathname === '/api/status') data = {healthy: true, version: 'test', job: {state: 'idle'}, backups: {operation: {}, archives: [], count: 0, bytes: 0, free_bytes: 1000, warnings: []}};
      if (url.pathname === '/api/recovery') data = {operation: {}, originals: []};
      if (url.pathname === '/api/worlds') data = {worlds, configured: 'Journey', editable: true, healthy: true, pending, staged_name: staged.TMOD_WORLDNAME, warnings: [], free_bytes: 1000, revision: 'r', detail: 'Saved worlds.'};
      if (url.pathname === '/api/worlds/journey') {
        const body = post ? route.request().postDataJSON() : null;
        const name = post ? body.name : url.searchParams.get('name');
        if (post) {
          if (failSave) return route.fulfill({status: 400, json: {error: 'Settings changed. Reopen this dialog.'}});
          saves++;
          if (name === null) defaults = body.permissions;
          else if (body.override) overrides[name] = body.permissions;
          else delete overrides[name];
          staged = {...staged, ...(overrides.Journey || defaults)}; pending = true;
        }
        data = {name, defaults, override: !!overrides[name], permissions: overrides[name] || defaults, revision: 'j', settings_revision: 'r', running, running_world: 'Journey', editable: true};
      }
      if (url.pathname === '/api/worlds/stage') { const body = route.request().postDataJSON(); assert.equal(body.name, 'Journey'); staged.TMOD_WORLDNAME = body.name; pending = true; data = config(); }
      if (url.pathname === '/api/apply') { applies++; data = {state: 'running'}; }
      await route.fulfill({json: data});
    });
    await page.goto('http://journey.test/');
    await page.locator('#token').fill('test-token'); await page.getByRole('button', {name: 'Connect', exact: true}).click();
    assert.equal(await page.locator('#config-world, #config-journey').count(), 0);
    await page.getByRole('button', {name: 'Worlds', exact: true}).click();
    const button = page.getByRole('button', {name: 'Set Journey permissions for Journey', exact: true});
    await button.waitFor();
    assert.equal(await page.getByRole('button', {name: 'Set Journey permissions for Classic', exact: true}).count(), 0);
    assert.equal(await page.getByRole('button', {name: 'Set Journey permissions for Unknown', exact: true}).count(), 0);
    await page.locator('#world-new').click();
    assert.equal(await page.locator('#world-create-dialog').isVisible(), true);
    assert.equal(await page.locator('#world-create-size').inputValue(), '2');
    await page.keyboard.press('Escape'); assert.equal(await page.locator('#world-create-dialog').isVisible(), false);
    await page.locator('#journey-defaults').click();
    const godmode = page.locator('#journey-fields [name="TMOD_JOURNEY_GODMODE"]');
    await godmode.selectOption('2'); await page.locator('#journey-save').click();
    await page.locator('#journey-status').filter({hasText: 'Saved.'}).waitFor();
    assert.equal(defaults.TMOD_JOURNEY_GODMODE, '2'); assert.equal(applies, 0);
    await page.locator('#journey-close').click(); await button.click();
    assert.equal(await godmode.inputValue(), '2'); assert.equal(await godmode.isDisabled(), true);
    await page.locator('#journey-override').check(); await godmode.selectOption('1');
    await page.evaluate(() => refreshWorlds(true));
    assert.equal(await godmode.inputValue(), '1');
    failSave = true; await page.locator('#journey-save').click();
    await page.locator('#journey-status').filter({hasText: 'Settings changed'}).waitFor();
    assert.equal(await page.locator('#journey-dialog').isVisible(), true);
    assert.equal(await godmode.inputValue(), '1'); failSave = false;
    await page.locator('#journey-save').click();
    await page.locator('#journey-status').filter({hasText: 'Saved.'}).waitFor();
    assert.equal(overrides.Journey.TMOD_JOURNEY_GODMODE, '1');
    await page.locator('#journey-close').click(); await button.click();
    assert.equal(await page.locator('#journey-override').isChecked(), true);
    await page.locator('#journey-override').uncheck();
    assert.equal(await godmode.inputValue(), '2');
    await page.locator('#journey-apply').click();
    await page.locator('#confirmation').waitFor();
    assert.equal(await page.locator('#journey-dialog').isVisible(), false);
    assert.equal(applies, 0); assert.equal(overrides.Journey, undefined);
    await page.locator('#confirm-cancel').click();
    await button.click(); await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    if (process.env.JOURNEY_SCREENSHOT) await page.screenshot({path: process.env.JOURNEY_SCREENSHOT});
    assert.equal(saves, 3); assert.deepEqual(errors, []);
    console.log('World dialogs, Journey-only controls, defaults, overrides, reset, failed saves and restart cancellation passed.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
