#!/usr/bin/env python3
"""
Remote MCP Server - Exposes all tools via FastAPI with dual transport support.

Supports both:
- Modern Transport (2025-03-26): Single POST /mcp endpoint with Mcp-Session-Id header
- Legacy Transport (2024-11-05): GET /mcp (SSE stream) + POST /messages (requests)
"""

import sys
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

import os
import asyncio
import logging
import inspect
import json
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from uuid import uuid4

from fastapi import FastAPI, Request, Header, Query, HTTPException, Form
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette import EventSourceResponse

# Import the existing MCP server instance from server.py
# This gives us access to all 82 tools already registered
import server

# Import Database and RequestContext for multi-tenant support
from database import Database
from request_context import RequestContext, create_request_context

# OAuth imports
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

# Stripe imports
import stripe

# Load environment variables
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ===========================================================================
# SESSION MANAGEMENT
# ===========================================================================

@dataclass
class MCPSession:
    """Session data for MCP connections."""
    session_id: str
    created_at: datetime
    last_activity: datetime
    transport_type: str  # "sse" or "streamable_http"
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    user_context: Optional[RequestContext] = None  # User-specific API clients for multi-tenant

    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity = datetime.now()


# Session storage
sessions: Dict[str, MCPSession] = {}

# OAuth state storage (for CSRF protection)
oauth_states: Dict[str, Dict[str, Any]] = {}


def validate_redirect_url(redirect: Optional[str]) -> str:
    """
    Validate and sanitize redirect URL for OAuth flow.

    Security: Only allows internal paths, prevents open redirect vulnerabilities.

    Args:
        redirect: Redirect path from user input

    Returns:
        Validated redirect path or default '/dashboard'
    """
    # Default to dashboard if no redirect
    if not redirect:
        return '/dashboard'

    # Strip whitespace
    redirect = redirect.strip()

    # Must start with '/' (internal path only)
    if not redirect.startswith('/'):
        logger.warning(f"Invalid redirect (not internal path): {redirect}")
        return '/dashboard'

    # Block protocol prefixes (http://, https://, //)
    if redirect.startswith(('http://', 'https://', '//')):
        logger.warning(f"Invalid redirect (protocol detected): {redirect}")
        return '/dashboard'

    # Whitelist allowed redirect patterns
    allowed_patterns = [
        '/dashboard',           # Default dashboard
        '/invite/',             # Team invitation pages
        '/settings',            # User settings
        '/subscription'         # Subscription management
    ]

    # Check if redirect starts with any allowed pattern
    is_allowed = any(redirect.startswith(pattern) for pattern in allowed_patterns)

    if not is_allowed:
        logger.warning(f"Invalid redirect (not whitelisted): {redirect}")
        return '/dashboard'

    logger.info(f"Validated redirect: {redirect}")
    return redirect


# ===========================================================================
# RATE LIMITING (Security: Prevent brute force attacks)
# ===========================================================================

@dataclass
class RateLimitBucket:
    """Sliding window rate limiter bucket."""
    attempts: list[datetime] = field(default_factory=list)

    def is_allowed(self, max_attempts: int, window_seconds: int) -> bool:
        """
        Check if request is allowed under rate limit.

        Uses sliding window: only counts attempts within the time window.

        Args:
            max_attempts: Maximum attempts allowed in window
            window_seconds: Time window in seconds

        Returns:
            True if request is allowed, False if rate limited
        """
        now = datetime.now()
        cutoff = now - timedelta(seconds=window_seconds)

        # Remove attempts outside the window
        self.attempts = [attempt for attempt in self.attempts if attempt > cutoff]

        # Check if under limit
        if len(self.attempts) < max_attempts:
            self.attempts.append(now)
            return True

        return False

    def get_retry_after(self, window_seconds: int) -> int:
        """Get seconds until oldest attempt expires (for Retry-After header)."""
        if not self.attempts:
            return 0
        oldest = min(self.attempts)
        retry_after = (oldest + timedelta(seconds=window_seconds) - datetime.now()).total_seconds()
        return max(0, int(retry_after))


class RateLimiter:
    """In-memory rate limiter for authentication endpoints."""

    def __init__(self):
        self.buckets: Dict[str, RateLimitBucket] = {}
        self.cleanup_task: Optional[asyncio.Task] = None

    def check_rate_limit(
        self,
        identifier: str,
        max_attempts: int,
        window_seconds: int
    ) -> tuple[bool, int]:
        """
        Check if request is allowed under rate limit.

        Args:
            identifier: IP address or user identifier
            max_attempts: Maximum attempts allowed
            window_seconds: Time window in seconds

        Returns:
            (allowed, retry_after): Boolean if allowed, seconds until retry if blocked
        """
        if identifier not in self.buckets:
            self.buckets[identifier] = RateLimitBucket()

        bucket = self.buckets[identifier]
        allowed = bucket.is_allowed(max_attempts, window_seconds)
        retry_after = 0 if allowed else bucket.get_retry_after(window_seconds)

        return allowed, retry_after

    async def cleanup_old_buckets(self):
        """Background task to cleanup rate limit buckets with no recent attempts."""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                now = datetime.now()
                cutoff = now - timedelta(hours=1)

                # Remove buckets with no attempts in last hour
                stale_identifiers = [
                    identifier for identifier, bucket in self.buckets.items()
                    if not bucket.attempts or max(bucket.attempts) < cutoff
                ]

                for identifier in stale_identifiers:
                    del self.buckets[identifier]

                if stale_identifiers:
                    logger.info(f"Cleaned up {len(stale_identifiers)} stale rate limit buckets")

            except Exception as e:
                logger.error(f"Error in rate limiter cleanup task: {e}")


# Global rate limiter instance
rate_limiter = RateLimiter()


def get_client_ip(request: Request) -> str:
    """
    Extract client IP address from request.

    Handles proxies (X-Forwarded-For, X-Real-IP) and direct connections.
    """
    # Check proxy headers first (for Railway, Cloudflare, etc.)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can be comma-separated list, take first (client IP)
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Fallback to direct connection IP
    if request.client:
        return request.client.host

    return "unknown"


async def cleanup_stale_sessions():
    """
    Background task to cleanup inactive sessions.

    Removes sessions inactive for more than 5 minutes to prevent memory leaks.
    """
    while True:
        try:
            await asyncio.sleep(60)  # Check every minute
            now = datetime.now()

            # Find stale sessions (inactive for 5+ minutes)
            stale_session_ids = [
                sid for sid, session in sessions.items()
                if (now - session.last_activity).total_seconds() > 300
            ]

            # Remove stale sessions
            for sid in stale_session_ids:
                del sessions[sid]
                logger.info(f"Cleaned up stale session: {sid}")

        except Exception as e:
            logger.error(f"Error in session cleanup task: {e}")


def create_session(transport_type: str, user_context: Optional[RequestContext] = None) -> str:
    """
    Create a new MCP session.

    Args:
        transport_type: "sse" or "streamable_http"
        user_context: Optional user-specific API clients for multi-tenant mode

    Returns:
        session_id: UUID string
    """
    session_id = str(uuid4())
    sessions[session_id] = MCPSession(
        session_id=session_id,
        created_at=datetime.now(),
        last_activity=datetime.now(),
        transport_type=transport_type,
        user_context=user_context
    )
    logger.info(f"Created {transport_type} session: {session_id}")
    return session_id


# ===========================================================================
# TOOL EXECUTION
# ===========================================================================

def get_tool_schema(tool_name: str, tool_func) -> Dict[str, Any]:
    """
    Generate MCP tool schema from function signature.

    Args:
        tool_name: Name of the tool
        tool_func: Tool function object

    Returns:
        Tool schema dict compatible with MCP protocol
    """
    # Extract description from docstring
    description = "No description available"
    if tool_func.__doc__:
        doc_lines = tool_func.__doc__.strip().split('\n')
        for line in doc_lines:
            line = line.strip()
            if line:
                description = line
                break

    # Build input schema from function signature
    input_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    sig = inspect.signature(tool_func)
    for param_name, param in sig.parameters.items():
        # Skip self/cls
        if param_name in ('self', 'cls'):
            continue

        # Determine JSON schema type from Python type annotation
        param_type = "string"  # default
        if param.annotation != inspect.Parameter.empty:
            annotation = param.annotation
            if annotation == int:
                param_type = "integer"
            elif annotation == float:
                param_type = "number"
            elif annotation == bool:
                param_type = "boolean"
            elif annotation == list:
                param_type = "array"
            elif annotation == dict:
                param_type = "object"

        param_schema = {"type": param_type}

        # Add default value if present
        if param.default != inspect.Parameter.empty:
            param_schema["default"] = param.default
        else:
            # No default = required parameter
            input_schema["required"].append(param_name)

        input_schema["properties"][param_name] = param_schema

    return {
        "name": tool_name,
        "description": description,
        "inputSchema": input_schema
    }


async def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """
    Execute a tool through FastMCP instance.

    Args:
        tool_name: Name of the tool to execute
        arguments: Dict of arguments to pass to the tool

    Returns:
        Tool result as string

    Raises:
        ValueError: If tool not found or invalid arguments
        RuntimeError: If tool execution fails
    """
    # Use FastMCP's call_tool method instead of accessing _tools directly
    try:
        result = await server.mcp.call_tool(tool_name, arguments)

        # Format result as string
        if isinstance(result, str):
            return result
        elif isinstance(result, (dict, list)):
            return json.dumps(result, indent=2)
        else:
            return str(result)

    except KeyError:
        raise ValueError(f"Tool not found: {tool_name}")
    except TypeError as e:
        # Parameter mismatch error
        raise ValueError(f"Invalid arguments for {tool_name}: {e}")
    except Exception as e:
        # Tool execution error
        logger.error(f"Tool {tool_name} execution failed: {e}", exc_info=True)
        raise RuntimeError(f"Tool execution failed: {e}")


async def execute_tool_with_context(
    tool_name: str,
    arguments: Dict[str, Any],
    ctx: RequestContext,
    request_id: int
) -> dict:
    """
    Execute a tool with user-specific API clients.

    This function temporarily replaces the global clients with user-specific
    clients before executing the tool, then restores the original clients.

    This is a quick MVP approach. For production, tools should be refactored
    to accept RequestContext as a parameter.

    Args:
        tool_name: Name of the tool to execute
        arguments: Dict of arguments to pass to the tool
        ctx: RequestContext with user-specific API clients
        request_id: JSON-RPC request ID

    Returns:
        JSON-RPC response dict with tool result or error

    Note:
        Uses global variable replacement as a temporary solution for MVP.
        Tools will use ctx.gmail_client, ctx.calendar_client, etc.
    """
    import server as server_module  # Import to access global clients

    try:
        # Store original global clients
        original_gmail = server_module.gmail_client
        original_calendar = server_module.calendar_client
        original_docs = server_module.docs_client
        original_sheets = server_module.sheets_client
        original_fathom = server_module.fathom_client
        original_instantly = server_module.instantly_api_key

        # Temporarily replace with user's clients
        server_module.gmail_client = ctx.gmail_client
        server_module.calendar_client = ctx.calendar_client
        server_module.docs_client = ctx.docs_client
        server_module.sheets_client = ctx.sheets_client
        server_module.fathom_client = ctx.fathom_client
        server_module.instantly_api_key = ctx.api_keys.get('instantly')

        logger.info(f"Executing tool '{tool_name}' for user {ctx.email}")

        # Execute tool (will use injected user-specific clients)
        result = await server.mcp.call_tool(tool_name, arguments)

        # Restore original global clients
        server_module.gmail_client = original_gmail
        server_module.calendar_client = original_calendar
        server_module.docs_client = original_docs
        server_module.sheets_client = original_sheets
        server_module.fathom_client = original_fathom
        server_module.instantly_api_key = original_instantly

        # Format result
        if isinstance(result, str):
            content = result
        elif isinstance(result, (dict, list)):
            content = json.dumps(result, indent=2)
        else:
            content = str(result)

        logger.info(f"Tool '{tool_name}' executed successfully for user {ctx.email}")

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": content}]
            }
        }

    except Exception as e:
        # Restore original clients even on error
        try:
            server_module.gmail_client = original_gmail
            server_module.calendar_client = original_calendar
            server_module.docs_client = original_docs
            server_module.sheets_client = original_sheets
            server_module.fathom_client = original_fathom
        except:
            pass

        logger.error(f"Tool execution error for '{tool_name}' (user: {ctx.email}): {e}", exc_info=True)

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32603,
                "message": f"Tool execution failed: {str(e)}"
            }
        }


# ===========================================================================
# JSON-RPC REQUEST HANDLER
# ===========================================================================

async def handle_jsonrpc_request(
    body: Dict[str, Any],
    session_id: Optional[str] = None,
    ctx: Optional[RequestContext] = None
) -> Dict[str, Any]:
    """
    Handle JSON-RPC request per MCP protocol.

    Supports methods:
    - initialize: Server capabilities
    - tools/list: List available tools
    - tools/call: Execute a tool

    Args:
        body: JSON-RPC request dict
        session_id: Optional session ID for tracking
        ctx: Optional RequestContext for multi-tenant user isolation

    Returns:
        JSON-RPC response dict
    """
    method = body.get("method")
    params = body.get("params", {})
    request_id = body.get("id")

    if ctx:
        logger.info(f"Handling {method} for user {ctx.email} (session: {session_id})")
    else:
        logger.info(f"Handling {method} (session: {session_id})")

    try:
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": server.config.server_name,
                        "version": "1.0.0"
                    }
                }
            }

        elif method == "tools/list":
            # Use FastMCP's list_tools method
            tool_list = await server.mcp.list_tools()

            # Convert Tool objects to MCP protocol format
            tools = []
            for tool in tool_list:
                tool_schema = {
                    "name": tool.name,
                    "description": tool.description or "No description available",
                    "inputSchema": tool.inputSchema
                }
                tools.append(tool_schema)

            logger.info(f"tools/list called - total tools before filtering: {len(tools)}, ctx exists: {ctx is not None}")

            # Helper function to map tool names to categories
            def get_tool_category(tool_name):
                """Determine which category a tool belongs to based on its name."""
                tool_name_lower = tool_name.lower()
                # Check in order of specificity to avoid conflicts
                if 'sheet' in tool_name_lower:
                    return 'sheets'
                elif 'doc' in tool_name_lower:  # Must come after sheets check
                    return 'docs'
                elif any(x in tool_name_lower for x in ['email', 'gmail', 'label', 'draft', 'send', 'thread', 'inbox', 'unreplied']):
                    return 'gmail'
                elif any(x in tool_name_lower for x in ['calendar', 'event', 'availability']):
                    return 'calendar'
                elif 'fathom' in tool_name_lower:
                    return 'fathom'
                elif 'bison' in tool_name_lower:
                    return 'bison'
                elif 'instantly' in tool_name_lower:
                    return 'instantly'
                # For multi-platform tools, require explicit subscription to either
                else:
                    # Return None for uncategorized tools - they won't show
                    return None

            # Filter by user's enabled tool categories (if applicable)
            if ctx:
                enabled_categories = ctx.enabled_tool_categories
                logger.info(f"DEBUG enabled_tool_categories: {enabled_categories}, active_subscriptions: {ctx.active_subscriptions}")
                if enabled_categories is not None:  # None = show all, [] or [...] = filter
                    # Filter tools by enabled categories
                    if enabled_categories == []:
                        # Empty list = no tools
                        tools = []
                    else:
                        # Filter to only enabled categories
                        logger.info(f"DEBUG Before enabled_categories filter: {len(tools)} tools")
                        filtered_tools = []
                        for tool in tools:
                            category = get_tool_category(tool['name'])
                            if category is None or category in enabled_categories:
                                filtered_tools.append(tool)
                        tools = filtered_tools
                        logger.info(f"DEBUG After enabled_categories filter: {len(tools)} tools")

                # Filter by active subscriptions (payment enforcement)
                active_subscriptions = ctx.active_subscriptions
                if active_subscriptions is not None and len(active_subscriptions) > 0:
                    # User has some subscriptions - only show subscribed categories
                    logger.info(f"DEBUG Before subscription filter: {len(tools)} tools")
                    # DEBUG: Show sample tool names
                    sample_tools = [t['name'] for t in tools[:15]]
                    logger.info(f"DEBUG Sample tools going into subscription filter: {sample_tools}")
                    subscription_filtered_tools = []
                    # DEBUG: Track categorization
                    categorized = {}
                    uncategorized = []
                    for tool in tools:
                        category = get_tool_category(tool['name'])
                        if category:
                            categorized[category] = categorized.get(category, 0) + 1
                        else:
                            uncategorized.append(tool['name'])
                        # ONLY allow tools that match subscribed categories (no uncategorized tools)
                        if category is not None and category in active_subscriptions:
                            subscription_filtered_tools.append(tool)
                    tools = subscription_filtered_tools
                    logger.info(f"Filtered to subscribed categories: {active_subscriptions}, showing {len(tools)} tools")
                    logger.info(f"DEBUG categorization: {categorized}")
                    if uncategorized:
                        logger.info(f"DEBUG uncategorized tools: {uncategorized[:10]}")
                elif active_subscriptions == []:
                    # User has no active subscriptions - show no tools
                    tools = []
                    logger.warning(f"User {ctx.email} has no active subscriptions - blocking all tools")

            logger.info(f"Listed {len(tools)} tools")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": tools
                }
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if not tool_name:
                raise ValueError("Missing tool name")

            # Track execution time for analytics
            import time
            import traceback
            start_time = time.time()

            try:
                # If multi-tenant context provided, use per-user clients
                if ctx:
                    # Determine tool category
                    def get_tool_category(tool_name):
                        """Determine which category a tool belongs to based on its name."""
                        tool_name_lower = tool_name.lower()
                        if any(x in tool_name_lower for x in ['email', 'gmail', 'label', 'draft', 'send', 'search']):
                            return 'gmail'
                        elif any(x in tool_name_lower for x in ['calendar', 'event', 'availability']):
                            return 'calendar'
                        elif 'doc' in tool_name_lower and 'google' not in tool_name_lower:
                            return 'docs'
                        elif 'sheet' in tool_name_lower:
                            return 'sheets'
                        elif 'fathom' in tool_name_lower:
                            return 'fathom'
                        elif 'bison' in tool_name_lower:
                            return 'bison'
                        elif 'instantly' in tool_name_lower or any(x in tool_name_lower for x in ['campaign', 'lead']):
                            return 'instantly'
                        return 'general'  # Default category

                    tool_category = get_tool_category(tool_name)

                    # Check usage limits and permissions
                    if hasattr(server, 'database') and server.database:
                        permission = server.database.can_use_tool(ctx.user_id, tool_category)

                        if not permission['allowed']:
                            # Return error with upgrade prompt
                            return {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "error": {
                                    "code": -32000,
                                    "message": permission['message'],
                                    "data": {
                                        "reason": permission['reason'],
                                        "daily_usage": permission['daily_usage'],
                                        "daily_limit": permission['daily_limit'],
                                        "upgrade_url": f"/dashboard?session_token={ctx.session_token}"
                                    }
                                }
                            }

                        # Increment usage counter
                        try:
                            new_count = server.database.increment_usage(ctx.user_id)
                            logger.info(f"User {ctx.email} usage: {new_count} calls today (reason: {permission['reason']})")
                        except Exception as e:
                            logger.warning(f"Failed to increment usage: {e}")

                    # Execute with user-specific clients
                    response = await execute_tool_with_context(
                        tool_name=tool_name,
                        arguments=arguments,
                        ctx=ctx,
                        request_id=request_id
                    )

                    # Log usage to database
                    if hasattr(server, 'database') and server.database:
                        elapsed_ms = int((time.time() - start_time) * 1000)
                        try:
                            server.database.log_usage(
                                user_id=ctx.user_id,
                                tool_name=tool_name,
                                method="tools/call",
                                success=True,
                                response_time_ms=elapsed_ms,
                                request_params=arguments,
                                response_data=response
                            )
                        except Exception as e:
                            logger.warning(f"Failed to log usage: {e}")

                    return response

                else:
                    # Legacy single-user mode
                    result = await execute_tool(tool_name, arguments)

                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
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
                # Log failed execution
                if ctx and hasattr(server, 'database') and server.database:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    try:
                        server.database.log_usage(
                            user_id=ctx.user_id,
                            tool_name=tool_name,
                            method="tools/call",
                            success=False,
                            error_message=str(e),
                            response_time_ms=elapsed_ms,
                            request_params=arguments,
                            error_type=type(e).__name__,
                            stack_trace=traceback.format_exc()
                        )
                    except Exception as log_err:
                        logger.warning(f"Failed to log error usage: {log_err}")

                raise  # Re-raise to be handled by outer try/except

        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }

    except ValueError as e:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32602,
                "message": f"Invalid params: {str(e)}"
            }
        }
    except Exception as e:
        logger.error(f"Request handling error: {e}", exc_info=True)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }


# ===========================================================================
# AUTHENTICATION MIDDLEWARE
# ===========================================================================

from fastapi import Depends


async def get_request_context(
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Query(None)
) -> RequestContext:
    """
    FastAPI dependency that extracts session token and creates per-user context.

    This middleware:
    1. Extracts session token from Authorization header OR query parameter
    2. Validates the session token format
    3. Looks up the user in the database
    4. Creates user-specific API clients (Gmail, Calendar, Docs, Sheets, Fathom)
    5. Returns a RequestContext with all user data and clients

    Args:
        authorization: Authorization header (format: "Bearer <session_token>")
        session_token: Session token as query parameter (alternative to header)

    Returns:
        RequestContext with user-specific API clients

    Raises:
        HTTPException(401): If authorization is missing, invalid, or expired
    """
    # Extract token from header or query parameter
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]  # Strip "Bearer "
    elif session_token:
        token = session_token

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing session token. Provide via Authorization header or ?session_token= parameter."
        )

    # Check if database is initialized
    if not hasattr(server, 'database') or server.database is None:
        raise HTTPException(
            status_code=503,
            detail="Multi-tenant mode not available. Database not initialized."
        )

    # Create user-specific clients from database
    ctx = await create_request_context(
        database=server.database,
        session_token=token,
        config=server.config
    )

    return ctx


# ===========================================================================
# FASTAPI APPLICATION
# ===========================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events."""
    logger.info("=" * 60)
    logger.info("Starting Remote MCP Server")
    logger.info("=" * 60)
    logger.info(f"Server name: {server.config.server_name}")

    # Initialize clients on startup (for backwards compatibility with single-user mode)
    # Skip if TOKEN_ENCRYPTION_KEY is set (multi-tenant mode)
    if not os.getenv("TOKEN_ENCRYPTION_KEY"):
        try:
            server.initialize_clients()
            logger.info("✓ Clients initialized successfully (single-user mode)")
        except Exception as e:
            logger.error(f"✗ Failed to initialize clients: {e}")
            logger.warning("Server will start but tools may not work until auth is set up")
    else:
        logger.info("✓ Multi-tenant mode enabled - clients will be created per-request")
        # Initialize EmailAnalyzer globally (doesn't need credentials)
        from email_analyzer import EmailAnalyzer
        server.email_analyzer = EmailAnalyzer()
        logger.info("✓ EmailAnalyzer initialized for multi-tenant mode")

    # Initialize database for multi-tenant support
    try:
        encryption_key = os.getenv("TOKEN_ENCRYPTION_KEY")
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        if encryption_key and supabase_url and supabase_key:
            # Use Supabase PostgreSQL
            server.database = Database(supabase_url, supabase_key, encryption_key)
            logger.info(f"✓ Connected to Supabase database at {supabase_url}")
        else:
            # Log which variables are missing
            missing = []
            if not encryption_key:
                missing.append("TOKEN_ENCRYPTION_KEY")
            if not supabase_url:
                missing.append("SUPABASE_URL")
            if not supabase_key:
                missing.append("SUPABASE_SERVICE_ROLE_KEY")

            logger.error(f"✗ Missing required environment variables: {', '.join(missing)}")
            logger.warning("⚠ Multi-tenant features disabled - server will not work")
            server.database = None
    except Exception as e:
        logger.error(f"✗ Failed to initialize database: {e}")
        import traceback
        logger.error(traceback.format_exc())
        logger.warning("Server will start in single-user mode only")
        server.database = None

    # Count registered tools
    tools = await server.mcp.list_tools()
    tool_count = len(tools)
    logger.info(f"✓ {tool_count} tools registered and ready")

    # Start background cleanup tasks
    session_cleanup_task = asyncio.create_task(cleanup_stale_sessions())
    rate_limiter_cleanup_task = asyncio.create_task(rate_limiter.cleanup_old_buckets())
    logger.info("✓ Background cleanup tasks started")
    logger.info("=" * 60)

    yield

    # Cleanup on shutdown
    logger.info("Shutting down Remote MCP Server...")
    session_cleanup_task.cancel()
    rate_limiter_cleanup_task.cancel()
    sessions.clear()
    rate_limiter.buckets.clear()
    logger.info("✓ Cleanup complete")


# Create FastAPI app
app = FastAPI(
    title="LeadGenJay MCP Remote Server",
    description="Remote MCP server exposing 82+ tools for Gmail, Calendar, Docs, Sheets, and more",
    version="1.0.0",
    lifespan=lifespan
)


# Build secure CORS allowed origins list
allowed_origins = [
    "http://localhost:8080",
    "http://localhost:8000",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8000",
]

# Add Railway deployment URL if available
railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
if railway_domain:
    allowed_origins.append(f"https://{railway_domain}")

# Add custom allowed origins from environment (comma-separated)
custom_origins = os.getenv("ALLOWED_ORIGINS", "")
if custom_origins:
    allowed_origins.extend([origin.strip() for origin in custom_origins.split(",") if origin.strip()])

logger.info(f"CORS allowed origins: {allowed_origins}")

# Add CORS middleware (CRITICAL for web-based MCP clients)
# SECURITY: Never use allow_origins=["*"] with allow_credentials=True
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id", "Content-Type"]  # Proper casing per MCP spec
)


# ===========================================================================
# HEALTH & INFO ENDPOINTS
# ===========================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint for Railway and monitoring."""
    try:
        tools = await server.mcp.list_tools()
        tool_count = len(tools)
    except Exception:
        tool_count = 0

    return JSONResponse({
        "status": "healthy",
        "server_name": server.config.server_name,
        "tools_count": tool_count,
        "sessions_active": len(sessions),
        "version": "1.0.0"
    })


@app.get("/")
async def root():
    """Landing page - Product-focused marketing."""
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Most Powerful MCP Server for Claude Desktop | 85 Tools Across Gmail, Calendar, Docs & More</title>
    <meta name="description" content="Transform Claude Desktop into your complete workspace. 84 enterprise-grade tools with multi-tenant security, per-user OAuth, and instant setup. Free 3-day trial.">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
            line-height: 1.6;
            color: #1a202c;
            background: #ffffff;
        }

        /* Hero Section - Enhanced */
        .hero {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 100px 20px 80px;
            text-align: center;
            position: relative;
            overflow: hidden;
        }

        .hero::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 120"><path d="M0,0 L1200,0 L1200,100 Q600,20 0,100 Z" fill="rgba(255,255,255,0.05)"/></svg>') no-repeat bottom;
            background-size: cover;
            opacity: 0.5;
        }

        .hero-content {
            max-width: 1000px;
            margin: 0 auto;
            position: relative;
            z-index: 1;
        }

        .hero-badge {
            display: inline-block;
            background: rgba(255, 255, 255, 0.2);
            padding: 8px 20px;
            border-radius: 30px;
            font-size: 0.9rem;
            font-weight: 600;
            margin-bottom: 25px;
            border: 1px solid rgba(255, 255, 255, 0.3);
        }

        h1 {
            font-size: 4rem;
            font-weight: 900;
            margin-bottom: 25px;
            line-height: 1.1;
            letter-spacing: -0.02em;
        }

        h1 .highlight {
            background: linear-gradient(120deg, #fff 0%, #a8d5ff 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .subtitle {
            font-size: 1.4rem;
            margin-bottom: 20px;
            opacity: 0.95;
            font-weight: 400;
            line-height: 1.5;
            max-width: 800px;
            margin-left: auto;
            margin-right: auto;
        }

        .hero-stats {
            display: flex;
            gap: 40px;
            justify-content: center;
            align-items: center;
            flex-wrap: wrap;
            margin: 30px 0 40px;
        }

        .stat {
            text-align: center;
        }

        .stat-number {
            font-size: 2.5rem;
            font-weight: 800;
            display: block;
            line-height: 1;
        }

        .stat-label {
            font-size: 0.9rem;
            opacity: 0.9;
            margin-top: 5px;
        }

        .trial-badge {
            display: inline-block;
            background: rgba(16, 185, 129, 0.9);
            padding: 12px 28px;
            border-radius: 30px;
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 30px;
            border: 2px solid rgba(255, 255, 255, 0.3);
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
        }

        .cta-buttons {
            display: flex;
            gap: 15px;
            justify-content: center;
            align-items: center;
            flex-wrap: wrap;
        }

        .cta-button {
            display: inline-block;
            background: white;
            color: #667eea;
            padding: 22px 55px;
            font-size: 1.3rem;
            font-weight: 700;
            text-decoration: none;
            border-radius: 50px;
            transition: all 0.3s;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }

        .cta-button:hover {
            transform: translateY(-3px);
            box-shadow: 0 15px 40px rgba(0,0,0,0.3);
        }

        .cta-button-secondary {
            display: inline-block;
            background: transparent;
            color: white;
            padding: 22px 55px;
            font-size: 1.3rem;
            font-weight: 700;
            text-decoration: none;
            border-radius: 50px;
            transition: all 0.3s;
            border: 3px solid white;
        }

        .cta-button-secondary:hover {
            background: rgba(255, 255, 255, 0.15);
            transform: translateY(-3px);
        }

        /* Problem/Solution Section */
        .problem-solution {
            background: #f7fafc;
            padding: 80px 20px;
        }

        .problem-solution .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0;
        }

        .problem-solution h2 {
            font-size: 2.8rem;
            font-weight: 800;
            text-align: center;
            margin-bottom: 50px;
            color: #1a202c;
        }

        .comparison {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 40px;
            margin-bottom: 60px;
        }

        .comparison-card {
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        }

        .comparison-card.problem {
            border: 3px solid #fca5a5;
        }

        .comparison-card.solution {
            border: 3px solid #10b981;
            background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
        }

        .comparison-card h3 {
            font-size: 1.8rem;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .comparison-card ul {
            list-style: none;
            margin: 0;
        }

        .comparison-card ul li {
            padding: 12px 0;
            font-size: 1.05rem;
            display: flex;
            align-items: flex-start;
            gap: 12px;
        }

        .comparison-card.problem ul li:before {
            content: "❌";
            flex-shrink: 0;
            margin-top: 2px;
        }

        .comparison-card.solution ul li:before {
            content: "✅";
            flex-shrink: 0;
            margin-top: 2px;
        }

        /* Enterprise Features Section */
        .enterprise-features {
            background: white;
            padding: 80px 20px;
        }

        .enterprise-features h2 {
            font-size: 2.8rem;
            font-weight: 800;
            text-align: center;
            margin-bottom: 20px;
            color: #1a202c;
        }

        .enterprise-features .subtitle-text {
            text-align: center;
            font-size: 1.2rem;
            color: #718096;
            margin-bottom: 60px;
        }

        .features-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 30px;
            max-width: 1200px;
            margin: 0 auto;
        }

        .feature-card {
            background: #f7fafc;
            border-radius: 16px;
            padding: 35px;
            transition: all 0.3s;
            border: 2px solid transparent;
        }

        .feature-card:hover {
            border-color: #667eea;
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(102, 126, 234, 0.15);
            background: white;
        }

        .feature-icon {
            font-size: 2.5rem;
            margin-bottom: 15px;
        }

        .feature-card h3 {
            font-size: 1.3rem;
            font-weight: 700;
            margin-bottom: 10px;
            color: #1a202c;
        }

        .feature-card p {
            color: #4a5568;
            font-size: 0.95rem;
            line-height: 1.6;
        }

        /* Container */
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 80px 20px;
        }

        /* Section Headers */
        .section-header {
            text-align: center;
            margin-bottom: 60px;
        }

        .section-header h2 {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 15px;
            color: #1a202c;
        }

        .section-header p {
            font-size: 1.2rem;
            color: #718096;
        }

        /* Tool Categories */
        .tool-categories {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 30px;
            margin-bottom: 80px;
        }

        .category-card {
            background: white;
            border: 2px solid #e2e8f0;
            border-radius: 16px;
            padding: 35px;
            transition: all 0.3s;
        }

        .category-card:hover {
            border-color: #667eea;
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(102, 126, 234, 0.15);
        }

        .category-icon {
            font-size: 3rem;
            margin-bottom: 20px;
        }

        .category-card h3 {
            font-size: 1.8rem;
            font-weight: 700;
            margin-bottom: 15px;
            color: #1a202c;
        }

        .tool-count {
            color: #667eea;
            font-weight: 600;
            font-size: 1.1rem;
            margin-bottom: 20px;
        }

        .tool-list {
            list-style: none;
            margin-bottom: 20px;
        }

        .tool-list li {
            padding: 8px 0;
            color: #4a5568;
            font-size: 0.95rem;
            border-bottom: 1px solid #f7fafc;
        }

        .tool-list li:before {
            content: "✓ ";
            color: #10b981;
            font-weight: 700;
            margin-right: 8px;
        }

        .category-price {
            font-size: 1.3rem;
            font-weight: 700;
            color: #667eea;
            margin-top: 20px;
        }

        /* How It Works */
        .how-it-works {
            background: #f7fafc;
            padding: 80px 20px;
        }

        .steps {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 40px;
            max-width: 1200px;
            margin: 0 auto;
        }

        .step {
            text-align: center;
        }

        .step-number {
            width: 70px;
            height: 70px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.8rem;
            font-weight: 700;
            margin: 0 auto 20px;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
        }

        .step h3 {
            font-size: 1.3rem;
            margin-bottom: 10px;
            color: #1a202c;
        }

        .step p {
            color: #718096;
            font-size: 1rem;
        }

        /* Pricing */
        .pricing-section {
            background: white;
            padding: 80px 20px;
        }

        .pricing-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 30px;
            max-width: 900px;
            margin: 0 auto;
        }

        .pricing-card {
            background: white;
            border: 2px solid #e2e8f0;
            border-radius: 16px;
            padding: 40px 30px;
            text-align: center;
            transition: all 0.3s;
        }

        .pricing-card.featured {
            border-color: #667eea;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            transform: scale(1.05);
        }

        .pricing-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }

        .plan-name {
            font-size: 1.5rem;
            font-weight: 700;
            margin-bottom: 15px;
        }

        .plan-price {
            font-size: 3rem;
            font-weight: 800;
            margin-bottom: 10px;
        }

        .plan-period {
            font-size: 1rem;
            opacity: 0.7;
            margin-bottom: 30px;
        }

        .plan-features {
            list-style: none;
            margin-bottom: 30px;
            text-align: left;
        }

        .plan-features li {
            padding: 10px 0;
            font-size: 0.95rem;
        }

        .plan-features li:before {
            content: "✓ ";
            color: #10b981;
            font-weight: 700;
            margin-right: 8px;
        }

        .pricing-card.featured .plan-features li:before {
            color: white;
        }

        .plan-button {
            display: inline-block;
            padding: 15px 40px;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 30px;
            font-weight: 600;
            transition: all 0.3s;
        }

        .plan-button:hover {
            background: #5568d3;
            transform: translateY(-2px);
        }

        .pricing-card.featured .plan-button {
            background: white;
            color: #667eea;
        }

        /* Footer CTA */
        .footer-cta {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 80px 20px;
            text-align: center;
        }

        .footer-cta h2 {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 20px;
        }

        .footer-cta p {
            font-size: 1.3rem;
            margin-bottom: 40px;
            opacity: 0.95;
        }

        /* See Possibilities Button */
        .possibilities-button {
            display: inline-block;
            margin-top: 15px;
            padding: 12px 24px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 30px;
            font-weight: 600;
            font-size: 0.95rem;
            cursor: pointer;
            transition: all 0.3s;
            text-decoration: none;
        }

        .possibilities-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }

        /* Modal Styles */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            padding: 20px;
        }

        .modal-overlay.active {
            display: flex;
        }

        .modal-content {
            background: white;
            border-radius: 20px;
            max-width: 800px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
            position: relative;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        }

        .modal-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 20px 20px 0 0;
            position: relative;
        }

        .modal-header h2 {
            font-size: 2rem;
            margin-bottom: 10px;
        }

        .modal-header p {
            opacity: 0.95;
            font-size: 1.1rem;
        }

        .modal-close {
            position: absolute;
            top: 20px;
            right: 20px;
            background: rgba(255, 255, 255, 0.2);
            border: none;
            color: white;
            font-size: 28px;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
        }

        .modal-close:hover {
            background: rgba(255, 255, 255, 0.3);
            transform: rotate(90deg);
        }

        .modal-body {
            padding: 40px;
        }

        .prompt-section {
            margin-bottom: 35px;
        }

        .prompt-section:last-child {
            margin-bottom: 0;
        }

        .prompt-section h3 {
            font-size: 1.4rem;
            color: #1a202c;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .difficulty-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }

        .difficulty-badge.basic {
            background: #d1fae5;
            color: #065f46;
        }

        .difficulty-badge.intermediate {
            background: #fef3c7;
            color: #92400e;
        }

        .difficulty-badge.advanced {
            background: #ddd6fe;
            color: #5b21b6;
        }

        .prompt-examples {
            list-style: none;
        }

        .prompt-examples li {
            background: #f7fafc;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 10px;
            border-left: 4px solid #667eea;
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 0.9rem;
            color: #2d3748;
        }

        @media (max-width: 768px) {
            h1 {
                font-size: 2.5rem;
            }

            .subtitle {
                font-size: 1.2rem;
            }

            .hero-stats {
                gap: 25px;
            }

            .stat-number {
                font-size: 2rem;
            }

            .comparison {
                grid-template-columns: 1fr;
            }

            .tool-categories {
                grid-template-columns: 1fr;
            }

            .features-grid {
                grid-template-columns: 1fr;
            }

            .steps {
                grid-template-columns: 1fr;
            }

            .pricing-cards {
                grid-template-columns: 1fr;
            }

            .pricing-card.featured {
                transform: scale(1);
            }

            .modal-content {
                max-height: 95vh;
            }

            .modal-header {
                padding: 20px;
            }

            .modal-body {
                padding: 25px;
            }
        }
    </style>
</head>
<body>
    <!-- Hero Section -->
    <div class="hero">
        <div class="hero-content">
            <div class="hero-badge">🚀 The Most Advanced MCP Server for Claude Desktop</div>
            <h1>Turn Claude into Your <span class="highlight">Complete Workspace</span></h1>
            <p class="subtitle">The only MCP server with enterprise-grade security, multi-tenant architecture, and 85 production-ready tools across Gmail, Calendar, Docs, Sheets, Fathom, Instantly, and Bison.</p>

            <div class="hero-stats">
                <div class="stat">
                    <span class="stat-number">84</span>
                    <span class="stat-label">Production Tools</span>
                </div>
                <div class="stat">
                    <span class="stat-number">7</span>
                    <span class="stat-label">Tool Categories</span>
                </div>
                <div class="stat">
                    <span class="stat-number">30s</span>
                    <span class="stat-label">Setup Time</span>
                </div>
                <div class="stat">
                    <span class="stat-number">100%</span>
                    <span class="stat-label">Secure</span>
                </div>
            </div>

            <div class="trial-badge">🎉 3-Day Free Trial • No Credit Card Required</div>
            <div class="cta-buttons">
                <a href="/signup" class="cta-button">Start Free Trial →</a>
                <a href="/login" class="cta-button-secondary">Log In</a>
            </div>
        </div>
    </div>

    <!-- Problem/Solution Section -->
    <div class="problem-solution">
        <div class="container">
            <h2>Stop Context Switching. Start Shipping.</h2>

            <div class="comparison">
                <div class="comparison-card problem">
                    <h3>😫 Without Our Platform</h3>
                    <ul>
                        <li>Switching between 7+ different tools constantly</li>
                        <li>Losing context every time you switch apps</li>
                        <li>Copy-pasting information back and forth</li>
                        <li>Waiting for AI to "re-understand" your workflow</li>
                        <li>Managing multiple logins and credentials</li>
                        <li>Security risks from sharing sensitive data</li>
                    </ul>
                </div>

                <div class="comparison-card solution">
                    <h3>🚀 With Our Platform</h3>
                    <ul>
                        <li>Everything happens inside Claude Desktop</li>
                        <li>AI maintains full context across all tools</li>
                        <li>Natural language commands for everything</li>
                        <li>Instant access to emails, docs, calendars, and more</li>
                        <li>Secure OAuth with per-user credential isolation</li>
                        <li>Enterprise-grade security built-in</li>
                    </ul>
                </div>
            </div>
        </div>
    </div>

    <!-- Enterprise Features Section -->
    <div class="enterprise-features">
        <div class="container">
            <h2>Built Different</h2>
            <p class="subtitle-text">Enterprise-grade architecture that other MCP servers can't match</p>

            <div class="features-grid">
                <div class="feature-card">
                    <div class="feature-icon">🔒</div>
                    <h3>Multi-Tenant Security</h3>
                    <p>True per-user credential isolation. Your data never touches other users. Bank-grade encryption for all stored tokens.</p>
                </div>

                <div class="feature-card">
                    <div class="feature-icon">🎯</div>
                    <h3>Per-User OAuth</h3>
                    <p>Every user authenticates with their own Google account. No shared credentials. Full control over permissions.</p>
                </div>

                <div class="feature-card">
                    <div class="feature-icon">⚡</div>
                    <h3>30-Second Setup</h3>
                    <p>One-click OAuth, copy-paste URL into Claude Desktop, done. No command line. No configuration files. Just works.</p>
                </div>

                <div class="feature-card">
                    <div class="feature-icon">🛡️</div>
                    <h3>Rate Limiting</h3>
                    <p>Built-in protection against brute force attacks. Sliding window rate limiting on all authentication endpoints.</p>
                </div>

                <div class="feature-card">
                    <div class="feature-icon">🌐</div>
                    <h3>Secure CORS</h3>
                    <p>Whitelist-only origin policy prevents CSRF attacks. Your credentials are safe from malicious sites.</p>
                </div>

                <div class="feature-card">
                    <div class="feature-icon">💳</div>
                    <h3>Stripe-Verified Webhooks</h3>
                    <p>Signature verification on all payment webhooks. Impossible to bypass payment or forge subscriptions.</p>
                </div>

                <div class="feature-card">
                    <div class="feature-icon">📊</div>
                    <h3>Usage Analytics</h3>
                    <p>Track tool usage, monitor performance, and understand your workflows. Built-in dashboard for all metrics.</p>
                </div>

                <div class="feature-card">
                    <div class="feature-icon">🔄</div>
                    <h3>Auto-Scaling Ready</h3>
                    <p>Deployed on Railway with automatic scaling. Handles thousands of concurrent users without breaking a sweat.</p>
                </div>
            </div>
        </div>
    </div>

    <!-- Tool Categories Section -->
    <div class="container">
        <div class="section-header">
            <h2>All 85 Tools, Organized by Category</h2>
            <p>Pick and choose the categories you need. Only pay for what you use.</p>
        </div>

        <div class="tool-categories">
            <!-- Gmail Tools -->
            <div class="category-card">
                <div class="category-icon">📧</div>
                <h3>Gmail Tools</h3>
                <div class="tool-count">25 tools included</div>
                <ul class="tool-list">
                    <li>Search emails with advanced filters</li>
                    <li>Read, send, and reply to messages</li>
                    <li>Manage labels and organize inbox</li>
                    <li>Mark as read/unread, archive, delete</li>
                    <li>Extract attachments and metadata</li>
                    <li>Bulk operations and email analysis</li>
                </ul>
                <div class="category-price">$5/month</div>
                <button class="possibilities-button" onclick="showPossibilities('gmail')">⭐ See the Possibilities</button>
            </div>

            <!-- Calendar Tools -->
            <div class="category-card">
                <div class="category-icon">📅</div>
                <h3>Google Calendar</h3>
                <div class="tool-count">15 tools included</div>
                <ul class="tool-list">
                    <li>Create and schedule events</li>
                    <li>Check availability and find meeting times</li>
                    <li>Update and delete events</li>
                    <li>Manage attendees and invitations</li>
                    <li>Set reminders and notifications</li>
                    <li>List upcoming events and agendas</li>
                </ul>
                <div class="category-price">$5/month</div>
                <button class="possibilities-button" onclick="showPossibilities('calendar')">⭐ See the Possibilities</button>
            </div>

            <!-- Google Docs -->
            <div class="category-card">
                <div class="category-icon">📄</div>
                <h3>Google Docs</h3>
                <div class="tool-count">8 tools included</div>
                <ul class="tool-list">
                    <li>Create and edit documents</li>
                    <li>Read and extract document content</li>
                    <li>Format text and paragraphs</li>
                    <li>Insert images and tables</li>
                    <li>Share and manage permissions</li>
                    <li>Export to PDF and other formats</li>
                </ul>
                <div class="category-price">$5/month</div>
                <button class="possibilities-button" onclick="showPossibilities('docs')">⭐ See the Possibilities</button>
            </div>

            <!-- Google Sheets -->
            <div class="category-card">
                <div class="category-icon">📊</div>
                <h3>Google Sheets</h3>
                <div class="tool-count">12 tools included</div>
                <ul class="tool-list">
                    <li>Read and write cell data</li>
                    <li>Create formulas and calculations</li>
                    <li>Format cells and ranges</li>
                    <li>Add charts and visualizations</li>
                    <li>Filter and sort data</li>
                    <li>Move, copy, and delete rows/columns</li>
                </ul>
                <div class="category-price">$5/month</div>
                <button class="possibilities-button" onclick="showPossibilities('sheets')">⭐ See the Possibilities</button>
            </div>

            <!-- Fathom Tools -->
            <div class="category-card">
                <div class="category-icon">🎙️</div>
                <h3>Fathom Meetings</h3>
                <div class="tool-count">11 tools included</div>
                <ul class="tool-list">
                    <li>Access meeting recordings</li>
                    <li>Read AI-generated transcripts</li>
                    <li>Extract key points and action items</li>
                    <li>Search across all meetings</li>
                    <li>Get meeting summaries</li>
                    <li>Analyze conversation insights</li>
                </ul>
                <div class="category-price">$5/month</div>
                <button class="possibilities-button" onclick="showPossibilities('fathom')">⭐ See the Possibilities</button>
            </div>

            <!-- Instantly Tools -->
            <div class="category-card">
                <div class="category-icon">✉️</div>
                <h3>Instantly Campaigns</h3>
                <div class="tool-count">10 tools included</div>
                <ul class="tool-list">
                    <li>Manage email campaigns</li>
                    <li>Track lead status and engagement</li>
                    <li>Add and remove leads</li>
                    <li>Update campaign settings</li>
                    <li>View analytics and performance</li>
                    <li>Automate follow-up sequences</li>
                </ul>
                <div class="category-price">$5/month</div>
                <button class="possibilities-button" onclick="showPossibilities('instantly')">⭐ See the Possibilities</button>
            </div>

            <!-- Bison Tools -->
            <div class="category-card">
                <div class="category-icon">🔍</div>
                <h3>Bison Analysis</h3>
                <div class="tool-count">4 tools included</div>
                <ul class="tool-list">
                    <li>Advanced data analysis</li>
                    <li>Pattern recognition</li>
                    <li>Predictive modeling</li>
                    <li>Custom insights generation</li>
                </ul>
                <div class="category-price">$5/month</div>
                <button class="possibilities-button" onclick="showPossibilities('bison')">⭐ See the Possibilities</button>
            </div>
        </div>
    </div>

    <!-- How It Works -->
    <div class="how-it-works">
        <div class="section-header">
            <h2>How It Works</h2>
            <p>Get started in less than 3 minutes</p>
        </div>
        <div class="steps">
            <div class="step">
                <div class="step-number">1</div>
                <h3>Sign Up Free</h3>
                <p>Connect your Google account with one click. No credit card required for the 3-day trial.</p>
            </div>
            <div class="step">
                <div class="step-number">2</div>
                <h3>Choose Categories</h3>
                <p>Select which tool categories you want. Start with everything free for 3 days.</p>
            </div>
            <div class="step">
                <div class="step-number">3</div>
                <h3>Connect to Claude</h3>
                <p>Add the server URL to Claude Desktop. Copy-paste setup takes 30 seconds.</p>
            </div>
            <div class="step">
                <div class="step-number">4</div>
                <h3>Start Using Tools</h3>
                <p>Ask Claude to check your email, schedule meetings, or create docs. It just works.</p>
            </div>
        </div>
    </div>

    <!-- Pricing -->
    <div class="pricing-section">
        <div class="section-header">
            <h2>Simple, Transparent Pricing</h2>
            <p>Only pay for the categories you need. Cancel anytime.</p>
        </div>
        <div class="pricing-cards">
            <div class="pricing-card">
                <div class="plan-name">Free Trial</div>
                <div class="plan-price">$0</div>
                <div class="plan-period">First 3 days</div>
                <ul class="plan-features">
                    <li>All 85 tools unlocked</li>
                    <li>All 7 categories included</li>
                    <li>No credit card required</li>
                    <li>Full access to test everything</li>
                </ul>
                <a href="/signup" class="plan-button">Start Free Trial</a>
            </div>

            <div class="pricing-card featured">
                <div class="plan-name">Pay-As-You-Go</div>
                <div class="plan-price">$5</div>
                <div class="plan-period">per category/month</div>
                <ul class="plan-features">
                    <li>Subscribe to 1+ categories</li>
                    <li>Unlimited tool usage</li>
                    <li>Cancel anytime</li>
                    <li>No contracts or commitments</li>
                </ul>
                <a href="/signup" class="plan-button">Get Started</a>
            </div>

            <div class="pricing-card">
                <div class="plan-name">Full Access</div>
                <div class="plan-price">$35</div>
                <div class="plan-period">per month</div>
                <ul class="plan-features">
                    <li>All 85 tools included</li>
                    <li>All 7 categories unlocked</li>
                    <li>Best value for power users</li>
                    <li>Everything you need</li>
                </ul>
                <a href="/signup" class="plan-button">Start Free Trial</a>
            </div>
        </div>
    </div>

    <!-- Footer CTA -->
    <div class="footer-cta">
        <h2>Ready to Transform Your Workflow?</h2>
        <p>Join thousands using the most powerful MCP server for Claude Desktop.</p>
        <div class="cta-buttons">
            <a href="/signup" class="cta-button">Start Free Trial →</a>
            <a href="/login" class="cta-button-secondary">Log In</a>
        </div>
    </div>

    <!-- Note: Modal and JavaScript would continue here but keeping this shorter for readability -->
</body>

    <!-- Possibilities Modal -->
    <div id="possibilitiesModal" class="modal-overlay" onclick="closeModal(event)">
        <div class="modal-content" onclick="event.stopPropagation()">
            <div class="modal-header">
                <button class="modal-close" onclick="closeModal()">×</button>
                <h2 id="modalTitle"></h2>
                <p id="modalSubtitle"></p>
                <div style="margin-top: 20px;">
                    <label for="roleSelector" style="font-size: 0.9rem; font-weight: 600; color: hsl(var(--foreground)); margin-bottom: 8px; display: block;">
                        👤 I am a:
                    </label>
                    <select id="roleSelector" onchange="updateExamplesForRole()" style="width: 100%; padding: 10px 12px; border: 2px solid hsl(var(--border)); border-radius: 8px; font-size: 0.95rem; background: white; cursor: pointer; font-weight: 500;">
                        <option value="founder">🚀 Founder / CEO</option>
                        <option value="sales">💼 Sales</option>
                        <option value="marketing">📣 Marketing</option>
                        <option value="ops">⚙️ Operations</option>
                    </select>
                </div>
            </div>
            <div class="modal-body" id="modalBody">
                <!-- Content will be dynamically inserted -->
            </div>
        </div>
    </div>

    <script>
        const toolExamples = {
            gmail: {
                title: '📧 Gmail Possibilities',
                subtitle: 'Real examples of what you can do with Gmail tools',
                byRole: {
                    founder: {
                        title: 'For Founders & CEOs',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Find all investor emails from the past month"',
                                    '"Create labels for Board, Investors, Customers, Team"',
                                    '"Search all emails mentioning \\\'fundraising\\\' or \\\'capital\\\'"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Summarize key questions from investor emails and draft responses"',
                                    '"Search for emails about partnerships and create a status doc with next steps"',
                                    '"Find unanswered emails from VIPs and prioritize responses"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Identify all customer feedback emails and extract common themes for product roadmap"',
                                    '"Analyze all investor communications and create a fundraising progress timeline"',
                                    '"Build an automated system to categorize and prioritize stakeholder emails by urgency"'
                                ]
                            }
                        ]
                    },
                    sales: {
                        title: 'For Sales Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me all emails from prospects who haven\\\'t replied in 7+ days"',
                                    '"Find all emails with \\\'pricing\\\' or \\\'quote\\\'"',
                                    '"Search for emails from hot leads with multiple replies"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Extract deal amounts from pricing emails and create a pipeline spreadsheet"',
                                    '"Find all emails where prospects asked about features and summarize for product team"',
                                    '"Draft personalized follow-up emails for prospects who opened but didn\\\'t reply"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Analyze competitor mentions and map concerns to our positioning strengths"',
                                    '"Build a lead prioritization system based on email engagement patterns"',
                                    '"Create automated follow-up sequences for different prospect personas based on email history"'
                                ]
                            }
                        ]
                    },
                    marketing: {
                        title: 'For Marketing Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Find all partnership inquiry emails"',
                                    '"Search for customer testimonials and success stories"',
                                    '"Identify all press/media requests"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Create a tracking spreadsheet for partnership opportunities with status"',
                                    '"Find event organizer emails and create a calendar of speaking opportunities"',
                                    '"Search customer questions and turn them into blog post ideas"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Extract all competitor mentions and analyze their positioning vs ours across conversations"',
                                    '"Build a content calendar by analyzing customer pain points from support emails"',
                                    '"Create an automated system to capture and categorize media opportunities with response templates"'
                                ]
                            }
                        ]
                    },
                    ops: {
                        title: 'For Operations Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Find all vendor invoices in my inbox"',
                                    '"Search for emails about system issues"',
                                    '"Identify all onboarding-related emails"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Extract invoice dates, amounts, and due dates to create a payment tracker"',
                                    '"Create a bug tracking document from system issue emails"',
                                    '"Extract questions from onboarding emails for an updated FAQ"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Analyze contract emails and build an automated expiration date tracking system"',
                                    '"Create budget forecasts by analyzing vendor and tool request patterns"',
                                    '"Build automated categorization and archiving rules for recurring operational emails"'
                                ]
                            }
                        ]
                    }
                }
            },
            calendar: {
                title: '📅 Calendar Possibilities',
                subtitle: 'Real examples of what you can do with Calendar tools',
                byRole: {
                    founder: {
                        title: 'For Founders & CEOs',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me all my meetings for next week"',
                                    '"Find open slots in my calendar for a 1-hour meeting this week"',
                                    '"List all recurring meetings I have scheduled"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Analyze my calendar and show me how much time I spend in meetings vs focus time"',
                                    '"Show me all 1-on-1s with direct reports that I haven\\\'t had in 30+ days"',
                                    '"Find a 2-hour block every week for strategic planning when I have no conflicts"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Identify which recurring meetings I could delegate or eliminate to free up 5 hours/week"',
                                    '"Schedule monthly board prep time the week before each board meeting"',
                                    '"Create a weekly investor update routine - block Friday afternoons for investor check-ins"'
                                ]
                            }
                        ]
                    },
                    sales: {
                        title: 'For Sales Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me all prospect meetings this week"',
                                    '"Find open slots for customer demos next Tuesday and Wednesday"',
                                    '"List all my scheduled discovery calls this month"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Analyze how many discovery calls vs closing calls I had this month"',
                                    '"Show me all prospect meetings this week and create prep docs with email context"',
                                    '"Schedule follow-up calls with all prospects I met 2 weeks ago"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Block time for prospecting every morning from 9-11am for the next month"',
                                    '"Find all customer meetings and extract key discussion points to update the CRM"',
                                    '"Create automated follow-up booking system for prospects who complete demos"'
                                ]
                            }
                        ]
                    },
                    marketing: {
                        title: 'For Marketing Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me all campaign planning meetings this month"',
                                    '"Find time to schedule a content review meeting with the team"',
                                    '"List all upcoming launch dates on my calendar"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Schedule content planning sessions every Monday at 10am for Q1"',
                                    '"Show me how much time I\\\'m spending in meetings vs actual content creation work"',
                                    '"Find a recurring time slot when the whole marketing team is available for weekly syncs"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Block campaign launch prep time the week before each scheduled launch date"',
                                    '"Schedule quarterly content calendar planning sessions with stakeholders"',
                                    '"Create campaign review meetings 3 days after each major launch automatically"'
                                ]
                            }
                        ]
                    },
                    ops: {
                        title: 'For Operations Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me all system maintenance windows scheduled this month"',
                                    '"Find time to schedule onboarding sessions for new hires next week"',
                                    '"List all vendor review meetings coming up"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Schedule quarterly business reviews with all vendors"',
                                    '"Analyze meeting patterns - which recurring meetings are underattended or could be async"',
                                    '"Find time slots to schedule onboarding sessions for new hires next month"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Block monthly recurring time for system maintenance and updates"',
                                    '"Create monthly all-hands planning time 2 weeks before each meeting"',
                                    '"Schedule regular 1-on-1s with each department head to gather process improvement ideas"'
                                ]
                            }
                        ]
                    }
                }
            },
            docs: {
                title: '📄 Google Docs Possibilities',
                subtitle: 'Real examples of what you can do with Docs tools',
                byRole: {
                    founder: {
                        title: 'For Founders & CEOs',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Create a new meeting notes document for board meetings"',
                                    '"Find all documents with \\\'strategy\\\' in the title"',
                                    '"List all investor update docs from this year"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Create a board meeting deck from my project update docs and key metrics"',
                                    '"Extract all product roadmap decisions from meeting notes and create a master roadmap doc"',
                                    '"Compile all team feedback from 1-on-1 notes into a culture assessment document"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Build an investor update template with sections for metrics, milestones, asks, and challenges"',
                                    '"Create a company strategy doc by pulling key points from planning meeting notes"',
                                    '"Draft a hiring plan document based on all the \\\'team needs\\\' mentions in my project docs"'
                                ]
                            }
                        ]
                    },
                    sales: {
                        title: 'For Sales Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Create a new prospect meeting notes document"',
                                    '"Find all call notes from last week"',
                                    '"List all proposal documents I\\\'ve created"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Create a sales battlecard from competitor intel in my various note docs"',
                                    '"Extract all customer objections from call notes and create an objection handling guide"',
                                    '"Compile customer success stories from account notes into case study drafts"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Build a proposal template with pricing, case studies, and ROI calculations"',
                                    '"Create a prospect research template for pre-meeting prep"',
                                    '"Build a new customer onboarding checklist based on all my handoff notes"'
                                ]
                            }
                        ]
                    },
                    marketing: {
                        title: 'For Marketing Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Create a new campaign brief document"',
                                    '"Find all blog post drafts from this quarter"',
                                    '"List all brand messaging documents"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Create a content calendar doc pulling blog ideas from brainstorming notes"',
                                    '"Extract key customer quotes from interview notes and organize by theme"',
                                    '"Compile partner announcement drafts from partnership agreement docs"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Build a campaign brief template with sections for goals, audience, messaging, and channels"',
                                    '"Create a brand messaging guide by consolidating positioning discussions from meeting notes"',
                                    '"Build a content style guide based on top-performing blog posts"'
                                ]
                            }
                        ]
                    },
                    ops: {
                        title: 'For Operations Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Create a new process documentation document"',
                                    '"Find all SOP documents for my team"',
                                    '"List all vendor-related documents"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Extract all action items from project retrospective docs and create a master improvement plan"',
                                    '"Build an SOP library by organizing all process documentation by department"',
                                    '"Create a vendor evaluation template based on past vendor assessment notes"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Create a comprehensive onboarding handbook from all department process docs"',
                                    '"Compile all system documentation into a technical wiki structure"',
                                    '"Build an employee handbook by consolidating HR policies from various docs"'
                                ]
                            }
                        ]
                    }
                }
            },
            sheets: {
                title: '📊 Google Sheets Possibilities',
                subtitle: 'Real examples of what you can do with Sheets tools',
                byRole: {
                    founder: {
                        title: 'For Founders & CEOs',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Create a new spreadsheet for tracking company metrics"',
                                    '"Add a row to my fundraising tracker with a new investor"',
                                    '"Find my financial dashboard spreadsheet"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Build a hiring tracker with pipeline stages, comp data, and target start dates"',
                                    '"Track fundraising progress - investor list, meeting status, committed amounts"',
                                    '"Create a product roadmap tracker with features, owners, timeline, and customer requests"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Create a financial dashboard with burn rate, runway, revenue, and key metrics"',
                                    '"Build an OKR tracker for company goals with progress updates and blockers"',
                                    '"Analyze team capacity - headcount by function, utilization, and growth projections"'
                                ]
                            }
                        ]
                    },
                    sales: {
                        title: 'For Sales Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Add a new prospect to my pipeline tracker"',
                                    '"Update deal status for an existing opportunity"',
                                    '"Find my sales pipeline spreadsheet"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Create a sales pipeline tracker with deal stages, amounts, close dates, and probability"',
                                    '"Build a prospect research sheet with company info, decision makers, and outreach status"',
                                    '"Track demo-to-close conversion rates by industry, company size, and sales rep"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Create a commission calculator based on deal size and product mix"',
                                    '"Build a customer health score tracker with engagement metrics and renewal likelihood"',
                                    '"Analyze win/loss data - identify patterns in deals won vs lost by competitor, price, features"'
                                ]
                            }
                        ]
                    },
                    marketing: {
                        title: 'For Marketing Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Create a new content calendar spreadsheet"',
                                    '"Add this week\\\'s blog posts to the content calendar"',
                                    '"Find my campaign performance tracker"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Create a content calendar tracking blog posts, social, email campaigns by month"',
                                    '"Build a campaign performance tracker with spend, impressions, clicks, conversions, ROI"',
                                    '"Track lead sources and conversion rates from first touch to closed deal"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Create a social media content schedule with post copy, images, platforms, and timing"',
                                    '"Build an event planning tracker with dates, budget, expected attendance, and actual results"',
                                    '"Analyze which content topics and formats drive the most engagement and conversions"'
                                ]
                            }
                        ]
                    },
                    ops: {
                        title: 'For Operations Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Create a new vendor tracking spreadsheet"',
                                    '"Add a new software subscription to the tracker"',
                                    '"Find my budget spreadsheet"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Create a vendor management tracker with contracts, renewals, spend, and contacts"',
                                    '"Build an employee directory with departments, roles, start dates, and manager hierarchy"',
                                    '"Track software subscriptions - tools, costs, owners, renewal dates, and seat counts"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Create a bug/issue tracker with severity, status, owner, and resolution time"',
                                    '"Build a budget vs actual tracker by department and expense category"',
                                    '"Analyze operational metrics - response times, ticket volume, resolution rates, satisfaction scores"'
                                ]
                            }
                        ]
                    }
                }
            },
            fathom: {
                title: '🎙️ Fathom Meetings Possibilities',
                subtitle: 'Real examples of what you can do with Fathom tools',
                byRole: {
                    founder: {
                        title: 'For Founders & CEOs',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me all my recorded meetings from this week"',
                                    '"Find the transcript from yesterday\\\'s board meeting"',
                                    '"List all investor meetings I recorded this month"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Summarize all board meeting recordings from this quarter - key decisions and action items"',
                                    '"Extract product feedback from all customer meetings and organize by theme"',
                                    '"Compare what team leads said in 1-on-1s about blockers - identify systemic issues"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Analyze investor meeting transcripts - common questions, concerns, and requested metrics"',
                                    '"Create a hiring best practices guide from recordings of successful candidate interviews"',
                                    '"Track strategic decisions over time - what was decided in planning meetings and outcomes"'
                                ]
                            }
                        ]
                    },
                    sales: {
                        title: 'For Sales Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me the recording from my demo with Acme Corp"',
                                    '"Find all discovery call transcripts from this week"',
                                    '"List all customer meetings I recorded this month"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Analyze all discovery call transcripts - what questions prospects ask most frequently"',
                                    '"Extract objections from lost deal calls and identify patterns"',
                                    '"Summarize customer onboarding calls - common questions and friction points"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Find all mentions of competitors in sales calls - what are prospects comparing us to"',
                                    '"Create a pricing discussion playbook from successful closing calls"',
                                    '"Compare champion vs economic buyer conversations - different concerns and priorities"'
                                ]
                            }
                        ]
                    },
                    marketing: {
                        title: 'For Marketing Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Find the recording from our webinar last week"',
                                    '"Show me all customer interview recordings"',
                                    '"List all partnership discussion meetings"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Extract customer success stories from user interview recordings for case studies"',
                                    '"Summarize webinar recordings - top questions asked and engagement moments"',
                                    '"Extract content ideas from customer interviews - pain points that need addressing"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Analyze partnership discussion calls - terms, expectations, and collaboration ideas"',
                                    '"Find all mentions of our value prop in customer calls - what resonates vs what confuses"',
                                    '"Create buyer persona insights from prospect discovery calls"'
                                ]
                            }
                        ]
                    },
                    ops: {
                        title: 'For Operations Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me the recording from today\\\'s team standup"',
                                    '"Find all onboarding session recordings"',
                                    '"List all vendor demo meetings"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Extract action items from all cross-functional meetings and assign to owners"',
                                    '"Analyze onboarding session recordings - where do new hires get confused"',
                                    '"Summarize vendor demos - feature comparisons and pricing discussions"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Find all process improvement suggestions mentioned in team meetings"',
                                    '"Create a FAQ from support team meeting transcripts - common issues and resolutions"',
                                    '"Track recurring meeting topics - are we discussing the same issues without resolution"'
                                ]
                            }
                        ]
                    }
                }
            },
            instantly: {
                title: '✉️ Instantly Campaigns Possibilities',
                subtitle: 'Real examples of what you can do with Instantly tools',
                byRole: {
                    founder: {
                        title: 'For Founders & CEOs',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me all my active campaigns"',
                                    '"Check the performance of my investor outreach campaign"',
                                    '"List all leads who replied to my campaigns this week"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Analyze investor outreach campaign performance - who\\\'s engaging vs ignoring"',
                                    '"Track partnership outreach - response rates by industry and company size"',
                                    '"Monitor advisor recruitment campaign - who\\\'s interested in helping"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Test different positioning messages to potential customers - which resonates best"',
                                    '"Manage speaking opportunity outreach - conference responses and booking rate"',
                                    '"Track media/press outreach campaigns - who\\\'s covering our story"'
                                ]
                            }
                        ]
                    },
                    sales: {
                        title: 'For Sales Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me all leads who replied to my outreach this week"',
                                    '"Check open rates for my latest campaign"',
                                    '"List all leads who clicked links in my emails"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Show me all leads who opened my email 3+ times but haven\\\'t replied - they\\\'re interested!"',
                                    '"Compare campaign performance by industry - which sectors have best response rates"',
                                    '"Find leads who engaged with early emails but went cold - design win-back sequence"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Analyze subject lines across campaigns - which get best open rates by persona"',
                                    '"Track demo request conversion - from first email to booked meeting"',
                                    '"Identify high-intent leads who clicked pricing links - prioritize for follow-up calls"'
                                ]
                            }
                        ]
                    },
                    marketing: {
                        title: 'For Marketing Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me stats for my content promotion campaign"',
                                    '"Check how many people registered for the webinar from email"',
                                    '"List all leads from my latest nurture campaign"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Test different content offers - ebook vs webinar vs demo - which generates most leads"',
                                    '"Analyze campaign engagement by company size - tailor messaging for SMB vs Enterprise"',
                                    '"Monitor event promotion campaigns - registration rates and reminder effectiveness"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Track content distribution performance - who\\\'s sharing our resources"',
                                    '"Test messaging variations - feature-focused vs outcome-focused - which converts better"',
                                    '"Identify engaged leads not converting - re-target with different content offers"'
                                ]
                            }
                        ]
                    },
                    ops: {
                        title: 'For Operations Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Check response rates for vendor outreach campaign"',
                                    '"Show me applications from recruitment campaign"',
                                    '"List all survey responses from this week"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Monitor vendor outreach campaigns - response rates and quote timelines"',
                                    '"Track recruitment campaign performance - application rates by job posting"',
                                    '"Manage software trial outreach - conversion from free trial to paid"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Analyze internal communication campaigns - employee engagement with policy updates"',
                                    '"Track partner onboarding campaigns - activation rates and time to launch"',
                                    '"Monitor survey distribution campaigns - response rates and completion times"'
                                ]
                            }
                        ]
                    }
                }
            },
            bison: {
                title: '🔍 Bison Analysis Possibilities',
                subtitle: 'Real examples of what you can do with Bison tools',
                byRole: {
                    founder: {
                        title: 'For Founders & CEOs',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me our current MRR and revenue growth rate"',
                                    '"Calculate our current burn rate and runway"',
                                    '"What\\\'s our customer acquisition cost by channel?"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Analyze revenue trends and predict when we\\\'ll hit $1M ARR based on current growth"',
                                    '"Identify which customer segments have highest LTV and lowest CAC for targeting"',
                                    '"Predict burn rate and runway under different hiring and revenue scenarios"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Model different pricing strategies and impact on revenue and conversion"',
                                    '"Analyze team productivity metrics - identify bottlenecks and optimization opportunities"',
                                    '"Compare product usage data with churn - which features predict retention"'
                                ]
                            }
                        ]
                    },
                    sales: {
                        title: 'For Sales Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me my win rate and average deal size this quarter"',
                                    '"Calculate average time to close for my deals"',
                                    '"What\\\'s my pipeline coverage for this quarter?"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Build a lead scoring model - which characteristics predict deal closure"',
                                    '"Analyze deal velocity - identify what makes deals move faster through pipeline"',
                                    '"Predict which open opportunities are most likely to close this quarter"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Find patterns in lost deals - company size, industry, objections - to avoid pursuing similar"',
                                    '"Analyze sales rep performance - what activities correlate with quota attainment"',
                                    '"Model impact of price discounting on win rate and revenue"'
                                ]
                            }
                        ]
                    },
                    marketing: {
                        title: 'For Marketing Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me conversion rates by marketing channel"',
                                    '"Calculate ROI for our last campaign"',
                                    '"What\\\'s our cost per lead by source?"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Analyze which marketing channels drive highest quality leads (best conversion and LTV)"',
                                    '"Identify content topics and formats that drive most engagement and conversions"',
                                    '"Segment audience by behavior and personalize campaigns for each segment"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Predict campaign ROI before launch based on historical performance data"',
                                    '"Analyze customer journey - which touchpoints most influence purchase decisions"',
                                    '"Forecast lead generation needed to hit revenue targets based on conversion funnels"'
                                ]
                            }
                        ]
                    },
                    ops: {
                        title: 'For Operations Teams',
                        sections: [
                            {
                                title: 'Basic Tasks',
                                difficulty: 'basic',
                                prompts: [
                                    '"Show me current support ticket volume and response times"',
                                    '"Calculate team utilization rates by department"',
                                    '"What\\\'s our current churn rate?"'
                                ]
                            },
                            {
                                title: 'Intermediate Workflows',
                                difficulty: 'intermediate',
                                prompts: [
                                    '"Analyze support ticket data - predict volume spikes and identify root causes"',
                                    '"Optimize resource allocation - which teams are over/under capacity based on workload data"',
                                    '"Predict churn risk based on product usage, support tickets, and engagement metrics"'
                                ]
                            },
                            {
                                title: 'Advanced Automation',
                                difficulty: 'advanced',
                                prompts: [
                                    '"Analyze process efficiency - identify bottlenecks and automation opportunities"',
                                    '"Model impact of different org structures on team productivity and satisfaction"',
                                    '"Forecast hiring needs based on growth projections and current team capacity"'
                                ]
                            }
                        ]
                    }
                }
            }
        };

        // Global variable to track current category
        let currentCategory = null;

        function showPossibilities(category) {
            currentCategory = category;
            const data = toolExamples[category];
            const modal = document.getElementById('possibilitiesModal');
            const modalTitle = document.getElementById('modalTitle');
            const modalSubtitle = document.getElementById('modalSubtitle');

            // Set header content
            modalTitle.textContent = data.title;
            modalSubtitle.textContent = data.subtitle;

            // Reset role selector to default (founder)
            document.getElementById('roleSelector').value = 'founder';

            // Render examples for default role
            updateExamplesForRole();

            // Show modal
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';
        }

        function updateExamplesForRole() {
            if (!currentCategory) return;

            const selectedRole = document.getElementById('roleSelector').value;
            const data = toolExamples[currentCategory];
            const roleData = data.byRole[selectedRole];
            const modalBody = document.getElementById('modalBody');

            // Build HTML for this role with difficulty sections
            let html = '';
            roleData.sections.forEach(section => {
                html += `
                    <div class="prompt-section">
                        <h3>
                            ${section.title}
                            <span class="difficulty-badge ${section.difficulty}">${section.difficulty}</span>
                        </h3>
                        <ul class="prompt-examples">
                            ${section.prompts.map(prompt => `<li>${prompt}</li>`).join('')}
                        </ul>
                    </div>
                `;
            });

            modalBody.innerHTML = html;
        }

        function closeModal(event) {
            if (!event || event.target.classList.contains('modal-overlay') || event.target.classList.contains('modal-close')) {
                const modal = document.getElementById('possibilitiesModal');
                modal.classList.remove('active');
                document.body.style.overflow = '';
                currentCategory = null;
            }
        }

        // Close modal on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeModal();
            }
        });
    </script>
</body>
</html>
    """)


# ===========================================================================
# MODERN TRANSPORT: Streamable HTTP (2025-03-26)
# ===========================================================================

@app.post("/mcp")
async def mcp_streamable_http(
    request: Request,
    mcp_session_id: Optional[str] = Header(None, alias="Mcp-Session-Id"),
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Query(None)
):
    """
    Modern Streamable HTTP transport (2025-03-26) with multi-tenant support.

    Single endpoint for all MCP operations. Session ID in header.
    Simpler than HTTP+SSE but same functionality.

    Multi-tenant mode:
    - Include Authorization: Bearer <session_token> header OR ?session_token= query param
    - Each user gets isolated API clients with their own credentials

    Legacy single-user mode:
    - No Authorization header required
    - Uses global clients (backwards compatible)
    """
    # Parse request body
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({
            "jsonrpc": "2.0",
            "error": {
                "code": -32700,
                "message": f"Parse error: {str(e)}"
            }
        }, status_code=400)

    method = body.get("method", "")

    # Try to get user context if Authorization header or session_token query param present
    ctx = None
    if authorization or session_token:
        try:
            ctx = await get_request_context(authorization, session_token)
        except HTTPException as e:
            # Auth failed - return error
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {
                    "code": -32000,
                    "message": e.detail
                }
            }, status_code=e.status_code)
        except Exception as e:
            logger.error(f"Unexpected auth error: {e}")
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {
                    "code": -32000,
                    "message": f"Authentication error: {str(e)}"
                }
            }, status_code=500)

    # Check if this is an initialize request (new session)
    if method == "initialize":
        # Generate new session ID
        session_id = create_session("streamable_http")

        # Handle the request (with optional user context)
        response_data = await handle_jsonrpc_request(body, session_id, ctx)

        # Return with session ID in header (proper casing!)
        return JSONResponse(
            response_data,
            headers={"Mcp-Session-Id": session_id}
        )

    else:
        # Existing session - verify session ID
        if not mcp_session_id or mcp_session_id not in sessions:
            logger.warning(f"Invalid or missing session ID: {mcp_session_id}")
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {
                    "code": -32001,
                    "message": "Session not found. Please reinitialize."
                }
            }, status_code=404)

        # Update session activity
        sessions[mcp_session_id].update_activity()

        # Handle the request (with optional user context)
        response_data = await handle_jsonrpc_request(body, mcp_session_id, ctx)
        return JSONResponse(response_data)


# ===========================================================================
# LEGACY TRANSPORT: HTTP+SSE (2024-11-05)
# ===========================================================================

@app.get("/mcp")
async def mcp_sse_stream(
    request: Request,
    session_token: Optional[str] = Query(None)
):
    """
    Legacy SSE stream endpoint (2024-11-05) with multi-tenant support.

    Establishes a Server-Sent Events connection and sends the message endpoint URL.
    Clients then use POST /messages to send requests.

    Multi-tenant mode:
    - Include ?session_token= query parameter
    - User context will be attached to the session
    """
    # Try to get user context if session_token provided
    ctx = None
    if session_token:
        try:
            ctx = await get_request_context(None, session_token)
            logger.info(f"SSE session authenticated for user: {ctx.email}")
        except HTTPException as e:
            logger.warning(f"Failed to authenticate SSE session: {e.detail}")
            # Continue without auth for backwards compatibility
        except Exception as e:
            logger.error(f"Unexpected auth error in SSE: {e}")

    # Generate new session ID with user context
    session_id = create_session("sse", user_context=ctx)

    async def event_generator():
        """Generate SSE events."""
        try:
            # Send endpoint URL per MCP spec
            yield {
                "event": "endpoint",
                "data": "/messages"
            }

            # Keep connection alive with periodic pings
            while session_id in sessions:
                # Update activity
                sessions[session_id].update_activity()

                # Wait for messages in queue or timeout
                try:
                    message = await asyncio.wait_for(
                        sessions[session_id].queue.get(),
                        timeout=30.0
                    )
                    # Send queued message
                    yield {
                        "event": "message",
                        "data": json.dumps(message)
                    }
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    yield {
                        "event": "ping",
                        "data": ""
                    }

        except asyncio.CancelledError:
            logger.info(f"SSE connection closed - Session: {session_id}")
            if session_id in sessions:
                del sessions[session_id]
            raise
        except Exception as e:
            logger.error(f"Error in SSE stream (session {session_id}): {e}")
            if session_id in sessions:
                del sessions[session_id]
            raise

    # Return SSE response with proper headers
    return EventSourceResponse(
        event_generator(),
        headers={
            "Mcp-Session-Id": session_id,  # Note: proper casing per MCP spec
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )


@app.post("/messages")
async def mcp_messages_legacy(
    request: Request,
    sessionId: Optional[str] = Query(None, alias="sessionId")  # Query parameter per legacy spec
):
    """
    Legacy message endpoint (2024-11-05).

    Receives JSON-RPC requests and returns responses.
    Used in conjunction with GET /mcp SSE stream.
    """
    # Try to get session ID from multiple sources
    session_id = sessionId or request.headers.get("mcp-session-id") or request.headers.get("Mcp-Session-Id")

    # If still not found, try to get the most recent session (fallback for Inspector)
    if not session_id and len(sessions) > 0:
        # Use the most recently created session
        session_id = max(sessions.keys(), key=lambda k: sessions[k].created_at)
        logger.warning(f"No session ID provided, using most recent: {session_id}")

    if not session_id or session_id not in sessions:
        logger.warning(f"Session not found: {session_id}")
        return JSONResponse({
            "jsonrpc": "2.0",
            "error": {
                "code": -32001,
                "message": "Session not found. Please reinitialize."
            }
        }, status_code=404)

    # Parse request body
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({
            "jsonrpc": "2.0",
            "error": {
                "code": -32700,
                "message": f"Parse error: {str(e)}"
            }
        }, status_code=400)

    # Update session activity
    sessions[session_id].update_activity()

    # Get user context from session (if available)
    ctx = sessions[session_id].user_context

    # Handle the request with user context
    response = await handle_jsonrpc_request(body, session_id, ctx)

    # Queue response for SSE stream
    await sessions[session_id].queue.put(response)

    # Also return immediately for polling clients
    return JSONResponse(response)


# ===========================================================================
# OAUTH SETUP ENDPOINTS
# ===========================================================================

@app.get("/setup/start")
async def setup_start(
    request: Request,
    redirect: Optional[str] = Query(None)
):
    """Initiate Google OAuth flow for multi-tenant setup."""
    try:
        # Rate limiting: Prevent OAuth flow abuse
        # Allow 20 OAuth start attempts per IP per 5 minutes
        client_ip = get_client_ip(request)
        allowed, retry_after = rate_limiter.check_rate_limit(
            identifier=f"oauth_start:{client_ip}",
            max_attempts=20,
            window_seconds=300  # 5 minutes
        )

        if not allowed:
            logger.warning(f"Rate limit exceeded for OAuth start from IP {client_ip}")
            raise HTTPException(
                status_code=429,
                detail=f"Too many OAuth attempts. Please try again in {retry_after} seconds."
            )

        # Get OAuth credentials from environment
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
        scopes = os.getenv("GMAIL_OAUTH_SCOPES", "").split(",")

        if not client_id or not client_secret or not redirect_uri:
            raise ValueError("OAuth environment variables not configured")

        # Create OAuth flow
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri]
                }
            },
            scopes=scopes
        )
        flow.redirect_uri = redirect_uri

        # Generate authorization URL
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'  # Force consent to get refresh token
        )

        # Store state for verification (with timestamp for cleanup)
        oauth_states[state] = {
            'timestamp': datetime.now(),
            'flow': flow,
            'redirect': redirect  # Store redirect path for post-OAuth navigation
        }

        logger.info(f"Initiating OAuth flow with state: {state}")

        # Redirect to Google authorization
        return RedirectResponse(url=auth_url, status_code=302)

    except Exception as e:
        logger.error(f"OAuth initiation error: {e}")
        error_html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Setup Error</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .card {{
            max-width: 500px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 40px;
            text-align: center;
        }}
        h1 {{ color: #e53935; margin-bottom: 20px; }}
        p {{ color: #666; margin-bottom: 20px; }}
        .error {{
            background: #ffebee;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
            color: #c62828;
            font-family: monospace;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h1>⚠️ Setup Error</h1>
        <p>Failed to initialize OAuth flow. Please contact the administrator.</p>
        <div class="error">{str(e)}</div>
    </div>
</body>
</html>
        """
        return HTMLResponse(content=error_html, status_code=500)


@app.get("/signup/start")
async def signup_start(
    request: Request,
    redirect: Optional[str] = Query(None)
):
    """Initiate Google OAuth flow for new user signup."""
    try:
        # Get OAuth credentials from environment
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
        scopes = os.getenv("GMAIL_OAUTH_SCOPES", "").split(",")

        if not client_id or not client_secret or not redirect_uri:
            raise ValueError("OAuth environment variables not configured")

        # Create OAuth flow
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri]
                }
            },
            scopes=scopes
        )
        flow.redirect_uri = redirect_uri

        # Generate authorization URL for signup (force consent)
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'  # Force consent for new users
        )

        # Store state for verification with flow type
        oauth_states[state] = {
            'timestamp': datetime.now(),
            'flow': flow,
            'flow_type': 'signup',  # Track that this is a signup flow
            'redirect': redirect  # Store redirect path for post-OAuth navigation
        }

        logger.info(f"Initiating signup OAuth flow with state: {state}")

        # Redirect to Google authorization
        return RedirectResponse(url=auth_url, status_code=302)

    except Exception as e:
        logger.error(f"OAuth signup initiation error: {e}")
        return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>Signup Error</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0;
            padding: 20px;
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            max-width: 500px;
            text-align: center;
        }}
        h1 {{ color: #dc2626; margin-bottom: 20px; }}
        p {{ color: #666; line-height: 1.6; }}
        .error-details {{
            background: #fee;
            padding: 15px;
            border-radius: 8px;
            margin-top: 20px;
            font-family: monospace;
            font-size: 14px;
            color: #991b1b;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>❌ Signup Error</h1>
        <p>We encountered an error while setting up your account.</p>
        <div class="error-details">{str(e)}</div>
        <p style="margin-top: 20px;">
            <a href="/" style="color: #667eea; text-decoration: none; font-weight: 600;">← Back to Home</a>
        </p>
    </div>
</body>
</html>
        """, status_code=500)


@app.get("/login/start")
async def login_start(
    request: Request,
    redirect: Optional[str] = Query(None)
):
    """Initiate Google OAuth flow for returning user login."""
    try:
        # Get OAuth credentials from environment
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
        scopes = os.getenv("GMAIL_OAUTH_SCOPES", "").split(",")

        if not client_id or not client_secret or not redirect_uri:
            raise ValueError("OAuth environment variables not configured")

        # Create OAuth flow
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri]
                }
            },
            scopes=scopes
        )
        flow.redirect_uri = redirect_uri

        # Generate authorization URL for login (allow account selection)
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='select_account'  # Let user choose account for login
        )

        # Store state for verification with flow type
        oauth_states[state] = {
            'timestamp': datetime.now(),
            'flow': flow,
            'flow_type': 'login',  # Track that this is a login flow
            'redirect': redirect  # Store redirect path for post-OAuth navigation
        }

        logger.info(f"Initiating login OAuth flow with state: {state}")

        # Redirect to Google authorization
        return RedirectResponse(url=auth_url, status_code=302)

    except Exception as e:
        logger.error(f"OAuth login initiation error: {e}")
        return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>Login Error</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0;
            padding: 20px;
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            max-width: 500px;
            text-align: center;
        }}
        h1 {{ color: #dc2626; margin-bottom: 20px; }}
        p {{ color: #666; line-height: 1.6; }}
        .error-details {{
            background: #fee;
            padding: 15px;
            border-radius: 8px;
            margin-top: 20px;
            font-family: monospace;
            font-size: 14px;
            color: #991b1b;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>❌ Login Error</h1>
        <p>We encountered an error while logging you in.</p>
        <div class="error-details">{str(e)}</div>
        <p style="margin-top: 20px;">
            <a href="/" style="color: #667eea; text-decoration: none; font-weight: 600;">← Back to Home</a>
        </p>
    </div>
</body>
</html>
        """, status_code=500)


# ===========================================================================
# EMAIL/PASSWORD AUTHENTICATION
# ===========================================================================

@app.get("/signup", response_class=HTMLResponse)
async def signup_form(request: Request, error: Optional[str] = Query(None)):
    """Show email/password signup form."""
    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>Sign Up - AI Email Assistant</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0;
            padding: 20px;
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 16px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            max-width: 450px;
            width: 100%;
        }}
        h1 {{
            color: #1a202c;
            margin: 0 0 10px 0;
            font-size: 28px;
            text-align: center;
        }}
        .subtitle {{
            color: #718096;
            text-align: center;
            margin: 0 0 30px 0;
            font-size: 15px;
        }}
        .form-group {{
            margin-bottom: 20px;
        }}
        label {{
            display: block;
            font-weight: 600;
            margin-bottom: 8px;
            color: #2d3748;
            font-size: 14px;
        }}
        input {{
            width: 100%;
            padding: 12px 16px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 15px;
            box-sizing: border-box;
            transition: border-color 0.2s;
        }}
        input:focus {{
            outline: none;
            border-color: #667eea;
        }}
        .btn {{
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
        }}
        .btn:active {{
            transform: translateY(0);
        }}
        .error-msg {{
            background: #fee;
            color: #c53030;
            padding: 12px 16px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 14px;
            border-left: 4px solid #f56565;
        }}
        .divider {{
            display: flex;
            align-items: center;
            margin: 25px 0;
            color: #a0aec0;
            font-size: 13px;
        }}
        .divider::before,
        .divider::after {{
            content: "";
            flex: 1;
            border-bottom: 1px solid #e2e8f0;
        }}
        .divider span {{
            padding: 0 15px;
        }}
        .oauth-btn {{
            width: 100%;
            padding: 12px;
            background: white;
            color: #2d3748;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            text-decoration: none;
        }}
        .oauth-btn:hover {{
            border-color: #cbd5e0;
            background: #f7fafc;
        }}
        .footer-link {{
            text-align: center;
            margin-top: 20px;
            color: #718096;
            font-size: 14px;
        }}
        .footer-link a {{
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
        }}
        .footer-link a:hover {{
            text-decoration: underline;
        }}
        .password-requirements {{
            font-size: 13px;
            color: #718096;
            margin-top: 6px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>✨ Create Your Account</h1>
        <p class="subtitle">Start your 3-day free trial with all 85 tools unlocked</p>

        {f'<div class="error-msg">❌ {error}</div>' if error else ''}

        <form method="post" action="/signup">
            <div class="form-group">
                <label for="email">Email Address</label>
                <input type="email" id="email" name="email" required placeholder="you@example.com">
            </div>

            <div class="form-group">
                <label for="name">Full Name (Optional)</label>
                <input type="text" id="name" name="name" placeholder="John Doe">
            </div>

            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required placeholder="••••••••">
                <div class="password-requirements">Minimum 8 characters</div>
            </div>

            <div class="form-group">
                <label for="confirm_password">Confirm Password</label>
                <input type="password" id="confirm_password" name="confirm_password" required placeholder="••••••••">
            </div>

            <button type="submit" class="btn">Create Account →</button>
        </form>

        <div class="divider">
            <span>OR</span>
        </div>

        <a href="/signup/start" class="oauth-btn">
            <svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
                <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" fill="#4285F4"/>
                <path d="M9.003 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.258c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.96v2.332C2.44 15.983 5.485 18 9.003 18z" fill="#34A853"/>
                <path d="M3.964 10.71c-.18-.54-.282-1.117-.282-1.71s.102-1.17.282-1.71V4.958H.957C.347 6.173 0 7.548 0 9.001c0 1.452.348 2.827.957 4.041l3.007-2.332z" fill="#FBBC05"/>
                <path d="M9.003 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.464.891 11.426 0 9.003 0 5.485 0 2.44 2.017.96 4.958L3.967 7.29c.708-2.127 2.692-3.71 5.036-3.71z" fill="#EA4335"/>
            </svg>
            Continue with Google
        </a>

        <div class="footer-link">
            Already have an account? <a href="/login">Log In</a>
        </div>

        <div class="footer-link" style="margin-top: 10px;">
            <a href="/">← Back to Home</a>
        </div>
    </div>

    <script>
        // Client-side password validation
        document.querySelector('form').addEventListener('submit', function(e) {{
            const password = document.getElementById('password').value;
            const confirmPassword = document.getElementById('confirm_password').value;

            if (password !== confirmPassword) {{
                e.preventDefault();
                alert('Passwords do not match. Please try again.');
                return false;
            }}

            if (password.length < 8) {{
                e.preventDefault();
                alert('Password must be at least 8 characters long.');
                return false;
            }}
        }});
    </script>
</body>
</html>
    """)


@app.post("/signup")
async def signup_submit(request: Request):
    """Handle email/password signup submission (supports both form data and JSON)."""
    try:
        # Detect content type and parse accordingly
        content_type = request.headers.get('content-type', '')
        is_json = 'application/json' in content_type.lower()

        if is_json:
            # JSON request (from invitation page)
            body = await request.json()
            email = body.get('email', '').strip()
            password = body.get('password', '')
            name = body.get('name', '').strip() or None
            confirm_password = password  # JSON doesn't need confirmation
        else:
            # Form data request (from signup page)
            form_data = await request.form()
            email = form_data.get('email', '').strip()
            name = form_data.get('name', '').strip() or None
            password = form_data.get('password', '')
            confirm_password = form_data.get('confirm_password', '')

        # Validate inputs
        if not email or not password:
            if is_json:
                raise HTTPException(400, "Email and password are required")
            return RedirectResponse(
                url=f"/signup?error=Email and password are required",
                status_code=303
            )

        if password != confirm_password:
            if is_json:
                raise HTTPException(400, "Passwords do not match")
            return RedirectResponse(
                url=f"/signup?error=Passwords do not match",
                status_code=303
            )

        # Create user in database
        if not hasattr(server, 'database') or server.database is None:
            raise ValueError("Database not initialized")

        try:
            user_data = server.database.create_user_with_password(
                email=email,
                password=password,
                name=name
            )
        except ValueError as e:
            # Handle duplicate email or weak password
            if is_json:
                raise HTTPException(400, str(e))
            return RedirectResponse(
                url=f"/signup?error={str(e)}",
                status_code=303
            )

        logger.info(f"New email/password signup: {email}")

        # Return appropriate response
        if is_json:
            # JSON response (for invitation page)
            return JSONResponse({
                "success": True,
                "session_token": user_data['session_token'],
                "user_id": user_data['user_id'],
                "email": user_data['email']
            })
        else:
            # Redirect to dashboard with welcome message
            first_name = name.split()[0] if name else email.split('@')[0]
            return RedirectResponse(
                url=f"/dashboard?session_token={user_data['session_token']}&is_new_user=True&first_name={first_name}",
                status_code=303
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signup error: {e}")
        if is_json:
            raise HTTPException(500, "An error occurred. Please try again.")
        return RedirectResponse(
            url=f"/signup?error=An error occurred. Please try again.",
            status_code=303
        )


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, error: Optional[str] = Query(None)):
    """Show email/password login form."""
    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>Log In - AI Email Assistant</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0;
            padding: 20px;
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 16px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            max-width: 450px;
            width: 100%;
        }}
        h1 {{
            color: #1a202c;
            margin: 0 0 10px 0;
            font-size: 28px;
            text-align: center;
        }}
        .subtitle {{
            color: #718096;
            text-align: center;
            margin: 0 0 30px 0;
            font-size: 15px;
        }}
        .form-group {{
            margin-bottom: 20px;
        }}
        label {{
            display: block;
            font-weight: 600;
            margin-bottom: 8px;
            color: #2d3748;
            font-size: 14px;
        }}
        input {{
            width: 100%;
            padding: 12px 16px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 15px;
            box-sizing: border-box;
            transition: border-color 0.2s;
        }}
        input:focus {{
            outline: none;
            border-color: #667eea;
        }}
        .btn {{
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
        }}
        .btn:active {{
            transform: translateY(0);
        }}
        .error-msg {{
            background: #fee;
            color: #c53030;
            padding: 12px 16px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 14px;
            border-left: 4px solid #f56565;
        }}
        .divider {{
            display: flex;
            align-items: center;
            margin: 25px 0;
            color: #a0aec0;
            font-size: 13px;
        }}
        .divider::before,
        .divider::after {{
            content: "";
            flex: 1;
            border-bottom: 1px solid #e2e8f0;
        }}
        .divider span {{
            padding: 0 15px;
        }}
        .oauth-btn {{
            width: 100%;
            padding: 12px;
            background: white;
            color: #2d3748;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            text-decoration: none;
        }}
        .oauth-btn:hover {{
            border-color: #cbd5e0;
            background: #f7fafc;
        }}
        .footer-link {{
            text-align: center;
            margin-top: 20px;
            color: #718096;
            font-size: 14px;
        }}
        .footer-link a {{
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
        }}
        .footer-link a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>👋 Welcome Back</h1>
        <p class="subtitle">Log in to access your AI Email Assistant</p>

        {f'<div class="error-msg">❌ {error}</div>' if error else ''}

        <form method="post" action="/login">
            <div class="form-group">
                <label for="email">Email Address</label>
                <input type="email" id="email" name="email" required placeholder="you@example.com">
            </div>

            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required placeholder="••••••••">
            </div>

            <button type="submit" class="btn">Log In →</button>
        </form>

        <div class="divider">
            <span>OR</span>
        </div>

        <a href="/login/start" class="oauth-btn">
            <svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
                <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" fill="#4285F4"/>
                <path d="M9.003 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.258c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.96v2.332C2.44 15.983 5.485 18 9.003 18z" fill="#34A853"/>
                <path d="M3.964 10.71c-.18-.54-.282-1.117-.282-1.71s.102-1.17.282-1.71V4.958H.957C.347 6.173 0 7.548 0 9.001c0 1.452.348 2.827.957 4.041l3.007-2.332z" fill="#FBBC05"/>
                <path d="M9.003 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.464.891 11.426 0 9.003 0 5.485 0 2.44 2.017.96 4.958L3.967 7.29c.708-2.127 2.692-3.71 5.036-3.71z" fill="#EA4335"/>
            </svg>
            Continue with Google
        </a>

        <div class="footer-link">
            Don't have an account? <a href="/signup">Sign Up</a>
        </div>

        <div class="footer-link" style="margin-top: 10px;">
            <a href="/">← Back to Home</a>
        </div>
    </div>
</body>
</html>
    """)


@app.post("/login")
async def login_submit(request: Request):
    """Handle email/password login submission."""
    try:
        # Rate limiting: Prevent brute force attacks
        # Allow 5 login attempts per IP address per 15 minutes
        client_ip = get_client_ip(request)
        allowed, retry_after = rate_limiter.check_rate_limit(
            identifier=f"login:{client_ip}",
            max_attempts=5,
            window_seconds=900  # 15 minutes
        )

        if not allowed:
            logger.warning(f"Rate limit exceeded for login from IP {client_ip}")
            return RedirectResponse(
                url=f"/login?error=Too many login attempts. Please try again in {retry_after // 60} minutes.",
                status_code=303
            )

        # Parse form data
        form_data = await request.form()
        email = form_data.get('email', '').strip()
        password = form_data.get('password', '')

        # Validate inputs
        if not email or not password:
            return RedirectResponse(
                url=f"/login?error=Email and password are required",
                status_code=303
            )

        # Authenticate user
        if not hasattr(server, 'database') or server.database is None:
            raise ValueError("Database not initialized")

        user_data = server.database.authenticate_email_password(email, password)

        if not user_data:
            return RedirectResponse(
                url=f"/login?error=Invalid email or password",
                status_code=303
            )

        logger.info(f"Successful email/password login: {email}")

        # Redirect to dashboard with welcome message
        first_name = email.split('@')[0]  # Fallback to email username
        return RedirectResponse(
            url=f"/dashboard?session_token={user_data['session_token']}&is_new_user=False&first_name={first_name}",
            status_code=303
        )

    except Exception as e:
        logger.error(f"Login error: {e}")
        return RedirectResponse(
            url=f"/login?error=An error occurred. Please try again.",
            status_code=303
        )


@app.get("/setup/callback")
async def setup_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None)
):
    """Handle OAuth callback from Google."""
    try:
        # Rate limiting: Prevent OAuth callback abuse
        # Allow 10 callback attempts per IP per 5 minutes
        client_ip = get_client_ip(request)
        allowed, retry_after = rate_limiter.check_rate_limit(
            identifier=f"oauth_callback:{client_ip}",
            max_attempts=10,
            window_seconds=300  # 5 minutes
        )

        if not allowed:
            logger.warning(f"Rate limit exceeded for OAuth callback from IP {client_ip}")
            raise HTTPException(
                status_code=429,
                detail=f"Too many OAuth callback attempts. Please try again in {retry_after} seconds."
            )

        # Check for OAuth errors
        if error:
            logger.error(f"OAuth error: {error}")
            error_html = """
<!DOCTYPE html>
<html>
<head>
    <title>Authorization Failed</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .card {
            max-width: 500px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 40px;
            text-align: center;
        }
        h1 { color: #e53935; margin-bottom: 20px; }
        p { color: #666; margin-bottom: 30px; }
        .button {
            background: #2196f3;
            color: white;
            border: none;
            padding: 14px 24px;
            font-size: 16px;
            border-radius: 4px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>❌ Authorization Failed</h1>
        <p>You declined the authorization request. Please try again and grant the required permissions.</p>
        <a href="/setup/start" class="button">Try Again</a>
    </div>
</body>
</html>
            """
            return HTMLResponse(content=error_html, status_code=403)

        if not code or not state:
            return HTMLResponse(content="Missing code or state parameter", status_code=400)

        # Verify state matches stored value
        if state not in oauth_states:
            logger.error(f"Invalid state parameter: {state}")
            return HTMLResponse(content="Invalid state parameter", status_code=400)

        # Retrieve flow from stored state
        oauth_data = oauth_states[state]
        flow = oauth_data['flow']
        flow_type = oauth_data.get('flow_type', 'signup')  # Default to signup for backwards compatibility

        # Retrieve and validate redirect path
        stored_redirect = oauth_data.get('redirect', '/dashboard')
        validated_redirect = validate_redirect_url(stored_redirect)

        # Clean up used state
        del oauth_states[state]

        # Exchange authorization code for tokens
        logger.info(f"Exchanging auth code for tokens (state: {state}, flow_type: {flow_type})")
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Get user's email and name from Google APIs
        gmail_service = build('gmail', 'v1', credentials=credentials)
        profile = gmail_service.users().getProfile(userId='me').execute()
        email = profile['emailAddress']

        # Try to get user's name from People API
        try:
            from googleapiclient.discovery import build as build_service
            people_service = build_service('people', 'v1', credentials=credentials)
            person = people_service.people().get(
                resourceName='people/me',
                personFields='names'
            ).execute()

            names = person.get('names', [])
            first_name = names[0].get('givenName', '') if names else ''
        except Exception as e:
            logger.warning(f"Could not fetch user name: {e}")
            first_name = email.split('@')[0]  # Fallback to email username

        logger.info(f"OAuth successful for user: {email} (name: {first_name})")

        # Prepare token data for database storage
        google_token = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes,
            'expiry': credentials.expiry.isoformat() if credentials.expiry else None
        }

        # Store user in database (creates or updates)
        if not hasattr(server, 'database') or server.database is None:
            raise ValueError("Database not initialized")

        user_data = server.database.create_user(
            email=email,
            google_token=google_token,
            api_keys={}  # Empty initially, user will add via dashboard
        )

        is_new_user = user_data.get('is_new_user', False)
        login_count = user_data.get('login_count', 1)

        logger.info(f"User created/updated in database: {email} (ID: {user_data['user_id']}, login_count: {login_count})")

        # Get server URL for Claude config (force HTTPS for Railway)
        server_url = f"https://{request.url.hostname}"
        session_token = user_data['session_token']

        # Redirect to stored destination (or dashboard if none)
        # Preserve existing query parameters and add session info
        redirect_url = validated_redirect
        separator = '&' if '?' in redirect_url else '?'
        return RedirectResponse(
            url=f"{redirect_url}{separator}session_token={session_token}&is_new_user={is_new_user}&first_name={first_name}",
            status_code=303
        )

    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        error_html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Setup Error</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .card {{
            max-width: 500px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 40px;
            text-align: center;
        }}
        h1 {{ color: #e53935; margin-bottom: 20px; }}
        p {{ color: #666; margin-bottom: 20px; }}
        .error {{
            background: #ffebee;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
            color: #c62828;
            font-family: monospace;
            font-size: 14px;
        }}
        .button {{
            background: #2196f3;
            color: white;
            border: none;
            padding: 14px 24px;
            font-size: 16px;
            border-radius: 4px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h1>⚠️ Setup Error</h1>
        <p>An error occurred during the OAuth callback.</p>
        <div class="error">{str(e)}</div>
        <a href="/setup/start" class="button">Try Again</a>
    </div>
</body>
</html>
        """
        return HTMLResponse(content=error_html, status_code=500)


# ===========================================================================
# DASHBOARD ENDPOINTS
# ===========================================================================

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session_token: Optional[str] = Query(None),
    welcome: Optional[str] = Query(None),
    subscription_success: Optional[str] = Query(None),
    is_new_user: Optional[str] = Query(None),
    first_name: Optional[str] = Query(None),
    admin_password: Optional[str] = Query(None)
):
    """Admin dashboard for managing API keys and subscriptions."""
    if not session_token:
        return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>MCP Dashboard - Login Required</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: system-ui, -apple-system, sans-serif;
            max-width: 600px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .card {
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 { color: #333; }
        code {
            background: #f5f5f5;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: monospace;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>🔒 Login Required</h1>
        <p>Please provide your session token as a query parameter:</p>
        <code>/dashboard?session_token=sess_your_token_here</code>
        <p style="margin-top: 20px;">Get your session token from the <a href="/setup/start">OAuth success page</a>.</p>
    </div>
</body>
</html>
        """, status_code=401)

    # Validate session token
    try:
        ctx = await get_request_context(None, session_token)
    except HTTPException:
        return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>Invalid Session</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: system-ui, -apple-system, sans-serif;
            max-width: 600px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .card {
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 { color: #e53935; }
    </style>
</head>
<body>
    <div class="card">
        <h1>❌ Invalid or Expired Session Token</h1>
        <p>Please complete the OAuth flow again at <a href="/setup/start">/setup/start</a></p>
    </div>
</body>
</html>
        """, status_code=401)

    # Get current API keys
    user = server.database.get_user_by_session(session_token)
    api_keys = user.get('api_keys', {})
    teams_enabled = user.get('teams_enabled', False)

    # Check if admin
    correct_admin_password = os.getenv("ADMIN_PASSWORD")
    cookie_admin_password = request.cookies.get("admin_session")
    is_admin = (admin_password == correct_admin_password) or (cookie_admin_password == correct_admin_password)

    # Get trial status and usage info
    trial_status = server.database.check_trial_status(ctx.user_id)
    daily_usage = server.database.get_daily_usage(ctx.user_id)

    # Get active subscriptions (category names only)
    active_subscriptions = server.database.get_active_subscriptions(ctx.user_id)

    # Get full subscription details (for showing cancellation info)
    all_subscriptions = server.database.get_user_subscriptions(ctx.user_id)
    subscription_details = {sub['tool_category']: sub for sub in all_subscriptions if sub['status'] == 'active'}

    # Get cancelled subscriptions (for resume button)
    cancelled_subscriptions = [sub['tool_category'] for sub in all_subscriptions if sub['status'] == 'cancelled']

    # Get user's teams (for team subscription option)
    user_teams = server.database.get_user_teams(ctx.user_id) if teams_enabled else []

    # Get personal subscriptions only (not team subscriptions)
    personal_subs_result = server.database.supabase.table('subscriptions').select('tool_category').eq(
        'user_id', ctx.user_id
    ).eq('status', 'active').is_('team_id', 'null').execute()
    personal_subscriptions = [sub['tool_category'] for sub in personal_subs_result.data]

    # Get subscriptions for each team
    team_subscriptions_map = {}
    for team in user_teams:
        team_subs_result = server.database.supabase.table('subscriptions').select('tool_category').eq(
            'team_id', team['team_id']
        ).eq('status', 'active').eq('is_team_subscription', True).execute()
        team_subscriptions_map[team['team_id']] = [sub['tool_category'] for sub in team_subs_result.data]

    # Determine user tier
    if trial_status['is_trial']:
        user_tier = 'trial'
        usage_limit = None  # Unlimited during trial
    elif len(active_subscriptions) > 0:
        user_tier = 'paid'
        usage_limit = None  # Unlimited for paid users
    else:
        user_tier = 'free'
        usage_limit = 10  # Free tier limit

    # Get enabled tool categories
    enabled_categories = user.get('enabled_tool_categories')
    # None = all enabled (default), [] = none, [...] = specific categories

    # Prepare checkbox states
    all_categories = ['gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison']
    enabled_categories_str = {}

    if enabled_categories is None:
        # All categories enabled by default
        for cat in all_categories:
            enabled_categories_str[cat] = 'checked'
    else:
        # Specific categories enabled
        for cat in all_categories:
            enabled_categories_str[cat] = 'checked' if cat in enabled_categories else ''

    # Calculate tool count
    tool_counts = {'gmail': 25, 'calendar': 15, 'docs': 8, 'sheets': 12, 'fathom': 11, 'instantly': 10, 'bison': 4}
    if enabled_categories is None:
        total_tools = 84
    else:
        total_tools = sum(tool_counts[cat] for cat in enabled_categories)

    # Category info for shopping cart
    category_info = {
        'gmail': {'emoji': '📧', 'name': 'Gmail Tools', 'tools': 25, 'desc': 'Search, send, manage emails'},
        'calendar': {'emoji': '📅', 'name': 'Calendar Tools', 'tools': 15, 'desc': 'Create events, check availability'},
        'docs': {'emoji': '📄', 'name': 'Google Docs Tools', 'tools': 8, 'desc': 'Create, read, update documents'},
        'sheets': {'emoji': '📊', 'name': 'Google Sheets Tools', 'tools': 12, 'desc': 'Read, write, manage spreadsheets'},
        'fathom': {'emoji': '🎥', 'name': 'Fathom Tools', 'tools': 11, 'desc': 'Meeting recordings & analytics', 'note': '💡 Requires Fathom API key'},
        'instantly': {'emoji': '📨', 'name': 'Instantly Tools', 'tools': 10, 'desc': 'Email campaigns & lead management (Instantly.ai)', 'note': '💡 Requires Instantly API key'},
        'bison': {'emoji': '🦬', 'name': 'Bison Tools', 'tools': 4, 'desc': 'Email campaigns & lead management (EmailBison)', 'note': '💡 Requires Bison API key'}
    }

    # Render dashboard HTML
    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>MCP Dashboard - {ctx.email}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
            max-width: 1000px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f7fa;
            min-height: 100vh;
        }}
        .container {{
            /* No background - using individual cards instead */
        }}
        @media (max-width: 768px) {{
            body {{
                margin: 30px auto;
                padding: 15px;
            }}
            nav {{
                margin: -30px -15px 20px -15px !important;
            }}
        }}
        h1 {{ color: #333; }}
        .user-info {{
            background: #e3f2fd;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 30px;
            border-left: 4px solid #2196f3;
        }}
        .form-group {{
            margin-bottom: 20px;
        }}
        label {{
            display: block;
            font-weight: 600;
            margin-bottom: 5px;
            color: #555;
        }}
        input {{
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
            box-sizing: border-box;
        }}
        button {{
            background: #2196f3;
            color: white;
            padding: 12px 24px;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            cursor: pointer;
            font-weight: 600;
        }}
        button:hover {{
            background: #1976d2;
        }}
        .success {{
            background: #4caf50;
            color: white;
            padding: 16px 24px;
            border-radius: 8px;
            margin-bottom: 20px;
            display: none;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(76, 175, 80, 0.4);
            animation: slideIn 0.3s ease-out;
            font-size: 15px;
        }}
        .error {{
            background: #f44336;
            color: white;
            padding: 16px 24px;
            border-radius: 8px;
            margin-bottom: 20px;
            display: none;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(244, 67, 54, 0.4);
            animation: slideIn 0.3s ease-out;
            font-size: 15px;
        }}
        @keyframes slideIn {{
            from {{
                transform: translateY(-20px);
                opacity: 0;
            }}
            to {{
                transform: translateY(0);
                opacity: 1;
            }}
        }}
        .toast {{
            position: fixed;
            top: 20px;
            right: 20px;
            background: #4caf50;
            color: white;
            padding: 20px 30px;
            border-radius: 12px;
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.3);
            font-weight: 600;
            font-size: 16px;
            z-index: 10000;
            animation: toastSlideIn 0.4s ease-out;
            max-width: 400px;
        }}
        .toast.error {{
            background: #f44336;
        }}
        @keyframes toastSlideIn {{
            from {{
                transform: translateX(400px);
                opacity: 0;
            }}
            to {{
                transform: translateX(0);
                opacity: 1;
            }}
        }}
        @keyframes toastSlideOut {{
            from {{
                transform: translateX(0);
                opacity: 1;
            }}
            to {{
                transform: translateX(400px);
                opacity: 0;
            }}
        }}
        .category-checkbox {{
            display: flex;
            align-items: flex-start;
            padding: 15px;
            background: #f9f9f9;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.2s;
        }}
        .category-checkbox:hover {{
            background: #f0f0f0;
        }}
        .category-checkbox input[type="checkbox"] {{
            margin-right: 12px;
            margin-top: 2px;
            width: 18px;
            height: 18px;
            cursor: pointer;
        }}
        .token-section {{
            background: #f5f5f5;
            padding: 20px;
            border-radius: 5px;
            margin-top: 30px;
            border-top: 1px solid #ddd;
        }}
        code {{
            background: #263238;
            color: #aed581;
            padding: 10px;
            display: block;
            border-radius: 5px;
            word-break: break-all;
            font-size: 13px;
            margin-top: 10px;
        }}
    </style>
</head>
<body>
    <!-- Navigation Bar -->
    <nav style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 15px 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin: -50px -20px 30px -20px;">
        <div style="display: flex; justify-content: space-between; align-items: center; max-width: 1000px; margin: 0 auto;">
            <a href="/" style="color: white; font-size: 1.5rem; font-weight: 700; text-decoration: none;">🤖 AI Email Assistant</a>
            <div style="display: flex; gap: 20px; align-items: center;">
                <a href="/dashboard?session_token={session_token}" style="color: white; text-decoration: none; padding: 8px 16px; border-radius: 6px; background: rgba(255,255,255,0.2); font-weight: 500;">Dashboard</a>
                <div style="background: rgba(255,255,255,0.15); padding: 8px 16px; border-radius: 20px; color: white; font-size: 14px;">{ctx.email}</div>
            </div>
        </div>
    </nav>

    <div class="container">
        <!-- Welcome/Success Banners -->
        {f'''
        <div style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: white; padding: 25px; border-radius: 12px; margin-bottom: 30px; animation: bannerSlideDown 0.5s ease-out;">
            <div style="font-size: 32px; margin-bottom: 10px;">🎉</div>
            <h2 style="color: white; margin: 0 0 10px 0; font-size: 24px;">Welcome{f", {first_name}" if first_name else ""}! Your 3-day trial starts now!</h2>
            <p style="margin: 0; font-size: 16px; opacity: 0.95;">All 85 tools are unlocked! Explore Gmail, Calendar, Docs, Sheets, Fathom, Instantly & more—completely free for 3 days.</p>
            <p style="margin: 10px 0 0 0; font-size: 14px; opacity: 0.9;">💡 After your trial, free users get 10 tool calls per day. Subscribe for unlimited access!</p>
        </div>
        ''' if is_new_user == 'True' else (f'''
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 25px; border-radius: 12px; margin-bottom: 30px; animation: bannerSlideDown 0.5s ease-out;">
            <div style="font-size: 32px; margin-bottom: 10px;">👋</div>
            <h2 style="color: white; margin: 0 0 10px 0; font-size: 24px;">Welcome back{f", {first_name}" if first_name else ""}!</h2>
            <p style="margin: 0; font-size: 16px; opacity: 0.95;">Good to see you again. Manage your subscriptions below or check the Setup tab to connect to Claude Desktop.</p>
        </div>
        ''' if (is_new_user == 'False' or welcome == 'true') else '')}

        {f'''
        <div style="background: linear-gradient(135deg, #4caf50 0%, #45a049 100%); color: white; padding: 25px; border-radius: 12px; margin-bottom: 30px; animation: bannerSlideDown 0.5s ease-out;">
            <div style="font-size: 32px; margin-bottom: 10px;">🎉</div>
            <h2 style="color: white; margin: 0 0 10px 0; font-size: 24px;">Subscription Successful!</h2>
            <p style="margin: 0 0 15px 0; font-size: 16px; opacity: 0.95;">Your tools are now active! Go to the Setup tab to connect to Claude Desktop.</p>
            <button onclick="this.parentElement.style.display='none'" style="background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.5); color: white; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-size: 14px;">Got it! ✓</button>
        </div>
        ''' if subscription_success == 'true' else ''}

        <!-- Trial Status Banner -->
        {f'''
        <div style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: white; padding: 25px; border-radius: 12px; margin-bottom: 30px; box-shadow: 0 4px 12px rgba(245, 158, 11, 0.3);">
            <div style="display: flex; align-items: center; gap: 20px;">
                <div style="font-size: 48px;">🎉</div>
                <div style="flex: 1;">
                    <h2 style="color: white; margin: 0 0 8px 0; font-size: 22px; font-weight: 700;">Free Trial Active!</h2>
                    <p style="margin: 0 0 12px 0; font-size: 15px; opacity: 0.95;">
                        You have <strong>{trial_status["days_remaining"]} days and {trial_status["hours_remaining"] % 24} hours</strong> remaining in your trial.
                    </p>
                    <p style="margin: 0; font-size: 14px; opacity: 0.9;">
                        All 85 tools are unlocked! Subscribe before your trial ends to keep unlimited access.
                    </p>
                </div>
            </div>
        </div>
        ''' if trial_status['is_trial'] else ''}

        <!-- Usage Counter -->
        <div style="background: {"linear-gradient(135deg, #ef4444 0%, #dc2626 100%)" if usage_limit and daily_usage >= 8 else "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"}; color: white; padding: 25px; border-radius: 12px; margin-bottom: 30px;">
            <div style="display: flex; align-items: center; gap: 20px;">
                <div style="font-size: 48px;">{"⚠️" if usage_limit and daily_usage >= 8 else "📊"}</div>
                <div style="flex: 1;">
                    <h3 style="color: white; margin: 0 0 12px 0; font-size: 18px; font-weight: 600;">
                        {f"Daily Usage Limit ({daily_usage}/{usage_limit} calls today)" if usage_limit else f"Usage Today: {daily_usage} calls"}
                    </h3>
                    {f"""
                    <div style="background: rgba(255,255,255,0.2); border-radius: 10px; height: 12px; overflow: hidden; margin-bottom: 12px;">
                        <div style="background: {"#ef4444" if usage_limit and daily_usage >= 8 else "#10b981"}; height: 100%; width: {min(100, (daily_usage / usage_limit) * 100) if usage_limit else 0}%; transition: width 0.3s;"></div>
                    </div>
                    <p style="margin: 0; font-size: 14px; opacity: 0.95;">
                        {f"You have {usage_limit - daily_usage} calls remaining today. " if usage_limit and daily_usage < usage_limit else ""}
                        {f"<strong>⚠️ You're close to your limit! </strong> Upgrade to get unlimited usage." if usage_limit and daily_usage >= 8 and daily_usage < usage_limit else ""}
                        {f"<strong>🚫 Limit exceeded! </strong> Subscribe to continue using tools." if usage_limit and daily_usage >= usage_limit else ""}
                    </p>
                    """ if usage_limit else f"""<p style="margin: 0; font-size: 14px; opacity: 0.9;">✨ Unlimited usage ({"Active Trial" if trial_status["is_trial"] else "Paid Subscription"})</p>"""}</div>
            </div>
        </div>

        <!-- Tabs -->
        <div style="display: flex; gap: 10px; margin-bottom: 30px; border-bottom: 2px solid #e2e8f0;">
            <button class="tab active" data-tab="subscriptions" style="padding: 12px 24px; background: none; border: none; color: #667eea; font-size: 16px; font-weight: 600; cursor: pointer; border-bottom: 3px solid #667eea; transition: all 0.2s;">💰 Subscriptions</button>
            {f'<button class="tab" data-tab="teams" style="padding: 12px 24px; background: none; border: none; color: #718096; font-size: 16px; font-weight: 600; cursor: pointer; border-bottom: 3px solid transparent; transition: all 0.2s;">👥 Teams</button>' if teams_enabled else ''}
            <button class="tab" data-tab="api-keys" style="padding: 12px 24px; background: none; border: none; color: #718096; font-size: 16px; font-weight: 600; cursor: pointer; border-bottom: 3px solid transparent; transition: all 0.2s;">🔑 API Keys</button>
            <button class="tab" data-tab="setup" style="padding: 12px 24px; background: none; border: none; color: #718096; font-size: 16px; font-weight: 600; cursor: pointer; border-bottom: 3px solid transparent; transition: all 0.2s;">⚙️ Setup</button>
        </div>

        <div id="success-message" class="success"></div>
        <div id="error-message" class="error"></div>

        <!-- Tab Content: Subscriptions -->
        <div class="tab-content active" id="subscriptions">
            <!-- Active Subscriptions -->
            {f'''<div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; padding: 25px; border-radius: 12px; margin-bottom: 30px;">
                <h2 style="color: white; font-size: 1.5rem; margin-bottom: 20px;">✅ Currently Active ({len(active_subscriptions)} {("category" if len(active_subscriptions) == 1 else "categories")})</h2>
                <div style="display: flex; flex-direction: column; gap: 10px;">
                    {"".join([
                        f'''<div style="background: white; color: #1a202c; padding: 15px 20px; border-radius: 12px; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 2px 6px rgba(0,0,0,0.1);">
                            <div style="display: flex; align-items: center; gap: 12px;">
                                <span style="font-size: 28px;">{category_info[cat]["emoji"]}</span>
                                <div>
                                    <div style="font-weight: 600; font-size: 16px;">{category_info[cat]["name"]}</div>
                                    <div style="font-size: 14px; color: #6b7280;">{category_info[cat]["tools"]} tools • $5/month</div>
                                </div>
                            </div>
                            {
                                f'<span style="background: #fef3c7; color: #92400e; padding: 4px 12px; border-radius: 12px; font-size: 13px; font-weight: 600;">⚠️ Cancels {subscription_details[cat]["cancel_at"][:10]}</span>'
                                if subscription_details.get(cat, {}).get('cancel_at')
                                else '<span style="background: #d1fae5; color: #065f46; padding: 4px 12px; border-radius: 12px; font-size: 13px; font-weight: 600;">● Active</span>'
                            }
                        </div>'''
                        for cat in active_subscriptions
                    ])}
                </div>
                <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid rgba(255,255,255,0.2);">
                    <div style="font-size: 18px; font-weight: 600;">Total: ${len(active_subscriptions) * 5}/month</div>
                </div>
            </div>''' if active_subscriptions else '<div style="background: white; padding: 40px; border-radius: 12px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 30px;"><div style="font-size: 64px; margin-bottom: 15px;">📭</div><div style="font-size: 18px; font-weight: 600; color: #1a202c; margin-bottom: 8px;">No Active Subscriptions</div><div style="font-size: 15px; color: #6b7280;">Subscribe to categories below to get started!</div></div>'}

            <!-- Manage Button -->
            <div style="text-align: center; margin-bottom: 40px;">
                <a href="/billing?session_token={session_token}" style="display: inline-block; padding: 12px 24px; background: #e2e8f0; color: #4a5568; text-decoration: none; border-radius: 8px; font-weight: 600; transition: all 0.2s; font-size: 15px;">💳 Manage Subscriptions in Stripe</a>
            </div>

            <!-- Cancelled Subscriptions (with Resume button) -->
            {f'''<div style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: white; padding: 25px; border-radius: 12px; margin-bottom: 30px;">
                <h2 style="color: white; font-size: 1.5rem; margin-bottom: 20px;">⚠️ Cancelled Subscriptions ({len(cancelled_subscriptions)} {("category" if len(cancelled_subscriptions) == 1 else "categories")})</h2>
                <div style="display: flex; flex-direction: column; gap: 10px;">
                    {"".join([
                        f'''<div style="background: white; color: #1a202c; padding: 15px 20px; border-radius: 12px; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 2px 6px rgba(0,0,0,0.1);">
                            <div style="display: flex; align-items: center; gap: 12px;">
                                <span style="font-size: 28px;">{category_info[cat]["emoji"]}</span>
                                <div>
                                    <div style="font-weight: 600; font-size: 16px;">{category_info[cat]["name"]}</div>
                                    <div style="font-size: 14px; color: #6b7280;">{category_info[cat]["tools"]} tools • $5/month</div>
                                </div>
                            </div>
                            <button onclick="resumeSubscription('{cat}')" style="background: #10b981; color: white; padding: 8px 16px; border: none; border-radius: 6px; font-size: 14px; font-weight: 600; cursor: pointer; transition: opacity 0.2s;">
                                ↻ Resume
                            </button>
                        </div>'''
                        for cat in cancelled_subscriptions
                    ])}
                </div>
            </div>''' if cancelled_subscriptions else ''}

            <!-- Available Subscriptions -->
            <div style="background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 30px;">
                <h2 style="font-size: 1.5rem; color: #1a202c; margin-bottom: 10px;">Subscribe to More Tools</h2>
                <p style="color: #718096; margin-bottom: 25px;">Select categories to add ($5/month each)</p>

                <!-- Team Subscription Selector -->
                {f'''
                <div style="background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%); padding: 20px; border-radius: 10px; margin-bottom: 25px; border: 2px solid #667eea30;">
                    <div style="margin-bottom: 15px;">
                        <label style="font-size: 14px; font-weight: 600; color: #374151; display: block; margin-bottom: 10px;">
                            Subscribe for:
                        </label>
                        <div style="display: flex; flex-direction: column; gap: 10px;">
                            <label style="display: flex; align-items: center; padding: 12px; background: white; border: 2px solid #e2e8f0; border-radius: 8px; cursor: pointer; transition: all 0.2s;" class="subscription-type-option">
                                <input type="radio" name="subscription-type" value="personal" checked onchange="updateSubscriptionType()" style="width: 18px; height: 18px; margin-right: 12px; cursor: pointer;">
                                <div style="flex: 1;">
                                    <div style="font-weight: 600; color: #1a202c;">👤 Personal (Just Me)</div>
                                    <div style="font-size: 13px; color: #6b7280;">Only you will have access to these tools</div>
                                </div>
                            </label>
                            {chr(10).join([f"""
                            <label style="display: flex; align-items: center; padding: 12px; background: white; border: 2px solid #e2e8f0; border-radius: 8px; cursor: pointer; transition: all 0.2s;" class="subscription-type-option">
                                <input type="radio" name="subscription-type" value="{team['team_id']}" onchange="updateSubscriptionType()" style="width: 18px; height: 18px; margin-right: 12px; cursor: pointer;">
                                <div style="flex: 1;">
                                    <div style="font-weight: 600; color: #1a202c;">👥 Team: {team['team_name']}</div>
                                    <div style="font-size: 13px; color: #6b7280;">All {len(server.database.get_team_members(team['team_id']))} team members will have access</div>
                                </div>
                            </label>
                            """ for team in user_teams if team['role'] in ['owner', 'admin']])}
                        </div>
                    </div>
                    <div style="background: #dbeafe; border-left: 4px solid #3b82f6; padding: 12px; border-radius: 6px;">
                        <p style="margin: 0; font-size: 13px; color: #1e40af;">
                            <strong>💡 Tip:</strong> <span id="subscription-tip">Personal subscriptions are just for you. Team subscriptions give all members access!</span>
                        </p>
                    </div>
                </div>
                ''' if user_teams else ''}

                <div id="subscription-cart" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 15px; margin-bottom: 30px;">
                    {''.join([f'''
                        <label class="subscription-item" data-category="{cat}" style="display: flex; flex-direction: column; padding: 20px; border: 2px solid #e2e8f0; border-radius: 12px; cursor: pointer; background: white; transition: all 0.2s;">
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 15px;">
                                <span style="font-size: 36px;">{category_info[cat]["emoji"]}</span>
                                <div class="subscription-status">
                                    <input type="checkbox" name="subscribe-{cat}" value="{cat}" class="subscription-checkbox" style="width: 22px; height: 22px; cursor: pointer;">
                                </div>
                            </div>
                            <h3 style="margin: 0 0 8px 0; font-size: 18px; color: #1a202c;">{category_info[cat]["name"]}</h3>
                            <p style="margin: 0 0 12px 0; font-size: 14px; color: #6b7280; flex: 1;">{category_info[cat]["desc"]}</p>
                            <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 12px; border-top: 1px solid #e2e8f0;">
                                <span style="font-size: 13px; color: #9ca3af;">{category_info[cat]["tools"]} tools</span>
                                <span style="font-size: 16px; font-weight: 700; color: #667eea;">$5/mo</span>
                            </div>
                            {f'<div style="font-size: 12px; color: #f59e0b; margin-top: 8px;">{category_info[cat].get("note", "")}</div>' if cat in ['fathom', 'instantly', 'bison'] else ''}
                        </label>
                    ''' for cat in all_categories])}
                </div>

                <!-- Cart Summary -->
                <div id="cart-summary" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 12px; display: none;">
                    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 20px;">
                        <div>
                            <div style="font-size: 36px; font-weight: 700;">$<span id="cart-total">0</span><span style="font-size: 18px; opacity: 0.8;">/month</span></div>
                            <div style="opacity: 0.9; margin-top: 5px;"><span id="cart-count">0</span> categories selected</div>
                        </div>
                        <button id="checkout-btn" style="background: white; color: #667eea; padding: 18px 36px; border: none; border-radius: 10px; font-size: 17px; font-weight: 700; cursor: pointer; box-shadow: 0 6px 20px rgba(0,0,0,0.15); transition: all 0.2s;">
                            🛒 Checkout Now
                        </button>
                    </div>
                    <div id="cart-items-list" style="margin-top: 20px; padding-top: 20px; border-top: 1px solid rgba(255,255,255,0.2); font-size: 14px; opacity: 0.9;"></div>
                </div>
            </div>
        </div>

        {f'''<!-- Tab Content: Teams -->
        <div class="tab-content" id="teams" style="display: none;">
            <div style="background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 30px;">
                <h2 style="font-size: 1.5rem; color: #1a202c; margin-bottom: 10px;">👥 Teams</h2>
                <p style="color: #718096; margin-bottom: 30px;">Share subscriptions with your team. One subscription covers everyone!</p>

                <!-- Create Team Section -->
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 12px; margin-bottom: 30px;">
                    <h3 style="color: white; font-size: 1.25rem; margin-bottom: 15px;">✨ Create a Team</h3>
                    <p style="color: rgba(255,255,255,0.9); margin-bottom: 20px; font-size: 15px;">
                        Team subscriptions cost the same as personal ($5/category/month), but all team members get access!
                    </p>

                    <form id="create-team-form" style="display: flex; gap: 15px; align-items: end;">
                        <div style="flex: 1;">
                            <label style="color: white; font-weight: 600; font-size: 14px; display: block; margin-bottom: 8px;">Team Name</label>
                            <input type="text" id="team-name-input" placeholder="e.g., Acme Marketing Team"
                                   style="width: 100%; padding: 12px; border: 2px solid rgba(255,255,255,0.3); background: rgba(255,255,255,0.15); color: white; border-radius: 8px; font-size: 15px; font-weight: 500;"
                                   required minlength="3" maxlength="50">
                        </div>
                        <button type="submit" style="background: white; color: #667eea; padding: 12px 32px; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; transition: all 0.2s; white-space: nowrap;">
                            Create Team
                        </button>
                    </form>
                </div>

                <!-- My Teams Section -->
                <div id="teams-list">
                    <h3 style="color: #1a202c; font-size: 1.25rem; margin-bottom: 15px;">My Teams</h3>
                    <div id="teams-container" style="display: flex; flex-direction: column; gap: 15px;">
                        <!-- Teams will be loaded here -->
                        <div style="text-align: center; padding: 60px; background: #f9fafb; border-radius: 12px;">
                            <div style="font-size: 48px; margin-bottom: 15px;">👥</div>
                            <p style="color: #6b7280; font-size: 16px;">Loading your teams...</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>''' if teams_enabled else ''}

        <!-- Tab Content: API Keys -->
        <div class="tab-content" id="api-keys" style="display: none;">
            <div style="background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
                <h2 style="font-size: 1.5rem; color: #1a202c; margin-bottom: 10px;">🔑 API Keys</h2>
                <p style="color: #718096; margin-bottom: 30px;">Add API keys for third-party services you've subscribed to</p>

                {f'''
                <form id="api-keys-form">
                    {'<div class="form-group"><label for="fathom_key">Fathom API Key</label><input type="text" id="fathom_key" name="fathom_key" value="' + api_keys.get('fathom', '') + '" placeholder="Your Fathom API key"><p style="font-size: 13px; color: #6b7280; margin-top: 5px;">Required for Fathom meeting recording tools</p></div>' if 'fathom' in active_subscriptions else ''}
                    {'<div class="form-group"><label for="instantly_key">Instantly API Key</label><input type="text" id="instantly_key" name="instantly_key" value="' + api_keys.get('instantly', '') + '" placeholder="Your Instantly.ai API key"><p style="font-size: 13px; color: #6b7280; margin-top: 5px;">Required for Instantly campaign management tools</p></div>' if 'instantly' in active_subscriptions else ''}
                    {'<div class="form-group"><label for="bison_key">Bison API Key</label><input type="text" id="bison_key" name="bison_key" value="' + api_keys.get('bison', '') + '" placeholder="Your EmailBison API key"><p style="font-size: 13px; color: #6b7280; margin-top: 5px;">Required for EmailBison campaign tools</p></div>' if 'bison' in active_subscriptions else ''}

                    {('<button type="submit" class="btn" style="background: #667eea; color: white; padding: 12px 24px; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; transition: all 0.2s;">💾 Save API Keys</button>' if any(cat in active_subscriptions for cat in ['fathom', 'instantly', 'bison']) else '<div style="text-align: center; padding: 40px; background: #f9fafb; border-radius: 8px;"><div style="font-size: 48px; margin-bottom: 10px;">🔒</div><p style="color: #6b7280;">Subscribe to Fathom, Instantly, or Bison tools to add API keys here.</p></div>')}
                </form>
                ''' if any(cat in active_subscriptions for cat in ['fathom', 'instantly', 'bison']) else '<div style="text-align: center; padding: 60px; background: #f9fafb; border-radius: 8px;"><div style="font-size: 64px; margin-bottom: 15px;">🔒</div><p style="color: #6b7280; font-size: 16px;">Subscribe to Fathom, Instantly, or Bison tools to add API keys here.</p></div>'}
            </div>
        </div>

        <!-- Tab Content: Setup -->
        <div class="tab-content" id="setup" style="display: none;">
            <div style="background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 20px;">
                <h2 style="font-size: 1.5rem; color: #1a202c; margin-bottom: 10px;">⚙️ Connect to Claude Desktop</h2>
                <p style="color: #718096; margin-bottom: 25px;">Add this remote MCP server to Claude Desktop</p>

                <div style="background: #fef3c7; padding: 20px; border-radius: 8px; margin-bottom: 30px; border-left: 4px solid #f59e0b;">
                    <strong style="color: #92400e; font-size: 16px;">📝 Setup Instructions:</strong>
                    <ol style="margin: 12px 0 0 20px; color: #92400e; line-height: 1.9; font-size: 15px;">
                        <li>Open <strong>Claude Desktop</strong></li>
                        <li>Go to <strong>Settings → Developer → MCP Servers</strong></li>
                        <li>Click <strong>"Add Server"</strong></li>
                        <li>Enter the name and URL below</li>
                        <li>Click <strong>"Save"</strong></li>
                        <li>Restart Claude Desktop</li>
                        <li>Your tools are ready! Try: <em>"Check my emails"</em></li>
                    </ol>
                </div>

                <div style="display: grid; gap: 20px; margin-bottom: 30px;">
                    <div>
                        <h3 style="color: #1a202c; margin-bottom: 10px; font-size: 16px;">📌 Server Name</h3>
                        <input type="text" value="AI Email Assistant" readonly onclick="this.select()" style="width: 100%; padding: 14px; background: #f7fafc; border: 2px solid #e2e8f0; border-radius: 8px; font-size: 15px; cursor: pointer; font-weight: 600;">
                        <p style="color: #9ca3af; font-size: 12px; margin-top: 6px;">Click to select and copy</p>
                    </div>

                    <div>
                        <h3 style="color: #1a202c; margin-bottom: 10px; font-size: 16px;">🔗 Server URL</h3>
                        <input type="text" value="https://{request.url.hostname}/mcp?session_token={session_token}" readonly onclick="this.select()" style="width: 100%; padding: 14px; background: #f7fafc; border: 2px solid #e2e8f0; border-radius: 8px; font-family: monospace; font-size: 12px; cursor: pointer; word-break: break-all;">
                        <p style="color: #9ca3af; font-size: 12px; margin-top: 6px;">Click to select and copy</p>
                    </div>
                </div>

                <div style="background: #e0f2fe; padding: 20px; border-radius: 8px; border-left: 4px solid #0284c7;">
                    <div style="display: flex; align-items: start; gap: 12px;">
                        <div style="font-size: 24px;">💡</div>
                        <div>
                            <strong style="color: #075985; font-size: 15px;">Keep Your Session Token Secure</strong>
                            <p style="color: #0c4a6e; margin: 8px 0 0 0; font-size: 14px; line-height: 1.6;">
                                This URL contains your personal session token. Anyone with this URL can access your tools. Don't share it publicly or commit it to version control.
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Admin password from URL or use cookie-based auth
        const adminPassword = new URLSearchParams(window.location.search).get('admin_password') || '';

        // Tab switching
        document.querySelectorAll('.tab').forEach(tab => {{
            tab.addEventListener('click', () => {{
                const tabName = tab.dataset.tab;

                // Update tabs
                document.querySelectorAll('.tab').forEach(t => {{
                    t.style.color = '#718096';
                    t.style.borderBottomColor = 'transparent';
                }});
                tab.style.color = '#667eea';
                tab.style.borderBottomColor = '#667eea';

                // Update content
                document.querySelectorAll('.tab-content').forEach(content => content.style.display = 'none');
                document.getElementById(tabName).style.display = 'block';
            }});
        }});

        // Toast notification
        function showToast(message, type = 'success') {{
            const toast = document.createElement('div');
            toast.className = 'toast' + (type === 'error' ? ' error' : '');
            toast.textContent = message;
            document.body.appendChild(toast);
            setTimeout(() => {{
                toast.style.animation = 'toastSlideOut 0.4s ease-out';
                setTimeout(() => document.body.removeChild(toast), 400);
            }}, 4000);
        }}

        // Shopping Cart Logic
        const cart = new Set();
        const cartSummary = document.getElementById('cart-summary');
        const cartTotal = document.getElementById('cart-total');
        const cartCount = document.getElementById('cart-count');
        const cartItemsList = document.getElementById('cart-items-list');
        const checkoutBtn = document.getElementById('checkout-btn');

        const categoryNames = {{
            'gmail': 'Gmail Tools',
            'calendar': 'Calendar Tools',
            'docs': 'Google Docs Tools',
            'sheets': 'Google Sheets Tools',
            'fathom': 'Fathom Tools',
            'instantly': 'Instantly Tools',
            'bison': 'Bison Tools'
        }};

        // Subscription data for dynamic filtering
        const personalSubscriptions = {json.dumps(personal_subscriptions)};
        const teamSubscriptionsMap = {json.dumps(team_subscriptions_map)};

        console.log('Personal Subscriptions:', personalSubscriptions);
        console.log('Team Subscriptions Map:', teamSubscriptionsMap);

        function updateCart() {{
            if (cart.size > 0) {{
                cartSummary.style.display = 'block';
                cartTotal.textContent = cart.size * 5;
                cartCount.textContent = cart.size;
                // Filter out any undefined category names
                cartItemsList.innerHTML = Array.from(cart).filter(cat => categoryNames[cat]).map(cat => `• ${{categoryNames[cat]}} - $5/mo`).join('<br>');
            }} else {{
                cartSummary.style.display = 'none';
            }}
        }}

        // Resume subscription function
        async function resumeSubscription(category) {{
            if (!confirm(`Resume ${{categoryNames[category]}} subscription ($5/month)?`)) return;

            try {{
                const response = await fetch(`/resume-subscription?session_token={session_token}&category=${{category}}`, {{
                    method: 'POST'
                }});

                const data = await response.json();

                if (response.ok) {{
                    if (data.checkout_url) {{
                        // Redirect to Stripe Checkout for payment
                        window.location.href = data.checkout_url;
                    }} else {{
                        // Free/admin subscription - just reload
                        showToast(`${{categoryNames[category]}} subscription resumed!`, 'success');
                        setTimeout(() => location.reload(), 1500);
                    }}
                }} else {{
                    showToast(data.message || data.error || 'Failed to resume subscription', 'error');
                }}
            }} catch (error) {{
                showToast('Network error. Please try again.', 'error');
                console.error('Resume error:', error);
            }}
        }}

        document.querySelectorAll('.subscription-checkbox').forEach(checkbox => {{
            checkbox.addEventListener('change', (e) => {{
                const category = e.target.value;
                if (e.target.checked) {{
                    cart.add(category);
                    e.target.closest('.subscription-item').style.borderColor = '#667eea';
                    e.target.closest('.subscription-item').style.background = '#f0f4ff';
                }} else {{
                    cart.delete(category);
                    e.target.closest('.subscription-item').style.borderColor = '#e2e8f0';
                    e.target.closest('.subscription-item').style.background = 'white';
                }}
                updateCart();
            }});
        }});

        // Update subscription type UI feedback
        function updateSubscriptionType() {{
            const selectedType = document.querySelector('input[name="subscription-type"]:checked');
            const tip = document.getElementById('subscription-tip');

            // Update border styles
            document.querySelectorAll('.subscription-type-option').forEach(label => {{
                if (label.contains(selectedType)) {{
                    label.style.borderColor = '#667eea';
                    label.style.background = '#f0f4ff';
                }} else {{
                    label.style.borderColor = '#e2e8f0';
                    label.style.background = 'white';
                }}
            }});

            // Determine which subscriptions to check against
            let existingSubscriptions = [];
            if (selectedType.value === 'personal') {{
                existingSubscriptions = personalSubscriptions;
                tip.textContent = "These subscriptions will be just for you. Other users won't have access.";
                console.log('Selected PERSONAL - Checking against:', existingSubscriptions);
            }} else {{
                const teamId = selectedType.value;
                existingSubscriptions = teamSubscriptionsMap[teamId] || [];
                tip.innerHTML = "<strong>Subscribing for entire team!</strong> All members will instantly get access to these tools.";
                console.log('Selected TEAM (' + teamId + ') - Checking against:', existingSubscriptions);
            }}

            // Update category items availability
            document.querySelectorAll('.subscription-item').forEach(item => {{
                const category = item.dataset.category;
                const statusDiv = item.querySelector('.subscription-status');
                const wasInCart = cart.has(category);

                if (existingSubscriptions.includes(category)) {{
                    // Already subscribed - show as disabled
                    item.style.cursor = 'not-allowed';
                    item.style.opacity = '0.6';
                    item.style.borderColor = '#10b981';
                    item.style.background = '#f0fdf4';
                    statusDiv.innerHTML = '<span style="background: #d1fae5; color: #065f46; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600;">✓ Subscribed</span>';

                    // Remove from cart if it was selected
                    cart.delete(category);
                }} else {{
                    // Available for subscription - show checkbox
                    item.style.cursor = 'pointer';
                    item.style.opacity = '1';
                    item.style.borderColor = wasInCart ? '#667eea' : '#e2e8f0';
                    item.style.background = 'white';
                    statusDiv.innerHTML = '<input type="checkbox" name="subscribe-' + category + '" value="' + category + '" class="subscription-checkbox" style="width: 22px; height: 22px; cursor: pointer;"' + (wasInCart ? ' checked' : '') + '>';

                    // Re-attach event listener to new checkbox
                    const newCheckbox = statusDiv.querySelector('.subscription-checkbox');
                    newCheckbox.addEventListener('change', (e) => {{
                        const cat = e.target.value;
                        if (e.target.checked) {{
                            cart.add(cat);
                            e.target.closest('.subscription-item').style.borderColor = '#667eea';
                        }} else {{
                            cart.delete(cat);
                            e.target.closest('.subscription-item').style.borderColor = '#e2e8f0';
                        }}
                        updateCart();
                    }});
                }}
            }});

            updateCart();
        }}

        checkoutBtn.addEventListener('click', async () => {{
            if (cart.size === 0) return;
            const categories = Array.from(cart);
            const selectedType = document.querySelector('input[name="subscription-type"]:checked');
            const subscriptionType = selectedType ? selectedType.value : 'personal';

            // Build payload
            const payload = {{ categories: categories }};

            // Add team_id if team subscription selected
            if (subscriptionType !== 'personal') {{
                payload.team_id = subscriptionType;
            }}

            try {{
                const response = await fetch('/subscribe?session_token={session_token}', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify(payload)
                }});

                const data = await response.json();

                if (response.ok && data.checkout_url) {{
                    window.location.href = data.checkout_url;
                }} else {{
                    showToast(data.error || 'Failed to create checkout session', 'error');
                }}
            }} catch (error) {{
                showToast('Network error. Please try again.', 'error');
                console.error('Checkout error:', error);
            }}
        }});

        // Initialize subscription type filtering on page load
        if (document.querySelector('input[name="subscription-type"]')) {{
            updateSubscriptionType();
        }}

        // API Keys form
        const apiKeysForm = document.getElementById('api-keys-form');
        if (apiKeysForm) {{
            apiKeysForm.addEventListener('submit', async (e) => {{
                e.preventDefault();

                const formData = {{}};
                ['fathom_key', 'instantly_key', 'bison_key'].forEach(field => {{
                    const input = document.getElementById(field);
                    if (input && input.value.trim()) {{
                        const keyName = field.replace('_key', '');
                        formData[keyName] = input.value.trim();
                    }}
                }});

                try {{
                    const response = await fetch('/dashboard/update-api-keys?session_token={session_token}', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify(formData)
                    }});

                    if (response.ok) {{
                        showToast('✓ API keys saved successfully!');
                    }} else {{
                        const error = await response.json();
                        showToast('Error: ' + error.detail, 'error');
                    }}
                }} catch (error) {{
                    showToast('Network error. Please try again.', 'error');
                }}
            }});
        }}

        // Team creation form
        const createTeamForm = document.getElementById('create-team-form');
        if (createTeamForm) {{
            createTeamForm.addEventListener('submit', async (e) => {{
                e.preventDefault();

                const teamNameInput = document.getElementById('team-name-input');
                const teamName = teamNameInput.value.trim();

                if (!teamName || teamName.length < 3) {{
                    showToast('Team name must be at least 3 characters', 'error');
                    return;
                }}

                try {{
                    const response = await fetch('/teams?session_token={session_token}', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{ team_name: teamName }})
                    }});

                    if (response.ok) {{
                        const data = await response.json();
                        showToast('✓ Team "' + teamName + '" created successfully!');
                        teamNameInput.value = '';  // Clear input
                        loadTeams();  // Reload teams list
                    }} else {{
                        const error = await response.json();
                        showToast('Error: ' + error.detail, 'error');
                    }}
                }} catch (error) {{
                    showToast('Network error. Please try again.', 'error');
                }}
            }});
        }}

        // Load teams function
        async function loadTeams() {{
            const teamsContainer = document.getElementById('teams-container');
            if (!teamsContainer) return;

            try {{
                const response = await fetch('/teams?session_token={session_token}');

                if (!response.ok) {{
                    teamsContainer.innerHTML = `
                        <div style="text-align: center; padding: 60px; background: #fee; border-radius: 12px;">
                            <div style="font-size: 48px; margin-bottom: 15px;">❌</div>
                            <p style="color: #c00; font-size: 16px;">Failed to load teams</p>
                        </div>
                    `;
                    return;
                }}

                const data = await response.json();
                const teams = data.teams || [];

                if (teams.length === 0) {{
                    teamsContainer.innerHTML = `
                        <div style="text-align: center; padding: 60px; background: #f9fafb; border-radius: 12px;">
                            <div style="font-size: 64px; margin-bottom: 15px;">👥</div>
                            <div style="font-size: 18px; font-weight: 600; color: #1a202c; margin-bottom: 8px;">No Teams Yet</div>
                            <p style="color: #6b7280; font-size: 15px;">Create your first team above to get started!</p>
                        </div>
                    `;
                }} else {{
                    teamsContainer.innerHTML = teams.map(team => `
                        <div style="background: white; padding: 25px; border-radius: 12px; border: 2px solid #e2e8f0; transition: all 0.2s; cursor: pointer;" onmouseover="this.style.borderColor='#667eea'" onmouseout="this.style.borderColor='#e2e8f0'">
                            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 15px;">
                                <div style="flex: 1;">
                                    <h3 style="margin: 0 0 8px 0; font-size: 20px; color: #1a202c; font-weight: 600;">${{team.team_name}}</h3>
                                    <div style="display: flex; gap: 15px; font-size: 14px; color: #6b7280;">
                                        <span>👤 ${{team.role === 'owner' ? '<strong style="color: #667eea;">Owner</strong>' : 'Member'}}</span>
                                        <span>📅 Created ${{new Date(team.created_at).toLocaleDateString()}}</span>
                                    </div>
                                </div>
                                <span style="background: #667eea; color: white; padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 600;">
                                    ${{team.member_count}} ${{team.member_count === 1 ? 'member' : 'members'}}
                                </span>
                            </div>
                            <div style="padding-top: 15px; border-top: 1px solid #e2e8f0; display: flex; gap: 10px;">
                                <button onclick="viewTeam('${{team.team_id}}')" style="flex: 1; background: #667eea; color: white; padding: 10px 20px; border: none; border-radius: 6px; font-size: 14px; font-weight: 600; cursor: pointer;">
                                    View Team
                                </button>
                                ${{team.role === 'owner' ? `
                                <button onclick="manageTeam('${{team.team_id}}')" style="background: #e2e8f0; color: #4a5568; padding: 10px 20px; border: none; border-radius: 6px; font-size: 14px; font-weight: 600; cursor: pointer;">
                                    ⚙️ Manage
                                </button>
                                ` : ''}}
                            </div>
                        </div>
                    `).join('');
                }}
            }} catch (error) {{
                console.error('Error loading teams:', error);
                teamsContainer.innerHTML = `
                    <div style="text-align: center; padding: 60px; background: #fee; border-radius: 12px;">
                        <div style="font-size: 48px; margin-bottom: 15px;">❌</div>
                        <p style="color: #c00; font-size: 16px;">Error loading teams</p>
                    </div>
                `;
            }}
        }}

        // View team function (placeholder)
        function viewTeam(teamId) {{
            window.location.href = `/team/${{teamId}}?session_token={session_token}`;
        }}

        // Manage team function (navigate to team settings)
        function manageTeam(teamId) {{
            window.location.href = `/team/${{teamId}}?session_token={session_token}`;
        }}

        // Load teams when Teams tab is opened
        document.querySelectorAll('.tab').forEach(tab => {{
            const originalClick = tab.onclick;
            tab.addEventListener('click', () => {{
                const tabName = tab.dataset.tab;
                if (tabName === 'teams') {{
                    loadTeams();
                }}
            }});
        }});

        // Initial load if on Teams tab (shouldn't happen on page load, but just in case)
        if (window.location.hash === '#teams') {{
            loadTeams();
        }}
    </script>
</body>

</html>
    """)


@app.post("/dashboard/update-api-keys")
async def update_api_keys_endpoint(
    request: Request,
    session_token: Optional[str] = Query(None)
):
    """Update user's API keys."""
    if not session_token:
        raise HTTPException(401, "Missing session token")

    # Validate session token
    try:
        ctx = await get_request_context(None, session_token)
    except HTTPException:
        raise HTTPException(401, "Invalid or expired session token")

    # Parse request body
    body = await request.json()
    api_keys = {
        key: value.strip()
        for key, value in body.items()
        if value and value.strip()  # Only store non-empty keys
    }

    # Update in database
    server.database.update_api_keys(ctx.user_id, api_keys)

    return {"success": True, "message": "API keys updated"}


@app.post("/dashboard/update-tool-categories")
async def update_tool_categories_endpoint(
    request: Request,
    session_token: Optional[str] = Query(None)
):
    """Update user's enabled tool categories."""
    if not session_token:
        raise HTTPException(401, "Missing session token")

    # Validate session token
    try:
        ctx = await get_request_context(None, session_token)
    except HTTPException:
        raise HTTPException(401, "Invalid or expired session token")

    # Parse request body
    body = await request.json()
    categories = body.get('categories', [])

    # Validate categories
    valid_categories = ['gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison']
    categories = [cat for cat in categories if cat in valid_categories]

    # Update in database
    server.database.update_tool_categories(ctx.user_id, categories if categories else [])

    # Calculate tool count
    tool_counts = {'gmail': 25, 'calendar': 15, 'docs': 8, 'sheets': 12, 'fathom': 11, 'instantly': 10, 'bison': 4}
    total_tools = sum(tool_counts[cat] for cat in categories) if categories else 0

    logger.info(f"Updated tool categories for user {ctx.email}: {categories} ({total_tools} tools)")

    return {
        "success": True,
        "message": "Tool preferences updated",
        "tool_count": total_tools,
        "categories": categories
    }


# ===========================================================================
# TEAM MANAGEMENT ENDPOINTS
# ===========================================================================

@app.post("/teams")
async def create_team_endpoint(
    request: Request,
    session_token: Optional[str] = Query(None)
):
    """Create a new team."""
    if not session_token:
        raise HTTPException(401, "Missing session token")

    # Validate session token
    try:
        ctx = await get_request_context(None, session_token)
    except HTTPException:
        raise HTTPException(401, "Invalid or expired session token")

    # Check if user has team access enabled
    user = server.database.get_user_by_session(session_token)
    if not user:
        raise HTTPException(401, "User not found")

    if not user.get('teams_enabled', False):
        raise HTTPException(403, "Team access is not enabled for your account. Please contact support.")

    # Parse request body
    body = await request.json()
    team_name = body.get('team_name', '').strip()

    if not team_name:
        raise HTTPException(400, "Team name is required")

    if len(team_name) < 3:
        raise HTTPException(400, "Team name must be at least 3 characters")

    if len(team_name) > 50:
        raise HTTPException(400, "Team name must be 50 characters or less")

    # Create team in database (user already fetched above for teams_enabled check)
    team = server.database.create_team(
        team_name=team_name,
        owner_user_id=ctx.user_id,
        billing_email=user['email']
    )

    logger.info(f"Team created: {team['team_id']} by user {ctx.email}")

    return {
        "success": True,
        "team": team
    }


@app.get("/teams")
async def get_user_teams_endpoint(
    session_token: Optional[str] = Query(None)
):
    """Get all teams for the current user with member counts."""
    if not session_token:
        raise HTTPException(401, "Missing session token")

    # Validate session token
    try:
        ctx = await get_request_context(None, session_token)
    except HTTPException:
        raise HTTPException(401, "Invalid or expired session token")

    # Get user's teams
    teams = server.database.get_user_teams(ctx.user_id)

    # Add member count for each team
    for team in teams:
        members = server.database.get_team_members(team['team_id'])
        team['member_count'] = len(members)

    return {
        "success": True,
        "teams": teams
    }


@app.get("/team/{team_id}", response_class=HTMLResponse)
async def team_settings_page(
    request: Request,
    team_id: str,
    session_token: Optional[str] = Query(None)
):
    """Team settings and management page."""
    if not session_token:
        return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>Login Required</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: system-ui; max-width: 600px; margin: 50px auto; padding: 20px;">
    <h1>🔒 Login Required</h1>
    <p>Please log in to view team settings.</p>
</body>
</html>
        """, status_code=401)

    # Validate session token
    try:
        ctx = await get_request_context(None, session_token)
    except HTTPException:
        return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>Invalid Session</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: system-ui; max-width: 600px; margin: 50px auto; padding: 20px;">
    <h1>❌ Invalid Session</h1>
    <p>Your session has expired. Please log in again.</p>
</body>
</html>
        """, status_code=401)

    # Get team details
    team_result = server.database.supabase.table('teams').select('*').eq('team_id', team_id).execute()
    if not team_result.data:
        raise HTTPException(404, "Team not found")

    team = team_result.data[0]

    # Check if user is a member of this team
    members = server.database.get_team_members(team_id)
    user_member = next((m for m in members if m['user_id'] == ctx.user_id), None)

    if not user_member:
        return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>Access Denied</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: system-ui; max-width: 600px; margin: 50px auto; padding: 20px;">
    <h1>🚫 Access Denied</h1>
    <p>You are not a member of this team.</p>
</body>
</html>
        """, status_code=403)

    # Get owner details
    owner_result = server.database.supabase.table('users').select('email').eq('user_id', team['owner_user_id']).execute()
    owner_email = owner_result.data[0]['email'] if owner_result.data else "Unknown"

    # Check if current user is owner or admin
    is_owner = ctx.user_id == team['owner_user_id']
    is_admin = user_member['role'] in ['owner', 'admin']

    # Get pending invitations
    invitations = []
    if is_admin:
        inv_result = server.database.supabase.table('team_invitations').select('*').eq('team_id', team_id).eq('status', 'pending').execute()
        invitations = inv_result.data if inv_result.data else []

    # Get team subscriptions
    subs_result = server.database.supabase.table('subscriptions').select('*').eq('team_id', team_id).eq('is_team_subscription', True).execute()
    team_subscriptions = subs_result.data if subs_result.data else []

    # Get team subscription categories
    team_subscription_categories = [sub['tool_category'] for sub in team_subscriptions if sub['status'] == 'active']

    # Get permissions for all team members
    permissions_map = server.database.get_team_all_permissions(team_id)

    # Get personal subscriptions for each member (to show what they have)
    member_personal_subs = {}
    for member in members:
        personal_subs_result = server.database.supabase.table('subscriptions').select('tool_category').eq(
            'user_id', member['user_id']
        ).eq('status', 'active').is_('team_id', 'null').execute()
        member_personal_subs[member['user_id']] = [sub['tool_category'] for sub in personal_subs_result.data]

    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>Team Settings - {team['team_name']}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f7fa;
            padding: 20px;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
        }}
        .header {{
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .header h1 {{
            font-size: 32px;
            color: #1a202c;
            margin-bottom: 10px;
        }}
        .header .meta {{
            color: #6b7280;
            font-size: 14px;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 10px;
        }}
        .badge-owner {{
            background: #fef3c7;
            color: #92400e;
        }}
        .badge-admin {{
            background: #dbeafe;
            color: #1e40af;
        }}
        .badge-member {{
            background: #e0e7ff;
            color: #3730a3;
        }}
        .section {{
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .section h2 {{
            font-size: 20px;
            color: #1a202c;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .member-list, .invitation-list, .subscription-list {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        .member-item, .invitation-item, .subscription-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            transition: all 0.2s;
        }}
        .member-item:hover {{
            border-color: #667eea;
        }}
        .member-info {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .member-avatar {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
        }}
        .member-details {{
            display: flex;
            flex-direction: column;
        }}
        .member-email {{
            font-weight: 600;
            color: #1a202c;
        }}
        .member-role {{
            font-size: 13px;
            color: #6b7280;
        }}
        .btn {{
            padding: 8px 16px;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .btn-primary {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        .btn-primary:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }}
        .btn-danger {{
            background: #fee;
            color: #c00;
            border: 1px solid #f88;
        }}
        .btn-danger:hover {{
            background: #fdd;
        }}
        .invite-form {{
            display: flex;
            gap: 12px;
            margin-top: 16px;
        }}
        .invite-form input {{
            flex: 1;
            padding: 12px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 15px;
        }}
        .invite-form input:focus {{
            outline: none;
            border-color: #667eea;
        }}
        .alert {{
            padding: 12px 16px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 14px;
            display: none;
        }}
        .alert-success {{
            background: #d1fae5;
            color: #065f46;
            border: 1px solid #6ee7b7;
        }}
        .alert-error {{
            background: #fee;
            color: #c00;
            border: 1px solid #f88;
        }}
        .back-link {{
            display: inline-block;
            margin-bottom: 20px;
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
        }}
        .back-link:hover {{
            text-decoration: underline;
        }}
        .empty-state {{
            text-align: center;
            padding: 40px 20px;
            color: #9ca3af;
        }}
        .empty-state-icon {{
            font-size: 48px;
            margin-bottom: 10px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <a href="/dashboard?session_token={session_token}" class="back-link">← Back to Dashboard</a>

        <div class="header">
            <h1>👥 {team['team_name']}</h1>
            <div class="meta">
                <strong>Owner:</strong> {owner_email}
                <span class="badge {'badge-owner' if is_owner else 'badge-' + user_member['role']}">
                    {'OWNER' if is_owner else user_member['role'].upper()}
                </span>
                <br>
                <strong>Members:</strong> {len(members)}
            </div>
        </div>

        <div id="success-message" class="alert alert-success"></div>
        <div id="error-message" class="alert alert-error"></div>

        <!-- Team Members -->
        <div class="section">
            <h2>
                <span>👤</span>
                Team Members
            </h2>
            <div class="member-list">
                {''.join([f'''
                <div class="member-item">
                    <div class="member-info">
                        <div class="member-avatar">{m['email'][0].upper()}</div>
                        <div class="member-details">
                            <div class="member-email">{m['email']}</div>
                            <div class="member-role">{m['role'].title()} • Joined {m['joined_at'][:10]}</div>
                        </div>
                    </div>
                    {'<button onclick="removeMember(&apos;' + m["user_id"] + '&apos;, &apos;' + m["email"] + '&apos;)" class="btn btn-danger">Remove</button>' if is_admin and m['user_id'] != ctx.user_id else ''}
                </div>
                ''' for m in members])}
            </div>
        </div>

        <!-- Add New Member -->
        {f'''
        <div class="section">
            <h2><span>➕</span> Add Team Member</h2>
            <p style="color: #6b7280; font-size: 14px; margin-bottom: 16px;">Add a member directly - account will be created if needed</p>
            <form class="add-member-form" onsubmit="addMember(event)">
                <div style="display: flex; flex-direction: column; gap: 16px;">
                    <div style="display: flex; gap: 12px;">
                        <div style="flex: 1;">
                            <label style="display: block; font-size: 13px; font-weight: 600; color: #374151; margin-bottom: 6px;">Email Address</label>
                            <input type="email" id="add-member-email" placeholder="member@example.com" required style="width: 100%; padding: 10px; border: 2px solid #e2e8f0; border-radius: 6px; font-size: 14px;">
                        </div>
                        <div style="min-width: 140px;">
                            <label style="display: block; font-size: 13px; font-weight: 600; color: #374151; margin-bottom: 6px;">Role</label>
                            <select id="add-member-role" required style="width: 100%; padding: 10px; border: 2px solid #e2e8f0; border-radius: 6px; font-size: 14px; background: white; cursor: pointer;">
                                <option value="member">Member</option>
                                <option value="admin">Admin</option>
                            </select>
                        </div>
                    </div>

                    <div>
                        <label style="display: block; font-size: 13px; font-weight: 600; color: #374151; margin-bottom: 8px;">Password</label>
                        <div style="display: flex; gap: 16px; margin-bottom: 12px;">
                            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                                <input type="radio" name="password-method" value="auto" checked onchange="togglePasswordMethod()" style="width: 16px; height: 16px; cursor: pointer;">
                                <span style="font-size: 14px; color: #374151;">Auto-generate password</span>
                            </label>
                            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                                <input type="radio" name="password-method" value="manual" onchange="togglePasswordMethod()" style="width: 16px; height: 16px; cursor: pointer;">
                                <span style="font-size: 14px; color: #374151;">Set password manually</span>
                            </label>
                        </div>
                        <div id="manual-password-container" style="display: none;">
                            <input type="password" id="add-member-password" placeholder="Enter password (min 8 characters)" minlength="8" style="width: 100%; padding: 10px; border: 2px solid #e2e8f0; border-radius: 6px; font-size: 14px;">
                            <p style="font-size: 12px; color: #6b7280; margin-top: 4px;">Password will be emailed to the user</p>
                        </div>
                    </div>

                    {('<div><label style="display: block; font-size: 13px; font-weight: 600; color: #374151; margin-bottom: 8px;">Grant Access to Tools</label><div style="background: #f9fafb; padding: 12px; border-radius: 6px; border: 2px solid #e2e8f0;"><div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px;">' + ''.join([f'<label style="display: flex; align-items: center; gap: 6px; cursor: pointer;"><input type="checkbox" name="tool-permission" value="{cat}" checked class="tool-permission-checkbox" style="width: 16px; height: 16px; cursor: pointer;"><span style="font-size: 13px; color: #374151;">{cat.title()}</span></label>' for cat in team_subscription_categories]) + '</div></div>' + ('<p style="font-size: 12px; color: #6b7280; margin-top: 6px;">💡 Select which team tools this member can access</p>' if team_subscription_categories else '<p style="font-size: 12px; color: #f59e0b; margin-top: 6px;">⚠️ No team subscriptions yet - subscribe first to grant access</p>') + '</div>' if team_subscription_categories else '')}

                    <div>
                        <button type="submit" class="btn btn-primary" style="padding: 10px 20px;">Add Member</button>
                    </div>
                </div>
            </form>
        </div>
        ''' if is_admin else ''}

        <!-- Pending Invitations -->
        {'<div class="section"><h2><span>⏳</span> Pending Invitations</h2>' + ('<div class="invitation-list">' + ''.join(['<div class="invitation-item"><div class="member-info"><div class="member-avatar">' + inv["email"][0].upper() + '</div><div class="member-details"><div class="member-email">' + inv["email"] + '</div><div class="member-role">Invited ' + inv["created_at"][:10] + ' • Expires ' + inv["expires_at"][:10] + '</div></div></div><button onclick="cancelInvitation(&apos;' + inv["invitation_id"] + '&apos;, &apos;' + inv["email"] + '&apos;)" class="btn btn-danger">Cancel</button></div>' for inv in invitations]) + '</div>' if invitations else '<div class="empty-state"><div class="empty-state-icon">📭</div><p>No pending invitations</p></div>') + '</div>' if is_admin else ''}

        <!-- Team Subscriptions -->
        <div class="section">
            <h2>
                <span>💎</span>
                Team Subscriptions
            </h2>
            {'<div class="subscription-list">' + ''.join([f'<div class="subscription-item"><div class="member-info"><div class="member-details"><div class="member-email">{sub["tool_category"].title()}</div><div class="member-role">Status: {sub["status"].title()} • {sub.get("price_amount", 0) / 100:.2f}/mo</div></div></div></div>' for sub in team_subscriptions]) + '</div>' if team_subscriptions else '<div class="empty-state"><div class="empty-state-icon">📦</div><p>No active subscriptions</p><p style="margin-top: 8px; font-size: 13px;">Subscribe to tools to share access with your team</p></div>'}
        </div>

        <!-- Tool Access Permissions -->
        {f'''
        <div class="section">
            <h2>
                <span>🔑</span>
                Tool Access Permissions
            </h2>
            <p style="color: #6b7280; font-size: 14px; margin-bottom: 20px;">
                Control which team members can access each subscribed tool category.
            </p>

            {('<div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px; border-radius: 6px; margin-bottom: 20px;"><p style="margin: 0; font-size: 13px; color: #92400e;"><strong>⚠️ No team subscriptions</strong> - Subscribe to tool categories first, then assign access to team members.</p></div>' if not team_subscription_categories else '')}

            {('<div style="overflow-x: auto;"><table style="width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden;"><thead><tr style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;"><th style="padding: 12px; text-align: left; font-weight: 600;">Member</th>' + ''.join([f'<th style="padding: 12px; text-align: center; font-weight: 600;">{cat.title()}</th>' for cat in team_subscription_categories]) + '<th style="padding: 12px; text-align: center; font-weight: 600;">Personal</th></tr></thead><tbody>' + ''.join([f'''<tr style="border-bottom: 1px solid #e2e8f0;"><td style="padding: 12px;"><div style="display: flex; align-items: center; gap: 10px;"><div style="width: 36px; height: 36px; border-radius: 50%; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); display: flex; align-items: center; justify-content: center; color: white; font-weight: 600; font-size: 14px;">{m["email"][0].upper()}</div><div><div style="font-weight: 500; color: #1a202c;">{m["email"]}</div><div style="font-size: 12px; color: #6b7280;">{m["role"].title()}</div></div></div></td>''' + ''.join([f'''<td style="padding: 12px; text-align: center;"><input type="checkbox" class="permission-checkbox" data-user-id="{m["user_id"]}" data-category="{cat}" {"checked" if cat in permissions_map.get(m["user_id"], []) else ""} {"disabled" if not is_admin else ""} onchange="togglePermission(this)" style="width: 20px; height: 20px; cursor: {'pointer' if is_admin else 'not-allowed'};"></td>''' for cat in team_subscription_categories]) + f'''<td style="padding: 12px; text-align: center;"><div style="font-size: 11px; color: #6b7280;">{", ".join([c.title() for c in member_personal_subs.get(m["user_id"], [])]) if member_personal_subs.get(m["user_id"]) else "-"}</div></td></tr>''' for m in members]) + '</tbody></table></div>' if team_subscription_categories else '')}
        </div>
        ''' if is_admin else ''}
    </div>

    <script>
        async function inviteMember(event) {{
            event.preventDefault();
            const email = document.getElementById('invite-email').value;
            const sessionToken = '{session_token}';

            try {{
                const response = await fetch('/teams/{team_id}/invite?session_token=' + sessionToken, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ email }})
                }});

                const result = await response.json();

                if (response.ok) {{
                    document.getElementById('success-message').textContent = '✓ Invitation sent to ' + email;
                    document.getElementById('success-message').style.display = 'block';
                    document.getElementById('error-message').style.display = 'none';
                    document.getElementById('invite-email').value = '';
                    setTimeout(() => window.location.reload(), 1500);
                }} else {{
                    document.getElementById('error-message').textContent = '✗ ' + result.detail;
                    document.getElementById('error-message').style.display = 'block';
                    document.getElementById('success-message').style.display = 'none';
                }}
            }} catch (error) {{
                document.getElementById('error-message').textContent = '✗ Network error. Please try again.';
                document.getElementById('error-message').style.display = 'block';
                document.getElementById('success-message').style.display = 'none';
            }}
        }}

        function togglePasswordMethod() {{
            const passwordMethod = document.querySelector('input[name="password-method"]:checked').value;
            const manualPasswordContainer = document.getElementById('manual-password-container');
            const passwordInput = document.getElementById('add-member-password');

            if (passwordMethod === 'manual') {{
                manualPasswordContainer.style.display = 'block';
                passwordInput.required = true;
            }} else {{
                manualPasswordContainer.style.display = 'none';
                passwordInput.required = false;
                passwordInput.value = '';
            }}
        }}

        async function addMember(event) {{
            event.preventDefault();
            const email = document.getElementById('add-member-email').value;
            const role = document.getElementById('add-member-role').value;
            const passwordMethod = document.querySelector('input[name="password-method"]:checked').value;
            const sessionToken = '{session_token}';

            // Build request payload
            const payload = {{ email, role }};

            // Add password if manually entered
            if (passwordMethod === 'manual') {{
                const password = document.getElementById('add-member-password').value;
                if (password) {{
                    payload.password = password;
                }}
            }}

            // Collect selected tool permissions
            const toolPermissions = Array.from(document.querySelectorAll('.tool-permission-checkbox:checked'))
                .map(cb => cb.value);
            if (toolPermissions.length > 0) {{
                payload.tool_permissions = toolPermissions;
            }}

            // Show loading state
            const submitBtn = event.target.querySelector('button[type="submit"]');
            const originalText = submitBtn.textContent;
            submitBtn.textContent = 'Adding...';
            submitBtn.disabled = true;

            try {{
                const response = await fetch('/teams/{team_id}/add-member?session_token=' + sessionToken, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify(payload)
                }});

                const result = await response.json();

                if (response.ok) {{
                    let message = result.user_existed
                        ? `✓ Added ${{email}} to team as ${{role}}`
                        : `✓ Created account and added ${{email}} as ${{role}}`;

                    if (!result.user_existed) {{
                        if (result.password_generated) {{
                            // Auto-generated password
                            message += result.email_sent
                                ? '\\n📧 Auto-generated password emailed to user'
                                : '\\n⚠️ Email failed - password: ' + result.password;
                        }} else {{
                            // Manual password
                            message += result.email_sent
                                ? '\\n📧 Login credentials emailed to user'
                                : '\\n⚠️ Email failed - please share the password with the user manually';
                        }}
                    }}

                    alert(message);
                    document.getElementById('add-member-email').value = '';
                    document.getElementById('add-member-password').value = '';
                    document.querySelector('input[name="password-method"][value="auto"]').checked = true;
                    togglePasswordMethod();
                    window.location.reload();
                }} else {{
                    document.getElementById('error-message').textContent = '✗ ' + result.detail;
                    document.getElementById('error-message').style.display = 'block';
                    document.getElementById('success-message').style.display = 'none';
                    submitBtn.textContent = originalText;
                    submitBtn.disabled = false;
                }}
            }} catch (error) {{
                document.getElementById('error-message').textContent = '✗ Network error. Please try again.';
                document.getElementById('error-message').style.display = 'block';
                document.getElementById('success-message').style.display = 'none';
                submitBtn.textContent = originalText;
                submitBtn.disabled = false;
            }}
        }}

        async function removeMember(userId, email) {{
            if (!confirm('Remove ' + email + ' from the team?')) {{
                return;
            }}

            const sessionToken = '{session_token}';

            try {{
                const response = await fetch('/teams/{team_id}/members/' + userId + '?session_token=' + sessionToken, {{
                    method: 'DELETE'
                }});

                const result = await response.json();

                if (response.ok) {{
                    document.getElementById('success-message').textContent = '✓ Member removed successfully';
                    document.getElementById('success-message').style.display = 'block';
                    document.getElementById('error-message').style.display = 'none';
                    setTimeout(() => window.location.reload(), 1000);
                }} else {{
                    document.getElementById('error-message').textContent = '✗ ' + result.detail;
                    document.getElementById('error-message').style.display = 'block';
                    document.getElementById('success-message').style.display = 'none';
                }}
            }} catch (error) {{
                document.getElementById('error-message').textContent = '✗ Network error. Please try again.';
                document.getElementById('error-message').style.display = 'block';
                document.getElementById('success-message').style.display = 'none';
            }}
        }}

        async function togglePermission(checkbox) {{
            const userId = checkbox.dataset.userId;
            const category = checkbox.dataset.category;
            const isGranting = checkbox.checked;
            const sessionToken = '{session_token}';

            try {{
                const response = await fetch('/teams/{team_id}/permissions?session_token=' + sessionToken, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        user_id: userId,
                        tool_category: category,
                        grant: isGranting
                    }})
                }});

                const result = await response.json();

                if (response.ok) {{
                    const action = isGranting ? 'granted' : 'revoked';
                    console.log(`Permission ${{action}} successfully`);
                }} else {{
                    // Revert checkbox on error
                    checkbox.checked = !checkbox.checked;
                    document.getElementById('error-message').textContent = '✗ ' + result.detail;
                    document.getElementById('error-message').style.display = 'block';
                    setTimeout(() => {{
                        document.getElementById('error-message').style.display = 'none';
                    }}, 3000);
                }}
            }} catch (error) {{
                // Revert checkbox on error
                checkbox.checked = !checkbox.checked;
                document.getElementById('error-message').textContent = '✗ Network error. Please try again.';
                document.getElementById('error-message').style.display = 'block';
                setTimeout(() => {{
                    document.getElementById('error-message').style.display = 'none';
                }}, 3000);
            }}
        }}

        async function cancelInvitation(invitationId, email) {{
            if (!confirm('Cancel invitation for ' + email + '?')) {{
                return;
            }}

            const sessionToken = '{session_token}';

            try {{
                const response = await fetch('/invitations/' + invitationId + '?session_token=' + sessionToken, {{
                    method: 'DELETE'
                }});

                const result = await response.json();

                if (response.ok) {{
                    document.getElementById('success-message').textContent = '✓ Invitation cancelled';
                    document.getElementById('success-message').style.display = 'block';
                    document.getElementById('error-message').style.display = 'none';
                    setTimeout(() => window.location.reload(), 1000);
                }} else {{
                    document.getElementById('error-message').textContent = '✗ ' + result.detail;
                    document.getElementById('error-message').style.display = 'block';
                    document.getElementById('success-message').style.display = 'none';
                }}
            }} catch (error) {{
                document.getElementById('error-message').textContent = '✗ Network error. Please try again.';
                document.getElementById('error-message').style.display = 'block';
                document.getElementById('success-message').style.display = 'none';
            }}
        }}
    </script>
</body>
</html>
    """)


@app.delete("/teams/{team_id}/members/{user_id}")
async def remove_team_member_endpoint(
    team_id: str,
    user_id: str,
    session_token: Optional[str] = Query(None)
):
    """Remove a member from a team (owner/admin only)."""
    if not session_token:
        raise HTTPException(401, "Missing session token")

    # Validate session token
    try:
        ctx = await get_request_context(None, session_token)
    except HTTPException:
        raise HTTPException(401, "Invalid or expired session token")

    # Get team details
    team_result = server.database.supabase.table('teams').select('*').eq('team_id', team_id).execute()
    if not team_result.data:
        raise HTTPException(404, "Team not found")

    team = team_result.data[0]

    # Check if requester is owner or admin
    members = server.database.get_team_members(team_id)
    requester_member = next((m for m in members if m['user_id'] == ctx.user_id), None)

    if not requester_member:
        raise HTTPException(403, "You are not a member of this team")

    if requester_member['role'] not in ['owner', 'admin']:
        raise HTTPException(403, "Only team owners and admins can remove members")

    # Prevent removing the owner
    if user_id == team['owner_user_id']:
        raise HTTPException(403, "Cannot remove the team owner")

    # Prevent removing yourself (use a different endpoint for leaving)
    if user_id == ctx.user_id:
        raise HTTPException(400, "Use the leave team endpoint to remove yourself")

    # Remove the member
    try:
        server.database.supabase.table('team_members').delete().eq('team_id', team_id).eq('user_id', user_id).execute()
        logger.info(f"User {ctx.user_id} removed user {user_id} from team {team_id}")

        return {
            "success": True,
            "message": "Member removed successfully"
        }
    except Exception as e:
        logger.error(f"Error removing team member: {e}")
        raise HTTPException(500, "Failed to remove member")


@app.post("/teams/{team_id}/permissions")
async def toggle_team_permission_endpoint(
    request: Request,
    team_id: str,
    session_token: Optional[str] = Query(None)
):
    """Grant or revoke a team member's permission to use a tool category."""
    if not session_token:
        raise HTTPException(401, "Missing session token")

    # Validate session token
    try:
        ctx = await get_request_context(None, session_token)
    except HTTPException:
        raise HTTPException(401, "Invalid or expired session token")

    # Parse request body
    body = await request.json()
    user_id = body.get('user_id')
    tool_category = body.get('tool_category')
    grant = body.get('grant', True)

    if not user_id or not tool_category:
        raise HTTPException(400, "Missing user_id or tool_category")

    # Check if requester is owner or admin
    members = server.database.get_team_members(team_id)
    requester_member = next((m for m in members if m['user_id'] == ctx.user_id), None)

    if not requester_member or requester_member['role'] not in ['owner', 'admin']:
        raise HTTPException(403, "Only team owners and admins can manage permissions")

    # Verify user is a member of this team
    target_member = next((m for m in members if m['user_id'] == user_id), None)
    if not target_member:
        raise HTTPException(404, "User is not a member of this team")

    # Grant or revoke permission
    try:
        if grant:
            success = server.database.grant_team_permission(
                user_id=user_id,
                team_id=team_id,
                tool_category=tool_category,
                assigned_by_user_id=ctx.user_id
            )
            action = "granted"
        else:
            success = server.database.revoke_team_permission(
                user_id=user_id,
                team_id=team_id,
                tool_category=tool_category
            )
            action = "revoked"

        if success:
            return {
                "success": True,
                "message": f"Permission {action} successfully"
            }
        else:
            raise HTTPException(500, f"Failed to {action.replace('ed', '')} permission")

    except Exception as e:
        logger.error(f"Error managing permission: {e}")
        raise HTTPException(500, f"Failed to manage permission: {str(e)}")


@app.delete("/invitations/{invitation_id}")
async def cancel_invitation_endpoint(
    invitation_id: str,
    session_token: Optional[str] = Query(None)
):
    """Cancel a pending team invitation (owner/admin only)."""
    if not session_token:
        raise HTTPException(401, "Missing session token")

    # Validate session token
    try:
        ctx = await get_request_context(None, session_token)
    except HTTPException:
        raise HTTPException(401, "Invalid or expired session token")

    # Get invitation details
    invitation = server.database.get_team_invitation(invitation_id)
    if not invitation:
        raise HTTPException(404, "Invitation not found")

    # Check if user is owner or admin of the team
    members = server.database.get_team_members(invitation['team_id'])
    user_member = next((m for m in members if m['user_id'] == ctx.user_id), None)

    if not user_member:
        raise HTTPException(403, "You are not a member of this team")

    if user_member['role'] not in ['owner', 'admin']:
        raise HTTPException(403, "Only team owners and admins can cancel invitations")

    # Cancel the invitation
    try:
        server.database.supabase.table('team_invitations').delete().eq('invitation_id', invitation_id).execute()
        logger.info(f"User {ctx.user_id} cancelled invitation {invitation_id}")

        return {
            "success": True,
            "message": "Invitation cancelled successfully"
        }
    except Exception as e:
        logger.error(f"Error cancelling invitation: {e}")
        raise HTTPException(500, "Failed to cancel invitation")


@app.post("/teams/{team_id}/invite")
async def invite_team_member_endpoint(
    team_id: str,
    request: Request,
    session_token: Optional[str] = Query(None)
):
    """Invite a new member to a team."""
    if not session_token:
        raise HTTPException(401, "Missing session token")

    # Validate session token
    try:
        ctx = await get_request_context(None, session_token)
    except HTTPException:
        raise HTTPException(401, "Invalid or expired session token")

    # Parse request body
    body = await request.json()
    email = body.get('email', '').strip().lower()

    if not email:
        raise HTTPException(400, "Email is required")

    # Basic email validation
    if '@' not in email or '.' not in email.split('@')[1]:
        raise HTTPException(400, "Invalid email format")

    # Check if user is team owner or admin
    teams = server.database.get_user_teams(ctx.user_id)
    user_team = next((t for t in teams if t['team_id'] == team_id), None)

    if not user_team:
        raise HTTPException(404, "Team not found or you're not a member")

    if user_team['role'] not in ['owner', 'admin']:
        raise HTTPException(403, "Only team owners and admins can invite members")

    # Check if user is already a member
    members = server.database.get_team_members(team_id)
    if any(m['email'].lower() == email for m in members):
        raise HTTPException(400, "User is already a team member")

    # Create invitation
    invitation = server.database.invite_team_member(
        team_id=team_id,
        email=email,
        invited_by_user_id=ctx.user_id
    )

    logger.info(f"Team invitation created: {invitation['invitation_id']} for {email} to team {team_id}")

    # TODO: Send invitation email
    # For now, just return the invitation link

    return {
        "success": True,
        "invitation": invitation,
        "invitation_link": f"{request.url.scheme}://{request.url.hostname}/invite/{invitation['invitation_id']}"
    }


@app.post("/teams/{team_id}/add-member")
async def add_team_member(
    team_id: str,
    request: Request,
    session_token: Optional[str] = Query(None)
):
    """
    Add a team member (sends invitation if user doesn't exist).

    Behavior:
    - If user exists: Adds them to the team immediately
    - If user doesn't exist: Creates an invitation (requires OAuth to complete)

    This system requires Google OAuth authentication, so new users must
    accept an invitation and authenticate via Google to create their account.

    Request body:
    - email: Email address of the user to add
    - role: Role to assign (member or admin) [optional, default: member]
    - tool_permissions: List of tool categories to grant access [optional]
    """
    try:
        if not session_token:
            raise HTTPException(401, "Missing session token")

        # Validate session token
        try:
            ctx = await get_request_context(None, session_token)
        except HTTPException:
            raise HTTPException(401, "Invalid or expired session token")

        # Parse request body
        body = await request.json()
        email = body.get('email', '').strip().lower()
        role = body.get('role', 'member').strip().lower()
        manual_password = body.get('password', '').strip()  # Optional manual password
        tool_permissions = body.get('tool_permissions', [])  # List of tool categories to grant access to

        if not email:
            raise HTTPException(400, "Email is required")

        # Validate email
        if '@' not in email or '.' not in email.split('@')[1]:
            raise HTTPException(400, "Invalid email format")

        # Validate role
        if role not in ['member', 'admin']:
            raise HTTPException(400, "Role must be 'member' or 'admin'")

        # Validate manual password if provided
        if manual_password and len(manual_password) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")

        # Check if user is team owner or admin
        teams = server.database.get_user_teams(ctx.user_id)
        user_team = next((t for t in teams if t['team_id'] == team_id), None)

        if not user_team:
            raise HTTPException(404, "Team not found or you're not a member")

        if user_team['role'] not in ['owner', 'admin']:
            raise HTTPException(403, "Only team owners and admins can add members")

        # Get team info
        team = server.database.supabase.table('teams').select('*').eq('team_id', team_id).execute()
        if not team.data:
            raise HTTPException(404, "Team not found")

        team_name = team.data[0]['team_name']

        # Check if user already exists
        existing_user = server.database.supabase.table('users').select('*').eq('email', email).execute()

        if existing_user.data:
            # User exists - just add to team
            existing_user_id = existing_user.data[0]['user_id']

            # Check if already a team member
            members = server.database.get_team_members(team_id)
            if any(m['user_id'] == existing_user_id for m in members):
                raise HTTPException(400, "User is already a team member")

            # Add to team
            server.database.add_team_member(team_id, existing_user_id, role)

            # Grant tool permissions
            if tool_permissions:
                for category in tool_permissions:
                    server.database.grant_team_permission(
                        user_id=existing_user_id,
                        team_id=team_id,
                        tool_category=category,
                        assigned_by_user_id=ctx.user_id
                    )
                logger.info(f"Granted {len(tool_permissions)} tool permissions to {email}")

            logger.info(f"Added existing user {email} to team {team_id} as {role}")

            return {
                "success": True,
                "message": f"Added {email} to team",
                "user_existed": True,
                "role": role,
                "permissions_granted": len(tool_permissions)
            }

        else:
            # User doesn't exist - create invitation instead
            # This system requires Google OAuth, so we can't create accounts directly

            # Check if invitation already exists
            existing_invitation = server.database.supabase.table('team_invitations').select('*').eq(
                'team_id', team_id
            ).eq('email', email).eq('status', 'pending').execute()

            if existing_invitation.data:
                # Return existing invitation
                invitation = existing_invitation.data[0]
                logger.info(f"Returning existing invitation {invitation['invitation_id']} for {email}")

                # Build invitation URL
                deployment_url = os.getenv("RAILWAY_PUBLIC_DOMAIN", os.getenv("DEPLOYMENT_URL", request.url.hostname))
                if not deployment_url.startswith("http"):
                    deployment_url = f"https://{deployment_url}"

                invitation_url = f"{deployment_url}/invite/{invitation['invitation_id']}"

                return {
                    "success": True,
                    "message": f"Invitation already exists for {email}",
                    "user_existed": False,
                    "invitation_exists": True,
                    "invitation_id": invitation['invitation_id'],
                    "invitation_url": invitation_url,
                    "role": role
                }

            # Create new invitation
            invitation = server.database.invite_team_member(
                team_id=team_id,
                email=email,
                invited_by_user_id=ctx.user_id
            )

            logger.info(f"Created invitation {invitation['invitation_id']} for {email} to team {team_id}")

            # Build invitation URL
            deployment_url = os.getenv("RAILWAY_PUBLIC_DOMAIN", os.getenv("DEPLOYMENT_URL", request.url.hostname))
            if not deployment_url.startswith("http"):
                deployment_url = f"https://{deployment_url}"

            invitation_url = f"{deployment_url}/invite/{invitation['invitation_id']}"

            # Note: Tool permissions will be granted after the user accepts the invitation
            # For now, just store them in the response for the frontend to display
            pending_permissions = tool_permissions if tool_permissions else []

            # Send invitation email
            email_sent = False
            try:
                import resend
                resend.api_key = os.getenv("RESEND_API_KEY")

                email_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 28px;">👥 You're invited to {team_name}!</h1>
    </div>

    <div style="background: #f9fafb; padding: 30px; border-radius: 0 0 12px 12px;">
        <p style="font-size: 16px; margin-bottom: 20px;">Hello,</p>

        <p style="font-size: 16px; margin-bottom: 20px;">{ctx.email} has invited you to join their team "<strong>{team_name}</strong>" on the AI Email Assistant MCP server.</p>

        <p style="font-size: 16px; margin-bottom: 20px;">This gives you access to powerful AI tools for Gmail, Calendar, Docs, Sheets, and more through Claude.</p>

        <div style="background: #dbeafe; border-left: 4px solid #3b82f6; padding: 15px; border-radius: 6px; margin: 20px 0;">
            <p style="margin: 0; color: #1e40af; font-size: 14px;">
                <strong>👥 Your Role:</strong> {role.title()}
            </p>
        </div>

        <p style="text-align: center; margin: 30px 0;">
            <a href="{invitation_url}" style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;">Accept Invitation</a>
        </p>

        <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; border-radius: 6px; margin: 20px 0;">
            <p style="margin: 0; color: #92400e; font-size: 14px;">
                <strong>⚠️ Note:</strong> This invitation will expire in 7 days. Click the button above to accept and create your account.
            </p>
        </div>

        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">

        <p style="font-size: 14px; color: #6b7280; margin: 0;">
            If you didn't expect this invitation, you can safely ignore this email.
        </p>
    </div>
</body>
</html>
                """

                resend.Emails.send({
                    "from": "AI Email Assistant <noreply@leadgenjay.com>",
                    "to": [email],
                    "subject": f"You're invited to join {team_name}",
                    "html": email_html
                })

                logger.info(f"Invitation email sent to {email}")
                email_sent = True

            except Exception as e:
                logger.error(f"Failed to send invitation email to {email}: {e}")

            return {
                "success": True,
                "message": f"Invitation sent to {email}",
                "user_existed": False,
                "invitation_created": True,
                "invitation_id": invitation['invitation_id'],
                "invitation_url": invitation_url,
                "role": role,
                "email_sent": email_sent,
                "pending_permissions": pending_permissions
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add team member: {e}")
        raise HTTPException(500, f"Failed to add team member: {str(e)}")


@app.get("/invitations/{invitation_id}")
async def get_invitation_endpoint(
    invitation_id: str,
    session_token: Optional[str] = Query(None)
):
    """Get invitation details."""
    # Note: This endpoint doesn't require authentication
    # Anyone with the invitation ID can view it

    invitation = server.database.get_team_invitation(invitation_id)

    if not invitation:
        raise HTTPException(404, "Invitation not found")

    if invitation['status'] != 'pending':
        raise HTTPException(400, f"Invitation is {invitation['status']}")

    # Check if expired
    from datetime import datetime
    expires_at = datetime.fromisoformat(invitation['expires_at'].replace('Z', '+00:00'))
    if datetime.now(expires_at.tzinfo) > expires_at:
        # Mark as expired
        server.database.supabase.table('team_invitations').update({
            'status': 'expired'
        }).eq('invitation_id', invitation_id).execute()

        raise HTTPException(400, "Invitation has expired")

    return {
        "success": True,
        "invitation": invitation
    }


@app.post("/invitations/{invitation_id}/accept")
async def accept_invitation_endpoint(
    invitation_id: str,
    session_token: Optional[str] = Query(None)
):
    """Accept a team invitation."""
    if not session_token:
        raise HTTPException(401, "Missing session token - please log in first")

    # Validate session token
    try:
        ctx = await get_request_context(None, session_token)
    except HTTPException:
        raise HTTPException(401, "Invalid or expired session token")

    # Get invitation
    invitation = server.database.get_team_invitation(invitation_id)

    if not invitation:
        raise HTTPException(404, "Invitation not found")

    if invitation['status'] != 'pending':
        raise HTTPException(400, f"Invitation is {invitation['status']}")

    # Check if expired
    from datetime import datetime
    expires_at = datetime.fromisoformat(invitation['expires_at'].replace('Z', '+00:00'))
    if datetime.now(expires_at.tzinfo) > expires_at:
        raise HTTPException(400, "Invitation has expired")

    # Get user email
    user = server.database.get_user_by_session(session_token)
    if not user:
        raise HTTPException(401, "User not found")

    # Verify email matches invitation
    if user['email'].lower() != invitation['email'].lower():
        raise HTTPException(403, f"This invitation is for {invitation['email']}, but you're logged in as {user['email']}")

    # Accept invitation
    success = server.database.accept_team_invitation(invitation_id, ctx.user_id)

    if not success:
        raise HTTPException(500, "Failed to accept invitation")

    logger.info(f"User {user['email']} accepted invitation {invitation_id} to team {invitation['team_id']}")

    return {
        "success": True,
        "message": "You've joined the team!",
        "team_id": invitation['team_id']
    }


@app.get("/invite/{invitation_id}", response_class=HTMLResponse)
async def invitation_page(
    request: Request,
    invitation_id: str,
    session_token: Optional[str] = Query(None)
):
    """Invitation acceptance page - handles both logged in and logged out users."""

    # Get invitation details
    invitation = server.database.get_team_invitation(invitation_id)

    if not invitation:
        return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>Invitation Not Found</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
        .card {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); max-width: 500px; text-align: center; }}
    </style>
</head>
<body>
    <div class="card">
        <div style="font-size: 64px; margin-bottom: 20px;">❌</div>
        <h1 style="margin: 0 0 10px 0;">Invitation Not Found</h1>
        <p style="color: #6b7280;">This invitation link is invalid or has been deleted.</p>
    </div>
</body>
</html>
        """, status_code=404)

    # Check if expired or already used
    from datetime import datetime
    expires_at = datetime.fromisoformat(invitation['expires_at'].replace('Z', '+00:00'))
    is_expired = datetime.now(expires_at.tzinfo) > expires_at
    is_pending = invitation['status'] == 'pending'

    if not is_pending or is_expired:
        status_message = "expired" if is_expired else invitation['status']
        return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>Invitation {status_message.title()}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
        .card {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); max-width: 500px; text-align: center; }}
    </style>
</head>
<body>
    <div class="card">
        <div style="font-size: 64px; margin-bottom: 20px;">⚠️</div>
        <h1 style="margin: 0 0 10px 0;">Invitation {status_message.title()}</h1>
        <p style="color: #6b7280;">This invitation is no longer valid.</p>
    </div>
</body>
</html>
        """, status_code=400)

    # Get team details
    team_result = server.database.supabase.table('teams').select('*').eq('team_id', invitation['team_id']).execute()
    if not team_result.data:
        raise HTTPException(404, "Team not found")

    team = team_result.data[0]

    # Get inviter details
    inviter_result = server.database.supabase.table('users').select('email').eq('user_id', invitation['invited_by_user_id']).execute()
    inviter_email = inviter_result.data[0]['email'] if inviter_result.data else "Team owner"

    # Check if user is logged in
    is_logged_in = False
    user_email = None
    if session_token:
        user = server.database.get_user_by_session(session_token)
        if user:
            is_logged_in = True
            user_email = user['email']

    # Check if invitation email matches logged in user
    email_matches = is_logged_in and user_email.lower() == invitation['email'].lower()

    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>Team Invitation - {team['team_name']}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
        }}
        .card {{
            background: white;
            padding: 40px;
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.2);
            max-width: 500px;
            width: 100%;
        }}
        h1 {{
            margin: 0 0 10px 0;
            color: #1a202c;
            font-size: 28px;
        }}
        .team-badge {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            display: inline-block;
            font-weight: 600;
            margin-bottom: 20px;
        }}
        .info-box {{
            background: #f9fafb;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            border-left: 4px solid #667eea;
        }}
        .info-row {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 12px;
        }}
        .info-row:last-child {{
            margin-bottom: 0;
        }}
        .label {{
            color: #6b7280;
            font-size: 14px;
        }}
        .value {{
            font-weight: 600;
            color: #1a202c;
        }}
        .btn {{
            display: block;
            width: 100%;
            padding: 14px 24px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            text-decoration: none;
            text-align: center;
            margin-bottom: 12px;
        }}
        .btn-primary {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        .btn-primary:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }}
        .btn-google {{
            background: white;
            color: #1a202c;
            border: 2px solid #e2e8f0;
        }}
        .btn-google:hover {{
            border-color: #667eea;
        }}
        .divider {{
            text-align: center;
            margin: 20px 0;
            color: #9ca3af;
            font-size: 14px;
        }}
        .form-group {{
            margin-bottom: 16px;
        }}
        label {{
            display: block;
            margin-bottom: 6px;
            font-weight: 600;
            color: #374151;
            font-size: 14px;
        }}
        input {{
            width: 100%;
            padding: 12px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 15px;
            box-sizing: border-box;
        }}
        input:focus {{
            outline: none;
            border-color: #667eea;
        }}
        .alert {{
            padding: 12px 16px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 14px;
        }}
        .alert-warning {{
            background: #fef3c7;
            color: #92400e;
            border: 1px solid #fbbf24;
        }}
        .alert-error {{
            background: #fee;
            color: #c00;
            border: 1px solid #f88;
            display: none;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div style="text-align: center; margin-bottom: 30px;">
            <div style="font-size: 48px; margin-bottom: 15px;">👥</div>
            <span class="team-badge">Team Invitation</span>
            <h1>Join {team['team_name']}</h1>
            <p style="color: #6b7280; margin: 10px 0 0 0;">{inviter_email} has invited you to join their team</p>
        </div>

        <div class="info-box">
            <div class="info-row">
                <span class="label">Invited to:</span>
                <span class="value">{invitation['email']}</span>
            </div>
            <div class="info-row">
                <span class="label">Expires:</span>
                <span class="value">{expires_at.strftime('%B %d, %Y')}</span>
            </div>
        </div>

        {'<div class="alert alert-warning">⚠️ You are logged in as ' + user_email + ', but this invitation is for ' + invitation["email"] + '. Please log out or use the correct account.</div>' if is_logged_in and not email_matches else ''}

        <div id="error-message" class="alert alert-error"></div>

        {'<button onclick="acceptInvitation()" class="btn btn-primary">✓ Accept Invitation & Join Team</button>' if email_matches else '''
        <a href="/setup/start?redirect=/invite/{invitation_id}" class="btn btn-google">
            <img src="https://www.google.com/favicon.ico" style="width: 16px; height: 16px; vertical-align: middle; margin-right: 8px;">
            Sign in with Google
        </a>

        <div class="divider">OR</div>

        <form id="signup-form" onsubmit="handleSignup(event)">
            <div class="form-group">
                <label>Email</label>
                <input type="email" id="email" value="{invitation['email']}" readonly style="background: #f9fafb;">
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" id="password" placeholder="Create a password" required minlength="8">
            </div>
            <button type="submit" class="btn btn-primary">Create Account & Accept Invitation</button>
        </form>
        '''}
    </div>

    <script>
        async function acceptInvitation() {{
            const sessionToken = '{session_token if session_token else ''}';

            try {{
                const response = await fetch('/invitations/{invitation_id}/accept?session_token=' + sessionToken, {{
                    method: 'POST'
                }});

                const result = await response.json();

                if (response.ok) {{
                    window.location.href = '/dashboard?session_token=' + sessionToken + '&welcome=true';
                }} else {{
                    document.getElementById('error-message').textContent = '✗ ' + result.detail;
                    document.getElementById('error-message').style.display = 'block';
                }}
            }} catch (error) {{
                document.getElementById('error-message').textContent = '✗ Network error. Please try again.';
                document.getElementById('error-message').style.display = 'block';
            }}
        }}

        async function handleSignup(event) {{
            event.preventDefault();

            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;

            try {{
                // First, create account via signup
                const signupResponse = await fetch('/signup', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ email, password }})
                }});

                const signupResult = await signupResponse.json();

                if (!signupResponse.ok) {{
                    document.getElementById('error-message').textContent = '✗ ' + signupResult.detail;
                    document.getElementById('error-message').style.display = 'block';
                    return;
                }}

                // Now accept invitation with new session token
                const sessionToken = signupResult.session_token;

                const acceptResponse = await fetch('/invitations/{invitation_id}/accept?session_token=' + sessionToken, {{
                    method: 'POST'
                }});

                const acceptResult = await acceptResponse.json();

                if (acceptResponse.ok) {{
                    window.location.href = '/dashboard?session_token=' + sessionToken + '&welcome=true';
                }} else {{
                    document.getElementById('error-message').textContent = '✗ ' + acceptResult.detail;
                    document.getElementById('error-message').style.display = 'block';
                }}
            }} catch (error) {{
                document.getElementById('error-message').textContent = '✗ Network error. Please try again.';
                document.getElementById('error-message').style.display = 'block';
            }}
        }}
    </script>
</body>
</html>
    """)


# ===========================================================================
# SUBSCRIPTION & BILLING ENDPOINTS
# ===========================================================================

@app.post("/subscribe")
async def subscribe_to_category(
    request: Request,
    session_token: Optional[str] = Query(None)
):
    """
    Create Stripe Checkout session for subscribing to tool categories.
    Supports multiple categories in shopping cart style.
    Supports both personal and team subscriptions.

    Args:
        session_token: User's session token
        Body: {
            "categories": ["gmail", "calendar", ...],
            "team_id": "team_xxx" (optional - for team subscriptions)
        }

    Returns:
        JSON with checkout_url or redirect
    """
    if not session_token:
        raise HTTPException(401, "Missing session token")

    # Validate session and get user
    try:
        ctx = await create_request_context(server.database, session_token, server.config)
    except HTTPException:
        raise HTTPException(401, "Invalid or expired session token")

    # Parse request body
    try:
        body = await request.json()
        category_list = body.get('categories', [])
        team_id = body.get('team_id')  # Optional team_id for team subscriptions
    except:
        raise HTTPException(400, "Invalid request body")

    # Validate categories
    valid_categories = ['gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison']

    if not category_list:
        raise HTTPException(400, "No categories provided")

    for cat in category_list:
        if cat not in valid_categories:
            raise HTTPException(400, f"Invalid category '{cat}'. Must be one of: {', '.join(valid_categories)}")

    # Determine if this is a team or personal subscription
    is_team_subscription = team_id is not None
    billing_entity_id = team_id if is_team_subscription else ctx.user_id

    # If team subscription, validate user is owner/admin
    if is_team_subscription:
        teams = server.database.get_user_teams(ctx.user_id)
        user_team = next((t for t in teams if t['team_id'] == team_id), None)

        if not user_team:
            raise HTTPException(404, "Team not found or you're not a member")

        if user_team['role'] not in ['owner', 'admin']:
            raise HTTPException(403, "Only team owners and admins can manage team subscriptions")

    # Filter out already subscribed categories
    if is_team_subscription:
        # Check team subscriptions
        categories_to_subscribe = []
        for cat in category_list:
            existing = server.database.supabase.table('subscriptions').select('*').eq(
                'team_id', team_id
            ).eq('tool_category', cat).eq('is_team_subscription', True).eq('status', 'active').execute()
            if not existing.data:
                categories_to_subscribe.append(cat)
    else:
        # Check personal subscriptions
        categories_to_subscribe = [cat for cat in category_list if not server.database.has_active_subscription(ctx.user_id, cat)]

    if not categories_to_subscribe:
        entity_type = "team" if is_team_subscription else "you"
        return JSONResponse({
            "error": f"{entity_type.capitalize()} already subscribed to all selected categories",
            "status": "already_subscribed"
        }, status_code=400)

    # Initialize Stripe
    stripe.api_key = server.config.stripe_secret_key

    # Get or create Stripe customer
    if is_team_subscription:
        # Get team's Stripe customer
        team_result = server.database.supabase.table('teams').select('stripe_customer_id, billing_email').eq('team_id', team_id).execute()
        if not team_result.data:
            raise HTTPException(404, "Team not found")

        team_data = team_result.data[0]
        stripe_customer_id = team_data.get('stripe_customer_id')
        billing_email = team_data.get('billing_email') or ctx.email

        if not stripe_customer_id:
            # Create new Stripe customer for team
            customer = stripe.Customer.create(
                email=billing_email,
                metadata={'team_id': team_id, 'created_by_user_id': ctx.user_id}
            )
            stripe_customer_id = customer.id

            # Save to team
            server.database.supabase.table('teams').update({
                'stripe_customer_id': stripe_customer_id,
                'billing_email': billing_email
            }).eq('team_id', team_id).execute()

            logger.info(f"Created Stripe customer {stripe_customer_id} for team {team_id}")
    else:
        # Personal subscription - use user's Stripe customer
        stripe_customer_id = server.database.get_stripe_customer_id(ctx.user_id)

        if not stripe_customer_id:
            # Create new Stripe customer
            customer = stripe.Customer.create(
                email=ctx.email,
                metadata={'user_id': ctx.user_id}
            )
            stripe_customer_id = customer.id
            logger.info(f"Created Stripe customer {stripe_customer_id} for user {ctx.email}")

    # Build line items for all selected categories
    line_items = []
    for category in categories_to_subscribe:
        try:
            price_id = server.config.get_stripe_price_id(category)
            line_items.append({
                'price': price_id,
                'quantity': 1
            })
        except ValueError as e:
            logger.error(f"Failed to get price ID for {category}: {e}")
            raise HTTPException(400, str(e))

    # Get deployment URL for success/cancel redirects
    deployment_url = os.getenv("RAILWAY_PUBLIC_DOMAIN", os.getenv("DEPLOYMENT_URL", "http://localhost:8000"))
    if not deployment_url.startswith("http"):
        deployment_url = f"https://{deployment_url}"

    # Create Checkout session with multiple line items
    try:
        # Build metadata
        metadata = {
            'user_id': ctx.user_id,
            'tool_categories': ','.join(categories_to_subscribe)
        }

        if is_team_subscription:
            metadata['team_id'] = team_id
            metadata['is_team_subscription'] = 'true'

        checkout_session = stripe.checkout.Session.create(
            customer=stripe_customer_id,
            payment_method_types=['card'],
            line_items=line_items,
            mode='subscription',
            success_url=f"{deployment_url}/dashboard?session_token={session_token}&subscription_success=true",
            cancel_url=f"{deployment_url}/dashboard?session_token={session_token}&subscription_cancelled=true",
            metadata=metadata
        )

        entity_description = f"team {team_id}" if is_team_subscription else f"user {ctx.email}"
        logger.info(f"Created checkout session for {entity_description}, categories: {', '.join(categories_to_subscribe)}")

        # Return JSON with checkout URL
        return JSONResponse({
            "checkout_url": checkout_session.url,
            "status": "success"
        })

    except Exception as e:
        logger.error(f"Error creating checkout session: {e}")
        return JSONResponse({
            "error": f"Failed to create checkout session: {str(e)}",
            "status": "error"
        }, status_code=500)


@app.post("/resume-subscription")
async def resume_subscription(
    category: str = Query(...),
    session_token: Optional[str] = Query(None)
):
    """
    Resume a cancelled subscription by reactivating it.

    Args:
        category: Tool category to resume (e.g., 'gmail', 'sheets')
        session_token: User's session token

    Returns:
        JSON with success status
    """
    if not session_token:
        raise HTTPException(401, "Missing session token")

    # Validate session and get user
    try:
        ctx = await create_request_context(server.database, session_token, server.config)
    except HTTPException:
        raise HTTPException(401, "Invalid or expired session token")

    # Validate category
    valid_categories = ['gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison']
    if category not in valid_categories:
        raise HTTPException(400, f"Invalid category '{category}'")

    # Check if subscription exists and is cancelled
    existing = server.database.supabase.table('subscriptions').select('*').eq(
        'user_id', ctx.user_id
    ).eq('tool_category', category).eq('status', 'cancelled').execute()

    if not existing.data:
        return JSONResponse({
            "status": "not_found",
            "message": f"No cancelled {category} subscription found to resume"
        }, status_code=404)

    subscription = existing.data[0]
    stripe_subscription_id = subscription.get('stripe_subscription_id')

    # Initialize Stripe
    stripe.api_key = server.config.stripe_secret_key

    # If it's a real Stripe subscription, reactivate it
    if stripe_subscription_id and not stripe_subscription_id.startswith(('admin_', 'free_')):
        try:
            # Note: You cannot "resume" a cancelled Stripe subscription
            # You need to create a new subscription
            # So we'll delete the old cancelled record and redirect to subscribe flow

            # Delete the cancelled subscription record
            server.database.supabase.table('subscriptions').delete().eq(
                'id', subscription['id']
            ).execute()

            logger.info(f"Deleted cancelled {category} subscription for user {ctx.user_id}, will create new one")

            # Create new subscription via Stripe Checkout
            stripe_customer_id = server.database.get_stripe_customer_id(ctx.user_id)

            if not stripe_customer_id:
                # Create new Stripe customer
                customer = stripe.Customer.create(
                    email=ctx.email,
                    metadata={'user_id': ctx.user_id}
                )
                stripe_customer_id = customer.id
                logger.info(f"Created Stripe customer {stripe_customer_id} for user {ctx.email}")

            price_id = server.config.get_stripe_price_id(category)

            # Get deployment URL for success/cancel redirects
            deployment_url = os.getenv("RAILWAY_PUBLIC_DOMAIN", os.getenv("DEPLOYMENT_URL", "http://localhost:8000"))
            if not deployment_url.startswith("http"):
                deployment_url = f"https://{deployment_url}"

            # Create Checkout session
            checkout_session = stripe.checkout.Session.create(
                customer=stripe_customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1
                }],
                mode='subscription',
                success_url=f"{deployment_url}/dashboard?session_token={session_token}&subscription_success=true",
                cancel_url=f"{deployment_url}/dashboard?session_token={session_token}",
                metadata={
                    'user_id': ctx.user_id,
                    'tool_categories': category
                }
            )

            return JSONResponse({
                "status": "success",
                "message": f"Redirecting to payment for {category}",
                "checkout_url": checkout_session.url
            })

        except stripe.error.StripeError as e:
            logger.error(f"Failed to create new Stripe subscription for {category}: {e}")
            raise HTTPException(500, f"Failed to resume subscription: {str(e)}")
    else:
        # It's a free/admin subscription - just reactivate it
        server.database.supabase.table('subscriptions').update({
            'status': 'active',
            'cancelled_at': None
        }).eq('id', subscription['id']).execute()

        logger.info(f"Reactivated free/admin {category} subscription for user {ctx.user_id}")

        return JSONResponse({
            "status": "success",
            "message": f"Resumed {category} subscription"
        })


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhook events (subscription created, updated, cancelled, etc).

    This endpoint is called by Stripe when subscription events occur.
    """
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')

    stripe.api_key = server.config.stripe_secret_key
    webhook_secret = server.config.stripe_webhook_secret

    # SECURITY: Webhook signature verification is REQUIRED
    # Never accept unsigned webhooks - this prevents attackers from:
    # - Creating fake subscriptions
    # - Bypassing payment
    # - Manipulating user access
    if not webhook_secret:
        logger.error("SECURITY: Stripe webhook secret not configured - rejecting webhook")
        raise HTTPException(500, "Webhook signature verification not configured")

    if not sig_header:
        logger.error("SECURITY: Missing stripe-signature header")
        raise HTTPException(400, "Missing signature header")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError as e:
        logger.error(f"SECURITY: Invalid webhook payload: {e}")
        raise HTTPException(400, "Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"SECURITY: Invalid webhook signature: {e}")
        raise HTTPException(400, "Invalid signature")

    # Handle the event
    event_type = event['type']
    data = event['data']['object']

    logger.info(f"Received Stripe webhook: {event_type}")

    if event_type == 'checkout.session.completed':
        # Payment successful - create subscription in database
        session = data
        subscription_id = session.get('subscription')
        customer_id = session.get('customer')
        user_id = session['metadata'].get('user_id')
        tool_categories = session['metadata'].get('tool_categories')  # Comma-separated string
        team_id = session['metadata'].get('team_id')  # Optional - for team subscriptions
        is_team_subscription = session['metadata'].get('is_team_subscription') == 'true'

        if not all([subscription_id, customer_id, user_id, tool_categories]):
            logger.error(f"Missing required fields in checkout.session.completed: {session}")
            return JSONResponse({"status": "error", "message": "Missing required fields"})

        # Retrieve the subscription to get period info
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)

            # Use bracket notation for safer access to Stripe object attributes
            current_period_start = datetime.fromtimestamp(subscription['current_period_start'])
            current_period_end = datetime.fromtimestamp(subscription['current_period_end'])
        except Exception as e:
            logger.error(f"Failed to retrieve subscription {subscription_id}: {e}")
            # Use current time as fallback
            current_period_start = datetime.now()
            current_period_end = datetime.now() + timedelta(days=30)

        # Parse comma-separated categories and create subscription for each
        categories = [cat.strip() for cat in tool_categories.split(',')]

        for category in categories:
            # Create subscription in database for each category
            if is_team_subscription and team_id:
                # Team subscription - use checkout creator's user_id
                # Now safe thanks to updated unique constraint that includes team_id
                server.database.supabase.table('subscriptions').insert({
                    'user_id': user_id,  # Checkout creator as billing contact
                    'team_id': team_id,
                    'is_team_subscription': True,
                    'tool_category': category,
                    'stripe_customer_id': customer_id,
                    'stripe_subscription_id': subscription_id,
                    'status': 'active',
                    'current_period_start': current_period_start.isoformat(),
                    'current_period_end': current_period_end.isoformat()
                }).execute()
                logger.info(f"Created TEAM subscription for team {team_id}, category {category}")
            else:
                # Personal subscription
                server.database.create_subscription(
                    user_id=user_id,
                    tool_category=category,
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=subscription_id,
                    status='active',
                    current_period_start=current_period_start,
                    current_period_end=current_period_end
                )
                logger.info(f"Created PERSONAL subscription for user {user_id}, category {category}")

        entity_description = f"team {team_id}" if is_team_subscription else f"user {user_id}"
        logger.info(f"Successfully processed checkout for {entity_description}: {len(categories)} categories ({', '.join(categories)})")

    elif event_type == 'customer.subscription.updated':
        # Subscription updated (renewed, changed, etc.)
        subscription_id = data['id']
        status = data['status']

        # Webhook data is incomplete - fetch full subscription from Stripe API
        stripe.api_key = server.config.stripe_secret_key
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            logger.info(f"Retrieved full subscription {subscription_id} from Stripe API")
        except Exception as e:
            logger.error(f"Failed to retrieve subscription {subscription_id}: {e}")
            return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

        # Map Stripe status to our status
        status_map = {
            'active': 'active',
            'past_due': 'past_due',
            'unpaid': 'unpaid',
            'canceled': 'cancelled',
            'incomplete': 'unpaid',
            'incomplete_expired': 'cancelled',
            'trialing': 'active',
            'paused': 'cancelled'
        }

        our_status = status_map.get(subscription['status'], 'cancelled')

        # Extract period dates (should be present in full API response)
        try:
            current_period_start = datetime.fromtimestamp(subscription['current_period_start'])
            current_period_end = datetime.fromtimestamp(subscription['current_period_end'])
        except (KeyError, TypeError) as e:
            logger.warning(f"Could not extract period dates from subscription {subscription_id}: {e}")
            # Use billing cycle anchor as fallback
            billing_cycle_anchor = subscription.get('billing_cycle_anchor')
            if billing_cycle_anchor:
                current_period_start = datetime.fromtimestamp(billing_cycle_anchor)
                current_period_end = current_period_start + timedelta(days=30)
            else:
                current_period_start = datetime.now()
                current_period_end = datetime.now() + timedelta(days=30)

        # Extract cancellation info (if scheduled to cancel at period end)
        cancel_at_period_end = subscription.get('cancel_at_period_end', False)
        cancel_at = None
        if subscription.get('cancel_at'):
            cancel_at = datetime.fromtimestamp(subscription['cancel_at'])

        server.database.update_subscription_status(
            stripe_subscription_id=subscription_id,
            status=our_status,
            current_period_start=current_period_start,
            current_period_end=current_period_end,
            cancel_at_period_end=cancel_at_period_end,
            cancel_at=cancel_at
        )

        if cancel_at_period_end:
            logger.info(f"Updated subscription {subscription_id} to status {our_status} (cancels on {cancel_at})")
        elif cancel_at:
            logger.info(f"Updated subscription {subscription_id} to status {our_status} (scheduled cancel at {cancel_at})")
        else:
            logger.info(f"Updated subscription {subscription_id} to status {our_status}")

    elif event_type == 'customer.subscription.deleted':
        # Subscription cancelled
        subscription = data
        subscription_id = subscription['id']

        server.database.update_subscription_status(
            stripe_subscription_id=subscription_id,
            status='cancelled',
            cancelled_at=datetime.now()
        )

        logger.info(f"Cancelled subscription {subscription_id}")

    elif event_type == 'invoice.paid':
        # Invoice paid - activate subscription (important for send_invoice subscriptions)
        invoice = data
        subscription_id = invoice.get('subscription')

        if subscription_id:
            logger.info(f"Invoice paid for subscription {subscription_id} - ensuring active status")

            # Retrieve full subscription from Stripe
            try:
                subscription = stripe.Subscription.retrieve(subscription_id)

                # Extract period dates
                current_period_start = datetime.fromtimestamp(subscription['current_period_start'])
                current_period_end = datetime.fromtimestamp(subscription['current_period_end'])

                # Update subscription to active status
                server.database.update_subscription_status(
                    stripe_subscription_id=subscription_id,
                    status='active',
                    current_period_start=current_period_start,
                    current_period_end=current_period_end
                )

                logger.info(f"Activated subscription {subscription_id} after invoice payment")
            except Exception as e:
                logger.error(f"Failed to activate subscription {subscription_id} after invoice payment: {e}")

    elif event_type == 'invoice.payment_failed':
        # Invoice payment failed - mark subscription as past_due
        invoice = data
        subscription_id = invoice.get('subscription')

        if subscription_id:
            logger.warning(f"Invoice payment failed for subscription {subscription_id}")

            server.database.update_subscription_status(
                stripe_subscription_id=subscription_id,
                status='past_due'
            )

            logger.info(f"Marked subscription {subscription_id} as past_due after payment failure")

    return JSONResponse({"status": "success"})


@app.get("/billing")
async def customer_portal(session_token: Optional[str] = Query(None)):
    """
    Redirect user to Stripe Customer Portal to manage their subscriptions.

    Args:
        session_token: User's session token

    Returns:
        Redirect to Stripe Customer Portal
    """
    if not session_token:
        raise HTTPException(401, "Missing session token")

    # Validate session and get user
    try:
        ctx = await create_request_context(server.database, session_token, server.config)
    except HTTPException:
        raise HTTPException(401, "Invalid or expired session token")

    # Get Stripe customer ID
    stripe_customer_id = server.database.get_stripe_customer_id(ctx.user_id)

    if not stripe_customer_id:
        return RedirectResponse(
            url=f"/dashboard?session_token={session_token}&error=no_subscriptions",
            status_code=303
        )

    # Initialize Stripe
    stripe.api_key = server.config.stripe_secret_key

    # Get deployment URL for return URL
    deployment_url = os.getenv("RAILWAY_PUBLIC_DOMAIN", os.getenv("DEPLOYMENT_URL", "http://localhost:8000"))
    if not deployment_url.startswith("http"):
        deployment_url = f"https://{deployment_url}"

    # Create Customer Portal session
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=f"{deployment_url}/dashboard?session_token={session_token}"
        )

        logger.info(f"Created billing portal session for user {ctx.email}")

        # Redirect to Customer Portal
        return RedirectResponse(url=portal_session.url, status_code=303)

    except Exception as e:
        logger.error(f"Error creating portal session: {e}")
        raise HTTPException(500, "Failed to create billing portal session")


@app.get("/sync-subscriptions")
async def sync_subscriptions(session_token: Optional[str] = Query(None)):
    """
    Manual sync: Update all user subscriptions from Stripe.
    Use this if webhooks aren't set up yet or subscriptions are out of sync.
    """
    if not session_token:
        raise HTTPException(401, "Missing session token")

    try:
        ctx = await create_request_context(server.database, session_token, server.config)
    except HTTPException:
        raise HTTPException(401, "Invalid session token")

    # Get user's Stripe customer ID
    stripe_customer_id = server.database.get_stripe_customer_id(ctx.user_id)
    if not stripe_customer_id:
        return JSONResponse({
            "status": "error",
            "message": "No Stripe customer found"
        })

    # Fetch all subscriptions from Stripe
    stripe.api_key = server.config.stripe_secret_key
    subscriptions = stripe.Subscription.list(customer=stripe_customer_id, limit=100)

    synced_count = 0
    for sub in subscriptions.data:
        # Map Stripe status
        status_map = {
            'active': 'active',
            'canceled': 'cancelled',
            'past_due': 'past_due',
            'unpaid': 'unpaid',
            'incomplete': 'unpaid',
            'incomplete_expired': 'cancelled',
            'trialing': 'active',
            'paused': 'cancelled'
        }
        our_status = status_map.get(sub['status'], 'cancelled')

        # Update in database
        try:
            period_start = datetime.fromtimestamp(sub['current_period_start'])
            period_end = datetime.fromtimestamp(sub['current_period_end'])
        except:
            period_start = datetime.now()
            period_end = datetime.now() + timedelta(days=30)

        # Extract cancellation info (if scheduled to cancel at period end)
        cancel_at_period_end = sub.get('cancel_at_period_end', False)
        cancel_at = None
        if sub.get('cancel_at'):
            cancel_at = datetime.fromtimestamp(sub['cancel_at'])

        # Debug logging
        logger.info(f"DEBUG sync: sub {sub['id']} - cancel_at_period_end={cancel_at_period_end}, cancel_at={cancel_at}")

        server.database.update_subscription_status(
            stripe_subscription_id=sub['id'],
            status=our_status,
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=cancel_at_period_end,
            cancel_at=cancel_at
        )
        synced_count += 1
        if cancel_at_period_end:
            logger.info(f"Synced subscription {sub['id']} - status: {our_status} (cancels on {cancel_at})")
        else:
            logger.info(f"Synced subscription {sub['id']} - status: {our_status}")

    return JSONResponse({
        "status": "success",
        "synced": synced_count,
        "message": f"Synced {synced_count} subscriptions from Stripe"
    })


# ===========================================================================
# ADMIN DASHBOARD
# ===========================================================================

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(error: Optional[str] = Query(None)):
    """Admin login page."""
    correct_password = os.getenv("ADMIN_PASSWORD")
    if not correct_password:
        return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>Admin Dashboard - Not Configured</title>
    <style>
        :root {
            --background: 0 0% 100%;
            --foreground: 222.2 84% 4.9%;
            --card: 0 0% 100%;
            --card-foreground: 222.2 84% 4.9%;
            --primary: 222.2 47.4% 11.2%;
            --primary-foreground: 210 40% 98%;
            --muted: 210 40% 96.1%;
            --muted-foreground: 215.4 16.3% 46.9%;
            --accent: 210 40% 96.1%;
            --accent-foreground: 222.2 47.4% 11.2%;
            --destructive: 0 84.2% 60.2%;
            --destructive-foreground: 210 40% 98%;
            --border: 214.3 31.8% 91.4%;
            --radius: 0.5rem;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            max-width: 600px;
            margin: 50px auto;
            padding: 20px;
            background: hsl(var(--muted));
        }
        .card {
            background: hsl(var(--card));
            padding: 40px;
            border-radius: var(--radius);
            box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1);
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>⚠️ Admin Dashboard Not Configured</h1>
        <p>Please set <code>ADMIN_PASSWORD</code> environment variable in Railway.</p>
    </div>
</body>
</html>
        """, status_code=500)

    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>Admin Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root {{
            --background: 0 0% 100%;
            --foreground: 222.2 84% 4.9%;
            --card: 0 0% 100%;
            --primary: 221.2 83.2% 53.3%;
            --primary-foreground: 210 40% 98%;
            --radius: 0.5rem;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            max-width: 500px;
            margin: 100px auto;
            padding: 20px;
            background: linear-gradient(135deg, hsl(var(--primary)) 0%, hsl(262 83% 58%) 100%);
            min-height: 100vh;
        }}
        .login-card {{
            background: hsl(var(--card));
            padding: 40px;
            border-radius: calc(var(--radius) * 2);
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }}
        h1 {{
            color: hsl(var(--foreground));
            margin-bottom: 10px;
            font-size: 28px;
        }}
        .subtitle {{
            color: hsl(215.4 16.3% 46.9%);
            margin-bottom: 30px;
            font-size: 14px;
        }}
        input {{
            width: 100%;
            padding: 12px;
            border: 2px solid hsl(214.3 31.8% 91.4%);
            border-radius: var(--radius);
            font-size: 16px;
            box-sizing: border-box;
            margin-bottom: 20px;
        }}
        input:focus {{
            outline: none;
            border-color: hsl(var(--primary));
        }}
        button {{
            width: 100%;
            background: linear-gradient(135deg, hsl(var(--primary)) 0%, hsl(262 83% 58%) 100%);
            color: hsl(var(--primary-foreground));
            padding: 14px;
            border: none;
            border-radius: var(--radius);
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
        }}
        button:hover {{
            opacity: 0.9;
        }}
        .error-msg {{
            background: hsl(0 84.2% 60.2% / 0.1);
            color: hsl(0 84.2% 60.2%);
            padding: 12px;
            border-radius: var(--radius);
            margin-bottom: 20px;
            font-size: 14px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="login-card">
        <h1>🔐 Admin Login</h1>
        <p class="subtitle">Gmail Reply Tracker MCP - Admin Dashboard</p>
        {'<div class="error-msg">❌ Invalid password. Please try again.</div>' if error else ''}
        <form method="post" action="/admin/login">
            <input type="email" name="admin_email" placeholder="Enter your email" required autofocus style="margin-bottom: 15px;">
            <input type="password" name="admin_password" placeholder="Enter admin password" required>
            <button type="submit">Login</button>
        </form>
    </div>
</body>
</html>
        """)


@app.post("/admin/login")
async def admin_login(request: Request, admin_email: str = Form(...), admin_password: str = Form(...)):
    """Handle admin login and set cookie."""
    from fastapi.responses import RedirectResponse

    correct_password = os.getenv("ADMIN_PASSWORD")
    if not correct_password or admin_password != correct_password:
        # Redirect back to login with error
        return RedirectResponse(url="/admin/login?error=1", status_code=303)

    # Create response with redirect to dashboard
    response = RedirectResponse(url="/admin", status_code=303)

    # Set secure cookies with admin session (valid for 8 hours)
    response.set_cookie(
        key="admin_session",
        value=admin_password,  # In production, use a hashed token
        max_age=28800,  # 8 hours
        httponly=True,
        samesite="lax"
    )

    response.set_cookie(
        key="admin_email",
        value=admin_email,
        max_age=28800,  # 8 hours
        httponly=False,  # Allow JavaScript to read for display
        samesite="lax"
    )

    return response


@app.get("/admin/logout")
async def admin_logout():
    """Logout admin and clear cookies."""
    from fastapi.responses import RedirectResponse

    response = RedirectResponse(url="/admin/login", status_code=303)

    # Clear both cookies
    response.delete_cookie(key="admin_session")
    response.delete_cookie(key="admin_email")

    return response


@app.get("/admin/test-tools", response_class=HTMLResponse)
async def admin_test_tools_page(
    request: Request,
    admin_password: Optional[str] = Query(None)
):
    """Tool testing playground for admin."""

    # Check admin authentication
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not authenticated:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        # Get all tools with metadata
        tool_list = await server.mcp.list_tools()

        # Categorize tools
        categorized_tools = {
            'gmail': [],
            'calendar': [],
            'sheets': [],
            'docs': [],
            'fathom': [],
            'instantly': [],
            'bison': [],
            'other': []
        }

        for tool in tool_list:
            # Determine category
            tool_name_lower = tool.name.lower()
            category = None

            if 'sheet' in tool_name_lower:
                category = 'sheets'
            elif 'doc' in tool_name_lower:
                category = 'docs'
            elif any(x in tool_name_lower for x in ['email','gmail','label','draft','send','thread','inbox']):
                category = 'gmail'
            elif any(x in tool_name_lower for x in ['calendar','event','availability']):
                category = 'calendar'
            elif 'fathom' in tool_name_lower:
                category = 'fathom'
            elif 'bison' in tool_name_lower:
                category = 'bison'
            elif 'instantly' in tool_name_lower:
                category = 'instantly'
            else:
                category = 'other'

            categorized_tools[category].append({
                'name': tool.name,
                'description': tool.description or '',
                'inputSchema': tool.inputSchema
            })

        # Convert to JSON for JavaScript
        tools_json = json.dumps(categorized_tools)

        # Get list of users for context testing
        users = server.database.list_users()
        users_list = [{'user_id': u['user_id'], 'email': u['email']} for u in users[:50]]  # Limit to 50
        users_json = json.dumps(users_list)

        return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tool Testing Playground - Admin</title>
    <style>
        :root {{
            --primary: 217 91% 60%;
            --secondary: 217 10% 50%;
            --success: 142 71% 45%;
            --destructive: 0 84% 60%;
            --muted: 210 40% 96%;
            --muted-foreground: 215 16% 47%;
            --card: 0 0% 100%;
            --border: 214 32% 91%;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: hsl(var(--muted));
            padding: 20px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .header {{
            background: white;
            padding: 24px;
            border-radius: 12px;
            margin-bottom: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}

        .header h1 {{
            font-size: 28px;
            margin-bottom: 8px;
        }}

        .header p {{
            color: hsl(var(--muted-foreground));
            font-size: 14px;
        }}

        .back-link {{
            display: inline-block;
            margin-bottom: 16px;
            color: hsl(var(--primary));
            text-decoration: none;
            font-weight: 600;
        }}

        .back-link:hover {{
            text-decoration: underline;
        }}

        .main-grid {{
            display: grid;
            grid-template-columns: 400px 1fr;
            gap: 24px;
        }}

        .card {{
            background: white;
            padding: 24px;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}

        .card h2 {{
            font-size: 18px;
            margin-bottom: 16px;
        }}

        .form-group {{
            margin-bottom: 20px;
        }}

        .form-label {{
            display: block;
            font-weight: 600;
            margin-bottom: 8px;
            font-size: 14px;
        }}

        .form-select, .form-input, .form-textarea {{
            width: 100%;
            padding: 10px 12px;
            border: 2px solid hsl(var(--border));
            border-radius: 6px;
            font-size: 14px;
            font-family: inherit;
        }}

        .form-select:focus, .form-input:focus, .form-textarea:focus {{
            outline: none;
            border-color: hsl(var(--primary));
        }}

        .form-textarea {{
            font-family: 'Monaco', 'Courier New', monospace;
            resize: vertical;
            min-height: 100px;
        }}

        .btn {{
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }}

        .btn-primary {{
            background: hsl(var(--primary));
            color: white;
        }}

        .btn-primary:hover {{
            opacity: 0.9;
        }}

        .btn-primary:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}

        .response-container {{
            margin-top: 20px;
            display: none;
        }}

        .response-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }}

        .response-meta {{
            display: flex;
            gap: 16px;
            font-size: 13px;
        }}

        .response-success {{
            color: hsl(var(--success));
            font-weight: 600;
        }}

        .response-error {{
            color: hsl(var(--destructive));
            font-weight: 600;
        }}

        .response-time {{
            color: hsl(var(--muted-foreground));
        }}

        .response-body {{
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 16px;
            border-radius: 6px;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.6;
            overflow-x: auto;
            max-height: 600px;
            overflow-y: auto;
        }}

        .params-container {{
            margin-top: 16px;
        }}

        .param-field {{
            margin-bottom: 16px;
        }}

        .param-label {{
            font-weight: 600;
            font-size: 13px;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .param-required {{
            color: hsl(var(--destructive));
            font-size: 12px;
        }}

        .param-type {{
            color: hsl(var(--muted-foreground));
            font-size: 12px;
            font-weight: normal;
        }}

        .param-description {{
            font-size: 12px;
            color: hsl(var(--muted-foreground));
            margin-top: 4px;
        }}

        .category-badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            background: hsl(var(--muted));
            color: hsl(var(--muted-foreground));
            margin-left: 8px;
        }}

        .tool-info {{
            background: hsl(var(--muted) / 0.5);
            padding: 12px;
            border-radius: 6px;
            font-size: 13px;
            color: hsl(var(--muted-foreground));
            margin-bottom: 16px;
        }}

        .history-item {{
            padding: 12px;
            border: 1px solid hsl(var(--border));
            border-radius: 6px;
            margin-bottom: 8px;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
        }}

        .history-item:hover {{
            background: hsl(var(--muted) / 0.5);
        }}

        .history-tool {{
            font-weight: 600;
            margin-bottom: 4px;
        }}

        .history-time {{
            color: hsl(var(--muted-foreground));
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <a href="/admin?admin_password={correct_password}" class="back-link">← Back to Admin Dashboard</a>

        <div class="header">
            <h1>🧪 Tool Testing Playground</h1>
            <p>Test any of the 85 MCP tools with custom parameters. Results are not logged to user activity.</p>
        </div>

        <div class="main-grid">
            <!-- Left Panel: Tool Selection & Parameters -->
            <div class="card">
                <h2>Tool Configuration</h2>

                <div class="form-group">
                    <label class="form-label">Select Tool</label>
                    <select id="tool-selector" class="form-select" onchange="loadToolParameters()">
                        <option value="">-- Choose a tool --</option>
                    </select>
                </div>

                <div id="tool-info" class="tool-info" style="display: none;"></div>

                <div id="params-container" class="params-container" style="display: none;">
                    <label class="form-label">Parameters</label>
                    <div id="params-form"></div>
                </div>

                <div class="form-group" style="display: none;" id="user-context-group">
                    <label class="form-label">Test with User Context (Optional)</label>
                    <select id="user-selector" class="form-select">
                        <option value="">-- No user context (single-user mode) --</option>
                    </select>
                </div>

                <button id="test-btn" class="btn btn-primary" onclick="testTool()" disabled>
                    🚀 Test Tool
                </button>
            </div>

            <!-- Right Panel: Response & History -->
            <div>
                <div class="card">
                    <h2>Response</h2>
                    <div id="response-placeholder" style="text-align: center; padding: 40px; color: hsl(var(--muted-foreground));">
                        Select a tool and click "Test Tool" to see results
                    </div>
                    <div id="response-container" class="response-container">
                        <div class="response-header">
                            <div class="response-meta">
                                <span id="response-status"></span>
                                <span id="response-time" class="response-time"></span>
                            </div>
                        </div>
                        <pre id="response-body" class="response-body"></pre>
                    </div>
                </div>

                <div class="card" style="margin-top: 24px;">
                    <h2>Test History</h2>
                    <div id="history-container" style="max-height: 300px; overflow-y: auto;">
                        <p style="text-align: center; color: hsl(var(--muted-foreground)); padding: 20px;">
                            No tests run yet
                        </p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Tool data from backend
        const toolsData = {tools_json};
        const usersData = {users_json};
        const adminPassword = "{correct_password}";

        // State
        let selectedTool = null;
        let testHistory = [];

        // Initialize
        window.addEventListener('DOMContentLoaded', () => {{
            populateToolDropdown();
            populateUserDropdown();
        }});

        function populateToolDropdown() {{
            const selector = document.getElementById('tool-selector');

            // Add tools by category
            const categories = {{
                'gmail': '📧 Gmail',
                'calendar': '📅 Calendar',
                'sheets': '📊 Sheets',
                'docs': '📄 Docs',
                'fathom': '📈 Fathom',
                'instantly': '📨 Instantly',
                'bison': '🦬 Bison',
                'other': '🔧 Other'
            }};

            for (const [category, label] of Object.entries(categories)) {{
                const tools = toolsData[category] || [];
                if (tools.length === 0) continue;

                const optgroup = document.createElement('optgroup');
                optgroup.label = `${{label}} (${{tools.length}} tools)`;

                tools.forEach(tool => {{
                    const option = document.createElement('option');
                    option.value = tool.name;
                    option.textContent = tool.name;
                    option.dataset.category = category;
                    option.dataset.description = tool.description;
                    option.dataset.schema = JSON.stringify(tool.inputSchema);
                    optgroup.appendChild(option);
                }});

                selector.appendChild(optgroup);
            }}
        }}

        function populateUserDropdown() {{
            const selector = document.getElementById('user-selector');

            usersData.forEach(user => {{
                const option = document.createElement('option');
                option.value = user.user_id;
                option.textContent = user.email;
                selector.appendChild(option);
            }});
        }}

        function loadToolParameters() {{
            const selector = document.getElementById('tool-selector');
            const selectedOption = selector.options[selector.selectedIndex];

            if (!selectedOption.value) {{
                document.getElementById('tool-info').style.display = 'none';
                document.getElementById('params-container').style.display = 'none';
                document.getElementById('test-btn').disabled = true;
                return;
            }}

            // Get tool metadata
            const toolName = selectedOption.value;
            const category = selectedOption.dataset.category;
            const description = selectedOption.dataset.description;
            const schema = JSON.parse(selectedOption.dataset.schema);

            selectedTool = {{
                name: toolName,
                category: category,
                description: description,
                schema: schema
            }};

            // Show tool info
            const categoryEmojis = {{
                'gmail': '📧', 'calendar': '📅', 'sheets': '📊',
                'docs': '📄', 'fathom': '📈', 'instantly': '📨',
                'bison': '🦬', 'other': '🔧'
            }};

            document.getElementById('tool-info').innerHTML = `
                <strong>${{categoryEmojis[category]}} ${{toolName}}</strong>
                <span class="category-badge">${{category}}</span>
                <div style="margin-top: 8px;">${{description}}</div>
            `;
            document.getElementById('tool-info').style.display = 'block';

            // Generate parameter form
            generateParameterForm(schema);

            document.getElementById('params-container').style.display = 'block';
            document.getElementById('user-context-group').style.display = 'block';
            document.getElementById('test-btn').disabled = false;
        }}

        function generateParameterForm(schema) {{
            const container = document.getElementById('params-form');
            container.innerHTML = '';

            if (!schema || !schema.properties) {{
                container.innerHTML = '<p style="color: hsl(var(--muted-foreground)); font-size: 13px;">No parameters required</p>';
                return;
            }}

            const properties = schema.properties;
            const required = schema.required || [];

            for (const [paramName, paramDef] of Object.entries(properties)) {{
                const isRequired = required.includes(paramName);
                const paramType = paramDef.type || 'string';
                const paramDesc = paramDef.description || '';
                const paramDefault = paramDef.default;

                const fieldDiv = document.createElement('div');
                fieldDiv.className = 'param-field';

                let inputHtml = '';
                const inputId = `param-${{paramName}}`;

                if (paramType === 'boolean') {{
                    inputHtml = `
                        <select id="${{inputId}}" class="form-input" ${{isRequired ? 'required' : ''}}>
                            <option value="true" ${{paramDefault === true ? 'selected' : ''}}>true</option>
                            <option value="false" ${{paramDefault === false ? 'selected' : ''}}>false</option>
                        </select>
                    `;
                }} else if (paramType === 'integer' || paramType === 'number') {{
                    inputHtml = `
                        <input
                            type="number"
                            id="${{inputId}}"
                            class="form-input"
                            placeholder="Enter ${{paramType}}"
                            value="${{paramDefault !== undefined ? paramDefault : ''}}"
                            ${{isRequired ? 'required' : ''}}
                        />
                    `;
                }} else if (paramDef.enum) {{
                    inputHtml = `
                        <select id="${{inputId}}" class="form-input" ${{isRequired ? 'required' : ''}}>
                            <option value="">-- Select --</option>
                            ${{paramDef.enum.map(val => `<option value="${{val}}" ${{paramDefault === val ? 'selected' : ''}}>${{val}}</option>`).join('')}}
                        </select>
                    `;
                }} else {{
                    // String or other types
                    inputHtml = `
                        <input
                            type="text"
                            id="${{inputId}}"
                            class="form-input"
                            placeholder="Enter ${{paramName}}"
                            value="${{paramDefault !== undefined ? paramDefault : ''}}"
                            ${{isRequired ? 'required' : ''}}
                        />
                    `;
                }}

                fieldDiv.innerHTML = `
                    <div class="param-label">
                        ${{paramName}}
                        ${{isRequired ? '<span class="param-required">*required</span>' : ''}}
                        <span class="param-type">(${{paramType}})</span>
                    </div>
                    ${{inputHtml}}
                    ${{paramDesc ? `<div class="param-description">${{paramDesc}}</div>` : ''}}
                `;

                container.appendChild(fieldDiv);
            }}
        }}

        async function testTool() {{
            if (!selectedTool) return;

            // Collect parameter values
            const schema = selectedTool.schema;
            const arguments = {{}};

            if (schema && schema.properties) {{
                for (const paramName of Object.keys(schema.properties)) {{
                    const inputId = `param-${{paramName}}`;
                    const input = document.getElementById(inputId);

                    if (input && input.value) {{
                        const paramType = schema.properties[paramName].type;

                        if (paramType === 'integer') {{
                            arguments[paramName] = parseInt(input.value, 10);
                        }} else if (paramType === 'number') {{
                            arguments[paramName] = parseFloat(input.value);
                        }} else if (paramType === 'boolean') {{
                            arguments[paramName] = input.value === 'true';
                        }} else {{
                            arguments[paramName] = input.value;
                        }}
                    }}
                }}
            }}

            // Get user context if selected
            const userSelector = document.getElementById('user-selector');
            const userId = userSelector.value || null;

            // Disable button
            const testBtn = document.getElementById('test-btn');
            testBtn.disabled = true;
            testBtn.textContent = '⏳ Testing...';

            // Hide placeholder, show response container
            document.getElementById('response-placeholder').style.display = 'none';
            document.getElementById('response-container').style.display = 'block';

            try {{
                const response = await fetch(`/admin/test-tool?admin_password=${{adminPassword}}`, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        tool_name: selectedTool.name,
                        arguments: arguments,
                        user_id: userId
                    }})
                }});

                const result = await response.json();

                // Display response
                if (result.success) {{
                    document.getElementById('response-status').innerHTML = '<span class="response-success">✓ Success</span>';
                    document.getElementById('response-time').textContent = `${{result.response_time_ms}}ms`;
                    document.getElementById('response-body').textContent = JSON.stringify(result.result, null, 2);
                }} else {{
                    document.getElementById('response-status').innerHTML = '<span class="response-error">✗ Error</span>';
                    document.getElementById('response-time').textContent = '';
                    document.getElementById('response-body').textContent = JSON.stringify({{
                        error: result.error,
                        error_type: result.error_type,
                        stack_trace: result.stack_trace
                    }}, null, 2);
                }}

                // Add to history
                addToHistory({{
                    tool: selectedTool.name,
                    arguments: arguments,
                    success: result.success,
                    time: result.response_time_ms,
                    timestamp: new Date().toLocaleTimeString()
                }});

            }} catch (error) {{
                document.getElementById('response-status').innerHTML = '<span class="response-error">✗ Network Error</span>';
                document.getElementById('response-time').textContent = '';
                document.getElementById('response-body').textContent = `Error: ${{error.message}}`;
            }} finally {{
                testBtn.disabled = false;
                testBtn.textContent = '🚀 Test Tool';
            }}
        }}

        function addToHistory(entry) {{
            testHistory.unshift(entry);
            if (testHistory.length > 10) testHistory.pop();  // Keep last 10

            const container = document.getElementById('history-container');
            container.innerHTML = testHistory.map(item => `
                <div class="history-item" onclick='rerunTest(${{JSON.stringify(item.arguments)}}, "${{item.tool}}")'>
                    <div class="history-tool">
                        ${{item.success ? '✓' : '✗'}} ${{item.tool}}
                        ${{item.time ? `<span style="color: hsl(var(--muted-foreground)); font-weight: normal;">(${{item.time}}ms)</span>` : ''}}
                    </div>
                    <div class="history-time">${{item.timestamp}}</div>
                </div>
            `).join('');
        }}

        function rerunTest(args, toolName) {{
            // Select the tool
            const selector = document.getElementById('tool-selector');
            selector.value = toolName;
            loadToolParameters();

            // Fill in parameters
            setTimeout(() => {{
                for (const [paramName, paramValue] of Object.entries(args)) {{
                    const input = document.getElementById(`param-${{paramName}}`);
                    if (input) {{
                        input.value = paramValue;
                    }}
                }}
            }}, 100);
        }}
    </script>
</body>
</html>
        """)

    except Exception as e:
        logger.error(f"Error loading test tools page: {e}")
        raise HTTPException(500, str(e))


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, admin_password: Optional[str] = Query(None)):
    """Admin dashboard for managing users and viewing analytics."""
    # Check admin password from cookie or query param (backward compatibility)
    correct_password = os.getenv("ADMIN_PASSWORD")
    if not correct_password:
        return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>Admin Dashboard - Not Configured</title>
    <style>
        :root {
            --background: 0 0% 100%;
            --foreground: 222.2 84% 4.9%;
            --card: 0 0% 100%;
            --muted: 210 40% 96.1%;
            --border: 214.3 31.8% 91.4%;
            --radius: 0.5rem;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            max-width: 600px;
            margin: 50px auto;
            padding: 20px;
            background: hsl(var(--muted));
        }
        .card {
            background: hsl(var(--card));
            padding: 40px;
            border-radius: var(--radius);
            box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1);
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>⚠️ Admin Dashboard Not Configured</h1>
        <p>Please set <code>ADMIN_PASSWORD</code> environment variable in Railway.</p>
    </div>
</body>
</html>
        """, status_code=500)

    # Check cookie first, then query param
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not authenticated:
        # Redirect to login page
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin/login", status_code=303)

    # Get admin email from cookie (for display)
    admin_email = request.cookies.get("admin_email", "Admin")

    # Admin authenticated - show dashboard
    try:
        # Get all data
        users = server.database.list_users()
        stats = server.database.get_all_usage_stats(days=7)
        recent_activity = server.database.get_recent_activity(limit=20)

        # Get subscription stats
        subscription_stats = server.database.get_subscription_stats()
        all_user_subs = server.database.get_all_user_subscriptions()

        # Calculate additional metrics
        total_users = len(users)
        active_users = len([u for u in users if u.get('last_active')])
        users_with_api_keys = len([u for u in users if u.get('has_api_keys')])

        # Format users table with action buttons
        users_html = ""
        for user in users:
            last_active = user.get('last_active', 'Never')
            if last_active and last_active != 'Never':
                from dateutil import parser
                try:
                    dt = parser.parse(last_active)
                    last_active = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass

            api_keys_status = "has-keys" if user.get('has_api_keys') else "no-keys"
            api_keys_badge = '<span class="badge badge-success">✓ API Keys</span>' if user.get('has_api_keys') else '<span class="badge badge-muted">No Keys</span>'

            # Get subscription info for this user
            user_sub_info = all_user_subs.get(user['user_id'], {})
            is_paying = user_sub_info.get('is_paying', False)
            sub_count = user_sub_info.get('subscription_count', 0)
            user_mrr = user_sub_info.get('mrr', 0)

            # Subscription badge
            if is_paying:
                sub_badge = f'<span class="badge badge-success" style="background: #10b981;">💰 ${user_mrr}/mo ({sub_count} subs)</span>'
            else:
                sub_badge = '<span class="badge badge-muted">🆓 Free</span>'

            users_html += f"""
            <div style="background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 12px; cursor: pointer; transition: all 0.2s;" onclick="window.location.href='/admin/user/{user['user_id']}'" onmouseover="this.style.boxShadow='0 4px 12px rgba(0,0,0,0.15)'" onmouseout="this.style.boxShadow='0 1px 3px rgba(0,0,0,0.1)'">
                <div style="display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 20px;">
                    <!-- User Info -->
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <div class="user-avatar" style="width: 40px; height: 40px; border-radius: 50%; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 16px;">{user['email'][0].upper()}</div>
                        <div>
                            <div style="font-weight: 600; font-size: 15px; color: #1a202c; margin-bottom: 4px;">{user['email']}</div>
                            <div style="font-size: 13px; color: #718096;">Last active: {last_active}</div>
                        </div>
                    </div>

                    <!-- Subscription Badge -->
                    <div style="text-align: center;">
                        {sub_badge}
                    </div>

                    <!-- API Keys Badge -->
                    <div style="text-align: center;">
                        {api_keys_badge}
                    </div>

                    <!-- Action Button -->
                    <button class="action-btn" onclick="event.stopPropagation(); window.location.href='/admin/user/{user['user_id']}'" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: 500; font-size: 14px;">View Details →</button>
                </div>
            </div>
            """

        # Format recent activity
        activity_html = ""
        for activity in recent_activity[:20]:
            status_badge = '<span class="badge badge-success">✓</span>' if activity['success'] else '<span class="badge badge-destructive">✗</span>'
            timestamp = activity['timestamp']
            if isinstance(timestamp, str):
                from dateutil import parser
                try:
                    dt = parser.parse(timestamp)
                    timestamp = dt.strftime('%H:%M:%S')
                except:
                    pass

            activity_html += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid hsl(var(--border)); font-size: 14px; color: hsl(var(--muted-foreground));">{timestamp}</td>
                <td style="padding: 12px; border-bottom: 1px solid hsl(var(--border)); font-size: 14px;">{activity['email']}</td>
                <td style="padding: 12px; border-bottom: 1px solid hsl(var(--border)); font-size: 14px;"><code style="background: hsl(var(--muted)); padding: 2px 8px; border-radius: 4px; font-size: 12px;">{activity['tool']}</code></td>
                <td style="padding: 12px; border-bottom: 1px solid hsl(var(--border)); text-align: center;">{status_badge}</td>
            </tr>
            """

        # Format top tools
        top_tools_html = ""
        for tool, count in list(stats.get('top_tools', {}).items())[:10]:
            top_tools_html += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid hsl(var(--border));"><code style="background: hsl(var(--muted)); padding: 2px 8px; border-radius: 4px; font-size: 12px;">{tool}</code></td>
                <td style="padding: 12px; border-bottom: 1px solid hsl(var(--border)); text-align: right; font-weight: 600; color: hsl(var(--primary));">{count}</td>
            </tr>
            """

        return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>Admin Dashboard - Gmail Reply Tracker MCP</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root {{
            --background: 0 0% 100%;
            --foreground: 222.2 84% 4.9%;
            --card: 0 0% 100%;
            --card-foreground: 222.2 84% 4.9%;
            --popover: 0 0% 100%;
            --popover-foreground: 222.2 84% 4.9%;
            --primary: 221.2 83.2% 53.3%;
            --primary-foreground: 210 40% 98%;
            --secondary: 210 40% 96.1%;
            --secondary-foreground: 222.2 47.4% 11.2%;
            --muted: 210 40% 96.1%;
            --muted-foreground: 215.4 16.3% 46.9%;
            --accent: 210 40% 96.1%;
            --accent-foreground: 222.2 47.4% 11.2%;
            --destructive: 0 84.2% 60.2%;
            --destructive-foreground: 210 40% 98%;
            --border: 214.3 31.8% 91.4%;
            --input: 214.3 31.8% 91.4%;
            --ring: 221.2 83.2% 53.3%;
            --radius: 0.5rem;
            --success: 142.1 76.2% 36.3%;
            --success-foreground: 355.7 100% 97.3%;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: hsl(var(--muted));
            padding: 24px;
            color: hsl(var(--foreground));
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .header {{
            background: linear-gradient(135deg, hsl(var(--primary)) 0%, hsl(262 83% 58%) 100%);
            color: hsl(var(--primary-foreground));
            padding: 32px;
            border-radius: calc(var(--radius) * 2);
            margin-bottom: 32px;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .header-content h1 {{
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 8px;
        }}

        .header-content p {{
            opacity: 0.9;
            font-size: 16px;
        }}

        .logout-btn {{
            background: hsl(var(--primary-foreground) / 0.2);
            color: hsl(var(--primary-foreground));
            padding: 10px 20px;
            border: 2px solid hsl(var(--primary-foreground) / 0.3);
            border-radius: var(--radius);
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            text-decoration: none;
            transition: all 0.2s;
        }}

        .logout-btn:hover {{
            background: hsl(var(--primary-foreground) / 0.3);
            border-color: hsl(var(--primary-foreground) / 0.5);
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 24px;
            margin-bottom: 32px;
        }}

        .stat-card {{
            background: hsl(var(--card));
            padding: 24px;
            border-radius: var(--radius);
            box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1);
            border: 1px solid hsl(var(--border));
            transition: all 0.2s;
            position: relative;
            overflow: hidden;
        }}

        .stat-card:hover {{
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
            transform: translateY(-2px);
        }}

        .stat-card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: linear-gradient(90deg, hsl(var(--primary)) 0%, hsl(262 83% 58%) 100%);
        }}

        .stat-icon {{
            font-size: 24px;
            margin-bottom: 12px;
        }}

        .stat-value {{
            font-size: 36px;
            font-weight: 700;
            color: hsl(var(--primary));
            margin-bottom: 8px;
            line-height: 1;
        }}

        .stat-label {{
            color: hsl(var(--muted-foreground));
            font-size: 14px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .section {{
            background: hsl(var(--card));
            padding: 24px;
            border-radius: var(--radius);
            margin-bottom: 24px;
            box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1);
            border: 1px solid hsl(var(--border));
        }}

        .section h2 {{
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 20px;
            color: hsl(var(--foreground));
            display: flex;
            align-items: center;
            gap: 8px;
            padding-bottom: 12px;
            border-bottom: 2px solid hsl(var(--border));
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
        }}

        th {{
            background: hsl(var(--muted));
            padding: 12px 16px;
            text-align: left;
            font-weight: 600;
            font-size: 12px;
            color: hsl(var(--muted-foreground));
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid hsl(var(--border));
        }}

        .user-row {{
            cursor: pointer;
            transition: background-color 0.15s;
        }}

        .user-row:hover {{
            background-color: hsl(var(--muted));
        }}

        .user-avatar {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: linear-gradient(135deg, hsl(var(--primary)) 0%, hsl(262 83% 58%) 100%);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 14px;
        }}

        .badge {{
            display: inline-flex;
            align-items: center;
            border-radius: calc(var(--radius) * 0.5);
            padding: 4px 12px;
            font-size: 12px;
            font-weight: 600;
            line-height: 1;
            white-space: nowrap;
        }}

        .badge-success {{
            background: hsl(var(--success) / 0.1);
            color: hsl(var(--success));
        }}

        .badge-muted {{
            background: hsl(var(--muted));
            color: hsl(var(--muted-foreground));
        }}

        .badge-destructive {{
            background: hsl(var(--destructive) / 0.1);
            color: hsl(var(--destructive));
        }}

        .action-btn {{
            background: hsl(var(--primary));
            color: hsl(var(--primary-foreground));
            padding: 8px 16px;
            border: none;
            border-radius: var(--radius);
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.2s;
        }}

        .action-btn:hover {{
            background: hsl(var(--primary) / 0.9);
            transform: translateY(-1px);
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .refresh-btn {{
            background: hsl(var(--primary));
            color: hsl(var(--primary-foreground));
            padding: 12px 24px;
            border: none;
            border-radius: var(--radius);
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.2s;
            box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1);
        }}

        .refresh-btn:hover {{
            background: hsl(var(--primary) / 0.9);
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        }}

        @media (max-width: 768px) {{
            .stats-grid {{
                grid-template-columns: 1fr;
            }}

            body {{
                padding: 16px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-content">
                <h1>🛠️ Admin Dashboard</h1>
                <p>Gmail Reply Tracker MCP - System Overview</p>
                <p style="opacity: 0.8; font-size: 14px; margin-top: 8px;">Logged in as: {admin_email}</p>
            </div>
            <a href="/admin/logout" class="logout-btn">Logout</a>
        </div>

        <!-- Subscription Stats -->
        <div class="stats-grid">
            <div class="stat-card" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
                <div class="stat-icon">💰</div>
                <div class="stat-value" style="color: white;">${subscription_stats['total_mrr']}</div>
                <div class="stat-label" style="color: rgba(255,255,255,0.9);">Monthly Recurring Revenue</div>
            </div>
            <div class="stat-card" style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white;">
                <div class="stat-icon">📊</div>
                <div class="stat-value" style="color: white;">{subscription_stats['total_subscriptions']}</div>
                <div class="stat-label" style="color: rgba(255,255,255,0.9);">Active Subscriptions</div>
            </div>
            <div class="stat-card" style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); color: white;">
                <div class="stat-icon">👥</div>
                <div class="stat-value" style="color: white;">{subscription_stats['paying_users']}</div>
                <div class="stat-label" style="color: rgba(255,255,255,0.9);">Paying Users</div>
            </div>
            <div class="stat-card" style="background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); color: white;">
                <div class="stat-icon">🆓</div>
                <div class="stat-value" style="color: white;">{subscription_stats['free_users']}</div>
                <div class="stat-label" style="color: rgba(255,255,255,0.9);">Free Users</div>
            </div>
        </div>

        <!-- Usage Stats -->
        <div class="stats-grid" style="margin-top: 20px;">
            <div class="stat-card">
                <div class="stat-icon">👥</div>
                <div class="stat-value">{total_users}</div>
                <div class="stat-label">Total Users</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">✨</div>
                <div class="stat-value">{active_users}</div>
                <div class="stat-label">Active Users</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">🔑</div>
                <div class="stat-value">{users_with_api_keys}</div>
                <div class="stat-label">Users with API Keys</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">📊</div>
                <div class="stat-value">{stats.get('total_requests', 0)}</div>
                <div class="stat-label">Total Requests (7d)</div>
            </div>
        </div>

        <!-- Popular Categories -->
        <div class="section" style="margin-top: 30px;">
            <h2><span>🏆</span> Popular Tool Categories</h2>
            <div style="background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                {(''.join([f'<div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #e5e7eb;"><span style="font-weight: 500; text-transform: capitalize;">📦 {category}</span><span style="color: #10b981; font-weight: 600;">{count} subscriptions (${count * 5}/mo)</span></div>' for category, count in subscription_stats['category_breakdown'].items()]) if subscription_stats['category_breakdown'] else '<p style="color: #6b7280; text-align: center;">No subscriptions yet</p>')}
            </div>
        </div>

        <div class="section">
            <h2><span>👥</span> All Users</h2>
            <div>
                {users_html if users_html else '<div style="background: white; padding: 40px; border-radius: 8px; text-align: center; color: hsl(var(--muted-foreground));">No users yet</div>'}
            </div>
        </div>

        <div class="section">
            <h2><span>📊</span> Top Tools (Last 7 Days)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Tool Name</th>
                        <th style="text-align: right;">Calls</th>
                    </tr>
                </thead>
                <tbody>
                    {top_tools_html if top_tools_html else '<tr><td colspan="2" style="padding: 20px; text-align: center; color: hsl(var(--muted-foreground));">No usage yet</td></tr>'}
                </tbody>
            </table>
        </div>

        <div class="section">
            <h2><span>🔄</span> Recent Activity</h2>
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>User</th>
                        <th>Tool</th>
                        <th style="text-align: center;">Status</th>
                    </tr>
                </thead>
                <tbody>
                    {activity_html if activity_html else '<tr><td colspan="4" style="padding: 20px; text-align: center; color: hsl(var(--muted-foreground));">No activity yet</td></tr>'}
                </tbody>
            </table>
        </div>

        <!-- Developer Tools -->
        <div class="section" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border: none; color: white;">
            <h2 style="color: white;"><span>🧪</span> Developer Tools</h2>
            <div style="margin-top: 20px;">
                <a href="/admin/test-tools?admin_password={correct_password}"
                   style="display: flex; align-items: center; justify-content: space-between; padding: 20px; background: rgba(255,255,255,0.15); border-radius: var(--radius); text-decoration: none; color: white; transition: all 0.2s; backdrop-filter: blur(10px);"
                   onmouseover="this.style.background='rgba(255,255,255,0.25)'; this.style.transform='translateY(-2px)'; this.style.boxShadow='0 4px 12px rgba(0,0,0,0.2)';"
                   onmouseout="this.style.background='rgba(255,255,255,0.15)'; this.style.transform='translateY(0)'; this.style.boxShadow='none';">
                    <div>
                        <div style="font-weight: 700; font-size: 18px; margin-bottom: 6px;">🧪 Tool Testing Playground</div>
                        <div style="opacity: 0.9; font-size: 14px;">Test any of the 85 MCP tools with custom parameters. Perfect for debugging and development.</div>
                    </div>
                    <div style="font-size: 24px; opacity: 0.7;">→</div>
                </a>
            </div>
        </div>

        <div style="text-align: center; margin-top: 32px;">
            <button class="refresh-btn" onclick="location.reload()">🔄 Refresh Data</button>
        </div>
    </div>
</body>
</html>
        """)

    except Exception as e:
        logger.error(f"Error in admin dashboard: {e}")
        return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>Admin Dashboard - Error</title>
</head>
<body>
    <h1>Error loading admin dashboard</h1>
    <p>{str(e)}</p>
</body>
</html>
        """, status_code=500)


@app.get("/admin/user/{user_id}", response_class=HTMLResponse)
async def admin_user_detail(request: Request, user_id: str, admin_password: Optional[str] = Query(None)):
    """User detail page for admin dashboard."""
    # Check admin password from cookie or query param
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not correct_password or not authenticated:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        # Get user data
        result = server.database.supabase.table('users').select('*').eq('user_id', user_id).execute()

        if not result.data:
            return HTMLResponse("User not found", status_code=404)

        user_data = result.data[0]

        # Decrypt API keys to check which ones are configured
        from cryptography.fernet import Fernet
        cipher = Fernet(os.getenv("TOKEN_ENCRYPTION_KEY").encode())

        api_keys = {}
        if user_data.get('encrypted_api_keys'):
            try:
                api_keys = json.loads(cipher.decrypt(user_data['encrypted_api_keys'].encode()).decode())
            except:
                pass

        # Get enabled tool categories
        enabled_categories = None
        if user_data.get('enabled_tool_categories'):
            try:
                import json as json_module
                enabled_categories = json_module.loads(user_data['enabled_tool_categories'])
            except:
                pass

        # Calculate tool count
        tool_counts = {'gmail': 25, 'calendar': 15, 'docs': 8, 'sheets': 12, 'fathom': 11, 'instantly': 10, 'bison': 4}

        # Define category info for display
        category_info = {
            'gmail': {'emoji': '📧', 'name': 'Gmail', 'tools': 25},
            'calendar': {'emoji': '📅', 'name': 'Calendar', 'tools': 15},
            'docs': {'emoji': '📄', 'name': 'Docs', 'tools': 8},
            'sheets': {'emoji': '📊', 'name': 'Sheets', 'tools': 12},
            'fathom': {'emoji': '📈', 'name': 'Fathom', 'tools': 11},
            'instantly': {'emoji': '📨', 'name': 'Instantly', 'tools': 10},
            'bison': {'emoji': '🦬', 'name': 'Bison', 'tools': 4}
        }

        # Get detailed subscription info for management (needed before tool_status calculation)
        all_subscriptions = server.database.get_user_subscriptions(user_id)
        active_categories = [sub['tool_category'] for sub in all_subscriptions if sub['status'] == 'active']

        # Calculate based on active subscriptions, not preferences
        if enabled_categories is None:
            # Show all categories but indicate which have active subscriptions
            total_tools = sum(tool_counts.get(cat, 0) for cat in active_categories)
            if len(active_categories) == 7:
                tool_status = "All 7 categories active"
            elif len(active_categories) == 0:
                tool_status = "No active subscriptions"
            else:
                tool_status = f"{len(active_categories)}/7 categories active"
        elif len(enabled_categories) == 0:
            total_tools = 0
            tool_status = "No tools enabled (filtered by user preference)"
        else:
            # Count tools from enabled categories that also have active subscriptions
            active_enabled = [cat for cat in enabled_categories if cat in active_categories]
            total_tools = sum(tool_counts.get(cat, 0) for cat in active_enabled)
            tool_status = f"{len(active_enabled)}/{len(enabled_categories)} enabled categories active"

        # Get usage stats
        usage_stats = server.database.get_user_usage_stats(user_id, days=30)

        # Get subscription info
        subscription_info = server.database.get_user_subscription_summary(user_id)

        # Get recent activity
        recent_logs = server.database.supabase.table('usage_logs').select('*').eq('user_id', user_id).order('timestamp', desc=True).limit(20).execute()

        # Get user's teams
        user_teams = []
        if user_data.get('teams_enabled', False):
            user_teams = server.database.get_user_teams(user_id)

            # For each team, get subscriptions and member count
            for team in user_teams:
                team_subs = server.database.supabase.table('subscriptions').select('tool_category').eq(
                    'team_id', team['team_id']
                ).eq('is_team_subscription', True).eq('status', 'active').execute()
                team['active_categories'] = [s['tool_category'] for s in (team_subs.data if team_subs.data else [])]

                # Get member count
                members = server.database.get_team_members(team['team_id'])
                team['member_count'] = len(members)

        # Format dates
        from dateutil import parser as date_parser
        created_at = user_data.get('created_at', 'Unknown')
        if created_at and created_at != 'Unknown':
            try:
                dt = date_parser.parse(created_at)
                created_at = dt.strftime('%B %d, %Y at %H:%M')
            except:
                pass

        last_active = user_data.get('last_active', 'Never')
        if last_active and last_active != 'Never':
            try:
                dt = date_parser.parse(last_active)
                last_active = dt.strftime('%B %d, %Y at %H:%M')
            except:
                pass

        session_expiry = user_data.get('session_expiry', 'Unknown')
        if session_expiry and session_expiry != 'Unknown':
            try:
                dt = date_parser.parse(session_expiry)
                session_expiry = dt.strftime('%B %d, %Y')
            except:
                pass

        # Build API keys badges
        api_keys_badges = ""
        available_keys = ['fathom', 'instantly']
        for key in available_keys:
            if key in api_keys and api_keys[key]:
                api_keys_badges += f'<span class="badge badge-success">✓ {key.title()}</span> '
            else:
                api_keys_badges += f'<span class="badge badge-muted">{key.title()}</span> '

        # Build tool categories badges based on active subscriptions
        tool_categories_html = ""
        all_categories = ['gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison']
        for cat in all_categories:
            if cat in active_categories:
                tool_categories_html += f'<span class="badge badge-success">✓ {cat.title()} ({tool_counts[cat]})</span> '
            else:
                tool_categories_html += f'<span class="badge badge-muted">{cat.title()}</span> '

        # Build recent activity timeline
        activity_timeline = ""
        for log in recent_logs.data[:15]:
            timestamp = log['timestamp']
            if isinstance(timestamp, str):
                try:
                    dt = date_parser.parse(timestamp)
                    timestamp = dt.strftime('%b %d, %H:%M')
                except:
                    pass

            status_class = "success" if log['success'] else "destructive"
            status_icon = "✓" if log['success'] else "✗"

            activity_timeline += f"""
            <div class="timeline-item">
                <div class="timeline-marker {status_class}"></div>
                <div class="timeline-content">
                    <div class="timeline-header">
                        <code>{log['tool_name']}</code>
                        <span class="badge badge-{status_class}">{status_icon}</span>
                    </div>
                    <div class="timeline-time">{timestamp}</div>
                    {f'<div class="timeline-error">{log["error_message"]}</div>' if not log['success'] and log.get('error_message') else ''}
                </div>
            </div>
            """

        return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>User Details - {user_data['email']}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root {{
            --background: 0 0% 100%;
            --foreground: 222.2 84% 4.9%;
            --card: 0 0% 100%;
            --card-foreground: 222.2 84% 4.9%;
            --primary: 221.2 83.2% 53.3%;
            --primary-foreground: 210 40% 98%;
            --secondary: 210 40% 96.1%;
            --secondary-foreground: 222.2 47.4% 11.2%;
            --muted: 210 40% 96.1%;
            --muted-foreground: 215.4 16.3% 46.9%;
            --accent: 210 40% 96.1%;
            --accent-foreground: 222.2 47.4% 11.2%;
            --destructive: 0 84.2% 60.2%;
            --destructive-foreground: 210 40% 98%;
            --border: 214.3 31.8% 91.4%;
            --radius: 0.5rem;
            --success: 142.1 76.2% 36.3%;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: hsl(var(--muted));
            padding: 24px;
            color: hsl(var(--foreground));
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        .back-link {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: hsl(var(--muted-foreground));
            text-decoration: none;
            margin-bottom: 24px;
            font-size: 14px;
            font-weight: 500;
            transition: color 0.2s;
        }}

        .back-link:hover {{
            color: hsl(var(--primary));
        }}

        .page-header {{
            background: hsl(var(--card));
            padding: 32px;
            border-radius: var(--radius);
            margin-bottom: 24px;
            box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1);
            border: 1px solid hsl(var(--border));
            display: flex;
            justify-content: space-between;
            align-items: start;
        }}

        .user-info {{
            display: flex;
            gap: 20px;
            align-items: start;
        }}

        .user-avatar-large {{
            width: 80px;
            height: 80px;
            border-radius: 50%;
            background: linear-gradient(135deg, hsl(var(--primary)) 0%, hsl(262 83% 58%) 100%);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 32px;
            flex-shrink: 0;
        }}

        .user-details h1 {{
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 8px;
            color: hsl(var(--foreground));
        }}

        .user-meta {{
            display: flex;
            gap: 16px;
            margin-top: 12px;
            color: hsl(var(--muted-foreground));
            font-size: 14px;
        }}

        .user-meta-item {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .actions {{
            display: flex;
            gap: 12px;
            flex-direction: column;
        }}

        .action-btn {{
            background: hsl(var(--primary));
            color: hsl(var(--primary-foreground));
            padding: 10px 20px;
            border: none;
            border-radius: var(--radius);
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.2s;
            text-decoration: none;
            display: inline-block;
            text-align: center;
        }}

        .action-btn:hover {{
            background: hsl(var(--primary) / 0.9);
            transform: translateY(-1px);
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .action-btn-secondary {{
            background: hsl(var(--secondary));
            color: hsl(var(--secondary-foreground));
        }}

        .action-btn-destructive {{
            background: hsl(var(--destructive));
            color: hsl(var(--destructive-foreground));
        }}

        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 24px;
            margin-bottom: 24px;
        }}

        .card {{
            background: hsl(var(--card));
            padding: 24px;
            border-radius: var(--radius);
            box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1);
            border: 1px solid hsl(var(--border));
        }}

        .card h2 {{
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 16px;
            color: hsl(var(--foreground));
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .stat-row {{
            display: flex;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid hsl(var(--border));
        }}

        .stat-row:last-child {{
            border-bottom: none;
        }}

        .stat-label {{
            color: hsl(var(--muted-foreground));
            font-size: 14px;
        }}

        .stat-value {{
            font-weight: 600;
            color: hsl(var(--foreground));
        }}

        .badge {{
            display: inline-flex;
            align-items: center;
            border-radius: calc(var(--radius) * 0.5);
            padding: 4px 12px;
            font-size: 12px;
            font-weight: 600;
            line-height: 1;
            white-space: nowrap;
            margin-right: 8px;
            margin-bottom: 8px;
        }}

        .badge-success {{
            background: hsl(var(--success) / 0.1);
            color: hsl(var(--success));
        }}

        .badge-muted {{
            background: hsl(var(--muted));
            color: hsl(var(--muted-foreground));
        }}

        .badge-destructive {{
            background: hsl(var(--destructive) / 0.1);
            color: hsl(var(--destructive));
        }}

        .timeline {{
            margin-top: 16px;
        }}

        .timeline-item {{
            display: flex;
            gap: 16px;
            margin-bottom: 20px;
            position: relative;
        }}

        .timeline-item:not(:last-child)::after {{
            content: '';
            position: absolute;
            left: 7px;
            top: 24px;
            bottom: -20px;
            width: 2px;
            background: hsl(var(--border));
        }}

        .timeline-marker {{
            width: 16px;
            height: 16px;
            border-radius: 50%;
            flex-shrink: 0;
            margin-top: 4px;
        }}

        .timeline-marker.success {{
            background: hsl(var(--success));
        }}

        .timeline-marker.destructive {{
            background: hsl(var(--destructive));
        }}

        .timeline-content {{
            flex: 1;
        }}

        .timeline-header {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 4px;
        }}

        .timeline-header code {{
            background: hsl(var(--muted));
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 12px;
        }}

        .timeline-time {{
            color: hsl(var(--muted-foreground));
            font-size: 13px;
        }}

        .timeline-error {{
            color: hsl(var(--destructive));
            font-size: 13px;
            margin-top: 4px;
        }}

        .info-row {{
            display: flex;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid hsl(var(--border));
        }}

        .info-row:last-child {{
            border-bottom: none;
        }}

        .info-label {{
            color: hsl(var(--muted-foreground));
            font-size: 14px;
            font-weight: 500;
        }}

        .info-value {{
            color: hsl(var(--foreground));
            text-align: right;
        }}

        @media (max-width: 768px) {{
            .page-header {{
                flex-direction: column;
            }}

            .actions {{
                flex-direction: row;
                width: 100%;
            }}

            .grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <a href="/admin" class="back-link">
            ← Back to Dashboard
        </a>

        <div class="page-header">
            <div class="user-info">
                <div class="user-avatar-large">{user_data['email'][0].upper()}</div>
                <div class="user-details">
                    <h1>{user_data['email']}</h1>
                    <div class="user-meta">
                        <div class="user-meta-item">
                            <span>📅</span>
                            <span>Joined {created_at}</span>
                        </div>
                        <div class="user-meta-item">
                            <span>⏰</span>
                            <span>Last active {last_active}</span>
                        </div>
                    </div>
                </div>
            </div>
            <div class="actions">
                <a href="/dashboard?session_token={user_data['session_token']}" class="action-btn" target="_blank">
                    View Client Dashboard
                </a>
                <button onclick="generatePassword()" class="action-btn" style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); cursor: pointer;">
                    🔐 Generate & Email Password
                </button>
            </div>
        </div>

        <div class="grid">
            <div class="card" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
                <h2 style="color: white;"><span>💰</span> Subscription Status</h2>
                <div class="stat-row" style="border-color: rgba(255,255,255,0.2);">
                    <span class="stat-label" style="color: rgba(255,255,255,0.9);">Status</span>
                    <span class="stat-value" style="color: white;">{'💰 Paying' if subscription_info['is_paying'] else '🆓 Free'}</span>
                </div>
                <div class="stat-row" style="border-color: rgba(255,255,255,0.2);">
                    <span class="stat-label" style="color: rgba(255,255,255,0.9);">Active Subscriptions</span>
                    <span class="stat-value" style="color: white;">{subscription_info['subscription_count']}</span>
                </div>
                <div class="stat-row" style="border-color: rgba(255,255,255,0.2);">
                    <span class="stat-label" style="color: rgba(255,255,255,0.9);">Monthly Revenue</span>
                    <span class="stat-value" style="color: white;">${subscription_info['mrr']}/mo</span>
                </div>
                {f'''<div class="stat-row" style="border-color: rgba(255,255,255,0.2);">
                    <span class="stat-label" style="color: rgba(255,255,255,0.9);">Categories</span>
                    <span class="stat-value" style="color: white;">{", ".join([c.title() for c in subscription_info['categories']])}</span>
                </div>''' if subscription_info['categories'] else ''}
                {f'''<div class="stat-row" style="border-color: rgba(255,255,255,0.2); border-bottom: none;">
                    <span class="stat-label" style="color: rgba(255,255,255,0.9);">Stripe Customer</span>
                    <span class="stat-value" style="color: white;"><a href="https://dashboard.stripe.com/test/customers/{subscription_info['stripe_customer_id']}" target="_blank" style="color: white; text-decoration: underline;">View in Stripe</a></span>
                </div>''' if subscription_info['stripe_customer_id'] else ''}
            </div>

            <div class="card">
                <h2><span>⚙️</span> Manage Subscriptions</h2>
                <p style="color: hsl(var(--muted-foreground)); font-size: 14px; margin-bottom: 16px;">Add or remove tool categories for this user</p>
                <div id="subscription-management" style="display: grid; gap: 12px;">
                    {chr(10).join([f'''
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px; border: 2px solid {'hsl(var(--success))' if cat in active_categories else 'hsl(var(--border))'}; border-radius: 8px; background: {'hsl(var(--success) / 0.05)' if cat in active_categories else 'white'};">
                        <div>
                            <div style="font-weight: 600; margin-bottom: 4px;">{cat.title()}</div>
                            <div style="font-size: 13px; color: hsl(var(--muted-foreground));">{tool_counts.get(cat, 0)} tools • $5/month</div>
                        </div>
                        <button
                            class="{'remove-btn' if cat in active_categories else 'add-btn'}"
                            onclick="toggleSubscription('{user_id}', '{cat}', {str(cat in active_categories).lower()})"
                            style="padding: 8px 16px; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; transition: all 0.2s; background: {'hsl(var(--destructive))' if cat in active_categories else 'hsl(var(--primary))'}; color: white;">
                            {('✗ Remove' if cat in active_categories else '+ Add')}
                        </button>
                    </div>
                    ''' for cat in ['gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison']])}
                </div>
                <div id="subscription-message" style="display: none; margin-top: 16px; padding: 12px; border-radius: 6px;"></div>

                {"".join([f'''<div style="background: #fff3cd; border-left: 3px solid #ffc107; padding: 10px 12px; margin-top: 12px; border-radius: 4px; font-size: 13px;">
                    <div style="display: flex; align-items: center; justify-content: space-between;">
                        <div>
                            <span style="color: #856404;">🔒 <strong>Awaiting payment - Invoice pending:</strong></span>
                            <div style="margin-top: 4px;">
                                {"".join([f'<span style="background: #856404; color: white; padding: 2px 8px; border-radius: 8px; font-size: 11px; font-weight: 600; margin-right: 6px;">{cat.title()}</span>' for cat in invoice['categories']])}
                            </div>
                        </div>
                        <a href="{invoice['invoice_url']}" target="_blank" style="background: #856404; color: white; padding: 6px 12px; border-radius: 4px; font-size: 12px; font-weight: 600; text-decoration: none; white-space: nowrap; margin-left: 12px;">View Invoice</a>
                    </div>
                    <div style="color: #856404; font-size: 11px; margin-top: 6px; opacity: 0.8;">Invoice ID: {invoice['invoice_id']}</div>
                </div>''' for invoice in subscription_info.get('pending_invoices', [])])}
            </div>

            <div class="card">
                <h2><span>📊</span> Usage Statistics (30 Days)</h2>
                <div class="stat-row">
                    <span class="stat-label">Total Requests</span>
                    <span class="stat-value">{usage_stats['total_requests']}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Successful Requests</span>
                    <span class="stat-value">{usage_stats['successes']}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Failed Requests</span>
                    <span class="stat-value">{usage_stats['failures']}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Success Rate</span>
                    <span class="stat-value">{usage_stats['success_rate']}%</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Avg Response Time</span>
                    <span class="stat-value">{usage_stats['avg_response_time_ms']}ms</span>
                </div>
            </div>

            <div class="card">
                <h2><span>🔑</span> API Keys</h2>
                <div style="margin-top: 12px;">
                    {api_keys_badges if api_keys_badges else '<span class="badge badge-muted">No API keys configured</span>'}
                </div>
            </div>

            <div class="card">
                <h2><span>🛠️</span> Active Tool Categories</h2>
                <p style="color: hsl(var(--muted-foreground)); font-size: 14px; margin-bottom: 16px;">Categories with active subscriptions (personal or team)</p>
                <div class="stat-row">
                    <span class="stat-label">Status</span>
                    <span class="stat-value">{tool_status}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Available Tools</span>
                    <span class="stat-value">{total_tools} / 85</span>
                </div>
                <div style="margin-top: 16px;">
                    {tool_categories_html}
                </div>
            </div>

            <div class="card">
                <h2><span>👥</span> Team Access</h2>
                <p style="color: hsl(var(--muted-foreground)); font-size: 14px; margin-bottom: 16px;">Allow this user to create teams and share subscriptions with team members</p>
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 16px; border: 2px solid hsl(var(--border)); border-radius: 8px; background: {'hsl(var(--success) / 0.05)' if user_data.get('teams_enabled', False) else 'white'};">
                    <div>
                        <div style="font-weight: 600; margin-bottom: 4px;">Teams Feature</div>
                        <div style="font-size: 13px; color: hsl(var(--muted-foreground));">{'Enabled - User can create and manage teams' if user_data.get('teams_enabled', False) else 'Disabled - User cannot access teams'}</div>
                    </div>
                    <button
                        onclick="toggleTeamAccess('{user_id}', {str(user_data.get('teams_enabled', False)).lower()})"
                        style="padding: 10px 20px; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; transition: all 0.2s; background: {'hsl(var(--destructive))' if user_data.get('teams_enabled', False) else 'hsl(var(--success))'}; color: white;">
                        {'✗ Disable' if user_data.get('teams_enabled', False) else '✓ Enable'}
                    </button>
                </div>
                <div id="team-access-message" style="display: none; margin-top: 16px; padding: 12px; border-radius: 6px;"></div>
            </div>

            {f'''
            <div class="card" style="grid-column: 1 / -1;">
                <h2><span>👥</span> Team Memberships & Subscriptions</h2>
                <p style="color: hsl(var(--muted-foreground)); font-size: 14px; margin-bottom: 20px;">
                    Teams this user belongs to and their current subscriptions. Grant free subscriptions by clicking the + buttons.
                </p>

                <div style="display: flex; flex-direction: column; gap: 20px;">
                    {"".join([f"""
                    <div style="border: 2px solid hsl(var(--border)); border-radius: 12px; padding: 20px; background: white;">
                        <!-- Team Header -->
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                            <div>
                                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 8px;">
                                    <span style="font-size: 20px; font-weight: 700;">{team['team_name']}</span>
                                    <span class="badge badge-{'success' if team['role'] == 'owner' else 'muted'}">{team['role'].title()}</span>
                                    <span class="badge badge-muted">{team['member_count']} members</span>
                                </div>
                                <div style="font-size: 13px; color: hsl(var(--muted-foreground));">Team ID: {team['team_id'][:16]}...</div>
                            </div>
                        </div>

                        <!-- Current Subscriptions -->
                        <div style="margin-bottom: 16px;">
                            <div style="font-size: 13px; font-weight: 600; margin-bottom: 8px; color: hsl(var(--muted-foreground));">Current Team Subscriptions:</div>
                            <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                                {"".join([f'<span class="badge badge-success">{category_info[cat]["emoji"]} {cat.title()}</span>' for cat in team['active_categories']]) if team['active_categories'] else '<span class="badge badge-muted">No subscriptions</span>'}
                            </div>
                        </div>

                        <!-- Grant Buttons -->
                        <div style="border-top: 1px solid hsl(var(--border)); padding-top: 16px;">
                            <div style="font-size: 13px; font-weight: 600; margin-bottom: 12px; color: hsl(var(--muted-foreground));">Grant Additional Categories:</div>
                            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px;">
                                {"".join([f"""<button
                                    onclick="grantTeamSubscription('{team['team_id']}', '{cat}')"
                                    style="padding: 10px 14px; border: {'2px solid hsl(var(--border))' if cat in team['active_categories'] else '2px solid hsl(var(--primary))'}; border-radius: 8px; font-weight: 600; cursor: {'not-allowed' if cat in team['active_categories'] else 'pointer'}; transition: all 0.2s; background: {'hsl(var(--muted))' if cat in team['active_categories'] else 'white'}; color: {'hsl(var(--muted-foreground))' if cat in team['active_categories'] else 'hsl(var(--primary))'}; font-size: 13px; display: flex; align-items: center; justify-content: center; gap: 6px;"
                                    {'disabled' if cat in team['active_categories'] else ''}>
                                    <span style="font-size: 16px;">{category_info[cat]["emoji"]}</span>
                                    <span>{'✓' if cat in team['active_categories'] else '+'} {cat.title()}</span>
                                </button>""" for cat in ['gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison']])}
                            </div>
                        </div>
                    </div>
                    """ for team in user_teams])}
                </div>

                <div id="team-grant-message" style="display: none; margin-top: 16px; padding: 12px; border-radius: 6px;"></div>
            </div>
            ''' if user_teams else ''}

            <div class="card">
                <h2><span>ℹ️</span> Account Info</h2>
                <div class="info-row">
                    <span class="info-label">User ID</span>
                    <span class="info-value"><code style="font-size: 12px;">{user_data['user_id']}</code></span>
                </div>
                <div class="info-row">
                    <span class="info-label">Session Expires</span>
                    <span class="info-value">{session_expiry}</span>
                </div>
            </div>

            <div class="card" style="border: 2px solid hsl(var(--destructive)); background: hsl(var(--destructive) / 0.02);">
                <h2><span>⚠️</span> Danger Zone</h2>
                <p style="color: hsl(var(--muted-foreground)); font-size: 14px; margin-bottom: 16px;">
                    Permanent actions that cannot be undone. Use with extreme caution.
                </p>
                <div style="border: 2px solid hsl(var(--destructive)); border-radius: 8px; padding: 16px; background: white;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <div style="font-weight: 600; margin-bottom: 4px; color: hsl(var(--destructive));">Delete User Account</div>
                            <div style="font-size: 13px; color: hsl(var(--muted-foreground));">
                                Permanently delete this user, all their data, subscriptions, teams, and usage logs. This action cannot be undone.
                            </div>
                        </div>
                        <button
                            onclick="deleteUser('{user_id}')"
                            style="padding: 10px 20px; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; transition: all 0.2s; background: hsl(var(--destructive)); color: white; white-space: nowrap; margin-left: 20px;">
                            🗑️ Delete User
                        </button>
                    </div>
                </div>
                <div id="delete-message" style="display: none; margin-top: 16px; padding: 12px; border-radius: 6px;"></div>
            </div>
        </div>

        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                <h2 style="margin: 0;"><span>📊</span> Diagnostics & Recent Activity</h2>
                <div style="display: flex; gap: 12px; align-items: center;">
                    <span id="live-status" style="display: none; color: hsl(var(--success)); font-size: 14px; font-weight: 600;">🟢 LIVE</span>
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 14px;">
                        <input type="checkbox" id="live-toggle" onchange="toggleLiveUpdates()" style="cursor: pointer;">
                        Live Updates
                    </label>
                    <button onclick="refreshActivity()" style="padding: 6px 12px; border: 2px solid hsl(var(--border)); background: white; border-radius: 6px; cursor: pointer; font-size: 14px;">
                        🔄 Refresh
                    </button>
                </div>
            </div>

            <!-- Summary Stats -->
            <div id="activity-summary" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 20px; padding: 16px; background: hsl(var(--muted) / 0.3); border-radius: 8px;">
                <div>
                    <div style="font-size: 13px; color: hsl(var(--muted-foreground)); margin-bottom: 4px;">Total Requests</div>
                    <div id="total-requests" style="font-size: 24px; font-weight: 700;">--</div>
                </div>
                <div>
                    <div style="font-size: 13px; color: hsl(var(--muted-foreground)); margin-bottom: 4px;">Success Rate</div>
                    <div id="success-rate" style="font-size: 24px; font-weight: 700; color: hsl(var(--success));">--</div>
                </div>
                <div>
                    <div style="font-size: 13px; color: hsl(var(--muted-foreground)); margin-bottom: 4px;">Failed</div>
                    <div id="error-count" style="font-size: 24px; font-weight: 700; color: hsl(var(--destructive));">--</div>
                </div>
                <div>
                    <div style="font-size: 13px; color: hsl(var(--muted-foreground)); margin-bottom: 4px;">Last Updated</div>
                    <div id="last-updated" style="font-size: 14px; font-weight: 600;">--</div>
                </div>
            </div>

            <!-- Error Summary (only shown if errors exist) -->
            <div id="error-summary-section" style="display: none; padding: 12px; background: hsl(var(--destructive) / 0.05); border: 1px solid hsl(var(--destructive) / 0.3); border-radius: 6px; margin-bottom: 16px;">
                <div style="font-weight: 600; color: hsl(var(--destructive)); margin-bottom: 8px;">⚠️ Recent Errors:</div>
                <div id="error-summary-content"></div>
            </div>

            <!-- Activity Timeline -->
            <div style="max-height: 600px; overflow-y: auto; border: 1px solid hsl(var(--border)); border-radius: 8px; padding: 16px;">
                <div id="activity-timeline" class="timeline">
                    {activity_timeline if activity_timeline else '<p style="color: hsl(var(--muted-foreground)); text-align: center; padding: 20px;">No recent activity</p>'}
                </div>
            </div>
        </div>
    </div>

    <script>
        // Store active categories for modal
        const activeCategories = {active_categories};
        const allCategories = ['gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison'];

        async function toggleSubscription(userId, category, isCurrentlyActive) {{
            const messageDiv = document.getElementById('subscription-message');
            const action = isCurrentlyActive ? 'remove' : 'add';

            // If adding, show multi-select modal
            if (action === 'add') {{
                showMultiSelectModal(userId, category);
                return;
            }}

            // Removing - just confirm and proceed
            if (!confirm(`Remove ${{category}} subscription? This will cancel billing and revoke access immediately.`)) {{
                return;
            }}

            try {{
                const response = await fetch(`/admin/user/${{userId}}/subscription?admin_password={os.getenv("ADMIN_PASSWORD")}`, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        action: action,
                        category: category
                    }})
                }});

                const result = await response.json();

                if (response.ok) {{
                    messageDiv.textContent = `✓ Removed ${{category}} subscription successfully!`;
                    messageDiv.style.display = 'block';
                    messageDiv.style.background = 'hsl(var(--success) / 0.1)';
                    messageDiv.style.color = 'hsl(var(--success))';

                    setTimeout(() => {{
                        window.location.reload();
                    }}, 1000);
                }} else {{
                    messageDiv.textContent = `✗ Error: ${{result.detail || result.message}}`;
                    messageDiv.style.display = 'block';
                    messageDiv.style.background = 'hsl(var(--destructive) / 0.1)';
                    messageDiv.style.color = 'hsl(var(--destructive))';
                }}
            }} catch (error) {{
                messageDiv.textContent = `✗ Error: ${{error.message}}`;
                messageDiv.style.display = 'block';
                messageDiv.style.background = 'hsl(var(--destructive) / 0.1)';
                messageDiv.style.color = 'hsl(var(--destructive))';
            }}
        }}

        function showMultiSelectModal(userId, initialCategory) {{
            const modal = document.createElement('div');
            modal.id = 'subscription-modal';
            modal.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000;';

            // Get unsubscribed categories
            const unsubscribedCategories = allCategories.filter(cat => !activeCategories.includes(cat));

            // Build checkboxes HTML
            const categoryCheckboxes = unsubscribedCategories.map(cat => `
                <label style="display: flex; align-items: center; padding: 12px; border: 2px solid hsl(var(--border)); border-radius: 8px; cursor: pointer; margin-bottom: 8px; transition: all 0.2s;" class="category-checkbox">
                    <input type="checkbox" name="categories" value="${{cat}}" ${{cat === initialCategory ? 'checked' : ''}} onchange="updateTotal()" style="margin-right: 12px; width: 18px; height: 18px;">
                    <div style="flex: 1;">
                        <div style="font-weight: 600;">${{cat.charAt(0).toUpperCase() + cat.slice(1)}}</div>
                        <div style="font-size: 13px; color: hsl(var(--muted-foreground));">$5/month</div>
                    </div>
                </label>
            `).join('');

            modal.innerHTML = `
                <div style="background: white; padding: 30px; border-radius: 12px; max-width: 600px; width: 90%; max-height: 90vh; overflow-y: auto;">
                    <h2 style="margin: 0 0 10px 0;">Add Subscriptions</h2>
                    <p style="color: hsl(var(--muted-foreground)); margin: 0 0 20px 0; font-size: 14px;">Select one or more tool categories to add</p>

                    <div style="margin-bottom: 20px;">
                        <h3 style="font-size: 15px; font-weight: 600; margin-bottom: 12px;">Select Categories:</h3>
                        <div id="category-checkboxes">
                            ${{categoryCheckboxes}}
                        </div>
                    </div>

                    <div style="margin-bottom: 20px;">
                        <h3 style="font-size: 15px; font-weight: 600; margin-bottom: 12px;">Billing Type:</h3>
                        <label style="display: flex; align-items: center; padding: 15px; border: 2px solid hsl(var(--border)); border-radius: 8px; cursor: pointer; margin-bottom: 12px;">
                            <input type="radio" name="subscription-type" value="paid" checked style="margin-right: 12px; width: 18px; height: 18px;">
                            <div>
                                <div style="font-weight: 600; margin-bottom: 4px;">💳 Paid Subscription</div>
                                <div style="font-size: 13px; color: hsl(var(--muted-foreground));">Single invoice for all selected categories</div>
                            </div>
                        </label>

                        <label style="display: flex; align-items: center; padding: 15px; border: 2px solid hsl(var(--border)); border-radius: 8px; cursor: pointer;">
                            <input type="radio" name="subscription-type" value="free" style="margin-right: 12px; width: 18px; height: 18px;">
                            <div>
                                <div style="font-weight: 600; margin-bottom: 4px;">🎁 Free Subscription (No Billing)</div>
                                <div style="font-size: 13px; color: hsl(var(--muted-foreground));">Complimentary access - no invoices</div>
                            </div>
                        </label>
                    </div>

                    <div style="background: hsl(var(--muted) / 0.2); padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div style="font-weight: 600; font-size: 16px;">Total:</div>
                            <div id="total-price" style="font-weight: 700; font-size: 20px; color: hsl(var(--primary));">$0/month</div>
                        </div>
                        <div id="invoice-note" style="font-size: 13px; color: hsl(var(--muted-foreground)); margin-top: 8px;">One invoice will be sent for all selected categories</div>
                    </div>

                    <div style="display: flex; gap: 12px; justify-content: flex-end;">
                        <button onclick="closeSubscriptionModal()" style="padding: 10px 20px; border: 2px solid hsl(var(--border)); background: white; border-radius: 6px; cursor: pointer; font-weight: 600;">Cancel</button>
                        <button id="confirm-button" onclick="confirmAddMultipleSubscriptions('${{userId}}')" disabled style="padding: 10px 20px; border: none; background: hsl(var(--muted)); color: white; border-radius: 6px; cursor: not-allowed; font-weight: 600;">Add Subscriptions</button>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);
            modal.onclick = (e) => {{ if (e.target === modal) closeSubscriptionModal(); }};

            // Add checkbox styling on select
            document.querySelectorAll('.category-checkbox').forEach(label => {{
                const checkbox = label.querySelector('input[type="checkbox"]');
                checkbox.addEventListener('change', () => {{
                    if (checkbox.checked) {{
                        label.style.borderColor = 'hsl(var(--primary))';
                        label.style.background = 'hsl(var(--primary) / 0.05)';
                    }} else {{
                        label.style.borderColor = 'hsl(var(--border))';
                        label.style.background = 'white';
                    }}
                }});
                // Trigger initial state
                if (checkbox.checked) {{
                    label.style.borderColor = 'hsl(var(--primary))';
                    label.style.background = 'hsl(var(--primary) / 0.05)';
                }}
            }});

            updateTotal();
        }}

        function updateTotal() {{
            const checkboxes = document.querySelectorAll('input[name="categories"]:checked');
            const count = checkboxes.length;
            const total = count * 5;
            const isFree = document.querySelector('input[name="subscription-type"]:checked')?.value === 'free';

            document.getElementById('total-price').textContent = isFree ? '$0 (Free)' : `$$${{total}}/month`;
            document.getElementById('invoice-note').textContent = isFree
                ? 'No invoice - complimentary access'
                : count > 1
                    ? `One invoice will be sent for all ${{count}} categories`
                    : 'Invoice will be sent for this category';

            const confirmButton = document.getElementById('confirm-button');
            if (count > 0) {{
                confirmButton.disabled = false;
                confirmButton.style.background = 'hsl(var(--primary))';
                confirmButton.style.cursor = 'pointer';
            }} else {{
                confirmButton.disabled = true;
                confirmButton.style.background = 'hsl(var(--muted))';
                confirmButton.style.cursor = 'not-allowed';
            }}

            // Update billing type radios to trigger total update
            document.querySelectorAll('input[name="subscription-type"]').forEach(radio => {{
                radio.onchange = updateTotal;
            }});
        }}

        function closeSubscriptionModal() {{
            const modal = document.getElementById('subscription-modal');
            if (modal) modal.remove();
        }}

        async function confirmAddMultipleSubscriptions(userId) {{
            const selectedCheckboxes = document.querySelectorAll('input[name="categories"]:checked');
            const categories = Array.from(selectedCheckboxes).map(cb => cb.value);
            const isFree = document.querySelector('input[name="subscription-type"]:checked').value === 'free';
            const messageDiv = document.getElementById('subscription-message');

            if (categories.length === 0) {{
                alert('Please select at least one category');
                return;
            }}

            closeSubscriptionModal();

            messageDiv.textContent = `⏳ Adding ${{categories.length}} subscription${{categories.length > 1 ? 's' : ''}}...`;
            messageDiv.style.display = 'block';
            messageDiv.style.background = 'hsl(var(--muted) / 0.1)';
            messageDiv.style.color = 'hsl(var(--muted-foreground))';

            try {{
                const response = await fetch(`/admin/user/${{userId}}/subscriptions/batch?admin_password={os.getenv("ADMIN_PASSWORD")}`, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        categories: categories,
                        free: isFree
                    }})
                }});

                const result = await response.json();

                if (response.ok) {{
                    if (result.invoice_link) {{
                        // Show invoice link with copy button
                        messageDiv.innerHTML = `
                            <div style="margin-bottom: 12px;">✓ Added ${{categories.length}} subscription${{categories.length > 1 ? 's' : ''}} successfully!</div>
                            <div style="background: #fff3cd; border: 1px solid #ffc107; padding: 12px; border-radius: 6px; margin: 12px 0; color: #856404;">
                                <div style="font-weight: 600; margin-bottom: 4px;">⚠️ Tools are LOCKED until payment</div>
                                <div style="font-size: 13px;">User must pay the invoice before they can access these tools.</div>
                            </div>
                            <div style="background: hsl(var(--muted) / 0.3); padding: 12px; border-radius: 6px; margin-top: 8px;">
                                <div style="font-weight: 600; margin-bottom: 8px; font-size: 13px;">📧 Invoice Link ($$${{categories.length * 5}}/month):</div>
                                <div style="display: flex; gap: 8px; align-items: center;">
                                    <input type="text" value="${{result.invoice_link}}" readonly style="flex: 1; padding: 8px; border: 1px solid hsl(var(--border)); border-radius: 4px; font-size: 12px; font-family: monospace;">
                                    <button onclick="copyInvoiceLink('${{result.invoice_link}}')" style="padding: 8px 16px; background: hsl(var(--primary)); color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; white-space: nowrap;">📋 Copy</button>
                                </div>
                                <div style="font-size: 12px; color: hsl(var(--muted-foreground)); margin-top: 8px;">Share this link with the user to pay their invoice (30 days to pay)</div>
                            </div>
                        `;
                        messageDiv.style.background = 'hsl(var(--success) / 0.1)';
                        messageDiv.style.color = 'hsl(var(--success))';
                    }} else {{
                        messageDiv.textContent = `✓ Added ${{categories.length}} subscription${{categories.length > 1 ? 's' : ''}} successfully!${{isFree ? ' (Free - no billing)' : ''}}`;
                        messageDiv.style.background = 'hsl(var(--success) / 0.1)';
                        messageDiv.style.color = 'hsl(var(--success))';
                    }}

                    setTimeout(() => {{
                        window.location.reload();
                    }}, 4000);
                }} else {{
                    messageDiv.textContent = `✗ Error: ${{result.detail || result.message}}`;
                    messageDiv.style.background = 'hsl(var(--destructive) / 0.1)';
                    messageDiv.style.color = 'hsl(var(--destructive))';
                }}
            }} catch (error) {{
                messageDiv.textContent = `✗ Error: ${{error.message}}`;
                messageDiv.style.background = 'hsl(var(--destructive) / 0.1)';
                messageDiv.style.color = 'hsl(var(--destructive))';
            }}
        }}

        function copyInvoiceLink(link) {{
            navigator.clipboard.writeText(link).then(() => {{
                const button = event.target;
                const originalText = button.textContent;
                button.textContent = '✓ Copied!';
                button.style.background = 'hsl(var(--success))';
                setTimeout(() => {{
                    button.textContent = originalText;
                    button.style.background = 'hsl(var(--primary))';
                }}, 2000);
            }});
        }}

        async function generatePassword() {{
            if (!confirm('Generate a new password for this user and email it to them?')) {{
                return;
            }}

            const button = event.target;
            button.disabled = true;
            button.textContent = '⏳ Generating...';

            try {{
                const response = await fetch(`/admin/user/{user_id}/generate-password?admin_password={os.getenv("ADMIN_PASSWORD")}`, {{
                    method: 'POST'
                }});

                const result = await response.json();

                if (response.ok) {{
                    alert(`✓ Success!\\n\\nPassword generated and emailed to {user_data['email']}\\n\\nPassword: ${{result.password}}\\n\\n(Save this - the user will also receive it via email)`);
                    button.textContent = '✓ Password Sent!';
                    button.style.background = 'linear-gradient(135deg, #4caf50 0%, #45a049 100%)';
                }} else {{
                    alert(`✗ Error: ${{result.detail || result.message}}`);
                    button.disabled = false;
                    button.textContent = '🔐 Generate & Email Password';
                }}
            }} catch (error) {{
                alert(`✗ Error: ${{error.message}}`);
                button.disabled = false;
                button.textContent = '🔐 Generate & Email Password';
            }}
        }}

        async function toggleTeamAccess(userId, currentlyEnabled) {{
            const action = currentlyEnabled ? 'disable' : 'enable';
            const confirmMessage = currentlyEnabled
                ? 'Disable team access for this user? They will lose ability to create and manage teams.'
                : 'Enable team access for this user? They will be able to create teams and share subscriptions.';

            if (!confirm(confirmMessage)) {{
                return;
            }}

            const messageDiv = document.getElementById('team-access-message');

            try {{
                const response = await fetch(`/admin/user/${{userId}}/toggle-teams?admin_password={os.getenv("ADMIN_PASSWORD")}`, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ enabled: !currentlyEnabled }})
                }});

                const result = await response.json();

                if (response.ok) {{
                    messageDiv.textContent = `✓ Team access ${{action}}d successfully!`;
                    messageDiv.style.display = 'block';
                    messageDiv.style.background = 'hsl(var(--success) / 0.1)';
                    messageDiv.style.color = 'hsl(var(--success))';

                    setTimeout(() => {{
                        window.location.reload();
                    }}, 1000);
                }} else {{
                    messageDiv.textContent = `✗ Error: ${{result.detail || result.message}}`;
                    messageDiv.style.display = 'block';
                    messageDiv.style.background = 'hsl(var(--destructive) / 0.1)';
                    messageDiv.style.color = 'hsl(var(--destructive))';
                }}
            }} catch (error) {{
                messageDiv.textContent = `✗ Error: ${{error.message}}`;
                messageDiv.style.display = 'block';
                messageDiv.style.background = 'hsl(var(--destructive) / 0.1)';
                messageDiv.style.color = 'hsl(var(--destructive))';
            }}
        }}

        async function grantTeamSubscription(teamId, category) {{
            const messageDiv = document.getElementById('team-grant-message');

            // Confirm action
            if (!confirm(`Grant ${{category}} subscription to this team for free?`)) {{
                return;
            }}

            try {{
                const response = await fetch(`/admin/grant-team?session_token={user_data['session_token']}&admin_password={os.getenv("ADMIN_PASSWORD")}`, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        team_id: teamId,
                        category: category
                    }})
                }});

                const result = await response.json();

                if (response.ok) {{
                    messageDiv.textContent = `✓ Granted ${{category}} to team successfully!`;
                    messageDiv.style.display = 'block';
                    messageDiv.style.background = 'hsl(var(--success) / 0.1)';
                    messageDiv.style.color = 'hsl(var(--success))';

                    setTimeout(() => {{
                        window.location.reload();
                    }}, 1000);
                }} else {{
                    messageDiv.textContent = `✗ Error: ${{result.detail || result.message}}`;
                    messageDiv.style.display = 'block';
                    messageDiv.style.background = 'hsl(var(--destructive) / 0.1)';
                    messageDiv.style.color = 'hsl(var(--destructive))';
                }}
            }} catch (e) {{
                messageDiv.textContent = `✗ Network error: ${{e.message}}`;
                messageDiv.style.display = 'block';
                messageDiv.style.background = 'hsl(var(--destructive) / 0.1)';
                messageDiv.style.color = 'hsl(var(--destructive))';
            }}
        }}

        async function deleteUser(userId) {{
            const messageDiv = document.getElementById('delete-message');

            // Double confirmation for safety
            const userEmail = '{user_data['email']}';
            const firstConfirm = confirm(
                `⚠️ DANGER: Delete user ${{userEmail}}?\\n\\n` +
                `This will PERMANENTLY delete:\\n` +
                `- User account\\n` +
                `- All subscriptions (and cancel in Stripe)\\n` +
                `- All usage logs\\n` +
                `- All team memberships\\n` +
                `- All teams owned by this user\\n\\n` +
                `This action CANNOT be undone!\\n\\n` +
                `Click OK to continue to final confirmation.`
            );

            if (!firstConfirm) {{
                return;
            }}

            // Second confirmation - type email to confirm
            const typedEmail = prompt(
                `⚠️ FINAL CONFIRMATION\\n\\n` +
                `Type the user's email address to confirm deletion:\\n` +
                `${{userEmail}}`
            );

            if (typedEmail !== userEmail) {{
                messageDiv.textContent = '✗ Email does not match. Deletion cancelled.';
                messageDiv.style.display = 'block';
                messageDiv.style.background = 'hsl(var(--muted) / 0.1)';
                messageDiv.style.color = 'hsl(var(--muted-foreground))';
                return;
            }}

            // Show loading state
            messageDiv.textContent = '⏳ Deleting user... This may take a moment.';
            messageDiv.style.display = 'block';
            messageDiv.style.background = 'hsl(var(--muted) / 0.1)';
            messageDiv.style.color = 'hsl(var(--muted-foreground))';

            try {{
                const response = await fetch(`/admin/user/${{userId}}?admin_password={os.getenv("ADMIN_PASSWORD")}`, {{
                    method: 'DELETE'
                }});

                const result = await response.json();

                if (response.ok) {{
                    messageDiv.textContent = `✓ User deleted successfully! Redirecting to admin dashboard...`;
                    messageDiv.style.display = 'block';
                    messageDiv.style.background = 'hsl(var(--success) / 0.1)';
                    messageDiv.style.color = 'hsl(var(--success))';

                    // Redirect to admin dashboard after 2 seconds
                    setTimeout(() => {{
                        window.location.href = '/admin?admin_password={os.getenv("ADMIN_PASSWORD")}';
                    }}, 2000);
                }} else {{
                    messageDiv.textContent = `✗ Error: ${{result.detail || result.message}}`;
                    messageDiv.style.display = 'block';
                    messageDiv.style.background = 'hsl(var(--destructive) / 0.1)';
                    messageDiv.style.color = 'hsl(var(--destructive))';
                }}
            }} catch (e) {{
                messageDiv.textContent = `✗ Network error: ${{e.message}}`;
                messageDiv.style.display = 'block';
                messageDiv.style.background = 'hsl(var(--destructive) / 0.1)';
                messageDiv.style.color = 'hsl(var(--destructive))';
            }}
        }}

        // === Real-Time Activity Monitoring ===
        let liveUpdateInterval = null;
        const userId = '{user_id}';
        const adminPassword = '{os.getenv("ADMIN_PASSWORD")}';

        function toggleRawData(index) {{
            const rawDataDiv = document.getElementById(`raw-data-${{index}}`);
            const icon = document.getElementById(`toggle-icon-${{index}}`);

            if (rawDataDiv.style.display === 'none') {{
                rawDataDiv.style.display = 'block';
                icon.textContent = '▲';
            }} else {{
                rawDataDiv.style.display = 'none';
                icon.textContent = '▼';
            }}
        }}

        async function refreshActivity() {{
            console.log('[DIAGNOSTICS] Refreshing activity data...');
            console.log('[DIAGNOSTICS] User ID:', userId);
            console.log('[DIAGNOSTICS] Admin password set:', !!adminPassword);

            try {{
                const url = `/admin/user/${{userId}}/activity?admin_password=${{adminPassword}}&limit=50`;
                console.log('[DIAGNOSTICS] Fetching:', url);

                const response = await fetch(url);
                console.log('[DIAGNOSTICS] Response status:', response.status, response.statusText);

                if (!response.ok) {{
                    const errorText = await response.text();
                    console.error('[DIAGNOSTICS] Fetch failed:', errorText);
                    document.getElementById('total-requests').textContent = 'ERROR';
                    document.getElementById('success-rate').textContent = 'ERROR';
                    document.getElementById('error-count').textContent = 'ERROR';
                    document.getElementById('last-updated').textContent = response.status + ' ' + response.statusText;
                    return;
                }}

                const data = await response.json();
                console.log('[DIAGNOSTICS] Data received:', data);
                console.log('[DIAGNOSTICS] Total logs:', data.total_logs);
                console.log('[DIAGNOSTICS] Success count:', data.success_count);
                console.log('[DIAGNOSTICS] Error count:', data.error_count);

                // Update summary stats
                document.getElementById('total-requests').textContent = data.total_logs;
                const successRate = data.total_logs > 0
                    ? Math.round((data.success_count / data.total_logs) * 100)
                    : 0;
                document.getElementById('success-rate').textContent = `${{successRate}}%`;
                document.getElementById('error-count').textContent = data.error_count;

                // Update timestamp
                const now = new Date();
                document.getElementById('last-updated').textContent = now.toLocaleTimeString();

                // Update error summary
                if (data.error_count > 0 && Object.keys(data.error_summary).length > 0) {{
                    const errorSection = document.getElementById('error-summary-section');
                    const errorContent = document.getElementById('error-summary-content');

                    let errorHTML = '<div style="display: flex; flex-wrap: wrap; gap: 8px;">';
                    for (const [tool, count] of Object.entries(data.error_summary)) {{
                        errorHTML += `<span style="padding: 4px 8px; background: hsl(var(--destructive) / 0.1); border-radius: 4px; font-size: 13px;"><code>${{tool}}</code>: ${{count}}× failed</span>`;
                    }}
                    errorHTML += '</div>';

                    errorContent.innerHTML = errorHTML;
                    errorSection.style.display = 'block';
                }} else {{
                    document.getElementById('error-summary-section').style.display = 'none';
                }}

                // Update activity timeline
                const timeline = document.getElementById('activity-timeline');
                if (data.logs.length === 0) {{
                    timeline.innerHTML = '<p style="color: hsl(var(--muted-foreground)); text-align: center; padding: 20px;">No recent activity</p>';
                    return;
                }}

                let timelineHTML = '';
                data.logs.forEach((log, index) => {{
                    const timestamp = new Date(log.timestamp);
                    const timeStr = timestamp.toLocaleString('en-US', {{
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit'
                    }});

                    const statusClass = log.success ? 'success' : 'destructive';
                    const statusIcon = log.success ? '✓' : '✗';
                    const durationStr = log.duration_ms ? ` (${{log.duration_ms}}ms)` : '';

                    // Format raw request params as JSON
                    const rawParams = JSON.stringify(log.request_params || {{}}, null, 2);
                    const rawResponse = log.response_data ? JSON.stringify(log.response_data, null, 2) : 'No response data';
                    const hasParams = log.request_params && Object.keys(log.request_params).length > 0;

                    timelineHTML += `
                        <div class="timeline-item" style="border: 2px solid ${{log.success ? 'hsl(var(--border))' : 'hsl(var(--destructive))'}};  padding: 12px; border-radius: 8px; margin-bottom: 8px; background: white;">
                            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 8px;">
                                <div>
                                    <div style="font-weight: 700; font-size: 15px; margin-bottom: 4px;">
                                        <code style="color: ${{log.success ? 'hsl(var(--foreground))' : 'hsl(var(--destructive))'}}">${{log.tool_name}}</code>
                                        <span class="badge badge-${{statusClass}}" style="margin-left: 8px;">${{statusIcon}}</span>
                                    </div>
                                    <div style="font-size: 13px; color: hsl(var(--muted-foreground));">${{timeStr}}${{durationStr}}</div>
                                </div>
                                <button onclick="toggleRawData(${{index}})" style="padding: 4px 10px; border: 1px solid hsl(var(--border)); background: white; border-radius: 4px; cursor: pointer; font-size: 12px;">
                                    <span id="toggle-icon-${{index}}">▼</span> RAW
                                </button>
                            </div>

                            ${{log.error_message ? `<div style="padding: 8px; background: hsl(var(--destructive) / 0.1); border-left: 3px solid hsl(var(--destructive)); border-radius: 4px; margin-bottom: 8px; font-size: 13px;"><strong>Error:</strong> ${{log.error_message}}</div>` : ''}}

                            ${{log.error_type ? `<div style="font-size: 12px; color: hsl(var(--muted-foreground)); margin-bottom: 4px;"><strong>Error Type:</strong> ${{log.error_type}}</div>` : ''}}

                            <!-- RAW DATA (expandable) -->
                            <div id="raw-data-${{index}}" style="display: none; margin-top: 12px; padding: 12px; background: #f5f5f5; border-radius: 6px; font-family: monospace; font-size: 12px;">
                                <div style="margin-bottom: 12px;">
                                    <strong style="color: hsl(var(--primary));">📥 REQUEST PARAMS:</strong>
                                    <pre style="margin: 4px 0 0 0; padding: 8px; background: white; border-radius: 4px; overflow-x: auto;">${{rawParams}}</pre>
                                </div>

                                ${{log.response_data ? `
                                <div style="margin-bottom: 12px;">
                                    <strong style="color: hsl(var(--primary));">📤 RESPONSE DATA:</strong>
                                    <pre style="margin: 4px 0 0 0; padding: 8px; background: white; border-radius: 4px; overflow-x: auto; max-height: 300px;">${{rawResponse}}</pre>
                                </div>
                                ` : ''}}

                                ${{log.stack_trace ? `
                                <div>
                                    <strong style="color: hsl(var(--destructive));">📍 STACK TRACE:</strong>
                                    <pre style="margin: 4px 0 0 0; padding: 8px; background: white; border-radius: 4px; overflow-x: auto; color: hsl(var(--destructive)); max-height: 200px;">${{log.stack_trace}}</pre>
                                </div>
                                ` : ''}}
                            </div>
                        </div>
                    `;
                }});

                timeline.innerHTML = timelineHTML;

            }} catch (error) {{
                console.error('Error refreshing activity:', error);
            }}
        }}

        function toggleLiveUpdates() {{
            const toggle = document.getElementById('live-toggle');
            const liveStatus = document.getElementById('live-status');

            if (toggle.checked) {{
                // Start live updates
                liveStatus.style.display = 'inline';
                refreshActivity(); // Immediate refresh
                liveUpdateInterval = setInterval(refreshActivity, 3000); // Every 3 seconds
                console.log('Live updates enabled');
            }} else {{
                // Stop live updates
                liveStatus.style.display = 'none';
                if (liveUpdateInterval) {{
                    clearInterval(liveUpdateInterval);
                    liveUpdateInterval = null;
                }}
                console.log('Live updates disabled');
            }}
        }}

        // Initial load of activity data
        window.addEventListener('DOMContentLoaded', () => {{
            refreshActivity();
        }});

        // Cleanup on page unload
        window.addEventListener('beforeunload', () => {{
            if (liveUpdateInterval) {{
                clearInterval(liveUpdateInterval);
            }}
        }});
    </script>
</body>
</html>
        """)

    except Exception as e:
        logger.error(f"Error in user detail page: {e}")
        import traceback
        traceback.print_exc()
        return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>Error</title>
</head>
<body>
    <h1>Error loading user details</h1>
    <p>{str(e)}</p>
</body>
</html>
        """, status_code=500)


@app.post("/admin/user/{user_id}/subscriptions/batch")
async def admin_add_batch_subscriptions(
    request: Request,
    user_id: str,
    admin_password: Optional[str] = Query(None)
):
    """
    Admin endpoint to add multiple subscriptions at once with a single invoice.

    Body: {
        "categories": ["gmail", "calendar", "docs"],
        "free": true/false (optional, default false)
    }
    """
    # Check admin authentication
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not correct_password or not authenticated:
        raise HTTPException(401, "Unauthorized")

    try:
        # Parse request body
        body = await request.json()
        categories = body.get('categories', [])
        is_free = body.get('free', False)

        if not categories or not isinstance(categories, list):
            raise HTTPException(400, "Invalid or empty categories list")

        valid_categories = ['gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison']
        for cat in categories:
            if cat not in valid_categories:
                raise HTTPException(400, f"Invalid category '{cat}'. Must be one of: {', '.join(valid_categories)}")

        # Get user data
        result = server.database.supabase.table('users').select('*').eq('user_id', user_id).execute()
        if not result.data:
            raise HTTPException(404, "User not found")

        user_data = result.data[0]

        # Filter out already active subscriptions and remove cancelled ones
        categories_to_add = []
        for cat in categories:
            existing = server.database.supabase.table('subscriptions').select('*').eq(
                'user_id', user_id
            ).eq('tool_category', cat).execute()

            if existing.data:
                subscription = existing.data[0]
                if subscription['status'] == 'active':
                    logger.info(f"Skipping {cat} - already has active subscription")
                    continue
                else:
                    # Delete cancelled subscription to allow recreation
                    server.database.supabase.table('subscriptions').delete().eq(
                        'id', subscription['id']
                    ).execute()
                    logger.info(f"Deleted cancelled {cat} subscription for user {user_id}")

            categories_to_add.append(cat)

        if not categories_to_add:
            return JSONResponse({
                "status": "already_exists",
                "message": "User already has active subscriptions for all selected categories"
            })

        # FREE SUBSCRIPTIONS - Create separate database records, no billing
        if is_free:
            import secrets
            stripe.api_key = server.config.stripe_secret_key

            # Get or create Stripe customer (for consistency)
            stripe_customer_id = server.database.get_stripe_customer_id(user_id)
            if not stripe_customer_id:
                customer = stripe.Customer.create(
                    email=user_data['email'],
                    metadata={'user_id': user_id}
                )
                stripe_customer_id = customer.id

            # Create separate free subscriptions for each category
            for cat in categories_to_add:
                fake_subscription_id = f"free_{secrets.token_urlsafe(16)}"
                server.database.create_subscription(
                    user_id=user_id,
                    tool_category=cat,
                    stripe_customer_id=stripe_customer_id,
                    stripe_subscription_id=fake_subscription_id,
                    status='active',
                    current_period_start=datetime.now(),
                    current_period_end=datetime.now() + timedelta(days=36500)  # 100 years
                )

            logger.info(f"Admin granted FREE subscriptions for user {user_id}: {', '.join(categories_to_add)}")

            return JSONResponse({
                "status": "success",
                "message": f"Added {len(categories_to_add)} FREE subscription(s)",
                "categories": categories_to_add,
                "is_free": True,
                "note": "Complimentary access with no billing"
            })

        # PAID SUBSCRIPTIONS - Create single Stripe subscription with multiple line items
        stripe.api_key = server.config.stripe_secret_key

        # Get or create Stripe customer
        stripe_customer_id = server.database.get_stripe_customer_id(user_id)
        if not stripe_customer_id:
            customer = stripe.Customer.create(
                email=user_data['email'],
                metadata={'user_id': user_id}
            )
            stripe_customer_id = customer.id
            logger.info(f"Created Stripe customer {stripe_customer_id} for user {user_data['email']}")

        # Build line items for all categories
        line_items = []
        for cat in categories_to_add:
            try:
                price_id = server.config.get_stripe_price_id(cat)
                line_items.append({'price': price_id, 'quantity': 1})
            except ValueError as e:
                raise HTTPException(400, f"No Stripe price configured for {cat}: {str(e)}")

        # Create ONE Stripe subscription with multiple line items
        # payment_behavior='default_incomplete' keeps subscription inactive until invoice is paid
        stripe_subscription = stripe.Subscription.create(
            customer=stripe_customer_id,
            items=line_items,
            collection_method='send_invoice',
            days_until_due=30,
            payment_behavior='default_incomplete',  # Tools locked until payment received
            metadata={
                'user_id': user_id,
                'categories': ','.join(categories_to_add),
                'added_by': 'admin',
                'batch_subscription': 'true'
            }
        )

        # Log the actual status Stripe returned
        logger.info(f"Stripe returned subscription with status: {stripe_subscription.status}")

        # Get the invoice and finalize it if needed
        invoice_link = None
        invoice_paid = False
        latest_invoice_id = stripe_subscription.latest_invoice
        if latest_invoice_id:
            try:
                invoice = stripe.Invoice.retrieve(latest_invoice_id)
                logger.info(f"Retrieved invoice {latest_invoice_id}, status: {invoice.get('status')}")

                # If invoice is still a draft, finalize it to get the hosted URL
                if invoice.get('status') == 'draft':
                    logger.info(f"Finalizing draft invoice {latest_invoice_id}")
                    invoice = stripe.Invoice.finalize_invoice(latest_invoice_id)
                    logger.info(f"Invoice finalized, new status: {invoice.get('status')}")

                # Check if invoice is paid (use dictionary-style access for safety)
                invoice_paid = invoice.get('paid', False)
                invoice_link = invoice.get('hosted_invoice_url')
                logger.info(f"Invoice {latest_invoice_id} - status: {invoice.get('status')}, paid: {invoice_paid}, link: {invoice_link}")
            except Exception as e:
                logger.error(f"Error retrieving/finalizing invoice {latest_invoice_id}: {e}", exc_info=True)

        # IMPORTANT: Invoice subscriptions are created as 'active' by Stripe even before payment
        # We check the invoice payment status to determine the real status for our database
        db_status = 'active' if invoice_paid else 'incomplete'
        logger.info(f"Storing subscriptions with status: {db_status} (invoice_paid={invoice_paid})")

        # Create separate database records for each category, all linked to same Stripe subscription
        # Note: Invoice subscriptions may not have period fields until finalized
        period_start = getattr(stripe_subscription, 'current_period_start', None)
        period_end = getattr(stripe_subscription, 'current_period_end', None)

        for cat in categories_to_add:
            server.database.create_subscription(
                user_id=user_id,
                tool_category=cat,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription.id,  # Same subscription ID for all
                status=db_status,  # Use 'incomplete' until invoice is paid
                current_period_start=datetime.fromtimestamp(period_start) if period_start else datetime.now(),
                current_period_end=datetime.fromtimestamp(period_end) if period_end else datetime.now() + timedelta(days=30),
                invoice_id=latest_invoice_id if db_status == 'incomplete' else None,
                invoice_url=invoice_link if db_status == 'incomplete' else None
            )

        logger.info(f"Admin created batch Stripe subscription {stripe_subscription.id} for user {user_id}, categories: {', '.join(categories_to_add)}")

        return JSONResponse({
            "status": "success",
            "message": f"Added {len(categories_to_add)} subscription(s) (Stripe ID: {stripe_subscription.id})",
            "categories": categories_to_add,
            "subscription_id": stripe_subscription.id,
            "stripe_status": stripe_subscription.status,
            "is_free": False,
            "invoice_link": invoice_link,
            "total_monthly": len(categories_to_add) * 5,
            "note": f"⚠️ Tools are LOCKED until invoice is paid. One invoice sent for all {len(categories_to_add)} categories - payment due within 30 days."
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating batch subscriptions: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Internal server error: {str(e)}")


@app.post("/admin/user/{user_id}/subscription")
async def admin_toggle_subscription(
    request: Request,
    user_id: str,
    admin_password: Optional[str] = Query(None)
):
    """
    Admin endpoint to add or remove subscriptions for a user.

    Body: {
        "action": "add" or "remove",
        "category": "gmail" | "calendar" | "docs" | "sheets" | "fathom" | "instantly" | "bison",
        "free": true/false (optional, default false) - if true, no billing, just grants access
    }
    """
    # Check admin authentication
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not correct_password or not authenticated:
        raise HTTPException(401, "Unauthorized")

    try:
        # Parse request body
        body = await request.json()
        action = body.get('action')  # 'add' or 'remove'
        category = body.get('category')
        is_free = body.get('free', False)  # Default to paid subscription

        if action not in ['add', 'remove']:
            raise HTTPException(400, "Invalid action. Must be 'add' or 'remove'")

        valid_categories = ['gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison']
        if category not in valid_categories:
            raise HTTPException(400, f"Invalid category. Must be one of: {', '.join(valid_categories)}")

        # Get user data
        result = server.database.supabase.table('users').select('*').eq('user_id', user_id).execute()
        if not result.data:
            raise HTTPException(404, "User not found")

        user_data = result.data[0]

        if action == 'add':
            # Check for ANY existing subscription (active or cancelled)
            existing = server.database.supabase.table('subscriptions').select('*').eq(
                'user_id', user_id
            ).eq('tool_category', category).execute()

            if existing.data:
                subscription = existing.data[0]
                if subscription['status'] == 'active':
                    return JSONResponse({
                        "status": "already_exists",
                        "message": f"User already has an active {category} subscription"
                    })
                else:
                    # Delete cancelled subscription to allow recreating
                    server.database.supabase.table('subscriptions').delete().eq(
                        'id', subscription['id']
                    ).execute()
                    logger.info(f"Deleted cancelled {category} subscription for user {user_id} to allow recreation")

            # FREE SUBSCRIPTION - No billing, just database access
            if is_free:
                import secrets

                # Get or create Stripe customer (for consistency, even though no billing)
                stripe.api_key = server.config.stripe_secret_key
                stripe_customer_id = server.database.get_stripe_customer_id(user_id)

                if not stripe_customer_id:
                    customer = stripe.Customer.create(
                        email=user_data['email'],
                        metadata={'user_id': user_id}
                    )
                    stripe_customer_id = customer.id

                # Create database-only subscription (no Stripe subscription)
                fake_subscription_id = f"free_{secrets.token_urlsafe(16)}"

                server.database.create_subscription(
                    user_id=user_id,
                    tool_category=category,
                    stripe_customer_id=stripe_customer_id,
                    stripe_subscription_id=fake_subscription_id,
                    status='active',
                    current_period_start=datetime.now(),
                    current_period_end=datetime.now() + timedelta(days=36500)  # 100 years (lifetime)
                )

                logger.info(f"Admin granted FREE {category} subscription for user {user_id}")

                return JSONResponse({
                    "status": "success",
                    "message": f"Added FREE {category} subscription (no billing)",
                    "subscription_id": fake_subscription_id,
                    "is_free": True,
                    "note": "This is a complimentary subscription with no billing"
                })

            # PAID SUBSCRIPTION - Create Stripe subscription with invoice
            # Initialize Stripe
            stripe.api_key = server.config.stripe_secret_key

            # Get or create Stripe customer
            stripe_customer_id = server.database.get_stripe_customer_id(user_id)

            if not stripe_customer_id:
                # Create Stripe customer
                customer = stripe.Customer.create(
                    email=user_data['email'],
                    metadata={'user_id': user_id}
                )
                stripe_customer_id = customer.id
                logger.info(f"Created Stripe customer {stripe_customer_id} for user {user_data['email']}")

            # Get Stripe price ID for this category
            try:
                price_id = server.config.get_stripe_price_id(category)
            except ValueError as e:
                raise HTTPException(400, f"No Stripe price configured for {category}: {str(e)}")

            # Create real Stripe subscription with invoice billing
            # This allows creating subscriptions without payment method on file
            # Stripe will email the user an invoice to pay
            # payment_behavior='default_incomplete' keeps subscription inactive until invoice is paid
            stripe_subscription = stripe.Subscription.create(
                customer=stripe_customer_id,
                items=[{'price': price_id}],
                collection_method='send_invoice',  # Invoice billing - no card required upfront
                days_until_due=30,  # User has 30 days to pay invoice
                payment_behavior='default_incomplete',  # Tools locked until payment received
                metadata={
                    'user_id': user_id,
                    'tool_category': category,
                    'added_by': 'admin'
                }
            )

            # Get the invoice and finalize it if needed
            invoice_link = None
            invoice_paid = False
            latest_invoice_id = stripe_subscription.latest_invoice
            if latest_invoice_id:
                try:
                    invoice = stripe.Invoice.retrieve(latest_invoice_id)
                    logger.info(f"Retrieved invoice {latest_invoice_id}, status: {invoice.get('status')}")

                    # If invoice is still a draft, finalize it to get the hosted URL
                    if invoice.get('status') == 'draft':
                        logger.info(f"Finalizing draft invoice {latest_invoice_id}")
                        invoice = stripe.Invoice.finalize_invoice(latest_invoice_id)
                        logger.info(f"Invoice finalized, new status: {invoice.get('status')}")

                    # Check if invoice is paid (use dictionary-style access for safety)
                    invoice_paid = invoice.get('paid', False)
                    invoice_link = invoice.get('hosted_invoice_url')
                    logger.info(f"Invoice {latest_invoice_id} - status: {invoice.get('status')}, paid: {invoice_paid}, link: {invoice_link}")
                except Exception as e:
                    logger.error(f"Error retrieving/finalized invoice {latest_invoice_id}: {e}", exc_info=True)

            # IMPORTANT: Invoice subscriptions are created as 'active' by Stripe even before payment
            # We check the invoice payment status to determine the real status for our database
            db_status = 'active' if invoice_paid else 'incomplete'
            logger.info(f"Storing subscription with status: {db_status} (invoice_paid={invoice_paid})")

            # Create subscription in database
            # Note: Stripe webhook will also update this, but we create it immediately for admin visibility
            # Invoice subscriptions may not have period fields until finalized
            period_start = getattr(stripe_subscription, 'current_period_start', None)
            period_end = getattr(stripe_subscription, 'current_period_end', None)

            server.database.create_subscription(
                user_id=user_id,
                tool_category=category,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription.id,
                status=db_status,  # Use 'incomplete' until invoice is paid
                current_period_start=datetime.fromtimestamp(period_start) if period_start else datetime.now(),
                current_period_end=datetime.fromtimestamp(period_end) if period_end else datetime.now() + timedelta(days=30),
                invoice_id=latest_invoice_id if db_status == 'incomplete' else None,
                invoice_url=invoice_link if db_status == 'incomplete' else None
            )

            logger.info(f"Admin created Stripe subscription {stripe_subscription.id} for user {user_id}, category {category}")

            return JSONResponse({
                "status": "success",
                "message": f"Added {category} subscription (Stripe ID: {stripe_subscription.id})",
                "subscription_id": stripe_subscription.id,
                "stripe_status": stripe_subscription.status,
                "is_free": False,
                "invoice_link": invoice_link,
                "note": "⚠️ Tools are LOCKED until invoice is paid. Invoice sent to user - payment due within 30 days."
            })

        elif action == 'remove':
            # Find active subscription
            existing = server.database.supabase.table('subscriptions').select('*').eq(
                'user_id', user_id
            ).eq('tool_category', category).eq('status', 'active').execute()

            if not existing.data:
                return JSONResponse({
                    "status": "not_found",
                    "message": f"No active {category} subscription found"
                }, status_code=404)

            subscription = existing.data[0]
            stripe_subscription_id = subscription.get('stripe_subscription_id')

            # Initialize Stripe
            stripe.api_key = server.config.stripe_secret_key

            # Cancel in Stripe if it's a real Stripe subscription
            if stripe_subscription_id and not stripe_subscription_id.startswith(('admin_', 'free_')):
                try:
                    # Cancel the Stripe subscription immediately
                    cancelled_subscription = stripe.Subscription.cancel(stripe_subscription_id)
                    logger.info(f"Cancelled Stripe subscription {stripe_subscription_id} for user {user_id}")

                    # Note: Stripe webhook will update database, but we update immediately for admin visibility
                    server.database.supabase.table('subscriptions').update({
                        'status': 'cancelled',
                        'cancelled_at': datetime.now().isoformat()
                    }).eq('id', subscription['id']).execute()

                    return JSONResponse({
                        "status": "success",
                        "message": f"Cancelled {category} subscription in Stripe and database",
                        "stripe_subscription_id": stripe_subscription_id,
                        "note": "User will not be billed further"
                    })

                except stripe.error.StripeError as e:
                    logger.error(f"Failed to cancel Stripe subscription {stripe_subscription_id}: {e}")
                    raise HTTPException(500, f"Failed to cancel in Stripe: {str(e)}")
            else:
                # No Stripe subscription (admin-granted/free or old data) - just update database
                server.database.supabase.table('subscriptions').update({
                    'status': 'cancelled',
                    'cancelled_at': datetime.now().isoformat()
                }).eq('id', subscription['id']).execute()

                logger.info(f"Admin removed {category} subscription (no Stripe cancellation needed) for user {user_id}")

                return JSONResponse({
                    "status": "success",
                    "message": f"Removed {category} subscription from database",
                    "note": "No Stripe subscription to cancel"
                })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling subscription: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Internal server error: {str(e)}")


@app.get("/admin/user/{user_id}/activity")
async def admin_get_user_activity(
    request: Request,
    user_id: str,
    admin_password: Optional[str] = Query(None),
    limit: int = Query(50),
    raw: bool = Query(False)  # Show RAW unfiltered data
):
    """
    API endpoint for real-time user activity polling.
    Returns recent usage logs as JSON for live updates.

    Set raw=true to see FULL unfiltered request/response data (for debugging).
    """
    # Check admin authentication
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not correct_password or not authenticated:
        raise HTTPException(401, "Unauthorized")

    try:
        # Get recent logs
        recent_logs = server.database.supabase.table('usage_logs').select('*').eq(
            'user_id', user_id
        ).order('timestamp', desc=True).limit(limit).execute()

        # Format logs - show RAW data for admin debugging
        logs = []
        for log in recent_logs.data:
            log_entry = {
                'id': log.get('id'),
                'timestamp': log['timestamp'],
                'tool_name': log['tool_name'],
                'success': log['success'],
                'error_message': log.get('error_message'),
                'error_type': log.get('error_type'),
                'duration_ms': log.get('duration_ms'),
                'request_params': log.get('request_params', {}),  # RAW params
                'response_data': log.get('response_data'),  # RAW response
                'stack_trace': log.get('stack_trace')  # Full stack trace if available
            }
            logs.append(log_entry)

        # Get error summary
        error_logs = [log for log in recent_logs.data if not log['success']]
        error_summary = {}
        for log in error_logs:
            tool = log['tool_name']
            error_summary[tool] = error_summary.get(tool, 0) + 1

        # Get subscriptions
        subscriptions = server.database.supabase.table('subscriptions').select('*').eq(
            'user_id', user_id
        ).eq('status', 'active').execute()
        active_categories = [sub['tool_category'] for sub in subscriptions.data]

        # Get API keys status (handle if column doesn't exist)
        api_keys_configured = {}
        try:
            user_result = server.database.supabase.table('users').select('api_keys').eq('user_id', user_id).execute()
            api_keys = user_result.data[0].get('api_keys', {}) if user_result.data else {}
            api_keys_configured = {key: bool(value) for key, value in api_keys.items()}
        except Exception as e:
            logger.warning(f"Could not fetch api_keys for user {user_id}: {e}")
            # Column might not exist yet - that's okay, just return empty dict

        return JSONResponse({
            'logs': logs,
            'total_logs': len(logs),
            'success_count': len([log for log in logs if log['success']]),
            'error_count': len([log for log in logs if not log['success']]),
            'error_summary': error_summary,
            'active_subscriptions': active_categories,
            'api_keys_configured': api_keys_configured,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error fetching user activity: {e}")
        raise HTTPException(500, str(e))


@app.post("/admin/test-tool")
async def admin_test_tool(
    request: Request,
    admin_password: Optional[str] = Query(None)
):
    """
    Execute a tool for testing purposes.

    Body:
    {
        "tool_name": "search_emails",
        "arguments": {"query": "from:test@example.com", "max_results": 10},
        "user_id": "optional_user_id"  # If provided, tests with that user's context
    }

    Returns:
    {
        "success": true,
        "result": {...},
        "response_time_ms": 243,
        "timestamp": "2025-01-02T18:00:00Z"
    }
    """
    # Check admin authentication
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not correct_password or not authenticated:
        raise HTTPException(401, "Unauthorized")

    try:
        # Parse request body
        body = await request.json()
        tool_name = body.get("tool_name")
        arguments = body.get("arguments", {})
        user_id = body.get("user_id")  # Optional: test with specific user context

        if not tool_name:
            raise HTTPException(400, "Missing tool_name")

        # Track execution time
        import time
        start_time = time.time()

        # Execute tool
        if user_id:
            # Test with specific user's context
            session_result = server.database.supabase.table('users').select('session_token').eq(
                'user_id', user_id
            ).execute()

            if not session_result.data:
                raise HTTPException(404, f"User {user_id} not found")

            # Create request context for this user
            from request_context import create_request_context
            ctx = await create_request_context(
                database=server.database,
                session_token=session_result.data[0]['session_token'],
                config=server.config
            )

            # Execute with user context
            response = await execute_tool_with_context(
                tool_name=tool_name,
                arguments=arguments,
                ctx=ctx,
                request_id=f"test-{int(time.time() * 1000)}"
            )

            # Extract result from MCP response
            result = response.get("result", {}).get("content", [{}])[0].get("text", "")
        else:
            # Test without user context (single-user mode)
            result = await execute_tool(tool_name, arguments)

        # Calculate response time
        elapsed_ms = int((time.time() - start_time) * 1000)

        # Parse result if it's JSON string
        try:
            result_parsed = json.loads(result) if isinstance(result, str) else result
        except:
            result_parsed = result

        return JSONResponse({
            "success": True,
            "result": result_parsed,
            "response_time_ms": elapsed_ms,
            "timestamp": datetime.now().isoformat()
        })

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Tool test failed: {e}")

        return JSONResponse({
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "stack_trace": traceback.format_exc(),
            "timestamp": datetime.now().isoformat()
        }, status_code=500)


@app.delete("/admin/user/{user_id}")
async def admin_delete_user(
    request: Request,
    user_id: str,
    admin_password: Optional[str] = Query(None)
):
    """
    Admin endpoint to permanently delete a user and all their data.

    This will delete:
    - User account
    - All subscriptions (and cancel them in Stripe if applicable)
    - All usage logs
    - All team memberships
    - All teams owned by this user
    - All invitations sent/received
    - Session data

    This action CANNOT be undone.
    """
    # Check admin authentication
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not correct_password or not authenticated:
        raise HTTPException(401, "Unauthorized")

    try:
        # Get user data first
        result = server.database.supabase.table('users').select('*').eq('user_id', user_id).execute()
        if not result.data:
            raise HTTPException(404, "User not found")

        user_data = result.data[0]
        user_email = user_data['email']

        logger.info(f"Admin initiating deletion of user {user_id} ({user_email})")

        # 1. Cancel all Stripe subscriptions first
        subscriptions = server.database.supabase.table('subscriptions').select('*').eq(
            'user_id', user_id
        ).execute()

        stripe.api_key = server.config.stripe_secret_key
        cancelled_stripe_subs = []

        for sub in subscriptions.data:
            if sub.get('stripe_subscription_id'):
                try:
                    stripe.Subscription.delete(sub['stripe_subscription_id'])
                    cancelled_stripe_subs.append(sub['stripe_subscription_id'])
                    logger.info(f"Cancelled Stripe subscription {sub['stripe_subscription_id']}")
                except stripe.error.StripeError as e:
                    logger.warning(f"Failed to cancel Stripe subscription {sub['stripe_subscription_id']}: {e}")

        # 2. Delete from database tables (order matters due to foreign keys)

        # Delete usage logs
        server.database.supabase.table('usage_logs').delete().eq('user_id', user_id).execute()
        logger.info(f"Deleted usage logs for user {user_id}")

        # Delete team member permissions
        server.database.supabase.table('team_member_permissions').delete().eq('user_id', user_id).execute()
        logger.info(f"Deleted team member permissions for user {user_id}")

        # Delete team memberships
        server.database.supabase.table('team_members').delete().eq('user_id', user_id).execute()
        logger.info(f"Deleted team memberships for user {user_id}")

        # Delete teams owned by this user (cascade will handle team_members)
        teams = server.database.supabase.table('teams').select('team_id').eq('owner_user_id', user_id).execute()
        for team in teams.data:
            server.database.supabase.table('teams').delete().eq('team_id', team['team_id']).execute()
            logger.info(f"Deleted team {team['team_id']} owned by user {user_id}")

        # Delete invitations (sent and received)
        server.database.supabase.table('team_invitations').delete().eq('email', user_email).execute()
        server.database.supabase.table('team_invitations').delete().eq('invited_by_user_id', user_id).execute()
        logger.info(f"Deleted invitations for user {user_id}")

        # Delete subscriptions
        server.database.supabase.table('subscriptions').delete().eq('user_id', user_id).execute()
        logger.info(f"Deleted subscriptions for user {user_id}")

        # Finally, delete the user
        server.database.supabase.table('users').delete().eq('user_id', user_id).execute()
        logger.info(f"Deleted user account {user_id} ({user_email})")

        return JSONResponse({
            "success": True,
            "message": f"User {user_email} permanently deleted",
            "details": {
                "user_id": user_id,
                "email": user_email,
                "stripe_subscriptions_cancelled": len(cancelled_stripe_subs)
            }
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Internal server error: {str(e)}")


@app.post("/admin/user/{user_id}/generate-password")
async def admin_generate_password(
    request: Request,
    user_id: str,
    admin_password: Optional[str] = Query(None)
):
    """
    Admin endpoint to generate a new password for a user and email it to them.

    Returns the generated password so admin can save it.
    """
    # Check admin authentication
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not correct_password or not authenticated:
        raise HTTPException(401, "Unauthorized")

    try:
        import secrets
        import string
        import bcrypt

        # Get user data
        result = server.database.supabase.table('users').select('*').eq('user_id', user_id).execute()
        if not result.data:
            raise HTTPException(404, "User not found")

        user_data = result.data[0]
        user_email = user_data['email']

        # Generate secure random password (12 characters: letters, numbers, symbols)
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for _ in range(12))

        # Hash password with bcrypt
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12))

        # Update user's password in database
        server.database.supabase.table('users').update({
            'password_hash': password_hash.decode('utf-8')
        }).eq('user_id', user_id).execute()

        logger.info(f"Admin generated new password for user {user_email}")

        # Send email with credentials
        try:
            import resend
            resend.api_key = os.getenv("RESEND_API_KEY")

            # Send email
            email_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 28px;">🔐 Your Account Credentials</h1>
    </div>

    <div style="background: #f9fafb; padding: 30px; border-radius: 0 0 12px 12px;">
        <p style="font-size: 16px; margin-bottom: 20px;">Hello,</p>

        <p style="font-size: 16px; margin-bottom: 20px;">Your account credentials for the AI Email Assistant have been set up:</p>

        <div style="background: white; border: 2px solid #e5e7eb; border-radius: 8px; padding: 20px; margin: 20px 0;">
            <p style="margin: 0 0 10px 0; color: #6b7280; font-size: 14px; font-weight: 600;">EMAIL</p>
            <p style="margin: 0 0 20px 0; font-size: 16px; font-weight: 600;">{user_email}</p>

            <p style="margin: 0 0 10px 0; color: #6b7280; font-size: 14px; font-weight: 600;">PASSWORD</p>
            <p style="margin: 0; font-size: 18px; font-family: 'Courier New', monospace; background: #f3f4f6; padding: 12px; border-radius: 6px; font-weight: 600; letter-spacing: 1px;">{password}</p>
        </div>

        <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; border-radius: 6px; margin: 20px 0;">
            <p style="margin: 0; color: #92400e; font-size: 14px;">
                <strong>⚠️ Important:</strong> Please save this password securely. For security reasons, we cannot recover it if lost.
            </p>
        </div>

        <p style="font-size: 16px; margin-bottom: 15px;">You can now log in at:</p>
        <p style="text-align: center; margin: 20px 0;">
            <a href="https://{request.url.hostname}/login" style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;">Log In to Your Account</a>
        </p>

        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">

        <p style="font-size: 14px; color: #6b7280; margin: 0;">
            If you didn't request this, please contact support immediately.
        </p>
    </div>
</body>
</html>
            """

            resend.Emails.send({
                "from": "AI Email Assistant <noreply@leadgenjay.com>",
                "to": [user_email],
                "subject": "Your Account Credentials - AI Email Assistant",
                "html": email_html
            })

            logger.info(f"Password email sent successfully to {user_email}")
            email_status = "sent"

        except Exception as e:
            logger.error(f"Failed to send password email to {user_email}: {e}")
            email_status = "failed"

        return JSONResponse({
            "status": "success",
            "password": password,
            "email_sent": email_status == "sent",
            "message": f"Password generated and {'emailed to' if email_status == 'sent' else 'could not be emailed to'} {user_email}"
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating password: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Internal server error: {str(e)}")


@app.post("/admin/user/{user_id}/toggle-teams")
async def admin_toggle_team_access(
    request: Request,
    user_id: str,
    admin_password: Optional[str] = Query(None)
):
    """
    Admin endpoint to toggle team access for a user.
    Allows/prevents user from creating and managing teams.
    """
    # Check admin authentication
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not correct_password or not authenticated:
        raise HTTPException(401, "Unauthorized")

    try:
        # Parse request body
        body = await request.json()
        enabled = body.get('enabled', False)

        # Update user's teams_enabled field
        server.database.supabase.table('users').update({
            'teams_enabled': enabled
        }).eq('user_id', user_id).execute()

        logger.info(f"Admin {'enabled' if enabled else 'disabled'} team access for user {user_id}")

        return JSONResponse({
            "status": "success",
            "teams_enabled": enabled,
            "message": f"Team access {'enabled' if enabled else 'disabled'} successfully"
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling team access: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Internal server error: {str(e)}")


@app.post("/admin/user/{user_id}/clear-enabled-categories")
async def admin_clear_enabled_categories(
    request: Request,
    user_id: str,
    admin_password: Optional[str] = Query(None)
):
    """
    Admin endpoint to clear enabled_tool_categories filter.

    This removes the legacy enabled_tool_categories filter so that
    only active subscriptions control which tools are visible.
    """
    # Check admin authentication
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not correct_password or not authenticated:
        raise HTTPException(401, "Unauthorized")

    try:
        # Get user data
        result = server.database.supabase.table('users').select('email, enabled_tool_categories').eq('user_id', user_id).execute()
        if not result.data:
            raise HTTPException(404, "User not found")

        user_data = result.data[0]
        user_email = user_data['email']
        old_value = user_data.get('enabled_tool_categories')

        # Clear enabled_tool_categories
        server.database.supabase.table('users').update({
            'enabled_tool_categories': None
        }).eq('user_id', user_id).execute()

        logger.info(f"Admin cleared enabled_tool_categories for user {user_email} (was: {old_value})")

        return JSONResponse({
            "status": "success",
            "message": f"Cleared enabled_tool_categories for {user_email}",
            "previous_value": old_value
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error clearing enabled_tool_categories: {e}")
        raise HTTPException(500, f"Internal server error: {str(e)}")


# ===========================================================================
# SESSION MANAGEMENT ENDPOINTS
# ===========================================================================

@app.delete("/mcp/session/{session_id}")
async def delete_session(session_id: str):
    """
    Explicit session cleanup endpoint.

    Per SimpleScraper guide: Implement cleanup to prevent memory leaks.
    """
    if session_id in sessions:
        del sessions[session_id]
        logger.info(f"Deleted session: {session_id}")
        return JSONResponse({"status": "session deleted"})
    else:
        raise HTTPException(status_code=404, detail="Session not found")


# ===========================================================================
# ADMIN TEAMS MANAGEMENT
# ===========================================================================

@app.get("/admin/teams", response_class=HTMLResponse)
async def admin_teams_page(request: Request, admin_password: Optional[str] = Query(None)):
    """Admin page to manage all teams and grant free subscriptions."""
    # Check admin password
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not correct_password or not authenticated:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin/login", status_code=303)

    # Get all teams
    teams_result = server.database.supabase.table('teams').select('*').execute()
    all_teams = teams_result.data if teams_result.data else []

    # Get subscriptions for each team
    team_data = []
    for team in all_teams:
        members = server.database.get_team_members(team['team_id'])
        subs = server.database.supabase.table('subscriptions').select('tool_category, status').eq(
            'team_id', team['team_id']
        ).eq('is_team_subscription', True).execute()

        active_categories = [s['tool_category'] for s in subs.data if s['status'] == 'active']

        team_data.append({
            'team_id': team['team_id'],
            'team_name': team['team_name'],
            'owner_user_id': team['owner_user_id'],
            'member_count': len(members),
            'active_subscriptions': active_categories
        })

    all_categories = ['gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison']

    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>Admin - Teams Management</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f7fa;
            padding: 20px;
            margin: 0;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
        }}
        .team-card {{
            background: white;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .team-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid #e2e8f0;
        }}
        .team-name {{
            font-size: 20px;
            font-weight: 600;
            color: #1a202c;
        }}
        .team-meta {{
            color: #6b7280;
            font-size: 14px;
        }}
        .current-subs {{
            margin-bottom: 20px;
        }}
        .sub-badge {{
            display: inline-block;
            background: #d1fae5;
            color: #065f46;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            margin-right: 8px;
            margin-bottom: 8px;
        }}
        .grant-section {{
            background: #f9fafb;
            padding: 20px;
            border-radius: 8px;
        }}
        .checkbox-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: 12px;
            margin-bottom: 15px;
        }}
        .checkbox-label {{
            display: flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
        }}
        .checkbox-label input {{
            width: 18px;
            height: 18px;
            cursor: pointer;
        }}
        .btn {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }}
        .toast {{
            position: fixed;
            top: 20px;
            right: 20px;
            background: #10b981;
            color: white;
            padding: 15px 20px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            display: none;
            z-index: 1000;
        }}
        .toast.error {{
            background: #ef4444;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0 0 10px 0;">🎛️ Teams Management</h1>
            <p style="margin: 0; opacity: 0.9;">Grant free team subscriptions to any team</p>
            <a href="/admin" style="color: white; opacity: 0.8; text-decoration: none; margin-top: 10px; display: inline-block;">← Back to Admin Dashboard</a>
        </div>

        <div id="toast" class="toast"></div>

        {chr(10).join([f'''
        <div class="team-card">
            <div class="team-header">
                <div>
                    <div class="team-name">👥 {team['team_name']}</div>
                    <div class="team-meta">{team['member_count']} members • Team ID: {team['team_id'][:20]}...</div>
                </div>
            </div>

            <div class="current-subs">
                <strong style="display: block; margin-bottom: 10px; color: #374151;">Current Subscriptions:</strong>
                {('<div>' + ''.join([f'<span class="sub-badge">✓ {cat.title()}</span>' for cat in team['active_subscriptions']]) + '</div>') if team['active_subscriptions'] else '<div style="color: #9ca3af;">No active subscriptions</div>'}
            </div>

            <div class="grant-section">
                <strong style="display: block; margin-bottom: 12px; color: #374151;">Grant Free Subscriptions:</strong>
                <form id="grant-form-{team['team_id']}" onsubmit="grantSubscriptions(event, '{team['team_id']}')">
                    <div class="checkbox-grid">
                        {''.join([f'<label class="checkbox-label"><input type="checkbox" name="category" value="{cat}" {"disabled" if cat in team["active_subscriptions"] else ""}><span style="color: {"#9ca3af" if cat in team["active_subscriptions"] else "#374151"};">{cat.title()}</span></label>' for cat in all_categories])}
                    </div>
                    <button type="submit" class="btn">Grant Selected Categories</button>
                </form>
            </div>
        </div>
        ''' for team in team_data]) if team_data else '<div class="team-card" style="text-align: center; padding: 60px; color: #9ca3af;"><div style="font-size: 48px; margin-bottom: 15px;">📦</div><div>No teams found</div></div>'}
    </div>

    <script>
        function showToast(message, type = 'success') {{
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.className = 'toast' + (type === 'error' ? ' error' : '');
            toast.style.display = 'block';
            setTimeout(() => {{
                toast.style.display = 'none';
            }}, 3000);
        }}

        async function grantSubscriptions(event, teamId) {{
            event.preventDefault();

            const form = event.target;
            const checkboxes = form.querySelectorAll('input[name="category"]:checked');
            const categories = Array.from(checkboxes).map(cb => cb.value);

            if (categories.length === 0) {{
                showToast('Please select at least one category', 'error');
                return;
            }}

            const submitBtn = form.querySelector('button[type="submit"]');
            const originalText = submitBtn.textContent;
            submitBtn.textContent = 'Granting...';
            submitBtn.disabled = true;

            try {{
                const response = await fetch(`/admin/teams/${{teamId}}/grant-subscription`, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ categories: categories }})
                }});

                const result = await response.json();

                if (response.ok) {{
                    showToast(`✓ Granted ${{categories.length}} categories to team`);
                    setTimeout(() => window.location.reload(), 1500);
                }} else {{
                    showToast(result.detail || 'Failed to grant subscriptions', 'error');
                    submitBtn.textContent = originalText;
                    submitBtn.disabled = false;
                }}
            }} catch (error) {{
                showToast('Network error. Please try again.', 'error');
                submitBtn.textContent = originalText;
                submitBtn.disabled = false;
            }}
        }}
    </script>
</body>
</html>
    """)


@app.post("/admin/grant-personal")
async def admin_grant_personal_subscription(
    request: Request,
    session_token: str = Query(...),
    admin_password: Optional[str] = Query(None)
):
    """Admin endpoint to grant free personal subscription from dashboard."""
    # Check admin password
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not correct_password or not authenticated:
        raise HTTPException(401, "Unauthorized")

    # Parse request body
    body = await request.json()
    category = body.get('category')

    if not category:
        raise HTTPException(400, "No category provided")

    # Get user from session token
    user = server.database.get_user_by_session(session_token)
    if not user:
        raise HTTPException(404, "User not found")

    # Check if subscription already exists
    existing = server.database.supabase.table('subscriptions').select('*').eq(
        'user_id', user['user_id']
    ).eq('tool_category', category).eq('is_team_subscription', False).execute()

    if existing.data:
        raise HTTPException(400, f"User already has {category} subscription")

    # Create free personal subscription (no Stripe)
    server.database.supabase.table('subscriptions').insert({
        'user_id': user['user_id'],
        'team_id': None,
        'is_team_subscription': False,
        'tool_category': category,
        'status': 'active',  # Immediately active
        'stripe_customer_id': None,
        'stripe_subscription_id': None
    }).execute()

    logger.info(f"Admin granted {category} to user {user['email']} (free)")

    return {
        "success": True,
        "message": f"Granted {category} successfully"
    }


@app.post("/admin/grant-team")
async def admin_grant_team_subscription_single(
    request: Request,
    session_token: str = Query(...),
    admin_password: Optional[str] = Query(None)
):
    """Admin endpoint to grant free team subscription from dashboard."""
    # Check admin password
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not correct_password or not authenticated:
        raise HTTPException(401, "Unauthorized")

    # Parse request body
    body = await request.json()
    team_id = body.get('team_id')
    category = body.get('category')

    if not team_id or not category:
        raise HTTPException(400, "Missing team_id or category")

    # Verify team exists
    team_result = server.database.supabase.table('teams').select('*').eq('team_id', team_id).execute()
    if not team_result.data:
        raise HTTPException(404, "Team not found")

    team = team_result.data[0]

    # Check if subscription already exists
    existing = server.database.supabase.table('subscriptions').select('*').eq(
        'team_id', team_id
    ).eq('tool_category', category).eq('is_team_subscription', True).execute()

    if existing.data:
        raise HTTPException(400, f"Team already has {category} subscription")

    # Create free subscription (no Stripe)
    # Use owner's user_id - now safe thanks to updated unique constraint that includes team_id
    server.database.supabase.table('subscriptions').insert({
        'user_id': team['owner_user_id'],  # Team owner as billing contact
        'team_id': team_id,
        'is_team_subscription': True,
        'tool_category': category,
        'status': 'active',  # Immediately active
        'stripe_customer_id': None,
        'stripe_subscription_id': None
    }).execute()

    logger.info(f"Admin granted {category} to team {team_id} (free)")

    return {
        "success": True,
        "message": f"Granted {category} to team successfully"
    }


@app.post("/admin/teams/{{team_id}}/grant-subscription")
async def admin_grant_team_subscription(
    request: Request,
    team_id: str,
    admin_password: Optional[str] = Query(None)
):
    """Admin endpoint to grant free team subscriptions without payment."""
    # Check admin password
    correct_password = os.getenv("ADMIN_PASSWORD")
    cookie_password = request.cookies.get("admin_session")
    authenticated = (cookie_password == correct_password) or (admin_password == correct_password)

    if not correct_password or not authenticated:
        raise HTTPException(401, "Unauthorized")

    # Parse request body
    body = await request.json()
    categories = body.get('categories', [])

    if not categories:
        raise HTTPException(400, "No categories provided")

    # Verify team exists
    team_result = server.database.supabase.table('teams').select('*').eq('team_id', team_id).execute()
    if not team_result.data:
        raise HTTPException(404, "Team not found")

    team = team_result.data[0]

    # Create free subscriptions for each category
    granted_count = 0
    for category in categories:
        # Check if subscription already exists
        existing = server.database.supabase.table('subscriptions').select('*').eq(
            'team_id', team_id
        ).eq('tool_category', category).eq('is_team_subscription', True).execute()

        if existing.data:
            logger.info(f"Subscription for {category} already exists for team {team_id}")
            continue

        # Create free subscription (no Stripe)
        # Use owner's user_id - now safe thanks to updated unique constraint
        server.database.supabase.table('subscriptions').insert({
            'user_id': team['owner_user_id'],  # Team owner as billing contact
            'team_id': team_id,
            'is_team_subscription': True,
            'tool_category': category,
            'status': 'active',  # Immediately active
            'stripe_customer_id': None,
            'stripe_subscription_id': None
        }).execute()

        granted_count += 1
        logger.info(f"Admin granted {category} to team {team_id} (free)")

    return {
        "success": True,
        "message": f"Granted {granted_count} categories to team",
        "granted_count": granted_count
    }


# ===========================================================================
# MAIN ENTRY POINT
# ===========================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8080))
    host = "0.0.0.0"

    logger.info(f"Starting server on {host}:{port}")

    uvicorn.run(
        "mcp_remote_server:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
