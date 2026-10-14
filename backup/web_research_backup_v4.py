"""
網路查資料：用 DuckDuckGo 搜尋，再把網頁正文抓下來（不需要 API 金鑰）

單獨測試：python web_research.py Blender 怎麼做頭髮
"""
import asyncio
import re
import sys
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except ImportError:              # 舊版套件名稱
    from duckduckgo_search import DDGS

# 優先採用的網站（越前面越優先）
PREFERRED = ("docs.blender.org", "blender.stackexchange.com", "blenderartists.org",
             "blender.org", "developer.blender.org")
# 抓不到正文或不適合引用的網站
SKIP = ("youtube.com", "youtu.be", "facebook.com", "instagram.com", "tiktok.com",
        "pinterest.", "x.com", "twitter.com", "reddit.com", "bilibili.com")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BlenderTA-bot/1.0",
           "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}
MAX_PAGES = 4
OLD_MANUAL = re.compile(r"(docs\.blender\.org/manual/[^/]+/)(\d+\.\d+|dev)/")
MAX_CHARS_PER_PAGE = 3500


def _search_sync(query, n):
    try:
        return list(DDGS().text(query, max_results=n) or [])
    except Exception as e:
        print(f"[網路搜尋] 失敗：{query}｜{e}")
        return []


def _rank(url):
    host = urlparse(url).netloc.lower()
    for i, d in enumerate(PREFERRED):
        if d in host:
            return i
    return len(PREFERRED)


ENGLISH_STOP = {"the", "a", "an", "to", "of", "in", "is", "and", "or", "if", "i", "my", "you", "blender"}


def heuristic_keywords(question, n=8):
    """沒有本地模型幫忙時：從問題裡挑出英文術語當關鍵字（Shape Key、Driver、IK…）"""
    words = []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9+\-]*", question):
        if w.lower() not in ENGLISH_STOP and w.lower() not in (x.lower() for x in words):
            words.append(w)
    return " ".join(words[:n])


async def search(question, keywords=None):
    """keywords：本地模型產生的英文關鍵字；問題太長時直接搜整句幾乎都會「No results」"""
    if not keywords and len(question) > 40:
        keywords = heuristic_keywords(question)
    base = keywords if keywords and len(keywords.split()) >= 2 else question[:60]
    q = base if "blender" in base.lower() else f"Blender {base}"
    queries = [q, f"{q} site:docs.blender.org"]
    if base is not question and len(question) <= 40:
        queries.append(f"Blender {question}")      # 短問題也用原本的中文搜一次
    print(f"[網路搜尋] 關鍵字：{q}")
    results = await asyncio.gather(*[asyncio.to_thread(_search_sync, x, 6) for x in queries])
    seen, items = set(), []
    for r in (x for lst in results for x in lst):
        url = r.get("href") or r.get("url")
        if not url or url in seen or any(s in url for s in SKIP):
            continue
        seen.add(url)
        items.append({"title": r.get("title", url), "url": url, "snippet": r.get("body", "")})
    items.sort(key=lambda x: _rank(x["url"]))   # 穩定排序：同等級保持搜尋順位
    return items


def to_latest_manual(url):
    """docs.blender.org/manual/en/2.90/... → /latest/...（舊版手冊的介面常常跟現在不一樣）"""
    return OLD_MANUAL.sub(r"\1latest/", url)


async def _ok(client, url):
    try:
        r = await client.head(url)
        return r.status_code < 400
    except Exception:
        return False


async def prefer_latest(client, url):
    """換成最新版手冊的網址；新版沒有這一頁（改版搬家）就保留原本的"""
    new = to_latest_manual(url)
    if new != url and await _ok(client, new):
        return new
    return url


def extract_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"]):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    lines = [re.sub(r"\s+", " ", l).strip() for l in main.get_text("\n").splitlines()]
    text = "\n".join(l for l in lines if len(l) > 1)
    return text[:MAX_CHARS_PER_PAGE]


async def _fetch(client, item):
    try:
        item = {**item, "url": await prefer_latest(client, item["url"])}
        r = await client.get(item["url"])
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return None
        text = extract_text(r.text)
        if len(text) < 200:          # 太短通常是擋爬蟲或空白頁
            return None
        return {**item, "text": text}
    except Exception as e:
        print(f"[網路抓取] 失敗：{item['url']}｜{e}")
        return None


async def research(question, keywords=None):
    """回傳 [{"title", "url", "text"}, ...]，最多 MAX_PAGES 篇；什麼都沒找到回傳空清單"""
    items = await search(question, keywords)
    if not items:
        return []
    async with httpx.AsyncClient(headers=HEADERS, timeout=12, follow_redirects=True) as c:
        pages = await asyncio.gather(*[_fetch(c, it) for it in items[:MAX_PAGES + 3]])
    pages = [p for p in pages if p][:MAX_PAGES]
    if not pages:   # 網頁都抓不到時，至少用搜尋結果的摘要
        pages = [{**it, "text": it["snippet"]} for it in items[:MAX_PAGES] if it["snippet"]]
    return pages


# ───────────── 延伸教學連結（中文優先：影片、部落格文章 → 官方手冊 → Reddit／論壇） ─────────────

try:
    from opencc import OpenCC
    _s2t = OpenCC("s2t").convert
except Exception:
    _s2t = None

# 不適合給學生的網站（內容農場、轉貼站、要登入才看得到的）
LINK_SKIP = ("facebook.com", "instagram.com", "pinterest.", "tiktok.com", "x.com", "twitter.com",
             "kknews.cc", "read01.com", "zhihu.com/question", "baidu.com", "sohu.com", "163.com",
             "douyin.com", "amazon.", "shopee.", "udemy.com", "skillshare.com", "domestika.org")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _search_region(query, n, region, kind="text"):
    try:
        d = DDGS()
        fn = d.videos if kind == "videos" else d.text
        return list(fn(query, region=region, max_results=n) or [])
    except Exception as e:
        print(f"[延伸教學] 搜尋失敗：{query}｜{e}")
        return []


