#!/bin/bash
#
# Gmail MCP Server - Automated Setup Script
# Usage: curl -fsSL https://mcp-gmail-multi-tenant-production.up.railway.app/install.sh | bash -s YOUR_SESSION_TOKEN
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SERVER_URL="https://mcp-gmail-multi-tenant-production.up.railway.app"
SESSION_TOKEN="$1"
USER_EMAIL="$2"

# Functions
print_header() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  Gmail MCP Server - Automated Setup${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo
}

print_step() {
    echo -e "${GREEN}▸${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Check if session token provided
if [ -z "$SESSION_TOKEN" ]; then
    print_header
    print_error "No session token provided!"
    echo
    echo "Usage:"
    echo "  curl -fsSL ${SERVER_URL}/install.sh | bash -s YOUR_SESSION_TOKEN YOUR_EMAIL"
    echo
    echo "To get your session token:"
    echo "  1. Visit: ${SERVER_URL}/setup"
    echo "  2. Authorize with Google"
    echo "  3. Copy the install command from the page"
    echo
    exit 1
fi

if [ -z "$USER_EMAIL" ]; then
    print_header
    print_error "No email provided!"
    echo
    echo "Usage:"
    echo "  curl -fsSL ${SERVER_URL}/install.sh | bash -s YOUR_SESSION_TOKEN YOUR_EMAIL"
    echo
    exit 1
fi

print_header

# Detect OS
print_step "Detecting operating system..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="mac"
    CONFIG_DIR="$HOME/Library/Application Support/Claude"
    INSTALL_DIR="$HOME/Library/Application Support/Claude/mcp-clients"
    print_success "Detected: macOS"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
    CONFIG_DIR="$HOME/.config/claude"
    INSTALL_DIR="$HOME/.config/claude/mcp-clients"
    print_success "Detected: Linux"
else
    print_error "Unsupported operating system: $OSTYPE"
    echo "This script supports macOS and Linux only."
    echo "For Windows, please use install.ps1"
    exit 1
fi

# Check if Node.js is installed
print_step "Checking for Node.js..."
if ! command -v node &> /dev/null; then
    print_error "Node.js is not installed!"
    echo
    echo "Please install Node.js first:"
    echo "  Visit: https://nodejs.org/"
    echo
    exit 1
fi
NODE_VERSION=$(node --version)
print_success "Node.js $NODE_VERSION found"

# Create installation directory
print_step "Creating installation directory..."
mkdir -p "$INSTALL_DIR"
print_success "Directory created: $INSTALL_DIR"

# Download http-mcp-client.js
print_step "Downloading MCP client..."
CLIENT_PATH="$INSTALL_DIR/http-mcp-client.js"
curl -fsSL "${SERVER_URL}/download/http-mcp-client.js" -o "$CLIENT_PATH"
chmod +x "$CLIENT_PATH"
print_success "Downloaded to: $CLIENT_PATH"

# Check if config file exists
CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"
print_step "Looking for Claude Desktop config..."
if [ ! -f "$CONFIG_FILE" ]; then
    print_warning "Config file doesn't exist, creating new one..."
    mkdir -p "$CONFIG_DIR"
    echo '{"mcpServers":{}}' > "$CONFIG_FILE"
fi
print_success "Found: $CONFIG_FILE"

# Backup existing config
print_step "Backing up existing configuration..."
BACKUP_FILE="${CONFIG_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$CONFIG_FILE" "$BACKUP_FILE"
print_success "Backup saved: $BACKUP_FILE"

# Update configuration using Python
print_step "Updating Claude Desktop configuration..."

python3 -c "
import json
import sys
import re

# Extract domain from email
email = '$USER_EMAIL'
domain_match = re.search(r'@([^@]+)$', email)
if domain_match:
    domain = domain_match.group(1)
    # Remove TLD and use first part as identifier
    # e.g., leadgenjay.com -> leadgenjay
    domain_name = domain.split('.')[0]
else:
    domain_name = 'default'

# Read existing config
with open('$CONFIG_FILE', 'r') as f:
    config = json.load(f)

# Ensure mcpServers exists
if 'mcpServers' not in config:
    config['mcpServers'] = {}

# Generate server name
# If gmail-calendar-fathom doesn't exist, use it
# Otherwise use gmail-calendar-fathom-DOMAIN
server_name = 'gmail-calendar-fathom'
if server_name in config['mcpServers']:
    # Check if it's pointing to our server
    existing_args = config['mcpServers'][server_name].get('args', [])
    if len(existing_args) > 1 and '${SERVER_URL}' in existing_args[1]:
        # It's already our server, use domain-based name
        server_name = f'gmail-calendar-fathom-{domain_name}'
    else:
        # Different server, use domain-based name
        server_name = f'gmail-calendar-fathom-{domain_name}'

# Add our server (or update if exists)
config['mcpServers'][server_name] = {
    'command': 'node',
    'args': [
        '$CLIENT_PATH',
        '${SERVER_URL}/mcp',
        '$SESSION_TOKEN'
    ]
}

# Write updated config
with open('$CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=2)

print(f'Configuration updated successfully!')
print(f'Server name: {server_name}')
"

if [ $? -eq 0 ]; then
    print_success "Configuration updated successfully!"
else
    print_error "Failed to update configuration"
    print_warning "Restoring backup..."
    cp "$BACKUP_FILE" "$CONFIG_FILE"
    exit 1
fi

# Success!
echo
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✓ Setup Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo
echo "Next steps:"
echo "  1. Restart Claude Desktop"
echo "  2. Try asking Claude:"
echo "     • 'Show me my unreplied emails from the last 3 days'"
echo "     • 'List my calendar events for next week'"
echo
echo "Files installed:"
echo "  • Client: $CLIENT_PATH"
echo "  • Config: $CONFIG_FILE"
echo "  • Backup: $BACKUP_FILE"
echo
