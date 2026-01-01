"""Database models and management for multi-tenant MCP server."""

from supabase import create_client, Client
from cryptography.fernet import Fernet
import json
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class Database:
    """Manages Supabase PostgreSQL database for user sessions and credentials."""

    def __init__(self, supabase_url: str, supabase_key: str, encryption_key: str):
        """
        Initialize Supabase connection.

        Args:
            supabase_url: Supabase project URL
            supabase_key: Supabase service role key (not anon key!)
            encryption_key: Base64-encoded Fernet key for encrypting tokens
        """
        self.supabase: Client = create_client(supabase_url, supabase_key)
        self.cipher = Fernet(encryption_key.encode())
        logger.info(f"Connected to Supabase at {supabase_url}")

    def _encrypt(self, data: str) -> str:
        """Encrypt sensitive data."""
        return self.cipher.encrypt(data.encode()).decode()

    def _decrypt(self, encrypted_data: str) -> str:
        """Decrypt sensitive data."""
        return self.cipher.decrypt(encrypted_data.encode()).decode()

    def create_user(
        self,
        email: str,
        google_token: Dict[str, Any],
        api_keys: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Create a new user or update existing user.

        Args:
            email: User's email address
            google_token: Google OAuth token dictionary
            api_keys: Optional dict of API keys (e.g., {"fathom": "abc", "instantly": "xyz"})

        Returns:
            Dict with user_id, session_token, and email
        """
        # Generate IDs
        user_id = secrets.token_urlsafe(16)
        session_token = f"sess_{secrets.token_urlsafe(32)}"

        # Encrypt tokens
        encrypted_google_token = self._encrypt(json.dumps(google_token))
        encrypted_api_keys = self._encrypt(json.dumps(api_keys or {}))

        # Session expiry (90 days)
        session_expiry = (datetime.now() + timedelta(days=90)).isoformat()

        # Check if user exists
        result = self.supabase.table('users').select('user_id').eq('email', email).execute()

        if result.data:
            # Update existing user
            existing_user_id = result.data[0]['user_id']
            self.supabase.table('users').update({
                'encrypted_google_token': encrypted_google_token,
                'encrypted_api_keys': encrypted_api_keys,
                'session_token': session_token,
                'session_expiry': session_expiry,
                'last_login': datetime.now().isoformat()
            }).eq('email', email).execute()

            logger.info(f"Updated existing user: {email}")
            return {
                "user_id": existing_user_id,
                "session_token": session_token,
                "email": email
            }
        else:
            # Create new user
            self.supabase.table('users').insert({
                'user_id': user_id,
                'email': email,
                'encrypted_google_token': encrypted_google_token,
                'encrypted_api_keys': encrypted_api_keys,
                'session_token': session_token,
                'session_expiry': session_expiry
            }).execute()

            logger.info(f"Created new user: {email}")
            return {
                "user_id": user_id,
                "session_token": session_token,
                "email": email
            }

    def get_user_by_session(self, session_token: str) -> Optional[Dict[str, Any]]:
        """
        Get user information by session token.

        Args:
            session_token: Session token to look up

        Returns:
            User dict with decrypted credentials, or None if not found/expired
        """
        result = self.supabase.table('users').select('*').eq('session_token', session_token).execute()

        if not result.data:
            return None

        user = result.data[0]

        # Check if session expired
        session_expiry_str = user['session_expiry']
        # Handle both datetime objects and strings
        if isinstance(session_expiry_str, str):
            # Remove timezone info if present for comparison
            if '+' in session_expiry_str:
                session_expiry_str = session_expiry_str.split('+')[0]
            session_expiry = datetime.fromisoformat(session_expiry_str)
        else:
            session_expiry = session_expiry_str

        if datetime.now() > session_expiry:
            logger.warning(f"Session expired for user: {user['email']}")
            return None

        # Decrypt tokens
        google_token = json.loads(self._decrypt(user['encrypted_google_token']))
        api_keys = json.loads(self._decrypt(user['encrypted_api_keys'])) if user.get('encrypted_api_keys') else {}

        # Update last_active
        self.supabase.table('users').update({
            'last_active': datetime.now().isoformat()
        }).eq('user_id', user['user_id']).execute()

        return {
            "user_id": user['user_id'],
            "email": user['email'],
            "google_token": google_token,
            "api_keys": api_keys,  # Dict with all API keys
            "fathom_key": api_keys.get('fathom'),  # Backwards compatibility
            "session_token": user['session_token'],
            "session_expiry": user['session_expiry'],
            "created_at": user['created_at'],
            "last_login": user['last_login']
        }

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Get user information by email address.

        Args:
            email: Email address to look up

        Returns:
            User dict with decrypted credentials, or None if not found
        """
        result = self.supabase.table('users').select('*').eq('email', email).execute()

        if not result.data:
            return None

        user = result.data[0]

        # Decrypt tokens
        google_token = json.loads(self._decrypt(user['encrypted_google_token']))
        api_keys = json.loads(self._decrypt(user['encrypted_api_keys'])) if user.get('encrypted_api_keys') else {}

        return {
            "user_id": user['user_id'],
            "email": user['email'],
            "google_token": google_token,
            "api_keys": api_keys,
            "fathom_key": api_keys.get('fathom'),  # Backwards compatibility
            "session_token": user['session_token'],
            "session_expiry": user['session_expiry'],
            "created_at": user['created_at'],
            "last_login": user['last_login']
        }

    def update_api_keys(self, user_id: str, api_keys: Dict[str, str]) -> bool:
        """
        Update API keys for a user.

        Args:
            user_id: User ID
            api_keys: Dict of API keys (e.g., {"fathom": "abc", "instantly": "xyz"})

        Returns:
            True if successful
        """
        encrypted_api_keys = self._encrypt(json.dumps(api_keys))

        self.supabase.table('users').update({
            'encrypted_api_keys': encrypted_api_keys
        }).eq('user_id', user_id).execute()

        logger.info(f"Updated API keys for user: {user_id}")
        return True

    def update_fathom_key(self, user_id: str, fathom_key: Optional[str]):
        """
        Update user's Fathom API key (backwards compatibility).

        Args:
            user_id: User ID
            fathom_key: New Fathom API key (or None to remove)
        """
        # Get current API keys
        result = self.supabase.table('users').select('encrypted_api_keys').eq('user_id', user_id).execute()

        if not result.data:
            logger.warning(f"User not found: {user_id}")
            return

        current_api_keys = {}
        if result.data[0].get('encrypted_api_keys'):
            current_api_keys = json.loads(self._decrypt(result.data[0]['encrypted_api_keys']))

        # Update fathom key
        if fathom_key:
            current_api_keys['fathom'] = fathom_key
        else:
            current_api_keys.pop('fathom', None)

        # Save back
        self.update_api_keys(user_id, current_api_keys)

    def update_google_token(self, user_id: str, google_token: Dict[str, Any]):
        """
        Update user's Google OAuth token (for token refresh).

        Args:
            user_id: User ID
            google_token: New Google OAuth token dictionary
        """
        encrypted_google_token = self._encrypt(json.dumps(google_token))

        self.supabase.table('users').update({
            'encrypted_google_token': encrypted_google_token
        }).eq('user_id', user_id).execute()

        logger.info(f"Updated Google token for user: {user_id}")

    def delete_user(self, user_id: str):
        """
        Delete a user and their credentials.

        Args:
            user_id: User ID to delete
        """
        self.supabase.table('users').delete().eq('user_id', user_id).execute()
        logger.info(f"Deleted user: {user_id}")

    def list_users(self) -> list[Dict[str, Any]]:
        """
        List all users (for admin dashboard).

        Returns:
            List of user dicts (without decrypted credentials)
        """
        result = self.supabase.table('users').select(
            'user_id, email, created_at, last_login, last_active, session_expiry, encrypted_api_keys'
        ).order('last_active', desc=True).execute()

        users = []
        for user in result.data:
            # Check if user has any API keys
            has_api_keys = False
            if user.get('encrypted_api_keys'):
                try:
                    api_keys = json.loads(self._decrypt(user['encrypted_api_keys']))
                    has_api_keys = len(api_keys) > 0
                except:
                    pass

            users.append({
                "user_id": user['user_id'],
                "email": user['email'],
                "has_api_keys": has_api_keys,
                "created_at": user['created_at'],
                "last_login": user['last_login'],
                "last_active": user['last_active'],
                "session_expiry": user['session_expiry']
            })

        return users

    def cleanup_expired_sessions(self):
        """Delete users with expired sessions (maintenance task)."""
        # Get current timestamp in ISO format
        now = datetime.now().isoformat()

        result = self.supabase.table('users').delete().lt('session_expiry', now).execute()

        deleted_count = len(result.data) if result.data else 0

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} expired sessions")

        return deleted_count

    def log_usage(
        self,
        user_id: str,
        tool_name: str,
        method: str,
        success: bool,
        error_message: Optional[str] = None,
        response_time_ms: Optional[int] = None
    ):
        """
        Log a tool usage event for analytics.

        Args:
            user_id: User ID
            tool_name: Name of the tool called
            method: MCP method (tools/call, tools/list, etc.)
            success: Whether the call succeeded
            error_message: Error message if failed
            response_time_ms: Response time in milliseconds
        """
        self.supabase.table('usage_logs').insert({
            'user_id': user_id,
            'tool_name': tool_name,
            'method': method,
            'success': success,
            'error_message': error_message,
            'response_time_ms': response_time_ms
        }).execute()

    def get_user_usage_stats(
        self,
        user_id: str,
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Get usage statistics for a specific user.

        Args:
            user_id: User ID
            days: Number of days to look back

        Returns:
            Dict with usage statistics
        """
        # Get cutoff date
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

        # Get all logs for user in time period
        result = self.supabase.table('usage_logs').select('*').eq('user_id', user_id).gte('timestamp', cutoff_date).execute()

        logs = result.data

        # Calculate statistics
        total_requests = len(logs)
        successes = sum(1 for log in logs if log['success'])
        failures = total_requests - successes
        success_rate = (successes / total_requests * 100) if total_requests > 0 else 0

        # Tool breakdown
        tool_breakdown = {}
        for log in logs:
            tool_name = log['tool_name']
            tool_breakdown[tool_name] = tool_breakdown.get(tool_name, 0) + 1

        # Average response time
        response_times = [log['response_time_ms'] for log in logs if log.get('response_time_ms') is not None]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0

        # Recent errors
        error_logs = [log for log in logs if not log['success']]
        error_logs.sort(key=lambda x: x['timestamp'], reverse=True)
        recent_errors = [
            {
                "tool": log['tool_name'],
                "error": log['error_message'],
                "timestamp": log['timestamp']
            }
            for log in error_logs[:10]
        ]

        return {
            "user_id": user_id,
            "period_days": days,
            "total_requests": total_requests,
            "successes": successes,
            "failures": failures,
            "success_rate": round(success_rate, 2),
            "tool_breakdown": tool_breakdown,
            "avg_response_time_ms": round(avg_response_time, 2),
            "recent_errors": recent_errors
        }

    def get_all_usage_stats(self, days: int = 7) -> Dict[str, Any]:
        """
        Get aggregated usage statistics across all users.

        Args:
            days: Number of days to look back

        Returns:
            Dict with aggregated statistics
        """
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

        # Get all logs in time period
        result = self.supabase.table('usage_logs').select('*').gte('timestamp', cutoff_date).execute()
        logs = result.data

        total_requests = len(logs)

        # Requests per user
        user_requests = {}
        for log in logs:
            user_id = log['user_id']
            user_requests[user_id] = user_requests.get(user_id, 0) + 1

        # Get user emails
        users_result = self.supabase.table('users').select('user_id, email').execute()
        user_emails = {u['user_id']: u['email'] for u in users_result.data}

        user_stats = [
            {"email": user_emails.get(user_id, "unknown"), "requests": count}
            for user_id, count in user_requests.items()
        ]
        user_stats.sort(key=lambda x: x['requests'], reverse=True)

        # Most used tools
        tool_counts = {}
        for log in logs:
            tool_name = log['tool_name']
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

        top_tools = dict(sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:10])

        # Daily usage
        daily_usage = {}
        for log in logs:
            date = log['timestamp'].split('T')[0]  # Extract date part
            daily_usage[date] = daily_usage.get(date, 0) + 1

        return {
            "period_days": days,
            "total_requests": total_requests,
            "user_stats": user_stats,
            "top_tools": top_tools,
            "daily_usage": daily_usage
        }

    def get_recent_activity(self, limit: int = 50) -> list[Dict[str, Any]]:
        """
        Get recent usage activity across all users (real-time feed).

        Args:
            limit: Maximum number of recent activities to return

        Returns:
            List of recent activity dicts
        """
        # Get recent logs
        result = self.supabase.table('usage_logs').select('*').order('timestamp', desc=True).limit(limit).execute()

        # Get user emails
        users_result = self.supabase.table('users').select('user_id, email').execute()
        user_emails = {u['user_id']: u['email'] for u in users_result.data}

        activities = [
            {
                "email": user_emails.get(log['user_id'], "unknown"),
                "tool": log['tool_name'],
                "method": log['method'],
                "success": log['success'],
                "error": log.get('error_message'),
                "response_time_ms": log.get('response_time_ms'),
                "timestamp": log['timestamp']
            }
            for log in result.data
        ]

        return activities
