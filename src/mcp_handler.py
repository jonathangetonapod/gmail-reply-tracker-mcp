#!/usr/bin/env python3
"""HTTP MCP Handler for multi-tenant server."""

import json
import logging
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime

from mcp.server.fastmcp import FastMCP
from google.oauth2.credentials import Credentials

from gmail_client import GmailClient
from calendar_client import CalendarClient
from fathom_client import FathomClient
from email_analyzer import EmailAnalyzer

logger = logging.getLogger(__name__)


class MCPHandler:
    """Handles MCP protocol over HTTP with per-user credentials."""

    def __init__(self):
        """Initialize the MCP handler."""
        self.mcp = FastMCP("gmail-calendar-fathom-multi-tenant")
        self._register_tools()

    def _register_tools(self):
        """Register all MCP tools."""
        # Import and register tools from server.py
        # We'll do this dynamically to avoid code duplication
        pass

    async def create_user_clients(
        self,
        google_token: Dict[str, Any],
        fathom_key: Optional[str] = None
    ) -> tuple:
        """
        Create Gmail, Calendar, and Fathom clients for a user.

        Args:
            google_token: Google OAuth token dictionary
            fathom_key: Optional Fathom API key

        Returns:
            Tuple of (gmail_client, calendar_client, fathom_client, email_analyzer)
        """
        # Create credentials from token
        credentials = Credentials(
            token=google_token.get('token'),
            refresh_token=google_token.get('refresh_token'),
            token_uri=google_token.get('token_uri'),
            client_id=google_token.get('client_id'),
            client_secret=google_token.get('client_secret'),
            scopes=google_token.get('scopes', [])
        )

        # Set expiry if present
        if google_token.get('expiry'):
            credentials.expiry = datetime.fromisoformat(google_token['expiry'])

        # Initialize clients
        gmail_client = GmailClient(credentials)
        calendar_client = CalendarClient(credentials)
        email_analyzer = EmailAnalyzer()
        fathom_client = FathomClient(fathom_key) if fathom_key else None

        return gmail_client, calendar_client, fathom_client, email_analyzer

    async def handle_request(
        self,
        request_data: Dict[str, Any],
        google_token: Dict[str, Any],
        fathom_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Handle an MCP request with user-specific credentials.

        Args:
            request_data: MCP request JSON
            google_token: User's Google OAuth token
            fathom_key: User's Fathom API key

        Returns:
            MCP response JSON
        """
        try:
            # Log incoming request
            logger.info(f"Received MCP request: {json.dumps(request_data)}")

            # Create clients for this user
            gmail, calendar, fathom, analyzer = await self.create_user_clients(
                google_token, fathom_key
            )

            # Handle MCP protocol
            method = request_data.get('method')
            params = request_data.get('params', {})

            response = None
            if method == 'initialize':
                response = await self._handle_initialize(request_data)
            elif method == 'tools/list':
                response = await self._handle_tools_list(request_data)
            elif method == 'tools/call':
                response = await self._handle_tool_call(
                    request_data, gmail, calendar, fathom, analyzer
                )
            else:
                request_id = request_data.get('id', 1)
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id if request_id is not None else 1,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                }

            # Log outgoing response
            logger.info(f"Sending MCP response: {json.dumps(response)}")
            return response

        except Exception as e:
            logger.error(f"Error handling MCP request: {e}", exc_info=True)
            request_id = request_data.get('id', 1)  # Default to 1 if no id
            return {
                "jsonrpc": "2.0",
                "id": request_id if request_id is not None else 1,
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}"
                }
            }

    async def _handle_initialize(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        request_id = request_data.get('id', 1)
        return {
            "jsonrpc": "2.0",
            "id": request_id if request_id is not None else 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "gmail-calendar-fathom-multi-tenant",
                    "version": "1.0.0"
                },
                "capabilities": {
                    "tools": {}
                }
            }
        }

    async def _handle_tools_list(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP tools/list request."""
        # Define all available tools
        tools = [
            {
                "name": "get_unreplied_emails",
                "description": "Get emails that haven't been replied to within a specified time period",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "days_back": {"type": "number", "description": "Number of days to look back"},
                        "max_results": {"type": "number", "description": "Maximum number of results"}
                    }
                }
            },
            {
                "name": "get_email_thread",
                "description": "Get the complete conversation history for an email thread",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "thread_id": {"type": "string", "description": "Thread ID"}
                    },
                    "required": ["thread_id"]
                }
            },
            {
                "name": "search_emails",
                "description": "Search emails using Gmail query syntax",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Gmail search query"},
                        "max_results": {"type": "number", "description": "Maximum results"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "send_email",
                "description": "Send a new email",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                        "cc": {"type": "string"},
                        "bcc": {"type": "string"}
                    },
                    "required": ["to", "subject", "body"]
                }
            },
            {
                "name": "reply_to_email",
                "description": "Reply to an email thread",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "thread_id": {"type": "string"},
                        "body": {"type": "string"}
                    },
                    "required": ["thread_id", "body"]
                }
            },
            {
                "name": "list_calendar_events",
                "description": "List upcoming calendar events",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "calendar_id": {"type": "string"},
                        "days_ahead": {"type": "number"}
                    }
                }
            },
            {
                "name": "create_calendar_event",
                "description": "Create a new calendar event",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "start_time": {"type": "string"},
                        "end_time": {"type": "string"},
                        "description": {"type": "string"},
                        "location": {"type": "string"},
                        "attendees": {"type": "string"}
                    },
                    "required": ["summary", "start_time"]
                }
            },
            {
                "name": "list_fathom_meetings",
                "description": "List recent Fathom meeting recordings with details",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "number", "description": "Maximum number of meetings to return"},
                        "calendar_invitees_domains_type": {"type": "string", "description": "Filter: all, internal_only, or one_or_more_external"}
                    }
                }
            },
            {
                "name": "get_fathom_transcript",
                "description": "Get the full transcript of a Fathom meeting recording",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "recording_id": {"type": "number", "description": "Fathom recording ID"}
                    },
                    "required": ["recording_id"]
                }
            },
            {
                "name": "get_fathom_summary",
                "description": "Get AI-generated summary and action items from a Fathom meeting",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "recording_id": {"type": "number", "description": "Fathom recording ID"}
                    },
                    "required": ["recording_id"]
                }
            },
            {
                "name": "search_fathom_meetings_by_title",
                "description": "Search Fathom meetings by title/topic",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "search_term": {"type": "string", "description": "Search term for meeting title"},
                        "limit": {"type": "number", "description": "Maximum results"}
                    },
                    "required": ["search_term"]
                }
            },
            {
                "name": "search_fathom_meetings_by_attendee",
                "description": "Search Fathom meetings by attendee name or email",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "attendee": {"type": "string", "description": "Attendee name or email to search for"},
                        "limit": {"type": "number", "description": "Maximum results"}
                    },
                    "required": ["attendee"]
                }
            }
        ]

        request_id = request_data.get('id', 1)
        return {
            "jsonrpc": "2.0",
            "id": request_id if request_id is not None else 1,
            "result": {
                "tools": tools
            }
        }

    async def _handle_tool_call(
        self,
        request_data: Dict[str, Any],
        gmail_client: GmailClient,
        calendar_client: CalendarClient,
        fathom_client: Optional[FathomClient],
        email_analyzer: EmailAnalyzer
    ) -> Dict[str, Any]:
        """Handle MCP tools/call request."""
        params = request_data.get('params', {})
        tool_name = params.get('name')
        arguments = params.get('arguments', {})

        try:
            # Call the appropriate tool
            if tool_name == 'get_unreplied_emails':
                result = await self._get_unreplied_emails(
                    gmail_client, email_analyzer, **arguments
                )
            elif tool_name == 'get_email_thread':
                result = await self._get_email_thread(gmail_client, **arguments)
            elif tool_name == 'search_emails':
                result = await self._search_emails(gmail_client, **arguments)
            elif tool_name == 'send_email':
                result = await self._send_email(gmail_client, **arguments)
            elif tool_name == 'reply_to_email':
                result = await self._reply_to_email(gmail_client, **arguments)
            elif tool_name == 'list_calendar_events':
                result = await self._list_calendar_events(calendar_client, **arguments)
            elif tool_name == 'create_calendar_event':
                result = await self._create_calendar_event(calendar_client, **arguments)
            elif tool_name == 'list_fathom_meetings':
                result = await self._list_fathom_meetings(fathom_client, **arguments)
            elif tool_name == 'get_fathom_transcript':
                result = await self._get_fathom_transcript(fathom_client, **arguments)
            elif tool_name == 'get_fathom_summary':
                result = await self._get_fathom_summary(fathom_client, **arguments)
            elif tool_name == 'search_fathom_meetings_by_title':
                result = await self._search_fathom_meetings_by_title(fathom_client, **arguments)
            elif tool_name == 'search_fathom_meetings_by_attendee':
                result = await self._search_fathom_meetings_by_attendee(fathom_client, **arguments)
            else:
                request_id = request_data.get('id', 1)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id if request_id is not None else 1,
                    "error": {
                        "code": -32601,
                        "message": f"Tool not found: {tool_name}"
                    }
                }

            request_id = request_data.get('id', 1)
            return {
                "jsonrpc": "2.0",
                "id": request_id if request_id is not None else 1,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": result
                        }
                    ]
                }
            }

        except Exception as e:
            logger.error(f"Error calling tool {tool_name}: {e}", exc_info=True)
            request_id = request_data.get('id', 1)
            return {
                "jsonrpc": "2.0",
                "id": request_id if request_id is not None else 1,
                "error": {
                    "code": -32603,
                    "message": f"Tool execution error: {str(e)}"
                }
            }

    # Tool implementations (simplified versions)
    async def _get_unreplied_emails(
        self, gmail: GmailClient, analyzer: EmailAnalyzer, **kwargs
    ) -> str:
        """Get unreplied emails."""
        days_back = kwargs.get('days_back', 7)
        max_results = kwargs.get('max_results', 50)

        unreplied = await asyncio.to_thread(
            gmail.get_unreplied_emails,
            days_back=days_back,
            max_results=max_results
        )

        if not unreplied:
            return "No unreplied emails found."

        return json.dumps([
            {
                "thread_id": email['thread_id'],
                "subject": email['subject'],
                "from": email['from'],
                "date": email['date'],
                "snippet": email['snippet']
            }
            for email in unreplied[:max_results]
        ], indent=2)

    async def _get_email_thread(self, gmail: GmailClient, **kwargs) -> str:
        """Get email thread."""
        thread_id = kwargs['thread_id']
        thread = await asyncio.to_thread(gmail.get_thread, thread_id)
        return json.dumps(thread, indent=2)

    async def _search_emails(self, gmail: GmailClient, **kwargs) -> str:
        """Search emails."""
        query = kwargs['query']
        max_results = kwargs.get('max_results', 20)
        results = await asyncio.to_thread(
            gmail.search_messages, query, max_results
        )
        return json.dumps(results, indent=2)

    async def _send_email(self, gmail: GmailClient, **kwargs) -> str:
        """Send email."""
        result = await asyncio.to_thread(gmail.send_email, **kwargs)
        return f"Email sent successfully. Message ID: {result}"

    async def _reply_to_email(self, gmail: GmailClient, **kwargs) -> str:
        """Reply to email."""
        result = await asyncio.to_thread(gmail.reply_to_thread, **kwargs)
        return f"Reply sent successfully. Message ID: {result}"

    async def _list_calendar_events(self, calendar: CalendarClient, **kwargs) -> str:
        """List calendar events."""
        from datetime import datetime, timedelta

        calendar_id = kwargs.get('calendar_id', 'primary')
        days_ahead = kwargs.get('days_ahead', 7)

        # Start from beginning of today (midnight) to include past events
        time_min = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        time_max = time_min + timedelta(days=days_ahead + 1)

        events = await asyncio.to_thread(
            calendar.list_events,
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            max_results=kwargs.get('max_results', 50)
        )
        return json.dumps(events, indent=2)

    async def _create_calendar_event(self, calendar: CalendarClient, **kwargs) -> str:
        """Create calendar event."""
        event = await asyncio.to_thread(calendar.create_event, **kwargs)
        return f"Event created successfully. Event ID: {event['id']}"

    async def _list_fathom_meetings(self, fathom: Optional[FathomClient], **kwargs) -> str:
        """List Fathom meetings."""
        if not fathom:
            return json.dumps({
                "success": False,
                "error": "Fathom API key not configured. Please add your Fathom API key in settings."
            }, indent=2)

        try:
            limit = kwargs.get('limit', 20)
            calendar_invitees_domains_type = kwargs.get('calendar_invitees_domains_type', 'all')

            response = await asyncio.to_thread(
                fathom.list_meetings,
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

            return json.dumps({
                "success": True,
                "count": len(meeting_list),
                "meetings": meeting_list,
                "next_cursor": response.get('next_cursor')
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)

    async def _get_fathom_transcript(self, fathom: Optional[FathomClient], **kwargs) -> str:
        """Get Fathom meeting transcript."""
        if not fathom:
            return json.dumps({
                "success": False,
                "error": "Fathom API key not configured. Please add your Fathom API key in settings."
            }, indent=2)

        try:
            recording_id = kwargs['recording_id']
            response = await asyncio.to_thread(
                fathom.get_meeting_transcript,
                recording_id
            )

            return json.dumps({
                "success": True,
                "recording_id": recording_id,
                "transcript": response.get('transcript', [])
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)

    async def _get_fathom_summary(self, fathom: Optional[FathomClient], **kwargs) -> str:
        """Get Fathom meeting summary."""
        if not fathom:
            return json.dumps({
                "success": False,
                "error": "Fathom API key not configured. Please add your Fathom API key in settings."
            }, indent=2)

        try:
            recording_id = kwargs['recording_id']
            response = await asyncio.to_thread(
                fathom.get_meeting_summary,
                recording_id
            )

            return json.dumps({
                "success": True,
                "recording_id": recording_id,
                "summary": response.get('summary', ''),
                "action_items": response.get('action_items', []),
                "keywords": response.get('keywords', [])
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)

    async def _search_fathom_meetings_by_title(self, fathom: Optional[FathomClient], **kwargs) -> str:
        """Search Fathom meetings by title."""
        if not fathom:
            return json.dumps({
                "success": False,
                "error": "Fathom API key not configured. Please add your Fathom API key in settings."
            }, indent=2)

        try:
            search_term = kwargs['search_term']
            limit = kwargs.get('limit', 20)

            # Get meetings and search client-side
            response = await asyncio.to_thread(
                fathom.list_meetings,
                limit=100  # Get more to search through
            )

            meetings = response.get('items', [])
            search_term_lower = search_term.lower()

            # Filter by title
            matching_meetings = []
            for meeting in meetings:
                title = meeting.get('title') or meeting.get('meeting_title') or ''
                if search_term_lower in title.lower():
                    matching_meetings.append({
                        "recording_id": meeting.get('recording_id'),
                        "title": title,
                        "url": meeting.get('url'),
                        "scheduled_start": meeting.get('scheduled_start_time'),
                        "scheduled_end": meeting.get('scheduled_end_time')
                    })

                if len(matching_meetings) >= limit:
                    break

            return json.dumps({
                "success": True,
                "count": len(matching_meetings),
                "search_term": search_term,
                "meetings": matching_meetings
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)

    async def _search_fathom_meetings_by_attendee(self, fathom: Optional[FathomClient], **kwargs) -> str:
        """Search Fathom meetings by attendee."""
        if not fathom:
            return json.dumps({
                "success": False,
                "error": "Fathom API key not configured. Please add your Fathom API key in settings."
            }, indent=2)

        try:
            attendee = kwargs['attendee']
            limit = kwargs.get('limit', 20)

            # Get meetings and search client-side
            response = await asyncio.to_thread(
                fathom.list_meetings,
                limit=100  # Get more to search through
            )

            meetings = response.get('items', [])
            attendee_lower = attendee.lower()

            # Filter by attendee
            matching_meetings = []
            for meeting in meetings:
                attendees = meeting.get('calendar_invitees', [])
                for att in attendees:
                    name = att.get('name', '').lower()
                    email = att.get('email', '').lower()

                    if attendee_lower in name or attendee_lower in email:
                        matching_meetings.append({
                            "recording_id": meeting.get('recording_id'),
                            "title": meeting.get('title') or meeting.get('meeting_title'),
                            "url": meeting.get('url'),
                            "scheduled_start": meeting.get('scheduled_start_time'),
                            "scheduled_end": meeting.get('scheduled_end_time'),
                            "attendees": [
                                {
                                    "name": a.get('name'),
                                    "email": a.get('email')
                                }
                                for a in attendees
                            ]
                        })
                        break

                if len(matching_meetings) >= limit:
                    break

            return json.dumps({
                "success": True,
                "count": len(matching_meetings),
                "search_term": attendee,
                "meetings": matching_meetings
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)
