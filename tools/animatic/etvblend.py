# Общие части сборки сцен Е ТВ в Blender (аниматики, полные сцены, логотипы).
# Главное здесь — редкие ключи: покадровая анимация из ролика превращается в несколько ключей Безье на план,
# чтобы камеру и предметы было удобно править руками. Склейки — постоянная интерполяция на последнем ключе плана.
import bpy, math
import numpy as np
from mathutils import Quaternion, Vector, Matrix

QC = Quaternion((math.cos(math.pi / 4), math.sin(math.pi / 4), 0, 0))  # камера three.js смотрит вдоль −Z с верхом +Y; в Blender то же, но мир Z-вверх
def loc(x, y, z): return (x, -z, y)
def quat_node(x, y, z, w): return (w, x, -z, y)
def scl(x, y, z): return (x, z, y)


_BAGS = {}
def bag(id_data, name):
    """Куда писать ключи. Blender 4.4+: действие → слот → слой → полоса → набор каналов; 4.2–4.3: каналы прямо в действии.
    Файлы собираются в 4.2 LTS и открываются в 4.2, 4.5 и 5.x (более новые версии переводят анимацию в слоты сами)."""
    key = id_data.as_pointer()
    if key in _BAGS: return _BAGS[key]   # второй набор ключей того же блока — в то же действие (иначе новое действие заменило бы прежнее)
    ad = id_data.animation_data_create()
    act = bpy.data.actions.new(name)
    if hasattr(act, 'layers') and hasattr(act, 'slots'):
        slot = act.slots.new(id_type=id_data.id_type, name=id_data.name)
        strip = act.layers.new('Слой').strips.new(type='KEYFRAME')
        ad.action = act; ad.action_slot = slot
        _BAGS[key] = strip.channelbag(slot, ensure=True); return _BAGS[key]
    ad.action = act
    _BAGS[key] = act; return act


def put(cb, path, index, values, interp=0):
    """Ключ на каждый кадр (для графики поверх кадра, где значения меняются скачками). interp: 0 — постоянная, 1 — линейная."""
    fc = cb.fcurves.new(path, index=index)
    fc.keyframe_points.add(len(values))
    co = [0.0] * (2 * len(values))
    for f, v in enumerate(values):
        co[2 * f] = f + 1; co[2 * f + 1] = v
    fc.keyframe_points.foreach_set('co', co)
    fc.keyframe_points.foreach_set('interpolation', [interp] * len(values))
    fc.update()
    return fc


# ---------- редкие ключи ----------
def slopes(V, segs):
    """Производная по кадрам внутри каждого плана (на краях плана — односторонняя второго порядка). V: (каналы, кадры)."""
    M = np.zeros_like(V)
    for a, b in segs:
        n = b - a + 1
        if n < 2: continue
        s = V[:, a:b + 1]
        if n == 2:
            M[:, a] = M[:, b] = s[:, 1] - s[:, 0]; continue
        M[:, a + 1:b] = (s[:, 2:] - s[:, :-2]) / 2
        M[:, a] = (-3 * s[:, 0] + 4 * s[:, 1] - s[:, 2]) / 2
        M[:, b] = (3 * s[:, -1] - 4 * s[:, -2] + s[:, -3]) / 2
    return M


