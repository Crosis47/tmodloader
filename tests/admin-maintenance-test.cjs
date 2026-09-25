const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.join(__dirname, '..');
const schema = JSON.parse(execFileSync(process.env.PYTHON || 'python', ['-c',
  'import json, admin_schema as a, admin_settings as s; print(json.dumps(dict(fields=a.FIELDS,groups=[dict(id=i,title=t,description=d) for i,t,d in a.GROUPS],ranges=s.RANGES,choices=s.CHOICES)))'], {cwd:root}));
const values = Object.fromEntries([...fs.readFileSync(path.join(root,'Dockerfile'),'utf8').matchAll(/^ENV (TMOD_\w+)="([^"]*)"/gm)]
  .filter(match=>schema.fields[match[1]]).map(match=>[match[1],match[2]]));
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{})});
  try {
    const page=await browser.newPage(); await page.clock.install();
    const errors=[]; page.on('pageerror',error=>errors.push(error.message));
    let job={state:'idle'}, schedule={state:'disabled'}, saves=0, restarts=0, posted;
    await page.route('http://maintenance.test/**',async route=>{
      const url=new URL(route.request().url());
      if(!url.pathname.startsWith('/api/')) {
        const name=url.pathname==='/'?'index.html':url.pathname.slice(1);
        return route.fulfill({body:fs.readFileSync(path.join(root,'web',name)),contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});
      }
      const payload=route.request().method()==='POST'?route.request().postDataJSON():null;
      let data={};
      if(url.pathname==='/api/settings') {
        if(payload){posted=payload.settings;Object.assign(values,posted);}
        data={...schema,mode:'web',revision:'r',running:values,staged:values,compose_only:{},pending:false};
      }
      if(url.pathname==='/api/status') data={healthy:true,busy:job.state==='running',version:'test',job,restart_schedule:schedule,
        backup_schedule:{state:'scheduled',mode:'weekly',weekday:'sunday',time:'03:00',timezone:'UTC',next_at:1790308800},
        backups:{operation:{},archives:[],count:0,bytes:0,free_bytes:90000,warnings:[]}};
      if(url.pathname==='/api/worlds') data={configured:'Test',healthy:true,worlds:[],free_bytes:1000,warnings:[]};
      if(url.pathname==='/api/players') data={available:true,players:[],activity:[]};
      if(url.pathname==='/api/profiles') data={profiles:[],running:''};
      if(url.pathname==='/api/playthroughs') data={playthroughs:[],running:{}};
      if(url.pathname==='/api/recovery') data={operation:{},interrupted:false,originals:[]};
      if(url.pathname==='/api/server/save'){saves++;data={sent:true};}
      if(url.pathname==='/api/server/restart') {
        assert.equal(payload.confirm,true);restarts++;job={state:'running',kind:'restart',detail:'Countdown active'};
        schedule={state:'countdown',mode:'disabled',countdown_end:Date.now()/1000+60};data=job;
      }
      if(url.pathname==='/api/restart/control') {
        assert.equal(payload.confirm,true);assert.equal(payload.action,'postpone');assert.equal(payload.minutes,15);
        schedule={state:'scheduled',mode:'interval',next_at:Date.now()/1000+900};job={state:'success',kind:'restart',detail:'Restart postponed; game was not stopped.'};data=schedule;
      }
      await route.fulfill({json:data});
    });
    await page.emulateMedia({colorScheme:'dark'});
    await page.goto('http://maintenance.test/');
    for (const palette of ['forest','ocean','amethyst','copper','slate','solarized','nord','rose-pine']) {
      await page.locator('#theme-palette').selectOption(palette);
      assert.equal(await page.locator('html').getAttribute('data-palette'),palette);
      const darkBackground = await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor);
      await page.locator('#theme-toggle').click();
      const lightBackground = await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor);
      assert.notEqual(darkBackground,lightBackground);
      await page.locator('#theme-toggle').click();
    }
    await page.locator('#theme-palette').selectOption('forest');
    await page.locator('#theme-toggle').click();
    assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
    await page.reload();
    assert.equal(await page.locator('#theme-palette').inputValue(),'forest');
    assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
    await page.locator('#token').fill('test-token');
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.locator('#save-now').click();assert.equal(saves,1);
    await page.locator('#server-action-status').filter({hasText:'Save command sent'}).waitFor();
    await page.locator('#restart-now').click();assert.equal(restarts,0);
    await page.locator('#confirm-go').click();
    await page.locator('#restart-control-status').filter({hasText:'Restart in'}).waitFor();
    assert.equal(restarts,1);assert.equal(await page.locator('#save-now').isDisabled(),true);
    await page.locator('#restart-postpone').click();await page.locator('#confirm-go').click();
    await page.locator('#server-action-status').filter({hasText:'Restart postponed'}).waitFor();
    await page.getByRole('button',{name:'Configuration',exact:true}).click();
    assert.equal(await page.locator('#game-controls').isVisible(),false);
    assert.deepEqual(await page.locator('#config-scheduling > section').evaluateAll(cards => cards.map(card => card.id)), ['config-backup', 'config-autosave', 'config-restart']);
    assert.equal(await page.locator('#config-jumps a[href="#config-scheduling"]').count(),1);
    assert.equal(await page.locator('#config-backup [name="TMOD_BACKUP_KEEP"]').count(),1);
    assert.equal(await page.locator('#config-autosave [name="TMOD_AUTOSAVE_INTERVAL"]').inputValue(),'10');
    await page.locator('[name="TMOD_BACKUP_MODE"]').selectOption('monthly');
    await page.locator('[name="TMOD_BACKUP_MONTHDAY"]').fill('31');
    await page.locator('[name="TMOD_BACKUP_TIME"]').fill('02:30');
    await page.locator('[name="TMOD_BACKUP_TIMEZONE"]').fill('America/New_York');
    assert.equal(await page.locator('[name="TMOD_BACKUP_KEEP"]').isVisible(),true);
    assert.equal(await page.locator('[name="TMOD_AUTOSAVE_INTERVAL"]').isVisible(),true);
    await page.locator('[name="TMOD_LOG_RETENTION_DAYS"]').fill('14');
    await page.locator('[name="TMOD_LOG_HISTORY_MAX_MB"]').fill('256');
    await page.locator('#save-settings').click();
    await page.waitForFunction(()=>!document.querySelector('.setting-unsaved'));
    assert.equal(posted.TMOD_BACKUP_MODE,'monthly');assert.equal(posted.TMOD_BACKUP_MONTHDAY,'31');
    assert.equal(posted.TMOD_LOG_RETENTION_DAYS,'14');assert.equal(posted.TMOD_LOG_HISTORY_MAX_MB,'256');
    await page.locator('#backup-config-status').filter({hasText:'Weekly on sunday'}).waitFor();
    assert.deepEqual(errors,[]);
    console.log('Save/restart actions, confirmation, countdown postpone, backup calendars, and retention controls passed.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
