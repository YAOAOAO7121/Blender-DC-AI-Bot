"""
本地知識庫檢索（不需網路、不需額外套件）

用法：
- 把教學筆記寫成 .md 放進 knowledge/ 資料夾（可以有子資料夾）
- 每個 "## 小標題" 會被切成一段，檢索時以「段」為單位
- 檔案有新增或修改時會自動重新讀取，不用重開機器人
- 檔名以 _ 開頭的檔案不會被讀取（可以放說明或草稿）

單獨測試：python knowledge.py 怎麼縮放物件
"""
import math
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge")
MAX_CHUNK_CHARS = 1200   # 單段太長就再依空行切開
HEADING_BOOST = 1.5      # 問題的字詞出現在小標題時的加分倍數

# 問句裡常見、但對找資料沒幫助的詞
STOP_BIGRAMS = {
    "怎麼", "什麼", "如何", "可以", "請問", "老師", "為什", "麼要", "要怎", "麼做",
    "一下", "我的", "我要", "我想", "想要", "是不", "不是", "有沒", "沒有", "這個",
    "那個", "時候", "的時", "了嗎", "怎樣", "麼辦", "應該", "需要", "問題", "請教",
    "知道", "還是", "然後", "就是", "因為", "所以", "一個", "一樣", "不一", "平常",
}
STOP_WORDS = {"the", "a", "an", "to", "of", "in", "is", "how", "do", "i", "blender", "can", "what"}

CJK = "㐀-鿿豈-﫿"
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
          "十": 10, "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
          "十六": 16, "十七": 17, "十八": 18}


def normalize(text):
    text = text.lower().replace("周", "週").replace("禮拜", "週")
    # 「第七週」「第 7 週」「第7周」都統一成 week7
    text = re.sub(r"第\s*([一二三四五六七八九十]+|\d+)\s*週",
                  lambda m: f" week{CN_NUM.get(m.group(1), m.group(1))} ", text)
    return text


def tokenize(text):
    """中文切成相鄰兩字（bigram），英文/數字/快捷鍵切成單字"""
    text = normalize(text)
    tokens = []
    for w in re.findall(r"[a-z0-9][a-z0-9_.+\-]*", text):
        w = w.strip(".-")
        if w and w not in STOP_WORDS:
            tokens.append(w)
    for run in re.findall(f"[{CJK}]+", text):
        if len(run) == 1:
            tokens.append(run)
        for i in range(len(run) - 1):
            bg = run[i:i + 2]
            if bg not in STOP_BIGRAMS and bg[0] != "麼":   # 「麼用」「麼弄」之類都是問句尾巴
                tokens.append(bg)
    return tokens


@dataclass
class Chunk:
    source: str              # 檔名，例如 02_物件基本操作.md
    title: str               # 「檔案標題 › 小標題」
    text: str
    heading: str = ""
    doc_title: str = ""
    tf: Counter = field(default_factory=Counter)
    length: int = 0
    heading_tokens: set = field(default_factory=set)
    links: list = field(default_factory=list)   # 網路整理的筆記會記錄來源網址


def _split_markdown(path, rel):
    with open(path, encoding="utf-8-sig") as f:
        raw = f.read()
    # <!-- --> 註解裡放的是來源、整理時間等資訊：取出網址，但不拿來檢索
    comments = " ".join(re.findall(r"<!--(.*?)-->", raw, re.S))
    links = list(dict.fromkeys(re.findall(r"https?://[^\s<>()]+", comments)))
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    doc_title = os.path.splitext(os.path.basename(rel))[0]
    m = re.search(r"^#\s+(.+)$", raw, re.M)
    if m:
        doc_title = m.group(1).strip()

    sections, heading, buf = [], None, []
    for line in raw.splitlines():
        if line.startswith("## "):
            if buf:
                sections.append((heading, "\n".join(buf).strip()))
            heading, buf = line[3:].strip(), []
        elif line.startswith("# "):
            continue  # 檔案大標題已記在 doc_title
        else:
            buf.append(line)
    if buf:
        sections.append((heading, "\n".join(buf).strip()))

    chunks = []
    for heading, body in sections:
        if not body:
            continue
        title = f"{doc_title} › {heading}" if heading else doc_title
        parts, cur = [], ""
        for para in re.split(r"\n\s*\n", body):
            if cur and len(cur) + len(para) > MAX_CHUNK_CHARS:
                parts.append(cur)
                cur = para
            else:
                cur = f"{cur}\n\n{para}" if cur else para
        if cur:
            parts.append(cur)
        for p in parts:
            chunks.append(Chunk(source=rel, title=title, text=p,
                                heading=heading or "", doc_title=doc_title, links=links))
    return chunks


class KnowledgeBase:
    def __init__(self, folder=KNOWLEDGE_DIR):
        self.folder = folder
        self.chunks = []
        self.df = Counter()
        self.avgdl = 1.0
        self._signature = None

    def _scan(self):
        files = []
        if os.path.isdir(self.folder):
            for root, _, names in os.walk(self.folder):
                for n in names:
                    if n.lower().endswith((".md", ".txt")) and not n.startswith("_"):
                        p = os.path.join(root, n)
                        files.append((p, os.path.getmtime(p)))
        return sorted(files)

    def reload_if_changed(self):
        files = self._scan()
        if files == self._signature:
            return
        self._signature = files
        chunks = []
        for path, _ in files:
            rel = os.path.relpath(path, self.folder)
            try:
                chunks.extend(_split_markdown(path, rel))
            except Exception as e:
                print(f"[知識庫] 讀取失敗 {rel}：{e}")
        df = Counter()
        for c in chunks:
            toks = tokenize(c.doc_title) + tokenize(c.heading) + tokenize(c.text)
            c.tf = Counter(toks)
            c.length = len(toks)
            c.heading_tokens = set(tokenize(c.heading))
            df.update(set(toks))
        self.chunks, self.df = chunks, df
        self.avgdl = (sum(c.length for c in chunks) / len(chunks)) if chunks else 1.0
        print(f"[知識庫] 已載入 {len(files)} 個檔案、{len(chunks)} 段")

    def search(self, query, k=3, min_score=None, k1=1.5, b=0.75):
        """回傳 [(分數, Chunk), ...]，分數由高到低；找不到回傳空清單"""
        self.reload_if_changed()
        if min_score is None:
            min_score = float(os.getenv("KB_MIN_SCORE", "4.0"))
        q = set(tokenize(query))
        if not q or not self.chunks:
            return []
        n = len(self.chunks)
        scored = []
        for c in self.chunks:
            s = 0.0
            for t in q:
                f = c.tf.get(t)
                if not f:
                    continue
                idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * c.length / self.avgdl))
                if t in c.heading_tokens:
                    s += idf * HEADING_BOOST
            if s >= min_score:
                scored.append((s, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:k]


def format_context(hits):
    """把找到的資料整理成要給 AI 看的文字"""
    return "\n\n".join(f"[資料{i}] {c.title}（{c.source}）\n{c.text}"
                       for i, (_, c) in enumerate(hits, 1))


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    kb = KnowledgeBase()
    query = " ".join(sys.argv[1:]) or input("輸入問題：")
    threshold = float(os.getenv("KB_MIN_SCORE", "4.0"))
    hits = kb.search(query, k=5, min_score=0.01)
    if not hits:
        print("找不到任何相關段落 → 機器人會用 AI 的一般知識回答")
    for s, c in hits:
        mark = "✔ 會被採用" if s >= threshold else "✘ 低於門檻"
        print(f"{s:6.2f}  {mark}  {c.title}  ({c.source})")
