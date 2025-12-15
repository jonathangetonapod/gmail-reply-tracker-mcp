#!/bin/bash
# Quick setup script for Get On A Pod Gmail/Calendar/Fathom MCP

set -e  # Exit on error

echo "🚀 Get On A Pod - MCP Quick Setup"
echo "=================================="
echo ""

# Check if we're in the right directory
if [ ! -f "requirements.txt" ]; then
    echo "❌ Error: Please run this from the gmail-calendar-fathom directory"
    echo "   cd ~/Desktop/GetOnAPod_MCPs/gmail-calendar-fathom"
    exit 1
fi

echo "Step 1: Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

echo ""
echo "Step 2: Activating virtual environment..."
source venv/bin/activate
echo "✓ Virtual environment activated"

echo ""
echo "Step 3: Installing dependencies..."
pip install -r requirements.txt --quiet
echo "✓ Dependencies installed"

echo ""
echo "Step 4: Checking for credentials..."
if [ ! -f "credentials/credentials.json" ]; then
    echo "⚠️  credentials.json not found!"
    echo ""
    echo "Next steps:"
    echo "1. Go to: https://console.cloud.google.com"
    echo "2. Create project: 'Get On A Pod MCP'"
    echo "3. Enable Gmail API and Calendar API"
    echo "4. Create OAuth Desktop credentials"
    echo "5. Download as credentials.json"
    echo "6. Move to: $(pwd)/credentials/credentials.json"
    echo ""
    echo "See SETUP_GUIDE.md for detailed instructions"
    exit 1
else
    echo "✓ credentials.json found"
fi

echo ""
echo "Step 5: Checking for .env configuration..."
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found! Creating template..."
    cat > .env << 'EOF'
# Gmail & Calendar
GMAIL_CREDENTIALS_PATH=./credentials/credentials.json
GMAIL_TOKEN_PATH=./credentials/token.json
GMAIL_OAUTH_SCOPES=https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar

# Server Settings
MCP_SERVER_NAME=getonapod-gmail-calendar-fathom
LOG_LEVEL=INFO
GMAIL_API_MAX_REQUESTS_PER_MINUTE=60

# Fathom API Key (paste your Get On A Pod key here)
FATHOM_API_KEY=
EOF
    echo "✓ Created .env template"
    echo "⚠️  Please edit .env and add your Fathom API key (if you use Fathom)"
    echo "   Run: open -e .env"
else
    echo "✓ .env file exists"
fi

echo ""
echo "Step 6: Authenticating with Google..."
if [ ! -f "credentials/token.json" ]; then
    echo "Running authentication flow..."
    echo "⚠️  IMPORTANT: Sign in with your GET ON A POD Google account!"
    echo ""
    read -p "Press Enter to continue..."
    python3 setup_oauth.py

    if [ $? -eq 0 ]; then
        echo "✓ Authentication successful!"
    else
        echo "❌ Authentication failed. Please try again."
        exit 1
    fi
else
    echo "✓ Already authenticated (token.json exists)"
    echo "   To re-authenticate: rm credentials/token.json && ./QUICKSTART.sh"
fi

echo ""
echo "================================================"
echo "✅ Setup Complete!"
echo "================================================"
echo ""
echo "Next steps:"
echo "1. Update Claude Desktop config:"
echo "   Edit: ~/Library/Application Support/Claude/claude_desktop_config.json"
echo ""
echo "2. Add this configuration:"
echo '   "getonapod-gmail": {'
echo '     "command": "python3",'
echo "     \"args\": [\"$(pwd)/src/server.py\"],"
echo '     "env": {'
echo "       \"GMAIL_CREDENTIALS_PATH\": \"$(pwd)/credentials/credentials.json\","
echo "       \"GMAIL_TOKEN_PATH\": \"$(pwd)/credentials/token.json\","
echo '       "GMAIL_OAUTH_SCOPES": "https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar",'
echo '       "FATHOM_API_KEY": "YOUR_KEY_HERE"'
echo '     }'
echo '   }'
echo ""
echo "3. Restart Claude Desktop"
echo ""
echo "See SETUP_GUIDE.md for detailed instructions!"
echo ""
