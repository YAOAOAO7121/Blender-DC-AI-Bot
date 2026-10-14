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


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or input("輸入問題：")
    for p in asyncio.run(research(question)):
        print(f"\n■ {p['title']}\n  {p['url']}\n  {p['text'][:150]!r}…")
