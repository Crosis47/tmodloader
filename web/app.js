'use strict';

let attentionSettings = null, attentionStatus = null, attentionRecovery = null;
let token = '', config = null, page = 1, timer = null;

let consoleTimer = null, consoleBusy = false, commandHistory = [], historyPosition = 0;

let historyMode = false, historyOffsets = [0], historyNext = 0, historyRequest = 0;

let historyIdentity = '';

const $ = id => document.getElementById(id);

const tell = text => { $('message').textContent = text; };

const bytes = n => {
  if (n == null) return 'Unavailable';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB', 'ZiB', 'YiB'];
  let unit = 0;
  // Promote at 1,000 for readability, retaining binary (1,024-byte) units.
  while (Math.abs(n) >= 1000 && unit < units.length - 1) {
    n /= 1024;
    unit++;
  }
  return new Intl.NumberFormat(undefined, {maximumFractionDigits: 1}).format(n) + ' ' + units[unit];
};

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
  attentionStatus = data;
  try { attentionSettings = await api('/api/settings'); } catch { attentionSettings = null; }
  renderAttention();

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

  if (['apply', 'restore', 'retry'].includes(data.job.kind) && data.job.state === 'success' && oldJob !== $('job').textContent) await loadSettings();

  showApplyProgress(data.job);

  await refreshRecovery(data);
  $('overview-backup').textContent = $('activity').textContent;
  $('overview-job').textContent = $('job').textContent;
  await refreshOverview();

  $('backup').disabled = !data.healthy || data.job.state === 'running';

  $('warnings').replaceChildren(...backups.warnings.map(warning => node('p', warning, 'notice')));

  renderArchives(data);

}

const expandedArchives = new Set(), inspectedArchives = new Map();
let archiveSignature = '';
function renderArchives(data) {
  if (data.job.state === 'success' && data.job.inspect) {
    const result = data.job.inspect;
    inspectedArchives.set(result.archive, result);
  }
  if (data.job.kind === 'inspect' && data.job.state === 'failed') inspectedArchives.delete(data.job.archive);
  const signature = JSON.stringify([data.backups.archives, data.job, [...inspectedArchives]]);
  if (signature === archiveSignature) return;
  archiveSignature = signature;
  const focusId = $('archives').contains(document.activeElement) ? document.activeElement.id : null;
  const rows = data.backups.archives.flatMap((archive, index) => {
    const cached = inspectedArchives.get(archive.name);
    const details = cached && cached.sha256 === archive.sha256 && cached.image_id === archive.image_id ? cached : archive;
    const snapshot = details.snapshot || {}, runtime = details.runtime || {}, compatibility = details.compatibility || {};
    const row = node('tr'), cell = node('td'), detailRow = node('tr'), detailCell = node('td'), disclosure = node('div'), summary = node('button', (expandedArchives.has(archive.name) ? '▾ ' : '▸ ') + archive.name);
    detailCell.colSpan = 3; disclosure.className = 'world-details';
    detailRow.hidden = !expandedArchives.has(archive.name);
    detailRow.id = 'archive-details-' + index;
    summary.setAttribute('aria-controls', detailRow.id);
    summary.setAttribute('aria-expanded', String(!detailRow.hidden));
    summary.id = 'archive-summary-' + index;
    summary.onclick = () => { detailRow.hidden = !detailRow.hidden; summary.textContent = (detailRow.hidden ? '▸ ' : '▾ ') + archive.name; summary.setAttribute('aria-expanded', String(!detailRow.hidden)); if (!detailRow.hidden) expandedArchives.add(archive.name); else expandedArchives.delete(archive.name); };
    const grid = node('dl'); grid.className = 'world-details-grid'; disclosure.append(grid);
    const lines = [
      ['Backup date', recoveryDate(archive.created)],
      [snapshot.active_world_source === 'Saved dashboard settings' ? 'Saved world selection (running world unconfirmed)' : 'Last running world', snapshot.active_world || 'Not recorded'],
      ['World identification source', snapshot.active_world_source || 'Not recorded; inspect this archive'],
      ['Saved worlds', (snapshot.worlds || []).join(', ') || 'Not recorded'],
      ['World count', snapshot.world_count ?? 'Not recorded'],
      ['Enabled mod count', snapshot.enabled_mod_count ?? 'Not recorded'],
      ['Enabled mods', (snapshot.enabled_mods || []).join(', ') || 'None recorded'],
      ['Workshop items', (snapshot.workshop || []).join(', ') || 'None recorded'],
      ['Container version', runtime.container_version || 'Not recorded'],
      ['tModLoader version', runtime.tmodloader_version || snapshot.tmodloader_version || 'Not recorded'],
      ['Unpacked size', snapshot.unpacked_bytes == null ? 'Not recorded' : bytes(snapshot.unpacked_bytes)],
      ['Files', snapshot.file_count ?? 'Not recorded'],
      ['Included data', [['Dashboard settings', snapshot.has_settings], ['Logs', snapshot.has_logs], ['Mod configuration', snapshot.has_mod_config]].filter(([, present]) => present).map(([label]) => label).join(', ') || 'Inspect to check contents'],
      ['Checksum (SHA-256)', details.sha256 || 'Not recorded'],
      ['Compatibility', compatibility.detail || 'Inspect to check compatibility']
    ];
    if (details.prepared_from) lines.push(['Prepared from', details.prepared_from.archive], ['Copy prepared on', recoveryDate(details.prepared_from.prepared_at)]);
    for (const [label, value] of lines) { const item = node('div'); item.append(node('dt', label), node('dd', String(value))); grid.append(item); }
    disclosure.append(node('p', details.verified ? 'Checksum and archive contents verified.' : 'Manifest summary; use Inspect & verify to check the archived files.', 'muted'));
    disclosure.append(node('p', 'Restoring replaces worlds, mods, mod configuration, logs and saved dashboard settings. Current admin credentials and Compose settings are preserved.', 'muted'));
    cell.append(summary); detailCell.append(disclosure); detailRow.append(detailCell); row.append(cell, node('td', bytes(archive.bytes)));
    const actions = node('td'), inspect = node('button', 'Inspect & verify'); inspect.id = 'archive-inspect-' + index;
    inspect.disabled = data.job.state === 'running' || data.backups.operation.state === 'running';
    const inspectionStatus = node('p', '', 'muted'); inspectionStatus.setAttribute('role', 'status');
    if (data.job.archive === archive.name && ['inspect', 'prepare'].includes(data.job.kind)) {
      inspectionStatus.textContent = data.job.state === 'running' ? 'Checking archive checksum and contents…' : data.job.detail || (data.job.state === 'failed' ? 'Inspection failed.' : 'Inspection complete.');
    } else if (details.verified) inspectionStatus.textContent = 'Checksum and contents verified.';
    inspect.onclick = action(async () => {
      expandedArchives.add(archive.name); inspect.disabled = true; inspectionStatus.textContent = 'Starting inspection…';
      try { await api('/api/recovery/inspect', {archive: archive.name}); await refresh(); }
      catch (error) { inspectionStatus.textContent = 'Inspection failed: ' + error.message; inspect.disabled = false; throw error; }
    });
    actions.append(inspect, inspectionStatus);
    if (details.verified && compatibility.can_prepare) {
      const prepare = node('button', 'Prepare for Running Container Version'); prepare.id = 'archive-prepare-' + index; prepare.disabled = inspect.disabled;
      prepare.onclick = action(async () => {
        if (await confirmAction('Prepare backup for this container?', 'Create a verified copy of ' + archive.name + ' for the current container. The original stays intact. This requires additional backup storage.', 'The tModLoader release matches. World files and mods are not converted or changed. Restore remains a separate action.')) {
          await api('/api/recovery/prepare', {archive: archive.name, sha256: details.sha256, confirm: true}); await refresh();
        }
      }); disclosure.append(prepare);
    }
    if (details.verified && compatibility.matches_current) {
      const restore = node('button', 'Restore this backup'); restore.id = 'archive-restore-' + index;
      restore.disabled = inspect.disabled;
      restore.onclick = action(() => openRestoreReview(archive.name)); disclosure.append(restore);
    }
    row.append(actions); return [row, detailRow];
  });
  if (!rows.length) { const row = node('tr'), cell = node('td', 'No backup archives found.'); cell.colSpan = 3; row.append(cell); rows.push(row); }
  $('archives').replaceChildren(...rows);
  if (focusId) document.getElementById(focusId)?.focus({preventScroll: true});
}

