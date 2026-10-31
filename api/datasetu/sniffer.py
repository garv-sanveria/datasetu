"""Smart Sniffer module for DataSetu.

What this module does:
1. Ingests messy tabular data from local files (.csv, .tsv, .xlsx) or HTTP(S) URLs.
2. Detects character encoding (UTF-8, UTF-8-BOM, CP1252 / Windows-1252, Latin-1) using chardet.
3. Identifies and strips non-tabular title preambles (ministry titles, notes, comment banners).
4. Detects and repairs 2-row merged headers (forward-fills blank/merged parent cells and combines
   them with sub-headers).
5. Unrolls Excel merged cell ranges so every cell has its correct parent header text.
6. Loads the cleaned tabular data into an in-memory DuckDB table with `all_varchar=true` and
   produces a clean PyArrow Table for downstream normalization.

Why it exists:
Indian public data portals (data.gov.in, state portals, PFMS) contain thousands of files with
decorative preamble rows, merged headers, and Windows CP1252 character encodings (e.g. en-dash \x96).
Standard parsers (pandas.read_csv, standard duckdb) fail on these files or garble the columns.

How it connects to other modules:
- Takes a raw file path or URL.
- Returns a `SniffResult` containing the `pyarrow.Table` (all VARCHAR columns), cleaned CSV path,
  and metadata (encoding, delimiter, preamble rows stripped, header fixing status).
- The `SniffResult.table` is passed directly to `normalizer.normalize()` for Indian numeral parsing
  and LGD district entity resolution.
"""

from __future__ import annotations

import csv
import io
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

import chardet
import duckdb
import httpx
import openpyxl
import pyarrow as pa


@dataclass
class SniffResult:
    """Detailed result of the sniffing and ingestion stage."""

    table: pa.Table
    cleaned_path: Path
    cleaned_text: Optional[str]
    encoding: str
    delimiter: str
    header_row_index: int
    preamble_rows_stripped: int
    merged_header_fixed: bool
    columns: List[str]
    notes: List[str] = field(default_factory=list)
    etag: Optional[str] = None
    last_modified: Optional[str] = None


def detect_encoding(raw_bytes: bytes) -> Tuple[str, float]:
    """Detect text encoding from raw bytes, handling BOMs and legacy Indian portal encodings."""
    # Check byte-order marks first
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", 1.0
    if raw_bytes.startswith(b"\xff\xfe"):
        return "utf-16-le", 1.0
    if raw_bytes.startswith(b"\xfe\xff"):
        return "utf-16-be", 1.0

    # Inspect up to first 128KB with chardet
    sample = raw_bytes[:131072]
    detected = chardet.detect(sample)
    enc = (detected.get("encoding") or "utf-8").lower()
    conf = float(detected.get("confidence") or 0.0)

    # Common portal mapping: windows-1252 / iso-8859-1 often contains CP1252 chars (e.g. \x96 en-dash)
    if enc in ("windows-1252", "iso-8859-1", "iso-8859-2", "latin-1", "ascii"):
        return "cp1252", max(conf, 0.85)

    return enc, conf


def detect_delimiter(sample_lines: List[str]) -> str:
    """Detect delimiter (comma, tab, semicolon, pipe) using frequency and consistency."""
    candidates = [",", "\t", ";", "|"]
    non_empty = [line.strip() for line in sample_lines if line.strip()][:30]
    if not non_empty:
        return ","

    # Try csv.Sniffer first
    try:
        sample_text = "\n".join(non_empty)
        sniffed = csv.Sniffer().sniff(sample_text, delimiters=",\t;|")
        if sniffed.delimiter in candidates:
            return sniffed.delimiter
    except Exception:
        pass

    # Fallback to consistency scoring
    best_delim = ","
    best_score = -1.0
    for delim in candidates:
        counts = [line.count(delim) for line in non_empty]
        avg = sum(counts) / len(counts)
        if avg > 0:
            variance = sum((c - avg) ** 2 for c in counts) / len(counts)
            # Higher average count and lower variance gives highest score
            score = avg / (1.0 + variance)
            if score > best_score:
                best_score = score
                best_delim = delim

    return best_delim


def _is_preamble_row(row: List[str], max_cols: int) -> bool:
    """Check if a row is a non-tabular preamble row (banner, title, comment, or blank)."""
    non_empty = [c.strip() for c in row if c.strip()]
    if not non_empty:
        return True

    first_val = non_empty[0]
    # Check comment indicators
    if first_val.startswith(("#", "//", "--", "/*")):
        return True

    # Check if this row is a banner spanning merged columns (e.g. identical value repeated)
    if len(set(non_empty)) == 1 and len(row) > 1 and len(first_val) > 10:
        return True

    # Check if it has only 1 non-empty cell while the table has 3 or more columns
    if len(non_empty) <= 1 and max_cols >= 3:
        return True

    return False


