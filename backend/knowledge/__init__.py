"""Knowledge Retrieval Layer for AI Personal CFO."""
from __future__ import annotations

import os
from typing import Optional

from knowledge.base import KnowledgeCitation, KnowledgeRetriever, RetrievalResult
from knowledge.null_retriever import NullKnowledgeBase
from knowledge.ragflow_retriever import RagflowKnowledgeBase


def get_knowledge_retriever(retriever_type: Optional[str] = None) -> KnowledgeRetriever:
    """Factory to retrieve configured knowledge retriever.

    Defaults to 'null'. If 'ragflow' is requested, returns RagflowKnowledgeBase
    which gracefully degrades to NullKnowledgeBase if offline or unconfigured.
    """
    mode = (retriever_type or os.getenv("KNOWLEDGE_RETRIEVER", "null")).lower().strip()
    if mode == "ragflow":
        return RagflowKnowledgeBase()
    return NullKnowledgeBase()


__all__ = [
    "KnowledgeCitation",
    "KnowledgeRetriever",
    "NullKnowledgeBase",
    "RagflowKnowledgeBase",
    "RetrievalResult",
    "get_knowledge_retriever",
]