let recoveryArchive = null, recoveryPreview = null, recoverySubmitting = false, recoveryBusy = false;

function recoveryDate(value) {

  const match = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(\d*)Z$/.exec(value || '');

  return match ? new Date(`${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${match[6]}Z`).toLocaleString() : value || 'Unknown';

}

async function refreshRecovery(data) {

  const recovery = await api('/api/recovery');
  attentionRecovery = recovery; renderAttention();

  const job = data.job;

  const busy = recoverySubmitting || job.state === 'running' || data.backups.operation.state === 'running';

  if (job.kind === 'preview' && job.state === 'success' && job.preview?.archive === recoveryArchive) recoveryPreview = job.preview;

  if (recoveryPreview?.archive !== recoveryArchive) recoveryPreview = null;

  const preview = recoveryPreview;

  $('recovery-preview-detail').replaceChildren(...(preview ? [node('p', 'Created: ' + recoveryDate(preview.created)), node('p', 'Last running world: ' + (preview.snapshot?.active_world || 'Not recorded')), node('p', 'Worlds: ' + (preview.worlds.join(', ') || 'No world files recorded')), node('p', preview.replaces), node('p', 'Staging space: ' + bytes(preview.required_bytes) + ' · available: ' + bytes(preview.free_bytes)), node('p', 'Original data will be retained for manual rollback. The archive is checked again before the game stops.', 'muted')] : [node('p', job.kind === 'preview' && job.state === 'failed' ? job.detail : 'Checking archive checksum, compatibility and available space…')]));

  $('recovery-restore').disabled = busy || !preview || recovery.interrupted;

  $('recovery-retry').disabled = busy || data.healthy || recovery.interrupted;

  const current = ['preview', 'restore', 'retry', 'inspect', 'prepare'].includes(job.kind) ? job : recovery.operation;

  $('recovery-status').textContent = recovery.interrupted ? 'Interrupted file replacement: manual recovery required. Do not restart the game.' : current.state ? [current.kind, current.state, current.detail].filter(Boolean).join(' · ') : 'No recovery operation recorded.';

  const stages = ['preview', 'inspect', 'prepare'].includes(current.kind) ? [['queued', current.kind === 'prepare' ? 'Prepare verified copy' : 'Verify archive']] : [['queued', 'Queued'], ['verifying', 'Verify before downtime'], ['stopping', 'Save & stop'], ['restoring', 'Stage & replace files'], ['settings', 'Load configuration'], ['starting', 'Start game'], ['health', 'Check health']].filter(([id]) => current.kind !== 'retry' || !['verifying', 'restoring'].includes(id));

  const index = stages.findIndex(([id]) => id === current.stage);

  $('recovery-steps').replaceChildren(...(current.state && !recovery.interrupted ? stages.map(([, title], i) => node('li', title + (current.state === 'success' || i < index ? ' — done' : i === index ? ' — ' + current.state : ' — waiting'))) : []));

  $('overview-recovery').textContent = $('recovery-status').textContent;
  $('overview-originals').textContent = recovery.originals.length + ' retained original data directories.';
  $('recovery-guidance').textContent = recovery.guidance;

  $('recovery-originals').replaceChildren(...(recovery.originals.length ? recovery.originals.map(name => node('li', name)) : [node('li', 'No retained original directories yet.')]));

}

async function openRestoreReview(name) {
  recoveryArchive = name; recoveryPreview = null;
  $('restore-archive').textContent = name;
  $('recovery-preview-detail').textContent = 'Checking archive checksum, compatibility and available space…';
  $('recovery-restore').disabled = true;
  $('restore-dialog').showModal();
  try { await submitRecovery('preview', {archive: name}); }
  catch (error) { $('recovery-preview-detail').textContent = error.message; }
}
$('restore-cancel').onclick = () => $('restore-dialog').close();
$('restore-dialog').addEventListener('close', () => { recoveryArchive = null; recoveryPreview = null; });

async function submitRecovery(kind, body) {

  if (recoverySubmitting) return;

  if (kind === 'preview') recoveryPreview = null;

  recoverySubmitting = true;

  for (const id of ['recovery-restore', 'recovery-retry']) $(id).disabled = true;

  try { await api('/api/recovery/' + kind, body); }

  finally { recoverySubmitting = false; }

  await refresh();

}

$('recovery-restore').onclick = action(async () => {
  const preview = recoveryPreview;
  if (!preview || preview.archive !== recoveryArchive) return;
  await submitRecovery('restore', {archive: preview.archive, sha256: preview.sha256, confirm: true});
  $('restore-dialog').close();
});

$('recovery-retry').onclick = action(async () => { if (await confirmAction('Retry game startup?', 'Start the current data again and check game health. This does not replace files.')) await submitRecovery('retry', {confirm: true}); });

