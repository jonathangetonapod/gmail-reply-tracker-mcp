"""Request context for multi-tenant MCP server.

This module provides per-request user context with isolated API clients.
Each request creates a new RequestContext with user-specific credentials.
"""

import logging
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from fastapi import HTTPException

from database import Database
from config import Config
from gmail_client import GmailClient
from calendar_client import CalendarClient
from docs_client import DocsClient
from sheets_client import SheetsClient
from fathom_client import FathomClient

logger = logging.getLogger(__name__)


@dataclass
class RequestContext:
    """Per-request user context with isolated API clients.

    Each request gets its own context with user-specific credentials
    and API clients. This ensures multi-tenant isolation.
    """
    user_id: str
    email: str
    gmail_client: GmailClient
    calendar_client: CalendarClient
    docs_client: DocsClient
    sheets_client: SheetsClient
    fathom_client: Optional[FathomClient]
    api_keys: dict  # Store all API keys for tools that need them


async def create_request_context(
    database: Database,
    session_token: str,
    config: Config
) -> RequestContext:
    """Create user-specific API clients for this request.

    This function:
    1. Looks up the user in the database using their session token
    2. Decrypts their stored Google OAuth tokens
    3. Creates user-specific API clients (Gmail, Calendar, Docs, Sheets, Fathom)
    4. Returns a RequestContext with all user data and clients

    Args:
        database: Database instance for user lookup
        session_token: User's session token from Authorization header
        config: Server configuration

    Returns:
        RequestContext with user-specific API clients

    Raises:
        HTTPException(401): If session token is invalid or expired
    """
    # Look up user in database
    try:
        user = database.get_user_by_session(session_token)
    except Exception as e:
        logger.error(f"Database error during user lookup: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error during authentication"
        )

    if not user:
        logger.warning(f"Invalid session token attempted")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session token"
        )

    # Check if session is expired
    session_expiry = user.get('session_expiry')
    if session_expiry:
        if isinstance(session_expiry, str):
            from dateutil import parser
            session_expiry = parser.parse(session_expiry)

        if datetime.now(timezone.utc) > session_expiry:
            logger.warning(f"Expired session token for user {user['email']}")
            raise HTTPException(
                status_code=401,
                detail="Session token has expired. Please re-authenticate."
            )

    # Reconstruct Google credentials from stored token
    google_token = user['google_token']

    # Handle expiry datetime
    expiry = google_token.get('expiry')
    if expiry and isinstance(expiry, str):
        from dateutil import parser
        expiry = parser.parse(expiry)

    try:
        credentials = Credentials(
            token=google_token['token'],
            refresh_token=google_token.get('refresh_token'),
            token_uri=google_token.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=google_token['client_id'],
            client_secret=google_token['client_secret'],
            scopes=google_token.get('scopes', config.oauth_scopes),
            expiry=expiry
        )
    except KeyError as e:
        logger.error(f"Missing required token field for user {user['email']}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Invalid stored credentials. Please re-authenticate."
        )

    # Check if token needs refresh
    if credentials.expired and credentials.refresh_token:
        logger.info(f"Refreshing expired token for user {user['email']}")
        try:
            from google.auth.transport.requests import Request
            credentials.refresh(Request())

            # Update token in database
            # IMPORTANT: Preserve original scopes - Google's refresh response
            # doesn't always include all scopes, only those used in the session
            updated_token = {
                'token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': google_token.get('scopes', config.oauth_scopes),  # Preserve original scopes
                'expiry': credentials.expiry.isoformat() if credentials.expiry else None
            }
            database.update_google_token(user['user_id'], updated_token)
            logger.info(f"Token refreshed and updated for user {user['email']}")

        except Exception as e:
            logger.error(f"Failed to refresh token for user {user['email']}: {e}")
            raise HTTPException(
                status_code=401,
                detail="Failed to refresh access token. Please re-authenticate."
            )

    # Create user-specific API clients
    try:
        gmail_client = GmailClient(credentials, config.max_requests_per_minute)
        calendar_client = CalendarClient(credentials, config.max_requests_per_minute)
        docs_client = DocsClient(credentials)
        sheets_client = SheetsClient(credentials)

        logger.info(f"Created API clients for user {user['email']}")
    except Exception as e:
        logger.error(f"Failed to create API clients for user {user['email']}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to initialize API clients"
        )

    # Create optional API clients from user's API keys
    api_keys = user.get('api_keys', {})

    fathom_client = None
    if api_keys.get('fathom'):
        try:
            fathom_client = FathomClient(api_keys['fathom'])
            logger.info(f"Created Fathom client for user {user['email']}")
        except Exception as e:
            logger.warning(f"Failed to create Fathom client for user {user['email']}: {e}")
            # Don't fail the request if Fathom client creation fails

    return RequestContext(
        user_id=user['user_id'],
        email=user['email'],
        gmail_client=gmail_client,
        calendar_client=calendar_client,
        docs_client=docs_client,
        sheets_client=sheets_client,
        fathom_client=fathom_client,
        api_keys=api_keys  # Store all API keys for tools that need them
    )
