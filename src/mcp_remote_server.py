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
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
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

            # Helper function to map tool names to categories
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
                return None  # Unknown category, include by default

            # Filter by user's enabled tool categories (if applicable)
            if ctx:
                enabled_categories = ctx.enabled_tool_categories
                if enabled_categories is not None:  # None = show all, [] or [...] = filter
                    # Filter tools by enabled categories
                    if enabled_categories == []:
                        # Empty list = no tools
                        tools = []
                    else:
                        # Filter to only enabled categories
                        filtered_tools = []
                        for tool in tools:
                            category = get_tool_category(tool['name'])
                            if category is None or category in enabled_categories:
                                filtered_tools.append(tool)
                        tools = filtered_tools

                # Filter by active subscriptions (payment enforcement)
                active_subscriptions = ctx.active_subscriptions
                if active_subscriptions is not None and len(active_subscriptions) > 0:
                    # User has some subscriptions - only show subscribed categories
                    subscription_filtered_tools = []
                    for tool in tools:
                        category = get_tool_category(tool['name'])
                        # Allow tools with no category OR tools in subscribed categories
                        if category is None or category in active_subscriptions:
                            subscription_filtered_tools.append(tool)
                    tools = subscription_filtered_tools
                    logger.info(f"Filtered to subscribed categories: {active_subscriptions}")
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
            start_time = time.time()

            try:
                # If multi-tenant context provided, use per-user clients
                if ctx:
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
                                response_time_ms=elapsed_ms
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
                            response_time_ms=elapsed_ms
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

    # Start session cleanup task
    cleanup_task = asyncio.create_task(cleanup_stale_sessions())
    logger.info("✓ Session cleanup task started")
    logger.info("=" * 60)

    yield

    # Cleanup on shutdown
    logger.info("Shutting down Remote MCP Server...")
    cleanup_task.cancel()
    sessions.clear()
    logger.info("✓ Cleanup complete")


# Create FastAPI app
app = FastAPI(
    title="LeadGenJay MCP Remote Server",
    description="Remote MCP server exposing 82+ tools for Gmail, Calendar, Docs, Sheets, and more",
    version="1.0.0",
    lifespan=lifespan
)


