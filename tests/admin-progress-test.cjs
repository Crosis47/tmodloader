// State-level tests with a minimal dialog stub; no browser automation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../web/app.js'), 'utf8');
const context = vm.createContext({assert, console});
vm.runInContext(`
function node(tag, text) { return {tag, textContent: text, dataset: {}, open: false,
  setAttribute() {}, append() {}, replaceChildren(...children) { this.children = children; },
  showModal() { this.open = true; }, close() { this.open = false; }}; }
const elements = {}; const $ = id => elements[id] ||= node(id);
const document = {body: node('body')};
const config = {mode: 'web', pending: true}; const token = 'test';
function setInterval() {};
`, context);
vm.runInContext(source.slice(source.indexOf("const applyDialog ="), source.indexOf('const historyControls =')), context);
vm.runInContext(source.slice(source.indexOf('function showApplyProgress('), source.indexOf('async function loadHistory(')), context);
vm.runInContext(`
const job = {kind:'apply', state:'running', stage:'mods', started:new Date().toISOString()};
showApplyProgress(job);
assert.equal(applyDialog.open, true); assert.equal(applyClose.disabled, true);
let cancelled = false; applyDialog.oncancel({preventDefault() { cancelled = true; }});
assert.equal(cancelled, true); applyClose.onclick(); assert.equal(applyDialog.open, true);
progressError(new Error('offline')); assert.equal(applyConnection.hidden, false);
assert.equal(applyProgress.dataset.running, 'true');
showApplyProgress({...job, state:'success', finished:new Date().toISOString()});
assert.equal(applyClose.disabled, false); assert.equal(applyConnection.hidden, true);
applyClose.onclick(); assert.equal(applyDialog.open, false);
showApplyProgress({...job, state:'success'}); assert.equal(applyDialog.open, false);
showApplyProgress({...job, started:'2026-09-10T00:00:00Z'}); assert.equal(applyDialog.open, true);
showApplyProgress({...job, state:'failed'}); assert.equal(applyClose.disabled, false);
applyClose.onclick();
showApplyProgress(job); assert.equal(applyDialog.open, true);
showApplyProgress({state:'idle'}); assert.equal(applyClose.disabled, false);
console.log('Apply modal state tests passed.');
`, context);
