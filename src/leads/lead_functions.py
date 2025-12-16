"""
MCP-ready functions that combine Google Sheets + Instantly API + Bison API.
These will be the tools exposed to Claude via MCP.
"""

from datetime import datetime, timedelta

# Import from our modular files
from .date_utils import validate_and_parse_dates
from .sheets_client import (
    load_workspaces_from_sheet,
    load_bison_workspaces_from_sheet,
    DEFAULT_SHEET_URL,
    SHEET_GID_INSTANTLY,
    SHEET_GID_BISON
)
from .instantly_client import (
    fetch_workspace_details,
    get_instantly_campaign_stats,
    get_instantly_lead_responses
)
from .bison_client import (
    get_bison_lead_replies,
    get_bison_conversation_thread,
    get_bison_campaign_stats_api
)


# ============================================================================
# INSTANTLY FUNCTIONS
# ============================================================================

def get_client_list(sheet_url: str = DEFAULT_SHEET_URL, include_details: bool = False):
    """
    MCP Tool: Get list of all available clients/workspaces.

    Args:
        sheet_url: Google Sheet URL (optional)
        include_details: If True, fetches workspace names from API for entries without names

    Returns:
        {
            "total_clients": int,
            "clients": [
                {
                    "workspace_id": "23dbc003-ebe2-4950...",
                    "client_name": "ABC Corp",
                    "workspace_name": "ABC Corp" (if include_details=True),
                    "plan_id": "pid_hg_v1" (if include_details=True)
                },
                ...
            ]
        }
    """
    workspaces = load_workspaces_from_sheet(sheet_url)

    clients = []
    for w in workspaces:
        client_entry = {
            "workspace_id": w["workspace_id"],
            "client_name": w["client_name"]
        }

        # If include_details is True and client_name is same as workspace_id,
        # fetch the actual workspace name from API
        if include_details and w["client_name"] == w["workspace_id"]:
            print(f"[API] Fetching details for {w['workspace_id'][:8]}...")
            details = fetch_workspace_details(w["api_key"])
            if details:
                client_entry["workspace_name"] = details.get("name", w["workspace_id"])
                client_entry["plan_id"] = details.get("plan_id")
                client_entry["org_domain"] = details.get("org_client_domain")
            else:
                client_entry["workspace_name"] = w["workspace_id"]

        clients.append(client_entry)

    return {
        "total_clients": len(clients),
        "clients": clients
    }


def get_lead_responses(
    workspace_id: str,
    start_date: str = None,
    end_date: str = None,
    days: int = 7,
    sheet_url: str = DEFAULT_SHEET_URL
):
    """
    MCP Tool: Get positive lead responses for a specific client/workspace.

    Args:
        workspace_id: Client name or workspace ID (e.g., "ABC Corp")
        start_date: Start date in ISO format (optional if using 'days')
        end_date: End date in ISO format (optional if using 'days')
        days: Number of days to look back (default: 7)
        sheet_url: Google Sheet URL (optional)

    Returns:
        {
            "workspace_id": str,
            "start_date": str,
            "end_date": str,
            "total_leads": int,
            "leads": [
                {
                    "email": str,
                    "reply_summary": str,
                    "subject": str,
                    "timestamp": str
                }
            ]
        }
    """
    # Load workspaces from sheet
    workspaces = load_workspaces_from_sheet(sheet_url)

    # Find the workspace by ID or name
    # Try exact match on workspace_id first
    workspace = None
    search_term = workspace_id.lower()

    # 1. Try exact workspace_id match
    for w in workspaces:
        if w["workspace_id"].lower() == search_term:
            workspace = w
            break

    # 2. Try fuzzy match on client_name, workspace_name, or person_name
    if not workspace:
        matches = []
        for w in workspaces:
            # Search in client_name (display), workspace_name (Column C), and person_name (Column D)
            if (search_term in w["client_name"].lower() or
                search_term in w.get("workspace_name", "").lower() or
                search_term in w.get("person_name", "").lower()):
                matches.append(w)

        if len(matches) == 1:
            workspace = matches[0]
        elif len(matches) > 1:
            match_list = [f"{w['client_name']} ({w['workspace_id']})" for w in matches]
            raise ValueError(
                f"Multiple matches found for '{workspace_id}':\n" +
                "\n".join(f"  - {m}" for m in match_list) +
                "\n\nPlease use the exact workspace_id or be more specific."
            )

    # 3. Try fuzzy match on workspace_id
    if not workspace:
        for w in workspaces:
            if search_term in w["workspace_id"].lower():
                workspace = w
                break

    if not workspace:
        # Show first 10 available clients
        available = [f"{w['client_name']} ({w['workspace_id'][:8]}...)" for w in workspaces[:10]]
        available_str = '\n'.join(f"  - {a}" for a in available)
        raise ValueError(
            f"Workspace '{workspace_id}' not found.\n\n"
            f"Available clients (showing first 10):\n{available_str}\n\n"
            f"Use get_client_list() to see all {len(workspaces)} clients."
        )

    print(f"[MCP] Found workspace: {workspace['workspace_id']}")

    # Validate and parse dates with safeguards
    # Note: Instantly API uses ISO format with T and Z, so we need to convert
    start_date_simple, end_date_simple, warnings = validate_and_parse_dates(start_date, end_date, days)

    # Convert to ISO format for Instantly API
    start_date = f"{start_date_simple}T00:00:00Z"
    end_date = f"{end_date_simple}T23:59:59Z"

    # Fetch interested leads
    results = get_instantly_lead_responses(
        api_key=workspace["api_key"],
        start_date=start_date,
        end_date=end_date
    )

    result = {
        "workspace_id": workspace["workspace_id"],
        "start_date": start_date,
        "end_date": end_date,
        "total_leads": results["total_count"],
        "leads": results["leads"]
    }

    # Add warnings if any
    if warnings:
        result["warnings"] = warnings

    return result


