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
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://github.com/jonathangetonapod/gmail-reply-tracker-mcp.git"
INSTALL_DIR="$HOME/gmail-calendar-mcp"

# Parse parameters
USER_EMAIL="$1"
FATHOM_API_KEY="$2"

# Progress tracking
TOTAL_STEPS=11
CURRENT_STEP=0

# Functions
print_header() {
    clear
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}${BOLD}  Gmail Calendar MCP - Local Setup${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo
    echo -e "${CYAN}This will take about 5-10 minutes to complete.${NC}"
    echo -e "${CYAN}Please don't close this window during installation.${NC}"
    echo
}

print_step() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}Step $CURRENT_STEP of $TOTAL_STEPS:${NC} $1"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_substep() {
    echo -e "${CYAN}  ▸${NC} $1"
}

print_error() {
    echo
    echo -e "${RED}${BOLD}✗ ERROR:${NC} $1"
}

print_success() {
    echo -e "${GREEN}  ✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}  ⚠${NC} $1"
}

print_friendly_error() {
    echo
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}${BOLD}  Something went wrong!${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo
    echo -e "$1"
    echo
    echo -e "${YELLOW}Need help?${NC}"
    echo -e "  • Check if you have an internet connection"
    echo -e "  • Try running the command again"
    echo -e "  • Contact support with a screenshot of this error"
    echo
    exit 1
}

check_and_quit_claude() {
    print_step "Checking if Claude Desktop is running"

    if [[ "$OSTYPE" == "darwin"* ]]; then
        # Check if Claude is running on macOS
        if pgrep -x "Claude" > /dev/null; then
            print_warning "Claude Desktop is currently running"
            echo
            echo -e "${YELLOW}${BOLD}⚠ IMPORTANT:${NC} Claude Desktop needs to be closed for installation."
            echo
            echo "Options:"
            echo "  1. We can close it automatically for you (recommended)"
            echo "  2. You can close it manually now"
            echo
            echo -n "Close Claude automatically? (y/n): "
            read -r response

            if [[ "$response" =~ ^[Yy]$ ]]; then
                print_substep "Closing Claude Desktop..."
                osascript -e 'quit app "Claude"' 2>/dev/null || killall "Claude" 2>/dev/null || true
                sleep 2

                if pgrep -x "Claude" > /dev/null; then
                    print_friendly_error "Could not close Claude Desktop automatically.\n\nPlease close it manually:\n  1. Click on the Claude icon in your menu bar\n  2. Select 'Quit Claude' or press ⌘Q\n  3. Run this installation command again"
                fi
                print_success "Claude Desktop closed"
            else
                echo
                echo "Please close Claude Desktop now:"
                echo "  1. Click on the Claude icon in your menu bar"
                echo "  2. Select 'Quit Claude' or press ⌘Q"
                echo
                echo "Press Enter when done..."
                read

                if pgrep -x "Claude" > /dev/null; then
                    print_friendly_error "Claude Desktop is still running.\nPlease close it completely before continuing."
                fi
            fi
        else
            print_success "Claude Desktop is not running"
        fi
    fi
}

print_header
check_and_quit_claude

# Detect OS
print_step "Detecting operating system"
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="mac"
    CONFIG_DIR="$HOME/Library/Application Support/Claude"
    print_success "Detected: macOS"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
    CONFIG_DIR="$HOME/.config/claude"
    print_success "Detected: Linux"
else
    print_friendly_error "Unsupported operating system: $OSTYPE\n\nThis script only works on macOS and Linux.\n\nIf you're on Windows, please use WSL (Windows Subsystem for Linux) first:\n  https://learn.microsoft.com/en-us/windows/wsl/install"
fi

# Check for Claude Desktop
print_step "Checking for Claude Desktop"
if [ ! -d "$CONFIG_DIR" ]; then
    print_friendly_error "Claude Desktop is not installed on your computer.\n\nPlease install it first:\n  1. Visit: https://claude.ai/download\n  2. Download and install Claude Desktop\n  3. Open it once to complete setup\n  4. Then run this installation command again"
fi
print_success "Claude Desktop found"

