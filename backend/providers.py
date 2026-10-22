"""Direct provider API clients (Anthropic, OpenAI, Google Gemini) for making LLM requests."""

import asyncio
import httpx
from typing import List, Dict, Any, Optional
from .config import (
    ANTHROPIC_API_KEY,
    OPENAI_API_KEY,
    GEMINI_API_KEY,
    ANTHROPIC_MAX_TOKENS,
)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


async def _post(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.is_error:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
        return response.json()


def _require_key(key: Optional[str], env_name: str) -> str:
    if not key:
        raise RuntimeError(f"{env_name} is not set in .env")
    return key


async def _query_anthropic(model: str, messages: List[Dict[str, str]], timeout: float) -> Dict[str, Any]:
    headers = {
        "x-api-key": _require_key(ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY"),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": ANTHROPIC_MAX_TOKENS,
        "messages": messages,
    }
    data = await _post(ANTHROPIC_API_URL, headers, payload, timeout)
    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    return {"content": text, "reasoning_details": None}


async def _query_openai(model: str, messages: List[Dict[str, str]], timeout: float) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {_require_key(OPENAI_API_KEY, 'OPENAI_API_KEY')}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
    }
    data = await _post(OPENAI_API_URL, headers, payload, timeout)
    message = data["choices"][0]["message"]
    return {"content": message.get("content"), "reasoning_details": None}


async def _query_gemini(model: str, messages: List[Dict[str, str]], timeout: float) -> Dict[str, Any]:
    headers = {
        "x-goog-api-key": _require_key(GEMINI_API_KEY, "GEMINI_API_KEY"),
        "Content-Type": "application/json",
    }
    # Gemini uses "model" instead of "assistant" and wraps text in parts
    payload = {
        "contents": [
            {
                "role": "model" if m["role"] == "assistant" else "user",
                "parts": [{"text": m["content"]}],
            }
            for m in messages
        ],
    }
    data = await _post(GEMINI_API_URL.format(model=model), headers, payload, timeout)
    parts = data["candidates"][0].get("content", {}).get("parts", [])
    # Skip thought summaries; keep only the answer text
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return {"content": text, "reasoning_details": None}


PROVIDERS = {
    "anthropic": _query_anthropic,
    "openai": _query_openai,
    "google": _query_gemini,
}


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 300.0
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via its provider's API.

    Args:
        model: "provider/model-id" identifier (e.g., "openai/gpt-5.1")
        messages: List of message dicts with 'role' and 'content'
        timeout: Request timeout in seconds

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed
    """
    try:
        provider, model_id = model.split("/", 1)
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}' (expected one of {list(PROVIDERS)})")
        return await PROVIDERS[provider](model_id, messages, timeout)

    except Exception as e:
        print(f"Error querying model {model}: {type(e).__name__}: {e}")
        return None


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]]
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of "provider/model-id" identifiers
        messages: List of message dicts to send to each model

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    # Create tasks for all models
    tasks = [query_model(model, messages) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}