def get_campaign_stats(
    workspace_id: str,
    start_date: str = None,
    end_date: str = None,
    days: int = 7,
    sheet_url: str = DEFAULT_SHEET_URL
):
    """
    MCP Tool: Get campaign statistics for a specific client/workspace.

    Uses the existing analytics endpoint from app.py.

    Args:
        workspace_id: Client name or workspace ID
        start_date: Start date in ISO format (optional)
        end_date: End date in ISO format (optional)
        days: Number of days to look back (default: 7)
        sheet_url: Google Sheet URL (optional)

    Returns:
        {
            "workspace_id": str,
            "start_date": str,
            "end_date": str,
            "emails_sent": int,
            "replies": int,
            "opportunities": int,
            "reply_rate": float
        }
    """
    # Load workspaces
    workspaces = load_workspaces_from_sheet(sheet_url)

    # Find the workspace by ID or name (same logic as get_lead_responses)
    workspace = None
    search_term = workspace_id.lower()

    # 1. Try exact workspace_id match
    for w in workspaces:
        if w["workspace_id"].lower() == search_term:
            workspace = w
            break

    # 2. Try fuzzy match on client_name, workspace_name, or person_name
    if not workspace:
        matches = []
        for w in workspaces:
            # Search in client_name (display), workspace_name (Column C), and person_name (Column D)
            if (search_term in w["client_name"].lower() or
                search_term in w.get("workspace_name", "").lower() or
                search_term in w.get("person_name", "").lower()):
                matches.append(w)

        if len(matches) == 1:
            workspace = matches[0]
        elif len(matches) > 1:
            match_list = [f"{w['client_name']} ({w['workspace_id']})" for w in matches]
            raise ValueError(
                f"Multiple matches found for '{workspace_id}':\n" +
                "\n".join(f"  - {m}" for m in match_list) +
                "\n\nPlease use the exact workspace_id or be more specific."
            )

    # 3. Try fuzzy match on workspace_id
    if not workspace:
        for w in workspaces:
            if search_term in w["workspace_id"].lower():
                workspace = w
                break

    if not workspace:
        # Show first 10 available clients
        available = [f"{w['client_name']} ({w['workspace_id'][:8]}...)" for w in workspaces[:10]]
        available_str = '\n'.join(f"  - {a}" for a in available)
        raise ValueError(
            f"Workspace '{workspace_id}' not found.\n\n"
            f"Available clients (showing first 10):\n{available_str}\n\n"
            f"Use get_client_list() to see all {len(workspaces)} clients."
        )

    # Validate and parse dates with safeguards
    start_date, end_date, warnings = validate_and_parse_dates(start_date, end_date, days)

    # Call Instantly analytics API
    print(f"[MCP] Fetching campaign stats for {workspace['workspace_id']}...")

    data = get_instantly_campaign_stats(
        api_key=workspace["api_key"],
        start_date=start_date,
        end_date=end_date
    )

    result = {
        "workspace_id": workspace["workspace_id"],
        "start_date": start_date,
        "end_date": end_date,
        "emails_sent": data.get("emails_sent_count", 0),
        "replies": data.get("reply_count_unique", 0),
        "opportunities": data.get("total_opportunities", 0),
        "reply_rate": data.get("reply_rate", 0)
    }

    # Add warnings if any
    if warnings:
        result["warnings"] = warnings

    return result


def get_workspace_info(
    workspace_id: str,
    sheet_url: str = DEFAULT_SHEET_URL
):
    """
    MCP Tool: Get detailed workspace information from Instantly API.

    Args:
        workspace_id: Client name or workspace ID
        sheet_url: Google Sheet URL (optional)

    Returns:
        {
            "workspace_id": str,
            "workspace_name": str,
            "owner": str,
            "plan_id": str,
            "org_logo_url": str,
            "org_client_domain": str,
            "plan_id_crm": str,
            "timestamp_created": str,
            "timestamp_updated": str
        }
    """
    # Load workspaces
    workspaces = load_workspaces_from_sheet(sheet_url)

    # Find the workspace (same lookup logic as other functions)
    workspace = None
    search_term = workspace_id.lower()

    # 1. Try exact workspace_id match
    for w in workspaces:
        if w["workspace_id"].lower() == search_term:
            workspace = w
            break

    # 2. Try fuzzy match on client_name, workspace_name, or person_name
    if not workspace:
        matches = []
        for w in workspaces:
            # Search in client_name (display), workspace_name (Column C), and person_name (Column D)
            if (search_term in w["client_name"].lower() or
                search_term in w.get("workspace_name", "").lower() or
                search_term in w.get("person_name", "").lower()):
                matches.append(w)

        if len(matches) == 1:
            workspace = matches[0]
        elif len(matches) > 1:
            match_list = [f"{w['client_name']} ({w['workspace_id']})" for w in matches]
            raise ValueError(
                f"Multiple matches found for '{workspace_id}':\n" +
                "\n".join(f"  - {m}" for m in match_list) +
                "\n\nPlease use the exact workspace_id or be more specific."
            )

    # 3. Try fuzzy match on workspace_id
    if not workspace:
        for w in workspaces:
            if search_term in w["workspace_id"].lower():
                workspace = w
                break

    if not workspace:
        raise ValueError(f"Workspace '{workspace_id}' not found.")

    print(f"[MCP] Fetching workspace info for {workspace['workspace_id']}...")

    # Fetch workspace details from API
    details = fetch_workspace_details(workspace["api_key"])

    if not details:
        raise ValueError(f"Failed to fetch workspace details for {workspace_id}")

    return {
        "workspace_id": details.get("id", workspace["workspace_id"]),
        "workspace_name": details.get("name"),
        "owner": details.get("owner"),
        "plan_id": details.get("plan_id"),
        "org_logo_url": details.get("org_logo_url"),
        "org_client_domain": details.get("org_client_domain"),
        "plan_id_crm": details.get("plan_id_crm"),
        "plan_id_leadfinder": details.get("plan_id_leadfinder"),
        "plan_id_verification": details.get("plan_id_verification"),
        "plan_id_website_visitor": details.get("plan_id_website_visitor"),
        "plan_id_inbox_placement": details.get("plan_id_inbox_placement"),
        "timestamp_created": details.get("timestamp_created"),
        "timestamp_updated": details.get("timestamp_updated"),
        "default_opportunity_value": details.get("default_opportunity_value")
    }


