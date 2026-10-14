"""
AI 模型呼叫：本地模型（Ollama）與 Gemini API

messages 格式：[{"role": "user" 或 "assistant", "content": "..."}]
"""
import json
import os

import httpx
from google import genai
from google.genai import types

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "qwen2.5:3b")
LOCAL_CTX = int(os.getenv("LOCAL_CTX", "4096"))          # 4GB 顯卡建議 4096
GEMINI_MODEL = os.getenv("MODEL", "gemini-3.8-flash")

_gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# 本地模型（例如 Qwen）有時會冒出簡體字，有裝 opencc 就自動轉成台灣繁體
try:
    from opencc import OpenCC
    _s2tw = OpenCC("s2twp").convert
except Exception:
    _s2tw = None


def to_traditional(text):
    return _s2tw(text) if _s2tw else text


async def local_chat(system_prompt, messages, timeout=180):
    """呼叫筆電上的 Ollama。失敗會丟出例外，由呼叫端決定要不要改用 Gemini"""
    payload = {
        "model": LOCAL_MODEL,
        "messages": [{"role": "system", "content": system_prompt}] + messages[-6:],
        "stream": False,
        "options": {"num_ctx": LOCAL_CTX, "temperature": 0.3},
    }
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
        text = r.json()["message"]["content"].strip()
    if not text:
        raise RuntimeError("本地模型沒有回傳內容")
    return to_traditional(text)


async def local_available():
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            names = [m["name"] for m in r.json().get("models", [])]
            return LOCAL_MODEL in names or f"{LOCAL_MODEL}:latest" in names, names
    except Exception:
        return False, []


def _contents(messages):
    return [types.Content(role="model" if m["role"] == "assistant" else "user",
                          parts=[types.Part(text=m["content"])]) for m in messages]


async def gemini_chat(system_prompt, messages):
    resp = await _gemini.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=_contents(messages),
        config=types.GenerateContentConfig(system_instruction=system_prompt),
    )
    return resp.text or "（沒有產生回答，請換個方式再問一次）"


async def gemini_json(system_prompt, messages):
    """要求 Gemini 回傳 JSON，解析失敗時回傳 None"""
    resp = await _gemini.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=_contents(messages),
        config=types.GenerateContentConfig(system_instruction=system_prompt,
                                           response_mime_type="application/json"),
    )
    text = (resp.text or "").strip()
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