setInterval(async () => {

  if (!token || $('recovery').hidden || document.hidden || recoveryBusy || recoverySubmitting) return;

  recoveryBusy = true;

  try { await refresh(); } catch (error) { $('recovery-status').textContent = 'Connection interrupted: ' + error.message + ' Status checks will retry. Do not resubmit an operation until its result is known.'; }

  finally { recoveryBusy = false; }

}, 2000);

async function loadSettings() {

  config = await api('/api/settings');
  attentionSettings = config; renderAttention();

  $('mode').textContent = config.mode === 'web' ? 'Web-managed' : 'Environment-managed · read-only';

  $('pending').hidden = !config.pending;

  $('save-settings').disabled = config.mode !== 'web'; $('apply').disabled = config.mode !== 'web' || !config.pending;

  $('workshop-apply').disabled = $('apply').disabled || applyProgress.dataset.running === 'true';

  $('compose-settings').textContent = Object.entries(config.compose_only).map(([key, value]) => key + ': ' + value).join('\n');

  const configurationGroups = config.groups.filter(group => !['world', 'journey'].includes(group.id));
  const sections = configurationGroups.map(group => {

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

    const unsaved = node('span', 'Unsaved change', 'unsaved-badge'); unsaved.hidden = true;
    const awaitingApply = value !== (config.running[key] ?? '');
    const stagedBadge = node('span', 'Saved · waiting to apply', 'staged-badge'); stagedBadge.hidden = !awaitingApply;
    label.classList.toggle('setting-staged', awaitingApply);
    label.classList.add('setting-card');
    const updateDirty = () => {
      const dirty = input.value !== value;
      label.classList.toggle('setting-unsaved', dirty); unsaved.hidden = !dirty;
      renderAttention();
    };
    input.addEventListener('input', updateDirty); input.addEventListener('change', updateDirty);
    label.append(input, unsaved, stagedBadge, help, node('small', 'Running: ' + (config.running[key] || '(empty)')), node('code', key, 'setting-key')); grid.append(label);

    }

    section.append(grid); return section;

  });

  $('fields').replaceChildren(...sections);
  renderAttention();

  $('config-jumps').replaceChildren(...configurationGroups.map(group => { const link = node('a', group.title); link.href = '#config-' + group.id; return link; }));

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

let worldState = null, worldsBusy = false, worldSubmitting = false;
const expandedWorlds = new Set();

function worldUptime(world) {
  if (!world.selected) return 'Not active';
  if (!worldState?.healthy) return 'Server not running / starting';
  if (world.session_uptime_seconds == null) return 'Unavailable';
  return uptimeDuration(world.session_uptime_seconds);
}

function uptimeDuration(value) {
  const seconds = Math.max(0, Math.floor(value));
  const days = Math.floor(seconds / 86400), hours = Math.floor(seconds % 86400 / 3600), minutes = Math.floor(seconds % 3600 / 60);
  return (days ? days + 'd ' : '') + (days || hours ? hours + 'h ' : '') + minutes + 'm ' + seconds % 60 + 's';
}

function updateWorldUptimes() {
  for (const element of $('worlds-list').querySelectorAll('[data-world-uptime]')) {
    const world = worldState?.worlds?.find(world => world.name === element.dataset.worldUptime);
    element.textContent = world ? (element.dataset.uptimeKind === 'total' ? world.total_uptime_seconds == null ? 'Not tracked yet' : uptimeDuration(world.total_uptime_seconds) : worldUptime(world)) : 'Unavailable';
  }
}

function worldDetails(world) {
  const panel = node('div', undefined, 'world-details'), details = world.metadata;
  const list = node('dl', undefined, 'world-details-grid');
  const add = (label, value) => { const item = node('div'); item.append(node('dt', label), node('dd', value)); list.append(item); };
  if (details?.available) {
    add('World name', details.title);
    add('Size', details.size + ' · ' + details.width.toLocaleString() + ' × ' + details.height.toLocaleString() + ' tiles');
    add('Difficulty', details.difficulty);
    add('Evil', details.evil);
    add('Seed', details.seed || 'Not recorded');
    add('Progression', details.hardmode ? 'Hardmode' : 'Pre-Hardmode');
    add('Special seeds', details.special_seeds?.join(', ') || 'None');
    add('Created', details.created ? new Date(details.created).toLocaleString() : 'Not recorded');
    add('Spawn (tiles)', details.spawn.x + ', ' + details.spawn.y);
    add('Dungeon (tiles)', details.dungeon.x + ', ' + details.dungeon.y);
    add('World ID', String(details.world_id));
  } else {
    panel.append(node('p', details?.detail || 'World details are unavailable for this save.', 'muted'));
  }
  add('World file', (world.filename || world.name + '.wld') + ' · ' + bytes(world.bytes));
  add('Mod data', world.has_mod_data ? world.name + '.twld · ' + bytes(world.mod_bytes) : 'No mod sidecar');
  add('Last saved', new Date(world.modified).toLocaleString());
  const uptime = node('div'), value = node('dd', worldUptime(world)); value.dataset.worldUptime = world.name;
  uptime.append(node('dt', 'Current session uptime'), value, node('small', 'Time since this world finished loading. Resets on restart or world switch.', 'muted')); list.append(uptime);
  const total = node('div'), totalValue = node('dd', world.total_uptime_seconds == null ? 'Not tracked yet' : uptimeDuration(world.total_uptime_seconds));
  totalValue.dataset.worldUptime = world.name; totalValue.dataset.uptimeKind = 'total';
  total.append(node('dt', 'Total uptime'), totalValue, node('small', world.uptime_tracked_since ? 'Time loaded across sessions, tracked since ' + new Date(world.uptime_tracked_since).toLocaleString() + '.' : 'Tracking starts the next time this world loads. Earlier sessions are not included.', 'muted')); list.append(total);
  panel.append(list, node('p', 'Details reflect the last saved world. Mods may add difficulty or progression beyond these base-game values.', 'muted'));
  return panel;
}

