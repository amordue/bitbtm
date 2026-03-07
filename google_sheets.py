"""Google Sheets API client and robot registration data parser."""

import re
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Expected column header names (case-insensitive matching).
_COL_ROBOTEER_NAME = ("roboteer name",)
_COL_ROBOT_NAME = ("robot name",)
_COL_WEAPON_TYPE = ("weapon type",)
_COL_CONTACT_EMAIL = ("contact email", "email", "e-mail")
_COL_IMAGE_URL = ("image url", "robot image", "image", "upload image")


def extract_sheet_id(sheet_url: str) -> str:
    """Extract the Google Sheets spreadsheet ID from its URL."""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", sheet_url)
    if not match:
        raise ValueError(f"Could not extract spreadsheet ID from URL: {sheet_url}")
    return match.group(1)


def _build_service(access_token: str):
    """Build an authenticated Google Sheets API service."""
    creds = Credentials(token=access_token)
    return build("sheets", "v4", credentials=creds)


def _extract_formula_hyperlink(cell: dict) -> Optional[str]:
    """Return the target URL from a HYPERLINK formula when present."""
    formula = cell.get("userEnteredValue", {}).get("formulaValue")
    if not formula:
        return None
    match = re.match(r'=HYPERLINK\("([^"]+)"', formula, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip() or None
    return None


def _extract_cell_link(cell: dict) -> Optional[str]:
    """Return the first hyperlink target embedded in a Google Sheets cell."""
    direct_link = cell.get("hyperlink")
    if direct_link:
        return direct_link.strip() or None

    for run in cell.get("textFormatRuns", []):
        uri = run.get("format", {}).get("link", {}).get("uri")
        if uri:
            return uri.strip() or None

    for run in cell.get("chipRuns", []):
        chip = run.get("chip", {})
        rich_link = chip.get("richLinkProperties", {})
        uri = rich_link.get("uri")
        if uri:
            return uri.strip() or None

    return _extract_formula_hyperlink(cell)


def _extract_cell_value(cell: dict) -> str:
    """Prefer hyperlink targets over display text for link-backed cells."""
    link = _extract_cell_link(cell)
    if link:
        return link
    return cell.get("formattedValue", "").strip()


def fetch_sheet_rows(sheet_url: str, access_token: str) -> list[dict]:
    """
    Fetch all rows from the first sheet tab and return them as a list of dicts.
    The first row is treated as column headers.  Columns not in the expected set
    are preserved as-is under their original header name.
    """
    sheet_id = extract_sheet_id(sheet_url)
    service = _build_service(access_token)
    result = (
        service.spreadsheets()
        .get(spreadsheetId=sheet_id, ranges=["A1:ZZ"], includeGridData=True)
        .execute()
    )
    sheet_data = result.get("sheets", [])
    if not sheet_data:
        return []

    row_data = sheet_data[0].get("data", [{}])[0].get("rowData", [])
    if not row_data:
        return []

    header_cells = row_data[0].get("values", [])
    headers = [_extract_cell_value(cell) for cell in header_cells]
    indexed_headers = [
        (index, header.strip()) for index, header in enumerate(headers) if header.strip()
    ]
    if not indexed_headers:
        return []

    rows = []
    for row in row_data[1:]:
        cells = row.get("values", [])
        parsed_row = {}
        for index, header in indexed_headers:
            cell = cells[index] if index < len(cells) else {}
            parsed_row[header] = _extract_cell_value(cell)
        rows.append(parsed_row)
    return rows


def parse_robot_registrations(
    rows: list[dict],
    sheet_id: str,
) -> list[dict]:
    """
    Convert raw sheet rows into structured robot registration dicts.

    Each returned dict contains:
        roboteer_name   str   (required — row skipped if blank)
        robot_name      str   (required — row skipped if blank)
        weapon_type     str | None
        contact_email   str | None
        image_url       str | None
        sheet_row_id    str   (1-based row index as string, offset by header row)
    """
    def _find(row: dict, targets: tuple[str, ...]) -> Optional[str]:
        """Case-insensitive column lookup; returns stripped value or None."""
        for key, val in row.items():
            if key.strip().lower() in targets:
                return str(val).strip() or None
        return None

    registrations = []
    for i, row in enumerate(rows, start=2):  # row 1 = headers; data starts at 2
        roboteer_name = _find(row, _COL_ROBOTEER_NAME)
        robot_name = _find(row, _COL_ROBOT_NAME)
        if not roboteer_name or not robot_name:
            continue  # skip blank / incomplete rows
        registrations.append(
            {
                "roboteer_name": roboteer_name,
                "robot_name": robot_name,
                "weapon_type": _find(row, _COL_WEAPON_TYPE),
                "contact_email": _find(row, _COL_CONTACT_EMAIL),
                "image_url": _find(row, _COL_IMAGE_URL),
                "sheet_row_id": f"{sheet_id}:{i}",
            }
        )
    return registrations
