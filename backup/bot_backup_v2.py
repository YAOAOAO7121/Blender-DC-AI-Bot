"""
Blender 課程 AI 教學助理 — 測試版
- 在指定頻道提問 → 機器人開討論串回答
- 在討論串裡繼續追問，會記得前面的對話
- 每則問答自動記錄到 questions_log.csv
- 回答前先查 knowledge/ 資料夾裡的本地知識庫（第一步：本地知識庫）
"""
import os
import csv
import datetime

import discord
from google import genai
from google.genai import types
from dotenv import load_dotenv

from knowledge import KnowledgeBase, format_context

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ASK_CHANNEL_ID = int(os.getenv("ASK_CHANNEL_ID"))  # 學生提問的頻道 ID
MODEL = os.getenv("MODEL", "gemini-3.8-flash")      # Gemini 免費額度可用的模型
LOG_FILE = "questions_log.csv"
LOG_HEADER = ["時間", "學生", "提問", "回答", "討論串ID", "參考資料", "分類"]
SHOW_SOURCES = os.getenv("SHOW_SOURCES", "1") == "1"  # 測試期間在回答下方顯示用了哪些資料

SYSTEM_PROMPT = """你是「基礎3D創作與設計」課程的 Blender 教學助理。
修課學生大多是 3D 零經驗者，請：
- 用繁體中文、口語、步驟清楚地回答
- 提到操作時，寫出選單路徑或快捷鍵
- 問題不清楚時先追問（例如 Blender 版本、截圖、做到哪一步）
- 不確定的事直接說不確定，不要編造
- 與課程無關的問題，禮貌地引導回課程"""

KB_FOUND = """

以下是課程知識庫中跟這個問題有關的資料（由老師和助教整理）：
{context}

使用資料的規則：
- 優先根據上面的資料回答；資料和你自己的知識不一致時，以資料為準
- 資料沒涵蓋的部分可以用一般知識補充，但要提醒同學這部分建議再確認
- 回答裡不要出現「資料1」「資料2」這種編號"""

KB_NONE = """

（課程知識庫裡沒有找到跟這個問題直接相關的資料。請用你的一般知識回答，不確定的地方要說清楚。）"""

kb = KnowledgeBase()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


def upgrade_log_file():
    """舊版紀錄檔沒有「參考資料」欄，自動補上"""
    if not os.path.exists(LOG_FILE):
        return
    with open(LOG_FILE, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows or "參考資料" in rows[0]:
        return
    rows = [LOG_HEADER] + [r[:5] + [""] + r[5:] for r in rows[1:]]
    with open(LOG_FILE, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)
    print("已更新 questions_log.csv 欄位（新增「參考資料」）")


def log_question(user, question, answer, thread_id, sources):
    new_file = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(LOG_HEADER)
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"),
                    user, question, answer, thread_id, sources, ""])


async def build_history(thread, bot_user):
    """把討論串裡的訊息整理成對話紀錄，讓 AI 能接續追問"""
    history = []
    async for msg in thread.history(limit=30, oldest_first=True):
        if not msg.content:
            continue
        role = "assistant" if msg.author == bot_user else "user"
        if history and history[-1]["role"] == role:
            history[-1]["content"] += "\n" + msg.content
        else:
            history.append({"role": role, "content": msg.content})
    # API 要求第一則必須是 user
    while history and history[0]["role"] != "user":
        history.pop(0)
    return history


async def ask_ai(messages, system_prompt):
    # Gemini 的角色名稱是 user / model
    contents = [
        types.Content(role="model" if m["role"] == "assistant" else "user",
                      parts=[types.Part(text=m["content"])])
        for m in messages
    ]
    resp = await client.aio.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=system_prompt),
    )
    return resp.text or "（沒有產生回答，請換個方式再問一次）"


async def send_long(channel, text):
    """Discord 單則訊息上限 2000 字，超過就分段送"""
    for i in range(0, len(text), 1900):
        await channel.send(text[i:i + 1900])


@bot.event
async def on_ready():
    upgrade_log_file()
    kb.reload_if_changed()
    print(f"已上線：{bot.user}")


@bot.event
async def on_message(message):
    if message.author.bot or not message.content:
        return

    # 情況一：在提問頻道發新問題 → 開討論串
    if message.channel.id == ASK_CHANNEL_ID:
        thread = await message.create_thread(name=message.content[:50])
        messages = [{"role": "user", "content": message.content}]

    # 情況二：在機器人開的討論串裡追問
    elif (isinstance(message.channel, discord.Thread)
          and message.channel.parent_id == ASK_CHANNEL_ID):
        thread = message.channel
        messages = await build_history(thread, bot.user)
        # 討論串的第一則（原始提問）在父頻道，補回來
        try:
            starter = await message.channel.parent.fetch_message(thread.id)
            messages.insert(0, {"role": "user", "content": starter.content})
            if len(messages) > 1 and messages[1]["role"] == "user":
                messages[0]["content"] += "\n" + messages.pop(1)["content"]
        except discord.NotFound:
            pass
    else:
        return

    # 先查本地知識庫：用「原始提問 + 最新這則」當查詢，追問時也能找到相關資料
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    query = user_msgs[0] if len(user_msgs) == 1 else user_msgs[0] + "\n" + user_msgs[-1]
    hits = kb.search(query, k=3)
    if hits:
        system_prompt = SYSTEM_PROMPT + KB_FOUND.format(context=format_context(hits))
        sources = "；".join(dict.fromkeys(c.title for _, c in hits))
    else:
        system_prompt = SYSTEM_PROMPT + KB_NONE
        sources = "（無）"   # 之後第三步「上網找資料」就從這些問題開始
    print(f"[提問] {message.content[:40]} → 參考：{sources}")

    async with thread.typing():
        try:
            answer = await ask_ai(messages, system_prompt)
        except Exception as e:
            await thread.send("抱歉，我暫時無法回答，請稍後再試或詢問助教。")
            print("API 錯誤：", e)
            return

    if SHOW_SOURCES:
        if hits:
            answer += "\n\n-# 📚 參考課程資料：" + sources
        else:
            answer += "\n\n-# 📚 課程資料裡沒有這題，以上是 AI 的一般知識，建議再確認"
    await send_long(thread, answer)
    log_question(str(message.author), message.content, answer, thread.id, sources)


bot.run(DISCORD_TOKEN)
