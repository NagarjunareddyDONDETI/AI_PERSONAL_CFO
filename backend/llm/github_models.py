"""GitHub Models provider (Azure AI inference, OpenAI-compatible).

Authenticates with a GitHub personal-access token (``GITHUB_TOKEN``).
"""
from __future__ import annotations

import os

from ._openai_compat import OpenAICompatProvider


class GitHubModelsProvider(OpenAICompatProvider):
    name = "github"
    # The old models.inference.ai.azure.com host no longer resolves at all.
    # This is the current endpoint, but note that GitHub Models is being retired:
    # it currently answers 410 "github_models_retirement_brownout". Leave
    # GITHUB_TOKEN unset to skip this provider until that changes.
    chat_url = "https://models.github.ai/inference/chat/completions"

    def __init__(self) -> None:
        self.model = os.getenv("GITHUB_MODEL", "gpt-4o-mini")

    def _api_key(self) -> str | None:
        return os.getenv("GITHUB_TOKEN")
