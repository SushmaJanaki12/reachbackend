"""Download Validation Report (PRD Sec. 12): row #, severity, issue type,
description, suggested fix -- row numbers point at the original uploaded
file (see parsing.py's row_number convention), not an internal index.
"""
import csv
import io

COLUMNS = ["Row", "Severity", "Issue Type", "Field", "Description", "Suggested Fix"]


def _rows(issues: list[dict]):
    for i in sorted(issues, key=lambda x: x["row_number"]):
        yield [i["row_number"], i["severity"], i["issue_type"], i["field"] or "",
               i["description"], i["suggested_fix"] or ""]


def to_csv(issues: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(COLUMNS)
    for row in _rows(issues):
        writer.writerow(row)
    return buf.getvalue().encode("utf-8-sig")


def to_xlsx(issues: list[dict]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Validation Report"
    ws.append(COLUMNS)
    for row in _rows(issues):
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
