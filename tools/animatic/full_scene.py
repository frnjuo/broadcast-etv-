# Полная сцена ролика в Blender: материалы из ролика доводятся до Principled/Emission, яркость и прозрачность по кадрам — редкими ключами,
# свет ролика (ключевой, заполняющий, контровые, прожекторы), студийное окружение, туман, свечение, меняющиеся экраны — атласом кадров,
# титры — текстом с материалом, графика поверх кадра — отдельной сценой без глубины резкости, накладывается в композиторе.
import bpy, math, os
import numpy as np
from mathutils import Vector
import etvblend as EB

GAIN_LED, GAIN_TEX, GAIN_EM = 2.4, 1.15, 1.6   # свечение: светодиоды и линии ярче (как без тон-маппинга в ролике), экраны — около единицы


def lin1(v): return ((v + .055) / 1.055) ** 2.4 if v > .04045 else v / 12.92
def hexc(h): return tuple(lin1(((h >> s) & 255) / 255) for s in (16, 8, 0))
def base(name): return name.split('.')[0]


def set_blend(m):
    for a, v in (('surface_render_method', 'BLENDED'), ('blend_method', 'BLEND'), ('show_transparent_back', False)):
        try: setattr(m, a, v)
        except Exception: pass


def key_curve(id_data, label, path, values, tol, index=0):
    vals = np.asarray(values, dtype=float)
    segs = EB.segments_from_jumps(vals[None], rel=8, abs_min=max(1e-3, .05 * (np.abs(vals).max() + 1e-6)))
    cb = EB.bag(id_data, label)
    return EB.sparse(cb, [(path, index, vals, tol)], segs)


def changing(v): return float(np.ptp(v)) > 1e-4


def vcol_layer(m):
    """Имя цветового атрибута вершин у сеток с этим материалом (панели и экраны архива окрашены по вершинам)."""
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and any(sl.material == m for sl in ob.material_slots):
            ca = getattr(ob.data, 'color_attributes', None)
            if ca and len(ca): return ca[0].name
    return None


def rebuild_unlit(m, arr):
    """Материал без освещения (светодиоды, экраны, свечения): Emission с оттенком из ролика, сила и прозрачность по кадрам."""
    vc = vcol_layer(m)
    img = None
    if m.use_nodes:
        for n in m.node_tree.nodes:
            if n.type == 'TEX_IMAGE' and n.image: img = n.image
    col = arr[:, 2:5]; k = col.max(axis=1); ref = col[int(np.argmax(k))]; hue = ref / max(ref.max(), 1e-6)
    op = arr[:, 0]; gain = GAIN_TEX if img else GAIN_LED
    m.use_nodes = True; nt = m.node_tree; nt.nodes.clear(); N_, L_ = nt.nodes.new, nt.links.new
    out = N_('ShaderNodeOutputMaterial'); out.location = (600, 0)
    em = N_('ShaderNodeEmission'); em.name = em.label = 'Свечение'; em.location = (200, -100); em.inputs['Color'].default_value = (*hue, 1)
    alpha = None
    if img:
        tex = N_('ShaderNodeTexImage'); tex.name = tex.label = 'Картинка'; tex.image = img; tex.location = (-500, 0)
        mul = N_('ShaderNodeMixRGB'); mul.blend_type = 'MULTIPLY'; mul.inputs['Fac'].default_value = 1; mul.location = (-150, 0)
        L_(tex.outputs['Color'], mul.inputs['Color1']); mul.inputs['Color2'].default_value = (*hue, 1); L_(mul.outputs['Color'], em.inputs['Color'])
        if img.alpha_mode != 'NONE' and img.channels == 4: alpha = tex.outputs['Alpha']
    if vc:   # цвет по вершинам умножается на цвет (и картинку)
        va = N_('ShaderNodeVertexColor'); va.layer_name = vc; va.location = (-500, -300)
        mv = N_('ShaderNodeMixRGB'); mv.blend_type = 'MULTIPLY'; mv.inputs['Fac'].default_value = 1; mv.location = (0, -250)
        if em.inputs['Color'].is_linked: L_(em.inputs['Color'].links[0].from_socket, mv.inputs['Color1'])
        else: mv.inputs['Color1'].default_value = (*hue, 1)
        L_(va.outputs['Color'], mv.inputs['Color2']); L_(mv.outputs['Color'], em.inputs['Color'])
    if changing(op) or op.min() < .999:
        ov = N_('ShaderNodeValue'); ov.name = ov.label = 'Непрозрачность'; ov.location = (-150, 250); ov.outputs[0].default_value = float(op[0])
        if alpha is not None:
            mm = N_('ShaderNodeMath'); mm.operation = 'MULTIPLY'; mm.location = (50, 250); L_(alpha, mm.inputs[0]); L_(ov.outputs[0], mm.inputs[1]); alpha = mm.outputs[0]
        else: alpha = ov.outputs[0]
        if changing(op): key_curve(nt, f'{base(m.name)}: прозрачность', 'nodes["Непрозрачность"].outputs[0].default_value', op, .01)
    if alpha is not None:
        tr = N_('ShaderNodeBsdfTransparent'); tr.location = (200, 100); mx = N_('ShaderNodeMixShader'); mx.location = (400, 0)
        L_(alpha, mx.inputs['Fac']); L_(tr.outputs[0], mx.inputs[1]); L_(em.outputs[0], mx.inputs[2]); L_(mx.outputs[0], out.inputs['Surface']); set_blend(m)
    else:
        L_(em.outputs[0], out.inputs['Surface'])
    st = k * gain
    em.inputs['Strength'].default_value = float(st[0])
    if changing(st): key_curve(nt, f'{base(m.name)}: свечение', 'nodes["Свечение"].inputs[1].default_value', st, max(.01, .015 * st.max()))
    return alpha is not None