function renderWorlds() {

  const state = worldState;

  const editable = state?.editable && !state.busy && !worldSubmitting;

  $('world-current-label').textContent = state?.healthy ? 'Active world' : 'Configured world';

  $('world-current').textContent = state?.configured || 'Not available';

  $('world-free').textContent = bytes(state?.free_bytes);

  $('worlds-status').textContent = !state ? 'Loading worlds…' : state.detail + (!state.editable ? ' Enable web-managed configuration to create or switch worlds here.' : state.busy ? ' Wait for the current operation to finish.' : '');

  $('worlds-warnings').replaceChildren(...(state?.warnings || []).map(message => node('p', message, 'notice')));

  $('worlds-refresh').disabled = worldsBusy || worldSubmitting;

  $('world-new').disabled = !editable;
  $('journey-defaults').hidden = !(state?.worlds || []).some(world => world.metadata?.available && world.metadata.difficulty === 'Journey');
  $('world-create-form').querySelectorAll('input, select, button:not(#world-create-cancel)').forEach(input => { input.disabled = !editable; });

  $('world-apply').disabled = !editable || !state?.pending;

  $('world-draft').textContent = state?.pending ? 'Saved draft selects ' + (state.staged_name || '(unknown)') + '. Review all pending changes before applying.' : 'No saved changes waiting to apply.';

  const filter = $('worlds-filter').value.toLocaleLowerCase();

  const rows = (state?.worlds || []).filter(world => world.name.toLocaleLowerCase().includes(filter)).flatMap((world, index) => {

    const row = node('tr'), name = node('td');
    const detailRow = node('tr'), detailCell = node('td');
    detailCell.colSpan = 4; detailCell.append(worldDetails(world)); detailRow.append(detailCell);
    detailRow.id = 'world-details-' + index; detailRow.hidden = !expandedWorlds.has(world.name);
    const expand = node('button', (detailRow.hidden ? '▸ ' : '▾ ') + world.name, 'world-expand');
    expand.setAttribute('aria-label', 'Details for ' + world.name);
    expand.setAttribute('aria-expanded', String(!detailRow.hidden));
    expand.setAttribute('aria-controls', detailRow.id);
    expand.onclick = () => {
      detailRow.hidden = !detailRow.hidden;
      if (detailRow.hidden) expandedWorlds.delete(world.name); else expandedWorlds.add(world.name);
      expand.textContent = (detailRow.hidden ? '▸ ' : '▾ ') + world.name;
      expand.setAttribute('aria-expanded', String(!detailRow.hidden));
    };
    name.append(expand, node('p', world.has_mod_data ? '.wld + .twld' : '.wld only · no mod sidecar', 'muted'));

    row.append(name, node('td', bytes(world.bytes + world.mod_bytes)), node('td', new Date(world.modified).toLocaleString()));

    const cell = node('td');

    if (world.selected) cell.append(node('span', state.healthy ? 'Active' : 'Configured', 'badge'));

    if (!world.selected) {
      const select = node('button', 'Switch'); select.disabled = !editable || !world.can_select;
      select.setAttribute('aria-label', 'Switch to ' + world.name);
      select.onclick = action(() => stageWorld({action: 'switch', name: world.name})); cell.append(select);
    }
    if (world.metadata?.available && world.metadata.difficulty === 'Journey') {
    const journey = node('button', 'Set Journey permissions', 'world-journey');
    journey.setAttribute('aria-label', 'Set Journey permissions for ' + world.name);
    journey.onclick = action(() => openJourney(world.name)); cell.append(journey);
    }
    row.append(cell); return [row, detailRow];

  });

  if (!rows.length) { const row = node('tr'), cell = node('td', state?.worlds?.length ? 'No worlds match your filter.' : 'No saved worlds found.'); cell.colSpan = 4; row.append(cell); rows.push(row); }

  $('worlds-list').replaceChildren(...rows);

}

function refreshWouldInterrupt(id) {
  const root = $(id), selection = window.getSelection();
  return root.contains(document.activeElement) ||
    (selection && !selection.isCollapsed && (root.contains(selection.anchorNode) || root.contains(selection.focusNode))) ||
    [...root.querySelectorAll('[data-saved-name]')].some(input => input.value !== input.dataset.savedName);
}

async function refreshWorlds(background = false) {

  background = background === true;


  if (!token || $('worlds').hidden || worldsBusy || worldSubmitting) return;

  worldsBusy = true;
  if (!background) renderWorlds();

  try { worldState = await api('/api/worlds'); }

  catch (error) { worldState = {editable: false, worlds: [], warnings: [], detail: 'World inventory unavailable: ' + error.message}; }

  finally { worldsBusy = false; if (!background || !refreshWouldInterrupt('worlds')) renderWorlds(); else updateWorldUptimes(); }

}

async function stageWorld(values) {

  if (worldSubmitting || !worldState?.editable) return;

  worldSubmitting = true; renderWorlds();

  try {

    await api('/api/worlds/stage', {...values, revision: worldState.revision});
    if (values.action === 'create') $('world-create-dialog').close();

    await loadSettings();

    tell('World selection saved as a draft. Review all changes before confirming the restart.');

  } finally { worldSubmitting = false; await refreshWorlds(); }

  await $('apply').onclick();

  await refreshWorlds();

}

let journeyState = null, journeySaving = false;

function renderJourneyInputs() {
  const useOverride = journeyState.name === null || $('journey-override').checked;
  for (const input of $('journey-fields').querySelectorAll('select')) {
    input.disabled = !journeyState.editable || !useOverride || journeySaving;
    if (!useOverride) input.value = journeyState.defaults[input.name];
  }
  $('journey-save').disabled = !journeyState.editable || journeySaving;
  $('journey-apply').disabled = !journeyState.editable || journeySaving;
  $('journey-override').disabled = !journeyState.editable || journeySaving;
  $('journey-close').disabled = journeySaving;
}

async function openJourney(name = null) {
  journeyState = await api('/api/worlds/journey' + (name === null ? '' : '?name=' + encodeURIComponent(name)));
  $('journey-title').textContent = name === null ? 'Server Journey defaults' : 'Journey permissions · ' + name;
  const world = worldState?.worlds?.find(world => world.name === name);
  const nonJourney = world?.metadata?.available && world.metadata.difficulty !== 'Journey';
  $('journey-description').textContent = (nonJourney ? 'This is a ' + world.metadata.difficulty + ' world. Journey permissions have no effect on it and do not change its difficulty. ' : '') +
    (name === null ? 'Defaults apply to Journey worlds without an override. ' : 'Inherit the server defaults, or customize permissions for this world. ') +
    'Saved permissions take effect the next time the world starts. Review & apply restarts the game after confirmation.';
  $('journey-override-label').hidden = name === null;
  $('journey-override').checked = journeyState.override;
  $('journey-fields').replaceChildren(...Object.entries(journeyState.permissions).map(([key, value]) => {
    const label = node('label', config?.fields?.[key]?.label || key.replace('TMOD_JOURNEY_', '').replaceAll('_', ' '));
    const input = node('select'); input.name = key;
    ['Locked', 'Host only', 'Everyone'].forEach((title, index) => { const option = node('option', title); option.value = String(index); input.append(option); });
    input.value = value; label.append(input);
    const running = journeyState.running[key];
    if (running !== undefined && (name === null || name === journeyState.running_world)) label.append(node('small', 'Running: ' + ['Locked', 'Host only', 'Everyone'][Number(running)], 'muted'));
    return label;
  }));
  $('journey-status').textContent = journeyState.editable ? (name === null ? 'Editing server defaults.' : journeyState.override ? 'Using a world override.' : 'Using server defaults.') : 'Environment-managed permissions are read-only.';
  renderJourneyInputs(); $('journey-dialog').showModal();
}

