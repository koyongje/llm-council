"""Configuration for the LLM Council."""

import os
from dotenv import load_dotenv

# .env takes precedence over OS environment variables
load_dotenv(override=True)

# Provider API keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Council members - "provider/model-id" (provider: anthropic | openai | google)
COUNCIL_MODELS = [
    "openai/gpt-5.1",
    "google/gemini-3.1-pro-preview",
    "anthropic/claude-opus-5-5",
]

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = "anthropic/claude-opus-5-5"

# Fast, cheap model for conversation titles
TITLE_MODEL = "google/gemini-3.8-flash"

# Anthropic requires an explicit output token limit
ANTHROPIC_MAX_TOKENS = 16000

# Data directory for conversation storage
DATA_DIR = "data/conversations"

# Uploaded reference files (PDFs), stored per conversation
UPLOADS_DIR = "data/uploads"

# Max total size of PDFs attached to one conversation
MAX_CONVERSATION_FILES_BYTES = 14 * 1024 * 1024
