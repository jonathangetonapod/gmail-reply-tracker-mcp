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

from fastapi import FastAPI, Request, Header, Query, HTTPException
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


def create_session(transport_type: str) -> str:
    """
    Create a new MCP session.

    Args:
        transport_type: "sse" or "streamable_http"

    Returns:
        session_id: UUID string
    """
    session_id = str(uuid4())
    sessions[session_id] = MCPSession(
        session_id=session_id,
        created_at=datetime.now(),
        last_activity=datetime.now(),
        transport_type=transport_type
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

        # Temporarily replace with user's clients
        server_module.gmail_client = ctx.gmail_client
        server_module.calendar_client = ctx.calendar_client
        server_module.docs_client = ctx.docs_client
        server_module.sheets_client = ctx.sheets_client
        server_module.fathom_client = ctx.fathom_client

        logger.info(f"Executing tool '{tool_name}' for user {ctx.email}")

        # Execute tool (will use injected user-specific clients)
        result = await server.mcp.call_tool(tool_name, arguments)

        # Restore original global clients
        server_module.gmail_client = original_gmail
        server_module.calendar_client = original_calendar
        server_module.docs_client = original_docs
        server_module.sheets_client = original_sheets
        server_module.fathom_client = original_fathom

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
    authorization: Optional[str] = Header(None)
) -> RequestContext:
    """
    FastAPI dependency that extracts session token and creates per-user context.

    This middleware:
    1. Extracts the Authorization header from the request
    2. Validates the session token format
    3. Looks up the user in the database
    4. Creates user-specific API clients (Gmail, Calendar, Docs, Sheets, Fathom)
    5. Returns a RequestContext with all user data and clients

    Args:
        authorization: Authorization header (format: "Bearer <session_token>")

    Returns:
        RequestContext with user-specific API clients

    Raises:
        HTTPException(401): If authorization is missing, invalid, or expired
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. Please add your session token."
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization format. Expected: Bearer <session_token>"
        )

    session_token = authorization[7:]  # Strip "Bearer " prefix

    # Check if database is initialized
    if not hasattr(server, 'database') or server.database is None:
        raise HTTPException(
            status_code=503,
            detail="Multi-tenant mode not available. Database not initialized."
        )

    # Create user-specific clients from database
    ctx = await create_request_context(
        database=server.database,
        session_token=session_token,
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

    # Initialize clients on startup (for backwards compatibility)
    try:
        server.initialize_clients()
        logger.info("✓ Clients initialized successfully")
    except Exception as e:
        logger.error(f"✗ Failed to initialize clients: {e}")
        logger.warning("Server will start but tools may not work until auth is set up")

    # Initialize database for multi-tenant support
    try:
        encryption_key = os.getenv("TOKEN_ENCRYPTION_KEY")
        if encryption_key:
            database_path = os.getenv("DATABASE_PATH", "./mcp_users.db")
            server.database = Database(database_path, encryption_key)
            logger.info(f"✓ Database initialized at {database_path}")
        else:
            logger.warning("⚠ TOKEN_ENCRYPTION_KEY not set - multi-tenant features disabled")
            logger.warning("⚠ Server will only work with legacy single-user mode")
            server.database = None
    except Exception as e:
        logger.error(f"✗ Failed to initialize database: {e}")
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
    authorization: Optional[str] = Header(None)
):
    """
    Modern Streamable HTTP transport (2025-03-26) with multi-tenant support.

    Single endpoint for all MCP operations. Session ID in header.
    Simpler than HTTP+SSE but same functionality.

    Multi-tenant mode:
    - Include Authorization: Bearer <session_token> header
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

    # Try to get user context if Authorization header present
    ctx = None
    if authorization:
        try:
            ctx = await get_request_context(authorization)
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
async def mcp_sse_stream(request: Request):
    """
    Legacy SSE stream endpoint (2024-11-05).

    Establishes a Server-Sent Events connection and sends the message endpoint URL.
    Clients then use POST /messages to send requests.
    """
    # Generate new session ID
    session_id = create_session("sse")

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

    # Handle the request
    response = await handle_jsonrpc_request(body, session_id)

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
            fathom_key=None  # Will be set later if needed
        )

        logger.info(f"User created/updated in database: {email} (ID: {user_data['user_id']})")

        # Get server URL for Claude config
        server_url = str(request.base_url).rstrip('/')
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

        function copyConfig() {{
            const configText = document.getElementById('config-content').textContent;
            navigator.clipboard.writeText(configText).then(() => {{
                const button = document.getElementById('copy-config-button');
                button.textContent = '✓ Copied!';
                button.style.background = '#4caf50';
                setTimeout(() => {{
                    button.textContent = '📋 Copy Config';
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

        <div class="instructions">
            <h2>🔧 Add to Claude Desktop</h2>
            <ol>
                <li>Open <strong>Claude Desktop</strong></li>
                <li>Go to <strong>Settings</strong> → <strong>Developer</strong> → <strong>Edit Config</strong></li>
                <li>Add this configuration to your <code>claude_desktop_config.json</code>:</li>
            </ol>

            <div class="config-box" id="config-content">{{
  "mcpServers": {{
    "gmail-mcp": {{
      "url": "{server_url}/mcp",
      "headers": {{
        "Authorization": "Bearer {session_token}"
      }}
    }}
  }}
}}</div>
            <button class="copy-button" id="copy-config-button" onclick="copyConfig()">📋 Copy Config</button>

            <ol start="4">
                <li><strong>Restart Claude Desktop</strong></li>
                <li>Start using your 82 Gmail & Calendar tools!</li>
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