async function saveJourney(apply) {
  if (journeySaving) return;
  journeySaving = true;
  const permissions = Object.fromEntries([...$('journey-fields').querySelectorAll('select')].map(input => [input.name, input.value]));
  renderJourneyInputs(); $('journey-status').textContent = 'Saving permissions…';
  try {
    journeyState = await api('/api/worlds/journey', {name: journeyState.name, override: $('journey-override').checked, permissions, revision: journeyState.revision, settings_revision: journeyState.settings_revision});
    $('journey-status').textContent = 'Saved. The running game has not changed. Permissions take effect when the world next starts.';
    if (apply) {
      if (journeyState.name !== null) await api('/api/worlds/stage', {action: 'switch', name: journeyState.name, revision: journeyState.settings_revision});
      $('journey-dialog').close();
      await loadSettings(); await refreshWorlds(); await $('apply').onclick();
    } else {
      attentionSettings = await api('/api/settings'); renderAttention();
      await refreshWorlds();
    }
  } catch (error) { $('journey-status').textContent = error.message; if (!$('journey-dialog').open) tell(error.message); }
  finally { journeySaving = false; renderJourneyInputs(); }
}

$('journey-defaults').onclick = action(() => openJourney());
$('journey-override').onchange = () => { renderJourneyInputs(); $('journey-status').textContent = 'Unsaved changes.'; };
$('journey-fields').onchange = () => { $('journey-status').textContent = 'Unsaved changes.'; };
$('journey-close').onclick = () => $('journey-dialog').close();
$('journey-dialog').addEventListener('cancel', event => { if (journeySaving) event.preventDefault(); });
$('journey-form').onsubmit = event => { event.preventDefault(); saveJourney(false); };
$('journey-apply').onclick = () => saveJourney(true);

$('worlds-filter').oninput = renderWorlds;

$('worlds-refresh').onclick = action(refreshWorlds);

$('world-apply').onclick = action(async () => { await loadSettings(); await $('apply').onclick(); await refreshWorlds(); });

$('world-new').onclick = () => {
  for (const [id, key] of [['world-create-size', 'TMOD_WORLDSIZE'], ['world-create-difficulty', 'TMOD_DIFFICULTY'], ['world-create-evil', 'TMOD_WORLDEVIL']]) {
    if (!$(id).dataset.initialized) { $(id).value = config?.staged?.[key] || $(id).value; $(id).dataset.initialized = 'true'; }
  }
  $('world-create-error').textContent = '';
  $('world-create-dialog').showModal(); $('world-create-name').focus();
};
$('world-create-cancel').onclick = () => $('world-create-dialog').close();
$('world-create-form').onsubmit = async event => {
  event.preventDefault(); $('world-create-error').textContent = '';
  try { await stageWorld({action: 'create', name: $('world-create-name').value, creation: {TMOD_WORLDSIZE: $('world-create-size').value, TMOD_DIFFICULTY: $('world-create-difficulty').value, TMOD_WORLDEVIL: $('world-create-evil').value, TMOD_WORLDSEED: $('world-create-seed').value}}); }
  catch (error) { if ($('world-create-dialog').open) $('world-create-error').textContent = error.message; else tell(error.message); }
};

document.querySelectorAll('[data-view="worlds"]').forEach(button => button.addEventListener('click', () => setTimeout(refreshWorlds, 0)));

setInterval(() => { if (!document.hidden) refreshWorlds(true); }, 10000);

let playerState = null, playersBusy = false, playerActionBusy = false;

function renderPlayers() {

  const state = playerState;

  const ready = state?.available && !playerActionBusy && !playersBusy;

  $('players-count').textContent = state?.available ? String(state.players.length) : 'Unknown';

  $('players-updated').textContent = state?.updated ? new Date(state.updated).toLocaleTimeString() : 'Unavailable';

  $('players-status').textContent = state?.detail || 'Querying the game…';

  $('players-announce').disabled = !ready;

  $('players-refresh').disabled = playersBusy || playerActionBusy;

  const filter = $('players-filter').value.toLocaleLowerCase();

  const players = state?.available ? state.players.filter(player => player.name.toLocaleLowerCase().includes(filter)) : [];

  const rows = players.map(player => {

    const row = node('tr'); row.append(node('td', player.name), node('td', player.address));

    const cell = node('td'), buttons = node('div', undefined, 'button-row');

    for (const kind of ['kick', 'ban']) {

      const button = node('button', kind === 'kick' ? 'Kick' : 'Ban');

      button.disabled = !ready || !player.can_moderate || (kind === 'ban' && !state.can_ban);

      button.setAttribute('aria-label', (kind === 'kick' ? 'Kick ' : 'Ban ') + player.name);

      button.onclick = action(async () => {

        const title = (kind === 'kick' ? 'Kick ' : 'Ban ') + player.name + '?';

        const explanation = kind === 'kick' ? 'Disconnect this player. They can reconnect afterward.' : 'Disconnect this player and persistently ban ' + player.identifier + '. An IP ban also blocks others sharing that address. Removing a ban currently requires editing the server ban list.';

        if (await confirmAction(title, explanation, 'Player: ' + player.name + '\nConnection: ' + player.address)) await playerAction('/api/players/moderate', {action: kind, key: player.key, confirm: true});

      });

      buttons.append(button);

    }

    cell.append(buttons);

    if (!player.can_moderate) cell.append(node('small', 'Ambiguous name; controls unavailable.', 'muted'));

    row.append(cell); return row;

  });

  if (!rows.length) { const row = node('tr'), cell = node('td', !state?.available ? 'Player list unavailable. Refresh when the game is ready.' : state.players.length ? 'No players match your filter.' : 'No players connected.'); cell.colSpan = 3; row.append(cell); rows.push(row); }

  $('players-list').replaceChildren(...rows);

  $('players-activity').replaceChildren(...(state?.activity?.length ? state.activity.map(item => { const entry = node('li'); entry.append(node('strong', item.action + ' · ' + item.target), node('p', item.detail), node('small', new Date(item.time).toLocaleString(), 'muted')); return entry; }) : [node('li', 'No player-management actions recorded yet.')]));

}

async function refreshPlayers(background = false) {

  background = background === true;
  if (background && refreshWouldInterrupt('players')) return;

  if (!token || $('players').hidden || playersBusy || playerActionBusy) return;

  playersBusy = true;
  if (!background) renderPlayers();

  try { playerState = await api('/api/players'); }

  catch (error) { playerState = {available: false, players: [], detail: 'Player query failed: ' + error.message, activity: playerState?.activity || []}; }

  finally { playersBusy = false; if (!background || !refreshWouldInterrupt('players')) renderPlayers(); }

}

