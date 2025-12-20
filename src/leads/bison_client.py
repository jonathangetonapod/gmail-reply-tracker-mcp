"""
Bison/LeadGenJay API wrapper functions.
"""

import logging
import requests
from datetime import datetime
from typing import Optional, List

logger = logging.getLogger(__name__)


def get_bison_lead_replies(api_key: str, status: str = "interested", folder: str = "all"):
    """
    Fetch lead replies from Bison API.

    Args:
        api_key: Bison API key
        status: Filter by status (e.g., "interested"), or None for all statuses
        folder: Filter by folder (e.g., "inbox", "all")

    Returns:
        {
            "data": [
                {
                    "id": int,
                    "from_email_address": str,
                    "from_name": str,
                    "subject": str,
                    "text_body": str,
                    "html_body": str,
                    "date_received": str,
                    "type": str,
                    "lead_id": int,
                    "read": bool
                }
            ]
        }
    """
    url = "https://send.leadgenjay.com/api/replies"
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"folder": folder}

    # Only add status filter if provided
    if status is not None:
        params["status"] = status

    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()

    return response.json()


def mark_bison_reply_as_interested(api_key: str, reply_id: int, skip_webhooks: bool = True):
    """
    Mark a specific reply as interested in Bison API.

    Args:
        api_key: Bison API key
        reply_id: Reply ID to mark as interested
        skip_webhooks: Whether to skip triggering webhooks (default: True)

    Returns:
        {
            "data": {
                "id": int,
                "uuid": str,
                "from_email_address": str,
                "from_name": str,
                "subject": str,
                "text_body": str,
                "interested": bool,
                "automated_reply": bool,
                ...
            }
        }
    """
    url = f"https://send.leadgenjay.com/api/replies/{reply_id}/mark-as-interested"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {"skip_webhooks": skip_webhooks}

    response = requests.patch(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()

    return response.json()


def get_bison_conversation_thread(api_key: str, reply_id: int):
    """
    Fetch conversation thread for a specific reply from Bison API.

    Args:
        api_key: Bison API key
        reply_id: Reply ID to fetch thread for

    Returns:
        {
            "data": {
                "current_reply": {...},
                "older_messages": [...],
                "newer_messages": [...]
            }
        }
    """
    url = f"https://send.leadgenjay.com/api/replies/{reply_id}/conversation-thread"
    headers = {"Authorization": f"Bearer {api_key}"}

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    return response.json()


def get_bison_campaign_stats_api(api_key: str, start_date: str, end_date: str):
    """
    Fetch campaign statistics from Bison API.

    Args:
        api_key: Bison API key
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        {
            "data": {
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
        }
    """
    url = "https://send.leadgenjay.com/api/workspaces/v1.1/stats"
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "start_date": start_date,
        "end_date": end_date
    }

    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()

    return response.json()


def create_bison_campaign_api(api_key: str, name: str, campaign_type: str = "outbound"):
    """
    Create a new campaign in Bison API.

    Args:
        api_key: Bison API key
        name: Campaign name
        campaign_type: Type of campaign (default: "outbound")

    Returns:
        {
            "data": {
                "id": int,
                "uuid": str,
                "name": str,
                "type": str,
                "status": str,
                ...
            }
        }
    """
    url = "https://send.leadgenjay.com/api/campaigns"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "name": name,
        "type": campaign_type
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()

    return response.json()