# ============================================================================
# BISON FUNCTIONS
# ============================================================================

def get_bison_client_list(sheet_url: str = DEFAULT_SHEET_URL):
    """
    MCP Tool: Get list of all Bison clients.

    Args:
        sheet_url: Google Sheet URL (optional)

    Returns:
        {
            "total_clients": int,
            "clients": [
                {"client_name": "ABC Corp"},
                ...
            ]
        }
    """
    workspaces = load_bison_workspaces_from_sheet(sheet_url)

    clients = [{"client_name": w["client_name"]} for w in workspaces]

    return {
        "total_clients": len(clients),
        "clients": clients
    }


def get_bison_lead_responses(
    client_name: str,
    start_date: str = None,
    end_date: str = None,
    days: int = 7,
    sheet_url: str = DEFAULT_SHEET_URL
):
    """
    MCP Tool: Get interested lead responses from Bison for a specific client.

    Returns UNIQUE leads (by lead_id) that have been marked as interested in any conversation,
    including those already replied to. This matches the "Lead Tag: Interested" filter in the UI
    and aligns with the campaign stats count.

    Each lead includes their full conversation thread with complete message history,
    providing context for follow-up actions.

    Note: Bison's "interested" status includes:
    - Incoming positive replies (green "Message Status")
    - Leads that were replied to (status persists as "Lead Tag")
    The function deduplicates by lead_id, returning the most recent interaction per lead with
    complete conversation context.

    Args:
        client_name: Client name (supports fuzzy matching)
        start_date: Start date in YYYY-MM-DD format (optional if using 'days')
        end_date: End date in YYYY-MM-DD format (optional if using 'days')
        days: Number of days to look back (default: 7)
        sheet_url: Google Sheet URL (optional)

    Returns:
        {
            "client_name": str,
            "start_date": str,
            "end_date": str,
            "total_leads": int,
            "leads": [
                {
                    "email": str,
                    "from_name": str,
                    "reply_body": str,
                    "subject": str,
                    "date_received": str,
                    "interested": bool,
                    "read": bool,
                    "lead_id": int,
                    "thread_message_count": int,
                    "conversation_thread": [
                        {
                            "date_received": str,
                            "from_name": str,
                            "from_email": str,
                            "subject": str,
                            "body": str,
                            "type": str,
                            "reply_id": int
                        }
                    ]
                }
            ]
        }
    """
    # Load workspaces
    workspaces = load_bison_workspaces_from_sheet(sheet_url)

    # Find the workspace by name (fuzzy matching)
    workspace = None
    search_term = client_name.lower()

    # Try exact match first
    for w in workspaces:
        if w["client_name"].lower() == search_term:
            workspace = w
            break

    # Try fuzzy match
    if not workspace:
        matches = []
        for w in workspaces:
            if search_term in w["client_name"].lower():
                matches.append(w)

        if len(matches) == 1:
            workspace = matches[0]
        elif len(matches) > 1:
            match_list = [w["client_name"] for w in matches]
            raise ValueError(
                f"Multiple matches found for '{client_name}':\n" +
                "\n".join(f"  - {m}" for m in match_list) +
                "\n\nPlease be more specific."
            )

    if not workspace:
        available = [w["client_name"] for w in workspaces[:10]]
        available_str = '\n'.join(f"  - {a}" for a in available)
        raise ValueError(
            f"Client '{client_name}' not found.\n\n"
            f"Available clients (showing first 10):\n{available_str}\n\n"
            f"Use get_bison_client_list() to see all {len(workspaces)} clients."
        )

    print(f"[Bison] Found client: {workspace['client_name']}")

    # Validate and parse dates with safeguards
    start_date, end_date, warnings = validate_and_parse_dates(start_date, end_date, days)

    # Call Bison API to get replies
    # Use folder='all' to get both unreplied and replied-to interested leads
    print(f"[Bison] Fetching interested replies for {workspace['client_name']}...")

    data = get_bison_lead_replies(
        api_key=workspace["api_key"],
        status="interested",
        folder="all"
    )

    # Group all interested replies by lead_id
    # The data already contains all interested messages (incoming and outgoing) from folder='all'
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    # Collect all interested replies within date range, grouped by lead_id
    replies_by_lead = {}
    for reply in data.get("data", []):
        date_received = reply.get("date_received")
        if date_received:
            reply_dt = datetime.fromisoformat(date_received.replace("Z", "+00:00"))
            if start_dt <= reply_dt.replace(tzinfo=None) <= end_dt:
                lead_id = reply.get("lead_id")
                if lead_id not in replies_by_lead:
                    replies_by_lead[lead_id] = []
                replies_by_lead[lead_id].append(reply)

    # For leads with only outgoing emails, fetch their incoming replies separately
    leads_needing_contact_info = []
    for lead_id, replies in replies_by_lead.items():
        has_incoming = any(r.get("type") == "Tracked Reply" for r in replies)
        if not has_incoming:
            leads_needing_contact_info.append(lead_id)

    # Fetch additional replies for leads without incoming interested replies
    additional_replies = {}
    if leads_needing_contact_info:
        print(f"[Bison] Fetching contact info for {len(leads_needing_contact_info)} leads...")
        all_data = get_bison_lead_replies(
            api_key=workspace["api_key"],
            status=None,  # No status filter to get all replies
            folder="all"
        )

        for lead_id in leads_needing_contact_info:
            lead_all_replies = [r for r in all_data.get("data", [])
                              if r.get("lead_id") == lead_id and r.get("type") == "Tracked Reply"]
            if lead_all_replies:
                # Get most recent incoming reply
                lead_all_replies.sort(key=lambda x: x.get("date_received", ""), reverse=True)
                additional_replies[lead_id] = lead_all_replies[0]

    # Build final leads list with proper contact info
    leads_by_id = {}
    for lead_id, replies in replies_by_lead.items():
        # Find the first incoming "Tracked Reply" for contact info
        best_reply = None
        for reply in replies:
            if reply.get("type") == "Tracked Reply":
                best_reply = reply
                break

        # If no incoming reply in interested set, use the one we fetched separately
        if not best_reply and lead_id in additional_replies:
            best_reply = additional_replies[lead_id]

        # Fallback to any reply if still nothing found
        if not best_reply and replies:
            best_reply = replies[0]

        if best_reply:
            leads_by_id[lead_id] = {
                "email": best_reply.get("from_email_address"),
                "from_name": best_reply.get("from_name"),
                "reply_body": best_reply.get("text_body") or best_reply.get("html_body", ""),
                "subject": best_reply.get("subject"),
                "date_received": best_reply.get("date_received"),
                "interested": True,
                "read": best_reply.get("read", False),
                "reply_id": best_reply.get("id"),
                "lead_id": lead_id
            }

    # Fetch conversation threads for each lead
    print(f"[Bison] Fetching conversation threads for {len(leads_by_id)} leads...")
    for lead_id, lead_data in leads_by_id.items():
        reply_id = lead_data["reply_id"]

        try:
            thread_response = get_bison_conversation_thread(
                api_key=workspace["api_key"],
                reply_id=reply_id
            )
            thread_data = thread_response.get("data", {})

            # Build chronological thread: older -> current -> newer
            thread = []

            # Add older messages (already in chronological order)
            for msg in thread_data.get("older_messages", []):
                thread.append({
                    "date_received": msg.get("date_received"),
                    "from_name": msg.get("from_name"),
                    "from_email": msg.get("from_email_address"),
                    "subject": msg.get("subject"),
                    "body": msg.get("text_body") or msg.get("html_body", ""),
                    "type": msg.get("type"),
                    "reply_id": msg.get("id")
                })

            # Add current reply
            current = thread_data.get("current_reply", {})
            if current:
                thread.append({
                    "date_received": current.get("date_received"),
                    "from_name": current.get("from_name"),
                    "from_email": current.get("from_email_address"),
                    "subject": current.get("subject"),
                    "body": current.get("text_body") or current.get("html_body", ""),
                    "type": current.get("type"),
                    "reply_id": current.get("id")
                })

            # Add newer messages
            for msg in thread_data.get("newer_messages", []):
                thread.append({
                    "date_received": msg.get("date_received"),
                    "from_name": msg.get("from_name"),
                    "from_email": msg.get("from_email_address"),
                    "subject": msg.get("subject"),
                    "body": msg.get("text_body") or msg.get("html_body", ""),
                    "type": msg.get("type"),
                    "reply_id": msg.get("id")
                })

            # Add thread to lead data
            lead_data["conversation_thread"] = thread
            lead_data["thread_message_count"] = len(thread)

        except Exception as e:
            print(f"[Bison] Warning: Could not fetch thread for lead {lead_id}: {e}")
            lead_data["conversation_thread"] = []
            lead_data["thread_message_count"] = 0

    # Convert to list, sorted by date (most recent first)
    leads = sorted(leads_by_id.values(), key=lambda x: x["date_received"], reverse=True)

    result = {
        "client_name": workspace["client_name"],
        "start_date": start_date,
        "end_date": end_date,
        "total_leads": len(leads),
        "leads": leads
    }

    # Add warnings if any
    if warnings:
        result["warnings"] = warnings

    return result