async function playerAction(path, body) {

  if (playerActionBusy) return;

  playerActionBusy = true; renderPlayers();

  try { const result = await api(path, body); tell(result.detail); if (path.endsWith('/announce')) $('players-announcement').value = ''; }

  catch (error) { tell(error.message + ' Refresh the list and inspect activity before retrying.'); }

  finally { playerActionBusy = false; await refreshPlayers(); }

}

$('players-refresh').onclick = action(refreshPlayers);

$('players-filter').oninput = renderPlayers;

$('players-announce-form').onsubmit = action(async () => {

  const message = $('players-announcement').value;

  if (!message.trim() || /[\r\n\x00-\x1f\x7f]/.test(message)) throw new Error('Enter one line of announcement text without control characters.');

  if (await confirmAction('Send this announcement?', 'Broadcast this message to every connected player.', message)) await playerAction('/api/players/announce', {message, confirm: true});

});

document.querySelectorAll('[data-view="players"]').forEach(button => button.addEventListener('click', () => setTimeout(refreshPlayers, 0)));

setInterval(() => { if (!document.hidden) refreshPlayers(true); }, 10000);

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

function savedDifferences(snapshot) {
  return snapshot.changes || Object.entries(snapshot.staged).filter(([key, value]) => value !== snapshot.running[key]).map(([key, value]) => ({key, label: snapshot.fields?.[key]?.label || key, running: snapshot.running[key], staged: value}));
}

function settingValue(value) { return value == null ? '(not set)' : value === '' ? '(empty)' : String(value); }
let reviewedSettings = null;
async function reviewSavedChanges() {
  reviewedSettings = await api('/api/settings');
  attentionSettings = reviewedSettings; renderAttention();
  const differences = savedDifferences(reviewedSettings);
  $('saved-changes-summary').textContent = differences.length ? differences.length + (differences.length === 1 ? ' saved setting differs' : ' saved settings differ') + ' from the running server. These differences are what trigger the reminder.' : reviewedSettings.draft_exists ? 'A saved draft file exists, but it matches the running settings. No changes need to be applied.' : 'No saved changes need to be applied.';
  $('saved-changes-list').replaceChildren(...differences.map(change => {
    const row = node('tr'), label = node('td'); label.append(node('strong', change.label), node('small', change.key));
    row.append(label, node('td', settingValue(change.running)), node('td', settingValue(change.staged))); return row;
  }));
  $('saved-changes-apply').disabled = !differences.length || reviewedSettings.mode !== 'web' || attentionStatus?.job?.state === 'running' || attentionStatus?.backups?.operation?.state === 'running';
  $('saved-changes-dialog').showModal();
}
$('saved-changes-close').onclick = () => $('saved-changes-dialog').close();
$('saved-changes-apply').onclick = action(async () => { $('saved-changes-dialog').close(); await applySavedSettings(reviewedSettings); });
$('workshop-apply').onclick = $('apply').onclick = action(async () => applySavedSettings(await api('/api/settings')));

async function applySavedSettings(snapshot) {

  const differences = savedDifferences(snapshot).map(change => change.label + ' (' + change.key + '): ' + settingValue(change.running) + ' → ' + settingValue(change.staged)).join('\n');

  if (!(await confirmAction('Apply settings and restart?', 'This applies the saved draft, not unsaved form edits. Players will disconnect. Mod changes may take time to download. A failed mod update leaves the game stopped for recovery.', differences || 'Reapply the saved settings.'))) return;

  applySubmitting = true;

  showApplyProgress({kind: 'apply', state: 'running', stage: 'queued', started: new Date().toISOString(), detail: 'Submitting the reviewed settings. Controls are locked until the operation finishes.'});

  try { showApplyProgress(await api('/api/apply', {confirm: true, revision: snapshot.revision})); }

  catch (error) { progressError(error); }

  finally { applySubmitting = false; }

  try { await refresh(); } catch (error) { progressError(error); }

}

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



let profileState = null, profileBusy = false;

function renderProfiles() {

  const state = profileState, locked = profileBusy || !state || state.busy;

  $('profiles-status').textContent = !state ? 'Loading profiles…' : state.busy ? 'A server operation is in progress.' : state.editable ? 'Loading a profile stages its selection. Review all draft changes before restarting.' : 'You can save profiles. Enable web-managed settings to load them.';

  $('profiles-running').textContent = 'Running selection: ' + (state?.running || '(no Workshop entries)');

  $('profiles-staged').textContent = 'Saved draft: ' + (state?.staged || '(no Workshop entries)');

  $('profile-save').disabled = locked;

  $('profiles-refresh').disabled = profileBusy;

  $('profiles-apply').disabled = locked || !state.editable || !state.pending;

  $('profiles-list').replaceChildren(...(state?.profiles || []).map(profile => {

    const card = node('article', undefined, 'panel'), name = node('input');

    name.value = profile.name; name.dataset.savedName = profile.name; name.maxLength = 64; name.setAttribute('aria-label', 'Name for ' + profile.name);

    card.append(node('h3', profile.name), node('p', (profile.mods ? profile.mods.split(',').length : 0) + ' Workshop entries'), node('p', profile.mods || 'Unmodded · no Workshop entries', 'profile-entries'));

    if (profile.mods === state.running) card.append(node('p', 'Matches running selection', 'badge'));

    if (profile.mods === state.staged) card.append(node('p', 'Matches saved draft', 'muted'));

    card.append(name);

    const buttons = node('div', undefined, 'button-row');

    for (const [kind, label] of [['stage', 'Load profile'], ['save', 'Replace from selection'], ['rename', 'Rename'], ['delete', 'Delete']]) {

      const button = node('button', label); button.disabled = locked || (kind === 'stage' && !state.editable);

      button.onclick = action(async () => {

        if (kind === 'delete' && !await confirmAction('Delete ' + profile.name + '?', 'This removes the saved profile. Your running selection and downloaded mods stay available.')) return;

        if (kind === 'save' && !await confirmAction('Replace ' + profile.name + '?', 'Replace this profile using the selection chosen in the save form.', state[$('profile-source').value] || '(no Workshop entries)')) return;

        await changeProfile({action: kind, id: profile.id, name: kind === 'rename' ? name.value : profile.name, source: $('profile-source').value, confirm: true});

        if (kind === 'stage') { await loadSettings(); await $('apply').onclick(); await refreshProfiles(); }

      }); buttons.append(button);

    }

    card.append(buttons); return card;

  }));

  if (state && !state.profiles.length) $('profiles-list').append(node('p', 'No profiles yet. Save a selection above to create your first profile.', 'muted'));

}

