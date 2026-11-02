# Сцена логотипа в Blender: геометрия и анимация из ролика, материалы Principled BSDF, свет, камера с глубиной резкости, Eevee.
# blender -b -P build_logo_blend.py -- <папка с scene.glb и anim.json> <out.blend> <шрифт титров> <шрифт моно>
import bpy, json, sys, math, os
from mathutils import Quaternion, Vector, Matrix

args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
src, out, font_title, font_mono = args[:4]
D = json.load(open(f'{src}/anim.json')); N, K = D['frames'], D['K']

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene; sc.name = 'Логотип Е ТВ'
sc.render.fps = 30; sc.frame_start = 1; sc.frame_end = N
sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
bpy.ops.import_scene.gltf(filepath=f'{src}/scene.glb')

def loc(x, y, z): return (x, -z, y)
def quat_node(x, y, z, w): return (w, x, -z, y)
def scl(x, y, z): return (x, z, y)
def lin(c): return tuple(((v + .055) / 1.055) ** 2.4 if v > .04045 else v / 12.92 for v in c)
def hexc(h): return lin((((h >> 16) & 255) / 255, ((h >> 8) & 255) / 255, (h & 255) / 255))
def bag(id_data, name):
    ad = id_data.animation_data_create(); act = bpy.data.actions.new(name)
    slot = act.slots.new(id_type=id_data.id_type, name=id_data.name)
    strip = act.layers.new('Слой').strips.new(type='KEYFRAME'); ad.action = act; ad.action_slot = slot
    return strip.channelbag(slot, ensure=True)
def put(cb, path, index, values, interp=1):
    fc = cb.fcurves.new(path, index=index); fc.keyframe_points.add(len(values))
    co = [0.0] * (2 * len(values))
    for f, v in enumerate(values): co[2 * f] = f + 1; co[2 * f + 1] = v
    fc.keyframe_points.foreach_set('co', co); fc.keyframe_points.foreach_set('interpolation', [interp] * len(values)); fc.update()
def changing(vals): return max(vals) - min(vals) > 1e-5

# ---------- материалы ----------
def principled(name, base, metal=0., rough=.5, coat=0., coat_rough=.1, aniso=0., emit=None, emit_k=0.):
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; b = nt.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*base, 1); b.inputs['Metallic'].default_value = metal; b.inputs['Roughness'].default_value = rough
    b.inputs['Coat Weight'].default_value = coat; b.inputs['Coat Roughness'].default_value = coat_rough; b.inputs['Anisotropic'].default_value = aniso
    if emit: b.inputs['Emission Color'].default_value = (*emit, 1); b.inputs['Emission Strength'].default_value = emit_k
    return m
MAT = {
    'Анодированный циан': principled('Анодированный циан', hexc(0x08a9c9), metal=.92, rough=.3, coat=.35, coat_rough=.25, aniso=.6),
    'Полированный алюминий': principled('Полированный алюминий', hexc(0xe3e9f0), metal=1, rough=.2),
    'Глянцевый графит': principled('Глянцевый графит', hexc(0x06080c), metal=.2, rough=.45, coat=.6, coat_rough=.2),
    'Стена': principled('Стена', hexc(0x080a0f), rough=.95),
    'Свет циан': principled('Свет циан', (0, 0, 0), rough=.4, emit=hexc(0x00d9ff), emit_k=14),
}
for ob in [o for o in bpy.data.objects if o.type == 'MESH']:
    for slot in ob.material_slots:
        if slot.material:
            nm = slot.material.name.split('.')[0]
            if nm in MAT: slot.material = MAT[nm]
