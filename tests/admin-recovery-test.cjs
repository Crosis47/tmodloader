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
    let job = {state: 'idle'}, healthy = true, interrupted = false, restores = 0, prepares = 0;
    const archiveInfo = {name: archive, bytes: 100, sha256: preview.sha256, image_id: 'old-build', created: preview.created};
    const inspection = {...archiveInfo, archive, verified: true, snapshot: {active_world: 'Recovery', active_world_source: 'Running settings at backup', worlds: ['Recovery.wld'], enabled_mods: ['ExampleMod'], unpacked_bytes: 1000}, compatibility: {can_prepare: true, detail: 'Same tModLoader release, different container build.'}};
    await page.route('http://recovery.test/**', async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith('/api/')) {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({body: fs.readFileSync(path.join(__dirname, '../web', name)), contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      }
      let data = {};
      if (url.pathname === '/api/settings') data = {mode: 'env', pending: false, staged: {TMOD_MODS: ''}, running: {}, compose_only: {}, fields: {}, groups: [], ranges: {}, choices: {}};
      if (url.pathname === '/api/status') data = {healthy, version: 'test', job, backups: {operation: {}, archives: [archiveInfo], count: 1, bytes: 100, free_bytes: 90000, warnings: []}};
      if (url.pathname === '/api/recovery') data = {operation: {}, interrupted, originals: ['before-restore-1234567890abcdef1234567890abcdef'], guidance: 'Original data is retained for manual rollback.'};
      if (url.pathname === '/api/recovery/inspect') job = {kind: 'inspect', state: 'success', inspect: inspection};
      if (url.pathname === '/api/recovery/prepare') { assert.equal(route.request().postDataJSON().sha256, preview.sha256); prepares++; job = {kind: 'prepare', state: 'success', detail: 'Prepared copy created.'}; }
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
    await page.getByRole('button', {name: 'Backups & recovery', exact: true}).click();
    await page.locator('#archive-summary-0').click();
    assert.equal(await page.locator('#archive-summary-0').getAttribute('aria-expanded'), 'true');
    await page.locator('#archive-inspect-0').click();
    await page.locator('#archive-details-0').getByText('Recovery', {exact: true}).waitFor();
    await page.locator('#archive-prepare-0').click(); await page.locator('#confirm-cancel').click(); assert.equal(prepares, 0);
    await page.locator('#archive-prepare-0').click(); await page.locator('#confirm-go').click();
    await page.locator('#recovery-status').filter({hasText: 'Prepared copy created.'}).waitFor();
    assert.equal(prepares, 1); assert.equal(restores, 0);
    await page.locator('#refresh').evaluate(button => button.click());
    assert.equal(await page.locator('#archive-details-0').isVisible(), true);
    inspection.compatibility = {can_prepare: false, detail: 'Different game release; original image required.'};
    await page.locator('#archive-inspect-0').click();
    await page.locator('#archive-details-0').getByText('Different game release; original image required.', {exact: true}).waitFor();
    assert.equal(await page.locator('#archive-prepare-0').count(), 0);
    await page.locator('#archive-summary-0').click();
    assert.equal(await page.locator('#archive-details-0').isVisible(), false);
    assert.equal(await page.locator('#recovery-restore').isDisabled(), true);
    inspection.compatibility = {matches_current: true, can_prepare: false};
    await page.locator('#archive-inspect-0').click();
    await page.locator('#archive-restore-0').click();
    await page.locator('#recovery-preview-detail').getByText('Worlds: Recovery.wld', {exact: true}).waitFor();
    await page.locator('#restore-cancel').click(); assert.equal(restores, 0);
    await page.locator('#archive-restore-0').click();
    await page.locator('#recovery-preview-detail').getByText('Worlds: Recovery.wld', {exact: true}).waitFor();
    await page.locator('#recovery-restore').click();
    await page.locator('#recovery-status').filter({hasText: 'Staging verified files.'}).waitFor();
    assert.equal(restores, 1); assert.equal(await page.locator('#recovery-restore').isDisabled(), true);
    job = {kind: 'restore', state: 'failed', stage: 'health', detail: 'Startup failed. Inspect console.'};
    await page.locator('#refresh').evaluate(button => button.click());
    await page.locator('#recovery-status').filter({hasText: 'Startup failed. Inspect console.'}).waitFor();
    await page.locator('#recovery-retry').click(); await page.locator('#confirm-go').click();
    await page.locator('#recovery-status').filter({hasText: 'Game server is healthy.'}).waitFor();
    interrupted = true;
    await page.locator('#refresh').evaluate(button => button.click());
    await page.locator('#recovery').getByText('Interrupted file replacement: manual recovery required. Do not restart the game.').waitFor();
    assert.equal(await page.locator('#recovery-retry').isDisabled(), true);
    assert.equal(await page.locator('#recovery-restore').isDisabled(), true);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, 'Recovery page must fit a narrow screen');
    if (process.env.RECOVERY_SCREENSHOT) await page.screenshot({path: process.env.RECOVERY_SCREENSHOT, fullPage: true});
    job = {kind: 'inspect', archive, state: 'failed', detail: 'Archive checksum mismatch.'};
    await page.locator('#refresh').evaluate(button => button.click());
    await page.locator('#archives [role=status]').filter({hasText: 'Archive checksum mismatch.'}).waitFor();
    assert.deepEqual(errors, []);
    console.log('Recovery browser preview, cancellation, confirmation, progress, retry and interrupted-state tests passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