def fit_keys(V, segs, tol, max_keys=80):
    """Ключи плана: сначала начало и конец, затем ключ в кадре с наибольшей ошибкой, пока ошибка всех каналов не меньше допуска.
    Между ключами кривая Эрмита с наклонами из ролика — это ровно кривая Безье Blender с ручками на трети промежутка.
    V: (каналы, кадры); tol: (каналы, кадры) — допуск; возвращает списки кадров ключей по планам и наклоны."""
    V = np.asarray(V, dtype=float); tol = np.maximum(np.asarray(tol, dtype=float), 1e-9)
    M = slopes(V, segs)
    out = []
    for a, b in segs:
        ks = [a] if b == a else [a, b]
        while len(ks) < max_keys:
            worst, wf = 1.0, None
            for i, j in zip(ks, ks[1:]):
                if j - i < 2: continue
                f = np.arange(i + 1, j); s = (f - i) / (j - i); h = j - i
                s2, s3 = s * s, s * s * s
                H = (V[:, i, None] * (2 * s3 - 3 * s2 + 1) + h * M[:, i, None] * (s3 - 2 * s2 + s)
                     + V[:, j, None] * (-2 * s3 + 3 * s2) + h * M[:, j, None] * (s3 - s2))
                E = np.max(np.abs(H - V[:, f]) / tol[:, f], axis=0)
                k = int(np.argmax(E))
                if E[k] > worst: worst, wf = float(E[k]), int(f[k])
            if wf is None: break
            ks = sorted(ks + [wf])
        out.append(ks)
    return out, M


def write_curve(cb, path, index, v, m, keysets, segs, group=None):
    """Кривая Безье по найденным ключам: ручки «выровненные», на трети промежутка, наклон из ролика; последний ключ плана перед склейкой — постоянный."""
    try: fc = cb.fcurves.new(path, index=index, action_group=group) if group else cb.fcurves.new(path, index=index)
    except TypeError: fc = cb.fcurves.new(path, index=index)
    allk = [(k, si, i) for si, ks in enumerate(keysets) for i, k in enumerate(ks)]
    fc.keyframe_points.add(len(allk))
    for n, (k, si, i) in enumerate(allk):
        ks = keysets[si]; kp = fc.keyframe_points[n]
        dl = (k - ks[i - 1]) if i > 0 else ((ks[1] - k) if len(ks) > 1 else 1)
        dr = (ks[i + 1] - k) if i < len(ks) - 1 else dl
        val, sl = float(v[k]), float(m[k])
        kp.co = (k + 1, val)
        kp.handle_left_type = 'ALIGNED'; kp.handle_right_type = 'ALIGNED'
        kp.handle_left = (k + 1 - dl / 3, val - sl * dl / 3); kp.handle_right = (k + 1 + dr / 3, val + sl * dr / 3)
        kp.interpolation = 'CONSTANT' if (i == len(ks) - 1 and si < len(segs) - 1) else 'BEZIER'
    fc.update()
    return fc


def sparse(cb, channels, segs, group=None):
    """channels: [(путь, индекс, значения[N], допуск[N] или число)] — общие кадры ключей для всех каналов. Возвращает число ключей."""
    N = len(channels[0][2])
    V = np.array([c[2] for c in channels], dtype=float)
    T = np.array([np.full(N, c[3]) if np.isscalar(c[3]) else np.asarray(c[3], dtype=float) for c in channels])
    keysets, M = fit_keys(V, segs, T)
    for ci, (path, idx, _, _) in enumerate(channels):
        write_curve(cb, path, idx, V[ci], M[ci], keysets, segs, group)
    return sum(len(k) for k in keysets)


def segments_from_jumps(V, rel=12.0, abs_min=1e-3):
    """Планы/участки без скачков: скачок — шаг, намного больший соседних. V: (каналы, кадры)."""
    V = np.asarray(V, dtype=float); N = V.shape[1]
    if N < 3: return [(0, N - 1)]
    step = np.max(np.abs(np.diff(V, axis=1)), axis=0)
    cuts = []
    for f in range(len(step)):
        nb = max(step[f - 1] if f > 0 else 0, step[f + 1] if f + 1 < len(step) else 0)
        if step[f] > abs_min and step[f] > rel * max(nb, 1e-6): cuts.append(f + 1)
    segs, a = [], 0
    for c in cuts: segs.append((a, c - 1)); a = c
    segs.append((a, N - 1))
    return segs


