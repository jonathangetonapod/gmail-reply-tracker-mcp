"""Database models and management for multi-tenant MCP server."""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet
import secrets

logger = logging.getLogger(__name__)


class Database:
    """Manages SQLite database for user sessions and credentials."""

    def __init__(self, db_path: str, encryption_key: str):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file
            encryption_key: Base64-encoded Fernet encryption key
        """
        self.db_path = db_path
        self.cipher = Fernet(encryption_key.encode())
        self._ensure_database()

    def _ensure_database(self):
        """Create database tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,

                -- Google OAuth tokens (encrypted)
                encrypted_google_token TEXT NOT NULL,
                google_token_expiry TIMESTAMP,

                -- Fathom API key (encrypted, optional)
                encrypted_fathom_key TEXT,

                -- Session management
                session_token TEXT UNIQUE NOT NULL,
                session_expiry TIMESTAMP NOT NULL,

                -- Metadata
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create index on session_token for fast lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_token
            ON users(session_token)
        """)

        # Create index on email for fast lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_email
            ON users(email)
        """)

        # Create usage_logs table for analytics
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                method TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                error_message TEXT,
                response_time_ms INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # Create indexes for analytics queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_user_id
            ON usage_logs(user_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_timestamp
            ON usage_logs(timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_tool
            ON usage_logs(tool_name)
        """)

        conn.commit()
        conn.close()

        logger.info("Database initialized at %s", self.db_path)

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
        fathom_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new user or update existing user.

        Args:
            email: User's email address
            google_token: Google OAuth token dictionary
            fathom_key: Optional Fathom API key

        Returns:
            Dict with user_id and session_token
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Generate IDs
        user_id = secrets.token_urlsafe(16)
        session_token = f"sess_{secrets.token_urlsafe(32)}"

        # Encrypt tokens
        encrypted_google_token = self._encrypt(json.dumps(google_token))
        encrypted_fathom_key = self._encrypt(fathom_key) if fathom_key else None

        # Calculate token expiry (from Google token)
        token_expiry = None
        if 'expires_in' in google_token:
            token_expiry = datetime.now() + timedelta(seconds=google_token['expires_in'])

        # Session expiry (90 days)
        session_expiry = datetime.now() + timedelta(days=90)

        try:
            # Check if user already exists
            cursor.execute("SELECT user_id FROM users WHERE email = ?", (email,))
            existing = cursor.fetchone()

            if existing:
                # Update existing user
                cursor.execute("""
                    UPDATE users
                    SET encrypted_google_token = ?,
                        google_token_expiry = ?,
                        encrypted_fathom_key = ?,
                        session_token = ?,
                        session_expiry = ?,
                        last_login = CURRENT_TIMESTAMP
                    WHERE email = ?
                """, (
                    encrypted_google_token,
                    token_expiry,
                    encrypted_fathom_key,
                    session_token,
                    session_expiry,
                    email
                ))
                user_id = existing[0]
                logger.info("Updated existing user: %s", email)
            else:
                # Create new user
                cursor.execute("""
                    INSERT INTO users (
                        user_id, email, encrypted_google_token, google_token_expiry,
                        encrypted_fathom_key, session_token, session_expiry
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, email, encrypted_google_token, token_expiry,
                    encrypted_fathom_key, session_token, session_expiry
                ))
                logger.info("Created new user: %s", email)

            conn.commit()

            return {
                "user_id": user_id,
                "session_token": session_token,
                "email": email
            }

        except sqlite3.IntegrityError as e:
            logger.error("Database integrity error: %s", str(e))
            raise Exception(f"Failed to create user: {str(e)}")
        finally:
            conn.close()

    def get_user_by_session(self, session_token: str) -> Optional[Dict[str, Any]]:
        """
        Get user information by session token.

        Args:
            session_token: Session token to look up

        Returns:
            User dict with decrypted credentials, or None if not found/expired
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM users WHERE session_token = ?
        """, (session_token,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        # Check if session expired
        session_expiry = datetime.fromisoformat(row['session_expiry'])
        if datetime.now() > session_expiry:
            logger.warning("Session expired for user: %s", row['email'])
            return None

        # Decrypt tokens
        google_token = json.loads(self._decrypt(row['encrypted_google_token']))
        fathom_key = self._decrypt(row['encrypted_fathom_key']) if row['encrypted_fathom_key'] else None

        # Update last_active
        self._update_last_active(row['user_id'])

        return {
            "user_id": row['user_id'],
            "email": row['email'],
            "google_token": google_token,
            "fathom_key": fathom_key,
            "session_token": row['session_token'],
            "session_expiry": row['session_expiry'],
            "created_at": row['created_at'],
            "last_login": row['last_login']
        }

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Get user information by email address.

        Args:
            email: Email address to look up

        Returns:
            User dict with decrypted credentials, or None if not found
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM users WHERE email = ?
        """, (email,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        # Decrypt tokens
        google_token = json.loads(self._decrypt(row['encrypted_google_token']))
        fathom_key = self._decrypt(row['encrypted_fathom_key']) if row['encrypted_fathom_key'] else None

        return {
            "user_id": row['user_id'],
            "email": row['email'],
            "google_token": google_token,
            "fathom_key": fathom_key,
            "session_token": row['session_token'],
            "session_expiry": row['session_expiry'],
            "created_at": row['created_at'],
            "last_login": row['last_login']
        }

    def update_fathom_key(self, user_id: str, fathom_key: Optional[str]):
        """
        Update user's Fathom API key.

        Args:
            user_id: User ID
            fathom_key: New Fathom API key (or None to remove)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        encrypted_fathom_key = self._encrypt(fathom_key) if fathom_key else None

        cursor.execute("""
            UPDATE users
            SET encrypted_fathom_key = ?
            WHERE user_id = ?
        """, (encrypted_fathom_key, user_id))

        conn.commit()
        conn.close()

        logger.info("Updated Fathom key for user: %s", user_id)

    def update_google_token(self, user_id: str, google_token: Dict[str, Any]):
        """
        Update user's Google OAuth token (for token refresh).

        Args:
            user_id: User ID
            google_token: New Google OAuth token dictionary
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        encrypted_google_token = self._encrypt(json.dumps(google_token))

        # Calculate token expiry
        token_expiry = None
        if 'expires_in' in google_token:
            token_expiry = datetime.now() + timedelta(seconds=google_token['expires_in'])

        cursor.execute("""
            UPDATE users
            SET encrypted_google_token = ?,
                google_token_expiry = ?
            WHERE user_id = ?
        """, (encrypted_google_token, token_expiry, user_id))

        conn.commit()
        conn.close()

        logger.info("Updated Google token for user: %s", user_id)

    def _update_last_active(self, user_id: str):
        """Update user's last_active timestamp."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE users
            SET last_active = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (user_id,))

        conn.commit()
        conn.close()

    def delete_user(self, user_id: str):
        """
        Delete a user and their credentials.

        Args:
            user_id: User ID to delete
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))

        conn.commit()
        conn.close()

        logger.info("Deleted user: %s", user_id)

    def list_users(self) -> list[Dict[str, Any]]:
        """
        List all users (for admin dashboard).

        Returns:
            List of user dicts (without decrypted credentials)
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT user_id, email, created_at, last_login, last_active,
                   session_expiry, encrypted_fathom_key
            FROM users
            ORDER BY last_active DESC
        """)

        rows = cursor.fetchall()
        conn.close()

        users = []
        for row in rows:
            users.append({
                "user_id": row['user_id'],
                "email": row['email'],
                "has_fathom": row['encrypted_fathom_key'] is not None,
                "created_at": row['created_at'],
                "last_login": row['last_login'],
                "last_active": row['last_active'],
                "session_expiry": row['session_expiry']
            })

        return users

    def cleanup_expired_sessions(self):
        """Delete users with expired sessions (maintenance task)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM users
            WHERE session_expiry < CURRENT_TIMESTAMP
        """)

        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()

        if deleted_count > 0:
            logger.info("Cleaned up %d expired sessions", deleted_count)

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
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO usage_logs (
                user_id, tool_name, method, success,
                error_message, response_time_ms
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, tool_name, method, success, error_message, response_time_ms))

        conn.commit()
        conn.close()

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
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get cutoff date
        cutoff_date = datetime.now() - timedelta(days=days)

        # Total requests
        cursor.execute("""
            SELECT COUNT(*) FROM usage_logs
            WHERE user_id = ? AND timestamp >= ?
        """, (user_id, cutoff_date))
        total_requests = cursor.fetchone()[0]

        # Success rate
        cursor.execute("""
            SELECT
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failures
            FROM usage_logs
            WHERE user_id = ? AND timestamp >= ?
        """, (user_id, cutoff_date))
        successes, failures = cursor.fetchone()
        success_rate = (successes / total_requests * 100) if total_requests > 0 else 0

        # Tool usage breakdown
        cursor.execute("""
            SELECT tool_name, COUNT(*) as count
            FROM usage_logs
            WHERE user_id = ? AND timestamp >= ?
            GROUP BY tool_name
            ORDER BY count DESC
        """, (user_id, cutoff_date))
        tool_breakdown = {row[0]: row[1] for row in cursor.fetchall()}

        # Average response time
        cursor.execute("""
            SELECT AVG(response_time_ms) FROM usage_logs
            WHERE user_id = ? AND timestamp >= ? AND response_time_ms IS NOT NULL
        """, (user_id, cutoff_date))
        avg_response_time = cursor.fetchone()[0] or 0

        # Recent errors
        cursor.execute("""
            SELECT tool_name, error_message, timestamp
            FROM usage_logs
            WHERE user_id = ? AND success = 0 AND timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT 10
        """, (user_id, cutoff_date))
        recent_errors = [
            {
                "tool": row[0],
                "error": row[1],
                "timestamp": row[2]
            }
            for row in cursor.fetchall()
        ]

        conn.close()

        return {
            "user_id": user_id,
            "period_days": days,
            "total_requests": total_requests,
            "successes": successes or 0,
            "failures": failures or 0,
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
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff_date = datetime.now() - timedelta(days=days)

        # Total requests across all users
        cursor.execute("""
            SELECT COUNT(*) FROM usage_logs
            WHERE timestamp >= ?
        """, (cutoff_date,))
        total_requests = cursor.fetchone()[0]

        # Requests per user
        cursor.execute("""
            SELECT u.email, COUNT(l.log_id) as request_count
            FROM users u
            LEFT JOIN usage_logs l ON u.user_id = l.user_id
                AND l.timestamp >= ?
            GROUP BY u.email
            ORDER BY request_count DESC
        """, (cutoff_date,))
        user_stats = [
            {"email": row[0], "requests": row[1]}
            for row in cursor.fetchall()
        ]

        # Most used tools
        cursor.execute("""
            SELECT tool_name, COUNT(*) as count
            FROM usage_logs
            WHERE timestamp >= ?
            GROUP BY tool_name
            ORDER BY count DESC
            LIMIT 10
        """, (cutoff_date,))
        top_tools = {row[0]: row[1] for row in cursor.fetchall()}

        # Daily usage
        cursor.execute("""
            SELECT DATE(timestamp) as date, COUNT(*) as count
            FROM usage_logs
            WHERE timestamp >= ?
            GROUP BY DATE(timestamp)
            ORDER BY date DESC
        """, (cutoff_date,))
        daily_usage = {row[0]: row[1] for row in cursor.fetchall()}

        conn.close()

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
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                u.email,
                l.tool_name,
                l.method,
                l.success,
                l.error_message,
                l.response_time_ms,
                l.timestamp
            FROM usage_logs l
            JOIN users u ON l.user_id = u.user_id
            ORDER BY l.timestamp DESC
            LIMIT ?
        """, (limit,))

        activities = [
            {
                "email": row[0],
                "tool": row[1],
                "method": row[2],
                "success": bool(row[3]),
                "error": row[4],
                "response_time_ms": row[5],
                "timestamp": row[6]
            }
            for row in cursor.fetchall()
        ]

        conn.close()

        return activities
