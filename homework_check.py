"""
作業健檢：學生丟 .blend → 背景開 Blender 跑 blend_check/check_blend.py → 整理成報告

- 不會開 Blender 視窗，也不會改到學生的檔案（在暫存資料夾裡檢查，檢查完就刪掉）
- 一次只檢查一個檔案（排隊），避免同時開好幾個 Blender 把電腦拖慢
- Blender 路徑：.env 的 BLENDER_PATH；沒填就自動找 PATH 和 C:\\Program Files\\Blender Foundation\\

單獨測試（不用開 Discord）：
  python homework_check.py 你的作業.blend
"""
import asyncio
import glob
import json
import os
import re
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(BASE, "blend_check", "check_blend.py")
TIMEOUT = int(os.getenv("BLEND_TIMEOUT", "180"))          # 秒；超過就放棄（檔案太大或卡住）
MAX_MB = int(os.getenv("BLEND_MAX_MB", "100"))

_lock = asyncio.Semaphore(1)
_waiting = 0


def find_blender():
    path = os.getenv("BLENDER_PATH", "").strip().strip('"')
    if path:
        return path if os.path.isfile(path) else None
    found = shutil.which("blender")
    if found:
        return found
    cands = glob.glob(r"C:\Program Files\Blender Foundation\Blender*\blender.exe")
    if not cands:
        return None

    def version(p):
        m = re.search(r"Blender\s*([\d.]+)", p)
        return tuple(int(x) for x in m.group(1).split(".") if x) if m else ()
    return max(cands, key=version)


def queue_size():
    return _waiting


async def run_check(blend_bytes, filename):
    """回傳 (報告 dict, 預覽圖路徑或 None, 暫存資料夾)；用完要呼叫 cleanup(暫存資料夾)"""
    global _waiting
    blender = find_blender()
    if not blender:
        raise RuntimeError("找不到 Blender，請在 .env 設定 BLENDER_PATH")
    tmp = tempfile.mkdtemp(prefix="blendcheck_")
    safe = re.sub(r'[\\/:*?"<>|]+', "_", filename) or "homework.blend"
    blend = os.path.join(tmp, safe)
    out_json = os.path.join(tmp, "report.json")
    out_png = os.path.join(tmp, "preview.png")
    with open(blend, "wb") as f:
        f.write(blend_bytes)

    try:
        return await _run(blender, blend, out_json, out_png, tmp)
    except BaseException:
        cleanup(tmp)
        raise


async def _run(blender, blend, out_json, out_png, tmp):
    global _waiting
    out = b""
    _waiting += 1
    try:
        async with _lock:
            proc = await asyncio.create_subprocess_exec(
                blender, "-b", "--factory-startup", "--disable-autoexec", blend,
                "--python", SCRIPT, "--", out_json, out_png,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=tmp)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError(f"檢查超過 {TIMEOUT} 秒，檔案可能太大")
    finally:
        _waiting -= 1

    if not os.path.exists(out_json):
        tail = (out or b"").decode("utf-8", "replace")[-800:]
        raise RuntimeError(f"Blender 沒有產生報告（檔案可能壞掉或不是 .blend）\n{tail}")
    with open(out_json, encoding="utf-8") as f:
        report = json.load(f)
    preview = out_png if os.path.exists(out_png) else None
    return report, preview, tmp


def cleanup(tmp):
    shutil.rmtree(tmp, ignore_errors=True)


# ───────────── 報告文字 ─────────────

def _names(items, n=4):
    items = [i["name"] if isinstance(i, dict) else i for i in items]
    s = "、".join(f"`{x}`" for x in items[:n])
    return s + (f" 等 {len(items)} 個" if len(items) > n else "")


def _num(n):
    return f"{n / 10000:.1f} 萬" if n >= 10000 else str(n)