# ореол за знаком: светящаяся плоскость с градиентом, прозрачная, сила свечения анимируется
halo = bpy.data.objects.get('Ореол')
if halo:
    old = halo.material_slots[0].material; img = None
    for n in old.node_tree.nodes:
        if n.type == 'TEX_IMAGE': img = n.image
    m = bpy.data.materials.new('Ореол'); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    o = nt.nodes.new('ShaderNodeOutputMaterial'); add = nt.nodes.new('ShaderNodeAddShader'); em = nt.nodes.new('ShaderNodeEmission'); tr = nt.nodes.new('ShaderNodeBsdfTransparent'); mix = nt.nodes.new('ShaderNodeMixShader')
    tex = nt.nodes.new('ShaderNodeTexImage'); tex.image = img
    nt.links.new(tex.outputs['Color'], em.inputs['Color']); nt.links.new(tex.outputs['Alpha'], mix.inputs['Fac'])
    nt.links.new(tr.outputs[0], mix.inputs[1]); nt.links.new(em.outputs[0], mix.inputs[2]); nt.links.new(mix.outputs[0], o.inputs['Surface'])
    em.inputs['Strength'].default_value = 0; em.name = 'Свечение ореола'
    m.surface_render_method = 'BLENDED'; halo.data.materials.clear(); halo.data.materials.append(m)
    op = [v[0] for v in D['mats'].get('Ореол', [[0, 0]])]
    if changing(op): put(bag(m.node_tree, 'Ореол: свечение'), 'nodes["Свечение ореола"].inputs[1].default_value', 0, [3.2 * v for v in op])

# ---------- анимация объектов ----------
for name, arr in D['anim'].items():
    ob = bpy.data.objects.get(name)
    if ob is None: continue
    ob.rotation_mode = 'QUATERNION'; fr = [arr[f * K:(f + 1) * K] for f in range(N)]
    cb = bag(ob, f'{name}: движение')
    L = [loc(*r[0:3]) for r in fr]; Q = [quat_node(*r[3:7]) for r in fr]; Sv = [[c * (1 if r[10] > .5 else 0) for c in scl(*r[7:10])] for r in fr]
    for path, data, n in (('location', L, 3), ('rotation_quaternion', Q, 4), ('scale', Sv, 3)):
        for i in range(n):
            vals = [d[i] for d in data]
            if changing(vals): put(cb, path, i, vals)
            else: getattr(ob, path)[i] = vals[0]

# ---------- надпись «ИГРОВОЙ КАНАЛ»: текстом, гравировка и свечение ----------
fT = bpy.data.fonts.load(font_title); fM = bpy.data.fonts.load(font_mono)
engr = principled('Гравировка', hexc(0x232a35), metal=.4, rough=.45)
for t in D['texts']:
    par = bpy.data.objects.get(t['name'])
    if par is None: continue
    cu = bpy.data.curves.new(t['name'], type='FONT'); cu.body = t['s']; cu.align_x = 'CENTER'; cu.align_y = 'CENTER'
    cu.size = t['h'] * t['px'] / 260; cu.font = fT if t['px'] >= 150 else fM; cu.space_character = 1.3
    ob = bpy.data.objects.new(f"Текст {t['s']}", cu); sc.collection.objects.link(ob); ob.parent = par
    op = t.get('op', [1] * N)
    if changing(op):  # загорающийся слой: циановое свечение по прозрачности из ролика
        m = principled('Надпись: свет', (0, 0, 0), emit=hexc(0x7fe9ff), emit_k=0); ob.data.materials.append(m); ob.location.z = .002
        put(bag(m.node_tree, 'Надпись: свечение'), 'nodes["Principled BSDF"].inputs["Emission Strength"].default_value', 0, [5 * v for v in op])
    else:
        ob.data.materials.append(engr)

