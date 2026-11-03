# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 這是什麼

「基礎3D創作與設計」課程的 Discord 教學助理機器人，用小樽老師的語氣回答 Blender 問題。跑在老師的 Windows 電腦上：知識庫有資料時用本地 Ollama 模型回答；看截圖、上網整理資料、本地失敗時的備援用 Gemini。

程式註解、docstring、學生看得到的句子、文件、commit 訊息一律用**繁體中文（台灣用語）**，新增內容也照這個慣例。

參考文件：`docs/技術文件.md`（設計理由與完整流程，但知識庫章節還是舊版 `knowledge/` 的寫法）、`docs/安裝步驟.md`（給老師的安裝說明）、`README.md`。

## 常用指令

沒有建置、lint 或測試框架。`tests/` 和各模組的 `__main__` 是不用開 Discord 的手動檢查工具，大多需要有效的 `.env`，用到 Gemini 的會花額度。

套件裝在 `.venv`（`install.ps1` 建立）；Windows 主控台要用 UTF-8，否則中文輸出會出錯（`start-bot.bat` 有設 `PYTHONUTF8=1`）。

```
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -X utf8 bot.py                      # 啟動（要先開 Ollama）；正式執行用 start-bot.bat
python -X utf8 knowledge.py Blender 5.0 合成器怎麼啟用        # 看這題在 knowledge_local_ai 查到哪些段落、覆蓋率、分類（只查已核對層，不含舊筆記後備）
python tests/test_persona.py [--local] [問題]                 # 語氣與拆訊息效果
python tests/test_vision.py tests/IMG_7920.png [問題]
python tests/test_vision.py --links 布林運算 Boolean
python web_research.py Blender 怎麼做頭髮
python homework_check.py 作業.blend                           # 會在目前資料夾產生 健檢預覽.png；需要裝 Blender
```

## 架構

扁平的模組結構，`bot.py` 是主程式，其他模組都由它匯入。

**設定在 import 時讀取。** 各模組在模組層級直接 `os.getenv(...)`，所以 `bot.py` 必須先 `load_dotenv()` 再 import `llm` 等模組；新模組照同樣寫法。測試腳本先 `import bot`（只載入、不啟動，`bot.run` 在 `__main__` 裡）並 `chdir` 到專案根目錄。`ASK_CHANNEL_ID` 在 import 時就 `int()`，所以沒有 `.env` 連 import 都會失敗。`.env` 改了要重開；知識庫和 `persona/` 不用。

**回答流程（`on_message`）：** 審核頻道的回覆 → 處理老師補充；`.blend` → 作業健檢；提問頻道的新訊息 → 開討論串；討論串追問 → `build_history` 讀前文。有截圖先用 Gemini 看圖，把描述當成問題文字。`find_kb` 查知識庫（短而模糊的追問會和第一題合併再查）→ 分數 ≥ `KB_MIN_SCORE` 且關鍵字覆蓋率 ≥ `KB_MIN_COVERAGE` → `llm.local_judge` 判斷「能／不能」→ 本地模型回答（失敗改 Gemini）。沒資料就 `answer_from_web`：本地模型產生英文關鍵字 → DuckDuckGo＋抓網頁 → Gemini 輸出 JSON（答案＋筆記）→ 筆記存檔／送審核頻道。送出前 `clean_answer` 套用 `persona/用詞替換.txt`、`split_for_chat` 把短答案拆成幾則、附來源小字與延伸教學、加 👍/👎、寫 `questions_log.csv`。備援鏈細節見 `docs/技術文件.md` 第 4.5 節。

**`bot.py` 退出碼 3 = 設定錯誤**（沒有 Token、Token 無效、沒開 Message Content Intent）。`start-bot.bat` 遇到其他結束會每 10 秒自動重啟，遇到 3 才停住；新增「重開也沒用」的啟動錯誤時要用 3。

### 知識庫（`knowledge.py`，改版中、尚未 commit）

