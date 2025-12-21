<div align="center">

# 📬 Gmail + Calendar + Docs + Sheets + Fathom + Leads MCP Server

### Production-Ready Multi-Tenant MCP Server with One-Command Setup

*Transform Claude into your AI productivity command center with 77 tools across Gmail, Calendar, Google Docs, Google Sheets, Fathom AI, campaign management, lead intelligence, mailbox health monitoring, and spam detection platforms*

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
> **💎 Hidden Gems (AI Lead Intelligence)**:
> - "Find hidden gems for Lena Kadriu in the last 90 days"
> - "Show me missed opportunities for Michael Hernandez this month"
> - "Analyze Rick Pendrick's replies and mark any interested leads"
> - *AI analyzes ALL replies, identifies HOT/WARM leads that weren't marked, and marks them with one click*
>
> **📊 Lead Analytics**:
> - "Show me interested leads from our top performing clients this week"
> - "Which clients are underperforming and need attention?"
> - "Get campaign statistics for all Instantly clients this month"
>
> **🛡️ Spam Detection**:
> - "Check spam in Instantly campaigns for Brian Bliss"
> - "Scan the Bison campaign for Michael Hernandez for spam words"
> - "Check if this subject line is spammy: 'FREE OFFER - Act Now!!!'"

---

## 🎯 Key Features

### 77 Production Tools Across 9 Categories

<table>
<tr>
<td width="50%" valign="top">

**📧 Gmail (13 tools)**
- Unreplied email detection with smart filtering
- Thread context & conversation history
- Send emails, replies, and reply-all
- Draft management
- Search with Gmail query syntax
- Label management
- Inbox statistics and recent emails

**📅 Google Calendar (7 tools)**
- Natural language scheduling ("tomorrow at 2pm")
- Automatic timezone detection & Google Meet links
- Email invitations sent to attendees automatically
- Multi-calendar support
- Event CRUD operations
- Quick add with natural language

**🎙️ Fathom AI (6 tools)**
- Meeting transcripts with timestamps
- AI-generated summaries
- Action item extraction
- Search by title or attendee
- Calendar event cross-reference
- Meeting analytics

**📝 Google Docs (9 tools)**
- Create, read, and edit documents
- Append and insert content
- Find and replace text
- Add formatted headings (H1-H6)
- Create tables with data
- Professional formatting & styling
- Multi-tenant safe with per-user OAuth

**📊 Google Sheets (18 tools)**
- Full CRUD operations on spreadsheets
- Professional cell formatting
- Insert/delete rows & columns
- Sort, filter, and organize data
- Freeze headers and auto-resize columns
- A1 notation support with RGB colors

</td>
<td width="50%" valign="top">

**🎯 Campaign Management (10 tools)**
- **Bison** & **Instantly** integrations
- Create email campaigns with sequences
- Auto-convert placeholders ({{firstname}} → {FIRST_NAME})
- HTML email formatting for Instantly
- Campaign analytics & performance tracking
- Fuzzy client name matching (60% similarity)
- Track 89+ clients across both platforms

**💎 Lead Intelligence (14 tools)**
- **Hidden Gems** - AI-powered missed opportunity detection
- HOT/WARM/COLD lead categorization with Claude API
- Interested lead identification & tracking
- One-click marking (green "Interested" tag on first reply)
- Smart deduplication (1 person = 1 hidden gem)
- Cross-platform support (Instantly + Bison)

**🛡️ Spam Detection (3 tools)**
- Ad-hoc subject & body spam checking
- Bison campaign sequence scanning
- Instantly campaign variant scanning
- EmailGuard API integration

**📮 Mailbox Health Monitoring (5 tools)**
- **Instantly & Bison** email account monitoring
- Real-time warmup scores (0-100 scale)
- Health classification (healthy/early/at_risk)
- Daily sending capacity tracking
- Multi-platform aggregated dashboard

</td>
</tr>
</table>

### 🆕 Latest Features (v2.7.0 - December 21, 2025)

- 📮 **Mailbox Health Monitoring** - Added 5 new tools for email account monitoring (77 total)
- 🔍 **Instantly Account Health** - Track warmup scores, daily limits, and account status across all workspaces
- 📊 **Bison Sender Email Monitoring** - Monitor all sender email accounts with real-time connection status
- 🚨 **Unhealthy Mailbox Alerts** - Automatically identify at-risk accounts requiring attention
- 📈 **Capacity Planning** - Aggregate daily sending limits across all healthy accounts
- 🎯 **Health Classification** - 3-tier system: healthy (active/connected), early (paused), at_risk (errors)

### Recent Features (v2.6.1 - December 21, 2025)

- 📝 **Enhanced Google Docs** - Added 3 new tools: tables, formatting, professional styling (9 total)
- 📊 **Table Creation** - Insert structured tables with header row support and custom formatting
- 🎨 **Professional Formatting** - One-command styling for titles, headings, and consistent spacing
- ✨ **Find & Format** - Search for specific text and apply RGB colors, bold, italic, font sizes
- 📚 **Complete Documentation** - Updated README and examples with all 72 tools across 8 platforms