def _combine_headers(parent_row: List[str], child_row: List[str]) -> List[str]:
    """Combine 2-row merged headers by forward-filling parents and pairing with child headers."""
    # Forward-fill parent row
    ff_parent: List[str] = []
    last_val = ""
    for cell in parent_row:
        val = cell.strip()
        if val:
            last_val = val
        ff_parent.append(last_val)

    # Pad child row to match length
    padded_child = child_row + [""] * (len(ff_parent) - len(child_row))

    combined: List[str] = []
    for parent, child in zip(ff_parent, padded_child):
        p = parent.strip()
        c = child.strip()

        if not p and not c:
            combined.append("column")
        elif not p:
            combined.append(c)
        elif not c:
            combined.append(p)
        elif p.lower() == c.lower():
            combined.append(c)
        elif p.lower() in c.lower():
            combined.append(c)
        elif c.lower() in p.lower():
            combined.append(p)
        else:
            combined.append(f"{p} - {c}")

    # Ensure uniqueness
    seen: dict[str, int] = {}
    unique_headers: List[str] = []
    for h in combined:
        base = h or "col"
        if base in seen:
            seen[base] += 1
            unique_headers.append(f"{base}_{seen[base]}")
        else:
            seen[base] = 0
            unique_headers.append(base)

    return unique_headers


def _read_xlsx(raw_bytes: bytes) -> Tuple[List[List[str]], List[str]]:
    """Parse an XLSX spreadsheet, resolving merged cell spans into uniform rows."""
    notes: List[str] = []
    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
    ws = wb.active
    if ws is None:
        raise ValueError("XLSX workbook has no active sheet")

    # Map merged cells to their top-left value
    merged_map: dict[Tuple[int, int], Any] = {}
    merged_count = len(ws.merged_cells.ranges)
    if merged_count > 0:
        notes.append(f"Unrolled {merged_count} merged cell ranges in Excel sheet '{ws.title}'")

    for rng in list(ws.merged_cells.ranges):
        top_val = ws.cell(row=rng.min_row, column=rng.min_col).value
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                merged_map[(r, c)] = top_val

    rows: List[List[str]] = []
    for r_idx, row in enumerate(ws.iter_rows(), start=1):
        row_vals: List[str] = []
        for c_idx, cell in enumerate(row, start=1):
            val = merged_map.get((r_idx, c_idx), cell.value)
            row_vals.append("" if val is None else str(val).strip())
        rows.append(row_vals)

    return rows, notes


def _read_csv_text(raw_bytes: bytes) -> Tuple[List[List[str]], str, str, List[str]]:
    """Detect encoding and delimiter, then parse raw CSV/TSV bytes into uniform rows."""
    notes: List[str] = []
    encoding, conf = detect_encoding(raw_bytes)
    notes.append(f"Detected character encoding '{encoding}' (confidence: {conf:.2f})")

    try:
        text = raw_bytes.decode(encoding)
    except UnicodeDecodeError:
        text = raw_bytes.decode("cp1252", errors="replace")
        encoding = "cp1252"
        notes.append("Fallback to CP1252 with character replacement")

    # Detect delimiter
    sample_lines = text.splitlines()[:50]
    delimiter = detect_delimiter(sample_lines)
    notes.append(f"Detected delimiter '{delimiter}'")

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [list(r) for r in reader]
    return rows, encoding, delimiter, notes