# ---------- свет ----------
for name, Lg in D['lights'].items():
    fr = Lg['fr']; r0 = fr[0]
    if Lg['type'] == 'HEMI': continue   # рассеянный свет неба даёт студийный мир ниже
    if Lg['type'] == 'SUN':
        ld = bpy.data.lights.new(name, 'SUN'); ld.energy = r0[6] * 1.0; ld.angle = math.radians(6)
    else:
        ld = bpy.data.lights.new(name, 'POINT'); ld.energy = r0[6] * 4 * math.pi; ld.shadow_soft_size = .25
    ld.color = r0[7:10]
    ob = bpy.data.objects.new(name, ld); sc.collection.objects.link(ob); ob.location = loc(*r0[0:3])
    if Lg['type'] == 'SUN':
        d = Vector(loc(*r0[3:6])) - Vector(loc(*r0[0:3])); ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    else:
        P = [loc(*r[0:3]) for r in fr]
        if any(changing([p[i] for p in P]) for i in range(3)):
            cb = bag(ob, f'{name}: движение')
            for i in range(3): put(cb, 'location', i, [p[i] for p in P])
    en = [r[6] * (1 if Lg['type'] == 'SUN' else 4 * math.pi) for r in fr]
    if changing(en): put(bag(ld, f'{name}: сила'), 'energy', 0, en)

# студийное окружение как в ролике: четыре софтбокса вокруг сцены — процедурно в мире, видны в отражениях и освещении, камера их не видит
def studio_world():
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
    boxes = [  # (азимут от, до, высота от, до, цвет, сила) — положения софтбоксов окружения ролика
        (None, None, R(58), R(91), 0xdfe8f5, 1.6),          # большой верхний
        (R(116), R(192), R(9), R(24), 0xb9c8de, 1.3),       # длинная полоса слева сзади
        (R(-25), R(-7), R(0), R(58), 0x8ea2bf, .8),         # высокая полоса справа
        (R(-118), R(-62), R(4), R(13), 0x6f84a3, .6),       # низкая полоса за камерой
    ]
    acc = None
    for a0, a1, e0, e1, col, k in boxes:
        m = band(el.outputs[0], e0, e1, R(3))
        if a0 is not None: m = mul(m, band(az.outputs[0], a0, a1, R(3)))
        c = N_('ShaderNodeMix'); c.data_type = 'RGBA'; c.inputs['Factor'].default_value = 1
        rgb = N_('ShaderNodeRGB'); rgb.outputs[0].default_value = (*[v * k for v in hexc(col)], 1)
        sm = N_('ShaderNodeMixRGB'); sm.blend_type = 'MULTIPLY'; sm.inputs['Fac'].default_value = 1; Lk(m, sm.inputs['Color1']); Lk(rgb.outputs[0], sm.inputs['Color2'])
        if acc is None: acc = sm.outputs[0]
        else:
            ad = N_('ShaderNodeMixRGB'); ad.blend_type = 'ADD'; ad.inputs['Fac'].default_value = 1; Lk(acc, ad.inputs['Color1']); Lk(sm.outputs[0], ad.inputs['Color2']); acc = ad.outputs[0]
    base = N_('ShaderNodeMixRGB'); base.blend_type = 'ADD'; base.inputs['Fac'].default_value = 1; Lk(acc, base.inputs['Color1']); base.inputs['Color2'].default_value = (*[v * .35 for v in hexc(0x1a2333)], 1)
    bgL = N_('ShaderNodeBackground'); Lk(base.outputs[0], bgL.inputs['Color'])
    bgC = N_('ShaderNodeBackground'); bgC.inputs['Color'].default_value = (*hexc(0x06080c), 1)
    lp = N_('ShaderNodeLightPath'); mx = N_('ShaderNodeMixShader'); Lk(lp.outputs['Is Camera Ray'], mx.inputs['Fac']); Lk(bgL.outputs[0], mx.inputs[1]); Lk(bgC.outputs[0], mx.inputs[2])
    Lk(mx.outputs[0], N_('ShaderNodeOutputWorld').inputs['Surface']); return w
sc.world = studio_world()

