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
    """Landing page - Product-focused marketing."""
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>84 AI Tools for Claude Desktop - Gmail, Calendar, Docs & More</title>
    <meta name="description" content="Access 84 powerful tools directly in Claude Desktop. Manage Gmail, Google Calendar, Docs, Sheets, Fathom, Instantly, and more. 3-day free trial.">
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

        /* Hero Section */
        .hero {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 80px 20px 60px;
            text-align: center;
        }

        .hero-content {
            max-width: 900px;
            margin: 0 auto;
        }

        h1 {
            font-size: 3.5rem;
            font-weight: 800;
            margin-bottom: 20px;
            line-height: 1.2;
        }

        .subtitle {
            font-size: 1.5rem;
            margin-bottom: 15px;
            opacity: 0.95;
            font-weight: 400;
        }

        .trial-badge {
            display: inline-block;
            background: rgba(255, 255, 255, 0.25);
            padding: 12px 28px;
            border-radius: 30px;
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 40px;
            border: 2px solid rgba(255, 255, 255, 0.3);
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
            padding: 20px 50px;
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
            padding: 20px 50px;
            font-size: 1.3rem;
            font-weight: 700;
            text-decoration: none;
            border-radius: 50px;
            transition: all 0.3s;
            border: 3px solid white;
        }

        .cta-button-secondary:hover {
            background: rgba(255, 255, 255, 0.1);
            transform: translateY(-3px);
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
            width: 60px;
            height: 60px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            font-weight: 700;
            margin: 0 auto 20px;
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

        @media (max-width: 768px) {
            h1 {
                font-size: 2.5rem;
            }

            .subtitle {
                font-size: 1.2rem;
            }

            .tool-categories {
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
        }
    </style>
</head>
<body>
    <!-- Hero Section -->
    <div class="hero">
        <div class="hero-content">
            <h1>84 AI Tools for Claude Desktop</h1>
            <p class="subtitle">Access Gmail, Google Calendar, Docs, Sheets, Fathom, Instantly & more—all without leaving Claude.</p>
            <div class="trial-badge">🎉 3-Day Free Trial • No Credit Card Required</div>
            <div class="cta-buttons">
                <a href="/signup" class="cta-button">Sign Up Free →</a>
                <a href="/login" class="cta-button-secondary">Log In</a>
            </div>
        </div>
    </div>

    <!-- Tool Categories Section -->
    <div class="container">
        <div class="section-header">
            <h2>All 84 Tools, Organized by Category</h2>
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
            </div>

            <!-- Fathom Tools -->
            <div class="category-card">
                <div class="category-icon">🎙️</div>
                <h3>Fathom Meetings</h3>
                <div class="tool-count">10 tools included</div>
                <ul class="tool-list">
                    <li>Access meeting recordings</li>
                    <li>Read AI-generated transcripts</li>
                    <li>Extract key points and action items</li>
                    <li>Search across all meetings</li>
                    <li>Get meeting summaries</li>
                    <li>Analyze conversation insights</li>
                </ul>
                <div class="category-price">$5/month</div>
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
                    <li>All 84 tools unlocked</li>
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
                    <li>All 84 tools included</li>
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
        <h2>Ready to supercharge Claude Desktop?</h2>
        <p>Start your 3-day free trial. No credit card required.</p>
        <div class="cta-buttons">
            <a href="/signup" class="cta-button">Sign Up Free →</a>
            <a href="/login" class="cta-button-secondary">Log In</a>
        </div>
    </div>
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


@app.get("/signup/start")
async def signup_start(request: Request):
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
            'flow_type': 'signup'  # Track that this is a signup flow
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
async def login_start(request: Request):
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
            'flow_type': 'login'  # Track that this is a login flow
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
        <p class="subtitle">Start your 3-day free trial with all 84 tools unlocked</p>

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
    """Handle email/password signup submission."""
    try:
        # Parse form data
        form_data = await request.form()
        email = form_data.get('email', '').strip()
        name = form_data.get('name', '').strip() or None
        password = form_data.get('password', '')
        confirm_password = form_data.get('confirm_password', '')

        # Validate inputs
        if not email or not password:
            return RedirectResponse(
                url=f"/signup?error=Email and password are required",
                status_code=303
            )

        if password != confirm_password:
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
            return RedirectResponse(
                url=f"/signup?error={str(e)}",
                status_code=303
            )

        logger.info(f"New email/password signup: {email}")

        # Redirect to dashboard with welcome message
        first_name = name.split()[0] if name else email.split('@')[0]
        return RedirectResponse(
            url=f"/dashboard?session_token={user_data['session_token']}&is_new_user=True&first_name={first_name}",
            status_code=303
        )

    except Exception as e:
        logger.error(f"Signup error: {e}")
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

        # Redirect to dashboard with welcome message type
        return RedirectResponse(
            url=f"/dashboard?session_token={session_token}&is_new_user={is_new_user}&first_name={first_name}",
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
    first_name: Optional[str] = Query(None)
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

    # Get trial status and usage info
    trial_status = server.database.check_trial_status(ctx.user_id)
    daily_usage = server.database.get_daily_usage(ctx.user_id)

    # Get active subscriptions (category names only)
    active_subscriptions = server.database.get_active_subscriptions(ctx.user_id)

    # Get full subscription details (for showing cancellation info)
    all_subscriptions = server.database.get_user_subscriptions(ctx.user_id)
    subscription_details = {sub['tool_category']: sub for sub in all_subscriptions if sub['status'] == 'active'}

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
    tool_counts = {'gmail': 25, 'calendar': 15, 'docs': 8, 'sheets': 12, 'fathom': 10, 'instantly': 10, 'bison': 4}
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
        'fathom': {'emoji': '🎥', 'name': 'Fathom Tools', 'tools': 10, 'desc': 'Meeting recordings & analytics', 'note': '💡 Requires Fathom API key'},
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
        <!-- Page Header -->
        <div style="background: white; padding: 25px 30px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 30px;">
            <h1 style="font-size: 2rem; color: #1a202c; margin-bottom: 8px;">Welcome back!</h1>
            <p style="color: #718096; font-size: 1.1rem; margin: 0;">Manage your subscriptions and connect to Claude Desktop</p>
        </div>

        <!-- Welcome/Success Banners -->
        {f'''
        <div style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: white; padding: 25px; border-radius: 12px; margin-bottom: 30px; animation: bannerSlideDown 0.5s ease-out;">
            <div style="font-size: 32px; margin-bottom: 10px;">🎉</div>
            <h2 style="color: white; margin: 0 0 10px 0; font-size: 24px;">Welcome{f", {first_name}" if first_name else ""}! Your 3-day trial starts now!</h2>
            <p style="margin: 0; font-size: 16px; opacity: 0.95;">All 84 tools are unlocked! Explore Gmail, Calendar, Docs, Sheets, Fathom, Instantly & more—completely free for 3 days.</p>
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
                        All 84 tools are unlocked! Subscribe before your trial ends to keep unlimited access.
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

            <!-- Available Subscriptions -->
            <div style="background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 30px;">
                <h2 style="font-size: 1.5rem; color: #1a202c; margin-bottom: 10px;">Subscribe to More Tools</h2>
                <p style="color: #718096; margin-bottom: 25px;">Select categories to add ($5/month each)</p>

                <div id="subscription-cart" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 15px; margin-bottom: 30px;">
                    {''.join([f'''
                        <label class="subscription-item" style="display: flex; flex-direction: column; padding: 20px; border: 2px solid {"#10b981" if cat in active_subscriptions else "#e2e8f0"}; border-radius: 12px; cursor: {"not-allowed" if cat in active_subscriptions else "pointer"}; background: {"#f0fdf4" if cat in active_subscriptions else "white"}; transition: all 0.2s;">
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 15px;">
                                <span style="font-size: 36px;">{category_info[cat]["emoji"]}</span>
                                {f'<span style="background: #d1fae5; color: #065f46; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600;">✓ Subscribed</span>' if cat in active_subscriptions else '<input type="checkbox" name="subscribe-{cat}" value="{cat}" class="subscription-checkbox" style="width: 22px; height: 22px; cursor: pointer;">'}
                            </div>
                            <h3 style="margin: 0 0 8px 0; font-size: 18px; color: #1a202c;">{category_info[cat]["name"]}</h3>
                            <p style="margin: 0 0 12px 0; font-size: 14px; color: #6b7280; flex: 1;">{category_info[cat]["desc"]}</p>
                            <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 12px; border-top: 1px solid #e2e8f0;">
                                <span style="font-size: 13px; color: #9ca3af;">{category_info[cat]["tools"]} tools</span>
                                <span style="font-size: 16px; font-weight: 700; color: #667eea;">$5/mo</span>
                            </div>
                            {f'<div style="font-size: 12px; color: #f59e0b; margin-top: 8px;">{category_info[cat].get("note", "")}</div>' if cat in ['fathom', 'instantly', 'bison'] and cat not in active_subscriptions else ''}
                        </label>
                    ''' for cat in all_categories if cat not in active_subscriptions])}
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

        function updateCart() {{
            if (cart.size > 0) {{
                cartSummary.style.display = 'block';
                cartTotal.textContent = cart.size * 5;
                cartCount.textContent = cart.size;
                cartItemsList.innerHTML = Array.from(cart).map(cat => `• ${{categoryNames[cat]}} - $5/mo`).join('<br>');
            }} else {{
                cartSummary.style.display = 'none';
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

        checkoutBtn.addEventListener('click', async () => {{
            if (cart.size === 0) return;
            const categories = Array.from(cart);

            try {{
                const response = await fetch('/subscribe?session_token={session_token}', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ categories: categories }})
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
    categories: str = Query(..., description="Comma-separated list of tool categories to subscribe to"),
    session_token: Optional[str] = Query(None)
):
    """
    Create Stripe Checkout session for subscribing to tool categories.
    Supports multiple categories in shopping cart style.

    Args:
        categories: Comma-separated categories ('gmail,calendar,docs')
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

    # Parse and validate categories
    valid_categories = ['gmail', 'calendar', 'docs', 'sheets', 'fathom', 'instantly', 'bison']
    category_list = [cat.strip() for cat in categories.split(',') if cat.strip()]

    if not category_list:
        raise HTTPException(400, "No categories provided")

    for cat in category_list:
        if cat not in valid_categories:
            raise HTTPException(400, f"Invalid category '{cat}'. Must be one of: {', '.join(valid_categories)}")

    # Filter out already subscribed categories
    categories_to_subscribe = [cat for cat in category_list if not server.database.has_active_subscription(ctx.user_id, cat)]

    if not categories_to_subscribe:
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
        checkout_session = stripe.checkout.Session.create(
            customer=stripe_customer_id,
            payment_method_types=['card'],
            line_items=line_items,
            mode='subscription',
            success_url=f"{deployment_url}/dashboard?session_token={session_token}&subscription_success=true",
            cancel_url=f"{deployment_url}/dashboard?session_token={session_token}&subscription_cancelled=true",
            metadata={
                'user_id': ctx.user_id,
                'tool_categories': ','.join(categories_to_subscribe)  # Store all categories
            }
        )

        logger.info(f"Created checkout session for user {ctx.email}, categories: {', '.join(categories_to_subscribe)}")

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
        tool_categories = session['metadata'].get('tool_categories')  # Comma-separated string

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
            server.database.create_subscription(
                user_id=user_id,
                tool_category=category,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                status='active',
                current_period_start=current_period_start,
                current_period_end=current_period_end
            )
            logger.info(f"Created subscription for user {user_id}, category {category}")

        logger.info(f"Successfully processed checkout for {len(categories)} categories: {', '.join(categories)}")

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
                {(''.join([f'<div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #e5e7eb;"><span style="font-weight: 500; text-transform: capitalize;">📦 {category}</span><span style="color: #10b981; font-weight: 600;">{count} subscriptions (${count * 5}/mo)</span></div>' for category, count in subscription_stats['category_breakdown'].items()]) if subscription_stats['category_breakdown'] else '<p style="color: #6b7280; text-align: center;">No subscriptions yet</p>')}
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

        # Get detailed subscription info for management
        all_subscriptions = server.database.get_user_subscriptions(user_id)
        active_categories = [sub['tool_category'] for sub in all_subscriptions if sub['status'] == 'active']

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

    <script>
        async function toggleSubscription(userId, category, isCurrentlyActive) {{
            const messageDiv = document.getElementById('subscription-message');
            const action = isCurrentlyActive ? 'remove' : 'add';

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
                    messageDiv.textContent = `✓ ${{action === 'add' ? 'Added' : 'Removed'}} ${{category}} subscription successfully!`;
                    messageDiv.style.display = 'block';
                    messageDiv.style.background = 'hsl(var(--success) / 0.1)';
                    messageDiv.style.color = 'hsl(var(--success))';

                    // Reload page after 1 second
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
        "category": "gmail" | "calendar" | "docs" | "sheets" | "fathom" | "instantly" | "bison"
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
            # Check if already subscribed
            existing = server.database.supabase.table('subscriptions').select('*').eq(
                'user_id', user_id
            ).eq('tool_category', category).eq('status', 'active').execute()

            if existing.data:
                return JSONResponse({
                    "status": "already_exists",
                    "message": f"User already has an active {category} subscription"
                })

            # Get or create Stripe customer
            stripe_customer_id = server.database.get_stripe_customer_id(user_id)

            if not stripe_customer_id:
                # Create Stripe customer
                stripe.api_key = server.config.stripe_secret_key
                customer = stripe.Customer.create(
                    email=user_data['email'],
                    metadata={'user_id': user_id}
                )
                stripe_customer_id = customer.id

                # Save to database
                server.database.supabase.table('users').update({
                    'stripe_customer_id': stripe_customer_id
                }).eq('user_id', user_id).execute()

            # Create subscription manually (bypass Stripe for admin-added)
            import secrets
            fake_subscription_id = f"admin_{secrets.token_urlsafe(16)}"

            server.database.create_subscription(
                user_id=user_id,
                tool_category=category,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=fake_subscription_id,
                status='active',
                current_period_start=datetime.now(),
                current_period_end=datetime.now() + timedelta(days=365)  # 1 year for admin-added
            )

            logger.info(f"Admin added {category} subscription for user {user_id}")

            return JSONResponse({
                "status": "success",
                "message": f"Added {category} subscription",
                "subscription_id": fake_subscription_id
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

            # Update status to cancelled
            server.database.supabase.table('subscriptions').update({
                'status': 'cancelled',
                'cancelled_at': datetime.now().isoformat()
            }).eq('subscription_id', subscription['subscription_id']).execute()

            logger.info(f"Admin removed {category} subscription for user {user_id}")

            return JSONResponse({
                "status": "success",
                "message": f"Removed {category} subscription"
            })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling subscription: {e}")
        import traceback
        traceback.print_exc()
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
