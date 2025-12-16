#!/usr/bin/env python3
"""Test OAuth that explicitly shows the URL."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import Config
from google_auth_oauthlib.flow import InstalledAppFlow

config = Config.from_env()

print("\n" + "="*70)
print("Gmail Calendar MCP - OAuth URL Test")
print("="*70 + "\n")

if not config.credentials_path.exists():
    print(f"✗ Credentials file not found: {config.credentials_path}")
    sys.exit(1)

print(f"✓ Found credentials: {config.credentials_path}\n")

# Create flow
flow = InstalledAppFlow.from_client_secrets_file(
    str(config.credentials_path),
    config.oauth_scopes
)

# Start the local server but don't auto-open browser
flow.run_local_server(
    port=0,
    open_browser=False,  # Don't auto-open
    authorization_prompt_message='\n✓ Authorization URL:\n\n{url}\n\nCopy and paste this URL into your browser to authorize.\n'
)

print("\n✓ Authorization successful!")
print(f"✓ Token saved to: {config.token_path}\n")