async function refreshProfiles(background = false) {

  background = background === true;
  if (background && refreshWouldInterrupt('profiles')) return;

  if (!token || $('profiles').hidden || profileBusy) return;

  profileBusy = true;
  if (!background) renderProfiles();

  try { profileState = await api('/api/profiles'); }

  catch (error) { tell('Profiles unavailable: ' + error.message); profileState = null; }

  finally { profileBusy = false; if (!background || !refreshWouldInterrupt('profiles')) renderProfiles(); }

}

async function changeProfile(values) {

  if (profileBusy || !profileState) return;

  profileBusy = true; renderProfiles();

  try {

    profileState = await api('/api/profiles', {...values, revision: profileState.revision, catalog_revision: profileState.catalog_revision});

    tell(values.action === 'stage' ? 'Profile loaded into the saved draft.' : 'Profiles updated.');

  } finally { profileBusy = false; renderProfiles(); }

}

$('profile-save-form').onsubmit = action(async () => { await changeProfile({action: 'save', name: $('profile-name').value, source: $('profile-source').value}); $('profile-name').value = ''; });

$('profiles-refresh').onclick = action(refreshProfiles);

$('profiles-apply').onclick = action(async () => { await loadSettings(); await $('apply').onclick(); });

document.querySelectorAll('[data-view="profiles"]').forEach(button => button.addEventListener('click', () => setTimeout(refreshProfiles, 0)));

setInterval(() => { if (!document.hidden) refreshProfiles(true); }, 10000);

let playthroughState = null, playthroughBusy = false;

function renderPlaythroughs() {

  const state = playthroughState, locked = playthroughBusy || !state || state.busy;

  $('playthroughs-status').textContent = !state ? 'Loading playthroughs…' : state.busy ? 'A server operation is in progress.' : state.editable ? 'Loading a playthrough stages its selection. Review all draft changes before restarting.' : 'You can save playthroughs. Enable web-managed settings to load them.';

  $('playthroughs-running').textContent = 'Running selection: ' + (state?.running?.TMOD_WORLDNAME || '(unavailable)');

  $('playthroughs-staged').textContent = 'Saved draft: ' + (state?.staged?.TMOD_WORLDNAME || '(unavailable)');

  $('playthrough-save').disabled = locked;

  $('playthroughs-refresh').disabled = playthroughBusy;

  $('playthroughs-apply').disabled = locked || !state.editable || !state.pending;

  const worldSelect = $('playthrough-world'), previousWorld = worldSelect.value;
  worldSelect.replaceChildren(...(state?.worlds || []).filter(world => world.can_select).map(world => { const option = node('option', world.name); option.value = world.name; return option; }));
  worldSelect.value = previousWorld || state?.staged?.TMOD_WORLDNAME || worldSelect.options[0]?.value || '';
  $('playthrough-save').disabled = locked || !worldSelect.value;
  $('playthroughs-list').replaceChildren(...(state?.playthroughs || []).map(playthrough => {

    const card = node('article', undefined, 'panel'), name = node('input');

    name.value = playthrough.name; name.dataset.savedName = playthrough.name; name.maxLength = 64; name.setAttribute('aria-label', 'Name for ' + playthrough.name);

    card.append(node('h3', playthrough.name), node('p', 'World: ' + playthrough.settings.TMOD_WORLDNAME), node('p', 'Mods: ' + (playthrough.settings.TMOD_MODS || '(unmodded)'), 'playthrough-entries'));
    const journeyWorld = state.worlds?.some(world => world.name === playthrough.settings.TMOD_WORLDNAME && world.metadata?.difficulty === 'Journey');
    const details = node('details'), summary = node('summary', journeyWorld ? 'Saved world and Journey settings' : 'Saved world settings'); details.append(summary);
    for (const [key, value] of Object.entries(playthrough.settings).filter(([key]) => key !== 'TMOD_MODS' && key !== 'TMOD_WORLDNAME' && (journeyWorld || !key.startsWith('TMOD_JOURNEY_')))) details.append(node('p', (config?.fields?.[key]?.label || key.replace('TMOD_', '').replaceAll('_', ' ')) + ': ' + (key.startsWith('TMOD_JOURNEY_') ? ['Locked', 'Host only', 'Everyone'][Number(value)] : value)));
    card.append(details);

    if (JSON.stringify(playthrough.settings) === JSON.stringify(state.running)) card.append(node('p', 'Matches running selection', 'badge'));

    if (JSON.stringify(playthrough.settings) === JSON.stringify(state.staged)) card.append(node('p', 'Matches saved draft', 'muted'));

    card.append(name);

    const buttons = node('div', undefined, 'button-row');

    for (const [kind, label] of [['stage', 'Load playthrough'], ['save', 'Replace from selection'], ['rename', 'Rename'], ['delete', 'Delete']]) {

      const button = node('button', label); button.disabled = locked || (kind === 'stage' && !state.editable);

      button.onclick = action(async () => {

        if (kind === 'delete' && !await confirmAction('Delete ' + playthrough.name + '?', 'This removes the saved playthrough. Your running selection and downloaded mods stay available.')) return;

        if (kind === 'save' && !await confirmAction('Replace ' + playthrough.name + '?', 'Replace this playthrough using the selection chosen in the save form.', JSON.stringify(state[$('playthrough-source').value], null, 2))) return;

        await changePlaythrough({revision: state.revision, catalog_revision: state.catalog_revision, action: kind, id: playthrough.id, name: kind === 'rename' ? name.value : playthrough.name, source: $('playthrough-source').value, world: $('playthrough-world').value, confirm: true});

        if (kind === 'stage') { await loadSettings(); await $('apply').onclick(); await refreshPlaythroughs(); }

      }); buttons.append(button);

    }

    card.append(buttons); return card;

  }));

  if (state && !state.playthroughs.length) $('playthroughs-list').append(node('p', 'No playthroughs yet. Save a selection above to create your first playthrough.', 'muted'));

}

async function refreshPlaythroughs(background = false) {

  background = background === true;
  if (background && refreshWouldInterrupt('playthroughs')) return;

  if (!token || $('playthroughs').hidden || playthroughBusy) return;

  playthroughBusy = true;
  if (!background) renderPlaythroughs();

  try { playthroughState = await api('/api/playthroughs'); }

  catch (error) { tell('Playthroughs unavailable: ' + error.message); playthroughState = null; }

  finally { playthroughBusy = false; if (!background || !refreshWouldInterrupt('playthroughs')) renderPlaythroughs(); }

}