def _convert_to_bison_placeholders(text: str) -> str:
    """
    Convert any placeholder format to Bison format.
    Handles: {{first_name}}, {{firstname}}, {{firstName}}, {first_name}, [first_name], etc.
    Converts to: {FIRST_NAME}, {LAST_NAME}, {COMPANY_NAME}, {TITLE}, {EMAIL}
    """
    import re

    if not text:
        return text

    conversions = [
        # First name variations
        (r'\{\{?\s*first[_\s]?name\s*\}?\}', '{FIRST_NAME}'),
        (r'\{\{?\s*firstName\s*\}?\}', '{FIRST_NAME}'),
        (r'\{\{?\s*firstname\s*\}?\}', '{FIRST_NAME}'),
        (r'\{\{?\s*first\s*\}?\}', '{FIRST_NAME}'),
        (r'\[\s*first[_\s]?name\s*\]', '{FIRST_NAME}'),
        # Last name variations
        (r'\{\{?\s*last[_\s]?name\s*\}?\}', '{LAST_NAME}'),
        (r'\{\{?\s*lastName\s*\}?\}', '{LAST_NAME}'),
        (r'\{\{?\s*lastname\s*\}?\}', '{LAST_NAME}'),
        (r'\{\{?\s*last\s*\}?\}', '{LAST_NAME}'),
        (r'\[\s*last[_\s]?name\s*\]', '{LAST_NAME}'),
        # Company variations
        (r'\{\{?\s*company[_\s]?name\s*\}?\}', '{COMPANY_NAME}'),
        (r'\{\{?\s*companyName\s*\}?\}', '{COMPANY_NAME}'),
        (r'\{\{?\s*companyname\s*\}?\}', '{COMPANY_NAME}'),
        (r'\{\{?\s*company\s*\}?\}', '{COMPANY_NAME}'),
        (r'\[\s*company[_\s]?name\s*\]', '{COMPANY_NAME}'),
        (r'\[\s*company\s*\]', '{COMPANY_NAME}'),
        # Title/job title variations
        (r'\{\{?\s*job[_\s]?title\s*\}?\}', '{TITLE}'),
        (r'\{\{?\s*jobTitle\s*\}?\}', '{TITLE}'),
        (r'\{\{?\s*jobtitle\s*\}?\}', '{TITLE}'),
        (r'\{\{?\s*title\s*\}?\}', '{TITLE}'),
        (r'\[\s*job[_\s]?title\s*\]', '{TITLE}'),
        (r'\[\s*title\s*\]', '{TITLE}'),
        # Email variations
        (r'\{\{?\s*email[_\s]?address\s*\}?\}', '{EMAIL}'),
        (r'\{\{?\s*emailAddress\s*\}?\}', '{EMAIL}'),
        (r'\{\{?\s*email\s*\}?\}', '{EMAIL}'),
        (r'\[\s*email\s*\]', '{EMAIL}'),
    ]

    result = text
    for pattern, replacement in conversions:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


