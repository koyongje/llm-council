from backend.providers import PdfFile, query_model

PDF = PdfFile("plan.pdf", b"%PDF-1.4 x")


async def test_anthropic_sends_pdf_and_web_search_and_extracts_sources(fake_post):
    fake_post.reply = {"stop_reason": "end_turn", "content": [
        {"type": "server_tool_use"},
        {"type": "web_search_tool_result", "content": [{"type": "web_search_result", "url": "https://a.com", "title": "A"}]},
        {"type": "text", "text": "answer"}]}
    r = await query_model("anthropic/claude-opus-5-5", [{"role": "user", "content": "q"}], files=[PDF], web_search=True)
    body = fake_post.calls[0][1]
    assert body["messages"][-1]["content"][0]["type"] == "document"
    assert body["tools"] == [{"type": "web_search_20260209", "name": "web_search"}]
    assert r == {"content": "answer", "reasoning_details": None, "sources": [{"url": "https://a.com", "title": "A"}]}


async def test_anthropic_tolerates_search_error_object(fake_post):
    fake_post.reply = {"stop_reason": "end_turn", "content": [
        {"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}},
        {"type": "text", "text": "answer"}]}
    r = await query_model("anthropic/claude-opus-5-5", [{"role": "user", "content": "q"}], web_search=True)
    assert r["sources"] == []


async def test_anthropic_resumes_pause_turn(fake_post):
    fake_post.replies = [{"stop_reason": "pause_turn", "content": [{"type": "text", "text": "part1 "}]},
                         {"stop_reason": "end_turn", "content": [{"type": "text", "text": "part2"}]}]
    r = await query_model("anthropic/claude-opus-5-5", [{"role": "user", "content": "q"}], web_search=True)
    assert r["content"] == "part1 part2"
    assert fake_post.calls[1][1]["messages"][-1]["role"] == "assistant"


async def test_openai_uses_responses_api(fake_post):
    fake_post.reply = {"output": [{"type": "web_search_call"}, {"type": "message", "content": [
        {"type": "output_text", "text": "answer", "annotations": [{"type": "url_citation", "url": "https://b.com", "title": "B"}]}]}]}
    r = await query_model("openai/gpt-5.1", [{"role": "user", "content": "old"}, {"role": "assistant", "content": "prev"}, {"role": "user", "content": "q"}], files=[PDF], web_search=True)
    url, body = fake_post.calls[0]
    assert url == "https://api.openai.com/v1/responses"
    assert body["input"][-1]["content"][0]["type"] == "input_file"
    assert body["input"][0] == {"role": "user", "content": "old"}
    assert body["tools"] == [{"type": "web_search"}]
    assert r["sources"] == [{"url": "https://b.com", "title": "B"}]


async def test_gemini_sends_inline_pdf_and_grounding(fake_post):
    fake_post.reply = {"candidates": [{"content": {"parts": [{"text": "answer"}]},
        "groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://c.com", "title": "C"}}]}}]}
    r = await query_model("google/gemini-3.1-pro-preview", [{"role": "user", "content": "q"}], files=[PDF], web_search=True)
    body = fake_post.calls[0][1]
    assert body["contents"][-1]["parts"][0]["inline_data"]["mime_type"] == "application/pdf"
    assert body["tools"] == [{"google_search": {}}]
    assert r["sources"] == [{"url": "https://c.com", "title": "C"}]


async def test_no_tools_when_web_search_off(fake_post):
    fake_post.reply = {"candidates": [{"content": {"parts": [{"text": "t"}]}}]}
    await query_model("google/gemini-3.8-flash", [{"role": "user", "content": "q"}])
    assert "tools" not in fake_post.calls[0][1]


async def test_gemini_without_candidates_returns_none(fake_post):
    fake_post.reply = {"promptFeedback": {"blockReason": "SAFETY"}}
    assert await query_model("google/gemini-3.1-pro-preview", [{"role": "user", "content": "q"}]) is None
