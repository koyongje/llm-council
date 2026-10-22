"""Verify API keys and model ids by sending a short prompt to every configured model.

Run from the project root: uv run python -m backend.check_models
"""

import asyncio
from .config import COUNCIL_MODELS, CHAIRMAN_MODEL, TITLE_MODEL
from .providers import query_models_parallel


async def main():
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


if __name__ == "__main__":
    asyncio.run(main())