# Check if Python 3.10+ is installed
print_step "Checking for Python 3.10+"
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
    print_warning "Python 3.10+ not found (MCP requires Python 3.10 or higher)"
    echo
    print_substep "Installing Python automatically..."
    echo

    if [[ "$OS" == "mac" ]]; then
        # Check if Homebrew is installed, if not install it automatically
        if ! command -v brew &> /dev/null; then
            print_substep "Homebrew not found. Installing Homebrew..."
            echo
            echo -e "${YELLOW}${BOLD}⚠ PASSWORD REQUIRED:${NC}"
            echo "Your Mac will ask for your password to install Homebrew."
            echo "This is normal and safe - Homebrew is Apple's recommended package manager."
            echo
            echo "This may take 3-5 minutes..."
            echo
            read -p "Press Enter to continue..."
            echo

            # Install Homebrew non-interactively
            NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

            # Add Homebrew to PATH for this session
            if [ -f "/opt/homebrew/bin/brew" ]; then
                # Apple Silicon
                eval "$(/opt/homebrew/bin/brew shellenv)"
                export PATH="/opt/homebrew/bin:$PATH"
            elif [ -f "/usr/local/bin/brew" ]; then
                # Intel Mac
                eval "$(/usr/local/bin/brew shellenv)"
                export PATH="/usr/local/bin:$PATH"
            fi

            # Verify Homebrew installation
            if command -v brew &> /dev/null; then
                print_success "Homebrew installed successfully!"
            else
                print_friendly_error "Homebrew installation failed.\n\nPlease try again, or install manually:\n  1. Visit: https://brew.sh\n  2. Follow the installation instructions\n  3. Then run this installation command again"
            fi
        fi

        # Now install Python via Homebrew
        print_substep "Installing Python 3.11 via Homebrew..."
        echo "  (This may take 2-3 minutes...)"
        brew install python@3.11 2>&1 | grep -v "^=" || true
        # Update path to use newly installed Python
        export PATH="/opt/homebrew/opt/python@3.11/bin:/usr/local/opt/python@3.11/bin:$PATH"
    else
        # Linux - use apt-get, yum, or dnf
        echo
        echo -e "${YELLOW}${BOLD}⚠ PASSWORD REQUIRED:${NC}"
        echo "You may be asked for your password to install Python."
        echo "This is normal and safe."
        echo
        read -p "Press Enter to continue..."
        echo

        if command -v apt-get &> /dev/null; then
            print_substep "Installing Python 3.11 via apt..."
            sudo apt-get update -qq
            sudo apt-get install -y python3.11 python3.11-pip python3.11-venv
            # Use python3.11 specifically
            PYTHON_CMD="python3.11"
        elif command -v yum &> /dev/null; then
            print_substep "Installing Python 3.11 via yum..."
            sudo yum install -y python3.11 python3.11-pip
            PYTHON_CMD="python3.11"
        elif command -v dnf &> /dev/null; then
            print_substep "Installing Python 3.11 via dnf..."
            sudo dnf install -y python3.11 python3.11-pip
            PYTHON_CMD="python3.11"
        else
            print_friendly_error "Could not detect package manager.\n\nPlease install Python 3.10+ manually:\n  1. Visit: https://www.python.org/downloads/\n  2. Download and install Python 3.10 or higher\n  3. Then run this installation command again"
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
        print_friendly_error "Python 3.10+ installation failed or version is still too old.\n\nCurrent version: $PYTHON_VERSION\nRequired: Python 3.10 or higher\n\nPlease install Python 3.10+ manually:\n  1. Visit: https://www.python.org/downloads/\n  2. Download Python 3.10 or higher\n  3. Then run this installation command again"
    fi
fi

PYTHON_FULL_VERSION=$($PYTHON_CMD --version)
print_success "$PYTHON_FULL_VERSION found"

