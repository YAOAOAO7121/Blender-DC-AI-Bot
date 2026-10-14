"""
Blender 課程 AI 教學助理 — 測試版 v3

回答流程：
1. 先查 knowledge/ 本地知識庫
2. 有資料 → 用筆電上的本地模型（Ollama）回答，不花 API
   （本地模型沒開或出錯時，自動改用 Gemini）
3. 沒資料 → 上網搜尋、抓網頁 → 交給 Gemini 整理
   → 回答學生並附上連結 → 整理成筆記存進知識庫，下次就能本地回答

- 在指定頻道提問 → 機器人開討論串回答；在討論串裡追問會記得前面的對話
- 每則問答記錄到 questions_log.csv，並自動標上課程章節分類（例如 06_修改器）
- 回答用小樽老師的語氣（設定在 persona/ 資料夾，改檔案就能調，不用重開）
  簡單問題會像小樽在 Discord 聊天一樣拆成幾則短訊息
- 追問時先用「最新那句」查資料，查不到才合併第一題一起查（避免一直拿到第一題的資料）
"""
import asyncio
import csv
import datetime
import os
import re

import discord
from dotenv import load_dotenv

load_dotenv()   # 要在 import llm 之前載入設定

import llm
import web_research
from knowledge import KnowledgeBase, classify, format_context

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ASK_CHANNEL_ID = int(os.getenv("ASK_CHANNEL_ID"))
USE_LOCAL = os.getenv("USE_LOCAL", "1") == "1"          # 0 = 全部用 Gemini
WEB_SEARCH = os.getenv("WEB_SEARCH", "1") == "1"        # 0 = 不上網查
AUTO_SAVE_WEB = os.getenv("AUTO_SAVE_WEB", "1") == "1"  # 1 = 直接存進知識庫；0 = 存到待審核資料夾
SHOW_SOURCES = os.getenv("SHOW_SOURCES", "1") == "1"    # 測試期間在回答下方顯示資料來源與使用的模型
KB_MIN_COVERAGE = float(os.getenv("KB_MIN_COVERAGE", "0.15"))  # 問題關鍵字在資料中出現的比例，低於這個就視為沒資料
LOCAL_JUDGE = os.getenv("LOCAL_JUDGE", "1") == "1"      # 1 = 回答前先請本地模型判斷資料夠不夠
PERSONA = os.getenv("PERSONA", "1") == "1"              # 1 = 用小樽的語氣；0 = 一般助教口吻
SPLIT_SHORT = os.getenv("SPLIT_SHORT", "1") == "1"      # 1 = 簡短回答拆成幾則短訊息送出

BASE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE, "questions_log.csv")
LOG_HEADER = ["時間", "學生", "提問", "回答", "討論串ID", "參考資料", "分類"]
WEB_NOTE_DIR = os.path.join(BASE, "knowledge", "網路整理")
DRAFT_DIR = os.path.join(BASE, "knowledge_待審核")
PERSONA_DIR = os.path.join(BASE, "persona")

# PERSONA=0 或語氣檔讀不到時用的一般助教設定
PLAIN_PROMPT = """你是「基礎3D創作與設計」課程的 Blender 教學助理。
修課學生大多是 3D 零經驗者，請：
- 一定要用繁體中文（台灣用語），口語、步驟清楚地回答，不要使用簡體字
- 提到操作時，寫出選單路徑或快捷鍵
- 問題不清楚時先追問（例如 Blender 版本、截圖、做到哪一步）
- 不確定的事直接說不確定，不要編造
- 與課程無關的問題，禮貌地引導回課程"""

