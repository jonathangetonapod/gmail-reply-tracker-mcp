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
    print_warning "Node.js is not installed. Installing now..."

    if [[ "$OS" == "mac" ]]; then
        # Check if Homebrew is installed
        if command -v brew &> /dev/null; then
            print_step "Installing Node.js via Homebrew..."
            brew install node
            if [ $? -eq 0 ]; then
                print_success "Node.js installed successfully!"

                # Update PATH to include Homebrew's node
                # Homebrew installs to /opt/homebrew on Apple Silicon, /usr/local on Intel
                export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

                # Verify node is now available
                if ! command -v node &> /dev/null; then
                    print_warning "Node.js installed but not found in PATH. Trying to locate..."
                    # Try to find node in common Homebrew locations
                    if [ -f "/opt/homebrew/bin/node" ]; then
                        export PATH="/opt/homebrew/bin:$PATH"
                    elif [ -f "/usr/local/bin/node" ]; then
                        export PATH="/usr/local/bin:$PATH"
                    else
                        print_error "Node.js installed but could not be located"
                        echo
                        echo "Please close this terminal and open a new one, then re-run:"
                        echo "  curl -fsSL ${SERVER_URL}/install.sh | bash -s $SESSION_TOKEN $USER_EMAIL"
                        echo
                        exit 1
                    fi
                fi
            else
                print_error "Failed to install Node.js via Homebrew"
                echo
                echo "Please install Node.js manually:"
                echo "  Visit: https://nodejs.org/"
                echo
                exit 1
            fi
        else
            print_warning "Homebrew is not installed. Installing Node.js directly..."
            echo

            # Detect architecture
            ARCH=$(uname -m)
            if [[ "$ARCH" == "arm64" ]]; then
                NODE_ARCH="arm64"
                print_step "Detected Apple Silicon (M1/M2/M3)"
            else
                NODE_ARCH="x64"
                print_step "Detected Intel Mac"
            fi

            # Download and install Node.js directly
            print_step "Downloading Node.js (this may take a minute)..."
            NODE_VERSION="v20.11.0"
            NODE_PKG="node-${NODE_VERSION}.pkg"

            cd /tmp
            curl -fsSL "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-darwin-${NODE_ARCH}.tar.gz" -o node.tar.gz

            if [ $? -eq 0 ]; then
                print_step "Extracting Node.js..."
                tar -xzf node.tar.gz

                # Create local bin directory
                mkdir -p "$HOME/.local/bin"

                # Copy node and npm to local bin
                cp "node-${NODE_VERSION}-darwin-${NODE_ARCH}/bin/node" "$HOME/.local/bin/"
                cp "node-${NODE_VERSION}-darwin-${NODE_ARCH}/bin/npm" "$HOME/.local/bin/"

                # Make executable
                chmod +x "$HOME/.local/bin/node"
                chmod +x "$HOME/.local/bin/npm"

                # Add to PATH for this session
                export PATH="$HOME/.local/bin:$PATH"

                # Clean up
                rm -rf node.tar.gz "node-${NODE_VERSION}-darwin-${NODE_ARCH}"

                # Verify installation
                if command -v node &> /dev/null; then
                    print_success "Node.js installed successfully!"
                    NODE_VERSION_INSTALLED=$(node --version)
                    print_success "Node.js $NODE_VERSION_INSTALLED is ready"
                else
                    print_error "Node.js installed but not found in PATH"
                    echo
                    echo "Please add the following to your ~/.zshrc or ~/.bash_profile:"
                    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
                    echo
                    echo "Then close this terminal, open a new one, and re-run:"
                    echo "  curl -fsSL ${SERVER_URL}/install.sh | bash -s $SESSION_TOKEN $USER_EMAIL"
                    echo
                    exit 1
                fi
            else
                print_error "Failed to download Node.js"
                echo
                echo "Please install Node.js manually:"
                echo "  Visit: https://nodejs.org/"
                echo
                echo "Or install Homebrew first (requires admin password):"
                echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
                echo "  Then re-run this script"
                echo
                exit 1
            fi
        fi
    elif [[ "$OS" == "linux" ]]; then
        # Try to detect Linux package manager and install
        if command -v apt-get &> /dev/null; then
            print_step "Installing Node.js via apt..."
            sudo apt-get update
            sudo apt-get install -y nodejs npm
        elif command -v yum &> /dev/null; then
            print_step "Installing Node.js via yum..."
            sudo yum install -y nodejs npm
        elif command -v dnf &> /dev/null; then
            print_step "Installing Node.js via dnf..."
            sudo dnf install -y nodejs npm
        else
            print_error "Could not detect package manager"
            echo
            echo "Please install Node.js manually:"
            echo "  Visit: https://nodejs.org/"
            echo
            exit 1
        fi

        # Refresh PATH for newly installed node
        export PATH="/usr/local/bin:/usr/bin:$PATH"

        if command -v node &> /dev/null; then
            print_success "Node.js installed successfully!"
        else
            print_error "Failed to install Node.js"
            echo
            echo "Please install Node.js manually:"
            echo "  Visit: https://nodejs.org/"
            echo
            exit 1
        fi
    fi
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

# Get full path to node for config
NODE_PATH=$(which node)
print_success "Node path: $NODE_PATH"

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
    'command': '$NODE_PATH',
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
