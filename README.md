# Gmail, Calendar & Fathom MCP Server

An MCP (Model Context Protocol) server that connects to Gmail, Google Calendar, and Fathom AI to help you manage emails, meetings, and meeting insights. This server exposes tools that let Claude interact with your productivity suite in real-time during conversations.

## Features

### Gmail
- **Smart Unreplied Email Detection**: Identifies emails you've read but haven't replied to
- **Automated Email Filtering**: Excludes newsletters, no-reply addresses, and automated messages
- **Full Thread Context**: Retrieves complete conversation history for any email
- **Powerful Search**: Query emails using Gmail's search syntax
- **Inbox Analytics**: Get summary statistics on response times and volume
- **Sender Filtering**: Find unreplied emails from specific people or domains
- **Email Sending & Replies**: Send emails and reply to threads with confirmation

### Google Calendar
- **Event Management**: List, create, update, and delete calendar events
- **Multi-Calendar Support**: Work with multiple calendars
- **Natural Language Event Creation**: Quick add events using plain English
- **Past & Future Events**: View events in any time range
- **Attendee Management**: Handle meeting invitations and responses

### Fathom AI Integration
- **Meeting Recordings**: List and access all your Fathom meeting recordings
- **Full Transcripts**: Get complete meeting transcripts with speaker attribution
- **AI Summaries**: Access AI-generated meeting summaries and key points
- **Action Items**: Extract and track action items from meetings
- **Search Meetings**: Find meetings by title, attendee, or date
- **Calendar Cross-Reference**: Connect calendar events with meeting recordings

## Tools Provided

The MCP server exposes 25+ tools across Gmail, Calendar, and Fathom:

### Gmail Tools (13)
1. **`get_unreplied_emails`** - Find emails you've read but haven't replied to
2. **`get_email_thread`** - Get full conversation history for an email thread
3. **`search_emails`** - Search emails using Gmail query syntax
4. **`get_inbox_summary`** - Get statistics on unreplied emails
5. **`get_unreplied_by_sender`** - Filter unreplied emails by sender or domain
6. **`send_email`** - Send a new email (with confirmation)
7. **`reply_to_email`** - Reply to an email thread (with confirmation)
8. **`reply_all_to_email`** - Reply all to an email thread (with confirmation)
9. **`create_email_draft`** - Create an email draft without sending

### Calendar Tools (7)
10. **`list_calendars`** - List all accessible calendars
11. **`list_calendar_events`** - List upcoming events
12. **`list_past_calendar_events`** - List past events
13. **`create_calendar_event`** - Create a new calendar event
14. **`update_calendar_event`** - Update an existing event
15. **`delete_calendar_event`** - Delete a calendar event
16. **`quick_add_calendar_event`** - Create event using natural language

### Fathom Meeting Tools (6)
17. **`list_fathom_meetings`** - List recent meeting recordings
18. **`get_fathom_transcript`** - Get full meeting transcript
19. **`get_fathom_summary`** - Get AI-generated meeting summary
20. **`get_fathom_action_items`** - Extract action items from meeting
21. **`search_fathom_meetings_by_title`** - Search meetings by title
22. **`search_fathom_meetings_by_attendee`** - Find meetings with specific people

## Prerequisites

- Python 3.10 or higher
- A Gmail account
- A Google Cloud Project with Gmail API and Calendar API enabled
- (Optional) Fathom AI account with API access
- Claude Desktop app

## Installation

### 1. Clone or Download This Repository

```bash
cd /Users/jonathangarces/Desktop/MCP_Gmail
```

### 2. Set Up Python Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
# OR
venv\Scripts\activate  # On Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Set Up Google Cloud Project

#### Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. Note your project ID

#### Enable Gmail and Calendar APIs

1. In your project, go to **APIs & Services** > **Library**
2. Search for "Gmail API" and click **Enable**
3. Search for "Google Calendar API" and click **Enable**

#### Create OAuth 2.0 Credentials

1. Go to **APIs & Services** > **Credentials**
2. Click **+ CREATE CREDENTIALS** > **OAuth client ID**
3. If prompted, configure the OAuth consent screen:
   - User Type: **External** (unless you have a Google Workspace)
   - App name: `Gmail Reply Tracker`
   - User support email: Your email
   - Developer contact: Your email
   - Scopes: Add the following scopes:
     - `https://www.googleapis.com/auth/gmail.readonly`
     - `https://www.googleapis.com/auth/gmail.send`
     - `https://www.googleapis.com/auth/calendar`
   - Test users: Add your Gmail address
   - Click **Save and Continue**
4. Back at Create OAuth client ID:
   - Application type: **Desktop app**
   - Name: `Gmail Reply Tracker`
   - Click **Create**
5. Click **Download JSON** (download icon next to your credential)
6. Save the file as `credentials.json`

#### Place Credentials File

```bash
# Create credentials directory if it doesn't exist
mkdir -p credentials

# Move the downloaded file
mv ~/Downloads/credentials.json credentials/credentials.json
```

### 5. Run OAuth Setup

```bash
python setup_oauth.py
```

