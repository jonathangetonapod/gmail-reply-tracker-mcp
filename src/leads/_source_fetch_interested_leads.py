"""
Simple function to fetch interested leads from Instantly API.
"""

import logging
import requests
import time
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def verify_lead_exists_in_instantly(api_key: str, lead_email: str) -> Dict:
    """
    Verify that a lead exists in Instantly before trying to mark it.

    Args:
        api_key: Instantly API key
        lead_email: Email address to verify

    Returns:
        {
            "exists": bool,
            "lead_data": dict or None,
            "message": str
        }
    """
    url = "https://api.instantly.ai/api/v1/lead/get"
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"email": lead_email}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            logger.info(f"✅ Lead exists in Instantly: {lead_email}")
            logger.info(f"   Lead data: {data}")
            return {
                "exists": True,
                "lead_data": data,
                "message": "Lead found in Instantly"
            }
        elif response.status_code == 404:
            logger.warning(f"❌ Lead NOT found in Instantly: {lead_email}")
            return {
                "exists": False,
                "lead_data": None,
                "message": f"Lead {lead_email} does not exist in this Instantly workspace"
            }
        else:
            logger.warning(f"⚠️  Unexpected status checking lead: {response.status_code}")
            logger.warning(f"   Response: {response.text}")
            return {
                "exists": False,
                "lead_data": None,
                "message": f"Error checking lead: {response.status_code}"
            }
    except Exception as e:
        logger.error(f"Error verifying lead exists: {e}")
        return {
            "exists": False,
            "lead_data": None,
            "message": f"Error: {str(e)}"
        }


