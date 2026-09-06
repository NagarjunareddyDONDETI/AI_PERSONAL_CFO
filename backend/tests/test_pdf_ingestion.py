"""PDF statement parsing: the text/line parser and the table assembler.

These exercise the parsing logic on realistic layouts directly, with no PDF
generation involved, so they stay fast and need no extra dependencies.

Several cases are regressions for layouts that used to fail outright: a leading
serial number, a second (value) date column, and a first detected table that is
the account-summary box rather than the transactions.
"""
from __future__ import annotations

import pytest

from agents.ingestion_agent import (
    IngestionError,
    _dataframe_to_transactions,
    _parse_pdf_text,
    _split_line_at_date,
    _strip_date_tokens,
    _tables_to_df,
)


# ---------- line splitting ----------
@pytest.mark.parametrize(
    "line,expected_date",
    [
        ("01-04-2025 UPI-SWIGGY 450.00 12,345.67", "01-04-2025"),
        ("2025-04-01 UPI-SWIGGY 450.00", "2025-04-01"),
        ("1/4/25 UPI-SWIGGY 450.00", "1/4/25"),
        ("01.04.2025 UPI-SWIGGY 450.00", "01.04.2025"),
        ("01-Apr-2025 UPI-SWIGGY 450.00", "01-Apr-2025"),
        ("01 Apr 2025 UPI-SWIGGY 450.00", "01 Apr 2025"),
        # Leading serial number — previously dropped every such row.
        ("1 01-04-2025 UPI-SWIGGY 450.00", "01-04-2025"),
        ("12.  01-04-2025  UPI-SWIGGY  450.00", "01-04-2025"),
    ],
)
def test_dates_are_found_despite_leading_tokens(line, expected_date):
    split = _split_line_at_date(line)
    assert split is not None, f"no date found in {line!r}"
    assert split[1] == expected_date


@pytest.mark.parametrize(
    "line",
    [
        "",
        "Statement of Account",
        "Account Number 1234567890123456",
        "Page 1 of 4",
        "IFSC HDFC0001234 MICR 400240123",
    ],
)
def test_non_transaction_lines_are_not_treated_as_dated(line):
    assert _split_line_at_date(line) is None


def test_date_tokens_are_blanked_without_shifting_offsets():
    line = "01-04-2025 SALARY 50,000.00"
    stripped = _strip_date_tokens(line)
    assert len(stripped) == len(line), "offsets would shift"
    assert "2025" not in stripped
    assert "50,000.00" in stripped


# ---------- the line parser on real-world layouts ----------
def test_simple_statement():
    text = """
Statement of Account
Date Description Amount Balance
01-04-2025 UPI-SWIGGY-ORDER 450.00 49,550.00
02-04-2025 SALARY CREDIT APRIL 50,000.00 99,550.00
05-04-2025 RENT PAYMENT 15,000.00 84,550.00
"""
    txns = _parse_pdf_text(text)
    assert len(txns) == 3
    assert txns[0] == {
        "date": "2025-04-01",
        "description": "UPI-SWIGGY-ORDER",
        "amount": -450.0,
    }
    # "SALARY" is a credit hint, so it must come through positive.
    assert txns[1]["amount"] == 50000.0
    assert txns[2]["amount"] == -15000.0


def test_leading_serial_number_layout():
    """Regression: a serial-number column used to drop every row."""
    text = """
Sl Date Particulars Amount Balance
1 01-04-2025 UPI-SWIGGY-ORDER 450.00 49,550.00
2 02-04-2025 SALARY CREDIT 50,000.00 99,550.00
3 05-04-2025 AMAZON PURCHASE 1,250.50 98,299.50
"""
    txns = _parse_pdf_text(text)
    assert len(txns) == 3
    assert txns[0]["description"] == "UPI-SWIGGY-ORDER"
    assert txns[0]["amount"] == -450.0
    assert txns[2]["amount"] == -1250.5


def test_transaction_and_value_date_layout():
    """Regression: the value date's year used to be read as the amount."""
    text = """
Txn Date Value Date Description Amount Balance
01-04-2025 02-04-2025 UPI-SWIGGY-ORDER 450.00 49,550.00
03-04-2025 03-04-2025 SALARY CREDIT 50,000.00 99,550.00
"""
    txns = _parse_pdf_text(text)
    assert len(txns) == 2
    assert txns[0]["date"] == "2025-04-01"
    assert txns[0]["amount"] == -450.0, "value-date year leaked into the amount"
    assert "2025" not in txns[0]["description"]
    assert txns[0]["description"] == "UPI-SWIGGY-ORDER"


