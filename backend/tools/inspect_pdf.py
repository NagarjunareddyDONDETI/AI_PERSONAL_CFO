"""Show exactly what the ingestion layer sees in a PDF statement.

Run from the backend folder:

    .venv\\Scripts\\python.exe tools\\inspect_pdf.py "C:\\path\\to\\statement.pdf"

Prints the extracted text, which lines the line-parser recognises, the tables
pdfplumber finds, and the transactions each strategy produces. Nothing is
uploaded and nothing is written to disk — this reads the file and prints.

Use --full to print every line rather than the first 60.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import ingestion_agent as ing  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnose PDF statement parsing.")
    ap.add_argument("pdf", help="Path to the PDF statement")
    ap.add_argument("--full", action="store_true", help="Print all lines, not just a sample")
    ap.add_argument("--lines", type=int, default=60, help="Lines to show (default 60)")
    args = ap.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"No such file: {args.pdf}")
        return 2

    try:
        import pdfplumber
    except ImportError:
        print("pdfplumber is not installed. Run: pip install pdfplumber")
        return 2

    with open(args.pdf, "rb") as fh:
        content = fh.read()
    print(f"file: {args.pdf}  ({len(content):,} bytes)\n")

    import io

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        print(f"pages: {len(pdf.pages)}")
        text = ing._pdf_extract_text(pdf)
        lines = text.splitlines()
        print(f"extracted text: {len(text):,} chars, {len(lines)} lines")
        if not text.strip():
            print("\nNo text layer at all — this is a scanned image and needs OCR.")
            return 1

        limit = len(lines) if args.full else args.lines
        print(f"\n{'=' * 78}\nTEXT LINES (marked * when the parser finds a date)\n{'=' * 78}")
        recognised = 0
        for i, raw in enumerate(lines):
            line = raw.strip()
            hit = ing._split_line_at_date(line) is not None if line else False
            recognised += bool(hit)
            if i < limit:
                print(f"{'*' if hit else ' '} {i:4} | {line[:150]}")
        if len(lines) > limit:
            print(f"  ... {len(lines) - limit} more lines (use --full)")
        print(f"\nlines with a usable date: {recognised}")

        print(f"\n{'=' * 78}\nTABLES\n{'=' * 78}")
        tables = ing._pdf_extract_tables(pdf)
        print(f"tables detected: {len(tables)}")
        for i, table in enumerate(tables[:6]):
            cols = ing._cells(table[0]) if table else []
            found = ing._find_header(table)
            print(f"\n  table {i}: {len(table)} rows x {len(table[0]) if table else 0} cols")
            print(f"    row 0        : {cols[:10]}")
            print(f"    header found : {found[1][:10] if found else 'NO'}")
            for r in table[1:4]:
                print(f"    sample row   : {ing._cells(r)[:10]}")
        if len(tables) > 6:
            print(f"  ... {len(tables) - 6} more tables")

    print(f"\n{'=' * 78}\nRESULTS PER STRATEGY\n{'=' * 78}")

    txns = ing._parse_pdf_text(text)
    print(f"1. text/line parser : {len(txns)} transactions")
    for t in txns[:8]:
        print(f"     {t['date']}  {t['amount']:>12,.2f}  {t['description'][:60]}")

    df = ing._tables_to_df(tables)
    if df is None:
        print("2. table parser     : no usable transaction table found")
    else:
        print(f"2. table parser     : table {df.shape[0]}x{df.shape[1]}, columns={list(df.columns)}")
        try:
            rows = ing._dataframe_to_transactions(df)
            print(f"                      {len(rows)} transactions")
            for t in rows[:8]:
                print(f"     {t['date']}  {t['amount']:>12,.2f}  {t['description'][:60]}")
        except ing.IngestionError as exc:
            print(f"                      rejected: {exc}")

    try:
        from agents import llm_client

        configured = llm_client.is_configured()
    except Exception:  # noqa: BLE001
        configured = False
    print(f"3. LLM fallback     : {'available' if configured else 'not configured'}")

    print(f"\n{'=' * 78}")
    try:
        final = ing.parse_statement(content, os.path.basename(args.pdf))
        print(f"RESULT: parsed {len(final)} transactions "
              f"({final[0]['date']} to {final[-1]['date']})")
        return 0
    except ing.IngestionError as exc:
        print(f"RESULT: FAILED — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
