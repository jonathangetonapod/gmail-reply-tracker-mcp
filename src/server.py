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
fathom_client: Optional[FathomClient] = None


def initialize_clients():
    """Initialize Gmail, Calendar, and Fathom clients."""
    global auth_manager, gmail_client, email_analyzer, calendar_client, fathom_client

    if gmail_client is not None and calendar_client is not None:
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
        thread_infos = gmail_client.list_threads(query, max_results * 2)

        # Get user email
        user_email = gmail_client.get_user_email()

        # Process threads
        unreplied = []
        for thread_info in thread_infos:
            if len(unreplied) >= max_results:
                break

            # Fetch full thread
            thread = gmail_client.get_thread(thread_info['id'])

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

        # Fetch message details
        results = []
        for msg_info in message_infos:
            msg = gmail_client.get_message(msg_info['id'])

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
        result_json = await get_unreplied_emails(days_back=30, max_results=100, exclude_automated=True)
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

        # Filter for unreplied
        unreplied = []

        for msg_info in message_infos:
            # Get full thread
            thread = gmail_client.get_thread(msg_info['threadId'])

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
    time_zone: str = None
) -> str:
    """
    Create a new calendar event.

    Args:
        summary: Event title
        start_time: Event start time (ISO 8601 format: YYYY-MM-DDTHH:MM:SS)
        end_time: Event end time (ISO 8601 format: YYYY-MM-DDTHH:MM:SS)
        calendar_id: Calendar ID (default: 'primary')
        description: Event description
        location: Event location
        attendees: Comma-separated list of attendee emails
        time_zone: Time zone (default: auto-detect from system, or 'America/Bogota')

    Returns:
        JSON string with created event details
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

        # Create event
        event = calendar_client.create_event(
            summary=summary,
            start_time=start_dt,
            end_time=end_dt,
            calendar_id=calendar_id,
            description=description,
            location=location,
            attendees=attendee_list,
            time_zone=time_zone
        )

        logger.info("Created event: %s (ID: %s)", summary, event['id'])

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
    replacements = {
        r'\{\{first_name\}\}': '{FIRST_NAME}',
        r'\{\{firstName\}\}': '{FIRST_NAME}',
        r'\{\{last_name\}\}': '{LAST_NAME}',
        r'\{\{lastName\}\}': '{LAST_NAME}',
        r'\{\{company\}\}': '{COMPANY_NAME}',
        r'\{\{company_name\}\}': '{COMPANY_NAME}',
        r'\{\{companyName\}\}': '{COMPANY_NAME}',
        r'\{\{title\}\}': '{TITLE}',
        r'\{\{job_title\}\}': '{TITLE}',
        r'\{\{jobTitle\}\}': '{TITLE}',
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

    Args:
        client_name: Name of the Bison client (e.g., 'Jeff Mikolai')
        sequence_title: Title for the sequence (e.g., 'Cold Outreach v2')
        steps: Array of email sequence steps (1-3 steps typically). Each step should have:
            - email_subject: Subject line
            - email_body: Email body content
            - order: Step order (1, 2, 3, etc.)
            - wait_in_days: Days to wait before sending (minimum: 1, default: 3 if not specified)
            - thread_reply: Whether to reply in same thread (default: false)
            - variant: Whether this is a variant (default: false)
            - variant_from_step: Which step this is a variant of (if variant=true)
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

        # Find workspace by client name
        workspace = None
        search_term = client_name.lower()
        for ws in workspaces:
            if search_term in ws["client_name"].lower():
                workspace = ws
                break

        if not workspace:
            return json.dumps({
                "success": False,
                "error": f"Client '{client_name}' not found in Bison clients list"
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

        # Ensure all steps have wait_in_days >= 1 (API requirement), default to 3
        # Also convert placeholder variables to Bison format
        for step in steps:
            if 'wait_in_days' not in step or step['wait_in_days'] < 1:
                step['wait_in_days'] = 3  # Default to 3 days

            # Convert placeholders to Bison format: {{first_name}} → {FIRST_NAME}
            if 'email_subject' in step:
                step['email_subject'] = convert_to_bison_placeholders(step['email_subject'])
            if 'email_body' in step:
                step['email_body'] = convert_to_bison_placeholders(step['email_body'])

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
            - body: Email body content
            - wait: Hours to wait before sending (for follow-ups, first email is 0)
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

        # Find workspace by client name
        workspace = None
        search_term = client_name.lower()
        for ws in workspaces:
            if search_term in ws["client_name"].lower():
                workspace = ws
                break

        if not workspace:
            return json.dumps({
                "success": False,
                "error": f"Client '{client_name}' not found in Instantly clients list"
            }, indent=2)

        # Convert placeholders to Instantly format: {FIRST_NAME} → {{first_name}}
        for step in steps:
            if 'subject' in step:
                step['subject'] = convert_to_instantly_placeholders(step['subject'])
            if 'body' in step:
                step['body'] = convert_to_instantly_placeholders(step['body'])

            # Also convert in variants if present
            if 'variants' in step and step['variants']:
                for variant in step['variants']:
                    if 'subject' in variant:
                        variant['subject'] = convert_to_instantly_placeholders(variant['subject'])
                    if 'body' in variant:
                        variant['body'] = convert_to_instantly_placeholders(variant['body'])

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
