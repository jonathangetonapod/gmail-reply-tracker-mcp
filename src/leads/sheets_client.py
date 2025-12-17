"""
Google Sheets reading logic for workspace configurations.
"""

import csv
from io import StringIO
import requests


# Google Sheet configuration
DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1CNejGg-egkp28ItSRfW7F_CkBXgYevjzstJ1QlrAyAY/edit"
)
SHEET_GID_INSTANTLY = "928115249"  # Instantly workspaces tab
SHEET_GID_BISON = "1631680229"  # Bison workspaces tab


def load_workspaces_from_sheet(sheet_url: str = DEFAULT_SHEET_URL, gid: str = SHEET_GID_INSTANTLY):
    """
    Reads a public/view-only Google Sheet tab as CSV and returns workspace configs.

    Returns:
        [
            {"workspace_id": "ABC Corp", "api_key": "..."},
            {"workspace_id": "XYZ Ltd", "api_key": "..."},
            ...
        ]
    """
    # Normalize URL to the "base" without /edit...
    if "/edit" in sheet_url:
        base = sheet_url.split("/edit", 1)[0]
    else:
        base = sheet_url

    csv_url = f"{base}/export?format=csv&gid={gid}"
    print(f"[Sheets] Fetching workspace list from Google Sheet...")

    resp = requests.get(csv_url, timeout=30)
    resp.raise_for_status()

    text = resp.text
    reader = csv.reader(StringIO(text))
    rows = list(reader)

    workspaces = []
    for idx, row in enumerate(rows):
        if len(row) < 2:
            continue
        raw_wid = (row[0] or "").strip()
        raw_key = (row[1] or "").strip()
        raw_workspace_name = (row[2] or "").strip() if len(row) > 2 else ""  # Column C
        raw_client_name = (row[3] or "").strip() if len(row) > 3 else ""  # Column D

        # Skip empty
        if not raw_wid or not raw_key:
            continue

        # Heuristic to skip header row
        if idx == 0 and (
            "workspace" in raw_wid.lower()
            or "id" in raw_wid.lower()
            or "api" in raw_key.lower()
        ):
            continue

        # Prefer Column D (Client Name) for display, but keep both for searching
        display_name = raw_client_name or raw_workspace_name or raw_wid

        workspaces.append({
            "workspace_id": raw_wid,
            "api_key": raw_key,
            "client_name": display_name,  # For display (Column D > Column C > ID)
            "workspace_name": raw_workspace_name,  # Column C - for search
            "person_name": raw_client_name,  # Column D - for search
        })

    print(f"[Sheets] Loaded {len(workspaces)} workspaces")
    return workspaces


def load_bison_workspaces_from_sheet(sheet_url: str = DEFAULT_SHEET_URL, gid: str = SHEET_GID_BISON):
    """
    Reads Bison workspaces from Google Sheet tab.

    Bison sheet structure:
    - Column A: Client Name
    - Column B: API Key

    Returns:
        [
            {"client_name": "ABC Corp", "api_key": "..."},
            {"client_name": "XYZ Ltd", "api_key": "..."},
            ...
        ]
    """
    # Normalize URL
    if "/edit" in sheet_url:
        base = sheet_url.split("/edit", 1)[0]
    else:
        base = sheet_url

    csv_url = f"{base}/export?format=csv&gid={gid}"
    print(f"[Bison] Fetching workspace list from Google Sheet...")

    resp = requests.get(csv_url, timeout=30)
    resp.raise_for_status()

    text = resp.text
    reader = csv.reader(StringIO(text))
    rows = list(reader)

    workspaces = []
    for idx, row in enumerate(rows):
        if len(row) < 2:
            continue
        raw_name = (row[0] or "").strip()
        raw_key = (row[1] or "").strip()

        # Skip empty
        if not raw_name or not raw_key:
            continue

        # Skip header row
        if idx == 0 and (
            "client" in raw_name.lower() or
            "name" in raw_name.lower() or
            "api" in raw_key.lower()
        ):
            continue

        workspaces.append({
            "client_name": raw_name,
            "api_key": raw_key
        })

    print(f"[Bison] Loaded {len(workspaces)} workspaces")
    return workspaces


def load_instantly_workspaces_from_sheet(sheet_url: str = DEFAULT_SHEET_URL, gid: str = SHEET_GID_INSTANTLY):
    """
    Reads Instantly workspaces from Google Sheet tab.

    Instantly sheet structure:
    - Column A: Workspace ID (UUID)
    - Column B: API Key
    - Column C: Workspace Name
    - Column D: Client Name (Person Name)
    - Column E: Client Email
    - Column F: Action/Status

    Returns:
        [
            {
                "workspace_id": "...",
                "api_key": "...",
                "workspace_name": "Source 1 Parcel",
                "client_name": "Brian Bliss",
                "client_email": "brian@example.com",
                "action": "..."
            },
            ...
        ]
    """
    # Normalize URL
    if "/edit" in sheet_url:
        base = sheet_url.split("/edit", 1)[0]
    else:
        base = sheet_url

    csv_url = f"{base}/export?format=csv&gid={gid}"
    print(f"[Instantly] Fetching workspace list from Google Sheet...")

    resp = requests.get(csv_url, timeout=30)
    resp.raise_for_status()

    text = resp.text
    reader = csv.reader(StringIO(text))
    rows = list(reader)

    workspaces = []
    for idx, row in enumerate(rows):
        if len(row) < 2:
            continue

        # Read all columns
        raw_workspace_id = (row[0] or "").strip()  # Column A
        raw_api_key = (row[1] or "").strip()       # Column B
        raw_workspace_name = (row[2] or "").strip() if len(row) > 2 else ""  # Column C
        raw_client_name = (row[3] or "").strip() if len(row) > 3 else ""     # Column D
        raw_client_email = (row[4] or "").strip() if len(row) > 4 else ""    # Column E
        raw_action = (row[5] or "").strip() if len(row) > 5 else ""          # Column F

        # Skip empty
        if not raw_workspace_id or not raw_api_key:
            continue

        # Skip header row
        if idx == 0 and (
            "workspace" in raw_workspace_id.lower() or
            "id" in raw_workspace_id.lower() or
            "api" in raw_api_key.lower()
        ):
            continue

        # Use Client Name (Column D) if available, otherwise Workspace Name (Column C)
        display_name = raw_client_name or raw_workspace_name or raw_workspace_id

        workspaces.append({
            "workspace_id": raw_workspace_id,      # Column A
            "api_key": raw_api_key,                # Column B
            "workspace_name": raw_workspace_name,  # Column C
            "client_name": display_name,           # Column D (or fallback)
            "person_name": raw_client_name,        # Column D (original)
            "client_email": raw_client_email,      # Column E
            "action": raw_action,                  # Column F
        })

    print(f"[Instantly] Loaded {len(workspaces)} workspaces")
    return workspaces
