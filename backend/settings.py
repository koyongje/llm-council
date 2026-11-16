"""Council membership chosen in the UI, stored in data/settings.json.

Read at call time, so a change applies from the next question without a
restart. Falls back to config.py when nothing valid is saved."""

import json
import logging
import os
from typing import List, Tuple

from .config import COUNCIL_MODELS, CHAIRMAN_MODEL, SETTINGS_PATH
from .storage import _write_json

logger = logging.getLogger(__name__)

PROVIDERS = ("anthropic", "openai", "google")
MIN_MEMBERS = 2  # peer review needs at least two responses
MAX_MEMBERS = 6  # cost and latency grow with every member


def _check_model(model: str) -> None:
    provider, _, model_id = (model or "").partition("/")
    if provider not in PROVIDERS or not model_id.strip():
        raise ValueError(f"'{model}' is not a valid model (expected provider/model-id, provider one of {', '.join(PROVIDERS)})")


def validate(council_models: List[str], chairman_model: str) -> None:
    if not MIN_MEMBERS <= len(council_models) <= MAX_MEMBERS:
        raise ValueError(f"The council needs {MIN_MEMBERS}-{MAX_MEMBERS} members, got {len(council_models)}")
    if len(set(council_models)) != len(council_models):
        raise ValueError("The council lists the same model more than once")
    for model in [*council_models, chairman_model]:
        _check_model(model)


def get_council() -> Tuple[List[str], str]:
    """(council_models, chairman_model) from the saved file, else config.py."""
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        validate(data["council_models"], data["chairman_model"])
        return list(data["council_models"]), data["chairman_model"]
    except FileNotFoundError:
        pass
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.warning("Ignoring unreadable %s, using config.py defaults: %s", SETTINGS_PATH, e)
    return list(COUNCIL_MODELS), CHAIRMAN_MODEL


def set_council(council_models: List[str], chairman_model: str) -> None:
    validate(council_models, chairman_model)
    os.makedirs(os.path.dirname(SETTINGS_PATH) or ".", exist_ok=True)
    _write_json(SETTINGS_PATH, {"council_models": list(council_models), "chairman_model": chairman_model})
