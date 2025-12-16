<div align="center">

# 📬 Gmail + Calendar + Fathom + Leads MCP Server

### Your AI-Powered Productivity & Lead Management Command Center

*Connect Claude to your entire productivity stack and lead generation platforms with natural language*

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

[Quick Start](#-quick-start) • [Features](#-features) • [Installation](#-installation) • [Documentation](#-documentation)

</div>

---

## 🚀 What This Does

Transform Claude into your personal productivity assistant with **one-click access** to:

- 📧 **Gmail** - Smart email management, automated filtering, and intelligent replies
- 📅 **Google Calendar** - Natural language scheduling with automatic timezone detection
- 🎙️ **Fathom AI** - Meeting transcripts, summaries, and action item extraction
- 🎯 **Lead Management** - Track 80 clients across Instantly.ai & Bison platforms with campaign analytics

**Ask Claude things like:**
> "What emails need my attention today?"
> "Schedule a meeting with Sarah tomorrow at 2pm and send her a calendar invite"
> "What were the action items from yesterday's client call?"
> "Show me interested leads from our top performing clients this week"
> "Which clients are underperforming and need attention?"

## ✨ What's New

- 🎯 **NEW: Lead Management Integration** - Track 80 clients across Instantly.ai (56) & Bison (24)
- 🎯 **NEW: Campaign Analytics** - Get performance stats, top clients, and weekly summaries
- 🎯 **NEW: Interested Lead Tracking** - Auto-fetch responses with conversation threads
- ✅ **Automatic timezone detection** - No more UTC confusion
- ✅ **Calendar invitations sent automatically** - Attendees actually receive emails now
- ✅ **Full Fathom AI integration** - Access transcripts, summaries, and action items
- ✅ **Multi-account support** - Run multiple instances for different companies/accounts
- ✅ **One-command setup** - New QUICKSTART.sh script for instant installation

## 📋 Table of Contents

- [Quick Start](#-quick-start)
- [Features](#-features)
- [Installation](#-installation)
- [Usage Examples](#-usage-examples)
- [Available Tools](#-available-tools)
- [Troubleshooting](#-troubleshooting)
- [Documentation](#-documentation)

---

## 🎯 Quick Start

**For MacBook Users (Easiest Method):**

```bash
# 1. Clone the repository
git clone https://github.com/jonathangetonapod/gmail-reply-tracker-mcp.git
cd gmail-reply-tracker-mcp

# 2. Run the quick setup script
chmod +x QUICKSTART.sh
./QUICKSTART.sh

# 3. Follow the prompts - it handles everything!
```

**Never touched code before?** We've got you covered:
- 📖 [Mac Setup Guide](MAC_SETUP.md) - 10 simple steps, 30 minutes
- 📖 [Complete Beginner's Guide](BEGINNER_SETUP.md) - Mac & Windows, explained from scratch

---

## 🎨 Features

<table>
<tr>
<td width="50%" valign="top">

### 📧 Gmail

- Smart unreplied email detection
- Automated filtering (newsletters, no-reply)
- Full thread context
- Advanced search (Gmail syntax)
- Inbox analytics
- Send emails & replies
- Draft creation

</td>
<td width="50%" valign="top">

### 📅 Calendar

- Natural language event creation
- Automatic timezone detection
- Email invitations (sent automatically)
- Multi-calendar support
- Event management (CRUD)
- Past & future events
- Meeting coordination

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🎙️ Fathom AI

- List meeting recordings
- Full transcripts with speakers
- AI-generated summaries
- Action item extraction
- Search by title/attendee
- Calendar cross-reference
- Meeting analytics

</td>
<td width="50%" valign="top">

### 🎯 Lead Management

- Track 80 clients (Instantly.ai + Bison)
- Interested lead responses
- Campaign performance analytics
- Top/underperforming client reports
- Weekly summary dashboards
- Conversation thread tracking
- Date validation & fuzzy search

</td>
</tr>
</table>

---

## 💬 Usage Examples

### Email Management
```
"What emails do I need to reply to?"
"Show me unreplied emails from john@company.com"
"Search for emails about the Q4 budget"
"Draft a reply thanking them for the update"
"Send an email to team@company.com about the project"
```

### Lead Management
```
"Show me all our Instantly clients"
"Get interested leads from ABC Corp for the last 7 days"
"Which clients are underperforming this week?"
"Show me top 5 clients by reply rate"
"Generate a weekly summary of all lead generation activity"
```

### Calendar & Scheduling
```
"What's on my calendar this week?"
"Schedule a meeting with sarah@company.com tomorrow at 2pm"
"Create a calendar event for Friday at 3pm and invite the team"
"Cancel my 3pm meeting today"
"Show me all meetings from last week"
```

### Meeting Intelligence (Fathom)
```
"List my recent Fathom meetings"
"Get the transcript from yesterday's client call"
"What action items came out of the engineering sync?"
"Summarize the Project Phoenix kickoff meeting"
"Find all meetings where we discussed the new feature"
```

### Cross-Platform Queries
```
"What's the status of the marketing campaign? Check emails, calendar, and meetings"
"Find all action items from this week across meetings and emails"
"Who have I been meeting with most this month?"
```

---

## 🛠️ Available Tools

**26 tools** available across Gmail, Calendar, and Fathom:

<details>
<summary><b>📧 Gmail Tools (13)</b></summary>

| Tool | Description |
|------|-------------|
| `get_unreplied_emails` | Find emails you've read but haven't replied to |
| `get_email_thread` | Get full conversation history for a thread |
| `search_emails` | Search using Gmail query syntax |
| `get_inbox_summary` | Statistics on unreplied emails |
| `get_unreplied_by_sender` | Filter by sender or domain |
| `send_email` | Send a new email (with confirmation) |
| `reply_to_email` | Reply to a thread (with confirmation) |
| `reply_all_to_email` | Reply all to a thread |
| `create_email_draft` | Create draft without sending |

</details>

<details>
<summary><b>📅 Calendar Tools (7)</b></summary>

| Tool | Description |
|------|-------------|
| `list_calendars` | List all accessible calendars |
| `list_calendar_events` | List upcoming events |
| `list_past_calendar_events` | List past events |
| `create_calendar_event` | Create new event (auto-sends invites) |
| `update_calendar_event` | Update existing event |
| `delete_calendar_event` | Delete an event |
| `quick_add_calendar_event` | Create event with natural language |

</details>

<details>
<summary><b>🎙️ Fathom Tools (6)</b></summary>

| Tool | Description |
|------|-------------|
| `list_fathom_meetings` | List recent meeting recordings |
| `get_fathom_transcript` | Get full meeting transcript |
| `get_fathom_summary` | Get AI-generated summary |
| `get_fathom_action_items` | Extract action items |
| `search_fathom_meetings_by_title` | Search meetings by title |
| `search_fathom_meetings_by_attendee` | Find meetings with specific people |

</details>

## 📦 Installation

### Prerequisites

- Python 3.10+ ([Download](https://www.python.org/downloads/))
- Gmail account
- Google Cloud Project ([Create one](https://console.cloud.google.com))
- Claude Desktop ([Download](https://claude.ai/download))
- (Optional) Fathom AI account with API access

### Installation Options

<details open>
<summary><b>⚡ Option 1: Quickstart Script (Recommended for Mac)</b></summary>

```bash
# Clone the repository
git clone https://github.com/jonathangetonapod/gmail-reply-tracker-mcp.git
cd gmail-reply-tracker-mcp

# Run the magic script
chmod +x QUICKSTART.sh
./QUICKSTART.sh
```

The script will:
- ✅ Create virtual environment
- ✅ Install all dependencies
- ✅ Check for credentials
- ✅ Run OAuth authentication
- ✅ Generate Claude Desktop config

</details>

<details>
<summary><b>📖 Option 2: Step-by-Step Guides (For Beginners)</b></summary>

Choose your operating system:
- **[Mac Setup Guide](MAC_SETUP.md)** - 10 simple steps, 30 minutes
- **[Complete Beginner's Guide](BEGINNER_SETUP.md)** - Mac & Windows, zero coding knowledge required

Both guides explain everything from scratch, including Python installation and Terminal basics.

</details>

<details>
<summary><b>🔧 Option 3: Manual Installation (For Developers)</b></summary>

#### 1. Clone Repository

```bash
git clone https://github.com/jonathangetonapod/gmail-reply-tracker-mcp.git
cd gmail-reply-tracker-mcp
```

#### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate    # Windows
```

#### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 4. Set Up Google Cloud Project

Follow [SETUP_GUIDE.md](SETUP_GUIDE.md) for detailed Google Cloud setup, or quick version:

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create new project → Enable Gmail API & Calendar API
3. Create OAuth Desktop credentials → Download as `credentials.json`
4. Move to `credentials/credentials.json`
5. Run: `python setup_oauth.py` (opens browser for auth)

#### 5. Configure Environment

```bash
cp .env.example .env
# Edit .env and add your Fathom API key (optional)
```

#### 6. Configure Claude Desktop

Edit your Claude Desktop config:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "gmail-calendar-fathom": {
      "command": "/ABSOLUTE/PATH/TO/PROJECT/venv/bin/python3",
      "args": ["/ABSOLUTE/PATH/TO/PROJECT/src/server.py"],
      "env": {
        "GMAIL_CREDENTIALS_PATH": "/ABSOLUTE/PATH/TO/PROJECT/credentials/credentials.json",
        "GMAIL_TOKEN_PATH": "/ABSOLUTE/PATH/TO/PROJECT/credentials/token.json",
        "GMAIL_OAUTH_SCOPES": "https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar",
        "FATHOM_API_KEY": "your_fathom_api_key_here"
      }
    }
  }
}
```

**Important:** Replace `/ABSOLUTE/PATH/TO/PROJECT` with your actual path (e.g., `/Users/yourname/gmail-reply-tracker-mcp`)

#### 7. Restart Claude Desktop

Quit and reopen Claude Desktop. You should see the MCP server connected!

</details>

---

## 🏗️ Project Structure

```
gmail-calendar-fathom/
├── src/
│   ├── server.py              # MCP server (26 tools)
│   ├── gmail_client.py        # Gmail API wrapper
│   ├── calendar_client.py     # Calendar API wrapper
│   ├── fathom_client.py       # Fathom AI wrapper
│   ├── email_analyzer.py      # Email intelligence
│   ├── auth.py                # OAuth handler
│   └── config.py              # Configuration
├── credentials/               # OAuth files (gitignored)
├── tests/                     # Unit tests
├── QUICKSTART.sh              # Automated setup script
├── MAC_SETUP.md               # Mac guide
├── BEGINNER_SETUP.md          # Beginner guide
├── requirements.txt           # Dependencies
└── .env                       # Config (gitignored)
```

---

## 🔧 Troubleshooting

<details>
<summary><b>🔐 Authentication Issues</b></summary>

**"Credentials file not found"**
- Download `credentials.json` from Google Cloud Console
- Place in `credentials/` directory

**"Authentication failed" or "Permission denied"**
```bash
# Delete token and re-authenticate
rm credentials/token.json
python setup_oauth.py
```

**"Error 403: org_internal"**
- OAuth consent screen must be set to **External** (not Internal)
- Create NEW credentials after changing to External
- See [SETUP_GUIDE.md](SETUP_GUIDE.md) for details

</details>

<details>
<summary><b>🔌 Claude Desktop Connection Issues</b></summary>

**Tools not appearing**
1. Use **absolute paths** (not `./` or `~/`)
2. Use venv python path: `/path/to/project/venv/bin/python3`
3. Restart Claude Desktop (Quit completely and reopen)
4. Check Claude logs for errors

**Two Gmail sign-in windows on startup**
- Tokens may be expired - run `python setup_oauth.py` to refresh
- Check that each MCP instance uses unique token paths

</details>

<details>
<summary><b>⚙️ Functionality Issues</b></summary>

**Calendar invitations not sent**
- Update to latest version: `git pull origin main`
- Restart Claude Desktop

**Calendar events at wrong time**
- Update to latest version (includes auto timezone detection)
- Restart Claude Desktop

**Fathom tools not available**
- Add `FATHOM_API_KEY` to `.env` file
- Get API key from https://fathom.video Settings > API
- Restart Claude Desktop

**Rate limit errors**
- Wait a few minutes
- Reduce `max_results` in queries
- Adjust `GMAIL_API_MAX_REQUESTS_PER_MINUTE` in `.env`

</details>

---

## 🔒 Security & Privacy

**What This Accesses:**
- Gmail (read/write via `gmail.modify` scope)
- Google Calendar (full access)
- Fathom AI (read-only via API key)

**Data Storage:**
- OAuth tokens stored locally in `credentials/token.json`
- No email data cached or stored
- All processing happens locally
- No third-party servers involved

**Best Practices:**
- Never commit `credentials/` to git (automatically ignored)
- Tokens have restrictive file permissions (600)
- Revoke access anytime: [Google Account Security](https://myaccount.google.com/permissions)

---

## 💡 FAQ

<details>
<summary><b>Can I use this with multiple accounts?</b></summary>

Yes! Create separate directories for each account:
```bash
~/GetOnAPod_MCPs/account1/
~/GetOnAPod_MCPs/account2/
```

Each gets its own credentials and MCP server entry in Claude Desktop config. See [SETUP_GUIDE.md](SETUP_GUIDE.md) for multi-account setup.

</details>

<details>
<summary><b>Works with Google Workspace?</b></summary>

Yes! Just ensure your organization allows third-party OAuth apps.

</details>

<details>
<summary><b>Can I customize email filtering?</b></summary>

Yes! Edit `AUTOMATED_FROM_PATTERNS` in `src/email_analyzer.py` to add your own automation patterns.

</details>

<details>
<summary><b>How do I share this with my team?</b></summary>

Each person needs:
1. Their own Google Cloud Project & credentials
2. Clone this repo & run setup
3. Configure their Claude Desktop

</details>

---

## 🗺️ Roadmap

- [ ] Slack integration
- [ ] Email templates & quick replies
- [ ] Advanced Fathom analytics
- [ ] Smart scheduling suggestions
- [ ] Email auto-categorization
- [ ] Meeting prep summaries

---

## 📚 Documentation

- **[Setup Guide](SETUP_GUIDE.md)** - Detailed Google Cloud setup
- **[Mac Guide](MAC_SETUP.md)** - 10-step Mac setup (30 mins)
- **[Beginner Guide](BEGINNER_SETUP.md)** - Zero-to-hero for non-coders
- **[Gmail API Docs](https://developers.google.com/gmail/api)** - Official Gmail API reference
- **[MCP Documentation](https://modelcontextprotocol.io/)** - Model Context Protocol

---

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

Run tests: `pytest`

---

## 📝 Changelog

**v1.2.0** (December 2024)
- ✨ Automatic timezone detection
- ✨ Calendar invitations sent automatically
- 🐛 Fixed multiple authentication bugs
- 📚 Added QUICKSTART.sh script

**v1.1.0** (December 2024)
- ✨ Fathom AI integration (6 new tools)
- ✨ Cross-platform search

**v1.0.0** (December 2024)
- 🎉 Initial release
- ✨ Gmail reply tracking
- ✨ Calendar management

---

## 📜 License

MIT License - See [LICENSE](LICENSE) for details

---

<div align="center">

**Built with [Model Context Protocol](https://modelcontextprotocol.io/)**

Powered by [Claude](https://claude.ai) • Uses [Gmail API](https://developers.google.com/gmail/api) & [Google Calendar API](https://developers.google.com/calendar)

⭐ Star this repo if you found it helpful!

[Report Bug](https://github.com/jonathangetonapod/gmail-reply-tracker-mcp/issues) • [Request Feature](https://github.com/jonathangetonapod/gmail-reply-tracker-mcp/issues)

</div>