def lit_anim(m, arr):
    """Материал с освещением: свечение (emissive) и прозрачность по кадрам — ключами на Principled."""
    if not m.use_nodes: return
    b = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if b is None: return
    ei, e = arr[:, 1], arr[:, 5:8]; emk = ei * e.max(axis=1)
    if changing(emk) or emk.max() > 1e-3:
        ref = e[int(np.argmax(emk))]; hue = ref / max(ref.max(), 1e-6)
        if not b.inputs['Emission Color'].is_linked: b.inputs['Emission Color'].default_value = (*hue, 1)
        st = emk * GAIN_EM; b.inputs['Emission Strength'].default_value = float(st[0])
        if changing(st): key_curve(m.node_tree, f'{base(m.name)}: свечение', f'nodes["{b.name}"].inputs["Emission Strength"].default_value', st, max(.01, .015 * st.max()))
    op = arr[:, 0]
    if changing(op):
        # прозрачность: альфа картинки (если есть) × «Непрозрачность» по кадрам; множитель из импорта glTF (прозрачность первого кадра) убирается
        nt = m.node_tree; tex = next((n for n in nt.nodes if n.type == 'TEX_IMAGE' and n.image and any(l.to_node == b or l.to_node.type == 'MATH' for l in n.outputs['Alpha'].links)), None)
        for l in list(b.inputs['Alpha'].links): nt.links.remove(l)
        ov = nt.nodes.new('ShaderNodeValue'); ov.name = ov.label = 'Непрозрачность'; ov.outputs[0].default_value = float(op[0]); ov.location = (b.location.x - 400, b.location.y - 500)
        src = ov.outputs[0]
        if tex is not None:
            mm = nt.nodes.new('ShaderNodeMath'); mm.operation = 'MULTIPLY'; mm.location = (b.location.x - 200, b.location.y - 500)
            nt.links.new(tex.outputs['Alpha'], mm.inputs[0]); nt.links.new(ov.outputs[0], mm.inputs[1]); src = mm.outputs[0]
        nt.links.new(src, b.inputs['Alpha']); set_blend(m)
        key_curve(nt, f'{base(m.name)}: прозрачность', 'nodes["Непрозрачность"].outputs[0].default_value', op, .01)


