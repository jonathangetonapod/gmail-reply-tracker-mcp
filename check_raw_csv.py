#!/usr/bin/env python3
"""Check the raw CSV structure of the Google Sheets."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

import csv
from io import StringIO
import requests
from config import Config

def check_sheet_structure():
    config = Config.from_env()

    # Fetch Instantly sheet
    base = config.lead_sheets_url.split("/edit", 1)[0]
    instantly_csv_url = f"{base}/export?format=csv&gid={config.lead_sheets_gid_instantly}"

    print("=" * 80)
    print("INSTANTLY SHEET STRUCTURE")
    print("=" * 80)
    print(f"URL: {instantly_csv_url}")
    print()

    resp = requests.get(instantly_csv_url, timeout=30)
    resp.raise_for_status()

    reader = csv.reader(StringIO(resp.text))
    rows = list(reader)

    print(f"Total rows: {len(rows)}")
    print()
    print("First 5 rows:")
    print("-" * 80)
    for i, row in enumerate(rows[:5]):
        print(f"Row {i}: {len(row)} columns")
        for j, cell in enumerate(row[:6]):  # Show first 6 columns
            print(f"  Column {chr(65+j)} ({j}): {cell[:50] if cell else '(empty)'}...")
        print()

    # Search for Brian
    print("=" * 80)
    print("SEARCHING FOR 'BRIAN' OR 'BLISS' IN ALL COLUMNS")
    print("=" * 80)
    search_terms = ['brian', 'bliss', 'source', 'parcel']

    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            cell_lower = cell.lower() if cell else ''
            if any(term in cell_lower for term in search_terms):
                print(f"✓ FOUND at Row {i}, Column {chr(65+j)} ({j}): {cell}")

if __name__ == "__main__":
    check_sheet_structure()
