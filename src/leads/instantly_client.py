"""
Instantly API wrapper functions.
"""

import requests
from ._source_fetch_interested_leads import fetch_interested_leads


def fetch_workspace_details(api_key: str):
    """
    Fetch workspace details from Instantly API.

    Args:
        api_key: Instantly API key

    Returns:
        {
            "id": "workspace-uuid",
            "name": "My Workspace",
            "owner": "user-uuid",
            "plan_id": "pid_hg_v1",
            "org_logo_url": "https://...",
            "org_client_domain": "example.com",
            ...
        }
    """
    url = "https://api.instantly.ai/api/v2/workspaces/current"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[API] Failed to fetch workspace details: {e}")
        return None


def get_instantly_campaign_stats(api_key: str, start_date: str, end_date: str):
    """
    Fetch campaign statistics from Instantly API.

    Args:
        api_key: Instantly API key
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        {
            "emails_sent_count": int,
            "reply_count_unique": int,
            "total_opportunities": int,
            "reply_rate": float
        }
    """
    url = "https://api.instantly.ai/api/v2/campaigns/analytics/overview"
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "start_date": start_date,
        "end_date": end_date
    }

    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()

    return response.json()


def get_instantly_lead_responses(api_key: str, start_date: str, end_date: str):
    """
    Fetch interested lead responses from Instantly API.

    Args:
        api_key: Instantly API key
        start_date: Start date in ISO format (e.g., "2024-12-01T00:00:00Z")
        end_date: End date in ISO format (e.g., "2024-12-11T23:59:59Z")

    Returns:
        {
            "total_count": int,
            "leads": [
                {
                    "email": str,
                    "reply_body": str,
                    "reply_summary": str,
                    "subject": str,
                    "timestamp": str
                }
            ]
        }
    """
    return fetch_interested_leads(
        api_key=api_key,
        start_date=start_date,
        end_date=end_date
    )
