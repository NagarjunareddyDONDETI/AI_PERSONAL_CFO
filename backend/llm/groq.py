"""Groq provider (OpenAI-compatible, very low latency)."""
from __future__ import annotations

import os

from ._openai_compat import OpenAICompatProvider


class GroqProvider(OpenAICompatProvider):
    name = "groq"
    chat_url = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self) -> None:
        # llama-3.3-70b-versatile was retired by Groq and now 404s with
        # "model_not_found". Verify against GET /openai/v1/models before changing.
        self.model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    def _api_key(self) -> str | None:
        return os.getenv("GROQ_API_KEY")