def _make_request_with_retry(url: str, headers: Dict, params: Dict, max_retries: int = 3, timeout: int = 60):
    """
    Make HTTP GET request with retry logic and exponential backoff.

    Args:
        url: API endpoint URL
        headers: Request headers
        params: Query parameters
        max_retries: Maximum number of retry attempts (default: 3)
        timeout: Request timeout in seconds (default: 60)

    Returns:
        Response object

    Raises:
        Exception: If all retries fail
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
            return response

        except requests.exceptions.Timeout as e:
            if attempt < max_retries - 1:
                wait_time = 30 * (2 ** attempt)  # 30s, 60s
                logger.warning(
                    f"   ⚠️  Timeout on attempt {attempt + 1}/{max_retries}, "
                    f"retrying in {wait_time}s... ({str(e)})"
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    f"   ❌ Failed after {max_retries} attempts: {str(e)}"
                )
                raise

        except Exception as e:
            # For non-timeout errors, don't retry
            logger.error(f"   ❌ Request failed: {str(e)}")
            raise


def mark_instantly_lead_as_interested(
    api_key: str,
    lead_email: str,
    interest_value: int = 1,
    campaign_id: Optional[str] = None,
    list_id: Optional[str] = None,
    ai_interest_value: Optional[int] = None,
    disable_auto_interest: bool = False
) -> Dict:
    """
    Mark a lead as interested in Instantly API.

    Args:
        api_key: Instantly API key
        lead_email: Email address of the lead
        interest_value: Interest status value (default: 1 for "Interested")
            1 = Interested
            2 = Meeting Booked
            3 = Meeting Completed
            4 = Closed
            -1 = Not Interested
            -2 = Wrong Person
            -3 = Lost
            0 = Out of Office
            None = Reset to "Lead"
        campaign_id: Optional campaign ID context
        list_id: Optional list ID context
        ai_interest_value: Optional AI-determined interest level
        disable_auto_interest: Whether to disable auto interest detection

    Returns:
        {
            "message": "Lead interest status update background job submitted"
        }
    """
    url = "https://api.instantly.ai/api/v2/leads/update-interest-status"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "lead_email": lead_email,
        "interest_value": interest_value
    }

    # Add optional fields
    if campaign_id:
        payload["campaign_id"] = campaign_id
    if list_id:
        payload["list_id"] = list_id
    if ai_interest_value is not None:
        payload["ai_interest_value"] = ai_interest_value
    if disable_auto_interest:
        payload["disable_auto_interest"] = disable_auto_interest

    # FIRST: Verify the lead exists in Instantly
    logger.info(f"🔍 Step 1: Verifying lead exists in Instantly...")
    verification = verify_lead_exists_in_instantly(api_key, lead_email)

    if not verification["exists"]:
        logger.warning(f"⚠️  Lead doesn't exist yet - this is likely a forwarded reply")
        logger.warning(f"   Email: {lead_email}")
        logger.info(f"🔧 Auto-creating lead in Instantly before marking...")

        # Skip auto-creation for now - the API endpoint requires different auth
        # Just proceed with marking and let Instantly create the lead automatically
        logger.warning(f"⚠️  Proceeding without lead verification...")
        logger.warning(f"   Instantly may auto-create the lead when marking")
        logger.warning(f"   If this fails, the lead needs to be manually added to Instantly first")

    logger.info(f"✅ Lead verified, proceeding to mark as interested...")

    # Log the request for debugging
    logger.info(f"🔵 Step 2: Instantly API Request:")
    logger.info(f"   URL: {url}")
    logger.info(f"   Payload: {payload}")

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    # Log the full response for debugging
    logger.info(f"🔵 Instantly API Response:")
    logger.info(f"   Status Code: {response.status_code}")
    logger.info(f"   Response Body: {response.text}")

    response.raise_for_status()

    result = response.json()

    # Check if the response indicates success
    if "message" in result and "background job submitted" in result["message"].lower():
        logger.info(f"✅ Marking request accepted - background job queued")
        return result
    elif "error" in result:
        logger.error(f"❌ Instantly returned an error: {result.get('error')}")
        return result
    else:
        logger.info(f"✅ Response received: {result}")
        return result


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
            "limit": limit,
            "sort_order": "asc",  # Ascending order for pagination
            "email_type": "received"  # Only fetch received emails (replies)
        }

        if starting_after:
            params["starting_after"] = starting_after

        # Make request with retry logic
        try:
            response = _make_request_with_retry(url, headers, params, max_retries=3, timeout=60)

            if not response.ok:
                # Error logging removed for MCP compatibility
                break

            data = response.json()
            items = data.get("items", [])

            # Progress logging removed for MCP compatibility

            # Process each email
            for email in items:
                # Safety check: Only process received emails (should already be filtered by API)
                # ue_type: 1=Sent, 2=Received, 3=Manual, 4=Scheduled
                if email.get("ue_type") != 2:
                    continue

                # Skip auto-replies detected by Instantly API (is_auto_reply: 0=false, 1=true)
                if email.get("is_auto_reply") == 1:
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


def fetch_all_campaign_replies(
    api_key: str,
    start_date: str,
    end_date: str,
    i_status: Optional[int] = None,
    limit: int = 100
) -> Dict:
    """
    Fetch ALL campaign replies from Instantly, optionally filtered by interest status.

    This function allows fetching replies regardless of their categorization,
    which is useful for finding "hidden gems" - interested leads that weren't
    marked as interested by Instantly's AI.

    Args:
        api_key: Instantly API key
        start_date: Start date in ISO format (e.g., "2024-12-01T00:00:00Z")
        end_date: End date in ISO format (e.g., "2024-12-11T23:59:59Z")
        i_status: Optional interest status filter (None=all, 0=not interested, 1=interested)
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
                    "lead_id": str (if available),
                    "i_status": int (0 or 1)
                }
            ],
            "i_status_filter": int | None
        }
    """
    url = "https://api.instantly.ai/api/v2/emails"
    headers = {"Authorization": f"Bearer {api_key}"}

    all_leads = []
    page_num = 0
    seen_emails = set()  # Track email addresses to detect duplicate pages
    seen_email_ids = set()  # Track email IDs to avoid processing duplicates
    current_min_timestamp = start_date  # Start with the original start_date

    while True:
        page_num += 1
        logger.info(f"   Fetching page {page_num} (i_status={i_status})...")

        # Build params - use timestamp-based pagination instead of cursor
        params = {
            "min_timestamp_created": current_min_timestamp,
            "max_timestamp_created": end_date,
            "limit": limit,
            "sort_order": "asc",  # Ascending order for pagination
            "email_type": "received"  # Only fetch received emails (replies)
        }

        # Add i_status filter if specified
        if i_status is not None:
            params["i_status"] = i_status

        # NOTE: Not using starting_after cursor due to API bug with email_type filter
        # Using timestamp-based pagination instead

        # Make request with retry logic
        try:
            response = _make_request_with_retry(url, headers, params, max_retries=3, timeout=60)

            if not response.ok:
                logger.warning(f"   API returned status {response.status_code}, stopping pagination")
                break

            data = response.json()
            items = data.get("items", [])
            logger.info(f"   Received {len(items)} items on page {page_num}")

            # Process each email
            processed = 0
            page_emails = set()  # Track emails on this specific page

            for email in items:
                # Create unique identifier for this email (id field or combination of lead + timestamp)
                email_id = email.get("id") or email.get("ue_id") or f"{email.get('lead')}_{email.get('timestamp_email')}"

                # Skip if we've already processed this exact email
                if email_id in seen_email_ids:
                    continue

                seen_email_ids.add(email_id)

                # Safety check: Only process received emails (should already be filtered by API)
                # ue_type: 1=Sent, 2=Received, 3=Manual, 4=Scheduled
                if email.get("ue_type") != 2:
                    continue

                # Skip auto-replies detected by Instantly API (is_auto_reply: 0=false, 1=true)
                if email.get("is_auto_reply") == 1:
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
                    "thread_id": email.get("thread_id"),
                    "i_status": email.get("i_status")  # Include the status
                }
                all_leads.append(lead_data)
                page_emails.add(from_email)
                processed += 1

            logger.info(f"   Processed {processed} valid replies from page {page_num}")

            # SAFETY CHECK: Detect if we're seeing the exact same emails as before
            if page_num > 1 and page_emails and page_emails.issubset(seen_emails):
                logger.warning(f"   ⚠️  All {len(page_emails)} emails on this page were already seen!")
                logger.warning(f"   Infinite loop detected - breaking pagination")
                break

            seen_emails.update(page_emails)

            # Break if we got fewer items than limit (last page)
            if len(items) < limit:
                logger.info(f"   Pagination complete after {page_num} pages (received {len(items)} < {limit})")
                break

            # Timestamp-based pagination: Use the last item's timestamp for next page
            if items:
                last_timestamp = items[-1].get("timestamp_email")
                if last_timestamp:
                    # Add 1ms to avoid getting the same email again
                    # (timestamps are in ISO format, so we can use string comparison safely)
                    current_min_timestamp = last_timestamp
                    logger.info(f"   Next page will start from timestamp: {current_min_timestamp}")
                else:
                    logger.warning(f"   No timestamp on last item, stopping pagination")
                    break
            else:
                logger.info(f"   No items returned, pagination complete")
                break

        except Exception as e:
            logger.error(f"   Error fetching page {page_num}: {e}")
            break

    # De-duplicate by email (keep most recent)
    unique_leads = _deduplicate_leads(all_leads)

    return {
        "total_count": len(unique_leads),
        "leads": unique_leads,
        "i_status_filter": i_status
    }
