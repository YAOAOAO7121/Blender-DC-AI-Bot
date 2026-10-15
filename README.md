# Blender 課程 AI 教學助理（Discord 機器人）

## 啟動
```
python bot.py
```
（要先開 Ollama；設定都在 `.env`，可以調的選項看 `.env.example`）

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
