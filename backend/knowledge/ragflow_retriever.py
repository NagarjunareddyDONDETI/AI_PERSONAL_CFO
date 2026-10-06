"""RAGFlow Hybrid Knowledge Retrieval Adapter (Optional Service).

Provides semantic knowledge retrieval, regulatory grounding, and citations
from RAGFlow datasets. Degrades transparently to NullKnowledgeBase if unavailable.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

from knowledge.base import KnowledgeCitation, KnowledgeRetriever, RetrievalResult
from knowledge.null_retriever import NullKnowledgeBase

logger = logging.getLogger("knowledge.ragflow")


class RagflowKnowledgeBase(KnowledgeRetriever):
    """Knowledge base retrieval adapter via RAGFlow REST API."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: float = 5.0,
        default_dataset: str = "finzo_guidelines",
    ) -> None:
        self.api_url = (api_url or os.getenv("RAGFLOW_API_URL", "http://localhost:9380")).rstrip("/")
        self.api_key = api_key or os.getenv("RAGFLOW_API_KEY", "")
        self.timeout_seconds = float(os.getenv("RAGFLOW_TIMEOUT_SECONDS", str(timeout_seconds)))
        self.default_dataset = default_dataset
        self._null_fallback = NullKnowledgeBase()

    @property
    def name(self) -> str:
        return "ragflow_retriever"

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=2.0) as client:
                res = client.get(
                    f"{self.api_url}/api/v1/datasets",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return res.status_code in (200, 201)
        except Exception:
            return False

    def retrieve(
        self,
        query: str,
        top_k: int = 4,
        dataset_name: Optional[str] = None,
    ) -> RetrievalResult:
        """Query RAGFlow vector + full-text retrieval for grounding citations."""
        if not self.api_key or not query.strip():
            return self._null_fallback.retrieve(query, top_k, dataset_name)

        ds_target = dataset_name or self.default_dataset

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                payload = {
                    "question": query.strip(),
                    "dataset_ids": [ds_target] if ds_target else [],
                    "top_k": max(1, min(20, top_k)),
                    "similarity_threshold": 0.2,
                }
                res = client.post(
                    f"{self.api_url}/api/v1/retrieval",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )

                if res.status_code != 200:
                    logger.warning("RAGFlow retrieval request failed (%d): %s", res.status_code, res.text)
                    return self._null_fallback.retrieve(query, top_k, dataset_name)

                data = res.json().get("data", {})
                chunks = data.get("chunks", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

                citations: list[KnowledgeCitation] = []
                contexts: list[str] = []

                for ch in chunks[:top_k]:
                    if not isinstance(ch, dict):
                        continue
                    content = (ch.get("content_with_weight") or ch.get("content") or "").strip()
                    doc_name = ch.get("docnm_kwd") or ch.get("document_name") or "Financial Reference"
                    sim = float(ch.get("similarity", 0.0) or ch.get("vector_similarity", 0.0))
                    pg = ch.get("page_num_int") or ch.get("page_number")

                    if content:
                        citations.append(
                            KnowledgeCitation(
                                source_title=str(doc_name),
                                snippet=content[:500],
                                confidence=sim,
                                dataset_name=ds_target,
                                page_number=int(pg) if pg is not None else None,
                            )
                        )
                        contexts.append(f"[{doc_name}]: {content}")

                combined_context = "\n\n".join(contexts)
                return RetrievalResult(
                    context=combined_context,
                    citations=citations,
                    backend="ragflow",
                )

        except Exception as exc:
            logger.warning("RAGFlow retrieval error: %s; falling back to null retriever", exc)
            return self._null_fallback.retrieve(query, top_k, dataset_name)
