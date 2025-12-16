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
            }
            # Add more tools as needed
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
        calendar_id = kwargs.get('calendar_id', 'primary')
        days_ahead = kwargs.get('days_ahead', 7)
        events = await asyncio.to_thread(
            calendar.list_upcoming_events, calendar_id, days_ahead
        )
        return json.dumps(events, indent=2)

    async def _create_calendar_event(self, calendar: CalendarClient, **kwargs) -> str:
        """Create calendar event."""
        event = await asyncio.to_thread(calendar.create_event, **kwargs)
        return f"Event created successfully. Event ID: {event['id']}"
