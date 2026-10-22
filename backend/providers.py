"""Direct provider API clients (Anthropic, OpenAI, Google Gemini) for making LLM requests."""

import asyncio
import base64
import httpx
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from .config import (
    ANTHROPIC_API_KEY,
    OPENAI_API_KEY,
    GEMINI_API_KEY,
    ANTHROPIC_MAX_TOKENS,
)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
OPENAI_API_URL = "https://api.openai.com/v1/responses"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

MAX_PAUSE_CONTINUATIONS = 3

# Mirrors backend.citations.Source
Source = Dict[str, str]


@dataclass
class PdfFile:
    filename: str
    data: bytes


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


def _b64(pdf: PdfFile) -> str:
    return base64.standard_b64encode(pdf.data).decode()


async def _query_anthropic(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float,
    files: Optional[List[PdfFile]] = None,
    web_search: bool = False,
) -> Dict[str, Any]:
    headers = {
        "x-api-key": _require_key(ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY"),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    msgs: List[Dict[str, Any]] = [dict(m) for m in messages]
    if files:
        blocks = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": _b64(f)}}
            for f in files
        ]
        msgs[-1] = {"role": msgs[-1]["role"], "content": blocks + [{"type": "text", "text": msgs[-1]["content"]}]}

    payload: Dict[str, Any] = {
        "model": model,
        "max_tokens": ANTHROPIC_MAX_TOKENS,
        "messages": msgs,
    }
    if web_search:
        payload["tools"] = [{"type": "web_search_20260209", "name": "web_search"}]

    text = ""
    sources: List[Source] = []
    for _ in range(MAX_PAUSE_CONTINUATIONS + 1):
        data = await _post(ANTHROPIC_API_URL, headers, payload, timeout)
        content = data.get("content", [])
        for block in content:
            if block.get("type") == "text":
                text += block.get("text", "")
            elif block.get("type") == "web_search_tool_result":
                results = block.get("content")
                # On failure `content` is an error object (dict), not a list
                if isinstance(results, list):
                    sources.extend(
                        {"url": r["url"], "title": r.get("title", "")}
                        for r in results
                        if r.get("type") == "web_search_result" and r.get("url")
                    )
        if data.get("stop_reason") != "pause_turn":
            break
        payload["messages"] = payload["messages"] + [{"role": "assistant", "content": content}]
    return {"content": text, "reasoning_details": None, "sources": sources}


async def _query_openai(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float,
    files: Optional[List[PdfFile]] = None,
    web_search: bool = False,
) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {_require_key(OPENAI_API_KEY, 'OPENAI_API_KEY')}",
        "Content-Type": "application/json",
    }
    items: List[Dict[str, Any]] = [{"role": m["role"], "content": m["content"]} for m in messages]
    if files:
        parts = [
            {"type": "input_file", "filename": f.filename, "file_data": "data:application/pdf;base64," + _b64(f)}
            for f in files
        ]
        items[-1] = {
            "role": items[-1]["role"],
            "content": parts + [{"type": "input_text", "text": items[-1]["content"]}],
        }
    payload: Dict[str, Any] = {"model": model, "input": items}
    if web_search:
        payload["tools"] = [{"type": "web_search"}]
        # The model otherwise often skips optional search and returns no sources.
        payload["tool_choice"] = "required"

    data = await _post(OPENAI_API_URL, headers, payload, timeout)
    text = ""
    sources: List[Source] = []
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if part.get("type") != "output_text":
                continue
            text += part.get("text", "")
            for ann in part.get("annotations", []):
                if ann.get("type") == "url_citation" and ann.get("url"):
                    sources.append({"url": ann["url"], "title": ann.get("title", "")})
    return {"content": text, "reasoning_details": None, "sources": sources}


async def _query_gemini(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float,
    files: Optional[List[PdfFile]] = None,
    web_search: bool = False,
) -> Dict[str, Any]:
    headers = {
        "x-goog-api-key": _require_key(GEMINI_API_KEY, "GEMINI_API_KEY"),
        "Content-Type": "application/json",
    }
    # Gemini uses "model" instead of "assistant" and wraps text in parts
    contents = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
    ]
    if files:
        pdf_parts = [{"inline_data": {"mime_type": "application/pdf", "data": _b64(f)}} for f in files]
        contents[-1]["parts"] = pdf_parts + contents[-1]["parts"]
    payload: Dict[str, Any] = {"contents": contents}
    if web_search:
        payload["tools"] = [{"google_search": {}}]

    data = await _post(GEMINI_API_URL.format(model=model), headers, payload, timeout)
    candidate = data["candidates"][0]
    parts = candidate.get("content", {}).get("parts", [])
    # Skip thought summaries; keep only the answer text
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    sources: List[Source] = []
    for chunk in candidate.get("groundingMetadata", {}).get("groundingChunks", []):
        web = chunk.get("web")
        if web and web.get("uri"):
            sources.append({"url": web["uri"], "title": web.get("title", "")})
    return {"content": text, "reasoning_details": None, "sources": sources}


PROVIDERS = {
    "anthropic": _query_anthropic,
    "openai": _query_openai,
    "google": _query_gemini,
}


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 300.0,
    files: Optional[List[PdfFile]] = None,
    web_search: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via its provider's API.

    Args:
        model: "provider/model-id" identifier (e.g., "openai/gpt-5.1")
        messages: List of message dicts with 'role' and 'content'
        timeout: Request timeout in seconds

    Returns:
        Response dict with 'content', 'reasoning_details' and 'sources', or None if failed
    """
    try:
        provider, model_id = model.split("/", 1)
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}' (expected one of {list(PROVIDERS)})")
        return await PROVIDERS[provider](model_id, messages, timeout, files, web_search)

    except Exception as e:
        print(f"Error querying model {model}: {type(e).__name__}: {e}")
        return None


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]],
    files: Optional[List[PdfFile]] = None,
    web_search: bool = False,
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
    tasks = [query_model(model, messages, files=files, web_search=web_search) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}