# Add CORS middleware (CRITICAL for web-based MCP clients)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    """Root endpoint with server information."""
    try:
        tools = await server.mcp.list_tools()
        tool_count = len(tools)
        tool_names = sorted([t.name for t in tools])
    except Exception:
        tool_count = 0
        tool_names = []

    return JSONResponse({
        "server": "LeadGenJay MCP Remote Server",
        "status": "online",
        "version": "1.0.0",
        "protocol_version": "2024-11-05",
        "tools_count": tool_count,
        "tools_preview": tool_names[:20],  # First 20 tools
        "sessions_active": len(sessions),
        "transports": [
            "Modern: POST /mcp (Streamable HTTP)",
            "Legacy: GET /mcp (SSE) + POST /messages"
        ],
        "endpoints": {
            "health": "GET /health",
            "modern_transport": "POST /mcp",
            "legacy_sse_stream": "GET /mcp",
            "legacy_messages": "POST /messages"
        },
        "documentation": "https://github.com/jonathangetonapod/gmail-reply-tracker-mcp"
    })


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
async def setup_start(request: Request):
    """Initiate Google OAuth flow for multi-tenant setup."""
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

        # Generate authorization URL
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'  # Force consent to get refresh token
        )

        # Store state for verification (with timestamp for cleanup)
        oauth_states[state] = {
            'timestamp': datetime.now(),
            'flow': flow
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


@app.get("/setup/callback")
async def setup_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None)
):
    """Handle OAuth callback from Google."""
    try:
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

        # Clean up used state
        del oauth_states[state]

        # Exchange authorization code for tokens
        logger.info(f"Exchanging auth code for tokens (state: {state})")
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Get user's email from Gmail API
        gmail_service = build('gmail', 'v1', credentials=credentials)
        profile = gmail_service.users().getProfile(userId='me').execute()
        email = profile['emailAddress']

        logger.info(f"OAuth successful for user: {email}")

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

        logger.info(f"User created/updated in database: {email} (ID: {user_data['user_id']})")

        # Get server URL for Claude config (force HTTPS for Railway)
        server_url = f"https://{request.url.hostname}"
        session_token = user_data['session_token']

        # Show success page with session token
        success_html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Setup Complete</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            padding: 40px 20px;
        }}
        .card {{
            max-width: 700px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 40px;
        }}
        h1 {{
            color: #4caf50;
            margin-bottom: 20px;
            font-size: 28px;
        }}
        .success-icon {{
            font-size: 48px;
            margin-bottom: 20px;
            text-align: center;
        }}
        p {{
            color: #666;
            margin-bottom: 20px;
            line-height: 1.6;
        }}
        .token-box {{
            background: #f5f5f5;
            border: 2px solid #e0e0e0;
            border-radius: 6px;
            padding: 20px;
            margin: 30px 0;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 14px;
            word-break: break-all;
            position: relative;
        }}
        .token-label {{
            font-weight: bold;
            margin-bottom: 10px;
            color: #333;
            font-size: 12px;
            text-transform: uppercase;
        }}
        .token-value {{
            background: white;
            padding: 12px;
            border-radius: 4px;
            border: 1px solid #ddd;
            margin-top: 8px;
        }}
        .copy-button {{
            background: #2196f3;
            color: white;
            border: none;
            padding: 8px 16px;
            font-size: 14px;
            border-radius: 4px;
            cursor: pointer;
            margin-top: 10px;
        }}
        .copy-button:hover {{
            background: #1976d2;
        }}
        .instructions {{
            background: #e3f2fd;
            padding: 20px;
            border-radius: 6px;
            border-left: 4px solid #2196f3;
            margin: 20px 0;
        }}
        .instructions h2 {{
            color: #1976d2;
            font-size: 18px;
            margin-bottom: 15px;
        }}
        .instructions ol {{
            margin-left: 20px;
            color: #555;
        }}
        .instructions li {{
            margin-bottom: 10px;
            line-height: 1.6;
        }}
        .config-box {{
            background: #263238;
            color: #aed581;
            padding: 20px;
            border-radius: 6px;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 13px;
            overflow-x: auto;
            margin: 20px 0;
        }}
        .highlight {{
            background: #fff9c4;
            padding: 2px 6px;
            border-radius: 3px;
            font-weight: 600;
        }}
    </style>
    <script>
        function copyToken() {{
            const tokenValue = document.getElementById('token-value').textContent;
            navigator.clipboard.writeText(tokenValue).then(() => {{
                const button = document.getElementById('copy-button');
                button.textContent = '✓ Copied!';
                button.style.background = '#4caf50';
                setTimeout(() => {{
                    button.textContent = '📋 Copy Token';
                    button.style.background = '#2196f3';
                }}, 2000);
            }});
        }}

        function copyURL() {{
            const urlText = document.getElementById('mcp-url').textContent;
            navigator.clipboard.writeText(urlText).then(() => {{
                const button = event.target;
                button.textContent = '✓ Copied!';
                button.style.background = '#4caf50';
                setTimeout(() => {{
                    button.textContent = '📋 Copy URL';
                    button.style.background = '#2196f3';
                }}, 2000);
            }});
        }}
    </script>
