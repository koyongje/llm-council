"""In-memory record of each engine's last call outcome, so the UI can show
which models ran out of credits or hit a usage limit. Resets on restart."""

from datetime import datetime, timezone
from typing import Dict, Any, Optional

MESSAGE_LIMIT = 200

# Billing exhausted: needs a top-up (OpenAI, Anthropic, Gemini prepay wording)
CREDIT_MARKERS = (
    "insufficient_quota",
    "no credits remaining",
    "exceeded your current quota",
    "credit balance is too low",
    "prepayment credits are depleted",
)
# Rate or quota limit: usually clears after a while
RATE_LIMIT_MARKERS = ("http 429", "rate limit", "resource_exhausted")

_status: Dict[str, Dict[str, Any]] = {}


def classify(error_text: str) -> str:
    text = error_text.lower()
    if any(m in text for m in CREDIT_MARKERS):
        return "credit"
    if any(m in text for m in RATE_LIMIT_MARKERS):
        return "rate_limit"
    return "error"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_success(model: str) -> None:
    _status[model] = {"status": "ok", "message": None, "at": _now()}


def record_failure(model: str, error_text: str) -> None:
    _status[model] = {
        "status": classify(error_text),
        "message": error_text[:MESSAGE_LIMIT],
        "at": _now(),
    }


def get(model: str) -> Dict[str, Optional[str]]:
    return _status.get(model, {"status": "unknown", "message": None, "at": None})


def reset() -> None:
    _status.clear()
