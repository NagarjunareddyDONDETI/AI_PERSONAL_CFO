"""Local Deterministic Document Parser for AI Personal CFO.

Wraps local ingestion formats (CSV, TSV, Excel, JSON, PDF via pdfplumber)
and routes all extracted records through the deterministic validation gate.
Guaranteed 100% offline functionality and zero network latency.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from agents.ingestion_agent import IngestionError, parse_statement
from ingestion.base import DocumentParser
from ingestion.validator import ValidatedTransaction, validate_transaction_row

logger = logging.getLogger("ingestion.local")


class LocalParser(DocumentParser):
    """Zero-dependency local statement parser."""

    @property
    def name(self) -> str:
        return "local_parser"

    def is_available(self) -> bool:
        return True

    def parse(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: Optional[str] = None,
    ) -> list[ValidatedTransaction]:
        """Parse statement locally and validate every row."""
        try:
            raw_txns = parse_statement(file_bytes, filename=filename)
        except IngestionError as err:
            logger.warning("LocalParser failed on %s: %s", filename, err)
            return []
        except Exception as exc:
            logger.error("Unexpected error in LocalParser on %s: %s", filename, exc, exc_info=True)
            return []

        validated: list[ValidatedTransaction] = []
        for raw in raw_txns:
            vt = validate_transaction_row(raw, source_parser="local")
            if vt is not None:
                validated.append(vt)

        logger.info("LocalParser parsed %d valid transactions from %s", len(validated), filename)
        return validated
