// Выгрузка ролика для аниматика в Blender: геометрия без материалов (GLB) + покадровая анимация, камера, маркеры (JSON)
// Запуск из корня репозитория: node tools/animatic/export.cjs <номер ролика 0–4> <папка> [full]
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const idx = +process.argv[2], out = process.argv[3], FULL = process.argv[4] === 'full'; // full: материалы, свет и прозрачности для настоящей сцены, а не аниматика
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const p = await b.newPage({ viewport: { width: 640, height: 560 } }); p.setDefaultTimeout(1800000);
  p.on('pageerror', e => console.log('PAGEERR', e.message));
  p.on('console', m => { if (m.type() === 'error') console.log('CONSOLE', m.text()); });
  // запись всех надписей, которые рисуются на текстурах: строка, шрифт, позиция, выравнивание, цвет, трансформация; tag — кадр выгрузки
  await p.addInitScript(() => {
    const of = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function (s, x, y, mw) {
      const c = this.canvas, t = this.getTransform();
      (c.__tx || (c.__tx = [])).push({ s: String(s), x, y, font: this.font, align: this.textAlign, base: this.textBaseline, fill: typeof this.fillStyle === 'string' ? this.fillStyle : '#cccccc', ls: parseFloat(this.letterSpacing || '0') || 0, ga: this.globalAlpha, m: [t.a, t.b, t.c, t.d, t.e, t.f], tag: window.__ftag });
      return of.call(this, s, x, y, mw);
    };
  });
  await p.goto('file://' + require('path').resolve(__dirname, '../../index.html'));
  await p.waitForFunction(() => window.__etv, null, { timeout: 600000 });
  const res = await p.evaluate(async ([i, FULL]) => {
    const T = window.__etv.THREE; window.__etv.seek(i, 0);
    const P = window.__etv.pieces[i], inst = P.inst, S = inst.S, N = Math.round(inst.dur * 30);
    const { GLTFExporter } = await import('three/addons/exporters/GLTFExporter.js');
    // свет и эффекты в аниматик не идут: спрайты, линии, аддитивные свечения, подсветки фона
    const targets = new Set(); S.scene.traverse(o => { if (o.isLight && o.target) targets.add(o.target); });
    // аниматик: без света и эффектов; full: свет пишется отдельно, светящиеся плоскости (ореол) остаются в сцене
    const isFX = o => o.userData.noExport || targets.has(o) || o.isSprite || o.isLine || o.isPoints || o.isLight || (!FULL && (o.userData.noAO || (o.isMesh && !Array.isArray(o.material) && o.material.isMeshBasicMaterial && o.material.blending === T.AdditiveBlending)));
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
    // носители надписей: плоскости и круги с текстурой-канвасом, на которой есть текст (кроме титров — они выгружаются отдельно)
    const inText = o => { for (let q = o; q; q = q.parent) if (q.userData.text) return true; return false; };
    const hosts = [];
    S.scene.traverse(o => {
      if (!o.isMesh || inText(o) || isFX(o) || Array.isArray(o.material)) return;
      const tex = o.material.map && o.material.map.image && o.material.map.image.__tx ? o.material.map : o.material.emissiveMap && o.material.emissiveMap.image && o.material.emissiveMap.image.__tx ? o.material.emissiveMap : null;
      if (!tex || !['PlaneGeometry', 'CircleGeometry'].includes(o.geometry.type)) return;
      o.geometry.computeBoundingBox(); hosts.push({ o, tex, bb: o.geometry.boundingBox, cv: tex.image });
    });
    const tracks = new Map(), TK = 11;
    const colOf = f => { let r = 200, g = 200, b = 200; const m = f.match(/#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i), n = f.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)/); if (m) [r, g, b] = [1, 2, 3].map(k => parseInt(m[k], 16)); else if (n) [r, g, b] = [1, 2, 3].map(k => +n[k]); return g > 150 && b > 180 && r < 120 ? 'c' : b > g + 40 && r > g ? 'v' : 'd'; };
    const hostVis = o => { for (let q = o; q; q = q.parent) { if (!q.visible) return false; if (Math.abs(q.scale.x * q.scale.y * q.scale.z) < 1e-6) return false; } const m = o.material; if (m.transparent && m.opacity < .05) return false; if (m.isMeshBasicMaterial && m.color.r + m.color.g + m.color.b < .06) return false; return true; };
    const textFrame = f => {
      const seen = new Set(); S.scene.updateMatrixWorld(true);
      hosts.forEach((h, hi) => {
        const all = h.cv.__tx, dyn = all.some(c => c.tag !== undefined), calls = dyn ? all.filter(c => c.tag === f) : all;
        if (!calls.length) return;
        const vis0 = hostVis(h.o); h.o.updateMatrixWorld(); h.tex.updateMatrix(); const inv = h.tex.matrix.clone().invert(), cw = h.cv.width, ch = h.cv.height, bb = h.bb, W = h.o.matrixWorld;
        const L = (u, v) => new T.Vector3(bb.min.x + u * (bb.max.x - bb.min.x), bb.min.y + v * (bb.max.y - bb.min.y), 0);
        calls.forEach((c, ci) => {
          if (!c.s.trim()) return;
          const key = `${hi}|${c.s}|${c.font}|${c.align}|${c.base}|${dyn ? '' : ci}`;
          const X = c.m[0] * c.x + c.m[2] * c.y + c.m[4], Y = c.m[1] * c.x + c.m[3] * c.y + c.m[5];
          let uv = null;
          for (const k of (h.tex.wrapT === T.RepeatWrapping ? [0, -1, 1] : [0])) { const q = new T.Vector3(X / cw, 1 - Y / ch + k, 1).applyMatrix3(inv); if (q.x > -.02 && q.x < 1.02 && q.y > -.02 && q.y < 1.02) { uv = q; break; } }
          const px = +((c.font.match(/([\d.]+)px/) || [0, 20])[1]), sy = Math.hypot(c.m[2], c.m[3]);
          const P0 = uv ? L(uv.x, uv.y).applyMatrix4(W) : new T.Vector3();
          const vUnit = new T.Vector3(0, (bb.max.y - bb.min.y) / ch / h.tex.repeat.y, 0), size = uv ? L(0, 0).add(vUnit).applyMatrix4(W).distanceTo(L(0, 0).applyMatrix4(W)) * px * sy : 0;
          const ax = L(1, 0).applyMatrix4(W).sub(L(0, 0).applyMatrix4(W)).normalize(), ay = L(0, 1).applyMatrix4(W).sub(L(0, 0).applyMatrix4(W)).normalize(), nz = ax.clone().cross(ay).normalize();
          const th = -Math.atan2(c.m[1], c.m[0]); const xa = ax.clone().multiplyScalar(Math.cos(th)).addScaledVector(ay, Math.sin(th)), ya = nz.clone().cross(xa).normalize();
          P0.addScaledVector(nz, .013); // над носителем и его тонкими накладками (тени барабанов счётчика и т. п.)
          let tr = tracks.get(key);
          if (!tr) { tr = { s: c.s, font: /Unbounded/.test(c.font) ? 'T' : 'M', size: size || 0, align: c.align, base: c.base, space: 1 + c.ls / Math.max(1, .65 * px), col: colOf(c.fill), f0: f, fr: [] }; tracks.set(key, tr); }
          if (!tr.size && size) tr.size = size;
          const vis = uv && vis0 && c.ga > .3 ? 1 : 0;
          tr.fr[f] = [P0.x, P0.y, P0.z, xa.x, xa.y, xa.z, ya.x, ya.y, ya.z, tr.size ? size / tr.size : 1, vis].map(v => Math.round(v * 1e4) / 1e4);
          seen.add(key);
        });
      });
      tracks.forEach((tr, key) => { if (!seen.has(key)) tr.fr[f] = null; });
    };
    const K = 11, rec = nodes.map(() => null), first = new Float32Array(nodes.length * K), cam = [], callouts = [], lights = {}, mats = {};
    const snap = (o, a, off) => { a[off] = o.position.x; a[off + 1] = o.position.y; a[off + 2] = o.position.z; a[off + 3] = o.quaternion.x; a[off + 4] = o.quaternion.y; a[off + 5] = o.quaternion.z; a[off + 6] = o.quaternion.w; a[off + 7] = o.scale.x; a[off + 8] = o.scale.y; a[off + 9] = o.scale.z; a[off + 10] = effVis(o); };
    const tmp = new Float32Array(K);
    for (let f = 0; f < N; f++) {
      const t = f / 30; window.__ftag = f; inst.update(t); textFrame(f);
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
      cam.push([cp.x, cp.y, cp.z, cq.x, cq.y, cq.z, cq.w, S.cam.fov, S.focus, vw ? vw.offsetX / vw.fullWidth : 0, vw ? -vw.offsetY / vw.fullWidth : 0, S.ap]);
      if (FULL) {
        // свет по кадрам: положение, сила, цвет; у направленных — ещё точка, куда светят
        S.scene.traverse(o => { if (!o.isLight) return; o.updateMatrixWorld(); const w = new T.Vector3().setFromMatrixPosition(o.matrixWorld), tg = o.target ? new T.Vector3().setFromMatrixPosition(o.target.matrixWorld) : w;
          const key = o.name || (o === S.key ? 'Ключевой' : o === S.fill ? 'Заполняющий' : o === S.rimA ? 'Контровой 1' : o === S.rimB ? 'Контровой 2' : o === S.hemi ? 'Небо' : 'Свет');
          (lights[key] = lights[key] || { type: o.isDirectionalLight ? 'SUN' : o.isPointLight ? 'POINT' : o.isSpotLight ? 'SPOT' : 'HEMI', fr: [] }).fr.push([w.x, w.y, w.z, tg.x, tg.y, tg.z, o.intensity, o.color.r, o.color.g, o.color.b, o.distance || 0].map(v => Math.round(v * 1e4) / 1e4)); });
        // прозрачность и свечение именованных материалов (ореол и т. п.) и прозрачность титров
        S.scene.traverse(o => { if (!o.isMesh || Array.isArray(o.material) || !o.material.name) return; const m = o.material; (mats[m.name] = mats[m.name] || []).push([m.opacity, m.emissiveIntensity ?? 0]); });
        texts.forEach(tx => { const g = S.scene.getObjectByName(tx.name); const ch = g && g.children.find(c => c.material); (tx.op = tx.op || []).push(ch ? Math.round(ch.material.opacity * 1e3) / 1e3 : 1); });
      }
      if (inst.exportCallouts) callouts.push(inst.exportCallouts(t));
    }
    const anim = {}; nodes.forEach((o, j) => { if (rec[j]) anim[o.name] = Array.from(rec[j], v => Math.round(v * 1e5) / 1e5); });
    // дорожки надписей: если положение и видимость не меняются — хранится один кадр
    const ttracks = [...tracks.values()].filter(tr => tr.size > 0).map(tr => {
      const fr = Array.from({ length: N }, (_, f) => tr.fr[f] || null), last = fr.find(x => x);
      const full = fr.map(x => x || [...last.slice(0, 10), 0]);
      const still = full.every(x => x.every((v, k) => Math.abs(v - full[0][k]) < 1e-4));
      return { s: tr.s, font: tr.font, size: Math.round(tr.size * 1e4) / 1e4, align: tr.align, base: tr.base, space: Math.round(tr.space * 1e3) / 1e3, col: tr.col, still, fr: still ? [full[0]] : full };
    });
    // геометрия без материалов в положении первого кадра
    inst.update(0);
    drop.forEach(([par, c]) => par.remove(c));
    const plain = new T.MeshStandardMaterial({ color: 0xbfbfbf, name: 'clay' }), saved = [];
    if (!FULL) S.scene.traverse(o => { if (o.isMesh) { saved.push([o, o.material]); o.material = plain; } });
    const glb = await new GLTFExporter().parseAsync(S.scene, { binary: true, onlyVisible: false });
    saved.forEach(([o, m]) => o.material = m); drop.forEach(([par, c]) => par.add(c));
    const b64 = await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result.split(',')[1]); fr.readAsDataURL(new Blob([glb])); });
    return { b64, data: { id: P.id, name: P.name, fps: 30, frames: N, K, anim, cam, texts, callouts, beats: P.beats, ttracks, lights, mats, exposure: S.exposure ?? .9 } };
  }, [idx, FULL]);
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(`${out}/scene.glb`, Buffer.from(res.b64, 'base64'));
  fs.writeFileSync(`${out}/anim.json`, JSON.stringify(res.data));
  console.log('ok', res.data.id, 'animated nodes', Object.keys(res.data.anim).length, 'texts', res.data.texts.length, 'labels', res.data.ttracks.length, 'glb MB', (res.b64.length * .75 / 1e6).toFixed(1));
  await b.close();
})();
