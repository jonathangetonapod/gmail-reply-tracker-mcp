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
    <title>Welcome to Gmail & Calendar MCP Setup</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            max-width: 700px;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 50px;
        }
        h1 {
            color: #333;
            font-size: 36px;
            margin-bottom: 10px;
            text-align: center;
        }
        .subtitle {
            text-align: center;
            color: #666;
            font-size: 18px;
            margin-bottom: 40px;
        }
        .big-number {
            display: inline-block;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            text-align: center;
            line-height: 50px;
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 15px;
        }
        .step {
            margin: 30px 0;
            padding-left: 10px;
        }
        .step h2 {
            color: #333;
            font-size: 22px;
            margin-bottom: 10px;
        }
        .step p {
            color: #555;
            font-size: 16px;
            line-height: 1.6;
            margin-bottom: 10px;
        }
        .step ul {
            list-style: none;
            padding-left: 20px;
            margin-top: 15px;
        }
        .step ul li {
            color: #666;
            font-size: 15px;
            line-height: 1.8;
            padding-left: 25px;
            position: relative;
        }
        .step ul li:before {
            content: "✓";
            position: absolute;
            left: 0;
            color: #28a745;
            font-weight: bold;
        }
        .start-button {
            display: block;
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
            text-align: center;
            padding: 20px 40px;
            border-radius: 12px;
            text-decoration: none;
            font-size: 20px;
            font-weight: bold;
            margin: 40px auto 20px;
            max-width: 400px;
            box-shadow: 0 4px 15px rgba(40, 167, 69, 0.4);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .start-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(40, 167, 69, 0.6);
        }
        .start-button:active {
            transform: translateY(0);
        }
        .time-estimate {
            text-align: center;
            color: #888;
            font-size: 14px;
            margin-top: 10px;
        }
        .info-box {
            background: #e3f2fd;
            border-left: 4px solid #2196f3;
            padding: 20px;
            border-radius: 8px;
            margin: 30px 0;
        }
        .info-box strong {
            color: #1976d2;
            font-size: 16px;
        }
        .info-box p {
            color: #555;
            margin-top: 10px;
            line-height: 1.6;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 Let's Get You Set Up!</h1>
        <p class="subtitle">Connect Claude to your Gmail & Calendar in 3 easy steps</p>

        <div class="step">
            <div class="big-number">1</div>
            <h2>Connect Your Google Account</h2>
            <p>You'll be asked to sign in with Google and grant permissions for:</p>
            <ul>
                <li>Reading and sending emails</li>
                <li>Viewing and creating calendar events</li>
            </ul>
            <p style="margin-top: 10px; color: #888; font-size: 14px;">
                ℹ️ Your credentials are encrypted and never shared. Each team member has their own separate account.
            </p>
        </div>

        <div class="step">
            <div class="big-number">2</div>
            <h2>Add Fathom API Key (Optional)</h2>
            <p>If you use Fathom for meeting notes, you can connect it too. Otherwise, just skip this step!</p>
        </div>

        <div class="step">
            <div class="big-number">3</div>
            <h2>Run One Command</h2>
            <p>Copy and paste one line into your terminal. That's it! It automatically:</p>
            <ul>
                <li>Downloads the connector file</li>
                <li>Finds your Claude config</li>
                <li>Updates it for you</li>
                <li>Creates a backup (just in case)</li>
            </ul>
        </div>

        <div class="info-box">
            <strong>💡 What you'll be able to do:</strong>
            <p>After setup, just ask Claude things like:<br><br>
            <em>"Show me emails I haven't replied to"</em><br>
            <em>"What's on my calendar tomorrow?"</em><br>
            <em>"Send an email to john@example.com about the meeting"</em></p>
        </div>

        <a href="{{ server_url }}/setup/start" class="start-button">
            ✨ Start Setup Now
        </a>
        <p class="time-estimate">⏱ Takes about 2 minutes</p>
    </div>
</body>
</html>
"""

FATHOM_FORM_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Step 2: Fathom Integration (Optional)</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .card {
            background: white;
            padding: 50px;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 600px;
            width: 100%;
        }
        .progress {
            text-align: center;
            color: #888;
            font-size: 14px;
            margin-bottom: 10px;
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
            text-align: center;
            font-size: 32px;
        }
        .success {
            text-align: center;
            color: #28a745;
            margin-bottom: 30px;
            font-size: 18px;
            font-weight: 500;
        }
        p {
            color: #666;
            margin-bottom: 25px;
            line-height: 1.6;
            text-align: center;
        }
        label {
            display: block;
            margin-bottom: 10px;
            color: #333;
            font-weight: 600;
            font-size: 15px;
        }
        input[type="text"] {
            width: 100%;
            padding: 14px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 15px;
            box-sizing: border-box;
            transition: border-color 0.2s;
        }
        input[type="text"]:focus {
            outline: none;
            border-color: #667eea;
        }
        .button {
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
            border: none;
            padding: 16px 40px;
            font-size: 18px;
            font-weight: bold;
            border-radius: 10px;
            cursor: pointer;
            width: 100%;
            margin-bottom: 15px;
            transition: transform 0.2s, box-shadow 0.2s;
            box-shadow: 0 4px 15px rgba(40, 167, 69, 0.3);
        }
        .button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(40, 167, 69, 0.5);
        }
        .button-secondary {
            background: linear-gradient(135deg, #6c757d 0%, #5a6268 100%);
            box-shadow: 0 4px 15px rgba(108, 117, 125, 0.3);
        }
        .button-secondary:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(108, 117, 125, 0.5);
        }
        .help-text {
            font-size: 13px;
            color: #888;
            margin-top: 10px;
            line-height: 1.5;
        }
        .help-text a {
            color: #667eea;
            text-decoration: none;
        }
        .help-text a:hover {
            text-decoration: underline;
        }
        .buttons {
            margin-top: 30px;
        }
        .skip-note {
            text-align: center;
            color: #999;
            font-size: 14px;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="progress">Step 2 of 3</div>
        <div class="success">✓ Google Account Connected!</div>
        <h1>🎙️ Fathom Integration</h1>
        <p>If you use Fathom for meeting notes, add your API key. Otherwise, click Skip!</p>

        <form method="POST" action="/setup/fathom">
            <input type="hidden" name="email" value="{{ email }}">

            <label for="fathom_key">Fathom API Key (Optional):</label>
            <input type="text" id="fathom_key" name="fathom_key" placeholder="Your Fathom API key...">
            <div class="help-text">
                Find your API key at: <a href="https://fathom.video/settings/integrations" target="_blank">fathom.video/settings/integrations</a>
            </div>

            <div class="buttons">
                <button type="submit" class="button">💾 Save & Continue</button>
                <button type="submit" class="button button-secondary" formaction="/setup/skip">⏭️ Skip This Step</button>
            </div>
        </form>

        <div class="skip-note">
            💡 You can always add your Fathom key later in settings
        </div>
    </div>
</body>
</html>
"""

SUCCESS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Final Step - Install in Claude Desktop</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .card {
            background: white;
            padding: 50px;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 900px;
            width: 100%;
        }
        .progress {
            text-align: center;
            color: #888;
            font-size: 14px;
            margin-bottom: 10px;
        }
        h1 {
            color: #28a745;
            margin-bottom: 10px;
            text-align: center;
            font-size: 38px;
        }
        .subtitle {
            text-align: center;
            color: #666;
            font-size: 18px;
            margin-bottom: 30px;
        }
        .info {
            background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
            padding: 25px;
            border-radius: 12px;
            margin: 30px 0;
            border-left: 5px solid #28a745;
            box-shadow: 0 2px 10px rgba(40, 167, 69, 0.1);
        }
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }
        .info-item {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .info-item strong {
            color: #2e7d32;
            font-size: 15px;
        }
        .final-step {
            background: linear-gradient(135deg, #fff9e6 0%, #fff3cd 100%);
            padding: 30px;
            border-radius: 12px;
            border: 3px solid #ffc107;
            margin: 30px 0;
        }
        .final-step h2 {
            color: #333;
            font-size: 28px;
            margin-bottom: 15px;
            text-align: center;
        }
        .final-step-subtitle {
            text-align: center;
            color: #666;
            font-size: 16px;
            margin-bottom: 25px;
        }
        .os-tabs {
            display: flex;
            gap: 10px;
            justify-content: center;
            margin-bottom: 25px;
        }
        .os-tab {
            background: white;
            border: 2px solid #ddd;
            padding: 12px 30px;
            border-radius: 10px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: all 0.2s;
        }
        .os-tab:hover {
            border-color: #667eea;
            transform: translateY(-2px);
        }
        .os-tab.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-color: #667eea;
        }
        .os-content {
            display: none;
        }
        .os-content.active {
            display: block;
        }
        .command-box {
            background: #1e1e1e;
            padding: 25px;
            border-radius: 12px;
            margin: 20px 0;
            position: relative;
        }
        .command-box pre {
            color: #f8f8f2;
            font-size: 14px;
            line-height: 1.6;
            overflow-x: auto;
            margin: 0;
            font-family: 'Monaco', 'Consolas', monospace;
        }
        .copy-btn {
            position: absolute;
            top: 15px;
            right: 15px;
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            font-weight: bold;
            box-shadow: 0 4px 15px rgba(40, 167, 69, 0.3);
            transition: all 0.2s;
        }
        .copy-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(40, 167, 69, 0.5);
        }
        .copy-btn.copied {
            background: linear-gradient(135deg, #007bff 0%, #0056b3 100%);
        }
        .instructions {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            margin-top: 20px;
        }
        .instructions h3 {
            color: #333;
            font-size: 18px;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .instructions ol {
            padding-left: 25px;
            color: #555;
        }
        .instructions li {
            margin: 12px 0;
            line-height: 1.6;
            font-size: 15px;
        }
        .instructions li strong {
            color: #333;
        }
        .what-next {
            background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
            padding: 25px;
            border-radius: 12px;
            margin: 30px 0;
            border-left: 5px solid #2196f3;
        }
        .what-next h3 {
            color: #1976d2;
            font-size: 20px;
            margin-bottom: 15px;
        }
        .what-next ul {
            list-style: none;
            padding: 0;
        }
        .what-next li {
            padding: 8px 0;
            padding-left: 30px;
            position: relative;
            color: #555;
            line-height: 1.6;
        }
        .what-next li:before {
            content: "✨";
            position: absolute;
            left: 0;
            font-size: 18px;
        }
        .footer {
            text-align: center;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 2px solid #eee;
        }
        .footer a {
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
        }
        .footer a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="progress">Step 3 of 3 - Almost Done!</div>
        <h1>🎉 Almost There!</h1>
        <p class="subtitle">Your accounts are connected. One final step to activate Claude Desktop.</p>

        <div class="info">
            <div class="info-grid">
                <div class="info-item">
                    <span style="font-size: 24px;">👤</span>
                    <div>
                        <strong>Email:</strong><br>
                        <span style="color: #666;">{{ email }}</span>
                    </div>
                </div>
                <div class="info-item">
                    <span style="font-size: 24px;">✅</span>
                    <div>
                        <strong>Gmail & Calendar:</strong><br>
                        <span style="color: #28a745;">Connected</span>
                    </div>
                </div>
                <div class="info-item">
                    <span style="font-size: 24px;">{{ '✅' if has_fathom else '⚪' }}</span>
                    <div>
                        <strong>Fathom:</strong><br>
                        <span style="color: {{ '#28a745' if has_fathom else '#999' }};">{{ 'Connected' if has_fathom else 'Skipped' }}</span>
                    </div>
                </div>
            </div>
        </div>

        <div class="final-step">
            <h2>🚀 Final Step: Run This Command</h2>
            <p class="final-step-subtitle">Copy & paste one line into your terminal. That's it!</p>

            <div class="os-tabs">
                <button class="os-tab active" onclick="showOS('mac')">🍎 Mac / Linux</button>
                <button class="os-tab" onclick="showOS('windows')">🪟 Windows</button>
            </div>

            <div id="mac-content" class="os-content active">
                <div class="command-box">
                    <button class="copy-btn" onclick="copyCommand('mac-command')">📋 Copy</button>
                    <pre id="mac-command">curl -fsSL {{ server_url }}/install.sh | bash -s {{ token }}</pre>
                </div>
                <div class="instructions">
                    <h3>📝 What to do:</h3>
                    <ol>
                        <li><strong>Click the "Copy" button</strong> above</li>
                        <li><strong>Open Terminal</strong> (search for "Terminal" in Spotlight)</li>
                        <li><strong>Paste the command</strong> and press Enter</li>
                        <li><strong>Wait 10 seconds</strong> for it to finish</li>
                        <li><strong>Restart Claude Desktop</strong></li>
                    </ol>
                </div>
            </div>

            <div id="windows-content" class="os-content">
                <div class="command-box">
                    <button class="copy-btn" onclick="copyCommand('windows-command')">📋 Copy</button>
                    <pre id="windows-command">$env:MCP_SESSION_TOKEN = "{{ token }}"; Invoke-WebRequest -Uri "{{ server_url }}/install.ps1" -UseBasicParsing | Invoke-Expression</pre>
                </div>
                <div class="instructions">
                    <h3>📝 What to do:</h3>
                    <ol>
                        <li><strong>Click the "Copy" button</strong> above</li>
                        <li><strong>Open PowerShell</strong> (search for "PowerShell" in Start Menu)</li>
                        <li><strong>Paste the command</strong> and press Enter</li>
                        <li><strong>Wait 10 seconds</strong> for it to finish</li>
                        <li><strong>Restart Claude Desktop</strong></li>
                    </ol>
                </div>
            </div>
        </div>

        <div class="what-next">
            <h3>💡 What You Can Do Next:</h3>
            <ul>
                <li>"Show me emails I haven't replied to in the last 3 days"</li>
                <li>"What's on my calendar tomorrow?"</li>
                <li>"Search my emails for messages about the project proposal"</li>
                <li>"Create a calendar event for tomorrow at 2pm"</li>
                <li>"Send an email to john@example.com thanking him for the meeting"</li>
            </ul>
        </div>

        <div class="footer">
            <a href="{{ server_url }}/settings?token={{ token }}">⚙️ Update Settings</a>
            <span style="color: #ccc; margin: 0 15px;">|</span>
            <span style="color: #888;">Need help? Contact your admin</span>
        </div>
    </div>

    <script>
        function showOS(os) {
            // Update tabs
            document.querySelectorAll('.os-tab').forEach(tab => {
                tab.classList.remove('active');
            });
            event.target.classList.add('active');

            // Update content
            document.querySelectorAll('.os-content').forEach(content => {
                content.classList.remove('active');
            });
            document.getElementById(os + '-content').classList.add('active');
        }

        function copyCommand(elementId) {
            const command = document.getElementById(elementId).textContent;
            navigator.clipboard.writeText(command).then(() => {
                const btn = event.target;
                const originalText = btn.textContent;
                btn.textContent = '✓ Copied!';
                btn.classList.add('copied');
                setTimeout(() => {
                    btn.textContent = originalText;
                    btn.classList.remove('copied');
                }, 3000);
            });
        }
    </script>

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
