"""
Instantly API wrapper functions.
"""

import requests
from ._source_fetch_interested_leads import fetch_interested_leads

# Valid timezones for Instantly API (complete list from API docs)
INSTANTLY_VALID_TIMEZONES = [
    # GMT Offsets
    "Etc/GMT+12", "Etc/GMT+11", "Etc/GMT+10", "Etc/GMT-12", "Etc/GMT-13",
    # Americas
    "America/Anchorage", "America/Dawson", "America/Creston", "America/Chihuahua",
    "America/Boise", "America/Belize", "America/Chicago", "America/Bahia_Banderas",
    "America/Regina", "America/Bogota", "America/Detroit", "America/Indiana/Marengo",
    "America/Caracas", "America/Asuncion", "America/Glace_Bay", "America/Campo_Grande",
    "America/Anguilla", "America/Santiago", "America/St_Johns", "America/Sao_Paulo",
    "America/Argentina/La_Rioja", "America/Araguaina", "America/Godthab",
    "America/Montevideo", "America/Bahia", "America/Noronha", "America/Scoresbysund",
    "America/Danmarkshavn",
    # Atlantic & Africa
    "Atlantic/Cape_Verde", "Africa/Casablanca", "Atlantic/Canary", "Africa/Abidjan",
    "Africa/Ceuta", "Africa/Algiers", "Africa/Windhoek", "Africa/Cairo",
    "Africa/Blantyre", "Africa/Tripoli", "Africa/Addis_Ababa",
    # Europe
    "Europe/Isle_of_Man", "Arctic/Longyearbyen", "Europe/Belgrade", "Europe/Sarajevo",
    "Europe/Bucharest", "Europe/Helsinki", "Europe/Istanbul", "Europe/Kaliningrad",
    "Europe/Kirov", "Europe/Astrakhan",
    # Asia
    "Asia/Nicosia", "Asia/Beirut", "Asia/Damascus", "Asia/Jerusalem", "Asia/Amman",
    "Asia/Baghdad", "Asia/Aden", "Asia/Tehran", "Asia/Dubai", "Asia/Baku",
    "Asia/Tbilisi", "Asia/Yerevan", "Asia/Kabul", "Asia/Yekaterinburg", "Asia/Karachi",
    "Asia/Kolkata", "Asia/Colombo", "Asia/Kathmandu", "Asia/Dhaka", "Asia/Rangoon",
    "Asia/Novokuznetsk", "Asia/Hong_Kong", "Asia/Krasnoyarsk", "Asia/Brunei",
    "Asia/Taipei", "Asia/Choibalsan", "Asia/Irkutsk", "Asia/Dili", "Asia/Pyongyang",
    "Asia/Chita", "Asia/Sakhalin", "Asia/Anadyr", "Asia/Kamchatka",
    # Australia & Pacific
    "Australia/Perth", "Australia/Adelaide", "Australia/Darwin", "Australia/Brisbane",
    "Australia/Melbourne", "Australia/Currie", "Pacific/Auckland", "Pacific/Fiji",
    "Pacific/Apia",
    # Antarctica & Indian Ocean
    "Antarctica/Mawson", "Antarctica/Vostok", "Antarctica/Davis",
    "Antarctica/DumontDUrville", "Antarctica/Macquarie", "Indian/Mahe"
]


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


