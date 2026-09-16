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
      if (url.pathname === '/api/worlds') data = {worlds: ['Original', 'Other'].map(name => ({name, bytes: 123456, mod_bytes: 1234, has_mod_data: true, modified: new Date().toISOString(), metadata: {available: true, title: name, size: 'Small', width: 4200, height: 1200, difficulty: 'Master', evil: 'Crimson', seed: '<seed & safe>', hardmode: true, special_seeds: ['For the worthy'], created: '2026-01-02T00:00:00', spawn: {x: 2100, y: 300}, dungeon: {x: 400, y: 350}, world_id: 42}, total_uptime_seconds: 180122, uptime_tracked_since: '2026-09-01T00:00:00Z', session_uptime_seconds: name === running.TMOD_WORLDNAME ? 90061 : null, can_select: true, selected: name === running.TMOD_WORLDNAME})), configured: running.TMOD_WORLDNAME, healthy: true, editable, busy: false, warnings: [], detail: 'Saved worlds.', free_bytes: 1234567890, revision: 'revision', pending, staged_name: staged.TMOD_WORLDNAME};
      if (url.pathname === '/api/worlds/stage') { lastStage = route.request().postDataJSON(); pending = true; staged = {...staged, TMOD_WORLDNAME: lastStage.name, ...lastStage.creation}; data = config(); }
      if (url.pathname === '/api/apply') { assert.equal(route.request().postDataJSON().confirm, true); applies++; running = {...staged}; pending = false; job = {kind: 'apply', state: 'success', stage: 'health', started: new Date().toISOString(), detail: 'Healthy'}; data = job; }
      await route.fulfill({json: data});
    });
    await page.goto('http://worlds.test/');
    await page.locator('#token').fill('test-token'); await page.getByRole('button', {name: 'Connect', exact: true}).click();
    await page.getByRole('button', {name: 'Worlds', exact: true}).click();
    await page.getByRole('button', {name: 'Details for Original', exact: true}).waitFor();
    assert.equal(await page.getByRole('button', {name: 'Switch to Original', exact: true}).count(), 0);
    const expand = page.getByRole('button', {name: 'Details for Original', exact: true});
    assert.equal(await expand.getAttribute('aria-expanded'), 'false');
    await expand.click();
    const details = page.locator('#world-details-0');
    assert.equal(await details.isVisible(), true);
    for (const value of ['Master', 'Crimson', '<seed & safe>', 'Hardmode', 'For the worthy']) {
      assert.equal(await details.getByText(value, {exact: true}).count(), 1);
    }
    assert.match(await details.innerText(), /Current session uptime/);
    assert.match(await details.innerText(), /1d 1h 1m 1s/);
    assert.match(await details.innerText(), /Total uptime/);
    assert.match(await details.innerText(), /2d 2h 2m 2s/);
    assert.doesNotMatch(await details.innerText(), /Explored|Playtime/);
    await page.evaluate(() => refreshWorlds(true));
    assert.equal(await expand.evaluate(element => element === document.activeElement), true);
    await expand.evaluate(button => button.blur());
    await page.evaluate(() => refreshWorlds(true));
    assert.equal(await expand.getAttribute('aria-expanded'), 'true');
    await page.locator('#worlds-filter').fill('Other');
    await page.locator('#worlds-filter').fill('');
    assert.equal(await expand.getAttribute('aria-expanded'), 'true');
    await expand.focus(); await page.keyboard.press('Enter');
    assert.equal(await expand.getAttribute('aria-expanded'), 'false');
    await page.locator('#world-new').click();
    await page.locator('#world-create-name').fill('Draft world');
    await page.locator('#world-create-name').evaluate(input => input.setSelectionRange(2, 5));
    await page.evaluate(() => refreshWorlds(true));
    assert.deepEqual(await page.locator('#world-create-name').evaluate(input => [input === document.activeElement, input.value, input.selectionStart, input.selectionEnd]), [true, 'Draft world', 2, 5]);
    // Start typing after the request starts but before its response arrives.
    await page.locator('#world-create-name').evaluate(input => input.blur());
    let releaseRefresh;
    const responseGate = new Promise(resolve => { releaseRefresh = resolve; });
    let requestStarted;
    const requestGate = new Promise(resolve => { requestStarted = resolve; });
    await page.route('**/api/worlds', async route => { requestStarted(); await responseGate; await route.fallback(); }, {times: 1});
    const refreshing = page.evaluate(() => refreshWorlds(true));
    await requestGate;
    await page.locator('#world-create-name').focus();
    await page.locator('#world-create-name').evaluate(input => input.setSelectionRange(2, 5));
    releaseRefresh(); await refreshing;
    assert.deepEqual(await page.locator('#world-create-name').evaluate(input => [input === document.activeElement, input.disabled, input.selectionStart, input.selectionEnd]), [true, false, 2, 5]);
    await page.keyboard.type('NEW');
    assert.equal(await page.locator('#world-create-name').inputValue(), 'DrNEW world');
    await page.locator('#world-create-cancel').click();
    await page.getByRole('button', {name: 'Switch to Other', exact: true}).click();
    await page.locator('#confirmation').waitFor(); assert.equal(lastStage.action, 'switch');
    await page.locator('#confirm-cancel').click(); assert.equal(applies, 0);
    await page.locator('#world-draft').filter({hasText: 'Other'}).waitFor();
    await page.locator('#world-apply').click(); await page.locator('#confirm-go').click();
    await page.getByRole('button', {name: 'Return to dashboard', exact: true}).click();
    await page.locator('#worlds-refresh').click();
    await page.locator('#world-current').filter({hasText: 'Other'}).waitFor(); assert.equal(applies, 1);
    await page.locator('#world-new').click();
    await page.locator('#world-create-name').fill('NewWorld');
    await page.locator('#world-create-evil').selectOption('crimson');
    await page.locator('#world-create').click(); await page.locator('#confirmation').waitFor();
    assert.equal(lastStage.action, 'create'); assert.equal(lastStage.creation.TMOD_WORLDEVIL, 'crimson');
    await page.locator('#confirm-cancel').click(); assert.equal(applies, 1);
    editable = false; await page.locator('#worlds-refresh').click();
    await page.locator('#worlds-status').filter({hasText: 'Enable web-managed'}).waitFor();
    assert.equal(await page.locator('#world-create').isDisabled(), true);
    await page.setViewportSize({width: 390, height: 844});
    await page.getByRole('button', {name: 'Details for Other', exact: true}).click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    if (process.env.WORLD_SCREENSHOT) await page.screenshot({path: process.env.WORLD_SCREENSHOT, fullPage: true});
    assert.deepEqual(errors, []);
    console.log('World page staged switch, cancellation, confirmed apply, creation options and read-only mode passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