# ---------- камера: объект с целью, редкие ключи, «дыхание» шумом ----------
def camera_rig(sc, C, coll=None, noise=True, dof=True):
    """C — строки камеры из ролика: позиция, кватернион, fov, фокус, смещение, диафрагма, точка взгляда, верх кадра, сила «дыхания», номер плана.
    Камера смотрит на пустышку «Камера · цель» (ограничение «Следить за»), верх кадра задаёт ось Z цели: её поворот = крен и вид сверху.
    Ключи — несколько на план; на склейке значение меняется скачком."""
    N = len(C); coll = coll or sc.collection
    cd = bpy.data.cameras.new('Камера'); cd.sensor_fit = 'VERTICAL'; cd.sensor_height = 24; cd.clip_start = .1; cd.clip_end = 300
    cam = bpy.data.objects.new('Камера', cd); coll.objects.link(cam); sc.camera = cam
    tg = bpy.data.objects.new('Камера · цель', None); tg.empty_display_type = 'ARROWS'; tg.empty_display_size = .6; coll.objects.link(tg)
    con = cam.constraints.new('TRACK_TO'); con.target = tg; con.track_axis = 'TRACK_NEGATIVE_Z'; con.up_axis = 'UP_Y'; con.use_target_z = True; con.name = 'Смотреть на цель'
    has = len(C[0]) > 12
    P = np.array([loc(*c[0:3]) for c in C]).T
    if has:
        Lk = np.array([loc(*c[12:15]) for c in C]).T
        UP = [Vector(loc(*c[15:18])).normalized() for c in C]
    else:
        Lk = np.array([tuple(Vector(loc(*c[0:3])) + (QC @ Quaternion((c[6], c[3], c[4], c[5]))) @ Vector((0, 0, -max(1., c[8])))) for c in C]).T
        UP = [(QC @ Quaternion((c[6], c[3], c[4], c[5]))) @ Vector((0, 1, 0)) for c in C]
    # склейки: скачок позиции, взгляда или угла
    fovs = np.array([c[7] for c in C])
    if has and len(C[0]) > 19:
        sid = [c[19] for c in C]; segs, a = [], 0
        for f in range(1, N):
            if sid[f] != sid[f - 1]: segs.append((a, f - 1)); a = f
        segs.append((a, N - 1))
        # внутри одного «плана» ролика тоже бывают скачки (камера-лифт и т. п. — нет; но на всякий случай)
    else:
        segs = segments_from_jumps(np.vstack([P, Lk, fovs[None] * .2]))
    dist = np.linalg.norm(P - Lk, axis=0)
    tolP = np.maximum(.004, .0025 * dist)
    cb = bag(cam, 'Камера: движение'); cbt = bag(tg, 'Цель: движение')
    # общие кадры ключей камеры и цели: ключ в кадре X задаёт и где камера, и куда смотрит
    V = np.vstack([P, Lk]); T = np.vstack([tolP] * 3 + [tolP * 1.2] * 3)
    keysets, M = fit_keys(V, segs, T)
    for i in range(3): write_curve(cb, 'location', i, V[i], M[i], keysets, segs)
    for i in range(3): write_curve(cbt, 'location', i, V[3 + i], M[3 + i], keysets, segs)
    nk = sum(len(k) for k in keysets)
    # верх кадра → поворот цели (ось Z цели = верх кадра)
    tg.rotation_mode = 'XYZ'
    E, prev = [], None
    for u in UP:
        e = Vector((0, 0, 1)).rotation_difference(u).to_euler('XYZ', prev) if prev else Vector((0, 0, 1)).rotation_difference(u).to_euler('XYZ')
        E.append(tuple(e)); prev = e
    E = np.array(E).T
    if np.ptp(E, axis=1).max() > 1e-4:
        sparse(cbt, [('rotation_euler', i, E[i], .002) for i in range(3)], segs)
    else:
        tg.rotation_euler = tuple(E[:, 0])
    # объектив: фокусное расстояние, дистанция фокуса, диафрагма, смещение (композиция по третям)
    cdb = bag(cd, 'Камера: объектив')
    lens = np.array([12 / math.tan(math.radians(c[7]) / 2) for c in C])
    foc = np.array([max(.1, c[8]) for c in C])
    fst = np.array([max(1.4, min(22, .025 / max(1e-4, c[11]))) for c in C])
    sx = np.array([c[9] for c in C]); sy = np.array([c[10] for c in C])
    chans = [('lens', 0, lens, .05)]
    if dof: chans += [('dof.focus_distance', 0, foc, np.maximum(.01, .006 * foc)), ('dof.aperture_fstop', 0, fst, np.maximum(.02, .02 * fst))]
    if np.abs(sx).max() > 1e-6 or np.abs(sy).max() > 1e-6: chans += [('shift_x', 0, sx, .0004), ('shift_y', 0, sy, .0004)]
    sparse(cdb, chans, segs)
    cd.dof.use_dof = bool(dof)
    # «дыхание» оператора: шум по положению камеры и цели в каждом плане, сила — как в ролике (±0,6 % и ±0,4 % дистанции); на финальном кране сходит на нет
    if noise and has:
        FA = np.array([c[18] for c in C])
        fcs = {}
        for fc in (cb.fcurves if hasattr(cb, 'fcurves') else []): fcs[('c', fc.array_index)] = fc
        for fc in (cbt.fcurves if hasattr(cbt, 'fcurves') else []):
            if fc.data_path == 'location': fcs[('t', fc.array_index)] = fc
        ph = 0
        for si, (a, b) in enumerate(segs):
            fa = FA[a:b + 1]
            if fa.max() < 1e-3: continue
            act = np.where(fa > .3 * fa.max())[0]
            f0, f1 = a + int(act[0]), a + int(act[-1]); amp = float(fa[act].mean())
            for (kind, i), fc in fcs.items():
                ph += 1
                mod = fc.modifiers.new('NOISE')
                mod.scale = 55 + 12 * ((ph * 7) % 5); mod.strength = (.012 if kind == 'c' else .008) * amp; mod.phase = 1 + (ph * 3.7) % 50; mod.offset = (ph * 13) % 400; mod.depth = 1
                mod.use_restricted_range = True; mod.frame_start = f0 + 1; mod.frame_end = f1 + 1
                mod.blend_in = min(8, (f1 - f0) // 4); mod.blend_out = min(8 if f1 < b else 30, (f1 - f0) // 3)
    # маркеры планов
    for si, (a, b) in enumerate(segs): sc.timeline_markers.new(f'План {si + 1}', frame=a + 1)
    print('camera keys', nk, 'shots', len(segs))
    return cam, tg, segs


def sparse_objects(D, N, K, tol_loc=.004, tol_rot=.0015, tol_scl=.003):
    """Предметы: редкие ключи положения, поворота и масштаба; видимость (масштаб 0) и скачки — постоянной интерполяцией."""
    total, dense = 0, 0
    for name, arr in D['anim'].items():
        ob = bpy.data.objects.get(name)
        if ob is None: continue
        ob.rotation_mode = 'QUATERNION'
        fr = [arr[f * K:(f + 1) * K] for f in range(N)]
        L = np.array([loc(*r[0:3]) for r in fr]).T
        Q, prev = [], None
        for r in fr:
            q = Quaternion(quat_node(*r[3:7]))
            if prev is not None and prev.dot(q) < 0: q.negate()
            Q.append(tuple(q)); prev = q
        Q = np.array(Q).T
        S = np.array([[c * (1 if r[10] > .5 else 0) for c in scl(*r[7:10])] for r in fr]).T
        chans = []
        for path, data, n, tl in (('location', L, 3, tol_loc), ('rotation_quaternion', Q, 4, tol_rot), ('scale', S, 3, tol_scl)):
            for i in range(n):
                if np.ptp(data[i]) > 1e-5: chans.append((path, i, data[i], tl * (max(1, np.abs(data[i]).max()) if path == 'scale' else 1)))
                else: getattr(ob, path)[i] = float(data[i][0])
        if not chans: continue
        V = np.array([c[2] for c in chans])
        segs = segments_from_jumps(V, rel=10, abs_min=.02)
        cb = bag(ob, f'{name}: движение')
        total += sparse(cb, chans, segs); dense += N
    print('object keys', total, 'instead of', dense)
