const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    let moderation = 0, announcements = 0, available = true;
    let players = [{name: '<Alice & Bob>', address: '127.0.0.1:45123', identifier: '127.0.0.1', key: 'alice', can_moderate: true}, {name: 'Ambiguous', address: '[::1]:1234', key: 'ambiguous', can_moderate: false}];
    await page.route('http://players.test/**', async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith('/api/')) {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({body: fs.readFileSync(path.join(__dirname, '../web', name)), contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      }
      let data = {};
      if (url.pathname === '/api/settings') data = {mode: 'env', pending: false, staged: {TMOD_MODS: ''}, running: {}, compose_only: {}, fields: {}, groups: [], ranges: {}, choices: {}};
      if (url.pathname === '/api/status') data = {healthy: true, version: 'test', job: {state: 'idle'}, backups: {operation: {}, archives: [], count: 0, bytes: 0, free_bytes: 90000, warnings: []}};
      if (url.pathname === '/api/recovery') data = {operation: {}, interrupted: false, originals: [], guidance: ''};
      if (url.pathname === '/api/players') data = {available, players: available ? players : [], updated: new Date().toISOString(), detail: available ? 'Player query complete.' : 'Game is not ready.', activity: [], can_ban: true};
      if (url.pathname === '/api/players/moderate') {
        const body = route.request().postDataJSON(); assert.equal(body.confirm, true); assert.equal(body.key, 'alice');
        moderation++; players = []; data = {detail: 'Player is no longer connected.'};
      }
      if (url.pathname === '/api/players/announce') {
        const body = route.request().postDataJSON(); assert.equal(body.message, 'Hello server'); assert.equal(body.confirm, true);
        announcements++; data = {detail: 'Announcement command delivered.'};
      }
      await route.fulfill({json: data});
    });
    await page.goto('http://players.test/');
    await page.locator('#token').fill('test-token'); await page.getByRole('button', {name: 'Connect', exact: true}).click();
    await page.getByRole('button', {name: 'Players', exact: true}).click();
    await page.locator('#players-count').filter({hasText: '2'}).waitFor();
    assert.equal(await page.getByRole('button', {name: 'Kick Ambiguous', exact: true}).isDisabled(), true);
    await page.locator('#players-filter').fill('Alice');
    assert.equal(await page.locator('#players-list tr').count(), 1);
    await page.getByRole('button', {name: 'Ban <Alice & Bob>', exact: true}).click();
    await page.locator('#confirm-text').filter({hasText: 'sharing that address'}).waitFor();
    await page.locator('#confirm-cancel').click(); assert.equal(moderation, 0);
    await page.getByRole('button', {name: 'Kick <Alice & Bob>', exact: true}).click();
    await page.locator('#confirm-go').click();
    await page.locator('#players-list').getByText('No players connected.', {exact: true}).waitFor();
    assert.equal(moderation, 1);
    await page.locator('#players-announcement').fill('Hello server');
    await page.locator('#players-announce').click(); await page.locator('#confirm-cancel').click(); assert.equal(announcements, 0);
    await page.locator('#players-announce').click(); await page.locator('#confirm-go').click();
    await page.locator('#message').filter({hasText: 'Announcement command delivered.'}).waitFor(); assert.equal(announcements, 1);
    available = false; await page.locator('#players-refresh').click();
    await page.locator('#players-count').filter({hasText: 'Unknown'}).waitFor();
    assert.equal(await page.locator('#players-announce').isDisabled(), true);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    if (process.env.PLAYER_SCREENSHOT) await page.screenshot({path: process.env.PLAYER_SCREENSHOT, fullPage: true});
    assert.deepEqual(errors, []);
    console.log('Player page filtering, escaping, moderation confirmation, announcements, unavailable state and narrow layout passed.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
