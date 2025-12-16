#!/usr/bin/env python3
"""
Fix Claude Desktop Config for Gmail Calendar MCP
Removes old/broken entries and adds the correct configuration.
"""

import json
import os
import sys
from datetime import datetime

def main():
    # Determine config path based on OS
    if sys.platform == 'darwin':  # macOS
        config_path = os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
    elif sys.platform == 'linux':
        config_path = os.path.expanduser("~/.config/claude/claude_desktop_config.json")
    else:
        print("❌ Unsupported operating system. This script supports macOS and Linux only.")
        sys.exit(1)

    # Check if config file exists
    if not os.path.exists(config_path):
        print(f"❌ Config file not found: {config_path}")
        print("\nPlease ensure Claude Desktop is installed.")
        sys.exit(1)

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Gmail Calendar MCP - Config Fix")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()

    # Backup existing config
    backup_path = f"{config_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        with open(config_path, 'r') as f:
            content = f.read()
        with open(backup_path, 'w') as f:
            f.write(content)
        print(f"✓ Backup saved: {backup_path}")
    except Exception as e:
        print(f"❌ Failed to backup config: {e}")
        sys.exit(1)

    # Read and parse config
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse config JSON: {e}")
        print("   Config file may be corrupted. Check backup file.")
        sys.exit(1)

    # Ensure mcpServers exists
    if 'mcpServers' not in config:
        config['mcpServers'] = {}

    # Remove ALL old/broken entries
    old_names = [
        'gmail-reply-tracker',      # Old name
        'gmail-calendar-fathom',    # Might have wrong path
        'gmail-fathom-calendar',    # Alternative naming
    ]

    removed = []
    for name in old_names:
        if name in config['mcpServers']:
            del config['mcpServers'][name]
            removed.append(name)
            print(f"✓ Removed old entry: {name}")

    if not removed:
        print("- No old entries found to remove")

    # Determine installation directory
    home = os.path.expanduser("~")
    install_dir = os.path.join(home, "gmail-calendar-mcp")
    python_path = os.path.join(install_dir, "venv", "bin", "python3")
    server_path = os.path.join(install_dir, "src", "server.py")

    # Check if installation exists
    if not os.path.exists(python_path):
        print(f"\n⚠️  Warning: Python venv not found at: {python_path}")
        print("   You may need to run the installation script first:")
        print("   curl -fsSL https://raw.githubusercontent.com/jonathangetonapod/gmail-reply-tracker-mcp/main/local_install.sh | bash -s YOUR_EMAIL")
        print("\n   Continuing anyway...")

    if not os.path.exists(server_path):
        print(f"\n⚠️  Warning: Server file not found at: {server_path}")
        print("   You may need to run the installation script first.")
        print("\n   Continuing anyway...")

    # Add the correct configuration
    config['mcpServers']['gmail-calendar-fathom'] = {
        'command': python_path,
        'args': [server_path]
    }
    print(f"✓ Added correct entry: gmail-calendar-fathom")

    # Save updated config
    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        print("\n✓ Config file updated successfully!")
    except Exception as e:
        print(f"\n❌ Failed to save config: {e}")
        print(f"   Restoring backup from: {backup_path}")
        with open(backup_path, 'r') as f:
            with open(config_path, 'w') as out:
                out.write(f.read())
        sys.exit(1)

    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  ✓ Setup Complete!")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("\nNext steps:")
    print("  1. Restart Claude Desktop (⌘Q to quit, then reopen)")
    print("  2. Start a new conversation")
    print("  3. Try: 'Show me my unreplied emails from the last 3 days'")
    print()

if __name__ == "__main__":
    main()