def load_persona(name):
    """讀 persona/ 裡的語氣檔；第一行「# 說明」不送給模型。每次都重讀，改了馬上生效"""
    try:
        with open(os.path.join(PERSONA_DIR, name), encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip() or None


def system_prompt(local=False):
    """local=True 給本地小模型（精簡版），否則給 Gemini（完整版）"""
    if PERSONA:
        text = load_persona("小樽_精簡.md" if local else "小樽_完整.md")
        if text:
            return text
        print("⚠️ 讀不到 persona/ 裡的語氣檔，改用一般助教口吻")
    return PLAIN_PROMPT


WAIT_MSG = "🔎 這題課程資料裡還沒有 我上網找一下 等我等我~" if PERSONA else "🔎 課程資料裡還沒有這題，我上網找一下資料，請稍等～"
ERROR_MSG = ("哎呀 我的腦袋暫時當機了XD 等一下再問一次 或先找助教唷" if PERSONA
             else "抱歉，我暫時無法回答，請稍後再試或詢問助教。")

KB_FOUND = """

以下是課程知識庫中跟這個問題有關的資料（由老師和助教整理）：
{context}

使用資料的規則：
- 根據上面的資料回答；資料和你自己的知識不一致時，以資料為準
- 資料沒提到的細節不要自己編，可以請同學補充狀況或去問老師
- 回答裡不要出現「資料1」「資料2」這種編號"""

# 給本地小模型用：資料和規則放在「最後一則訊息」裡，小模型比較會照做
LOCAL_RULES = """請只根據上面的【課程資料】回答【學生的問題】，規則：
1. 資料裡的步驟、快捷鍵、選單名稱要照資料寫，不可以改成別的按鍵
2. 資料沒有提到的步驟、按鍵、功能，一律不要寫，不要自己補充或延伸
3. 用繁體中文；每個步驟獨立一行、用 1. 2. 3. 編號，不要寫成一整段
4. 不要寫「資料1」這種編號"""
LOCAL_PARTIAL = "\n5. 資料只能回答一部分時，只回答那部分，最後加一句「其他細節課程資料沒寫到，可以再問老師或助教喔」"
# 小模型照「範例」學格式比照規則學得好；範例內容故意跟 Blender 操作無關，避免被抄進答案
LOCAL_TONE = """
5. 口氣輕鬆像朋友，句尾可以加「唷」「囉~」「XD」；不要自稱小樽或老師
6. 格式照下面這個範例（範例的內容跟這題無關，只學它的格式和口氣）：
同學安安~ 這個功能可以幫你省很多時間唷
1. 第一個步驟寫在這一行
2. 第二個步驟寫在這一行，關鍵的地方可以提醒「務必記得」
3. 第三個步驟寫在這一行
如果畫面跟預期不一樣先別緊張XD
試試看，有問題再來問~
7. 最後一行二選一：資料完整回答了就寫「試試看，有問題再來問~」；
   資料只能回答一部分就改寫「其他細節課程資料沒寫到 可以再問老師或助教唷」"""


def tidy_local(text):
    """小模型的回答常擠成一大段、結尾兩句重複 → 整理成好讀的樣子"""
    text = text.strip()
    if "可以再問老師或助教" in text:   # 兩種結尾都寫了 → 只留「資料沒寫到」那句
        text = re.sub(r"\n*試試看[，, ]*有問題再來問[~～]*\s*$", "", text).strip()
    body_lines = [l for l in text.splitlines() if l.strip()]
    if body_lines and max(len(l) for l in body_lines) > 150:
        # 某一行太長 → 在句號處斷行（保留句號後面接的引號、括號）
        text = re.sub(r"([。！？!?][」）)]?)(?=[^\n」）)])", r"\1\n", text)
        text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


async def local_answer(system, messages):
    return tidy_local(await llm.local_chat(system, messages))


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
  "note": "存進知識庫的筆記"     // 用中性的教學文字寫，不要用小樽的語氣詞；Markdown，用「## 小標題」分段；小標題寫成學生會問的說法並附英文名稱，
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


def backfill_categories():
    """舊紀錄的「分類」欄是空的 → 用知識庫自動補上（啟動時跑一次）"""
    if not os.path.exists(LOG_FILE):
        return
    with open(LOG_FILE, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows or "分類" not in rows[0]:
        return
    col = rows[0].index("分類")
    changed = 0
    for r in rows[1:]:
        while len(r) <= col:
            r.append("")
        if not r[col].strip() and len(r) > 2:
            r[col] = classify(kb, r[2])
            changed += 1
    if changed:
        tmp = LOG_FILE + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows(rows)
        os.replace(tmp, LOG_FILE)
        print(f"已幫 {changed} 筆舊紀錄補上分類")


def log_question(user, question, answer, thread_id, sources, category=""):
    new_file = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(LOG_HEADER)
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"),
                    user, question, answer, thread_id, sources, category])


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

def local_rules():
    return LOCAL_RULES + (LOCAL_TONE if PERSONA else LOCAL_PARTIAL)


