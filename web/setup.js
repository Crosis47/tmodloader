'use strict';
const form = document.getElementById('setup-form');
const code = document.getElementById('setup-code');
const token = document.getElementById('setup-token');
const confirm = document.getElementById('setup-confirm');
const button = document.getElementById('setup-submit');
const message = document.getElementById('setup-message');
let submitting = false;

function tokenError(value) {
  const errors = [];
  if (value.length < 8) errors.push(`Use at least 8 characters (${value.length}/8 entered).`);
  if (value.length > 256) errors.push(`Use no more than 256 characters (${value.length} entered).`);
  if (/[^\x00-\x7f]/.test(value)) errors.push('Use ASCII characters only; accented letters and emoji are not supported.');
  // Match Python str.isspace() for ASCII, including separator controls.
  if (/[\x09-\x0d\x1c-\x20]/.test(value)) errors.push('Remove spaces and other whitespace.');
  return errors.join(' ');
}

function feedback(input, text, state) {
  const help = document.getElementById(input.id + '-help');
  help.textContent = text;
  help.dataset.state = state;
  input.setAttribute('aria-invalid', String(state === 'invalid'));
}

function validate() {
  const codeReady = code.value.trim().length > 0;
  feedback(code, codeReady ? 'Code entered. It will be checked when you submit.' : 'Enter the one-time code from the current container logs.', 'neutral');
  const error = tokenError(token.value);
  feedback(token, error || '✓ Admin token meets all requirements.', error ? 'invalid' : 'valid');
  const matches = confirm.value.length > 0 && confirm.value === token.value;
  feedback(confirm, !confirm.value ? 'Enter the same admin token again.' :
    !matches ? 'The admin tokens do not match.' : error ? 'Tokens match. Fix the admin token requirements above.' : '✓ Admin tokens match.',
  matches && !error ? 'valid' : confirm.value ? 'invalid' : 'neutral');
  const ready = codeReady && !error && matches;
  button.disabled = submitting || !ready;
  return ready;
}

for (const input of [code, token, confirm]) {
  input.addEventListener('input', () => { message.textContent = ''; validate(); });
  input.addEventListener('change', validate);
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (submitting || !validate()) return;
  submitting = true;
  button.disabled = true;
  button.textContent = 'Creating token…';
  message.textContent = 'Checking the setup code and saving your admin token…';
  form.setAttribute('aria-busy', 'true');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch('/api/setup', {
      method: 'POST', credentials: 'omit', cache: 'no-store', signal: controller.signal,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code: code.value.trim(), token: token.value, confirm: confirm.value})
    });
    let result;
    try { result = await response.json(); }
    catch { throw new Error(`The server returned an unexpected response (${response.status}). Reload the page and check the container logs.`); }
    if (!response.ok) throw new Error(result.error || 'Setup failed.');
    form.reset();
    message.textContent = 'Token created. The game is starting. Opening sign-in…';
    location.replace('/');
  } catch (error) {
    message.textContent = error.name === 'AbortError' ?
      'The request timed out. Reload the page to check whether setup completed before trying again.' :
      error instanceof TypeError ? 'Cannot reach the server. Check your connection and reload the page.' : error.message;
  } finally {
    clearTimeout(timeout);
    submitting = false;
    button.textContent = 'Create token and start server';
    form.setAttribute('aria-busy', 'false');
    validate();
  }
});
validate();
