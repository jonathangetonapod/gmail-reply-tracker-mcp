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

    # API Keys
    fathom_api_key: str

    # Lead Management
    lead_sheets_url: str
    lead_sheets_gid_instantly: str
    lead_sheets_gid_bison: str

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
        # Try to find .env file - check current dir, then script dir
        env_file = None
        if Path(env_path).exists():
            env_file = env_path
        else:
            # Try relative to this file's directory
            script_dir = Path(__file__).parent.parent
            env_candidate = script_dir / env_path
            if env_candidate.exists():
                env_file = str(env_candidate)

        # Load .env file if found
        if env_file:
            load_dotenv(env_file)

        # Parse configuration from environment variables
        # Get project root directory (parent of src/) to resolve paths correctly
        # regardless of current working directory
        project_root = Path(__file__).parent.parent

        # Resolve credentials path - support both absolute and relative paths
        credentials_path_str = os.getenv(
            "GMAIL_CREDENTIALS_PATH",
            "credentials/credentials.json"  # Relative to project root
        )
        credentials_path = Path(credentials_path_str)
        if not credentials_path.is_absolute():
            credentials_path = project_root / credentials_path

        # Resolve token path - support both absolute and relative paths
        token_path_str = os.getenv(
            "GMAIL_TOKEN_PATH",
            "credentials/token.json"  # Relative to project root
        )
        token_path = Path(token_path_str)
        if not token_path.is_absolute():
            token_path = project_root / token_path

        oauth_scopes_str = os.getenv(
            "GMAIL_OAUTH_SCOPES",
            "https://www.googleapis.com/auth/gmail.readonly"
        )
        oauth_scopes = [s.strip() for s in oauth_scopes_str.split(",")]

        fathom_api_key = os.getenv("FATHOM_API_KEY", "")

        # Lead Management Configuration
        lead_sheets_url = os.getenv(
            "LEAD_SHEETS_URL",
            "https://docs.google.com/spreadsheets/d/1CNejGg-egkp28ItSRfW7F_CkBXgYevjzstJ1QlrAyAY/edit"
        )
        lead_sheets_gid_instantly = os.getenv("LEAD_SHEETS_GID_INSTANTLY", "928115249")
        lead_sheets_gid_bison = os.getenv("LEAD_SHEETS_GID_BISON", "1631680229")

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
            fathom_api_key=fathom_api_key,
            lead_sheets_url=lead_sheets_url,
            lead_sheets_gid_instantly=lead_sheets_gid_instantly,
            lead_sheets_gid_bison=lead_sheets_gid_bison,
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

        # Warn if Fathom API key is not set (optional feature)
        if not self.fathom_api_key:
            logger = logging.getLogger(__name__)
            logger.warning(
                "FATHOM_API_KEY not set. Fathom meeting tools will not be available."
            )

        # Warn if Lead Management sheets URL is not set (optional feature)
        if not self.lead_sheets_url or self.lead_sheets_url == "":
            logger = logging.getLogger(__name__)
            logger.warning(
                "LEAD_SHEETS_URL not set. Lead management tools will not be available."
            )

        return errors

    def setup_logging(self):
        """Configure logging based on config settings."""
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