# Check if git is installed
print_step "Checking for Git"
if ! command -v git &> /dev/null; then
    print_warning "Git not found"
    print_substep "Installing Git automatically..."

    if [[ "$OS" == "mac" ]]; then
        # Try Homebrew first
        if command -v brew &> /dev/null; then
            print_substep "Installing Git via Homebrew..."
            brew install git 2>&1 | grep -v "^=" || true
        else
            print_friendly_error "Homebrew not found.\n\nPlease install Git manually:\n  1. Visit: https://git-scm.com/downloads\n  2. Download and install Git\n  3. Then run this installation command again\n\nOr install Homebrew first: https://brew.sh"
        fi
    else
        # Linux - use apt-get, yum, or dnf
        if command -v apt-get &> /dev/null; then
            print_substep "Installing Git via apt..."
            sudo apt-get install -y git
        elif command -v yum &> /dev/null; then
            print_substep "Installing Git via yum..."
            sudo yum install -y git
        elif command -v dnf &> /dev/null; then
            print_substep "Installing Git via dnf..."
            sudo dnf install -y git
        else
            print_friendly_error "Could not detect package manager.\n\nPlease install Git manually:\n  1. Visit: https://git-scm.com/downloads\n  2. Download and install Git\n  3. Then run this installation command again"
        fi
    fi

    # Verify installation
    if ! command -v git &> /dev/null; then
        print_friendly_error "Git installation failed.\n\nPlease install Git manually:\n  1. Visit: https://git-scm.com/downloads\n  2. Download and install Git\n  3. Then run this installation command again"
    fi
fi
GIT_VERSION=$(git --version)
print_success "$GIT_VERSION found"

# Remove existing installation if present
if [ -d "$INSTALL_DIR" ]; then
    print_warning "Found previous installation"
    print_substep "Removing old version..."
    rm -rf "$INSTALL_DIR"
    print_success "Old version removed"
fi

# Clone repository
print_step "Downloading Gmail Calendar MCP"
print_substep "Cloning from GitHub..."
if git clone "$REPO_URL" "$INSTALL_DIR" --quiet 2>&1; then
    print_success "Download complete"
else
    print_friendly_error "Failed to download from GitHub.\n\nPlease check:\n  • You have an internet connection\n  • GitHub is accessible\n  • Try again in a few minutes"
fi

# Create virtual environment
print_step "Setting up Python environment"
cd "$INSTALL_DIR"
print_substep "Creating virtual environment..."
if $PYTHON_CMD -m venv venv 2>&1; then
    print_success "Virtual environment created"
else
    print_friendly_error "Failed to create Python virtual environment.\n\nThis might be a Python installation issue.\nPlease try:\n  1. Reinstalling Python from python.org\n  2. Running this installation command again"
fi

# Install dependencies using venv's python explicitly
print_step "Installing Python packages"
print_substep "This may take 1-2 minutes..."
echo
# Use venv's python directly instead of relying on activation
./venv/bin/python -m pip install --quiet --upgrade pip 2>&1 | grep -v "^Requirement" || true
./venv/bin/python -m pip install --quiet -r requirements.txt 2>&1 | grep -v "^Requirement" || true
print_success "All packages installed"

# Copy public credentials to credentials directory
print_substep "Setting up OAuth credentials..."
mkdir -p credentials
cp public/credentials.json credentials/credentials.json
print_success "OAuth credentials configured"

# Run OAuth setup
echo
print_step "Connecting to Google Account"
echo
echo -e "${CYAN}${BOLD}What happens next:${NC}"
echo "  1. A browser window will open automatically"
echo "  2. Sign in to your Google account"
echo "  3. Click 'Allow' to authorize Gmail and Calendar access"
echo "  4. Close the browser tab when done"
echo
echo -e "${YELLOW}Note:${NC} If you have multiple Google accounts, make sure to"
echo "       choose the one you want to use with Claude."
echo
read -p "Press Enter to open your browser..."
echo

# Try to open OAuth in browser
print_substep "Opening browser..."
./venv/bin/python auto_oauth.py &
OAUTH_PID=$!

# Wait a few seconds to see if it succeeds
sleep 3

