"""
MCP-ready functions that combine Google Sheets + Instantly API + Bison API.
These will be the tools exposed to Claude via MCP.
"""

import logging
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

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
    sheet_url: str = DEFAULT_SHEET_URL,
    gid: str = None
):
    """
    MCP Tool: Get positive lead responses for a specific client/workspace.

    Args:
        workspace_id: Client name or workspace ID (e.g., "ABC Corp")
        start_date: Start date in ISO format (optional if using 'days')
        end_date: End date in ISO format (optional if using 'days')
        days: Number of days to look back (default: 7)
        sheet_url: Google Sheet URL (optional)
        gid: Google Sheet GID for specific tab (optional)

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
    workspaces = load_workspaces_from_sheet(sheet_url, gid=gid)

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
    sheet_url: str = DEFAULT_SHEET_URL,
    gid: str = None
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
        gid: Google Sheet GID for specific tab (optional)

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
    workspaces = load_workspaces_from_sheet(sheet_url, gid=gid)

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

def get_bison_client_list(sheet_url: str = DEFAULT_SHEET_URL, gid: str = SHEET_GID_BISON):
    """
    MCP Tool: Get list of all Bison clients.

    Args:
        sheet_url: Google Sheet URL (optional)
        gid: Google Sheet GID (optional)

    Returns:
        {
            "total_clients": int,
            "clients": [
                {"client_name": "ABC Corp"},
                ...
            ]
        }
    """
    workspaces = load_bison_workspaces_from_sheet(sheet_url, gid=gid)

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
    sheet_url: str = DEFAULT_SHEET_URL,
    gid: str = SHEET_GID_BISON
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
        gid: Google Sheet GID (optional)

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
    workspaces = load_bison_workspaces_from_sheet(sheet_url, gid=gid)

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


    # Validate and parse dates with safeguards
    start_date, end_date, warnings = validate_and_parse_dates(start_date, end_date, days)

    # Call Bison API to get replies
    # Use folder='all' to get both unreplied and replied-to interested leads

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
    sheet_url: str = DEFAULT_SHEET_URL,
    gid: str = SHEET_GID_BISON
):
    """
    MCP Tool: Get campaign statistics from Bison for a specific client.

    Args:
        client_name: Client name (supports fuzzy matching)
        start_date: Start date in YYYY-MM-DD format (optional)
        end_date: End date in YYYY-MM-DD format (optional)
        days: Number of days to look back (default: 7)
        sheet_url: Google Sheet URL (optional)
        gid: Google Sheet GID (optional)

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
    workspaces = load_bison_workspaces_from_sheet(sheet_url, gid=gid)

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
    OPTIMIZED: Uses parallel processing to fetch stats from all clients simultaneously.

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
    # Progress logging removed for MCP compatibility

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

    # PARALLEL PROCESSING: Fetch Instantly stats for all clients simultaneously
    with ThreadPoolExecutor(max_workers=15) as executor:
        # Submit all Instantly client fetches
        future_to_workspace = {
            executor.submit(get_campaign_stats, workspace["workspace_id"], days=days, sheet_url=sheet_url): workspace
            for workspace in instantly_workspaces
        }

        # Collect results as they complete
        for future in as_completed(future_to_workspace):
            workspace = future_to_workspace[future]
            try:
                stats = future.result()
                instantly_total_emails += stats.get("emails_sent", 0)
                instantly_total_replies += stats.get("replies", 0)
                instantly_total_opportunities += stats.get("opportunities", 0)
                instantly_clients_processed += 1
            except Exception as e:
                # Error logging removed for MCP compatibility
                continue

    # Bison aggregated stats
    bison_total_emails = 0
    bison_total_replies = 0
    bison_total_interested = 0
    bison_clients_processed = 0

    # PARALLEL PROCESSING: Fetch Bison stats for all clients simultaneously
    with ThreadPoolExecutor(max_workers=15) as executor:
        # Submit all Bison client fetches
        future_to_workspace = {
            executor.submit(get_bison_campaign_stats, workspace["client_name"], days=days, sheet_url=sheet_url): workspace
            for workspace in bison_workspaces
        }

        # Collect results as they complete
        for future in as_completed(future_to_workspace):
            workspace = future_to_workspace[future]
            try:
                stats = future.result()
                bison_total_emails += stats.get("emails_sent", 0)
                bison_total_replies += stats.get("unique_replies_per_contact", 0)
                bison_total_interested += stats.get("interested", 0)
                bison_clients_processed += 1
            except Exception as e:
                # Error logging removed for MCP compatibility
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
    OPTIMIZED: Uses parallel processing to fetch all client stats simultaneously.

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
    # Progress logging removed for MCP compatibility

    # Get all clients
    instantly_workspaces = load_workspaces_from_sheet(sheet_url)
    bison_workspaces = load_bison_workspaces_from_sheet(sheet_url)

    all_client_stats = []

    # Helper function to fetch and parse Instantly stats
    def fetch_instantly_stats(workspace):
        stats = get_campaign_stats(workspace_id=workspace["workspace_id"], days=days, sheet_url=sheet_url)
        metric_value = 0
        if metric == "interested_leads":
            metric_value = stats.get("opportunities", 0)
        elif metric == "emails_sent":
            metric_value = stats.get("emails_sent", 0)
        elif metric == "replies":
            metric_value = stats.get("replies", 0)
        elif metric == "reply_rate":
            metric_value = stats.get("reply_rate", 0)
        return {
            "client_name": workspace["client_name"],
            "platform": "instantly",
            "metric_value": metric_value,
            "stats": stats
        }

    # Helper function to fetch and parse Bison stats
    def fetch_bison_stats(workspace):
        stats = get_bison_campaign_stats(client_name=workspace["client_name"], days=days, sheet_url=sheet_url)
        metric_value = 0
        if metric == "interested_leads":
            metric_value = stats.get("interested", 0)
        elif metric == "emails_sent":
            metric_value = stats.get("emails_sent", 0)
        elif metric == "replies":
            metric_value = stats.get("unique_replies_per_contact", 0)
        elif metric == "reply_rate":
            metric_value = stats.get("unique_replies_per_contact_percentage", 0)
        return {
            "client_name": workspace["client_name"],
            "platform": "bison",
            "metric_value": metric_value,
            "stats": stats
        }

    # PARALLEL PROCESSING: Fetch ALL client stats simultaneously
    with ThreadPoolExecutor(max_workers=15) as executor:
        # Submit all tasks
        futures = []
        futures.extend([executor.submit(fetch_instantly_stats, ws) for ws in instantly_workspaces])
        futures.extend([executor.submit(fetch_bison_stats, ws) for ws in bison_workspaces])

        # Collect results as they complete
        for future in as_completed(futures):
            try:
                client_stat = future.result()
                all_client_stats.append(client_stat)
            except Exception as e:
                # Error logging removed for MCP compatibility
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
    OPTIMIZED: Uses parallel processing to fetch all client stats simultaneously.

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
    # Progress logging removed for MCP compatibility

    # Get all clients
    instantly_workspaces = load_workspaces_from_sheet(sheet_url)
    bison_workspaces = load_bison_workspaces_from_sheet(sheet_url)

    underperforming = []

    # Helper function to check Instantly client
    def check_instantly_client(workspace):
        stats = get_campaign_stats(workspace_id=workspace["workspace_id"], days=days, sheet_url=sheet_url)
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
            return {
                "client_name": workspace["client_name"],
                "platform": "instantly",
                "metric_value": metric_value,
                "stats": stats
            }
        return None

    # Helper function to check Bison client
    def check_bison_client(workspace):
        stats = get_bison_campaign_stats(client_name=workspace["client_name"], days=days, sheet_url=sheet_url)
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
            return {
                "client_name": workspace["client_name"],
                "platform": "bison",
                "metric_value": metric_value,
                "stats": stats
            }
        return None

    # PARALLEL PROCESSING: Check ALL clients simultaneously
    with ThreadPoolExecutor(max_workers=15) as executor:
        # Submit all tasks
        futures = []
        futures.extend([executor.submit(check_instantly_client, ws) for ws in instantly_workspaces])
        futures.extend([executor.submit(check_bison_client, ws) for ws in bison_workspaces])

        # Collect results as they complete
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:  # Only add if client is underperforming
                    underperforming.append(result)
            except Exception as e:
                # Error logging removed for MCP compatibility
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
    # Progress logging removed for MCP compatibility

    days = 7

    # Calculate date range
    end = datetime.now()
    start = end - timedelta(days=days)
    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")

    # Get all clients
    instantly_workspaces = load_workspaces_from_sheet(sheet_url)
    bison_workspaces = load_bison_workspaces_from_sheet(sheet_url)

    # FETCH ALL STATS ONCE (instead of 3 times) - NOW WITH PARALLEL PROCESSING
    all_client_stats = []

    instantly_total_emails = 0
    instantly_total_replies = 0
    instantly_total_opportunities = 0
    instantly_clients_processed = 0

    # Helper function to fetch Instantly stats
    def fetch_instantly_stats_for_summary(workspace):
        stats = get_campaign_stats(workspace_id=workspace["workspace_id"], days=days, sheet_url=sheet_url)
        return {
            "client_name": workspace["client_name"],
            "platform": "instantly",
            "interested_leads": stats.get("opportunities", 0),
            "emails_sent": stats.get("emails_sent", 0),
            "replies": stats.get("replies", 0),
            "stats": stats
        }

    # PARALLEL PROCESSING: Fetch all Instantly stats simultaneously
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(fetch_instantly_stats_for_summary, ws) for ws in instantly_workspaces]

        for future in as_completed(futures):
            try:
                client_data = future.result()
                instantly_total_emails += client_data["emails_sent"]
                instantly_total_replies += client_data["replies"]
                instantly_total_opportunities += client_data["interested_leads"]
                instantly_clients_processed += 1
                all_client_stats.append(client_data)
            except Exception as e:
                # Error logging removed for MCP compatibility
                continue

    bison_total_emails = 0
    bison_total_replies = 0
    bison_total_interested = 0
    bison_clients_processed = 0

    # Helper function to fetch Bison stats
    def fetch_bison_stats_for_summary(workspace):
        stats = get_bison_campaign_stats(client_name=workspace["client_name"], days=days, sheet_url=sheet_url)
        return {
            "client_name": workspace["client_name"],
            "platform": "bison",
            "interested_leads": stats.get("interested", 0),
            "emails_sent": stats.get("emails_sent", 0),
            "replies": stats.get("unique_replies_per_contact", 0),
            "stats": stats
        }

    # PARALLEL PROCESSING: Fetch all Bison stats simultaneously
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(fetch_bison_stats_for_summary, ws) for ws in bison_workspaces]

        for future in as_completed(futures):
            try:
                client_data = future.result()
                bison_total_emails += client_data["emails_sent"]
                bison_total_replies += client_data["replies"]
                bison_total_interested += client_data["interested_leads"]
                bison_clients_processed += 1
                all_client_stats.append(client_data)
            except Exception as e:
                # Error logging removed for MCP compatibility
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
    print("TESTING MCP FUNCTIONS")

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
INSTANTLY_ACCOUNTS_URL = "https://api.instantly.ai/api/v1/account/list"
INSTANTLY_WORKSPACE_URL = "https://api.instantly.ai/api/v1/workspaces/current"
EMAIL_BISON_ACCOUNTS_URL = "https://send.leadgenjay.com/api/sender-emails"
EMAIL_BISON_REPLIES_URL = "https://send.leadgenjay.com/api/sender-emails/{sender_id}/replies"


