#!/usr/bin/env python3
"""Extract 51 hidden gem leads from Gmail analysis"""

import sys
import os
import json

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config import Config
from leads.interest_analyzer import find_missed_opportunities_for_client

# Load configuration
config = Config.from_env()

CLIENT_NAME = "Daniel Drynan"
DAYS_BACK = 180

def extract_hidden_gems():
    """Extract hidden gem emails from Gmail analysis"""
    print(f"🔍 Analyzing {DAYS_BACK} days of replies for {CLIENT_NAME}...")

    try:
        # Run analysis
        result = find_missed_opportunities_for_client(
            client_name=CLIENT_NAME,
            days_back=DAYS_BACK,
            platform="instantly"
        )

        # Parse result
        data = json.loads(result) if isinstance(result, str) else result

        if not data.get("success"):
            print(f"❌ Error: {data.get('error')}")
            sys.exit(1)

        hidden_gems = data.get("hidden_gems", [])
        print(f"\n✅ Found {len(hidden_gems)} hidden gems!")

        # Extract emails
        emails = []
        for gem in hidden_gems:
            email = gem.get("email")
            if email:
                emails.append(email)
                print(f"   - {email}")

        # Save to file for import
        output_file = "hidden_gems_emails.json"
        with open(output_file, "w") as f:
            json.dump({"emails": emails, "count": len(emails)}, f, indent=2)

        print(f"\n💾 Saved {len(emails)} emails to {output_file}")
        print(f"   Use these with add_hidden_gems.py")

        return emails

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    extract_hidden_gems()