def cable_pulse(m, P):
    """Кабель с бегущим импульсом (в ролике — шейдер): яркость вдоль кабеля по координате U, голова импульса и заливка по кадрам."""
    if not m.use_nodes: return
    b = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if b is None: return
    nt = m.node_tree; N_, L_ = nt.nodes.new, nt.links.new
    fr = np.array(P['fr'], dtype=float); Lc = float(P['len']); col = P['col']
    def math(op, a, b=None, loc=(0, 0)):
        n = N_('ShaderNodeMath'); n.operation = op; n.location = loc
        for i, x in enumerate((a, b)):
            if x is None: continue
            if isinstance(x, (int, float)): n.inputs[i].default_value = x
            else: L_(x, n.inputs[i])
        return n.outputs[0]
    tc = N_('ShaderNodeTexCoord'); tc.location = (-1400, -400); sp = N_('ShaderNodeSeparateXYZ'); sp.location = (-1200, -400); L_(tc.outputs['UV'], sp.inputs[0]); u = sp.outputs['X']
    hv = N_('ShaderNodeValue'); hv.name = hv.label = 'Голова импульса'; hv.location = (-1200, -200)
    rv = N_('ShaderNodeValue'); rv.name = rv.label = 'Заливка кабеля'; rv.location = (-1200, -600)
    d = math('MULTIPLY', math('SUBTRACT', hv.outputs[0], u, (-1000, -300)), Lc, (-850, -300))
    tail = math('MULTIPLY', math('EXPONENT', math('DIVIDE', math('MAXIMUM', d, 0.0, (-700, -250)), -.7, (-550, -250)), None, (-400, -250)),
                math('EXPONENT', math('MULTIPLY', math('MINIMUM', d, 0.0, (-700, -400)), 9.0, (-550, -400)), None, (-400, -400)), (-250, -300))
    on = math('GREATER_THAN', hv.outputs[0], -.5, (-400, -150))
    fill = math('MULTIPLY', math('LESS_THAN', u, hv.outputs[0], (-400, -550)), rv.outputs[0], (-250, -550))
    e = math('ADD', math('MULTIPLY', math('MULTIPLY', tail, 2.6, (-100, -300)), on, (50, -300)), fill, (200, -400))
    L_(math('MULTIPLY', e, GAIN_EM, (350, -400)), b.inputs['Emission Strength']); b.inputs['Emission Color'].default_value = (*col, 1)
    hv.outputs[0].default_value = float(fr[0, 0]); rv.outputs[0].default_value = float(fr[0, 1])
    if changing(fr[:, 0]): key_curve(nt, f'{base(m.name)}: импульс', 'nodes["Голова импульса"].outputs[0].default_value', fr[:, 0], .002)
    if changing(fr[:, 1]): key_curve(nt, f'{base(m.name)}: заливка', 'nodes["Заливка кабеля"].outputs[0].default_value', fr[:, 1], .005)