def _is_chinese(title):
    return len(CJK_RE.findall(title)) >= 2


def _is_traditional(title):
    """標題轉成繁體後沒有變化 → 本來就是繁體（台灣）"""
    return _s2t is None or _s2t(title) == title


def _minutes(dur):
    m = re.match(r"^(?:(\d+):)?(\d+):(\d+)$", dur or "")
    return (int(m.group(1) or 0) * 60 + int(m.group(2))) if m else None


def _url_of(r):
    return r.get("href") or r.get("content") or r.get("url") or ""


def _ok_link(url, seen):
    return url and url not in seen and not any(x in url for x in LINK_SKIP)


async def tutorial_links(zh, en, max_links=5):
    """回傳 [{"title", "url", "kind"}]，順序：中文影片／文章（繁體優先）→ 官方手冊 → Reddit 或 StackExchange
    zh：中文關鍵字（例如「材質顯示成粉紅色」）；en：英文關鍵字（例如「Missing Texture」）"""
    zh, en = (zh or "").strip(), (en or "").strip()
    jobs = {}
    if zh:
        jobs["zh_vid"] = asyncio.to_thread(_search_region, f"Blender {zh} 教學", 10, "tw-tzh", "videos")
        jobs["zh_web"] = asyncio.to_thread(_search_region, f"Blender {zh} 教學", 10, "tw-tzh")
    if en:
        q = en if "blender" in en.lower() else f"Blender {en}"
        jobs["doc"] = asyncio.to_thread(_search_region, f"{q} site:docs.blender.org", 4, "us-en")
        jobs["reddit"] = asyncio.to_thread(_search_region, f"{q} site:reddit.com/r/blender", 4, "us-en")
        jobs["se"] = asyncio.to_thread(_search_region, f"{q} site:blender.stackexchange.com", 3, "us-en")
        jobs["en_vid"] = asyncio.to_thread(_search_region, f"{q} tutorial", 8, "us-en", "videos")
    if not jobs:
        return []
    res = dict(zip(jobs, await asyncio.gather(*jobs.values())))
    seen, chinese, out = set(), [], []

    # 中文影片（YouTube、10～40 分鐘以內）
    for v in res.get("zh_vid", []):
        url, title = _url_of(v), v.get("title", "")
        mins = _minutes(v.get("duration"))
        if ("youtube.com" in url or "youtu.be" in url) and _is_chinese(title) \
                and _ok_link(url, seen) and (mins is None or mins <= 40):
            dur = f"（{v['duration']}）" if v.get("duration") else ""
            chinese.append({"title": title + dur, "url": url, "kind": "📺", "tw": _is_traditional(title)})
            seen.add(url)
    # 中文文章（部落格、教學網站；YouTube 已經在上面處理）
    for r in res.get("zh_web", []):
        url, title = _url_of(r), r.get("title", "")
        if _is_chinese(title) and _ok_link(url, seen) and "youtube.com" not in url:
            chinese.append({"title": title, "url": url, "kind": "📝", "tw": _is_traditional(title)})
            seen.add(url)
    # 繁體優先、同等級保持搜尋順位；影片和文章各至少留一個
    chinese.sort(key=lambda x: not x["tw"])
    vids = [c for c in chinese if c["kind"] == "📺"][:2]
    arts = [c for c in chinese if c["kind"] == "📝"][:2]
    picked = (vids[:1] + arts[:1] + vids[1:] + arts[1:])[:3]
    out += picked

    # 官方手冊（換成最新版）
    async with httpx.AsyncClient(headers=HEADERS, timeout=8, follow_redirects=True) as c:
        for r in res.get("doc", []):
            url = _url_of(r)
            if "docs.blender.org/manual" in url:
                out.append({"title": r.get("title", url), "url": await prefer_latest(c, url), "kind": "📖"})
                seen.add(url)
                break
    # 討論區：Reddit 優先，沒有就 StackExchange
    for r in res.get("reddit", []) + res.get("se", []):
        url = _url_of(r)
        if ("reddit.com/r/blender" in url or "blender.stackexchange.com/questions" in url) and _ok_link(url, seen):
            out.append({"title": r.get("title", url), "url": url, "kind": "💬"})
            seen.add(url)
            break
    # 中文影片一支都沒有 → 補一支英文影片
    if not vids:
        for v in res.get("en_vid", []):
            url, mins = _url_of(v), _minutes(v.get("duration"))
            if ("youtube.com" in url or "youtu.be" in url) and _ok_link(url, seen) and (mins is None or mins <= 40):
                dur = f"（{v['duration']}）" if v.get("duration") else ""
                out.append({"title": v.get("title", url) + dur, "url": url, "kind": "📺"})
                break
    return out[:max_links]


if __name__ == "__main__":
    if sys.argv[1:2] == ["--links"]:      # python web_research.py --links 布林運算 Boolean
        args = sys.argv[2:]
        zh = " ".join(a for a in args if CJK_RE.search(a))
        en = " ".join(a for a in args if not CJK_RE.search(a))
        for t in asyncio.run(tutorial_links(zh, en)):
            print(t["kind"], t["title"], t["url"])
        sys.exit()
    question = " ".join(sys.argv[1:]) or input("輸入問題：")
    for p in asyncio.run(research(question)):
        print(f"\n■ {p['title']}\n  {p['url']}\n  {p['text'][:150]!r}…")
