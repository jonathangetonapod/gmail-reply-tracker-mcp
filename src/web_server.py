"""Web server for OAuth flow and user setup."""

import os
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, request, redirect, render_template_string, jsonify
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
import secrets

from database import Database

logger = logging.getLogger(__name__)

# HTML templates
SETUP_START_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>MCP Server Setup</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 600px;
            margin: 100px auto;
            padding: 20px;
            text-align: center;
        }
        .card {
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
        }
        p {
            color: #666;
            margin-bottom: 30px;
        }
        .button {
            background: #4285f4;
            color: white;
            border: none;
            padding: 15px 40px;
            font-size: 16px;
            border-radius: 6px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }
        .button:hover {
            background: #357ae8;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>📬 Gmail + Calendar MCP Setup</h1>
        <p>Connect your Google account to enable Gmail and Calendar tools in Claude</p>
        <a href="{{ auth_url }}" class="button">Sign in with Google</a>
    </div>
</body>
</html>
"""

FATHOM_FORM_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Add Fathom Integration</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 600px;
            margin: 100px auto;
            padding: 20px;
        }
        .card {
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
        }
        .success {
            color: #28a745;
            margin-bottom: 20px;
        }
        p {
            color: #666;
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 10px;
            color: #333;
            font-weight: 500;
        }
        input[type="text"] {
            width: 100%;
            padding: 12px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 14px;
            box-sizing: border-box;
        }
        .button {
            background: #4285f4;
            color: white;
            border: none;
            padding: 15px 40px;
            font-size: 16px;
            border-radius: 6px;
            cursor: pointer;
            margin-right: 10px;
        }
        .button:hover {
            background: #357ae8;
        }
        .button-secondary {
            background: #6c757d;
        }
        .button-secondary:hover {
            background: #5a6268;
        }
        .help-text {
            font-size: 12px;
            color: #999;
            margin-top: 8px;
        }
        .buttons {
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="success">✓ Gmail & Calendar Connected</div>
        <h1>🎙️ Fathom Integration (Optional)</h1>
        <p>Enter your Fathom API key to enable meeting transcripts and summaries</p>

        <form method="POST" action="/setup/fathom">
            <input type="hidden" name="email" value="{{ email }}">

            <label for="fathom_key">Fathom API Key:</label>
            <input type="text" id="fathom_key" name="fathom_key" placeholder="fathom_...">
            <div class="help-text">
                Get your API key from: <a href="https://fathom.video/settings/integrations" target="_blank">fathom.video/settings/integrations</a>
            </div>

            <div class="buttons">
                <button type="submit" class="button">Save & Continue</button>
                <button type="submit" class="button button-secondary" formaction="/setup/skip">Skip</button>
            </div>
        </form>
    </div>
</body>
</html>
"""

SUCCESS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Setup Complete</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 600px;
            margin: 100px auto;
            padding: 20px;
        }
        .card {
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        h1 {
            color: #28a745;
            margin-bottom: 20px;
        }
        .info {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            text-align: left;
        }
        .info strong {
            color: #333;
        }
        pre {
            background: #272822;
            color: #f8f8f2;
            padding: 15px;
            border-radius: 6px;
            overflow-x: auto;
        }
        .note {
            color: #666;
            font-size: 14px;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>✓ Setup Complete!</h1>

        <div class="info">
            <strong>Your Email:</strong> {{ email }}<br>
            <strong>Server:</strong> {{ server_url }}<br>
            <strong>Gmail & Calendar:</strong> ✓ Enabled<br>
            <strong>Fathom:</strong> {{ '✓ Enabled' if has_fathom else '✗ Not configured' }}
        </div>

        <h3>Claude Desktop Configuration</h3>
        <p>The setup script has automatically configured your Claude Desktop. Simply restart Claude Desktop to start using the tools!</p>

        <p>If you need to manually configure, add this to your Claude config:</p>
        <pre>{{ config_json }}</pre>

        <div class="note">
            You can close this window and return to your terminal.
        </div>
    </div>
</body>
</html>
"""


class WebServer:
    """Web server for OAuth flow and user management."""

    def __init__(
        self,
        database: Database,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: list[str]
    ):
        """
        Initialize web server.

        Args:
            database: Database instance
            client_id: Google OAuth client ID
            client_secret: Google OAuth client secret
            redirect_uri: OAuth redirect URI
            scopes: List of OAuth scopes
        """
        self.database = database
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes

        self.app = Flask(__name__)
        self.app.secret_key = os.getenv('SESSION_SECRET', secrets.token_urlsafe(32))

        # Store temporary state during OAuth flow
        self.oauth_states = {}

        self._register_routes()

    def _register_routes(self):
        """Register Flask routes."""

        @self.app.route('/')
        def index():
            """Home page."""
            return """
            <h1>Gmail + Calendar + Fathom MCP Server</h1>
            <p>Multi-tenant server for Claude Desktop</p>
            <ul>
                <li><a href="/setup">Setup your account</a></li>
                <li><a href="/health">Health check</a></li>
            </ul>
            """

        @self.app.route('/health')
        def health():
            """Health check endpoint."""
            return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

        @self.app.route('/setup')
        def setup_start():
            """Start setup flow - redirect to Google OAuth."""
            # Create OAuth flow
            flow = Flow.from_client_config(
                {
                    "web": {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [self.redirect_uri]
                    }
                },
                scopes=self.scopes
            )
            flow.redirect_uri = self.redirect_uri

            # Generate authorization URL
            authorization_url, state = flow.authorization_url(
                access_type='offline',
                prompt='consent'  # Force consent to get refresh token
            )

            # Store flow state temporarily
            self.oauth_states[state] = {
                "flow": flow,
                "timestamp": datetime.now()
            }

            # Redirect to Google
            return redirect(authorization_url)

        @self.app.route('/auth/callback')
        def oauth_callback():
            """Handle OAuth callback from Google."""
            state = request.args.get('state')
            code = request.args.get('code')
            error = request.args.get('error')

            if error:
                return f"<h1>Authentication Error</h1><p>{error}</p>", 400

            if not state or state not in self.oauth_states:
                return "<h1>Error</h1><p>Invalid state parameter</p>", 400

            # Retrieve flow
            flow_data = self.oauth_states[state]
            flow = flow_data['flow']

            # Exchange code for token
            try:
                flow.fetch_token(code=code)
                credentials = flow.credentials

                # Get user email
                from googleapiclient.discovery import build
                service = build('oauth2', 'v2', credentials=credentials)
                user_info = service.userinfo().get().execute()
                email = user_info.get('email')

                # Store credentials token temporarily for Fathom setup
                token_dict = {
                    'token': credentials.token,
                    'refresh_token': credentials.refresh_token,
                    'token_uri': credentials.token_uri,
                    'client_id': credentials.client_id,
                    'client_secret': credentials.client_secret,
                    'scopes': credentials.scopes,
                    'expiry': credentials.expiry.isoformat() if credentials.expiry else None
                }

                # Store temporarily in oauth_states with email as key
                self.oauth_states[email] = {
                    'credentials': token_dict,
                    'timestamp': datetime.now()
                }

                # Clean up state
                del self.oauth_states[state]

                # Show Fathom form
                return render_template_string(FATHOM_FORM_HTML, email=email)

            except Exception as e:
                logger.error("OAuth callback error: %s", str(e))
                return f"<h1>Error</h1><p>Failed to complete authentication: {str(e)}</p>", 500

        @self.app.route('/setup/fathom', methods=['POST'])
        def setup_fathom():
            """Save Fathom API key and complete setup."""
            email = request.form.get('email')
            fathom_key = request.form.get('fathom_key', '').strip()

            if not email:
                return "<h1>Error</h1><p>Email missing</p>", 400

            # Retrieve stored credentials
            if email not in self.oauth_states:
                return "<h1>Error</h1><p>Session expired. Please start setup again.</p>", 400

            creds_data = self.oauth_states[email]
            token_dict = creds_data['credentials']

            try:
                # Save to database
                user_data = self.database.create_user(
                    email=email,
                    google_token=token_dict,
                    fathom_key=fathom_key if fathom_key else None
                )

                # Clean up temporary storage
                del self.oauth_states[email]

                # Show success with token
                session_token = user_data['session_token']
                config_json = json.dumps({
                    "mcpServers": {
                        "gmail-railway": {
                            "command": "npx",
                            "args": [
                                "-y",
                                "@modelcontextprotocol/server-fetch",
                                f"{self.redirect_uri.rsplit('/', 2)[0]}/mcp",
                                "--header",
                                f"Authorization: Bearer {session_token}"
                            ]
                        }
                    }
                }, indent=2)

                return render_template_string(
                    SUCCESS_HTML,
                    email=email,
                    token=session_token,
                    server_url=self.redirect_uri.rsplit('/', 2)[0],
                    has_fathom=bool(fathom_key),
                    config_json=config_json
                )

            except Exception as e:
                logger.error("Failed to save user: %s", str(e))
                return f"<h1>Error</h1><p>Failed to save configuration: {str(e)}</p>", 500

        @self.app.route('/setup/skip', methods=['POST'])
        def setup_skip():
            """Skip Fathom setup and complete."""
            email = request.form.get('email')

            if not email:
                return "<h1>Error</h1><p>Email missing</p>", 400

            # Retrieve stored credentials
            if email not in self.oauth_states:
                return "<h1>Error</h1><p>Session expired. Please start setup again.</p>", 400

            creds_data = self.oauth_states[email]
            token_dict = creds_data['credentials']

            try:
                # Save to database without Fathom key
                user_data = self.database.create_user(
                    email=email,
                    google_token=token_dict,
                    fathom_key=None
                )

                # Clean up temporary storage
                del self.oauth_states[email]

                # Show success with token
                session_token = user_data['session_token']
                config_json = json.dumps({
                    "mcpServers": {
                        "gmail-railway": {
                            "command": "npx",
                            "args": [
                                "-y",
                                "@modelcontextprotocol/server-fetch",
                                f"{self.redirect_uri.rsplit('/', 2)[0]}/mcp",
                                "--header",
                                f"Authorization: Bearer {session_token}"
                            ]
                        }
                    }
                }, indent=2)

                return render_template_string(
                    SUCCESS_HTML,
                    email=email,
                    token=session_token,
                    server_url=self.redirect_uri.rsplit('/', 2)[0],
                    has_fathom=False,  # Skip endpoint means no Fathom
                    config_json=config_json
                )

            except Exception as e:
                logger.error("Failed to save user: %s", str(e))
                return f"<h1>Error</h1><p>Failed to save configuration: {str(e)}</p>", 500

        @self.app.route('/admin/users')
        def admin_users():
            """List all users (admin endpoint)."""
            # TODO: Add authentication
            users = self.database.list_users()
            return jsonify({"users": users})

    def run(self, host='0.0.0.0', port=8080, debug=False):
        """
        Run the web server.

        Args:
            host: Host to bind to
            port: Port to bind to
            debug: Enable debug mode
        """
        logger.info("Starting web server on %s:%d", host, port)
        self.app.run(host=host, port=port, debug=debug)
