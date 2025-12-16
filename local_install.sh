#!/bin/bash
#
# Gmail Calendar MCP - Local Installation Script
# Works with both Free and Pro Claude Desktop users
#
# Usage: curl -fsSL https://raw.githubusercontent.com/jonathangetonapod/gmail-reply-tracker-mcp/main/local_install.sh | bash
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://github.com/jonathangetonapod/gmail-reply-tracker-mcp.git"
INSTALL_DIR="$HOME/gmail-calendar-mcp"

# Parse parameters
USER_EMAIL="$1"
FATHOM_API_KEY="$2"

# Functions
print_header() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  Gmail Calendar MCP - Local Setup${NC}"
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

print_header

# Detect OS
print_step "Detecting operating system..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="mac"
    CONFIG_DIR="$HOME/Library/Application Support/Claude"
    print_success "Detected: macOS"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
    CONFIG_DIR="$HOME/.config/claude"
    print_success "Detected: Linux"
else
    print_error "Unsupported operating system: $OSTYPE"
    echo "This script supports macOS and Linux only."
    exit 1
fi

# Check for Claude Desktop
print_step "Checking for Claude Desktop..."
if [ ! -d "$CONFIG_DIR" ]; then
    print_error "Claude Desktop not found!"
    echo
    echo "Please install Claude Desktop first:"
    echo "  Visit: https://claude.ai/download"
    echo
    exit 1
fi
print_success "Claude Desktop found"

# Check if Python 3.10+ is installed
print_step "Checking for Python 3.10+..."
PYTHON_CMD=""
PYTHON_VERSION_OK=false

# Check python3 command
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

    if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 10 ]; then
        PYTHON_CMD="python3"
        PYTHON_VERSION_OK=true
    fi
fi

if [ "$PYTHON_VERSION_OK" = false ]; then
    print_warning "Python 3.10+ not found (MCP requires Python 3.10 or higher). Installing now..."

    if [[ "$OS" == "mac" ]]; then
        # Try Homebrew first
        if command -v brew &> /dev/null; then
            print_step "Installing Python 3.11 via Homebrew..."
            brew install python@3.11
            # Update path to use newly installed Python
            export PATH="/opt/homebrew/opt/python@3.11/bin:/usr/local/opt/python@3.11/bin:$PATH"
        else
            print_error "Homebrew not found. Please install Python 3.10+ manually:"
            echo "  Visit: https://www.python.org/downloads/"
            echo "  Or install Homebrew first: https://brew.sh"
            exit 1
        fi
    else
        # Linux - use apt-get, yum, or dnf
        if command -v apt-get &> /dev/null; then
            print_step "Installing Python 3.11 via apt..."
            sudo apt-get update
            sudo apt-get install -y python3.11 python3.11-pip python3.11-venv
            # Use python3.11 specifically
            PYTHON_CMD="python3.11"
        elif command -v yum &> /dev/null; then
            print_step "Installing Python 3.11 via yum..."
            sudo yum install -y python3.11 python3.11-pip
            PYTHON_CMD="python3.11"
        elif command -v dnf &> /dev/null; then
            print_step "Installing Python 3.11 via dnf..."
            sudo dnf install -y python3.11 python3.11-pip
            PYTHON_CMD="python3.11"
        else
            print_error "Could not detect package manager. Please install Python 3.10+ manually:"
            echo "  Visit: https://www.python.org/downloads/"
            exit 1
        fi
    fi

    # Verify installation - check for python3.11 first, then python3
    if command -v python3.11 &> /dev/null; then
        PYTHON_VERSION=$(python3.11 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
        PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

        if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 10 ]; then
            PYTHON_CMD="python3.11"
            PYTHON_VERSION_OK=true
        fi
    elif command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
        PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

        if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 10 ]; then
            PYTHON_CMD="python3"
            PYTHON_VERSION_OK=true
        fi
    fi

    if [ "$PYTHON_VERSION_OK" = false ]; then
        print_error "Python 3.10+ installation failed or version is still too old"
        echo "  Current version: $PYTHON_VERSION"
        echo "  Required: Python 3.10 or higher"
        echo
        echo "Please install Python 3.10+ manually:"
        echo "  Visit: https://www.python.org/downloads/"
        exit 1
    fi
fi

PYTHON_FULL_VERSION=$($PYTHON_CMD --version)
print_success "$PYTHON_FULL_VERSION found"

