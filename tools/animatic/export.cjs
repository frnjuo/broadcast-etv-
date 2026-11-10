// Выгрузка ролика для аниматика в Blender: геометрия без материалов (GLB) + покадровая анимация, камера, маркеры (JSON)
// Запуск из корня репозитория: node tools/animatic/export.cjs <номер ролика 0–5> <папка> [full]
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const idx = +process.argv[2], out = process.argv[3], FULL = process.argv[4] === 'full'; // full: материалы, свет и прозрачности для настоящей сцены, а не аниматика
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const p = await b.newPage({ viewport: { width: 640, height: 560 } }); p.setDefaultTimeout(1800000);
  p.on('pageerror', e => console.log('PAGEERR', e.message));
  p.on('console', m => { if (m.type() === 'error') console.log('CONSOLE', m.text()); });
  // запись всего, что рисуется на текстурах и в кадре: надписи (строка, шрифт, ширина и базовая линия по измерению браузера,
  // выравнивание, межбуквенный интервал, трансформация) и знак Е (контур Path2D); tag — кадр выгрузки
  await p.addInitScript(() => {
    const C2 = CanvasRenderingContext2D.prototype, of = C2.fillText;
    C2.fillText = function (s, x, y, mw) {
      const c = this.canvas, t = this.getTransform(), mm = this.measureText(String(s));
      (c.__tx || (c.__tx = [])).push({ s: String(s), x, y, mw: mw === undefined ? null : mw, w: mm.width, ab: mm.alphabeticBaseline, font: this.font, align: this.textAlign, base: this.textBaseline, dir: this.direction, fill: typeof this.fillStyle === 'string' ? this.fillStyle : '#cccccc', ls: parseFloat(this.letterSpacing || '0') || 0, ga: this.globalAlpha, blur: /blur/.test(this.filter || ''), m: [t.a, t.b, t.c, t.d, t.e, t.f], tag: window.__ftag });
      return of.call(this, s, x, y, mw);
    };
    // контур знака: Path2D запоминает точки; на fill/stroke проверяется, что это знак Е (то же число точек и пропорция, что у LOGO_D)
    const P2 = Path2D.prototype;
    for (const k of ['moveTo', 'lineTo']) { const o = P2[k]; P2[k] = function (x, y) { (this.__p || (this.__p = [])).push(x, y); return o.call(this, x, y); }; }
    let NL = 0;
    const logoN = () => { if (NL) return NL; const pe = document.querySelector('.logo-svg path'); const d = pe && pe.getAttribute('d'); if (d && d.length > 20) NL = (d.match(/[ML]/g) || []).length; return NL; };
    const isLogo = P => {
      const a = P && P.__p; if (!a || a.length < 60) return null; const n = logoN(); if (n && a.length / 2 !== n) return null;
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9; for (let i = 0; i < a.length; i += 2) { x0 = Math.min(x0, a[i]); x1 = Math.max(x1, a[i]); y0 = Math.min(y0, a[i + 1]); y1 = Math.max(y1, a[i + 1]); }
      const r = (x1 - x0) / (y1 - y0); return r > 1.4 && r < 1.5 ? [x0, y0, x1, y1] : null;
    };
    for (const k of ['fill', 'stroke']) {
      const o = C2[k];
      C2[k] = function (...args) {
        const P = args[0] instanceof Path2D ? args[0] : null, bb = P && isLogo(P);
        if (bb && !/blur/.test(this.filter || '')) { const c = this.canvas, t = this.getTransform(); (c.__tx || (c.__tx = [])).push({ logo: k, s: '', bb, pts: P.__p, lw: this.lineWidth, fill: String(k === 'fill' ? this.fillStyle : this.strokeStyle), ga: this.globalAlpha, m: [t.a, t.b, t.c, t.d, t.e, t.f], tag: window.__ftag }); }
        return o.apply(this, args);
      };
    }
  });
  await p.goto('file://' + require('path').resolve(__dirname, '../../index.html'));
  await p.waitForFunction(() => window.__etv, null, { timeout: 600000 });
  await p.addStyleTag({ content: '#stage{position:fixed!important;left:0;top:0;width:1600px!important;height:900px!important;max-width:none!important;border:0!important;z-index:999}' });
  await p.evaluate(() => document.fonts.ready);
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
    const tracks = new Map();
    const colOf = f => { let r = 200, g = 200, b = 200; const m = f.match(/#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i), n = f.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)/); if (m) [r, g, b] = [1, 2, 3].map(k => parseInt(m[k], 16)); else if (n) [r, g, b] = [1, 2, 3].map(k => +n[k]); return g > 150 && b > 180 && r < 120 ? 'c' : b > g + 40 && r > g ? 'v' : 'd'; };
    const fontKey = f => /Unbounded/.test(f) ? 'T' : /JetBrains|monospace/.test(f) ? 'M' : 'I';
    const hostVis = o => { for (let q = o; q; q = q.parent) { if (!q.visible) return false; if (Math.abs(q.scale.x * q.scale.y * q.scale.z) < 1e-6) return false; } const m = o.material; if (m.transparent && m.opacity < .05) return false; if (m.isMeshBasicMaterial && m.color.r + m.color.g + m.color.b < .06) return false; return true; };
    let logoOutline = null;
    // одна запись холста → положение на носителе: M — матрица «геометрия носителя → мир» (или → локально в группе титра)
    // точка — левый край первой буквы на базовой линии (для знака — центр), оси: xa — вдоль строки, ya — вверх по строке, nz — нормаль
    const place = (c, cv, tex, bb, M, ci) => {
      tex.updateMatrix(); const inv = tex.matrix.clone().invert(), cw = cv.width, ch = cv.height;
      const L = (u, v) => new T.Vector3(bb.min.x + u * (bb.max.x - bb.min.x), bb.min.y + v * (bb.max.y - bb.min.y), 0);
      const [a, b, cc, d, e, f] = c.m, sx = Math.hypot(a, b), sy = Math.hypot(cc, d);
      let X0, Y0, rec = {};
      if (c.logo) {
        const cx = (c.bb[0] + c.bb[2]) / 2, cy = (c.bb[1] + c.bb[3]) / 2; X0 = a * cx + cc * cy + e; Y0 = b * cx + d * cy + f;
        if (!logoOutline) { const h = c.bb[3] - c.bb[1], o = []; for (let i = 0; i < c.pts.length; i += 2) o.push([+((c.pts[i] - cx) / h).toFixed(5), +(-(c.pts[i + 1] - cy) / h).toFixed(5)]); logoOutline = o; }
      } else {
        const wv = c.mw !== null && c.w > c.mw ? c.mw : c.w, rtl = c.dir === 'rtl';
        const al = c.align === 'center' ? -.5 : (c.align === 'right' || (c.align === 'end' && !rtl) || (c.align === 'start' && rtl)) ? -1 : 0;
        const xL = c.x + al * wv, yB = c.y - c.ab; X0 = a * xL + cc * yB + e; Y0 = b * xL + d * yB + f;
      }
      let uv = null;
      for (const k of (tex.wrapT === T.RepeatWrapping ? [0, -1, 1] : [0])) { const q = new T.Vector3(X0 / cw, 1 - Y0 / ch + k, 1).applyMatrix3(inv); if (q.x > -.02 && q.x < 1.02 && q.y > -.02 && q.y < 1.02) { uv = q; break; } }
      if (!uv) return null;
      const O = L(0, 0).applyMatrix4(M);
      const wV = L(0, 0).add(new T.Vector3(0, (bb.max.y - bb.min.y) / ch / tex.repeat.y, 0)).applyMatrix4(M).distanceTo(O);   // мир на 1 px холста по вертикали
      const wH = L(0, 0).add(new T.Vector3((bb.max.x - bb.min.x) / cw / tex.repeat.x, 0, 0)).applyMatrix4(M).distanceTo(O);   // и по горизонтали
      const ax = L(1, 0).applyMatrix4(M).sub(O).normalize(), ay = L(0, 1).applyMatrix4(M).sub(O).normalize(), nz = ax.clone().cross(ay).normalize();
      const xa = ax.clone().multiplyScalar(a * wH).addScaledVector(ay, -b * wV).normalize(), ya = nz.clone().cross(xa).normalize();
      const P0 = L(uv.x, uv.y).applyMatrix4(M);
      // наклон букв (курсив титров): проекция «вверх по строке» на направление строки
      const ux = -cc * wH, uy = d * wV, ex = a * wH, ey = -b * wV, el = Math.hypot(ex, ey), along = (ux * ex + uy * ey) / el, perp = Math.abs(ux * ey - uy * ex) / el;
      rec = { P0, xa, ya, nz, wH, wV, shear: perp > 1e-9 ? along / perp : 0, sxr: (sx * wH) / Math.max(1e-9, sy * wV) };
      if (c.logo) { rec.h = (c.bb[3] - c.bb[1]) * sy * wV; rec.lw = c.logo === 'stroke' ? c.lw * sy * wV : 0; }
      else { const px = +((c.font.match(/([\d.]+)px/) || [0, 20])[1]); rec.px = px; rec.em = px * sy * wV; rec.wem = c.w / px; rec.lsem = c.ls / px; rec.cond = c.mw !== null && c.w > c.mw ? c.mw / c.w : 1; }
      return rec;
    };
    const textFrame = f => {
      const seen = new Set(); S.scene.updateMatrixWorld(true);
      hosts.forEach((h, hi) => {
        const all = h.cv.__tx, dyn = all.some(c => c.tag !== undefined), calls = (dyn ? all.filter(c => c.tag === f) : all).filter(c => !c.blur);
        if (!calls.length) return;
        const vis0 = hostVis(h.o); h.o.updateMatrixWorld();
        calls.forEach((c, ci) => {
          if (!c.logo && !c.s.trim()) return;
          const key = c.logo ? `${hi}|логотип|${dyn ? '' : ci}` : `${hi}|${c.s}|${c.font}|${c.align}|${c.base}|${dyn ? '' : ci}`;
          const r = place(c, h.cv, h.tex, h.bb, h.o.matrixWorld, ci);
          let tr = tracks.get(key);
          if (!r) { if (tr) tr.fr[f] = null; return; }
          r.P0.addScaledVector(r.nz, .013); // над носителем и его тонкими накладками (тени барабанов счётчика и т. п.)
          if (!tr) {
            tr = c.logo ? { type: 'logo', mode: c.logo, size: r.h, lw: r.lw / r.h, sx: r.sxr, col: colOf(c.fill), fr: [] }
              : { s: c.s, font: fontKey(c.font), size: r.em, wem: r.wem, lsem: r.lsem, shear: r.shear, sx: r.cond * r.sxr, col: colOf(c.fill), fr: [] };
            tracks.set(key, tr);
          }
          const sz = c.logo ? r.h : r.em, vis = vis0 && c.ga > .3 ? 1 : 0;
          tr.fr[f] = [r.P0.x, r.P0.y, r.P0.z, r.xa.x, r.xa.y, r.xa.z, r.ya.x, r.ya.y, r.ya.z, tr.size ? sz / tr.size : 1, vis].map(v => Math.round(v * 1e5) / 1e5);
          seen.add(key);
        });
      });
      tracks.forEach((tr, key) => { if (!seen.has(key)) tr.fr[f] = null; });
    };
    // титры: надписи с холста лицевого слоя — в координатах группы титра (группа движется анимацией)
    const titles = [];
    texts.forEach(tx => {
      const g = S.scene.getObjectByName(tx.name); if (!g) return;
      const faces = g.children.filter(m => m.isMesh && m.material && m.material.map && m.material.map.image && m.material.map.image.__tx);
      if (!faces.length) return;
      const top = faces.reduce((p, q) => q.position.y > p.position.y ? q : p); top.updateMatrix(); top.geometry.computeBoundingBox();
      const parts = [];
      top.material.map.image.__tx.filter(c => !c.blur && !c.logo && c.s.trim()).forEach((c, ci) => {
        const r = place(c, top.material.map.image, top.material.map, top.geometry.boundingBox, top.matrix, ci); if (!r) return;
        parts.push({ s: c.s, font: fontKey(c.font), em: r.em, wem: r.wem, lsem: r.lsem, shear: r.shear, sx: r.cond * r.sxr, col: colOf(c.fill), P: r.P0.toArray(), xa: r.xa.toArray(), ya: r.ya.toArray() });
      });
      titles.push({ name: tx.name, depth: tx.depth, parts });
    });
    // наложения поверх кадра (знак канала, плашка, сноски): раскладка DOM по кадрам, в единицах ширины кадра от центра, y вверх
    const ovEl = document.getElementById('ov'), stEl = document.getElementById('stage'), els = {};
    ovEl.querySelectorAll('[data-k]').forEach(e => els[e.dataset.k] = e);
    const mc = document.createElement('canvas').getContext('2d'), ovt = new Map(), ovs = new Map();
    const idOf = el => { const a = []; for (let e = el; e && e !== ovEl; e = e.parentElement) a.push((e.dataset && e.dataset.k) || `${(e.getAttribute('class') || e.tagName).split(' ')[0]}${[...e.parentElement.children].indexOf(e)}`); return a.reverse().join('/'); };
    const opOf = el => { let op = 1; for (let e = el; e && e !== ovEl.parentElement; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden') return 0; op *= parseFloat(cs.opacity); } return op; };
    const clipOf = el => {
      let R = null;
      for (let e = el; e && e !== ovEl; e = e.parentElement) {
        const cp = getComputedStyle(e).clipPath; if (!cp || !cp.startsWith('inset(')) continue;
        const bx = e.getBoundingClientRect(), tk = cp.slice(6, cp.indexOf(')')).trim().split(/\s+/).map((v, i) => v.endsWith('%') ? parseFloat(v) / 100 * (i % 2 ? bx.width : bx.height) : parseFloat(v));
        const [t, r = t, b = t, l = r] = tk, rr = [bx.left + l, bx.top + t, bx.right - r, bx.bottom - b];
        R = R ? [Math.max(R[0], rr[0]), Math.max(R[1], rr[1]), Math.min(R[2], rr[2]), Math.min(R[3], rr[3])] : rr;
      }
      return R;
    };
    const inCard = el => { for (let e = el; e && e !== ovEl; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.backgroundImage !== 'none' || (cs.backgroundColor && !/rgba\(0, 0, 0, 0\)|transparent/.test(cs.backgroundColor))) return true; } return false; };
    const ovFrame = f => {
      const st = stEl.getBoundingClientRect(), W = st.width, H = st.height, X = px => (px - st.left) / W - .5, Y = py => (st.top + H / 2 - py) / W;
      const seen = new Set();
      const set = (map, key, init, row) => { let tr = map.get(key); if (!tr) { tr = { ...init(), fr: [] }; map.set(key, tr); } tr.fr[f] = row; seen.add(key); };
      // надписи: каждый текстовый узел — своя дорожка (строка входит в ключ: печать по буквам даёт по объекту на каждую длину)
      const tw = document.createTreeWalker(ovEl, NodeFilter.SHOW_TEXT);
      for (let n = tw.nextNode(); n; n = tw.nextNode()) {
        const el = n.parentElement, cs = getComputedStyle(el); let s = n.textContent; if (!s.trim() || el.closest('style')) continue;
        if (cs.textTransform === 'uppercase') s = s.toUpperCase();
        const rg = document.createRange(); rg.selectNodeContents(n); const r = rg.getBoundingClientRect(); if (!r.width) continue;
        let vis = opOf(el) > .3 ? 1 : 0; const cl = clipOf(el); if (vis && cl) vis = (Math.min(r.right, cl[2]) - Math.max(r.left, cl[0])) / r.width >= .5 ? 1 : 0;
        const fs = parseFloat(cs.fontSize); mc.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`; const base = r.top + mc.measureText(s).fontBoundingBoxAscent;
        set(ovt, `${idOf(el)}|${s}`, () => ({ s, font: fontKey(cs.fontFamily), weight: +cs.fontWeight, em: fs / W, wem: r.width / fs, lsem: cs.letterSpacing === 'normal' ? 0 : parseFloat(cs.letterSpacing) / fs, col: colOf(cs.color), card: inCard(el) }), [X(r.left), Y(base), vis].map(v => Math.round(v * 1e5) / 1e5));
      }
      // знак канала в углу (SVG с контуром LOGO_D)
      ovEl.querySelectorAll('svg.logo-svg path').forEach(pe => { const r = pe.getBoundingClientRect(); set(ovs, 'логотип|' + idOf(pe), () => ({ type: 'logo', col: colOf(getComputedStyle(pe).fill === 'none' ? getComputedStyle(pe).stroke : getComputedStyle(pe.closest('svg')).color) }), [X(r.left + r.width / 2), Y(r.top + r.height / 2), r.height / W, r.height > 0 && opOf(pe) > .3 ? 1 : 0].map(v => Math.round(v * 1e5) / 1e5)); });
      // плашки с рамкой или фоном (карточки сносок, рамка номера, полоска)
      ovEl.querySelectorAll('*').forEach(el => {
        if (el.closest('svg') || el.tagName === 'STYLE') return; const cs = getComputedStyle(el), bw = parseFloat(cs.borderTopWidth) || 0, bg = cs.backgroundImage !== 'none' || !/rgba\(0, 0, 0, 0\)|transparent/.test(cs.backgroundColor);
        if (!bw && !bg) return; const r = el.getBoundingClientRect();
        let vis = r.width > 0 && opOf(el) > .3 ? 1 : 0; const cl = clipOf(el); if (vis && cl) vis = (Math.min(r.right, cl[2]) - Math.max(r.left, cl[0])) / r.width >= .5 ? 1 : 0;
        set(ovs, 'плашка|' + idOf(el), () => ({ type: 'rect', border: bw / W, bcol: colOf(cs.borderTopColor), fill: bg ? (cs.backgroundImage !== 'none' ? 'd' : colOf(cs.backgroundColor)) : null }), [X(r.left), Y(r.top), X(r.right), Y(r.bottom), vis].map(v => Math.round(v * 1e5) / 1e5));
      });
      // точки, кольца и выноски сносок (SVG)
      ovEl.querySelectorAll('svg:not(.logo-svg) circle').forEach(ce => { const r = ce.getBoundingClientRect(), cs = getComputedStyle(ce), k = W / 1600; set(ovs, 'круг|' + idOf(ce), () => ({ type: 'circle', fillc: cs.fill !== 'none', sw: (parseFloat(cs.strokeWidth) || 0) * k / W, col: colOf(cs.fill !== 'none' ? cs.fill : cs.stroke) }), [X(r.left + r.width / 2), Y(r.top + r.height / 2), r.width / 2 / W, r.width > 0 && opOf(ce) > .15 ? 1 : 0].map(v => Math.round(v * 1e5) / 1e5)); });
      ovEl.querySelectorAll('svg:not(.logo-svg) polyline').forEach(pl => {
        const svg = pl.ownerSVGElement, M = svg.getScreenCTM(), cs = getComputedStyle(pl), raw = (pl.getAttribute('points') || '').trim();
        const pts = raw ? raw.split(/\s+/).map(q => q.split(',').map(Number)).map(([x, y]) => { const p = svg.createSVGPoint(); p.x = x; p.y = y; const s2 = p.matrixTransform(M); return [X(s2.x), Y(s2.y)]; }) : [];
        const L = parseFloat(pl.style.strokeDasharray) || 0, off = parseFloat(pl.style.strokeDashoffset) || 0, frac = L ? Math.max(0, Math.min(1, 1 - off / L)) : 1;
        set(ovs, 'выноска|' + idOf(pl), () => ({ type: 'line', n: 3, sw: (parseFloat(cs.strokeWidth) || 0) * (W / 1600) / W, col: colOf(cs.stroke) }), [...(pts.length === 3 ? pts.flat() : [0, 0, 0, 0, 0, 0]), frac, pts.length === 3 && opOf(pl) > .3 && frac > .001 ? 1 : 0].map(v => Math.round(v * 1e5) / 1e5));
      });
      ovt.forEach((tr, key) => { if (!seen.has(key)) tr.fr[f] = null; }); ovs.forEach((tr, key) => { if (!seen.has(key)) tr.fr[f] = null; });
    };
    const K = 11, rec = nodes.map(() => null), first = new Float32Array(nodes.length * K), cam = [], callouts = [], lights = {}, mats = {}, matKind = {};
    const snap = (o, a, off) => { a[off] = o.position.x; a[off + 1] = o.position.y; a[off + 2] = o.position.z; a[off + 3] = o.quaternion.x; a[off + 4] = o.quaternion.y; a[off + 5] = o.quaternion.z; a[off + 6] = o.quaternion.w; a[off + 7] = o.scale.x; a[off + 8] = o.scale.y; a[off + 9] = o.scale.z; a[off + 10] = effVis(o); };
    const tmp = new Float32Array(K);
    for (let f = 0; f < N; f++) {
      const t = f / 30; window.__ftag = f; inst.update(t); inst.ov(t, els); textFrame(f); ovFrame(f);
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
        S.scene.traverse(o => { if (!o.isMesh || !o.material) return; for (const m of (Array.isArray(o.material) ? o.material : [o.material])) { if (!m.name) continue; matKind[m.name] = m.type; const a = (mats[m.name] = mats[m.name] || []); if (a.length < N && a.lastF !== f) { a.lastF = f; a.push([m.opacity, m.emissiveIntensity ?? 0, m.color ? m.color.r : 0, m.color ? m.color.g : 0, m.color ? m.color.b : 0].map(v => Math.round(v * 1e4) / 1e4)); } } });
        texts.forEach(tx => { const g = S.scene.getObjectByName(tx.name); const ch = g && g.children.find(c => c.material); (tx.op = tx.op || []).push(ch ? Math.round(ch.material.opacity * 1e3) / 1e3 : 1); });
      }
      if (inst.exportCallouts) callouts.push(inst.exportCallouts(t));
    }
    const anim = {}; nodes.forEach((o, j) => { if (rec[j]) anim[o.name] = Array.from(rec[j], v => Math.round(v * 1e5) / 1e5); });
    // дорожки надписей: если положение и видимость не меняются — хранится один кадр
    const pack = (tr, keys) => { const fr = Array.from({ length: N }, (_, f) => tr.fr[f] || null), last = fr.find(x => x); if (!last) return null;
      const full = fr.map(x => x || [...last.slice(0, last.length - 1), 0]); const still = full.every(x => x.every((v, k) => Math.abs(v - full[0][k]) < 1e-4));
      const o = {}; keys.forEach(k => { if (tr[k] !== undefined) o[k] = tr[k]; }); o.still = still; o.fr = still ? [full[0]] : full; return o; };
    const ttracks = [...tracks.values()].filter(tr => tr.size > 0).map(tr => pack(tr, ['type', 'mode', 's', 'font', 'size', 'wem', 'lsem', 'shear', 'sx', 'lw', 'col'])).filter(Boolean);
    const overlay = { texts: [...ovt.values()].map(tr => pack(tr, ['s', 'font', 'weight', 'em', 'wem', 'lsem', 'col', 'card'])).filter(Boolean), shapes: [...ovs.values()].map(tr => pack(tr, ['type', 'border', 'bcol', 'fill', 'fillc', 'sw', 'col', 'n'])).filter(Boolean) };
    // отображение кадра: соотношение сторон и шрифты, которыми браузер набирал наложения
    const aspect = stEl.getBoundingClientRect().width / stEl.getBoundingClientRect().height;
    // контур знака, если на текстурах его не было: из SVG знака канала (тот же LOGO_D)
    if (!logoOutline) { const pe = document.querySelector('.logo-svg path'), d = pe && pe.getAttribute('d'); if (d) { const P = d.replace(/[MLZ]/g, ' ').trim().split(/\s+/).map(q => q.split(',').map(Number)); let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9; P.forEach(([x, y]) => { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }); const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, h = y1 - y0; logoOutline = P.map(([x, y]) => [+((x - cx) / h).toFixed(5), +(-(y - cy) / h).toFixed(5)]); } }
    // геометрия без материалов в положении первого кадра
    inst.update(0);
    drop.forEach(([par, c]) => par.remove(c));
    const plain = new T.MeshStandardMaterial({ color: 0xbfbfbf, name: 'clay' }), saved = [];
    if (!FULL) S.scene.traverse(o => { if (o.isMesh) { saved.push([o, o.material]); o.material = plain; } });
    const glb = await new GLTFExporter().parseAsync(S.scene, { binary: true, onlyVisible: false });
    saved.forEach(([o, m]) => o.material = m); drop.forEach(([par, c]) => par.add(c));
    const b64 = await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result.split(',')[1]); fr.readAsDataURL(new Blob([glb])); });
    return { b64, data: { id: P.id, name: P.name, fps: 30, frames: N, K, anim, cam, texts, titles, callouts, beats: P.beats, ttracks, overlay, logo: logoOutline, aspect, lights, mats, matKind, exposure: S.exposure ?? .9 } };
  }, [idx, FULL]);
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(`${out}/scene.glb`, Buffer.from(res.b64, 'base64'));
  fs.writeFileSync(`${out}/anim.json`, JSON.stringify(res.data));
  console.log('ok', res.data.id, 'animated nodes', Object.keys(res.data.anim).length, 'texts', res.data.texts.length, 'labels', res.data.ttracks.length, 'glb MB', (res.b64.length * .75 / 1e6).toFixed(1));
  await b.close();
})();