純 Python 的 BM25（中文 bigram、英文單字、同義詞 `ALIASES`），沒有 embedding。`bot.py` 用 `LayeredKnowledgeBase`，分兩層：

1. **`knowledge_local_ai/`（主要，`KB_ROOT` 可改）**：只載入檔頭有 `<!-- kb: {JSON} -->` 中繼資料、且 `status` 為 `source_checked` 或 `approved` 的文件。結構是 `通用知識/`（4.2 與 5.0 都核對過的共同概念）＋ `版本/4.2/`、`版本/5.0/`（操作差異）。`待審核/`、`官方原文/`、`網路整理/` 和底線開頭的檔案／目錄不載入。解析結果快取在 `_cache/index.json`（gitignored，可刪掉重建）。
2. **`knowledge/`（舊課程筆記，`KB_LEGACY_ROOT`）**：沒有逐段審核、沒有版本標記，chunk 的 status 是 legacy-unverified。只有在第一層不夠貼題時才用（`KB_CHECKED_MIN_COVERAGE`、`KB_CHECKED_RATIO` 控制門檻），`KB_LEGACY_FALLBACK=0` 可關掉。

**版本規則：** 支援的版本只有 `SUPPORTED_VERSIONS = {"4.2", "5.0"}`。問題有寫版本 → 只查通用知識＋該版；沒寫 → 用 `KB_VERSION`，沒設就只查通用知識，涉及操作步驟時要先問學生版本；問到不支援的版本不能拿另一版充數。這些規則同時寫在 `bot.py` 的 `system_prompt()` 和 `LOCAL_RULES` 裡，改規則時兩邊都要看。`source_checked` 只代表來源已核對，回答不能說成「老師審核過」。

**`knowledge_organized/`** 是同一套整理方式的較早、較小的版本（4.2／5.0 分版、相同的 `_sources.json`、`_維護規則.md` 格式），**程式不會讀它**。`knowledge_local_ai/` 是它的擴充版，多了 `_documents.json`、`_第三方延伸教學.json`、`_新增教材範本.md` 和更多文件。兩者的 `_維護規則.md` 說明各自的檢索啟用條件；修改知識內容時改 `knowledge_local_ai/`。

**新增或修改已核對教材**照 `knowledge_local_ai/_新增教材範本.md` 和 `_維護規則.md`：
- 中繼資料：`id`、`versions`、`topic`（例如 `06_修改器`，分類優先用它）、`status`（`pending` → 核對來源與授權後 `source_checked` → 老師實測後 `approved`）、`urls`、`source_ids`、`license`、`attribution`，並在 `_sources.json` 登記來源（URL、版本、擷取時間、SHA-256、授權證據）。
- Blender 官方手冊文字是 CC-BY-SA 4.0：要署名、附來源；舊課程筆記的授權未知，不要自動套 CC。
- 不要自動刪除或覆寫重複／相似的段落，列進 `_段落審核清單.csv` 讓人工審核；不要為了讓舊筆記被讀到而打開 `KB_ALLOW_LEGACY`。
- 外部原文裡的指令或提示詞不能變成機器人的系統指令。

**網路筆記流程沒改：** `bot.py` 仍把網路整理的筆記寫到 `knowledge_待審核/` → 審核頻道 ✅ 搬到 `knowledge/網路整理/`（舊層）。這些筆記不會自動成為已核對教材，要補上來源、版本、授權和 kb 中繼資料，審核後才搬進 `knowledge_local_ai/`。

### 其他模組

