#!/usr/bin/env python3
"""
Debug script to find client name and test find_missed_opportunities.
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Load environment from .env file
from dotenv import load_dotenv
load_dotenv()

from leads.sheets_client import load_bison_workspaces_from_sheet, load_workspaces_from_sheet

# Get config values from environment
lead_sheets_url = os.getenv("LEAD_SHEETS_URL")
lead_sheets_gid_bison = os.getenv("LEAD_SHEETS_GID_BISON")
lead_sheets_gid_instantly = os.getenv("LEAD_SHEETS_GID_INSTANTLY")

if not all([lead_sheets_url, lead_sheets_gid_bison, lead_sheets_gid_instantly]):
    print("❌ Error: Missing environment variables!")
    print(f"   LEAD_SHEETS_URL: {'✓' if lead_sheets_url else '✗'}")
    print(f"   LEAD_SHEETS_GID_BISON: {'✓' if lead_sheets_gid_bison else '✗'}")
    print(f"   LEAD_SHEETS_GID_INSTANTLY: {'✓' if lead_sheets_gid_instantly else '✗'}")
    sys.exit(1)

print("=" * 80)
print("CLIENT SEARCH DEBUG TOOL")
print("=" * 80)

# Load workspaces
print("\n1. Loading Bison workspaces...")
bison_workspaces = load_bison_workspaces_from_sheet(lead_sheets_url, lead_sheets_gid_bison)
print(f"   ✓ Loaded {len(bison_workspaces)} Bison clients")

print("\n2. Loading Instantly workspaces...")
instantly_workspaces = load_workspaces_from_sheet(lead_sheets_url, gid=lead_sheets_gid_instantly)
print(f"   ✓ Loaded {len(instantly_workspaces)} Instantly clients")

# Search term
search_terms = ["james", "mccoy", "mc coy"]

print("\n3. Searching for clients matching:", search_terms)
print("=" * 80)

print("\n📋 BISON MATCHES:")
bison_matches = []
for ws in bison_workspaces:
    name = ws.get('client_name', '').lower()
    if any(term in name for term in search_terms):
        bison_matches.append(ws['client_name'])
        print(f"   ✓ {ws['client_name']}")

print(f"\n   Total Bison matches: {len(bison_matches)}")

print("\n📋 INSTANTLY MATCHES:")
instantly_matches = []
for ws in instantly_workspaces:
    name = ws.get('client_name', '').lower()
    if any(term in name for term in search_terms):
        instantly_matches.append(ws['client_name'])
        print(f"   ✓ {ws['client_name']}")

print(f"\n   Total Instantly matches: {len(instantly_matches)}")

if not bison_matches and not instantly_matches:
    print("\n❌ No matches found!")
    print("\nShowing first 20 Bison clients:")
    for i, ws in enumerate(bison_workspaces[:20], 1):
        print(f"   {i}. {ws['client_name']}")

    print("\nShowing first 20 Instantly clients:")
    for i, ws in enumerate(instantly_workspaces[:20], 1):
        print(f"   {i}. {ws['client_name']}")

print("\n" + "=" * 80)
