// Выгрузка ролика для аниматика в Blender: геометрия без материалов (GLB) + покадровая анимация, камера, маркеры (JSON)
// Запуск из корня репозитория: node tools/animatic/export.cjs <номер ролика 0–3> <папка>
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const idx = +process.argv[2], out = process.argv[3];
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const p = await b.newPage({ viewport: { width: 640, height: 560 } }); p.setDefaultTimeout(1800000);
  p.on('pageerror', e => console.log('PAGEERR', e.message));
  p.on('console', m => { if (m.type() === 'error') console.log('CONSOLE', m.text()); });
  await p.goto('file://' + require('path').resolve(__dirname, '../../index.html'));
  await p.waitForFunction(() => window.__etv, null, { timeout: 600000 });
  const res = await p.evaluate(async i => {
    const T = window.__etv.THREE; window.__etv.seek(i, 0);
    const P = window.__etv.pieces[i], inst = P.inst, S = inst.S, N = Math.round(inst.dur * 30);
    const { GLTFExporter } = await import('three/addons/exporters/GLTFExporter.js');
    // свет и эффекты в аниматик не идут: спрайты, линии, аддитивные свечения, подсветки фона
    const targets = new Set(); S.scene.traverse(o => { if (o.isLight && o.target) targets.add(o.target); });
    const isFX = o => targets.has(o) || o.isSprite || o.isLine || o.isPoints || o.isLight || o.userData.noAO || (o.isMesh && !Array.isArray(o.material) && o.material.isMeshBasicMaterial && o.material.blending === T.AdditiveBlending);
    const used = new Map(), uname = base => { base = base.slice(0, 26); const n = (used.get(base) || 0) + 1; used.set(base, n); return n === 1 ? base : `${base} ${n}`; };
    const nodes = [], texts = [], drop = [];
    const walk = (o, inText) => {
      for (const c of [...o.children]) {
        if (inText || isFX(c)) { drop.push([o, c]); continue; }
        const tx = c.userData.text;
        c.name = uname(tx ? `Титр ${tx.s}` : c.name || (c.isMesh ? 'часть' : 'группа'));
        nodes.push(c); if (tx) texts.push({ name: c.name, ...tx });
        walk(c, !!tx);
      }
    };
    walk(S.scene, false);
    const effVis = o => {
      if (!o.visible) return 0;
      if (o.userData.visFrom) return o.userData.visFrom.material.opacity > .05 ? 1 : 0;
      if (o.userData.text) return o.children.some(c => c.material && c.material.opacity > .05) ? 1 : 0;
      const m = o.material; if (m && !Array.isArray(m) && m.transparent && m.opacity < .05) return 0;
      return 1;
    };
    // покадровая запись: положение, поворот, масштаб, видимость
    const K = 11, rec = nodes.map(() => null), first = new Float32Array(nodes.length * K), cam = [], callouts = [];
    const snap = (o, a, off) => { a[off] = o.position.x; a[off + 1] = o.position.y; a[off + 2] = o.position.z; a[off + 3] = o.quaternion.x; a[off + 4] = o.quaternion.y; a[off + 5] = o.quaternion.z; a[off + 6] = o.quaternion.w; a[off + 7] = o.scale.x; a[off + 8] = o.scale.y; a[off + 9] = o.scale.z; a[off + 10] = effVis(o); };
    const tmp = new Float32Array(K);
    for (let f = 0; f < N; f++) {
      const t = f / 30; inst.update(t);
      nodes.forEach((o, j) => {
        if (f === 0) { snap(o, first, j * K); return; }
        snap(o, tmp, 0);
        if (!rec[j]) {
          let ch = false; for (let q = 0; q < K; q++) if (Math.abs(tmp[q] - first[j * K + q]) > 1e-5) { ch = true; break; }
          if (!ch) return;
          rec[j] = new Float32Array(N * K); for (let g = 0; g < f; g++) rec[j].set(first.subarray(j * K, j * K + K), g * K);
        }
        rec[j].set(tmp, f * K);
      });
      S.cam.updateMatrixWorld();
      const cp = new T.Vector3(), cq = new T.Quaternion(), cs = new T.Vector3(); S.cam.matrixWorld.decompose(cp, cq, cs);
      const vw = S.cam.view && S.cam.view.enabled ? S.cam.view : null;
      cam.push([cp.x, cp.y, cp.z, cq.x, cq.y, cq.z, cq.w, S.cam.fov, S.focus, vw ? vw.offsetX / vw.fullWidth : 0, vw ? -vw.offsetY / vw.fullWidth : 0]);
      if (inst.exportCallouts) callouts.push(inst.exportCallouts(t));
    }
    const anim = {}; nodes.forEach((o, j) => { if (rec[j]) anim[o.name] = Array.from(rec[j], v => Math.round(v * 1e5) / 1e5); });
    // геометрия без материалов в положении первого кадра
    inst.update(0);
    drop.forEach(([par, c]) => par.remove(c));
    const plain = new T.MeshStandardMaterial({ color: 0xbfbfbf, name: 'clay' }), saved = [];
    S.scene.traverse(o => { if (o.isMesh) { saved.push([o, o.material]); o.material = plain; } });
    const glb = await new GLTFExporter().parseAsync(S.scene, { binary: true, onlyVisible: false });
    saved.forEach(([o, m]) => o.material = m); drop.forEach(([par, c]) => par.add(c));
    const b64 = await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result.split(',')[1]); fr.readAsDataURL(new Blob([glb])); });
    return { b64, data: { id: P.id, name: P.name, fps: 30, frames: N, K, anim, cam, texts, callouts, beats: P.beats } };
  }, idx);
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(`${out}/scene.glb`, Buffer.from(res.b64, 'base64'));
  fs.writeFileSync(`${out}/anim.json`, JSON.stringify(res.data));
  console.log('ok', res.data.id, 'animated nodes', Object.keys(res.data.anim).length, 'texts', res.data.texts.length, 'glb MB', (res.b64.length * .75 / 1e6).toFixed(1));
  await b.close();
})();