def tex_offsets(D):
    """Текстуры, сдвиг которых меняется по ходу ролика (барабаны роликового счётчика): ключи на «Положение» узла Mapping.
    Перевод из three.js/glTF: x = сдвиг x, y = 1 − сдвиг y − повтор y (как это делает импорт glTF в Blender)."""
    for nm, fr in D.get('texOff', {}).items():
        m = next((x for x in bpy.data.materials if base(x.name) == nm), None)
        if m is None or not m.use_nodes: continue
        mp = next((n for n in m.node_tree.nodes if n.type == 'MAPPING'), None)
        if mp is None:
            tex = next((n for n in m.node_tree.nodes if n.type == 'TEX_IMAGE'), None)
            if tex is None: continue
            uv = m.node_tree.nodes.new('ShaderNodeTexCoord'); mp = m.node_tree.nodes.new('ShaderNodeMapping')
            m.node_tree.links.new(uv.outputs['UV'], mp.inputs['Vector']); m.node_tree.links.new(mp.outputs['Vector'], tex.inputs['Vector'])
        mp.name = mp.label = 'Сдвиг текстуры'
        F = np.array(fr, dtype=float)
        mp.inputs['Scale'].default_value = (F[0, 2], F[0, 3], 1)
        X, Y = F[:, 0], 1 - F[:, 1] - F[:, 3]
        cb = EB.bag(m.node_tree, f'{nm}: сдвиг текстуры'); segs = EB.segments_from_jumps(np.vstack([X, Y]), rel=8, abs_min=.02)
        EB.sparse(cb, [('nodes["Сдвиг текстуры"].inputs[1].default_value', 0, X, .0005), ('nodes["Сдвиг текстуры"].inputs[1].default_value', 1, Y, .0005)], segs)
        print('texture offset', nm)


def materials(D):
    mats, kinds = D.get('mats', {}), D.get('matKind', {})
    glow_objs = set()
    for m in list(bpy.data.materials):
        arr = mats.get(base(m.name))
        if not arr: continue
        arr = np.array(arr, dtype=float)
        if arr.shape[1] < 10: arr = np.hstack([arr, np.zeros((arr.shape[0], 10 - arr.shape[1]))])
        if kinds.get(base(m.name)) == 'MeshBasicMaterial':
            if rebuild_unlit(m, arr) or arr[0, 8] > .5: glow_objs.add(m.name)
        else:
            lit_anim(m, arr)
        if base(m.name) in D.get('pulses', {}): cable_pulse(m, D['pulses'][base(m.name)])
    # свечения и прозрачные плоскости не отбрасывают тени
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and any(s.material and s.material.name in glow_objs for s in ob.material_slots):
            try: ob.visible_shadow = False
            except Exception: pass
    print('materials', len(mats))


def dynamic_screens(D, src):
    """Экраны, которые меняются по ходу ролика: все состояния — в одной картинке-атласе (упакована в файл),
    нужная ячейка выбирается сдвигом координат по кадрам (постоянная интерполяция)."""
    for di, d in enumerate(D.get('dyn', [])):
        m = next((x for x in bpy.data.materials if base(x.name) == d['mat']), None)
        if m is None or not m.use_nodes: continue
        tex = next((n for n in m.node_tree.nodes if n.type == 'TEX_IMAGE'), None)
        if tex is None: continue
        ims = [bpy.data.images.load(os.path.join(src, f)) for f in d['files']]
        n = len(ims); w, h = ims[0].size
        cols = math.ceil(math.sqrt(n * h / w)); rows = math.ceil(n / cols)
        k = min(1.0, 8192 / (cols * w), 8192 / (rows * h)); cw, ch = max(8, int(w * k)), max(8, int(h * k))
        if (cw, ch) != (w, h):
            for im in ims: im.scale(cw, ch)
        A = np.zeros((rows * ch, cols * cw, 4), dtype=np.float32)
        for i, im in enumerate(ims):
            px = np.empty(cw * ch * 4, dtype=np.float32); im.pixels.foreach_get(px); px = px.reshape(ch, cw, 4)[::-1]   # картинки текстур в сцене перевёрнуты (так их пишет выгрузка glTF) — состояния экрана тоже
            c, r = i % cols, i // cols; y0 = (rows - 1 - r) * ch
            A[y0:y0 + ch, c * cw:(c + 1) * cw] = px
        at = bpy.data.images.new(f'{d["mat"]}: кадры', cols * cw, rows * ch, alpha=True)
        at.pixels.foreach_set(A.ravel()); at.filepath_raw = os.path.join(src, f'atlas_{di}.png'); at.file_format = 'PNG'; at.save(); at.pack()
        at.colorspace_settings.name = ims[0].colorspace_settings.name
        for im in ims: bpy.data.images.remove(im)
        tex.image = at
        nt = m.node_tree; uv = nt.nodes.new('ShaderNodeTexCoord'); mp = nt.nodes.new('ShaderNodeMapping'); mp.name = mp.label = 'Кадр экрана'
        uv.location = (tex.location.x - 450, tex.location.y); mp.location = (tex.location.x - 250, tex.location.y)
        nt.links.new(uv.outputs['UV'], mp.inputs['Vector']); nt.links.new(mp.outputs['Vector'], tex.inputs['Vector'])
        mp.inputs['Scale'].default_value = (1 / cols, 1 / rows, 1)
        idx = d['idx']; cb = EB.bag(nt, f'{d["mat"]}: кадр экрана')
        fx = cb.fcurves.new('nodes["Кадр экрана"].inputs[1].default_value', index=0); fy = cb.fcurves.new('nodes["Кадр экрана"].inputs[1].default_value', index=1)
        for f, i in enumerate(idx):
            if f and idx[f - 1] == i: continue
            c, r = i % cols, i // cols
            for fc, v in ((fx, c / cols), (fy, (rows - 1 - r) / rows)):
                kp = fc.keyframe_points.insert(f + 1, v); kp.interpolation = 'CONSTANT'
        print('screen atlas', d['mat'], n, 'states', f'{cols}x{rows}')