### Recent Features (v2.5.0 - December 19, 2025)

- 📝 **Google Docs Integration** - 6 new tools for document creation, editing, and formatting (51 total tools)
- 🔐 **Per-User OAuth** - Each user's Google Docs access fully isolated with encrypted credential storage
- 📋 **Real-Time Document Management** - Create, read, edit, append, insert, replace text, add headings
- 🎯 **Template Population** - Find and replace for populating document templates
- ⚡ **Production-Ready** - Thread-safe rate limiting (60 req/min), automatic retries, 100+ unit tests

### Recent Features (v2.5.1 - December 20, 2025)

- 🔧 **Fixed Bison Pagination** - Now fetches all 50-80+ sender emails per client (was only 15)
- 🎯 **Already-Interested Detection** - Fixed detection of leads marked via client replies
- ✅ **Eliminated False Positives** - Client emails no longer appear as interested leads

### Features (v2.3.0)

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
│  72 Tools  │  • Session management
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

## 🛠️ Complete Tool List (77 Tools)

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

### 📝 Google Docs Tools (9)

| Tool | Description |
|------|-------------|
| `create_google_doc` | Create new documents |
| `read_google_doc` | Read document content |
| `append_to_google_doc` | Add content to end |
| `insert_into_google_doc` | Insert at specific position |
| `replace_text_in_google_doc` | Find and replace |
| `add_heading_to_google_doc` | Add formatted headings (H1-H6) |
| `create_table_in_google_doc` | Insert tables with data |
| `format_google_doc_section` | Find and format text |
| `format_google_doc_professional` | Apply professional styling |

### 📊 Google Sheets Tools (18)

| Tool | Description |
|------|-------------|
| `create_spreadsheet` | Create new spreadsheets |
| `read_spreadsheet` | Read data from ranges |
| `append_to_spreadsheet` | Append rows to end |
| `update_spreadsheet` | Update specific cells |
| `clear_spreadsheet_range` | Clear values |
| `find_replace_in_spreadsheet` | Find and replace text |
| `delete_spreadsheet_rows` | Delete specific rows |
| `delete_spreadsheet_columns` | Delete specific columns |
| `add_sheet_to_spreadsheet` | Create new tabs |
| `delete_sheet_from_spreadsheet` | Delete tabs |
| `list_sheets_in_spreadsheet` | List all tabs |
| `rename_spreadsheet_sheet` | Rename tabs |
| `insert_spreadsheet_rows` | Insert blank rows |
| `insert_spreadsheet_columns` | Insert blank columns |
| `format_spreadsheet_cells` | Apply styling |
| `sort_spreadsheet_range` | Sort by column |
| `freeze_spreadsheet_rows_columns` | Freeze headers |
| `auto_resize_spreadsheet_columns` | Auto-fit widths |

### 🎯 Campaign Management Tools (4)

| Tool | Description |
|------|-------------|
| `create_bison_sequence` | Create Bison email sequence |
| `create_instantly_campaign` | Create Instantly campaign |
| `check_campaign_spam` | Check campaign for spam |
| `check_text_spam` | Check text for spam |

### 💎 Lead Intelligence Tools (14)

| Tool | Description |
|------|-------------|
| `get_all_clients_with_positive_replies` | Fast parallel search across all clients |
| `get_all_active_clients` | Find clients with recent campaign activity |
| `get_active_instantly_clients` | Instantly clients with sent emails |
| `get_active_bison_clients` | Bison clients with sent emails |
| `get_client_lead_details` | Detailed lead responses for specific client |
| `find_missed_opportunities` | Find hidden gems - interested leads AI missed |
| `mark_lead_as_interested` | Mark leads across Instantly & Bison |
| `get_all_lead_clients` | All clients from both platforms |
| `get_lead_platform_stats` | Aggregated stats across platforms |
| `get_top_clients` | Top performing clients by metric |
| `get_underperforming_clients_list` | Clients below threshold |
| `get_lead_weekly_summary` | Comprehensive weekly report |
| `get_instantly_clients` | All Instantly workspaces |
| `get_bison_clients` | All Bison clients |

**Lead Intelligence Features:**
- 💎 **Hidden Gems**: AI finds interested leads that other AIs missed with HOT/WARM/COLD scoring
- 🔧 **Fixed Pagination**: Fetches all 50-80+ sender emails per client (eliminates false positives)
- 🎯 **Dual-Marking**: Automatically marks both responder AND original lead for forwarded replies
- ⚡ **Parallel Processing**: Fast search across 88+ clients in seconds
- 🔍 **Multi-Layer Detection**: API → Keywords → Claude → Timing validation

### 🛡️ Spam Detection Tools (1)

| Tool | Description |
|------|-------------|
| `check_text_spam` | Check any email text for spam words with EmailGuard API |

**Spam Detection Features:**
- 🛡️ **EmailGuard API Integration**: Industry-standard spam detection with scoring
- 💬 **User-Friendly Error Messages**: Clear explanations for quota limits and rate limiting
- 📊 **Detailed Reports**: Spam scores, word counts, and specific spam words identified
- ⚠️ **Smart Error Handling**: Graceful handling of API quota exhaustion

