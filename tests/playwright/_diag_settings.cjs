const { chromium } = require('playwright');
const CHROME = 'browsers/chrome/linux-150.0.7871.46/chrome-linux64/chrome';
const BASE = 'http://127.0.0.1:8027';
const DB = 'pet_spot_elsahel';

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 1000 } });
  const page = await ctx.newPage();
  try {
    const authResp = await ctx.request.post(`${BASE}/web/session/authenticate`, {
      data: { jsonrpc: '2.0', params: { db: DB, login: 'admin', password: 'admin' } },
    });
    const authJson = await authResp.json();
    console.log('auth uid:', authJson && authJson.result && authJson.result.uid);

    await page.goto(`${BASE}/odoo/settings`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(4000);
    console.log('settings url:', page.url());

    // capture selected tab
    const active = await page.evaluate(() => {
      const sel = document.querySelector('.settings_tab .selected, .settings_tab .o_setting_search + * , .settings_tab li.selected, .settings_tab .list-group-item.selected');
      const blocks = [...document.querySelectorAll('.app_settings_block')].map(b => b.getAttribute('data-key') || b.getAttribute('string'));
      const tabs = [...document.querySelectorAll('.settings_tab .list-group-item, .settings_tab .tab')].map(t => (t.textContent||'').trim()).slice(0,8);
      const visibleBlock = document.querySelector('.app_settings_block');
      return {
        selectedText: sel ? sel.textContent.trim() : null,
        firstVisibleBlockKey: visibleBlock ? (visibleBlock.getAttribute('data-key')||visibleBlock.getAttribute('string')) : null,
        firstTabs: tabs,
        title: document.title,
      };
    });
    console.log('ACTIVE:', JSON.stringify(active, null, 1));
    await page.screenshot({ path: '/tmp/settings_main.png', fullPage: false });
    console.log('screenshot saved /tmp/settings_main.png');
  } catch (e) {
    console.log('ERROR:', e.message);
    await page.screenshot({ path: '/tmp/settings_err.png' }).catch(()=>{});
  } finally {
    await browser.close();
  }
})();