def lights(sc, D, coll):
    for name, Lg in D.get('lights', {}).items():
        t = Lg['type']; fr = np.array(Lg['fr'], dtype=float)
        if t == 'HEMI': continue
        kind = {'SUN': 'SUN', 'SPOT': 'SPOT'}.get(t, 'POINT')
        ld = bpy.data.lights.new(name, kind)
        sc_e = 1.0 if kind == 'SUN' else 4 * math.pi   # кандела → ватты (так же, как свет считает three.js)
        if kind == 'SUN': ld.angle = math.radians(5)
        else: ld.shadow_soft_size = .3
        if kind == 'SPOT': ld.spot_size = 2 * Lg.get('angle', .5); ld.spot_blend = Lg.get('penumbra', .5)
        if fr[0][10] > 0:
            for a, v in (('use_custom_distance', True), ('cutoff_distance', float(fr[0][10]))):
                try: setattr(ld, a, v)
                except Exception: pass
        ld.color = tuple(fr[0][7:10])
        ob = bpy.data.objects.new(name, ld); coll.objects.link(ob)
        P = np.array([EB.loc(*r[0:3]) for r in fr]).T
        ob.location = tuple(P[:, 0])
        if np.ptp(P, axis=1).max() > 1e-3:
            EB.sparse(EB.bag(ob, f'{name}: движение'), [('location', i, P[i], .01) for i in range(3)], EB.segments_from_jumps(P, rel=10, abs_min=.05))
        if kind in ('SUN', 'SPOT'):
            tg = bpy.data.objects.new(f'{name} · цель', None); tg.empty_display_size = .3; coll.objects.link(tg)
            T = np.array([EB.loc(*r[3:6]) for r in fr]).T; tg.location = tuple(T[:, 0])
            if np.ptp(T, axis=1).max() > 1e-3:
                EB.sparse(EB.bag(tg, f'{name} · цель: движение'), [('location', i, T[i], .01) for i in range(3)], EB.segments_from_jumps(T, rel=10, abs_min=.05))
            c = ob.constraints.new('TRACK_TO'); c.target = tg; c.track_axis = 'TRACK_NEGATIVE_Z'; c.up_axis = 'UP_Y'
        en = fr[:, 6] * sc_e; ld.energy = float(en[0])
        if changing(en): key_curve(ld, f'{name}: сила', 'energy', en, max(.01, .01 * en.max()))


