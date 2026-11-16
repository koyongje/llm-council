"""List the chat models each provider offers (free list endpoints), for the
council settings UI. A provider that fails reports an error and no models."""

import asyncio
import re
from typing import Any, Dict, List, Optional

import httpx

from .config import ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY

TIMEOUT = 20.0

# OpenAI lists every model kind; keep chat models only
OPENAI_CHAT = re.compile(r"^(gpt-|o\d|chatgpt-)")
OPENAI_EXCLUDE = ("audio", "realtime", "tts", "transcribe", "image", "embedding", "moderation", "search", "live")
GEMINI_EXCLUDE = ("embedding", "tts", "image", "transcribe", "computer-use", "robotics", "nano-banana")


async def _get(url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(url, headers=headers, params=params)
        if response.is_error:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
        return response.json()


def _key(key: Optional[str], env_name: str) -> str:
    if not key:
        raise RuntimeError(f"{env_name} is not set in .env")
    return key


async def _openai() -> List[str]:
    data = await _get("https://api.openai.com/v1/models",
                      {"Authorization": f"Bearer {_key(OPENAI_API_KEY, 'OPENAI_API_KEY')}"})
    return [m["id"] for m in data.get("data", [])
            if OPENAI_CHAT.match(m["id"]) and not any(x in m["id"] for x in OPENAI_EXCLUDE)]


async def _anthropic() -> List[str]:
    data = await _get("https://api.anthropic.com/v1/models",
                      {"x-api-key": _key(ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"},
                      {"limit": 1000})
    return [m["id"] for m in data.get("data", [])]


async def _google() -> List[str]:
    data = await _get("https://generativelanguage.googleapis.com/v1beta/models",
                      {"x-goog-api-key": _key(GEMINI_API_KEY, "GEMINI_API_KEY")},
                      {"pageSize": 1000})
    names = []
    for m in data.get("models", []):
        name = m.get("name", "").removeprefix("models/")
        if ("generateContent" in m.get("supportedGenerationMethods", [])
                and "gemini" in name and not any(x in name for x in GEMINI_EXCLUDE)):
            names.append(name)
    return names


FETCHERS = {"openai": _openai, "anthropic": _anthropic, "google": _google}


async def _one(provider: str) -> Dict[str, Any]:
    try:
        ids = await FETCHERS[provider]()
        return {"models": sorted(f"{provider}/{i}" for i in ids), "error": None}
    except Exception as e:
        return {"models": [], "error": str(e) or type(e).__name__}


async def list_models() -> Dict[str, Dict[str, Any]]:
    results = await asyncio.gather(*(_one(p) for p in FETCHERS))
    return dict(zip(FETCHERS, results))
