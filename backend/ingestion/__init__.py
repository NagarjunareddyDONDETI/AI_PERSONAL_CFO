"""Document Ingestion Layer for AI Personal CFO."""
from __future__ import annotations

import os
from typing import Optional

from ingestion.base import DocumentParser
from ingestion.local_parser import LocalParser
from ingestion.ragflow_parser import RagflowParser
from ingestion.validator import ValidatedTransaction, parse_iso_date, sanitize_text, validate_transaction_row


def get_document_parser(parser_type: Optional[str] = None) -> DocumentParser:
    """Factory to retrieve configured document parser.

    Defaults to 'local'. If 'ragflow' is specified but RAGFLOW_API_KEY is not set,
    RagflowParser automatically delegates to LocalParser.
    """
    mode = (parser_type or os.getenv("DOCUMENT_PARSER", "local")).lower().strip()
    if mode == "ragflow":
        return RagflowParser()
    return LocalParser()


__all__ = [
    "DocumentParser",
    "LocalParser",
    "RagflowParser",
    "ValidatedTransaction",
    "get_document_parser",
    "parse_iso_date",
    "sanitize_text",
    "validate_transaction_row",
]
