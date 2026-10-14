"""
AI 模型呼叫：本地模型（Ollama）與 Gemini API

messages 格式：[{"role": "user" 或 "assistant", "content": "..."}]
"""
import asyncio
import json
import os
import re

import httpx
from google import genai
from google.genai import types

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "qwen2.5:3b")
THINKING_MODEL = any(k in LOCAL_MODEL.lower() for k in ("qwen3", "deepseek-r1", "magistral"))
LOCAL_CTX = int(os.getenv("LOCAL_CTX", "4096"))          # 4GB 顯卡建議 4096
GEMINI_MODEL = os.getenv("MODEL", "gemini-3.8-flash")
GEMINI_RETRIES = int(os.getenv("GEMINI_RETRIES", "3"))   # Gemini 忙線（503/429）時最多試幾次
GEMINI_FALLBACK = os.getenv("GEMINI_FALLBACK_MODEL", "").strip()  # 選填：主模型一直忙線時，最後改用這個模型試一次

_gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# 本地模型（例如 Qwen）有時會冒出簡體字，有裝 opencc 就自動轉成台灣繁體
try:
    from opencc import OpenCC
    _s2tw = OpenCC("s2twp").convert
except Exception:
    _s2tw = None


def to_traditional(text):
    return _s2tw(text) if _s2tw else text


async def _ollama(system_prompt, messages, temperature, num_predict, timeout):
    payload = {
        "model": LOCAL_MODEL,
        "messages": [{"role": "system", "content": system_prompt}] + messages[-6:],
        "stream": False,
        "options": {"num_ctx": LOCAL_CTX, "temperature": temperature, "num_predict": num_predict},
    }
    if THINKING_MODEL:
        payload["think"] = False     # qwen3 這類模型預設會先「思考」很久，教學回答不需要
        # 舊版 Ollama 不認得 think 參數 → 再用 qwen3 的開關「/no_think」保險一次
        msgs = payload["messages"]
        if msgs and msgs[-1]["role"] == "user" and "/no_think" not in msgs[-1]["content"]:
            msgs[-1] = {**msgs[-1], "content": msgs[-1]["content"] + " /no_think"}
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
        text = r.json()["message"]["content"]
        return strip_thinking(text)


