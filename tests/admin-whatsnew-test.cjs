const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    let pending = true, fail = false, dismissed = 0;
    await page.route('http://news.test/**', async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith('/api/')) {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({body: fs.readFileSync(path.join(__dirname, '../web', name)), contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      }
      let data = {};
      if (url.pathname === '/api/settings') data = {mode: 'web', pending: false, running: {}, staged: {}, revision: 'r', compose_only: {}, fields: {}, groups: [], choices: {}, ranges: {}};
      if (url.pathname === '/api/status') data = {healthy: true, version: '3.8.0', job: {}, backups: {operation: {}, archives: [], warnings: []}};
      if (url.pathname === '/api/recovery') data = {operation: {}, originals: []};
      if (url.pathname === '/api/whats-new') {
        if (route.request().method() === 'POST') {
          assert.equal(route.request().postDataJSON().version, '3.8.0');
          if (fail) return route.fulfill({status: 500, json: {error: 'Storage unavailable'}});
          pending = false; dismissed++;
        }
        data = {available: true, pending, version: '3.8.0', highlights: [{title: 'Profile configs', description: 'Restore saved settings.'}, {title: 'Support reports', description: '<script>safe text</script>'}], url: 'https://github.com/Crosis47/tmodloader/releases/tag/3.8.0'};
      }
      await route.fulfill({json: data});
    });
    async function login() { await page.locator('#token').fill('test-token'); await page.getByRole('button', {name: 'Connect', exact: true}).click(); }
    await page.goto('http://news.test/');
    assert.equal(await page.locator('#whats-new-dialog').isVisible(), false);
    await login();
    await page.locator('#whats-new-dialog').waitFor();
    assert.equal(await page.locator('#whats-new-title').innerText(), 'What’s new in 3.8.0');
    assert.equal(await page.locator('#whats-new-highlights script').count(), 0);
    assert.match(await page.locator('#whats-new-highlights').innerText(), /<script>safe text/);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    fail = true; await page.locator('#whats-new-dismiss').click();
    await page.locator('#whats-new-status').filter({hasText: 'Storage unavailable'}).waitFor();
    assert.equal(await page.locator('#whats-new-dialog').isVisible(), true);
    fail = false; await page.keyboard.press('Escape');
    await page.locator('#whats-new-dialog').waitFor({state: 'hidden'});
    assert.equal(dismissed, 1);
    await page.reload();
    await Promise.all([page.waitForResponse(response => response.url().endsWith('/api/whats-new')), login()]);
    assert.equal(await page.locator('#whats-new-dialog').isVisible(), false);
    await page.locator('#whats-new-open').click();
    await page.locator('#whats-new-dialog').waitFor();
    await page.locator('#whats-new-dismiss').click();
    await page.locator('#whats-new-dialog').waitFor({state: 'hidden'});
    // Upgrade highlights wait for an existing dialog instead of replacing it.
    pending = true;
    await Promise.all([page.waitForResponse(response => response.url().endsWith('/api/whats-new')),
      page.evaluate(() => { document.getElementById('support-report-dialog').showModal(); showWhatsNew(); })]);
    assert.equal(await page.locator('#whats-new-dialog').isVisible(), false);
    await page.locator('#support-report-close').click();
    await page.locator('#whats-new-dialog').waitFor();
    await page.locator('#whats-new-dismiss').click();
    assert.deepEqual(errors, []);
    console.log('Upgrade highlights: sign-in, safe text, dismissal, failure/retry, Escape, reload, manual reopen, modal deferral and mobile layout passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
