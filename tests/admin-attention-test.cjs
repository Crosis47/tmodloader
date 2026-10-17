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
    let posts = 0, pending = true;
    let modContent = '{"Enabled": true}';
    const duplicateContent = '{\r\n  "enabled": true\r\n}\r\n';
    const duplicateFiles = new Map([['DuplicateA.json', duplicateContent], ['DuplicateB.json', duplicateContent]]);
    let job = {state: 'idle'}, healthy = true, interrupted = false, restores = 0;
    await page.route('http://recovery.test/**', async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith('/api/')) {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({body: fs.readFileSync(path.join(__dirname, '../web', name)), contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      }
      if (route.request().method() === 'POST') posts++;
      let data = {};
      if (url.pathname === '/api/mod-configs/preview') {
        const payload = route.request().postDataJSON();
        if (payload.name.endsWith('.json')) {
          try { JSON.parse(payload.content); }
          catch (error) { return route.fulfill({status: 400, json: {error: 'Invalid JSON: ' + error.message}}); }
        }
        data = {current: {name: payload.name, content: duplicateFiles.get(payload.name) ?? modContent, format: payload.name.endsWith('.yaml') ? 'YAML' : 'JSON', revision: 'file-revision'},
          content: payload.content, action: 'save', conflict: false, diff: 'Test change preview', diff_limited: false};
      }
      if (url.pathname === '/api/mod-configs/validate') data = {format: 'YAML', checked: true};
      if (url.pathname === '/api/settings/discard') pending = false;
      if (url.pathname === '/api/mod-configs') {
        const name = url.searchParams.get('name') || route.request().postDataJSON()?.name || 'ModConfigs/Example_Server.json';
        if (route.request().method() === 'POST') {
          const content = route.request().postDataJSON().content;
          if (duplicateFiles.has(name)) duplicateFiles.set(name, content);
          else modContent = content;
        }
        data = url.searchParams.has('name') || route.request().method() === 'POST' ? {name, content: duplicateFiles.get(name) ?? modContent, format: name.endsWith('.yaml') ? 'YAML' : 'JSON', revision: 'file-revision'} : {files: ['ModConfigs/Example_Server.json', 'ModConfigs/SSCS/Custom.yaml', 'HEROsModDatabase.json', ...duplicateFiles.keys()]};
      }
      if (url.pathname === '/api/worlds') data = {configured:'Adventure',healthy:true,worlds:[{}],free_bytes:1000,warnings:[]};
      if (url.pathname === '/api/players') data = {available:true,players:[{name:'Test Player'}],updated:new Date().toISOString(),activity:[]};
      if (url.pathname === '/api/profiles') data = {profiles:[],running:''};
      if (url.pathname === '/api/playthroughs') data = {playthroughs:[],running:{}};
      if (url.pathname === '/api/settings') data = {mode: 'env', pending, draft_exists: true, staged: {TMOD_WORLDNAME: pending ? 'Next world' : 'Adventure'}, running: {TMOD_WORLDNAME: 'Adventure'}, compose_only: {}, fields: {TMOD_WORLDNAME: {label: 'World name'}}, groups: [], ranges: {}, choices: {}};
      if (url.pathname === '/api/status') data = {healthy, version: 'test', job, backups: {operation: {}, archives: [{name: archive, bytes: 100}], count: 1, bytes: 100, free_bytes: 90000, warnings: []}};
      if (url.pathname === '/api/recovery') data = {operation: {}, interrupted, originals: ['before-restore-1234567890abcdef1234567890abcdef'], guidance: 'Original data is retained for manual rollback.'};
      if (url.pathname === '/api/recovery/preview') job = {kind: 'preview', state: 'success', preview, started: new Date().toISOString()};
      if (url.pathname === '/api/recovery/restore') {
        assert.equal(route.request().postDataJSON().sha256, preview.sha256);
        restores++; job = {kind: 'restore', state: 'running', stage: 'restoring', detail: 'Staging verified files.'}; healthy = false;
      }
      if (url.pathname === '/api/recovery/retry') { job = {kind: 'retry', state: 'success', stage: 'health', detail: 'Game server is healthy.'}; healthy = true; }
      await route.fulfill({json: data});
    });
    await page.goto('http://recovery.test/');
    const issueLink = page.getByRole('link', {name: 'Report an issue', exact: true});
    assert.equal(await issueLink.isVisible(), true);
    assert.equal(await issueLink.getAttribute('href'), 'https://github.com/Crosis47/tmodloader/issues/new?template=bug_report.yml');
    assert.equal(await issueLink.getAttribute('target'), '_blank');
    assert.match(await issueLink.getAttribute('rel'), /noopener/);
    const featureLink = page.getByRole('link', {name: 'Request a feature', exact: true});
    assert.equal(await featureLink.getAttribute('href'), 'https://github.com/Crosis47/tmodloader/issues/new?template=feature_request.yml');
    assert.equal(await featureLink.getAttribute('target'), '_blank');
    assert.equal(await page.getByRole('link', {name: 'Wiki', exact: true}).isVisible(), true);
    await page.locator('#token').fill('test-token'); await page.getByRole('button', {name: 'Connect', exact: true}).click();
    await page.locator('#overview-world').filter({hasText:'Adventure'}).waitFor();
    await page.locator('#overview-players').filter({hasText:'Test Player'}).waitFor();
    assert.equal(await page.locator('#overview #backup, #overview #archives, #overview #recovery-restore, #overview input:not(#updates-announcements), #overview select').count(), 0);
    await page.locator('#attention-banner').waitFor();
    assert.equal(await page.locator('#overview-settings').evaluate(el => el.classList.contains('pending-highlight')), true);
    await page.getByRole('button', {name:'Review saved changes',exact:true}).click();
    assert.equal(await page.locator('#saved-changes-dialog').isVisible(), true);
    assert.match(await page.locator('#saved-changes-list').innerText(), /TMOD_WORLDNAME/);
    assert.match(await page.locator('#saved-changes-list').innerText(), /Next world/);
    if (process.env.CHANGES_SCREENSHOT) await page.screenshot({path: process.env.CHANGES_SCREENSHOT});
    await page.locator('#saved-changes-close').click();
    assert.equal(posts, 0);
    await page.getByRole('button', {name:'Overview',exact:true}).click();
    pending = false;
    await page.locator('#refresh').click();
    await page.locator('#attention-banner').waitFor({state:'hidden'});
    assert.equal(posts, 0);
    await page.evaluate(() => reviewSavedChanges());
    assert.match(await page.locator('#saved-changes-summary').innerText(), /matches the running settings/);
    assert.equal(await page.locator('#saved-changes-apply').isDisabled(), true);
    await page.locator('#saved-changes-close').click();
    await page.getByRole('button', {name: 'Backups & recovery', exact: true}).click();
    assert.equal(await page.locator('#backup').isVisible(), true);
    assert.equal(await page.locator('#archives').isVisible(), true);
    assert.equal(await page.locator('#recovery-preview').count(), 0);
    assert.equal(await page.locator('#restore-dialog').isVisible(), false);
    await page.locator('#backup').click(); await page.locator('#confirm-cancel').click(); assert.equal(posts, 0);
    pending = true;
    await page.evaluate(() => reviewSavedChanges());
    assert.equal(await page.locator('#saved-changes-close').innerText(), 'Continue');
    assert.equal(await page.locator('#saved-changes-apply').innerText(), 'Apply & Restart');
    await page.locator('#saved-changes-cancel').click();
    await page.locator('#saved-changes-dialog').waitFor({state: 'hidden'});
    assert.equal(pending, false);
    await page.getByRole('button', {name: 'Mod configs', exact: true}).click();
    await page.locator('#mod-config-file option').first().waitFor({state: 'attached'});
    await page.locator('#mod-config-file').selectOption('ModConfigs/Example_Server.json');
    await page.locator('#mod-config-open').click();
    await page.locator('#mod-config-content:not([disabled])').waitFor();
    assert.equal(await page.locator('#mod-config-highlight .syntax-key').innerText(), '"Enabled":');
    assert.equal(await page.locator('#mod-config-highlight .syntax-literal').innerText(), 'true');
    await page.locator('#mod-config-content').fill('{broken');
    await page.locator('#mod-config-save').click();
    await page.locator('#mod-config-validation').filter({hasText: 'Invalid JSON'}).waitFor();
    assert.equal(modContent, '{"Enabled": true}');
    await page.getByRole('button', {name: 'Overview', exact: true}).click();
    await page.getByRole('button', {name: 'Mod configs', exact: true}).click();
    assert.equal(await page.locator('#mod-config-content').inputValue(), '{broken');
    await page.locator('#mod-config-content').fill('{"Enabled": false}');
    await page.locator('#mod-config-save').click();
    await page.locator('#mod-config-review-confirm').click();
    await page.locator('#mod-config-status').filter({hasText: 'Saved ModConfigs/Example_Server.json'}).waitFor();
    assert.equal(modContent, '{"Enabled": false}');
    assert.equal(await page.locator('#mod-config-file option[value="ModConfigs/SSCS/Custom.yaml"]').innerText(), '/ModConfigs/SSCS/Custom.yaml');
    await page.locator('#mod-config-file').selectOption('ModConfigs/SSCS/Custom.yaml');
    await page.locator('#mod-config-open').click();
    await page.locator('#mod-config-status').filter({hasText: 'YAML'}).waitFor();
    await page.locator('#mod-config-content').fill('# retained comment\nenabled: true\n');
    assert.equal(await page.locator('#mod-config-highlight .syntax-comment').innerText(), '# retained comment');
    assert.equal(await page.locator('#mod-config-highlight .syntax-key').innerText(), 'enabled:');
    assert.equal(await page.locator('#mod-config-highlight').textContent(), '# retained comment\nenabled: true\n\n');
    await page.locator('#mod-config-check').click();
    await page.locator('#mod-config-validation').filter({hasText: 'YAML syntax is valid'}).waitFor();
    await page.locator('#mod-config-save').click();
    await page.locator('#mod-config-review-confirm').click();
    await page.locator('#mod-config-status').filter({hasText: 'Saved ModConfigs/SSCS/Custom.yaml'}).waitFor();
    assert.equal(modContent, '# retained comment\nenabled: true\n');
    modContent = '{"Users": []}';
    await page.locator('#mod-config-file').selectOption('HEROsModDatabase.json');
    assert.equal(await page.locator('#mod-config-file option:checked').innerText(), '/HEROsModDatabase.json');
    await page.locator('#mod-config-open').click();
    await page.locator('#mod-config-status').filter({hasText: 'Editing HEROsModDatabase.json'}).waitFor();
    await page.locator('#mod-config-content').fill('{"Users": [], "Groups": []}');
    await page.locator('#mod-config-save').click();
    await page.locator('#mod-config-review-confirm').click();
    await page.locator('#mod-config-status').filter({hasText: 'Saved HEROsModDatabase.json'}).waitFor();
    assert.equal(modContent, '{"Users": [], "Groups": []}');
    for (const name of ['DuplicateA.json', 'DuplicateB.json', 'DuplicateA.json', 'DuplicateB.json']) {
      await page.locator('#mod-config-file').selectOption(name);
      await page.locator('#mod-config-open').click();
      await page.locator('#mod-config-status').filter({hasText: 'Editing ' + name + ' ·'}).waitFor();
      assert.equal(await page.locator('#confirmation').isVisible(), false);
      assert.equal(await page.evaluate(() => modConfigDirty()), false);
      assert.equal(await page.locator('#mod-config-content').inputValue(), duplicateContent.replace(/\r\n/g, '\n'));
    }
    await page.locator('#mod-config-content').fill('{"enabled": false}');
    await page.locator('#mod-config-file').selectOption('DuplicateA.json');
    await page.locator('#mod-config-open').click();
    await page.locator('#confirmation').waitFor();
    await page.locator('#confirm-cancel').click();
    assert.equal(await page.evaluate(() => modConfig.name), 'DuplicateB.json');
    await page.locator('#mod-config-save').click();
    await page.locator('#mod-config-review-confirm').click();
    await page.locator('#mod-config-status').filter({hasText: 'Saved DuplicateB.json'}).waitFor();
    assert.equal(duplicateFiles.get('DuplicateA.json'), duplicateContent);
    assert.equal(duplicateFiles.get('DuplicateB.json'), '{"enabled": false}');
    assert.equal(await issueLink.isVisible(), true);
    await page.getByRole('button', {name:'Overview',exact:true}).click();
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    console.log('Overview read-only summaries, refresh, combined backup controls, cancellation and mobile layout passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