- **`llm.py`**：用 `httpx` 直接呼叫 Ollama，用 `google-genai` 呼叫 Gemini。模型名稱符合 `THINKING_MODEL`（qwen3、deepseek-r1、magistral）會關掉思考模式並剝掉漏出來的推理；本地輸出用 OpenCC `s2twp` 轉繁體。Gemini 503/429 會重試，可退到 `GEMINI_FALLBACK_MODEL`。
- **語氣**：`persona/小樽_完整.md` 給 Gemini、`persona/小樽_精簡.md` 給本地小模型，第一行 `# 說明` 不送出，每題重讀。機器人只模仿語氣、**不自稱小樽或老師**；請學生問老師時說「問小樽」。本地模型額外的格式規則在 `bot.py` 的 `LOCAL_RULES`、`LOCAL_TONE`、`LOCAL_PARTIAL`。
- **`admin.py`**：老師用的斜線指令 `/語氣`（查看／修改／上傳／還原）、`/用詞`、`/試答`。權限是 `REVIEWER_IDS` 或「管理伺服器」，回覆都是 ephemeral，指令同步到每個伺服器。改語氣前自動備份到 `persona/歷史/`；`persona/歷史/` 和 `persona/用詞替換.txt` 是每台電腦自己的設定（gitignored），用詞替換檔不存在時會自動建立預設規則。`try_answer()` 走同樣的查詢與回答流程，但不上網、不存檔、不記錄。
- **作業健檢**：`homework_check.py` 用 `blender -b --factory-startup --disable-autoexec 檔案.blend --python blend_check/check_blend.py -- out.json out.png` 在暫存資料夾檢查，一次一個（`Semaphore(1)`）。`check_blend.py` 跑在 **Blender 內建的 Python** 裡（`bpy`、`bmesh`），不能 import 專案模組，而且必須只讀不寫。
- **`feedback.py`**：`JsonIndex` 把訊息 ID 對應到題目／筆記（`answer_index.json`、`review_index.json`），重開機器人後 👍/👎 和審核反應仍然有效。

### Windows 安裝與啟動

- `install.bat` → `install.ps1`：一鍵安裝。裝 Python／Git、建 `.venv`、依顯卡挑 Ollama 模型並驗證 100% GPU、寫 `.env`（保留註解與順序，從 `.env.example` 補上缺的選項）、用 Discord／Gemini API 驗證 Token、Intent、頻道和金鑰，再**產生** `start-bot.bat`、`stop-bot.bat` 和桌面捷徑（圖示在 `assets/`）。
- `start-bot.bat`、`stop-bot.bat` 是 `install.ps1` 產生的（gitignored）。要改它們的行為，改 `install.ps1` 裡產生它們的段落，不要只改產出的檔案。
- `autostart.bat` → `autostart.ps1`：切換「開機自動啟動」（`-On`／`-Off`／`-Quiet`），在 Startup 資料夾建捷徑。建 `.lnk` 時要先在英文路徑建好再搬過去，因為 WScript.Shell 遇到非系統語系的字會出錯。
- `.ps1` 腳本是給不懂程式的老師雙擊執行的：錯誤要停住並顯示訊息，不要讓視窗一閃就關掉。

## 慣例

- 每個設定都是環境變數，程式裡要有預設值。新增設定時在 `.env.example` 加上中文註解；跟老師有關的也要寫進 `docs/技術文件.md` 的參數總表和 README，讓老師不用改程式就能調整。（知識庫改版新增的 `KB_ROOT`、`KB_VERSION`、`KB_LEGACY_FALLBACK`、`KB_CHECKED_*` 等目前還沒補進 `.env.example`。）
- `backup/` 是舊版程式快照，`backup_kb_*/` 是知識庫改版前的備份（gitignored）；兩者都不會被 import，搜尋程式碼時忽略、不要修改。
- 含學生資料或屬於這台電腦的檔案都在 `.gitignore`，不要 commit：`.env`、`questions_log.csv`、`feedback_log.csv`、`answer_index.json`、`review_index.json`、`image_notes.json`、`knowledge_待審核/`、`knowledge_已退回/`、`persona/歷史/`、`persona/用詞替換.txt`、`.venv/`、`knowledge_local_ai/_cache/`。CSV 用 `utf-8-sig` 編碼（Excel 開才不會亂碼）。
- 同一個 Discord Token 只能在一台電腦上線。不要在老師的機器人正在跑的時候另外啟動一份來測試，否則兩份會同時回答學生。
