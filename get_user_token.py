#!/usr/bin/env python3
"""Get a user's session token for reinstallation."""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from database import Database

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 get_user_token.py <user_email>")
        sys.exit(1)

    email = sys.argv[1]

    # Initialize database
    db_path = os.environ.get('DATABASE_PATH', 'data/users.db')
    encryption_key = os.environ.get('ENCRYPTION_KEY')

    if not encryption_key:
        print("Error: ENCRYPTION_KEY environment variable not set")
        sys.exit(1)

    db = Database(db_path, encryption_key)

    # Get user
    user = db.get_user_by_email(email)
    if not user:
        print(f"Error: User not found: {email}")
        sys.exit(1)

    # Display user info and install command
    print(f"User: {user['email']}")
    print(f"Session Token: {user['session_token']}")
    print()
    print("=" * 80)
    print("INSTALLATION COMMAND FOR MAC:")
    print("=" * 80)
    print(f"curl -fsSL https://mcp-gmail-multi-tenant-production.up.railway.app/install.sh | bash -s {user['session_token']} {user['email']}")
    print()

if __name__ == '__main__':
    main()
