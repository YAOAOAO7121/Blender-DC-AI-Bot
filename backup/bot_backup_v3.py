"""
Blender 課程 AI 教學助理 — 測試版 v3

回答流程：
1. 先查 knowledge/ 本地知識庫
2. 有資料 → 用筆電上的本地模型（Ollama）回答，不花 API
   （本地模型沒開或出錯時，自動改用 Gemini）
3. 沒資料 → 上網搜尋、抓網頁 → 交給 Gemini 整理
   → 回答學生並附上連結 → 整理成筆記存進知識庫，下次就能本地回答

- 在指定頻道提問 → 機器人開討論串回答；在討論串裡追問會記得前面的對話
- 每則問答記錄到 questions_log.csv
"""
import csv
import datetime
import os
import re

import discord
from dotenv import load_dotenv

load_dotenv()   # 要在 import llm 之前載入設定

import llm
import web_research
from knowledge import KnowledgeBase, format_context

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ASK_CHANNEL_ID = int(os.getenv("ASK_CHANNEL_ID"))
USE_LOCAL = os.getenv("USE_LOCAL", "1") == "1"          # 0 = 全部用 Gemini
WEB_SEARCH = os.getenv("WEB_SEARCH", "1") == "1"        # 0 = 不上網查
AUTO_SAVE_WEB = os.getenv("AUTO_SAVE_WEB", "1") == "1"  # 1 = 直接存進知識庫；0 = 存到待審核資料夾
SHOW_SOURCES = os.getenv("SHOW_SOURCES", "1") == "1"    # 測試期間在回答下方顯示資料來源與使用的模型

BASE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE, "questions_log.csv")
LOG_HEADER = ["時間", "學生", "提問", "回答", "討論串ID", "參考資料", "分類"]
WEB_NOTE_DIR = os.path.join(BASE, "knowledge", "網路整理")
DRAFT_DIR = os.path.join(BASE, "knowledge_待審核")

SYSTEM_PROMPT = """你是「基礎3D創作與設計」課程的 Blender 教學助理。
修課學生大多是 3D 零經驗者，請：
- 一定要用繁體中文（台灣用語），口語、步驟清楚地回答，不要使用簡體字
- 提到操作時，寫出選單路徑或快捷鍵
- 問題不清楚時先追問（例如 Blender 版本、截圖、做到哪一步）
- 不確定的事直接說不確定，不要編造
- 與課程無關的問題，禮貌地引導回課程"""

KB_FOUND = """

以下是課程知識庫中跟這個問題有關的資料（由老師和助教整理）：
{context}

使用資料的規則：
- 根據上面的資料回答；資料和你自己的知識不一致時，以資料為準
- 資料沒提到的細節不要自己編，可以請同學補充狀況或去問老師
- 回答裡不要出現「資料1」「資料2」這種編號"""

KB_NONE = """

（課程知識庫裡沒有找到跟這個問題直接相關的資料。請用你的一般知識回答，不確定的地方要說清楚。）"""

WEB_PROMPT = """

課程知識庫裡沒有這題的資料，以下是剛剛從網路上找到的網頁內容：
{pages}

請閱讀這些網頁，完成兩件事，並只輸出一個 JSON 物件（不要有其他文字）：
{{
  "found": true 或 false,      // 這些網頁是否足以回答學生的問題
  "answer": "給學生的回答",     // 依照上面的回答原則撰寫；不要放網址，也不要寫「根據網頁1」
  "sources": [1, 3],           // 回答實際用到的網頁編號
  "note_title": "筆記標題",     // 10 字左右，例如「頭髮粒子系統」
  "note": "存進知識庫的筆記"     // Markdown，用「## 小標題」分段；小標題寫成學生會問的說法並附英文名稱，
                               // 例如「## 用粒子系統做頭髮（Hair Particles）」；內容精簡正確、寫出操作步驟與快捷鍵
}}
- 網頁內容互相矛盾或明顯過時（例如 Blender 2.7 以前的介面）時，以新版 Blender 為準並在回答中提醒
- found 為 false 時，answer 照樣用你的一般知識回答，但要說明網路上沒找到可靠資料、建議問老師；note 留空字串"""

kb = KnowledgeBase()

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


# ───────────── 紀錄 ─────────────

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


# ───────────── 網路整理的筆記存檔 ─────────────

def save_web_note(title, note, pages, question):
    folder = WEB_NOTE_DIR if AUTO_SAVE_WEB else DRAFT_DIR
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", title).strip("_")[:40] or "未命名"
    stamp = datetime.date.today().isoformat()
    path = os.path.join(folder, f"{stamp}_{safe}.md")
    i = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{stamp}_{safe}_{i}.md")
        i += 1
    meta = "\n".join([
        "<!--",
        "來源：網路整理（AI 自動整理，尚未經老師審核）",
        f"整理時間：{datetime.datetime.now().isoformat(timespec='minutes')}",
        f"學生原始提問：{question}",
        "參考網址：",
        *[f"- {p['title']} {p['url']}" for p in pages],
        "-->",
    ])
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{meta}\n\n{note.strip()}\n")
    return os.path.relpath(path, BASE)


def link_list(pages):
    # <網址> 可以避免 Discord 展開一大堆預覽卡片
    return "\n".join(f"{i}. [{p['title'][:60]}](<{p['url']}>)" for i, p in enumerate(pages, 1))


# ───────────── 回答流程 ─────────────

async def answer_from_kb(messages, hits):
    """知識庫有資料：先用本地模型，不行再用 Gemini"""
    system_prompt = SYSTEM_PROMPT + KB_FOUND.format(context=format_context(hits))
    if USE_LOCAL:
        try:
            return await llm.local_chat(system_prompt, messages), f"本地模型 {llm.LOCAL_MODEL}"
        except Exception as e:
            print(f"[本地模型] 失敗，改用 Gemini：{e!r}")
    return await llm.gemini_chat(system_prompt, messages), "Gemini（本地模型未啟用或失敗）"