def get_bison_campaign_stats(
    client_name: str,
    start_date: str = None,
    end_date: str = None,
    days: int = 7,
    sheet_url: str = DEFAULT_SHEET_URL
):
    """
    MCP Tool: Get campaign statistics from Bison for a specific client.

    Args:
        client_name: Client name (supports fuzzy matching)
        start_date: Start date in YYYY-MM-DD format (optional)
        end_date: End date in YYYY-MM-DD format (optional)
        days: Number of days to look back (default: 7)
        sheet_url: Google Sheet URL (optional)

    Returns:
        {
            "client_name": str,
            "start_date": str,
            "end_date": str,
            "emails_sent": int,
            "total_leads_contacted": int,
            "opened": int,
            "opened_percentage": float,
            "unique_replies_per_contact": int,
            "unique_replies_per_contact_percentage": float,
            "bounced": int,
            "bounced_percentage": float,
            "unsubscribed": int,
            "unsubscribed_percentage": float,
            "interested": int,
            "interested_percentage": float
        }
    """
    # Load workspaces
    workspaces = load_bison_workspaces_from_sheet(sheet_url)

    # Find the workspace (same logic as get_bison_lead_responses)
    workspace = None
    search_term = client_name.lower()

    # Try exact match first
    for w in workspaces:
        if w["client_name"].lower() == search_term:
            workspace = w
            break

    # Try fuzzy match
    if not workspace:
        matches = []
        for w in workspaces:
            if search_term in w["client_name"].lower():
                matches.append(w)

        if len(matches) == 1:
            workspace = matches[0]
        elif len(matches) > 1:
            match_list = [w["client_name"] for w in matches]
            raise ValueError(
                f"Multiple matches found for '{client_name}':\n" +
                "\n".join(f"  - {m}" for m in match_list) +
                "\n\nPlease be more specific."
            )

    if not workspace:
        raise ValueError(f"Client '{client_name}' not found.")

    # Validate and parse dates with safeguards
    start_date, end_date, warnings = validate_and_parse_dates(start_date, end_date, days)

    # Call Bison stats API
    print(f"[Bison] Fetching campaign stats for {workspace['client_name']}...")

    response = get_bison_campaign_stats_api(
        api_key=workspace["api_key"],
        start_date=start_date,
        end_date=end_date
    )

    data = response.get("data", {})

    result = {
        "client_name": workspace["client_name"],
        "start_date": start_date,
        "end_date": end_date,
        "emails_sent": int(data.get("emails_sent", 0)),
        "total_leads_contacted": int(data.get("total_leads_contacted", 0)),
        "opened": int(data.get("opened", 0)),
        "opened_percentage": float(data.get("opened_percentage", 0)),
        "unique_replies_per_contact": int(data.get("unique_replies_per_contact", 0)),
        "unique_replies_per_contact_percentage": float(data.get("unique_replies_per_contact_percentage", 0)),
        "bounced": int(data.get("bounced", 0)),
        "bounced_percentage": float(data.get("bounced_percentage", 0)),
        "unsubscribed": int(data.get("unsubscribed", 0)),
        "unsubscribed_percentage": float(data.get("unsubscribed_percentage", 0)),
        "interested": int(data.get("interested", 0)),
        "interested_percentage": float(data.get("interested_percentage", 0))
    }

    # Add warnings if any
    if warnings:
        result["warnings"] = warnings

    return result


