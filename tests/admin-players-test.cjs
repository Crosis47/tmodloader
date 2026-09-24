const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    let moderation = 0, announcements = 0, historicalBans = 0, available = true, world = 'First world';
    const record = name => ({name, first_joined: '2026-09-01T12:00:00Z', last_joined: '2026-09-23T12:00:00Z', visits: 3});
    const allHistory = [record('<Alice & Bob>'), record('Offline Veteran'), ...Array.from({length: 49}, (_, i) => record('Visitor ' + i))];
    allHistory[1].identities = [{identifier: '203.0.113.4', kind: 'ip', key: 'a'.repeat(64), last_seen: '2026-09-23T12:00:00Z', banned: false}];
    const appearance = {skin: '#ffd0aa', eyes: '#123456', hair_color: '#543210', hair: 4, skin_variant: 0};
    allHistory[2] = {...record('Alex'), character_id: '@character:' + 'b'.repeat(64), appearance};
    allHistory[3] = {...record('Alex'), character_id: '@character:' + 'c'.repeat(64), appearance: {...appearance, skin: '#553322'}};
    allHistory[2].identities = ['192.0.2.10', '198.51.100.20', '203.0.113.30'].map((identifier, i) => ({identifier, kind: 'ip', key: String(i + 1).repeat(64), last_seen: '2026-09-23T12:00:00Z', banned: false}));
    function historyPage(rows, offset, search) {
      rows = rows.filter(p => p.name.toLowerCase().includes(search.toLowerCase()));
      return {players: rows.slice(offset, offset + 50), total: rows.length, offset, page_size: 50};
    }
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
      if (url.pathname === '/api/players') {
        const search = url.searchParams.get('history_search') || '';
        data = {available, players: available ? players : [], updated: new Date().toISOString(), detail: available ? 'Player query complete.' : 'Game is not ready.', activity: [], can_ban: true,
          history: {can_ban: true, current_world: {id: world, name: world, detail: ''}, error: '',
            server: historyPage(allHistory, Number(url.searchParams.get('server_offset') || 0), search),
            world: historyPage(world === 'First world' ? [allHistory[0]] : [allHistory[1]], Number(url.searchParams.get('world_offset') || 0), search)}};
      }
      if (url.pathname === '/api/players/moderate') {
        const body = route.request().postDataJSON(); assert.equal(body.confirm, true); assert.equal(body.key, 'alice');
        moderation++; players = []; data = {detail: 'Player is no longer connected.'};
      }
      if (url.pathname === '/api/players/announce') {
        const body = route.request().postDataJSON(); assert.equal(body.message, 'Hello server'); assert.equal(body.confirm, true);
        announcements++; data = {detail: 'Announcement command delivered.'};
      }
      if (url.pathname === '/api/players/history/ban') {
        assert.deepEqual(route.request().postDataJSON(), {key: 'a'.repeat(64), confirm: true});
        historicalBans++; allHistory[1].identities[0].banned = true;
        data = {detail: 'Ban saved for 203.0.113.4.'};
      }
      if (url.pathname === '/api/players/history/unban') {
        assert.deepEqual(route.request().postDataJSON(), {key: 'a'.repeat(64), confirm: true});
        allHistory[1].identities[0].banned = false;
        data = {detail: 'Ban removed for 203.0.113.4.'};
      }
      await route.fulfill({json: data});
    });
    await page.goto('http://players.test/');
    await page.locator('#token').fill('test-token'); await page.getByRole('button', {name: 'Connect', exact: true}).click();
    await page.getByRole('button', {name: 'Players', exact: true}).click();
    await page.locator('#players-count').filter({hasText: '2'}).waitFor();
    await page.locator('#player-history-server-list').getByText('Offline Veteran', {exact: true}).waitFor();
    assert.equal(await page.locator('#player-history-server-list tr').filter({hasText: '<Alice & Bob>'}).getByRole('button').isDisabled(), true);
    assert.equal(await page.locator('#player-history-server-list script').count(), 0);
    const alex = page.locator('#player-history-server-list tr').filter({hasText: 'Alex'});
    assert.equal(await alex.count(), 2);
    assert.equal(await page.locator('.character-face, canvas').count(), 0);
    const addresses = alex.first().locator('details');
    assert.equal(await addresses.getAttribute('open'), null);
    await addresses.locator('summary').click();
    await addresses.getByText('Observed IP address: 198.51.100.20', {exact: true}).waitFor();
    await page.locator('#players-refresh').click();
    await addresses.getByText('Observed IP address: 198.51.100.20', {exact: true}).waitFor();
    assert.equal(await addresses.locator('button').count(), 3);
    await addresses.locator('summary').click();
    assert.equal(await addresses.getAttribute('open'), null);

    assert.equal(await page.locator('#player-history-server-previous').isVisible(), false);
    assert.equal(await page.locator('#player-history-world-next').isVisible(), false);
    await page.locator('#player-history-server-next').click();
    await page.locator('#player-history-server-count').filter({hasText: '51–51 of 51'}).waitFor();
    assert.equal(await page.locator('#player-history-server-next').isVisible(), false);
    await page.locator('#player-history-server-previous').click();
    await page.locator('#player-history-server-count').filter({hasText: '1–50 of 51'}).waitFor();
    await page.locator('#player-history-search').fill('Veteran');
    await page.locator('#player-history-server-count').filter({hasText: '1–1 of 1'}).waitFor();
    await page.locator('#player-history-world-list').getByText('No recorded players match your search.').waitFor();
    assert.equal(await page.locator('#player-history-search').inputValue(), 'Veteran');
    await page.locator('#player-history-search').fill('');
    await page.locator('#player-history-server-count').filter({hasText: '1–50 of 51'}).waitFor();
    world = 'Second world'; await page.locator('#players-refresh').click();
    await page.locator('#player-history-world-list').getByText('Offline Veteran', {exact: true}).waitFor();
    world = 'First world'; await page.locator('#players-refresh').click();
    await page.locator('#player-history-world-list').getByText('<Alice & Bob>', {exact: true}).waitFor();
    assert.equal(await page.getByRole('button', {name: 'Kick Ambiguous', exact: true}).isDisabled(), true);
    await page.locator('#players-filter').fill('Alice');
    assert.equal(await page.locator('#players-list tr').count(), 1);
    await page.getByRole('button', {name: 'Ban IP for <Alice & Bob>', exact: true}).click();
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
    await page.locator('#player-history-server-list').getByText('Offline Veteran', {exact: true}).waitFor();
    const offlineBan = page.locator('#player-history-server-list').getByRole('button', {name: 'Ban IP for Offline Veteran at 203.0.113.4', exact: true});
    await offlineBan.click();
    await page.locator('#confirm-text').filter({hasText: 'sharing this address'}).waitFor();
    await page.locator('#confirm-cancel').click(); assert.equal(historicalBans, 0);
    await offlineBan.click(); await page.locator('#confirm-go').click();
    const unban = page.locator('#player-history-server-list').getByRole('button', {name: 'Unban IP for Offline Veteran at 203.0.113.4', exact: true});
    await unban.waitFor(); assert.equal(historicalBans, 1);
    await unban.click(); await page.locator('#confirm-cancel').click();
    assert.equal(allHistory[1].identities[0].banned, true);
    await unban.click(); await page.locator('#confirm-go').click();
    await offlineBan.waitFor(); assert.equal(await offlineBan.isEnabled(), true);
    assert.equal(allHistory[1].identities[0].banned, false);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    if (process.env.PLAYER_SCREENSHOT) {
      await page.locator('#player-history-search').fill('Alex');
      await page.locator('#player-history-server-count').filter({hasText: '1–2 of 2'}).waitFor();
      await page.screenshot({path: process.env.PLAYER_SCREENSHOT, fullPage: true});
      await page.locator('.player-history-card').first().screenshot({path: process.env.PLAYER_SCREENSHOT.replace(/\.png$/, '-card.png')});
    }
    assert.deepEqual(errors, []);
    console.log('Player page filtering, escaping, moderation confirmation, announcements, unavailable state and narrow layout passed.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
