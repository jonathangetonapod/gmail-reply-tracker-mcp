"""
Version and changelog management for the MCP server.
"""

VERSION = "2.3.1"
RELEASE_DATE = "2024-12-17"

# Changelog organized by version
CHANGELOG = {
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
