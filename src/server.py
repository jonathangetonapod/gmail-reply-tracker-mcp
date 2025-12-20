#!/usr/bin/env python3
"""Gmail Reply Tracker MCP Server."""

import sys
from pathlib import Path

# Add the src directory to Python path so imports work when launched from Claude Desktop
# This ensures module resolution works regardless of the current working directory
sys.path.insert(0, str(Path(__file__).parent))

import json
import logging
import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional

from mcp.server.fastmcp import FastMCP
from googleapiclient.errors import HttpError

# Load .env file if it exists (for local installations)
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # dotenv not installed, that's ok

from config import Config
from auth import GmailAuthManager
from gmail_client import GmailClient
from email_analyzer import EmailAnalyzer
from calendar_client import CalendarClient
from docs_client import DocsClient
from fathom_client import FathomClient
from leads import (
    get_client_list, get_lead_responses, get_campaign_stats, get_workspace_info,
    get_bison_client_list, get_bison_lead_responses, get_bison_campaign_stats,
    get_all_clients, get_all_platform_stats, get_top_performing_clients,
    get_underperforming_clients, get_weekly_summary
)


# Initialize logging
logger = logging.getLogger(__name__)

# Load configuration
config = Config.from_env()
config.setup_logging()

# Initialize MCP server
mcp = FastMCP(config.server_name)

# Initialize components
auth_manager: Optional[GmailAuthManager] = None
gmail_client: Optional[GmailClient] = None
email_analyzer: Optional[EmailAnalyzer] = None
calendar_client: Optional[CalendarClient] = None
docs_client: Optional[DocsClient] = None
fathom_client: Optional[FathomClient] = None


def initialize_clients():
    """Initialize Gmail, Calendar, Docs, and Fathom clients."""
    global auth_manager, gmail_client, email_analyzer, calendar_client, docs_client, fathom_client

    if gmail_client is not None and calendar_client is not None and docs_client is not None:
        return

    logger.info("Initializing clients...")

    # Validate configuration
    errors = config.validate()
    if errors:
        error_msg = "Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
        logger.error(error_msg)
        raise Exception(error_msg)

    # Initialize authentication
    auth_manager = GmailAuthManager(
        config.credentials_path,
        config.token_path,
        config.oauth_scopes
    )

    try:
        credentials = auth_manager.ensure_authenticated()
    except Exception as e:
        logger.error("Authentication failed: %s", str(e))
        raise

    # Initialize Gmail client
    gmail_client = GmailClient(
        credentials,
        config.max_requests_per_minute
    )

    # Initialize email analyzer
    email_analyzer = EmailAnalyzer()

    # Initialize Calendar client
    calendar_client = CalendarClient(
        credentials,
        config.max_requests_per_minute
    )

    # Initialize Docs client
    docs_client = DocsClient(
        credentials,
        config.max_requests_per_minute
    )

    # Initialize Fathom client (if API key is configured)
    if config.fathom_api_key:
        fathom_client = FathomClient(
            config.fathom_api_key,
            config.max_requests_per_minute
        )
        logger.info("Fathom client initialized")
    else:
        logger.warning("Fathom API key not configured. Fathom tools will not be available.")

    logger.info("Clients initialized successfully")


@mcp.tool()
async def get_unreplied_emails(
    days_back: int = 7,
    max_results: int = 50,
    exclude_automated: bool = True
) -> str:
    """
    Find emails that have been read but not replied to.

    This tool identifies emails where:
    - Someone else sent the last message (not you)
    - You have read the message
    - You haven't replied yet
    - Optionally filters out automated emails

    Args:
        days_back: Number of days to look back (default: 7)
        max_results: Maximum number of results to return (default: 50)
        exclude_automated: Filter out automated emails (default: True)

    Returns:
        JSON string with list of unreplied emails
    """
    try:
        initialize_clients()

        # Calculate date range
        since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y/%m/%d')

        # Build Gmail query
        # -in:sent = exclude sent emails
        # -in:draft = exclude drafts
        # after:YYYY/MM/DD = date filter
        query = f"-in:sent -in:draft after:{since_date}"

        logger.info("Searching for unreplied emails: query=%s, max_results=%d", query, max_results)

        # Fetch threads (over-fetch to account for filtering)
        thread_infos = gmail_client.list_threads(query, int(max_results * 1.5))

        # Get user email
        user_email = gmail_client.get_user_email()

        # Fetch all threads in parallel
        thread_ids = [t['id'] for t in thread_infos]
        threads = gmail_client.batch_get_threads(thread_ids)

        # Process threads
        unreplied = []
        for thread in threads:
            if len(unreplied) >= max_results:
                break

            # Check if unreplied
            if email_analyzer.is_unreplied(thread, user_email):
                last_message = thread['messages'][-1]

                # Optional: Filter automated
                if exclude_automated and email_analyzer.is_automated_email(last_message):
                    continue

                # Format email information
                email_info = email_analyzer.format_unreplied_email(thread, last_message)
                unreplied.append(email_info)

        logger.info("Found %d unreplied emails", len(unreplied))

        return json.dumps({
            "success": True,
            "count": len(unreplied),
            "days_back": days_back,
            "exclude_automated": exclude_automated,
            "emails": unreplied
        }, indent=2)

    except HttpError as e:
        error_msg = f"Gmail API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg,
            "suggestion": "Check authentication and API quota. Run: python setup_oauth.py"
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_unreplied_emails: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_email_thread(thread_id: str) -> str:
    """
    Get the complete conversation history for an email thread.

    This tool retrieves all messages in a thread, showing the full
    back-and-forth conversation.

    Args:
        thread_id: Gmail thread ID

    Returns:
        JSON string with complete thread history
    """
    try:
        initialize_clients()

        logger.info("Fetching thread: %s", thread_id)

        # Fetch thread
        thread = gmail_client.get_thread(thread_id)

        # Parse all messages
        messages = []
        for msg in thread.get('messages', []):
            headers = email_analyzer.parse_headers(
                msg.get('payload', {}).get('headers', [])
            )

            # Extract timestamp
            received_timestamp = email_analyzer.extract_received_timestamp(msg)
            received_date = None
            if received_timestamp:
                try:
                    dt = datetime.fromtimestamp(int(received_timestamp) / 1000.0)
                    received_date = dt.isoformat()
                except (ValueError, OSError):
                    pass

            messages.append({
                "id": msg.get('id'),
                "from": headers.get('From'),
                "to": headers.get('To'),
                "subject": headers.get('Subject'),
                "date": received_date or headers.get('Date'),
                "snippet": msg.get('snippet', ''),
                "labels": msg.get('labelIds', [])
            })

        logger.info("Retrieved thread with %d messages", len(messages))

        return json.dumps({
            "success": True,
            "thread_id": thread_id,
            "message_count": len(messages),
            "messages": messages
        }, indent=2)

    except HttpError as e:
        if e.resp.status == 404:
            error_msg = f"Thread {thread_id} not found"
            logger.error(error_msg)
            return json.dumps({
                "success": False,
                "error": error_msg,
                "suggestion": "Verify the thread ID is correct"
            }, indent=2)

        error_msg = f"Gmail API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_email_thread: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def search_emails(query: str, max_results: int = 20) -> str:
    """
    Search emails using Gmail query syntax.

    This tool allows you to search emails using Gmail's powerful
    search operators.

    Args:
        query: Gmail search query (e.g., "from:example@gmail.com is:unread")
        max_results: Maximum number of results to return (default: 20)

    Returns:
        JSON string with search results

    Examples:
        - "from:boss@company.com after:2024/01/01"
        - "subject:urgent is:unread"
        - "has:attachment larger:5M"
        - "to:me -from:noreply"

    Gmail search operators: https://support.google.com/mail/answer/7190
    """
    try:
        initialize_clients()

        logger.info("Searching emails: query=%s, max_results=%d", query, max_results)

        # Search messages
        message_infos = gmail_client.list_messages(query, max_results)

        # Fetch message details in parallel using batch_get_messages
        message_ids = [msg_info['id'] for msg_info in message_infos]
        messages = gmail_client.batch_get_messages(message_ids)

        # Process results
        results = []
        for msg in messages:
            headers = email_analyzer.parse_headers(
                msg.get('payload', {}).get('headers', [])
            )

            # Extract timestamp
            received_timestamp = email_analyzer.extract_received_timestamp(msg)
            received_date = None
            if received_timestamp:
                try:
                    dt = datetime.fromtimestamp(int(received_timestamp) / 1000.0)
                    received_date = dt.isoformat()
                except (ValueError, OSError):
                    pass

            results.append({
                "id": msg.get('id'),
                "thread_id": msg.get('threadId'),
                "from": headers.get('From'),
                "subject": headers.get('Subject'),
                "date": received_date or headers.get('Date'),
                "snippet": msg.get('snippet', ''),
                "labels": msg.get('labelIds', [])
            })

        logger.info("Found %d messages", len(results))

        return json.dumps({
            "success": True,
            "query": query,
            "count": len(results),
            "results": results
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in search_emails: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg,
            "suggestion": "Check Gmail query syntax: https://support.google.com/mail/answer/7190"
        }, indent=2)


