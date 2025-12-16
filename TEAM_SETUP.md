# Gmail MCP Server - Team Setup Guide

This guide helps your team get set up with the Gmail MCP Server for Claude Desktop in under 5 minutes.

## Quick Setup (3 Steps)

### Step 1: Get Your Credentials

1. Visit: **https://mcp-gmail-multi-tenant-production.up.railway.app/setup**
2. Click "Authorize with Google"
3. Optionally add your Fathom API key
4. Download your credentials (you'll get a JSON file with your token)

### Step 2: Install the MCP Server

**Clone the repository:**
```bash
git clone https://github.com/jonathangetonapod/gmail-reply-tracker-mcp.git
cd gmail-reply-tracker-mcp
```

**Set up Python environment:**
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Step 3: Configure Claude Desktop

Add this to your Claude Desktop config file:

**Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "gmail-calendar-fathom": {
      "command": "/FULL/PATH/TO/venv/bin/python3",
      "args": [
        "/FULL/PATH/TO/gmail-reply-tracker-mcp/src/server.py"
      ],
      "env": {
        "GMAIL_CREDENTIALS_PATH": "/FULL/PATH/TO/gmail-reply-tracker-mcp/credentials/credentials.json",
        "GMAIL_TOKEN_PATH": "/FULL/PATH/TO/gmail-reply-tracker-mcp/credentials/token.json",
        "GMAIL_OAUTH_SCOPES": "openid,https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar,https://www.googleapis.com/auth/userinfo.email",
        "FATHOM_API_KEY": "YOUR_FATHOM_KEY_IF_YOU_HAVE_ONE"
      }
    }
  }
}
```

**Replace:**
- `/FULL/PATH/TO/` with the actual path (e.g., `/Users/yourname/Desktop/`)
- `YOUR_FATHOM_KEY_IF_YOU_HAVE_ONE` with your Fathom key (or remove this line)

### Step 4: Restart Claude Desktop

That's it! You now have access to:
- ✅ Search and reply to emails
- ✅ Manage calendar events
- ✅ Access Fathom meeting transcripts
- ✅ And more!

## Available Tools

Once connected, you can ask Claude to:
- "Show me unreplied emails from the last 3 days"
- "Search my emails for messages about the project proposal"
- "List my calendar events for next week"
- "Create a meeting for tomorrow at 2pm"
- "Reply to the email from john@example.com"
- "Get the transcript from my last Fathom meeting"

## Troubleshooting

**Server won't start?**
- Make sure Python 3.8+ is installed
- Check that you activated the virtual environment
- Verify all paths in the config are absolute paths

**Can't authorize?**
- Make sure you're using a Google Workspace or Gmail account
- Check that you have the necessary permissions

**Need help?**
Contact the team lead or check the repository README.
