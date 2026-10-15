# Blender 課程 AI 教學助理（Discord 機器人）

## 啟動
```
python bot.py
```
（要先開 Ollama；設定都在 `.env`，可以調的選項看 `.env.example`）

## 在新電腦架設（換電腦／換更強的本地模型）
> ⚠️ 同一個 Discord Token 只能在一台電腦跑，**先關掉舊電腦的機器人**，不然兩台會同時回答。

### 1. 確認顯卡
終端機輸入 `nvidia-smi`，看顯卡型號和記憶體（例如 `24564MiB` = 24GB），第 4 步要用。

### 2. 安裝環境
1. 安裝 Python 3.10 以上（安裝時勾「Add Python to PATH」）
2. 安裝 Git，下載程式並裝套件：
   ```
   git clone https://github.com/YAOAOAO7121/Blender-DC-AI-Bot.git
   cd Blender-DC-AI-Bot
   pip install -r requirements.txt
   ```
3. 安裝 [Ollama](https://ollama.com)
4. （要用作業健檢才需要）安裝 Blender；不是裝在 `C:\Program Files\Blender Foundation\` 就在 `.env` 填 `BLENDER_PATH`，不用就設 `BLEND_CHECK=0`

### 3. 帶過去的檔案（不在 GitHub 上，要自己複製）
- **`.env`（必要）**：有 Discord Token 和 Gemini 金鑰，用隨身碟或私人雲端複製，**不要用 Discord 或公開的地方傳**
- 想延續舊紀錄才需要：`questions_log.csv`、`feedback_log.csv`、`answer_index.json`、`review_index.json`、`image_notes.json`、`knowledge_待審核/`、`knowledge_已退回/`

### 4. 依顯卡挑本地模型
| 顯卡記憶體 | 建議模型 | 下載指令 | `LOCAL_CTX` |
|---|---|---|---|
| 4–8GB | Qwen 3 4B / 8B | `ollama pull qwen3:4b` | 4096 |
| 12–16GB | Qwen 3.5 9B | `ollama pull qwen3.5:9b` | 8192 |
| 24GB（RTX 3090/4090） | Qwen 3.6 27B | `ollama pull qwen3.6:27b` | 16384 |
| 32GB（RTX 5090） | Qwen 3.6 35B | `ollama pull qwen3.6:35b` | 16384 |
| 80GB 以上 | Qwen 3.5 122B | `ollama pull qwen3.5:122b` | 32768 |

- 模型要**整個放進顯卡**：先 `ollama run 模型名稱` 問一句，再開另一個終端機打 `ollama ps`，顯示 `100% GPU` 才 OK；出現 CPU/GPU 混合就換小一級
- 建議用 Qwen 系列：中文好，而且名稱含 `qwen3` 的模型，程式會自動關掉「思考模式」
- **不建議** `gemma4`、`deepseek-r1` 這類會思考的模型（可能把思考過程當答案）；要用 gemma4 得先把它加進 `llm.py` 的 `THINKING_MODEL` 名單
- `qwen2.5:72b` 也能用（不用改程式），但要約 48GB 顯卡記憶體，而且比 `qwen3.5:27b` 舊、慢
- 模型名稱更新很快，下載前到 [ollama.com/library](https://ollama.com/library) 確認

### 5. 修改 `.env`
```
LOCAL_MODEL=qwen3.6:27b      ← 換成第 4 步選的模型
LOCAL_CTX=16384              ← 照上表
USE_LOCAL=1
LOCAL_JUDGE=1
LOCAL_KEEP_RATIO=0.5         ← 大模型比較不會抓錯，可以多看幾段資料（小模型維持 0.7）
```
舊的 `.env` 如果沒有 v13 的選項（`FEEDBACK`、`REVIEW_CHANNEL_ID`、`REVIEWER_IDS`、`BLEND_CHECK`…），從 `.env.example` 補上。

### 6. 讓模型常駐顯卡
Ollama 預設閒置 5 分鐘就卸載模型，大模型重新載入很慢，可能超過程式 180 秒逾時而改用 Gemini。
Windows 新增系統環境變數 `OLLAMA_KEEP_ALIVE`，值設 `-1`（永不卸載），然後重開 Ollama。

### 7. 測試再上線
```
python tests/test_persona.py --local     測語氣和速度
python knowledge.py 布林運算怎麼用         測知識庫查詢
python bot.py                            正式啟動
```
啟動訊息出現「本地模型就緒：模型名稱」就成功；出現「⚠️ 找不到本地模型」代表 Ollama 沒開或名稱打錯（會改用 Gemini）。

> 換了強的本地模型，**看截圖、網路資料整理成筆記、本地答不出來時的備援**仍然用 Gemini，所以 `GEMINI_API_KEY` 還是要填。
> 電腦要一直開著機器人才在線上；學生那邊不用裝任何東西。

## 檔案說明
| 檔案／資料夾 | 用途 |
|---|---|
| `bot.py` | 機器人主程式：收問題、查資料、回答、記錄 |
| `knowledge.py` | 本地知識庫搜尋、提問分類 |
| `llm.py` | 呼叫 AI 模型（本地 Ollama、Gemini、看圖） |
| `web_research.py` | 上網查資料、找延伸教學連結 |
| `feedback.py` | 👍/👎 回饋紀錄、審核訊息對照表 |
| `homework_check.py` | 作業健檢：叫 Blender 檢查 .blend、整理成報告 |
| `blend_check/` | 在 Blender 裡面跑的檢查腳本 |
| `knowledge/` | 課程知識庫（.md 筆記，改了自動重新讀取）；`網路整理/` 是 AI 從網路整理的筆記 |
| `persona/` | 回答語氣設定（改了下一題就生效） |
| `questions_log.csv` | 學生提問紀錄（含分類） |
| `feedback_log.csv` | 學生按 👍/👎 的紀錄 |
| `knowledge_待審核/` | 網路整理、等老師審核的筆記（有設審核頻道才會用到） |
| `knowledge_已退回/` | 老師按 ❌ 的筆記（不會被讀進知識庫，留著備查） |
| `answer_index.json` / `review_index.json` | 記住哪則訊息是哪題／哪篇筆記（重開機器人也能按反應） |
| `image_notes.json` | 截圖的看圖描述（追問時用，有人傳截圖後才會出現） |
| `.env` / `.env.example` | 設定檔／設定範本（`.env` 有金鑰，不要上傳） |
| `requirements.txt` | 需要的 Python 套件 |
| `tests/` | 測試工具，不用開 Discord 就能試 |
| `backup/` | 舊版程式備份 |
| `docs/` | 課程大綱等參考文件 |

## 測試（在這個資料夾執行）
```
python tests/test_persona.py            測語氣（本地模型＋Gemini）
python tests/test_persona.py --local    只測本地模型
python tests/test_vision.py tests/IMG_7920.png      測看截圖
python tests/test_vision.py --links 布林運算 Boolean  測延伸教學連結
python knowledge.py 你的問題             看這題會查到哪些資料、分到哪一類
python homework_check.py 作業.blend      測作業健檢（會在目前資料夾產生 健檢預覽.png）
```

## 新功能（v13）
**👍/👎 回饋**：每則回答下面會有 👍 👎。學生按了會記到 `feedback_log.csv`；
提問的同學按 👎 時，機器人會請他補充，同時通知審核頻道。

**老師審核頻道**：在 `.env` 填 `REVIEW_CHANNEL_ID` 後，AI 從網路整理的筆記會先存在 `knowledge_待審核/`，
並貼到審核頻道（附 .md 檔）：
- 按 ✅ → 搬進 `knowledge/網路整理/`，下一題就查得到
- 按 ❌ → 搬到 `knowledge_已退回/`
- **回覆**那則訊息打字 → 加到筆記最後的「老師補充」；回覆並上傳改好的 .md → 整份取代
- 機器人啟動時，待審核資料夾裡還沒貼過的筆記會自動補貼

**作業健檢**：學生在提問頻道（或討論串）丟 `.blend`，機器人在背景開 Blender 檢查後回報告＋預覽圖。
檢查項目：貼圖沒打包（會變粉紅）、法線反了、負縮放、縮放沒套用、重疊的點、布林刀具沒隱藏、
細分太高、非流形邊、散點、零面積面、沒材質、沒攝影機/燈光、面數太多。
- 用 `--disable-autoexec` 開檔，學生檔案裡的腳本不會被執行；檔案在暫存資料夾檢查完就刪
- 一次只檢查一個檔案，其他人排隊
- Discord 免費伺服器上傳上限 10MB，大檔案學生可能傳不上來

**機器人權限**：要多開「新增反應」「附加檔案」「讀取訊息歷史」，審核頻道也要讓機器人看得到。
