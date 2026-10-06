"""Base Abstract Knowledge Retrieval Protocol and Data Structures."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class KnowledgeCitation:
    source_title: str
    snippet: str
    confidence: float = 0.0
    url_or_ref: Optional[str] = None
    dataset_name: str = "general_finance"
    page_number: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_title": self.source_title,
            "snippet": self.snippet,
            "confidence": round(self.confidence, 4),
            "url_or_ref": self.url_or_ref,
            "dataset_name": self.dataset_name,
            "page_number": self.page_number,
        }


@dataclass(frozen=True)
class RetrievalResult:
    context: str
    citations: list[KnowledgeCitation] = field(default_factory=list)
    backend: str = "null"

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context,
            "citations": [c.to_dict() for c in self.citations],
            "backend": self.backend,
        }


class KnowledgeRetriever(ABC):
    """Abstract base class for financial knowledge retrievers."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def retrieve(
        self,
        query: str,
        top_k: int = 4,
        dataset_name: Optional[str] = None,
    ) -> RetrievalResult:
        """Retrieve relevant background financial knowledge and citations.

        Must never throw unhandled exceptions: return empty RetrievalResult on failure.
        """
        ...
