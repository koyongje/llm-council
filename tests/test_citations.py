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
