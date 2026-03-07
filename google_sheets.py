"""Google Sheets API client and robot registration data parser."""

import re
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Expected column header names (case-insensitive matching).
_COL_ROBOTEER_NAME = "roboteer name"
_COL_ROBOT_NAME = "robot name"
_COL_WEAPON_TYPE = "weapon type"
_COL_CONTACT_EMAIL = "contact email"
_COL_IMAGE_URL = "image url"


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
        .values()
        .get(spreadsheetId=sheet_id, range="A1:ZZ")
        .execute()
    )
    values = result.get("values", [])
    if not values:
        return []

    headers = [h.strip() for h in values[0]]
    rows = []
    for raw_row in values[1:]:
        # Pad short rows so zip works correctly.
        padded = raw_row + [""] * (len(headers) - len(raw_row))
        rows.append(dict(zip(headers, padded)))
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
    def _find(row: dict, target: str) -> Optional[str]:
        """Case-insensitive column lookup; returns stripped value or None."""
        for key, val in row.items():
            if key.strip().lower() == target:
                return val.strip() or None
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
