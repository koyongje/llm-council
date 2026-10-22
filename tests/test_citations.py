from backend.citations import format_sources, normalize_url, collect_verified_urls, mark_unverified

def test_format_sources_lists_unique_links():
    out = format_sources([{"url": "https://a.com/x", "title": "A"}, {"url": "https://a.com/x", "title": "A"}, {"url": "https://b.com", "title": ""}])
    assert out == "\n\n출처:\n- [A](https://a.com/x)\n- [https://b.com](https://b.com)"

def test_format_sources_empty():
    assert format_sources([]) == "\n\n출처: 웹 검색 출처 없음"

def test_normalize_url():
    assert normalize_url("HTTPS://Example.com/path/") == "https://example.com/path"
    assert normalize_url("https://example.com/a).") == "https://example.com/a"

def test_collect_verified_urls_merges_prior_and_current():
    prior = [{"role": "user", "content": "q"},
             {"role": "assistant", "stage1": [{"model": "m", "response": "r", "sources": [{"url": "https://old.com/", "title": ""}]}]},
             {"role": "assistant", "stage1": [{"model": "m", "response": "r"}]}]
    current = [{"model": "m", "response": "r", "sources": [{"url": "https://new.com", "title": ""}]}]
    assert collect_verified_urls(prior, current) == {"https://old.com", "https://new.com"}

def test_mark_unverified_flags_only_unknown_links():
    text = "See [ok](https://ok.com/) and [bad](https://bad.com) and https://ok.com and https://fake.org/x."
    out = mark_unverified(text, {"https://ok.com"})
    assert out == "See [ok](https://ok.com/) and [bad](https://bad.com) ⚠️ 미검증 and https://ok.com and https://fake.org/x ⚠️ 미검증."

def test_mark_unverified_is_idempotent():
    once = mark_unverified("[bad](https://bad.com)", set())
    assert mark_unverified(once, set()) == once

WIKI = "https://en.wikipedia.org/wiki/Foo_(bar)"

def test_mark_unverified_keeps_parenthesised_link_intact():
    out = mark_unverified(f"[w]({WIKI}) end", set())
    assert out == f"[w]({WIKI}) ⚠️ 미검증 end"
    assert mark_unverified(out, set()) == out

def test_mark_unverified_verified_parenthesised_link_unchanged():
    text = f"[w]({WIKI}) end"
    assert mark_unverified(text, {normalize_url(WIKI)}) == text

import pytest

K = "https://kosis.kr/stat"
VERIFIED = {normalize_url(K)}
M = " ⚠️ 미검증"

@pytest.mark.parametrize("template", [
    "{u}에서 확인", "**{u}**", "<{u}>", "| {u}|", "{u}。", "{u}:", "{u}!", "{u}?", "({u})",
])
def test_verified_bare_url_in_context_not_marked(template):
    text = template.format(u=K)
    assert mark_unverified(text, VERIFIED) == text

@pytest.mark.parametrize("template,expected", [
    ("{u}에서 확인", "{u}" + M + "에서 확인"),
    ("**{u}**", "**{u}" + M + "**"),
    ("<{u}>", "<{u}" + M + ">"),
    ("| {u}|", "| {u}" + M + "|"),
    ("{u}。", "{u}" + M + "。"),
    ("{u}:", "{u}" + M + ":"),
    ("{u}!", "{u}" + M + "!"),
])
def test_unverified_bare_url_marker_placed_right_after_url(template, expected):
    u = "https://fake.org/x"
    out = mark_unverified(template.format(u=u), set())
    assert out == expected.format(u=u)
    assert mark_unverified(out, set()) == out

def test_bare_url_with_balanced_parens_kept_whole():
    out = mark_unverified(f"see {WIKI} end", set())
    assert out == f"see {WIKI}{M} end"
