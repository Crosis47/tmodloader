'use strict';
let token = '', config = null, page = 1, timer = null;
let consoleTimer = null, consoleBusy = false, commandHistory = [], historyPosition = 0;
let historyMode = false, historyOffsets = [0], historyNext = 0, historyRequest = 0;
let historyIdentity = '';
const $ = id => document.getElementById(id);
const tell = text => { $('message').textContent = text; };
const bytes = n => n == null ? 'Unavailable' : new Intl.NumberFormat(undefined, {maximumFractionDigits: 1}).format(n / 1073741824) + ' GiB';
async function api(path, body) {
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
    credentials: 'omit', headers: {Authorization: 'Bearer ' + token, ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
    body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
function action(fn) { return async event => { event?.preventDefault(); try { await fn(); } catch (error) { tell(error.message); } }; }
function confirmAction(title, text, diff = '') {
  $('confirm-title').textContent = title; $('confirm-text').textContent = text; $('confirm-diff').textContent = diff;
  $('confirmation').showModal();
  return new Promise(resolve => {
    $('confirm-go').onclick = () => { $('confirmation').close(); resolve(true); };
    $('confirm-cancel').onclick = () => { $('confirmation').close(); resolve(false); };
    $('confirmation').oncancel = () => resolve(false);
  });
}
function node(tag, text, className) { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; if (className) element.className = className; return element; }
const workshopApply = node('button', 'Apply changes'); workshopApply.id = 'workshop-apply'; workshopApply.type = 'button'; workshopApply.disabled = true;
const workshopActions = node('div', undefined, 'actions');
workshopActions.append(workshopApply, node('span', 'Review and apply all saved changes, then restart the game.', 'muted'));
$('selection-summary').after(workshopActions);
const runningModsPanel = node('section', undefined, 'panel');
const runningModsTitle = node('h3', 'Running mods');
const runningModsDetail = node('p', 'Waiting for server status…', 'muted');
const runningModsList = node('ul');
runningModsPanel.append(runningModsTitle, runningModsDetail, runningModsList);
$('overview').append(runningModsPanel);
const applyDialog = node('dialog'); applyDialog.id = 'apply-progress-dialog'; applyDialog.setAttribute('aria-label', 'Apply settings progress');
const applyProgress = node('section'); applyProgress.setAttribute('aria-live', 'polite');
const applyConnection = node('p', '', 'notice'); applyConnection.hidden = true; applyConnection.setAttribute('role', 'status');
const applyClose = node('button', 'Return to dashboard');
let dismissedApply = '', currentApply = '';
applyDialog.append(applyProgress, applyConnection, applyClose); document.body.append(applyDialog);
applyClose.onclick = () => { if (applyProgress.dataset.running !== 'true') { dismissedApply = currentApply; applyDialog.close(); } };
applyDialog.oncancel = event => { if (applyProgress.dataset.running === 'true') event.preventDefault(); else dismissedApply = currentApply; };
function progressError(error) { applyConnection.hidden = false; applyConnection.textContent = 'Connection interrupted: ' + error.message + ' Retrying status checks. The server may still be applying changes; do not submit them again.'; }
let progressPolling = false, applySubmitting = false;
setInterval(async () => {
  if (!token || applySubmitting || applyProgress.dataset.running !== 'true' || progressPolling || document.hidden) return;
  progressPolling = true;
  try { await refresh(); } catch (error) { progressError(error); }
  finally { progressPolling = false; }
}, 2000);
const historyControls = node('div', undefined, 'button-row');
const historyToggle = node('button', 'Browse full history'), historyFirst = node('button', 'Beginning'), historyPrevious = node('button', 'Previous page'), historyMore = node('button', 'Next page'), historyInfo = node('span', '', 'muted');
historyControls.append(historyToggle, historyFirst, historyPrevious, historyMore, historyInfo);
const historySource = node('select'); historySource.setAttribute('aria-label', 'Retained console log'); historySource.hidden = true;
async function loadHistorySources() {
  const data = await api('/api/console/runs');
  const selected = historySource.value;
  historySource.replaceChildren(...data.runs.map(run => {
    const label = run.id === 'current' ? 'Current run' : run.id === 'previous' ? 'Previous run' : 'Archived run';
    const range = (run.first ? new Date(run.first).toLocaleString() : 'First output unknown') + ' → ' + new Date(run.updated).toLocaleString();
    const option = node('option', range + ' — ' + label); option.value = run.id; return option;
  }));
  if (data.runs.some(run => run.id === selected)) historySource.value = selected;
  else if (data.runs.some(run => run.id === 'current')) historySource.value = 'current';
}
historyControls.insertBefore(historySource, historyFirst);
historySource.onchange = () => { historyIdentity = ''; historyOffsets = [0]; loadHistory(0); };
$('console-output').before(historyControls);
historyFirst.hidden = historyPrevious.hidden = historyMore.hidden = true;
function showApplyProgress(job) {
  applyConnection.hidden = true;
  if (job.kind !== 'apply') {
    if (applyDialog.open) {
      applyProgress.dataset.running = 'false'; applyClose.disabled = false;
      applyProgress.replaceChildren(node('h3', 'No active apply reported'), node('p', 'The server no longer reports this operation. Check the running settings and server status before trying again.'));
    }
    return;
  }
  applyProgress.dataset.running = String(job.kind === 'apply' && job.state === 'running');
  currentApply = job.started || 'pending';
  applyClose.disabled = job.state === 'running';
  applyClose.textContent = job.state === 'running' ? 'Please wait for the apply to finish' : 'Return to dashboard';
  if (!applyDialog.open && (job.state === 'running' || dismissedApply !== currentApply)) { $('confirmation').close(); applyDialog.showModal(); }
  const stages = [['queued', 'Queued'], ['stopping', 'Save & stop'], ['settings', 'Write settings'], ['mods', 'Update mods'], ['starting', 'Start game'], ['health', 'Check health']];
  const current = stages.findIndex(([id]) => id === job.stage);
  const end = job.finished ? Date.parse(job.finished) : Date.now();
  const elapsed = Math.max(0, Math.floor((end - Date.parse(job.started)) / 1000));
  const steps = node('ol', undefined, 'apply-steps');
  stages.forEach(([, title], index) => { const item = node('li', title + (job.state === 'success' || index < current ? ' — done' : index === current ? (job.state === 'failed' ? ' — failed' : ' — in progress') : '')); if (index === current) item.setAttribute('aria-current', 'step'); steps.append(item); });
  applyProgress.replaceChildren(node('h3', job.state === 'running' ? 'Applying settings…' : job.state === 'success' ? 'Settings applied successfully' : 'Settings could not be applied'), node('p', job.detail || 'Waiting for progress…'), steps, node('p', 'Elapsed: ' + elapsed + ' seconds. ' + (job.state === 'failed' ? 'Open the console to inspect output; correct the draft and apply again.' : 'Progress reflects completed stages, not a time estimate.'), 'muted'));
  $('apply').disabled = job.state === 'running' || config?.mode !== 'web' || !config?.pending;
  $('workshop-apply').disabled = $('apply').disabled;
  if (job.removed_client_mods?.length) {
    const notice = node('section', undefined, 'notice');
    notice.append(node('h3', 'Client-only mods removed'), node('p', 'These mods were removed from the server selection because they only run on clients. Cached downloads were kept.'));
    const list = node('ul'); list.append(...job.removed_client_mods.map(name => node('li', name))); notice.append(list); applyProgress.append(notice);
  }
  $('save-settings').disabled = job.state === 'running' || config?.mode !== 'web';
}
async function loadHistory(offset) {
  const request = ++historyRequest;
  historyInfo.textContent = 'Loading history…'; historyMore.disabled = true;
  try {
    const data = await api('/api/console?' + new URLSearchParams({mode: 'history', offset, source: historySource.value, ...(historyIdentity ? {identity: historyIdentity} : {})}));
    if (!historyMode || request !== historyRequest) return;
    $('console-output').textContent = data.output || '(No output retained)'; $('console-output').scrollTop = 0;
    historyNext = data.next_offset || 0; historyMore.disabled = !data.available || data.done;
    historyIdentity = data.identity || '';
    historyPrevious.disabled = historyOffsets.length === 1;
    historyInfo.textContent = data.available ? 'Bytes ' + offset.toLocaleString() + '–' + historyNext.toLocaleString() + ' of ' + data.total_bytes.toLocaleString() + (data.done ? ' · End of retained history' : '') : 'No retained log yet';
  } catch (error) { if (request === historyRequest) historyInfo.textContent = error.message; }
}
historyToggle.onclick = action(async () => {
  historyMode = !historyMode; historyRequest++;
  historyToggle.textContent = historyMode ? 'Return to live output' : 'Browse full history';
  historyFirst.hidden = historyPrevious.hidden = historyMore.hidden = !historyMode;
  historySource.hidden = !historyMode;
  $('console-follow').disabled = historyMode;
  if (historyMode) { historyIdentity = ''; historyOffsets = [0]; await loadHistorySources(); if (historyMode) await loadHistory(0); }
  else { historyInfo.textContent = ''; refreshConsole().catch(error => tell(error.message)); }
});
historyFirst.onclick = () => { historyIdentity = ''; historyOffsets = [0]; loadHistory(0); };
historyPrevious.onclick = () => { if (historyOffsets.length > 1) historyOffsets.pop(); loadHistory(historyOffsets.at(-1)); };
historyMore.onclick = () => { historyOffsets.push(historyNext); loadHistory(historyNext); };
async function refresh() {
  const data = await api('/api/status');
  if (applySubmitting) return;
  $('health').textContent = data.healthy ? 'Healthy' : 'Not ready / stopped';
  $('connection').textContent = 'Connected · v' + data.version;
  const loaded = data.mods || {available: false, mods: [], detail: 'Loaded-mod information is unavailable.'};
  runningModsTitle.textContent = 'Running mods' + (loaded.available ? ' (' + loaded.mods.length + ')' : '');
  runningModsDetail.textContent = loaded.detail;
  runningModsList.replaceChildren(...(loaded.available ? loaded.mods.map(mod => node('li', mod.name + ' — v' + mod.version)) : []));
  if (loaded.available && !loaded.mods.length) runningModsList.append(node('li', 'No gameplay mods loaded.'));
  const backups = data.backups;
  $('last-backup').textContent = backups.operation.last_success ? new Date(backups.operation.last_success).toLocaleString() : 'No recorded success';
  $('free-space').textContent = bytes(backups.free_bytes);
  $('archive-size').textContent = bytes(backups.bytes) + ' · ' + backups.count + ' archives';
  $('activity').textContent = [backups.operation.state || 'No recorded activity', backups.operation.detail || '', backups.operation.updated || ''].filter(Boolean).join(' — ');
  const oldJob = $('job').textContent;
  $('job').textContent = data.job.state === 'idle' ? '' : [data.job.kind, data.job.state, data.job.detail || ''].join(' · ');
  if (data.job.kind === 'apply' && data.job.state === 'success' && oldJob !== $('job').textContent) await loadSettings();
  showApplyProgress(data.job);
  $('backup').disabled = !data.healthy || data.job.state === 'running';
  $('warnings').replaceChildren(...backups.warnings.map(warning => node('p', warning, 'notice')));
  const rows = backups.archives.map(archive => {
    const row = node('tr'); row.append(node('td', archive.name), node('td', bytes(archive.bytes)));
    const cell = node('td'); const button = node('button', 'Verify'); button.disabled = data.job.state === 'running';
    button.onclick = action(async () => { await api('/api/verify', {archive: archive.name, confirm: true}); tell('Archive verification started. See operation status above.'); await refresh(); });
    cell.append(button); row.append(cell); return row;
  });
  $('archives').replaceChildren(...rows);
  if (!rows.length) { const row = node('tr'); const cell = node('td', 'No backup archives found.'); cell.colSpan = 3; row.append(cell); $('archives').append(row); }
}
async function loadSettings() {
  config = await api('/api/settings');
  $('mode').textContent = config.mode === 'web' ? 'Web-managed' : 'Environment-managed · read-only';
  $('pending').hidden = !config.pending;
  $('save-settings').disabled = config.mode !== 'web'; $('apply').disabled = config.mode !== 'web' || !config.pending;
  $('workshop-apply').disabled = $('apply').disabled || applyProgress.dataset.running === 'true';
  $('compose-settings').textContent = Object.entries(config.compose_only).map(([key, value]) => key + ': ' + value).join('\n');
  const sections = config.groups.map(group => {
    const section = node('fieldset', undefined, 'config-section'); section.id = 'config-' + group.id;
    section.append(node('legend', group.title), node('p', group.description, 'muted'));
    const grid = node('div', undefined, 'fields');
    for (const [key, metadata] of Object.entries(config.fields).filter(([, field]) => field.group === group.id)) {
    if (!(key in config.staged)) continue;
    const value = config.staged[key];
    const label = node('label', metadata.label);
    let input;
    const numericChoices = key.startsWith('TMOD_JOURNEY_') ? {'0': 'Locked', '1': 'Host only', '2': 'Everyone'} : ({TMOD_WORLDSIZE: {'1': 'Small', '2': 'Medium', '3': 'Large'}, TMOD_DIFFICULTY: {'0': 'Classic', '1': 'Expert', '2': 'Master', '3': 'Journey'}, TMOD_SECURE: {'0': 'Disabled', '1': 'Enabled'}, TMOD_UPNP: {'0': 'Disabled', '1': 'Enabled'}})[key];
    if (numericChoices || config.choices[key]) { input = node('select'); const choices = numericChoices || Object.fromEntries(config.choices[key].map(choice => [choice, choice])); for (const [choice, title] of Object.entries(choices)) { const option = node('option', title + (numericChoices ? ' (' + choice + ')' : '')); option.value = choice; input.append(option); } }
    else { input = node('input'); input.type = config.ranges[key] ? 'number' : 'text'; if (config.ranges[key]) { [input.min, input.max] = config.ranges[key]; input.step = '1'; } }
    input.name = key; input.value = value; input.disabled = config.mode !== 'web';
    const help = node('span', metadata.help, 'field-help'); help.id = 'help-' + key; input.setAttribute('aria-describedby', help.id);
    label.append(input, help, node('small', 'Running: ' + (config.running[key] || '(empty)')), node('code', key, 'setting-key')); grid.append(label);
    }
    section.append(grid); return section;
  });
  $('fields').replaceChildren(...sections);
  $('config-jumps').replaceChildren(...config.groups.map(group => { const link = node('a', group.title); link.href = '#config-' + group.id; return link; }));
  $('search-help').textContent = config.workshop_search ? 'Browse tModLoader mods with real Steam preview images. Steam metadata does not guarantee multiplayer or version compatibility.' : 'Provide a Steam API key to unlock the full graphical mod browser and search on this page, including real Steam preview images. Mount the key as a secret file, set TMOD_WORKSHOP_KEY_FILE to its container path, and recreate the container. A configured key must have access to Steam’s Workshop API.';
  if (!config.workshop_search) $('search-help').textContent += ' Import by Workshop URL or ID below works without an API key.';
  for (const id of ['search-form']) {
    $(id).hidden = !config.workshop_search;
    $(id).querySelectorAll('input, select, button').forEach(control => { control.disabled = !config.workshop_search; });
  }
  $('previous').parentElement.hidden = !config.workshop_search;
  $('search-button').disabled = !config.workshop_search;
  $('selection-summary').textContent = 'Staged Workshop entries: ' + (config.staged.TMOD_MODS || '(none)');
}
async function stageMod(item) {
  if (config.mode !== 'web') throw new Error('Enable web-managed configuration to stage mods.');
  const entry = (item.collection ? 'collection:' : '') + item.id;
  const items = new Set((config.staged.TMOD_MODS || '').split(',').filter(Boolean));
  if (item.client_only && !items.has(entry)) throw new Error('Client-only mods cannot be added to the server selection.');
  if (items.has(entry)) items.delete(entry); else items.add(entry);
  await api('/api/settings', {revision: config.revision, settings: {TMOD_MODS: [...items].join(',')}});
  await loadSettings(); tell('Mod selection staged. Use Apply changes here or Review & apply in Configuration when ready.');
}
function renderMods(items) {
  $('results').replaceChildren(...items.map(item => {
    const card = node('article', undefined, 'mod-card');
    if (item.client_only) { card.classList.add('client-only'); card.append(node('p', 'Client-only — does not run on a dedicated server', 'badge')); }
    if (item.preview) { const img = node('img'); img.src = item.preview; img.alt = ''; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer'; card.append(img); }
    const link = node('a', item.title); link.href = item.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    const heading = node('h3'); heading.append(link); card.append(heading, node('p', item.description));
    const runningEntry = (item.collection ? 'collection:' : '') + item.id;
    card.append(node('p', [item.collection ? 'Collection' : 'Mod', 'ID ' + item.id, item.downloaded ? 'Download folder present' : '', (config.running.TMOD_MODS || '').split(',').includes(runningEntry) ? 'In running selection' : '', item.updated ? new Date(item.updated * 1000).toLocaleDateString() : '', item.subscriptions == null ? '' : item.subscriptions + ' subscribers', item.votes?.votes_up == null ? '' : item.votes.votes_up + ' positive votes'].filter(Boolean).join(' · '), 'metadata'));
    const entry = (item.collection ? 'collection:' : '') + item.id;
    const button = node('button', (config.staged.TMOD_MODS || '').split(',').includes(entry) ? 'Remove from selection' : 'Add to selection');
    const selected = (config.staged.TMOD_MODS || '').split(',').includes(entry);
    button.disabled = config.mode !== 'web' || (item.client_only && !selected);
    if (item.client_only && !selected) button.textContent = 'Client-only';
    button.onclick = action(async () => { await stageMod(item); renderMods(items); }); card.append(button); return card;
  }));
  if (!items.length) $('results').append(node('p', 'No matching tModLoader items found.'));
}
async function search() {
  if (!config.workshop_search) throw new Error('Configure a Steam API key to unlock Workshop browsing.');
  tell('Searching Steam…');
  const result = await api('/api/workshop?' + new URLSearchParams({q: $('search-query').value, tag: $('search-tag').value, sort: $('search-sort').value, page}));
  renderMods(result.items); $('page-info').textContent = 'Page ' + page + ' · ' + result.total + ' results';
  $('previous').disabled = page <= 1; $('next').disabled = page >= 100 || page * 20 >= result.total; tell('');
}
async function refreshConsole() {
  if (!token || historyMode || $('console').hidden || consoleBusy || document.hidden) return;
  consoleBusy = true;
  try {
    const data = await api('/api/console'); const output = $('console-output');
    if (!historyMode && output.textContent !== data.output) { const position = output.scrollTop; output.textContent = data.output || '(No output yet)'; output.scrollTop = $('console-follow').checked ? output.scrollHeight : position; }
  } finally { consoleBusy = false; }
}
$('login-form').onsubmit = action(async () => { token = $('token').value; await loadSettings(); await refresh(); $('token').value = ''; $('login').hidden = true; $('dashboard').hidden = false; $('logout').hidden = false; tell(''); clearInterval(timer); timer = setInterval(() => refresh().catch(error => tell(error.message)), 15000); clearInterval(consoleTimer); consoleTimer = setInterval(() => refreshConsole().catch(error => { $('console-status').textContent = error.message; }), 2000); });
$('logout').onclick = () => { token = ''; config = null; commandHistory = []; clearInterval(timer); clearInterval(consoleTimer); location.reload(); };
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => { document.querySelectorAll('.view').forEach(view => { view.hidden = view.id !== button.dataset.view; }); document.querySelectorAll('nav [data-view]').forEach(item => { item.removeAttribute('aria-current'); if (item.dataset.view === button.dataset.view) item.setAttribute('aria-current', 'page'); }); if (button.dataset.view === 'console') { refreshConsole().catch(error => tell(error.message)); $('console-command').focus(); } });
$('console-form').onsubmit = action(async () => {
  const command = $('console-command').value.trim(); if (!command) return;
  const stopping = ['exit', 'exit-nosave'].includes(command.split(/\s+/)[0].toLowerCase());
  if (stopping && !(await confirmAction('Stop the game server?', 'This command can stop the container and disconnect this dashboard. exit-nosave discards unsaved world changes. You may need Docker to start it again.', command))) return;
  $('console-send').disabled = true;
  try { const result = await api('/api/console', {command, confirm_stop: stopping}); commandHistory.push(command); commandHistory = commandHistory.slice(-40); historyPosition = commandHistory.length; $('console-command').value = ''; $('console-status').textContent = result.detail; await refreshConsole(); }
  finally { $('console-send').disabled = false; $('console-command').focus(); }
});
$('console-command').onkeydown = event => { if (!['ArrowUp', 'ArrowDown'].includes(event.key) || !commandHistory.length) return; event.preventDefault(); historyPosition = Math.max(0, Math.min(commandHistory.length, historyPosition + (event.key === 'ArrowUp' ? -1 : 1))); $('console-command').value = commandHistory[historyPosition] || ''; };
$('refresh').onclick = action(refresh);
$('backup').onclick = action(async () => { if (await confirmAction('Back up now?', 'Players will be disconnected while the world is saved, archived, and restarted.')) { await api('/api/backup', {confirm: true}); await refresh(); } });
$('settings-form').onsubmit = action(async () => { const values = Object.fromEntries(new FormData($('settings-form'))); await api('/api/settings', {revision: config.revision, settings: values}); await loadSettings(); tell('Changes saved as a draft. The running server has not changed.'); });
$('workshop-apply').onclick = $('apply').onclick = action(async () => {
  const differences = Object.entries(config.staged).filter(([key, value]) => value !== config.running[key]).map(([key, value]) => key + ': ' + (config.running[key] || '(empty)') + ' → ' + value).join('\n');
  if (!(await confirmAction('Apply settings and restart?', 'This applies the saved draft, not unsaved form edits. Players will disconnect. Mod changes may take time to download. A failed mod update leaves the game stopped for recovery.', differences || 'Reapply the saved settings.'))) return;
  applySubmitting = true;
  showApplyProgress({kind: 'apply', state: 'running', stage: 'queued', started: new Date().toISOString(), detail: 'Submitting the reviewed settings. Controls are locked until the operation finishes.'});
  try { showApplyProgress(await api('/api/apply', {confirm: true, revision: config.revision})); }
  catch (error) { progressError(error); }
  finally { applySubmitting = false; }
  try { await refresh(); } catch (error) { progressError(error); }
});
$('search-form').onsubmit = action(async () => { page = 1; await search(); });
$('lookup-form').onsubmit = action(async () => { tell('Looking up Workshop item…'); renderMods([await api('/api/workshop/lookup', {value: $('lookup').value.trim()})]); $('page-info').textContent = ''; $('previous').disabled = true; $('next').disabled = true; tell(''); });
$('previous').onclick = action(async () => { page--; await search(); }); $('next').onclick = action(async () => { page++; await search(); });
// Optional browser-agent access uses the same authenticated, read-only API.
if (document.modelContext?.registerTool) {
  const lifecycle = new AbortController();
  Promise.resolve(document.modelContext.registerTool({name: 'read_server_backup_status',
    description: 'Read this server’s health, backup activity and storage warnings after the user connects.',
    inputSchema: {type: 'object', properties: {}, additionalProperties: false},
    annotations: {readOnlyHint: true, untrustedContentHint: true},
    execute: async input => { if (!token || !input || Object.keys(input).length) throw new Error('Connect first and provide an empty object.'); await refresh(); return api('/api/status'); }
  }, {signal: lifecycle.signal})).catch(() => {});
  window.addEventListener('pagehide', () => lifecycle.abort(), {once: true});
}
