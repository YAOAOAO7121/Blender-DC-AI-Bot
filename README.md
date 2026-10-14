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
| `knowledge/` | 課程知識庫（.md 筆記，改了自動重新讀取）；`網路整理/` 是 AI 從網路整理的筆記 |
| `persona/` | 回答語氣設定（改了下一題就生效） |
| `questions_log.csv` | 學生提問紀錄（含分類） |
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
```