def studio_world(bg):
    """Окружение как в ролике: софтбоксы вокруг сцены — в отражениях и освещении; камера видит цвет фона ролика."""
    w = bpy.data.worlds.new('Студия'); w.use_nodes = True; nt = w.node_tree; nt.nodes.clear()
    N_ = nt.nodes.new; Lk = nt.links.new
    tc = N_('ShaderNodeTexCoord'); sep = N_('ShaderNodeSeparateXYZ'); Lk(tc.outputs['Generated'], sep.inputs[0])
    az = N_('ShaderNodeMath'); az.operation = 'ARCTAN2'; Lk(sep.outputs['Y'], az.inputs[0]); Lk(sep.outputs['X'], az.inputs[1])
    el = N_('ShaderNodeMath'); el.operation = 'ARCSINE'; Lk(sep.outputs['Z'], el.inputs[0])
    def band(sock, lo, hi, soft):
        a = N_('ShaderNodeMapRange'); a.interpolation_type = 'SMOOTHSTEP'; Lk(sock, a.inputs['Value']); a.inputs['From Min'].default_value = lo - soft; a.inputs['From Max'].default_value = lo + soft
        b = N_('ShaderNodeMapRange'); b.interpolation_type = 'SMOOTHSTEP'; Lk(sock, b.inputs['Value']); b.inputs['From Min'].default_value = hi + soft; b.inputs['From Max'].default_value = hi - soft
        m = N_('ShaderNodeMath'); m.operation = 'MULTIPLY'; Lk(a.outputs[0], m.inputs[0]); Lk(b.outputs[0], m.inputs[1]); return m.outputs[0]
    def mul(x, y):
        m = N_('ShaderNodeMath'); m.operation = 'MULTIPLY'; Lk(x, m.inputs[0]); Lk(y, m.inputs[1]); return m.outputs[0]
    R = math.radians
    boxes = [(None, None, R(58), R(91), 0xdfe8f5, 1.3), (R(116), R(192), R(9), R(24), 0xb9c8de, 1.0), (R(-25), R(-7), R(0), R(58), 0x8ea2bf, .6), (R(-118), R(-62), R(4), R(13), 0x6f84a3, .45)]
    acc = None
    for a0, a1, e0, e1, col, k in boxes:
        m = band(el.outputs[0], e0, e1, R(3))
        if a0 is not None: m = mul(m, band(az.outputs[0], a0, a1, R(3)))
        rgb = N_('ShaderNodeRGB'); rgb.outputs[0].default_value = (*[v * k for v in hexc(col)], 1)
        sm = N_('ShaderNodeMixRGB'); sm.blend_type = 'MULTIPLY'; sm.inputs['Fac'].default_value = 1; Lk(m, sm.inputs['Color1']); Lk(rgb.outputs[0], sm.inputs['Color2'])
        if acc is None: acc = sm.outputs[0]
        else:
            ad = N_('ShaderNodeMixRGB'); ad.blend_type = 'ADD'; ad.inputs['Fac'].default_value = 1; Lk(acc, ad.inputs['Color1']); Lk(sm.outputs[0], ad.inputs['Color2']); acc = ad.outputs[0]
    amb = N_('ShaderNodeMixRGB'); amb.blend_type = 'ADD'; amb.inputs['Fac'].default_value = 1; Lk(acc, amb.inputs['Color1']); amb.inputs['Color2'].default_value = (*[v * .3 for v in hexc(0x1a2333)], 1)
    bgL = N_('ShaderNodeBackground'); bgL.name = bgL.label = 'Окружение: свет'; Lk(amb.outputs[0], bgL.inputs['Color']); bgL.inputs['Strength'].default_value = .8
    bgC = N_('ShaderNodeBackground'); bgC.name = bgC.label = 'Фон в кадре'; bgC.inputs['Color'].default_value = (*bg, 1)
    lp = N_('ShaderNodeLightPath'); mx = N_('ShaderNodeMixShader'); Lk(lp.outputs['Is Camera Ray'], mx.inputs['Fac']); Lk(bgL.outputs[0], mx.inputs[1]); Lk(bgC.outputs[0], mx.inputs[2])
    Lk(mx.outputs[0], N_('ShaderNodeOutputWorld').inputs['Surface']); return w


