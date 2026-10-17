// Editor behavior against deterministic disk changes. Run with Playwright and Chromium/Edge installed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    const original = '{\r\n  "enabled": true\r\n}\r\n';
    const files = new Map([['ModConfigs/Example.json', original], ['HEROsModDatabase.json', original], ['Custom/options.json', '{}'], ['Custom/Nested/config.json', '{}']]);
    const history = new Map();
    const revision = content => createHash('sha256').update(content).digest('hex');
    const current = name => ({name, content: files.get(name), format: 'JSON', revision: revision(files.get(name)), can_restore: history.has(name)});
    let writes = 0, rejectWrite = false;
    let lastMergePayload = null;
    let mergeResult = {content:'{\n  "a": 2,\n  "b": 2\n}\n',conflicts:0,choices:[],manual:false};
    let resolvedMergeContent = '{"mine": 1, "disk": 1}';
    await page.route('http://editor.test/**', async route => {
      const request = route.request(), url = new URL(request.url());
      if (!url.pathname.startsWith('/api/')) {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({body: fs.readFileSync(path.join(__dirname, '../web', name)), contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      }
      const payload = request.method() === 'POST' ? request.postDataJSON() : {};
      let data = {};
      if (url.pathname === '/api/settings') data = {mode:'env',pending:false,staged:{TMOD_WORLDNAME:'Test'},running:{TMOD_WORLDNAME:'Test'},compose_only:{},fields:{},groups:[],ranges:{},choices:{}};
      if (url.pathname === '/api/status') data = {healthy:true,version:'test',job:{state:'idle'},backups:{operation:{},archives:[],count:0,bytes:0,free_bytes:90000,warnings:[]}};
      if (url.pathname === '/api/worlds') data = {configured:'Test',healthy:true,worlds:[],free_bytes:1000,warnings:[]};
      if (url.pathname === '/api/players') data = {available:true,players:[],activity:[]};
      if (url.pathname === '/api/recovery') data = {operation:{},originals:[]};
      if (url.pathname === '/api/profiles') data = {profiles:[],running:''};
      if (url.pathname === '/api/playthroughs') data = {playthroughs:[],running:{}};
      if (url.pathname === '/api/mod-configs' && request.method() === 'GET') {
        data = url.searchParams.has('name') ? current(url.searchParams.get('name')) : {files:[...files.keys()]};
      }
      if (url.pathname === '/api/mod-configs/preview') {
        const disk = current(payload.name), previous = history.get(payload.name), restoring = payload.action === 'restore';
        if (!restoring) {
          try {JSON.parse(payload.content);} catch {return route.fulfill({status:400,json:{error:'Invalid JSON'}});}
        }
        const proposed = restoring ? previous : payload.content;
        let diskError = null;
        if (!restoring) {
          try {JSON.parse(payload.disk_content ?? disk.content);}
          catch {
            if (payload.disk_content !== undefined) return route.fulfill({status:400,json:{error:'Invalid JSON in disk corrections'}});
            diskError='Invalid JSON: missing comma';
          }
        }
        data = {current:disk,content:proposed,action:restoring?'restore':'save',conflict:payload.revision!==disk.revision,
          disk_error:diskError,
          history_revision: previous && revision(previous),saved_at:'2026-10-17T00:00:00Z',
          diff:'--- On disk\n+++ Proposed\n-' + disk.content + '\n+' + proposed, diff_limited:false};
      }
      if (url.pathname === '/api/mod-configs/merge') {
        lastMergePayload = payload;
        data = {current:current(payload.name),...mergeResult, ...(payload.resolve ? {content:resolvedMergeContent} : {})};
      }
      if (url.pathname === '/api/mod-configs/validate') {
        try {JSON.parse(payload.content);data={checked:true,format:'JSON'};}
        catch {return route.fulfill({status:400,json:{error:'Invalid JSON'}});}
      }
      if (url.pathname === '/api/mod-configs' && request.method() === 'POST' || url.pathname === '/api/mod-configs/restore') {
        const disk = current(payload.name);
        if (payload.revision !== disk.revision) return route.fulfill({status:409,json:{error:'This file changed on disk.',conflict:disk}});
        if (rejectWrite) return route.fulfill({status:400,json:{error:'Wait for the current server operation.'}});
        const content = url.pathname.endsWith('/restore') ? history.get(payload.name) : payload.content;
        history.set(payload.name,disk.content); files.set(payload.name,content); writes++;
        data = current(payload.name);
      }
      return route.fulfill({json:data});
    });
    const open = async name => {
      await page.locator('#mod-config-file').selectOption(name);
      await page.locator('#mod-config-open').click();
      await page.locator('#mod-config-status').filter({hasText:'Editing '+name+' ·'}).waitFor();
    };
    const review = async () => {
      await page.locator('#mod-config-save').click();
      await page.locator('#mod-config-review').waitFor();
    };
    const confirm = async text => {
      await page.locator('#mod-config-review-confirm').click();
      await page.locator('#mod-config-status').filter({hasText:text}).waitFor();
    };
    await page.goto('http://editor.test');
    await page.locator('#token').fill('test-token');
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.locator('#dashboard').waitFor();
    await page.getByRole('button',{name:'Mod configs',exact:true}).click();
    await page.locator('#mod-config-file option').first().waitFor({state:'attached'});
    assert.equal(await page.locator('#mod-config-file optgroup').count(),4);
    assert.deepEqual(await page.locator('#mod-config-location option').evaluateAll(options=>options.map(option=>option.value)),['','.','Custom','Custom/Nested','ModConfigs']);
    await open('ModConfigs/Example.json');
    await open('HEROsModDatabase.json');
    assert.equal(await page.evaluate(() => modConfigDirty()),false);
    assert.equal(await page.locator('#mod-config-save').isDisabled(),true);
    await page.locator('#mod-config-content').fill('{broken');
    assert.equal(await page.locator('#mod-config-save').isEnabled(),true);
    await page.locator('#mod-config-check').click();
    await page.locator('#mod-config-validation').filter({hasText:'Invalid JSON'}).waitFor();
    assert.equal(await page.locator('#mod-config-validation').getAttribute('data-error'),'true');
    assert.equal(await page.locator('#message').innerText(),'');
    assert.equal(await page.locator('#mod-config-validation').evaluate(el=>el.nextElementSibling.classList.contains('config-code-editor')),true);
    files.set('HEROsModDatabase.json','{"external":true}');
    await page.locator('#mod-config-save').click();
    await page.locator('#mod-config-validation').filter({hasText:'Invalid JSON'}).waitFor();
    assert.equal(await page.locator('#mod-config-review').isVisible(),false);
    files.set('HEROsModDatabase.json',original);
    await page.locator('#mod-config-content').fill(original.replace(/\r\n/g,'\n'));
    assert.equal(await page.locator('#mod-config-save').isDisabled(),true);
    await page.locator('#mod-config-content').fill('{"enabled": false}');
    await page.locator('#mod-config-search').fill('CUSTOM/options');
    assert.equal(await page.locator('#mod-config-file option').count(),1);
    assert.equal(await page.locator('#mod-config-content').inputValue(),'{"enabled": false}');
    assert.match(await page.locator('#mod-config-current').innerText(),/HEROsModDatabase/);
    await page.locator('#mod-config-search').fill('missing');
    assert.equal(await page.locator('#mod-config-open').isDisabled(),true);
    await page.locator('#mod-config-search').fill('');
    await page.locator('#mod-config-location').selectOption('Custom/Nested');
    assert.equal(await page.locator('#mod-config-file option').count(),1);
    assert.equal(await page.locator('#mod-config-file option').first().getAttribute('value'),'Custom/Nested/config.json');
    await page.locator('#mod-config-location').selectOption('ModConfigs');
    assert.equal(await page.locator('#mod-config-file option').count(),1);
    await page.locator('#mod-config-location').selectOption('');
    await review();
    assert.match(await page.locator('#mod-config-diff').innerText(),/false/);
    assert.equal(writes,0);
    await page.locator('#mod-config-review-cancel').click();
    assert.equal(files.get('HEROsModDatabase.json'),original);
    await review(); await confirm('Saved HEROsModDatabase.json');
    assert.equal(files.get('ModConfigs/Example.json'),original);
    assert.equal(files.get('HEROsModDatabase.json'),'{"enabled": false}');
    assert.equal(await page.locator('#mod-config-save').isDisabled(),true);
    assert.equal(await page.locator('#mod-config-undo').isEnabled(),true);
    await page.locator('#mod-config-undo').click();
    await page.locator('#mod-config-review').waitFor();
    await page.locator('#mod-config-review-cancel').click();
    assert.equal(writes,1);
    await page.locator('#mod-config-undo').click();
    await confirm('Restored HEROsModDatabase.json');
    assert.equal(files.get('HEROsModDatabase.json'),original);
    assert.equal(history.get('HEROsModDatabase.json'),'{"enabled": false}');
    await page.locator('#mod-config-content').fill('{"mine": true}');
    files.set('HEROsModDatabase.json','{"external": 1}');
    await review();
    assert.match(await page.locator('#mod-config-review-title').innerText(),/changed on disk/);
    assert.equal(await page.locator('#mod-config-disk').inputValue(),'{"external": 1}');
    assert.equal(await page.locator('#mod-config-proposed').inputValue(),'{"mine": true}');
    assert.equal(await page.locator('#mod-config-review-confirm').isVisible(),false);
    await page.locator('#mod-config-review-cancel').click();
    assert.equal(await page.locator('#mod-config-content').inputValue(),'{"mine": true}');
    await review(); await page.locator('#mod-config-keep-draft').click();
    assert.equal(writes,2);
    assert.equal(await page.evaluate(() => modConfigDirty()),true);
    await review();
    files.set('HEROsModDatabase.json','{"external": 2}');
    await page.locator('#mod-config-review-confirm').click();
    await page.locator('#mod-config-review-title').filter({hasText:'changed on disk'}).waitFor();
    assert.equal(writes,2);
    assert.equal(await page.locator('#mod-config-content').inputValue(),'{"mine": true}');
    await page.locator('#mod-config-use-disk').click();
    assert.equal(await page.locator('#mod-config-content').inputValue(),'{"external": 2}');
    assert.equal(await page.evaluate(() => modConfigDirty()),false);
    assert.equal(await page.locator('#mod-config-save').isDisabled(),true);
    await page.locator('#mod-config-content').fill('{"mine": "retry"}');
    await review(); rejectWrite=true;
    await page.locator('#mod-config-review-confirm').click();
    await page.locator('#mod-config-review-summary').filter({hasText:'current server operation'}).waitFor();
    assert.equal(await page.locator('#mod-config-content').inputValue(),'{"mine": "retry"}');
    rejectWrite=false; await confirm('Saved HEROsModDatabase.json');
    assert.equal(writes,3);
    files.set('HEROsModDatabase.json','{\n  "a": 1,\n  "b": 1\n}\n');
    await open('HEROsModDatabase.json');
    await page.locator('#mod-config-content').fill('{\n  "a": 2,\n  "b": 1\n}\n');
    files.set('HEROsModDatabase.json','{"a":1 "b":2}');
    await page.locator('#mod-config-save').click();
    await page.locator('#mod-config-disk-repair').waitFor();
    assert.equal(await page.locator('#mod-config-review').isVisible(),false);
    assert.match(await page.locator('#mod-config-disk-error').innerText(),/Invalid JSON/);
    assert.equal(await page.locator('#mod-config-content').inputValue(),'{\n  "a": 2,\n  "b": 1\n}\n');
    assert.equal(await page.locator('#mod-config-merge-choices').isVisible(),false);
    assert.equal(writes,3);
    await page.locator('#mod-config-disk-repair-content').fill('{bad disk correction');
    await page.locator('#mod-config-disk-repair-continue').click();
    await page.locator('#mod-config-disk-error').filter({hasText:'Invalid JSON'}).waitFor();
    assert.equal(await page.locator('#mod-config-review').isVisible(),false);
    const correctedDisk = '{"a":1,"b":2}';
    await page.locator('#mod-config-disk-repair-content').fill(correctedDisk);
    await page.locator('#mod-config-disk-repair-cancel').click();
    await page.locator('#confirmation').waitFor();
    await page.locator('#confirm-cancel').click();
    assert.equal(await page.locator('#mod-config-disk-repair-content').inputValue(),correctedDisk);
    assert.equal(writes,3);
    await page.locator('#mod-config-disk-repair-continue').click();
    await page.locator('#mod-config-review').waitFor();
    assert.equal(await page.locator('#mod-config-disk-repair').isVisible(),false);
    assert.equal(await page.locator('#mod-config-disk').evaluate(el=>el.readOnly),true);
    assert.equal(await page.locator('#mod-config-check-disk').count(),0);
    await page.locator('#mod-config-combine').click();
    await page.locator('#mod-config-review').waitFor({state:'hidden'});
    assert.equal(lastMergePayload.disk_content,correctedDisk);
    assert.equal(await page.locator('#mod-config-content').inputValue(),mergeResult.content);
    await review(); await confirm('Saved HEROsModDatabase.json');
    assert.equal(writes,4);
    /* Continue with a genuine conflict after successful retry. */
    await page.locator('#mod-config-content').fill('{"mine": 1}');
    files.set('HEROsModDatabase.json','{"disk": 1}');
    mergeResult={content:'{"disk": 1}',conflicts:1,manual:false,skipped:1,
      choices:[{id:'0',label:'Setting /mine',mine:'1',disk:'2',original:'0'}]};
    await review(); await page.locator('#mod-config-combine').click();
    await page.locator('#mod-config-review-summary').filter({hasText:'matching change(s) already on disk skipped'}).waitFor();
    assert.equal(await page.locator('#mod-config-review-confirm').isDisabled(),true);
    assert.equal(await page.locator('#mod-config-merge-choices fieldset').count(),1);
    assert.match(await page.locator('#mod-config-merge-choices').innerText(),/Setting \/mine/);
    assert.equal(await page.locator('#mod-config-comparison').isVisible(),false);
    await page.getByRole('radio',{name:'Use my edit',exact:false}).check();
    assert.equal(await page.locator('#mod-config-review-confirm').isEnabled(),true);
    await page.locator('#mod-config-review-confirm').click();
    assert.equal(writes,4);
    assert.equal(await page.locator('#mod-config-content').inputValue(),'{"mine": 1, "disk": 1}');
    await review(); await confirm('Saved HEROsModDatabase.json');
    const writesAfterMerge = writes;
    await page.locator('#mod-config-content').fill('{"mine": 2, "disk": 1}');
    files.set('HEROsModDatabase.json','{"mine": 2, "disk": 2}');
    mergeResult={content:files.get('HEROsModDatabase.json'),conflicts:0,choices:[],skipped:1,manual:false};
    await review(); await page.locator('#mod-config-combine').click();
    await page.locator('#mod-config-review').waitFor({state:'hidden'});
    assert.equal(await page.locator('#mod-config-save').isDisabled(),true);
    assert.equal(writes,writesAfterMerge);
    assert.match(await page.locator('#mod-config-status').innerText(),/already match/);
    await page.locator('#mod-config-content').fill('{"mine": 3, "disk": 2}');
    files.set('HEROsModDatabase.json','{"mine": 3, "disk": 2}');
    await page.locator('#mod-config-save').click();
    await page.locator('#mod-config-status').filter({hasText:'already match'}).waitFor();
    assert.equal(await page.locator('#mod-config-review').isVisible(),false);
    assert.equal(await page.locator('#mod-config-save').isDisabled(),true);
    // Reloading retrieves the persisted file and undo availability.
    await open('HEROsModDatabase.json');
    assert.equal(await page.locator('#mod-config-undo').isEnabled(),true);
    await page.locator('#mod-config-content').fill('{"mine": "mobile"}');
    await page.setViewportSize({width:390,height:844});
    await review();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
    assert.equal(await page.locator('#mod-config-review').evaluate(el => el.scrollWidth <= el.clientWidth),true);
    if (process.env.EDITOR_SCREENSHOT) await page.screenshot({path:process.env.EDITOR_SCREENSHOT});
    await page.locator('#mod-config-review-cancel').click();
    assert.deepEqual(errors,[]);
    console.log('Discovered-folder filters, local syntax errors, dirty-only save, combined drafts, overlap resolution, undo, conflict recovery, save races and mobile layout passed.');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