def format_report(r, filename):
    """回傳 (報告文字, 給 log 的一行摘要)"""
    if not r.get("ok"):
        return ("這個檔案我打開的時候出錯了QQ 可能檔案壞掉 或是用比較新的 Blender 存的\n"
                "可以再存一次檔重傳 或直接拿去問老師/助教唷",
                "檢查失敗")

    must, should = [], []
    img = r["images"]
    if img["unpacked"]:
        line = f"**貼圖沒有打包**：{_names(img['unpacked'])}\n　→ 別人打開會變**粉紅色**！`File → External Data → Pack Resources`（舊版叫 Pack All Into .blend）然後再存檔"
        if img["absolute"]:
            line += f"\n　（路徑是你電腦上的位置，例如 `{img['absolute'][0]['path'][:60]}`，換台電腦一定找不到）"
        must.append(line)

    sc, mesh = r["scale"], r["mesh"]
    if sc["negative"]:
        must.append(f"**縮放是負的**：{_names(sc['negative'])}\n　→ 法線會整個反過來。物件模式 `Ctrl+A → Scale` 套用後，進編輯模式 `A` 全選 → `Shift+N`")
    flipped = list(dict.fromkeys(mesh["inside_out"] + mesh["flipped"]))
    if flipped:
        must.append(f"**法線方向不對**：{_names(flipped)}\n　→ 編輯模式 `A` 全選 → `Shift+N`（Recalculate Outside）；打開 `Overlays → Face Orientation` 看，紅色就是反面")

    if sc["unapplied"]:
        should.append(f"**縮放還沒套用**：{_names(sc['unapplied'])}\n　→ 倒角、修改器、UV 會怪怪的。物件模式選起來 `Ctrl+A → Scale`")
    if mesh["dup_verts"]:
        total = sum(d["n"] for d in mesh["dup_verts"])
        should.append(f"**有 {total} 個重疊的點**：{_names(mesh['dup_verts'])}\n　→ 編輯模式 `A` 全選 → `M → By Distance`")
    if r["bool_cutters_visible"]:
        should.append(f"**布林用的刀具物件還看得到**：{_names(r['bool_cutters_visible'])}\n　→ 算圖會被拍進去。選它 → `Object Properties → Viewport Display → Display As: Wire`，`Visibility` 取消 Renders")
    if r["heavy_subsurf"]:
        s = r["heavy_subsurf"][0]
        should.append(f"**細分層數很高**：{_names(r['heavy_subsurf'])}（Levels {s['levels']}／Render {s['render']}）\n　→ 很吃效能，`Levels Viewport` 調到 1～2 通常就夠")
    if mesh["nonmanifold"]:
        should.append(f"**有非流形的邊**（一條邊接 3 個以上的面）：{_names(mesh['nonmanifold'])}\n　→ 要 3D 列印一定要修。編輯模式 `Select → Select All by Trait → Non Manifold` 找出來")
    if mesh["loose"]:
        should.append(f"**有沒連到面的散點/散邊**：{_names(mesh['loose'])}\n　→ `Select → Select All by Trait → Loose Geometry` 然後 `X` 刪掉")
    if mesh["zero_faces"]:
        should.append(f"**有面積是 0 的面**：{_names(mesh['zero_faces'])}\n　→ `Mesh → Clean Up → Degenerate Dissolve`")
    meshes = r["counts"].get("MESH", 0)
    if r["no_material"] and len(r["no_material"]) >= meshes:
        should.append("**場景裡的物件都還沒有材質**\n　→ 純建模作業可以不管；要上色的話 `Material Properties → New`")
    elif r["no_material"]:
        should.append(f"**沒有材質**：{_names(r['no_material'])}\n　→ 如果作業要上色，`Material Properties → New`")
    scene = r["scene"]
    if not scene["camera"]:
        should.append("**場景沒有攝影機**\n　→ 要算圖的話 `Shift+A → Camera`，調好視角按 `Ctrl+Alt+Numpad0` 對準目前畫面")
    elif scene["lights"] == 0 and scene["engine"] != "BLENDER_WORKBENCH":
        should.append("**場景沒有燈光**\n　→ 如果沒用 HDRI 環境光，算出來可能是黑的。`Shift+A → Light`")
    if r["totals"]["tris"] > 1_000_000:
        h = r["heaviest"][0]
        should.append(f"**面數有點多**（{_num(r['totals']['tris'])} 個三角面，最重的是 `{h['name']}`）\n　→ 檔案會很卡，檢查細分或雕刻的解析度")

    if not must and not should:
        head = "看完了 這個檔案很乾淨欸👍 沒發現常見問題"
    elif not must:
        head = "看完了～ 沒有大問題 有幾個地方可以順手修一下"
    else:
        head = "看完了！有幾個交作業前**一定要修**的地方XD"

    out = [f"🩺 **作業健檢：{filename}**", head]
    if must:
        out += ["", "🔴 **一定要修**"] + [f"{i}. {t}" for i, t in enumerate(must, 1)]
    if should:
        out += ["", "🟡 **建議修**"] + [f"{i}. {t}" for i, t in enumerate(should, 1)]

    t = r["totals"]
    eng = {"BLENDER_EEVEE_NEXT": "EEVEE", "BLENDER_EEVEE": "EEVEE", "CYCLES": "Cycles",
           "BLENDER_WORKBENCH": "Workbench"}.get(scene["engine"], scene["engine"])
    res = scene["resolution"]
    out += ["", f"-# 📊 {_num(t['verts'])} 個點／{_num(t['faces'])} 個面／{_num(t['tris'])} 個三角面"
                f"｜算圖 {eng} {res[0]}×{res[1]}（{res[2]}%）｜Blender {'.'.join(r['file_version'].split('.')[:2])} 存檔"]
    if mesh.get("skipped"):
        out.append(f"-# {_names(mesh['skipped'])} 點太多，跳過了重疊點和法線檢查")
    preview = r.get("preview")
    if preview == "temp_camera":
        out.append("-# 🖼️ 預覽圖是我臨時放一台攝影機拍的，不是你的算圖結果")
    elif preview == "scene_camera":
        out.append("-# 🖼️ 預覽圖是用你的攝影機、Workbench 快速拍的，材質燈光效果以你自己算圖為準")
    out.append("-# 機器檢查只能抓常見問題，作品好不好看還是要給老師看唷")

    summary = f"一定要修 {len(must)}／建議修 {len(should)}"
    return "\n".join(out), summary


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python homework_check.py 作業.blend")
        sys.exit(1)
    path = sys.argv[1]
    print("Blender：", find_blender())
    with open(path, "rb") as f:
        data = f.read()
    rep, prev, tmpdir = asyncio.run(run_check(data, os.path.basename(path)))
    text, summ = format_report(rep, os.path.basename(path))
    print(text)
    print("\n摘要：", summ)
    if prev:
        dst = os.path.join(os.getcwd(), "健檢預覽.png")
        shutil.copy(prev, dst)
        print("預覽圖：", dst)
    cleanup(tmpdir)
