"""
回饋與審核用的小工具：記住「哪則訊息是什麼」，重開機器人也不會忘

- answer_index.json：機器人的回答訊息 → 這題的提問、分類、學生（學生按 👍/👎 時查）
- review_index.json：審核頻道的訊息 → 待審核筆記的檔案路徑（老師按 ✅/❌ 時查）
- feedback_log.csv：學生的 👍/👎 紀錄（可以用 Excel 開）
"""
import csv
import datetime
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
FEEDBACK_LOG = os.path.join(BASE, "feedback_log.csv")
FEEDBACK_HEADER = ["時間", "按的人", "動作", "回饋", "是不是提問者", "提問", "分類", "回答來源", "討論串ID", "回答訊息ID"]


class JsonIndex:
    """{訊息ID: 資料} 存成 JSON 檔；超過 limit 筆就刪掉最舊的"""

    def __init__(self, filename, limit=3000):
        self.path = os.path.join(BASE, filename)
        self.limit = limit
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def get(self, msg_id):
        return self.data.get(str(msg_id))

    def set(self, msg_id, value):
        self.data[str(msg_id)] = value
        if len(self.data) > self.limit:
            for k in list(self.data)[:-self.limit]:
                del self.data[k]
        self.save()

    def items(self):
        return self.data.items()

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError as e:
            print(f"[紀錄] {os.path.basename(self.path)} 存檔失敗：{e}")


def log_feedback(user, action, emoji, is_asker, info, thread_id, msg_id):
    new_file = not os.path.exists(FEEDBACK_LOG)
    try:
        with open(FEEDBACK_LOG, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(FEEDBACK_HEADER)
            w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), user, action, emoji,
                        "是" if is_asker else "否", info.get("question", ""), info.get("category", ""),
                        info.get("source", ""), thread_id, msg_id])
    except PermissionError:
        print("⚠️ feedback_log.csv 被其他程式開著（Excel？），這筆回饋沒記到")
