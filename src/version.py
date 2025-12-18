"""
Version and changelog management for the MCP server.
"""

VERSION = "2.4.1"
RELEASE_DATE = "2025-12-17"

# Changelog organized by version
CHANGELOG = {
    "2.4.1": {
        "date": "December 17, 2025",
        "title": "Performance & Critical Bug Fixes",
        "highlights": [
            {
                "icon": "🚀",
                "category": "Performance",
                "title": "5-10x Faster Gmail Operations",
                "description": "Parallel processing for messages, threads, and analytics",
                "details": "Added ThreadPoolExecutor to all Gmail operations. Message fetching: 50 messages in ~4s vs 10s sequential (5x faster). Thread fetching: 100 threads in ~2-4s vs 20s sequential (5-10x faster). Analytics: 88+ clients in 10-15s vs 3-4 minutes (12-24x faster). Parallel processing for: batch_get_messages(), batch_get_threads(), search_emails(), get_unreplied_emails(), get_all_platform_stats(), and more.",
                "screenshot": None,
            },
            {
                "icon": "🔧",
                "category": "Bug Fix",
                "title": "Fixed Bison Lead Fetching",
                "description": "Bison positive replies now appear in fast search tool",
                "details": "The get_all_clients_with_positive_replies() tool was only calling Instantly API for all clients. Updated to detect platform and call get_bison_lead_responses() for Bison clients with client_name, while Instantly clients continue using get_lead_responses() with workspace_id.",
                "screenshot": None,
            },
            {
                "icon": "🔧",
                "category": "Bug Fix",
                "title": "Fixed JSON-RPC Protocol Errors",
                "description": "Removed ALL remaining print() statements breaking MCP protocol",
                "details": "Removed 4 print() statements from date_utils.py and 15+ from lead_functions.py that were outputting text to stdout, causing 'Unexpected token' and 'is not valid JSON' errors. MCP JSON-RPC protocol requires clean stdout with only valid JSON responses.",
                "screenshot": None,
            },
            {
                "icon": "🔧",
                "category": "Bug Fix",
                "title": "Fixed Instantly Lead Fetching",
                "description": "Resolved MCP JSON-RPC protocol errors preventing lead data retrieval",
                "details": "Removed print() statements from _source_fetch_interested_leads.py that were breaking the MCP JSON-RPC protocol and causing 'technical difficulties' errors when fetching Instantly lead responses.",
                "screenshot": None,
            },
            {
                "icon": "🔧",
                "category": "Bug Fix",
                "title": "Fixed Instantly API Parameter Error",
                "description": "Resolved 'unexpected parameter' error in campaign statistics",
                "details": "Added missing gid parameter to get_lead_responses() and get_campaign_stats() functions. These functions were being called with a gid parameter from server.py but weren't accepting it, causing API failures.",
                "screenshot": None,
            },
            {
                "icon": "🔧",
                "category": "Bug Fix",
                "title": "Fixed OAuth Port Conflicts",
                "description": "OAuth now automatically finds available ports instead of crashing",
                "details": "Added automatic port detection to auto_oauth.py that tries ports 8080-8089 until finding a free one. Fixes 'Address already in use' errors when port 8080 is occupied by another process. Also added fix_port_issue.sh helper script.",
                "screenshot": None,
            },
            {
                "icon": "🐛",
                "category": "Critical Fix",
                "title": "Fixed RateLimiter Deadlock",
                "description": "Resolved deadlock causing parallel operations to freeze",
                "details": "Fixed critical bug where RateLimiter was calling time.sleep() while holding the lock, causing all 10 worker threads to block and freeze the entire system. Now releases lock before sleeping, allowing parallel operations to proceed smoothly.",
                "screenshot": None,
            },
            {
                "icon": "⚡",
                "category": "Performance",
                "title": "Optimized Inbox Summary",
                "description": "50x faster inbox queries with intelligent rate limiting",
                "details": "Reduced inbox summary from fetching 200 threads to 75 (changed max_results from 100 to 50, over-fetch from 2x to 1.5x). Increased rate limit from 60 to 250 requests/minute to match Gmail API capabilities. Inbox summary now completes in 20-30 seconds instead of 17+ minutes.",
                "screenshot": None,
            },
            {
                "icon": "📦",
                "category": "Enhancement",
                "title": "Response Size Optimization",
                "description": "10x smaller payloads with summary-first approach",
                "details": "Redesigned get_all_clients_with_positive_replies() to return summaries instead of full lead details (~500KB → ~50KB). Added new get_client_lead_details() tool for drilling down into specific clients. Prevents conversation compaction and improves response rendering speed.",
                "screenshot": None,
            },
        ],
        "breaking_changes": [],
        "technical_notes": [
            "Added batch_get_threads() to GmailClient for parallel thread fetching (10 workers)",
            "Added batch_get_messages() to GmailClient for parallel message fetching (10 workers)",
            "Updated search_emails() to use parallel batch fetching",
            "Updated get_unreplied_emails() to use parallel thread fetching",
            "Updated get_unreplied_by_sender() to use parallel thread fetching with deduplication",
            "Gmail operations: Message fetching 5x faster, thread fetching 5-10x faster",
            "Added parallel processing with ThreadPoolExecutor (15-20 workers) to 5 analytics functions",
            "Performance improvement: 3-4 minutes → 10-15 seconds (12-24x faster) for 88+ clients",
            "Fixed get_all_clients_with_positive_replies() to call appropriate API per platform",
            "Bison clients now use get_bison_lead_responses() with client_name parameter",
            "Instantly clients continue using get_lead_responses() with workspace_id parameter",
            "Removed 19+ total print() statements breaking MCP JSON-RPC protocol",
            "Removed 4 print() statements from src/leads/date_utils.py",
            "Removed 15+ print() statements from src/leads/lead_functions.py",
            "Removed 5 print() statements from src/leads/_source_fetch_interested_leads.py",
            "Added gid parameter to get_lead_responses() in lead_functions.py",
            "Added gid parameter to get_campaign_stats() in lead_functions.py",
            "Added find_free_port() function to auto_oauth.py that scans ports 8080-8089",
            "Created fix_port_issue.sh helper script to manually clear port 8080",
            "OAuth now displays 'Found available port: XXXX' message",
            "Fixed RateLimiter deadlock by releasing lock before time.sleep()",
            "RateLimiter now: (1) calculates wait time with lock, (2) releases lock, (3) sleeps, (4) re-acquires lock",
            "Reduced inbox summary thread fetching from 200 to 75 threads (max_results 100→50, over-fetch 2.0x→1.5x)",
            "Increased rate limit from 60 to 250 requests/minute to match Gmail API capabilities",
            "Inbox summary performance: 17+ minutes → 20-30 seconds (50x faster)",
            "Redesigned get_all_clients_with_positive_replies() to return summaries only (~500KB → ~50KB)",
            "Added get_client_lead_details(client_name) tool for drilling down into specific clients",
            "Response payload optimization prevents conversation compaction and improves rendering speed",
        ],
    },
    "2.4.0": {
        "date": "December 17, 2024",
        "title": "Spam Detection & Enhanced Testing",
        "highlights": [
            {
                "icon": "🛡️",
                "category": "Feature",
                "title": "EmailGuard API Integration",
                "description": "Industry-standard spam detection for campaign sequences",
                "details": "Check any subject line or email body for spam words using EmailGuard API. Scan entire Bison and Instantly campaigns including all variants. Get detailed reports with spam scores, word counts, and specific spam words identified.",
                "screenshot": None,
            },
            {
                "icon": "💬",
                "category": "Enhancement",
                "title": "User-Friendly Error Messages",
                "description": "Clear explanations for API quota limits and rate limiting",
                "details": "When EmailGuard API quota is exhausted, Claude now tells you 'EmailGuard API quota limit reached - please wait for reset or upgrade plan' instead of cryptic 400 errors. Also handles 429 rate limits, 401 auth failures, and 403 permissions errors with helpful messages.",
                "screenshot": None,
            },
            {
                "icon": "📊",
                "category": "Quality",
                "title": "100 Unit Tests",
                "description": "Complete test coverage across all features",
                "details": "Comprehensive test suite: 27 email analysis tests, 14 campaign management tests, 14 lead fetching tests, 13 spam checking tests, 18 workspace management tests, 14 Gmail integration tests. All passing!",
                "screenshot": None,
            },
            {
                "icon": "🔍",
                "category": "Feature",
                "title": "Campaign Spam Scanning",
                "description": "Check entire campaigns for spam words",
                "details": "Scan all sequence steps in Bison campaigns or all A/B test variants in Instantly campaigns. Get detailed reports showing which steps contain spam words and what needs to be fixed.",
                "screenshot": None,
            },
            {
                "icon": "🎯",
                "category": "Bug Fix",
                "title": "Bison A/B Testing Support",
                "description": "Fixed tool documentation to properly create A/B test variants",
                "details": "Corrected create_bison_sequence tool to show how to properly use variant_from_step parameter. Now Claude creates 1 campaign with 3 A/B variants instead of 3 separate campaigns. Variants use order numbers (variant_from_step=1 means 'variant of step with order=1').",
                "screenshot": None,
            },
            {
                "icon": "⏰",
                "category": "Enhancement",
                "title": "Smart Delay Defaults",
                "description": "Intelligent wait times based on email position for optimal follow-up cadence",
                "details": "No more manual wait time configuration! Automatic defaults: Bison campaigns use 1→3→5→7 days, Instantly campaigns use 0→72→120→168 hours. Based on industry best practices for maximum response rates while avoiding spam. Users can still override if needed.",
                "screenshot": None,
            },
        ],
        "breaking_changes": [],
        "technical_notes": [
            "Added src/leads/spam_checker.py with 3 spam checking functions",
            "Added src/leads/emailguard_client.py for API integration",
            "Enhanced error handling with HTTPError status code parsing",
            "Removed all print() statements that were breaking MCP JSON-RPC protocol",
            "Fixed Instantly API endpoint from /campaigns/list to /campaigns",
            "Fixed create_bison_sequence tool description with correct A/B testing examples",
            "Implemented smart delay defaults in server.py and bison_client.py",
            "Position-based wait times: idx==0→1 day, idx==1→3 days, idx==2→5 days, idx>=3→7 days",
            "Added test_bison_variants.py script to verify variant structure",
            "Added tests/test_spam_checker.py with 13 comprehensive tests",
            "Added tests/test_leads_fetching.py with 14 tests",
            "Added tests/test_campaign_management.py with 14 tests",
            "Added tests/test_workspace_management.py with 18 tests",
        ],
    },
    "2.3.1": {
        "date": "December 17, 2024",
        "title": "Google Meet Integration",
        "highlights": [
            {
                "icon": "🎥",
                "category": "Feature",
                "title": "Automatic Google Meet Links",
                "description": "Calendar events with attendees now automatically include Google Meet video conference links",
                "details": "No more manual 'Add Google Meet' clicks! When you create a calendar event with attendees, the system automatically generates a Google Meet link and includes it in the event and email invitations. The Meet link includes video access, phone dial-in, and PIN for maximum flexibility.",
                "screenshot": None,
            },
            {
                "icon": "📧",
                "category": "Enhancement",
                "title": "Meet Links in Email Invites",
                "description": "Email invitations now prominently display the Google Meet link",
                "details": "Attendees receive the Meet link directly in their invitation email with a clear 🎥 icon, making it easy to join the meeting with one click.",
                "screenshot": None,
            },
            {
                "icon": "⚙️",
                "category": "Feature",
                "title": "Smart Auto-Detection",
                "description": "Intelligently adds Meet links only when needed",
                "details": "Events with attendees automatically get Meet links. Personal events without attendees don't get cluttered with unnecessary video conference links. You can also manually control this with add_meet_link parameter.",
                "screenshot": None,
            },
        ],
        "breaking_changes": [],
        "technical_notes": [
            "Added add_meet_link parameter to calendar_client.create_event()",
            "Implemented conferenceData with hangoutsMeet solution key",
            "Set conferenceDataVersion=1 for events with conference data",
            "Meet link included in API response JSON with meet_link field",
        ],
    },
    "2.3.0": {
        "date": "December 17, 2024",
        "title": "Campaign Automation & Privacy Enhancements",
        "highlights": [
            {
                "icon": "✨",
                "category": "Feature",
                "title": "Instantly HTML Formatting",
                "description": "Email bodies now display with proper line breaks and paragraph spacing in Instantly campaigns",
                "details": "Converts plain text with newlines to proper HTML <div> structure. No more collapsed emails!",
                "screenshot": None,  # Can add URL to screenshot
            },
            {
                "icon": "🔧",
                "category": "Fix",
                "title": "Bison Placeholder Conversion",
                "description": "Placeholders like {{firstname}} now correctly convert to {FIRST_NAME} in Bison campaigns",
                "details": "Added comprehensive regex patterns to handle all placeholder variations: {{first_name}}, {{firstName}}, {{firstname}}, etc.",
                "screenshot": None,
            },
            {
                "icon": "🔍",
                "category": "Feature",
                "title": "Fuzzy Client Name Matching",
                "description": "Client lookup now tolerates typos and partial names",
                "details": "Search for 'brian blis' and find 'Brian Bliss'. Uses rapidfuzz with 60% similarity threshold.",
                "screenshot": None,
            },
            {
                "icon": "🔒",
                "category": "Feature",
                "title": "Privacy & Security Modal",
                "description": "Crystal-clear explanation of what admin can and cannot access",
                "details": "Comprehensive modal showing that default install is 100% private. Explains admin dashboard visibility for Railway shared server users.",
                "screenshot": None,
            },
            {
                "icon": "🧪",
                "category": "Quality",
                "title": "Unit Test Suite",
                "description": "18 comprehensive tests covering all campaign features",
                "details": "Tests for Bison conversion, Instantly formatting, fuzzy matching, and full workflows. All passing!",
                "screenshot": None,
            },
        ],
        "breaking_changes": [],
        "technical_notes": [
            "Added rapidfuzz>=3.0.0 dependency for fuzzy matching",
            "Instantly campaigns now use HTML <div> structure instead of plain newlines",
            "Bison placeholder conversion happens at API client level (single source of truth)",
        ],
    },
    "2.2.0": {
        "date": "December 10, 2024",
        "title": "Multi-Client Campaign Management",
        "highlights": [
            {
                "icon": "🎯",
                "category": "Feature",
                "title": "Bison & Instantly Integration",
                "description": "Create campaigns for 88+ clients across Bison and Instantly platforms",
                "details": "Google Sheets-based client management with API key storage",
                "screenshot": None,
            },
            {
                "icon": "📊",
                "category": "Feature",
                "title": "Campaign Analytics",
                "description": "Track campaign performance with reply rates and interested leads",
                "details": "Fetch stats from both platforms with date range filtering",
                "screenshot": None,
            },
        ],
        "breaking_changes": [],
        "technical_notes": [],
    },
    "2.1.0": {
        "date": "November 28, 2024",
        "title": "Fathom AI Integration",
        "highlights": [
            {
                "icon": "🎙️",
                "category": "Feature",
                "title": "Meeting Transcripts & Summaries",
                "description": "Access Fathom meeting recordings, transcripts, and AI-generated summaries",
                "details": "6 tools for searching meetings, extracting action items, and viewing highlights",
                "screenshot": None,
            },
        ],
        "breaking_changes": [],
        "technical_notes": [],
    },
    "2.0.0": {
        "date": "November 15, 2024",
        "title": "Multi-Tenant Railway Deployment",
        "highlights": [
            {
                "icon": "🚀",
                "category": "Feature",
                "title": "Railway Web Setup",
                "description": "One-command install for team members via Railway-hosted setup page",
                "details": "Automated OAuth flow, Claude Desktop config, and credential management",
                "screenshot": None,
            },
            {
                "icon": "🔐",
                "category": "Security",
                "title": "Admin Dashboard",
                "description": "Optional usage analytics for Railway shared server users",
                "details": "View tool usage, success rates, and activity logs (metadata only, no content)",
                "screenshot": None,
            },
        ],
        "breaking_changes": [
            "Local install now uses different OAuth flow (backwards compatible)"
        ],
        "technical_notes": [
            "Added SQLite database for user management",
            "Encrypted Fathom API key storage",
            "Usage logging for analytics",
        ],
    },
}


def get_latest_version():
    """Get the latest version number."""
    return VERSION


def get_latest_release():
    """Get the latest release information."""
    return {
        "version": VERSION,
        "date": RELEASE_DATE,
        "changelog": CHANGELOG.get(VERSION, {}),
    }


def get_all_releases():
    """Get all releases in reverse chronological order."""
    # Sort by version number (descending)
    versions = sorted(CHANGELOG.keys(), reverse=True, key=lambda v: [int(x) for x in v.split('.')])
    return [{
        "version": v,
        "changelog": CHANGELOG[v],
    } for v in versions]


def format_version_badge():
    """Format version badge for display."""
    return f"v{VERSION} • Updated {RELEASE_DATE}"