async function changePlaythrough(values) {

  if (playthroughBusy || !playthroughState) return;

  playthroughBusy = true; renderPlaythroughs();

  try {

    playthroughState = await api('/api/playthroughs', {revision: playthroughState.revision, catalog_revision: playthroughState.catalog_revision, ...values});

    tell(values.action === 'stage' ? 'Playthrough loaded into the saved draft.' : 'Playthroughs updated.');

  } finally { playthroughBusy = false; renderPlaythroughs(); }

}

$('playthrough-save-form').onsubmit = action(async () => { await changePlaythrough({action: 'save', name: $('playthrough-name').value, source: $('playthrough-source').value, world: $('playthrough-world').value}); $('playthrough-name').value = ''; });

$('playthroughs-refresh').onclick = action(refreshPlaythroughs);

$('playthroughs-apply').onclick = action(async () => { await loadSettings(); await $('apply').onclick(); });

document.querySelectorAll('[data-view="playthroughs"]').forEach(button => button.addEventListener('click', () => setTimeout(refreshPlaythroughs, 0)));

setInterval(() => { if (!document.hidden) refreshPlaythroughs(true); }, 10000);

let overviewBusy = false;
async function refreshOverview() {
  if (!token || $('overview').hidden || overviewBusy) return;
  overviewBusy = true;
  try {
    const paths = ['/api/worlds', '/api/players', '/api/settings', '/api/playthroughs', '/api/profiles'];
    const results = await Promise.allSettled(paths.map(path => api(path)));
    const [world, players, settings, playthroughs, profiles] = results.map(result => result.status === 'fulfilled' ? result.value : null);
    $('overview-world').textContent = world?.configured ? (world.healthy ? 'Active: ' : 'Configured: ') + world.configured : 'World information unavailable or custom configuration in use.';
    $('overview-world-storage').textContent = world?.worlds ? world.worlds.length + ' saved worlds · ' + bytes(world.free_bytes) + ' free data storage' : 'World storage unavailable.';
    $('overview-world-warnings').textContent = (world?.warnings || []).join(' ');
    $('overview-player-status').textContent = players?.available ? players.players.length + ' online · queried ' + new Date(players.updated).toLocaleTimeString() : players?.detail || 'Player information unavailable.';
    $('overview-players').replaceChildren(...(players?.available ? players.players.map(player => node('li', player.name)) : []));
    if (players?.available && !players.players.length) $('overview-players').append(node('li', 'No players connected.'));
    $('overview-player-activity').replaceChildren(...(players?.activity || []).slice(0, 5).map(item => node('li', [item.action, item.target, item.detail].filter(Boolean).join(' · '))));
    if (!$('overview-player-activity').children.length) $('overview-player-activity').append(node('li', players ? 'No dashboard actions recorded.' : 'Activity unavailable.'));
    $('overview-settings').classList.toggle('pending-highlight', !!settings?.pending);
    $('overview-settings').textContent = settings?.mode ? (settings.mode === 'web' ? 'Web-managed settings' : 'Compose-managed settings') + (settings.pending ? ' · Saved changes are waiting to be applied.' : ' · No saved draft changes.') : 'Settings unavailable.';
    $('overview-journey-section').hidden = !world?.worlds?.some(item => item.selected && item.metadata?.available && item.metadata.difficulty === 'Journey');
    $('overview-journey').replaceChildren(...Object.entries(settings?.running || {}).filter(([key]) => key.startsWith('TMOD_JOURNEY_')).flatMap(([key, value]) => [node('dt', settings.fields?.[key]?.label || key.replace('TMOD_JOURNEY_', '').replaceAll('_', ' ')), node('dd', ['Locked', 'Host only', 'Everyone'][Number(value)] || value)]));
    if (!$('overview-journey').children.length) $('overview-journey').append(node('dd', 'Journey permissions unavailable.'));
    const matches = (values, current) => Object.entries(values).every(([key, value]) => current?.[key] === value);
    const matching = (playthroughs?.playthroughs || []).filter(item => matches(item.settings, playthroughs.running)).map(item => item.name);
    $('overview-playthroughs').textContent = playthroughs?.playthroughs ? playthroughs.playthroughs.length + ' saved playthroughs · Matches running settings: ' + (matching.join(', ') || 'None') : 'Playthroughs unavailable.';
    const matchingMods = (profiles?.profiles || []).filter(item => item.mods === profiles.running).map(item => item.name);
    $('overview-profiles').textContent = profiles?.profiles ? profiles.profiles.length + ' mod profiles · Matches running selection: ' + (matchingMods.join(', ') || 'None') : 'Mod profiles unavailable.';
  } finally { overviewBusy = false; }
}
$('recovery-refresh').onclick = action(refresh);
document.querySelectorAll('[data-view="overview"]').forEach(button => button.addEventListener('click', () => setTimeout(() => refresh().catch(error => tell(error.message)), 0)));

function renderAttention() {
  const rows = [], status = attentionStatus, recovery = attentionRecovery;
  const busy = status?.job?.state === 'running' || status?.backups?.operation?.state === 'running';
  const add = (title, detail, view, label, onClick) => {
    const row = node('div', undefined, 'attention-item'), copy = node('div');
    copy.append(node('strong', title), node('p', detail));
    const button = node('button', label); button.type = 'button';
    button.onclick = onClick || (() => document.querySelector('nav [data-view="' + view + '"]').click());
    row.append(copy, button); rows.push(row);
  };
  const unsavedCount = $('fields').querySelectorAll('.setting-unsaved').length;
  if (unsavedCount) add('Unsaved settings', unsavedCount + ' setting' + (unsavedCount === 1 ? ' has' : 's have') + ' been edited. Save the draft to keep these changes.', 'settings', 'Review unsaved settings');
  if (recovery?.interrupted) add('Recovery requires attention', 'An interrupted restore needs manual recovery. Read the recovery guidance before restarting.', 'recovery', 'View recovery');
  if (attentionSettings?.pending) add('Saved changes are waiting', busy ? 'A server operation is in progress. Review the saved draft after it finishes.' : 'Review and apply your saved draft when you are ready to restart the game.', 'settings', 'Review saved changes', action(reviewSavedChanges));
  if (!recovery?.interrupted && status?.job?.state === 'failed') add('The last operation failed', status.job.detail || 'Review the result and recovery options.', 'recovery', 'View operation');
  for (const warning of status?.backups?.warnings || []) add('Backup warning', warning, 'recovery', 'View backups');
  if (!attentionSettings && status) add('Settings status unavailable', 'Saved changes could not be checked. Refresh status before deciding whether to apply changes.', 'settings', 'View configuration');
  const signature = rows.map(row => row.textContent).join('|');
  if ($('attention-items').dataset.signature !== signature) {
    $('attention-items').replaceChildren(...rows); $('attention-items').dataset.signature = signature;
  }
  $('attention-banner').hidden = !rows.length;
}
