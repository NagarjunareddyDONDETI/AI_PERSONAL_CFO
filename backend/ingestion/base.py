"""Base Abstract Document Parser and Ingestion Protocol."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from ingestion.validator import ValidatedTransaction


class DocumentParser(ABC):
    """Abstract interface for all document parsers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name identifier of the parser."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if parser dependencies / services are reachable."""
        ...

    @abstractmethod
    def parse(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: Optional[str] = None,
    ) -> list[ValidatedTransaction]:
        """Parse raw document bytes into strictly validated transactions.

        Must never throw unhandled exceptions: return empty list on fatal parsing failure.
        """
        ...
