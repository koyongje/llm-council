"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import uuid
import json
import asyncio
from contextlib import aclosing

from . import storage, engine_status, settings, model_catalog
from .config import MAX_CONVERSATION_FILES_BYTES, TITLE_MODEL
from .providers import query_models_parallel
from .council import run_full_council, generate_conversation_title, stage1_collect_responses, stage2_collect_rankings, stage3_synthesize_final, calculate_aggregate_rankings, build_history, ALL_FAILED_RESPONSE
from .citations import collect_verified_urls

app = FastAPI(title="LLM Council API")

UPLOAD_CHUNK_BYTES = 1024 * 1024

# A council run can take many minutes with no events; an SSE comment line this
# often shows the connection is alive and lets the server notice a closed client
HEARTBEAT_SECONDS = 15.0

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sse(payload: Dict[str, Any]) -> str:
    """Format one Server-Sent Event; keep Korean text unescaped to shrink payloads."""
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


async def _with_heartbeat(awaitable, result: List[Any]):
    """
    Run `awaitable`, yielding an SSE keepalive comment every HEARTBEAT_SECONDS
    until it finishes, then append its return value to `result`.

    If the client disconnects (or presses "중지"), the generator is closed and
    the stage is cancelled instead of continuing to spend API calls nobody will
    read. Callers wrap it in `aclosing` so that happens immediately, not
    whenever the event loop finalizes the abandoned generator.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
            if done:
                break
            yield ": keepalive\n\n"
    finally:
        if not task.done():
            task.cancel()
    result.append(task.result())


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]
    files: List[Dict[str, Any]] = []


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


class CouncilSettings(BaseModel):
    """Council membership chosen in the UI."""
    council_models: List[str]
    chairman_model: str


class TestModelsRequest(BaseModel):
    """Models to ping before saving the council."""
    models: List[str]


def _settings_body() -> Dict[str, Any]:
    council_models, chairman_model = settings.get_council()
    return {"council_models": council_models, "chairman_model": chairman_model, "title_model": TITLE_MODEL}


@app.get("/api/settings")
async def get_settings():
    """Current council membership (saved settings, else config.py)."""
    return _settings_body()


@app.put("/api/settings")
async def put_settings(request: CouncilSettings):
    """Save the council; applies from the next question without a restart."""
    try:
        settings.set_council(request.council_models, request.chairman_model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _settings_body()


@app.get("/api/models")
async def list_models():
    """Chat models each provider offers, for the settings UI."""
    return await model_catalog.list_models()


@app.post("/api/settings/test")
async def test_models(request: TestModelsRequest):
    """Send each model a tiny prompt (a small paid call) to see if it answers."""
    models = list(dict.fromkeys(request.models))
    messages = [{"role": "user", "content": "Reply with the single word: OK"}]
    responses = await query_models_parallel(models, messages, timeout=60.0)
    results = []
    for model in models:
        if responses.get(model) is not None:
            results.append({"model": model, "ok": True, "status": "ok", "message": None})
        else:
            entry = engine_status.get(model)
            results.append({"model": model, "ok": False, "status": entry["status"], "message": entry["message"]})
    return results


@app.get("/api/engines")
async def list_engines():
    """Last call outcome of every configured engine (credit/limit exhaustion)."""
    council_models, chairman_model = settings.get_council()
    models = dict.fromkeys([*council_models, chairman_model, TITLE_MODEL])
    return [{"model": m, **engine_status.get(m)} for m in models]


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.post("/api/conversations/{conversation_id}/files")
async def upload_file(conversation_id: str, file: UploadFile = File(...)):
    """Attach a PDF reference file to a conversation."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Read in chunks and stop as soon as the limit is passed, so an oversized
    # upload is never held in memory in full
    remaining = MAX_CONVERSATION_FILES_BYTES - sum(f["size"] for f in conversation["files"])
    chunks = []
    received = 0
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        received += len(chunk)
        if received > remaining:
            raise HTTPException(status_code=400, detail="Attachments for this conversation would exceed 14 MB")
        chunks.append(chunk)
    data = b"".join(chunks)

    if not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    return storage.add_file(conversation_id, file.filename or "document.pdf", data)


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    prior = conversation["messages"]
    is_first_message = len(prior) == 0
    files = storage.get_files(conversation_id)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run the 3-stage council process
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content, prior, files
    )

    # Save the question and its answer together (nothing is saved on failure)
    storage.add_turn(
        conversation_id,
        request.content,
        stage1_results,
        stage2_results,
        stage3_result
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    prior = conversation["messages"]
    is_first_message = len(prior) == 0
    files = storage.get_files(conversation_id)
    history = build_history(prior)

    async def event_generator():
        # The user message is saved together with the answer at the end, so
        # a failed or stopped run leaves nothing behind (the client drops its copy too)

        # Start title generation in parallel (don't await yet)
        title_task = None
        if is_first_message:
            title_task = asyncio.create_task(generate_conversation_title(request.content))

        try:
            # Stage 1: Collect responses
            yield _sse({'type': 'stage1_start'})
            box: List[Any] = []
            async with aclosing(_with_heartbeat(stage1_collect_responses(request.content, history, files), box)) as beats:
                async for ping in beats:
                    yield ping
            stage1_results = box.pop()
            yield _sse({'type': 'stage1_complete', 'data': stage1_results})

            if not stage1_results:
                # Same outcome as run_full_council: skip stages 2 and 3
                stage3_result = {"model": "error", "response": ALL_FAILED_RESPONSE}
                yield _sse({'type': 'stage3_complete', 'data': stage3_result})
                if title_task:
                    title = await title_task
                    storage.update_conversation_title(conversation_id, title)
                    yield _sse({'type': 'title_complete', 'data': {'title': title}})
                storage.add_turn(conversation_id, request.content, [], [], stage3_result)
                yield _sse({'type': 'complete'})
                return

            # Stage 2: Collect rankings
            yield _sse({'type': 'stage2_start'})
            async with aclosing(_with_heartbeat(stage2_collect_rankings(request.content, stage1_results, history, files), box)) as beats:
                async for ping in beats:
                    yield ping
            stage2_results, label_to_model = box.pop()
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            yield _sse({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})

            # Stage 3: Synthesize final answer
            yield _sse({'type': 'stage3_start'})
            async with aclosing(_with_heartbeat(stage3_synthesize_final(
                request.content, stage1_results, stage2_results, history, files,
                collect_verified_urls(prior, stage1_results)
            ), box)) as beats:
                async for ping in beats:
                    yield ping
            stage3_result = box.pop()
            yield _sse({'type': 'stage3_complete', 'data': stage3_result})

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield _sse({'type': 'title_complete', 'data': {'title': title}})

            # Save the question and its answer together
            storage.add_turn(
                conversation_id,
                request.content,
                stage1_results,
                stage2_results,
                stage3_result
            )

            # Send completion event
            yield _sse({'type': 'complete'})

        except Exception as e:
            # Send error event
            yield _sse({'type': 'error', 'message': str(e)})
        finally:
            # Client stopped or disconnected mid-run: nothing will be saved,
            # so don't keep paying for a title nobody will see
            if title_task and not title_task.done():
                title_task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
