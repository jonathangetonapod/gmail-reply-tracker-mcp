#!/usr/bin/env python3
"""
Interactive OAuth 2.0 setup script for Gmail Reply Tracker MCP Server.

This script helps users authenticate with Gmail API for the first time.
"""

import sys
from pathlib import Path

# Add src to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import Config
from auth import GmailAuthManager


def print_header():
    """Print welcome header."""
    print("=" * 70)
    print("Gmail Reply Tracker - OAuth 2.0 Setup")
    print("=" * 70)
    print()


def print_step(step_num: int, title: str):
    """Print step header."""
    print(f"\nStep {step_num}: {title}")
    print("-" * 70)


def check_credentials_file(config: Config) -> bool:
    """
    Check if credentials.json exists.

    Args:
        config: Configuration object

    Returns:
        True if credentials file exists, False otherwise
    """
    if config.credentials_path.exists():
        print(f"✓ Found credentials file: {config.credentials_path}")
        return True
    else:
        print(f"✗ Credentials file not found: {config.credentials_path}")
        print()
        print("Please follow these steps to get your credentials:")
        print()
        print("1. Go to: https://console.cloud.google.com")
        print("2. Create a new project (or select existing)")
        print("3. Enable Gmail API:")
        print("   - Go to 'APIs & Services' > 'Library'")
        print("   - Search for 'Gmail API'")
        print("   - Click 'Enable'")
        print("4. Create OAuth 2.0 credentials:")
        print("   - Go to 'APIs & Services' > 'Credentials'")
        print("   - Click '+ CREATE CREDENTIALS' > 'OAuth client ID'")
        print("   - Application type: 'Desktop app'")
        print("   - Name: 'Gmail Reply Tracker' (or any name)")
        print("   - Click 'Create'")
        print("5. Download the credentials:")
        print("   - Click the download icon next to your credential")
        print("   - Save as 'credentials.json'")
        print(f"6. Place the file at: {config.credentials_path}")
        print()
        print("Note: If your app is not published, you'll need to:")
        print("- Configure OAuth consent screen")
        print("- Add your email as a test user")
        print()
        return False


def run_oauth_flow(auth_manager: GmailAuthManager):
    """
    Run the OAuth flow.

    Args:
        auth_manager: Authentication manager
    """
    print()
    print("Starting OAuth 2.0 authorization flow...")
    print()
    print("A browser window will open for you to authorize the application.")
    print("Please:")
    print("1. Sign in with your Gmail account")
    print("2. Review the permissions requested")
    print("3. Click 'Allow' to grant access")
    print()
    input("Press Enter to continue...")
    print()

    try:
        credentials = auth_manager.ensure_authenticated()
        print()
        print("✓ OAuth authorization successful!")
        print(f"✓ Token saved to: {auth_manager.token_path}")
        return credentials
    except Exception as e:
        print()
        print(f"✗ OAuth authorization failed: {str(e)}")
        print()
        raise


def test_connection(auth_manager: GmailAuthManager):
    """
    Test Gmail API connection.

    Args:
        auth_manager: Authentication manager
    """
    print()
    print("Testing Gmail API connection...")
    print()

    try:
        from googleapiclient.discovery import build

        credentials = auth_manager.get_credentials()
        service = build('gmail', 'v1', credentials=credentials)

        # Get user profile
        profile = service.users().getProfile(userId='me').execute()
        email = profile.get('emailAddress')

        print("✓ Successfully connected to Gmail API!")
        print(f"✓ Authenticated as: {email}")
        print(f"✓ Total messages: {profile.get('messagesTotal', 'N/A')}")
        print(f"✓ Total threads: {profile.get('threadsTotal', 'N/A')}")

        return True

    except Exception as e:
        print(f"✗ Connection test failed: {str(e)}")
        return False


def print_next_steps(config: Config):
    """Print next steps after successful setup."""
    print()
    print("=" * 70)
    print("Setup Complete!")
    print("=" * 70)
    print()
    print("Next steps:")
    print()
    print("1. Test the MCP server:")
    print("   python src/server.py")
    print()
    print("2. Configure Claude Desktop:")
    print("   Edit: ~/Library/Application Support/Claude/claude_desktop_config.json")
    print()
    print('   Add this configuration:')
    print('   {')
    print('     "mcpServers": {')
    print('       "gmail-reply-tracker": {')
    print('         "command": "python",')
    print('         "args": [')
    print(f'           "{Path.cwd() / "src" / "server.py"}"')
    print('         ],')
    print('         "env": {')
    print(f'           "GMAIL_CREDENTIALS_PATH": "{config.credentials_path.absolute()}",')
    print(f'           "GMAIL_TOKEN_PATH": "{config.token_path.absolute()}"')
    print('         }')
    print('       }')
    print('     }')
    print('   }')
    print()
    print("3. Restart Claude Desktop")
    print()
    print("4. Test by asking Claude:")
    print('   "What emails do I need to reply to?"')
    print()


def main():
    """Main setup function."""
    print_header()

    # Load configuration
    print_step(1, "Loading Configuration")
    try:
        config = Config.from_env()
        config.setup_logging()
        print("✓ Configuration loaded successfully")
    except Exception as e:
        print(f"✗ Failed to load configuration: {str(e)}")
        sys.exit(1)

    # Validate configuration
    print_step(2, "Validating Configuration")
    errors = config.validate()

    # Special handling for missing credentials - this is expected on first run
    if errors:
        # Filter out credential file error for now
        creds_errors = [e for e in errors if "Credentials file not found" in e]
        other_errors = [e for e in errors if e not in creds_errors]

        if other_errors:
            print("✗ Configuration errors found:")
            for error in other_errors:
                print(f"  - {error}")
            sys.exit(1)

    # Check credentials file
    print_step(3, "Checking Credentials File")
    if not check_credentials_file(config):
        print()
        print("Please obtain credentials.json and run this script again.")
        sys.exit(1)

    # Run OAuth flow
    print_step(4, "OAuth 2.0 Authorization")
    auth_manager = GmailAuthManager(
        config.credentials_path,
        config.token_path,
        config.oauth_scopes
    )

    try:
        run_oauth_flow(auth_manager)
    except Exception:
        sys.exit(1)

    # Test connection
    print_step(5, "Testing Connection")
    if not test_connection(auth_manager):
        sys.exit(1)

    # Print next steps
    print_next_steps(config)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print()
        print("Setup cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print()
        print(f"Unexpected error: {str(e)}")
        sys.exit(1)
