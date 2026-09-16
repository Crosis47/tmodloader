// Run against a disposable first-run server: SETUP_TEST_URL and SETUP_TEST_CODE.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.SETUP_TEST_BROWSER || undefined});
  try {
    const page = await browser.newPage({viewport: {width: 900, height: 1000}});
    await page.goto(process.env.SETUP_TEST_URL);
    const button = page.locator('#setup-submit');
    const code = page.locator('#setup-code');
    const token = page.locator('#setup-token');
    const confirm = page.locator('#setup-confirm');
    assert(await button.isDisabled());
    await code.fill('incorrect-code');
    for (const [value, text] of [['short', 'at least 8'], ['has space', 'whitespace'],
      ['nonasciié', 'ASCII'], ['x'.repeat(257), 'no more than 256']]) {
      await token.fill(value);
      await confirm.fill(value);
      assert(await button.isDisabled());
      assert((await page.locator('#setup-token-help').textContent()).includes(text));
    }
    await token.fill('Valid123');
    await confirm.fill('Mismatch');
    assert(await button.isDisabled());
    assert((await page.locator('#setup-confirm-help').textContent()).includes('do not match'));
    await confirm.fill('Valid123');
    assert(await button.isEnabled());
    assert.equal(await page.locator('#setup-token-help').getAttribute('data-state'), 'valid');
    await code.fill('');
    assert(await button.isDisabled());
    await code.fill('incorrect-code');
    await button.click();
    await page.waitForFunction(() => document.querySelector('#setup-message').textContent.includes('Invalid setup code'));
    assert(await button.isEnabled());
    await page.waitForTimeout(1100); // Server deliberately rate-limits setup attempts.
    await code.fill(process.env.SETUP_TEST_CODE);
    if (process.env.SETUP_TEST_SCREENSHOT) await page.screenshot({path: process.env.SETUP_TEST_SCREENSHOT});
    await button.click();
    await page.locator('#login-form').waitFor({timeout: 15000});
    console.log('Setup browser validation, incorrect-code error, and real provisioning passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
