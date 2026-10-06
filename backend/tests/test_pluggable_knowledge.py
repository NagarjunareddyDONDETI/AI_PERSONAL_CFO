"""Tests for Pluggable Knowledge Retrieval Layer."""
from __future__ import annotations

import pytest

from knowledge import get_knowledge_retriever
from knowledge.null_retriever import NullKnowledgeBase
from knowledge.ragflow_retriever import RagflowKnowledgeBase


def test_null_retriever_returns_empty_gracefully() -> None:
    retriever = NullKnowledgeBase()
    assert retriever.is_available() is True
    res = retriever.retrieve("What is the 50/30/20 budget rule?")
    assert res.context == ""
    assert res.citations == []
    assert res.backend == "null"


def test_ragflow_retriever_offline_fallback() -> None:
    retriever = RagflowKnowledgeBase(api_url="http://localhost:9999", api_key="", timeout_seconds=0.1)
    assert retriever.is_available() is False
    res = retriever.retrieve("What are the 401k contribution limits?")
    assert res.backend == "null"
    assert res.citations == []


def test_knowledge_retriever_factory() -> None:
    r_null = get_knowledge_retriever("null")
    assert isinstance(r_null, NullKnowledgeBase)

    r_rag = get_knowledge_retriever("ragflow")
    assert isinstance(r_rag, RagflowKnowledgeBase)