def create_instantly_campaign_api(
    api_key: str,
    name: str,
    sequence_steps: list,
    email_accounts: list = None,
    daily_limit: int = 50,
    timezone: str = "America/Chicago",  # Central Time (valid timezone)
    schedule_name: str = "Work Hours",
    schedule_from: str = "09:00",
    schedule_to: str = "17:00",
    days: dict = None,
    stop_on_reply: bool = True,
    link_tracking: bool = True,
    open_tracking: bool = True,
    text_only: bool = False,
    first_email_text_only: bool = False
):
    """
    Create a campaign with sequences in Instantly API.

    Args:
        api_key: Instantly API key
        name: Campaign name
        sequence_steps: List of sequence step dictionaries, each containing:
            - subject (str): Subject line
            - body (str): Email body content
            - variants (list, optional): List of variant objects with subject/body
            - wait (int): Hours to wait before sending (for follow-ups)
        email_accounts: List of email addresses to send from (optional)
        daily_limit: Daily sending limit per account (default: 50)
        timezone: Timezone for schedule (default: "America/Chicago")
            IMPORTANT: Must be exact timezone from INSTANTLY_VALID_TIMEZONES list.
            Common names like "America/New_York", "America/Los_Angeles", "US/Eastern"
            are NOT valid. Use "America/Chicago" (Central), "America/Detroit" (Eastern),
            "America/Boise" (Mountain), etc. See INSTANTLY_VALID_TIMEZONES for full list.
        schedule_name: Name of the schedule (default: "Work Hours")
        schedule_from: Start time HH:MM (default: "09:00")
        schedule_to: End time HH:MM (default: "17:00")
        days: Dict with days 0-6 set to true/false (default: Mon-Fri)
        stop_on_reply: Stop campaign when lead replies (default: True)
        link_tracking: Track link clicks (default: True)
        open_tracking: Track email opens (default: True)
        text_only: Send all emails as text only (default: False)
        first_email_text_only: Send first email as text only (default: False)

    Returns:
        {
            "id": str (campaign UUID),
            "name": str,
            "status": str,
            ...
        }

    Raises:
        HTTPError: If timezone is invalid or other API errors occur
    """
    # Validate timezone
    if timezone not in INSTANTLY_VALID_TIMEZONES:
        print(f"[Instantly] WARNING: Timezone '{timezone}' may not be valid.")
        print(f"[Instantly] Valid timezones include: America/Chicago, America/Detroit, America/Boise, etc.")
        print(f"[Instantly] See INSTANTLY_VALID_TIMEZONES list for all options.")

    url = "https://api.instantly.ai/api/v2/campaigns"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Default to Mon-Fri if no days specified
    if days is None:
        days = {
            "0": False,  # Sunday
            "1": True,   # Monday
            "2": True,   # Tuesday
            "3": True,   # Wednesday
            "4": True,   # Thursday
            "5": True,   # Friday
            "6": False   # Saturday
        }

    # Transform steps to Instantly API format
    transformed_steps = []
    for step in sequence_steps:
        # Extract wait time and rename to delay
        wait_time = step.get('wait', 0)

        # Get variants or create from subject/body
        variants = step.get('variants', [])

        # If no variants provided, create one from subject/body at step level
        if not variants and ('subject' in step or 'body' in step):
            body = step.get('body', '')
            # Convert newlines to HTML breaks for Instantly
            if body and '\n' in body:
                original_newlines = body.count('\n')
                body = body.replace('\n', '<br>')
                print(f"[Instantly] Converted {original_newlines} newlines to <br> tags")
            variants = [{
                "subject": step.get('subject', ''),
                "body": body
            }]
        else:
            # If variants were provided, also convert their newlines to <br> tags
            for variant in variants:
                if 'body' in variant and variant['body'] and '\n' in variant['body']:
                    original_newlines = variant['body'].count('\n')
                    variant['body'] = variant['body'].replace('\n', '<br>')
                    print(f"[Instantly] Converted {original_newlines} newlines to <br> tags in variant")

        # Create step with correct Instantly API structure
        transformed_step = {
            "type": "email",  # Required: must be 'email'
            "delay": wait_time,  # Days to wait before sending NEXT email
            "variants": variants  # Array of variant objects with subject/body
        }

        transformed_steps.append(transformed_step)

    # Build payload
    payload = {
        "name": name,
        "campaign_schedule": {
            "schedules": [
                {
                    "name": schedule_name,
                    "timing": {
                        "from": schedule_from,
                        "to": schedule_to
                    },
                    "days": days,
                    "timezone": timezone
                }
            ]
        },
        "sequences": [
            {
                "steps": transformed_steps
            }
        ],
        "daily_limit": daily_limit,
        "stop_on_reply": stop_on_reply,
        "link_tracking": link_tracking,
        "open_tracking": open_tracking,
        "text_only": text_only,
        "first_email_text_only": first_email_text_only
    }

    # Add email accounts if provided
    if email_accounts:
        payload["email_list"] = email_accounts

    # Debug: Print request details
    import json as json_module
    print(f"[INSTANTLY] POST {url}")
    print(f"[INSTANTLY] Payload: {json_module.dumps(payload, indent=2)}")

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    # Debug: print error response if request fails
    if not response.ok:
        print(f"[INSTANTLY] API Error {response.status_code}: {response.text}")

    response.raise_for_status()

    return response.json()
