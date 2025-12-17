#!/usr/bin/env python3
"""Check what's actually in the Google Sheets."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

import asyncio
from leads import sheets_client
from config import Config

async def check_sheets():
    config = Config.from_env()

    print("=" * 80)
    print("INSTANTLY CLIENTS")
    print("=" * 80)
    print(f"Sheets URL: {config.lead_sheets_url}")
    print(f"GID: {config.lead_sheets_gid_instantly}")
    print()

    # Load Instantly workspaces
    instantly_workspaces = await asyncio.to_thread(
        sheets_client.load_instantly_workspaces_from_sheet,
        config.lead_sheets_url,
        config.lead_sheets_gid_instantly
    )

    print(f"Found {len(instantly_workspaces)} Instantly workspaces:")
    for i, ws in enumerate(instantly_workspaces, 1):
        print(f"{i}. {ws.get('client_name', 'NO NAME')} - API Key: {ws.get('api_key', 'NO KEY')[:20]}...")

    print("\n" + "=" * 80)
    print("BISON CLIENTS")
    print("=" * 80)
    print(f"Sheets URL: {config.lead_sheets_url}")
    print(f"GID: {config.lead_sheets_gid_bison}")
    print()

    # Load Bison workspaces
    bison_workspaces = await asyncio.to_thread(
        sheets_client.load_bison_workspaces_from_sheet,
        config.lead_sheets_url,
        config.lead_sheets_gid_bison
    )

    print(f"Found {len(bison_workspaces)} Bison workspaces:")
    for i, ws in enumerate(bison_workspaces, 1):
        print(f"{i}. {ws.get('client_name', 'NO NAME')} - API Key: {ws.get('api_key', 'NO KEY')[:20]}...")

    print("\n" + "=" * 80)
    print("SEARCHING FOR 'BRIAN' OR 'BLISS' OR 'SOURCE' OR 'PARCEL'")
    print("=" * 80)

    search_terms = ['brian', 'bliss', 'source', 'parcel']

    print("\nIn Instantly:")
    for ws in instantly_workspaces:
        name = ws.get('client_name', '').lower()
        if any(term in name for term in search_terms):
            print(f"  ✓ FOUND: {ws['client_name']}")

    print("\nIn Bison:")
    for ws in bison_workspaces:
        name = ws.get('client_name', '').lower()
        if any(term in name for term in search_terms):
            print(f"  ✓ FOUND: {ws['client_name']}")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    asyncio.run(check_sheets())
