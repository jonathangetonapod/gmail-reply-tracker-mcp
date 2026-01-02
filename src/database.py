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

        Only returns categories with status='active' (payment received).
        'incomplete' subscriptions remain locked until invoice is paid.

        Args:
            user_id: User ID

        Returns:
            List of category names with active subscriptions
        """
        result = self.supabase.table('subscriptions').select('tool_category').eq(
            'user_id', user_id
        ).eq('status', 'active').execute()

        return [sub['tool_category'] for sub in result.data]

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