### 📮 Mailbox Health Monitoring Tools (5)

| Tool | Description |
|------|-------------|
| `get_instantly_mailbox_health` | Monitor Instantly email accounts with warmup scores and status |
| `get_bison_mailbox_health` | Monitor Bison sender email accounts with connection status |
| `get_all_mailbox_health_summary` | Aggregated health dashboard across all platforms |
| `get_unhealthy_mailboxes_alert` | Filter for at-risk accounts requiring attention |
| `get_mailbox_capacity_report` | Calculate total daily sending capacity |

**Mailbox Health Monitoring Features:**
- 📮 **Multi-Platform Support**: Monitor both Instantly and Bison email accounts
- 🔍 **Warmup Score Tracking**: Real-time warmup scores (0-100) for Instantly accounts
- 📊 **All-Time Metrics**: Track sent, opened, clicked, replied, bounced, spam, and unsubscribed for Bison
- 🚨 **Health Classification**: 3-tier system - healthy (active/connected), early (paused), at_risk (errors)
- 📈 **Capacity Planning**: Aggregate daily sending limits across all healthy accounts
- ⚡ **Parallel Processing**: Fast health checks across 88+ clients simultaneously

**Total: 77 tools across 9 platforms** 🎉

---

## 📊 Production Features

### For Developers

- ✅ **100 unit tests** - Complete test coverage: 27 email analysis, 14 campaign management, 14 lead fetching, 13 spam checking, 18 workspace management, 14 Gmail integration
- ✅ **Type hints** - Complete type safety across all modules
- ✅ **Error handling** - Friendly error messages with recovery steps for EmailGuard quota limits, rate limiting, authentication failures
- ✅ **Rate limiting** - API quota management for Gmail/Calendar
- ✅ **Logging** - Comprehensive debug logs for troubleshooting
- ✅ **OAuth 2.0** - Secure authentication with encrypted token storage
- ✅ **Session management** - Multi-tenant support with SQLite
- ✅ **SQLite database** - User session and credential storage
- ✅ **Fuzzy matching** - Client name search with 60% similarity threshold using rapidfuzz
- ✅ **HTML conversion** - Automatic email body formatting for Instantly
- ✅ **Spam detection** - EmailGuard API integration with intelligent error handling

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
- Proper error handling with user-friendly messages
- Comprehensive logging
- 100 unit tests with full coverage

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

- 77 tools across 9 platforms
- Complete Google Workspace integration (Gmail, Calendar, Docs, Sheets)
- Advanced document automation (tables, formatting, professional styling)
- Lead management with 88+ clients
- Campaign automation and analytics
- Hidden gems discovery with AI
- Mailbox health monitoring with real-time status

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

**v2.5.0** (December 19, 2024) - **Hidden Gems Intelligence & Deduplication**
- 💎 **Hidden Gems Deduplication** - Groups replies by email address and keeps only the earliest reply per person
- 🏷️ **Green Tag Support** - Marks only first reply to trigger Bison's green "Interested" status (matches Bison UX)
- ⚡ **Performance Optimization** - Reduced API calls by marking one reply per person instead of all replies
- 🎯 **Cleaner Results** - Hidden gems now show 1 person = 1 opportunity instead of multiple duplicate entries
- 🛠️ **Technical**: Added email deduplication logic with timestamp-based earliest reply selection

**v2.4.0** (December 17, 2024) - **Spam Detection & Enhanced Testing**
- 🛡️ **EmailGuard API Integration** - Industry-standard spam detection for campaigns
- 📊 **100 Unit Tests** - Complete coverage across all features (up from 41)
- 💬 **User-Friendly Error Messages** - Clear explanations for quota limits, rate limiting, auth failures
- 🔍 **Campaign Spam Scanning** - Check entire Bison/Instantly campaigns for spam words
- 🎯 **Bison A/B Testing** - Fixed tool documentation to properly create A/B test variants using `variant_from_step` parameter
- ⏰ **Smart Delay Defaults** - Intelligent wait times: 1→3→5→7 days (Bison) and 0→72→120→168 hours (Instantly) for optimal follow-up cadence
- 🧪 **Comprehensive Test Suite** - Added 14 lead fetching tests, 14 campaign tests, 13 spam checking tests, 18 workspace tests
- 🛠️ **Technical**: Added spam_checker.py, emailguard_client.py, enhanced error handling with status code parsing
- 🐛 **Bug Fixes**: Removed print() statements breaking MCP JSON-RPC, fixed Instantly API endpoint from /campaigns/list to /campaigns

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
- 📦 Expanded tool count significantly

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

**Production-ready multi-tenant MCP server with 77 tools across 9 platforms**

⭐ Star this repo if you found it helpful!

[Report Bug](https://github.com/jonathangetonapod/gmail-reply-tracker-mcp/issues) • [Request Feature](https://github.com/jonathangetonapod/gmail-reply-tracker-mcp/issues) • [Documentation](https://github.com/jonathangetonapod/gmail-reply-tracker-mcp/wiki)

Made with ❤️ by the GetOnAPod team

</div>
