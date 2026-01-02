#!/usr/bin/env python3
"""Add 51 hidden gem leads to Daniel Drynan's Instantly campaign"""

import sys
import os
import json

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config import Config
from leads.sheets_client import load_instantly_workspaces_from_sheet
from leads.instantly_client import add_leads_to_campaign
from rapidfuzz import process, fuzz

# Load configuration
config = Config.from_env()

# Campaign details
CLIENT_NAME = "Daniel Drynan"
CAMPAIGN_ID = "be402f34-2e51-4c6a-9830-d8b3f89d55f7"  # Upgrade & Save_v2

# 51 Hidden Gem Leads
# TODO: Add all 51 email addresses here
HIDDEN_GEM_EMAILS = [
    "annette@revivery.co",
    "hello@mvmthouseindy.com",  # Vanessa
    "marybeth@dripyogastudio.com",
    "carlos@salt360float.com",  # GOLD - VA/implementation opportunity
    "janel@purephoenix.com",
    "jocelyn@theformulaxmeredith.com",
    "smarton@f45training.com",  # Skye Marton
    "niccole@kalofitness.com",
    "greg@impoweredfitness.com",
    "john@gillhamfitness.com",
    "ashley@aumintegralwellness.com",
    "john@thrivepersonaltrainer.com",
    "pete@capitalcryo.com",
    "louisa@shantihouse.co",
    "derek@itsplenty.com",
    # Add remaining 36 emails below...
]

def find_client_workspace(client_name: str):
    """Find workspace for client using fuzzy matching"""
    workspaces = load_instantly_workspaces_from_sheet(config.lead_sheets_url, int(config.lead_sheets_gid_instantly))
    workspace_names = [w["client_name"] for w in workspaces]

    result = process.extractOne(
        client_name,
        workspace_names,
        scorer=fuzz.WRatio,
        score_cutoff=60
    )

    if not result:
        print(f"❌ Client '{client_name}' not found")
        return None

    matched_name, score, index = result
    workspace = workspaces[index]
    print(f"✓ Matched '{client_name}' to '{matched_name}' (score: {score}%)")
    return workspace

def add_hidden_gems():
    """Add all hidden gem leads to campaign"""
    print(f"🚀 Adding {len(HIDDEN_GEM_EMAILS)} hidden gem leads to campaign...")

    # Find client workspace
    workspace = find_client_workspace(CLIENT_NAME)
    if not workspace:
        sys.exit(1)

    # Prepare leads data
    leads = [{"email": email} for email in HIDDEN_GEM_EMAILS]

    # Add leads to campaign
    try:
        result = add_leads_to_campaign(
            api_key=workspace["api_key"],
            campaign_id=CAMPAIGN_ID,
            leads=leads,
            skip_if_in_workspace=True  # Skip duplicates
        )

        print(f"\n✅ Success!")
        print(f"   Added: {len(result.get('leads', []))}")
        print(f"   Skipped: {result.get('skipped', 0)} (duplicates)")
        print(f"   Total attempted: {len(leads)}")

        # Show added leads
        if result.get('leads'):
            print(f"\n📧 Added leads:")
            for lead in result['leads'][:10]:  # Show first 10
                print(f"   - {lead.get('email')}")
            if len(result['leads']) > 10:
                print(f"   ... and {len(result['leads']) - 10} more")

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    add_hidden_gems()
