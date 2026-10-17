const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    let requests = 0, fail = false;
    await page.addInitScript(() => {
      window.copiedReport = '';
      Object.defineProperty(navigator, 'clipboard', {value: {writeText: async value => {
        if (window.failClipboard) throw new Error('Clipboard blocked');
        window.copiedReport = value;
      }}});
    });
    await page.route('http://support.test/**', async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith('/api/')) {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({body: fs.readFileSync(path.join(__dirname, '../web', name)), contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      }
      let data = {};
      if (url.pathname === '/api/settings') data = {mode: 'web', pending: false, running: {}, staged: {}, revision: 'r', compose_only: {}, fields: {}, groups: [], choices: {}, ranges: {}};
      if (url.pathname === '/api/status') data = {healthy: true, version: 'test', job: {}, backups: {operation: {}, archives: [], warnings: []}};
      if (url.pathname === '/api/recovery') data = {operation: {}, originals: []};
      if (url.pathname === '/api/support-report') {
        assert.equal(route.request().method(), 'GET'); requests++;
        if (fail) return route.fulfill({status: 500, json: {error: 'Report unavailable'}});
        data = {report: '## Server support report\nContainer: 3.7.5\nError: [REDACTED]\n<script>test</script>'};
      }
      await route.fulfill({json: data});
    });
    await page.goto('http://support.test/');
    await page.locator('#token').fill('test-token'); await page.getByRole('button', {name: 'Connect', exact: true}).click();
    assert.equal(requests, 0);
    await page.locator('#support-report-open').click();
    await page.locator('#support-report-dialog').waitFor();
    assert.equal(requests, 1);
    assert.match(await page.locator('#support-report-content').inputValue(), /REDACTED/);
    assert.equal(await page.locator('#support-report-dialog script').count(), 0);
    await page.locator('#support-report-content').fill('Reviewed and edited report');
    await page.locator('#support-report-copy').click();
    assert.equal(await page.evaluate(() => window.copiedReport), 'Reviewed and edited report');
    await page.evaluate(() => { window.failClipboard = true; });
    await page.locator('#support-report-copy').click();
    await page.locator('#support-report-status').filter({hasText: 'Clipboard access is unavailable'}).waitFor();
    assert.equal(await page.locator('#support-report-content').evaluate(input => input.selectionEnd - input.selectionStart), 'Reviewed and edited report'.length);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.locator('#support-report-close').click();
    await page.waitForFunction(() => document.getElementById('support-report-content').value === '');
    assert.equal(await page.locator('#support-report-content').inputValue(), '');
    fail = true;
    await page.locator('#support-report-open').click();
    await page.locator('#message').filter({hasText: 'Report unavailable'}).waitFor();
    assert.equal(await page.locator('#support-report-dialog').isVisible(), false);
    assert.equal(await page.locator('#support-report-open').isEnabled(), true);
    assert.deepEqual(errors, []);
    console.log('Support preview, user edits, copy, clipboard fallback, safe text, cleanup, failure and mobile layout passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