@mcp.tool()
async def get_inbox_summary() -> str:
    """
    Get statistics on unreplied emails.

    This tool provides a summary of your unreplied emails including:
    - Total count of unreplied emails
    - Top senders you haven't replied to
    - Top domains you haven't replied to
    - Date of oldest unreplied email

    Returns:
        JSON string with inbox summary statistics
    """
    try:
        initialize_clients()

        logger.info("Generating inbox summary...")

        # Get unreplied emails from last 30 days
        result_json = await get_unreplied_emails(days_back=30, max_results=50, exclude_automated=True)
        result = json.loads(result_json)

        if not result.get('success'):
            return result_json

        emails = result.get('emails', [])

        # Calculate statistics
        by_sender = {}
        by_domain = {}
        dates = []

        for email in emails:
            sender = email['sender']['email']
            domain = email['sender']['domain']

            by_sender[sender] = by_sender.get(sender, 0) + 1
            by_domain[domain] = by_domain.get(domain, 0) + 1

            if email.get('received_date'):
                try:
                    dt = datetime.fromisoformat(email['received_date'])
                    dates.append(dt)
                except ValueError:
                    pass

        # Sort by count
        top_senders = sorted(by_sender.items(), key=lambda x: x[1], reverse=True)[:10]
        top_domains = sorted(by_domain.items(), key=lambda x: x[1], reverse=True)[:10]

        # Find oldest and newest
        oldest_date = min(dates).isoformat() if dates else None
        newest_date = max(dates).isoformat() if dates else None

        logger.info("Generated summary: %d unreplied emails", len(emails))

        return json.dumps({
            "success": True,
            "total_unreplied": len(emails),
            "top_senders": [{"email": k, "count": v} for k, v in top_senders],
            "top_domains": [{"domain": k, "count": v} for k, v in top_domains],
            "oldest_unreplied": oldest_date,
            "newest_unreplied": newest_date,
            "date_range_days": 30
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_inbox_summary: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_unreplied_by_sender(email_or_domain: str) -> str:
    """
    Get unreplied emails from a specific sender or domain.

    This tool filters unreplied emails to show only those from
    a particular email address or domain.

    Args:
        email_or_domain: Email address (user@domain.com) or domain (@domain.com)

    Returns:
        JSON string with filtered unreplied emails

    Examples:
        - "john@example.com" - emails from John
        - "@example.com" - emails from anyone at example.com
    """
    try:
        initialize_clients()

        # Determine if email or domain
        is_domain = email_or_domain.startswith('@')

        logger.info("Searching unreplied from: %s", email_or_domain)

        # Build query
        if is_domain:
            query = f"from:{email_or_domain} -in:sent -in:draft"
        else:
            query = f"from:{email_or_domain} -in:sent -in:draft"

        # Search emails
        message_infos = gmail_client.list_messages(query, max_results=50)

        # Get user email
        user_email = gmail_client.get_user_email()

        # Get unique thread IDs and fetch all threads in parallel
        thread_ids = list(set([msg_info['threadId'] for msg_info in message_infos]))
        threads = gmail_client.batch_get_threads(thread_ids)

        # Create thread lookup dict
        threads_by_id = {t['id']: t for t in threads}

        # Filter for unreplied
        unreplied = []

        for msg_info in message_infos:
            thread = threads_by_id.get(msg_info['threadId'])
            if not thread:
                continue

            # Check if unreplied
            if email_analyzer.is_unreplied(thread, user_email):
                last_message = thread['messages'][-1]
                email_info = email_analyzer.format_unreplied_email(thread, last_message)
                unreplied.append(email_info)

        logger.info("Found %d unreplied emails from %s", len(unreplied), email_or_domain)

        return json.dumps({
            "success": True,
            "filter": email_or_domain,
            "count": len(unreplied),
            "emails": unreplied
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_unreplied_by_sender: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def list_calendars() -> str:
    """
    List all calendars accessible to the user.

    Returns:
        JSON string with list of calendars
    """
    try:
        initialize_clients()

        logger.info("Fetching calendars...")

        calendars = calendar_client.list_calendars()

        # Format calendar information
        calendar_list = []
        for cal in calendars:
            calendar_list.append({
                "id": cal.get('id'),
                "summary": cal.get('summary'),
                "description": cal.get('description', ''),
                "primary": cal.get('primary', False),
                "time_zone": cal.get('timeZone', ''),
                "access_role": cal.get('accessRole', '')
            })

        logger.info("Found %d calendars", len(calendar_list))

        return json.dumps({
            "success": True,
            "count": len(calendar_list),
            "calendars": calendar_list
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in list_calendars: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def list_calendar_events(
    calendar_id: str = 'primary',
    days_ahead: int = 7,
    max_results: int = 50,
    query: str = None
) -> str:
    """
    List upcoming calendar events.

    Args:
        calendar_id: Calendar ID (default: 'primary')
        days_ahead: Number of days ahead to fetch events (default: 7)
        max_results: Maximum number of events to return (default: 50)
        query: Optional search query to filter events

    Returns:
        JSON string with list of events
    """
    try:
        initialize_clients()

        logger.info("Fetching calendar events for next %d days...", days_ahead)

        # Calculate time range
        # Start from beginning of today (midnight) to include past events
        time_min = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        time_max = time_min + timedelta(days=days_ahead + 1)  # Add 1 to include the full last day

        # Fetch events
        events = calendar_client.list_events(
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
            query=query
        )

        # Format event information
        event_list = []
        for event in events:
            start = event.get('start', {})
            end = event.get('end', {})
            start_time_str = start.get('dateTime', start.get('date'))

            # Parse start time to get day of week and formatted date
            day_of_week = None
            formatted_date = None
            formatted_start_time = None
            if start_time_str:
                try:
                    if 'T' in start_time_str:
                        # DateTime format
                        start_dt = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        day_of_week = start_dt.strftime('%A')  # Monday, Tuesday, etc.
                        formatted_date = start_dt.strftime('%B %d, %Y')  # December 08, 2025
                        formatted_start_time = start_dt.strftime('%I:%M %p')  # 09:00 AM
                    else:
                        # Date-only format
                        start_dt = datetime.fromisoformat(start_time_str)
                        day_of_week = start_dt.strftime('%A')
                        formatted_date = start_dt.strftime('%B %d, %Y')
                except (ValueError, AttributeError):
                    # If we can't parse, leave as None
                    pass

            event_list.append({
                "id": event.get('id'),
                "summary": event.get('summary', 'No title'),
                "description": event.get('description', ''),
                "location": event.get('location', ''),
                "start": start_time_str,
                "end": end.get('dateTime', end.get('date')),
                "day_of_week": day_of_week,
                "formatted_date": formatted_date,
                "formatted_start_time": formatted_start_time,
                "attendees": [
                    {
                        "email": att.get('email'),
                        "response_status": att.get('responseStatus')
                    }
                    for att in event.get('attendees', [])
                ],
                "html_link": event.get('htmlLink', '')
            })

        logger.info("Found %d events", len(event_list))

        return json.dumps({
            "success": True,
            "calendar_id": calendar_id,
            "days_ahead": days_ahead,
            "count": len(event_list),
            "events": event_list
        }, indent=2)

    except HttpError as e:
        error_msg = f"Calendar API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in list_calendar_events: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def create_calendar_event(
    summary: str,
    start_time: str,
    end_time: str,
    calendar_id: str = 'primary',
    description: str = None,
    location: str = None,
    attendees: str = None,
    time_zone: str = None,
    add_meet_link: bool = None
) -> str:
    """
    Create a new calendar event.

    Args:
        summary: Event title
        start_time: Event start time (ISO 8601 format: YYYY-MM-DDTHH:MM:SS)
        end_time: Event end time (ISO 8601 format: YYYY-MM-DDTHH:MM:SS)
        calendar_id: Calendar ID (default: 'primary')
        description: Event description
        location: Event location (can be a Zoom link or physical location)
        attendees: Comma-separated list of attendee emails
        time_zone: Time zone (default: auto-detect from system, or 'America/Bogota')
        add_meet_link: Add Google Meet link (default: True if attendees present, False otherwise)

    Returns:
        JSON string with created event details including Google Meet link if added
    """
    try:
        initialize_clients()

        logger.info("Creating calendar event: %s", summary)

        # Auto-detect timezone if not provided
        if time_zone is None:
            import pytz
            from tzlocal import get_localzone
            try:
                local_tz = get_localzone()
                time_zone = str(local_tz)
                logger.info("Auto-detected timezone: %s", time_zone)
            except Exception:
                # Fallback to Colombia timezone
                time_zone = 'America/Bogota'
                logger.info("Using fallback timezone: %s", time_zone)

        # Parse datetime strings
        start_dt = datetime.fromisoformat(start_time)
        end_dt = datetime.fromisoformat(end_time)

        # Parse attendees if provided
        attendee_list = None
        if attendees:
            attendee_list = [email.strip() for email in attendees.split(',')]

        # Auto-add Google Meet if attendees present (unless explicitly disabled)
        if add_meet_link is None:
            add_meet_link = bool(attendee_list)  # True if there are attendees

        # Create event
        event = calendar_client.create_event(
            summary=summary,
            start_time=start_dt,
            end_time=end_dt,
            calendar_id=calendar_id,
            description=description,
            location=location,
            attendees=attendee_list,
            time_zone=time_zone,
            add_meet_link=add_meet_link
        )

        logger.info("Created event: %s (ID: %s)", summary, event['id'])

        # Extract Google Meet link if present
        meet_link = None
        if 'conferenceData' in event:
            entry_points = event['conferenceData'].get('entryPoints', [])
            for entry in entry_points:
                if entry.get('entryPointType') == 'video':
                    meet_link = entry.get('uri')
                    break

        # Send email notifications to all attendees
        if attendee_list:
            # Format the time nicely for the email
            start_formatted = start_dt.strftime('%A, %B %d, %Y at %I:%M %p')

            # Build email body
            email_body = f"You've been invited to a meeting:\n\n"
            email_body += f"Title: {summary}\n"
            email_body += f"Time: {start_formatted}\n"

            if location:
                email_body += f"Location: {location}\n"

            # Add Google Meet link prominently if present
            if meet_link:
                email_body += f"\n🎥 Google Meet: {meet_link}\n"

            if description:
                email_body += f"\nDetails:\n{description}\n"

            email_body += f"\nCalendar Link: {event.get('htmlLink', '')}\n"
            email_body += f"\nThis event has been added to your calendar."

            # Send email to each attendee
            for attendee_email in attendee_list:
                try:
                    gmail_client.send_message(
                        to=attendee_email,
                        subject=f"Calendar Invite: {summary}",
                        body=email_body
                    )
                    logger.info("Sent email notification to: %s", attendee_email)
                except Exception as e:
                    logger.warning("Failed to send email notification to %s: %s", attendee_email, str(e))

        # Build response
        response = {
            "success": True,
            "event_id": event['id'],
            "summary": event.get('summary'),
            "start": event.get('start', {}).get('dateTime'),
            "end": event.get('end', {}).get('dateTime'),
            "html_link": event.get('htmlLink', '')
        }

        # Add Meet link to response if present
        if meet_link:
            response['meet_link'] = meet_link
            logger.info("Google Meet link added: %s", meet_link)

        return json.dumps(response, indent=2)

    except ValueError as e:
        error_msg = f"Invalid datetime format: {str(e)}. Use ISO 8601 format (YYYY-MM-DDTHH:MM:SS)"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except HttpError as e:
        error_msg = f"Calendar API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in create_calendar_event: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def update_calendar_event(
    event_id: str,
    calendar_id: str = 'primary',
    summary: str = None,
    start_time: str = None,
    end_time: str = None,
    description: str = None,
    location: str = None,
    time_zone: str = None
) -> str:
    """
    Update an existing calendar event.

    Args:
        event_id: Event ID
        calendar_id: Calendar ID (default: 'primary')
        summary: New event title
        start_time: New start time (ISO 8601 format)
        end_time: New end time (ISO 8601 format)
        description: New description
        location: New location
        time_zone: Time zone (default: auto-detect from system, or 'America/Bogota')

    Returns:
        JSON string with updated event details
    """
    try:
        initialize_clients()

        logger.info("Updating calendar event: %s", event_id)

        # Auto-detect timezone if not provided
        if time_zone is None:
            import pytz
            from tzlocal import get_localzone
            try:
                local_tz = get_localzone()
                time_zone = str(local_tz)
                logger.info("Auto-detected timezone: %s", time_zone)
            except Exception:
                # Fallback to Colombia timezone
                time_zone = 'America/Bogota'
                logger.info("Using fallback timezone: %s", time_zone)

        # Parse datetime strings if provided
        start_dt = datetime.fromisoformat(start_time) if start_time else None
        end_dt = datetime.fromisoformat(end_time) if end_time else None

        # Update event
        event = calendar_client.update_event(
            event_id=event_id,
            calendar_id=calendar_id,
            summary=summary,
            start_time=start_dt,
            end_time=end_dt,
            description=description,
            location=location,
            time_zone=time_zone
        )

        logger.info("Updated event: %s", event_id)

        return json.dumps({
            "success": True,
            "event_id": event['id'],
            "summary": event.get('summary'),
            "start": event.get('start', {}).get('dateTime'),
            "end": event.get('end', {}).get('dateTime'),
            "html_link": event.get('htmlLink', '')
        }, indent=2)

    except ValueError as e:
        error_msg = f"Invalid datetime format: {str(e)}. Use ISO 8601 format (YYYY-MM-DDTHH:MM:SS)"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except HttpError as e:
        if e.resp.status == 404:
            error_msg = f"Event {event_id} not found"
            logger.error(error_msg)
            return json.dumps({
                "success": False,
                "error": error_msg
            }, indent=2)

        error_msg = f"Calendar API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in update_calendar_event: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def delete_calendar_event(
    event_id: str,
    calendar_id: str = 'primary'
) -> str:
    """
    Delete a calendar event.

    Args:
        event_id: Event ID
        calendar_id: Calendar ID (default: 'primary')

    Returns:
        JSON string with deletion confirmation
    """
    try:
        initialize_clients()

        logger.info("Deleting calendar event: %s", event_id)

        calendar_client.delete_event(event_id, calendar_id)

        logger.info("Deleted event: %s", event_id)

        return json.dumps({
            "success": True,
            "event_id": event_id,
            "message": "Event deleted successfully"
        }, indent=2)

    except HttpError as e:
        if e.resp.status == 404:
            error_msg = f"Event {event_id} not found"
            logger.error(error_msg)
            return json.dumps({
                "success": False,
                "error": error_msg
            }, indent=2)

        error_msg = f"Calendar API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in delete_calendar_event: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def list_past_calendar_events(
    calendar_id: str = 'primary',
    days_back: int = 7,
    max_results: int = 50,
    query: str = None
) -> str:
    """
    List past calendar events.

    Args:
        calendar_id: Calendar ID (default: 'primary')
        days_back: Number of days back to fetch events (default: 7)
        max_results: Maximum number of events to return (default: 50)
        query: Optional search query to filter events

    Returns:
        JSON string with list of past events
    """
    try:
        initialize_clients()

        logger.info("Fetching past calendar events for last %d days...", days_back)

        # Calculate time range
        time_max = datetime.now()
        time_min = time_max - timedelta(days=days_back)

        # Fetch events
        events = calendar_client.list_events(
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
            query=query
        )

        # Format event information
        event_list = []
        for event in events:
            start = event.get('start', {})
            end = event.get('end', {})
            start_time_str = start.get('dateTime', start.get('date'))

            # Parse start time to get day of week and formatted date
            day_of_week = None
            formatted_date = None
            formatted_start_time = None
            if start_time_str:
                try:
                    if 'T' in start_time_str:
                        # DateTime format
                        start_dt = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        day_of_week = start_dt.strftime('%A')  # Monday, Tuesday, etc.
                        formatted_date = start_dt.strftime('%B %d, %Y')  # December 08, 2025
                        formatted_start_time = start_dt.strftime('%I:%M %p')  # 09:00 AM
                    else:
                        # Date-only format
                        start_dt = datetime.fromisoformat(start_time_str)
                        day_of_week = start_dt.strftime('%A')
                        formatted_date = start_dt.strftime('%B %d, %Y')
                except (ValueError, AttributeError):
                    # If we can't parse, leave as None
                    pass

            event_list.append({
                "id": event.get('id'),
                "summary": event.get('summary', 'No title'),
                "description": event.get('description', ''),
                "location": event.get('location', ''),
                "start": start_time_str,
                "end": end.get('dateTime', end.get('date')),
                "day_of_week": day_of_week,
                "formatted_date": formatted_date,
                "formatted_start_time": formatted_start_time,
                "attendees": [
                    {
                        "email": att.get('email'),
                        "response_status": att.get('responseStatus')
                    }
                    for att in event.get('attendees', [])
                ],
                "html_link": event.get('htmlLink', '')
            })

        logger.info("Found %d past events", len(event_list))

        return json.dumps({
            "success": True,
            "calendar_id": calendar_id,
            "days_back": days_back,
            "count": len(event_list),
            "events": event_list
        }, indent=2)

    except HttpError as e:
        error_msg = f"Calendar API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in list_past_calendar_events: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def quick_add_calendar_event(
    text: str,
    calendar_id: str = 'primary'
) -> str:
    """
    Create a calendar event using natural language.

    This tool uses Google Calendar's natural language processing
    to create events from text descriptions.

    Args:
        text: Natural language description (e.g., "Dinner with John tomorrow at 7pm")
        calendar_id: Calendar ID (default: 'primary')

    Returns:
        JSON string with created event details

    Examples:
        - "Meeting with team tomorrow at 3pm"
        - "Lunch at Cafe Roma on Friday at noon"
        - "Vacation from Dec 20 to Dec 30"
    """
    try:
        initialize_clients()

        logger.info("Quick adding calendar event: %s", text)

        event = calendar_client.quick_add_event(text, calendar_id)

        logger.info("Quick added event: %s (ID: %s)", text, event['id'])

        return json.dumps({
            "success": True,
            "event_id": event['id'],
            "summary": event.get('summary'),
            "start": event.get('start', {}).get('dateTime', event.get('start', {}).get('date')),
            "end": event.get('end', {}).get('dateTime', event.get('end', {}).get('date')),
            "html_link": event.get('htmlLink', '')
        }, indent=2)

    except HttpError as e:
        error_msg = f"Calendar API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in quick_add_calendar_event: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


# ===============================================
# Google Docs Tools
# ===============================================

@mcp.tool()
async def create_google_doc(
    title: str,
    initial_content: str = None
) -> str:
    """
    Create a new Google Doc with optional initial content.

    Args:
        title: Title of the document
        initial_content: Optional text to add to the document

    Returns:
        JSON string with document ID, title, and URL

    Examples:
        - create_google_doc("Meeting Notes - Dec 19", "Attendees:\\n- John\\n- Sarah")
        - create_google_doc("Project Proposal")
    """
    try:
        initialize_clients()

        logger.info(f"Creating Google Doc: {title}")

        # Create the document
        doc = docs_client.create_document(title)
        doc_id = doc['documentId']
        doc_url = docs_client.get_document_url(doc_id)

        # Add initial content if provided
        if initial_content:
            docs_client.insert_text(doc_id, initial_content + '\n', index=1)
            logger.info(f"Added initial content to document")

        logger.info(f"Created Google Doc: {doc_url}")

        return json.dumps({
            "success": True,
            "document_id": doc_id,
            "title": doc['title'],
            "url": doc_url,
            "message": f"Created document '{title}'"
        }, indent=2)

    except HttpError as e:
        error_msg = f"Google Docs API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in create_google_doc: {error_msg}")
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def append_to_google_doc(
    document_id: str,
    content: str
) -> str:
    """
    Append text to the end of an existing Google Doc.

    Args:
        document_id: The ID of the document (from the URL)
        content: Text to append

    Returns:
        JSON string with success status

    Example:
        - append_to_google_doc("1abc...", "\\n\\nAdditional notes:\\n- Point 1\\n- Point 2")
    """
    try:
        initialize_clients()

        logger.info(f"Appending to Google Doc: {document_id}")

        # Append the content
        docs_client.append_text(document_id, content)
        doc_url = docs_client.get_document_url(document_id)

        logger.info(f"Successfully appended content")

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "url": doc_url,
            "message": "Content appended successfully"
        }, indent=2)

    except HttpError as e:
        error_msg = f"Google Docs API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in append_to_google_doc: {error_msg}")
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def insert_into_google_doc(
    document_id: str,
    content: str,
    index: int = 1
) -> str:
    """
    Insert text at a specific position in a Google Doc.

    Args:
        document_id: The ID of the document (from the URL)
        content: Text to insert
        index: Character position where to insert (default: 1, right after title)

    Returns:
        JSON string with success status

    Example:
        - insert_into_google_doc("1abc...", "Introduction\\n\\n", index=1)
    """
    try:
        initialize_clients()

        logger.info(f"Inserting into Google Doc: {document_id} at index {index}")

        # Insert the content
        docs_client.insert_text(document_id, content, index=index)
        doc_url = docs_client.get_document_url(document_id)

        logger.info(f"Successfully inserted content")

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "url": doc_url,
            "message": f"Content inserted at index {index}"
        }, indent=2)

    except HttpError as e:
        error_msg = f"Google Docs API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in insert_into_google_doc: {error_msg}")
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def read_google_doc(
    document_id: str
) -> str:
    """
    Read the text content from a Google Doc.

    Args:
        document_id: The ID of the document (from the URL)

    Returns:
        JSON string with document content and metadata

    Example:
        - read_google_doc("1abc...")
    """
    try:
        initialize_clients()

        logger.info(f"Reading Google Doc: {document_id}")

        # Get the document
        doc = docs_client.get_document(document_id)
        text_content = docs_client.extract_text(document_id)
        doc_url = docs_client.get_document_url(document_id)

        logger.info(f"Successfully read document")

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "title": doc['title'],
            "content": text_content,
            "url": doc_url
        }, indent=2)

    except HttpError as e:
        error_msg = f"Google Docs API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in read_google_doc: {error_msg}")
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def replace_text_in_google_doc(
    document_id: str,
    find_text: str,
    replace_with: str
) -> str:
    """
    Find and replace text in a Google Doc.

    Args:
        document_id: The ID of the document (from the URL)
        find_text: Text to find
        replace_with: Text to replace with

    Returns:
        JSON string with success status

    Example:
        - replace_text_in_google_doc("1abc...", "{{client_name}}", "Acme Corp")
    """
    try:
        initialize_clients()

        logger.info(f"Replacing text in Google Doc: {document_id}")

        # Replace the text
        docs_client.replace_all_text(document_id, find_text, replace_with)
        doc_url = docs_client.get_document_url(document_id)

        logger.info(f"Successfully replaced text")

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "url": doc_url,
            "message": f"Replaced '{find_text}' with '{replace_with}'"
        }, indent=2)

    except HttpError as e:
        error_msg = f"Google Docs API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in replace_text_in_google_doc: {error_msg}")
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def add_heading_to_google_doc(
    document_id: str,
    heading_text: str,
    heading_level: int = 1,
    index: int = None
) -> str:
    """
    Add a formatted heading to a Google Doc.

    Args:
        document_id: The ID of the document (from the URL)
        heading_text: The heading text
        heading_level: Heading level (1-6, default: 1 for H1)
        index: Position to insert (default: end of document)

    Returns:
        JSON string with success status

    Example:
        - add_heading_to_google_doc("1abc...", "Executive Summary", heading_level=1)
        - add_heading_to_google_doc("1abc...", "Background", heading_level=2)
    """
    try:
        initialize_clients()

        logger.info(f"Adding heading to Google Doc: {document_id}")

        # Map heading level to Google Docs style
        heading_map = {
            1: "HEADING_1",
            2: "HEADING_2",
            3: "HEADING_3",
            4: "HEADING_4",
            5: "HEADING_5",
            6: "HEADING_6"
        }

        heading_style = heading_map.get(heading_level, "HEADING_1")

        # Insert heading
        if index is None:
            # Get document to find end index
            doc = docs_client.get_document(document_id)
            index = doc['body']['content'][-1]['endIndex'] - 1

        docs_client.insert_paragraph(document_id, heading_text, index=index, heading=heading_style)
        doc_url = docs_client.get_document_url(document_id)

        logger.info(f"Successfully added heading")

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "url": doc_url,
            "message": f"Added {heading_style} heading"
        }, indent=2)

    except HttpError as e:
        error_msg = f"Google Docs API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in add_heading_to_google_doc: {error_msg}")
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = None,
    bcc: str = None,
    force_new_thread: bool = False,
    confirm: bool = False
) -> str:
    """
    Send a NEW email (creates a new conversation thread).

    ⚠️ IMPORTANT: This creates a NEW thread. To REPLY to existing emails, use reply_to_email instead!

    This tool will:
    1. Check if you have existing conversations with this recipient
    2. Suggest using reply_to_email if threads exist
    3. Show preview before sending
    4. Require confirmation to actually send

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body (plain text)
        cc: CC recipients (comma-separated, optional)
        bcc: BCC recipients (comma-separated, optional)
        force_new_thread: Set True to skip existing thread check and force new thread
        confirm: Set to True to actually send (after previewing)

    Returns:
        JSON string with preview, existing thread suggestions, or sent message confirmation
    """
    try:
        initialize_clients()

        # Check for existing threads with this recipient (unless forcing new thread)
        if not force_new_thread and not confirm:
            logger.info("Checking for existing threads with: %s", to)

            # Extract email address from "Name <email>" format
            recipient_email = to
            if '<' in to and '>' in to:
                recipient_email = to[to.index('<')+1:to.index('>')]

            # Search for existing conversations
            search_query = f"(to:{recipient_email} OR from:{recipient_email})"
            try:
                message_infos = gmail_client.search_messages(search_query, max_results=5)

                if message_infos:
                    # Found existing threads - suggest using reply_to_email
                    existing_threads = []
                    seen_threads = set()

                    for msg in message_infos:
                        thread_id = msg.get('threadId')
                        if thread_id not in seen_threads:
                            seen_threads.add(thread_id)

                            # Get thread details
                            headers = email_analyzer.parse_headers(
                                msg.get('payload', {}).get('headers', [])
                            )

                            existing_threads.append({
                                "thread_id": thread_id,
                                "subject": headers.get('Subject', 'No subject'),
                                "from": headers.get('From', ''),
                                "date": headers.get('Date', ''),
                                "snippet": msg.get('snippet', '')[:100]
                            })

                            if len(existing_threads) >= 3:
                                break

                    if existing_threads:
                        return json.dumps({
                            "success": False,
                            "warning": "EXISTING_CONVERSATIONS_FOUND",
                            "message": f"Found {len(message_infos)} existing email(s) with {to}. Are you trying to REPLY?",
                            "suggestion": "Use reply_to_email instead of send_email to continue an existing conversation.",
                            "existing_threads": existing_threads,
                            "options": {
                                "to_reply": "Use reply_to_email with one of the thread_ids above",
                                "force_new": "If you really want a NEW conversation, call send_email again with force_new_thread=True"
                            }
                        }, indent=2)

            except Exception as search_error:
                # If search fails, continue with sending (don't block on search errors)
                logger.warning("Thread search failed, continuing: %s", search_error)

        # If not confirmed, return preview
        if not confirm:
            preview = {
                "action": "PREVIEW - NOT SENT",
                "to": to,
                "subject": subject,
                "body": body,
                "message": "Email NOT sent yet. This will create a NEW thread. Review and confirm."
            }

            if cc:
                preview["cc"] = cc
            if bcc:
                preview["bcc"] = bcc

            return json.dumps({
                "success": True,
                "requires_confirmation": True,
                "preview": preview
            }, indent=2)

        # Confirmed - send the email
        logger.info("Sending NEW email to: %s, subject: %s", to, subject)

        sent_message = gmail_client.send_message(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc
        )

        logger.info("Email sent successfully: %s", sent_message['id'])

        return json.dumps({
            "success": True,
            "message_id": sent_message['id'],
            "message": f"Email sent successfully to {to}"
        }, indent=2)

    except HttpError as e:
        error_msg = f"Gmail API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in send_email: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def reply_to_email(
    thread_id: str,
    body: str,
    confirm: bool = False
) -> str:
    """
    Reply to an EXISTING email thread (continues the conversation).

    ✅ USE THIS to reply to existing emails - keeps them in the same thread!
    ❌ DO NOT use send_email for replies - that creates a new thread

    This tool:
    - Automatically adds "Re:" to subject
    - Sets proper threading headers (In-Reply-To, References)
    - Maintains thread continuity in Gmail
    - Shows preview before sending
    - Requires confirmation to send

    Args:
        thread_id: Gmail thread ID to reply to (from search results or get_thread)
        body: Reply body (plain text)
        confirm: Set to True to actually send (after previewing)

    Returns:
        JSON string with preview or sent message confirmation
    """
    try:
        initialize_clients()

        # Get the thread to extract reply information
        thread = gmail_client.get_thread(thread_id)

        # Find the last real message (skip automated messages like reminders, no-reply, etc.)
        last_message = None
        automated_domains = ['superhuman.com', 'noreply', 'no-reply', 'donotreply', 'do-not-reply']

        for msg in reversed(thread['messages']):
            msg_headers = email_analyzer.parse_headers(msg.get('payload', {}).get('headers', []))
            from_addr_check = msg_headers.get('From', '').lower()

            # Skip automated messages
            is_automated = any(domain in from_addr_check for domain in automated_domains)
            if not is_automated:
                last_message = msg
                break

        if not last_message:
            # Fallback to last message if all are automated
            last_message = thread['messages'][-1]

        # Parse headers
        from email_analyzer import EmailAnalyzer
        analyzer = EmailAnalyzer()
        headers = analyzer.parse_headers(last_message.get('payload', {}).get('headers', []))

        # Extract reply info
        from_addr = headers.get('From', '')
        to_addr = headers.get('To', '')
        cc_addr = headers.get('Cc', '')
        subject = headers.get('Subject', '')
        message_id = headers.get('Message-ID', '')
        references = headers.get('References', '')

        # Safety check: If Message-ID is missing, use last message's ID as fallback
        if not message_id:
            logger.warning("Message-ID header missing, using message ID as fallback")
            message_id = f"<{last_message['id']}@mail.gmail.com>"

        # Get user email to exclude from CC
        user_email = gmail_client.get_user_email()

        # Build CC list with other participants
        all_recipients = []
        if to_addr:
            all_recipients.extend([addr.strip() for addr in to_addr.split(',')])
        if cc_addr:
            all_recipients.extend([addr.strip() for addr in cc_addr.split(',')])

        # Filter out user's own email and the sender (they're in To field)
        cc_list = []
        for recipient in all_recipients:
            # Extract just the email from "Name <email>" format
            email_part = recipient
            if '<' in recipient and '>' in recipient:
                email_part = recipient[recipient.index('<')+1:recipient.index('>')]

            # Skip if it's the user or the person we're replying to
            if user_email.lower() not in email_part.lower() and email_part.lower() not in from_addr.lower():
                cc_list.append(recipient)

        cc = ', '.join(cc_list) if cc_list else None

        # Add Re: if not already present
        if not subject.startswith('Re:'):
            subject = f"Re: {subject}"

        # Build references header for proper threading
        if references and message_id:
            new_references = f"{references} {message_id}"
        elif message_id:
            new_references = message_id
        else:
            new_references = None

        # If not confirmed, return preview
        if not confirm:
            preview = {
                "action": "PREVIEW - NOT SENT",
                "to": from_addr,
                "subject": subject,
                "body": body,
                "thread_id": thread_id,
                "message": "Reply NOT sent yet. Review the details above. To send, confirm with the user first."
            }

            if cc:
                preview["cc"] = cc

            return json.dumps({
                "success": True,
                "requires_confirmation": True,
                "preview": preview
            }, indent=2)

        # Confirmed - send the reply
        logger.info("Sending reply to thread: %s", thread_id)

        sent_message = gmail_client.send_message(
            to=from_addr,
            subject=subject,
            body=body,
            cc=cc,
            thread_id=thread_id,
            in_reply_to=message_id,
            references=new_references
        )

        logger.info("Reply sent successfully: %s", sent_message['id'])

        return json.dumps({
            "success": True,
            "message_id": sent_message['id'],
            "thread_id": thread_id,
            "message": f"Reply sent successfully to thread {thread_id}"
        }, indent=2)

    except HttpError as e:
        error_msg = f"Gmail API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in reply_to_email: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def reply_all_to_email(
    thread_id: str,
    body: str,
    confirm: bool = False
) -> str:
    """
    Reply to all recipients in an email thread. Requires confirmation before sending.

    This tool will show you a preview first. Reply with confirmation to actually send.

    Args:
        thread_id: Gmail thread ID to reply to
        body: Reply body (plain text)
        confirm: Set to True to actually send (after previewing)

    Returns:
        JSON string with preview or sent message confirmation
    """
    try:
        initialize_clients()

        # Get the thread to extract reply information
        thread = gmail_client.get_thread(thread_id)

        # Find the last real message (skip automated messages like reminders, no-reply, etc.)
        last_message = None
        automated_domains = ['superhuman.com', 'noreply', 'no-reply', 'donotreply', 'do-not-reply']

        for msg in reversed(thread['messages']):
            msg_headers = email_analyzer.parse_headers(msg.get('payload', {}).get('headers', []))
            from_addr_check = msg_headers.get('From', '').lower()

            # Skip automated messages
            is_automated = any(domain in from_addr_check for domain in automated_domains)
            if not is_automated:
                last_message = msg
                break

        if not last_message:
            # Fallback to last message if all are automated
            last_message = thread['messages'][-1]

        # Parse headers
        from email_analyzer import EmailAnalyzer
        analyzer = EmailAnalyzer()
        headers = analyzer.parse_headers(last_message.get('payload', {}).get('headers', []))

        # Extract reply info
        from_addr = headers.get('From', '')
        to_addr = headers.get('To', '')
        cc_addr = headers.get('Cc', '')
        subject = headers.get('Subject', '')
        message_id = headers.get('Message-ID', '')
        references = headers.get('References', '')

        # Get user email to exclude from recipients
        user_email = gmail_client.get_user_email()

        # Build recipient lists (excluding user)
        all_recipients = []
        if to_addr:
            all_recipients.extend([addr.strip() for addr in to_addr.split(',')])
        if cc_addr:
            all_recipients.extend([addr.strip() for addr in cc_addr.split(',')])

        # Filter out user's own email
        all_recipients = [r for r in all_recipients if user_email.lower() not in r.lower()]

        # Primary recipient is the sender
        to = from_addr

        # CC is everyone else
        cc = ', '.join(all_recipients) if all_recipients else None

        # Add Re: if not already present
        if not subject.startswith('Re:'):
            subject = f"Re: {subject}"

        # Build references header
        if references:
            new_references = f"{references} {message_id}"
        else:
            new_references = message_id

        # If not confirmed, return preview
        if not confirm:
            preview = {
                "action": "PREVIEW - NOT SENT",
                "to": to,
                "cc": cc,
                "subject": subject,
                "body": body,
                "thread_id": thread_id,
                "message": "Reply All NOT sent yet. Review the details above. To send, confirm with the user first."
            }

            return json.dumps({
                "success": True,
                "requires_confirmation": True,
                "preview": preview
            }, indent=2)

        # Confirmed - send the reply
        logger.info("Sending reply-all to thread: %s", thread_id)

        sent_message = gmail_client.send_message(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            thread_id=thread_id,
            in_reply_to=message_id,
            references=new_references
        )

        logger.info("Reply-all sent successfully: %s", sent_message['id'])

        return json.dumps({
            "success": True,
            "message_id": sent_message['id'],
            "thread_id": thread_id,
            "message": f"Reply-all sent successfully to thread {thread_id}"
        }, indent=2)

    except HttpError as e:
        error_msg = f"Gmail API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in reply_all_to_email: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def create_email_draft(
    to: str,
    subject: str,
    body: str,
    cc: str = None,
    bcc: str = None
) -> str:
    """
    Create an email draft without sending.

    Drafts can be reviewed and edited in Gmail before sending.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body (plain text)
        cc: CC recipients (comma-separated, optional)
        bcc: BCC recipients (comma-separated, optional)

    Returns:
        JSON string with draft creation confirmation
    """
    try:
        initialize_clients()

        logger.info("Creating email draft to: %s, subject: %s", to, subject)

        draft = gmail_client.create_draft(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc
        )

        logger.info("Draft created successfully: %s", draft['id'])

        return json.dumps({
            "success": True,
            "draft_id": draft['id'],
            "message": f"Draft created successfully. You can review and edit it in Gmail before sending.",
            "to": to,
            "subject": subject
        }, indent=2)

    except HttpError as e:
        error_msg = f"Gmail API error: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in create_email_draft: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