# ---------- камера: ключи на каждый кадр, склейки без интерполяции, глубина резкости ----------
QC = Quaternion((math.cos(math.pi / 4), math.sin(math.pi / 4), 0, 0))
cd = bpy.data.cameras.new('Камера'); cd.sensor_fit = 'VERTICAL'; cd.sensor_height = 24; cd.clip_start = .1; cd.clip_end = 300
cam = bpy.data.objects.new('Камера', cd); sc.collection.objects.link(cam); sc.camera = cam; cam.rotation_mode = 'QUATERNION'
C = D['cam']; cb = bag(cam, 'Камера: монтаж')
for i in range(3): put(cb, 'location', i, [loc(*c[0:3])[i] for c in C], 0)
CQ = [tuple(QC @ Quaternion((c[6], c[3], c[4], c[5]))) for c in C]
for i in range(4): put(cb, 'rotation_quaternion', i, [q[i] for q in CQ], 0)
cdb = bag(cd, 'Камера: объектив'); cd.dof.use_dof = True
put(cdb, 'lens', 0, [12 / math.tan(math.radians(c[7]) / 2) for c in C], 0)
put(cdb, 'dof.focus_distance', 0, [c[8] for c in C], 0)
put(cdb, 'dof.aperture_fstop', 0, [max(1.4, min(22, .025 / max(1e-4, c[11]))) for c in C], 0)
if any(c[9] or c[10] for c in C):
    put(cdb, 'shift_x', 0, [c[9] for c in C], 0); put(cdb, 'shift_y', 0, [c[10] for c in C], 0)
step = [0] + [(Vector(C[f][0:3]) - Vector(C[f - 1][0:3])).length for f in range(1, N)] + [0]
cut = 1; sc.timeline_markers.new('План 1', frame=1)
for f in range(1, N):
    if step[f] > .25 and step[f] > 4 * max(step[f - 1], step[f + 1], .02): cut += 1; sc.timeline_markers.new(f'План {cut}', frame=f + 1)
for t, label in D['beats']: sc.timeline_markers.new(label[:60], frame=int(round(t * 30)) + 1)

# ---------- рендер: Eevee, трассировка отражений, размытие в движении, свечение ----------
sc.render.engine = 'BLENDER_EEVEE'; ee = sc.eevee
ee.taa_render_samples = 64; ee.use_raytracing = True
try: ee.ray_tracing_options.resolution_scale = '1'
except Exception: pass
ee.use_shadows = True; sc.render.use_motion_blur = True; sc.render.motion_blur_shutter = .5
sc.view_settings.view_transform = 'AgX'; sc.view_settings.look = 'AgX - Medium High Contrast'; sc.view_settings.exposure = math.log2(D.get('exposure', 1.15)) + .3
try:
    ng = bpy.data.node_groups.new('Свечение', 'CompositorNodeTree'); sc.compositing_node_group = ng
    i_ = ng.nodes.new('CompositorNodeRLayers'); g_ = ng.nodes.new('CompositorNodeGlare'); o_ = ng.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor') if hasattr(ng, 'interface') else None
    go = ng.nodes.new('NodeGroupOutput')
    if 'Type' in g_.inputs: g_.inputs['Type'].default_value = 'Bloom'   # Blender 5.x: тип свечения — вход узла
    else: g_.glare_type = 'BLOOM'
    for k_, v_ in (('Threshold', 1.0), ('Strength', .45), ('Size', .6)):
        if k_ in g_.inputs: g_.inputs[k_].default_value = v_
    ng.links.new(i_.outputs['Image'], g_.inputs['Image']); ng.links.new(g_.outputs['Image'], go.inputs[0])
except Exception as e:
    print('compositor skipped:', e)
sc.render.image_settings.media_type = 'VIDEO'
try: sc.render.image_settings.file_format = 'FFMPEG'; sc.render.ffmpeg.format = 'MPEG4'; sc.render.ffmpeg.codec = 'H264'
except Exception as e: print('ffmpeg', e)
sc.render.filepath = '//ETV_logo_'
for scr in bpy.data.screens:
    for ar in scr.areas:
        if ar.type == 'VIEW_3D':
            for sp in ar.spaces:
                if sp.type == 'VIEW_3D': sp.shading.type = 'MATERIAL'; sp.region_3d.view_perspective = 'CAMERA'
sc.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
print('saved', out, 'objects', len(bpy.data.objects), 'lights', len([o for o in bpy.data.objects if o.type == 'LIGHT']))
