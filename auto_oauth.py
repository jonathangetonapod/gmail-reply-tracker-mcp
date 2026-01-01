#!/usr/bin/env python3
"""Automatic OAuth that runs without user interaction."""

import os
import sys
import socket
from pathlib import Path

# Fix for Google OAuth adding 'openid' scope causing oauthlib validation errors
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import Config
from google_auth_oauthlib.flow import InstalledAppFlow


def find_free_port(start_port=8080, max_attempts=10):
    """Find a free port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        try:
            # Try to bind to the port
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('localhost', port))
            sock.close()
            return port
        except OSError:
            # Port is in use, try next one
            continue
    raise RuntimeError(f"No free ports found in range {start_port}-{start_port + max_attempts - 1}")

config = Config.from_env()

print("\n" + "="*70)
print("Gmail Calendar MCP - OAuth Authorization")
print("="*70 + "\n")

if not config.credentials_path.exists():
    print(f"✗ Credentials file not found: {config.credentials_path}")
    sys.exit(1)

print(f"✓ Found credentials: {config.credentials_path}\n")

# Find a free port
try:
    port = find_free_port(start_port=8080, max_attempts=10)
    print(f"✓ Found available port: {port}\n")
except RuntimeError as e:
    print(f"✗ {e}")
    print("\nTry closing other applications that might be using ports 8080-8089")
    sys.exit(1)

# Create flow
flow = InstalledAppFlow.from_client_secrets_file(
    str(config.credentials_path),
    config.oauth_scopes
)

print(f"Starting local server on port {port}...")
print("Browser will open automatically for authorization.")
print()

# Run local server
try:
    credentials = flow.run_local_server(
        port=port,
        open_browser=True,
        authorization_prompt_message='Please visit this URL: {url}',
        success_message='✓ Authorization successful! You can close this window.'
    )

    # Save token
    config.token_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config.token_path, 'w') as f:
        f.write(credentials.to_json())

    print("\n" + "="*70)
    print("✓ AUTHORIZATION SUCCESSFUL!")
    print("="*70)
    print(f"\n✓ Token saved to: {config.token_path}\n")
    print("You can now use the MCP server with Claude Desktop.\n")

except Exception as e:
    print(f"\n✗ Authorization failed: {e}\n")
    import traceback
    traceback.print_exc()
    sys.exit(1)
