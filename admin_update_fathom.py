#!/usr/bin/env python3
"""Admin script to update a user's Fathom API key."""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from database import Database

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 admin_update_fathom.py <user_email> <fathom_api_key>")
        print("       python3 admin_update_fathom.py <user_email> REMOVE  (to remove key)")
        sys.exit(1)

    email = sys.argv[1]
    fathom_key = sys.argv[2]

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

    # Update Fathom key
    if fathom_key.upper() == "REMOVE":
        db.update_fathom_key(user['id'], None)
        print(f"✓ Removed Fathom API key for: {email}")
    else:
        db.update_fathom_key(user['id'], fathom_key)
        print(f"✓ Updated Fathom API key for: {email}")

    print(f"  User ID: {user['id']}")
    print(f"  New Fathom key: {fathom_key if fathom_key.upper() != 'REMOVE' else '(removed)'}")

if __name__ == '__main__':
    main()
