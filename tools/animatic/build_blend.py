# Сборка аниматика в Blender: геометрия без материалов и света, покадровая анимация, камера со склейками,
# маркеры монтажного листа; все надписи — текстовыми объектами того же шрифта и размера, что в ролике; знак канала — плоской фигурой;
# наложения поверх кадра (знак в углу, плашка, сноски) — объектами, привязанными к камере. Шрифты упаковываются в файл.
# blender -b -P build_blend.py -- <папка с scene.glb и anim.json> <out.blend> <Unbounded ExtraBold> <JetBrains Mono SemiBold> [Inter SemiBold]
# (или python build_blend.py ... с модулем bpy; нужен Blender 4.4+)
import bpy, json, sys, math
from mathutils import Quaternion, Vector, Matrix

args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
src, out, font_title, font_mono = args[:4]
import os
font_body = args[4] if len(args) > 4 else next((p for p in (os.path.join(os.path.dirname(font_title), 'Inter-SemiBold.otf'), '/usr/share/fonts/opentype/inter/Inter-SemiBold.otf') if os.path.exists(p)), font_mono)
D = json.load(open(f'{src}/anim.json'))
N, K = D['frames'], D['K']

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.name = D['name']
sc.render.fps = D['fps']; sc.frame_start = 1; sc.frame_end = N
sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
bpy.ops.import_scene.gltf(filepath=f'{src}/scene.glb')

# без материалов: серый «клей» Workbench
for ob in bpy.data.objects:
    if ob.type == 'MESH':
        ob.data.materials.clear()
for m in list(bpy.data.materials):
    bpy.data.materials.remove(m)
for im in list(bpy.data.images):
    bpy.data.images.remove(im)

QC = Quaternion((math.cos(math.pi / 4), math.sin(math.pi / 4), 0, 0))  # Y-вверх → Z-вверх
def loc(x, y, z): return (x, -z, y)
def quat_node(x, y, z, w): return (w, x, -z, y)
def scl(x, y, z): return (x, z, y)

def bag(id_data, name):
    """Слой действия Blender 4.4+/5.x: action → слот → слой → полоса → набор каналов."""
    ad = id_data.animation_data_create()
    act = bpy.data.actions.new(name)
    slot = act.slots.new(id_type=id_data.id_type, name=id_data.name)
    strip = act.layers.new('Слой').strips.new(type='KEYFRAME')
    ad.action = act; ad.action_slot = slot
    return strip.channelbag(slot, ensure=True)

def put(cb, path, index, values, interp):
    fc = cb.fcurves.new(path, index=index)
    fc.keyframe_points.add(len(values))
    co = [0.0] * (2 * len(values))
    for f, v in enumerate(values):
        co[2 * f] = f + 1; co[2 * f + 1] = v
    fc.keyframe_points.foreach_set('co', co)
    fc.keyframe_points.foreach_set('interpolation', [interp] * len(values))
    fc.update()

LIN, CONST = 1, 0
missing = []
for name, arr in D['anim'].items():
    ob = bpy.data.objects.get(name)
    if ob is None:
        missing.append(name); continue
    ob.rotation_mode = 'QUATERNION'
    fr = [arr[f * K:(f + 1) * K] for f in range(N)]
    cb = bag(ob, f'{name}: движение')
    L = [loc(*r[0:3]) for r in fr]; Q = [quat_node(*r[3:7]) for r in fr]; Sv = [[c * (1 if r[10] > .5 else 0) for c in scl(*r[7:10])] for r in fr]
    # каналы, которые не меняются, не ключуем
    for path, data, n in (('location', L, 3), ('rotation_quaternion', Q, 4), ('scale', Sv, 3)):
        for i in range(n):
            vals = [d[i] for d in data]
            if max(vals) - min(vals) > 1e-5:
                put(cb, path, i, vals, LIN)
            else:
                setattr_val = getattr(ob, path); setattr_val[i] = vals[0]
print('animated', len(D['anim']) - len(missing), 'missing', missing[:10])


# ---------- шрифты ----------
# размер текста в Blender считается от полной высоты глифов шрифта (yMax − yMin), а не от кегля:
# чтобы буквы были того же размера, что в браузере, кегль умножается на этот коэффициент шрифта
from fontTools.ttLib import TTFont as _TT
FPATH = {'T': font_title, 'M': font_mono, 'I': font_body}
FONTS = {k: bpy.data.fonts.load(p) for k, p in FPATH.items()}
def _kf(p): f = _TT(p); h = f['head']; return (h.yMax - h.yMin) / h.unitsPerEm
KF = {k: _kf(p) for k, p in FPATH.items()}
FALLBACK = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'
fFB = bpy.data.fonts.load(FALLBACK) if os.path.exists(FALLBACK) else None
KFB = _kf(FALLBACK) if fFB else 1.0
_CM = {}
def cmap(p):
    if p not in _CM: _CM[p] = _TT(p).getBestCmap()
    return _CM[p]
def runs_of(text, fkey):
    # символы, которых нет в шрифте (▸, ▍), набираются запасным шрифтом, как это делает браузер
    if not fFB: return [(text, False)]
    cm, out = cmap(FPATH[fkey]), []
    for ch in text:
        fb = ord(ch) not in cm and ord(ch) in cmap(FALLBACK)
        if out and out[-1][1] == fb: out[-1] = (out[-1][0] + ch, fb)
        else: out.append((ch, fb))
    return out
def _w(body, font, size, space):
    cu = bpy.data.curves.new('_измер', type='FONT'); cu.body = body; cu.font = font; cu.size = size; cu.space_character = space
    ob = bpy.data.objects.new('_измер', cu); sc.collection.objects.link(ob); bpy.context.view_layer.update(); w = ob.dimensions.x
    bpy.data.objects.remove(ob); bpy.data.curves.remove(cu); return w
def adv(text, font, size, space):
    # ширина набора в Blender: строка с концевым знаком минус ширина знака — так учитываются пробелы и интервал после последней буквы
    return _w(text + 'Ш', font, size, space) - _w('Ш', font, size, space)
def ktext(name, s, fkey, em, wem, lsem=0.0, shear=0.0):
    """Текстовый объект: тот же шрифт, кегль em, межбуквенный интервал и ширина строки (по измерению браузера) — wem в кеглях.
    Начало координат — левый край первой буквы на базовой линии. Возвращает объект (с дочерними для запасного шрифта)."""
    rs = runs_of(s, fkey); objs, x0 = [], 0.0
    for r, fb in rs:
        font, k = (fFB, KFB) if fb else (FONTS[fkey], KF[fkey]); size = em * k
        cu = bpy.data.curves.new(f'{name} · {r}' if objs else name, type='FONT'); cu.body = r; cu.font = font; cu.size = size
        cu.align_x = 'LEFT'; cu.align_y = 'BOTTOM_BASELINE'; cu.shear = max(-1.0, min(1.0, shear))
        # в Blender интервал добавляет (space − 1) · size / 2 на каждый знак; в браузере — lsem · em
        cu.space_character = sp = max(0.0, 1 + 2 * lsem * em / size)
        objs.append((cu, adv(r, font, size, sp), size, len(r)))
    # браузер применяет кернинг, Blender нет: ширина строки подгоняется под измеренную в браузере
    if len(objs) == 1 and objs[0][3] > 1 and wem > 0:
        cu, a, size, n = objs[0]; cu.space_character = max(0.0, cu.space_character + 2 * (wem * em - a) / (n * size))
    root = None
    for cu, a, size, n in objs:
        ob = bpy.data.objects.new(cu.name, cu)
        if root is None: root = ob
        else: ob.parent = root; ob.location = (x0, 0, 0)
        x0 += a
    return root, [o for o in bpy.data.objects if o == root or o.parent == root]
def link(objs, coll, col):
    for o in objs: coll.objects.link(o); o.color = col
# знак Е: контур из ролика (нормирован на высоту 1, центр в нуле)
LOGO = D.get('logo')
def logo_curve(name, fill=True, lw=0.0):
    cu = bpy.data.curves.new(name, type='CURVE'); cu.dimensions = '2D'; cu.fill_mode = 'BOTH' if fill else 'NONE'
    if not fill: cu.bevel_depth = lw / 2
    sp = cu.splines.new('POLY'); sp.points.add(len(LOGO) - 1)
    for i, (x, y) in enumerate(LOGO): sp.points[i].co = (x, y, 0, 1)
    sp.use_cyclic_u = True; return cu
TCOL = {'d': (.12, .13, .15, 1), 'c': (0, .62, .78, 1), 'v': (.36, .18, .86, 1)}
DARK = (.08, .09, .11, 1)
def basis(xa, ya):
    x, y = Vector(loc(*xa)), Vector(loc(*ya)); return Matrix((x, y, x.cross(y))).transposed()

# ---------- титры: текст внутри пустышки, которую двигает анимация; положение, кегль, наклон и ширина — с холста ролика ----------
colT = bpy.data.collections.new('Титры'); sc.collection.children.link(colT)
for t in D.get('titles', []):
    par = bpy.data.objects.get(t['name'])
    if par is None: continue
    for p in t['parts']:
        ob, objs = ktext(f"Текст {p['s']}"[:60], p['s'], p['font'], p['em'], p['wem'], p['lsem'], p['shear'])
        B = basis(p['xa'], p['ya']); nz = B.col[2]
        for o in objs:
            if t['depth']: o.data.extrude = t['depth'] / 2
        link(objs, colT, DARK)
        ob.parent = par; ob.matrix_parent_inverse = Matrix.Identity(4); ob.rotation_mode = 'QUATERNION'
        ob.location = Vector(loc(*p['P'])) - nz * (t['depth'] / 2); ob.rotation_quaternion = B.to_quaternion(); ob.scale = (p['sx'], 1, 1)

# ---------- надписи и знак на экранах, табло, бланках, этикетках: на тех же местах, по кадрам ----------
def keyed(ob, frames, still, mk):
    """Покадровое положение объекта: mk(fr) → (location, quaternion, scale)."""
    ob.rotation_mode = 'QUATERNION'
    if still:
        p, q, s = mk(frames[0]); ob.location = p; ob.rotation_quaternion = q; ob.scale = s; return
    vals, prev = [], None
    for fr in frames:
        p, q, s = mk(fr)
        if prev is not None and prev.dot(q) < 0: q.negate()
        vals.append((p, q, s)); prev = q
    cbt = bag(ob, f'{ob.name}: движение')
    for i in range(3): put(cbt, 'location', i, [v[0][i] for v in vals], LIN)
    for i in range(4): put(cbt, 'rotation_quaternion', i, [v[1][i] for v in vals], LIN)
    for i in range(3): put(cbt, 'scale', i, [v[2][i] for v in vals], CONST)
if D.get('ttracks'):
    colL = bpy.data.collections.new('Надписи'); sc.collection.children.link(colL)
    for t in D['ttracks']:
        if t.get('type') == 'logo':
            ob = bpy.data.objects.new('Знак Е на экране', logo_curve('Знак Е на экране', t['mode'] == 'fill', t.get('lw', 0))); link([ob], colL, TCOL.get(t['col'], DARK) if t['col'] != 'd' else DARK)
            base = t['size']
        else:
            ob, objs = ktext(f"Надпись {t['s'][:40]}", t['s'], t['font'], t['size'], t['wem'], t['lsem'], t['shear']); link(objs, colL, TCOL[t['col']])
            base = 1.0
        sx = t.get('sx', 1)
        def mk(fr, base=base, sx=sx):
            v = fr[9] * (1.0 if fr[10] > .5 else 0.0) * base
            return Vector(loc(*fr[0:3])), basis(fr[3:6], fr[6:9]).to_quaternion(), (v * sx, v, v)
        keyed(ob, t['fr'], t['still'], mk)
    print('labels', len(D['ttracks']))
# плоские знаки из геометрии — знак Е, вытравленный в стекле консоли, запятая на счётчике итога — тёмным, как титры, чтобы читались на сером
for ob in bpy.data.objects:
    if ob.name.startswith(('Знак Е', 'Запятая')) and ob.type == 'MESH': ob.color = DARK

# камера: покадровые ключи, склейки — постоянная интерполяция
cd = bpy.data.cameras.new('Камера'); cd.sensor_fit = 'VERTICAL'; cd.sensor_height = 24; cd.clip_start = .1; cd.clip_end = 300
cam = bpy.data.objects.new('Камера', cd); sc.collection.objects.link(cam); sc.camera = cam; cam.rotation_mode = 'QUATERNION'
C = D['cam']
cb = bag(cam, 'Камера: монтаж')
CL = [loc(*c[0:3]) for c in C]
CQ = [tuple(QC @ Quaternion((c[6], c[3], c[4], c[5]))) for c in C]
for i in range(3): put(cb, 'location', i, [v[i] for v in CL], CONST)
for i in range(4): put(cb, 'rotation_quaternion', i, [v[i] for v in CQ], CONST)
cdb = bag(cd, 'Камера: объектив')
put(cdb, 'lens', 0, [12 / math.tan(math.radians(c[7]) / 2) for c in C], CONST)
put(cdb, 'dof.focus_distance', 0, [c[8] for c in C], CONST)
# смещение объектива: композиция по третям, как в ролике
if any(len(c) > 9 and (c[9] or c[10]) for c in C):
    put(cdb, 'shift_x', 0, [c[9] if len(c) > 9 else 0 for c in C], CONST)
    put(cdb, 'shift_y', 0, [c[10] if len(c) > 9 else 0 for c in C], CONST)
cd.dof.use_dof = False

# маркеры: склейки планов и события монтажного листа
# склейка — скачок камеры, заметно больший, чем движение в соседних кадрах
step = [0] + [(Vector(C[f][0:3]) - Vector(C[f - 1][0:3])).length + abs(C[f][7] - C[f - 1][7]) * .2 for f in range(1, N)] + [0]
cut = 1; sc.timeline_markers.new('План 1', frame=1)
for f in range(1, N):
    if step[f] > .25 and step[f] > 4 * max(step[f - 1], step[f + 1], .02):
        cut += 1; sc.timeline_markers.new(f'План {cut}', frame=f + 1)
for t, label in D['beats']:
    sc.timeline_markers.new(label[:60], frame=int(round(t * 30)) + 1)


# ---------- наложения поверх кадра: знак канала в углу, плашка, сноски ----------
# пустышка «Наложение» — дочерняя камере, на расстоянии d перед объективом; её масштаб — ширина кадра на этом расстоянии,
# с поправкой на угол обзора и смещение объектива в каждом кадре; внутри — координаты в долях ширины кадра от центра, y вверх
OV = D.get('overlay') or {'texts': [], 'shapes': []}
if OV['texts'] or OV['shapes']:
    colO = bpy.data.collections.new('Наложение'); sc.collection.children.link(colO)
    root = bpy.data.objects.new('Наложение', None); root.empty_display_type = 'PLAIN_AXES'; root.empty_display_size = .05; colO.objects.link(root); root.parent = cam
    d, asp = .5, D.get('aspect', 16 / 9)
    Wv = [2 * d * math.tan(math.radians(c[7]) / 2) * asp for c in C]
    cbr = bag(root, 'Наложение: кадр')
    put(cbr, 'location', 0, [(c[9] if len(c) > 9 else 0) * w for c, w in zip(C, Wv)], CONST)
    put(cbr, 'location', 1, [(c[10] if len(c) > 9 else 0) * w for c, w in zip(C, Wv)], CONST)
    put(cbr, 'location', 2, [-d] * N, CONST)
    for i in range(3): put(cbr, 'scale', i, Wv, CONST)
    def full(t):
        return t['fr'] if not t['still'] else [t['fr'][0]] * N
    def keyloc(ob, name, F, xy, vis, sc_=lambda fr: 1.0, z=0.0):
        cb_ = bag(ob, name)
        put(cb_, 'location', 0, [xy(fr)[0] for fr in F], CONST); put(cb_, 'location', 1, [xy(fr)[1] for fr in F], CONST); ob.location.z = z
        S_ = [sc_(fr) * (1.0 if vis(fr) else 0.0) for fr in F]
        for i in range(3): put(cb_, 'scale', i, S_, CONST)
    LIGHT = (.92, .95, .98, 1)
    for t in OV['texts']:
        ob, objs = ktext(f"Наложение {t['s'][:40]}", t['s'], t['font'], t['em'], t['wem'], t['lsem'])
        link(objs, colO, (TCOL['c'] if t['col'] == 'c' else LIGHT) if t['card'] else TCOL.get(t['col'], DARK))
        ob.parent = root; F = full(t)
        keyloc(ob, f'{ob.name}: кадры', F, lambda fr: fr[0:2], lambda fr: fr[2] > .5)
    for t in OV['shapes']:
        F = full(t); vis_frames = [fr for fr in F if fr[-1] > .5]
        if not vis_frames: continue
        f0 = vis_frames[0]
        if t['type'] == 'logo':
            ob = bpy.data.objects.new('Знак канала', logo_curve('Знак канала')); link([ob], colO, TCOL['c']); ob.parent = root
            keyloc(ob, 'Знак канала: кадры', F, lambda fr: fr[0:2], lambda fr: fr[3] > .5, lambda fr: fr[2])
        elif t['type'] == 'rect':
            w, h = f0[2] - f0[0], f0[1] - f0[3]
            if t.get('fill') == 'd' or (t.get('fill') and h < .004):
                me = bpy.data.meshes.new('Плашка'); me.from_pydata([(-.5, -.5, 0), (.5, -.5, 0), (.5, .5, 0), (-.5, .5, 0)], [], [(0, 1, 2, 3)])
                ob = bpy.data.objects.new('Плашка сноски' if t['fill'] == 'd' else 'Полоска', me); link([ob], colO, (.1, .12, .16, 1) if t['fill'] == 'd' else TCOL['c']); ob.parent = root
                ob.location.z = -.0006   # чуть дальше от объектива, чем текст карточки
                cb_ = bag(ob, f'{ob.name}: кадры'); V_ = [1.0 if fr[4] > .5 else 0.0 for fr in F]
                put(cb_, 'location', 0, [(fr[0] + fr[2]) / 2 for fr in F], CONST); put(cb_, 'location', 1, [(fr[1] + fr[3]) / 2 for fr in F], CONST)
                put(cb_, 'scale', 0, [(fr[2] - fr[0]) * v for fr, v in zip(F, V_)], CONST); put(cb_, 'scale', 1, [(fr[1] - fr[3]) * v for fr, v in zip(F, V_)], CONST); put(cb_, 'scale', 2, V_, CONST)
            if t.get('border', 0) > 0:
                cu = bpy.data.curves.new('Рамка', type='CURVE'); cu.dimensions = '2D'; cu.bevel_depth = t['border'] / 2
                sp = cu.splines.new('POLY'); sp.points.add(3)
                for i, (x, y) in enumerate(((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))): sp.points[i].co = (x, y, 0, 1)
                sp.use_cyclic_u = True
                ob = bpy.data.objects.new('Рамка сноски', cu); link([ob], colO, TCOL['c']); ob.parent = root
                keyloc(ob, 'Рамка: кадры', F, lambda fr: ((fr[0] + fr[2]) / 2, (fr[1] + fr[3]) / 2), lambda fr: fr[4] > .5)
        elif t['type'] == 'circle':
            r0 = max(1e-4, max(fr[2] for fr in vis_frames))
            cu = bpy.data.curves.new('Кольцо', type='CURVE'); cu.dimensions = '2D'; cu.resolution_u = 24
            sp = cu.splines.new('POLY'); M_ = 48; sp.points.add(M_ - 1)
            for i in range(M_): a = 2 * math.pi * i / M_; sp.points[i].co = (math.cos(a), math.sin(a), 0, 1)
            sp.use_cyclic_u = True
            if t.get('fillc'): cu.fill_mode = 'BOTH'
            else: cu.fill_mode = 'NONE'; cu.bevel_depth = t['sw'] / 2 / r0
            ob = bpy.data.objects.new('Точка сноски' if t.get('fillc') else 'Кольцо сноски', cu); link([ob], colO, TCOL['c'] if not t.get('fillc') else DARK); ob.parent = root
            keyloc(ob, f'{ob.name}: кадры', F, lambda fr: fr[0:2], lambda fr: fr[3] > .5 and fr[2] > 1e-5, lambda fr: fr[2])
        elif t['type'] == 'line':
            cu = bpy.data.curves.new('Выноска', type='CURVE'); cu.dimensions = '3D'; cu.bevel_depth = t['sw'] / 2; cu.bevel_factor_mapping_end = 'SPLINE'
            sp = cu.splines.new('POLY'); sp.points.add(2)
            ob = bpy.data.objects.new('Выноска сноски', cu); link([ob], colO, TCOL['c']); ob.parent = root
            for k in range(3):
                hk = bpy.data.objects.new(f'Выноска · точка {k + 1}', None); hk.empty_display_size = .004; colO.objects.link(hk); hk.parent = root
                cbh = bag(hk, f'{hk.name}: кадры'); put(cbh, 'location', 0, [fr[2 * k] for fr in F], CONST); put(cbh, 'location', 1, [fr[2 * k + 1] for fr in F], CONST)
                h = ob.modifiers.new(f'крючок {k + 1}', 'HOOK'); h.object = hk; h.vertex_indices_set([k])
            cbl = bag(cu, 'Выноска: прорисовка'); put(cbl, 'bevel_factor_end', 0, [fr[6] if fr[7] > .5 else 0.0 for fr in F], CONST)
    print('overlay', len(OV['texts']), len(OV['shapes']))

# без материалов: у объектов только цвет вьюпорта — серая геометрия, тёмные титры, циановые сноски
for ob in bpy.data.objects:
    if ob.type in ('MESH', 'CURVE') and tuple(ob.color) == (1, 1, 1, 1):
        ob.color = (.74, .74, .74, 1)
w = bpy.data.worlds.new('Фон'); w.color = (.5, .51, .53); sc.world = w

# вид: Workbench, студийный свет вьюпорта; 3D-вид смотрит через камеру
sc.render.engine = 'BLENDER_WORKBENCH'
sh = sc.display.shading; sh.light = 'STUDIO'; sh.color_type = 'OBJECT'; sh.show_cavity = True
sc.display.render_aa = 'FXAA'
for scr in bpy.data.screens:
    for ar in scr.areas:
        if ar.type == 'VIEW_3D':
            for sp in ar.spaces:
                if sp.type == 'VIEW_3D':
                    sp.shading.type = 'SOLID'; sp.shading.color_type = 'OBJECT'; sp.region_3d.view_perspective = 'CAMERA'
try:
    sc.render.image_settings.media_type = 'VIDEO'
except Exception:
    pass
try:
    sc.render.image_settings.file_format = 'FFMPEG'; sc.render.ffmpeg.format = 'MPEG4'; sc.render.ffmpeg.codec = 'H264'
except Exception as e:
    print('ffmpeg settings', e)
sc.render.filepath = f"//аниматик_{D['id']}_"
sc.frame_set(1)
# шрифты внутри файла: открывается на любом компьютере с теми же шрифтами, что в ролике
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
print('saved', out, 'objects', len(bpy.data.objects), 'markers', len(sc.timeline_markers))
