"""本地 AI 知識檢索：預設讀取 knowledge_local_ai。
只載入具 kb JSON 中繼資料且狀態為 approved/source_checked 的文件。
每個 ## 標題為一段；排除待審核及原文；文件修改最多一秒後生效。
python -X utf8 knowledge.py Blender 5.0 合成器怎麼啟用
KB_VERSION 可設定課程預設版本；未設定時僅檢索通用概念。
"""
import math
import json
import time
from pathlib import Path
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_DIR = os.getenv("KB_ROOT", os.path.join(BASE_DIR, "knowledge_local_ai"))
SUPPORTED_VERSIONS = {"4.2", "5.0"}
CACHE_FORMAT = 3
ALIASES = (("倒角", "bevel"), ("鏡像", "mirror"), ("布林", "boolean"),
           ("法線", "normal", "normals"), ("縮放", "scale"),
           ("貼圖", "texture"), ("合成器", "compositor", "compositing"),
           ("細分", "subdivision", "subsurf"), ("展開", "unwrap"))

def query_tokens(query):
    expanded = query.lower()
    for group in ALIASES:
        if any((re.search(r"\b" + re.escape(w) + r"\b", expanded) if w.isascii() else w in expanded) for w in group):
            expanded += " " + " ".join(group)
    return set(tokenize(expanded))

def requested_versions(query, default=None):
    # Never silently substitute an unsupported explicit version with the default.
    numbers = re.findall(r"(?<![\d.])(\d+\.\d+)(?:\.\d+)?(?![\d.])", query)
    explicit = re.findall(r"(?:blender\s*|版本\s*|\bv)(\d+\.\d+)(?:\.\d+)?", query, re.I)
    found = set(explicit) | (set(numbers) & SUPPORTED_VERSIONS)
    if found:
        return found
    configured = default if default is not None else os.getenv("KB_VERSION", "")
    return {configured} if configured else set()

