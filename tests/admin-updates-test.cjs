const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    let checks = 0, rollbacks = 0, restarts = 0, deletions = 0;
    const updates = {installed:'v2026.06.3.0', channel:'stable', automatic:true, available:true, diagnostics_available:true,
      latest:{version:'v2026.07.3.0', url:'https://github.com/tModLoader/tModLoader/releases/tag/v2026.07.3.0'},
      operation:{state:'blocked',detail:'Missing dependency ExampleLibrary'}, rollback_available:true,
      previous_version:'v2026.05.3.0',checkpoint_created:'2026-09-21T00:00:00Z'};
    await page.route('http://updates.test/**', async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith('/api/')) {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({body:fs.readFileSync(path.join(__dirname,'../web',name)), contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});
      }
      let data = {};
      if (url.pathname === '/api/container-update') data={installed:'3.3.0',latest:'3.4.0',available:true,url:'https://github.com/Crosis47/tmodloader/releases/tag/3.4.0'};
      if (url.pathname === '/api/settings') data={mode:'env',pending:false,staged:{},running:{},compose_only:{},fields:{},groups:[],choices:{},ranges:{}};
      if (url.pathname === '/api/status') data={healthy:true,version:'test',updates,job:{state:'idle'},backups:{operation:{},archives:[],count:0,bytes:0,free_bytes:0,warnings:[]}};
      if (url.pathname === '/api/recovery') data={operation:{},interrupted:false,originals:[]};
      if (url.pathname === '/api/worlds') data={worlds:[],warnings:[]};
      if (url.pathname === '/api/players') data={players:[],activity:[]};
      if (url.pathname === '/api/profiles') data={profiles:[]};
      if (url.pathname === '/api/playthroughs') data={playthroughs:[]};
      if (url.pathname === '/api/updates/restart') { assert.equal(route.request().postDataJSON().confirm,true); restarts++; data={state:'running'}; }
      if (url.pathname === '/api/updates/check') { checks++; data=updates; }
      if (url.pathname === '/api/updates/rollback') { assert.equal(route.request().postDataJSON().confirm,true); rollbacks++; updates.rollback_pending=true; data=updates; }
      if (url.pathname === '/api/updates/delete-checkpoint') { assert.deepEqual(route.request().postDataJSON(), {confirm:true,checkpoint:'abc'}); deletions++; data={...updates,checkpoint_id:null,rollback_available:false,rollback_pending:false}; }
      if (url.pathname === '/api/updates/log') data={output:'compatibility.log\nExampleLibrary could not be loaded.'};
      await route.fulfill({json:data});
    });
    await page.goto('http://updates.test/');
    await page.locator('#token').fill('test-token');
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.locator('#container-release-dialog').waitFor({state:'visible'});
    assert.match(await page.locator('#container-release-dialog').innerText(),/Installed: 3.3.0/);
    await page.getByRole('button',{name:'Continue to dashboard',exact:true}).click();
    await page.locator('#updates-versions').filter({hasText:'v2026.06.3.0'}).waitFor();
    assert.match(await page.locator('#attention-items').innerText(),/New tModLoader version available/);
    assert.match(await page.locator('#updates-detail').innerText(),/Missing dependency/);
    assert.equal(await page.locator('#updates-release').getAttribute('href'),updates.latest.url);
    await page.locator('#updates-check').click(); assert.equal(checks,1); assert.equal(rollbacks,0);
    await page.locator('#updates-logs').click();
    await page.locator('#updates-log').filter({hasText:'ExampleLibrary could not be loaded'}).waitFor();
    await page.locator('#updates-rollback').click(); await page.locator('#confirm-cancel').click(); assert.equal(rollbacks,0);
    await page.locator('#updates-rollback').click(); await page.locator('#confirm-go').click();
    await page.locator('#updates-detail').filter({hasText:'Recovery is ready'}).waitFor();
    assert.equal(rollbacks,1); assert.equal(await page.locator('#updates-rollback').isHidden(),true);
    await page.locator('#updates-restart').click(); await page.locator('#confirm-cancel').click(); assert.equal(restarts,0);
    await page.locator('#updates-restart').click(); await page.locator('#confirm-go').click();
    await page.waitForFunction(() => !document.querySelector('#confirm-dialog')?.open);
    assert.equal(restarts,1);
    assert.equal(await page.locator('.update-guide').getAttribute('open'),null);
    assert.equal(await page.locator('.update-guide summary').innerText(),'Update workflow');
    await page.evaluate(() => showUpdateProgress({kind:'runtime-update',state:'running',stage:'updating',started:'2026-09-21T00:00:00Z'}, {operation:{state:'testing',detail:'Checking copied world'}}));
    assert.equal(await page.locator('#update-progress-dialog').isVisible(),true);
    assert.match(await page.locator('#update-progress-dialog [aria-current="step"]').innerText(),/Test mods/);
    await page.evaluate(() => showUpdateProgress({kind:'runtime-update',state:'success',stage:'health',started:'2026-09-21T00:00:00Z'}, {operation:{state:'blocked',detail:'Missing dependency'}}));
    assert.match(await page.locator('#update-progress-dialog').innerText(),/Update blocked/);
    assert.equal(await page.locator('#update-progress-dialog li').last().innerText(),'Update Complete - pending');
    await page.locator('#update-progress-dialog button').click();
    for (const state of ['updated', 'held', 'rolled_back']) {
      await page.evaluate(state => showUpdateProgress({kind:'runtime-update',state:'success',stage:'health',started:'2026-09-21T00:00:00Z'}, {operation:{state}}), state);
      assert.equal(await page.locator('#updates-progress').isHidden(),true);
      assert.equal(await page.locator('#update-progress-dialog li').last().innerText(),state === 'updated' ? 'Update Complete - done' : 'Recovery Complete - done');
      assert.equal(await page.locator('#update-progress-dialog').isVisible(),false);
    }
    await page.evaluate(() => renderUpdates({installed:'v2026.06.3.6',channel:'stable',automatic:true,available:true,rollback_available:true,hold:'v2026.06.3.6',operation:{state:'held'}}));
    assert.equal(await page.locator('#updates-rollback').isHidden(),true);

    await page.evaluate(() => renderUpdates({installed:'v2026.07.3.0',channel:'stable',automatic:true,available:false,operation:{state:'current'}}));
    for (const id of ['updates-restart','updates-logs','updates-rollback','updates-resume','updates-release']) assert.equal(await page.locator('#'+id).isHidden(),true,id);
    await page.evaluate(() => renderUpdates({installed:'v2026.06.3.6',channel:'stable',automatic:true,available:true,hold:'v2026.06.3.6',operation:{state:'held'}}));
    assert.equal(await page.locator('#updates-restart').isVisible(),true);
    assert.equal(await page.locator('#updates-resume').isHidden(),true);
    await page.evaluate(() => renderUpdates({installed:'v2026.06.3.6',channel:'stable',automatic:true,available:true,operation:{state:'current'}}));
    assert.equal(await page.locator('#updates-restart').isVisible(),true);
    await page.evaluate(() => renderUpdates({installed:'v2026.06.3.6',channel:'stable',automatic:true,checkpoint_id:'abc',hold:'v2026.06.3.6',operation:{state:'held'}}));
    await page.locator('#updates-delete').click(); await page.locator('#confirm-cancel').click(); assert.equal(deletions,0);
    await page.locator('#updates-delete').click(); await page.locator('#confirm-go').click();
    await page.locator('#updates-delete').waitFor({state:'hidden'}); assert.equal(deletions,1);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
    assert.deepEqual(errors,[]);
    console.log('Update notice, blocked compatibility, diagnostics, check-only action and confirmed recovery passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
