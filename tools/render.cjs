// Покадровый экспорт index.html в PNG 1920×1080, 30 к/с.
// Запуск: node tools/render.cjs; параллельно — K=0..N-1 N=4; выборочно — ONLY=0,3
// Готовые кадры пропускаются, поэтому прерванный рендер можно докатить тем же запуском.
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..');
const NAMES = ['01_zastavka_kanala', '02_verdikt', '03_gadzhetoteka', '04_otbivka'];
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 }); p.setDefaultTimeout(300000);
  p.on('pageerror', e => console.log('PAGEERR', e.message));
  await p.goto('file://' + path.join(ROOT, 'index.html'));
  await p.addStyleTag({ content: '#stage{position:fixed!important;left:0;top:0;width:1920px!important;height:1080px!important;z-index:999;border:0!important}' });
  await p.waitForFunction(() => window.__etv, null, { timeout: 120000 });
  await p.waitForTimeout(500);
  const K = +(process.env.K || 0), N = +(process.env.N || 1);
  for (const i of (process.env.ONLY ? process.env.ONLY.split(',').map(Number) : [0, 1, 2, 3])) {
    const dir = path.join(ROOT, 'frames', NAMES[i]); fs.mkdirSync(dir, { recursive: true });
    const n = Math.round((await p.evaluate(i => window.__etv.durs[i], i)) * 30);
    for (let f = K; f < n; f += N) {
      const out = path.join(dir, String(f).padStart(4, '0') + '.png');
      if (fs.existsSync(out) && fs.statSync(out).size > 100000) continue;
      await p.evaluate(([i, t]) => window.__etv.seek(i, t), [i, f / 30]);
      await p.screenshot({ path: out + '.tmp.png', clip: { x: 0, y: 0, width: 1920, height: 1080 } });
      fs.renameSync(out + '.tmp.png', out);
    }
    console.log('done', NAMES[i], 'worker', K);
  }
  await b.close();
})();
