"""Configuration management for Gmail Reply Tracker MCP Server."""

import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List
from dotenv import load_dotenv


@dataclass
class Config:
    """Configuration settings for the Gmail MCP server."""

    # Paths
    credentials_path: Path
    token_path: Path

    # OAuth
    oauth_scopes: List[str]

    # Server
    server_name: str
    log_level: str

    # Rate limiting
    max_requests_per_minute: int

    @classmethod
    def from_env(cls, env_path: str = ".env") -> "Config":
        """
        Load configuration from .env file.

        Args:
            env_path: Path to .env file (default: ".env")

        Returns:
            Config object with loaded settings
        """
        # Load .env file if it exists
        if Path(env_path).exists():
            load_dotenv(env_path)

        # Parse configuration from environment variables
        credentials_path = Path(os.getenv(
            "GMAIL_CREDENTIALS_PATH",
            "./credentials/credentials.json"
        ))

        token_path = Path(os.getenv(
            "GMAIL_TOKEN_PATH",
            "./credentials/token.json"
        ))

        oauth_scopes_str = os.getenv(
            "GMAIL_OAUTH_SCOPES",
            "https://www.googleapis.com/auth/gmail.readonly"
        )
        oauth_scopes = [s.strip() for s in oauth_scopes_str.split(",")]

        server_name = os.getenv("MCP_SERVER_NAME", "gmail-reply-tracker")
        log_level = os.getenv("LOG_LEVEL", "INFO")

        max_requests_per_minute = int(os.getenv(
            "GMAIL_API_MAX_REQUESTS_PER_MINUTE",
            "60"
        ))

        return cls(
            credentials_path=credentials_path,
            token_path=token_path,
            oauth_scopes=oauth_scopes,
            server_name=server_name,
            log_level=log_level,
            max_requests_per_minute=max_requests_per_minute
        )

    def validate(self) -> List[str]:
        """
        Validate configuration and return list of errors.

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Check credentials path exists
        if not self.credentials_path.exists():
            errors.append(
                f"Credentials file not found: {self.credentials_path}\n"
                f"Please download credentials.json from Google Cloud Console "
                f"and place it at {self.credentials_path}"
            )

        # Check credentials directory exists
        if not self.credentials_path.parent.exists():
            errors.append(
                f"Credentials directory not found: {self.credentials_path.parent}"
            )

        # Check token directory is writable
        token_dir = self.token_path.parent
        if not token_dir.exists():
            errors.append(
                f"Token directory not found: {token_dir}"
            )
        elif not os.access(token_dir, os.W_OK):
            errors.append(
                f"Token directory is not writable: {token_dir}"
            )

        # Validate log level
        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_log_levels:
            errors.append(
                f"Invalid log level: {self.log_level}. "
                f"Must be one of: {', '.join(valid_log_levels)}"
            )

        # Validate rate limiting
        if self.max_requests_per_minute <= 0:
            errors.append(
                f"Invalid max_requests_per_minute: {self.max_requests_per_minute}. "
                f"Must be greater than 0"
            )

        return errors

    def setup_logging(self):
        """Configure logging based on config settings."""
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