# ============================================================================
# UNIFIED FUNCTIONS (Both Instantly + Bison)
# ============================================================================

def get_all_clients(sheet_url: str = DEFAULT_SHEET_URL):
    """
    MCP Tool: Get list of ALL clients from both Instantly and Bison.

    Args:
        sheet_url: Google Sheet URL (optional)

    Returns:
        {
            "total_clients": int,
            "instantly_clients": [...],
            "bison_clients": [...],
            "clients": [
                {
                    "client_name": str,
                    "platform": "instantly" | "bison",
                    "workspace_id": str (only for instantly)
                }
            ]
        }
    """
    # Get both client lists
    instantly = get_client_list(sheet_url)
    bison = get_bison_client_list(sheet_url)

    # Combine into unified list
    all_clients = []

    # Add Instantly clients
    for client in instantly["clients"]:
        all_clients.append({
            "client_name": client["client_name"],
            "platform": "instantly",
            "workspace_id": client["workspace_id"]
        })

    # Add Bison clients
    for client in bison["clients"]:
        all_clients.append({
            "client_name": client["client_name"],
            "platform": "bison"
        })

    return {
        "total_clients": len(all_clients),
        "instantly_clients": instantly["clients"],
        "bison_clients": bison["clients"],
        "clients": all_clients
    }


# ============================================================================
# AGGREGATED ANALYTICS TOOLS
# ============================================================================

