// Scheduling controls, draft submission, and polling without disrupting edits.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  try {
    const page = await browser.newPage();
    await page.clock.install();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const values = {TMOD_RESTART_MODE:'disabled', TMOD_RESTART_INTERVAL:'1440', TMOD_RESTART_TIME:'04:00',
      TMOD_RESTART_TIMEZONE:'UTC', TMOD_RESTART_DELAY:'60', TMOD_RESTART_MESSAGE:'Restart soon',
      TMOD_RESTART_DAYS:'7', TMOD_RESTART_WEEKDAY:'sunday', TMOD_RESTART_MONTHDAY:'1'};
    let posted;
    let schedule = {state:'scheduled',mode:'daily',time:'04:00',timezone:'America/New_York',next_at:1790308800};
    await page.route('http://restart.test/**', async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith('/api/')) {
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        return route.fulfill({body:fs.readFileSync(path.join(__dirname,'../web',name)),
          contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});
      }
      let data = {};
      if (url.pathname === '/api/settings') {
        if (route.request().method() === 'POST') { posted=route.request().postDataJSON(); Object.assign(values,posted.settings); }
        data={mode:'web',pending:false,revision:'r',running:values,staged:values,compose_only:{},
          groups:[{id:'restart',title:'Scheduled restarts',description:'Restart schedule'}],
          fields:Object.fromEntries(Object.keys(values).map(key=>[key,{group:'restart',label:key,help:'Schedule configuration'}])),
          choices:{TMOD_RESTART_MODE:['disabled','interval','days','daily','weekly','monthly'],
            TMOD_RESTART_WEEKDAY:['monday','tuesday','wednesday','thursday','friday','saturday','sunday']},
          ranges:{TMOD_RESTART_INTERVAL:[0,9999999],TMOD_RESTART_DELAY:[0,3600],
            TMOD_RESTART_DAYS:[1,3650],TMOD_RESTART_MONTHDAY:[1,31]}};
      }
      if (url.pathname === '/api/status') data={healthy:true,version:'test',job:{state:'idle'},restart_schedule:schedule,
        backups:{operation:{},archives:[],count:0,bytes:0,free_bytes:90000,warnings:[]}};
      if (url.pathname === '/api/worlds') data={configured:'Test',healthy:true,worlds:[],free_bytes:1000,warnings:[]};
      if (url.pathname === '/api/players') data={available:true,players:[],activity:[]};
      if (url.pathname === '/api/profiles') data={profiles:[],running:''};
      if (url.pathname === '/api/playthroughs') data={playthroughs:[],running:{}};
      if (url.pathname === '/api/recovery') data={operation:{},interrupted:false,originals:[]};
      await route.fulfill({json:data});
    });
    await page.goto('http://restart.test/');
    await page.locator('#token').fill('test-token');
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.getByRole('button',{name:'Configuration',exact:true}).click();
    await page.locator('#restart-schedule-status').filter({hasText:'America/New_York'}).waitFor();
    const mode=page.locator('[name="TMOD_RESTART_MODE"]');
    assert.deepEqual(await mode.locator('option').evaluateAll(options=>options.map(option=>option.value)),['disabled','interval','days','daily','weekly','monthly']);
    assert.equal(await page.locator('[name="TMOD_RESTART_TIME"]').isVisible(),false);
    await mode.selectOption('daily');
    const clock=page.locator('[name="TMOD_RESTART_TIME"]');
    await clock.fill('05:30');
    await page.locator('[name="TMOD_RESTART_TIMEZONE"]').fill('America/New_York');
    await clock.focus();
    schedule={state:'failed',detail:'Scheduled restart failed; inspect console.'};
    await page.clock.fastForward(16000);
    await page.locator('#restart-schedule-status').filter({hasText:'Scheduled restart failed'}).waitFor();
    assert.equal(await clock.inputValue(),'05:30');
    assert.equal(await clock.evaluate(el=>el===document.activeElement),true);
    await page.locator('#save-settings').click();
    await page.waitForFunction(()=>!document.querySelector('.setting-unsaved'));
    assert.equal(posted.settings.TMOD_RESTART_MODE,'daily');
    assert.equal(posted.settings.TMOD_RESTART_TIME,'05:30');
    assert.equal(posted.settings.TMOD_RESTART_TIMEZONE,'America/New_York');
    await mode.selectOption('interval');
    await page.locator('[name="TMOD_RESTART_INTERVAL"]').fill('360');
    await page.locator('#save-settings').click();
    await page.waitForFunction(()=>!document.querySelector('.setting-unsaved'));
    assert.equal(posted.settings.TMOD_RESTART_MODE,'interval');
    assert.equal(posted.settings.TMOD_RESTART_INTERVAL,'360');
    for (const [choice, key, value] of [['weekly','TMOD_RESTART_WEEKDAY','friday'],
                                      ['monthly','TMOD_RESTART_MONTHDAY','31'],
                                      ['days','TMOD_RESTART_DAYS','3']]) {
      await mode.selectOption(choice);
      const input=page.locator('[name="'+key+'"]');
      assert.equal(await input.isVisible(),true);
      assert.equal(await clock.isVisible(),choice!=='days');
      assert.equal(await page.locator('[name="TMOD_RESTART_INTERVAL"]').isVisible(),false);
      if(choice==='weekly') await input.selectOption(value); else await input.fill(value);
      await page.locator('#save-settings').click();
      await page.waitForFunction(()=>!document.querySelector('.setting-unsaved'));
      assert.equal(posted.settings.TMOD_RESTART_MODE,choice);
      assert.equal(posted.settings[key],value);
    }
    // Switching modes preserves previously saved values for each schedule.
    await mode.selectOption('weekly');
    assert.equal(await page.locator('[name="TMOD_RESTART_WEEKDAY"]').inputValue(),'friday');
    assert.equal(await clock.inputValue(),'05:30');
    schedule={state:'scheduled',mode:'monthly',monthday:31,time:'05:30',timezone:'America/New_York',next_at:1790308800};
    await page.clock.fastForward(16000);
    await page.locator('#restart-schedule-status').filter({hasText:'last day in shorter months'}).waitFor();
    await mode.selectOption('disabled');
    await page.locator('#save-settings').click();
    await page.waitForFunction(()=>!document.querySelector('.setting-unsaved'));
    assert.equal(posted.settings.TMOD_RESTART_MODE,'disabled');
    assert.deepEqual(errors,[]);
    console.log('All restart modes, relevant fields, retained values, and focus-safe status polling passed.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
