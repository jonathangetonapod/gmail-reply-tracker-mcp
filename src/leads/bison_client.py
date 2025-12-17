"""
Bison/LeadGenJay API wrapper functions.
"""

import requests
from datetime import datetime
from typing import Optional, List


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
    for step in sequence_steps:
        converted_step = step.copy()

        # Ensure wait_in_days is at least 1 (API requirement)
        if 'wait_in_days' not in converted_step or converted_step['wait_in_days'] < 1:
            converted_step['wait_in_days'] = 3  # Default to 3 days

        # Handle both 'email_subject'/'email_body' AND 'subject'/'body' key names
        subject_keys = ['email_subject', 'subject']
        body_keys = ['email_body', 'body']

        # Convert subject placeholders
        for key in subject_keys:
            if key in converted_step and converted_step[key]:
                original = converted_step[key]
                converted = _convert_to_bison_placeholders(converted_step[key])

                # Normalize to 'email_subject'
                if key == 'subject':
                    converted_step['email_subject'] = converted
                    del converted_step['subject']
                else:
                    converted_step[key] = converted

                if original != converted:
                    print(f"[BISON] Converted subject: '{original}' → '{converted}'")

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

                if original != converted:
                    print(f"[BISON] Converted body: '{original[:100]}...' → '{converted[:100]}...'")

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

    # Debug: Print request details
    import json as json_module
    print(f"[DEBUG] POST {url}")
    print(f"[DEBUG] Payload: {json_module.dumps(payload, indent=2)}")

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    # Debug: Print response details if error
    if not response.ok:
        print(f"[DEBUG] Response Status: {response.status_code}")
        print(f"[DEBUG] Response Body: {response.text}")

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

    payload = {}
    if search is not None:
        payload["search"] = search
    if status is not None:
        payload["status"] = status
    if tag_ids is not None:
        payload["tag_ids"] = tag_ids

    response = requests.post(url, headers=headers, json=payload, timeout=30)
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