def read_metadata(path):
    raw = Path(path).read_text(encoding="utf-8-sig")
    m = re.search(r"<!--\s*kb:\s*(\{.*?\})\s*-->", raw, re.S)
    return json.loads(m.group(1)) if m else {}

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
    versions: tuple = ()
    topic: str = ""
    status: str = ""
    license: str = ""
    attribution: str = ""
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
    """Local, dependency-free retrieval. Approved metadata is required by default.

    Scan at most once per second; persist per-file parsed chunks; score only posting
    candidates in common knowledge plus the explicitly selected supported version.
    Returned chunk identities remain stable between unchanged scans for bot.py.
    """
    def __init__(self, folder=KNOWLEDGE_DIR, version=None, scan_interval=1.0, cache_path=None):
        self.folder = os.path.abspath(folder)
        self.version = version
        self.scan_interval = scan_interval
        self.chunks = []
        self.df = Counter()
        self.avgdl = 1.0
        self._signature = None
        self._next_scan = 0.0
        self.postings = {}
        self.file_cache = {}
        self.last_stats = {}
        self.cache_path = Path(cache_path) if cache_path else Path(self.folder) / "_cache" / "index.json"
        try:
            cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if cached.get("format") == CACHE_FORMAT and cached.get("root") == self.folder:
                self.file_cache = cached["files"]
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def _scan(self):
        files = []
        for root, dirs, names in os.walk(self.folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith(("_", ".")) and d not in
                             {"待審核", "官方原文", "原文", "backup", "網路整理"})
            for name in sorted(names):
                if name.lower().endswith((".md", ".txt")) and not name.startswith(("_", ".")):
                    p = os.path.join(root, name)
                    stat = os.stat(p)
                    files.append((p, stat.st_mtime_ns, stat.st_size))
        return sorted(files)

    def reload_if_changed(self, force=False):
        now = time.monotonic()
        if not force and now < self._next_scan:
            return
        self._next_scan = now + self.scan_interval
        files = self._scan()
        if files == self._signature and not force:
            return
        chunks, cache = [], {}
        for path, modified, size in files:
            rel = os.path.relpath(path, self.folder).replace("\\", "/")
            signature = [modified, size]
            old = self.file_cache.get(rel)
            try:
                if old and old.get("signature") == signature and not force:
                    records = old["chunks"]
                else:
                    meta = read_metadata(path)
                    if meta.get("status") not in {"approved", "source_checked"}:
                        # Flat legacy notes require an explicit opt-in, never enabled by install.
                        if os.getenv("KB_ALLOW_LEGACY", "0") != "1" or "/" in rel:
                            continue
                        meta = {"versions": [], "status": "legacy-unverified"}
                    records = []
                    for c in _split_markdown(path, rel):
                        c.versions = tuple(meta.get("versions", []))
                        c.topic = meta.get("topic", category_of(rel))
                        c.status = meta.get("status", "")
                        c.license = meta.get("license", "unknown")
                        c.attribution = meta.get("attribution", "未標示作者")
                        c.links = list(dict.fromkeys(u.rstrip('" ,]}') for u in (meta.get("urls") or c.links)))
                        records.append({"source": c.source, "title": c.title, "text": c.text,
                                        "heading": c.heading, "doc_title": c.doc_title,
                                        "versions": list(c.versions), "topic": c.topic,
                                        "status": c.status, "license": c.license,
                                        "attribution": c.attribution, "links": c.links})
                cache[rel] = {"signature": signature, "chunks": records}
                chunks.extend(Chunk(**record) for record in records)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                print(f"[知識庫] 跳過無法驗證的文件 {rel}: {exc}")
        self._index(chunks, cache, files)

    def _index(self, chunks, cache, files):
        # Collapse exact same text only within the same version scope and topic.
        # Keep all contributing URLs so deduplication does not discard attribution.
        unique = {}
        for c in chunks:
            key = (tuple(c.versions), c.topic, re.sub(r"\s+", " ", c.text).strip())
            if key in unique:
                previous = unique[key]
                previous.links = list(dict.fromkeys(previous.links + c.links))
            else:
                unique[key] = c
        chunks = list(unique.values())
        df, postings = Counter(), {}
        for i, c in enumerate(chunks):
            toks = tokenize(c.doc_title) + tokenize(c.heading) + tokenize(c.text)
            c.tf = Counter(toks)
            c.length = len(toks)
            c.heading_tokens = set(tokenize(c.heading))
            df.update(set(toks))
            for token in c.tf:
                postings.setdefault(token, set()).add(i)
        self.chunks, self.df, self.postings = chunks, df, postings
        self.avgdl = sum(c.length for c in chunks) / len(chunks) if chunks else 1.0
        self.file_cache, self._signature = cache, files
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"format": CACHE_FORMAT, "root": self.folder,
                                       "files": cache}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.cache_path)
        except OSError:
            pass  # Read-only deployments still work with the in-memory index.

    def search(self, query, k=3, min_score=None, k1=1.5, b=0.75, version=None):
        self.reload_if_changed()
        if min_score is None:
            min_score = float(os.getenv("KB_MIN_SCORE", "4.0"))
        versions = requested_versions(query, version if version is not None else self.version)
        if versions - SUPPORTED_VERSIONS:
            self.last_stats = {"total_chunks": len(self.chunks), "scored_candidates": 0,
                               "versions": sorted(versions), "reason": "unsupported_version"}
            return []
        q = query_tokens(query)
        candidates = set()
        for token in q:
            candidates.update(self.postings.get(token, ()))
        scored, n, count = [], len(self.chunks), 0
        for i in sorted(candidates):
            c = self.chunks[i]
            is_versioned = c.source.startswith("版本/")
            if is_versioned and not (versions & set(c.versions)):
                continue
            if not is_versioned and versions and c.versions and not (versions & set(c.versions)):
                continue
            count += 1
            score = 0.0
            for token in q:
                f = c.tf.get(token, 0)
                if f:
                    idf = math.log(1 + (n - self.df[token] + 0.5) / (self.df[token] + 0.5))
                    score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * c.length / self.avgdl))
                    if token in c.heading_tokens:
                        score += idf * HEADING_BOOST
            if score >= min_score and score > 0:
                scored.append((score, c))
        scored.sort(key=lambda pair: (-pair[0], pair[1].source, pair[1].heading))
        self.last_stats = {"total_chunks": n, "scored_candidates": count,
                           "versions": sorted(versions), "reason": "ok"}
        return scored[:k]


    def coverage(self, query, hits):
        """問題裡的關鍵字（越少見的字權重越高）有多少比例出現在找到的資料裡，0~1
        搜尋分數會隨問題變長而變高，所以另外用這個判斷「資料是不是真的在講這題」"""
        q = set(tokenize(query))
        if not q or not hits:
            return 0.0
        n = len(self.chunks)

        def idf(t):
            return math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))

        found = set().union(*(set(c.tf) for _, c in hits))
        total = sum(idf(t) for t in q)
        return sum(idf(t) for t in q & found) / total if total else 0.0



