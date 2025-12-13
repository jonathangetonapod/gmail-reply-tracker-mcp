#!/usr/bin/env python3
"""Gmail Reply Tracker MCP Server."""

import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from mcp.server.fastmcp import FastMCP
from googleapiclient.errors import HttpError

from config import Config
from auth import GmailAuthManager
from gmail_client import GmailClient
from email_analyzer import EmailAnalyzer
from calendar_client import CalendarClient


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


def initialize_clients():
    """Initialize Gmail and Calendar clients."""
    global auth_manager, gmail_client, email_analyzer, calendar_client

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
        time_min = datetime.now()
        time_max = time_min + timedelta(days=days_ahead)

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
    time_zone: str = 'UTC'
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
        time_zone: Time zone (default: 'UTC')

    Returns:
        JSON string with created event details
    """
    try:
        initialize_clients()

        logger.info("Creating calendar event: %s", summary)

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
    time_zone: str = 'UTC'
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
        time_zone: Time zone (default: 'UTC')

    Returns:
        JSON string with updated event details
    """
    try:
        initialize_clients()

        logger.info("Updating calendar event: %s", event_id)

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
