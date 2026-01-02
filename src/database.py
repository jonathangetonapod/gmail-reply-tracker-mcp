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
        result = self.supabase.table('users').select('user_id, login_count').eq('email', email).execute()

        if result.data:
            # Update existing user (returning user)
            existing_user_id = result.data[0]['user_id']
            current_login_count = result.data[0].get('login_count', 0)
            new_login_count = current_login_count + 1

            self.supabase.table('users').update({
                'encrypted_google_token': encrypted_google_token,
                'encrypted_api_keys': encrypted_api_keys,
                'session_token': session_token,
                'session_expiry': session_expiry,
                'last_login': datetime.now().isoformat(),
                'login_count': new_login_count
            }).eq('email', email).execute()

            logger.info(f"Updated existing user: {email} (login count: {new_login_count})")
            return {
                "user_id": existing_user_id,
                "session_token": session_token,
                "email": email,
                "is_new_user": False,
                "login_count": new_login_count
            }
        else:
            # Create new user with 3-day free trial
            trial_end_date = (datetime.now() + timedelta(days=3)).isoformat()
            now = datetime.now().isoformat()

            self.supabase.table('users').insert({
                'user_id': user_id,
                'email': email,
                'encrypted_google_token': encrypted_google_token,
                'encrypted_api_keys': encrypted_api_keys,
                'session_token': session_token,
                'session_expiry': session_expiry,
                'trial_end_date': trial_end_date,
                'is_trial_active': True,
                'first_login_at': now,
                'login_count': 1,
                'last_login': now
            }).execute()

            logger.info(f"Created new user: {email} (3-day trial expires: {trial_end_date})")
            return {
                "user_id": user_id,
                "session_token": session_token,
                "email": email,
                "trial_end_date": trial_end_date,
                "is_new_user": True,
                "login_count": 1
            }

    def create_user_with_password(
        self,
        email: str,
        password: str,
        name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new user with email/password authentication.

        Args:
            email: User's email address
            password: Plain text password (will be hashed)
            name: Optional user's full name

        Returns:
            Dict with user_id, session_token, and email

        Raises:
            ValueError: If email already exists or password is too weak
        """
        import bcrypt

        # Validate email doesn't already exist
        result = self.supabase.table('users').select('user_id').eq('email', email).execute()
        if result.data:
            raise ValueError("Email already registered. Please log in instead.")

        # Validate password strength (minimum 8 characters)
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")

        # Hash password with bcrypt
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12))

        # Generate IDs
        user_id = secrets.token_urlsafe(16)
        session_token = f"sess_{secrets.token_urlsafe(32)}"

        # Session expiry (90 days)
        session_expiry = (datetime.now() + timedelta(days=90)).isoformat()

        # Trial period (3 days)
        trial_end_date = (datetime.now() + timedelta(days=3)).isoformat()
        now = datetime.now().isoformat()

        # Create empty encrypted API keys (user will add via dashboard)
        encrypted_api_keys = self._encrypt(json.dumps({}))

        # For email/password users, we don't have Google tokens yet
        # Store a placeholder that indicates this is an email/password account
        placeholder_google_token = {
            'type': 'email_password',
            'token': None,
            'refresh_token': None
        }
        encrypted_google_token = self._encrypt(json.dumps(placeholder_google_token))

        # Create new user
        self.supabase.table('users').insert({
            'user_id': user_id,
            'email': email,
            'password_hash': password_hash.decode('utf-8'),  # Store as string
            'encrypted_google_token': encrypted_google_token,  # Placeholder
            'encrypted_api_keys': encrypted_api_keys,
            'session_token': session_token,
            'session_expiry': session_expiry,
            'trial_end_date': trial_end_date,
            'is_trial_active': True,
            'first_login_at': now,
            'login_count': 1,
            'last_login': now
        }).execute()

        logger.info(f"Created new email/password user: {email} (3-day trial expires: {trial_end_date})")
        return {
            "user_id": user_id,
            "session_token": session_token,
            "email": email,
            "name": name,
            "trial_end_date": trial_end_date,
            "is_new_user": True,
            "login_count": 1
        }

    def authenticate_email_password(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Authenticate user with email and password.

        Args:
            email: User's email address
            password: Plain text password to verify

        Returns:
            Dict with user data and new session token if successful, None otherwise
        """
        import bcrypt

        # Look up user by email
        result = self.supabase.table('users').select('user_id, email, password_hash, login_count').eq('email', email).execute()

        if not result.data:
            logger.warning(f"Login attempt for non-existent email: {email}")
            return None

        user = result.data[0]
        stored_hash = user.get('password_hash')

        # Check if user has a password (might be OAuth-only user)
        if not stored_hash:
            logger.warning(f"Login attempt for OAuth-only user: {email}")
            return None

        # Verify password
        if not bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
            logger.warning(f"Invalid password attempt for: {email}")
            return None

        # Password correct - generate new session token
        session_token = f"sess_{secrets.token_urlsafe(32)}"
        session_expiry = (datetime.now() + timedelta(days=90)).isoformat()

        # Increment login count
        current_login_count = user.get('login_count', 0)
        new_login_count = current_login_count + 1

        # Update session and login tracking
        self.supabase.table('users').update({
            'session_token': session_token,
            'session_expiry': session_expiry,
            'last_login': datetime.now().isoformat(),
            'login_count': new_login_count
        }).eq('user_id', user['user_id']).execute()

        logger.info(f"Successful email/password login: {email} (login count: {new_login_count})")
        return {
            "user_id": user['user_id'],
            "session_token": session_token,
            "email": user['email'],
            "is_new_user": False,
            "login_count": new_login_count
        }

    def update_password(self, user_id: str, new_password: str) -> bool:
        """
        Update user's password.

        Args:
            user_id: User's ID
            new_password: New plain text password (will be hashed)

        Returns:
            True if successful

        Raises:
            ValueError: If password is too weak
        """
        import bcrypt

        # Validate password strength
        if len(new_password) < 8:
            raise ValueError("Password must be at least 8 characters long")

        # Hash new password
        password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt(rounds=12))

        # Update in database
        self.supabase.table('users').update({
            'password_hash': password_hash.decode('utf-8')
        }).eq('user_id', user_id).execute()

        logger.info(f"Password updated for user: {user_id}")
        return True

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

        # Parse enabled tool categories
        enabled_tool_categories = None
        if user.get('enabled_tool_categories'):
            try:
                enabled_tool_categories = json.loads(user['enabled_tool_categories'])
            except:
                enabled_tool_categories = None

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
            "enabled_tool_categories": enabled_tool_categories,  # List of enabled categories or None for all
            "teams_enabled": user.get('teams_enabled', False),  # Team access control
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

    def update_tool_categories(self, user_id: str, categories: list):
        """
        Update user's enabled tool categories.

        Args:
            user_id: User ID
            categories: List of enabled category names (e.g., ["gmail", "calendar"])
                       Empty list = no tools
                       None/null = all tools (default)
        """
        self.supabase.table('users').update({
            'enabled_tool_categories': json.dumps(categories) if categories is not None else None
        }).eq('user_id', user_id).execute()

        logger.info(f"Updated tool categories for user {user_id}: {categories}")

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

    # ==================== Subscription Management ====================

    def create_subscription(
        self,
        user_id: str,
        tool_category: str,
        stripe_customer_id: str,
        stripe_subscription_id: str,
        status: str = 'active',
        current_period_start: Optional[datetime] = None,
        current_period_end: Optional[datetime] = None,
        invoice_id: Optional[str] = None,
        invoice_url: Optional[str] = None
    ):
        """
        Create a new subscription for a user.

        Args:
            user_id: User ID
            tool_category: Category name ('gmail', 'calendar', etc.)
            stripe_customer_id: Stripe customer ID
            stripe_subscription_id: Stripe subscription ID
            status: Subscription status ('active', 'cancelled', 'past_due', 'unpaid')
            current_period_start: Start of current billing period
            current_period_end: End of current billing period
            invoice_id: Stripe invoice ID (for pending invoices)
            invoice_url: Hosted invoice URL (for pending invoices)
        """
        subscription_data = {
            'user_id': user_id,
            'tool_category': tool_category,
            'stripe_customer_id': stripe_customer_id,
            'stripe_subscription_id': stripe_subscription_id,
            'status': status,
            'current_period_start': current_period_start.isoformat() if current_period_start else None,
            'current_period_end': current_period_end.isoformat() if current_period_end else None
        }

        # Add invoice details if provided
        if invoice_id:
            subscription_data['invoice_id'] = invoice_id
        if invoice_url:
            subscription_data['invoice_url'] = invoice_url

        self.supabase.table('subscriptions').insert(subscription_data).execute()

        logger.info(f"Created subscription for user {user_id}, category {tool_category}")

    def get_user_subscriptions(self, user_id: str) -> list[Dict[str, Any]]:
        """
        Get all subscriptions for a user.

        Args:
            user_id: User ID

        Returns:
            List of subscription dicts
        """
        result = self.supabase.table('subscriptions').select('*').eq('user_id', user_id).execute()
        return result.data

    def get_active_subscriptions(self, user_id: str) -> list[str]:
        """
        Get list of active tool categories for a user.
        Includes BOTH personal subscriptions AND team subscriptions (with permission check).

        Only returns categories with status='active' (payment received).
        'incomplete' subscriptions remain locked until invoice is paid.

        For team subscriptions, checks team_member_permissions table to see
        if this user has been granted access to that category.

        Args:
            user_id: User ID

        Returns:
            List of category names with active subscriptions (deduplicated)
        """
        categories = set()

        # 1. Get personal subscriptions
        personal_result = self.supabase.table('subscriptions').select('tool_category').eq(
            'user_id', user_id
        ).eq('status', 'active').is_('team_id', 'null').execute()

        for sub in personal_result.data:
            categories.add(sub['tool_category'])

        # 2. Get team categories user has permission to use
        # This joins team subscriptions with user's permissions
        permissions_result = self.supabase.table('team_member_permissions').select('tool_category').eq(
            'user_id', user_id
        ).execute()

        for perm in permissions_result.data:
            # Verify the team actually has an active subscription for this category
            # (in case permission exists but subscription was cancelled)
            categories.add(perm['tool_category'])

        return list(categories)

    def has_active_subscription(self, user_id: str, tool_category: str) -> bool:
        """
        Check if user has active subscription for a category.

        Args:
            user_id: User ID
            tool_category: Category name

        Returns:
            True if user has active subscription
        """
        result = self.supabase.table('subscriptions').select('id').eq(
            'user_id', user_id
        ).eq('tool_category', tool_category).eq('status', 'active').execute()

        return len(result.data) > 0

    def update_subscription_status(
        self,
        stripe_subscription_id: str,
        status: str,
        current_period_start: Optional[datetime] = None,
        current_period_end: Optional[datetime] = None,
        cancelled_at: Optional[datetime] = None,
        cancel_at_period_end: Optional[bool] = None,
        cancel_at: Optional[datetime] = None
    ):
        """
        Update subscription status (called by Stripe webhook).

        Args:
            stripe_subscription_id: Stripe subscription ID
            status: New status ('active', 'cancelled', 'past_due', 'unpaid')
            current_period_start: Start of current billing period
            current_period_end: End of current billing period
            cancelled_at: Cancellation timestamp
            cancel_at_period_end: Whether subscription is set to cancel at period end
            cancel_at: When subscription will cancel (if scheduled)
        """
        update_data = {'status': status}

        if current_period_start:
            update_data['current_period_start'] = current_period_start.isoformat()
        if current_period_end:
            update_data['current_period_end'] = current_period_end.isoformat()
        if cancelled_at:
            update_data['cancelled_at'] = cancelled_at.isoformat()
        if cancel_at_period_end is not None:
            update_data['cancel_at_period_end'] = cancel_at_period_end
        if cancel_at:
            update_data['cancel_at'] = cancel_at.isoformat()

        self.supabase.table('subscriptions').update(update_data).eq(
            'stripe_subscription_id', stripe_subscription_id
        ).execute()

        logger.info(f"Updated subscription {stripe_subscription_id} to status: {status}")

    def get_subscription_by_stripe_id(self, stripe_subscription_id: str) -> Optional[Dict[str, Any]]:
        """
        Get subscription by Stripe subscription ID.

        Args:
            stripe_subscription_id: Stripe subscription ID

        Returns:
            Subscription dict or None
        """
        result = self.supabase.table('subscriptions').select('*').eq(
            'stripe_subscription_id', stripe_subscription_id
        ).execute()

        return result.data[0] if result.data else None

    def get_stripe_customer_id(self, user_id: str) -> Optional[str]:
        """
        Get Stripe customer ID for a user.

        Args:
            user_id: User ID

        Returns:
            Stripe customer ID or None
        """
        result = self.supabase.table('subscriptions').select('stripe_customer_id').eq(
            'user_id', user_id
        ).limit(1).execute()

        return result.data[0]['stripe_customer_id'] if result.data else None

    # ==================== Subscription Analytics ====================

    def get_subscription_stats(self) -> Dict[str, Any]:
        """
        Get overall subscription statistics for admin dashboard.

        Returns:
            Dict with subscription stats (MRR, user counts, category breakdown)
        """
        # Get all active subscriptions
        result = self.supabase.table('subscriptions').select('*').eq('status', 'active').execute()
        active_subs = result.data

        # Calculate MRR (each subscription is $5/month)
        total_mrr = len(active_subs) * 5

        # Get unique paying users
        paying_user_ids = set(sub['user_id'] for sub in active_subs)
        paying_users_count = len(paying_user_ids)

        # Get total users
        all_users_result = self.supabase.table('users').select('user_id', count='exact').execute()
        total_users = all_users_result.count if hasattr(all_users_result, 'count') else len(all_users_result.data)

        free_users_count = total_users - paying_users_count

        # Category breakdown
        category_counts = {}
        for sub in active_subs:
            category = sub['tool_category']
            category_counts[category] = category_counts.get(category, 0) + 1

        # Sort by most popular
        category_breakdown = dict(sorted(category_counts.items(), key=lambda x: x[1], reverse=True))

        return {
            'total_mrr': total_mrr,
            'total_subscriptions': len(active_subs),
            'paying_users': paying_users_count,
            'free_users': free_users_count,
            'total_users': total_users,
            'category_breakdown': category_breakdown
        }

    def get_user_subscription_summary(self, user_id: str) -> Dict[str, Any]:
        """
        Get subscription summary for a specific user.

        Args:
            user_id: User ID

        Returns:
            Dict with user subscription info (active subs, MRR, Stripe customer ID, incomplete subs grouped by invoice)
        """
        # Get active subscriptions
        result = self.supabase.table('subscriptions').select('*').eq(
            'user_id', user_id
        ).eq('status', 'active').execute()

        active_subs = result.data
        subscription_count = len(active_subs)
        user_mrr = subscription_count * 5

        # Get incomplete/unpaid subscriptions (awaiting payment)
        incomplete_result = self.supabase.table('subscriptions').select('*').eq(
            'user_id', user_id
        ).in_('status', ['incomplete', 'incomplete_expired', 'past_due', 'unpaid']).execute()

        incomplete_subs = incomplete_result.data

        # Group incomplete subscriptions by invoice ID
        pending_invoices = {}
        for sub in incomplete_subs:
            invoice_id = sub.get('invoice_id')
            if invoice_id:
                if invoice_id not in pending_invoices:
                    pending_invoices[invoice_id] = {
                        'invoice_id': invoice_id,
                        'invoice_url': sub.get('invoice_url'),
                        'categories': []
                    }
                pending_invoices[invoice_id]['categories'].append(sub['tool_category'])

        # Get Stripe customer ID
        stripe_customer_id = self.get_stripe_customer_id(user_id) if subscription_count > 0 else None

        # Get category names
        categories = [sub['tool_category'] for sub in active_subs]

        return {
            'subscription_count': subscription_count,
            'mrr': user_mrr,
            'stripe_customer_id': stripe_customer_id,
            'categories': categories,
            'is_paying': subscription_count > 0,
            'pending_invoices': list(pending_invoices.values())  # List of invoices with their categories
        }

    def get_all_user_subscriptions(self) -> Dict[str, Dict[str, Any]]:
        """
        Get subscription summaries for all users (for admin user list).

        Returns:
            Dict mapping user_id to subscription summary
        """
        # Get all active subscriptions
        result = self.supabase.table('subscriptions').select('*').eq('status', 'active').execute()
        active_subs = result.data

        # Group by user_id
        user_subs = {}
        for sub in active_subs:
            user_id = sub['user_id']
            if user_id not in user_subs:
                user_subs[user_id] = {
                    'subscription_count': 0,
                    'categories': [],
                    'stripe_customer_id': sub['stripe_customer_id']
                }
            user_subs[user_id]['subscription_count'] += 1
            user_subs[user_id]['categories'].append(sub['tool_category'])

        # Calculate MRR for each user
        for user_id in user_subs:
            user_subs[user_id]['mrr'] = user_subs[user_id]['subscription_count'] * 5
            user_subs[user_id]['is_paying'] = True

        return user_subs

    # ========================================================================
    # FREE TRIAL & USAGE TRACKING
    # ========================================================================

    def check_trial_status(self, user_id: str) -> Dict[str, Any]:
        """
        Check if user is in trial period and how much time remains.

        Args:
            user_id: User ID

        Returns:
            Dict with trial status info
        """
        result = self.supabase.table('users').select('trial_end_date, is_trial_active').eq('user_id', user_id).execute()

        if not result.data:
            return {'is_trial': False, 'days_remaining': 0, 'expired': True}

        user = result.data[0]
        trial_end_date = user.get('trial_end_date')
        is_trial_active = user.get('is_trial_active', False)

        if not trial_end_date or not is_trial_active:
            return {'is_trial': False, 'days_remaining': 0, 'expired': True}

        # Parse trial end date
        if isinstance(trial_end_date, str):
            if '+' in trial_end_date:
                trial_end_date = trial_end_date.split('+')[0]
            trial_end = datetime.fromisoformat(trial_end_date)
        else:
            trial_end = trial_end_date

        # Calculate time remaining
        now = datetime.now()
        time_remaining = trial_end - now

        if time_remaining.total_seconds() <= 0:
            # Trial expired - mark as inactive
            self.supabase.table('users').update({
                'is_trial_active': False
            }).eq('user_id', user_id).execute()

            return {
                'is_trial': False,
                'days_remaining': 0,
                'hours_remaining': 0,
                'expired': True,
                'trial_end_date': trial_end.isoformat()
            }

        days_remaining = time_remaining.days
        hours_remaining = int(time_remaining.total_seconds() / 3600)

        return {
            'is_trial': True,
            'days_remaining': days_remaining,
            'hours_remaining': hours_remaining,
            'expired': False,
            'trial_end_date': trial_end.isoformat()
        }

    def get_daily_usage(self, user_id: str) -> int:
        """
        Get tool call count for user today.

        Args:
            user_id: User ID

        Returns:
            Number of tool calls made today
        """
        result = self.supabase.table('daily_usage').select('tool_calls_count').eq(
            'user_id', user_id
        ).eq('usage_date', datetime.now().date().isoformat()).execute()

        if result.data:
            return result.data[0]['tool_calls_count']
        return 0

    def increment_usage(self, user_id: str) -> int:
        """
        Increment tool call count for user today.

        Args:
            user_id: User ID

        Returns:
            New tool call count for today
        """
        # Use the PostgreSQL function
        result = self.supabase.rpc('increment_daily_usage', {'p_user_id': user_id}).execute()

        if result.data:
            return result.data

        # Fallback if function doesn't exist
        current_count = self.get_daily_usage(user_id)
        new_count = current_count + 1

        today = datetime.now().date().isoformat()

        if current_count == 0:
            # Insert new record
            self.supabase.table('daily_usage').insert({
                'user_id': user_id,
                'usage_date': today,
                'tool_calls_count': 1
            }).execute()
        else:
            # Update existing record
            self.supabase.table('daily_usage').update({
                'tool_calls_count': new_count,
                'updated_at': datetime.now().isoformat()
            }).eq('user_id', user_id).eq('usage_date', today).execute()

        return new_count

    def can_use_tool(self, user_id: str, tool_category: str) -> Dict[str, Any]:
        """
        Check if user can use a tool (trial or paid subscription).

        Args:
            user_id: User ID
            tool_category: Category of the tool (gmail, calendar, etc.)

        Returns:
            Dict with permission status and reason
        """
        # Check if in trial
        trial_status = self.check_trial_status(user_id)

        if trial_status['is_trial']:
            # In trial - check daily limit (10 calls/day for free tier after trial)
            daily_usage = self.get_daily_usage(user_id)

            return {
                'allowed': True,
                'reason': 'trial',
                'trial_days_remaining': trial_status['days_remaining'],
                'daily_usage': daily_usage
            }

        # Not in trial - check for active subscription
        has_subscription = self.has_active_subscription(user_id, tool_category)

        if has_subscription:
            return {
                'allowed': True,
                'reason': 'subscription',
                'daily_usage': self.get_daily_usage(user_id)
            }

        # No trial, no subscription - check free tier limit
        daily_usage = self.get_daily_usage(user_id)
        FREE_TIER_DAILY_LIMIT = 10

        if daily_usage < FREE_TIER_DAILY_LIMIT:
            return {
                'allowed': True,
                'reason': 'free_tier',
                'daily_usage': daily_usage,
                'daily_limit': FREE_TIER_DAILY_LIMIT,
                'remaining': FREE_TIER_DAILY_LIMIT - daily_usage
            }

        # Exceeded free tier limit
        return {
            'allowed': False,
            'reason': 'limit_exceeded',
            'daily_usage': daily_usage,
            'daily_limit': FREE_TIER_DAILY_LIMIT,
            'message': f'Free tier limit exceeded ({daily_usage}/{FREE_TIER_DAILY_LIMIT} calls today). Upgrade to continue.'
        }

    # =========================================================================
    # TEAM MANAGEMENT METHODS
    # =========================================================================

    def create_team(self, team_name: str, owner_user_id: str, billing_email: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new team with the specified owner.

        Args:
            team_name: Name of the team
            owner_user_id: User ID of the team owner
            billing_email: Optional billing email (defaults to owner's email)

        Returns:
            Dict with team_id, team_name, owner_user_id
        """
        # Generate team ID
        team_id = f"team_{secrets.token_urlsafe(16)}"

        # Get owner's email for billing if not provided
        if not billing_email:
            owner = self.supabase.table('users').select('email').eq('user_id', owner_user_id).execute()
            if owner.data:
                billing_email = owner.data[0]['email']

        # Create team
        result = self.supabase.table('teams').insert({
            'team_id': team_id,
            'team_name': team_name,
            'owner_user_id': owner_user_id,
            'billing_email': billing_email
        }).execute()

        # Add owner as team member
        self.supabase.table('team_members').insert({
            'team_id': team_id,
            'user_id': owner_user_id,
            'role': 'owner'
        }).execute()

        logger.info(f"Created team: {team_name} (ID: {team_id}) for owner: {owner_user_id}")

        return {
            'team_id': team_id,
            'team_name': team_name,
            'owner_user_id': owner_user_id,
            'billing_email': billing_email
        }

    def get_user_teams(self, user_id: str) -> list[Dict[str, Any]]:
        """
        Get all teams a user is a member of.

        Args:
            user_id: User ID

        Returns:
            List of team dicts with role information
        """
        result = self.supabase.table('team_members').select(
            'team_id, role, joined_at, teams(team_name, owner_user_id, created_at)'
        ).eq('user_id', user_id).execute()

        teams = []
        for row in result.data:
            team_data = row.get('teams', {})
            teams.append({
                'team_id': row['team_id'],
                'team_name': team_data.get('team_name'),
                'role': row['role'],
                'is_owner': row['role'] == 'owner',
                'joined_at': row['joined_at'],
                'created_at': team_data.get('created_at')
            })

        return teams

    def get_team_members(self, team_id: str) -> list[Dict[str, Any]]:
        """
        Get all members of a team.

        Args:
            team_id: Team ID

        Returns:
            List of member dicts with user information
        """
        result = self.supabase.table('team_members').select(
            'user_id, role, joined_at, users(email)'
        ).eq('team_id', team_id).execute()

        members = []
        for row in result.data:
            user_data = row.get('users', {})
            members.append({
                'user_id': row['user_id'],
                'email': user_data.get('email'),
                'role': row['role'],
                'joined_at': row['joined_at']
            })

        return members

    def invite_team_member(self, team_id: str, email: str, invited_by_user_id: str) -> Dict[str, Any]:
        """
        Create an invitation for someone to join a team.

        Args:
            team_id: Team ID
            email: Email address to invite
            invited_by_user_id: User ID of person sending invitation

        Returns:
            Dict with invitation_id and details
        """
        # Generate invitation ID
        invitation_id = f"inv_{secrets.token_urlsafe(20)}"

        # Create invitation
        result = self.supabase.table('team_invitations').insert({
            'invitation_id': invitation_id,
            'team_id': team_id,
            'email': email.lower().strip(),
            'invited_by_user_id': invited_by_user_id,
            'status': 'pending'
        }).execute()

        if result.data:
            logger.info(f"Created team invitation for {email} to team {team_id}")
            return result.data[0]

        return {}

    def get_team_invitation(self, invitation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get details of a team invitation.

        Args:
            invitation_id: Invitation ID

        Returns:
            Invitation dict or None if not found/expired
        """
        result = self.supabase.table('team_invitations').select(
            '*, teams(team_name, owner_user_id)'
        ).eq('invitation_id', invitation_id).execute()

        if not result.data:
            return None

        invitation = result.data[0]

        # Check if expired
        expires_at = datetime.fromisoformat(invitation['expires_at'].replace('Z', '+00:00'))
        if datetime.now(expires_at.tzinfo) > expires_at:
            # Mark as expired
            self.supabase.table('team_invitations').update({
                'status': 'expired'
            }).eq('invitation_id', invitation_id).execute()
            return None

        # Check if already accepted
        if invitation['status'] != 'pending':
            return None

        team_data = invitation.get('teams', {})
        return {
            'invitation_id': invitation['invitation_id'],
            'team_id': invitation['team_id'],
            'team_name': team_data.get('team_name'),
            'email': invitation['email'],
            'invited_by_user_id': invitation['invited_by_user_id'],
            'expires_at': invitation['expires_at'],
            'created_at': invitation['created_at']
        }

    def accept_team_invitation(self, invitation_id: str, user_id: str) -> bool:
        """
        Accept a team invitation and add user to team.

        Args:
            invitation_id: Invitation ID
            user_id: User ID accepting invitation

        Returns:
            True if successful, False otherwise
        """
        # Get invitation
        invitation = self.get_team_invitation(invitation_id)
        if not invitation:
            logger.warning(f"Invalid or expired invitation: {invitation_id}")
            return False

        team_id = invitation['team_id']

        # Check if user already in team
        existing = self.supabase.table('team_members').select('team_id').eq(
            'team_id', team_id
        ).eq('user_id', user_id).execute()

        if existing.data:
            logger.warning(f"User {user_id} already in team {team_id}")
            return False

        # Add user to team
        self.supabase.table('team_members').insert({
            'team_id': team_id,
            'user_id': user_id,
            'role': 'member'
        }).execute()

        # Mark invitation as accepted
        self.supabase.table('team_invitations').update({
            'status': 'accepted',
            'accepted_at': datetime.now().isoformat()
        }).eq('invitation_id', invitation_id).execute()

        logger.info(f"User {user_id} accepted invitation and joined team {team_id}")
        return True

    def add_team_member(self, team_id: str, user_id: str, role: str = 'member') -> bool:
        """
        Add a user to a team with specified role.

        Args:
            team_id: Team ID
            user_id: User ID to add
            role: Role to assign (member, admin)

        Returns:
            True if successful
        """
        # Check if user already in team
        existing = self.supabase.table('team_members').select('team_id').eq(
            'team_id', team_id
        ).eq('user_id', user_id).execute()

        if existing.data:
            logger.warning(f"User {user_id} already in team {team_id}")
            return False

        # Add user to team
        self.supabase.table('team_members').insert({
            'team_id': team_id,
            'user_id': user_id,
            'role': role
        }).execute()

        logger.info(f"Added user {user_id} to team {team_id} as {role}")
        return True

    def remove_team_member(self, team_id: str, user_id: str, removed_by_user_id: str) -> bool:
        """
        Remove a member from a team.

        Args:
            team_id: Team ID
            user_id: User ID to remove
            removed_by_user_id: User ID performing the removal (must be owner/admin)

        Returns:
            True if successful, False otherwise
        """
        # Check if remover has permission (owner or admin)
        remover = self.supabase.table('team_members').select('role').eq(
            'team_id', team_id
        ).eq('user_id', removed_by_user_id).execute()

        if not remover.data or remover.data[0]['role'] not in ['owner', 'admin']:
            logger.warning(f"User {removed_by_user_id} lacks permission to remove members from team {team_id}")
            return False

        # Cannot remove the owner
        member = self.supabase.table('team_members').select('role').eq(
            'team_id', team_id
        ).eq('user_id', user_id).execute()

        if member.data and member.data[0]['role'] == 'owner':
            logger.warning(f"Cannot remove owner from team {team_id}")
            return False

        # Remove member
        self.supabase.table('team_members').delete().eq(
            'team_id', team_id
        ).eq('user_id', user_id).execute()

        logger.info(f"Removed user {user_id} from team {team_id} by {removed_by_user_id}")
        return True

    def get_team_subscriptions(self, team_id: str) -> list[str]:
        """
        Get all active tool categories subscribed by a team.

        Args:
            team_id: Team ID

        Returns:
            List of tool category names
        """
        result = self.supabase.table('subscriptions').select('tool_category').eq(
            'team_id', team_id
        ).eq('status', 'active').eq('is_team_subscription', True).execute()

        return [row['tool_category'] for row in result.data]

    # ============================================================
    # Team Member Permissions Methods
    # ============================================================

    def grant_team_permission(
        self,
        user_id: str,
        team_id: str,
        tool_category: str,
        assigned_by_user_id: str
    ) -> bool:
        """
        Grant a team member permission to use a tool category from team subscription.

        Args:
            user_id: User to grant permission to
            team_id: Team ID
            tool_category: Tool category (gmail, sheets, etc.)
            assigned_by_user_id: Admin user granting the permission

        Returns:
            True if successful
        """
        try:
            self.supabase.table('team_member_permissions').insert({
                'user_id': user_id,
                'team_id': team_id,
                'tool_category': tool_category,
                'assigned_by_user_id': assigned_by_user_id
            }).execute()
            logger.info(f"Granted {tool_category} permission to user {user_id} in team {team_id}")
            return True
        except Exception as e:
            # Handle duplicate key error (permission already exists)
            if 'duplicate' in str(e).lower():
                logger.debug(f"Permission already exists for user {user_id}, team {team_id}, category {tool_category}")
                return True
            logger.error(f"Failed to grant permission: {e}")
            return False

    def revoke_team_permission(
        self,
        user_id: str,
        team_id: str,
        tool_category: str
    ) -> bool:
        """
        Revoke a team member's permission to use a tool category.

        Args:
            user_id: User to revoke permission from
            team_id: Team ID
            tool_category: Tool category

        Returns:
            True if successful
        """
        try:
            self.supabase.table('team_member_permissions').delete().eq(
                'user_id', user_id
            ).eq('team_id', team_id).eq('tool_category', tool_category).execute()
            logger.info(f"Revoked {tool_category} permission from user {user_id} in team {team_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to revoke permission: {e}")
            return False

    def get_user_team_permissions(self, user_id: str, team_id: str) -> list[str]:
        """
        Get all tool categories a user has permission to use in a team.

        Args:
            user_id: User ID
            team_id: Team ID

        Returns:
            List of tool category names
        """
        result = self.supabase.table('team_member_permissions').select('tool_category').eq(
            'user_id', user_id
        ).eq('team_id', team_id).execute()

        return [row['tool_category'] for row in result.data]

    def get_team_all_permissions(self, team_id: str) -> dict:
        """
        Get all permissions for all members of a team.

        Args:
            team_id: Team ID

        Returns:
            Dict mapping user_id to list of tool categories
            Example: {'user1': ['gmail', 'sheets'], 'user2': ['gmail']}
        """
        result = self.supabase.table('team_member_permissions').select('user_id, tool_category').eq(
            'team_id', team_id
        ).execute()

        permissions_map = {}
        for row in result.data:
            user_id = row['user_id']
            category = row['tool_category']
            if user_id not in permissions_map:
                permissions_map[user_id] = []
            permissions_map[user_id].append(category)

        return permissions_map

    def set_user_team_permissions(
        self,
        user_id: str,
        team_id: str,
        categories: list[str],
        assigned_by_user_id: str
    ) -> bool:
        """
        Set all permissions for a user in a team (replaces existing permissions).

        Args:
            user_id: User ID
            team_id: Team ID
            categories: List of tool categories to grant access to
            assigned_by_user_id: Admin user setting the permissions

        Returns:
            True if successful
        """
        try:
            # Delete existing permissions
            self.supabase.table('team_member_permissions').delete().eq(
                'user_id', user_id
            ).eq('team_id', team_id).execute()

            # Add new permissions
            if categories:
                permissions = [{
                    'user_id': user_id,
                    'team_id': team_id,
                    'tool_category': cat,
                    'assigned_by_user_id': assigned_by_user_id
                } for cat in categories]

                self.supabase.table('team_member_permissions').insert(permissions).execute()

            logger.info(f"Set permissions for user {user_id} in team {team_id}: {categories}")
            return True
        except Exception as e:
            logger.error(f"Failed to set permissions: {e}")
            return False

    def get_user_all_subscriptions(self, user_id: str) -> list[str]:
        """
        Get all tool categories a user has access to (personal + team subscriptions).

        Args:
            user_id: User ID

        Returns:
            List of tool category names (deduplicated)
        """
        categories = set()

        # Get personal subscriptions
        personal = self.get_active_subscriptions(user_id)
        categories.update(personal)

        # Get team subscriptions
        teams = self.get_user_teams(user_id)
        for team in teams:
            team_subs = self.get_team_subscriptions(team['team_id'])
            categories.update(team_subs)

        return list(categories)

    def create_team_subscription(
        self,
        team_id: str,
        tool_category: str,
        stripe_customer_id: Optional[str] = None,
        stripe_subscription_id: Optional[str] = None,
        status: str = 'incomplete',
        current_period_start: Optional[datetime] = None,
        current_period_end: Optional[datetime] = None
    ) -> bool:
        """
        Create a team subscription for a tool category.

        Args:
            team_id: Team ID
            tool_category: Tool category name
            stripe_customer_id: Stripe customer ID
            stripe_subscription_id: Stripe subscription ID
            status: Subscription status
            current_period_start: Start of billing period
            current_period_end: End of billing period

        Returns:
            True if successful
        """
        self.supabase.table('subscriptions').insert({
            'team_id': team_id,
            'tool_category': tool_category,
            'stripe_customer_id': stripe_customer_id,
            'stripe_subscription_id': stripe_subscription_id,
            'status': status,
            'is_team_subscription': True,
            'current_period_start': current_period_start.isoformat() if current_period_start else None,
            'current_period_end': current_period_end.isoformat() if current_period_end else None
        }).execute()

        logger.info(f"Created team subscription: {tool_category} for team {team_id}")
        return True