LEGACY_ROOT = os.getenv("KB_LEGACY_ROOT", os.path.join(BASE_DIR, "knowledge"))
LEGACY_STATUS = "legacy-unverified"


class LegacyKnowledgeBase(KnowledgeBase):
    """原本的 knowledge/ 課程筆記（含老師審核後移入的 網路整理/）。
    尚未逐段審核、版本未標示，只在已核對資料找不到時當作後備。"""
    def __init__(self, folder=LEGACY_ROOT, **kw):
        kw.setdefault("cache_path", Path(KNOWLEDGE_DIR) / "_cache" / "legacy_index.json")
        super().__init__(folder, **kw)

    def _scan(self):
        files = []
        for root, dirs, names in os.walk(self.folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith(("_", ".")))
            for name in sorted(names):
                if name.lower().endswith((".md", ".txt")) and not name.startswith(("_", ".")):
                    p = os.path.join(root, name)
                    st = os.stat(p)
                    files.append((p, st.st_mtime_ns, st.st_size))
        return sorted(files)

    def reload_if_changed(self, force=False):
        self._legacy_reload(force)

    def _legacy_reload(self, force):
        now = time.monotonic()
        if not force and now < self._next_scan:
            return
        files = self._scan()
        if files == self._signature and not force:
            self._next_scan = now + self.scan_interval
            return
        # 父類別只接受根目錄的平面檔；網路整理/ 在子目錄，所以這裡自己解析
        chunks, cache = [], {}
        for path, modified, size in files:
            rel = os.path.relpath(path, self.folder).replace("\\", "/")
            sig = [modified, size]
            old = self.file_cache.get(rel)
            try:
                if old and old.get("signature") == sig and not force:
                    records = old["chunks"]
                else:
                    web = rel.startswith("網路整理/")
                    records = []
                    for c in _split_markdown(path, rel):
                        records.append({"source": c.source, "title": c.title, "text": c.text,
                                        "heading": c.heading, "doc_title": c.doc_title,
                                        "versions": [], "topic": category_of(rel),
                                        "status": LEGACY_STATUS,
                                        "license": "課程筆記，未逐檔標示授權",
                                        "attribution": "網路整理筆記" if web else "原課程筆記（待教師審核）",
                                        "links": c.links})
                cache[rel] = {"signature": sig, "chunks": records}
                chunks.extend(Chunk(**r) for r in records)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                print(f"[舊筆記] 跳過 {rel}: {exc}")
        self._index(chunks, cache, files)
        self._next_scan = now + self.scan_interval