def get_all_platform_stats(days: int = 7, sheet_url: str = DEFAULT_SHEET_URL):
    """
    MCP Tool: Get aggregated statistics from BOTH Instantly and Bison platforms.

    Args:
        days: Number of days to look back (default: 7)
        sheet_url: Google Sheet URL (optional)

    Returns:
        {
            "date_range": {
                "days": int,
                "start_date": str,
                "end_date": str
            },
            "total_stats": {
                "total_emails_sent": int,
                "total_leads": int,
                "total_interested_leads": int,
                "platforms": {
                    "instantly": {...},
                    "bison": {...}
                }
            }
        }
    """
    print(f"[Analytics] Fetching aggregated stats for last {days} days...")

    # Calculate date range
    end = datetime.now()
    start = end - timedelta(days=days)
    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")

    # Get all clients
    instantly_workspaces = load_workspaces_from_sheet(sheet_url)
    bison_workspaces = load_bison_workspaces_from_sheet(sheet_url)

    # Instantly aggregated stats
    instantly_total_emails = 0
    instantly_total_replies = 0
    instantly_total_opportunities = 0
    instantly_clients_processed = 0

    for workspace in instantly_workspaces:
        try:
            stats = get_campaign_stats(
                workspace_id=workspace["workspace_id"],
                days=days,
                sheet_url=sheet_url
            )
            instantly_total_emails += stats.get("emails_sent", 0)
            instantly_total_replies += stats.get("replies", 0)
            instantly_total_opportunities += stats.get("opportunities", 0)
            instantly_clients_processed += 1
        except Exception as e:
            print(f"[Analytics] Warning: Failed to fetch Instantly stats for {workspace['workspace_id']}: {e}")
            continue

    # Bison aggregated stats
    bison_total_emails = 0
    bison_total_replies = 0
    bison_total_interested = 0
    bison_clients_processed = 0

    for workspace in bison_workspaces:
        try:
            stats = get_bison_campaign_stats(
                client_name=workspace["client_name"],
                days=days,
                sheet_url=sheet_url
            )
            bison_total_emails += stats.get("emails_sent", 0)
            bison_total_replies += stats.get("unique_replies_per_contact", 0)
            bison_total_interested += stats.get("interested", 0)
            bison_clients_processed += 1
        except Exception as e:
            print(f"[Analytics] Warning: Failed to fetch Bison stats for {workspace['client_name']}: {e}")
            continue

    # Calculate combined totals
    total_emails_sent = instantly_total_emails + bison_total_emails
    total_replies = instantly_total_replies + bison_total_replies
    total_interested = instantly_total_opportunities + bison_total_interested

    return {
        "date_range": {
            "days": days,
            "start_date": start_date,
            "end_date": end_date
        },
        "total_stats": {
            "total_emails_sent": total_emails_sent,
            "total_replies": total_replies,
            "total_interested_leads": total_interested,
            "reply_rate": round((total_replies / total_emails_sent * 100), 2) if total_emails_sent > 0 else 0,
            "clients_processed": instantly_clients_processed + bison_clients_processed
        },
        "platform_breakdown": {
            "instantly": {
                "clients": instantly_clients_processed,
                "emails_sent": instantly_total_emails,
                "replies": instantly_total_replies,
                "opportunities": instantly_total_opportunities,
                "reply_rate": round((instantly_total_replies / instantly_total_emails * 100), 2) if instantly_total_emails > 0 else 0
            },
            "bison": {
                "clients": bison_clients_processed,
                "emails_sent": bison_total_emails,
                "replies": bison_total_replies,
                "interested": bison_total_interested,
                "reply_rate": round((bison_total_replies / bison_total_emails * 100), 2) if bison_total_emails > 0 else 0
            }
        }
    }


def get_top_performing_clients(
    limit: int = 10,
    metric: str = "interested_leads",
    days: int = 7,
    sheet_url: str = DEFAULT_SHEET_URL
):
    """
    MCP Tool: Get top performing clients across both platforms.

    Args:
        limit: Number of top clients to return (default: 10)
        metric: Metric to sort by - "interested_leads", "emails_sent", "replies", "reply_rate" (default: "interested_leads")
        days: Number of days to look back (default: 7)
        sheet_url: Google Sheet URL (optional)

    Returns:
        {
            "metric": str,
            "days": int,
            "top_clients": [
                {
                    "rank": int,
                    "client_name": str,
                    "platform": str,
                    "metric_value": int/float,
                    "stats": {...}
                }
            ]
        }
    """
    print(f"[Analytics] Finding top {limit} clients by {metric}...")

    # Get all clients
    instantly_workspaces = load_workspaces_from_sheet(sheet_url)
    bison_workspaces = load_bison_workspaces_from_sheet(sheet_url)

    all_client_stats = []

    # Fetch Instantly client stats
    for workspace in instantly_workspaces:
        try:
            stats = get_campaign_stats(
                workspace_id=workspace["workspace_id"],
                days=days,
                sheet_url=sheet_url
            )

            metric_value = 0
            if metric == "interested_leads":
                metric_value = stats.get("opportunities", 0)
            elif metric == "emails_sent":
                metric_value = stats.get("emails_sent", 0)
            elif metric == "replies":
                metric_value = stats.get("replies", 0)
            elif metric == "reply_rate":
                metric_value = stats.get("reply_rate", 0)

            all_client_stats.append({
                "client_name": workspace["client_name"],
                "platform": "instantly",
                "metric_value": metric_value,
                "stats": stats
            })
        except Exception as e:
            print(f"[Analytics] Warning: Failed to fetch stats for {workspace['client_name']}: {e}")
            continue

    # Fetch Bison client stats
    for workspace in bison_workspaces:
        try:
            stats = get_bison_campaign_stats(
                client_name=workspace["client_name"],
                days=days,
                sheet_url=sheet_url
            )

            metric_value = 0
            if metric == "interested_leads":
                metric_value = stats.get("interested", 0)
            elif metric == "emails_sent":
                metric_value = stats.get("emails_sent", 0)
            elif metric == "replies":
                metric_value = stats.get("unique_replies_per_contact", 0)
            elif metric == "reply_rate":
                metric_value = stats.get("unique_replies_per_contact_percentage", 0)

            all_client_stats.append({
                "client_name": workspace["client_name"],
                "platform": "bison",
                "metric_value": metric_value,
                "stats": stats
            })
        except Exception as e:
            print(f"[Analytics] Warning: Failed to fetch stats for {workspace['client_name']}: {e}")
            continue

    # Sort by metric value (descending)
    all_client_stats.sort(key=lambda x: x["metric_value"], reverse=True)

    # Get top N
    top_clients = []
    for idx, client in enumerate(all_client_stats[:limit], start=1):
        top_clients.append({
            "rank": idx,
            "client_name": client["client_name"],
            "platform": client["platform"],
            "metric_value": client["metric_value"],
            "stats": client["stats"]
        })

    return {
        "metric": metric,
        "days": days,
        "limit": limit,
        "top_clients": top_clients
    }


