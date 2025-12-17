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
from config import Config
import leads

logger = logging.getLogger(__name__)


def convert_to_bison_placeholders(text: str) -> str:
    """
    Convert Instantly-style placeholders to Bison format.
    {{first_name}} → {FIRST_NAME}
    {{firstname}} → {FIRST_NAME}
    {{company}} → {COMPANY_NAME}
    """
    import re

    # Map of Instantly → Bison placeholders
    # Includes all common variations (camelCase, snake_case, no separator)
    replacements = {
        r'\{\{first_name\}\}': '{FIRST_NAME}',
        r'\{\{firstName\}\}': '{FIRST_NAME}',
        r'\{\{firstname\}\}': '{FIRST_NAME}',
        r'\{\{last_name\}\}': '{LAST_NAME}',
        r'\{\{lastName\}\}': '{LAST_NAME}',
        r'\{\{lastname\}\}': '{LAST_NAME}',
        r'\{\{company\}\}': '{COMPANY_NAME}',
        r'\{\{company_name\}\}': '{COMPANY_NAME}',
        r'\{\{companyName\}\}': '{COMPANY_NAME}',
        r'\{\{companyname\}\}': '{COMPANY_NAME}',
        r'\{\{title\}\}': '{TITLE}',
        r'\{\{job_title\}\}': '{TITLE}',
        r'\{\{jobTitle\}\}': '{TITLE}',
        r'\{\{jobtitle\}\}': '{TITLE}',
        r'\{\{email\}\}': '{EMAIL}',
    }

    result = text
    for pattern, replacement in replacements.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


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
            # Gmail Tools
            {
                "name": "get_unreplied_emails",
                "description": "Get emails that haven't been replied to within a specified time period",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "days_back": {"type": "number", "description": "Number of days to look back"},
                        "max_results": {"type": "number", "description": "Maximum number of results"},
                        "exclude_automated": {"type": "boolean", "description": "Filter out automated emails"}
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
                "name": "get_inbox_summary",
                "description": "Get statistics on unreplied emails including top senders and domains",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_unreplied_by_sender",
                "description": "Get unreplied emails from a specific sender or domain",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "email_or_domain": {"type": "string", "description": "Email address or @domain.com"}
                    },
                    "required": ["email_or_domain"]
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
                "name": "reply_all_to_email",
                "description": "Reply to all recipients in an email thread",
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
                "name": "create_email_draft",
                "description": "Create an email draft without sending",
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
            # Calendar Tools
            {
                "name": "list_calendars",
                "description": "List all calendars accessible to the user",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "list_calendar_events",
                "description": "List upcoming calendar events",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "calendar_id": {"type": "string"},
                        "days_ahead": {"type": "number"},
                        "max_results": {"type": "number"},
                        "query": {"type": "string"}
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
                        "calendar_id": {"type": "string"},
                        "description": {"type": "string"},
                        "location": {"type": "string"},
                        "attendees": {"type": "string"},
                        "time_zone": {"type": "string"}
                    },
                    "required": ["summary", "start_time"]
                }
            },
            {
                "name": "update_calendar_event",
                "description": "Update an existing calendar event",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string"},
                        "calendar_id": {"type": "string"},
                        "summary": {"type": "string"},
                        "start_time": {"type": "string"},
                        "end_time": {"type": "string"},
                        "description": {"type": "string"},
                        "location": {"type": "string"},
                        "time_zone": {"type": "string"}
                    },
                    "required": ["event_id"]
                }
            },
            {
                "name": "delete_calendar_event",
                "description": "Delete a calendar event",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string"},
                        "calendar_id": {"type": "string"}
                    },
                    "required": ["event_id"]
                }
            },
            {
                "name": "list_past_calendar_events",
                "description": "List past calendar events",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "calendar_id": {"type": "string"},
                        "days_back": {"type": "number"},
                        "max_results": {"type": "number"},
                        "query": {"type": "string"}
                    }
                }
            },
            {
                "name": "quick_add_calendar_event",
                "description": "Create a calendar event using natural language",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Natural language description"},
                        "calendar_id": {"type": "string"}
                    },
                    "required": ["text"]
                }
            },
            # Fathom Tools
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
                "name": "get_fathom_action_items",
                "description": "Get action items from a Fathom meeting recording",
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
            },
            # Lead Management Tools - Instantly.ai
            {
                "name": "get_instantly_clients",
                "description": "Get list of all Instantly.ai clients/workspaces",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_instantly_leads",
                "description": "Get lead responses for a specific Instantly.ai workspace",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string"},
                        "days": {"type": "number"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"}
                    },
                    "required": ["workspace_id"]
                }
            },
            {
                "name": "get_instantly_stats",
                "description": "Get campaign statistics for a specific Instantly.ai workspace",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string"},
                        "days": {"type": "number"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"}
                    },
                    "required": ["workspace_id"]
                }
            },
            {
                "name": "get_instantly_workspace",
                "description": "Get detailed information about a specific Instantly.ai workspace",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string"}
                    },
                    "required": ["workspace_id"]
                }
            },
            # Lead Management Tools - Bison
            {
                "name": "get_bison_clients",
                "description": "Get list of all Bison clients",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_bison_leads",
                "description": "Get lead responses for a specific Bison client",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "client_name": {"type": "string"},
                        "days": {"type": "number"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"}
                    },
                    "required": ["client_name"]
                }
            },
            {
                "name": "get_bison_stats",
                "description": "Get campaign statistics for a specific Bison client",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "client_name": {"type": "string"},
                        "days": {"type": "number"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"}
                    },
                    "required": ["client_name"]
                }
            },
            {
                "name": "create_bison_sequence",
                "description": "Upload/create email sequence steps for a Bison campaign. If no campaign_id is provided, creates a new campaign automatically. Use this to automate sequence creation instead of manually copying sequences. Each step can have subject, body, wait time, and thread reply settings.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "client_name": {
                            "type": "string",
                            "description": "Name of the Bison client (e.g., 'Jeff Mikolai')"
                        },
                        "campaign_id": {
                            "type": "number",
                            "description": "The Bison campaign ID to add sequences to (optional - if not provided, creates a new campaign)"
                        },
                        "campaign_name": {
                            "type": "string",
                            "description": "Campaign name (required if campaign_id not provided, e.g., 'Speaker Outreach 2025')"
                        },
                        "sequence_title": {
                            "type": "string",
                            "description": "Title for the sequence (e.g., 'Cold Outreach v2')"
                        },
                        "steps": {
                            "type": "array",
                            "description": "Array of email sequence steps (1-3 steps typically)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "email_subject": {"type": "string"},
                                    "email_body": {"type": "string"},
                                    "order": {"type": "number", "description": "Step order (1, 2, 3, etc.)"},
                                    "wait_in_days": {"type": "number", "description": "Days to wait before sending"},
                                    "thread_reply": {"type": "boolean", "description": "Whether to reply in same thread (default: false)"},
                                    "variant": {"type": "boolean", "description": "Whether this is a variant (default: false)"},
                                    "variant_from_step": {"type": "number", "description": "Which step this is a variant of"}
                                },
                                "required": ["email_subject", "email_body", "order", "wait_in_days"]
                            }
                        }
                    },
                    "required": ["client_name", "sequence_title", "steps"]
                }
            },
            {
                "name": "create_instantly_campaign",
                "description": "Create an Instantly.ai campaign with email sequences. Automatically sets up campaign with scheduling, tracking, and sequences. Use this to automate campaign creation instead of manually setting up in Instantly UI.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "client_name": {
                            "type": "string",
                            "description": "Name of the Instantly client (e.g., 'Jeff Mikolai')"
                        },
                        "campaign_name": {
                            "type": "string",
                            "description": "Campaign name (e.g., 'Speaker Outreach 2025')"
                        },
                        "steps": {
                            "type": "array",
                            "description": "Array of email sequence steps (1-3 steps typically)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "subject": {"type": "string", "description": "Email subject line"},
                                    "body": {"type": "string", "description": "Email body content"},
                                    "wait": {"type": "number", "description": "Hours to wait before sending (for follow-ups, first email is 0)"},
                                    "variants": {
                                        "type": "array",
                                        "description": "Optional A/B test variants for this step",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "subject": {"type": "string"},
                                                "body": {"type": "string"}
                                            }
                                        }
                                    }
                                },
                                "required": ["subject", "body"]
                            }
                        },
                        "email_accounts": {
                            "type": "array",
                            "description": "List of email addresses to send from (optional)",
                            "items": {"type": "string"}
                        },
                        "daily_limit": {
                            "type": "number",
                            "description": "Daily sending limit per account (default: 50)"
                        },
                        "timezone": {
                            "type": "string",
                            "description": "Timezone for schedule (default: 'America/Chicago')"
                        },
                        "schedule_from": {
                            "type": "string",
                            "description": "Start time in HH:MM format (default: '09:00')"
                        },
                        "schedule_to": {
                            "type": "string",
                            "description": "End time in HH:MM format (default: '17:00')"
                        },
                        "stop_on_reply": {
                            "type": "boolean",
                            "description": "Stop campaign when lead replies (default: true)"
                        },
                        "text_only": {
                            "type": "boolean",
                            "description": "Send all emails as text only (default: false)"
                        }
                    },
                    "required": ["client_name", "campaign_name", "steps"]
                }
            },
            # Lead Management Tools - Combined
            {
                "name": "get_all_lead_clients",
                "description": "Get list of all clients from both Instantly.ai and Bison platforms",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_lead_platform_stats",
                "description": "Get aggregated statistics across both Instantly.ai and Bison platforms",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "number"}
                    }
                }
            },
            {
                "name": "get_top_clients",
                "description": "Get the top performing clients based on a specific metric",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "number"},
                        "metric": {"type": "string"},
                        "days": {"type": "number"}
                    }
                }
            },
            {
                "name": "get_underperforming_clients_list",
                "description": "Get list of underperforming clients based on a specific metric threshold",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "threshold": {"type": "number"},
                        "metric": {"type": "string"},
                        "days": {"type": "number"}
                    }
                }
            },
            {
                "name": "get_lead_weekly_summary",
                "description": "Get a comprehensive weekly summary of lead generation activities",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
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
            # Call the appropriate tool - Gmail tools
            if tool_name == 'get_unreplied_emails':
                result = await self._get_unreplied_emails(
                    gmail_client, email_analyzer, **arguments
                )
            elif tool_name == 'get_email_thread':
                result = await self._get_email_thread(gmail_client, **arguments)
            elif tool_name == 'search_emails':
                result = await self._search_emails(gmail_client, **arguments)
            elif tool_name == 'get_inbox_summary':
                result = await self._get_inbox_summary(gmail_client, email_analyzer, **arguments)
            elif tool_name == 'get_unreplied_by_sender':
                result = await self._get_unreplied_by_sender(gmail_client, email_analyzer, **arguments)
            elif tool_name == 'send_email':
                result = await self._send_email(gmail_client, **arguments)
            elif tool_name == 'reply_to_email':
                result = await self._reply_to_email(gmail_client, **arguments)
            elif tool_name == 'reply_all_to_email':
                result = await self._reply_all_to_email(gmail_client, email_analyzer, **arguments)
            elif tool_name == 'create_email_draft':
                result = await self._create_email_draft(gmail_client, **arguments)
            # Calendar tools
            elif tool_name == 'list_calendars':
                result = await self._list_calendars(calendar_client, **arguments)
            elif tool_name == 'list_calendar_events':
                result = await self._list_calendar_events(calendar_client, **arguments)
            elif tool_name == 'create_calendar_event':
                result = await self._create_calendar_event(calendar_client, gmail_client, **arguments)
            elif tool_name == 'update_calendar_event':
                result = await self._update_calendar_event(calendar_client, **arguments)
            elif tool_name == 'delete_calendar_event':
                result = await self._delete_calendar_event(calendar_client, **arguments)
            elif tool_name == 'list_past_calendar_events':
                result = await self._list_past_calendar_events(calendar_client, **arguments)
            elif tool_name == 'quick_add_calendar_event':
                result = await self._quick_add_calendar_event(calendar_client, **arguments)
            # Fathom tools
            elif tool_name == 'list_fathom_meetings':
                result = await self._list_fathom_meetings(fathom_client, **arguments)
            elif tool_name == 'get_fathom_transcript':
                result = await self._get_fathom_transcript(fathom_client, **arguments)
            elif tool_name == 'get_fathom_summary':
                result = await self._get_fathom_summary(fathom_client, **arguments)
            elif tool_name == 'get_fathom_action_items':
                result = await self._get_fathom_action_items(fathom_client, **arguments)
            elif tool_name == 'search_fathom_meetings_by_title':
                result = await self._search_fathom_meetings_by_title(fathom_client, **arguments)
            elif tool_name == 'search_fathom_meetings_by_attendee':
                result = await self._search_fathom_meetings_by_attendee(fathom_client, **arguments)
            # Lead Management tools - Instantly.ai
            elif tool_name == 'get_instantly_clients':
                result = await self._get_instantly_clients(**arguments)
            elif tool_name == 'get_instantly_leads':
                result = await self._get_instantly_leads(**arguments)
            elif tool_name == 'get_instantly_stats':
                result = await self._get_instantly_stats(**arguments)
            elif tool_name == 'get_instantly_workspace':
                result = await self._get_instantly_workspace(**arguments)
            # Lead Management tools - Bison
            elif tool_name == 'get_bison_clients':
                result = await self._get_bison_clients(**arguments)
            elif tool_name == 'get_bison_leads':
                result = await self._get_bison_leads(**arguments)
            elif tool_name == 'get_bison_stats':
                result = await self._get_bison_stats(**arguments)
            elif tool_name == 'create_bison_sequence':
                result = await self._create_bison_sequence(**arguments)
            elif tool_name == 'create_instantly_campaign':
                result = await self._create_instantly_campaign(**arguments)
            # Lead Management tools - Combined
            elif tool_name == 'get_all_lead_clients':
                result = await self._get_all_lead_clients(**arguments)
            elif tool_name == 'get_lead_platform_stats':
                result = await self._get_lead_platform_stats(**arguments)
            elif tool_name == 'get_top_clients':
                result = await self._get_top_clients(**arguments)
            elif tool_name == 'get_underperforming_clients_list':
                result = await self._get_underperforming_clients_list(**arguments)
            elif tool_name == 'get_lead_weekly_summary':
                result = await self._get_lead_weekly_summary(**arguments)
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
        from datetime import datetime, timedelta

        days_back = kwargs.get('days_back', 7)
        max_results = kwargs.get('max_results', 50)
        exclude_automated = kwargs.get('exclude_automated', True)

        # Build Gmail query
        since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y/%m/%d')
        query = f"-in:sent -in:draft after:{since_date}"

        # Fetch threads
        thread_infos = await asyncio.to_thread(gmail.list_threads, query, max_results * 2)
        user_email = await asyncio.to_thread(gmail.get_user_email)

        # Process threads
        unreplied = []
        for thread_info in thread_infos:
            if len(unreplied) >= max_results:
                break

            # Fetch full thread
            thread = await asyncio.to_thread(gmail.get_thread, thread_info['id'])

            # Check if unreplied
            if analyzer.is_unreplied(thread, user_email):
                last_message = thread['messages'][-1]

                # Optional: Filter automated
                if exclude_automated and analyzer.is_automated_email(last_message):
                    continue

                # Format email information
                email_info = analyzer.format_unreplied_email(thread, last_message)
                unreplied.append(email_info)

        return json.dumps({
            "success": True,
            "count": len(unreplied),
            "days_back": days_back,
            "exclude_automated": exclude_automated,
            "emails": unreplied
        }, indent=2)

    async def _get_email_thread(self, gmail: GmailClient, **kwargs) -> str:
        """Get email thread."""
        thread_id = kwargs['thread_id']
        thread = await asyncio.to_thread(gmail.get_thread, thread_id)
        return json.dumps(thread, indent=2)

    async def _search_emails(self, gmail: GmailClient, **kwargs) -> str:
        """Search emails."""
        query = kwargs['query']
        max_results = kwargs.get('max_results', 20)

        # Search messages using list_messages
        message_infos = await asyncio.to_thread(gmail.list_messages, query, max_results)

        # Fetch message details
        results = []
        for msg_info in message_infos:
            msg = await asyncio.to_thread(gmail.get_message, msg_info['id'])

            from email_analyzer import EmailAnalyzer
            analyzer = EmailAnalyzer()
            headers = analyzer.parse_headers(msg.get('payload', {}).get('headers', []))

            # Extract timestamp
            received_timestamp = analyzer.extract_received_timestamp(msg)
            received_date = None
            if received_timestamp:
                try:
                    from datetime import datetime
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

        return json.dumps({
            "success": True,
            "query": query,
            "count": len(results),
            "results": results
        }, indent=2)

    async def _send_email(self, gmail: GmailClient, **kwargs) -> str:
        """Send email."""
        result = await asyncio.to_thread(
            gmail.send_message,
            to=kwargs['to'],
            subject=kwargs['subject'],
            body=kwargs['body'],
            cc=kwargs.get('cc'),
            bcc=kwargs.get('bcc')
        )
        return json.dumps({
            "success": True,
            "message_id": result['id'],
            "message": f"Email sent successfully to {kwargs['to']}"
        }, indent=2)

    async def _reply_to_email(self, gmail: GmailClient, **kwargs) -> str:
        """Reply to email."""
        thread_id = kwargs['thread_id']
        body = kwargs['body']

        # Get thread to extract reply information
        thread = await asyncio.to_thread(gmail.get_thread, thread_id)
        last_message = thread['messages'][-1]

        from email_analyzer import EmailAnalyzer
        analyzer = EmailAnalyzer()
        headers = analyzer.parse_headers(last_message.get('payload', {}).get('headers', []))

        from_addr = headers.get('From', '')
        subject = headers.get('Subject', '')
        message_id = headers.get('Message-ID', '')
        references = headers.get('References', '')

        if not subject.startswith('Re:'):
            subject = f"Re: {subject}"

        new_references = f"{references} {message_id}" if references else message_id

        result = await asyncio.to_thread(
            gmail.send_message,
            to=from_addr,
            subject=subject,
            body=body,
            thread_id=thread_id,
            in_reply_to=message_id,
            references=new_references
        )

        return json.dumps({
            "success": True,
            "message_id": result['id'],
            "thread_id": thread_id,
            "message": f"Reply sent successfully to thread {thread_id}"
        }, indent=2)

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

    async def _create_calendar_event(self, calendar: CalendarClient, gmail: GmailClient, **kwargs) -> str:
        """Create calendar event with email notifications."""
        from datetime import datetime

        start_time = kwargs.get('start_time')
        end_time = kwargs.get('end_time', start_time)

        # Parse dates
        start_dt = datetime.fromisoformat(start_time) if isinstance(start_time, str) else start_time
        end_dt = datetime.fromisoformat(end_time) if isinstance(end_time, str) and end_time else start_dt

        # Parse attendees
        attendee_list = None
        attendees_str = kwargs.get('attendees')
        if attendees_str:
            attendee_list = [email.strip() for email in attendees_str.split(',')]

        # Create event
        event = await asyncio.to_thread(
            calendar.create_event,
            summary=kwargs['summary'],
            start_time=start_dt,
            end_time=end_dt,
            calendar_id=kwargs.get('calendar_id', 'primary'),
            description=kwargs.get('description'),
            location=kwargs.get('location'),
            attendees=attendee_list,
            time_zone=kwargs.get('time_zone', 'America/Bogota')
        )

        return json.dumps({
            "success": True,
            "event_id": event['id'],
            "summary": event.get('summary'),
            "start": event.get('start', {}).get('dateTime'),
            "end": event.get('end', {}).get('dateTime'),
            "html_link": event.get('htmlLink', '')
        }, indent=2)

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


    # ========================================================================
    # ADDITIONAL GMAIL METHODS
    # ========================================================================

    async def _get_inbox_summary(
        self, gmail: GmailClient, analyzer: EmailAnalyzer, **kwargs
    ) -> str:
        """Get inbox summary statistics."""
        from datetime import datetime, timedelta
        
        # Get unreplied emails from last 30 days
        since_date = (datetime.now() - timedelta(days=30)).strftime('%Y/%m/%d')
        query = f"-in:sent -in:draft after:{since_date}"
        
        thread_infos = await asyncio.to_thread(gmail.list_threads, query, 100)
        user_email = await asyncio.to_thread(gmail.get_user_email)
        
        unreplied = []
        by_sender = {}
        by_domain = {}
        dates = []
        
        for thread_info in thread_infos:
            thread = await asyncio.to_thread(gmail.get_thread, thread_info['id'])
            
            if analyzer.is_unreplied(thread, user_email):
                last_message = thread['messages'][-1]
                if not analyzer.is_automated_email(last_message):
                    headers = analyzer.parse_headers(last_message.get('payload', {}).get('headers', []))
                    from_header = headers.get('From', '')
                    
                    # Parse sender email
                    email = from_header
                    if '<' in from_header and '>' in from_header:
                        email = from_header[from_header.index('<')+1:from_header.index('>')]
                    
                    domain = email.split('@')[1] if '@' in email else 'unknown'
                    
                    by_sender[email] = by_sender.get(email, 0) + 1
                    by_domain[domain] = by_domain.get(domain, 0) + 1
                    
                    timestamp = analyzer.extract_received_timestamp(last_message)
                    if timestamp:
                        try:
                            dt = datetime.fromtimestamp(int(timestamp) / 1000.0)
                            dates.append(dt)
                        except (ValueError, OSError):
                            pass
                    
                    unreplied.append(analyzer.format_unreplied_email(thread, last_message))
        
        top_senders = sorted(by_sender.items(), key=lambda x: x[1], reverse=True)[:10]
        top_domains = sorted(by_domain.items(), key=lambda x: x[1], reverse=True)[:10]
        
        oldest_date = min(dates).isoformat() if dates else None
        newest_date = max(dates).isoformat() if dates else None
        
        return json.dumps({
            "success": True,
            "total_unreplied": len(unreplied),
            "top_senders": [{"email": k, "count": v} for k, v in top_senders],
            "top_domains": [{"domain": k, "count": v} for k, v in top_domains],
            "oldest_unreplied": oldest_date,
            "newest_unreplied": newest_date,
            "date_range_days": 30
        }, indent=2)

    async def _get_unreplied_by_sender(
        self, gmail: GmailClient, analyzer: EmailAnalyzer, **kwargs
    ) -> str:
        """Get unreplied emails from specific sender/domain."""
        email_or_domain = kwargs['email_or_domain']
        
        query = f"from:{email_or_domain} -in:sent -in:draft"
        message_infos = await asyncio.to_thread(gmail.list_messages, query, 50)
        user_email = await asyncio.to_thread(gmail.get_user_email)
        
        unreplied = []
        for msg_info in message_infos:
            thread = await asyncio.to_thread(gmail.get_thread, msg_info['threadId'])
            
            if analyzer.is_unreplied(thread, user_email):
                last_message = thread['messages'][-1]
                unreplied.append(analyzer.format_unreplied_email(thread, last_message))
        
        return json.dumps({
            "success": True,
            "filter": email_or_domain,
            "count": len(unreplied),
            "emails": unreplied
        }, indent=2)

    async def _reply_all_to_email(
        self, gmail: GmailClient, analyzer: EmailAnalyzer, **kwargs
    ) -> str:
        """Reply to all recipients in email thread."""
        thread_id = kwargs['thread_id']
        body = kwargs['body']
        
        thread = await asyncio.to_thread(gmail.get_thread, thread_id)
        last_message = thread['messages'][-1]
        headers = analyzer.parse_headers(last_message.get('payload', {}).get('headers', []))
        
        from_addr = headers.get('From', '')
        to_addr = headers.get('To', '')
        cc_addr = headers.get('Cc', '')
        subject = headers.get('Subject', '')
        message_id = headers.get('Message-ID', '')
        references = headers.get('References', '')
        
        user_email = await asyncio.to_thread(gmail.get_user_email)
        
        # Build recipient lists
        all_recipients = []
        if to_addr:
            all_recipients.extend([addr.strip() for addr in to_addr.split(',')])
        if cc_addr:
            all_recipients.extend([addr.strip() for addr in cc_addr.split(',')])
        
        all_recipients = [r for r in all_recipients if user_email.lower() not in r.lower()]
        
        to = from_addr
        cc = ', '.join(all_recipients) if all_recipients else None
        
        if not subject.startswith('Re:'):
            subject = f"Re: {subject}"
        
        new_references = f"{references} {message_id}" if references else message_id
        
        sent_message = await asyncio.to_thread(
            gmail.send_message,
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            thread_id=thread_id,
            in_reply_to=message_id,
            references=new_references
        )
        
        return json.dumps({
            "success": True,
            "message_id": sent_message['id'],
            "thread_id": thread_id,
            "message": "Reply-all sent successfully"
        }, indent=2)

    async def _create_email_draft(self, gmail: GmailClient, **kwargs) -> str:
        """Create an email draft."""
        draft = await asyncio.to_thread(
            gmail.create_draft,
            to=kwargs['to'],
            subject=kwargs['subject'],
            body=kwargs['body'],
            cc=kwargs.get('cc'),
            bcc=kwargs.get('bcc')
        )
        
        return json.dumps({
            "success": True,
            "draft_id": draft['id'],
            "message": "Draft created successfully",
            "to": kwargs['to'],
            "subject": kwargs['subject']
        }, indent=2)

    # ========================================================================
    # ADDITIONAL CALENDAR METHODS
    # ========================================================================

    async def _list_calendars(self, calendar: CalendarClient, **kwargs) -> str:
        """List all calendars."""
        calendars = await asyncio.to_thread(calendar.list_calendars)
        
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
        
        return json.dumps({
            "success": True,
            "count": len(calendar_list),
            "calendars": calendar_list
        }, indent=2)

    async def _update_calendar_event(self, calendar: CalendarClient, **kwargs) -> str:
        """Update a calendar event."""
        from datetime import datetime
        
        event_id = kwargs['event_id']
        calendar_id = kwargs.get('calendar_id', 'primary')
        
        start_dt = datetime.fromisoformat(kwargs['start_time']) if kwargs.get('start_time') else None
        end_dt = datetime.fromisoformat(kwargs['end_time']) if kwargs.get('end_time') else None
        
        event = await asyncio.to_thread(
            calendar.update_event,
            event_id=event_id,
            calendar_id=calendar_id,
            summary=kwargs.get('summary'),
            start_time=start_dt,
            end_time=end_dt,
            description=kwargs.get('description'),
            location=kwargs.get('location'),
            time_zone=kwargs.get('time_zone')
        )
        
        return json.dumps({
            "success": True,
            "event_id": event['id'],
            "summary": event.get('summary'),
            "start": event.get('start', {}).get('dateTime'),
            "end": event.get('end', {}).get('dateTime'),
            "html_link": event.get('htmlLink', '')
        }, indent=2)

    async def _delete_calendar_event(self, calendar: CalendarClient, **kwargs) -> str:
        """Delete a calendar event."""
        event_id = kwargs['event_id']
        calendar_id = kwargs.get('calendar_id', 'primary')
        
        await asyncio.to_thread(calendar.delete_event, event_id, calendar_id)
        
        return json.dumps({
            "success": True,
            "event_id": event_id,
            "message": "Event deleted successfully"
        }, indent=2)

    async def _list_past_calendar_events(self, calendar: CalendarClient, **kwargs) -> str:
        """List past calendar events."""
        from datetime import datetime, timedelta
        
        calendar_id = kwargs.get('calendar_id', 'primary')
        days_back = kwargs.get('days_back', 7)
        max_results = kwargs.get('max_results', 50)
        
        time_max = datetime.now()
        time_min = time_max - timedelta(days=days_back)
        
        events = await asyncio.to_thread(
            calendar.list_events,
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
            query=kwargs.get('query')
        )
        
        event_list = []
        for event in events:
            start = event.get('start', {})
            event_list.append({
                "id": event.get('id'),
                "summary": event.get('summary', 'No title'),
                "description": event.get('description', ''),
                "location": event.get('location', ''),
                "start": start.get('dateTime', start.get('date')),
                "end": event.get('end', {}).get('dateTime', event.get('end', {}).get('date')),
                "html_link": event.get('htmlLink', '')
            })
        
        return json.dumps({
            "success": True,
            "calendar_id": calendar_id,
            "days_back": days_back,
            "count": len(event_list),
            "events": event_list
        }, indent=2)

    async def _quick_add_calendar_event(self, calendar: CalendarClient, **kwargs) -> str:
        """Quick add calendar event using natural language."""
        text = kwargs['text']
        calendar_id = kwargs.get('calendar_id', 'primary')
        
        event = await asyncio.to_thread(calendar.quick_add_event, text, calendar_id)
        
        return json.dumps({
            "success": True,
            "event_id": event['id'],
            "summary": event.get('summary'),
            "start": event.get('start', {}).get('dateTime', event.get('start', {}).get('date')),
            "end": event.get('end', {}).get('dateTime', event.get('end', {}).get('date')),
            "html_link": event.get('htmlLink', '')
        }, indent=2)

    # ========================================================================
    # ADDITIONAL FATHOM METHODS
    # ========================================================================

    async def _get_fathom_action_items(self, fathom: Optional[FathomClient], **kwargs) -> str:
        """Get action items from Fathom meeting."""
        if not fathom:
            return json.dumps({
                "success": False,
                "error": "Fathom API key not configured"
            }, indent=2)
        
        try:
            recording_id = kwargs['recording_id']
            
            response = await asyncio.to_thread(fathom.list_meetings, limit=100)
            meetings = response.get('items', [])
            
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
            
            action_list = []
            for item in action_items:
                assignee = item.get('assignee', {})
                action_list.append({
                    "description": item.get('description'),
                    "completed": item.get('completed'),
                    "timestamp": item.get('recording_timestamp'),
                    "assignee_name": assignee.get('name'),
                    "assignee_email": assignee.get('email')
                })
            
            return json.dumps({
                "success": True,
                "recording_id": recording_id,
                "count": len(action_list),
                "action_items": action_list
            }, indent=2)
        
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)

    # ========================================================================
    # LEAD MANAGEMENT METHODS
    # ========================================================================

    async def _get_instantly_clients(self, **kwargs) -> str:
        """Get list of Instantly.ai clients."""
        try:
            config = Config.from_env()
            result = await asyncio.to_thread(
                leads.get_client_list,
                sheet_url=config.lead_sheets_url
            )
            return json.dumps({"success": True, **result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    async def _get_instantly_leads(self, **kwargs) -> str:
        """Get leads for Instantly.ai workspace."""
        try:
            config = Config.from_env()
            result = await asyncio.to_thread(
                leads.get_lead_responses,
                sheet_url=config.lead_sheets_url,
                gid=config.lead_sheets_gid_instantly,
                workspace_id=kwargs['workspace_id'],
                days=kwargs.get('days', 7),
                start_date=kwargs.get('start_date'),
                end_date=kwargs.get('end_date')
            )
            return json.dumps({"success": True, **result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    async def _get_instantly_stats(self, **kwargs) -> str:
        """Get stats for Instantly.ai workspace."""
        try:
            config = Config.from_env()
            result = await asyncio.to_thread(
                leads.get_campaign_stats,
                sheet_url=config.lead_sheets_url,
                gid=config.lead_sheets_gid_instantly,
                workspace_id=kwargs['workspace_id'],
                days=kwargs.get('days', 7),
                start_date=kwargs.get('start_date'),
                end_date=kwargs.get('end_date')
            )
            return json.dumps({"success": True, **result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    async def _get_instantly_workspace(self, **kwargs) -> str:
        """Get Instantly.ai workspace info."""
        try:
            config = Config.from_env()
            result = await asyncio.to_thread(
                leads.get_workspace_info,
                sheet_url=config.lead_sheets_url,
                workspace_id=kwargs['workspace_id']
            )
            return json.dumps({"success": True, **result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    async def _get_bison_clients(self, **kwargs) -> str:
        """Get list of Bison clients."""
        try:
            config = Config.from_env()
            result = await asyncio.to_thread(
                leads.get_bison_client_list,
                sheet_url=config.lead_sheets_url,
                gid=config.lead_sheets_gid_bison
            )
            return json.dumps({"success": True, **result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    async def _get_bison_leads(self, **kwargs) -> str:
        """Get leads for Bison client."""
        try:
            config = Config.from_env()
            result = await asyncio.to_thread(
                leads.get_bison_lead_responses,
                sheet_url=config.lead_sheets_url,
                gid=config.lead_sheets_gid_bison,
                client_name=kwargs['client_name'],
                days=kwargs.get('days', 7),
                start_date=kwargs.get('start_date'),
                end_date=kwargs.get('end_date')
            )
            return json.dumps({"success": True, **result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    async def _get_bison_stats(self, **kwargs) -> str:
        """Get stats for Bison client."""
        try:
            config = Config.from_env()
            result = await asyncio.to_thread(
                leads.get_bison_campaign_stats,
                sheet_url=config.lead_sheets_url,
                gid=config.lead_sheets_gid_bison,
                client_name=kwargs['client_name'],
                days=kwargs.get('days', 7),
                start_date=kwargs.get('start_date'),
                end_date=kwargs.get('end_date')
            )
            return json.dumps({"success": True, **result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    async def _create_bison_sequence(self, **kwargs) -> str:
        """Create email sequence for a Bison campaign. Auto-creates campaign if needed."""
        try:
            config = Config.from_env()
            from leads import sheets_client, bison_client

            # Get client's API key from sheet
            client_name = kwargs['client_name']
            workspaces = await asyncio.to_thread(
                sheets_client.load_bison_workspaces_from_sheet,
                config.lead_sheets_url,
                config.lead_sheets_gid_bison
            )

            # Find workspace by client name using fuzzy matching
            from rapidfuzz import fuzz, process

            workspace = None
            if workspaces:
                client_names = [ws["client_name"] for ws in workspaces]
                result = process.extractOne(
                    client_name,
                    client_names,
                    scorer=fuzz.WRatio,
                    score_cutoff=60
                )

                if result:
                    matched_name, score, index = result
                    workspace = workspaces[index]
                    logger.info("Matched '%s' to '%s' (score: %d%%)", client_name, matched_name, score)
                else:
                    logger.warning("No match found for '%s'", client_name)

            if not workspace:
                return json.dumps({
                    "success": False,
                    "error": f"Client '{client_name}' not found. Available clients: {', '.join([ws['client_name'] for ws in workspaces[:5]])}..."
                }, indent=2)

            # Get or create campaign
            campaign_id = kwargs.get('campaign_id')

            if not campaign_id:
                # Create new campaign
                campaign_name = kwargs.get('campaign_name', kwargs['sequence_title'])
                campaign_result = await asyncio.to_thread(
                    bison_client.create_bison_campaign_api,
                    api_key=workspace["api_key"],
                    name=campaign_name,
                    campaign_type="outbound"
                )
                campaign_id = campaign_result['data']['id']
                created_campaign = True
            else:
                created_campaign = False

            # Convert placeholder variables to Bison format and ensure wait_in_days >= 1
            steps = kwargs['steps']
            converted_subjects = []
            for step in steps:
                # Default wait_in_days to 3 if missing or < 1 (API requirement)
                if 'wait_in_days' not in step or step['wait_in_days'] < 1:
                    step['wait_in_days'] = 3

                # Convert placeholders: {{first_name}} → {FIRST_NAME}
                if 'email_subject' in step:
                    original = step['email_subject']
                    step['email_subject'] = convert_to_bison_placeholders(step['email_subject'])
                    if original != step['email_subject']:
                        logger.info("[Bison] Converted subject: %s → %s", original, step['email_subject'])
                        converted_subjects.append(step['email_subject'])

                if 'email_body' in step:
                    original = step['email_body']
                    step['email_body'] = convert_to_bison_placeholders(step['email_body'])
                    if original != step['email_body']:
                        logger.info("[Bison] Converted body placeholders")

            # Create the sequence
            result = await asyncio.to_thread(
                bison_client.create_bison_sequence_api,
                api_key=workspace["api_key"],
                campaign_id=campaign_id,
                title=kwargs['sequence_title'],
                sequence_steps=steps
            )

            response = {
                "success": True,
                "message": f"Successfully created sequence '{kwargs['sequence_title']}' with {len(kwargs['steps'])} steps",
                "campaign_id": campaign_id,
                "sequence_id": result['data']['id'],
                "steps_created": len(result['data']['sequence_steps'])
            }

            if created_campaign:
                response["campaign_created"] = True
                response["campaign_name"] = kwargs.get('campaign_name', kwargs['sequence_title'])

            # Include converted subjects for verification
            if converted_subjects:
                response["converted_subjects"] = converted_subjects

            return json.dumps(response, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    async def _create_instantly_campaign(self, **kwargs) -> str:
        """Create Instantly.ai campaign with email sequences."""
        try:
            config = Config.from_env()
            from leads import sheets_client, instantly_client

            # Get client's API key from sheet
            client_name = kwargs['client_name']
            workspaces = await asyncio.to_thread(
                sheets_client.load_instantly_workspaces_from_sheet,
                config.lead_sheets_url,
                config.lead_sheets_gid_instantly
            )

            # Find workspace by client name using fuzzy matching
            from rapidfuzz import fuzz, process

            workspace = None
            if workspaces:
                client_names = [ws["client_name"] for ws in workspaces]
                result = process.extractOne(
                    client_name,
                    client_names,
                    scorer=fuzz.WRatio,
                    score_cutoff=60
                )

                if result:
                    matched_name, score, index = result
                    workspace = workspaces[index]
                    logger.info("Matched '%s' to '%s' (score: %d%%)", client_name, matched_name, score)
                else:
                    logger.warning("No match found for '%s'", client_name)

            if not workspace:
                return json.dumps({
                    "success": False,
                    "error": f"Client '{client_name}' not found. Available clients: {', '.join([ws['client_name'] for ws in workspaces[:5]])}..."
                }, indent=2)

            # Create the campaign with sequences
            result = await asyncio.to_thread(
                instantly_client.create_instantly_campaign_api,
                api_key=workspace["api_key"],
                name=kwargs['campaign_name'],
                sequence_steps=kwargs['steps'],
                email_accounts=kwargs.get('email_accounts'),
                daily_limit=kwargs.get('daily_limit', 50),
                timezone=kwargs.get('timezone', 'America/Chicago'),
                schedule_from=kwargs.get('schedule_from', '09:00'),
                schedule_to=kwargs.get('schedule_to', '17:00'),
                stop_on_reply=kwargs.get('stop_on_reply', True),
                text_only=kwargs.get('text_only', False)
            )

            response = {
                "success": True,
                "message": f"Successfully created campaign '{kwargs['campaign_name']}' with {len(kwargs['steps'])} steps",
                "campaign_id": result.get('id'),
                "campaign_name": result.get('name'),
                "steps_created": len(kwargs['steps'])
            }

            return json.dumps(response, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    async def _get_all_lead_clients(self, **kwargs) -> str:
        """Get all clients from both platforms."""
        try:
            config = Config.from_env()

            # Inline logic to bypass module caching issues
            instantly_result = await asyncio.to_thread(
                leads.get_client_list,
                sheet_url=config.lead_sheets_url
            )
            instantly_clients = [
                {**client, 'platform': 'instantly'}
                for client in instantly_result.get('clients', [])
            ]

            bison_result = await asyncio.to_thread(
                leads.get_bison_client_list,
                sheet_url=config.lead_sheets_url,
                gid=config.lead_sheets_gid_bison
            )
            bison_clients = [
                {**client, 'platform': 'bison'}
                for client in bison_result.get('clients', [])
            ]

            all_clients = instantly_clients + bison_clients

            result = {
                'total_clients': len(all_clients),
                'instantly_count': len(instantly_clients),
                'bison_count': len(bison_clients),
                'clients': all_clients
            }

            return json.dumps({"success": True, **result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    async def _get_lead_platform_stats(self, **kwargs) -> str:
        """Get aggregated platform stats."""
        try:
            config = Config.from_env()
            result = await asyncio.to_thread(
                leads.get_all_platform_stats,
                sheet_url=config.lead_sheets_url,
                instantly_gid=config.lead_sheets_gid_instantly,
                bison_gid=config.lead_sheets_gid_bison,
                days=kwargs.get('days', 7)
            )
            return json.dumps({"success": True, **result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    async def _get_top_clients(self, **kwargs) -> str:
        """Get top performing clients."""
        try:
            config = Config.from_env()
            result = await asyncio.to_thread(
                leads.get_top_performing_clients,
                sheet_url=config.lead_sheets_url,
                instantly_gid=config.lead_sheets_gid_instantly,
                bison_gid=config.lead_sheets_gid_bison,
                limit=kwargs.get('limit', 10),
                metric=kwargs.get('metric', 'interested_leads'),
                days=kwargs.get('days', 7)
            )
            return json.dumps({"success": True, **result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    async def _get_underperforming_clients_list(self, **kwargs) -> str:
        """Get underperforming clients."""
        try:
            config = Config.from_env()
            result = await asyncio.to_thread(
                leads.get_underperforming_clients,
                sheet_url=config.lead_sheets_url,
                instantly_gid=config.lead_sheets_gid_instantly,
                bison_gid=config.lead_sheets_gid_bison,
                threshold=kwargs.get('threshold', 5),
                metric=kwargs.get('metric', 'interested_leads'),
                days=kwargs.get('days', 7)
            )
            return json.dumps({"success": True, **result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    async def _get_lead_weekly_summary(self, **kwargs) -> str:
        """Get weekly lead summary."""
        try:
            config = Config.from_env()
            result = await asyncio.to_thread(
                leads.get_weekly_summary,
                sheet_url=config.lead_sheets_url,
                instantly_gid=config.lead_sheets_gid_instantly,
                bison_gid=config.lead_sheets_gid_bison
            )
            return json.dumps({"success": True, **result}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