def _fetch_workspace_info(api_key: str) -> Dict[str, str]:
    """
    Fetch workspace info from Instantly API.

    Args:
        api_key: Instantly API key

    Returns:
        Dictionary with workspace_id and workspace_name
    """
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(INSTANTLY_WORKSPACE_URL, headers=headers, timeout=30)
        if not resp.ok:
            logger.warning(f"Error fetching workspace info: {resp.status_code}")
            resp.raise_for_status()

        data = resp.json()
        return {
            "workspace_id": data.get("id", ""),
            "workspace_name": data.get("name", "")
        }
    except Exception as e:
        logger.error(f"Exception fetching workspace info: {e}")
        return {"workspace_id": "", "workspace_name": ""}


def _fetch_instantly_accounts(api_key: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Fetch email accounts from Instantly API with pagination.

    Args:
        api_key: Instantly API key
        limit: Page size

    Returns:
        List of account dictionaries
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    all_accounts = []
    starting_after = None

    try:
        while True:
            params = {"limit": limit}
            if starting_after:
                params["starting_after"] = starting_after

            resp = requests.get(
                INSTANTLY_ACCOUNTS_URL,
                headers=headers,
                params=params,
                timeout=30
            )

            if not resp.ok:
                logger.warning(f"Error fetching Instantly accounts: {resp.status_code}")
                resp.raise_for_status()

            data = resp.json()
            items = data.get("items", [])
            all_accounts.extend(items)

            # Check for next page
            starting_after = data.get("next_starting_after")
            if not starting_after:
                break

        logger.info(f"Fetched {len(all_accounts)} Instantly email accounts")
        return all_accounts

    except Exception as e:
        logger.error(f"Exception fetching Instantly accounts: {e}")
        return []


def _fetch_emailbison_accounts(api_key: str) -> List[Dict[str, Any]]:
    """
    Fetch sender emails from LeadGenJay API.

    Args:
        api_key: LeadGenJay API key

    Returns:
        List of sender email dictionaries
    """
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(
            EMAIL_BISON_ACCOUNTS_URL,
            headers=headers,
            timeout=30
        )

        if not resp.ok:
            logger.warning(f"Error fetching LeadGenJay sender emails: {resp.status_code}")
            resp.raise_for_status()

        data = resp.json()
        accounts = data.get("data", [])

        logger.info(f"Fetched {len(accounts)} LeadGenJay sender emails")
        return accounts

    except Exception as e:
        logger.error(f"Exception fetching LeadGenJay sender emails: {e}")
        return []


def _fetch_emailbison_sender_replies(
    api_key: str,
    sender_id: int,
    per_page: int = 15,
    search: str = None,
    interested: bool = None,
    status: str = None,
    max_results: int = None
) -> List[Dict[str, Any]]:
    """
    Fetch ALL replies for a specific sender email from LeadGenJay API with pagination.

    Args:
        api_key: LeadGenJay API key
        sender_id: Sender email ID
        per_page: Results per page (max 15 for Bison)
        search: Search query
        interested: Filter by interested status (True/False)
        status: Filter by reply status
        max_results: Maximum total results to fetch (optional)

    Returns:
        List of all reply dictionaries
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    url = EMAIL_BISON_REPLIES_URL.format(sender_id=sender_id)

    all_replies = []
    page = 1

    # Build base query parameters
    params = {"per_page": min(per_page, 15)}  # Bison max is 15
    if search:
        params["search"] = search
    if interested is not None:
        params["interested"] = "true" if interested else "false"
    if status:
        params["status"] = status

    try:
        while True:
            # Add page number
            params["page"] = page

            resp = requests.get(url, headers=headers, params=params, timeout=30)

            if not resp.ok:
                logger.warning(f"Error fetching sender replies: {resp.status_code}")
                resp.raise_for_status()

            data = resp.json()
            replies = data.get("data", [])

            if not replies:
                # No more results
                break

            all_replies.extend(replies)
            logger.info(f"Fetched page {page} with {len(replies)} replies for sender {sender_id}")

            # Check if we've reached max_results
            if max_results and len(all_replies) >= max_results:
                all_replies = all_replies[:max_results]
                break

            # Check if there are more pages
            meta = data.get("meta", {})
            current_page = meta.get("current_page", page)
            last_page = meta.get("last_page", page)

            if current_page >= last_page:
                break

            page += 1

        logger.info(f"Fetched total of {len(all_replies)} replies for sender {sender_id}")
        return all_replies

    except Exception as e:
        logger.error(f"Exception fetching sender replies: {e}")
        return []


def get_instantly_mailboxes(
    sheet_url: str,
    instantly_gid: str,
    workspace_id: str
) -> Dict[str, Any]:
    """
    Get all connected email accounts (mailboxes) for an Instantly workspace.

    Args:
        sheet_url: Google Sheets URL with API keys
        instantly_gid: Instantly sheet GID
        workspace_id: Workspace ID to query

    Returns:
        Dictionary with mailbox data and health status
    """
    try:
        # Load clients
        workspaces = load_workspaces_from_sheet(sheet_url, gid=instantly_gid)

        # Find the workspace
        workspace = next((ws for ws in workspaces if ws['workspace_id'] == workspace_id), None)
        if not workspace:
            raise ValueError(f"Workspace {workspace_id} not found")

        api_key = workspace['api_key']

        # Get workspace info
        workspace_info = _fetch_workspace_info(api_key)
        workspace_name = workspace_info.get("workspace_name") or workspace_id

        # Fetch accounts
        accounts = _fetch_instantly_accounts(api_key)

        # Status code mapping
        status_map = {
            1: "Active",
            2: "Paused",
            -1: "Connection Error",
            -2: "Soft Bounce Error",
            -3: "Sending Error"
        }

        warmup_map = {1: "Active", 0: "Inactive"}

        # Process accounts
        processed_accounts = []
        status_breakdown = {}
        healthy_count = 0
        at_risk_count = 0
        early_count = 0

        for account in accounts:
            status_code = account.get("status")
            status_name = status_map.get(status_code, f"Unknown ({status_code})")
            status_breakdown[status_name] = status_breakdown.get(status_name, 0) + 1

            # Determine health
            if status_code == 1:
                health = "healthy"
                healthy_count += 1
            elif status_code == 2:
                health = "early"
                early_count += 1
            else:
                health = "at_risk"
                at_risk_count += 1

            processed_accounts.append({
                "email": account.get("email", "Unknown"),
                "status": status_name,
                "status_code": status_code,
                "daily_limit": account.get("daily_limit", 0),
                "warmup_status": warmup_map.get(account.get("warmup_status"), "Unknown"),
                "warmup_score": account.get("stat_warmup_score", 0),
                "last_used": account.get("timestamp_last_used", "Never"),
                "health": health,
                "provider": account.get("provider_code", "Unknown")
            })

        logger.info(
            f"Instantly workspace {workspace_name}: {len(processed_accounts)} accounts | "
            f"Healthy: {healthy_count}, At Risk: {at_risk_count}, Early: {early_count}"
        )

        return {
            "workspace_id": workspace_id,
            "workspace_name": workspace_name,
            "platform": "instantly",
            "total_accounts": len(processed_accounts),
            "healthy_count": healthy_count,
            "at_risk_count": at_risk_count,
            "early_count": early_count,
            "status_breakdown": status_breakdown,
            "accounts": processed_accounts
        }

    except Exception as e:
        logger.error(f"Error getting Instantly mailboxes: {e}")
        raise


def get_bison_mailboxes(
    sheet_url: str,
    bison_gid: str,
    client_name: str
) -> Dict[str, Any]:
    """
    Get all connected email accounts (mailboxes) for a Bison client.

    Args:
        sheet_url: Google Sheets URL with API keys
        bison_gid: Bison sheet GID
        client_name: Client name to query

    Returns:
        Dictionary with mailbox data and health status
    """
    try:
        # Load clients
        workspaces = load_bison_workspaces_from_sheet(sheet_url, gid=bison_gid)

        # Find the client
        workspace = next((ws for ws in workspaces if ws['client_name'].lower() == client_name.lower()), None)
        if not workspace:
            raise ValueError(f"Client {client_name} not found")

        api_key = workspace['api_key']

        # Fetch accounts
        accounts = _fetch_emailbison_accounts(api_key)

        # Process accounts
        processed_accounts = []
        status_breakdown = {}
        healthy_count = 0
        at_risk_count = 0

        for account in accounts:
            status = account.get("status", "Unknown")
            status_breakdown[status] = status_breakdown.get(status, 0) + 1

            # Determine health
            health = "healthy" if status == "Connected" else "at_risk"
            if health == "healthy":
                healthy_count += 1
            else:
                at_risk_count += 1

            # Extract tags
            tags = account.get("tags", [])
            tag_names = [tag.get("name") for tag in tags if tag.get("name")]

            processed_accounts.append({
                "email": account.get("email", "Unknown"),
                "name": account.get("name", ""),
                "status": status,
                "daily_limit": account.get("daily_limit", 0),
                "emails_sent": account.get("emails_sent_count", 0),
                "total_replies": account.get("total_replied_count", 0),
                "unique_replies": account.get("unique_replied_count", 0),
                "unique_opens": account.get("unique_opened_count", 0),
                "total_opens": account.get("total_opened_count", 0),
                "unsubscribed": account.get("unsubscribed_count", 0),
                "bounces": account.get("bounced_count", 0),
                "interested_leads": account.get("interested_leads_count", 0),
                "total_leads_contacted": account.get("total_leads_contacted_count", 0),
                "health": health,
                "tags": tag_names,
                "type": account.get("type", ""),
                "created_at": account.get("created_at", ""),
                "updated_at": account.get("updated_at", "")
            })

        logger.info(
            f"Bison client {client_name}: {len(processed_accounts)} accounts | "
            f"Healthy: {healthy_count}, At Risk: {at_risk_count}"
        )

        return {
            "client_name": client_name,
            "platform": "bison",
            "total_accounts": len(processed_accounts),
            "healthy_count": healthy_count,
            "at_risk_count": at_risk_count,
            "status_breakdown": status_breakdown,
            "accounts": processed_accounts
        }

    except Exception as e:
        logger.error(f"Error getting Bison mailboxes: {e}")
        raise


def get_bison_sender_replies(
    sheet_url: str,
    bison_gid: str,
    client_name: str,
    sender_email: str = None,
    interested_only: bool = False,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Get email replies for Bison sender email(s).

    Args:
        sheet_url: Google Sheets URL with API keys
        bison_gid: Bison sheet GID
        client_name: Client name to query
        sender_email: Specific sender email address (optional, gets all if not provided)
        interested_only: Filter to only interested leads
        limit: Max replies to return per sender

    Returns:
        Dictionary with reply data for sender email(s)
    """
    try:
        # Load clients
        workspaces = load_bison_workspaces_from_sheet(sheet_url, gid=bison_gid)

        # Find the client
        workspace = next((ws for ws in workspaces if ws['client_name'].lower() == client_name.lower()), None)
        if not workspace:
            raise ValueError(f"Client {client_name} not found")

        api_key = workspace['api_key']

        # Fetch sender accounts
        accounts = _fetch_emailbison_accounts(api_key)

        # Filter to specific sender if provided
        if sender_email:
            accounts = [acc for acc in accounts if acc.get("email", "").lower() == sender_email.lower()]
            if not accounts:
                raise ValueError(f"Sender email {sender_email} not found for client {client_name}")

        # Fetch replies for each sender
        all_replies = []
        sender_summaries = []

        for account in accounts:
            sender_id = account.get("id")
            sender_email_addr = account.get("email", "Unknown")

            # Fetch ALL replies with pagination
            replies = _fetch_emailbison_sender_replies(
                api_key=api_key,
                sender_id=sender_id,
                per_page=15,  # Bison max
                interested=interested_only if interested_only else None,
                max_results=limit if limit else None
            )

            total_replies = len(replies)

            # Process replies
            processed_replies = []
            for reply in replies:
                processed_replies.append({
                    "id": reply.get("id"),
                    "lead_email": reply.get("lead_email", "Unknown"),
                    "lead_name": reply.get("lead_name", ""),
                    "company": reply.get("company", ""),
                    "reply_text": reply.get("reply_text", ""),
                    "interested": reply.get("interested", False),
                    "status": reply.get("status", ""),
                    "replied_at": reply.get("replied_at", ""),
                    "campaign_name": reply.get("campaign_name", ""),
                    "sequence_step": reply.get("sequence_step", 0)
                })

            sender_summaries.append({
                "sender_email": sender_email_addr,
                "sender_id": sender_id,
                "total_replies": total_replies,
                "showing": len(processed_replies),
                "interested_count": sum(1 for r in processed_replies if r["interested"])
            })

            all_replies.extend(processed_replies)

        logger.info(
            f"Bison client {client_name}: Fetched {len(all_replies)} replies from {len(sender_summaries)} sender(s)"
        )

        return {
            "client_name": client_name,
            "platform": "bison",
            "total_senders": len(sender_summaries),
            "total_replies": len(all_replies),
            "interested_count": sum(1 for r in all_replies if r["interested"]),
            "sender_summaries": sender_summaries,
            "replies": all_replies
        }

    except Exception as e:
        logger.error(f"Error getting Bison sender replies: {e}")
        raise


def get_all_mailbox_health(
    sheet_url: str,
    instantly_gid: str,
    bison_gid: str
) -> Dict[str, Any]:
    """
    Get aggregated mailbox health across all clients and platforms.

    Args:
        sheet_url: Google Sheets URL
        instantly_gid: Instantly sheet GID
        bison_gid: Bison sheet GID

    Returns:
        Dictionary with aggregated mailbox health data
    """
    try:
        # Get all clients
        all_clients = get_all_clients(sheet_url)

        total_accounts = 0
        total_healthy = 0
        total_at_risk = 0
        total_early = 0

        instantly_totals = {"accounts": 0, "healthy": 0, "at_risk": 0, "early": 0}
        bison_totals = {"accounts": 0, "healthy": 0, "at_risk": 0}

        client_summaries = []

        # Process each client
        for client in all_clients['clients']:
            try:
                if client['platform'] == 'instantly':
                    mailboxes = get_instantly_mailboxes(
                        sheet_url, instantly_gid,
                        client['workspace_id']
                    )

                    instantly_totals['accounts'] += mailboxes['total_accounts']
                    instantly_totals['healthy'] += mailboxes['healthy_count']
                    instantly_totals['at_risk'] += mailboxes['at_risk_count']
                    instantly_totals['early'] += mailboxes['early_count']

                    total_accounts += mailboxes['total_accounts']
                    total_healthy += mailboxes['healthy_count']
                    total_at_risk += mailboxes['at_risk_count']
                    total_early += mailboxes['early_count']

                elif client['platform'] == 'bison':
                    mailboxes = get_bison_mailboxes(
                        sheet_url, bison_gid,
                        client['client_name']
                    )

                    bison_totals['accounts'] += mailboxes['total_accounts']
                    bison_totals['healthy'] += mailboxes['healthy_count']
                    bison_totals['at_risk'] += mailboxes['at_risk_count']

                    total_accounts += mailboxes['total_accounts']
                    total_healthy += mailboxes['healthy_count']
                    total_at_risk += mailboxes['at_risk_count']

                # Add to summaries
                client_summaries.append({
                    'client_name': client.get('client_name') or client.get('workspace_name'),
                    'platform': client['platform'],
                    'total_accounts': mailboxes['total_accounts'],
                    'healthy': mailboxes['healthy_count'],
                    'at_risk': mailboxes['at_risk_count'],
                    'early': mailboxes.get('early_count', 0)
                })

            except Exception as e:
                logger.warning(f"Error getting mailboxes for {client}: {e}")

        # Calculate health percentage
        health_percentage = round((total_healthy / total_accounts * 100), 2) if total_accounts > 0 else 0

        return {
            'total_accounts': total_accounts,
            'healthy_count': total_healthy,
            'at_risk_count': total_at_risk,
            'early_count': total_early,
            'health_percentage': health_percentage,
            'instantly_totals': instantly_totals,
            'bison_totals': bison_totals,
            'client_summaries': client_summaries,
            'total_clients': all_clients['total_clients']
        }

    except Exception as e:
        logger.error(f"Error getting all mailbox health: {e}")
        raise


def get_unhealthy_mailboxes(
    sheet_url: str,
    instantly_gid: str,
    bison_gid: str
) -> Dict[str, Any]:
    """
    Get all unhealthy (at_risk) mailboxes across all platforms.

    Args:
        sheet_url: Google Sheets URL
        instantly_gid: Instantly sheet GID
        bison_gid: Bison sheet GID

    Returns:
        Dictionary with unhealthy mailboxes needing attention
    """
    try:
        # Get all clients
        all_clients = get_all_clients(sheet_url)

        unhealthy_mailboxes = []

        # Process each client
        for client in all_clients['clients']:
            try:
                if client['platform'] == 'instantly':
                    mailboxes = get_instantly_mailboxes(
                        sheet_url, instantly_gid,
                        client['workspace_id']
                    )
                elif client['platform'] == 'bison':
                    mailboxes = get_bison_mailboxes(
                        sheet_url, bison_gid,
                        client['client_name']
                    )
                else:
                    continue

                # Filter for unhealthy accounts
                for account in mailboxes['accounts']:
                    if account['health'] == 'at_risk':
                        unhealthy_mailboxes.append({
                            'client_name': client.get('client_name') or client.get('workspace_name'),
                            'platform': client['platform'],
                            'email': account['email'],
                            'status': account['status'],
                            'daily_limit': account.get('daily_limit', 0),
                            'issue': account.get('status')
                        })

            except Exception as e:
                logger.warning(f"Error checking mailboxes for {client}: {e}")

        logger.info(f"Found {len(unhealthy_mailboxes)} unhealthy mailboxes across all platforms")

        return {
            'count': len(unhealthy_mailboxes),
            'mailboxes': unhealthy_mailboxes
        }

    except Exception as e:
        logger.error(f"Error getting unhealthy mailboxes: {e}")
        raise
