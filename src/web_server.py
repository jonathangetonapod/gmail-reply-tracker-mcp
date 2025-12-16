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
            max-width: 800px;
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
        h1 {
            color: #28a745;
            margin-bottom: 10px;
        }
        h2 {
            color: #333;
            font-size: 20px;
            margin-top: 30px;
            margin-bottom: 15px;
        }
        .info {
            background: #e8f5e9;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            border-left: 4px solid #28a745;
        }
        .info strong {
            color: #2e7d32;
        }
        .step {
            background: #f8f9fa;
            padding: 15px 20px;
            border-radius: 8px;
            margin: 15px 0;
            border-left: 4px solid #007bff;
        }
        .step-number {
            display: inline-block;
            background: #007bff;
            color: white;
            width: 28px;
            height: 28px;
            border-radius: 50%;
            text-align: center;
            line-height: 28px;
            margin-right: 10px;
            font-weight: bold;
        }
        pre {
            background: #272822;
            color: #f8f8f2;
            padding: 20px;
            border-radius: 6px;
            overflow-x: auto;
            font-size: 13px;
            line-height: 1.5;
        }
        .copy-btn {
            background: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            margin-top: 10px;
        }
        .copy-btn:hover {
            background: #0056b3;
        }
        .download-btn {
            background: #28a745;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
            text-decoration: none;
            display: inline-block;
            margin: 10px 0;
        }
        .download-btn:hover {
            background: #218838;
        }
        .note {
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
            font-size: 14px;
        }
        .config-location {
            background: #e3f2fd;
            padding: 10px 15px;
            border-radius: 6px;
            margin: 10px 0;
            font-family: monospace;
            font-size: 13px;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>✓ You're All Set!</h1>
        <p style="color: #666; font-size: 16px;">Your Gmail & Calendar are connected. Follow the steps below to finish setup.</p>

        <div class="info">
            <strong>Your Account:</strong> {{ email }}<br>
            <strong>Gmail & Calendar:</strong> ✓ Connected<br>
            <strong>Fathom:</strong> {{ '✓ Connected' if has_fathom else '✗ Not added' }}
        </div>

        <h2>🚀 Automated Installation (Recommended)</h2>
        <p style="color: #666; margin-bottom: 15px;">Copy and run ONE command - everything is done automatically!</p>

        <div class="step" style="border-left-color: #28a745;">
            <strong>Mac / Linux:</strong>
            <button class="copy-btn" onclick="copyCommand('mac-command')">📋 Copy Command</button>
            <pre id="mac-command" style="margin-top: 10px;">curl -fsSL {{ server_url }}/install.sh | bash -s {{ token }}</pre>
            <p style="margin: 10px 0 0 0; color: #666; font-size: 13px;">
                Open Terminal and paste the command above. It will:<br>
                • Download the MCP client<br>
                • Find your Claude config automatically<br>
                • Back up your existing config<br>
                • Add the Gmail/Calendar server<br>
                • Done! Just restart Claude Desktop
            </p>
        </div>

        <div class="step" style="border-left-color: #28a745;">
            <strong>Windows:</strong>
            <button class="copy-btn" onclick="copyCommand('windows-command')">📋 Copy Command</button>
            <pre id="windows-command" style="margin-top: 10px;">$env:MCP_SESSION_TOKEN = "{{ token }}"; Invoke-WebRequest -Uri "{{ server_url }}/install.ps1" -UseBasicParsing | Invoke-Expression</pre>
            <p style="margin: 10px 0 0 0; color: #666; font-size: 13px;">
                Open PowerShell and paste the command above. Same magic happens!
            </p>
        </div>

        <details style="margin-top: 30px;">
            <summary style="cursor: pointer; color: #007bff; font-weight: bold;">
                📝 Manual Installation (if you prefer)
            </summary>

            <div style="margin-top: 20px;">
                <div class="step">
                    <span class="step-number">1</span>
                    <strong>Download the connector file</strong><br>
                    <a href="{{ server_url }}/download/http-mcp-client.js" class="download-btn" download>Download http-mcp-client.js</a>
                    <p style="margin: 10px 0 0 38px; color: #666; font-size: 14px;">
                        Save this file somewhere permanent (e.g., your Documents folder). Don't delete it!
                    </p>
                </div>

                <div class="step">
                    <span class="step-number">2</span>
                    <strong>Open your Claude Desktop config file</strong><br>
                    <p style="margin: 10px 0 0 38px; color: #666;">The config file is located at:</p>
                    <div class="config-location" style="margin-left: 38px;">
                        <strong>Mac:</strong> ~/Library/Application Support/Claude/claude_desktop_config.json<br>
                        <strong>Windows:</strong> %APPDATA%\\Claude\\claude_desktop_config.json
                    </div>
                </div>

                <div class="step">
                    <span class="step-number">3</span>
                    <strong>Add this configuration</strong><br>
                    <p style="margin: 10px 0 0 38px; color: #666;">
                        Copy the code below and add it to your config file.
                        <strong>Replace</strong> <code>/path/to/http-mcp-client.js</code> with the actual path where you saved the file in Step 1.
                    </p>
                    <button class="copy-btn" onclick="copyConfig()" style="margin-left: 38px;">📋 Copy Configuration</button>
                    <pre id="config">{{ config_json }}</pre>
                </div>
            </div>
        </details>

        <div class="note">
            <strong>💡 After setup:</strong> Restart Claude Desktop. Then you can ask Claude to:
            <ul style="margin: 10px 0;">
                <li>"Show me my unreplied emails from the last 3 days"</li>
                <li>"List my calendar events for next week"</li>
                <li>"Search my emails for messages about project proposal"</li>
            </ul>
        </div>

        <div style="text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee;">
            <p style="color: #666; font-size: 14px;">
                <a href="{{ server_url }}/settings?token={{ token }}" style="color: #2196f3; text-decoration: none;">
                    ⚙️ Update Settings (Fathom API Key)
                </a>
            </p>
            <p style="color: #888; font-size: 14px; margin-top: 10px;">
                Need help? Contact your team admin.
            </p>
        </div>
    </div>

    <script>
        function copyConfig() {
            const config = document.getElementById('config').textContent;
            navigator.clipboard.writeText(config).then(() => {
                const btn = event.target;
                const originalText = btn.textContent;
                btn.textContent = '✓ Copied!';
                btn.style.background = '#28a745';
                setTimeout(() => {
                    btn.textContent = originalText;
                    btn.style.background = '#007bff';
                }, 2000);
            });
        }

        function copyCommand(elementId) {
            const command = document.getElementById(elementId).textContent;
            navigator.clipboard.writeText(command).then(() => {
                const btn = event.target;
                const originalText = btn.textContent;
                btn.textContent = '✓ Copied!';
                btn.style.background = '#28a745';
                setTimeout(() => {
                    btn.textContent = originalText;
                    btn.style.background = '#007bff';
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