async def answer_from_kb(messages, hits, query):
    """知識庫有資料：先用本地模型，不行再用 Gemini
    回傳 (None, None) 代表本地模型判斷資料不足 → 呼叫端改上網查"""
    context = format_context(hits)
    if USE_LOCAL:
        try:
            if LOCAL_JUDGE and not await llm.local_judge(query, context):
                return None, None
            question = messages[-1]["content"]
            local_msgs = messages[:-1] + [{
                "role": "user",
                "content": f"【課程資料】\n{context}\n\n【學生的問題】\n{question}\n\n{local_rules()}",
            }]
            return await local_answer(system_prompt(local=True), local_msgs), f"本地模型 {llm.LOCAL_MODEL}"
        except Exception as e:
            print(f"[本地模型] 失敗，改用 Gemini：{e!r}")
    return (await llm.gemini_chat(system_prompt() + KB_FOUND.format(context=context), messages),
            "Gemini（本地模型未啟用或失敗）")


async def general_answer(messages):
    """知識庫和網路都沒資料時，用一般知識回答：先 Gemini，Gemini 掛了就用本地模型。回傳 (回答, 模型名稱)"""
    try:
        return await llm.gemini_chat(system_prompt() + KB_NONE, messages), "Gemini"
    except Exception as e:
        if not USE_LOCAL:
            raise
        print(f"[Gemini] 失敗，改用本地模型：{e!r}"[:200])
        return await local_answer(system_prompt(local=True) + KB_NONE, messages), f"本地模型 {llm.LOCAL_MODEL}"


async def local_from_pages(messages, pages):
    """Gemini 整理網頁失敗時的備案：讓本地模型看前兩篇網頁的摘要來回答（不存進知識庫）"""
    context = "\n\n".join(f"[{p['title']}]\n{p['text'][:1500]}" for p in pages[:2])
    local_msgs = messages[:-1] + [{
        "role": "user",
        "content": f"【網路資料】\n{context}\n\n【學生的問題】\n{messages[-1]['content']}\n\n"
                   + local_rules().replace("課程資料", "網路資料"),
    }]
    return await local_answer(system_prompt(local=True), local_msgs)


async def answer_from_web(messages, question, thread):
    """知識庫沒資料：上網找 → Gemini 整理 → 存進知識庫。回傳 (回答, 附註, 紀錄用來源)"""
    await thread.send(WAIT_MSG)
    keywords = None
    if USE_LOCAL:
        try:
            keywords = await llm.local_keywords(question)
        except Exception as e:
            print(f"[搜尋關鍵字] 本地模型產生失敗，改用問題裡的英文術語：{e!r}")
    pages = await web_research.research(question, keywords)
    if not pages:
        answer, engine = await general_answer(messages)
        return (answer, f"\n\n-# 🔎 網路上沒找到合適的資料，以上是 AI 的一般知識（{engine}），建議再確認或問老師",
                "（網路查無資料）")

    page_text = "\n\n".join(f"[網頁{i}] {p['title']}\n網址：{p['url']}\n{p['text']}"
                            for i, p in enumerate(pages, 1))
    try:
        data = await llm.gemini_json(system_prompt() + WEB_PROMPT.format(pages=page_text), messages)
    except Exception as e:
        if not USE_LOCAL:
            raise
        print(f"[Gemini] 整理網頁失敗，改用本地模型：{e!r}"[:200])
        answer = await local_from_pages(messages, pages)
        extra = ("\n\n🔗 **參考連結**\n" + link_list(pages[:2])
                 + f"\n-# ⚠️ Gemini 暫時忙線，這次由本地模型 {llm.LOCAL_MODEL} 根據網頁回答，沒有存進知識庫，請再確認")
        return answer, extra, "[網路・本地模型備援] " + " ".join(p["url"] for p in pages[:2])
    if not data or not data.get("answer"):
        answer, engine = await general_answer(messages)
        return answer, f"\n\n-# ⚠️ 網路資料整理失敗，以上是 AI 的一般知識（{engine}）", "（整理失敗）"

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


def split_for_chat(answer):
    """簡短、沒有條列步驟的回答 → 拆成幾行，像小樽在 Discord 連發短訊息；不適合拆就回傳 None"""
    lines = [l.strip() for l in answer.strip().splitlines() if l.strip()]
    if not (2 <= len(lines) <= 5) or len(answer) > 220:
        return None
    if any(re.match(r"^(\d+[.、)]|[-*•]|#)", l) or len(l) > 70 for l in lines):
        return None
    return lines