</head>
<body>
    <div class="card">
        <div class="success-icon">✅</div>
        <h1>🎉 Setup Complete!</h1>
        <p>Your Google account ({email}) has been successfully authorized.</p>

        <div class="token-box">
            <div class="token-label">Your Session Token</div>
            <div class="token-value" id="token-value">{session_token}</div>
            <button class="copy-button" id="copy-button" onclick="copyToken()">📋 Copy Token</button>
        </div>

        <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 20px; margin: 20px 0; border-radius: 6px;">
            <h3 style="color: #856404; margin-bottom: 10px;">⚙️ Manage Your API Keys</h3>
            <p style="color: #856404; margin-bottom: 15px;">Add Fathom, Instantly, and other API keys to unlock additional tools:</p>
            <a href="/dashboard?session_token={session_token}" style="display: inline-block; background: #2196f3; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: 600;">Go to Dashboard →</a>
        </div>

        <div class="instructions">
            <h2>🔧 Add to Claude Desktop (via GUI)</h2>
            <ol>
                <li>Open <strong>Claude Desktop</strong></li>
                <li>Go to <strong>Settings</strong> ⚙️ → <strong>Developer</strong> tab</li>
                <li>Under "Custom Connectors", click <strong>Add Connector</strong> or <strong>+</strong></li>
                <li>Fill in the form:</li>
            </ol>

            <div style="background: #f9f9f9; padding: 20px; border-radius: 6px; margin: 20px 0; border: 1px solid #ddd;">
                <div style="margin-bottom: 15px;">
                    <strong style="color: #333; display: block; margin-bottom: 5px;">Name:</strong>
                    <div style="background: white; padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-family: monospace;">gmail-mcp</div>
                </div>
                <div style="margin-bottom: 15px;">
                    <strong style="color: #333; display: block; margin-bottom: 5px;">Remote MCP Server URL:</strong>
                    <div style="background: white; padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-family: monospace; word-break: break-all;" id="mcp-url">{server_url}/mcp?session_token={session_token}</div>
                    <button class="copy-button" onclick="copyURL()" style="margin-top: 8px;">📋 Copy URL</button>
                </div>
                <div style="color: #666; font-size: 14px; margin-top: 10px;">
                    ℹ️ Leave OAuth Client ID and OAuth Client Secret fields <strong>empty</strong>
                </div>
            </div>

            <ol start="5">
                <li>Click <strong>Save</strong> or <strong>Add</strong></li>
                <li><strong>Restart Claude Desktop</strong></li>
                <li>Start using your 84 Gmail & Calendar tools!</li>
            </ol>
        </div>

        <p style="text-align: center; margin-top: 30px; color: #999; font-size: 14px;">
            🔒 Your token is stored securely and encrypted in the database.
        </p>
    </div>