This script will:
- Validate your credentials.json file
- Open a browser window for OAuth authorization
- Save your access token to `credentials/token.json`
- Test the connection to Gmail

**Important**: When authorizing, you may see a warning that the app is not verified. Click "Advanced" > "Go to Gmail Reply Tracker (unsafe)" to proceed. This is normal for apps in development.

### 6. Configure Environment

Create a `.env` file in the project root with your configuration:

```bash
# Create .env file
touch .env
```

Edit `.env` and add the following (update paths and API keys as needed):

```env
# Gmail & Calendar
GMAIL_CREDENTIALS_PATH=./credentials/credentials.json
GMAIL_TOKEN_PATH=./credentials/token.json
GMAIL_OAUTH_SCOPES=https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/calendar
MCP_SERVER_NAME=gmail-calendar-fathom
LOG_LEVEL=INFO
GMAIL_API_MAX_REQUESTS_PER_MINUTE=60

# Fathom AI (optional)
FATHOM_API_KEY=your_fathom_api_key_here
```

**To get your Fathom API key:**
1. Log in to [Fathom](https://fathom.video)
2. Go to Settings > API
3. Generate a new API key
4. Copy and paste it into your `.env` file

### 7. Configure Claude Desktop

Add the MCP server to your Claude Desktop configuration:

**macOS**: Edit `~/Library/Application Support/Claude/claude_desktop_config.json`

**Windows**: Edit `%APPDATA%\Claude\claude_desktop_config.json`

Add this configuration:

```json
{
  "mcpServers": {
    "gmail-calendar-fathom": {
      "command": "python",
      "args": [
        "/Users/jonathangarces/Desktop/MCP_Gmail/src/server.py"
      ],
      "env": {
        "GMAIL_CREDENTIALS_PATH": "/Users/jonathangarces/Desktop/MCP_Gmail/credentials/credentials.json",
        "GMAIL_TOKEN_PATH": "/Users/jonathangarces/Desktop/MCP_Gmail/credentials/token.json",
        "GMAIL_OAUTH_SCOPES": "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/calendar",
        "FATHOM_API_KEY": "your_fathom_api_key_here"
      }
    }
  }
}
```

**Important**: Replace `/Users/jonathangarces/Desktop/MCP_Gmail` with the actual absolute path to your installation directory.

### 8. Restart Claude Desktop

Quit and restart Claude Desktop to load the new MCP server.

## Usage

Once configured, you can ask Claude natural language questions about your Gmail:

### Example Queries

**Find unreplied emails:**
```
What emails do I need to reply to?
```

**Search by sender:**
```
Show me unreplied emails from john@example.com
```

**Search by domain:**
```
What emails from @acme.com need replies?
```

**Get inbox summary:**
```
Give me my inbox summary
```

**Who are you ghosting:**
```
Who have I ghosted this week?
```

**Search with Gmail syntax:**
```
Find emails from my boss after January 1st
```

**Get thread context:**
```
Show me the full conversation for thread [thread-id]
```

**Calendar queries:**
```
What's on my calendar this week?
Schedule a meeting with John tomorrow at 2pm
Show me my meetings from last week
```

**Fathom meeting queries:**
```
List my recent Fathom meetings
Get the transcript from my meeting about the Q4 budget
What action items came out of my last meeting with Sarah?
Find all meetings with john@company.com
Summarize the Project Phoenix kickoff meeting
```

## Tool Reference

### get_unreplied_emails

Find emails you've read but haven't replied to.

**Parameters:**
- `days_back` (int, default: 7) - Number of days to look back
- `max_results` (int, default: 50) - Maximum results to return
- `exclude_automated` (bool, default: true) - Filter out automated emails

**Example:**
```python
get_unreplied_emails(days_back=14, max_results=100)
```

### get_email_thread

Get complete conversation history for a thread.

**Parameters:**
- `thread_id` (str, required) - Gmail thread ID

**Example:**
```python
get_email_thread("18c5f1a2b3d4e5f6")
```

### search_emails

Search emails using Gmail query syntax.

**Parameters:**
- `query` (str, required) - Gmail search query
- `max_results` (int, default: 20) - Maximum results

**Example:**
```python
search_emails("from:boss@company.com after:2024/01/01", max_results=50)
```

**Gmail Search Operators:**
- `from:email@example.com` - From specific sender
- `to:email@example.com` - To specific recipient
- `subject:keyword` - Subject contains keyword
- `after:YYYY/MM/DD` - After date
- `before:YYYY/MM/DD` - Before date
- `has:attachment` - Has attachments
- `is:unread` - Unread emails
- `is:starred` - Starred emails
- `label:labelname` - Has specific label

[Full Gmail search reference](https://support.google.com/mail/answer/7190)

### get_inbox_summary

Get statistics on unreplied emails.

**Parameters:** None

**Returns:**
- Total unreplied count
- Top senders you haven't replied to
- Top domains you haven't replied to
- Oldest unreplied email date

### get_unreplied_by_sender

Filter unreplied emails by sender or domain.

**Parameters:**
- `email_or_domain` (str, required) - Email or domain (e.g., "john@example.com" or "@example.com")

**Example:**
```python
get_unreplied_by_sender("@acme.com")
```

## How It Works

### Unreplied Email Detection

An email is considered "needs reply" if:

1. **Last message is from someone else** (not you)
2. **You have read it** (no UNREAD label)
3. **It's not automated** (not from no-reply@, newsletters, etc.)

### Automated Email Detection

The system filters out automated emails by checking:

- **From addresses**: `noreply@`, `no-reply@`, `donotreply@`, `automated@`, `notifications@`, `alerts@`, `bounce@`, `mailer-daemon@`, `newsletter@`, `updates@`
- **Headers**:
  - `Auto-Submitted` (RFC 3834)
  - `Precedence: bulk/list/junk`
  - `List-Unsubscribe` (newsletters)
  - `X-Auto-Response-Suppress` (Microsoft)

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_analyzer.py

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src tests/
```

### Project Structure

```
MCP_Gmail/
├── src/
│   ├── __init__.py
│   ├── server.py              # MCP server entry point
│   ├── gmail_client.py        # Gmail API wrapper
│   ├── email_analyzer.py      # Reply detection logic
│   ├── auth.py                # OAuth authentication
│   └── config.py              # Configuration management
├── tests/
│   ├── __init__.py
│   ├── test_analyzer.py       # Email analyzer tests
│   └── test_gmail_client.py  # Gmail client tests
├── credentials/
│   ├── credentials.json       # OAuth credentials (gitignored)
│   └── token.json            # Access token (gitignored)
├── requirements.txt           # Python dependencies
├── .env                       # Environment config (gitignored)
├── .env.example               # Environment template
├── .gitignore
├── README.md
└── setup_oauth.py             # OAuth setup script
```

## Troubleshooting

### "Credentials file not found"

**Solution**: Make sure you've downloaded `credentials.json` from Google Cloud Console and placed it in the `credentials/` directory.

### "Authentication failed"

**Solutions**:
1. Run `python setup_oauth.py` again to re-authenticate
2. Check that Gmail API is enabled in your Google Cloud Project
3. Verify your email is added as a test user (if app is not published)
4. Delete `credentials/token.json` and re-authenticate

### "Permission denied" or scope errors

**Solution**: Delete `credentials/token.json` and run `python setup_oauth.py` again. The token may have incorrect scopes.

### Claude Desktop doesn't see the tools

**Solutions**:
1. Verify the config path is correct in `claude_desktop_config.json`
2. Use **absolute paths** (not relative paths like `./` or `~/`)
3. Restart Claude Desktop completely (Quit and reopen)
4. Check Claude Desktop logs for errors

### "Rate limit exceeded"

**Solution**: The server has built-in rate limiting. If you hit Gmail API quotas:
1. Wait a few minutes
2. Reduce `max_results` parameters in your queries
3. Adjust `GMAIL_API_MAX_REQUESTS_PER_MINUTE` in `.env`

### Server crashes or errors

**Solutions**:
1. Check logs for specific error messages
2. Ensure all dependencies are installed: `pip install -r requirements.txt`
3. Verify Python version is 3.10+: `python --version`
4. Try running the server directly to see errors: `python src/server.py`

## Security & Privacy

### What This Server Can Access

- **Read-only access** to your Gmail (uses `gmail.readonly` scope)
- Can read email headers, content, and metadata
- **Cannot send, delete, or modify emails**

### Where Data Is Stored

- **OAuth tokens** stored locally in `credentials/token.json`
- **No email data** is stored or cached
- **No data sent to external servers** (except Google's Gmail API)

### Best Practices

1. **Keep credentials secure**: Never commit `credentials/` to git
2. **Token permissions**: File permissions set to 600 (owner only)
3. **Revoke access**: Go to [Google Account > Security > Third-party apps](https://myaccount.google.com/permissions) to revoke access
4. **Use readonly scope**: Don't request write permissions unless needed

## FAQ

### Can I use this with Google Workspace accounts?

Yes! Just make sure your organization allows third-party apps.

### Will this work with multiple Gmail accounts?

Currently, the server authenticates with one account. To switch accounts, delete `credentials/token.json` and run `python setup_oauth.py` again.

### How do I deploy this to my team?

Each team member needs to:
1. Clone/download the repository
2. Install dependencies
3. Create their own Google Cloud Project and credentials
4. Run `setup_oauth.py` with their Gmail account
5. Configure their Claude Desktop

### Can I customize the automated email detection?

Yes! Edit the `AUTOMATED_FROM_PATTERNS` list in `src/email_analyzer.py` to add your own patterns.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass: `pytest`
5. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues, questions, or feature requests:
- Open an issue on GitHub
- Check the troubleshooting section above
- Review Gmail API documentation: https://developers.google.com/gmail/api

## Acknowledgments

- Built with [Model Context Protocol](https://modelcontextprotocol.io/)
- Uses [Gmail API](https://developers.google.com/gmail/api)
- Powered by [Claude](https://claude.ai)
