"""
不用開 Discord，直接測試小樽語氣的回答長什麼樣子

用法：
  python tests/test_persona.py                 → 跑內建的幾題
  python tests/test_persona.py 物件不見了怎麼辦  → 測你自己的問題
  python tests/test_persona.py --local          → 只測本地模型（Gemini 忙線時用這個）

每題會分別用「本地模型」和「Gemini」各回答一次（Gemini 會花一點點 API 額度），
並顯示在 Discord 上會不會被拆成幾則短訊息。
"""
import asyncio
import os
import sys

# 測試檔放在 tests/ 資料夾，要先把上一層（機器人程式所在的資料夾）加進搜尋路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # 讓 .env 找得到

import bot   # 只載入設定和函式，不會啟動機器人
import llm

LOCAL_ONLY = "--local" in sys.argv
ARGS = [a for a in sys.argv[1:] if a != "--local"]
QUESTIONS = ARGS and [" ".join(ARGS)] or [
    "物件不見了怎麼辦",
    "布林運算怎麼用?",
    "筆電沒有中鍵怎麼轉視角?",
]


def show(title, answer):
    print(f"\n── {title} ──")
    parts = bot.split_for_chat(answer) if bot.PERSONA and bot.SPLIT_SHORT else None
    if parts:
        print(f"（會拆成 {len(parts)} 則訊息）")
        for p in parts:
            print(f"  💬 {p}")
    else:
        print(answer)


async def main():
    print(f"語氣：{'小樽' if bot.PERSONA else '一般助教'}｜本地模型：{llm.LOCAL_MODEL}｜Gemini：{llm.GEMINI_MODEL}")
    for q in QUESTIONS:
        print("\n" + "=" * 60 + f"\n❓ {q}")
        hits = bot.kb.search(q, k=3)
        if not hits:
            print("（知識庫沒資料，機器人會上網查；這個測試只測有資料的題目）")
            continue
        print("📚 " + "；".join(c.title for _, c in hits))
        msgs = [{"role": "user", "content": q}]
        ctx = bot.format_context(hits)
        try:
            local_msgs = [{"role": "user", "content":
                           f"【課程資料】\n{ctx}\n\n【學生的問題】\n{q}\n\n{bot.local_rules()}"}]
            show(f"本地模型 {llm.LOCAL_MODEL}", await bot.local_answer(bot.system_prompt(local=True), local_msgs))
        except Exception as e:
            print(f"\n── 本地模型失敗：{e!r}（Ollama 有開嗎？）")
        if LOCAL_ONLY:
            continue
        try:
            show("Gemini", await llm.gemini_chat(bot.system_prompt() + bot.KB_FOUND.format(context=ctx), msgs))
        except Exception as e:
            print(f"\n── Gemini 失敗：{e!r}"[:200])


try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\n（已中斷）")