# Check if browser opened
if ! ps -p $OAUTH_PID > /dev/null 2>&1; then
    # Process already finished, check if successful
    if [ ! -f "credentials/token.json" ]; then
        print_warning "Browser may not have opened automatically"
        echo
        echo -e "${YELLOW}${BOLD}Manual Steps:${NC}"
        echo "  1. The browser window should open soon"
        echo "  2. If it doesn't open in 10 seconds:"
        echo "     • Copy the URL from below"
        echo "     • Paste it into your browser"
        echo "     • Complete the authorization"
        echo
    fi
else
    # Wait for OAuth to complete
    wait $OAUTH_PID
fi

# Verify OAuth completed
if [ ! -f "credentials/token.json" ]; then
    print_friendly_error "Google authorization was not completed.\n\nPlease try again:\n  1. Make sure you clicked 'Allow' in the browser\n  2. Check that you're signed into the correct Google account\n  3. Run this command again:\n\n     cd $INSTALL_DIR && ./venv/bin/python auto_oauth.py\n\n  4. Then update Claude config manually"
fi

print_success "Google account connected!"

# Configure environment variables
echo
print_step "Configuring environment variables"

# Copy .env.example to .env (includes EmailGuard API key)
if [ -f ".env.example" ]; then
    cp .env.example .env
    print_success "Environment variables configured (includes EmailGuard API)"
else
    print_warning ".env.example not found, creating minimal .env"
    touch .env
fi

# Optional: Add Fathom API key if provided
if [ -n "$FATHOM_API_KEY" ]; then
    # Update or add FATHOM_API_KEY in .env
    if grep -q "^FATHOM_API_KEY=" .env; then
        # Replace existing line
        sed -i.bak "s|^FATHOM_API_KEY=.*|FATHOM_API_KEY=$FATHOM_API_KEY|" .env && rm .env.bak
    else
        # Append new line
        echo "FATHOM_API_KEY=$FATHOM_API_KEY" >> .env
    fi
    print_success "Fathom API key configured"
else
    print_substep "No Fathom key provided (you can add it later if needed)"
fi

# Update Claude Desktop configuration
print_step "Updating Claude Desktop configuration"

CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"

# Backup existing config
if [ -f "$CONFIG_FILE" ]; then
    BACKUP_FILE="${CONFIG_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$CONFIG_FILE" "$BACKUP_FILE"
    print_substep "Backed up existing config"
else
    print_substep "Creating new config file..."
    mkdir -p "$CONFIG_DIR"
    echo '{"mcpServers":{}}' > "$CONFIG_FILE"
fi

# Get full path to Python in venv (will use the venv's python, which inherits the version)
PYTHON_PATH="$INSTALL_DIR/venv/bin/python"
SERVER_PATH="$INSTALL_DIR/src/server.py"
FATHOM_KEY_VALUE="${FATHOM_API_KEY:-}"

# Update configuration using Python (use any available python3 for this simple JSON manipulation)
print_substep "Adding MCP server to config..."
if python3 << EOF
import json
import sys

config_file = "$CONFIG_FILE"
python_path = "$PYTHON_PATH"
server_path = "$SERVER_PATH"
fathom_api_key = "$FATHOM_KEY_VALUE"

# Read existing config
try:
    with open(config_file, 'r') as f:
        config = json.load(f)
except Exception as e:
    print(f"Error reading config: {e}", file=sys.stderr)
    sys.exit(1)

# Ensure mcpServers exists
if 'mcpServers' not in config:
    config['mcpServers'] = {}

# Remove old/duplicate entries to avoid conflicts
old_servers = ['gmail-reply-tracker', 'gmail-calendar-fathom']
for server_name in old_servers:
    if server_name in config['mcpServers']:
        del config['mcpServers'][server_name]

# Add the correct local server configuration with full paths and environment variables
install_dir = "$INSTALL_DIR"
env_vars = {
    'GMAIL_CREDENTIALS_PATH': f'{install_dir}/credentials/credentials.json',
    'GMAIL_TOKEN_PATH': f'{install_dir}/credentials/token.json',
    'GMAIL_OAUTH_SCOPES': 'https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/calendar,https://www.googleapis.com/auth/userinfo.email',
    'LEAD_SHEETS_URL': 'https://docs.google.com/spreadsheets/d/1CNejGg-egkp28ItSRfW7F_CkBXgYevjzstJ1QlrAyAY/edit',
    'LEAD_SHEETS_GID_INSTANTLY': '928115249',
    'LEAD_SHEETS_GID_BISON': '1631680229',
    'EMAILGUARD_API_KEY': '55483|lebMfPQndeLapfcsDTMpWBe6ff1cuzftnVSGdxfC6a437dd0',
    'ANTHROPIC_API_KEY': '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'
}

