# RAGFlow Integration Guide for AI Personal CFO (FINZO)

This guide documents how **RAGFlow** operates as an **OPTIONAL** ingestion and knowledge service for AI Personal CFO.

---

## 1. Architectural Role

```
+-----------------------------------------------------------------------------------+
|                            AI Personal CFO (FINZO)                                |
|                                                                                   |
|  +-----------------------------+           +-----------------------------------+  |
|  |   Document Ingestion Layer  |           |   Knowledge Retrieval Layer       |  |
|  |                             |           |                                   |  |
|  |  +-----------------------+  |           |  +-----------------------------+  |  |
|  |  | LocalParser (Default) |  |           |  | NullKnowledgeBase (Default) |  |  |
|  |  | - PDF, CSV, Excel     |  |           |  | - Zero-network offline      |  |  |
|  |  +-----------------------+  |           |  +-----------------------------+  |  |
|  |              ^              |           |                ^                  |  |
|  |       Fallback on error     |           |         Fallback on error         |  |
|  |              |              |           |                |                  |  |
|  |  +-----------------------+  |           |  +-----------------------------+  |  |
|  |  | RagflowParser (Opt)   |  |           |  | RagflowKnowledgeBase (Opt)  |  |  |
|  |  | - DeepDoc OCR & Table |  |           |  | - Hybrid vector + keyword   |  |  |
|  |  +-----------------------+  |           |  +-----------------------------+  |  |
|  +--------------+--------------+           +----------------+------------------+  |
|                 |                                           |                     |
|                 v                                           v                     |
|  +-----------------------------+           +-----------------------------------+  |
|  | Deterministic Validation    |           | Grounded Citations                |  |
|  | - Strict Decimal types      |           | - Source Title, Page, Similarity  |  |
|  | - Prompt-injection filter   |           | - Read-only context for LLM       |  |
|  +--------------+--------------+           +-----------------------------------+  |
|                 |                                                                 |
|                 v                                                                 |
|  +-----------------------------+                                                  |
|  | FINZO DB (Single Truth)     |                                                  |
|  +-----------------------------+                                                  |
+-----------------------------------------------------------------------------------+
```

---

## 2. Configuration & Environment Variables

All RAGFlow settings are optional. If unspecified, FINZO runs 100% offline using local parsing and zero external knowledge dependencies.

```bash
# Ingestion Mode ('local' or 'ragflow')
DOCUMENT_PARSER=local

# Knowledge Retriever Mode ('null' or 'ragflow')
KNOWLEDGE_RETRIEVER=null

# RAGFlow API Configuration (Required ONLY if mode is 'ragflow')
RAGFLOW_API_URL=http://localhost:9380
RAGFLOW_API_KEY=ragflow-your-api-key
RAGFLOW_TIMEOUT_SECONDS=5.0
```

---

## 3. Invariants & Safety Guarantees

1. **RAGFlow is never a source of financial truth**: All parsed transactions must pass `validate_transaction_row()` in `backend/ingestion/validator.py` where types, ISO dates, and `Decimal` amounts are strictly verified.
2. **Zero-Crash Graceful Degradation**: If RAGFlow is unreachable, times out, or returns a 500 error, `RagflowParser` automatically catches the exception and executes `LocalParser`, logging a warning without interrupting the user.
3. **Prompt-Injection Neutralization**: All text descriptions parsed from documents are sanitized via `sanitize_text()`, stripping prompt-injection keywords (`ignore previous instructions`, `system prompt:`, `delete database`) before reaching any LLM prompt.
