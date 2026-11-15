"""JSON-based storage for conversations."""

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path
from .config import DATA_DIR, UPLOADS_DIR
from .providers import PdfFile


logger = logging.getLogger(__name__)


def is_valid_id(conversation_id: str) -> bool:
    """Conversation ids are UUIDs; anything else could escape the data directories."""
    try:
        uuid.UUID(conversation_id)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def ensure_data_dir():
    """Ensure the data directory exists."""
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def get_conversation_path(conversation_id: str) -> str:
    """Get the file path for a conversation."""
    return os.path.join(DATA_DIR, f"{conversation_id}.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: str, data: Dict[str, Any]) -> None:
    """Write via a temp file + rename so a crash never leaves a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def create_conversation(conversation_id: str) -> Dict[str, Any]:
    """
    Create a new conversation.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        New conversation dict
    """
    ensure_data_dir()

    conversation = {
        "id": conversation_id,
        "created_at": _now(),
        "title": "New Conversation",
        "messages": [],
        "files": []
    }

    _write_json(get_conversation_path(conversation_id), conversation)
    return conversation


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a conversation from storage.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        Conversation dict or None if not found
    """
    if not is_valid_id(conversation_id):
        return None
    path = get_conversation_path(conversation_id)

    if not os.path.exists(path):
        return None

    with open(path, 'r') as f:
        conversation = json.load(f)
    conversation.setdefault("files", [])
    return conversation


def save_conversation(conversation: Dict[str, Any]):
    """
    Save a conversation to storage.

    Args:
        conversation: Conversation dict to save
    """
    ensure_data_dir()

    _write_json(get_conversation_path(conversation['id']), conversation)


def list_conversations() -> List[Dict[str, Any]]:
    """
    List all conversations (metadata only).

    Returns:
        List of conversation metadata dicts
    """
    ensure_data_dir()

    conversations = []
    for filename in os.listdir(DATA_DIR):
        if filename.endswith('.json'):
            path = os.path.join(DATA_DIR, filename)
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                # Return metadata only
                conversations.append({
                    "id": data["id"],
                    "created_at": data["created_at"],
                    "title": data.get("title", "New Conversation"),
                    "message_count": len(data["messages"])
                })
            except (OSError, ValueError, KeyError) as e:
                # One unreadable file must not hide every other conversation
                logger.warning("Skipping unreadable conversation file %s: %s", path, e)

    # Sort by creation time, newest first
    conversations.sort(key=lambda x: x["created_at"], reverse=True)

    return conversations


def add_turn(
    conversation_id: str,
    user_content: str,
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any]
):
    """
    Append a user message and its council answer in a single save.

    Saving both together means a failed council run leaves no orphan user
    message behind (the client discards its optimistic copy on error).
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["messages"].append({"role": "user", "content": user_content})
    conversation["messages"].append({
        "role": "assistant",
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3
    })

    save_conversation(conversation)


def update_conversation_title(conversation_id: str, title: str):
    """
    Update the title of a conversation.

    Args:
        conversation_id: Conversation identifier
        title: New title for the conversation
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["title"] = title
    save_conversation(conversation)


def _uploads_path(conversation_id: str, file_id: str) -> Path:
    return Path(UPLOADS_DIR) / conversation_id / f"{file_id}.pdf"


def add_file(conversation_id: str, filename: str, data: bytes) -> Dict[str, Any]:
    """
    Store a PDF for a conversation and record it in the conversation.

    Returns:
        File metadata dict: {id, filename, size, uploaded_at}
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    file_id = uuid.uuid4().hex
    path = _uploads_path(conversation_id, file_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    entry = {
        "id": file_id,
        "filename": filename,
        "size": len(data),
        "uploaded_at": _now()
    }
    conversation["files"].append(entry)
    save_conversation(conversation)
    return entry


def get_files(conversation_id: str) -> List[PdfFile]:
    """Load the bytes of every file attached to a conversation."""
    conversation = get_conversation(conversation_id)
    if conversation is None:
        return []
    files = []
    for f in conversation.get("files", []):
        path = _uploads_path(conversation_id, f["id"])
        try:
            files.append(PdfFile(filename=f["filename"], data=path.read_bytes()))
        except FileNotFoundError:
            logger.warning("Skipping missing attachment %s for conversation %s", path, conversation_id)
    return files