# Add Fathom API key if provided
if fathom_api_key:
    env_vars['FATHOM_API_KEY'] = fathom_api_key

config['mcpServers']['gmail-calendar-fathom'] = {
    'command': python_path,
    'args': [server_path],
    'env': env_vars
}

# Write updated config
try:
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"Successfully wrote config with command: {python_path}")
except Exception as e:
    print(f"Error writing config: {e}", file=sys.stderr)
    sys.exit(1)
EOF
then
    print_success "Claude Desktop configured!"
else
    print_friendly_error "Failed to update Claude Desktop configuration.\n\nPlease try manually adding to:\n  $CONFIG_FILE\n\nOr contact support with a screenshot of this error."
fi

# Success!
echo
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}               🎉  Installation Complete!  🎉${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo
echo -e "${GREEN}${BOLD}Congratulations! You now have access to 36 powerful tools:${NC}"
echo
echo -e "${BOLD}📧 Gmail (13 tools)${NC}"
echo "   • Find unreplied emails"
echo "   • Search & read threads"
echo "   • Send emails & replies"
echo "   • Manage drafts & labels"
echo
echo -e "${BOLD}📅 Google Calendar (7 tools)${NC}"
echo "   • List & search events"
echo "   • Create & update meetings"
echo "   • Auto-send invitations"
echo "   • Natural language scheduling"
echo
if [ -n "$FATHOM_KEY" ]; then
echo -e "${BOLD}🎙️  Fathom AI (6 tools)${NC}"
echo "   • Meeting transcripts"
echo "   • AI summaries"
echo "   • Action item extraction"
echo "   • Meeting search"
echo
fi
echo -e "${BOLD}🎯 Lead Management & Campaign Automation (10 tools)${NC}"
echo "   • Track 89 clients (64 Instantly + 25 Bison)"
echo "   • Campaign analytics & interested lead tracking"
echo "   • Create Bison sequences automatically"
echo "   • Create Instantly.ai campaigns with A/B testing"
echo
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo
echo -e "${CYAN}${BOLD}Next Steps:${NC}"
echo
echo -e "${BOLD}1. Restart Claude Desktop${NC}"
if [[ "$OS" == "mac" ]]; then
    echo "   • Press ⌘Q to quit Claude"
    echo "   • Or click Claude in menu bar → Quit"
    echo "   • Then reopen Claude from Applications"
else
    echo "   • Close Claude Desktop completely"
    echo "   • Then reopen it"
fi
echo
echo -e "${BOLD}2. Verify Connection${NC}"
echo "   • Look for 'gmail-calendar-fathom' in Claude's MCP status"
echo "   • Should show as connected with 36 tools"
echo
echo -e "${BOLD}3. Try These Commands:${NC}"
echo -e "   ${CYAN}📧 'Show me my unreplied emails from the last 3 days'${NC}"
echo -e "   ${CYAN}📅 'What meetings do I have tomorrow?'${NC}"
echo -e "   ${CYAN}🎙️  'What were the action items from yesterday's client call?'${NC}"
echo -e "   ${CYAN}🎯 'Show me interested leads from this week'${NC}"
echo
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}Installation Details:${NC}"
echo -e "  Installation: $INSTALL_DIR"
echo -e "  Config file:  $CONFIG_FILE"
if [ -n "$BACKUP_FILE" ]; then
    echo -e "  Backup saved: $BACKUP_FILE"
fi
echo
echo -e "${YELLOW}To uninstall:${NC}"
echo -e "  Remove the 'gmail-calendar-fathom' server from Claude Desktop settings,"
echo -e "  then run: ${CYAN}rm -rf $INSTALL_DIR${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo
