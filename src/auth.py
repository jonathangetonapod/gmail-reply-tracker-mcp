"""OAuth 2.0 authentication handler for Gmail API."""

import os
import json
import logging
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Fix for Google OAuth adding 'openid' scope causing oauthlib validation errors
# Google always adds 'openid' to returned scopes even if not requested
os.environ.setdefault('OAUTHLIB_RELAX_TOKEN_SCOPE', '1')


logger = logging.getLogger(__name__)


class GmailAuthManager:
    """Manages OAuth 2.0 authentication for Gmail API."""

    def __init__(self, credentials_path: Path, token_path: Path, scopes: list[str]):
        """
        Initialize the authentication manager.

        Args:
            credentials_path: Path to credentials.json from Google Cloud Console
            token_path: Path where token.json will be stored
            scopes: List of OAuth scopes to request
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.scopes = scopes
        self._credentials: Optional[Credentials] = None

    def ensure_authenticated(self) -> Credentials:
        """
        Ensure valid credentials are available.

        This method will:
        1. Load existing token if available
        2. Refresh expired token if possible
        3. Trigger new OAuth flow if needed

        Returns:
            Valid Credentials object

        Raises:
            FileNotFoundError: If credentials.json is missing
            Exception: For other authentication errors
        """
        # Check if credentials.json exists
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"Credentials file not found: {self.credentials_path}\n\n"
                f"Please follow these steps:\n"
                f"1. Go to https://console.cloud.google.com\n"
                f"2. Create a project and enable Gmail API\n"
                f"3. Create OAuth 2.0 credentials (Desktop app)\n"
                f"4. Download credentials.json\n"
                f"5. Place it at: {self.credentials_path}"
            )

        # Try to load existing token
        if self.token_path.exists():
            try:
                self._credentials = Credentials.from_authorized_user_file(
                    str(self.token_path),
                    self.scopes
                )
                logger.info("Loaded existing token from %s", self.token_path)
            except Exception as e:
                logger.warning(
                    "Failed to load token from %s: %s",
                    self.token_path,
                    str(e)
                )
                self._credentials = None

        # Refresh expired token or authenticate
        if self._credentials and self._credentials.valid:
            logger.info("Credentials are valid")
            return self._credentials

        if self._credentials and self._credentials.expired and self._credentials.refresh_token:
            try:
                logger.info("Refreshing expired token...")
                self._credentials.refresh(Request())
                self._save_token()
                logger.info("Token refreshed successfully")
                return self._credentials
            except Exception as e:
                logger.error("Failed to refresh token: %s", str(e))
                logger.info("Will attempt new OAuth flow")
                self._credentials = None

        # No valid credentials - run OAuth flow
        logger.info("Starting OAuth flow...")
        self._credentials = self._run_oauth_flow()
        self._save_token()
        logger.info("OAuth flow completed successfully")

        return self._credentials

    def _run_oauth_flow(self) -> Credentials:
        """
        Run the OAuth 2.0 authorization flow.

        Returns:
            New Credentials object

        Raises:
            Exception: If OAuth flow fails
        """
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.credentials_path),
                self.scopes
            )

            # Run local server for OAuth callback
            # Use port 8080 to match Google Cloud Console redirect URI
            # Make sure http://localhost:8080 is in your OAuth client's redirect URIs
            credentials = flow.run_local_server(
                port=8080,
                authorization_prompt_message='Please visit this URL to authorize: {url}',
                success_message='Authorization successful! You can close this window.',
                open_browser=True
            )

            return credentials

        except Exception as e:
            logger.error("OAuth flow failed: %s", str(e))
            raise Exception(
                f"OAuth flow failed: {str(e)}\n\n"
                f"Please ensure:\n"
                f"1. credentials.json is valid\n"
                f"2. Gmail API is enabled in Google Cloud Console\n"
                f"3. OAuth consent screen is configured\n"
                f"4. Your email is added as a test user (if app is not published)"
            ) from e

    def _save_token(self):
        """
        Save credentials to token file.

        The token is saved in JSON format and includes both access and refresh tokens.
        File permissions are set to 600 (read/write for owner only) for security.
        """
        try:
            # Ensure directory exists
            self.token_path.parent.mkdir(parents=True, exist_ok=True)

            # Save credentials to file
            with open(self.token_path, 'w') as token_file:
                token_file.write(self._credentials.to_json())

            # Set secure permissions (owner read/write only)
            os.chmod(self.token_path, 0o600)

            logger.info("Token saved to %s", self.token_path)

        except Exception as e:
            logger.error("Failed to save token: %s", str(e))
            raise Exception(f"Failed to save token: {str(e)}") from e

    def get_credentials(self) -> Credentials:
        """
        Get valid credentials.

        Returns:
            Valid Credentials object

        Raises:
            Exception: If credentials are not available
        """
        if self._credentials is None or not self._credentials.valid:
            return self.ensure_authenticated()
        return self._credentials

    def revoke_token(self):
        """
        Revoke the current token and delete the token file.

        This is useful for testing or when switching accounts.
        """
        if self.token_path.exists():
            try:
                # Revoke token with Google
                if self._credentials:
                    from google.auth.transport.requests import Request
                    import requests

                    requests.post(
                        'https://oauth2.googleapis.com/revoke',
                        params={'token': self._credentials.token},
                        headers={'content-type': 'application/x-www-form-urlencoded'}
                    )
                    logger.info("Token revoked with Google")

                # Delete local token file
                self.token_path.unlink()
                logger.info("Token file deleted: %s", self.token_path)

                self._credentials = None

            except Exception as e:
                logger.error("Failed to revoke token: %s", str(e))
                raise

    def validate_scopes(self) -> bool:
        """
        Validate that current credentials have the required scopes.

        Returns:
            True if scopes match, False otherwise
        """
        if not self._credentials:
            return False

        current_scopes = set(self._credentials.scopes or [])
        required_scopes = set(self.scopes)

        if current_scopes != required_scopes:
            logger.warning(
                "Scope mismatch. Current: %s, Required: %s",
                current_scopes,
                required_scopes
            )
            return False

        return True
