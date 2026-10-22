"""Citation helpers: source lists and flagging of unverified URLs."""

import re
from typing import Dict, List, Set

Source = Dict[str, str]

MARKER = " ⚠️ 미검증"

_ASCII_URL_CHARS = r"A-Za-z0-9\-._~:/?#@!$&'*+,;=%"
_TRAILING_PUNCT = "*>.,;:!?"

_URL_PATTERN = re.compile(
    r"\[[^\]]*\]\((https?://(?:[^()\s]|\([^()\s]*\))+)\)"
    rf"|https?://(?:[{_ASCII_URL_CHARS}]|\([{_ASCII_URL_CHARS}]*\))+"
)


def format_sources(sources: List[Source]) -> str:
    """Format a markdown source list, deduplicated by URL."""
    if not sources:
        return "\n\n출처: 웹 검색 출처 없음"
    lines = []
    seen = set()
    for source in sources:
        url = source["url"]
        if url in seen:
            continue
        seen.add(url)
        title = source.get("title") or url
        lines.append(f"- [{title}]({url})")
    return "\n\n출처:\n" + "\n".join(lines)


def normalize_url(url: str) -> str:
    """Lowercase scheme/host and strip trailing slash and punctuation."""
    url = url.rstrip(".,;:!?*)").rstrip("/")
    match = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*://)([^/?#]*)(.*)$", url)
    if match:
        scheme, host, rest = match.groups()
        url = scheme.lower() + host.lower() + rest
    return url.rstrip("/")


def collect_verified_urls(prior_messages: List[Dict], stage1_results: List[Dict]) -> Set[str]:
    """Collect normalized source URLs from prior assistant messages and current stage 1."""
    verified: Set[str] = set()

    def add(results: List[Dict]) -> None:
        for result in results:
            for source in result.get("sources") or []:
                verified.add(normalize_url(source["url"]))

    for message in prior_messages:
        if message.get("role") == "assistant":
            add(message.get("stage1") or [])
    add(stage1_results)
    return verified


def mark_unverified(text: str, verified: Set[str]) -> str:
    """Append a warning marker after every URL not in the verified set."""

    def replace(match: re.Match) -> str:
        whole = match.group(0)
        if match.group(1) is not None:
            url, core, tail = match.group(1), whole, ""
        else:
            core = whole.rstrip(_TRAILING_PUNCT)
            url, tail = core, whole[len(core):]
        if normalize_url(url) in verified:
            return whole
        if match.string.startswith(MARKER.strip(), match.start() + len(core) + 1):
            return whole
        return core + MARKER + tail

    return _URL_PATTERN.sub(replace, text)