async def send_answer(thread, answer, extra):
    parts = split_for_chat(answer) if PERSONA and SPLIT_SHORT else None
    if not parts:
        await send_long(thread, answer + extra)
        return
    for i, line in enumerate(parts):
        if i:
            async with thread.typing():
                await asyncio.sleep(min(0.5 + len(line) * 0.04, 2.0))   # 模擬打字的停頓
        await thread.send(line + (extra if i == len(parts) - 1 else ""))


async def build_history(thread, bot_user):
    """把討論串裡的訊息整理成對話紀錄，讓 AI 能接續追問"""
    history = []
    async for msg in thread.history(limit=30, oldest_first=True):
        if not msg.content or msg.content.startswith("🔎"):
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
    try:
        backfill_categories()
    except PermissionError:
        print("⚠️ questions_log.csv 被其他程式開著（Excel？），這次沒有補分類")
    if USE_LOCAL:
        ok, names = await llm.local_available()
        if ok:
            print(f"本地模型就緒：{llm.LOCAL_MODEL}")
        else:
            print(f"⚠️ 找不到本地模型 {llm.LOCAL_MODEL}（Ollama 有開嗎？已安裝：{names or '無'}），會改用 Gemini")
    print(f"語氣：{'小樽（persona/）' if PERSONA else '一般助教'}")
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
    latest = user_msgs[-1]
    combined = latest if len(user_msgs) == 1 else user_msgs[0] + "\n" + latest
    # 先只用最新那句查（追問「那要怎麼綁骨架」不該拿到第一題布林運算的資料）；
    # 查不到才合併第一題一起查（像「那第二步呢」這種要靠前文才看得懂的追問）
    query, hits = None, []
    for q in dict.fromkeys([latest, combined]):
        found = kb.search(q, k=3)
        if not found:
            continue
        cov = kb.coverage(q, found)
        if cov >= KB_MIN_COVERAGE:
            query, hits = q, found
            break
        print(f"[知識庫] 關鍵字覆蓋率 {cov:.2f} < {KB_MIN_COVERAGE}，資料不是在講這題")
    if query is None:
        # 知識庫沒資料 → 上網查：最新那句夠完整就只查它，太短（「那第二步呢」）才帶上第一題
        query = latest if len(latest.strip()) >= 8 else combined
    category = classify(kb, latest)
    if category == "未分類" and combined != latest:
        category = classify(kb, combined)

    async with thread.typing():
        try:
            answer = None
            if hits:
                answer, engine = await answer_from_kb(messages, hits, query)
                if answer is None:
                    print("[本地模型判斷] 課程資料不足以回答 → 改上網查")
            if answer is not None:
                titles = "；".join(dict.fromkeys(c.title for _, c in hits))
                links = list(dict.fromkeys(u for _, c in hits for u in c.links))
                extra = ""
                if links:   # 這段資料是之前上網整理的 → 把原始連結也給學生
                    extra += "\n\n🔗 **參考連結**\n" + "\n".join(
                        f"{i}. <{u}>" for i, u in enumerate(links[:4], 1))
                if SHOW_SOURCES:
                    extra += f"\n-# 📚 參考課程資料：{titles}｜🤖 {engine}｜🏷️ {category}"
                log_src = f"[{engine}] {titles}"
            elif WEB_SEARCH:
                answer, extra, log_src = await answer_from_web(messages, query, thread)
            else:
                answer, _ = await general_answer(messages)
                extra = "\n\n-# 📚 課程資料裡沒有這題，以上是 AI 的一般知識，建議再確認" if SHOW_SOURCES else ""
                log_src = "（無）"
        except Exception as e:
            await thread.send(ERROR_MSG)
            print("錯誤：", repr(e))
            return

    print(f"[提問] {message.content[:40]} → {log_src[:80]}｜分類：{category}")
    await send_answer(thread, answer, extra)
    try:
        log_question(str(message.author), message.content, answer, thread.id, log_src, category)
    except PermissionError:
        print("⚠️ questions_log.csv 被其他程式開著（Excel？），這筆沒記到")


if __name__ == "__main__":   # 讓 test_persona.py 可以 import 這個檔案而不啟動機器人
    bot.run(DISCORD_TOKEN)
