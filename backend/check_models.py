"""Verify API keys and model ids by sending a short prompt to every configured model.

Run from the project root:
  uv run python -m backend.check_models          # plain connectivity check
  uv run python -m backend.check_models --full   # PDF + web search check
"""

import asyncio
import sys
from pathlib import Path
from .config import COUNCIL_MODELS, CHAIRMAN_MODEL, TITLE_MODEL
from .providers import PdfFile, query_models_parallel

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample.pdf"
FULL_PROMPT = (
    "What market size figure does the attached PDF state? "
    "Then find the latest published figure for the Korean e-commerce market via web search."
)


async def run_plain():
    models = list(dict.fromkeys(COUNCIL_MODELS + [CHAIRMAN_MODEL, TITLE_MODEL]))
    messages = [{"role": "user", "content": "Reply with the single word: OK"}]
    responses = await query_models_parallel(models, messages)

    failed = 0
    for model, response in responses.items():
        if response is None:
            failed += 1
            print(f"FAIL  {model}")
        else:
            print(f"OK    {model}: {(response.get('content') or '').strip()[:40]!r}")

    if failed:
        raise SystemExit(f"{failed} model(s) failed - see errors above")


async def run_full():
    pdf = PdfFile(filename=FIXTURE.name, data=FIXTURE.read_bytes())
    messages = [{"role": "user", "content": FULL_PROMPT}]
    responses = await query_models_parallel(
        COUNCIL_MODELS, messages, files=[pdf], web_search=True
    )

    bad = 0
    for model, response in responses.items():
        if response is None:
            bad += 1
            print(f"FAIL  {model}")
            continue
        sources = response.get("sources") or []
        if not sources:
            bad += 1
            print(f"FAIL  {model} (0 sources)")
        else:
            print(f"OK    {model} ({len(sources)} sources)")
        print(f"      {(response.get('content') or '').strip()[:200]!r}")

    if bad:
        raise SystemExit(f"{bad} model(s) failed - see errors above")


if __name__ == "__main__":
    asyncio.run(run_full() if "--full" in sys.argv[1:] else run_plain())
