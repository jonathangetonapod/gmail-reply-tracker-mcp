"""Web server for OAuth flow and user setup."""

import os
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, request, redirect, render_template_string, jsonify, send_file
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

SETUP_LANDING_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Gmail & Calendar Setup</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            padding: 40px 20px;
        }
        .container {
            max-width: 600px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 40px;
        }
        h1 {
            color: #333;
            font-size: 28px;
            margin-bottom: 10px;
        }
        .subtitle {
            color: #666;
            font-size: 16px;
            margin-bottom: 30px;
        }
        .step {
            margin: 20px 0;
            padding: 20px;
            background: #fafafa;
            border-radius: 6px;
        }
        .step-title {
            font-weight: 600;
            color: #333;
            margin-bottom: 8px;
        }
        .step-desc {
            color: #666;
            font-size: 14px;
            line-height: 1.5;
        }
        .start-button {
            display: block;
            background: #2196f3;
            color: white;
            text-align: center;
            padding: 14px;
            border-radius: 6px;
            text-decoration: none;
            font-size: 16px;
            font-weight: 500;
            margin: 30px 0 10px;
        }
        .start-button:hover {
            background: #1976d2;
        }
        .note {
            text-align: center;
            color: #999;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Gmail & Calendar Setup</h1>
        <p class="subtitle">Connect Claude to your Gmail and Google Calendar</p>

        <div class="step">
            <div class="step-title">Step 1: Connect Google Account</div>
            <div class="step-desc">Sign in with Google to authorize Gmail and Calendar access</div>
        </div>

        <div class="step">
            <div class="step-title">Step 2: Fathom (Optional)</div>
            <div class="step-desc">Add your Fathom API key if you use it, or skip this step</div>
        </div>

        <div class="step">
            <div class="step-title">Step 3: Install</div>
            <div class="step-desc">Run one command in your terminal to connect Claude Desktop</div>
        </div>

        <a href="{{ server_url }}/setup/start" class="start-button">Start Setup</a>
        <p class="note">Takes 2 minutes</p>
    </div>
</body>
</html>
"""

FATHOM_FORM_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Step 2: Fathom (Optional)</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            padding: 40px 20px;
        }
        .card {
            max-width: 600px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 40px;
        }
        .progress {
            color: #999;
            font-size: 14px;
            margin-bottom: 10px;
        }
        h1 {
            color: #333;
            margin-bottom: 8px;
            font-size: 24px;
        }
        .success {
            color: #28a745;
            margin-bottom: 20px;
            font-size: 14px;
        }
        p {
            color: #666;
            margin-bottom: 20px;
            line-height: 1.5;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 500;
            font-size: 14px;
        }
        input[type="text"] {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            box-sizing: border-box;
        }
        input[type="text"]:focus {
            outline: none;
            border-color: #2196f3;
        }
        .button {
            background: #2196f3;
            color: white;
            border: none;
            padding: 12px;
            font-size: 14px;
            font-weight: 500;
            border-radius: 4px;
            cursor: pointer;
            width: 100%;
            margin-bottom: 10px;
        }
        .button:hover {
            background: #1976d2;
        }
        .button-secondary {
            background: #757575;
        }
        .button-secondary:hover {
            background: #616161;
        }
        .help-text {
            font-size: 12px;
            color: #999;
            margin-top: 6px;
        }
        .help-text a {
            color: #2196f3;
            text-decoration: none;
        }
        .buttons {
            margin-top: 20px;
        }
        .note {
            text-align: center;
            color: #999;
            font-size: 13px;
            margin-top: 15px;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="progress">Step 2 of 3</div>
        <div class="success">✓ Google Connected</div>
        <h1>Fathom Integration (Optional)</h1>
        <p>Add your Fathom API key if you use it, otherwise skip this step.</p>

        <form method="POST" action="/setup/fathom">
            <input type="hidden" name="email" value="{{ email }}">

            <label for="fathom_key">Fathom API Key:</label>
            <input type="text" id="fathom_key" name="fathom_key" placeholder="Optional">
            <div class="help-text">
                Get your key at <a href="https://fathom.video/settings/integrations" target="_blank">fathom.video/settings/integrations</a>
            </div>

            <div class="buttons">
                <button type="submit" class="button">Save & Continue</button>
                <button type="submit" class="button button-secondary" formaction="/setup/skip">Skip</button>
            </div>
        </form>

        <div class="note">You can add this later in settings</div>
    </div>
</body>
</html>
"""

SUCCESS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Step 3: Install</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            padding: 40px 20px;
        }
        .card {
            max-width: 700px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 40px;
        }
        .progress {
            color: #999;
            font-size: 14px;
            margin-bottom: 10px;
        }
        h1 {
            color: #333;
            margin-bottom: 8px;
            font-size: 24px;
        }
        .success {
            color: #28a745;
            margin-bottom: 20px;
            font-size: 14px;
        }
        .status {
            background: #fafafa;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
            font-size: 14px;
        }
        .status-line {
            padding: 4px 0;
            color: #666;
        }
        h2 {
            color: #333;
            font-size: 18px;
            margin: 30px 0 15px;
        }
        .os-select {
            font-size: 14px;
            color: #666;
            margin-bottom: 15px;
        }
        select {
            padding: 8px;
            font-size: 14px;
            border: 1px solid #ddd;
            border-radius: 4px;
            margin-left: 8px;
        }
        .command-box {
            background: #f5f5f5;
            padding: 15px;
            border-radius: 4px;
            margin: 15px 0;
            position: relative;
            border: 1px solid #ddd;
        }
        .command-box pre {
            color: #333;
            font-size: 13px;
            overflow-x: auto;
            margin: 0;
            font-family: monospace;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .copy-btn {
            background: #2196f3;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 13px;
            margin-top: 10px;
        }
        .copy-btn:hover {
            background: #1976d2;
        }
        .instructions {
            background: #fafafa;
            padding: 15px;
            border-radius: 4px;
            margin: 15px 0;
            font-size: 14px;
            line-height: 1.6;
            color: #666;
        }
        .examples {
            background: #fafafa;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
        }
        .examples h3 {
            color: #333;
            font-size: 14px;
            margin-bottom: 10px;
            font-weight: 600;
        }
        .examples ul {
            list-style: none;
            padding: 0;
            margin: 0;
        }
        .examples li {
            padding: 6px 0;
            color: #666;
            font-size: 13px;
        }
        .footer {
            text-align: center;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            font-size: 13px;
            color: #999;
        }
        .footer a {
            color: #2196f3;
            text-decoration: none;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="progress">Step 3 of 3</div>
        <div class="success">✓ Setup Complete</div>
        <h1>Final Step: Install</h1>

        <div class="status">
            <div class="status-line"><strong>Email:</strong> {{ email }}</div>
            <div class="status-line"><strong>Gmail & Calendar:</strong> Connected</div>
            <div class="status-line"><strong>Fathom:</strong> {{ 'Connected' if has_fathom else 'Skipped' }}</div>
        </div>

        <h2>Run this command:</h2>
        <div class="os-select">
            <label>
                Operating System:
                <select id="os-select" onchange="showCommand()">
                    <option value="mac">Mac / Linux</option>
                    <option value="windows">Windows</option>
                </select>
            </label>
        </div>

        <div id="mac-command" class="command-container">
            <div class="command-box">
                <pre>curl -fsSL {{ server_url }}/install.sh | bash -s {{ token }}</pre>
            </div>
            <button class="copy-btn" onclick="copyToClipboard('mac')">Copy Command</button>
            <div class="instructions">
                1. Copy the command above<br>
                2. Open Terminal<br>
                3. Paste and press Enter<br>
                4. Restart Claude Desktop
            </div>
        </div>

        <div id="windows-command" class="command-container" style="display:none;">
            <div class="command-box">
                <pre>$env:MCP_SESSION_TOKEN = "{{ token }}"; Invoke-WebRequest -Uri "{{ server_url }}/install.ps1" -UseBasicParsing | Invoke-Expression</pre>
            </div>
            <button class="copy-btn" onclick="copyToClipboard('windows')">Copy Command</button>
            <div class="instructions">
                1. Copy the command above<br>
                2. Open PowerShell<br>
                3. Paste and press Enter<br>
                4. Restart Claude Desktop
            </div>
        </div>

        <div class="examples">
            <h3>What you can ask Claude:</h3>
            <ul>
                <li>"Show me unreplied emails from last week"</li>
                <li>"What's on my calendar tomorrow?"</li>
                <li>"Search emails about project proposal"</li>
            </ul>
        </div>

        <div class="footer">
            <a href="{{ server_url }}/settings?token={{ token }}">Settings</a>
        </div>
    </div>

    <script>
        function showCommand() {
            const os = document.getElementById('os-select').value;
            document.getElementById('mac-command').style.display = os === 'mac' ? 'block' : 'none';
            document.getElementById('windows-command').style.display = os === 'windows' ? 'block' : 'none';
        }

        function copyToClipboard(os) {
            const commands = {
                'mac': 'curl -fsSL {{ server_url }}/install.sh | bash -s {{ token }}',
                'windows': '$env:MCP_SESSION_TOKEN = "{{ token }}"; Invoke-WebRequest -Uri "{{ server_url }}/install.ps1" -UseBasicParsing | Invoke-Expression'
            };

            navigator.clipboard.writeText(commands[os]).then(() => {
                event.target.textContent = '✓ Copied!';
                setTimeout(() => {
                    event.target.textContent = 'Copy Command';
                }, 2000);
            });
        }
    </script>
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
        def setup_landing():
            """Show setup landing page with explanation."""
            server_url = os.environ.get('SERVER_URL', request.host_url.rstrip('/'))
            return render_template_string(SETUP_LANDING_HTML, server_url=server_url)

        @self.app.route('/setup/start')
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
                        "gmail-calendar-fathom": {
                            "command": "node",
                            "args": [
                                "/path/to/http-mcp-client.js",
                                f"{self.redirect_uri.rsplit('/', 2)[0]}/mcp",
                                session_token
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
                        "gmail-calendar-fathom": {
                            "command": "node",
                            "args": [
                                "/path/to/http-mcp-client.js",
                                f"{self.redirect_uri.rsplit('/', 2)[0]}/mcp",
                                session_token
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

        @self.app.route('/mcp', methods=['POST'])
        def mcp_endpoint():
            """Handle MCP protocol requests over HTTP."""
            import asyncio

            # Get Authorization header
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                return jsonify({"error": "Missing or invalid Authorization header"}), 401

            session_token = auth_header[7:]  # Remove 'Bearer ' prefix

            # Get user from database
            user = self.database.get_user_by_session(session_token)
            if not user:
                return jsonify({"error": "Invalid or expired token"}), 401

            # Get MCP request
            try:
                request_data = request.get_json()
            except Exception:
                return jsonify({"error": "Invalid JSON"}), 400

            # Handle MCP request
            from mcp_handler import MCPHandler
            handler = MCPHandler()

            # Run async handler in event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                response = loop.run_until_complete(
                    handler.handle_request(
                        request_data,
                        user['google_token'],
                        user.get('fathom_key')
                    )
                )
            finally:
                loop.close()

            return jsonify(response)

        @self.app.route('/download/credentials')
        def download_credentials():
            """Download credentials for local MCP server setup."""
            # Get session token from query parameter
            session_token = request.args.get('token')
            if not session_token:
                return "Missing token parameter", 400

            # Get user from database
            user = self.database.get_user_by_session(session_token)
            if not user:
                return "Invalid or expired token", 401

            # Create credentials file
            google_token = user['google_token']
            credentials_data = {
                "installed": {
                    "client_id": google_token['client_id'],
                    "client_secret": google_token['client_secret'],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": google_token['token_uri'],
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "redirect_uris": ["http://localhost"]
                }
            }

            # Create token file
            token_data = {
                "token": google_token['token'],
                "refresh_token": google_token['refresh_token'],
                "token_uri": google_token['token_uri'],
                "client_id": google_token['client_id'],
                "client_secret": google_token['client_secret'],
                "scopes": google_token['scopes'],
                "expiry": google_token.get('expiry')
            }

            # Return as downloadable files
            response = {
                "credentials.json": json.dumps(credentials_data, indent=2),
                "token.json": json.dumps(token_data, indent=2),
                "fathom_key": user.get('fathom_key'),
                "setup_instructions": """
1. Save 'credentials.json' and 'token.json' to your MCP server's credentials/ folder
2. Set FATHOM_API_KEY in your environment if you have one
3. Configure Claude Desktop with the local server path
4. Restart Claude Desktop
"""
            }

            return jsonify(response)

        @self.app.route('/settings')
        def settings_page():
            """Show settings page for updating Fathom API key."""
            # Get session token from query parameter
            session_token = request.args.get('token')
            if not session_token:
                return """
                    <h1>Settings</h1>
                    <p>Please provide your session token as a query parameter:</p>
                    <code>?token=YOUR_SESSION_TOKEN</code>
                """, 400

            # Get user from database
            user = self.database.get_user_by_session(session_token)
            if not user:
                return "<h1>Error</h1><p>Invalid or expired token</p>", 401

            # Show settings page
            settings_html = """
<!DOCTYPE html>
<html>
<head>
    <title>Settings - Gmail MCP Server</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 600px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .card {
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        h1 { color: #333; margin-bottom: 10px; }
        .info {
            background: #e3f2fd;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
            border-left: 4px solid #2196f3;
        }
        label {
            display: block;
            margin-top: 20px;
            font-weight: bold;
            color: #333;
        }
        input[type="text"] {
            width: 100%;
            padding: 12px;
            margin-top: 8px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 14px;
            box-sizing: border-box;
        }
        button {
            background: #2196f3;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
            margin-top: 20px;
            width: 100%;
        }
        button:hover {
            background: #1976d2;
        }
        .remove-btn {
            background: #f44336;
        }
        .remove-btn:hover {
            background: #d32f2f;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>⚙️ Settings</h1>

        <div class="info">
            <strong>Email:</strong> {{ email }}<br>
            <strong>Gmail & Calendar:</strong> ✓ Connected<br>
            <strong>Fathom:</strong> {{ '✓ Connected' if has_fathom else '✗ Not configured' }}
        </div>

        <h2>Update Fathom API Key</h2>
        <form method="POST" action="/settings/update-fathom">
            <input type="hidden" name="token" value="{{ token }}">

            <label for="fathom_key">Fathom API Key</label>
            <input
                type="text"
                id="fathom_key"
                name="fathom_key"
                placeholder="Enter your Fathom API key"
                value="{{ current_fathom_key if current_fathom_key else '' }}"
            >
            <small style="color: #666; display: block; margin-top: 5px;">
                Leave blank to remove Fathom integration
            </small>

            <button type="submit">Update Fathom Key</button>
        </form>

        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee;">
            <p style="color: #666; font-size: 14px;">
                <strong>Note:</strong> Changes take effect immediately. No need to restart Claude Desktop.
            </p>
        </div>
    </div>
</body>
</html>
            """

            return render_template_string(
                settings_html,
                email=user['email'],
                token=session_token,
                has_fathom=bool(user.get('fathom_key')),
                current_fathom_key=user.get('fathom_key', '')
            )

        @self.app.route('/settings/update-fathom', methods=['POST'])
        def update_fathom():
            """Update Fathom API key."""
            session_token = request.form.get('token')
            fathom_key = request.form.get('fathom_key', '').strip()

            if not session_token:
                return "<h1>Error</h1><p>Missing session token</p>", 400

            # Get user from database
            user = self.database.get_user_by_session(session_token)
            if not user:
                return "<h1>Error</h1><p>Invalid or expired token</p>", 401

            try:
                # Update Fathom key in database
                self.database.update_fathom_key(
                    user['id'],
                    fathom_key if fathom_key else None
                )

                # Show success message
                success_html = """
<!DOCTYPE html>
<html>
<head>
    <title>Settings Updated</title>
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
        h1 { color: #28a745; }
        a {
            display: inline-block;
            margin-top: 20px;
            color: #2196f3;
            text-decoration: none;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>✓ Settings Updated!</h1>
        <p>Your Fathom API key has been {{ 'updated' if fathom_key else 'removed' }}.</p>
        <p>Changes are active immediately - no restart needed.</p>
        <a href="/settings?token={{ token }}">← Back to Settings</a>
    </div>
</body>
</html>
                """

                return render_template_string(
                    success_html,
                    fathom_key=fathom_key,
                    token=session_token
                )

            except Exception as e:
                logger.error("Failed to update Fathom key: %s", str(e))
                return f"<h1>Error</h1><p>Failed to update: {str(e)}</p>", 500

        @self.app.route('/download/http-mcp-client.js')
        def download_http_client():
            """Download the HTTP MCP client JavaScript file."""
            import os
            # Path to the http-mcp-client.js file
            client_path = os.path.join(os.path.dirname(__file__), '..', 'public', 'http-mcp-client.js')
            if not os.path.exists(client_path):
                # Fallback to root directory
                client_path = os.path.join(os.path.dirname(__file__), '..', 'http-mcp-client.js')

            if not os.path.exists(client_path):
                return "Client file not found", 404

            return send_file(
                client_path,
                as_attachment=True,
                download_name='http-mcp-client.js',
                mimetype='application/javascript'
            )

        @self.app.route('/install.sh')
        def download_install_sh():
            """Download the automated setup script for Mac/Linux."""
            import os
            script_path = os.path.join(os.path.dirname(__file__), '..', 'install.sh')
            if not os.path.exists(script_path):
                return "Install script not found", 404

            return send_file(
                script_path,
                as_attachment=False,
                download_name='install.sh',
                mimetype='text/x-shellscript'
            )

        @self.app.route('/install.ps1')
        def download_install_ps1():
            """Download the automated setup script for Windows."""
            import os
            script_path = os.path.join(os.path.dirname(__file__), '..', 'install.ps1')
            if not os.path.exists(script_path):
                return "Install script not found", 404

            return send_file(
                script_path,
                as_attachment=False,
                download_name='install.ps1',
                mimetype='text/plain'
            )

        @self.app.route('/admin/users')
        def admin_users():
            """List all users (admin endpoint)."""
            # Simple admin authentication via environment variable
            admin_token = request.headers.get('Authorization', '').replace('Bearer ', '')
            expected_token = os.environ.get('ADMIN_TOKEN', 'change-me-in-production')

            if admin_token != expected_token:
                return jsonify({"error": "Unauthorized"}), 401

            users = self.database.list_users()

            # Remove sensitive data
            safe_users = []
            for user in users:
                safe_users.append({
                    "id": user["user_id"],
                    "email": user["email"],
                    "has_fathom": user.get("has_fathom", False),
                    "session_token": "...available via /admin",  # Don't expose full tokens
                    "created_at": user.get("created_at", "")
                })

            return jsonify({"users": safe_users, "count": len(safe_users)})

        @self.app.route('/admin')
        def admin_dashboard():
            """Admin dashboard for managing users."""
            import os
            admin_token = request.args.get('token')
            expected_token = os.environ.get('ADMIN_TOKEN', 'change-me-in-production')

            if admin_token != expected_token:
                return """
                    <h1>Admin Dashboard</h1>
                    <p>Please provide admin token as query parameter:</p>
                    <code>?token=YOUR_ADMIN_TOKEN</code>
                """, 401

            admin_html = """
<!DOCTYPE html>
<html>
<head>
    <title>Admin Dashboard</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .card {
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        h1 { color: #333; margin-bottom: 10px; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        th, td {
            text-align: left;
            padding: 12px;
            border-bottom: 1px solid #ddd;
        }
        th {
            background: #f8f9fa;
            font-weight: bold;
        }
        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
        }
        .badge-success { background: #d4edda; color: #155724; }
        .badge-secondary { background: #e2e3e5; color: #383d41; }
        button {
            background: #007bff;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }
        button:hover { background: #0056b3; }
        .update-form {
            display: none;
            margin-top: 10px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 6px;
        }
        .update-form input {
            width: 300px;
            padding: 8px;
            margin-right: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>🔐 Admin Dashboard</h1>
        <p style="color: #666;">Manage user accounts and Fathom API keys</p>
    </div>

    <div class="card">
        <h2>Users</h2>
        <table id="users-table">
            <thead>
                <tr>
                    <th>Email</th>
                    <th>User ID</th>
                    <th>Fathom Status</th>
                    <th>Session Token</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                <tr><td colspan="5" style="text-align: center;">Loading...</td></tr>
            </tbody>
        </table>
    </div>

    <script>
        const adminToken = '{{ admin_token }}';

        async function loadUsers() {
            try {
                const response = await fetch('/admin/users', {
                    headers: {
                        'Authorization': `Bearer ${adminToken}`
                    }
                });
                const data = await response.json();

                const tbody = document.querySelector('#users-table tbody');
                tbody.innerHTML = '';

                data.users.forEach(user => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td><strong>${user.email}</strong></td>
                        <td><code style="font-size: 12px;">${user.id.substring(0, 12)}...</code></td>
                        <td>
                            <span class="badge ${user.has_fathom ? 'badge-success' : 'badge-secondary'}">
                                ${user.has_fathom ? '✓ Connected' : '✗ Not set'}
                            </span>
                        </td>
                        <td><code style="font-size: 11px;">${user.session_token}</code></td>
                        <td>
                            <button onclick="showUpdateForm('${user.email}', '${user.id}')">
                                Update Fathom
                            </button>
                            <div id="update-form-${user.id}" class="update-form">
                                <input
                                    type="text"
                                    id="fathom-key-${user.id}"
                                    placeholder="Enter new Fathom API key"
                                >
                                <button onclick="updateFathom('${user.id}', '${user.email}')">Save</button>
                                <button onclick="removeFathom('${user.id}', '${user.email}')" style="background: #dc3545;">Remove</button>
                                <button onclick="hideUpdateForm('${user.id}')" style="background: #6c757d;">Cancel</button>
                            </div>
                        </td>
                    `;
                    tbody.appendChild(row);
                });
            } catch (error) {
                console.error('Error loading users:', error);
            }
        }

        function showUpdateForm(email, userId) {
            document.getElementById(`update-form-${userId}`).style.display = 'block';
        }

        function hideUpdateForm(userId) {
            document.getElementById(`update-form-${userId}`).style.display = 'none';
        }

        async function updateFathom(userId, email) {
            const fathomKey = document.getElementById(`fathom-key-${userId}`).value;

            if (!fathomKey) {
                alert('Please enter a Fathom API key');
                return;
            }

            try {
                const response = await fetch('/admin/update-fathom', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${adminToken}`
                    },
                    body: JSON.stringify({
                        user_id: userId,
                        fathom_key: fathomKey
                    })
                });

                if (response.ok) {
                    alert(`✓ Updated Fathom key for ${email}`);
                    loadUsers();
                } else {
                    alert('Error updating Fathom key');
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }

        async function removeFathom(userId, email) {
            if (!confirm(`Remove Fathom API key for ${email}?`)) return;

            try {
                const response = await fetch('/admin/update-fathom', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${adminToken}`
                    },
                    body: JSON.stringify({
                        user_id: userId,
                        fathom_key: null
                    })
                });

                if (response.ok) {
                    alert(`✓ Removed Fathom key for ${email}`);
                    loadUsers();
                } else {
                    alert('Error removing Fathom key');
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }

        // Load users on page load
        loadUsers();

        // Refresh every 30 seconds
        setInterval(loadUsers, 30000);
    </script>
</body>
</html>
            """

            return render_template_string(admin_html, admin_token=admin_token)

        @self.app.route('/admin/update-fathom', methods=['POST'])
        def admin_update_fathom():
            """Admin endpoint to update user's Fathom key."""
            import os
            admin_token = request.headers.get('Authorization', '').replace('Bearer ', '')
            expected_token = os.environ.get('ADMIN_TOKEN', 'change-me-in-production')

            if admin_token != expected_token:
                return jsonify({"error": "Unauthorized"}), 401

            data = request.get_json()
            user_id = data.get('user_id')
            fathom_key = data.get('fathom_key')

            if not user_id:
                return jsonify({"error": "Missing user_id"}), 400

            try:
                self.database.update_fathom_key(user_id, fathom_key)
                return jsonify({
                    "success": True,
                    "message": f"Updated Fathom key for user {user_id}"
                })
            except Exception as e:
                logger.error("Failed to update Fathom key: %s", str(e))
                return jsonify({"error": str(e)}), 500

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