# ============================================================================
# FATHOM MEETING TOOLS
# ============================================================================

@mcp.tool()
async def list_fathom_meetings(
    limit: int = 20,
    calendar_invitees_domains_type: str = "all"
) -> str:
    """
    List recent Fathom meeting recordings.

    This tool retrieves your recent meetings recorded by Fathom with basic
    information including title, date, participants, and recording URL.

    Args:
        limit: Maximum number of meetings to return (default: 20)
        calendar_invitees_domains_type: Filter meetings by attendee type
            - "all": All meetings
            - "internal_only": Only meetings with internal attendees
            - "one_or_more_external": Meetings with at least one external attendee

    Returns:
        JSON string with list of meetings
    """
    try:
        initialize_clients()

        if not fathom_client:
            return json.dumps({
                "success": False,
                "error": "Fathom API key not configured. Please set FATHOM_API_KEY in your environment."
            }, indent=2)

        logger.info("Fetching %d Fathom meetings...", limit)

        response = fathom_client.list_meetings(
            limit=limit,
            calendar_invitees_domains_type=calendar_invitees_domains_type
        )

        meetings = response.get('items', [])

        # Format meeting information
        meeting_list = []
        for meeting in meetings:
            meeting_list.append({
                "recording_id": meeting.get('recording_id'),
                "title": meeting.get('title') or meeting.get('meeting_title'),
                "url": meeting.get('url'),
                "share_url": meeting.get('share_url'),
                "scheduled_start": meeting.get('scheduled_start_time'),
                "scheduled_end": meeting.get('scheduled_end_time'),
                "recording_start": meeting.get('recording_start_time'),
                "recording_end": meeting.get('recording_end_time'),
                "language": meeting.get('transcript_language'),
                "attendees": [
                    {
                        "name": att.get('name'),
                        "email": att.get('email'),
                        "is_external": att.get('is_external')
                    }
                    for att in meeting.get('calendar_invitees', [])
                ]
            })

        logger.info("Found %d Fathom meetings", len(meeting_list))

        return json.dumps({
            "success": True,
            "count": len(meeting_list),
            "meetings": meeting_list,
            "next_cursor": response.get('next_cursor')
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in list_fathom_meetings: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_fathom_transcript(recording_id: int) -> str:
    """
    Get the full transcript of a Fathom meeting recording.

    This tool retrieves the complete transcript with speaker names,
    timestamps, and the spoken text.

    Args:
        recording_id: Fathom recording ID

    Returns:
        JSON string with complete transcript
    """
    try:
        initialize_clients()

        if not fathom_client:
            return json.dumps({
                "success": False,
                "error": "Fathom API key not configured. Please set FATHOM_API_KEY in your environment."
            }, indent=2)

        logger.info("Fetching transcript for recording %d...", recording_id)

        response = fathom_client.get_meeting_transcript(recording_id)
        transcript = response.get('transcript', [])

        # Format transcript entries
        transcript_list = []
        for entry in transcript:
            speaker = entry.get('speaker', {})
            transcript_list.append({
                "speaker_name": speaker.get('display_name'),
                "speaker_email": speaker.get('matched_calendar_invitee_email'),
                "text": entry.get('text'),
                "timestamp": entry.get('timestamp')
            })

        logger.info("Retrieved transcript with %d entries", len(transcript_list))

        return json.dumps({
            "success": True,
            "recording_id": recording_id,
            "entry_count": len(transcript_list),
            "transcript": transcript_list
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_fathom_transcript: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_fathom_summary(recording_id: int) -> str:
    """
    Get the AI-generated summary of a Fathom meeting recording.

    This tool retrieves a concise summary of the meeting with key points,
    decisions, and action items.

    Args:
        recording_id: Fathom recording ID

    Returns:
        JSON string with meeting summary
    """
    try:
        initialize_clients()

        if not fathom_client:
            return json.dumps({
                "success": False,
                "error": "Fathom API key not configured. Please set FATHOM_API_KEY in your environment."
            }, indent=2)

        logger.info("Fetching summary for recording %d...", recording_id)

        response = fathom_client.get_meeting_summary(recording_id)
        summary = response.get('summary', {})

        logger.info("Retrieved summary for recording %d", recording_id)

        return json.dumps({
            "success": True,
            "recording_id": recording_id,
            "template": summary.get('template_name'),
            "summary": summary.get('markdown_formatted')
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_fathom_summary: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def search_fathom_meetings_by_title(
    search_term: str,
    limit: int = 50
) -> str:
    """
    Search Fathom meetings by title or meeting name.

    This tool searches through your recent meetings to find those matching
    the search term in the title.

    Args:
        search_term: Search term to match in meeting titles
        limit: Maximum number of meetings to search through (default: 50)

    Returns:
        JSON string with matching meetings
    """
    try:
        initialize_clients()

        if not fathom_client:
            return json.dumps({
                "success": False,
                "error": "Fathom API key not configured. Please set FATHOM_API_KEY in your environment."
            }, indent=2)

        logger.info("Searching for meetings with title containing '%s'...", search_term)

        meetings = fathom_client.search_meetings_by_title(search_term, limit)

        # Format meeting information
        meeting_list = []
        for meeting in meetings:
            meeting_list.append({
                "recording_id": meeting.get('recording_id'),
                "title": meeting.get('title') or meeting.get('meeting_title'),
                "url": meeting.get('url'),
                "scheduled_start": meeting.get('scheduled_start_time'),
                "attendees": [
                    att.get('email') for att in meeting.get('calendar_invitees', [])
                ]
            })

        logger.info("Found %d meetings matching '%s'", len(meeting_list), search_term)

        return json.dumps({
            "success": True,
            "search_term": search_term,
            "count": len(meeting_list),
            "meetings": meeting_list
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in search_fathom_meetings_by_title: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def search_fathom_meetings_by_attendee(
    email: str,
    limit: int = 50
) -> str:
    """
    Find Fathom meetings with a specific attendee.

    This tool searches through your recent meetings to find those that
    included a specific person (by email address).

    Args:
        email: Email address of the attendee to search for
        limit: Maximum number of meetings to search through (default: 50)

    Returns:
        JSON string with meetings including the specified attendee
    """
    try:
        initialize_clients()

        if not fathom_client:
            return json.dumps({
                "success": False,
                "error": "Fathom API key not configured. Please set FATHOM_API_KEY in your environment."
            }, indent=2)

        logger.info("Searching for meetings with attendee '%s'...", email)

        meetings = fathom_client.search_meetings_by_attendee(email, limit)

        # Format meeting information
        meeting_list = []
        for meeting in meetings:
            meeting_list.append({
                "recording_id": meeting.get('recording_id'),
                "title": meeting.get('title') or meeting.get('meeting_title'),
                "url": meeting.get('url'),
                "scheduled_start": meeting.get('scheduled_start_time'),
                "all_attendees": [
                    {
                        "name": att.get('name'),
                        "email": att.get('email')
                    }
                    for att in meeting.get('calendar_invitees', [])
                ]
            })

        logger.info("Found %d meetings with attendee '%s'", len(meeting_list), email)

        return json.dumps({
            "success": True,
            "attendee_email": email,
            "count": len(meeting_list),
            "meetings": meeting_list
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in search_fathom_meetings_by_attendee: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_fathom_action_items(recording_id: int) -> str:
    """
    Get action items from a Fathom meeting recording.

    This tool retrieves all action items identified in a meeting, including
    who they're assigned to and whether they've been completed.

    Args:
        recording_id: Fathom recording ID

    Returns:
        JSON string with action items
    """
    try:
        initialize_clients()

        if not fathom_client:
            return json.dumps({
                "success": False,
                "error": "Fathom API key not configured. Please set FATHOM_API_KEY in your environment."
            }, indent=2)

        logger.info("Fetching action items for recording %d...", recording_id)

        # Get the full meeting data which includes action items
        response = fathom_client.list_meetings(limit=100)
        meetings = response.get('items', [])

        # Find the specific meeting
        target_meeting = None
        for meeting in meetings:
            if meeting.get('recording_id') == recording_id:
                target_meeting = meeting
                break

        if not target_meeting:
            return json.dumps({
                "success": False,
                "error": f"Meeting with recording_id {recording_id} not found"
            }, indent=2)

        action_items = target_meeting.get('action_items', [])

        # Format action items
        action_list = []
        for item in action_items:
            assignee = item.get('assignee', {})
            action_list.append({
                "description": item.get('description'),
                "completed": item.get('completed'),
                "user_generated": item.get('user_generated'),
                "timestamp": item.get('recording_timestamp'),
                "playback_url": item.get('recording_playback_url'),
                "assignee_name": assignee.get('name'),
                "assignee_email": assignee.get('email')
            })

        logger.info("Found %d action items for recording %d", len(action_list), recording_id)

        return json.dumps({
            "success": True,
            "recording_id": recording_id,
            "count": len(action_list),
            "action_items": action_list
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_fathom_action_items: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


# ============================================================================
# LEAD MANAGEMENT TOOLS
# ============================================================================

@mcp.tool()
async def get_instantly_clients() -> str:
    """
    Get list of all Instantly.ai clients/workspaces.

    Returns all 56 Instantly clients with their workspace IDs and client names.

    Returns:
        JSON string with client list
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching Instantly client list...")

        result = get_client_list(
            sheet_url=config.lead_sheets_url
        )

        logger.info("Found %d Instantly clients", result.get('total_clients', 0))

        return json.dumps({
            "success": True,
            **result
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_instantly_clients: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_instantly_leads(
    workspace_id: str,
    days: int = 7,
    start_date: str = None,
    end_date: str = None
) -> str:
    """
    Get lead responses for a specific Instantly.ai workspace.

    This tool retrieves all lead responses (interested/replied leads) for a given
    workspace within the specified time period.

    Args:
        workspace_id: Instantly.ai workspace ID
        days: Number of days to look back (default: 7)
        start_date: Start date in YYYY-MM-DD format (optional, overrides days)
        end_date: End date in YYYY-MM-DD format (optional, overrides days)

    Returns:
        JSON string with lead responses
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching Instantly leads for workspace %s (days=%d)...", workspace_id, days)

        result = get_lead_responses(
            sheet_url=config.lead_sheets_url,
            gid=config.lead_sheets_gid_instantly,
            workspace_id=workspace_id,
            days=days,
            start_date=start_date,
            end_date=end_date
        )

        logger.info("Found %d leads for workspace %s", result.get('total_leads', 0), workspace_id)

        return json.dumps({
            "success": True,
            **result
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_instantly_leads: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_instantly_stats(
    workspace_id: str,
    days: int = 7,
    start_date: str = None,
    end_date: str = None
) -> str:
    """
    Get campaign statistics for a specific Instantly.ai workspace.

    This tool retrieves comprehensive campaign statistics including sent emails,
    opens, replies, interested leads, and more for a given workspace.

    Args:
        workspace_id: Instantly.ai workspace ID
        days: Number of days to look back (default: 7)
        start_date: Start date in YYYY-MM-DD format (optional, overrides days)
        end_date: End date in YYYY-MM-DD format (optional, overrides days)

    Returns:
        JSON string with campaign statistics
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching Instantly stats for workspace %s (days=%d)...", workspace_id, days)

        result = get_campaign_stats(
            sheet_url=config.lead_sheets_url,
            gid=config.lead_sheets_gid_instantly,
            workspace_id=workspace_id,
            days=days,
            start_date=start_date,
            end_date=end_date
        )

        logger.info("Retrieved stats for workspace %s: %d interested leads",
                   workspace_id, result.get('interested_leads', 0))

        return json.dumps({
            "success": True,
            **result
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_instantly_stats: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_instantly_workspace(workspace_id: str) -> str:
    """
    Get detailed information about a specific Instantly.ai workspace.

    This tool retrieves workspace details including client name, workspace ID,
    and other metadata.

    Args:
        workspace_id: Instantly.ai workspace ID

    Returns:
        JSON string with workspace information
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching Instantly workspace info for %s...", workspace_id)

        result = get_workspace_info(
            sheet_url=config.lead_sheets_url,
            workspace_id=workspace_id
        )

        logger.info("Retrieved workspace info for %s", workspace_id)

        return json.dumps({
            "success": True,
            **result
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_instantly_workspace: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_all_clients_with_positive_replies(
    days: int = 7,
    platform: str = "all"
) -> str:
    """
    FAST: Get ALL clients with positive replies across platforms using parallel processing.

    This tool is OPTIMIZED for speed - it fetches data from all 88+ clients simultaneously
    instead of checking them one by one. Perfect for queries like "which clients had positive
    replies this week?"

    Args:
        days: Number of days to look back (default: 7)
        platform: Which platform to check - "all", "instantly", or "bison" (default: "all")

    Returns:
        JSON with list of clients that have positive replies, sorted by reply count
    """
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from leads.lead_functions import get_lead_responses
        from leads.sheets_client import load_workspaces_from_sheet, load_bison_workspaces_from_sheet

        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching positive replies for all clients (days=%d, platform=%s)...", days, platform)

        clients_with_replies = []

        # Helper function to fetch leads for a single workspace
        def fetch_workspace_leads(workspace, platform_name, gid):
            try:
                # Call appropriate function based on platform
                if platform_name == "bison":
                    from leads.lead_functions import get_bison_lead_responses
                    client_name = workspace.get("client_name")
                    result = get_bison_lead_responses(
                        client_name=client_name,
                        days=days,
                        sheet_url=config.lead_sheets_url,
                        gid=gid
                    )
                else:  # instantly
                    workspace_id = workspace.get("workspace_id") or workspace.get("client_name")
                    result = get_lead_responses(
                        workspace_id=workspace_id,
                        days=days,
                        sheet_url=config.lead_sheets_url,
                        gid=gid
                    )

                total_leads = result.get("total_leads", 0)
                if total_leads > 0:
                    client_name = workspace.get("client_name") or workspace.get("workspace_id", "unknown")
                    return {
                        "client_name": client_name,
                        "platform": platform_name,
                        "total_replies": total_leads
                    }
            except Exception as e:
                logger.debug(f"Error fetching leads for {workspace.get('client_name', 'unknown')}: {e}")
            return None

        # PARALLEL PROCESSING: Fetch all clients simultaneously
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []

            # Queue Instantly clients
            if platform in ["all", "instantly"]:
                instantly_workspaces = load_workspaces_from_sheet(config.lead_sheets_url, gid=config.lead_sheets_gid_instantly)
                for ws in instantly_workspaces:
                    futures.append(executor.submit(fetch_workspace_leads, ws, "instantly", config.lead_sheets_gid_instantly))

            # Queue Bison clients
            if platform in ["all", "bison"]:
                bison_workspaces = load_bison_workspaces_from_sheet(config.lead_sheets_url, gid=config.lead_sheets_gid_bison)
                for ws in bison_workspaces:
                    futures.append(executor.submit(fetch_workspace_leads, ws, "bison", config.lead_sheets_gid_bison))

            # Collect results as they complete
            for future in as_completed(futures):
                result = future.result()
                if result:
                    clients_with_replies.append(result)

        # Sort by number of replies (descending)
        clients_with_replies.sort(key=lambda x: x["total_replies"], reverse=True)

        total_replies = sum(c["total_replies"] for c in clients_with_replies)

        # Calculate platform breakdown
        instantly_clients = [c for c in clients_with_replies if c["platform"] == "instantly"]
        bison_clients = [c for c in clients_with_replies if c["platform"] == "bison"]

        instantly_replies = sum(c["total_replies"] for c in instantly_clients)
        bison_replies = sum(c["total_replies"] for c in bison_clients)

        logger.info("Found %d clients with positive replies (total: %d replies)",
                   len(clients_with_replies), total_replies)

        return json.dumps({
            "success": True,
            "period": f"Last {days} days",
            "platform": platform,
            "summary": {
                "total_clients_with_replies": len(clients_with_replies),
                "total_positive_replies": total_replies,
                "average_replies_per_client": round(total_replies / len(clients_with_replies), 1) if clients_with_replies else 0
            },
            "platform_breakdown": {
                "instantly": {
                    "clients": len(instantly_clients),
                    "replies": instantly_replies,
                    "percentage": round(instantly_replies / total_replies * 100, 1) if total_replies > 0 else 0
                },
                "bison": {
                    "clients": len(bison_clients),
                    "replies": bison_replies,
                    "percentage": round(bison_replies / total_replies * 100, 1) if total_replies > 0 else 0
                }
            },
            "top_10_performers": clients_with_replies[:10],
            "all_clients_summary": clients_with_replies,
            "note": "Use get_client_lead_details(client_name) to see individual lead responses for any client"
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_all_clients_with_positive_replies: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_active_instantly_clients(days: int = 14) -> str:
    """
    FAST: Get all Instantly clients that have sent emails in the specified time period.

    Uses parallel processing to check campaign activity across all Instantly workspaces
    simultaneously. Perfect for queries like "which Instantly clients sent emails this week?"

    Args:
        days: Number of days to look back (default: 14)

    Returns:
        JSON with list of Instantly clients that have campaign activity, sorted by emails sent

    Example:
        get_active_instantly_clients(14)  # Get clients with activity in last 14 days
    """
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from leads.date_utils import validate_and_parse_dates
        from leads.sheets_client import load_workspaces_from_sheet
        import requests

        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching active Instantly clients (last %d days)...", days)

        # Calculate date range
        start_date, end_date, warnings = validate_and_parse_dates(days=days)

        # Load all Instantly workspaces
        instantly_workspaces = load_workspaces_from_sheet(
            sheet_url=config.lead_sheets_url,
            gid=config.lead_sheets_gid_instantly
        )

        logger.info("Checking %d Instantly workspaces for campaign activity...", len(instantly_workspaces))

        def check_client_activity(workspace):
            """Check if client has sent emails"""
            try:
                from leads.instantly_client import get_instantly_campaign_stats

                client_name = workspace.get("client_name", workspace.get("workspace_name", "Unknown"))
                api_key = workspace["api_key"]

                # Get campaign stats from Instantly API (V2)
                data = get_instantly_campaign_stats(
                    api_key=api_key,
                    start_date=start_date,
                    end_date=end_date
                )

                # Check if any emails were sent
                emails_sent = data.get("emails_sent_count", 0)

                if emails_sent > 0:
                    return {
                        "client_name": client_name,
                        "emails_sent": emails_sent,
                        "replied": data.get("reply_count_unique", 0),
                        "total_opportunities": data.get("total_opportunities", 0),
                        "reply_rate": data.get("reply_rate", 0)
                    }
                return None

            except Exception as e:
                logger.warning("Error checking Instantly client %s: %s", client_name, str(e))
                return None

        # Use parallel processing to check all clients simultaneously
        active_clients = []
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(check_client_activity, ws): ws for ws in instantly_workspaces}

            for future in as_completed(futures):
                result = future.result()
                if result:
                    active_clients.append(result)

        # Sort by emails sent (descending)
        active_clients.sort(key=lambda x: x["emails_sent"], reverse=True)

        # Calculate summary stats
        total_emails = sum(c["emails_sent"] for c in active_clients)
        total_replied = sum(c["replied"] for c in active_clients)
        total_opportunities = sum(c["total_opportunities"] for c in active_clients)

        logger.info("Found %d active Instantly clients with %d emails sent",
                   len(active_clients), total_emails)

        return json.dumps({
            "success": True,
            "period": f"Last {days} days",
            "date_range": {
                "start_date": start_date,
                "end_date": end_date
            },
            "summary": {
                "total_instantly_workspaces": len(instantly_workspaces),
                "active_clients": len(active_clients),
                "inactive_clients": len(instantly_workspaces) - len(active_clients),
                "total_emails_sent": total_emails,
                "total_replied": total_replied,
                "total_opportunities": total_opportunities,
                "average_emails_per_client": round(total_emails / len(active_clients), 1) if active_clients else 0,
                "average_reply_rate": round(sum(c["reply_rate"] for c in active_clients) / len(active_clients), 2) if active_clients else 0
            },
            "active_clients": active_clients[:50],  # Limit to top 50
            "note": "Clients sorted by emails sent (highest first). Note: Instantly API returns workspace-level stats."
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_active_instantly_clients: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_active_bison_clients(days: int = 14) -> str:
    """
    FAST: Get all Bison clients that have sent emails in the specified time period.

    Uses parallel processing to check campaign activity across all Bison workspaces
    simultaneously. Perfect for queries like "which Bison clients sent emails this week?"

    Args:
        days: Number of days to look back (default: 14)

    Returns:
        JSON with list of Bison clients that have campaign activity, sorted by emails sent

    Example:
        get_active_bison_clients(14)  # Get clients with activity in last 14 days
    """
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from leads.date_utils import validate_and_parse_dates
        from leads.sheets_client import load_bison_workspaces_from_sheet
        from leads.bison_client import get_bison_campaign_stats_api

        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching active Bison clients (last %d days)...", days)

        # Calculate date range
        start_date, end_date, warnings = validate_and_parse_dates(days=days)

        # Load all Bison workspaces
        bison_workspaces = load_bison_workspaces_from_sheet(
            sheet_url=config.lead_sheets_url,
            gid=config.lead_sheets_gid_bison
        )

        logger.info("Checking %d Bison workspaces for campaign activity...", len(bison_workspaces))

        def check_client_activity(workspace):
            """Check if client has sent emails"""
            try:
                client_name = workspace.get("client_name", workspace.get("workspace_name", "Unknown"))
                api_key = workspace["api_key"]

                # Get campaign stats from Bison API
                response = get_bison_campaign_stats_api(
                    api_key=api_key,
                    start_date=start_date,
                    end_date=end_date
                )

                data = response.get("data", {})

                # Check if any emails were sent
                emails_sent = data.get("emails_sent", 0)

                if emails_sent > 0:
                    return {
                        "client_name": client_name,
                        "emails_sent": emails_sent,
                        "total_leads_contacted": data.get("total_leads_contacted", 0),
                        "opened": data.get("opened", 0),
                        "opened_percentage": data.get("opened_percentage", 0),
                        "replied": data.get("unique_replies_per_contact", 0),
                        "reply_percentage": data.get("unique_replies_per_contact_percentage", 0),
                        "bounced": data.get("bounced", 0),
                        "bounced_percentage": data.get("bounced_percentage", 0),
                        "interested": data.get("interested", 0),
                        "interested_percentage": data.get("interested_percentage", 0),
                        "unsubscribed": data.get("unsubscribed", 0)
                    }
                return None

            except Exception as e:
                logger.warning("Error checking Bison client %s: %s", client_name, str(e))
                return None

        # Use parallel processing to check all clients simultaneously
        active_clients = []
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(check_client_activity, ws): ws for ws in bison_workspaces}

            for future in as_completed(futures):
                result = future.result()
                if result:
                    active_clients.append(result)

        # Sort by emails sent (descending)
        active_clients.sort(key=lambda x: x["emails_sent"], reverse=True)

        # Calculate summary stats
        total_emails = sum(c["emails_sent"] for c in active_clients)
        total_opened = sum(c["opened"] for c in active_clients)
        total_replied = sum(c["replied"] for c in active_clients)
        total_interested = sum(c["interested"] for c in active_clients)

        logger.info("Found %d active Bison clients with %d emails sent",
                   len(active_clients), total_emails)

        return json.dumps({
            "success": True,
            "period": f"Last {days} days",
            "date_range": {
                "start_date": start_date,
                "end_date": end_date
            },
            "summary": {
                "total_bison_workspaces": len(bison_workspaces),
                "active_clients": len(active_clients),
                "inactive_clients": len(bison_workspaces) - len(active_clients),
                "total_emails_sent": total_emails,
                "total_opened": total_opened,
                "total_replied": total_replied,
                "total_interested": total_interested,
                "average_emails_per_client": round(total_emails / len(active_clients), 1) if active_clients else 0,
                "average_reply_rate": round(sum(c["reply_percentage"] for c in active_clients) / len(active_clients), 1) if active_clients else 0
            },
            "active_clients": active_clients[:50],  # Limit to top 50
            "note": "Clients sorted by emails sent (highest first)"
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_active_bison_clients: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_all_active_clients(days: int = 14, platform: str = "all") -> str:
    """
    FAST: Get all active clients across both Instantly and Bison platforms.

    Combines results from both platforms using parallel processing. Perfect for
    overview queries like "show me all clients that sent emails this week"

    Args:
        days: Number of days to look back (default: 14)
        platform: Which platform to check - "all", "instantly", or "bison" (default: "all")

    Returns:
        JSON with combined list of active clients from both platforms

    Example:
        get_all_active_clients(14)  # All platforms, last 14 days
        get_all_active_clients(7, "instantly")  # Only Instantly
    """
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = {}

        def fetch_instantly():
            """Fetch Instantly clients"""
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(get_active_instantly_clients(days))
                return ("instantly", json.loads(result))
            except Exception as e:
                logger.error("Error fetching Instantly clients: %s", str(e))
                return ("instantly", {"success": False, "error": str(e)})

        def fetch_bison():
            """Fetch Bison clients"""
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(get_active_bison_clients(days))
                return ("bison", json.loads(result))
            except Exception as e:
                logger.error("Error fetching Bison clients: %s", str(e))
                return ("bison", {"success": False, "error": str(e)})

        # Fetch both platforms in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = []

            if platform in ["all", "instantly"]:
                futures.append(executor.submit(fetch_instantly))

            if platform in ["all", "bison"]:
                futures.append(executor.submit(fetch_bison))

            for future in as_completed(futures):
                platform_name, data = future.result()
                results[platform_name] = data

        # Combine results
        combined_clients = []
        total_emails = 0
        total_replied = 0

        for platform_name, data in results.items():
            if data.get("success"):
                clients = data.get("active_clients", [])
                for client in clients:
                    client["platform"] = platform_name
                    combined_clients.append(client)

                summary = data.get("summary", {})
                total_emails += summary.get("total_emails_sent", 0)
                total_replied += summary.get("total_replied", 0)

        # Sort by emails sent
        combined_clients.sort(key=lambda x: x.get("emails_sent", 0), reverse=True)

        return json.dumps({
            "success": True,
            "period": f"Last {days} days",
            "summary": {
                "total_active_clients": len(combined_clients),
                "total_emails_sent": total_emails,
                "total_replied": total_replied,
                "instantly_clients": len([c for c in combined_clients if c["platform"] == "instantly"]),
                "bison_clients": len([c for c in combined_clients if c["platform"] == "bison"])
            },
            "active_clients": combined_clients[:50],  # Top 50
            "platform_details": {
                "instantly": results.get("instantly", {}).get("summary", {}),
                "bison": results.get("bison", {}).get("summary", {})
            },
            "note": "Clients from both platforms sorted by emails sent. Instantly data is workspace-level."
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_all_active_clients: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_client_lead_details(client_name: str, days: int = 7) -> str:
    """
    Get detailed lead responses for a specific client.

    Use this after get_all_clients_with_positive_replies() to drill down into
    individual client performance and see the actual lead responses.

    Args:
        client_name: Name of the client (from the all_clients_summary)
        days: Number of days to look back (default: 7)

    Returns:
        JSON string with detailed lead responses including email, status, and reply content

    Example:
        get_client_lead_details("Rick Pendrick", 7)
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching detailed leads for client: %s (days=%d)", client_name, days)

        # Try to find the client in both platforms
        result = None
        platform_used = None

        # Try Instantly first
        try:
            instantly_workspaces = load_workspaces_from_sheet(
                config.lead_sheets_url,
                gid=config.lead_sheets_gid_instantly
            )
            matching_workspace = next(
                (ws for ws in instantly_workspaces
                 if ws.get("client_name", "").lower() == client_name.lower() or
                    ws.get("workspace_id", "").lower() == client_name.lower()),
                None
            )

            if matching_workspace:
                workspace_id = matching_workspace.get("workspace_id") or matching_workspace.get("client_name")
                result = get_lead_responses(
                    workspace_id=workspace_id,
                    days=days,
                    sheet_url=config.lead_sheets_url,
                    gid=config.lead_sheets_gid_instantly
                )
                platform_used = "instantly"
        except Exception as e:
            logger.debug(f"Client not found in Instantly: {e}")

        # Try Bison if not found in Instantly
        if not result or result.get("total_leads", 0) == 0:
            try:
                from leads.lead_functions import get_bison_lead_responses
                result = get_bison_lead_responses(
                    client_name=client_name,
                    days=days,
                    sheet_url=config.lead_sheets_url,
                    gid=config.lead_sheets_gid_bison
                )
                platform_used = "bison"
            except Exception as e:
                logger.debug(f"Client not found in Bison: {e}")

        if not result or result.get("total_leads", 0) == 0:
            return json.dumps({
                "success": False,
                "error": f"No lead data found for client '{client_name}' in the last {days} days. "
                        f"Check that the client name matches exactly (case-insensitive)."
            }, indent=2)

        return json.dumps({
            "success": True,
            "client_name": client_name,
            "platform": platform_used,
            "period": f"Last {days} days",
            "total_leads": result.get("total_leads", 0),
            "leads": result.get("leads", []),
            "summary": result.get("summary", "")
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_client_lead_details: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def find_missed_opportunities(
    client_name: str,
    days: int = 7,
    use_claude: bool = True,
    exclude_auto_replies: bool = True
) -> str:
    """
    Find "hidden gems" - interested leads that Instantly/Bison AI didn't categorize correctly.

    This tool fetches ALL campaign replies (not just marked-as-interested), excludes the ones
    already marked, and uses AI to analyze the remaining replies to find missed opportunities.

    Perfect for quality assurance on lead categorization!

    Supports BOTH Instantly and Bison clients - automatically detects which platform the client uses.

    Args:
        client_name: Name of the client to analyze (works with both Instantly and Bison)
        days: Number of days to look back (default: 7)
        use_claude: Use Claude API for unclear cases (default: True, requires ANTHROPIC_API_KEY)
        exclude_auto_replies: Exclude automated replies like OOO messages (default: True, Bison only)

    Returns:
        JSON with hidden gems report showing missed interested leads

    Examples:
        find_missed_opportunities("Rick Pendrick", 7, True)  # Instantly client
        find_missed_opportunities("Rich Cave", 7, True)      # Bison client
        find_missed_opportunities("Jeff Mikolai", 30, True, True)  # Exclude auto-replies
    """
    try:
        from leads._source_fetch_interested_leads import fetch_all_campaign_replies
        from leads.interest_analyzer import categorize_leads
        from leads.sheets_client import load_workspaces_from_sheet
        from leads.date_utils import validate_and_parse_dates

        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Finding missed opportunities for %s (days=%d, use_claude=%s, exclude_auto_replies=%s)",
                   client_name, days, use_claude, exclude_auto_replies)

        # Calculate date range
        logger.info("Step 1/7: Calculating date range...")
        start_date, end_date, warnings = validate_and_parse_dates(days=days)
        logger.info("Date range: %s to %s", start_date, end_date)

        # Try to find client in Instantly workspaces first
        from leads.sheets_client import load_bison_workspaces_from_sheet
        from leads.bison_client import get_bison_lead_replies

        platform_used = None
        all_replies = []
        already_interested = []

        logger.info("Step 2/7: Loading Instantly workspaces...")
        instantly_workspaces = load_workspaces_from_sheet(
            config.lead_sheets_url,
            gid=config.lead_sheets_gid_instantly
        )
        logger.info("Loaded %d Instantly workspaces", len(instantly_workspaces))

        matching_instantly_workspace = next(
            (ws for ws in instantly_workspaces
             if ws.get("client_name", "").lower() == client_name.lower() or
                ws.get("workspace_id", "").lower() == client_name.lower()),
            None
        )

        # Try Instantly first
        if matching_instantly_workspace:
            api_key = matching_instantly_workspace.get("api_key")
            if not api_key:
                return json.dumps({
                    "success": False,
                    "error": f"No API key found for Instantly client '{client_name}'"
                }, indent=2)

            logger.info("Found client in Instantly, fetching replies...")
            platform_used = "instantly"

            # Step 1: Fetch ALL campaign replies (no i_status filter)
            logger.info("Step 3/7: Fetching all Instantly replies...")
            all_replies_result = fetch_all_campaign_replies(
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                i_status=None  # Fetch ALL replies
            )
            logger.info("Fetched %d total replies", all_replies_result.get("total_count", 0))

            # Step 2: Split replies into already-captured (positive status) vs missed opportunities
            logger.info("Step 4/7: Filtering Instantly replies by status...")
            all_replies = all_replies_result.get("leads", [])

            # Add platform field to Instantly replies for timing detection
            for reply in all_replies:
                reply["platform"] = "instantly"

            # Positive statuses that indicate already-captured opportunities
            POSITIVE_STATUSES = [1, 2, 3, 4]  # Interested, Meeting Booked, Meeting Completed, Closed

            # Separate already-captured from potential missed opportunities
            already_interested = [
                lead for lead in all_replies
                if lead.get("i_status") in POSITIVE_STATUSES
            ]

            # Log status breakdown for debugging
            logger.info(
                "Found %d already-captured opportunities: %s",
                len(already_interested),
                ", ".join([
                    f"{sum(1 for l in already_interested if l.get('i_status') == 1)} Interested (1)",
                    f"{sum(1 for l in already_interested if l.get('i_status') == 2)} Meeting Booked (2)",
                    f"{sum(1 for l in already_interested if l.get('i_status') == 3)} Meeting Completed (3)",
                    f"{sum(1 for l in already_interested if l.get('i_status') == 4)} Closed/Won (4)"
                ])
            )

            # Debug: Log first few already-interested emails
            if already_interested:
                sample_emails = [lead.get("email") for lead in already_interested[:5]]
                logger.info(f"Sample of already-interested emails: {sample_emails}")

            # Debug: Log status distribution of ALL replies
            status_counts = {}
            for reply in all_replies:
                status = reply.get("i_status")
                status_counts[status] = status_counts.get(status, 0) + 1
            logger.info(f"Status distribution of all replies: {status_counts}")

        # If not found in Instantly, try Bison
        if not matching_instantly_workspace:
            logger.info("Client not found in Instantly, checking Bison...")
            logger.info("Step 3/7: Loading Bison workspaces...")
            bison_workspaces = load_bison_workspaces_from_sheet(
                config.lead_sheets_url,
                gid=config.lead_sheets_gid_bison
            )
            logger.info("Loaded %d Bison workspaces", len(bison_workspaces))

            matching_bison_workspace = next(
                (ws for ws in bison_workspaces
                 if ws.get("client_name", "").lower() == client_name.lower()),
                None
            )

            if not matching_bison_workspace:
                # Show similar client names to help with debugging
                all_client_names = [ws.get("client_name", "") for ws in bison_workspaces]
                similar_names = [name for name in all_client_names if client_name.lower() in name.lower() or name.lower() in client_name.lower()]

                error_msg = f"Client '{client_name}' not found in either Instantly or Bison workspaces."
                if similar_names:
                    error_msg += f"\n\nDid you mean one of these?\n" + "\n".join(f"  - {name}" for name in similar_names[:10])
                else:
                    error_msg += f"\n\nAvailable Bison clients (first 10):\n" + "\n".join(f"  - {name}" for name in all_client_names[:10])

                return json.dumps({
                    "success": False,
                    "error": error_msg,
                    "suggestion": "Use get_bison_clients() or get_instantly_clients() to see all available clients"
                }, indent=2)

            api_key = matching_bison_workspace.get("api_key")
            if not api_key:
                return json.dumps({
                    "success": False,
                    "error": f"No API key found for Bison client '{client_name}'"
                }, indent=2)

            logger.info("Found client in Bison, fetching replies...")
            platform_used = "bison"

            # Step 1: Fetch ALL campaign replies (excluding auto-replies if requested)
            # Use status="not_automated_reply" to exclude OOO messages and other auto-replies
            logger.info("Step 4/7: Fetching all Bison replies...")
            all_replies_status = "not_automated_reply" if exclude_auto_replies else None
            all_replies_result = get_bison_lead_replies(
                api_key=api_key,
                status=all_replies_status,
                folder="all"
            )
            logger.info("Fetched %d total Bison replies", len(all_replies_result.get("data", [])))

            # Step 2: Filter for already-marked interested leads using the "interested" field (GRAY TAG)
            # NOTE: Don't use status="interested" API filter - it only returns GREEN status (new unreplied)
            # The "interested" field is the persistent GRAY TAG that survives after you reply back
            logger.info("Step 5/7: Filtering for Bison interested tag (persistent gray label)...")
            all_replies_raw = all_replies_result.get("data", [])
            interested_replies_raw = [r for r in all_replies_raw if r.get("interested", False)]
            logger.info("Found %d Bison replies with interested=true (gray tag)", len(interested_replies_raw))

            logger.info("Bison raw counts - All replies: %d, Interested replies: %d",
                       len(all_replies_raw), len(interested_replies_raw))

            # Normalize Bison replies to match Instantly format
            # Filter out client's own outbound emails using 'sender_email_id' field
            for reply in all_replies_raw:
                reply_type = reply.get("type", "").lower()
                from_email = reply.get("from_email_address", "")
                campaign_id = reply.get("campaign_id")
                lead_id = reply.get("lead_id")
                sender_email_id = reply.get("sender_email_id")

                # Skip client's sent emails: sender_email_id is present when CLIENT sent the email
                # Lead replies have sender_email_id = None
                if sender_email_id is not None:
                    logger.debug(f"Skipping client sent email (sender_email_id={sender_email_id}) from {from_email}")
                    continue

                # Skip if this is an outbound/sent email (backup check using type field)
                if reply_type in ["sent", "outbound", "out"]:
                    logger.debug(f"Skipping outbound email (type={reply_type}) from {from_email}")
                    continue

                # Skip test emails: no campaign AND no lead = test/untracked email (not a real campaign reply)
                # Real campaign replies ALWAYS have campaign_id and lead_id
                if campaign_id is None and lead_id is None:
                    logger.debug(f"Skipping test/untracked email (no campaign_id/lead_id) from {from_email}")
                    continue

                # Log the type for debugging
                logger.debug(f"Processing reply type={reply_type} from {from_email}, sender_email_id={sender_email_id}, campaign_id={campaign_id}, lead_id={lead_id}")

                all_replies.append({
                    "email": reply.get("from_email_address", "Unknown"),
                    "reply_body": reply.get("text_body", ""),
                    "reply_summary": reply.get("text_body", "")[:200] + "..." if len(reply.get("text_body", "")) > 200 else reply.get("text_body", ""),
                    "subject": reply.get("subject", ""),
                    "timestamp": reply.get("date_received", ""),
                    "id": reply.get("id"),  # Bison reply ID for thread lookup
                    "lead_id": reply.get("lead_id"),
                    "interested": reply.get("interested", False),
                    "platform": "bison"  # Track platform for timing detection
                })

            for reply in interested_replies_raw:
                reply_type = reply.get("type", "").lower()
                from_email = reply.get("from_email_address", "")
                sender_email_id = reply.get("sender_email_id")

                # Skip client's sent emails: sender_email_id is present when CLIENT sent the email
                if sender_email_id is not None:
                    logger.debug(f"Skipping client sent email from interested list (sender_email_id={sender_email_id}) from {from_email}")
                    continue

                # Skip outbound emails (backup check)
                if reply_type in ["sent", "outbound", "out"]:
                    logger.debug(f"Skipping outbound email (type={reply_type}) from {from_email}")
                    continue

                already_interested.append({
                    "email": reply.get("from_email_address", "Unknown"),
                    "reply_body": reply.get("text_body", ""),
                    "reply_summary": reply.get("text_body", "")[:200] + "..." if len(reply.get("text_body", "")) > 200 else reply.get("text_body", ""),
                    "subject": reply.get("subject", ""),
                    "timestamp": reply.get("date_received", ""),
                    "id": reply.get("id"),  # Bison reply ID for thread lookup
                    "lead_id": reply.get("lead_id"),
                    "interested": True,
                    "platform": "bison"  # Track platform for timing detection
                })

        # Create set of already-interested email addresses
        logger.info("Step 6/7: Filtering replies...")
        already_interested_emails = {lead["email"].lower() for lead in already_interested}

        # Step 3: Filter to get ONLY the non-interested replies
        non_interested_replies = [
            lead for lead in all_replies
            if lead["email"].lower() not in already_interested_emails
        ]

        logger.info("Total replies: %d, Already interested: %d, Not marked interested: %d",
                   len(all_replies), len(already_interested), len(non_interested_replies))

        if not non_interested_replies:
            return json.dumps({
                "success": True,
                "client_name": client_name,
                "period": f"Last {days} days",
                "total_replies": len(all_replies),
                "already_marked_interested": len(already_interested),
                "analyzed_replies": 0,
                "hidden_gems_found": 0,
                "message": "All replies have already been marked as interested! No hidden gems to find.",
                "hidden_gems": []
            }, indent=2)

        # Deduplicate by email - keep only the FIRST (earliest) reply per person
        # This ensures green "Interested" tag shows on the first reply
        from collections import defaultdict
        email_to_earliest_reply = {}
        for reply in non_interested_replies:
            email = reply["email"].lower()
            timestamp = reply.get("timestamp", "")

            # If we haven't seen this email yet, or this reply is earlier
            if email not in email_to_earliest_reply:
                email_to_earliest_reply[email] = reply
            else:
                # Compare timestamps and keep the earlier one
                existing_timestamp = email_to_earliest_reply[email].get("timestamp", "")
                if timestamp < existing_timestamp:
                    email_to_earliest_reply[email] = reply

        # Use deduplicated list (one reply per person)
        non_interested_replies = list(email_to_earliest_reply.values())
        logger.info("After deduplication: %d unique people to analyze", len(non_interested_replies))

        # Step 4: AI analyze the non-interested replies
        logger.info("Step 7/7: AI analyzing %d non-interested replies (use_claude=%s)...",
                   len(non_interested_replies), use_claude)
        logger.info("This may take 30-60 seconds for 100+ replies with Claude API enabled...")
        categorized = categorize_leads(non_interested_replies, use_claude=use_claude, api_key=api_key)
        logger.info("AI analysis complete!")

        # Hidden gems = HOT + WARM leads from the non-interested bucket
        hidden_gems = categorized["hot"] + categorized["warm"]

        # Sort by confidence
        hidden_gems.sort(key=lambda x: x["ai_confidence"], reverse=True)

        # Build detailed report for hidden gems
        hidden_gems_report = []
        for gem in hidden_gems:
            report_item = {
                "email": gem["email"],
                "category": gem["ai_category"],
                "confidence": gem["ai_confidence"],
                "reason": gem["ai_reason"],
                "reply_summary": gem["reply_summary"],
                "full_reply": gem["reply_body"][:500] + "..." if len(gem["reply_body"]) > 500 else gem["reply_body"],
                "subject": gem["subject"],
                "timestamp": gem["timestamp"],
                "analysis_method": gem["ai_method"]
            }

            # Add reply_id for Bison (needed for mark_lead_as_interested)
            if "id" in gem:
                report_item["reply_id"] = gem["id"]
            elif "reply_id" in gem:
                report_item["reply_id"] = gem["reply_id"]

            # Add lead_id for Instantly (needed for mark_lead_as_interested)
            if "lead_id" in gem:
                report_item["lead_id"] = gem["lead_id"]

            # Add thread_id for context
            if "thread_id" in gem:
                report_item["thread_id"] = gem["thread_id"]

            # Add campaign_id for marking
            if "campaign_id" in gem:
                report_item["campaign_id"] = gem["campaign_id"]

            hidden_gems_report.append(report_item)

        # Also build report for unclear leads (for manual review)
        unclear_report = []
        for unclear_lead in categorized["unclear"]:
            report_item = {
                "email": unclear_lead["email"],
                "confidence": unclear_lead["ai_confidence"],
                "reason": unclear_lead["ai_reason"],
                "reply_summary": unclear_lead["reply_summary"],
                "full_reply": unclear_lead["reply_body"][:500] + "..." if len(unclear_lead["reply_body"]) > 500 else unclear_lead["reply_body"],
                "subject": unclear_lead["subject"],
                "timestamp": unclear_lead["timestamp"],
                "analysis_method": unclear_lead["ai_method"]
            }

            # Add reply_id for Bison (needed for mark_lead_as_interested)
            if "id" in unclear_lead:
                report_item["reply_id"] = unclear_lead["id"]
            elif "reply_id" in unclear_lead:
                report_item["reply_id"] = unclear_lead["reply_id"]

            unclear_report.append(report_item)

        logger.info("Found %d hidden gems (hot: %d, warm: %d)",
                   len(hidden_gems), len(categorized["hot"]), len(categorized["warm"]))

        platform_name = "Instantly" if platform_used == "instantly" else "Bison"

        return json.dumps({
            "success": True,
            "client_name": client_name,
            "platform": platform_used,
            "period": f"Last {days} days",
            "summary": {
                "total_replies": len(all_replies),
                "already_marked_interested": len(already_interested),
                "analyzed_replies": len(non_interested_replies),
                "hidden_gems_found": len(hidden_gems),
                "breakdown": {
                    "hot": len(categorized["hot"]),
                    "warm": len(categorized["warm"]),
                    "cold": len(categorized["cold"]),
                    "auto_reply": len(categorized["auto_reply"]),
                    "unclear": len(categorized["unclear"])
                }
            },
            "hidden_gems": hidden_gems_report[:20],  # Limit to top 20
            "unclear_leads": unclear_report[:20],  # Include unclear leads for manual review
            "message": f"Found {len(hidden_gems)} potential missed opportunities! "
                      f"These replies look interested but weren't marked by {platform_name} AI.",
            "note": f"To mark leads: Use mark_lead_as_interested with client_name, lead_email, and lead_id (if present) for best results!"
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in find_missed_opportunities: %s", error_msg)
        import traceback
        logger.error("Traceback: %s", traceback.format_exc())
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def mark_lead_as_interested(
    client_name: str,
    lead_email: str,
    reply_id: Optional[int] = None,
    lead_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    interest_value: int = 1
) -> str:
    """
    Mark a lead as interested in Instantly or Bison.

    Auto-detects which platform the client uses and marks the lead accordingly.
    For Bison: Uses reply_id to mark the reply as interested
    For Instantly: Uses lead_id to look up campaign, then marks the lead

    Args:
        client_name: Name of the client (e.g., "Jeff Mikolai", "Lena Kadriu")
        lead_email: Email address of the lead to mark (the person who replied)
        reply_id: (Bison only) Reply ID to mark as interested
        lead_id: (Instantly) IMPORTANT - Original lead's email for campaign lookup
                 For forwarded replies, this is the original recipient's email
                 Example: If Julian forwarded to Amanda, lead_id=julian@example.com
                 Used to look up campaign when campaign_id is not provided
        campaign_id: (Instantly) Campaign UUID - will be auto-looked-up from lead_id if not provided
        interest_value: (Instantly) Interest status value (default: 1)
            1 = Interested, 2 = Meeting Booked, 3 = Meeting Completed,
            4 = Closed, -1 = Not Interested, -2 = Wrong Person, -3 = Lost

    Returns:
        JSON string with success status and platform used

    Example:
        # Bison
        mark_lead_as_interested("Jeff Mikolai", "john@example.com", reply_id=123)

        # Instantly with campaign
        mark_lead_as_interested("Lena Kadriu", "jane@example.com", campaign_id="abc-123-def")

        # Instantly forwarded reply (campaign auto-looked-up from lead_id)
        mark_lead_as_interested("Brian Rechtman", "amanda@example.com", lead_id="julian@example.com")
    """
    try:
        # Import required functions
        from leads._source_fetch_interested_leads import mark_instantly_lead_as_interested
        from leads.bison_client import mark_bison_reply_as_interested
        from leads.sheets_client import load_workspaces_from_sheet, load_bison_workspaces_from_sheet

        logger.info("Marking lead as interested: %s (client: %s)", lead_email, client_name)

        # Try Instantly first
        instantly_workspaces = load_workspaces_from_sheet(
            sheet_url=config.lead_sheets_url,
            gid=config.lead_sheets_gid_instantly
        )

        matching_instantly_workspace = next(
            (w for w in instantly_workspaces if w["client_name"].lower() == client_name.lower()),
            None
        )

        if matching_instantly_workspace:
            # Use Instantly API
            api_key = matching_instantly_workspace["api_key"]

            # Log whether we have lead_id for better debugging
            if lead_id:
                logger.info("✅ Marking lead %s with lead_id: %s (will look up campaign from this lead)", lead_email, lead_id)
            else:
                logger.warning("⚠️  Marking lead WITHOUT lead_id: %s", lead_email)
                logger.warning("⚠️  For forwarded replies, pass lead_id (original recipient's email) to auto-lookup campaign")
                logger.warning("⚠️  If marking fails, ensure lead_id is provided from hidden gems output")

            result = mark_instantly_lead_as_interested(
                api_key=api_key,
                lead_email=lead_email,
                interest_value=interest_value,
                campaign_id=campaign_id,  # Pass campaign_id for proper association
                lead_id=lead_id  # Pass lead_id to look up campaign if needed
            )

            # Check if the result contains an error
            if "error" in result:
                logger.error("Failed to mark lead in Instantly: %s", result.get("error"))
                return json.dumps({
                    "success": False,
                    "platform": "instantly",
                    "client_name": client_name,
                    "lead_email": lead_email,
                    "error": result.get("error"),
                    "message": result.get("message", "Failed to mark lead"),
                    "suggestion": result.get("suggestion", "The lead may not exist in this Instantly workspace. This often happens with forwarded replies where the person who replied was never added as a lead.")
                }, indent=2)

            logger.info("Successfully marked lead as interested in Instantly: %s", lead_email)

            return json.dumps({
                "success": True,
                "platform": "instantly",
                "client_name": client_name,
                "lead_email": lead_email,
                "lead_id": lead_id,
                "interest_value": interest_value,
                "message": result.get("message", "Lead marked as interested"),
                "note": "Lead interest status update job submitted to Instantly"
            }, indent=2)

        # If not Instantly, try Bison
        bison_workspaces = load_bison_workspaces_from_sheet(
            sheet_url=config.lead_sheets_url,
            gid=config.lead_sheets_gid_bison
        )

        matching_bison_workspace = next(
            (w for w in bison_workspaces if w["client_name"].lower() == client_name.lower()),
            None
        )

        if matching_bison_workspace:
            # Use Bison API
            api_key = matching_bison_workspace["api_key"]

            # For Bison, we need a reply_id
            if not reply_id:
                return json.dumps({
                    "success": False,
                    "error": "Bison requires reply_id parameter. Please provide the reply ID to mark as interested.",
                    "platform": "bison",
                    "client_name": client_name,
                    "suggestion": "Use find_missed_opportunities() to get reply IDs, then pass the reply_id here"
                }, indent=2)

            result = mark_bison_reply_as_interested(
                api_key=api_key,
                reply_id=reply_id,
                skip_webhooks=True
            )

            logger.info("Successfully marked reply as interested in Bison: reply_id=%d, email=%s",
                       reply_id, lead_email)

            return json.dumps({
                "success": True,
                "platform": "bison",
                "client_name": client_name,
                "lead_email": lead_email,
                "reply_id": reply_id,
                "interested": result.get("data", {}).get("interested", True),
                "message": "Reply marked as interested in Bison",
                "note": "Lead status updated successfully"
            }, indent=2)

        # Client not found in either platform
        return json.dumps({
            "success": False,
            "error": f"Client '{client_name}' not found in Instantly or Bison workspaces.",
            "suggestion": "Check client name spelling or use get_instantly_clients() / get_bison_clients() to see available clients"
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error marking lead as interested: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_bison_clients() -> str:
    """
    Get list of all Bison clients.

    Returns all Bison clients with their client names.

    Returns:
        JSON string with client list
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching Bison client list...")

        result = get_bison_client_list(
            sheet_url=config.lead_sheets_url,
            gid=config.lead_sheets_gid_bison
        )

        logger.info("Found %d Bison clients", result.get('total_clients', 0))

        return json.dumps({
            "success": True,
            **result
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_bison_clients: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_bison_leads(
    client_name: str,
    days: int = 7,
    start_date: str = None,
    end_date: str = None
) -> str:
    """
    Get lead responses for a specific Bison client.

    This tool retrieves all lead responses (interested/replied leads) for a given
    Bison client within the specified time period.

    Args:
        client_name: Bison client name
        days: Number of days to look back (default: 7)
        start_date: Start date in YYYY-MM-DD format (optional, overrides days)
        end_date: End date in YYYY-MM-DD format (optional, overrides days)

    Returns:
        JSON string with lead responses
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching Bison leads for client %s (days=%d)...", client_name, days)

        result = get_bison_lead_responses(
            sheet_url=config.lead_sheets_url,
            gid=config.lead_sheets_gid_bison,
            client_name=client_name,
            days=days,
            start_date=start_date,
            end_date=end_date
        )

        logger.info("Found %d leads for client %s", result.get('total_leads', 0), client_name)

        return json.dumps({
            "success": True,
            **result
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_bison_leads: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_bison_stats(
    client_name: str,
    days: int = 7,
    start_date: str = None,
    end_date: str = None
) -> str:
    """
    Get campaign statistics for a specific Bison client.

    This tool retrieves comprehensive campaign statistics including sent emails,
    opens, replies, interested leads, and more for a given Bison client.

    Args:
        client_name: Bison client name
        days: Number of days to look back (default: 7)
        start_date: Start date in YYYY-MM-DD format (optional, overrides days)
        end_date: End date in YYYY-MM-DD format (optional, overrides days)

    Returns:
        JSON string with campaign statistics
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching Bison stats for client %s (days=%d)...", client_name, days)

        result = get_bison_campaign_stats(
            sheet_url=config.lead_sheets_url,
            gid=config.lead_sheets_gid_bison,
            client_name=client_name,
            days=days,
            start_date=start_date,
            end_date=end_date
        )

        logger.info("Retrieved stats for client %s: %d interested leads",
                   client_name, result.get('interested_leads', 0))

        return json.dumps({
            "success": True,
            **result
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_bison_stats: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_all_lead_clients() -> str:
    """
    Get list of all clients from both Instantly.ai and Bison platforms.

    Returns a comprehensive list of all clients across both lead generation
    platforms with their platform identifiers and client names.

    Returns:
        JSON string with all clients from both platforms
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching all clients from both platforms...")

        result = get_all_clients(
            sheet_url=config.lead_sheets_url,
            instantly_gid=config.lead_sheets_gid_instantly,
            bison_gid=config.lead_sheets_gid_bison
        )

        logger.info("Found %d total clients (%d Instantly, %d Bison)",
                   result.get('total_clients', 0),
                   result.get('instantly_count', 0),
                   result.get('bison_count', 0))

        return json.dumps({
            "success": True,
            **result
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_all_lead_clients: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_lead_platform_stats(days: int = 7) -> str:
    """
    Get aggregated statistics across both Instantly.ai and Bison platforms.

    This tool provides a high-level overview of lead generation performance
    across all clients and both platforms, including total leads, conversion
    rates, and platform comparisons.

    Args:
        days: Number of days to look back (default: 7)

    Returns:
        JSON string with aggregated platform statistics
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching platform stats for last %d days...", days)

        result = get_all_platform_stats(
            sheet_url=config.lead_sheets_url,
            instantly_gid=config.lead_sheets_gid_instantly,
            bison_gid=config.lead_sheets_gid_bison,
            days=days
        )

        logger.info("Retrieved platform stats: %d total interested leads",
                   result.get('total_interested_leads', 0))

        return json.dumps({
            "success": True,
            **result
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_lead_platform_stats: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_top_clients(
    limit: int = 10,
    metric: str = "interested_leads",
    days: int = 7
) -> str:
    """
    Get the top performing clients based on a specific metric.

    This tool ranks clients by performance metrics such as interested leads,
    reply rates, or open rates, helping identify the most successful campaigns.

    Args:
        limit: Maximum number of clients to return (default: 10)
        metric: Metric to rank by - "interested_leads", "replies", "opens",
                "sent", or "reply_rate" (default: "interested_leads")
        days: Number of days to look back (default: 7)

    Returns:
        JSON string with top performing clients
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching top %d clients by %s (last %d days)...", limit, metric, days)

        result = get_top_performing_clients(
            sheet_url=config.lead_sheets_url,
            instantly_gid=config.lead_sheets_gid_instantly,
            bison_gid=config.lead_sheets_gid_bison,
            limit=limit,
            metric=metric,
            days=days
        )

        logger.info("Found top %d clients by %s", len(result.get('clients', [])), metric)

        return json.dumps({
            "success": True,
            **result
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_top_clients: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_underperforming_clients_list(
    threshold: int = 5,
    metric: str = "interested_leads",
    days: int = 7
) -> str:
    """
    Get list of underperforming clients based on a specific metric threshold.

    This tool identifies clients that are performing below a specified threshold,
    helping to flag campaigns that may need attention or optimization.

    Args:
        threshold: Minimum acceptable value for the metric (default: 5)
        metric: Metric to evaluate - "interested_leads", "replies", "opens",
                or "sent" (default: "interested_leads")
        days: Number of days to look back (default: 7)

    Returns:
        JSON string with underperforming clients
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Fetching underperforming clients (threshold=%d %s, last %d days)...",
                   threshold, metric, days)

        result = get_underperforming_clients(
            sheet_url=config.lead_sheets_url,
            instantly_gid=config.lead_sheets_gid_instantly,
            bison_gid=config.lead_sheets_gid_bison,
            threshold=threshold,
            metric=metric,
            days=days
        )

        logger.info("Found %d underperforming clients", len(result.get('clients', [])))

        return json.dumps({
            "success": True,
            **result
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_underperforming_clients_list: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def get_lead_weekly_summary() -> str:
    """
    Get a comprehensive weekly summary of lead generation activities.

    This tool provides a high-level weekly report including total leads generated,
    top performing clients, platform comparisons, and key metrics across all
    campaigns for the past 7 days.

    Returns:
        JSON string with weekly summary
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        logger.info("Generating weekly lead summary...")

        result = get_weekly_summary(
            sheet_url=config.lead_sheets_url,
            instantly_gid=config.lead_sheets_gid_instantly,
            bison_gid=config.lead_sheets_gid_bison
        )

        logger.info("Generated weekly summary: %d total leads",
                   result.get('total_leads', 0))

        return json.dumps({
            "success": True,
            **result
        }, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in get_lead_weekly_summary: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


# ============================================================================
# CAMPAIGN AUTOMATION TOOLS
# ============================================================================

def convert_to_bison_placeholders(text: str) -> str:
    """
    Convert Instantly-style placeholders to Bison format.
    {{first_name}} → {FIRST_NAME}
    {{last_name}} → {LAST_NAME}
    {{company}} → {COMPANY_NAME}
    {{title}} → {TITLE}
    """
    import re

    # Map of Instantly → Bison placeholders
    # Includes all common variations (camelCase, snake_case, no separator)
    replacements = {
        r'\{\{first_name\}\}': '{FIRST_NAME}',
        r'\{\{firstName\}\}': '{FIRST_NAME}',
        r'\{\{firstname\}\}': '{FIRST_NAME}',  # No underscore
        r'\{\{last_name\}\}': '{LAST_NAME}',
        r'\{\{lastName\}\}': '{LAST_NAME}',
        r'\{\{lastname\}\}': '{LAST_NAME}',  # No underscore
        r'\{\{company\}\}': '{COMPANY_NAME}',
        r'\{\{company_name\}\}': '{COMPANY_NAME}',
        r'\{\{companyName\}\}': '{COMPANY_NAME}',
        r'\{\{companyname\}\}': '{COMPANY_NAME}',  # No separator
        r'\{\{title\}\}': '{TITLE}',
        r'\{\{job_title\}\}': '{TITLE}',
        r'\{\{jobTitle\}\}': '{TITLE}',
        r'\{\{jobtitle\}\}': '{TITLE}',  # No underscore
        r'\{\{email\}\}': '{EMAIL}',
    }

    result = text
    for pattern, replacement in replacements.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


def convert_to_instantly_placeholders(text: str) -> str:
    """
    Convert Bison-style placeholders to Instantly format.
    {FIRST_NAME} → {{first_name}}
    {LAST_NAME} → {{last_name}}
    {COMPANY_NAME} → {{company}}
    {TITLE} → {{title}}
    """
    import re

    # Map of Bison → Instantly placeholders
    # Use word boundaries and uppercase patterns to avoid re-matching converted placeholders
    replacements = [
        (r'\{COMPANY[_\s]NAME\}', '{{company}}'),
        (r'\{JOB[_\s]TITLE\}', '{{title}}'),
        (r'\{FIRST[_\s]NAME\}', '{{first_name}}'),
        (r'\{LAST[_\s]NAME\}', '{{last_name}}'),
        (r'\{COMPANY\}', '{{company}}'),
        (r'\{TITLE\}', '{{title}}'),
        (r'\{EMAIL\}', '{{email}}'),
    ]

    result = text
    for pattern, replacement in replacements:
        # Only match uppercase Bison-style placeholders (no IGNORECASE to avoid re-matching)
        result = re.sub(pattern, replacement, result)

    return result


@mcp.tool()
async def create_bison_sequence(
    client_name: str,
    sequence_title: str,
    steps: list,
    campaign_id: int = None,
    campaign_name: str = None
) -> str:
    """
    Upload/create email sequence steps for a Bison campaign.

    If no campaign_id is provided, creates a new campaign automatically.
    Use this to automate sequence creation instead of manually copying sequences.
    Each step can have subject, body, wait time, and thread reply settings.

    IMPORTANT - A/B Testing / Email Variations:
    Bison DOES support A/B test variants! Use the variant and variant_from_step parameters
    to create multiple variations in a SINGLE campaign for testing different copy.

    How variants work:
    - Set variant=true and variant_from_step=ORDER_NUMBER to create a variant
    - variant_from_step references the "order" field of the base step
    - All variants of the same step are A/B tested against each other

    Example: To A/B test 3 subject line variations in ONE campaign:
      ✅ CORRECT: Create ONE campaign with 3 variant steps:
      steps = [
        {
          "order": 1,
          "email_subject": "quick question",
          "email_body": "...",
          "wait_in_days": 1,
          "variant": false  # Base version
        },
        {
          "order": 2,
          "email_subject": "speaking question",  # Different subject!
          "email_body": "...",
          "wait_in_days": 1,
          "variant": true,
          "variant_from_step": 1  # This is a variant of order=1
        },
        {
          "order": 3,
          "email_subject": "quick question for you",  # Another variant!
          "email_body": "...",
          "wait_in_days": 1,
          "variant": true,
          "variant_from_step": 1  # Also a variant of order=1
        }
      ]

      ❌ INCORRECT: Creating 3 separate campaigns for A/B testing
         - This creates 3 campaigns instead of 1 campaign with 3 variants

    Args:
        client_name: Name of the Bison client (e.g., 'Jeff Mikolai')
        sequence_title: Title for the sequence (e.g., 'Cold Outreach v2')
        steps: Array of email sequence steps. Each step should have:
            - email_subject: Subject line
            - email_body: Email body content
            - order: Step order (1, 2, 3, etc.) - REQUIRED for variant_from_step to work
            - wait_in_days: Days to wait before sending (optional, smart defaults: step 1=1 day, step 2=3 days, step 3=5 days, step 4+=7 days)
            - thread_reply: Whether to reply in same thread (default: false)
            - variant: Whether this is a variant (default: false)
            - variant_from_step: Order number of the step to be a variant of (e.g., 1)
        campaign_id: The Bison campaign ID to add sequences to (optional - if not provided, creates a new campaign)
        campaign_name: Campaign name (required if campaign_id not provided, e.g., 'Speaker Outreach 2025')

    Returns:
        JSON string with creation result
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        from leads import sheets_client, bison_client

        logger.info("Creating Bison sequence for client '%s'...", client_name)

        # Get client's API key from sheet
        workspaces = await asyncio.to_thread(
            sheets_client.load_bison_workspaces_from_sheet,
            config.lead_sheets_url,
            config.lead_sheets_gid_bison
        )

        # Find workspace by client name using fuzzy matching
        from rapidfuzz import fuzz, process

        workspace = None
        if workspaces:
            # Get all client names
            client_names = [ws["client_name"] for ws in workspaces]

            # Find best match using fuzzy matching
            # extractOne returns (match, score, index)
            result = process.extractOne(
                client_name,
                client_names,
                scorer=fuzz.WRatio,  # Weighted ratio for better matching
                score_cutoff=60  # Minimum 60% similarity
            )

            if result:
                matched_name, score, index = result
                workspace = workspaces[index]
                logger.info("Matched '%s' to '%s' (score: %d%%)", client_name, matched_name, score)
            else:
                logger.warning("No match found for '%s' (tried %d clients)", client_name, len(workspaces))

        if not workspace:
            return json.dumps({
                "success": False,
                "error": f"Client '{client_name}' not found in Bison clients list. Available clients: {', '.join([ws['client_name'] for ws in workspaces[:5]])}..."
            }, indent=2)

        # Get or create campaign
        created_campaign = False
        if not campaign_id:
            # Create new campaign
            if not campaign_name:
                campaign_name = sequence_title

            logger.info("Creating new Bison campaign '%s'...", campaign_name)
            campaign_result = await asyncio.to_thread(
                bison_client.create_bison_campaign_api,
                api_key=workspace["api_key"],
                name=campaign_name,
                campaign_type="outbound"
            )
            campaign_id = campaign_result['data']['id']
            created_campaign = True
            logger.info("Created campaign ID: %d", campaign_id)

        # Set smart defaults for wait_in_days based on step position
        # Pattern: Step 1=1 day (API minimum), Step 2=3 days, Step 3=5 days, Step 4+=7 days
        # Also convert placeholder variables to Bison format
        for idx, step in enumerate(steps):
            if 'wait_in_days' not in step or step['wait_in_days'] < 1:
                # Smart defaults based on step position (not including variants)
                if idx == 0:
                    step['wait_in_days'] = 1  # First step: 1 day (API minimum)
                elif idx == 1:
                    step['wait_in_days'] = 3  # Second step: 3 days
                elif idx == 2:
                    step['wait_in_days'] = 5  # Third step: 5 days
                else:
                    step['wait_in_days'] = 7  # Fourth+ step: 7 days

            # Convert placeholders to Bison format: {{first_name}} → {FIRST_NAME}
            if 'email_subject' in step:
                original_subject = step['email_subject']

                # Handle empty subjects for thread replies
                if not original_subject and step.get('thread_reply', False):
                    # Bison API requires non-empty subject, use placeholder for thread replies
                    step['email_subject'] = 'Re:'
                    logger.info("Thread reply with empty subject, using 'Re:' placeholder")
                else:
                    step['email_subject'] = convert_to_bison_placeholders(step['email_subject'])
                    if original_subject != step['email_subject']:
                        logger.info(f"Converted subject: '{original_subject}' → '{step['email_subject']}'")
            if 'email_body' in step:
                original_body = step['email_body']
                step['email_body'] = convert_to_bison_placeholders(step['email_body'])
                if original_body != step['email_body']:
                    logger.info(f"Converted body: '{original_body[:50]}...' → '{step['email_body'][:50]}...'")

        # Create the sequence
        logger.info("Creating sequence with %d steps...", len(steps))
        result = await asyncio.to_thread(
            bison_client.create_bison_sequence_api,
            api_key=workspace["api_key"],
            campaign_id=campaign_id,
            title=sequence_title,
            sequence_steps=steps
        )

        response = {
            "success": True,
            "message": f"Successfully created sequence '{sequence_title}' with {len(steps)} steps",
            "client_name": workspace["client_name"],
            "campaign_id": campaign_id,
            "sequence_id": result['data']['id'],
            "steps_created": len(result['data']['sequence_steps'])
        }

        if created_campaign:
            response["campaign_created"] = True
            response["campaign_name"] = campaign_name

        logger.info("Bison sequence created successfully")

        return json.dumps(response, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in create_bison_sequence: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def create_instantly_campaign(
    client_name: str,
    campaign_name: str,
    steps: list,
    email_accounts: list = None,
    daily_limit: int = 50,
    timezone: str = "America/Chicago",
    schedule_from: str = "09:00",
    schedule_to: str = "17:00",
    stop_on_reply: bool = True,
    text_only: bool = False
) -> str:
    """
    Create an Instantly.ai campaign with email sequences.

    Automatically sets up campaign with scheduling, tracking, and sequences.
    Use this to automate campaign creation instead of manually setting up in Instantly UI.

    Args:
        client_name: Name of the Instantly client (e.g., 'Jeff Mikolai')
        campaign_name: Campaign name (e.g., 'Speaker Outreach 2025')
        steps: Array of email sequence steps (1-3 steps typically). Each step should have:
            - subject: Email subject line
            - body: Email body content. IMPORTANT: Use \\n for line breaks between paragraphs.
              Example: "Hey {{first_name}},\\n\\nI noticed...\\n\\nBest,\\nMike"
            - wait: Hours to wait before sending (optional, smart defaults: step 1=0 hrs, step 2=72 hrs (3 days), step 3=120 hrs (5 days), step 4+=168 hrs (7 days))
            - variants: Optional array of A/B test variants, each with subject and body
        email_accounts: List of email addresses to send from (optional)
        daily_limit: Daily sending limit per account (default: 50)
        timezone: Timezone for schedule (default: 'America/Chicago'). Must be exact timezone from Instantly API.
            Valid options include: America/Chicago, America/Detroit, America/Boise, Asia/Tokyo, Europe/London, etc.
        schedule_from: Start time HH:MM (default: '09:00')
        schedule_to: End time HH:MM (default: '17:00')
        stop_on_reply: Stop campaign when lead replies (default: True)
        text_only: Send all emails as text only (default: False)

    Returns:
        JSON string with creation result
    """
    try:
        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        from leads import sheets_client, instantly_client

        logger.info("Creating Instantly campaign '%s' for client '%s'...", campaign_name, client_name)

        # Get client's API key from sheet
        workspaces = await asyncio.to_thread(
            sheets_client.load_instantly_workspaces_from_sheet,
            config.lead_sheets_url,
            config.lead_sheets_gid_instantly
        )

        # Find workspace by client name using fuzzy matching
        from rapidfuzz import fuzz, process

        workspace = None
        if workspaces:
            # Get all client names
            client_names = [ws["client_name"] for ws in workspaces]

            # Find best match using fuzzy matching
            result = process.extractOne(
                client_name,
                client_names,
                scorer=fuzz.WRatio,
                score_cutoff=60  # Minimum 60% similarity
            )

            if result:
                matched_name, score, index = result
                workspace = workspaces[index]
                logger.info("Matched '%s' to '%s' (score: %d%%)", client_name, matched_name, score)
            else:
                logger.warning("No match found for '%s' (tried %d clients)", client_name, len(workspaces))

        if not workspace:
            return json.dumps({
                "success": False,
                "error": f"Client '{client_name}' not found in Instantly clients list. Available clients: {', '.join([ws['client_name'] for ws in workspaces[:5]])}..."
            }, indent=2)

        # Auto-format email bodies that are missing line breaks
        def auto_format_email_body(body: str) -> str:
            """Add line breaks to email body if missing."""
            if not body:
                return body

            # Check if body already has newlines
            if '\n' in body:
                logger.info("[Instantly] Body already has newlines, keeping as-is")
                return body

            import re

            logger.info("[Instantly] Body has no newlines, adding auto-formatting...")
            logger.info("[Instantly] Original body: %s", body[:80])

            # Add double newline before common email closings
            closings = ['Best,', 'Thanks,', 'Regards,', 'Sincerely,', 'Cheers,']
            for closing in closings:
                if f' {closing}' in body:
                    body = body.replace(f' {closing}', f'\n\n{closing}')
                    logger.info("[Instantly] Added newline before '%s'", closing)

            # Add double newline after sentence endings followed by capital letter
            # This catches paragraph breaks like: "...referrals. Asking because..."
            body = re.sub(r'([.!?]) ([A-Z])', r'\1\n\n\2', body)

            newline_count = body.count('\n')
            logger.info("[Instantly] Formatted body now has %d newlines", newline_count)
            logger.info("[Instantly] Formatted body preview: %s", body[:80])

            return body

        # Set smart defaults for wait time based on step position
        # Pattern: Step 1=0 hours, Step 2=72 hours (3 days), Step 3=120 hours (5 days), Step 4+=168 hours (7 days)
        # Convert placeholders to Instantly format: {FIRST_NAME} → {{first_name}}
        for idx, step in enumerate(steps):
            # Set default wait times if not specified
            if 'wait' not in step:
                if idx == 0:
                    step['wait'] = 0  # First email: immediate
                elif idx == 1:
                    step['wait'] = 72  # Second email: 3 days (72 hours)
                elif idx == 2:
                    step['wait'] = 120  # Third email: 5 days (120 hours)
                else:
                    step['wait'] = 168  # Fourth+ email: 7 days (168 hours)

            # Auto-format body if needed
            if 'body' in step:
                original_body = step['body']
                step['body'] = auto_format_email_body(step['body'])
                if original_body != step['body']:
                    logger.info("[Instantly] ✓ Auto-formatting applied to email body")
            if 'subject' in step:
                original = step['subject']
                step['subject'] = convert_to_instantly_placeholders(step['subject'])
                if original != step['subject']:
                    logger.info(f"Converted subject: '{original}' → '{step['subject']}'")
            if 'body' in step:
                original = step['body']
                step['body'] = convert_to_instantly_placeholders(step['body'])
                if original != step['body']:
                    logger.info(f"Converted body: '{original[:50]}...' → '{step['body'][:50]}...'")

            # Also convert in variants if present
            if 'variants' in step and step['variants']:
                for variant in step['variants']:
                    if 'subject' in variant:
                        original = variant['subject']
                        variant['subject'] = convert_to_instantly_placeholders(variant['subject'])
                        if original != variant['subject']:
                            logger.info(f"Converted variant subject: '{original}' → '{variant['subject']}'")
                    if 'body' in variant:
                        original = variant['body']
                        variant['body'] = convert_to_instantly_placeholders(variant['body'])
                        if original != variant['body']:
                            logger.info(f"Converted variant body: '{original[:50]}...' → '{variant['body'][:50]}...'")

        # Create the campaign with sequences
        logger.info("Creating campaign with %d steps...", len(steps))
        result = await asyncio.to_thread(
            instantly_client.create_instantly_campaign_api,
            api_key=workspace["api_key"],
            name=campaign_name,
            sequence_steps=steps,
            email_accounts=email_accounts,
            daily_limit=daily_limit,
            timezone=timezone,
            schedule_from=schedule_from,
            schedule_to=schedule_to,
            stop_on_reply=stop_on_reply,
            text_only=text_only
        )

        response = {
            "success": True,
            "message": f"Successfully created campaign '{campaign_name}' with {len(steps)} steps",
            "client_name": workspace["client_name"],
            "campaign_id": result.get('id'),
            "campaign_name": result.get('name'),
            "steps_created": len(steps),
            "timezone": timezone,
            "schedule": f"{schedule_from} - {schedule_to}"
        }

        logger.info("Instantly campaign created successfully")

        return json.dumps(response, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in create_instantly_campaign: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def check_text_spam(
    subject: str = "",
    body: str = ""
) -> str:
    """
    Check any email text for spam without creating a campaign (ad-hoc spam checking).

    Perfect for:
    - Pre-writing campaign copy review
    - A/B testing subject line variations
    - Checking draft email content before sending
    - Competitive analysis of forwarded emails

    Args:
        subject: Email subject line to check (optional)
        body: Email body content to check (optional)

    Returns:
        JSON string with spam analysis:
        - is_spam: Whether content is flagged as spam
        - spam_score: Numeric spam score (higher = more spammy)
        - spam_words: List of spam trigger words found
        - number_of_spam_words: Count of spam words

    Example Usage:
        - "Check this subject line for spam: Get 100% FREE money now!"
        - "Is this email body spammy? [paste email content]"
        - "Check both subject and body for spam triggers"
    """
    try:
        # Get EmailGuard API key from environment
        emailguard_key = os.environ.get('EMAILGUARD_API_KEY')
        if not emailguard_key:
            return json.dumps({
                "success": False,
                "error": "EmailGuard API key not configured. Please set EMAILGUARD_API_KEY environment variable."
            }, indent=2)

        if not subject and not body:
            return json.dumps({
                "success": False,
                "error": "Please provide either a subject line or email body to check."
            }, indent=2)

        from leads import spam_checker

        # Check the text
        result = await asyncio.to_thread(
            spam_checker.check_text_spam,
            emailguard_key,
            subject=subject,
            body=body
        )

        if "error" in result:
            return json.dumps({
                "success": False,
                "error": result["error"]
            }, indent=2)

        # Build response
        response = {
            "success": True,
            "result": result,
            "summary": f"{'⚠️ SPAM DETECTED' if result['is_spam'] else '✅ CLEAN'} - Score: {result['spam_score']:.2f}"
        }

        if result['spam_words']:
            response["spam_triggers"] = result['spam_words']

        return json.dumps(response, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in check_text_spam: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


@mcp.tool()
async def check_campaign_spam(
    client_name: str = None,
    platform: str = "bison",
    status: str = "active"
) -> str:
    """
    Check active campaigns for spam content using EmailGuard API.

    Scans all email sequences (subject lines and bodies) from Bison or Instantly campaigns
    and identifies spam words, spam scores, and potential deliverability issues.

    Args:
        client_name: Optional specific client to check (uses fuzzy matching). If not provided, checks all clients.
        platform: Platform to check - "bison" or "instantly" (default: "bison")
        status: Campaign status to filter - "active", "launching", "draft", etc. (default: "active")

    Returns:
        JSON string with spam analysis:
        - total_clients: Number of clients checked
        - total_campaigns: Number of campaigns checked
        - spam_campaigns: Number of campaigns with spam issues
        - clients: Array of client results with campaigns and spam details

    Example Usage:
        - "Check spam for all active Bison campaigns"
        - "Check spam for Michael Hernandez's draft campaigns"
        - "Scan Brian Bliss's launching campaigns for spam words"
        - "Check all Jeff's campaigns regardless of status"
    """
    try:
        # Get EmailGuard API key from environment
        emailguard_key = os.environ.get('EMAILGUARD_API_KEY')
        if not emailguard_key:
            return json.dumps({
                "success": False,
                "error": "EmailGuard API key not configured. Please set EMAILGUARD_API_KEY environment variable."
            }, indent=2)

        if not config.lead_sheets_url:
            return json.dumps({
                "success": False,
                "error": "Lead management not configured. Please set LEAD_SHEETS_URL in your environment."
            }, indent=2)

        from leads import spam_checker

        logger.info("Checking campaign spam for platform: %s, status: %s, client: %s",
                   platform, status, client_name or "all")

        # Check campaigns based on platform
        if platform.lower() == "bison":
            results = await asyncio.to_thread(
                spam_checker.check_all_bison_campaigns_spam,
                emailguard_key,
                status=status,
                client_name=client_name
            )
        elif platform.lower() == "instantly":
            results = await asyncio.to_thread(
                spam_checker.check_all_instantly_campaigns_spam,
                emailguard_key,
                status=status,
                client_name=client_name
            )
        else:
            return json.dumps({
                "success": False,
                "error": f"Platform '{platform}' not supported. Please use 'bison' or 'instantly'."
            }, indent=2)

        # Add summary
        response = {
            "success": True,
            "platform": platform,
            "status_filter": status,
            "summary": {
                "total_clients": results["total_clients"],
                "total_campaigns": results["total_campaigns"],
                "spam_campaigns": results["spam_campaigns"],
                "clean_campaigns": results["total_campaigns"] - results["spam_campaigns"]
            },
            "results": results
        }

        logger.info("Spam check complete: %d campaigns checked, %d with spam issues",
                   results["total_campaigns"], results["spam_campaigns"])

        return json.dumps(response, indent=2)

    except Exception as e:
        error_msg = str(e)
        logger.error("Error in check_campaign_spam: %s", error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg
        }, indent=2)


def main():
    """Main entry point for MCP server."""
    try:
        logger.info("Starting Gmail & Calendar MCP Server...")

        # Initialize clients at startup
        initialize_clients()

        logger.info("MCP server ready")

        # Run MCP server using FastMCP's built-in run method
        mcp.run()

    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error("Server error: %s", str(e))
        raise


if __name__ == "__main__":
    main()