def test_debit_credit_markers_win_over_balance():
    text = """
01-04-2025 ATM WITHDRAWAL 2,000.00 Dr 47,550.00
02-04-2025 NEFT INWARD 8,500.00 Cr 56,050.00
"""
    txns = _parse_pdf_text(text)
    assert [t["amount"] for t in txns] == [-2000.0, 8500.0]


def test_credit_hints_set_the_sign():
    text = """
01-04-2025 GROCERY STORE 1,200.00 10,000.00
02-04-2025 REFUND FROM AMAZON 1,200.00 11,200.00
"""
    txns = _parse_pdf_text(text)
    assert txns[0]["amount"] == -1200.0
    assert txns[1]["amount"] == 1200.0


def test_header_and_noise_lines_are_ignored():
    text = """
HDFC BANK LTD
Statement for account 50100123456789
Period 01-04-2025 to 30-04-2025
Page 1 of 2
Date Narration Withdrawal Deposit Balance
01-04-2025 UPI-SWIGGY 450.00 49,550.00
"""
    txns = _parse_pdf_text(text)
    # The period line has dates but no money after them, so it is skipped.
    assert len(txns) == 1
    assert txns[0]["description"] == "UPI-SWIGGY"


# ---------- table assembly ----------
def test_summary_box_before_the_transaction_table():
    """Regression: the first detected table is usually the account summary, and
    using its first row as the header broke the whole table path."""
    summary = [
        ["Account Holder", "D NAGARJUNA"],
        ["Account Number", "50100123456789"],
        ["Branch", "BANGALORE"],
    ]
    transactions = [
        ["Date", "Description", "Amount", "Balance"],
        ["01-04-2025", "UPI-SWIGGY", "-450.00", "49,550.00"],
        ["02-04-2025", "SALARY", "50000.00", "99,550.00"],
    ]
    df = _tables_to_df([summary, transactions])
    assert df is not None, "summary box still shadows the transaction table"
    assert list(df.columns) == ["Date", "Description", "Amount", "Balance"]
    txns = _dataframe_to_transactions(df)
    assert len(txns) == 2
    assert txns[0]["amount"] == -450.0


def test_two_row_header_is_merged():
    table = [
        ["Txn", "", "Withdrawal", "Deposit"],
        ["Date", "Narration", "Amt", "Amt"],
        ["01-04-2025", "UPI-SWIGGY", "450.00", ""],
        ["02-04-2025", "SALARY", "", "50000.00"],
    ]
    df = _tables_to_df([table])
    assert df is not None
    txns = _dataframe_to_transactions(df)
    assert [t["amount"] for t in txns] == [-450.0, 50000.0]


def test_continuation_table_on_a_later_page():
    page1 = [
        ["Date", "Description", "Amount"],
        ["01-04-2025", "UPI-SWIGGY", "-450.00"],
    ]
    page2 = [
        ["05-04-2025", "AMAZON", "-1250.00"],
        ["07-04-2025", "SALARY", "50000.00"],
    ]
    df = _tables_to_df([page1, page2])
    assert df is not None
    assert len(_dataframe_to_transactions(df)) == 3


def test_repeated_header_row_is_dropped():
    page1 = [
        ["Date", "Description", "Amount"],
        ["01-04-2025", "UPI-SWIGGY", "-450.00"],
    ]
    page2 = [
        ["Date", "Description", "Amount"],
        ["05-04-2025", "AMAZON", "-1250.00"],
    ]
    df = _tables_to_df([page1, page2])
    txns = _dataframe_to_transactions(df)
    assert len(txns) == 2, "the repeated header became a transaction row"


def test_tables_without_a_transaction_header_are_rejected():
    assert _tables_to_df([[["Name", "Value"], ["Holder", "Someone"]]]) is None
    assert _tables_to_df([]) is None
    assert _tables_to_df([[]]) is None


def test_blank_column_headings_get_placeholders():
    table = [
        ["Date", "", "Amount"],
        ["01-04-2025", "UPI-SWIGGY", "-450.00"],
        ["02-04-2025", "AMAZON", "-100.00"],
    ]
    df = _tables_to_df([table])
    assert df is not None
    assert "col_1" in df.columns
    # No description column, so mapping must fail loudly rather than guess.
    with pytest.raises(IngestionError):
        _dataframe_to_transactions(df)