async def answer_from_web(messages, question, thread):
    """知識庫沒資料：上網找 → Gemini 整理 → 存進知識庫。回傳 (回答, 附註, 紀錄用來源)"""
    await thread.send("🔎 課程資料裡還沒有這題，我上網找一下資料，請稍等～")
    pages = await web_research.research(question)
    if not pages:
        answer = await llm.gemini_chat(SYSTEM_PROMPT + KB_NONE, messages)
        return answer, "\n\n-# 🔎 網路上沒找到合適的資料，以上是 AI 的一般知識，建議再確認或問老師", "（網路查無資料）"

    page_text = "\n\n".join(f"[網頁{i}] {p['title']}\n網址：{p['url']}\n{p['text']}"
                            for i, p in enumerate(pages, 1))
    data = await llm.gemini_json(SYSTEM_PROMPT + WEB_PROMPT.format(pages=page_text), messages)
    if not data or not data.get("answer"):
        answer = await llm.gemini_chat(SYSTEM_PROMPT + KB_NONE, messages)
        return answer, "\n\n-# ⚠️ 網路資料整理失敗，以上是 AI 的一般知識", "（整理失敗）"

    used = [pages[i - 1] for i in data.get("sources", [])
            if isinstance(i, int) and 1 <= i <= len(pages)] or pages
    extra = "\n\n🔗 **參考連結**\n" + link_list(used)
    log_src = "[網路] " + " ".join(p["url"] for p in used)

    if data.get("found") and data.get("note", "").strip():
        saved = save_web_note(data.get("note_title") or question[:20], data["note"], used, question)
        print(f"[知識庫] 新增筆記：{saved}")
        log_src += f"｜存檔：{saved}"
        if SHOW_SOURCES:
            where = "知識庫" if AUTO_SAVE_WEB else "待審核資料夾"
            extra += f"\n-# 📝 已整理存進{where}：{saved}（尚未經老師審核）"
    elif SHOW_SOURCES:
        extra += "\n-# 網路資料不足以確定答案，這次沒有存進知識庫"
    return data["answer"], extra, log_src


async def send_long(channel, text):
    """Discord 單則訊息上限 2000 字，超過就分段送（盡量在換行處切）"""
    while text:
        if len(text) <= 1900:
            await channel.send(text)
            return
        cut = text.rfind("\n", 0, 1900)
        cut = cut if cut > 500 else 1900
        await channel.send(text[:cut])
        text = text[cut:].lstrip("\n")


async def build_history(thread, bot_user):
    """把討論串裡的訊息整理成對話紀錄，讓 AI 能接續追問"""
    history = []
    async for msg in thread.history(limit=30, oldest_first=True):
        if not msg.content or msg.content.startswith("🔎 課程資料裡還沒有這題"):
            continue
        role = "assistant" if msg.author == bot_user else "user"
        content = re.sub(r"\n+-# .*$", "", msg.content, flags=re.M)   # 去掉附註小字
        if history and history[-1]["role"] == role:
            history[-1]["content"] += "\n" + content
        else:
            history.append({"role": role, "content": content})
    while history and history[0]["role"] != "user":
        history.pop(0)
    return history


@bot.event
async def on_ready():
    upgrade_log_file()
    kb.reload_if_changed()
    if USE_LOCAL:
        ok, names = await llm.local_available()
        if ok:
            print(f"本地模型就緒：{llm.LOCAL_MODEL}")
        else:
            print(f"⚠️ 找不到本地模型 {llm.LOCAL_MODEL}（Ollama 有開嗎？已安裝：{names or '無'}），會改用 Gemini")
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
        try:
            starter = await message.channel.parent.fetch_message(thread.id)
            messages.insert(0, {"role": "user", "content": starter.content})
            if len(messages) > 1 and messages[1]["role"] == "user":
                messages[0]["content"] += "\n" + messages.pop(1)["content"]
        except discord.NotFound:
            pass
    else:
        return

    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    query = user_msgs[0] if len(user_msgs) == 1 else user_msgs[0] + "\n" + user_msgs[-1]
    hits = kb.search(query, k=3)

    async with thread.typing():
        try:
            if hits:
                answer, engine = await answer_from_kb(messages, hits)
                titles = "；".join(dict.fromkeys(c.title for _, c in hits))
                links = list(dict.fromkeys(u for _, c in hits for u in c.links))
                extra = ""
                if links:   # 這段資料是之前上網整理的 → 把原始連結也給學生
                    extra += "\n\n🔗 **參考連結**\n" + "\n".join(
                        f"{i}. <{u}>" for i, u in enumerate(links[:4], 1))
                if SHOW_SOURCES:
                    extra += f"\n-# 📚 參考課程資料：{titles}｜🤖 {engine}"
                log_src = f"[{engine}] {titles}"
            elif WEB_SEARCH:
                answer, extra, log_src = await answer_from_web(messages, query, thread)
            else:
                answer = await llm.gemini_chat(SYSTEM_PROMPT + KB_NONE, messages)
                extra = "\n\n-# 📚 課程資料裡沒有這題，以上是 AI 的一般知識，建議再確認" if SHOW_SOURCES else ""
                log_src = "（無）"
        except Exception as e:
            await thread.send("抱歉，我暫時無法回答，請稍後再試或詢問助教。")
            print("錯誤：", repr(e))
            return

    print(f"[提問] {message.content[:40]} → {log_src[:80]}")
    await send_long(thread, answer + extra)
    log_question(str(message.author), message.content, answer, thread.id, log_src)


bot.run(DISCORD_TOKEN)