def strip_thinking(text):
    """去掉模型的思考過程。只會思考的模型（例如 qwen3 thinking 版）關不掉思考，
    輸出會是「思考內容…</think>答案」，甚至沒有開頭的 <think>"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    elif "<think>" in text:            # 想到一半就被截斷，沒有答案
        text = ""
    return text.strip()


def looks_like_thinking(text):
    """沒有標籤、但內容明顯是在自言自語推理（「首先，學生的問題是…」「我需要根據…」）"""
    head = text[:200]
    return bool(re.search(r"^(首先|好的?，|嗯|Okay|Let me|我需要|用户|用戶)", text.strip())) and \
        any(k in head for k in ("學生的問題", "学生的问题", "我需要", "用户", "the user"))


async def local_chat(system_prompt, messages, timeout=180):
    """呼叫筆電上的 Ollama。失敗會丟出例外，由呼叫端決定要不要改用 Gemini
    溫度調低（0.1）讓小模型少自由發揮、多照資料講"""
    text = await _ollama(system_prompt, messages, 0.1, 700, timeout)
    if not text:
        raise RuntimeError("本地模型沒有回傳內容")
    if looks_like_thinking(text):
        # 這個模型會把思考過程直接當答案吐出來 → 丟掉，讓呼叫端改用 Gemini
        raise RuntimeError(f"本地模型 {LOCAL_MODEL} 輸出的是思考過程，不是答案（建議換成 instruct 版本）")
    return to_traditional(text)


async def local_keywords(question, timeout=60):
    """請本地模型把學生的問題轉成英文搜尋關鍵字（Blender 的英文資料多很多）"""
    prompt = ("把下面這個 Blender 問題轉成「英文」網路搜尋關鍵字：5 到 8 個英文單字或術語，"
              "用空白隔開，只輸出關鍵字，不要句子、不要解釋。\n\n問題：" + question)
    text = await _ollama("你只輸出英文搜尋關鍵字。", [{"role": "user", "content": prompt}], 0, 40, timeout)
    words = re.sub(r"[^A-Za-z0-9+\- ]", " ", text).split()
    return " ".join(words[:10])


JUDGE_SYSTEM = "你是資料審核員，只會回答「能」或「不能」，不做任何解釋。"


async def local_judge(question, context, timeout=60):
    """請本地模型判斷：這些課程資料能不能直接回答這個問題。回傳 True / False
    （模型回了看不懂的東西時回傳 True，交給搜尋分數決定）"""
    prompt = (f"【課程資料】\n{context}\n\n【學生的問題】\n{question}\n\n"
              "上面的課程資料，有沒有包含回答這個問題所需的具體內容？\n"
              "資料只是提到相關名詞、但沒有講到問題真正問的東西 → 回答「不能」。\n"
              "只回答「能」或「不能」。")
    text = to_traditional(await _ollama(JUDGE_SYSTEM, [{"role": "user", "content": prompt}], 0, 5, timeout))
    print(f"[本地模型判斷] 資料能否回答：{text!r}")
    return not text.startswith(("不", "否", "no", "No"))


async def local_available():
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            names = [m["name"] for m in r.json().get("models", [])]
            return LOCAL_MODEL in names or f"{LOCAL_MODEL}:latest" in names, names
    except Exception:
        return False, []


async def _gemini_generate(contents, config):
    """呼叫 Gemini；遇到忙線、額度暫滿這類暫時性錯誤會等一下再重試"""
    delay = 2
    for attempt in range(1, GEMINI_RETRIES + 1):
        try:
            return await _gemini.aio.models.generate_content(
                model=GEMINI_MODEL, contents=contents, config=config)
        except Exception as e:
            msg = str(e)
            temporary = any(k in msg for k in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED",
                                               "500", "INTERNAL", "overloaded", "high demand"))
            if temporary and attempt == GEMINI_RETRIES and GEMINI_FALLBACK:
                print(f"[Gemini] {GEMINI_MODEL} 一直忙線，改用備用模型 {GEMINI_FALLBACK}")
                return await _gemini.aio.models.generate_content(
                    model=GEMINI_FALLBACK, contents=contents, config=config)
            if not temporary or attempt == GEMINI_RETRIES:
                raise
            print(f"[Gemini] 暫時無法使用（{msg[:30]}…），{delay} 秒後重試（{attempt}/{GEMINI_RETRIES - 1}）")
            await asyncio.sleep(delay)
            delay *= 3


def _contents(messages):
    return [types.Content(role="model" if m["role"] == "assistant" else "user",
                          parts=[types.Part(text=m["content"])]) for m in messages]


async def gemini_chat(system_prompt, messages):
    resp = await _gemini_generate(
        _contents(messages),
        types.GenerateContentConfig(system_instruction=system_prompt),
    )
    return resp.text or "（沒有產生回答，請換個方式再問一次）"


async def gemini_json(system_prompt, messages):
    """要求 Gemini 回傳 JSON，解析失敗時回傳 None"""
    resp = await _gemini_generate(
        _contents(messages),
        types.GenerateContentConfig(system_instruction=system_prompt,
                                    response_mime_type="application/json"),
    )
    return _parse_json(resp.text)


async def gemini_vision_json(system_prompt, text, images):
    """讓 Gemini 看圖片（截圖）並回傳 JSON。images = [(圖片bytes, "image/png"), ...]"""
    parts = [types.Part.from_bytes(data=d, mime_type=m) for d, m in images] + [types.Part(text=text)]
    resp = await _gemini_generate(
        [types.Content(role="user", parts=parts)],
        types.GenerateContentConfig(system_instruction=system_prompt,
                                    response_mime_type="application/json"),
    )
    return _parse_json(resp.text)


def _parse_json(text):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    return None