def create_bison_sequence_api(api_key: str, campaign_id: int, title: str, sequence_steps: list):
    """
    Create campaign sequence steps in Bison API.

    Args:
        api_key: Bison API key
        campaign_id: The ID of the campaign
        title: The title for the sequence
        sequence_steps: List of sequence step dictionaries, each containing:
            - email_subject (str, required): Subject line
            - email_subject_variables (list, optional): Variables like ["{FIRST_NAME}"]
            - order (int, required): Step order (1, 2, 3, etc.)
            - email_body (str, required): Email body content
            - wait_in_days (int, required): Days to wait before sending
            - variant (bool, optional): Whether this is a variant step (default: False)
            - variant_from_step (int, optional): Which step this is a variant of
            - thread_reply (bool, optional): Whether to reply in thread (default: False)

    Returns:
        {
            "data": {
                "id": int,
                "type": "Campaign sequence",
                "title": str,
                "sequence_steps": [
                    {
                        "id": int,
                        "email_subject": str,
                        "order": int,
                        "email_body": str,
                        "wait_in_days": int,
                        "variant": bool,
                        "variant_from_step_id": int or None,
                        "attachments": str or None,
                        "thread_reply": bool
                    }
                ]
            }
        }
    """
    # Convert placeholder variables and normalize field names
    converted_steps = []
    for idx, step in enumerate(sequence_steps):
        converted_step = step.copy()

        # Set smart defaults for wait_in_days based on step position
        # Pattern: Step 1=1 day (API minimum), Step 2=3 days, Step 3=5 days, Step 4+=7 days
        if 'wait_in_days' not in converted_step or converted_step['wait_in_days'] < 1:
            if idx == 0:
                converted_step['wait_in_days'] = 1  # First step: 1 day (API minimum)
            elif idx == 1:
                converted_step['wait_in_days'] = 3  # Second step: 3 days
            elif idx == 2:
                converted_step['wait_in_days'] = 5  # Third step: 5 days
            else:
                converted_step['wait_in_days'] = 7  # Fourth+ step: 7 days

        # Handle both 'email_subject'/'email_body' AND 'subject'/'body' key names
        subject_keys = ['email_subject', 'subject']
        body_keys = ['email_body', 'body']

        # Convert subject placeholders
        # For thread replies with empty subjects, use a space placeholder
        for key in subject_keys:
            if key in converted_step:
                subject_value = converted_step[key]

                # If empty string and this is a thread reply, use space as placeholder
                if not subject_value and converted_step.get('thread_reply', False):
                    # Bison API requires email_subject field, use space for thread replies
                    converted_step['email_subject'] = ' '
                    # Remove alternate 'subject' key if present
                    converted_step.pop('subject', None)
                elif subject_value:
                    # Non-empty subject: convert placeholders
                    converted = _convert_to_bison_placeholders(subject_value)

                    # Normalize to 'email_subject'
                    if key == 'subject':
                        converted_step['email_subject'] = converted
                        del converted_step['subject']
                    else:
                        converted_step['email_subject'] = converted
                else:
                    # Empty subject but NOT a thread reply: keep as-is
                    if key == 'subject':
                        converted_step['email_subject'] = subject_value
                        del converted_step['subject']

                # Conversion logging removed for MCP compatibility

        # Convert body placeholders
        for key in body_keys:
            if key in converted_step and converted_step[key]:
                original = converted_step[key]
                converted = _convert_to_bison_placeholders(converted_step[key])

                # Normalize to 'email_body'
                if key == 'body':
                    converted_step['email_body'] = converted
                    del converted_step['body']
                else:
                    converted_step[key] = converted

                # Conversion logging removed for MCP compatibility

        converted_steps.append(converted_step)

    url = f"https://send.leadgenjay.com/api/campaigns/v1.1/{campaign_id}/sequence-steps"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "title": title,
        "sequence_steps": converted_steps
    }

    # Debug logging removed for MCP compatibility

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    # Error logging removed for MCP compatibility
    if not response.ok:
        # Print error details for debugging
        try:
            error_data = response.json()
            print(f"Bison API Error: {response.status_code}")
            print(f"Error details: {error_data}")
        except:
            print(f"Bison API Error: {response.status_code}")
            print(f"Response text: {response.text}")

    response.raise_for_status()

    return response.json()

def list_bison_campaigns(
    api_key: str,
    status: Optional[str] = None,
    search: Optional[str] = None,
    tag_ids: Optional[List[int]] = None
):
    """
    List all campaigns from Bison API.

    Args:
        api_key: Bison API key
        status: Filter by status (e.g., "active", "launching", "draft")
        search: Search term to filter campaigns
        tag_ids: List of tag IDs to filter by

    Returns:
        {
            "data": [
                {
                    "id": int,
                    "uuid": str,
                    "name": str,
                    "type": str,
                    "status": str,
                    "emails_sent": int,
                    "opened": int,
                    ...
                }
            ]
        }
    """
    url = "https://send.leadgenjay.com/api/campaigns"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    params = {}
    if search is not None:
        params["search"] = search
    if status is not None:
        params["status"] = status
    if tag_ids is not None:
        params["tag_ids"] = tag_ids

    # Use GET to list campaigns (POST is for creating campaigns)
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()

    return response.json()


def get_bison_campaign_sequences(api_key: str, campaign_id: int):
    """
    Get campaign sequence steps from Bison API.

    Args:
        api_key: Bison API key
        campaign_id: Campaign ID

    Returns:
        {
            "data": {
                "sequence_id": int,
                "sequence_steps": [
                    {
                        "id": int,
                        "email_subject": str,
                        "order": str,
                        "email_body": str,
                        "wait_in_days": str,
                        "variant": bool,
                        "variant_from_step_id": int or None,
                        "attachments": list,
                        "thread_reply": bool
                    }
                ]
            }
        }
    """
    url = f"https://send.leadgenjay.com/api/campaigns/v1.1/{campaign_id}/sequence-steps"
    headers = {"Authorization": f"Bearer {api_key}"}

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    return response.json()