def get_underperforming_clients(
    threshold: int = 5,
    metric: str = "interested_leads",
    days: int = 7,
    sheet_url: str = DEFAULT_SHEET_URL
):
    """
    MCP Tool: Get underperforming clients across both platforms.

    Args:
        threshold: Minimum value for the metric - clients below this are considered underperforming (default: 5)
        metric: Metric to check - "interested_leads", "emails_sent", "replies", "reply_rate" (default: "interested_leads")
        days: Number of days to look back (default: 7)
        sheet_url: Google Sheet URL (optional)

    Returns:
        {
            "metric": str,
            "threshold": int,
            "days": int,
            "underperforming_clients": [
                {
                    "client_name": str,
                    "platform": str,
                    "metric_value": int/float,
                    "stats": {...}
                }
            ]
        }
    """
    print(f"[Analytics] Finding clients with {metric} below {threshold}...")

    # Get all clients
    instantly_workspaces = load_workspaces_from_sheet(sheet_url)
    bison_workspaces = load_bison_workspaces_from_sheet(sheet_url)

    underperforming = []

    # Check Instantly clients
    for workspace in instantly_workspaces:
        try:
            stats = get_campaign_stats(
                workspace_id=workspace["workspace_id"],
                days=days,
                sheet_url=sheet_url
            )

            metric_value = 0
            if metric == "interested_leads":
                metric_value = stats.get("opportunities", 0)
            elif metric == "emails_sent":
                metric_value = stats.get("emails_sent", 0)
            elif metric == "replies":
                metric_value = stats.get("replies", 0)
            elif metric == "reply_rate":
                metric_value = stats.get("reply_rate", 0)

            if metric_value < threshold:
                underperforming.append({
                    "client_name": workspace["client_name"],
                    "platform": "instantly",
                    "metric_value": metric_value,
                    "stats": stats
                })
        except Exception as e:
            print(f"[Analytics] Warning: Failed to fetch stats for {workspace['client_name']}: {e}")
            continue

    # Check Bison clients
    for workspace in bison_workspaces:
        try:
            stats = get_bison_campaign_stats(
                client_name=workspace["client_name"],
                days=days,
                sheet_url=sheet_url
            )

            metric_value = 0
            if metric == "interested_leads":
                metric_value = stats.get("interested", 0)
            elif metric == "emails_sent":
                metric_value = stats.get("emails_sent", 0)
            elif metric == "replies":
                metric_value = stats.get("unique_replies_per_contact", 0)
            elif metric == "reply_rate":
                metric_value = stats.get("unique_replies_per_contact_percentage", 0)

            if metric_value < threshold:
                underperforming.append({
                    "client_name": workspace["client_name"],
                    "platform": "bison",
                    "metric_value": metric_value,
                    "stats": stats
                })
        except Exception as e:
            print(f"[Analytics] Warning: Failed to fetch stats for {workspace['client_name']}: {e}")
            continue

    # Sort by metric value (ascending - worst performers first)
    underperforming.sort(key=lambda x: x["metric_value"])

    return {
        "metric": metric,
        "threshold": threshold,
        "days": days,
        "total_underperforming": len(underperforming),
        "underperforming_clients": underperforming
    }


