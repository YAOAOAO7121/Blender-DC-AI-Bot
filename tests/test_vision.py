"""
不用開 Discord，測試看截圖和延伸教學連結

用法：
  python tests/test_vision.py tests/IMG_7920.png                 → 看圖（學生沒打字的情況）
  python tests/test_vision.py 截圖.png 為什麼變黑黑的   → 看圖＋學生的問題
  python tests/test_vision.py --links 布林運算 Boolean  → 只測延伸教學連結（中文、英文關鍵字都可以給）
"""
import asyncio
import os
import mimetypes
import sys

# 測試檔放在 tests/ 資料夾，要先把上一層（機器人程式所在的資料夾）加進搜尋路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # 讓 .env 找得到

import bot
import llm
import web_research


async def main():
    if sys.argv[1:2] == ["--links"]:
        args = sys.argv[2:]
        zh = " ".join(a for a in args if web_research.CJK_RE.search(a))
        en = " ".join(a for a in args if not web_research.CJK_RE.search(a))
        print(await bot.tutorial_footer((zh, en)) or "（沒找到連結）")
        return
    path, question = sys.argv[1], " ".join(sys.argv[2:])
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        data = f.read()
    print(f"圖片：{path}（{len(data) // 1024} KB）｜Gemini：{llm.GEMINI_MODEL}")
    res = await llm.gemini_vision_json(bot.VISION_PROMPT, f"學生的問題：{question or '（學生只傳了截圖，沒有打字說明）'}",
                                       [(data, mime)])
    if not res:
        print("看圖失敗（Gemini 沒有回傳正確格式）")
        return
    for k in ("is_blender", "description", "issue", "search"):
        print(f"\n【{k}】{res.get(k)}")
    kw = f"{question} {res.get('search', '')}".strip()
    hits = bot.kb.search(kw, k=3)
    print("\n📚 知識庫找到：" + ("；".join(c.title for _, c in hits) if hits else "（沒有，機器人會上網查）"))
    print(await bot.tutorial_footer(bot.tutorial_keywords(hits, kw)))


try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\n（已中斷）")