</body>
</html>
        """
        return HTMLResponse(content=success_html)

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
async def dashboard(session_token: Optional[str] = Query(None)):
    """Admin dashboard for managing API keys."""
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

    # Get active subscriptions
    active_subscriptions = server.database.get_active_subscriptions(ctx.user_id)

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
    tool_counts = {'gmail': 25, 'calendar': 15, 'docs': 8, 'sheets': 12, 'fathom': 10, 'instantly': 10, 'bison': 4}
    if enabled_categories is None:
        total_tools = 84
    else:
        total_tools = sum(tool_counts[cat] for cat in enabled_categories)

    # Pre-compute subscription badges for each category (avoids complex nested f-string)
    subscription_badges = {}
    for category in all_categories:
        if category in active_subscriptions:
            subscription_badges[category] = '<span style="background: #d4edda; color: #155724; padding: 4px 12px; border-radius: 12px; font-size: 13px; font-weight: 600;">✅ Subscribed</span>'
        else:
            subscription_badges[category] = f'<a href="/subscribe?category={category}&session_token={session_token}" style="background: #007bff; color: white; padding: 4px 12px; border-radius: 12px; font-size: 13px; font-weight: 600; text-decoration: none;">🔒 Subscribe ($5/mo)</a>'

    # Render dashboard HTML
    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>MCP Dashboard - {ctx.email}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
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
    <div class="container">
        <h1>🛠️ MCP Dashboard</h1>

        <div class="user-info">
            <strong>Logged in as:</strong> {ctx.email}<br>
            <strong>User ID:</strong> {ctx.user_id}
        </div>

        <div id="success-message" class="success"></div>
        <div id="error-message" class="error"></div>

        <h2>API Keys</h2>
        <p>Add or update your API keys for third-party services:</p>

        <form id="api-keys-form">
            <div class="form-group">
                <label for="fathom_key">Fathom API Key</label>
                <input type="text" id="fathom_key" name="fathom_key"
                       value="{api_keys.get('fathom', '')}"
                       placeholder="Your Fathom API key">
            </div>

            <div class="form-group">
                <label for="instantly_key">Instantly API Key</label>
                <input type="text" id="instantly_key" name="instantly_key"
                       value="{api_keys.get('instantly', '')}"
                       placeholder="Your Instantly.ai API key">
            </div>

            <div class="form-group">
                <label for="bison_key">Bison API Key</label>
                <input type="text" id="bison_key" name="bison_key"
                       value="{api_keys.get('bison', '')}"
                       placeholder="Your EmailBison API key">
            </div>

            <button type="submit">💾 Save API Keys</button>
        </form>

        <hr style="margin: 40px 0; border: none; border-top: 1px solid #ddd;">

        <h2>🛠️ Tool Selection</h2>
        <p>Choose which tool categories you want available in Claude Desktop:</p>

        <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 16px; border-radius: 8px; margin-bottom: 20px;">
            <div style="display: flex; align-items: start; gap: 12px;">
                <div style="font-size: 24px;">⚠️</div>
                <div>
                    <strong style="color: #856404; font-size: 15px;">Important: Restart Required</strong>
                    <div style="color: #856404; margin-top: 6px; font-size: 14px;">
                        After saving tool preferences, you <strong>must restart Claude Desktop</strong> to see changes. This is an MCP protocol limitation.
                    </div>
                </div>
            </div>
        </div>

        <div class="tools-info" style="background: #f0f7ff; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
            <strong>Currently showing: <span id="tool-count">{total_tools}</span> tools</strong>
        </div>

        <!-- Manage Billing Button -->
        <div style="margin-bottom: 30px; text-align: center;">
            <a href="/billing?session_token={session_token}" style="display: inline-block; padding: 12px 24px; background: #6c757d; color: white; text-decoration: none; border-radius: 6px; font-weight: 600;">
                💳 Manage Billing & Subscriptions
            </a>
        </div>

        <form id="tool-categories-form">
            <div style="display: grid; gap: 15px;">
                <label class="category-checkbox" style="display: flex; justify-content: space-between; align-items: center; padding: 15px; border: 1px solid #ddd; border-radius: 8px;">
                    <div style="flex: 1;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <input type="checkbox" name="gmail" {enabled_categories_str.get('gmail', 'checked')}>
                            <span>📧 <strong>Gmail Tools</strong> (25 tools)</span>
                            {subscription_badges['gmail']}
                        </div>
                        <div style="font-size: 13px; color: #666; margin-left: 28px;">Search, send, manage emails</div>
                    </div>
                </label>

                <label class="category-checkbox" style="display: flex; justify-content: space-between; align-items: center; padding: 15px; border: 1px solid #ddd; border-radius: 8px;">
                    <div style="flex: 1;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <input type="checkbox" name="calendar" {enabled_categories_str.get('calendar', 'checked')}>
                            <span>📅 <strong>Calendar Tools</strong> (15 tools)</span>
                            {subscription_badges['calendar']}
                        </div>
                        <div style="font-size: 13px; color: #666; margin-left: 28px;">Create events, check availability</div>
                    </div>
                </label>

                <label class="category-checkbox" style="display: flex; justify-content: space-between; align-items: center; padding: 15px; border: 1px solid #ddd; border-radius: 8px;">
                    <div style="flex: 1;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <input type="checkbox" name="docs" {enabled_categories_str.get('docs', 'checked')}>
                            <span>📄 <strong>Google Docs Tools</strong> (8 tools)</span>
                            {subscription_badges['docs']}
                        </div>
                        <div style="font-size: 13px; color: #666; margin-left: 28px;">Create, read, update documents</div>
                    </div>
                </label>

                <label class="category-checkbox" style="display: flex; justify-content: space-between; align-items: center; padding: 15px; border: 1px solid #ddd; border-radius: 8px;">
                    <div style="flex: 1;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <input type="checkbox" name="sheets" {enabled_categories_str.get('sheets', 'checked')}>
                            <span>📊 <strong>Google Sheets Tools</strong> (12 tools)</span>
                            {subscription_badges['sheets']}
                        </div>
                        <div style="font-size: 13px; color: #666; margin-left: 28px;">Read, write, manage spreadsheets</div>
                    </div>
                </label>

                <label class="category-checkbox" style="display: flex; justify-content: space-between; align-items: center; padding: 15px; border: 1px solid #ddd; border-radius: 8px;">
                    <div style="flex: 1;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <input type="checkbox" name="fathom" {enabled_categories_str.get('fathom', 'checked')}>
                            <span>🎥 <strong>Fathom Tools</strong> (10 tools)</span>
                            {subscription_badges['fathom']}
                        </div>
                        <div style="font-size: 13px; color: #666; margin-left: 28px;">Meeting recordings & analytics</div>
                        <div style="font-size: 12px; color: #999; margin-left: 28px;">💡 Requires Fathom API key</div>
                    </div>
                </label>

                <label class="category-checkbox" style="display: flex; justify-content: space-between; align-items: center; padding: 15px; border: 1px solid #ddd; border-radius: 8px;">
                    <div style="flex: 1;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <input type="checkbox" name="instantly" {enabled_categories_str.get('instantly', 'checked')}>
                            <span>📨 <strong>Instantly Tools</strong> (10 tools)</span>
                            {subscription_badges['instantly']}
                        </div>
                        <div style="font-size: 13px; color: #666; margin-left: 28px;">Email campaigns & lead management (Instantly.ai)</div>
                        <div style="font-size: 12px; color: #999; margin-left: 28px;">💡 Requires Instantly API key</div>
                    </div>
                </label>

                <label class="category-checkbox" style="display: flex; justify-content: space-between; align-items: center; padding: 15px; border: 1px solid #ddd; border-radius: 8px;">
                    <div style="flex: 1;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <input type="checkbox" name="bison" {enabled_categories_str.get('bison', 'checked')}>
                            <span>🦬 <strong>Bison Tools</strong> (4 tools)</span>
                            {subscription_badges['bison']}
                        </div>
                        <div style="font-size: 13px; color: #666; margin-left: 28px;">Email campaigns & lead management (EmailBison)</div>
                        <div style="font-size: 12px; color: #999; margin-left: 28px;">💡 Requires Bison API key</div>
                    </div>
                </label>
            </div>

            <button type="submit" style="margin-top: 20px;">💾 Save Tool Preferences</button>
        </form>

        <div class="token-section">
            <h2>Session Token</h2>
            <p>Use this token in Claude Desktop to connect to your MCP server:</p>
            <code>{session_token}</code>
        </div>
    </div>

    <script>
        // Toast notification function
        function showToast(message, type = 'success') {{
            // Create toast element
            const toast = document.createElement('div');
            toast.className = 'toast' + (type === 'error' ? ' error' : '');
            toast.textContent = message;

            // Add to document
            document.body.appendChild(toast);

            // Auto-remove after animation
            setTimeout(() => {{
                toast.style.animation = 'toastSlideOut 0.4s ease-out';
                setTimeout(() => {{
                    document.body.removeChild(toast);
                }}, 400);
            }}, 4000);
        }}

        document.getElementById('api-keys-form').addEventListener('submit', async (e) => {{
            e.preventDefault();

            const fathomKey = document.getElementById('fathom_key').value;
            const instantlyKey = document.getElementById('instantly_key').value;
            const bisonKey = document.getElementById('bison_key').value;

            const response = await fetch('/dashboard/update-api-keys?session_token={session_token}', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    fathom: fathomKey,
                    instantly: instantlyKey,
                    bison: bisonKey
                }})
            }});

            const successDiv = document.getElementById('success-message');
            const errorDiv = document.getElementById('error-message');

            if (response.ok) {{
                // Show toast notification
                showToast('✅ API keys updated successfully! Changes apply immediately (no restart needed).');

                // Also show inline message
                successDiv.textContent = '✅ API keys updated successfully! Changes apply immediately - no restart needed.';
                successDiv.style.display = 'block';
                errorDiv.style.display = 'none';
                setTimeout(() => {{ successDiv.style.display = 'none'; }}, 4000);
            }} else {{
                const error = await response.json();
                const errorMsg = '❌ Error: ' + error.detail;

                // Show toast notification
                showToast(errorMsg, 'error');

                // Also show inline message
                errorDiv.textContent = errorMsg;
                errorDiv.style.display = 'block';
                successDiv.style.display = 'none';
            }}
        }});

        // Tool categories form handler
        document.getElementById('tool-categories-form').addEventListener('submit', async (e) => {{
            e.preventDefault();

            const form = e.target;
            const formData = new FormData(form);
            const categories = [];

            // Collect checked categories
            for (let [key, value] of formData.entries()) {{
                if (form.elements[key].checked) {{
                    categories.push(key);
                }}
            }}

            const response = await fetch('/dashboard/update-tool-categories?session_token={session_token}', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    categories: categories
                }})
            }});

            const successDiv = document.getElementById('success-message');
            const errorDiv = document.getElementById('error-message');

            if (response.ok) {{
                const data = await response.json();
                const successMsg = `✅ Tool preferences saved! Now showing ${{data.tool_count}} tools.`;
                const reminderMsg = '⚠️ IMPORTANT: You must restart Claude Desktop to see these changes (MCP protocol limitation).';

                // Show prominent toast notification
                showToast(successMsg + ' ' + reminderMsg);

                // Also show inline message
                successDiv.innerHTML = `<strong>${{successMsg}}</strong><br><strong style="color: #856404;">${{reminderMsg}}</strong>`;
                successDiv.style.display = 'block';
                errorDiv.style.display = 'none';

                // Update tool count display
                document.getElementById('tool-count').textContent = data.tool_count;

                setTimeout(() => {{ successDiv.style.display = 'none'; }}, 6000);
            }} else {{
                const error = await response.json();
                const errorMsg = '❌ Error: ' + error.detail;

                // Show toast notification
                showToast(errorMsg, 'error');

                // Also show inline message
                errorDiv.textContent = errorMsg;
                errorDiv.style.display = 'block';
                successDiv.style.display = 'none';
            }}
        }});

        // Update tool count dynamically as user checks/unchecks
        const toolCounts = {{gmail: 25, calendar: 15, docs: 8, sheets: 12, fathom: 10, instantly: 10, bison: 4}};
        document.querySelectorAll('.category-checkbox input').forEach(checkbox => {{
            checkbox.addEventListener('change', () => {{
                let total = 0;
                document.querySelectorAll('.category-checkbox input:checked').forEach(checked => {{
                    total += toolCounts[checked.name] || 0;
                }});
                document.getElementById('tool-count').textContent = total;
            }});
        }});
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
    tool_counts = {'gmail': 25, 'calendar': 15, 'docs': 8, 'sheets': 12, 'fathom': 10, 'instantly': 10, 'bison': 4}
    total_tools = sum(tool_counts[cat] for cat in categories) if categories else 0

    logger.info(f"Updated tool categories for user {ctx.email}: {categories} ({total_tools} tools)")

    return {
        "success": True,
        "message": "Tool preferences updated",
        "tool_count": total_tools,
        "categories": categories
    }


# ===========================================================================
# SUBSCRIPTION & BILLING ENDPOINTS
# ===========================================================================

@app.get("/subscribe")
async def subscribe_to_category(
    category: str = Query(..., description="Tool category to subscribe to"),
    session_token: Optional[str] = Query(None)
):
    """
    Create Stripe Checkout session for subscribing to a tool category.

    Args:
        category: Tool category ('gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison')
        session_token: User's session token

    Returns:
        Redirect to Stripe Checkout
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
        raise HTTPException(400, f"Invalid category. Must be one of: {', '.join(valid_categories)}")

    # Check if already subscribed
    if server.database.has_active_subscription(ctx.user_id, category):
        return RedirectResponse(
            url=f"/dashboard?session_token={session_token}&error=already_subscribed",
            status_code=303
        )

    # Initialize Stripe
    stripe.api_key = server.config.stripe_secret_key

    # Get or create Stripe customer
    stripe_customer_id = server.database.get_stripe_customer_id(ctx.user_id)

    if not stripe_customer_id:
        # Create new Stripe customer
        customer = stripe.Customer.create(
            email=ctx.email,
            metadata={'user_id': ctx.user_id}
        )
        stripe_customer_id = customer.id
        logger.info(f"Created Stripe customer {stripe_customer_id} for user {ctx.email}")

    # Get price ID for category
    try:
        price_id = server.config.get_stripe_price_id(category)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Get deployment URL for success/cancel redirects
    deployment_url = os.getenv("RAILWAY_PUBLIC_DOMAIN", os.getenv("DEPLOYMENT_URL", "http://localhost:8000"))
    if not deployment_url.startswith("http"):
        deployment_url = f"https://{deployment_url}"

    # Create Checkout session
    try:
        checkout_session = stripe.checkout.Session.create(
            customer=stripe_customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1
            }],
            mode='subscription',
            success_url=f"{deployment_url}/dashboard?session_token={session_token}&subscription_success=true",
            cancel_url=f"{deployment_url}/dashboard?session_token={session_token}&subscription_cancelled=true",
            metadata={
                'user_id': ctx.user_id,
                'tool_category': category
            }
        )

        logger.info(f"Created checkout session for user {ctx.email}, category {category}")

        # Redirect to Stripe Checkout
        return RedirectResponse(url=checkout_session.url, status_code=303)

    except Exception as e:
        logger.error(f"Error creating checkout session: {e}")
        raise HTTPException(500, "Failed to create checkout session")


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

    if not webhook_secret:
        logger.warning("Stripe webhook secret not configured - skipping signature verification")
        event = json.loads(payload)
    else:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        except ValueError:
            logger.error("Invalid webhook payload")
            raise HTTPException(400, "Invalid payload")
        except stripe.error.SignatureVerificationError:
            logger.error("Invalid webhook signature")
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
        category = session['metadata'].get('tool_category')

        if not all([subscription_id, customer_id, user_id, category]):
            logger.error(f"Missing required fields in checkout.session.completed: {session}")
            return JSONResponse({"status": "error", "message": "Missing required fields"})

        # Retrieve the subscription to get period info
        subscription = stripe.Subscription.retrieve(subscription_id)

        # Create subscription in database
        server.database.create_subscription(
            user_id=user_id,
            tool_category=category,
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
            status='active',
            current_period_start=datetime.fromtimestamp(subscription.current_period_start),
            current_period_end=datetime.fromtimestamp(subscription.current_period_end)
        )

        logger.info(f"Created subscription for user {user_id}, category {category}")

    elif event_type == 'customer.subscription.updated':
        # Subscription updated (renewed, changed, etc.)
        subscription = data
        subscription_id = subscription['id']
        status = subscription['status']

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

        our_status = status_map.get(status, 'cancelled')

        server.database.update_subscription_status(
            stripe_subscription_id=subscription_id,
            status=our_status,
            current_period_start=datetime.fromtimestamp(subscription.current_period_start),
            current_period_end=datetime.fromtimestamp(subscription.current_period_end)
        )

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

    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>Admin Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root {
            --background: 0 0% 100%;
            --foreground: 222.2 84% 4.9%;
            --card: 0 0% 100%;
            --primary: 221.2 83.2% 53.3%;
            --primary-foreground: 210 40% 98%;
            --radius: 0.5rem;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            max-width: 500px;
            margin: 100px auto;
            padding: 20px;
            background: linear-gradient(135deg, hsl(var(--primary)) 0%, hsl(262 83% 58%) 100%);
            min-height: 100vh;
        }
        .login-card {
            background: hsl(var(--card));
            padding: 40px;
            border-radius: calc(var(--radius) * 2);
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }
        h1 {
            color: hsl(var(--foreground));
            margin-bottom: 10px;
            font-size: 28px;
        }
        .subtitle {
            color: hsl(215.4 16.3% 46.9%);
            margin-bottom: 30px;
            font-size: 14px;
        }
        input {
            width: 100%;
            padding: 12px;
            border: 2px solid hsl(214.3 31.8% 91.4%);
            border-radius: var(--radius);
            font-size: 16px;
            box-sizing: border-box;
            margin-bottom: 20px;
        }
        input:focus {
            outline: none;
            border-color: hsl(var(--primary));
        }
        button {
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
        }
        button:hover {
            opacity: 0.9;
        }
        .error-msg {
            background: hsl(0 84.2% 60.2% / 0.1);
            color: hsl(0 84.2% 60.2%);
            padding: 12px;
            border-radius: var(--radius);
            margin-bottom: 20px;
            font-size: 14px;
            text-align: center;
        }
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
            <tr class="user-row" onclick="window.location.href='/admin/user/{user['user_id']}'">
                <td style="padding: 16px; border-bottom: 1px solid hsl(var(--border)); font-weight: 500;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <div class="user-avatar">{user['email'][0].upper()}</div>
                        <div>{user['email']}</div>
                    </div>
                </td>
                <td style="padding: 16px; border-bottom: 1px solid hsl(var(--border)); text-align: center;">{sub_badge}</td>
                <td style="padding: 16px; border-bottom: 1px solid hsl(var(--border)); text-align: center;">{api_keys_badge}</td>
                <td style="padding: 16px; border-bottom: 1px solid hsl(var(--border)); font-size: 14px; color: hsl(var(--muted-foreground));">{last_active}</td>
                <td style="padding: 16px; border-bottom: 1px solid hsl(var(--border)); text-align: right;">
                    <button class="action-btn" onclick="event.stopPropagation(); window.location.href='/admin/user/{user['user_id']}'">View</button>
                </td>
            </tr>
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
                {(''.join([f'<div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #e5e7eb;"><span style="font-weight: 500; text-transform: capitalize;">📦 {{category}}</span><span style="color: #10b981; font-weight: 600;">{{count}} subscriptions (${{{count * 5}}}/mo)</span></div>' for category, count in subscription_stats['category_breakdown'].items()]) if subscription_stats['category_breakdown'] else '<p style="color: #6b7280; text-align: center;">No subscriptions yet</p>')}
            </div>
        </div>

        <div class="section">
            <h2><span>👥</span> All Users</h2>
            <table>
                <thead>
                    <tr>
                        <th>User</th>
                        <th style="text-align: center;">Subscription</th>
                        <th style="text-align: center;">API Keys</th>
                        <th>Last Active</th>
                        <th style="text-align: right;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {users_html if users_html else '<tr><td colspan="5" style="padding: 20px; text-align: center; color: hsl(var(--muted-foreground));">No users yet</td></tr>'}
                </tbody>
            </table>
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
        tool_counts = {'gmail': 25, 'calendar': 15, 'docs': 8, 'sheets': 12, 'fathom': 10, 'instantly': 10, 'bison': 4}
        if enabled_categories is None:
            total_tools = 84
            tool_status = "All tools enabled"
        elif len(enabled_categories) == 0:
            total_tools = 0
            tool_status = "No tools enabled"
        else:
            total_tools = sum(tool_counts.get(cat, 0) for cat in enabled_categories)
            tool_status = f"{len(enabled_categories)}/7 categories enabled"

        # Get usage stats
        usage_stats = server.database.get_user_usage_stats(user_id, days=30)

        # Get subscription info
        subscription_info = server.database.get_user_subscription_summary(user_id)

        # Get recent activity
        recent_logs = server.database.supabase.table('usage_logs').select('*').eq('user_id', user_id).order('timestamp', desc=True).limit(20).execute()

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

        # Build tool categories badges
        tool_categories_html = ""
        all_categories = ['gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison']
        if enabled_categories is None:
            for cat in all_categories:
                tool_categories_html += f'<span class="badge badge-success">{cat.title()} ({tool_counts[cat]})</span> '
        else:
            for cat in all_categories:
                if cat in enabled_categories:
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
                <h2><span>🛠️</span> Tool Preferences</h2>
                <div class="stat-row">
                    <span class="stat-label">Status</span>
                    <span class="stat-value">{tool_status}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Total Tools</span>
                    <span class="stat-value">{total_tools} / 84</span>
                </div>
                <div style="margin-top: 16px;">
                    {tool_categories_html}
                </div>
            </div>

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
        </div>

        <div class="card">
            <h2><span>🔄</span> Recent Activity (Last 15)</h2>
            <div class="timeline">
                {activity_timeline if activity_timeline else '<p style="color: hsl(var(--muted-foreground)); text-align: center; padding: 20px;">No recent activity</p>'}
            </div>
        </div>
    </div>
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
