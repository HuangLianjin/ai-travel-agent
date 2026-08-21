const { chromium } = require('C:/Users/hlj/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path = require('path');
const fs = require('fs');

(async () => {
  const outDir = path.join(__dirname, '..', 'docs', 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });

  const userPage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await userPage.goto('http://127.0.0.1:8000/', { waitUntil: 'domcontentloaded' });
  await userPage.fill('input[placeholder="demo / admin"]', 'demo');
  await userPage.fill('input[placeholder="demo123 / admin123"]', 'demo123');
  await userPage.click('button.btn.primary.block');
  await userPage.waitForTimeout(2500);
  await userPage.screenshot({ path: path.join(outDir, 'plan.png'), fullPage: false });
  await userPage.click('button.nav-item:has-text("攻略广场")');
  await userPage.waitForTimeout(1500);
  await userPage.screenshot({ path: path.join(outDir, 'guides.png'), fullPage: false });
  await userPage.close();

  const adminPage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await adminPage.goto('http://127.0.0.1:8000/', { waitUntil: 'domcontentloaded' });
  await adminPage.fill('input[placeholder="demo / admin"]', 'admin');
  await adminPage.fill('input[placeholder="demo123 / admin123"]', 'admin123');
  await adminPage.click('button.btn.primary.block');
  await adminPage.waitForTimeout(2500);
  await adminPage.screenshot({ path: path.join(outDir, 'admin.png'), fullPage: false });
  await adminPage.close();

  await browser.close();
  console.log('screenshots saved to', outDir);
})().catch(e => { console.error(e); process.exit(1); });
