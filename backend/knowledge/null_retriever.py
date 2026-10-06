"""Offline Null Knowledge Retriever for AI Personal CFO.

Provides safe zero-dependency defaults when RAGFlow is absent or disabled.
Can optionally supply basic static financial definitions without network calls.
"""
from __future__ import annotations

from typing import Optional

from knowledge.base import KnowledgeCitation, KnowledgeRetriever, RetrievalResult


class NullKnowledgeBase(KnowledgeRetriever):
    """Offline default knowledge retriever."""

    @property
    def name(self) -> str:
        return "null_retriever"

    def is_available(self) -> bool:
        return True

    def retrieve(
        self,
        query: str,
        top_k: int = 4,
        dataset_name: Optional[str] = None,
    ) -> RetrievalResult:
        """Return empty result without making any network calls."""
        return RetrievalResult(
            context="",
            citations=[],
            backend="null",
        )
