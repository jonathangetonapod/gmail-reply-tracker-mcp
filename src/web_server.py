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
        .info-button {
            display: inline-block;
            background: #4caf50;
            color: white;
            padding: 10px 20px;
            border-radius: 6px;
            text-decoration: none;
            font-size: 14px;
            font-weight: 500;
            margin-bottom: 20px;
            cursor: pointer;
            border: none;
        }
        .info-button:hover {
            background: #45a049;
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
        .requirement {
            background: #fff8e1;
            border-left: 4px solid #ff9800;
            padding: 20px;
            margin: 20px 0;
            border-radius: 6px;
        }
        .requirement-title {
            font-weight: 600;
            color: #e65100;
            margin-bottom: 10px;
            font-size: 16px;
        }
        .requirement-text {
            color: #666;
            font-size: 14px;
            line-height: 1.5;
            margin-bottom: 12px;
        }
        .download-link {
            display: inline-block;
            background: #ff9800;
            color: white;
            padding: 8px 16px;
            border-radius: 4px;
            text-decoration: none;
            font-size: 14px;
            font-weight: 500;
        }
        .download-link:hover {
            background: #f57c00;
        }

        /* Modal styles */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            overflow: auto;
            background-color: rgba(0,0,0,0.5);
            animation: fadeIn 0.3s;
        }
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        .modal-content {
            background-color: #fefefe;
            margin: 5% auto;
            padding: 0;
            border-radius: 12px;
            width: 90%;
            max-width: 800px;
            max-height: 85vh;
            overflow-y: auto;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            animation: slideIn 0.3s;
        }
        @keyframes slideIn {
            from {
                transform: translateY(-50px);
                opacity: 0;
            }
            to {
                transform: translateY(0);
                opacity: 1;
            }
        }
        .modal-header {
            background: linear-gradient(135deg, #2196f3 0%, #1976d2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px 12px 0 0;
        }
        .modal-header h2 {
            margin: 0 0 10px 0;
            font-size: 26px;
        }
        .modal-header p {
            margin: 0;
            opacity: 0.9;
            font-size: 15px;
        }
        .modal-body {
            padding: 30px;
        }
        .close {
            color: white;
            float: right;
            font-size: 32px;
            font-weight: bold;
            cursor: pointer;
            line-height: 20px;
            opacity: 0.8;
        }
        .close:hover {
            opacity: 1;
        }
        .section {
            margin-bottom: 30px;
        }
        .section h3 {
            color: #2196f3;
            margin-bottom: 15px;
            font-size: 20px;
            display: flex;
            align-items: center;
        }
        .section h3:before {
            content: "→";
            margin-right: 10px;
            font-weight: bold;
        }
        .section p {
            color: #555;
            line-height: 1.6;
            margin-bottom: 12px;
        }
        .section ul {
            margin-left: 20px;
            color: #555;
            line-height: 1.8;
        }
        .section li {
            margin-bottom: 8px;
        }
        .highlight-box {
            background: #e3f2fd;
            border-left: 4px solid #2196f3;
            padding: 15px;
            border-radius: 6px;
            margin: 15px 0;
        }
        .security-box {
            background: #e8f5e9;
            border-left: 4px solid #4caf50;
            padding: 15px;
            border-radius: 6px;
            margin: 15px 0;
        }
        .example-prompt {
            background: #f5f5f5;
            padding: 12px 15px;
            border-radius: 6px;
            margin: 8px 0;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 13px;
            color: #333;
        }
        .tool-count {
            background: #2196f3;
            color: white;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 13px;
            font-weight: 600;
            display: inline-block;
            margin-left: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Gmail & Calendar Setup</h1>
        <p class="subtitle">Connect Claude to your Gmail and Google Calendar</p>

        <div style="display: flex; gap: 10px; justify-content: center; margin-bottom: 30px; flex-wrap: wrap;">
            <button class="info-button" onclick="openModal()">
                ℹ️ How This Works & Example Prompts
            </button>
            <button class="info-button" onclick="openPrivacyModal()" style="background: linear-gradient(135deg, #4caf50 0%, #2e7d32 100%);">
                🔒 Privacy & Who Can See What
            </button>
            <button class="info-button" onclick="openTroubleshootingModal()" style="background: linear-gradient(135deg, #f44336 0%, #e91e63 100%);">
                🔧 Troubleshooting Guide
            </button>
        </div>

        <div class="requirement">
            <div class="requirement-title">⚠️ Claude Desktop Required</div>
            <div class="requirement-text">
                This MCP server works with <strong>Claude Desktop</strong>, not the web version at claude.ai.
                If you don't have it yet, download it first:
            </div>
            <a href="https://claude.ai/download" target="_blank" class="download-link">Download Claude Desktop</a>
        </div>

        <div class="step">
            <div class="step-title">Step 1: Enter Your Info</div>
            <div class="step-desc">Provide your email and optional Fathom API key</div>
        </div>

        <div class="step">
            <div class="step-title">Step 2: Run Install Command</div>
            <div class="step-desc">Copy and paste one command in your terminal - it handles everything</div>
        </div>

        <div class="step">
            <div class="step-title">Step 3: Authorize Google</div>
            <div class="step-desc">Browser opens for Gmail/Calendar authorization (happens during install)</div>
        </div>

        <div class="step">
            <div class="step-title">Step 4: Restart Claude</div>
            <div class="step-desc">Restart Claude Desktop and start using your new tools!</div>
        </div>

        <a href="{{ server_url }}/setup/start" class="start-button">Start Setup</a>
        <p class="note">Takes 2 minutes</p>
    </div>

    <!-- Information Modal -->
    <div id="infoModal" class="modal" onclick="closeModalOnClickOutside(event)">
        <div class="modal-content">
            <div class="modal-header">
                <span class="close" onclick="closeModal()">&times;</span>
                <h2>📬 How This MCP Server Works</h2>
                <p>34 powerful tools to supercharge your productivity with Claude</p>
            </div>
            <div class="modal-body">

                <div class="section">
                    <h3>🚀 What You Get</h3>
                    <p><strong>34 production-ready tools</strong> that connect Claude to your entire productivity stack:</p>
                    <div class="highlight-box">
                        <strong>📧 Gmail</strong><span class="tool-count">13 tools</span>
                        <p style="margin-top: 8px; font-size: 14px;">Smart email management, unreplied email tracking, send/reply, search, drafts</p>

                        <strong>📅 Google Calendar</strong><span class="tool-count">7 tools</span>
                        <p style="margin-top: 8px; font-size: 14px;">Natural language scheduling, auto-timezone detection, event management, invitations</p>

                        <strong>🎙️ Fathom AI</strong><span class="tool-count">6 tools</span>
                        <p style="margin-top: 8px; font-size: 14px;">Meeting transcripts, AI summaries, action items, search recordings</p>

                        <strong>🎯 Lead Management</strong><span class="tool-count">8 tools</span>
                        <p style="margin-top: 8px; font-size: 14px;">Track 88 clients (Instantly.ai + Bison), campaign analytics, interested leads</p>
                    </div>
                </div>

                <div class="section">
                    <h3>🔐 Should Your Team Worry? (Security & Privacy)</h3>
                    <div class="security-box">
                        <p><strong>✅ Completely Safe:</strong></p>
                        <ul>
                            <li><strong>Runs locally</strong> - MCP server runs on your machine, not on our servers</li>
                            <li><strong>No data stored</strong> - We don't store, cache, or see your emails/calendar</li>
                            <li><strong>Google OAuth</strong> - You authorize directly with Google (revoke anytime)</li>
                            <li><strong>Open source</strong> - Full code visibility on GitHub</li>
                            <li><strong>Encrypted tokens</strong> - OAuth tokens stored securely with 600 permissions</li>
                        </ul>
                        <p style="margin-top: 12px;"><strong>What We Access:</strong></p>
                        <ul>
                            <li>Gmail: Read, send, and modify (gmail.modify scope)</li>
                            <li>Calendar: Full access to create/edit events</li>
                            <li>Fathom: Read-only via your API key (optional)</li>
                        </ul>
                        <p style="margin-top: 12px; font-size: 13px; color: #666;">
                            <strong>Revoke access anytime:</strong> Visit <a href="https://myaccount.google.com/permissions" target="_blank" style="color: #2196f3;">Google Account Permissions</a>
                        </p>
                    </div>
                </div>

                <div class="section">
                    <h3>🔄 How It All Comes Together</h3>
                    <p><strong>The Architecture:</strong></p>
                    <ol style="line-height: 1.8; margin-left: 20px;">
                        <li><strong>You authorize</strong> → Google gives us an OAuth token</li>
                        <li><strong>Token stored locally</strong> → Encrypted on your machine</li>
                        <li><strong>Claude asks questions</strong> → "Show me unreplied emails"</li>
                        <li><strong>MCP server fetches</strong> → Calls Gmail/Calendar APIs with your token</li>
                        <li><strong>Claude responds</strong> → Shows you the results in natural language</li>
                    </ol>
                    <p style="margin-top: 12px;">All processing happens <strong>locally</strong> on your machine. No third-party servers involved.</p>
                </div>

                <div class="section">
                    <h3>💬 Example Prompts You Can Use</h3>

                    <p><strong>📧 Email Management:</strong></p>
                    <div class="example-prompt">"Show me emails I haven't replied to from the last 3 days"</div>
                    <div class="example-prompt">"Search for emails about the Q4 budget proposal"</div>
                    <div class="example-prompt">"Draft a reply thanking them for the update"</div>
                    <div class="example-prompt">"Send an email to team@company.com about tomorrow's meeting"</div>

                    <p style="margin-top: 15px;"><strong>📅 Calendar & Scheduling:</strong></p>
                    <div class="example-prompt">"What's on my calendar this week?"</div>
                    <div class="example-prompt">"Schedule a meeting with sarah@company.com tomorrow at 2pm"</div>
                    <div class="example-prompt">"Create a team standup every Monday at 9am and invite everyone"</div>
                    <div class="example-prompt">"Cancel my 3pm meeting today"</div>

                    <p style="margin-top: 15px;"><strong>🎙️ Meeting Intelligence:</strong></p>
                    <div class="example-prompt">"Get the transcript from yesterday's client call"</div>
                    <div class="example-prompt">"What action items came out of the engineering sync?"</div>
                    <div class="example-prompt">"Summarize the Project Phoenix kickoff meeting"</div>
                    <div class="example-prompt">"Find all meetings where we discussed the new feature"</div>

                    <p style="margin-top: 15px;"><strong>🎯 Lead Management:</strong></p>
                    <div class="example-prompt">"Show me all clients from Instantly and Bison"</div>
                    <div class="example-prompt">"Get interested leads from ABC Corp in the last 7 days"</div>
                    <div class="example-prompt">"Which clients are underperforming this week?"</div>
                    <div class="example-prompt">"Show me the top 5 clients by reply rate"</div>
                    <div class="example-prompt">"Generate a weekly summary of all lead activity"</div>

                    <p style="margin-top: 15px;"><strong>🔀 Cross-Platform:</strong></p>
                    <div class="example-prompt">"What's the status of the marketing campaign? Check emails, calendar, and meetings"</div>
                    <div class="example-prompt">"Find all action items from this week across meetings and emails"</div>
                    <div class="example-prompt">"Who have I been meeting with most this month?"</div>
                </div>

                <div class="section">
                    <h3>🎯 Why This Is Powerful</h3>
                    <ul>
                        <li><strong>Natural language</strong> - No more clicking through interfaces</li>
                        <li><strong>Context-aware</strong> - Claude understands your full work context</li>
                        <li><strong>Time-saving</strong> - Automate repetitive email/calendar tasks</li>
                        <li><strong>Smart filtering</strong> - Automatically filters automated emails, newsletters</li>
                        <li><strong>Multi-app queries</strong> - Ask about emails, calendar, meetings in one go</li>
                        <li><strong>Action items tracking</strong> - Never miss a follow-up</li>
                    </ul>
                </div>

                <div class="section">
                    <h3>📈 Production Features</h3>
                    <div class="highlight-box">
                        <strong>For Your Team:</strong>
                        <ul style="margin-top: 8px;">
                            <li>41 unit tests - Full test coverage</li>
                            <li>Type hints - Complete type safety</li>
                            <li>Rate limiting - API quota management</li>
                            <li>Error handling - Friendly error messages</li>
                            <li>Auto timezone detection - No more UTC confusion</li>
                            <li>One-command setup - 5-10 minute installation</li>
                        </ul>
                    </div>
                </div>

            </div>
        </div>
    </div>

    <!-- Troubleshooting Modal -->
    <div id="troubleshootingModal" class="modal" onclick="closeTroubleshootingModalOnClickOutside(event)">
        <div class="modal-content" style="max-width: 800px;">
            <div class="modal-header" style="background: linear-gradient(135deg, #f44336 0%, #e91e63 100%);">
                <span class="close" onclick="closeTroubleshootingModal()">&times;</span>
                <h2>🔧 Troubleshooting Guide</h2>
                <p style="margin: 8px 0 0 0; opacity: 0.95;">Quick fixes for common issues</p>
            </div>
            <div class="modal-body" style="max-height: 70vh; overflow-y: auto; padding: 25px;">

                <!-- Issue 1: Xcode Command Line Tools -->
                <div style="background: #fff5f5; border-left: 4px solid #f44336; padding: 18px; margin-bottom: 20px; border-radius: 6px;">
                    <h3 style="color: #f44336; margin: 0 0 10px 0; font-size: 18px;">❌ "xcode-select: no developer tools installed"</h3>
                    <p style="margin: 8px 0; color: #555;"><strong>What's happening:</strong> macOS needs developer tools for Git</p>
                    <div style="background: white; padding: 15px; border-radius: 6px; margin-top: 12px;">
                        <strong style="color: #2e7d32;">✅ Fix:</strong>
                        <ol style="margin: 10px 0 0 0; padding-left: 20px; line-height: 1.6;">
                            <li>Click <strong>Install</strong> when the dialog appears</li>
                            <li>Wait 5-10 minutes</li>
                            <li>Script continues automatically</li>
                        </ol>
                    </div>
                </div>

                <!-- Issue 2: OAuth Timeout -->
                <div style="background: #fff8e1; border-left: 4px solid #ff9800; padding: 18px; margin-bottom: 20px; border-radius: 6px;">
                    <h3 style="color: #ff9800; margin: 0 0 10px 0; font-size: 18px;">⏱️ OAuth "Connection Refused"</h3>
                    <p style="margin: 8px 0; color: #555;"><strong>What's happening:</strong> Browser can't connect to OAuth server</p>
                    <div style="background: white; padding: 15px; border-radius: 6px; margin-top: 12px;">
                        <strong style="color: #2e7d32;">✅ Fix:</strong>
                        <ol style="margin: 10px 0 0 0; padding-left: 20px; line-height: 1.6;">
                            <li>Close the error browser tab</li>
                            <li>Rerun the install command</li>
                            <li>OAuth browser will open automatically</li>
                        </ol>
                        <p style="margin: 12px 0 0 0; font-size: 14px; color: #666;">💡 Still failing? Contact your admin about OAuth config</p>
                    </div>
                </div>

                <!-- Issue 3: Claude Not Connecting -->
                <div style="background: #f3e5f5; border-left: 4px solid #9c27b0; padding: 18px; margin-bottom: 20px; border-radius: 6px;">
                    <h3 style="color: #9c27b0; margin: 0 0 10px 0; font-size: 18px;">🔌 Claude Desktop Not Connecting</h3>
                    <p style="margin: 8px 0; color: #555;"><strong>What's happening:</strong> MCP server not appearing in Claude</p>
                    <div style="background: white; padding: 15px; border-radius: 6px; margin-top: 12px;">
                        <strong style="color: #2e7d32;">✅ Fix 1 - Restart Claude:</strong>
                        <ol style="margin: 10px 0 0 0; padding-left: 20px; line-height: 1.6;">
                            <li>Completely quit Claude (⌘Q)</li>
                            <li>Reopen Claude Desktop</li>
                            <li>Wait 10 seconds for MCP to connect</li>
                        </ol>

                        <hr style="margin: 15px 0; border: none; border-top: 1px solid #e0e0e0;">

                        <strong style="color: #2e7d32;">✅ Fix 2 - Check Config File:</strong>
                        <p style="margin: 10px 0 4px 0; font-size: 14px;">Open config in TextEdit:</p>
                        <pre style="background: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0 0 10px 0; white-space: pre-wrap; word-wrap: break-word;">open -a TextEdit ~/Library/Application\ Support/Claude/claude_desktop_config.json</pre>

                        <p style="margin: 10px 0 4px 0; font-size: 14px;">Or view in terminal:</p>
                        <pre style="background: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0 0 10px 0; white-space: pre-wrap; word-wrap: break-word;">cat ~/Library/Application\ Support/Claude/claude_desktop_config.json</pre>

                        <p style="margin: 10px 0 0 0; font-size: 14px; color: #666;">Make sure you see <code style="background: #f5f5f5; padding: 2px 6px; border-radius: 3px;">"gmail-calendar-fathom"</code> in the config</p>

                        <hr style="margin: 15px 0; border: none; border-top: 1px solid #e0e0e0;">

                        <strong style="color: #2e7d32;">✅ Fix 3 - View Logs:</strong>
                        <p style="margin: 10px 0 4px 0; font-size: 14px;">Watch logs in real-time:</p>
                        <pre style="background: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0 0 10px 0; white-space: pre-wrap; word-wrap: break-word;">tail -f ~/Library/Logs/Claude/mcp*.log</pre>

                        <p style="margin: 10px 0 4px 0; font-size: 14px;">Open logs folder in Finder:</p>
                        <pre style="background: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">open ~/Library/Logs/Claude/</pre>
                    </div>
                </div>

                <!-- Issue 4: No Tools Showing -->
                <div style="background: #e8eaf6; border-left: 4px solid #3f51b5; padding: 18px; margin-bottom: 20px; border-radius: 6px;">
                    <h3 style="color: #3f51b5; margin: 0 0 10px 0; font-size: 18px;">🔍 No Tools Showing</h3>
                    <p style="margin: 8px 0; color: #555;"><strong>What's happening:</strong> Connected but no tools available</p>
                    <div style="background: white; padding: 15px; border-radius: 6px; margin-top: 12px;">
                        <strong style="color: #2e7d32;">✅ Fix - Delete token and re-authenticate:</strong>
                        <pre style="background: #f5f5f5; padding: 12px; border-radius: 4px; overflow-x: auto; font-size: 13px; margin: 10px 0; white-space: pre-wrap; word-wrap: break-word;">rm ~/gmail-calendar-mcp/credentials/token.json && cd ~/gmail-calendar-mcp && ./venv/bin/python auto_oauth.py</pre>
                        <p style="margin: 10px 0 0 0; font-size: 14px;">Then restart Claude Desktop (⌘Q and reopen)</p>

                        <hr style="margin: 15px 0; border: none; border-top: 1px solid #e0e0e0;">

                        <p style="margin: 10px 0 4px 0; font-size: 14px;"><strong>Check if token exists:</strong></p>
                        <pre style="background: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">ls -la ~/gmail-calendar-mcp/credentials/token.json</pre>

                        <p style="margin: 12px 0 4px 0; font-size: 14px;"><strong>View token contents (check scopes):</strong></p>
                        <pre style="background: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">cat ~/gmail-calendar-mcp/credentials/token.json | python3 -m json.tool</pre>
                    </div>
                </div>

                <!-- Issue 5: Email Threading -->
                <div style="background: #e0f7fa; border-left: 4px solid #00bcd4; padding: 18px; margin-bottom: 20px; border-radius: 6px;">
                    <h3 style="color: #00bcd4; margin: 0 0 10px 0; font-size: 18px;">📧 Replies Creating New Threads</h3>
                    <p style="margin: 8px 0; color: #555;"><strong>What's happening:</strong> Emails not staying in same conversation</p>
                    <div style="background: white; padding: 15px; border-radius: 6px; margin-top: 12px;">
                        <strong style="color: #2e7d32;">✅ Fix - Use reply_to_email tool:</strong>
                        <ol style="margin: 10px 0 0 0; padding-left: 20px; line-height: 1.6;">
                            <li>Search for the email first</li>
                            <li>Get the <code>thread_id</code> from results</li>
                            <li>Reply using: "Reply to thread [ID] with: [message]"</li>
                        </ol>
                        <p style="margin: 12px 0 0 0; font-size: 14px; color: #666;">✨ System now auto-detects threads and suggests correct tool!</p>
                    </div>
                </div>

                <!-- Issue 6: Permissions -->
                <div style="background: #e8f5e9; border-left: 4px solid #4caf50; padding: 18px; margin-bottom: 20px; border-radius: 6px;">
                    <h3 style="color: #4caf50; margin: 0 0 10px 0; font-size: 18px;">🔐 "App Not Verified" Warning</h3>
                    <p style="margin: 8px 0; color: #555;"><strong>What's happening:</strong> Google security warning during login</p>
                    <div style="background: white; padding: 15px; border-radius: 6px; margin-top: 12px;">
                        <strong style="color: #2e7d32;">✅ Fix - Click through the warning:</strong>
                        <ol style="margin: 10px 0 0 0; padding-left: 20px; line-height: 1.6;">
                            <li>Click <strong>"Advanced"</strong></li>
                            <li>Click <strong>"Go to [App Name] (unsafe)"</strong></li>
                            <li>Review permissions</li>
                            <li>Click <strong>"Allow"</strong></li>
                        </ol>
                        <p style="margin: 12px 0 0 0; font-size: 14px; color: #666;">✅ This is safe - it's your team's internal app!</p>
                        <hr style="margin: 15px 0; border: none; border-top: 1px solid #e0e0e0;">
                        <p style="margin: 10px 0 0 0; font-size: 14px; color: #d32f2f;"><strong>Getting "Access Blocked"?</strong> Contact your admin to add you as a test user</p>
                    </div>
                </div>

                <!-- Issue 7: Bison/Instantly Tools Failing -->
                <div style="background: #fce4ec; border-left: 4px solid #e91e63; padding: 18px; margin-bottom: 20px; border-radius: 6px;">
                    <h3 style="color: #e91e63; margin: 0 0 10px 0; font-size: 18px;">🔧 Bison/Instantly Tools Failing</h3>
                    <p style="margin: 8px 0; color: #555;"><strong>What's happening:</strong> Claude tries to use Bison/Instantly tools but they fail repeatedly</p>
                    <div style="background: white; padding: 15px; border-radius: 6px; margin-top: 12px;">
                        <strong style="color: #e91e63;">❌ Why it's failing:</strong>
                        <p style="margin: 10px 0 0 0; font-size: 14px;">Bison/Instantly tools need access to a specific Google Sheet that tracks lead data. You likely don't have access to it.</p>

                        <hr style="margin: 15px 0; border: none; border-top: 1px solid #e0e0e0;">

                        <strong style="color: #2e7d32;">✅ Solution - Tell Claude to skip these tools:</strong>
                        <p style="margin: 10px 0 0 0; font-size: 14px;">Simply tell Claude in your conversation:</p>
                        <pre style="background: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 13px; margin: 10px 0; white-space: pre-wrap; word-wrap: break-word;">"Don't use Bison or Instantly tools - I don't have access to them"</pre>

                        <p style="margin: 10px 0 0 0; font-size: 14px;">Then ask your question again. Claude will use other available tools instead!</p>

                        <hr style="margin: 15px 0; border: none; border-top: 1px solid #e0e0e0;">

                        <p style="margin: 10px 0 0 0; font-size: 14px; color: #666;"><strong>💡 Good news:</strong> You still have 31 other tools working (Gmail, Calendar, Fathom) that don't need any special access!</p>

                        <p style="margin: 10px 0 0 0; font-size: 13px; color: #999;"><strong>For admins:</strong> To enable these tools, grant the user access to the lead tracking Google Sheet</p>
                    </div>
                </div>

                <!-- Claude Desktop Settings -->
                <div style="background: #e1f5fe; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                    <h3 style="margin: 0 0 15px 0; font-size: 16px;">⚙️ Finding Claude Desktop Settings</h3>

                    <p style="margin: 0 0 10px 0; font-weight: 600; font-size: 14px;">Option 1 - In Claude Desktop app:</p>
                    <ol style="margin: 0 0 15px 0; padding-left: 20px; line-height: 1.8;">
                        <li>Open Claude Desktop</li>
                        <li>Click <strong>Claude</strong> in menu bar → <strong>Settings</strong> (or press ⌘,)</li>
                        <li>Go to <strong>Developer</strong> tab</li>
                        <li>Click <strong>Edit Config</strong> button</li>
                    </ol>

                    <p style="margin: 15px 0 10px 0; font-weight: 600; font-size: 14px;">Option 2 - Direct file access:</p>
                    <p style="margin: 0 0 5px 0; font-size: 14px;">Click this command to open config in TextEdit:</p>
                    <pre style="background: white; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">open -a TextEdit ~/Library/Application\ Support/Claude/claude_desktop_config.json</pre>
                </div>

                <!-- Quick Commands -->
                <div style="background: #f5f5f5; padding: 20px; border-radius: 8px;">
                    <h3 style="margin: 0 0 15px 0; font-size: 16px;">💡 Useful Terminal Commands</h3>

                    <p style="margin: 12px 0 4px 0; font-weight: 600; font-size: 14px;">📝 Open Claude config in editor:</p>
                    <pre style="background: white; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">open -a TextEdit ~/Library/Application\ Support/Claude/claude_desktop_config.json</pre>

                    <p style="margin: 16px 0 4px 0; font-weight: 600; font-size: 14px;">👁️ View Claude config:</p>
                    <pre style="background: white; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">cat ~/Library/Application\ Support/Claude/claude_desktop_config.json</pre>

                    <p style="margin: 16px 0 4px 0; font-weight: 600; font-size: 14px;">📂 Open Claude config folder in Finder:</p>
                    <pre style="background: white; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">open ~/Library/Application\ Support/Claude/</pre>

                    <p style="margin: 16px 0 4px 0; font-weight: 600; font-size: 14px;">📋 Watch MCP logs live:</p>
                    <pre style="background: white; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">tail -f ~/Library/Logs/Claude/mcp*.log</pre>

                    <p style="margin: 16px 0 4px 0; font-weight: 600; font-size: 14px;">📁 Open logs folder in Finder:</p>
                    <pre style="background: white; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">open ~/Library/Logs/Claude/</pre>

                    <p style="margin: 16px 0 4px 0; font-weight: 600; font-size: 14px;">✅ Check if MCP is configured:</p>
                    <pre style="background: white; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">cat ~/Library/Application\ Support/Claude/claude_desktop_config.json | grep gmail-calendar-fathom</pre>

                    <p style="margin: 16px 0 4px 0; font-weight: 600; font-size: 14px;">🔐 Test OAuth manually:</p>
                    <pre style="background: white; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">cd ~/gmail-calendar-mcp && ./venv/bin/python auto_oauth.py</pre>

                    <p style="margin: 16px 0 4px 0; font-weight: 600; font-size: 14px;">📂 Open MCP install folder in Finder:</p>
                    <pre style="background: white; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">open ~/gmail-calendar-mcp</pre>

                    <p style="margin: 16px 0 4px 0; font-weight: 600; font-size: 14px;">🧹 Clean reinstall (deletes everything):</p>
                    <pre style="background: white; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">rm -rf ~/gmail-calendar-mcp && curl -fsSL https://raw.githubusercontent.com/jonathangetonapod/gmail-reply-tracker-mcp/main/local_install.sh | bash -s "your@email.com"</pre>

                    <p style="margin: 16px 0 4px 0; font-weight: 600; font-size: 14px;">🚀 Force quit Claude Desktop:</p>
                    <pre style="background: white; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">pkill -9 Claude && open -a "Claude"</pre>
                </div>

                <!-- Still Need Help -->
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 25px; border-radius: 8px; margin-top: 20px; text-align: center;">
                    <h3 style="margin: 0 0 10px 0; color: white;">💬 Still Need Help?</h3>
                    <p style="margin: 0 0 15px 0; opacity: 0.95;">Contact your admin or report the issue</p>
                    <a href="https://github.com/jonathangetonapod/gmail-reply-tracker-mcp/issues" target="_blank"
                       style="display: inline-block; background: white; color: #667eea; padding: 12px 30px;
                              border-radius: 6px; text-decoration: none; font-weight: 600; transition: transform 0.2s;">
                        📝 Report on GitHub
                    </a>
                </div>

            </div>
        </div>
    </div>

    <!-- Privacy Modal -->
    <div id="privacyModal" class="modal" onclick="closePrivacyModalOnClickOutside(event)">
        <div class="modal-content" style="max-width: 900px;">
            <div class="modal-header" style="background: linear-gradient(135deg, #4caf50 0%, #2e7d32 100%);">
                <span class="close" onclick="closePrivacyModal()">&times;</span>
                <h2>🔒 Privacy & Who Can See What</h2>
                <p style="margin: 8px 0 0 0; opacity: 0.95;">Crystal clear breakdown of data access and security</p>
            </div>
            <div class="modal-body" style="max-height: 75vh; overflow-y: auto; padding: 30px;">

                <!-- Key Message -->
                <div style="background: linear-gradient(135deg, #4caf50 0%, #66bb6a 100%); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center;">
                    <h2 style="margin: 0 0 15px 0; font-size: 28px; color: white;">✅ Your Personal Data is 100% Private</h2>
                    <p style="margin: 0; font-size: 18px; opacity: 0.95; line-height: 1.6;">
                        <strong>Jonathan (the admin) CANNOT access your personal Gmail, Calendar, or Fathom data.</strong>
                    </p>
                    <p style="margin: 15px 0 0 0; font-size: 16px; opacity: 0.9;">
                        Here's exactly why, with technical proof...
                    </p>
                </div>

                <!-- Section 1: What Jonathan CANNOT See -->
                <div style="background: #e8f5e9; border: 2px solid #4caf50; padding: 25px; border-radius: 12px; margin-bottom: 25px;">
                    <h3 style="color: #2e7d32; margin: 0 0 20px 0; font-size: 22px; display: flex; align-items: center;">
                        <span style="font-size: 32px; margin-right: 12px;">❌</span>
                        What Jonathan CANNOT Access
                    </h3>

                    <div style="background: white; padding: 20px; border-radius: 8px; margin-bottom: 15px;">
                        <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 16px;">🚫 Your Personal Gmail</h4>
                        <p style="margin: 0; color: #555; line-height: 1.6;">Cannot read, search, or access any of your emails. Your inbox is completely private.</p>
                    </div>

                    <div style="background: white; padding: 20px; border-radius: 8px; margin-bottom: 15px;">
                        <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 16px;">🚫 Your Personal Calendar</h4>
                        <p style="margin: 0; color: #555; line-height: 1.6;">Cannot see your meetings, appointments, or schedule. Your calendar is yours alone.</p>
                    </div>

                    <div style="background: white; padding: 20px; border-radius: 8px; margin-bottom: 15px;">
                        <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 16px;">🚫 Your Fathom Recordings</h4>
                        <p style="margin: 0; color: #555; line-height: 1.6;">Cannot access your meeting recordings, transcripts, or notes. Completely private.</p>
                    </div>

                    <div style="background: white; padding: 20px; border-radius: 8px;">
                        <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 16px;">🚫 Your OAuth Tokens</h4>
                        <p style="margin: 0; color: #555; line-height: 1.6;">Cannot access the security tokens that connect to your Google account. They're stored only on YOUR computer.</p>
                    </div>
                </div>

                <!-- Section 2: Why This Is True (Technical Explanation) -->
                <div style="background: #e3f2fd; border: 2px solid #2196f3; padding: 25px; border-radius: 12px; margin-bottom: 25px;">
                    <h3 style="color: #1976d2; margin: 0 0 20px 0; font-size: 22px; display: flex; align-items: center;">
                        <span style="font-size: 32px; margin-right: 12px;">🔐</span>
                        Why Your Data is Private (Technical Proof)
                    </h3>

                    <div style="background: white; padding: 20px; border-radius: 8px; margin-bottom: 15px;">
                        <h4 style="margin: 0 0 12px 0; color: #1976d2; font-size: 16px;">1. OAuth Tokens Are Stored Locally</h4>
                        <p style="margin: 0 0 10px 0; color: #555; line-height: 1.6;">When you authorize Google access during setup, your OAuth token is saved to:</p>
                        <pre style="background: #f5f5f5; padding: 12px; border-radius: 6px; font-size: 13px; margin: 0 0 10px 0; overflow-x: auto;">~/gmail-calendar-mcp/credentials/token.json</pre>
                        <p style="margin: 0; color: #555; line-height: 1.6;"><strong>This file lives on YOUR computer only.</strong> It never gets sent to any server, cloud, or shared location. Jonathan has no way to access files on your machine.</p>
                    </div>

                    <div style="background: white; padding: 20px; border-radius: 8px; margin-bottom: 15px;">
                        <h4 style="margin: 0 0 12px 0; color: #1976d2; font-size: 16px;">2. MCP Server Runs Locally</h4>
                        <p style="margin: 0 0 10px 0; color: #555; line-height: 1.6;">The MCP server that connects Claude to your Gmail/Calendar runs as a local process on YOUR machine:</p>
                        <pre style="background: #f5f5f5; padding: 12px; border-radius: 6px; font-size: 13px; margin: 0 0 10px 0; overflow-x: auto;">~/gmail-calendar-mcp/venv/bin/python ~/gmail-calendar-mcp/src/server.py</pre>
                        <p style="margin: 0; color: #555; line-height: 1.6;"><strong>This is your own private server.</strong> It only responds to YOUR Claude Desktop app. No one else can connect to it.</p>
                    </div>

                    <div style="background: white; padding: 20px; border-radius: 8px; margin-bottom: 15px;">
                        <h4 style="margin: 0 0 12px 0; color: #1976d2; font-size: 16px;">3. Direct Google API Connection</h4>
                        <p style="margin: 0; color: #555; line-height: 1.6;">When Claude asks for your emails or calendar:</p>
                        <ol style="margin: 10px 0 0 20px; padding: 0; color: #555; line-height: 1.8;">
                            <li>Your local MCP server uses YOUR token</li>
                            <li>Connects directly to Google's API (gmail.googleapis.com)</li>
                            <li>Fetches data and returns it to Claude on YOUR machine</li>
                            <li>Nothing touches the internet except the Google API call</li>
                        </ol>
                        <p style="margin: 10px 0 0 0; color: #555; line-height: 1.6;"><strong>No middleman, no shared server, no admin access.</strong></p>
                    </div>

                    <div style="background: white; padding: 20px; border-radius: 8px;">
                        <h4 style="margin: 0 0 12px 0; color: #1976d2; font-size: 16px;">4. You Can Verify This Yourself</h4>
                        <p style="margin: 0 0 10px 0; color: #555; line-height: 1.6;">Check where your token is stored (only on your machine):</p>
                        <pre style="background: #f5f5f5; padding: 12px; border-radius: 6px; font-size: 13px; margin: 0 0 10px 0; overflow-x: auto;">ls -la ~/gmail-calendar-mcp/credentials/token.json</pre>
                        <p style="margin: 10px 0 0 0; color: #555; line-height: 1.6;">Check the file permissions (only YOU can read it):</p>
                        <pre style="background: #f5f5f5; padding: 12px; border-radius: 6px; font-size: 13px; margin: 0; overflow-x: auto;">-rw------- 1 yourname staff ... token.json</pre>
                        <p style="margin: 10px 0 0 0; color: #666; font-size: 14px;">The <code>-rw-------</code> means only you can read/write this file.</p>
                    </div>
                </div>

                <!-- Section 3: What Jonathan CAN See -->
                <div style="background: #fff8e1; border: 2px solid #ff9800; padding: 25px; border-radius: 12px; margin-bottom: 25px;">
                    <h3 style="color: #e65100; margin: 0 0 20px 0; font-size: 22px; display: flex; align-items: center;">
                        <span style="font-size: 32px; margin-right: 12px;">⚠️</span>
                        What Jonathan CAN Access (Full Transparency)
                    </h3>

                    <div style="background: #e3f2fd; padding: 20px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid #2196f3;">
                        <h4 style="margin: 0 0 10px 0; color: #1976d2; font-size: 16px;">📌 Important: Default Setup is Fully Private</h4>
                        <p style="margin: 0; color: #555; line-height: 1.6;"><strong>When you run the install script, you get a LOCAL MCP server.</strong> This means Jonathan has ZERO visibility into your usage. The items below only apply if you were to manually connect to the Railway shared server (which is NOT the default setup).</p>
                    </div>

                    <div style="background: white; padding: 20px; border-radius: 8px; margin-bottom: 15px;">
                        <h4 style="margin: 0 0 12px 0; color: #e65100; font-size: 16px;">✓ Admin Dashboard (ONLY if using Railway shared server)</h4>
                        <p style="margin: 0 0 10px 0; color: #555; line-height: 1.6;"><strong>Default install:</strong> You run locally → <span style="color: #4caf50; font-weight: bold;">NO admin visibility</span></p>
                        <p style="margin: 0 0 10px 0; color: #555; line-height: 1.6;"><strong>If manually configured to Railway:</strong> Admin dashboard can see usage analytics</p>

                        <div style="background: #f5f5f5; padding: 15px; border-radius: 6px; margin-top: 12px;">
                            <p style="margin: 0 0 8px 0; color: #333; font-weight: bold;">What Admin Dashboard Shows:</p>
                            <ul style="margin: 0; padding-left: 20px; color: #555; line-height: 1.8;">
                                <li>✓ Your email address (for identification)</li>
                                <li>✓ Which tools you used (e.g., "search_gmail", "create_calendar_event")</li>
                                <li>✓ When you used them (timestamps)</li>
                                <li>✓ Success/failure status</li>
                                <li>✓ Error messages (if tools failed)</li>
                            </ul>

                            <p style="margin: 12px 0 0 0; color: #d32f2f; font-weight: bold;">What Admin Dashboard CANNOT See:</p>
                            <ul style="margin: 0; padding-left: 20px; color: #555; line-height: 1.8;">
                                <li>❌ Actual email content</li>
                                <li>❌ Search queries you typed</li>
                                <li>❌ Calendar event details</li>
                                <li>❌ Any arguments passed to tools</li>
                                <li>❌ OAuth tokens</li>
                            </ul>
                        </div>

                        <p style="margin: 15px 0 0 0; color: #666; font-size: 14px;"><strong>Think of it like web server logs:</strong> The admin can see "User searched Gmail at 3:45pm" but cannot see what they searched for or what results they got.</p>
                    </div>

                    <div style="background: white; padding: 20px; border-radius: 8px; margin-bottom: 15px;">
                        <h4 style="margin: 0 0 12px 0; color: #e65100; font-size: 16px;">✓ Client API Keys (Bison & Instantly)</h4>
                        <p style="margin: 0 0 10px 0; color: #555; line-height: 1.6;"><strong>Location:</strong> Stored in a shared Google Sheet that tracks client campaigns</p>
                        <p style="margin: 0 0 10px 0; color: #555; line-height: 1.6;"><strong>What this means:</strong> Jonathan can create/manage marketing campaigns for clients using Bison and Instantly</p>
                        <p style="margin: 0; color: #d32f2f; line-height: 1.6; font-size: 14px;"><strong>⚠️ Important:</strong> This is for client campaign management, not your personal Gmail/Calendar</p>
                    </div>

                    <div style="background: white; padding: 20px; border-radius: 8px;">
                        <h4 style="margin: 0 0 12px 0; color: #e65100; font-size: 16px;">✓ This Source Code</h4>
                        <p style="margin: 0 0 10px 0; color: #555; line-height: 1.6;"><strong>What:</strong> The entire MCP server code is on GitHub (open source)</p>
                        <p style="margin: 0; color: #555; line-height: 1.6;"><strong>Why this matters:</strong> You can audit the code yourself to verify these privacy claims</p>
                        <a href="https://github.com/jonathangetonapod/gmail-reply-tracker-mcp" target="_blank" style="display: inline-block; margin-top: 10px; padding: 8px 16px; background: #2196f3; color: white; text-decoration: none; border-radius: 6px; font-size: 14px;">View Source Code on GitHub</a>
                    </div>
                </div>

                <!-- Architecture Diagram -->
                <div style="background: #f5f5f5; border: 2px solid #757575; padding: 25px; border-radius: 12px; margin-bottom: 25px;">
                    <h3 style="color: #424242; margin: 0 0 20px 0; font-size: 22px; text-align: center;">
                        📊 How Data Flows (Visual Explanation)
                    </h3>

                    <div style="background: white; padding: 25px; border-radius: 8px; font-family: monospace; font-size: 13px; line-height: 2;">
                        <div style="text-align: center; margin-bottom: 15px;">
                            <strong style="color: #2196f3; font-size: 15px;">YOUR COMPUTER (100% Private)</strong>
                        </div>
                        <div style="padding-left: 20px; border-left: 3px solid #4caf50;">
                            ├─ 💻 Claude Desktop (your app)<br>
                            │  └─ Asks: "Show me unreplied emails"<br>
                            │<br>
                            ├─ 🔌 MCP Server (runs locally)<br>
                            │  └─ Receives request from Claude<br>
                            │<br>
                            ├─ 🔑 token.json (YOUR OAuth token)<br>
                            │  └─ Stored only on YOUR machine<br>
                            │  └─ <strong style="color: #4caf50;">✅ Jonathan CANNOT access this</strong><br>
                            │<br>
                            └─ 🌐 Direct API call to Google<br>
                               └─ gmail.googleapis.com (using YOUR token)<br>
                               └─ Returns YOUR emails to YOUR machine
                        </div>
                        <div style="margin-top: 20px; padding: 15px; background: #e8f5e9; border-radius: 6px; border-left: 4px solid #4caf50;">
                            <strong style="color: #2e7d32;">✅ Result:</strong> Your data never leaves your machine except for the direct Google API call, which uses YOUR credentials and returns data only to YOU.
                        </div>
                    </div>
                </div>

                <!-- You Can Revoke Access -->
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 25px; border-radius: 12px; margin-bottom: 25px;">
                    <h3 style="color: white; margin: 0 0 15px 0; font-size: 20px;">🔓 You Have Full Control</h3>
                    <p style="margin: 0 0 15px 0; opacity: 0.95; line-height: 1.6;">You can revoke access to your Gmail/Calendar at any time:</p>
                    <ol style="margin: 0 0 20px 20px; padding: 0; opacity: 0.95; line-height: 1.8;">
                        <li>Visit <a href="https://myaccount.google.com/permissions" target="_blank" style="color: #fff; text-decoration: underline;">Google Account Permissions</a></li>
                        <li>Find the MCP app in the list</li>
                        <li>Click "Remove Access"</li>
                        <li>Done! The MCP server can no longer access your data</li>
                    </ol>
                    <a href="https://myaccount.google.com/permissions" target="_blank"
                       style="display: inline-block; background: white; color: #667eea; padding: 12px 24px;
                              border-radius: 6px; text-decoration: none; font-weight: 600;">
                        Manage Google Permissions →
                    </a>
                </div>

                <!-- Bottom Line Summary -->
                <div style="background: #f5f5f5; padding: 30px; border-radius: 12px; text-align: center; border: 3px solid #4caf50;">
                    <h3 style="margin: 0 0 15px 0; font-size: 24px; color: #2e7d32;">🎯 Bottom Line</h3>
                    <p style="margin: 0 0 10px 0; font-size: 18px; color: #333; line-height: 1.6;">
                        <strong>Default Install (Recommended):</strong> Your personal Gmail, Calendar, and Fathom data is <strong>100% private</strong> and stored only on your computer. Jonathan has <strong>ZERO visibility</strong> into your usage.
                    </p>
                    <p style="margin: 10px 0; font-size: 16px; color: #666; line-height: 1.6;">
                        If manually configured to use Railway shared server: Jonathan can see usage analytics (which tools, when) but <strong>NOT the actual content</strong> (emails, calendar details, search queries, etc.).
                    </p>
                    <p style="margin: 10px 0 0 0; font-size: 16px; color: #666; line-height: 1.6;">
                        Jonathan can only access shared client API keys for campaign management (Bison/Instantly) - nothing personal.
                    </p>
                </div>

            </div>
        </div>
    </div>

    <script>
        function openModal() {
            document.getElementById('infoModal').style.display = 'block';
            document.body.style.overflow = 'hidden';
        }

        function closeModal() {
            document.getElementById('infoModal').style.display = 'none';
            document.body.style.overflow = 'auto';
        }

        function closeModalOnClickOutside(event) {
            if (event.target.id === 'infoModal') {
                closeModal();
            }
        }

        function openTroubleshootingModal() {
            document.getElementById('troubleshootingModal').style.display = 'block';
            document.body.style.overflow = 'hidden';
        }

        function closeTroubleshootingModal() {
            document.getElementById('troubleshootingModal').style.display = 'none';
            document.body.style.overflow = 'auto';
        }

        function closeTroubleshootingModalOnClickOutside(event) {
            if (event.target.id === 'troubleshootingModal') {
                closeTroubleshootingModal();
            }
        }

        function openPrivacyModal() {
            document.getElementById('privacyModal').style.display = 'block';
            document.body.style.overflow = 'hidden';
        }

        function closePrivacyModal() {
            document.getElementById('privacyModal').style.display = 'none';
            document.body.style.overflow = 'auto';
        }

        function closePrivacyModalOnClickOutside(event) {
            if (event.target.id === 'privacyModal') {
                closePrivacyModal();
            }
        }

        // Close modals with Escape key
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                closeModal();
                closeTroubleshootingModal();
                closePrivacyModal();
            }
        });
    </script>
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
                    <option value="windows">Windows (Coming Soon)</option>
                </select>
            </label>
        </div>

        <div id="mac-command" class="command-container">
            <div class="command-box">
                <pre>curl -fsSL https://raw.githubusercontent.com/jonathangetonapod/gmail-reply-tracker-mcp/main/local_install.sh | bash -s "{{ email }}"{% if fathom_key %} "{{ fathom_key }}"{% endif %}</pre>
            </div>
            <button class="copy-btn" onclick="copyToClipboard('mac')">Copy Command</button>
            <div class="instructions">
                1. Copy the command above<br>
                2. Open Terminal<br>
                3. Paste and press Enter<br>
                4. Browser will open for Google authorization<br>
                5. Restart Claude Desktop
            </div>
        </div>

        <div id="windows-command" class="command-container" style="display:none;">
            <div class="command-box">
                <pre># Windows installer coming soon!<br># For now, please use Mac/Linux or install manually</pre>
            </div>
            <div class="instructions">
                Windows support coming soon. Please use Mac/Linux for now.
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
                'mac': 'curl -fsSL https://raw.githubusercontent.com/jonathangetonapod/gmail-reply-tracker-mcp/main/local_install.sh | bash -s "{{ email }}"{% if fathom_key %} "{{ fathom_key }}"{% endif %}',
                'windows': '# Windows installer coming soon!'
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
            """Show simple form to collect email and Fathom key."""
            form_html = """
<!DOCTYPE html>
<html>
<head>
    <title>Setup - Gmail Calendar MCP</title>
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
        h1 {
            color: #333;
            margin-bottom: 8px;
            font-size: 24px;
        }
        .subtitle {
            color: #666;
            font-size: 16px;
            margin-bottom: 30px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 500;
            font-size: 14px;
        }
        input[type="email"],
        input[type="text"] {
            width: 100%;
            padding: 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            margin-bottom: 20px;
        }
        input:focus {
            outline: none;
            border-color: #2196f3;
        }
        .help-text {
            font-size: 12px;
            color: #999;
            margin-top: -15px;
            margin-bottom: 20px;
        }
        .button {
            background: #2196f3;
            color: white;
            border: none;
            padding: 14px;
            font-size: 16px;
            font-weight: 500;
            border-radius: 4px;
            cursor: pointer;
            width: 100%;
        }
        .button:hover {
            background: #1976d2;
        }
        .note {
            background: #e3f2fd;
            padding: 15px;
            border-radius: 6px;
            margin: 20px 0;
            border-left: 4px solid #2196f3;
            font-size: 14px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>Gmail + Calendar + Fathom MCP</h1>
        <p class="subtitle">Set up Gmail and Calendar tools for Claude Desktop</p>

        <div class="note">
            <strong>How it works:</strong><br>
            1. Enter your email and optional Fathom key<br>
            2. Get a custom install command<br>
            3. Run it in your terminal<br>
            4. Authorize Google (one time)<br>
            5. Done!
        </div>

        <form method="POST" action="/setup/generate">
            <label for="email">Your Email:</label>
            <input type="email" id="email" name="email" placeholder="you@example.com" required>
            <div class="help-text">Used to identify your setup</div>

            <label for="fathom_key">Fathom API Key (Optional):</label>
            <input type="text" id="fathom_key" name="fathom_key" placeholder="Leave blank to skip">
            <div class="help-text">
                Get your key at <a href="https://fathom.video/settings/integrations" target="_blank">fathom.video/settings/integrations</a>
            </div>

            <button type="submit" class="button">Generate Install Command</button>
        </form>
    </div>
</body>
</html>
            """
            return form_html

        @self.app.route('/setup/generate', methods=['POST'])
        def setup_generate():
            """Generate install command with email and Fathom key."""
            email = request.form.get('email', '').strip()
            fathom_key = request.form.get('fathom_key', '').strip()

            if not email:
                return "<h1>Error</h1><p>Email is required</p>", 400

            # Show success page with install command
            return render_template_string(
                SUCCESS_HTML,
                email=email,
                token='',  # Not needed for local install
                server_url='',  # Not needed
                has_fathom=bool(fathom_key),
                fathom_key=fathom_key,
                config_json=''  # Not needed
            )

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
            import time
            handler = MCPHandler()

            # Track timing for analytics
            start_time = time.time()

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

            # Calculate response time
            response_time_ms = int((time.time() - start_time) * 1000)

            # Log usage for analytics
            try:
                method = request_data.get('method', 'unknown')
                tool_name = 'unknown'

                # Extract tool name from tools/call requests
                if method == 'tools/call':
                    params = request_data.get('params', {})
                    tool_name = params.get('name', 'unknown')

                # Check if request was successful
                success = 'result' in response
                error_message = None
                if not success and 'error' in response:
                    error_message = response['error'].get('message', 'Unknown error')

                # Log to database
                self.database.log_usage(
                    user_id=user['user_id'],
                    tool_name=tool_name,
                    method=method,
                    success=success,
                    error_message=error_message,
                    response_time_ms=response_time_ms
                )
            except Exception as e:
                # Don't fail the request if logging fails
                self.logger.error(f"Failed to log usage: {e}")

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
            expected_token = os.environ.get('ADMIN_TOKEN', 'change-me-in-production')

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
        <h2>📊 Usage Analytics (Last 7 Days)</h2>
        <div id="analytics-summary" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0;">
            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center;">
                <div style="font-size: 32px; font-weight: bold; color: #2196f3;">-</div>
                <div style="color: #666; font-size: 14px;">Total Requests</div>
            </div>
            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center;">
                <div style="font-size: 32px; font-weight: bold; color: #28a745;">-</div>
                <div style="color: #666; font-size: 14px;">Success Rate</div>
            </div>
            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center;">
                <div style="font-size: 32px; font-weight: bold; color: #6c757d;">-</div>
                <div style="color: #666; font-size: 14px;">Active Users</div>
            </div>
        </div>

        <h3>Top Tools</h3>
        <div id="top-tools" style="margin: 20px 0;">
            <p style="color: #999;">Loading...</p>
        </div>

        <h3>Recent Activity (Real-time)</h3>
        <div id="recent-activity" style="max-height: 300px; overflow-y: auto; border: 1px solid #ddd; border-radius: 6px; padding: 10px;">
            <p style="color: #999;">Loading...</p>
        </div>
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

        async function loadAnalytics() {
            try {
                // Load overall analytics
                const analyticsResponse = await fetch('/admin/analytics?days=7', {
                    headers: {
                        'Authorization': `Bearer ${adminToken}`
                    }
                });
                const analytics = await analyticsResponse.json();

                // Update summary cards
                const summaryDiv = document.querySelector('#analytics-summary');
                const totalRequests = analytics.total_requests || 0;

                // Calculate success rate
                let successRate = 0;
                if (totalRequests > 0) {
                    const successCount = analytics.user_stats ?
                        analytics.user_stats.reduce((sum, user) => sum + (user.requests || 0), 0) : 0;
                    successRate = totalRequests > 0 ? Math.round((successCount / totalRequests) * 100) : 0;
                }

                const activeUsers = analytics.user_stats ?
                    analytics.user_stats.filter(u => u.requests > 0).length : 0;

                summaryDiv.innerHTML = `
                    <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #2196f3;">${totalRequests}</div>
                        <div style="color: #666; font-size: 14px;">Total Requests</div>
                    </div>
                    <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #28a745;">${successRate}%</div>
                        <div style="color: #666; font-size: 14px;">Success Rate</div>
                    </div>
                    <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #6c757d;">${activeUsers}</div>
                        <div style="color: #666; font-size: 14px;">Active Users</div>
                    </div>
                `;

                // Update top tools
                const topToolsDiv = document.querySelector('#top-tools');
                if (analytics.top_tools && Object.keys(analytics.top_tools).length > 0) {
                    const toolsHtml = Object.entries(analytics.top_tools)
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 5)
                        .map(([tool, count]) => {
                            const percentage = Math.round((count / totalRequests) * 100);
                            return `
                                <div style="margin-bottom: 10px;">
                                    <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                                        <span><strong>${tool}</strong></span>
                                        <span style="color: #666;">${count} uses (${percentage}%)</span>
                                    </div>
                                    <div style="background: #e9ecef; border-radius: 4px; height: 8px;">
                                        <div style="background: #2196f3; border-radius: 4px; height: 8px; width: ${percentage}%;"></div>
                                    </div>
                                </div>
                            `;
                        }).join('');
                    topToolsDiv.innerHTML = toolsHtml;
                } else {
                    topToolsDiv.innerHTML = '<p style="color: #999;">No tool usage data yet</p>';
                }

                // Load recent activity
                const activityResponse = await fetch('/admin/analytics/activity?limit=20', {
                    headers: {
                        'Authorization': `Bearer ${adminToken}`
                    }
                });
                const activityData = await activityResponse.json();

                const activityDiv = document.querySelector('#recent-activity');
                if (activityData.activities && activityData.activities.length > 0) {
                    const activityHtml = activityData.activities.map(activity => {
                        const timestamp = new Date(activity.timestamp).toLocaleString();
                        const statusColor = activity.success ? '#28a745' : '#dc3545';
                        const statusIcon = activity.success ? '✓' : '✗';

                        return `
                            <div style="padding: 10px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <div>
                                        <strong>${activity.email}</strong>
                                        <span style="color: #666;">→ ${activity.tool_name}</span>
                                    </div>
                                    <div style="font-size: 12px; color: #999;">
                                        ${timestamp}
                                        ${activity.error ? `<br><span style="color: #dc3545;">Error: ${activity.error}</span>` : ''}
                                    </div>
                                </div>
                                <div>
                                    <span style="color: ${statusColor}; font-weight: bold;">${statusIcon}</span>
                                </div>
                            </div>
                        `;
                    }).join('');
                    activityDiv.innerHTML = activityHtml;
                } else {
                    activityDiv.innerHTML = '<p style="color: #999; padding: 20px; text-align: center;">No activity yet</p>';
                }

            } catch (error) {
                console.error('Error loading analytics:', error);
            }
        }

        // Load users on page load
        loadUsers();
        loadAnalytics();

        // Refresh every 30 seconds
        setInterval(() => {
            loadUsers();
            loadAnalytics();
        }, 30000);
    </script>