def get_weekly_summary(sheet_url: str = DEFAULT_SHEET_URL):
    """
    MCP Tool: Generate a comprehensive weekly summary across all clients and platforms.
    OPTIMIZED: Fetches stats once and reuses data instead of making 240+ API calls.

    Args:
        sheet_url: Google Sheet URL (optional)

    Returns:
        {
            "period": "Last 7 days",
            "overall_stats": {...},
            "top_performers": [...],
            "underperformers": [...],
            "insights": [...]
        }
    """
    print("[Analytics] Generating optimized weekly summary...")

    days = 7

    # Calculate date range
    end = datetime.now()
    start = end - timedelta(days=days)
    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")

    # Get all clients
    instantly_workspaces = load_workspaces_from_sheet(sheet_url)
    bison_workspaces = load_bison_workspaces_from_sheet(sheet_url)

    # FETCH ALL STATS ONCE (instead of 3 times)
    all_client_stats = []

    instantly_total_emails = 0
    instantly_total_replies = 0
    instantly_total_opportunities = 0
    instantly_clients_processed = 0

    print(f"[Analytics] Fetching stats from {len(instantly_workspaces)} Instantly clients...")
    for workspace in instantly_workspaces:
        try:
            stats = get_campaign_stats(
                workspace_id=workspace["workspace_id"],
                days=days,
                sheet_url=sheet_url
            )
            instantly_total_emails += stats.get("emails_sent", 0)
            instantly_total_replies += stats.get("replies", 0)
            instantly_total_opportunities += stats.get("opportunities", 0)
            instantly_clients_processed += 1

            # Store for ranking
            all_client_stats.append({
                "client_name": workspace["client_name"],
                "platform": "instantly",
                "interested_leads": stats.get("opportunities", 0),
                "stats": stats
            })
        except Exception as e:
            print(f"[Analytics] Warning: Failed to fetch Instantly stats for {workspace['workspace_id']}: {e}")
            continue

    bison_total_emails = 0
    bison_total_replies = 0
    bison_total_interested = 0
    bison_clients_processed = 0

    print(f"[Analytics] Fetching stats from {len(bison_workspaces)} Bison clients...")
    for workspace in bison_workspaces:
        try:
            stats = get_bison_campaign_stats(
                client_name=workspace["client_name"],
                days=days,
                sheet_url=sheet_url
            )
            bison_total_emails += stats.get("emails_sent", 0)
            bison_total_replies += stats.get("unique_replies_per_contact", 0)
            bison_total_interested += stats.get("interested", 0)
            bison_clients_processed += 1

            # Store for ranking
            all_client_stats.append({
                "client_name": workspace["client_name"],
                "platform": "bison",
                "interested_leads": stats.get("interested", 0),
                "stats": stats
            })
        except Exception as e:
            print(f"[Analytics] Warning: Failed to fetch Bison stats for {workspace['client_name']}: {e}")
            continue

    # Calculate combined totals
    total_emails_sent = instantly_total_emails + bison_total_emails
    total_replies = instantly_total_replies + bison_total_replies
    total_interested = instantly_total_opportunities + bison_total_interested

    overall = {
        "total_stats": {
            "total_emails_sent": total_emails_sent,
            "total_replies": total_replies,
            "total_interested_leads": total_interested,
            "reply_rate": round((total_replies / total_emails_sent * 100), 2) if total_emails_sent > 0 else 0,
            "clients_processed": instantly_clients_processed + bison_clients_processed
        },
        "platform_breakdown": {
            "instantly": {
                "clients": instantly_clients_processed,
                "emails_sent": instantly_total_emails,
                "replies": instantly_total_replies,
                "opportunities": instantly_total_opportunities,
                "reply_rate": round((instantly_total_replies / instantly_total_emails * 100), 2) if instantly_total_emails > 0 else 0
            },
            "bison": {
                "clients": bison_clients_processed,
                "emails_sent": bison_total_emails,
                "replies": bison_total_replies,
                "interested": bison_total_interested,
                "reply_rate": round((bison_total_replies / bison_total_emails * 100), 2) if bison_total_emails > 0 else 0
            }
        }
    }

    # Sort and get top 5 performers (reusing fetched data)
    all_client_stats.sort(key=lambda x: x["interested_leads"], reverse=True)
    top_clients = []
    for idx, client in enumerate(all_client_stats[:5], start=1):
        top_clients.append({
            "rank": idx,
            "client_name": client["client_name"],
            "platform": client["platform"],
            "metric_value": client["interested_leads"],
            "stats": client["stats"]
        })

    # Get underperformers (less than 3 interested leads)
    underperforming = [
        {
            "client_name": client["client_name"],
            "platform": client["platform"],
            "metric_value": client["interested_leads"],
            "stats": client["stats"]
        }
        for client in all_client_stats
        if client["interested_leads"] < 3
    ]
    underperforming.sort(key=lambda x: x["metric_value"])

    # Generate insights
    insights = []

    # Platform comparison
    instantly_stats = overall["platform_breakdown"]["instantly"]
    bison_stats = overall["platform_breakdown"]["bison"]

    if instantly_stats["emails_sent"] > bison_stats["emails_sent"]:
        insights.append(f"Instantly sent {instantly_stats['emails_sent'] - bison_stats['emails_sent']:,} more emails than Bison")
    else:
        insights.append(f"Bison sent {bison_stats['emails_sent'] - instantly_stats['emails_sent']:,} more emails than Instantly")

    if instantly_stats["reply_rate"] > bison_stats["reply_rate"]:
        insights.append(f"Instantly has a better reply rate ({instantly_stats['reply_rate']}%) vs Bison ({bison_stats['reply_rate']}%)")
    else:
        insights.append(f"Bison has a better reply rate ({bison_stats['reply_rate']}%) vs Instantly ({instantly_stats['reply_rate']}%)")

    # Top performer insight
    if top_clients:
        top = top_clients[0]
        insights.append(f"Top performer: {top['client_name']} ({top['platform']}) with {top['metric_value']} interested leads")

    # Underperformer insight
    if underperforming:
        insights.append(f"{len(underperforming)} clients need attention (less than 3 interested leads)")

    return {
        "period": f"Last {days} days",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overall_stats": overall["total_stats"],
        "platform_breakdown": overall["platform_breakdown"],
        "top_5_performers": top_clients,
        "underperformers": {
            "count": len(underperforming),
            "clients": underperforming
        },
        "insights": insights
    }


# Test the functions
if __name__ == "__main__":
    print("="*80)
    print("TESTING MCP FUNCTIONS")
    print("="*80)

    # Test 1: Get client list
    print("\n1. Getting client list...")
    try:
        clients = get_client_list()
        print(f"Found {clients['total_clients']} clients:")
        for c in clients['clients'][:5]:
            print(f"   - {c['workspace_id']}")
        if clients['total_clients'] > 5:
            print(f"   ... and {clients['total_clients'] - 5} more")
    except Exception as e:
        print(f"Error: {e}")

    # Test 2: Get lead responses for first client
    if clients['clients']:
        print(f"\n2. Getting lead responses for first client...")
        first_client = clients['clients'][0]['workspace_id']
        try:
            leads = get_lead_responses(first_client, days=30)
            print(f"{first_client}: {leads['total_leads']} interested leads")
            if leads['leads']:
                print(f"   Sample: {leads['leads'][0]['email']}")
        except Exception as e:
            print(f"Error: {e}")

        # Test 3: Get campaign stats
        print(f"\n3. Getting campaign stats for first client...")
        try:
            stats = get_campaign_stats(first_client, days=30)
            print(f"{stats['workspace_id']}:")
            print(f"   - Emails sent: {stats['emails_sent']:,}")
            print(f"   - Replies: {stats['replies']}")
            print(f"   - Opportunities: {stats['opportunities']}")
        except Exception as e:
            print(f"Error: {e}")
