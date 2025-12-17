"""
Simple function to fetch interested leads from Instantly API.
"""

import requests
from datetime import datetime
from typing import List, Dict


def fetch_interested_leads(
    api_key: str,
    start_date: str,
    end_date: str,
    limit: int = 100
) -> Dict:
    """
    Fetch emails marked as interested (i_status=1) from Instantly.

    Args:
        api_key: Instantly API key
        start_date: Start date in ISO format (e.g., "2024-12-01T00:00:00Z")
        end_date: End date in ISO format (e.g., "2024-12-11T23:59:59Z")
        limit: Max emails per page (default 100)

    Returns:
        {
            "total_count": int,
            "leads": [
                {
                    "email": str,
                    "reply_body": str,
                    "reply_summary": str,
                    "subject": str,
                    "timestamp": str,
                    "lead_id": str (if available)
                }
            ]
        }
    """
    url = "https://api.instantly.ai/api/v2/emails"
    headers = {"Authorization": f"Bearer {api_key}"}

    all_leads = []
    starting_after = None

    # Progress logging removed for MCP compatibility

    while True:
        # Build params
        params = {
            "i_status": 1,  # Interested
            "min_timestamp_created": start_date,
            "max_timestamp_created": end_date,
            "limit": limit
        }

        if starting_after:
            params["starting_after"] = starting_after

        # Make request
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)

            if not response.ok:
                # Error logging removed for MCP compatibility
                break

            data = response.json()
            items = data.get("items", [])

            # Progress logging removed for MCP compatibility

            # Process each email
            for email in items:
                # IMPORTANT: Only process received emails (replies from leads)
                # i_status=1 returns BOTH sent and received emails in interested threads
                if email.get("ue_type") != 2:
                    continue

                from_email = email.get("from_address_email", "").lower()

                # Skip emails FROM your team (prism, leadgenjay, etc.)
                if any(keyword in from_email for keyword in ["prism", "leadgenjay", "pendrick"]):
                    continue

                # Skip system/auto emails
                if "noreply" in from_email or "no-reply" in from_email or "paypal" in from_email:
                    continue

                lead_data = {
                    "email": email.get("from_address_email", "Unknown"),
                    "reply_body": email.get("body", {}).get("text", ""),
                    "reply_summary": _summarize_reply(email.get("body", {}).get("text", "")),
                    "subject": email.get("subject", ""),
                    "timestamp": email.get("timestamp_email", ""),
                    "lead_id": email.get("lead"),
                    "thread_id": email.get("thread_id")
                }
                all_leads.append(lead_data)

            # Check for next page
            starting_after = data.get("next_starting_after")

            # Break if no more pages OR if we got fewer items than limit (last page)
            if not starting_after or len(items) < limit:
                break

        except Exception as e:
            # Exception logging removed for MCP compatibility
            break

    # De-duplicate by email (keep most recent)
    unique_leads = _deduplicate_leads(all_leads)

    # Progress logging removed for MCP compatibility

    return {
        "total_count": len(unique_leads),
        "leads": unique_leads
    }


def _summarize_reply(body: str, max_length: int = 200) -> str:
    """
    Simple summarization: take first meaningful part of reply.
    Removes email signatures, quoted text, etc.
    """
    if not body or not body.strip():
        return "[Reply content not available]"

    # Split by common reply separators
    separators = [
        "\n\nOn ",  # Gmail style
        "\n\nFrom:",  # Outlook style
        "\n\n---",  # Signature separator
        "\nSent from",  # Mobile signatures
        "\n\n\n",  # Multiple newlines often indicate signature
    ]

    clean_body = body.strip()
    for sep in separators:
        if sep in clean_body:
            clean_body = clean_body.split(sep)[0].strip()

    # Remove common auto-reply indicators
    if clean_body.lower().startswith("out of office") or \
       clean_body.lower().startswith("automatic reply"):
        return "[Auto-reply: Out of office]"

    # Take first few lines
    lines = [line.strip() for line in clean_body.split("\n") if line.strip()]

    # Skip very short replies that are just greetings
    meaningful_lines = [line for line in lines if len(line) > 10]

    if meaningful_lines:
        summary = " ".join(meaningful_lines[:3])  # First 3 meaningful lines
    else:
        # Fallback to any lines if all are short
        summary = " ".join(lines[:3])

    # Truncate if too long
    if len(summary) > max_length:
        summary = summary[:max_length] + "..."

    return summary.strip() or "[Reply content not available]"


def _deduplicate_leads(leads: List[Dict]) -> List[Dict]:
    """
    Keep only the most recent reply per email address.
    """
    by_email = {}

    for lead in leads:
        email = lead["email"]
        timestamp = lead["timestamp"]

        if email not in by_email:
            by_email[email] = lead
        else:
            # Keep the most recent
            if timestamp > by_email[email]["timestamp"]:
                by_email[email] = lead

    # Sort by timestamp (most recent first)
    sorted_leads = sorted(
        by_email.values(),
        key=lambda x: x["timestamp"],
        reverse=True
    )

    return sorted_leads
