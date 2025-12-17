<div align="center">

# 📬 Gmail + Calendar + Fathom + Leads MCP Server

### Production-Ready Multi-Tenant MCP Server with One-Command Setup

*Transform Claude into your AI productivity command center with 34 tools across Gmail, Calendar, Fathom AI, and lead management platforms*

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)
[![Railway](https://img.shields.io/badge/Deploy-Railway-blueviolet)](https://railway.app)

[Quick Start](#-quick-start) • [Features](#-what-you-can-do) • [Architecture](#-architecture) • [Installation](#-installation)

</div>

---

## 🚀 What This Is

A **production-ready multi-tenant MCP server** that connects Claude to your entire productivity stack with natural language. Deploy once, serve multiple users.

### Two Deployment Models

**1. Multi-Tenant Railway Server** (Recommended for teams)
- Deploy once on Railway, serve unlimited users
- Web-based OAuth flow - no credentials.json needed
- Session-based authentication
- Automatic scaling

**2. Local Installation** (Individual use)
- One-command installation with beautiful UX
- Runs locally on your machine
- Full control and privacy
- Zero ongoing costs

---

## ✨ What You Can Do

Ask Claude things like:

> **📧 Email Management**:
> - "Show me unreplied emails from the last 3 days"
> - "Reply to the thread from john@company.com about the proposal"
> - "Create a draft email to sarah@example.com about the meeting"
>
> **📅 Calendar & Scheduling**:
> - "Schedule a meeting with sarah@company.com tomorrow at 2pm and send invites"
> - "Create a 30-minute call with john@company.com on Friday at 3pm" (automatically adds Google Meet link!)
> - "What do I have on my calendar this week?"
> - "Create a recurring meeting every Monday at 10am"
>
> **🎙️ Meeting Intelligence**:
> - "What were the action items from yesterday's client call?"
> - "Summarize the meeting with [Client Name] from last week"
> - "Show me all meetings where we discussed pricing"
>
> **🎯 Campaign Creation**:
> - "Create a Bison campaign for Michael Hernandez with a 3-step sequence"
> - "Set up an Instantly campaign for Brian Bliss targeting speakers"
> - "Use fuzzy matching to find client 'source 1 parcel' and create a campaign"
>
> **📊 Lead Analytics**:
> - "Show me interested leads from our top performing clients this week"
> - "Which clients are underperforming and need attention?"
> - "Get campaign statistics for all Instantly clients this month"

---

## 🎯 Key Features

### 34 Production Tools Across 4 Platforms

<table>
<tr>
<td width="50%" valign="top">

**📧 Gmail (13 tools)**
- Unreplied email detection with smart filtering
- Thread context & conversation history
- Send emails & reply to threads
- Draft management
- Inbox analytics & label management
- Search with Gmail query syntax

**📅 Google Calendar (7 tools)**
- Natural language scheduling ("tomorrow at 2pm")
- Automatic timezone detection
- Email invitations sent to attendees
- Multi-calendar support
- Event CRUD operations
- Quick add with natural language

</td>
<td width="50%" valign="top">

**🎙️ Fathom AI (6 tools)**
- Meeting transcripts with timestamps
- AI-generated summaries
- Action item extraction
- Search by title or attendee
- Calendar event cross-reference
- Meeting analytics

**🎯 Campaign Management (8 tools)**
- **Bison** & **Instantly** integrations
- Create email campaigns with sequences
- Auto-convert placeholders ({{firstname}} → {FIRST_NAME})
- HTML email formatting for Instantly
- Campaign analytics & performance tracking
- Interested lead identification
- Fuzzy client name matching
- Track 88+ clients across both platforms

</td>
</tr>
</table>

### 🆕 Latest Features (v2.3.1)

- 🎥 **Automatic Google Meet Links** - Calendar events with attendees automatically include video conference links
- 📧 **Meet Links in Email Invites** - Invitations prominently display the Google Meet link with one-click join
- ⚙️ **Smart Auto-Detection** - Intelligently adds Meet links only when needed (events with attendees)

### Recent Features (v2.3.0)

- ✨ **Instantly HTML Formatting** - Email bodies display with proper line breaks and paragraph spacing
- 🔧 **Bison Placeholder Conversion** - Automatic conversion of {{firstname}}, {{company}} to Bison format
- 🔍 **Fuzzy Client Name Matching** - Tolerates typos and partial names ("brian blis" finds "Brian Bliss")
- 🔒 **Privacy & Security Modal** - Crystal-clear explanation of data access on setup page
- 🧪 **Unit Test Suite** - 18 comprehensive tests covering all campaign features
- 📊 **Visual Feature Timeline** - Beautiful "What's New" page showing all updates

---

## 🏗️ Architecture

### Multi-Tenant Railway Deployment

```
┌─────────────┐
│   Railway   │  ← Deploy once, serve everyone
│   Server    │
│             │  • Web OAuth flow
│  34 Tools  │  • Session management
│             │  • Multi-user support
└──────┬──────┘
       │
       ├──── User 1 (session token)
       ├──── User 2 (session token)
       └──── User N (session token)
```

**Key Advantages:**
- ✅ No credentials.json distribution
- ✅ Centralized updates
- ✅ Web-based authentication
- ✅ Automatic scaling
- ✅ Zero client-side setup

### Hybrid Local Installation

```
┌──────────────────┐
│ Railway Setup    │  ← OAuth flow only
│ Page (Web)       │
│                  │
│ User enters:     │
│ • Email          │
│ • Fathom API key │
│                  │
│ Gets: One command│
└────────┬─────────┘
         │
         ↓
┌──────────────────┐
│ Local Machine    │  ← MCP runs here
│                  │
│ One command:     │
│ • Installs deps  │
│ • Configures     │
│ • Authenticates  │
│ • Updates Claude │
└──────────────────┘
```

**Key Advantages:**
- ✅ One-command setup
- ✅ Beautiful UX for non-technical users
- ✅ Runs locally (full privacy)
- ✅ Auto-detects & closes Claude Desktop
- ✅ Step-by-step progress (1 of 9, 2 of 9...)
- ✅ Friendly error messages

---

## 📦 Quick Start

### Option 1: Multi-Tenant Railway (Teams)

**Deploy the server:**

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template)

1. Click "Deploy on Railway"
2. Set environment variables (guide: [RAILWAY_SETUP.md](RAILWAY_SETUP.md))
3. Share your Railway URL with users
4. Users authenticate via web OAuth

**User setup:**
Users just need to:
1. Visit your Railway URL
2. Click "Authorize Gmail & Calendar"
3. Get their session token
4. Add MCP server to Claude Desktop config

### Option 2: Local Installation (Individual)

**For non-technical users:**

1. Visit: `https://your-railway-url.railway.app/setup`
2. Enter your email + optional Fathom API key
3. Copy the one-line command
4. Paste in Terminal and press Enter
5. Follow the beautiful step-by-step progress

**The script handles everything:**
- ✅ Installs Homebrew (if needed)
- ✅ Installs Python 3.11+ (if needed)
- ✅ Installs Git (if needed)
- ✅ Downloads the project
- ✅ Creates virtual environment
- ✅ Installs dependencies
- ✅ Runs OAuth (opens browser)
- ✅ Updates Claude Desktop config
- ✅ Auto-detects & closes Claude if running

**Total time:** 5-10 minutes (mostly automated)

---

## 🛠️ Complete Tool List

### 📧 Gmail Tools (13)

| Tool | Description |
|------|-------------|
| `get_unreplied_emails` | Find unre plied emails with smart filtering |
| `get_email_thread` | Full conversation history |
| `search_emails` | Gmail query syntax search |
| `get_inbox_summary` | Inbox statistics |
| `get_unreplied_by_sender` | Filter by sender/domain |
| `send_email` | Send new email |
| `reply_to_email` | Reply to thread |
| `reply_all_to_email` | Reply all |
| `create_email_draft` | Create draft |
| `get_recent_emails` | Recent emails |
| `get_email_by_id` | Get specific email |
| `list_email_labels` | List all labels |
| `modify_email_labels` | Add/remove labels |

### 📅 Calendar Tools (7)

| Tool | Description |
|------|-------------|
| `list_calendars` | All accessible calendars |
| `list_calendar_events` | Upcoming events |
| `list_past_calendar_events` | Past events |
| `create_calendar_event` | Create event (auto-invites) |
| `update_calendar_event` | Update event |
| `delete_calendar_event` | Delete event |
| `quick_add_calendar_event` | Natural language creation |

### 🎙️ Fathom Tools (6)

| Tool | Description |
|------|-------------|
| `list_fathom_meetings` | Recent recordings |
| `get_fathom_transcript` | Full transcript |
| `get_fathom_summary` | AI summary |
| `get_fathom_action_items` | Action items |
| `search_fathom_meetings_by_title` | Search by title |
| `search_fathom_meetings_by_attendee` | Search by attendee |

### 🎯 Campaign Management Tools (8)

| Tool | Description |
|------|-------------|
| `get_all_clients` | All 88+ clients (Instantly + Bison) with fuzzy name matching |
| `get_instantly_clients` | 64 Instantly.ai clients with workspace IDs and API keys |
| `get_bison_clients` | 24 Bison clients with API credentials |
| `create_bison_campaign` | Create email sequence with automatic placeholder conversion |
| `create_instantly_campaign` | Create campaign with HTML formatting and sequences |
| `get_client_campaigns` | Fetch campaign analytics and performance metrics |
| `get_interested_leads` | Identify and track positive lead responses |
| `get_campaign_statistics` | Weekly/monthly analytics dashboard |

**Campaign Creation Features:**
- 🔄 **Auto Placeholder Conversion**: `{{firstname}}`, `{{company}}` → `{FIRST_NAME}`, `{COMPANY_NAME}`
- 🎨 **HTML Email Formatting**: Converts plain text to proper `<div>` structure for Instantly
- 🔍 **Fuzzy Client Matching**: Find clients with typos ("michael hernandex" → "Michael Hernandez")
- 📧 **Multi-Step Sequences**: Create follow-up sequences with custom wait times
- 📊 **Performance Tracking**: Monitor reply rates, interested leads, and campaign success

**Total: 34 tools** 🎉

---

## 📊 Production Features

### For Developers

- ✅ **18+ unit tests** - Campaign feature test coverage with mocked API calls
- ✅ **Type hints** - Complete type safety across all modules
- ✅ **Error handling** - Friendly error messages with recovery steps
- ✅ **Rate limiting** - API quota management for Gmail/Calendar
- ✅ **Logging** - Comprehensive debug logs for troubleshooting
- ✅ **OAuth 2.0** - Secure authentication with encrypted token storage
- ✅ **Session management** - Multi-tenant support with SQLite
- ✅ **SQLite database** - User session and credential storage
- ✅ **Fuzzy matching** - Client name search with 60% similarity threshold
- ✅ **HTML conversion** - Automatic email body formatting for Instantly

### For Users

- ✅ **Automatic timezone detection** - No more UTC confusion
- ✅ **Calendar invitations sent automatically** - Attendees get emails
- ✅ **Smart email filtering** - Auto-filters newsletters/automated emails
- ✅ **Step-by-step progress** - Beautiful installation UX
- ✅ **Auto-recovery** - Handles errors gracefully
- ✅ **Cross-platform** - macOS & Linux support

---

## 🔧 Advanced Setup

### Railway Multi-Tenant Deployment

See [RAILWAY_SETUP.md](RAILWAY_SETUP.md) for complete deployment guide.

**Environment variables needed:**
```env
# Required
LEAD_SHEETS_URL=https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID
LEAD_SHEETS_GID_INSTANTLY=0
LEAD_SHEETS_GID_BISON=123456789

# Optional
FATHOM_API_KEY=your_key_here
PORT=8080
```

### Manual Local Installation

For developers who want full control:

```bash
# 1. Clone
git clone https://github.com/jonathangetonapod/gmail-reply-tracker-mcp.git
cd gmail-reply-tracker-mcp

# 2. Create venv
python3 -m venv venv
source venv/bin/activate

# 3. Install deps
pip install -r requirements.txt

# 4. Setup OAuth
mkdir -p credentials
# Download credentials.json from Google Cloud Console
# Place in credentials/credentials.json
python setup_oauth.py

# 5. Configure Claude Desktop
# Edit: ~/Library/Application Support/Claude/claude_desktop_config.json
# Add MCP server config (see docs)

# 6. Restart Claude Desktop
```

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for detailed manual installation.

---

## 🏆 What Makes This Special

### 1. Production-Ready Architecture

- Multi-tenant from day one
- Session-based authentication
- Proper error handling
- Comprehensive logging
- 41 unit tests

### 2. Amazing User Experience

- One-command installation
- Step-by-step progress indicators
- Auto-detects and closes Claude Desktop
- Friendly error messages with recovery steps
- Password warnings before sudo prompts
- OAuth flow with fallback instructions

### 3. Solved Hard Problems

- **Railway Python bytecode caching** - Inlined logic to bypass cache
- **Google OAuth scope validation** - Handles 'openid' scope addition
- **Multi-tenant session management** - SQLite + encrypted tokens
- **Timezone auto-detection** - No more UTC confusion
- **Calendar invitations** - Actually sends emails to attendees

### 4. Comprehensive Integration

- 34 tools across 4 platforms
- Lead management with 88 clients
- Google Sheets as database
- Campaign analytics
- Interested lead tracking

---

## 📚 Documentation

- **[Railway Setup Guide](RAILWAY_SETUP.md)** - Multi-tenant deployment
- **[Setup Guide](SETUP_GUIDE.md)** - Manual installation
- **[Testing Guide](TESTING.md)** - Running tests
- **[Contributing Guide](CONTRIBUTING.md)** - For contributors

### 🆕 What's New Feature

Visit `/changelog` on your Railway deployment to see a beautiful visual timeline of all updates:
- Version history with release dates
- Feature highlights with icons and descriptions
- Breaking changes warnings
- Technical notes for developers
- Accessible from setup page via "✨ What's New" button

This helps your team stay informed about new features and decide when to update!

---

## 🔒 Security & Privacy

### Multi-Tenant Model
- OAuth tokens encrypted in SQLite
- Session-based authentication
- No credentials.json distribution
- Server-side token management

### Local Model
- OAuth tokens stored locally
- File permissions set to 600
- No third-party servers
- All processing local

### Best Practices
- Never commit credentials
- Revoke access anytime: [Google Account](https://myaccount.google.com/permissions)
- Regular security audits
- Minimal scope requests

---

## 🚀 Roadmap

- [ ] Slack integration (10+ tools)
- [ ] Email templates & quick replies
- [ ] Advanced Fathom analytics
- [ ] Smart scheduling suggestions
- [ ] Email auto-categorization
- [ ] Meeting prep summaries
- [ ] Multi-language support
- [ ] Mobile OAuth flow

---

## 📝 Changelog

> 💡 **See full visual timeline**: Visit `/changelog` on your Railway deployment for a beautiful timeline view!

**v2.3.1** (December 17, 2024) - **Google Meet Integration**
- 🎥 **Automatic Google Meet Links** - Calendar events with attendees automatically include video conference links
- 📧 **Meet Links in Email Invites** - Invitations prominently display the Google Meet link for one-click joining
- ⚙️ **Smart Auto-Detection** - Intelligently adds Meet links only when attendees are present
- 📞 **Phone Dial-In Included** - Meet links come with phone numbers and PINs for maximum accessibility
- 🐛 **Technical**: Added conferenceData support, add_meet_link parameter, meet_link in API responses

**v2.3.0** (December 17, 2024) - **Campaign Automation & Privacy Enhancements**
- ✨ **Instantly HTML Formatting** - Email bodies now display with proper line breaks and paragraph spacing
- 🔧 **Bison Placeholder Conversion** - Placeholders like `{{firstname}}` correctly convert to `{FIRST_NAME}` format
- 🔍 **Fuzzy Client Name Matching** - Search for "brian blis" and find "Brian Bliss" (60% similarity threshold)
- 🔒 **Privacy & Security Modal** - Crystal-clear explanation of what admin can/cannot access
- 🧪 **Unit Test Suite** - 18 comprehensive tests covering all campaign features
- 📊 **Visual Feature Timeline** - Beautiful "What's New" page showing all updates
- 🐛 **Technical**: Added rapidfuzz>=3.0.0 dependency, HTML `<div>` structure for Instantly campaigns

**v2.2.0** (December 10, 2024) - **Multi-Client Campaign Management**
- 🎯 **Bison & Instantly Integration** - Create campaigns for 88+ clients across both platforms
- 📊 **Campaign Analytics** - Track performance with reply rates and interested leads
- 📧 **Google Sheets as Database** - Multi-column CSV export for client management

**v2.1.0** (November 28, 2024) - **Fathom AI Integration**
- 🎙️ **Meeting Intelligence** - 6 tools for transcripts, summaries, and action items
- 🔍 **Meeting Search** - Search by title or attendee
- 📅 **Calendar Cross-Reference** - Link Fathom meetings to calendar events

**v2.0.0** (November 15, 2024) - **Multi-Tenant Railway Deployment**
- 🎉 **Major**: Multi-tenant Railway deployment with web OAuth flow
- 🎉 **Major**: Lead management integration (8 tools)
- ✨ One-command installation with beautiful UX
- ✨ 88 clients tracked (64 Instantly + 24 Bison)
- ✨ Auto-detect and close Claude Desktop
- ✨ Step-by-step progress indicators (1 of 9, 2 of 9...)
- 🐛 Fixed Railway Python bytecode caching
- 🐛 Fixed Google OAuth scope validation
- 📦 Expanded from 26 to 34 tools

**v1.2.0** (December 2024)
- ✨ Automatic timezone detection
- ✨ Calendar invitations sent automatically
- 🐛 Fixed multiple authentication bugs

**v1.0.0** (December 2024)
- 🎉 Initial release
- ✨ Gmail + Calendar + Fathom (26 tools)

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing`
3. Add tests for new functionality
4. Ensure tests pass: `pytest`
5. Submit pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## 📜 License

MIT License - See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

Built with:
- [Model Context Protocol](https://modelcontextprotocol.io/) - MCP framework
- [Gmail API](https://developers.google.com/gmail/api) - Email integration
- [Google Calendar API](https://developers.google.com/calendar) - Calendar integration
- [Fathom AI API](https://fathom.video) - Meeting intelligence
- [Railway](https://railway.app) - Multi-tenant hosting

---

<div align="center">

**Production-ready multi-tenant MCP server with 34 tools**

⭐ Star this repo if you found it helpful!

[Report Bug](https://github.com/jonathangetonapod/gmail-reply-tracker-mcp/issues) • [Request Feature](https://github.com/jonathangetonapod/gmail-reply-tracker-mcp/issues) • [Documentation](https://github.com/jonathangetonapod/gmail-reply-tracker-mcp/wiki)

Made with ❤️ by the GetOnAPod team

</div>
