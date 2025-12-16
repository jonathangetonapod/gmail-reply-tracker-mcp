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
