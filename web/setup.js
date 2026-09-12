'use strict';
document.getElementById('setup-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = document.getElementById('setup-submit');
  const message = document.getElementById('setup-message');
  button.disabled = true;
  try {
    if (location.protocol !== 'https:' && !['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)) {
      throw new Error('Use HTTPS or a localhost SSH tunnel for setup.');
    }
    const response = await fetch('/api/setup', {
      method: 'POST', credentials: 'omit', cache: 'no-store',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code: document.getElementById('setup-code').value,
        token: document.getElementById('setup-token').value,
        confirm: document.getElementById('setup-confirm').value})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Setup failed.');
    document.getElementById('setup-form').reset();
    message.textContent = 'Token created. The game is starting. Opening sign-in…';
    location.replace('/');
  } catch (error) {
    message.textContent = error.message;
    button.disabled = false;
  }
});