class LayeredKnowledgeBase:
    """先查已核對的 knowledge_local_ai；覆蓋率不足時才退回舊課程筆記。
    KB_LEGACY_FALLBACK=0 可關閉後備。"""
    def __init__(self, primary=None, legacy=None):
        self.primary = primary or KnowledgeBase()
        if legacy is None and os.getenv("KB_LEGACY_FALLBACK", "1") == "1" and os.path.isdir(LEGACY_ROOT):
            legacy = LegacyKnowledgeBase()
        self.legacy = legacy
        self.last_stats = {}

    @property
    def chunks(self):
        return self.primary.chunks + (self.legacy.chunks if self.legacy else [])

    def reload_if_changed(self, force=False):
        self.primary.reload_if_changed(force)
        if self.legacy:
            self.legacy.reload_if_changed(force)

    def _owner(self, hits):
        if self.legacy and hits and hits[0][1].status == LEGACY_STATUS:
            return self.legacy
        return self.primary

    def coverage(self, query, hits):
        return self._owner(hits).coverage(query, hits)

    def search(self, query, k=3, min_score=None, **kw):
        hits = self.primary.search(query, k=k, min_score=min_score, **kw)
        self.last_stats = dict(self.primary.last_stats, tier="checked")
        if self.primary.last_stats.get("reason") == "unsupported_version" or not self.legacy:
            return hits
        # 已核對資料量還小，關鍵字稍微沾到邊就會被選中；所以除非它夠貼題、
        # 而且不比舊筆記差太多，否則改用舊筆記（避免「影片格式」配到「布林」）。
        min_cov = float(os.getenv("KB_MIN_COVERAGE", "0.15"))
        strong = float(os.getenv("KB_CHECKED_MIN_COVERAGE", "0.4"))
        ratio = float(os.getenv("KB_CHECKED_RATIO", "0.5"))
        pc = self.primary.coverage(query, hits[:3]) if hits else 0.0
        old = self.legacy.search(query, k=k, min_score=min_score)
        lc = self.legacy.coverage(query, old[:3]) if old else 0.0
        if hits and pc >= min_cov and (lc < min_cov or (pc >= strong and pc >= ratio * lc)):
            return hits
        if old and lc >= min_cov:
            self.last_stats = dict(self.legacy.last_stats, tier="legacy")
            return old
        return hits

# 分類時不算章節的檔案（跨主題的常見問題、AI 從網路整理的筆記）
CATEGORY_SKIP = ("98_", "99_", "網路整理")


def category_of(source):
    """06_修改器.md → 06_修改器；網路整理/xxx.md → 網路整理"""
    return os.path.splitext(source.replace("\\", "/").split("/")[-1])[0]


def classify(kb, query, k=8):
    """把問題歸到課程知識庫的章節（例如 06_修改器），找不到回傳「未分類」
    用比較低的門檻搜尋，所以就算這題最後是上網查的，也能歸到最接近的章節；
    同一章節的分數加總，避免被單一段落帶偏"""
    hits = kb.search(query, k=k, min_score=0.5)
    scores = Counter()
    for s, c in hits:
        cat = c.topic or category_of(c.source)
        if not cat.startswith(CATEGORY_SKIP):
            scores[cat] += s
    return scores.most_common(1)[0][0] if scores else "未分類"


def format_context(hits):
    sections = []
    for i, (_, c) in enumerate(hits, 1):
        versions = ", ".join(c.versions) if c.versions else "版本未驗證"
        links = "\n".join(c.links[:4])
        sections.append(f"[資料{i}] {c.title}（{c.source}）\n"
                        f"適用版本：{versions}；審核狀態：{c.status}；授權：{c.license}；作者：{c.attribution}\n"
                        f"{c.text}\n來源：\n{links}")
    return "\n\n".join(sections)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    kb = KnowledgeBase()
    query = " ".join(sys.argv[1:]) or input("輸入問題：")
    threshold = float(os.getenv("KB_MIN_SCORE", "4.0"))
    hits = kb.search(query, k=5, min_score=0.01)
    if not hits:
        print("找不到已核對的相關段落；操作問題請指定 Blender 4.2 或 5.0，不應直接猜版本")
    for s, c in hits:
        mark = "✔ 會被採用" if s >= threshold else "✘ 低於門檻"
        print(f"{s:6.2f}  {mark}  {c.title}  ({c.source})")
    if hits:
        cov = kb.coverage(query, hits[:3])
        min_cov = float(os.getenv("KB_MIN_COVERAGE", "0.15"))
        print(f"關鍵字覆蓋率 {cov:.2f}（門檻 {min_cov}）→ {'用知識庫' if cov >= min_cov else '視為沒資料、上網查'}")
    print(f"分類：{classify(kb, query)}")
    print(format_context(hits[:3]))
    print(kb.last_stats)
