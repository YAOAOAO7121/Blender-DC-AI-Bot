"""
作業健檢：在 Blender 背景模式裡檢查學生的 .blend，輸出 JSON 報告＋預覽圖

由 bot.py 呼叫，學生不用碰這個檔案：
  blender -b --factory-startup --disable-autoexec 學生.blend --python check_blend.py -- 報告.json 預覽.png

單獨測試（在這個資料夾執行）：
  "C:\\Program Files\\Blender Foundation\\Blender 4.2\\blender.exe" -b --factory-startup --disable-autoexec 你的檔案.blend --python check_blend.py -- out.json out.png

--disable-autoexec：學生檔案裡如果藏了會自動執行的 Python 腳本，不讓它跑（安全）
只讀不寫：不會存檔、不會改到學生的檔案
"""
import json
import math
import os
import sys
import traceback

import bpy
import bmesh
from mathutils import Vector
from mathutils.kdtree import KDTree

MAX_DETAIL_VERTS = 300_000   # 單一物件超過這麼多點，就跳過比較花時間的檢查（重複點、法線方向）
DUP_DIST = 1e-5              # 兩個點距離小於這個值，算重疊的點
MAX_LIST = 8                 # 每個問題最多列出幾個物件名稱


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_json = argv[0] if argv else "blend_report.json"
    out_png = argv[1] if len(argv) > 1 else ""
    return out_json, out_png


def ver(t):
    return ".".join(str(x) for x in tuple(t)[:3])


def mesh_stats(obj, depsgraph):
    """回傳這個網格物件的檢查結果"""
    me = obj.data
    r = {"name": obj.name, "verts": len(me.vertices), "faces": len(me.polygons)}

    # 套用修改器之後的三角面數（實際渲染的量）
    try:
        ev = obj.evaluated_get(depsgraph)
        tmp = ev.to_mesh()
        r["tris"] = sum(len(p.vertices) - 2 for p in tmp.polygons)
        ev.to_mesh_clear()
    except Exception:
        r["tris"] = sum(len(p.vertices) - 2 for p in me.polygons)

    r["ngons"] = sum(1 for p in me.polygons if len(p.vertices) > 4)
    if len(me.vertices) > MAX_DETAIL_VERTS:
        r["skipped"] = True
        return r

    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()

    r["loose_verts"] = sum(1 for v in bm.verts if not v.link_edges)
    r["loose_edges"] = sum(1 for e in bm.edges if not e.link_faces)
    # 非流形邊：一條邊連到 3 個以上的面，或是破洞的邊緣（只連 1 個面）
    boundary = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    multi = sum(1 for e in bm.edges if len(e.link_faces) > 2)
    r["boundary_edges"] = boundary
    r["nonmanifold_edges"] = multi
    r["zero_faces"] = sum(1 for f in bm.faces if f.calc_area() < 1e-10)

    # 法線方向不一致：相鄰兩個面的方向相反（is_contiguous=False 但兩邊都只有這兩個面）
    r["flipped_edges"] = sum(1 for e in bm.edges if len(e.link_faces) == 2 and not e.is_contiguous)

    # 封閉的物件：用帶正負號的體積判斷法線是不是整個朝內
    r["inside_out"] = False
    if boundary == 0 and multi == 0 and r["flipped_edges"] == 0 and len(bm.faces) >= 4:
        try:
            vol = bm.calc_volume(signed=True)
            r["inside_out"] = vol < 0
        except Exception:
            pass

    # 重疊的點（Merge by Distance 會合併掉的）
    kd = KDTree(len(bm.verts))
    for v in bm.verts:
        kd.insert(v.co, v.index)
    kd.balance()
    dup = set()
    for v in bm.verts:
        if v.index in dup:
            continue
        for _, idx, _ in kd.find_range(v.co, DUP_DIST):
            if idx != v.index:
                dup.add(idx)
    r["dup_verts"] = len(dup)
    bm.free()
    return r


def check_images():
    """貼圖：沒打包又是外部路徑 → 老師打開會變粉紅色"""
    unpacked, missing, absolute = [], [], []
    for img in bpy.data.images:
        if img.source not in {"FILE", "SEQUENCE", "TILED"} or img.packed_file or not img.users:
            continue
        unpacked.append(img.name)
        raw = img.filepath
        if not raw.startswith("//"):
            absolute.append({"name": img.name, "path": raw})
        if not os.path.exists(bpy.path.abspath(raw)):
            missing.append(img.name)
    return {"unpacked": unpacked, "missing_here": missing, "absolute": absolute}


def frame_camera(scene, objs):
    """場景沒有攝影機時，臨時放一台對準所有物件（只為了出預覽圖，不會存檔）"""
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    if not pts:
        return None
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    center, size = (lo + hi) / 2, max((hi - lo).length, 0.01)
    cam_data = bpy.data.cameras.new("健檢預覽")
    cam = bpy.data.objects.new("健檢預覽", cam_data)
    scene.collection.objects.link(cam)
    direction = Vector((1, -1.2, 0.8)).normalized()
    cam.location = center + direction * size * 1.6
    cam.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    cam_data.clip_end = max(1000, size * 10)
    return cam