# ---------- UPI / wallet statements (PhonePe, GPay, Paytm) ----------
# These carry no balance column, print amounts as "₹8" with no decimals or
# grouping, state the direction as a word, and embed 10-digit phone numbers in
# the description. Found against a real 21-page PhonePe statement where the
# parser silently kept only 72 of 161 rows and invented a ₹9,848,369,396
# transaction out of a phone number.
RUPEE = "\u20b9"


@pytest.mark.parametrize(
    "line,expected_amount,expected_desc",
    [
        # Small amounts with no decimals and no grouping — previously dropped.
        (f"Sep 01, 2026 Paid to Yash pavan xerox DEBIT {RUPEE}8", -8.0,
         "Paid to Yash pavan xerox"),
        (f"Aug 27, 2026 Paid to RAJKUMAR PANIPURI DEBIT {RUPEE}60", -60.0,
         "Paid to RAJKUMAR PANIPURI"),
        (f"Aug 28, 2026 Received from Satyanarayana@frnd CREDIT {RUPEE}80", 80.0,
         "Received from Satyanarayana@frnd"),
        # Grouped amount still works.
        (f"Aug 04, 2026 Paid to BASAMSETTI KEERTHINA DEBIT {RUPEE}4,000", -4000.0,
         "Paid to BASAMSETTI KEERTHINA"),
        # Decimal amount still works.
        (f"Aug 04, 2026 Paid to VIJETHA SUPERMARKETS DEBIT {RUPEE}34.65", -34.65,
         "Paid to VIJETHA SUPERMARKETS"),
    ],
)
def test_upi_statement_rows(line, expected_amount, expected_desc):
    txns = _parse_pdf_text(line)
    assert len(txns) == 1, f"row was dropped: {line!r}"
    assert txns[0]["amount"] == expected_amount
    # The direction label and currency symbol are stripped from the description.
    assert txns[0]["description"] == expected_desc


@pytest.mark.parametrize(
    "line,expected",
    [
        (f"Aug 03, 2026 Received from 9848369396 CREDIT {RUPEE}400", 400.0),
        (f"Aug 26, 2026 Mobile recharged 7893901410 DEBIT {RUPEE}302", -302.0),
    ],
)
def test_phone_number_in_description_is_not_an_amount(line, expected):
    """Regression: a 10-digit phone number was parsed as the amount."""
    txns = _parse_pdf_text(line)
    assert len(txns) == 1
    assert txns[0]["amount"] == expected, "phone number leaked into the amount"


def test_direction_word_beats_description_guessing():
    """"DEBIT"/"CREDIT" in the row is authoritative over keyword hints."""
    # "Refund" is a credit hint, but the row explicitly says DEBIT.
    txns = _parse_pdf_text(f"Aug 10, 2026 Refund adjustment DEBIT {RUPEE}250")
    assert txns[0]["amount"] == -250.0
    txns = _parse_pdf_text(f"Aug 10, 2026 Paid order reversal CREDIT {RUPEE}250")
    assert txns[0]["amount"] == 250.0


@pytest.mark.parametrize(
    "digits", ["9848369396", "12345678901", "879297790347"]
)
def test_long_digit_runs_are_never_amounts(digits):
    """UTR, account and phone numbers must not be read as money."""
    txns = _parse_pdf_text(f"Aug 03, 2026 Transfer ref {digits}")
    assert txns == [], f"{digits} was accepted as an amount"


def test_currency_anchored_amount_wins_over_an_earlier_bare_number():
    line = f"Aug 03, 2026 Paid to Store 123456 order DEBIT {RUPEE}75"
    txns = _parse_pdf_text(line)
    assert txns[0]["amount"] == -75.0, "an earlier bare number won"


def test_statement_period_header_is_not_a_transaction():
    """"02 Aug, 2026 - 01 Sep, 2026" has dates but no amount."""
    assert _parse_pdf_text("02 Aug, 2026 - 01 Sep, 2026") == []


def test_balance_column_still_wins_over_currency_when_absent():
    """Bank rows without a currency symbol keep the old [amount, balance] rule."""
    txns = _parse_pdf_text("01-04-2025 UPI-SWIGGY-ORDER 450.00 49,550.00")
    assert txns[0]["amount"] == -450.0
