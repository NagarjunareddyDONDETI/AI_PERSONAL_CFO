"""Deterministic Transaction Validation Gate for AI Personal CFO.

Validates that any ingested transaction (from LocalParser or RagflowParser)
satisfies strict schema, type, bounds, and precision constraints before entering
the CFO database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional


@dataclass(frozen=True)
class ValidatedTransaction:
    date: str           # ISO format: YYYY-MM-DD
    amount: Decimal     # Positive for income, negative for expense
    description: str    # Cleaned, bounded description
    category: str = "Uncategorized"
    balance: Optional[Decimal] = None
    source_parser: str = "local"
    raw_row: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        amt_float = float(self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        bal_float = float(self.balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if self.balance is not None else None
        return {
            "date": self.date,
            "amount": amt_float,
            "description": self.description,
            "category": self.category,
            "balance": bal_float,
            "source_parser": self.source_parser,
        }


# ISO regex validation
_DATE_ISO_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso_date(date_str: Any) -> Optional[str]:
    """Normalize date strings (YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY) into ISO YYYY-MM-DD."""
    if not date_str:
        return None
    s = str(date_str).strip()
    if _DATE_ISO_REGEX.match(s):
        try:
            datetime.strptime(s, "%Y-%m-%d")
            return s
        except ValueError:
            return None

    # Common alternate formats
    for fmt in (
        "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d %b %Y",
        "%d-%b-%Y", "%d %B %Y", "%d-%B-%Y", "%Y/%m/%d",
        "%Y.%m.%d", "%d.%m.%Y",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# Prompt injection signatures to neutralize in untrusted document text
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*:", re.IGNORECASE),
    re.compile(r"<\s*\|?\s*im_start\s*\|?\s*>", re.IGNORECASE),
    re.compile(r"<\s*\|?\s*im_end\s*\|?\s*>", re.IGNORECASE),
    re.compile(r"role\s*:\s*system", re.IGNORECASE),
    re.compile(r"delete\s+database", re.IGNORECASE),
]


def sanitize_text(text: Any, max_len: int = 256) -> str:
    """Sanitize description: neutralize prompt-injections and remove control characters."""
    if text is None:
        return "Transaction"
    s = str(text).strip()
    # Strip non-printable/control chars except standard punctuation and alphanumerics
    s = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", s)

    # Neutralize prompt injection patterns
    for pat in _INJECTION_PATTERNS:
        s = pat.sub("[FILTERED_PROMPT_INJECTION]", s)

    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s).strip()
    # Enforce bounds
    return s[:max_len] if s else "Transaction"


def validate_transaction_row(
    row: dict[str, Any],
    source_parser: str = "local",
) -> Optional[ValidatedTransaction]:
    """Strictly validate a raw dictionary into a ValidatedTransaction or None."""
    if not isinstance(row, dict):
        return None

    raw_date = row.get("date") or row.get("Date") or row.get("txn_date") or row.get("Transaction Date")
    norm_date = parse_iso_date(raw_date)
    if not norm_date:
        return None

    raw_amt = row.get("amount") if "amount" in row else row.get("Amount")
    if raw_amt is None:
        # Check debit/credit columns
        debit = row.get("debit") or row.get("Debit") or row.get("withdrawal") or row.get("Withdrawal")
        credit = row.get("credit") or row.get("Credit") or row.get("deposit") or row.get("Deposit")
        if debit:
            raw_amt = f"-{debit}"
        elif credit:
            raw_amt = credit
        else:
            return None

    try:
        amt_str = str(raw_amt).replace(",", "").strip()
        amt_dec = Decimal(amt_str)
        if amt_dec.is_nan() or amt_dec.is_infinite():
            return None
    except (InvalidOperation, ValueError, TypeError):
        return None

    if amt_dec == Decimal("0.00"):
        return None

    raw_desc = (
        row.get("description")
        or row.get("Description")
        or row.get("narration")
        or row.get("Narration")
        or row.get("details")
        or "Transaction"
    )
    clean_desc = sanitize_text(raw_desc)

    raw_bal = row.get("balance") or row.get("Balance")
    bal_dec = None
    if raw_bal is not None:
        try:
            bal_str = str(raw_bal).replace(",", "").strip()
            b = Decimal(bal_str)
            if not b.is_nan() and not b.is_infinite():
                bal_dec = b
        except Exception:
            bal_dec = None

    category = str(row.get("category") or row.get("Category") or "Uncategorized")

    return ValidatedTransaction(
        date=norm_date,
        amount=amt_dec,
        description=clean_desc,
        category=category,
        balance=bal_dec,
        source_parser=source_parser,
        raw_row=row,
    )
