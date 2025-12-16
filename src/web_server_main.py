#!/usr/bin/env python3
"""Main entry point for Railway deployment."""

import os
import sys
import logging
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent))

from database import Database
from web_server import WebServer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    logger.info("Starting MCP Web Server...")

    # Get configuration from environment
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    redirect_uri = os.getenv('GOOGLE_REDIRECT_URI')
    scopes_str = os.getenv('GOOGLE_OAUTH_SCOPES', '')
    encryption_key = os.getenv('TOKEN_ENCRYPTION_KEY')
    db_path = os.getenv('DATABASE_PATH', './data/users.db')
    port = int(os.getenv('PORT', '8080'))

    # Validate required environment variables
    required_vars = {
        'GOOGLE_CLIENT_ID': client_id,
        'GOOGLE_CLIENT_SECRET': client_secret,
        'GOOGLE_REDIRECT_URI': redirect_uri,
        'TOKEN_ENCRYPTION_KEY': encryption_key
    }

    missing = [k for k, v in required_vars.items() if not v]
    if missing:
        logger.error("Missing required environment variables: %s", ', '.join(missing))
        logger.error("Please set these in Railway dashboard or .env file")
        sys.exit(1)

    # Parse scopes
    scopes = [s.strip() for s in scopes_str.split(',') if s.strip()]
    if not scopes:
        scopes = [
            'openid',
            'https://www.googleapis.com/auth/gmail.modify',
            'https://www.googleapis.com/auth/calendar',
            'https://www.googleapis.com/auth/userinfo.email'
        ]
        logger.warning("No scopes provided, using defaults: %s", scopes)

    # Ensure database directory exists
    db_dir = Path(db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Database path: %s", db_path)

    # Initialize database
    try:
        database = Database(db_path, encryption_key)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize database: %s", str(e))
        sys.exit(1)

    # Initialize web server
    try:
        web_server = WebServer(
            database=database,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scopes=scopes
        )
        logger.info("Web server initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize web server: %s", str(e))
        sys.exit(1)

    # Start server
    logger.info("Starting server on port %d...", port)
    try:
        web_server.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        logger.error("Server error: %s", str(e))
        sys.exit(1)


if __name__ == '__main__':
    main()