def title_materials(D):
    """Титры: светлые буквы с лёгким свечением (как в ролике — читаются в любом свете), прозрачность по кадрам."""
    op = {t['name']: t.get('op') for t in D.get('texts', [])}
    COL = {'d': (hexc(0xE6EEF8), .32), 'c': (hexc(0x00D9FF), 1.6), 'v': (hexc(0x7A35FF), 1.6)}
    cache = {}
    col = bpy.data.collections.get('Титры')
    if not col: return
    for ob in col.objects:
        if ob.type != 'FONT': continue
        par = ob
        while par.parent is not None and par.parent.name not in op: par = par.parent
        g = par.parent.name if par.parent is not None else None
        ck = ob.get('etv_col', 'd'); key = (g, ck)
        if key not in cache:
            c, ek = COL.get(ck, COL['d'])
            m = bpy.data.materials.new(f'Титр: {g or "текст"}' if ck == 'd' else f'Титр: {g or "текст"} · цвет'); m.use_nodes = True
            b = m.node_tree.nodes['Principled BSDF']; b.inputs['Base Color'].default_value = (*c, 1); b.inputs['Roughness'].default_value = .38
            b.inputs['Emission Color'].default_value = (*c, 1); b.inputs['Emission Strength'].default_value = ek
            o = op.get(g)
            if o and changing(np.array(o)):
                set_blend(m); b.inputs['Alpha'].default_value = float(o[0])
                key_curve(m.node_tree, f'{m.name}: прозрачность', 'nodes["Principled BSDF"].inputs["Alpha"].default_value', o, .01)
            cache[key] = m
        ob.data.materials.clear(); ob.data.materials.append(cache[key])


def overlay_scene(sc, colO, colC):
    """Графика поверх кадра (знак канала, плашка, сноски) — отдельная сцена: плоские цвета, без глубины резкости и тумана;
    композитор основной сцены накладывает её поверх кадра."""
    if colO is None: return None
    so = bpy.data.scenes.new('Графика поверх кадра')
    so.frame_start, so.frame_end = sc.frame_start, sc.frame_end; so.render.fps = sc.render.fps
    so.render.resolution_x, so.render.resolution_y = sc.render.resolution_x, sc.render.resolution_y
    sc.collection.children.unlink(colO); so.collection.children.link(colO); so.collection.children.link(colC)
    so.camera = sc.camera
    # цвета графики — как в ролике (в аниматике они подобраны под серую геометрию): циан, фиолетовый, светлый текст, тёмные карточки
    lin = lambda h: (*hexc(h), 1)
    for ob in colO.all_objects:
        c = tuple(round(v, 2) for v in ob.color[:3])
        if ob.name.startswith('Плашка сноски'): ob.color = lin(0x0A0F18)
        elif ob.name.startswith(('Точка сноски', 'Полоска', 'Рамка', 'Кольцо', 'Выноска', 'Знак канала')) or c == (0.0, .62, .78): ob.color = lin(0x00D9FF)
        elif c == (.36, .18, .86): ob.color = lin(0x7A35FF)
        else: ob.color = lin(0xE6EEF8)
    so.render.engine = 'BLENDER_WORKBENCH'; so.render.film_transparent = True
    sh = so.display.shading; sh.light = 'FLAT'; sh.color_type = 'OBJECT'
    for a, v in (('show_cavity', False), ('show_shadows', False), ('use_dof', False), ('show_object_outline', False)):
        try: setattr(sh, a, v)
        except Exception: pass
    so.display.render_aa = '16'
    so.view_settings.view_transform = 'Standard'
    return so


