"""
Bison/LeadGenJay API wrapper functions.
"""

import requests
from datetime import datetime


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
    url = f"https://send.leadgenjay.com/api/campaigns/v1.1/{campaign_id}/sequence-steps"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "title": title,
        "sequence_steps": sequence_steps
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()

    return response.json()
