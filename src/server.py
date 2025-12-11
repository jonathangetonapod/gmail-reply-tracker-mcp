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


def initialize_clients():
    """Initialize Gmail client and analyzer."""
    global auth_manager, gmail_client, email_analyzer

    if gmail_client is not None:
        return

    logger.info("Initializing Gmail client...")

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

    logger.info("Gmail client initialized successfully")


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


def main():
    """Main entry point for MCP server."""
    try:
        logger.info("Starting Gmail Reply Tracker MCP Server...")

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
