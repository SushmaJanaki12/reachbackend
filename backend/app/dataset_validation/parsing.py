"""CSV/XLSX/XLS parsing for the dataset-validation flow.

Row numbers are 1-based and include the header row (row 1), matching how a
user would count rows looking at the file in a spreadsheet app -- so the
first data row is row 2. This is what the error report (PRD Sec. 12) and
in-UI issue list point back to.
"""
import csv
import io


class ParseError(Exception):
    """User-facing parse failure -> surfaced as a 400."""


class ParseResult:
    def __init__(self, headers, rows, empty_rows_skipped, encoding_warning=False):
        self.headers = headers
        self.rows = rows
        self.empty_rows_skipped = empty_rows_skipped
        self.encoding_warning = encoding_warning


def _cell_to_str(val) -> str:
    # openpyxl/xlrd hand back number-formatted cells (phone numbers, zip
    # codes) as floats, so plain str() would append a spurious ".0".
    if val is None:
        return ""
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val)


def parse_file(filename: str, content_type: str | None, raw: bytes, max_rows: int) -> ParseResult:
    name = (filename or "").lower()

    if name.endswith(".csv") or content_type in ("text/csv", "application/vnd.ms-excel"):
        return _parse_csv(raw, max_rows)
    if name.endswith(".xlsx"):
        return _parse_xlsx(raw, max_rows)
    if name.endswith(".xls"):
        return _parse_xls(raw, max_rows)
    raise ParseError("Unsupported file type. Upload .csv, .xls or .xlsx")


def _parse_csv(raw: bytes, max_rows: int) -> ParseResult:
    text, encoding_warning = _decode(raw)
    reader = csv.reader(io.StringIO(text))
    try:
        headers = [h.strip() for h in next(reader)]
    except StopIteration:
        raise ParseError("No data rows found in the file")

    rows, skipped = [], 0
    for values in reader:
        row_number = reader.line_num
        row = {headers[i]: (values[i].strip() if i < len(values) and values[i] is not None else "")
               for i in range(len(headers)) if headers[i]}
        if any(v for v in row.values()):
            rows.append({"row_number": row_number, "values": row})
        else:
            skipped += 1
        if len(rows) > max_rows:
            raise ParseError(f"File exceeds the maximum of {max_rows} rows")
    return ParseResult(headers, rows, skipped, encoding_warning)


def _decode(raw: bytes) -> tuple[str, bool]:
    """utf-8 first, falling back to common legacy encodings. Returns
    (text, used_fallback) -- callers surface a warning when the fallback
    was needed, since it means the file wasn't UTF-8 as expected."""
    try:
        return raw.decode("utf-8-sig"), False
    except UnicodeDecodeError:
        for enc in ("cp1252", "latin-1"):
            try:
                return raw.decode(enc), True
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace"), True


def _parse_xlsx(raw: bytes, max_rows: int) -> ParseResult:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else "" for h in next(it, [])]
    if not any(headers):
        raise ParseError("No data rows found in the file")

    rows, skipped = [], 0
    for row_number, values in enumerate(it, start=2):
        if values is None:
            skipped += 1
            continue
        row = {}
        for i, h in enumerate(headers):
            if not h:
                continue
            val = values[i] if i < len(values) else None
            row[h] = _cell_to_str(val)
        if any(v for v in row.values()):
            rows.append({"row_number": row_number, "values": row})
        else:
            skipped += 1
        if len(rows) > max_rows:
            raise ParseError(f"File exceeds the maximum of {max_rows} rows")
    return ParseResult(headers, rows, skipped)


def _parse_xls(raw: bytes, max_rows: int) -> ParseResult:
    import xlrd

    wb = xlrd.open_workbook(file_contents=raw)
    ws = wb.sheet_by_index(0)
    if ws.nrows == 0:
        raise ParseError("No data rows found in the file")
    headers = [str(c).strip() if c is not None else "" for c in ws.row_values(0)]
    if not any(headers):
        raise ParseError("No data rows found in the file")

    rows, skipped = [], 0
    for r in range(1, ws.nrows):
        values = ws.row_values(r)
        row = {}
        for i, h in enumerate(headers):
            if not h:
                continue
            val = values[i] if i < len(values) else None
            row[h] = _cell_to_str(val)
        if any(v for v in row.values()):
            rows.append({"row_number": r + 1, "values": row})
        else:
            skipped += 1
        if len(rows) > max_rows:
            raise ParseError(f"File exceeds the maximum of {max_rows} rows")
    return ParseResult(headers, rows, skipped)