def create_bison_campaign_with_sequences(
    client_name: str,
    campaign_name: str,
    sequence_title: str,
    steps: list,
    campaign_type: str = "outbound",
    sheet_url: str = None,
    gid: str = None
):
    """
    High-level function to create a Bison campaign with sequences in one call.

    This function:
    1. Loads client configuration from Google Sheet
    2. Creates a new campaign
    3. Creates sequence steps for the campaign

    Args:
        client_name: The client name (e.g., "Rick Ables")
        campaign_name: Name for the campaign (e.g., "Insurance Agency")
        sequence_title: Title for the sequence (e.g., "Insurance Agency Campaign - Lead Follow-Up Gap")
        steps: List of sequence step dictionaries (same format as create_bison_sequence_api)
        campaign_type: Type of campaign (default: "outbound")
        sheet_url: Optional Google Sheet URL (uses default if not provided)
        gid: Optional Google Sheet GID for Bison tab (uses default if not provided)

    Returns:
        {
            "campaign": {...},  # Campaign creation response
            "sequence": {...}   # Sequence creation response
        }
    """
    from .sheets_client import load_bison_workspaces_from_sheet, DEFAULT_SHEET_URL, SHEET_GID_BISON

    # Use defaults if not provided
    if sheet_url is None:
        sheet_url = DEFAULT_SHEET_URL
    if gid is None:
        gid = SHEET_GID_BISON

    # Load client configurations from sheet
    workspaces = load_bison_workspaces_from_sheet(sheet_url, gid=gid)

    # Find the client
    client = None
    for workspace in workspaces:
        if workspace["client_name"].lower() == client_name.lower():
            client = workspace
            break

    if not client:
        raise ValueError(f"Client '{client_name}' not found in Bison clients sheet")

    api_key = client["api_key"]

    # Step 1: Create the campaign
    campaign_result = create_bison_campaign_api(
        api_key=api_key,
        name=campaign_name,
        campaign_type=campaign_type
    )

    campaign_id = campaign_result["data"]["id"]

    # Step 2: Create the sequence steps
    sequence_result = create_bison_sequence_api(
        api_key=api_key,
        campaign_id=campaign_id,
        title=sequence_title,
        sequence_steps=steps
    )

    return {
        "campaign": campaign_result,
        "sequence": sequence_result
    }


def get_bison_sender_emails(api_key: str):
    """
    Fetch ALL sender email accounts from Bison API with pagination.

    Note: Bison API returns 15 results per page by default and doesn't support
    per_page parameter. Standard clients have 50+ inboxes, so we fetch multiple
    pages explicitly.

    Args:
        api_key: Bison API key

    Returns:
        {
            "data": [
                {
                    "id": int,
                    "name": str,
                    "email": str,
                    "status": str,
                    ...
                }
            ]
        }
    """
    url = "https://send.leadgenjay.com/api/sender-emails"
    headers = {"Authorization": f"Bearer {api_key}"}

    all_emails = []

    # Bison API returns 15 per page, standard clients have 50-80 inboxes
    # Fetch up to 10 pages (150 emails) to ensure we get everything
    max_pages = 10
    logger.info(f"Starting pagination for sender emails (fetching up to {max_pages} pages)")

    for page in range(1, max_pages + 1):
        logger.info(f"Fetching sender emails page {page}")
        params = {"page": page}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
        except Exception as e:
            logger.warning(f"Error fetching page {page}: {e}")
            break

        result = response.json()
        logger.info(f"API response keys: {list(result.keys())}")

        data = result.get("data", [])
        logger.info(f"Page {page} returned {len(data)} emails (total so far: {len(all_emails) + len(data)})")

        if not data:
            # No more data, we've fetched all pages
            logger.info(f"No data on page {page}, stopping pagination")
            break

        all_emails.extend(data)

        # If we got less than 15 results, we're on the last page
        if len(data) < 15:
            logger.info(f"Got {len(data)} < 15 results, last page reached")
            break

    logger.info(f"Pagination complete: fetched {len(all_emails)} total sender emails across {page} pages")
    return {"data": all_emails}
