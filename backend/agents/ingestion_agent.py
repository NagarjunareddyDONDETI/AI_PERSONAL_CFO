"""Statement ingestion: parse, clean, and validate bank-statement rows.

Accepts many file formats and normalises them to a clean list of
``{date, description, amount}`` dicts:

- CSV / TXT / TSV / any delimited text (delimiter is auto-sniffed)
- Excel: .xlsx (openpyxl) and legacy .xls (xlrd)
- OpenDocument spreadsheets: .ods (odf) when available
- JSON: array of records or {"transactions": [...]}
- PDF: tabular bank statements (pdfplumber) when available

Row-level cleaning handles:
- +/- signs on amounts, Dr/Cr suffixes, parentheses for negatives
- comma / space grouped amounts (e.g. "+50,000")
- currency symbols (Rs, INR, ₹, $, etc.)
- many date formats (DD-MM-YYYY, ISO, etc.), day-first by default
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
from datetime import datetime
from typing import Any

import pandas as pd

logger = logging.getLogger("agents.ingestion")

# Columns we will try to map, case-insensitive.
_DATE_KEYS = {"date", "txn date", "transaction date", "value date", "posting date"}
_DESC_KEYS = {
    "description",
    "desc",
    "narration",
    "particulars",
    "details",
    "merchant",
    "remarks",
    "transaction details",
}
_AMT_KEYS = {"amount", "amt", "value", "transaction amount"}
# Separate debit/credit columns are common in Indian bank exports.
_DEBIT_KEYS = {"debit", "withdrawal", "withdrawal amt", "dr", "debit amount", "paid out"}
_CREDIT_KEYS = {"credit", "deposit", "deposit amt", "cr", "credit amount", "paid in"}

_DATE_FORMATS = [
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d-%m-%y",
    "%d/%m/%y",
    "%m/%d/%Y",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d-%B-%Y",
    "%d %B %Y",
    "%Y/%m/%d",
]


class IngestionError(Exception):
    """Raised when a file cannot be parsed into valid transactions."""


def _find_column(
    columns: list[str], candidates: set[str], exclude: set | None = None
) -> str | None:
    """Locate a column by name, exact match first then substring.

    ``exclude`` skips already-claimed columns. This matters because the generic
    amount key "amt" substring-matches real debit/credit headings such as
    "Withdrawal Amt" and "Deposit Amt" (HDFC's exact wording): without excluding
    them, a withdrawal column gets treated as a signed amount, which drops rows
    and flips signs.
    """
    blocked = {str(c) for c in (exclude or set())}
    lowered = {
        str(c).lower().strip(): c for c in columns if str(c) not in blocked
    }
    for cand in candidates:
        if cand in lowered:
            return lowered[cand]
    # fuzzy contains
    for low, original in lowered.items():
        if any(cand in low for cand in candidates):
            return original
    return None


def _parse_amount(raw: Any) -> float:
    if raw is None:
        raise ValueError("empty amount")
    s = str(raw).strip()
    if s == "" or s.lower() in {"nan", "none"}:
        raise ValueError("empty amount")
    # Detect sign
    sign = 1.0
    low = s.lower()
    if s.startswith("-") or s.startswith("(") or low.endswith("dr") or " dr" in low:
        sign = -1.0
    if s.startswith("+") or low.endswith("cr") or " cr" in low:
        sign = 1.0
    # Strip currency symbols, letters, parens, commas, spaces, sign chars
    cleaned = re.sub(r"[^\d.]", "", s)
    if cleaned == "":
        raise ValueError(f"no numeric value in amount: {raw!r}")
    # Guard against multiple dots (e.g. thousands with '.') -> keep last as decimal
    if cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    value = float(cleaned)
    return sign * value


def _parse_date(raw: Any) -> str:
    s = str(raw).strip()
    # pandas Timestamp / datetime coming from Excel cells
    if isinstance(raw, (pd.Timestamp, datetime)):
        return pd.Timestamp(raw).strftime("%Y-%m-%d")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # last resort: let pandas try (dayfirst for Indian statements)
    try:
        return pd.to_datetime(s, dayfirst=True).strftime("%Y-%m-%d")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"unparseable date: {raw!r}") from exc


def _dataframe_to_transactions(df: pd.DataFrame) -> list[dict]:
    """Map an arbitrary statement DataFrame to clean transactions."""
    if df is None or df.empty:
        raise IngestionError("The file contains no rows.")

    # Drop fully-empty columns/rows that spreadsheets often carry.
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
    df.columns = [str(c).strip() for c in df.columns]
    cols = list(df.columns)

    date_col = _find_column(cols, _DATE_KEYS)
    desc_col = _find_column(cols, _DESC_KEYS)
    # Resolve the specific debit/credit columns before the generic amount column
    # so "Withdrawal Amt" is not claimed as a plain signed amount.
    debit_col = _find_column(cols, _DEBIT_KEYS)
    credit_col = _find_column(cols, _CREDIT_KEYS, exclude={debit_col})
    amt_col = _find_column(cols, _AMT_KEYS, exclude={debit_col, credit_col})

    has_amount = amt_col is not None
    has_split = debit_col is not None or credit_col is not None

    missing = []
    if date_col is None:
        missing.append("date")
    if desc_col is None:
        missing.append("description")
    if not has_amount and not has_split:
        missing.append("amount (or debit/credit)")
    if missing:
        raise IngestionError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Found columns: {', '.join(cols) or '(none)'}"
        )

    transactions: list[dict] = []
    errors: list[str] = []
    for idx, row in df.iterrows():
        try:
            date = _parse_date(row[date_col])
            desc = str(row[desc_col]).strip()
            if desc == "" or desc.lower() == "nan":
                raise ValueError("empty description")

            # Prefer the debit/credit pair when present: it states the direction
            # explicitly, whereas a lone amount column relies on a sign that
            # many exports omit. Falls back per row, since these columns are
            # mutually exclusive and one of them is blank on every row.
            amount = None
            if has_split:
                debit = 0.0
                credit = 0.0
                if debit_col is not None:
                    try:
                        debit = abs(_parse_amount(row[debit_col]))
                    except ValueError:
                        debit = 0.0
                if credit_col is not None:
                    try:
                        credit = abs(_parse_amount(row[credit_col]))
                    except ValueError:
                        credit = 0.0
                if debit or credit:
                    amount = credit - debit
            if amount is None and has_amount:
                amount = _parse_amount(row[amt_col])
            if amount is None:
                raise ValueError("no amount, debit or credit value")

            transactions.append({"date": date, "description": desc, "amount": amount})
        except ValueError as exc:
            errors.append(f"row {idx + 2}: {exc}")
            continue

    if not transactions:
        raise IngestionError(
            "No valid transactions found. Sample errors: " + "; ".join(errors[:5])
        )

    transactions.sort(key=lambda t: t["date"])
    return transactions


# ---------- format-specific readers ----------
def _decode_text(content: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    # last resort: detect
    try:
        import chardet

        guess = chardet.detect(content).get("encoding") or "utf-8"
        return content.decode(guess, errors="replace")
    except Exception:  # noqa: BLE001
        return content.decode("utf-8", errors="replace")


def _read_delimited(content: bytes | str) -> pd.DataFrame:
    text = _decode_text(content) if isinstance(content, bytes) else content
    # Sniff the delimiter from the first non-empty line.
    sample_lines = [ln for ln in text.splitlines() if ln.strip()][:5]
    sample = "\n".join(sample_lines)
    delimiter = ","
    if sample:
        counts = {d: sample.count(d) for d in [",", "\t", ";", "|"]}
        delimiter = max(counts, key=counts.get) if max(counts.values()) > 0 else ","
    try:
        return pd.read_csv(io.StringIO(text), sep=delimiter, engine="python", skip_blank_lines=True)
    except Exception as exc:  # noqa: BLE001
        raise IngestionError(f"Could not read delimited text: {exc}") from exc


def _read_excel(content: bytes, engine: str | None = None) -> pd.DataFrame:
    try:
        return pd.read_excel(io.BytesIO(content), engine=engine)
    except Exception as exc:  # noqa: BLE001
        raise IngestionError(
            f"Could not read spreadsheet: {exc}. "
            "Make sure the file is a valid Excel/ODS workbook."
        ) from exc


def _read_json(content: bytes | str) -> pd.DataFrame:
    text = _decode_text(content) if isinstance(content, bytes) else content
    try:
        data = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        raise IngestionError(f"Invalid JSON: {exc}") from exc
    if isinstance(data, dict):
        for key in ("transactions", "data", "rows", "records"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise IngestionError("JSON must be an array of transaction objects.")
    return pd.DataFrame(data)


# A date token anywhere in a line: 01-01-2025, 1/1/25, 2025-01-01, 01 Jan 2025,
# 01-Jan-2025, 01.01.2025. The lookarounds stop it matching inside a longer
# number (e.g. an account or reference number).
_DATE_TOKEN = (
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"                 # 2025-01-01
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"              # 01-01-2025 / 1/1/25
    r"|\d{1,2}[-\s][A-Za-z]{3,9}[-\s,]{1,2}\s?\d{2,4}"  # 01 Jan 2025 / 01-Jan-2025
    r"|[A-Za-z]{3,9}\s\d{1,2},?\s\d{2,4}"            # Jan 01, 2025
)
_LINE_DATE_RE = re.compile(rf"(?<![\d/-])({_DATE_TOKEN})(?![\d/-])")

# How far into a line the transaction date may start. Statements frequently lead
# with a serial number ("1  01-04-2025  ...") or a reference id, so anchoring to
# the start of the line drops every row in those layouts.
_MAX_DATE_OFFSET = 40
# A monetary token with 2 decimals, optional grouping, sign, parens and Dr/Cr.
_MONEY_RE = re.compile(
    r"(\(?\s*[-+]?\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})\s*\)?)\s*(cr|dr)?",
    re.IGNORECASE,
)
# Fallback: integer amounts (no decimals) with optional grouping / Dr-Cr.
_MONEY_INT_RE = re.compile(
    r"(\(?\s*[-+]?\d{1,3}(?:,\d{2,3})+\s*\)?|\(?\s*[-+]?\d{3,}\s*\)?)\s*(cr|dr)?",
    re.IGNORECASE,
)

# Highest-confidence form: a number attached to a currency symbol. UPI/wallet
# statements (PhonePe, GPay, Paytm) print "₹8" with no decimals and no grouping,
# which neither pattern above matches, and they also embed 10-digit phone numbers
# in the description — anchoring on the symbol picks the real amount and ignores
# the phone number, which is otherwise read as ₹9,848,369,396.
_CURRENCY_SYMBOL = r"(?:\u20b9|Rs\.?|INR|\$|\u20ac|\u00a3|\u00a5)"
_AMOUNT_BODY = r"\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d{1,9}(?:\.\d{1,2})?"
_MONEY_CURRENCY_RE = re.compile(
    rf"{_CURRENCY_SYMBOL}\s*(\(?\s*[-+]?(?:{_AMOUNT_BODY})\s*\)?)\s*(cr|dr)?",
    re.IGNORECASE,
)

# No real transaction amount has 10+ integer digits, but phone numbers, UTR
# numbers and account numbers do. Used to reject them outright.
_MAX_AMOUNT_DIGITS = 9

# Statements that name the direction in words rather than with a Dr/Cr suffix.
_DEBIT_WORD_RE = re.compile(r"\b(?:debit|debited|withdrawal|withdrawn)\b", re.I)
_CREDIT_WORD_RE = re.compile(r"\b(?:credit|credited|deposit|deposited)\b", re.I)
_CREDIT_HINTS = (
    "salary",
    "credit",
    "deposit",
    "refund",
    "cashback",
    "interest",
    "neft cr",
    "imps cr",
    "received",
    "reversal",
)


def _pdf_extract_text(pdf) -> str:
    """Fast path: pull text from every page (cheap in pdfplumber)."""
    parts: list[str] = []
    for page in pdf.pages:
        txt = page.extract_text() or ""
        if txt:
            parts.append(txt)
    return "\n".join(parts)


def _pdf_extract_tables(pdf) -> list:
    """Slow path: table detection per page. Only call when text parsing fails."""
    tables: list = []
    for page in pdf.pages:
        for table in page.extract_tables() or []:
            if table:
                tables.append(table)
    return tables


def _cells(row: list) -> list[str]:
    return [str(c or "").strip().replace("\n", " ") for c in row]


def _is_transaction_header(cols: list[str]) -> bool:
    """True when a row names a date column and something amount-like."""
    return bool(_find_column(cols, _DATE_KEYS)) and bool(
        _find_column(cols, _AMT_KEYS)
        or _find_column(cols, _DEBIT_KEYS)
        or _find_column(cols, _CREDIT_KEYS)
    )


def _find_header(table: list) -> tuple[int, list[str]] | None:
    """Locate the header row in one table, returning (body_start_index, columns).

    Scans the first few rows rather than assuming row 0, and tries merging each
    row with the next, because statements often wrap a heading across two lines
    ("Withdrawal" above "Amt").
    """
    for i, row in enumerate(table[:4]):
        cols = _cells(row)
        if _is_transaction_header(cols):
            return i + 1, cols
        if i + 1 < len(table):
            nxt = _cells(table[i + 1])
            merged = [
                f"{a} {b}".strip()
                for a, b in zip(cols + [""] * len(nxt), nxt + [""] * len(cols))
            ][: max(len(cols), len(nxt))]
            if _is_transaction_header(merged):
                return i + 2, merged
    return None


def _tables_to_df(tables: list) -> pd.DataFrame | None:
    """Assemble transaction rows from detected tables.

    Every table is considered on its own instead of trusting the first one's
    first row: in real bank PDFs the first detected table is usually the account
    summary box (name, address, account number), and using its header made the
    whole table path fail. Tables with no header of their own but a matching
    column count are treated as continuations onto the next page.
    """
    header: list[str] | None = None
    rows: list[list[str]] = []

    for table in tables:
        if not table or not any(any(_cells(r)) for r in table):
            continue
        found = _find_header(table)
        if found is not None:
            start, cols = found
            if header is None:
                header = cols
            elif len(cols) != len(header):
                # A differently-shaped table: keep the first transaction table.
                continue
            rows.extend(_cells(r) for r in table[start:])
        elif header is not None and len(table[0]) == len(header):
            # Continuation of the transaction table on a later page.
            rows.extend(_cells(r) for r in table)

    if not header or not rows:
        return None

    width = len(header)
    # Blank column headings break column lookup; give them stable placeholders.
    header = [c if c else f"col_{i}" for i, c in enumerate(header)]
    norm = [r[:width] + [""] * (width - len(r)) for r in rows]
    # Drop rows that are entirely empty or that repeat the header on a new page.
    norm = [
        r for r in norm
        if any(cell for cell in r) and not _is_transaction_header(r)
    ]
    if not norm:
        return None

    df = pd.DataFrame(norm, columns=header)
    return df if _is_transaction_header([str(c) for c in df.columns]) else None


def _money_matches(text: str) -> list[re.Match]:
    """Money tokens in a line, most trustworthy interpretation first.

    A currency symbol is the strongest signal available, so it wins outright.
    Only if there is none do we guess from shape, where a bare digit run could
    equally be a reference or phone number.
    """
    for pattern in (_MONEY_CURRENCY_RE, _MONEY_RE, _MONEY_INT_RE):
        matches = [m for m in pattern.finditer(text) if _token_value(m)[0] is not None]
        if matches:
            return matches
    return []


def _token_value(m: re.Match) -> tuple[float | None, str | None]:
    """Numeric value and Dr/Cr marker for a money match, or (None, ...) if the
    token cannot be an amount (too many digits to be anything but an id)."""
    token = m.group(1).strip()
    marker = (m.group(2) or "").lower() or None
    negative = token.startswith("(") or token.startswith("-")
    num = re.sub(r"[^\d.]", "", token)
    if num in ("", "."):
        return None, marker
    integer_digits = num.split(".")[0]
    if len(integer_digits) > _MAX_AMOUNT_DIGITS:
        return None, marker  # phone / UTR / account number, not money
    try:
        value = float(num)
    except ValueError:
        return None, marker
    return (-value if negative else value), marker


def _amount_from_line(rest: str, description: str) -> float | None:
    """Pick the transaction amount from the non-date part of a statement line."""
    matches = _money_matches(rest)
    if not matches:
        return None

    # A Dr/Cr suffix on the number itself is unambiguous: that token is the
    # transaction amount, not the running balance.
    for m in matches:
        value, marker = _token_value(m)
        if value is None:
            continue
        if marker == "dr":
            return -abs(value)
        if marker == "cr":
            return abs(value)

    value, _ = _token_value(matches[0])
    if value is None or value == 0.0:
        return None
    if value < 0:
        return value

    # Direction stated as a word ("... DEBIT ₹8") beats guessing from the
    # description, which is how UPI statements label every row.
    if _CREDIT_WORD_RE.search(rest):
        return abs(value)
    if _DEBIT_WORD_RE.search(rest):
        return -abs(value)

    desc_low = description.lower()
    is_credit = any(h in desc_low for h in _CREDIT_HINTS)
    return abs(value) if is_credit else -abs(value)


def _strip_date_tokens(text: str) -> str:
    """Blank out date tokens so they cannot be misread as money.

    Without this, the year in a value date ("02-04-2025") matches the integer
    money pattern and becomes an amount of 2025 — a silently wrong figure, which
    is worse than failing to parse.

    Replacements are the same length as what they replace, so offsets stay valid
    against the original string.
    """
    return _LINE_DATE_RE.sub(lambda m: " " * len(m.group(0)), text)


def _clean_description(text: str) -> str:
    """Tidy the description slice of a statement line.

    Drops the trailing direction label and currency symbol that sit between the
    merchant name and the amount, so descriptions read "Paid to Yash pavan xerox"
    rather than "Paid to Yash pavan xerox DEBIT ₹".
    """
    out = text.strip(" -|\t:")
    out = re.sub(rf"\s*{_CURRENCY_SYMBOL}\s*$", "", out, flags=re.IGNORECASE)
    out = re.sub(
        r"\s+(?:debit|credit|debited|credited|dr|cr|withdrawal|deposit)\s*$",
        "",
        out,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s{2,}", " ", out).strip(" -|\t:")


def _split_line_at_date(line: str) -> tuple[str, str, str] | None:
    """Split a statement line into (leading_text, date_token, remainder).

    Returns None when the line has no date near its start. ``leading_text`` is
    whatever preceded the date — usually a serial number, occasionally a real
    part of the description.
    """
    for match in _LINE_DATE_RE.finditer(line):
        if match.start() > _MAX_DATE_OFFSET:
            break
        return line[: match.start()], match.group(1), line[match.end() :]
    return None


def _parse_pdf_text(text: str) -> list[dict]:
    """Heuristic line-by-line parser for text-based statement PDFs.

    Handles the layouts that show up in practice: a leading serial number before
    the date, a second (value) date after the first, and running balances
    alongside the transaction amount.
    """
    transactions: list[dict] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        split = _split_line_at_date(line)
        if split is None:
            continue
        lead, date_token, rest = split
        try:
            date = _parse_date(date_token)
        except ValueError:
            continue

        rest = rest.strip(" -|\t")
        # Statements with both a transaction date and a value date put the second
        # one here; drop it so it does not become part of the description.
        value_date = _LINE_DATE_RE.match(rest)
        if value_date:
            rest = rest[value_date.end() :].strip(" -|\t")

        # Keep whatever preceded the date only if it is not just a serial number.
        lead = lead.strip(" .-|\t")
        prefix = "" if (not lead or re.fullmatch(r"[\d\W]+", lead)) else lead

        # Match money against a date-free copy so year digits are never amounts,
        # but keep the offsets aligned by substituting equal-length spaces.
        money_source = _strip_date_tokens(rest)
        money = _money_matches(money_source)
        if not money:
            continue

        description = _clean_description(rest[: money[0].start()])
        if prefix:
            description = f"{prefix} {description}".strip()
        if not description:
            continue

        amount = _amount_from_line(money_source, description)
        if amount is None or amount == 0.0:
            continue
        transactions.append({"date": date, "description": description, "amount": amount})

    transactions.sort(key=lambda t: t["date"])
    return transactions


def _llm_extract_transactions(text: str) -> list[dict]:
    """Last-resort: ask the configured LLM to transcribe transactions to JSON.

    This only transcribes what is written in the document; all downstream
    financial figures (score, forecast, what-if) remain deterministic.
    """
    try:
        from agents import llm_client
    except Exception:  # noqa: BLE001
        return []
    if not llm_client.is_configured():
        return []

    snippet = text[:12000]
    prompt = (
        "You are a precise bank-statement parser. Extract EVERY transaction from "
        "the statement text below into a JSON array. Each element must be exactly:\n"
        '{"date": "YYYY-MM-DD", "description": "string", "amount": number}\n'
        "Rules: amount is NEGATIVE for debits/withdrawals/payments and POSITIVE "
        "for credits/deposits/salary. Do NOT include running balances as amounts. "
        "Copy figures exactly as printed; never invent values. Return ONLY the JSON "
        "array, nothing else.\n\nSTATEMENT TEXT:\n" + snippet
    )
    raw = llm_client.generate(prompt)
    if not raw or raw.startswith("[LLM error"):
        return []
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            date = _parse_date(item.get("date"))
            amount = float(item.get("amount"))
            desc = str(item.get("description", "")).strip()
        except (ValueError, TypeError):
            continue
        if desc:
            out.append({"date": date, "description": desc, "amount": amount})
    out.sort(key=lambda t: t["date"])
    return out


def _parse_pdf(content: bytes) -> list[dict]:
    """Parse a PDF statement fast-first: cheap text extraction and heuristic
    line parsing, then (only if that fails) expensive table detection, then an
    optional LLM fallback. The PDF is opened once and reused.
    """
    try:
        import pdfplumber
    except Exception as exc:  # noqa: BLE001
        raise IngestionError(
            "PDF support requires pdfplumber. Run: pip install pdfplumber"
        ) from exc

    started = time.perf_counter()
    text = ""
    df: pd.DataFrame | None = None
    page_count = 0
    table_count = 0
    table_columns: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            page_count = len(pdf.pages)
            # 1) FAST PATH: text extraction (cheap) + heuristic line parsing.
            text = _pdf_extract_text(pdf)
            if text.strip():
                txns = _parse_pdf_text(text)
                if len(txns) >= 2:
                    logger.info(
                        "PDF parsed via text in %.0fms (%d pages, %d txns)",
                        (time.perf_counter() - started) * 1000, page_count, len(txns),
                    )
                    return txns

            # 2) SLOW PATH: structured table detection — only when text failed.
            logger.info(
                "PDF text path insufficient after %.0fms; trying table detection",
                (time.perf_counter() - started) * 1000,
            )
            tables = _pdf_extract_tables(pdf)
            table_count = len(tables)
            df = _tables_to_df(tables)
            if df is None and tables:
                # Recorded for the error message so an unsupported layout can be
                # diagnosed from the message alone.
                table_columns = _cells(tables[0][0])[:12]
    except Exception as exc:  # noqa: BLE001
        raise IngestionError(f"Could not read the PDF: {exc}") from exc

    if df is not None:
        try:
            txns = _dataframe_to_transactions(df)
            logger.info(
                "PDF parsed via tables in %.0fms (%d txns)",
                (time.perf_counter() - started) * 1000, len(txns),
            )
            return txns
        except IngestionError as exc:
            logger.info("PDF table path rejected: %s", exc)

    # 3) LLM-assisted extraction for irregular layouts (network — last resort).
    if text.strip():
        txns = _llm_extract_transactions(text)
        if txns:
            logger.info(
                "PDF parsed via LLM in %.0fms (%d txns)",
                (time.perf_counter() - started) * 1000, len(txns),
            )
            return txns

        # Report what was actually seen — "unusual format" alone gives the user
        # nothing to act on.
        dated_lines = sum(
            1 for ln in text.splitlines() if _split_line_at_date(ln.strip())
        )
        details = [
            f"{page_count} page(s)",
            f"{len(text.splitlines())} text line(s)",
            f"{dated_lines} line(s) starting with a date",
            f"{table_count} table(s) detected",
        ]
        if table_columns:
            details.append("first table columns: " + ", ".join(table_columns))
        logger.warning("PDF parse failed — %s", "; ".join(details))
        raise IngestionError(
            "Couldn't find transactions in this PDF ("
            + "; ".join(details)
            + "). Statements need a date, a description and an amount per row. "
            "Export as CSV or Excel, or configure an LLM provider for smarter "
            "PDF extraction. Run `python tools/inspect_pdf.py <file.pdf>` in the "
            "backend folder to see exactly what was extracted."
        )

    raise IngestionError(
        f"No readable text found in the PDF ({page_count} page(s)) — it looks like "
        "a scanned image. Scanned statements need OCR; please upload a text-based "
        "PDF, CSV, or Excel file."
    )


# ---------- public entry points ----------
def parse_statement(content: bytes | str, filename: str | None = None) -> list[dict]:
    """Parse a statement of any supported format into clean transactions.

    Dispatches on the file extension; falls back to delimited-text parsing when
    the extension is unknown.
    """
    name = (filename or "").lower().strip()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""

    # PDF returns transactions directly (tables/text/LLM layered internally).
    if ext == "pdf":
        if isinstance(content, str):
            raise IngestionError("PDF must be uploaded as binary, not text.")
        return _parse_pdf(content)

    if ext in {"xlsx", "xlsm"}:
        df = _read_excel(content if isinstance(content, bytes) else content.encode(), "openpyxl")
    elif ext == "xls":
        df = _read_excel(content if isinstance(content, bytes) else content.encode(), "xlrd")
    elif ext == "ods":
        df = _read_excel(content if isinstance(content, bytes) else content.encode(), "odf")
    elif ext == "json":
        df = _read_json(content)
    elif ext in {"csv", "tsv", "txt", ""}:
        df = _read_delimited(content)
    else:
        # Unknown extension: best-effort as delimited text.
        df = _read_delimited(content)

    return _dataframe_to_transactions(df)


def parse_csv(content: bytes | str) -> list[dict]:
    """Backward-compatible CSV entry point (delegates to parse_statement)."""
    return parse_statement(content, filename="upload.csv")
