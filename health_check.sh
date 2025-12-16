#!/bin/bash
#
# Gmail Calendar MCP - Health Check
# Diagnoses common installation issues
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_DIR="$HOME/gmail-calendar-mcp"
CONFIG_DIR="$HOME/Library/Application Support/Claude"
CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"

ISSUES_FOUND=0

print_header() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  Gmail Calendar MCP - Health Check${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo
}

check_pass() {
    echo -e "${GREEN}✓${NC} $1"
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_header

# Check 1: Installation directory exists
echo "Checking installation..."
if [ -d "$INSTALL_DIR" ]; then
    check_pass "Installation directory exists: $INSTALL_DIR"
else
    check_fail "Installation directory not found: $INSTALL_DIR"
    echo "   Run: curl -fsSL https://raw.githubusercontent.com/jonathangetonapod/gmail-reply-tracker-mcp/main/local_install.sh | bash -s YOUR_EMAIL"
    exit 1
fi

# Check 2: Server file exists
if [ -f "$INSTALL_DIR/src/server.py" ]; then
    check_pass "Server file exists"
else
    check_fail "Server file not found: $INSTALL_DIR/src/server.py"
fi

# Check 3: Virtual environment exists
if [ -d "$INSTALL_DIR/venv" ]; then
    check_pass "Virtual environment exists"

    # Check Python version in venv
    PYTHON_VERSION=$("$INSTALL_DIR/venv/bin/python" --version 2>&1)
    PYTHON_MINOR=$(echo "$PYTHON_VERSION" | grep -oE '[0-9]+\.[0-9]+' | head -1 | cut -d. -f2)

    if [ "$PYTHON_MINOR" -ge 10 ]; then
        check_pass "Python version: $PYTHON_VERSION (>= 3.10)"
    else
        check_fail "Python version too old: $PYTHON_VERSION (need >= 3.10)"
        echo "   Run: cd $INSTALL_DIR && rm -rf venv && python3.11 -m venv venv"
    fi
else
    check_fail "Virtual environment not found"
    echo "   Run: cd $INSTALL_DIR && python3.11 -m venv venv"
fi

# Check 4: Dependencies installed
if [ -f "$INSTALL_DIR/venv/bin/python" ]; then
    echo
    echo "Checking dependencies..."

    # Check for key packages
    for package in mcp google-auth google-api-python-client; do
        if "$INSTALL_DIR/venv/bin/python" -c "import $package" 2>/dev/null; then
            check_pass "$package installed"
        else
            check_fail "$package not installed"
            echo "   Run: cd $INSTALL_DIR && ./venv/bin/python -m pip install -r requirements.txt"
        fi
    done
fi

# Check 5: Credentials file
echo
echo "Checking OAuth credentials..."
if [ -f "$INSTALL_DIR/credentials/credentials.json" ]; then
    check_pass "OAuth credentials file exists"
else
    check_fail "Credentials file not found"
    echo "   This should have been created during installation"
fi

# Check 6: Token file (optional but important)
if [ -f "$INSTALL_DIR/credentials/token.json" ]; then
    check_pass "OAuth token exists (you're authenticated)"

    # Check if token is expired (rough check - just see if it's older than 7 days)
    if [ "$(find "$INSTALL_DIR/credentials/token.json" -mtime +7)" ]; then
        check_warn "Token is older than 7 days - might need refresh"
        echo "   If you see authentication errors, run: cd $INSTALL_DIR && ./venv/bin/python setup_oauth.py"
    fi
else
    check_warn "OAuth token not found - you need to authenticate"
    echo "   Run: cd $INSTALL_DIR && ./venv/bin/python setup_oauth.py"
fi

# Check 7: Claude Desktop config
echo
echo "Checking Claude Desktop config..."
if [ -f "$CONFIG_FILE" ]; then
    check_pass "Claude Desktop config file exists"

    # Check if our server is in the config
    if grep -q "gmail-calendar-fathom" "$CONFIG_FILE"; then
        check_pass "MCP server entry found in config"

        # Check if it's pointing to the right path
        EXPECTED_PYTHON="$INSTALL_DIR/venv/bin/python3"
        if grep -q "$EXPECTED_PYTHON" "$CONFIG_FILE"; then
            check_pass "Config has correct Python path"
        else
            check_fail "Config has wrong Python path"
            echo "   Run: curl -fsSL https://raw.githubusercontent.com/jonathangetonapod/gmail-reply-tracker-mcp/main/fix_config.py | python3"
        fi
    else
        check_fail "MCP server entry NOT found in config"
        echo "   Run: curl -fsSL https://raw.githubusercontent.com/jonathangetonapod/gmail-reply-tracker-mcp/main/fix_config.py | python3"
    fi
else
    check_fail "Claude Desktop config file not found"
    echo "   Is Claude Desktop installed? Check: $CONFIG_DIR"
fi

# Check 8: Can we import the server?
echo
echo "Testing server import..."
cd "$INSTALL_DIR"
if "$INSTALL_DIR/venv/bin/python" -c "import sys; sys.path.insert(0, 'src'); from config import Config; from auth import GmailAuthManager" 2>/dev/null; then
    check_pass "Server modules can be imported"
else
    check_fail "Server modules cannot be imported"
    echo "   There may be a Python path issue"
fi

# Summary
echo
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if [ $ISSUES_FOUND -eq 0 ]; then
    echo -e "${GREEN}  ✓ No issues found!${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo
    echo "Next steps:"
    echo "  1. Make sure Claude Desktop is restarted (⌘Q, then reopen)"
    echo "  2. Start a new conversation"
    echo "  3. Try: 'Show me my unreplied emails'"
    echo
else
    echo -e "${RED}  Found $ISSUES_FOUND issue(s)${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo
    echo "Follow the suggestions above to fix the issues."
    echo "If problems persist, see: https://github.com/jonathangetonapod/gmail-reply-tracker-mcp/blob/main/TROUBLESHOOTING.md"
    echo
fi
