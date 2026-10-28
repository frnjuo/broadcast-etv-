# Сборка аниматика в Blender: геометрия без материалов и света, покадровая анимация, камера со склейками,
# маркеры монтажного листа, титры и сноски текстовыми объектами.
# blender -b -P build_blend.py -- <папка с scene.glb и anim.json> <out.blend> <шрифт титров> <шрифт сносок>
# (или python build_blend.py ... с модулем bpy; нужен Blender 4.4+)
import bpy, json, sys, math
from mathutils import Quaternion, Vector

args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
src, out, font_title, font_mono = args[:4]
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

fT = bpy.data.fonts.load(font_title); fM = bpy.data.fonts.load(font_mono)

# титры: текстовый объект внутри пустышки, которую двигает анимация
for t in D['texts']:
    par = bpy.data.objects.get(t['name'])
    if par is None: continue
    cu = bpy.data.curves.new(f"{t['name']}", type='FONT')
    cu.body = t['s']; cu.align_x = 'CENTER'; cu.align_y = 'CENTER'
    cu.size = t['h'] * t['px'] / 260; cu.extrude = t['depth'] / 2
    cu.font = fT if t['px'] >= 150 else fM
    ob = bpy.data.objects.new(f"Текст {t['s']}"[:60], cu); sc.collection.objects.link(ob); ob.parent = par; ob.color = (.08, .09, .11, 1)

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

# сноски (Гаджетотека): точка на детали, подпись лицом к камере и линия-выноска на крючках
if D['callouts']:
    col = bpy.data.collections.new('Сноски'); sc.collection.children.link(col)
    for i in range(len(D['callouts'][0])):
        c0 = D['callouts'][0][i]
        A = bpy.data.objects.new(f"Сноска {c0['num']} точка", None); A.empty_display_type = 'SPHERE'; A.empty_display_size = .08; col.objects.link(A)
        B = bpy.data.objects.new(f"Сноска {c0['num']} подпись", None); B.empty_display_type = 'PLAIN_AXES'; B.empty_display_size = .1; col.objects.link(B)
        for ob, key in ((A, 'a'), (B, 'b')):
            cbx = bag(ob, f'{ob.name}: движение')
            P = [loc(*D['callouts'][f][i][key]) for f in range(N)]
            V = [1.0 if D['callouts'][f][i]['vis'] else 0.0 for f in range(N)]
            for k in range(3): put(cbx, 'location', k, [p[k] for p in P], LIN)
            for k in range(3): put(cbx, 'scale', k, V, CONST)
        tc = B.constraints.new('TRACK_TO'); tc.target = cam; tc.track_axis = 'TRACK_Z'; tc.up_axis = 'UP_Y'
        cu = bpy.data.curves.new(f"Сноска {c0['num']}", type='FONT'); cu.body = f"{c0['num']}  {c0['title']}\n{c0['sub']}"
        cu.size = .32; cu.align_y = 'CENTER'; cu.font = fM; cu.offset_x = .15
        T = bpy.data.objects.new(f"Сноска {c0['num']} текст", cu); col.objects.link(T); T.parent = B; T.color = (0, .62, .78, 1)
        ln = bpy.data.curves.new(f"Сноска {c0['num']} выноска", type='CURVE'); ln.dimensions = '3D'; ln.bevel_depth = .012
        sp = ln.splines.new('POLY'); sp.points.add(1); sp.points[0].co = (0, 0, 0, 1); sp.points[1].co = (0, 0, 0, 1)
        L = bpy.data.objects.new(f"Сноска {c0['num']} выноска", ln); col.objects.link(L); L.color = (0, .62, .78, 1)
        for k, tgt in enumerate((A, B)):
            h = L.modifiers.new(f'крючок {k}', 'HOOK'); h.object = tgt; h.vertex_indices_set([k])
        # выноска видна вместе со сноской: масштаб 0 стягивает её в точку
        cbl = bag(L, f'{L.name}: видимость'); V = [1.0 if D['callouts'][f][i]['vis'] else 0.0 for f in range(N)]
        for k in range(3): put(cbl, 'scale', k, V, CONST)

# плашка отбивки: в ролике это слой поверх кадра, здесь — текст, привязанный к камере
if D['id'] == 'bumper':
    cu = bpy.data.curves.new('РЕКЛАМА', type='FONT'); cu.body = 'РЕКЛАМА'; cu.size = .024; cu.font = fM
    T = bpy.data.objects.new('Плашка РЕКЛАМА', cu); sc.collection.objects.link(T); T.parent = cam; T.location = (-.435, -.19, -1.0); T.color = (.08, .09, .11, 1)

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
bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
print('saved', out, 'objects', len(bpy.data.objects), 'markers', len(sc.timeline_markers))
