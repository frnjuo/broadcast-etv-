// Поиск взаимопроникновений: по кадрам проверяет, входят ли точки поверхности движущихся предметов внутрь других предметов
// (и наоборот), и не оказывается ли камера внутри геометрии. Касания поверхностей не считаются.
// Запуск из корня репозитория: node tools/collisions.cjs <номер ролика 0–5> [шаг кадров, по умолчанию 3]
// Вывод — JSON: moving — движущиеся предметы, res — пересечения {t, a, b, n — сколько точек внутри, at — пример точки}, camIn — камера внутри.
// Задуманные стыки тоже попадают в отчёт (картридж в слоте, кабель в разъёме, штамп на подушке) — их отличают по кадру.
const { chromium } = require('playwright');
(async () => {
  const idx = +process.argv[2], step = +(process.argv[3] || 3);
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const p = await b.newPage({ viewport: { width: 320, height: 380 } }); p.setDefaultTimeout(3600000);
  p.on('pageerror', e => console.log('PAGEERR', e.message));
  await p.goto('file://' + require('path').resolve(__dirname, '../index.html'));
  await p.waitForFunction(() => window.__etv, null, { timeout: 600000 });
  const out = await p.evaluate(([i, step]) => {
    const T = window.__etv.THREE; window.__etv.seek(i, 0); const inst = window.__etv.pieces[i].inst, S = inst.S, N = Math.round(inst.dur * 30);
    const thin = m => { m.geometry.computeBoundingBox(); const s = m.geometry.boundingBox.getSize(new T.Vector3()).multiply(m.getWorldScale(new T.Vector3())); return Math.min(Math.abs(s.x), Math.abs(s.y), Math.abs(s.z)) < .02; };
    const visible = o => { for (let q = o; q; q = q.parent) { if (!q.visible) return false; const s = q.scale; if (Math.abs(s.x * s.y * s.z) < 1e-6) return false; } return true; };
    const solid = m => m.isMesh && !m.isSprite && !(m.material && (Array.isArray(m.material) ? false : (m.material.transparent && m.material.opacity < .05) || m.material.blending === T.AdditiveBlending)) && !m.userData.noAO;
    const bodies = S.scene.children.filter(o => !o.isLight && !o.isSprite && !o.isLine && !o.isCamera && (o.isMesh || o.isGroup) && !(o.userData.text) && !(o.userData.visFrom));
    const name = o => o.name || (o.isMesh ? 'mesh' : 'group');
    S.scene.traverse(o => { if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => m.side = T.DoubleSide); });
    const meshesOf = bd => { const a = []; bd.traverse(o => { if (solid(o) && visible(o) && !thin(o)) a.push(o); }); return a; };
    const sig = bd => { let s = ''; bd.traverse(o => { if (o.isMesh) s += o.matrixWorld.elements.map(v => v.toFixed(3)).join(','); }); return s; };
    // какие тела двигаются
    const sigs = bodies.map(() => new Set());
    for (const t of [0, 1, 2.5, 4, 5.5, 7, 8.5, 10, 11.5, 13, 14.9]) { if (t > inst.dur) continue; inst.update(t); S.scene.updateMatrixWorld(true); bodies.forEach((bd, j) => sigs[j].add(sig(bd))); }
    const moving = bodies.map((bd, j) => sigs[j].size > 1);
    const rc = new T.Raycaster(); rc.firstHitOnly = false;
    const dirs = [new T.Vector3(1, .013, .007).normalize(), new T.Vector3(-.011, 1, .017).normalize()];
    const inside = (pt, meshes) => dirs.every(d => { rc.set(pt, d); const hits = rc.intersectObjects(meshes, false); const ds = []; hits.forEach(h => { if (!ds.some(x => Math.abs(x - h.distance) < 1e-4)) ds.push(h.distance); }); return ds.length % 2 === 1; });
    const pts = (meshes, maxN) => {
      const all = []; meshes.forEach(m => { const pa = m.geometry.attributes.position, n = pa.count, st = Math.max(1, Math.floor(n / 120)); for (let k = 0; k < n; k += st) all.push(new T.Vector3().fromBufferAttribute(pa, k).applyMatrix4(m.matrixWorld)); });
      const st = Math.max(1, Math.floor(all.length / maxN)); return all.filter((_, k) => k % st === 0);
    };
    // точки по поверхности (равномерно по площади) в пределах области перекрытия; каждая сдвигается внутрь своего тела — касания не считаются
    const tri = new T.Triangle(), va = new T.Vector3(), vb = new T.Vector3(), vc = new T.Vector3(), nrm = new T.Vector3();
    const surf = (meshes, box, maxN) => {
      const out = [];
      for (const m of meshes) {
        const g = m.geometry, pa = g.attributes.position, ix = g.index, nt = ix ? ix.count / 3 : pa.count / 3;
        for (let k = 0; k < nt; k++) {
          const i0 = ix ? ix.getX(3 * k) : 3 * k, i1 = ix ? ix.getX(3 * k + 1) : 3 * k + 1, i2 = ix ? ix.getX(3 * k + 2) : 3 * k + 2;
          va.fromBufferAttribute(pa, i0).applyMatrix4(m.matrixWorld); vb.fromBufferAttribute(pa, i1).applyMatrix4(m.matrixWorld); vc.fromBufferAttribute(pa, i2).applyMatrix4(m.matrixWorld);
          tri.set(va, vb, vc); const tb = new T.Box3().setFromPoints([va, vb, vc]); if (!tb.intersectsBox(box)) continue;
          const ar = tri.getArea(); if (ar < 1e-7) continue; tri.getNormal(nrm);
          const n = Math.min(60, Math.max(1, Math.round(ar / .0025)));
          for (let q = 0; q < n; q++) { let u = Math.random(), v = Math.random(); if (u + v > 1) { u = 1 - u; v = 1 - v; } const p = va.clone().multiplyScalar(1 - u - v).addScaledVector(vb, u).addScaledVector(vc, v); if (box.containsPoint(p)) out.push([p, nrm.clone()]); }
        }
      }
      const st = Math.max(1, Math.floor(out.length / maxN)); return out.filter((_, k) => k % st === 0);
    };
    const res = [], camIn = [];
    for (let f = 0; f < N; f += step) {
      const t = f / 30; inst.update(t); S.scene.updateMatrixWorld(true); S.cam.updateMatrixWorld();
      const M = bodies.map(meshesOf), BB = M.map(ms => { const bx = new T.Box3(); ms.forEach(m => bx.expandByObject(m)); return bx; });
      const MB = M.map(ms => ms.map(m => new T.Box3().setFromObject(m)));
      for (let a = 0; a < bodies.length; a++) {
        if (!moving[a] || !M[a].length) continue;
        for (let c = 0; c < bodies.length; c++) {
          if (c === a || !M[c].length || (moving[c] && c < a)) continue;
          if (!BB[a].intersectsBox(BB[c])) continue;
          const ov = BB[a].clone().intersect(BB[c]); if (ov.isEmpty()) continue;
          const ca = M[a].filter((m, k) => MB[a][k].intersectsBox(ov)), cc = M[c].filter((m, k) => MB[c][k].intersectsBox(ov)); if (!ca.length || !cc.length) continue;
          let n = 0, ex = null;
          const test = (pts, own, other) => { const pick = other; for (const [p, nr] of pts) { const q = p.clone(); // внутрь своего тела: проверяем обе стороны нормали, берём ту, что внутри своего тела
              const q1 = p.clone().addScaledVector(nr, -.03), q2 = p.clone().addScaledVector(nr, .03); const qq = inside(q1, own) ? q1 : (inside(q2, own) ? q2 : null); if (!qq) continue;
              if (inside(qq, pick)) { n++; ex = ex || qq; } } };
          test(surf(ca, ov, 260), ca, cc); test(surf(cc, ov, 260), cc, ca);
          if (n >= 5) res.push({ t: +t.toFixed(2), a: name(bodies[a]), b: name(bodies[c]), n, at: ex.toArray().map(v => +v.toFixed(2)) });
        }
      }
      const cp = S.cam.position.clone();
      bodies.forEach((bd, c) => { if (M[c].length && BB[c].containsPoint(cp)) { const cand = M[c].filter((m, k) => MB[c][k].containsPoint(cp)); if (cand.length && inside(cp, cand)) camIn.push({ t: +t.toFixed(2), b: name(bd) }); } });
    }
    return { moving: bodies.filter((_, j) => moving[j]).map(name), res, camIn };
  }, [idx, step]);
  console.log(JSON.stringify(out));
  await b.close();
})();
