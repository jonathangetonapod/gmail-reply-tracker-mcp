#!/usr/bin/env python3
"""Check what placeholders are actually in the Bison campaign."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

import asyncio
import requests
from leads import sheets_client
from config import Config

async def check_campaign():
    config = Config.from_env()

    # Get Michael Hernandez's API key
    workspaces = await asyncio.to_thread(
        sheets_client.load_bison_workspaces_from_sheet,
        config.lead_sheets_url,
        config.lead_sheets_gid_bison
    )

    michael = None
    for ws in workspaces:
        if "michael hernandez" in ws["client_name"].lower():
            michael = ws
            break

    if not michael:
        print("❌ Michael Hernandez not found")
        return

    print(f"✓ Found client: {michael['client_name']}")

    # Get campaign 127, sequence 107
    campaign_id = 127
    url = f"https://send.leadgenjay.com/api/campaigns/v1.1/{campaign_id}/sequences"
    headers = {"Authorization": f"Bearer {michael['api_key']}"}

    print(f"\nFetching sequences for campaign {campaign_id}...")
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    sequences = response.json()

    # Find sequence 107
    for seq in sequences.get('data', []):
        if seq['id'] == 107:
            print(f"\n✓ Found Sequence {seq['id']}: {seq['title']}")
            print("\nEmail Steps:")
            for step in seq.get('sequence_steps', []):
                print(f"\n  Step {step['order']}:")
                print(f"    Subject: {step['email_subject']}")
                print(f"    Body: {step['email_body']}")

                # Check for placeholders
                if '{{' in step['email_body'] or '{{' in step['email_subject']:
                    print("    ⚠️  Found Instantly-style placeholders ({{}})")
                if '{' in step['email_body'] and '{{' not in step['email_body']:
                    print("    ✓ Found Bison-style placeholders ({})")
            return

    print(f"\n❌ Sequence 107 not found in campaign {campaign_id}")

if __name__ == "__main__":
    asyncio.run(check_campaign())