def sniff(source: Union[str, Path]) -> SniffResult:
    """Sniff, clean, and load a tabular dataset from a local path or HTTP(S) URL.

    Parameters
    ----------
    source : str or Path
        File path (.csv, .tsv, .xlsx) or HTTP/HTTPS URL.

    Returns
    -------
    SniffResult
        Object containing the parsed PyArrow table (all varchar), cleaned CSV path,
        and comprehensive sniffing metadata.
    """
    notes: List[str] = []
    etag: Optional[str] = None
    last_modified: Optional[str] = None

    source_str = str(source)
    is_url = source_str.startswith("http://") or source_str.startswith("https://")

    # 1. Fetch or read raw bytes
    if is_url:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(source_str)
            resp.raise_for_status()
            etag = resp.headers.get("etag")
            last_modified = resp.headers.get("last-modified")
            raw_bytes = resp.content
            notes.append(f"Fetched URL {source_str} ({len(raw_bytes)} bytes)")
        is_xlsx = (
            source_str.lower().endswith((".xlsx", ".xlsm", ".xltx"))
            or "spreadsheetml" in resp.headers.get("content-type", "").lower()
        )
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Dataset source file not found: {source}")
        raw_bytes = path.read_bytes()
        mtime = path.stat().st_mtime
        last_modified = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        is_xlsx = path.suffix.lower() in (".xlsx", ".xlsm", ".xltx")
        notes.append(f"Read local file {path.name} ({len(raw_bytes)} bytes)")

    # 2. Extract initial matrix of rows
    if is_xlsx:
        rows, xlsx_notes = _read_xlsx(raw_bytes)
        notes.extend(xlsx_notes)
        encoding = "binary/xlsx"
        delimiter = ","
    else:
        rows, encoding, delimiter, csv_notes = _read_csv_text(raw_bytes)
        notes.extend(csv_notes)

    if not rows:
        raise ValueError(f"Source {source} contains no data rows")

    # 3. Detect and strip preamble rows
    max_cols = max((len([c for c in r if c.strip()]) for r in rows[:25]), default=1)
    preamble_rows_stripped = 0
    while preamble_rows_stripped < len(rows) and _is_preamble_row(
        rows[preamble_rows_stripped], max_cols
    ):
        preamble_rows_stripped += 1

    if preamble_rows_stripped > 0:
        notes.append(f"Stripped {preamble_rows_stripped} preamble rows before table header")

    table_rows = rows[preamble_rows_stripped:]
    if not table_rows:
        raise ValueError(f"Source {source} has no tabular data after stripping preambles")

    header_row_index = preamble_rows_stripped

    # 4. Check for 2-row merged headers
    r0 = table_rows[0]
    r1 = table_rows[1] if len(table_rows) > 1 else None

    merged_header_fixed = False
    if r1 is not None and len(table_rows) > 2:
        # Check if r1 has numbers: if r1 contains numbers, it is data, not a sub-header
        has_numeric = any(
            c.replace(",", "").replace(".", "").replace("-", "").isdigit()
            for c in r1
            if c.strip()
        )
        # Check if r0 has blanks or if it's an unrolled XLSX with duplicate parent headers
        has_gaps = any(not c.strip() for c in r0)
        has_duplicates = len(set(c for c in r0 if c.strip())) < len([c for c in r0 if c.strip()])

        if not has_numeric and (has_gaps or has_duplicates):
            merged_header_fixed = True
            final_headers = _combine_headers(r0, r1)
            data_rows = table_rows[2:]
            notes.append(f"Repaired 2-row merged header into {len(final_headers)} columns")
        else:
            final_headers = [c.strip() or f"col_{i}" for i, c in enumerate(r0)]
            data_rows = table_rows[1:]
    else:
        final_headers = [c.strip() or f"col_{i}" for i, c in enumerate(r0)]
        data_rows = table_rows[1:]

    # Remove completely empty trailing rows
    while data_rows and not any(c.strip() for c in data_rows[-1]):
        data_rows.pop()

    num_cols = len(final_headers)

    # 5. Write cleaned data to a temporary CSV for DuckDB
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="") as tmp:
        writer = csv.writer(tmp)
        writer.writerow(final_headers)
        for r in data_rows:
            padded = (r + [""] * num_cols)[:num_cols]
            writer.writerow(padded)
        cleaned_path = Path(tmp.name)

    # 6. Load into DuckDB with all_varchar=True so downstream normalizer controls typing
    con = duckdb.connect()
    try:
        # Escape path for SQL query
        safe_path = str(cleaned_path).replace("'", "''")
        tbl = con.execute(
            f"SELECT * FROM read_csv('{safe_path}', all_varchar=true, auto_detect=true)"
        ).fetch_arrow_table()
    finally:
        con.close()

    # Capture preview of cleaned text (first 50 lines)
    preview_lines = [",".join(final_headers)]
    for r in data_rows[:49]:
        preview_lines.append(",".join(r))
    cleaned_text = "\n".join(preview_lines)

    notes.append(f"Successfully loaded {len(tbl):,} rows across {len(final_headers)} columns into Arrow table")

    return SniffResult(
        table=tbl,
        cleaned_path=cleaned_path,
        cleaned_text=cleaned_text,
        encoding=encoding,
        delimiter=delimiter,
        header_row_index=header_row_index,
        preamble_rows_stripped=preamble_rows_stripped,
        merged_header_fixed=merged_header_fixed,
        columns=final_headers,
        notes=notes,
        etag=etag,
        last_modified=last_modified,
    )