def render_preview(scene, path, mesh_objs):
    """用 Workbench 快速出一張小預覽圖（幾秒就好，不用等 Cycles）"""
    cam = scene.camera
    temp = False
    if cam is None:
        cam = frame_camera(scene, [o for o in mesh_objs if o.visible_get()] or mesh_objs)
        if cam is None:
            return "no_objects"
        scene.camera = cam
        temp = True
    r = scene.render
    r.engine = "BLENDER_WORKBENCH"
    r.resolution_x, r.resolution_y, r.resolution_percentage = 800, 450, 100
    r.image_settings.file_format = "PNG"
    r.film_transparent = False
    sh = scene.display.shading
    sh.light = "STUDIO"
    sh.color_type = "MATERIAL"
    r.filepath = path
    bpy.ops.render.render(write_still=True)
    return "temp_camera" if temp else "scene_camera"


def main():
    out_json, out_png = args()
    report = {"ok": True}
    try:
        scene = bpy.context.scene
        depsgraph = bpy.context.evaluated_depsgraph_get()
        objs = list(scene.objects)
        meshes = [o for o in objs if o.type == "MESH"]

        report["file_version"] = ver(bpy.data.version)
        report["blender_version"] = bpy.app.version_string
        report["counts"] = {t: sum(1 for o in objs if o.type == t)
                            for t in sorted({o.type for o in objs})}

        stats = [mesh_stats(o, depsgraph) for o in meshes]
        report["totals"] = {
            "verts": sum(s["verts"] for s in stats),
            "faces": sum(s["faces"] for s in stats),
            "tris": sum(s["tris"] for s in stats),
        }
        report["heaviest"] = [{"name": s["name"], "tris": s["tris"]}
                              for s in sorted(stats, key=lambda s: -s["tris"])[:3]]

        def names(pred):
            return [s["name"] for s in stats if pred(s)]

        report["mesh"] = {
            "dup_verts": [{"name": s["name"], "n": s["dup_verts"]} for s in stats if s.get("dup_verts")][:MAX_LIST],
            "flipped": names(lambda s: s.get("flipped_edges", 0) > 0),
            "inside_out": names(lambda s: s.get("inside_out")),
            "nonmanifold": names(lambda s: s.get("nonmanifold_edges", 0) > 0),
            "loose": names(lambda s: s.get("loose_verts", 0) + s.get("loose_edges", 0) > 0),
            "zero_faces": names(lambda s: s.get("zero_faces", 0) > 0),
            "ngons": sum(s["ngons"] for s in stats),
            "skipped": names(lambda s: s.get("skipped")),
        }

        # 縮放沒套用 / 負的縮放（負的會讓法線整個反過來）
        unapplied, negative = [], []
        for o in meshes:
            sc = o.scale
            if any(v < 0 for v in sc):
                negative.append(o.name)
            elif any(abs(v - 1) > 1e-4 for v in sc):
                unapplied.append({"name": o.name, "scale": [round(v, 3) for v in sc]})
        report["scale"] = {"unapplied": unapplied, "negative": negative}

        # 材質
        report["no_material"] = [o.name for o in meshes
                                 if not any(slot.material for slot in o.material_slots)][:20]

        # 修改器：細分太高（很卡）、還沒套用的布林物件還看得到
        heavy_subsurf, bool_cutters = [], set()
        for o in objs:
            for m in getattr(o, "modifiers", []):
                if m.type == "SUBSURF" and max(m.levels, m.render_levels) >= 4:
                    heavy_subsurf.append({"name": o.name, "levels": m.levels, "render": m.render_levels})
                if m.type == "BOOLEAN" and getattr(m, "object", None):
                    cut = m.object
                    if cut.visible_get() and not cut.hide_render and cut.display_type in {"TEXTURED", "SOLID"}:
                        bool_cutters.add(cut.name)
        report["heavy_subsurf"] = heavy_subsurf
        report["bool_cutters_visible"] = sorted(bool_cutters)

        report["images"] = check_images()

        cam = scene.camera
        report["scene"] = {
            "camera": cam.name if cam else None,
            "lights": sum(1 for o in objs if o.type == "LIGHT"),
            "engine": scene.render.engine,
            "resolution": [scene.render.resolution_x, scene.render.resolution_y,
                           scene.render.resolution_percentage],
            "frames": [scene.frame_start, scene.frame_end],
            "world": bool(scene.world),
        }
        report["has_animation"] = any(o.animation_data and o.animation_data.action for o in objs)

        if out_png:
            try:
                report["preview"] = render_preview(scene, out_png, meshes)
            except Exception as e:
                report["preview"] = "failed"
                report["preview_error"] = repr(e)[:300]
    except Exception:
        report["ok"] = False
        report["error"] = traceback.format_exc()[-1500:]

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)


main()