# Check if git is installed
print_step "Checking for git..."
if ! command -v git &> /dev/null; then
    print_warning "Git not found. Installing now..."

    if [[ "$OS" == "mac" ]]; then
        # Try Homebrew first
        if command -v brew &> /dev/null; then
            print_step "Installing Git via Homebrew..."
            brew install git
        else
            print_error "Homebrew not found. Please install Git manually:"
            echo "  Visit: https://git-scm.com/downloads"
            echo "  Or install Homebrew first: https://brew.sh"
            exit 1
        fi
    else
        # Linux - use apt-get, yum, or dnf
        if command -v apt-get &> /dev/null; then
            print_step "Installing Git via apt..."
            sudo apt-get update
            sudo apt-get install -y git
        elif command -v yum &> /dev/null; then
            print_step "Installing Git via yum..."
            sudo yum install -y git
        elif command -v dnf &> /dev/null; then
            print_step "Installing Git via dnf..."
            sudo dnf install -y git
        else
            print_error "Could not detect package manager. Please install Git manually:"
            echo "  Visit: https://git-scm.com/downloads"
            exit 1
        fi
    fi

    # Verify installation
    if ! command -v git &> /dev/null; then
        print_error "Git installation failed"
        exit 1
    fi
fi
GIT_VERSION=$(git --version)
print_success "$GIT_VERSION found"

# Remove existing installation if present
if [ -d "$INSTALL_DIR" ]; then
    print_warning "Existing installation found at $INSTALL_DIR"
    print_step "Removing old installation..."
    rm -rf "$INSTALL_DIR"
    print_success "Old installation removed"
fi

# Clone repository
print_step "Cloning Gmail Calendar MCP repository..."
git clone "$REPO_URL" "$INSTALL_DIR" --quiet
print_success "Repository cloned to: $INSTALL_DIR"

# Create virtual environment
print_step "Creating Python virtual environment..."
cd "$INSTALL_DIR"
$PYTHON_CMD -m venv venv
print_success "Virtual environment created"

# Activate virtual environment and install dependencies
print_step "Installing Python dependencies (this may take a minute)..."
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
print_success "Dependencies installed"

# Copy public credentials to credentials directory
print_step "Setting up OAuth credentials..."
mkdir -p credentials
cp public/credentials.json credentials/credentials.json
print_success "OAuth credentials configured"

# Run OAuth setup
echo
print_step "Starting Google OAuth setup..."
echo
echo "A browser window will open for you to:"
echo "  1. Sign in to your Google account"
echo "  2. Authorize Gmail and Calendar access"
echo "  3. Complete the authorization"
echo
echo "Press Enter to continue..."
read

$PYTHON_CMD setup_oauth.py

if [ ! -f "data/token.json" ]; then
    print_error "OAuth setup failed - token.json not found"
    echo
    echo "Please try running the setup manually:"
    echo "  cd $INSTALL_DIR"
    echo "  source venv/bin/activate"
    echo "  $PYTHON_CMD setup_oauth.py"
    echo
    exit 1
fi

print_success "OAuth setup completed!"

# Optional: Fathom API key
echo
print_step "Configuring Fathom Integration"
if [ -n "$FATHOM_API_KEY" ]; then
    # Create .env file with Fathom key from parameter
    echo "FATHOM_API_KEY=$FATHOM_API_KEY" > .env
    print_success "Fathom API key configured automatically"
else
    print_success "No Fathom key provided (you can add it later if needed)"
fi

# Update Claude Desktop configuration
print_step "Configuring Claude Desktop..."

CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"

# Backup existing config
if [ -f "$CONFIG_FILE" ]; then
    BACKUP_FILE="${CONFIG_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$CONFIG_FILE" "$BACKUP_FILE"
    print_success "Backup saved: $BACKUP_FILE"
else
    print_warning "No existing config found, creating new one..."
    mkdir -p "$CONFIG_DIR"
    echo '{"mcpServers":{}}' > "$CONFIG_FILE"
fi

# Get full path to Python in venv (will use the venv's python, which inherits the version)
PYTHON_PATH="$INSTALL_DIR/venv/bin/python"
SERVER_PATH="$INSTALL_DIR/src/server.py"

# Update configuration using Python
$PYTHON_CMD -c "
import json

# Read existing config
with open('$CONFIG_FILE', 'r') as f:
    config = json.load(f)

# Ensure mcpServers exists
if 'mcpServers' not in config:
    config['mcpServers'] = {}

# Add local server
config['mcpServers']['gmail-calendar-fathom'] = {
    'command': '$PYTHON_PATH',
    'args': ['$SERVER_PATH']
}

# Write updated config
with open('$CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=2)

print('Configuration updated!')
"

if [ $? -eq 0 ]; then
    print_success "Claude Desktop configured successfully!"
else
    print_error "Failed to update configuration"
    exit 1
fi

# Success!
echo
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✓ Setup Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo
echo "Next steps:"
echo "  1. Restart Claude Desktop (Quit with ⌘Q, then reopen)"
echo "  2. Start a new conversation"
echo "  3. Try asking Claude:"
echo "     • 'Show me my unreplied emails from the last 3 days'"
echo "     • 'List my calendar events for next week'"
echo
echo "Installation location:"
echo "  • Server: $INSTALL_DIR"
echo "  • Config: $CONFIG_FILE"
echo
echo "To uninstall:"
echo "  • Remove from Claude config, then: rm -rf $INSTALL_DIR"
echo