def compositor(sc, D, so, bloom=True):
    """Туман (по проходу «туман»), свечение ярких мест, тон-маппинг AgX для кадра — и графика поверх уже готового кадра с её точными цветами."""
    vl = sc.view_layers[0]; vl.use_pass_mist = True
    fog = D.get('fog')
    if fog and sc.world:
        sc.world.mist_settings.start = fog['near']; sc.world.mist_settings.depth = fog['far'] - fog['near']; sc.world.mist_settings.falloff = 'LINEAR'
    sc.use_nodes = True; nt = sc.node_tree; nt.nodes.clear(); N_, L_ = nt.nodes.new, nt.links.new
    rl = N_('CompositorNodeRLayers'); rl.scene = sc; rl.location = (-900, 0)
    img = rl.outputs['Image']
    if fog:
        mx = N_('CompositorNodeMixRGB'); mx.name = mx.label = 'Туман'; mx.location = (-650, 0)
        L_(rl.outputs['Mist'], mx.inputs['Fac']); L_(img, mx.inputs[1]); mx.inputs[2].default_value = (*fog['color'], 1); img = mx.outputs[0]
    if bloom:
        gl = N_('CompositorNodeGlare'); gl.name = gl.label = 'Свечение'; gl.location = (-450, 0)
        try: gl.glare_type = 'BLOOM'
        except Exception: gl.glare_type = 'FOG_GLOW'
        gl.threshold = 1.25; gl.size = 7; gl.mix = -.72
        L_(img, gl.inputs['Image']); img = gl.outputs['Image']
    # кадр → AgX (как вид сцены) → обратно в линейное: дальше вид «Стандарт», и графика поверх ложится своими цветами
    ex = N_('CompositorNodeExposure'); ex.name = ex.label = 'Экспозиция'; ex.location = (-250, 0); ex.inputs['Exposure'].default_value = sc.get('etv_exposure', 0.0)
    L_(img, ex.inputs['Image']); img = ex.outputs['Image']
    c1 = N_('CompositorNodeConvertColorSpace'); c1.from_color_space = 'Linear Rec.709'; c1.to_color_space = 'AgX Base sRGB'; c1.location = (-50, 0); c1.label = 'Тон-маппинг AgX'
    c2 = N_('CompositorNodeConvertColorSpace'); c2.from_color_space = 'sRGB'; c2.to_color_space = 'Linear Rec.709'; c2.location = (150, 0)
    L_(img, c1.inputs[0]); L_(c1.outputs[0], c2.inputs[0]); img = c2.outputs[0]
    if so is not None:
        ro = N_('CompositorNodeRLayers'); ro.scene = so; ro.location = (150, -300); ro.label = 'Графика поверх кадра'
        ao = N_('CompositorNodeAlphaOver'); ao.location = (380, 0); L_(img, ao.inputs[1]); L_(ro.outputs['Image'], ao.inputs[2]); img = ao.outputs['Image']
    co = N_('CompositorNodeComposite'); co.location = (600, 0); L_(img, co.inputs['Image'])
    vw = N_('CompositorNodeViewer'); vw.location = (600, -200); L_(img, vw.inputs['Image'])
    sc.view_settings.view_transform = 'Standard'; sc.view_settings.look = 'None'


def render_settings(sc, D):
    try: sc.render.engine = 'BLENDER_EEVEE_NEXT'
    except TypeError: sc.render.engine = 'BLENDER_EEVEE'
    ee = sc.eevee
    for a, v in (('taa_render_samples', 64), ('use_raytracing', True), ('use_shadows', True), ('shadow_ray_count', 2), ('shadow_step_count', 8), ('use_gtao', True), ('fast_gi_method', 'GLOBAL_ILLUMINATION')):
        try: setattr(ee, a, v)
        except Exception: pass
    try: ee.ray_tracing_options.resolution_scale = '1'
    except Exception: pass
    sc.render.use_motion_blur = True; sc.render.motion_blur_shutter = .5
    cy = sc.cycles
    for a, v in (('samples', 128), ('use_denoising', True), ('use_adaptive_sampling', True), ('max_bounces', 8)):
        try: setattr(cy, a, v)
        except Exception: pass
    sc['etv_exposure'] = math.log2(D.get('exposure', 1.15)) + .12