</body>
</html>
            """

            return render_template_string(admin_html, admin_token=expected_token)

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

        @self.app.route('/admin/analytics')
        def admin_analytics():
            """Admin endpoint to view overall usage analytics."""
            import os
            admin_token = request.headers.get('Authorization', '').replace('Bearer ', '')
            expected_token = os.environ.get('ADMIN_TOKEN', 'change-me-in-production')

            if admin_token != expected_token:
                return jsonify({"error": "Unauthorized"}), 401

            try:
                days = int(request.args.get('days', 7))
                stats = self.database.get_all_usage_stats(days=days)
                return jsonify(stats)
            except Exception as e:
                logger.error("Failed to get analytics: %s", str(e))
                return jsonify({"error": str(e)}), 500

        @self.app.route('/admin/analytics/user/<user_id>')
        def admin_user_analytics(user_id):
            """Admin endpoint to view user-specific usage analytics."""
            import os
            admin_token = request.headers.get('Authorization', '').replace('Bearer ', '')
            expected_token = os.environ.get('ADMIN_TOKEN', 'change-me-in-production')

            if admin_token != expected_token:
                return jsonify({"error": "Unauthorized"}), 401

            try:
                days = int(request.args.get('days', 7))
                stats = self.database.get_user_usage_stats(user_id=user_id, days=days)
                return jsonify(stats)
            except Exception as e:
                logger.error("Failed to get user analytics: %s", str(e))
                return jsonify({"error": str(e)}), 500

        @self.app.route('/admin/analytics/activity')
        def admin_activity_feed():
            """Admin endpoint to view real-time activity feed."""
            import os
            admin_token = request.headers.get('Authorization', '').replace('Bearer ', '')
            expected_token = os.environ.get('ADMIN_TOKEN', 'change-me-in-production')

            if admin_token != expected_token:
                return jsonify({"error": "Unauthorized"}), 401

            try:
                limit = int(request.args.get('limit', 50))
                activities = self.database.get_recent_activity(limit=limit)
                return jsonify({"activities": activities})
            except Exception as e:
                logger.error("Failed to get activity feed: %s", str(e))
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
