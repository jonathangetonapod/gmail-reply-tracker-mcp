# Railway Deployment Guide - Multi-Tenant MCP Server

## 🎯 What We're Building

A centralized multi-tenant MCP server where:
- You deploy once to Railway
- Team members run a simple setup command
- They authenticate with their own Google accounts
- They optionally add their own Fathom API keys
- Updates happen automatically when you push to GitHub

---

## 📊 Current Progress

### ✅ Completed
1. **Database Schema** (`src/database.py`)
   - User table with encrypted credentials
   - Session management (90-day expiry)
   - Per-user Google OAuth tokens
   - Per-user Fathom API keys
   - SQLite-based (easy to migrate to PostgreSQL later)

2. **Web Server Foundation** (`src/web_server.py`)
   - Flask-based OAuth flow
   - Google sign-in integration
   - User setup pages
   - Health check endpoint

3. **Dependencies Updated** (`requirements.txt`)
   - Added Flask for web server
   - Added cryptography for token encryption
   - All existing dependencies preserved

4. **Railway Configuration**
   - `railway.toml` - Railway build/deploy config
   - `Procfile` - Process definition

### 🚧 Still Needed
1. **Complete Web Server Implementation**
   - Finish OAuth callback flow
   - Properly store credentials after authentication
   - Generate setup completion response
   - Create user setup script endpoint

2. **Multi-Tenant MCP Server**
   - Modify `src/server.py` to accept session tokens
   - Route requests to correct user's credentials
   - Handle per-user Fathom keys

3. **User Setup Script**
   - Bash script that team members run
   - Opens browser for OAuth
   - Configures Claude Desktop automatically

4. **Environment Configuration**
   - Document required Railway environment variables
   - Create `.env.example` for local testing

5. **Testing & Documentation**
   - Test OAuth flow
   - Test multi-user scenarios
   - Write admin documentation

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────┐
│  Railway Deployment                         │
│                                             │
│  ┌───────────────────────────────────────┐ │
│  │  Flask Web Server (Port 8080)         │ │
│  │  - /setup (OAuth flow)                │ │
│  │  - /auth/callback (Google redirect)   │ │
│  │  - /health (health check)             │ │
│  │  - /install.sh (setup script)         │ │
│  └───────────────────────────────────────┘ │
│                                             │
│  ┌───────────────────────────────────────┐ │
│  │  MCP Server (HTTP endpoint)           │ │
│  │  - Accepts session tokens             │ │
│  │  - Routes to user credentials         │ │
│  │  - Executes Gmail/Calendar/Fathom ops│ │
│  └───────────────────────────────────────┘ │
│                                             │
│  ┌───────────────────────────────────────┐ │
│  │  SQLite Database                      │ │
│  │  - User sessions                      │ │
│  │  - Encrypted Google tokens            │ │
│  │  - Encrypted Fathom keys              │ │
│  └───────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
         ↓                    ↓
    [User 1 Claude]     [User 2 Claude]
```

---

## 🔐 Security Model

### Encryption
- **Master Key**: Stored in Railway environment variable `TOKEN_ENCRYPTION_KEY`
- **Algorithm**: Fernet (AES-256-CBC + HMAC)
- **What's Encrypted**:
  - Google OAuth tokens (per user)
  - Fathom API keys (per user)
- **What's NOT Encrypted**:
  - Email addresses (needed for lookups)
  - Session tokens (UUIDs, not sensitive)
  - Timestamps

### Authentication Flow
```
1. User runs: curl https://yourapp.railway.app/setup | bash

2. Browser opens → User clicks "Sign in with Google"

3. Google OAuth → User grants permissions

4. Server receives:
   - Google OAuth token (access to THEIR Gmail/Calendar)
   - User email

5. Optional: User enters their Fathom API key

6. Server:
   - Encrypts tokens with master key
   - Stores in database
   - Generates session token
   - Returns session token to setup script

7. Setup script:
   - Writes session token to Claude Desktop config
   - User restarts Claude
   - Done!

8. Daily use:
   - Claude sends session token with each request
   - Server looks up user by session token
   - Server decrypts THAT user's credentials
   - Server makes API calls with user's tokens
   - Returns results
```

---

## 📋 Environment Variables (Railway Dashboard)

You'll need to set these in Railway:

```bash
# Google OAuth (YOUR shared OAuth app)
GOOGLE_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=abc123secret

# OAuth Redirect URI
GOOGLE_REDIRECT_URI=https://yourapp.railway.app/auth/callback

# OAuth Scopes
GOOGLE_OAUTH_SCOPES=https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar,https://www.googleapis.com/auth/userinfo.email

# Encryption Key (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
TOKEN_ENCRYPTION_KEY=<generated-key-here>

# Database Path
DATABASE_PATH=./data/users.db

# Server Config
FLASK_ENV=production
PORT=8080
SESSION_SECRET=<random-secret>

# Railway Public URL (auto-set by Railway)
RAILWAY_PUBLIC_DOMAIN=yourapp.railway.app
```

---

## 🚀 Deployment Steps (When Complete)

### 1. Set Up Google Cloud Project (One Time)

```bash
1. Go to https://console.cloud.google.com
2. Create project: "yourcompany-mcp-server"
3. Enable APIs:
   - Gmail API
   - Google Calendar API
   - People API
4. OAuth Consent Screen:
   - Type: External
   - App name: "YourCompany MCP Integration"
   - Add scopes: gmail.modify, calendar, userinfo.email
5. Create OAuth Credentials:
   - Type: Web application
   - Authorized redirect URIs: https://yourapp.railway.app/auth/callback
6. Copy Client ID and Client Secret
```

### 2. Deploy to Railway

```bash
# Connect Railway to your GitHub repo
railway login
railway link

# Set environment variables in Railway dashboard
railway variables set GOOGLE_CLIENT_ID=...
railway variables set GOOGLE_CLIENT_SECRET=...
railway variables set TOKEN_ENCRYPTION_KEY=...
# (set all other variables)

# Push to GitHub (Railway auto-deploys)
git add .
git commit -m "Deploy multi-tenant MCP server"
git push origin main

# Railway automatically:
# - Builds the container
# - Installs dependencies
# - Starts the web server
# - Provides HTTPS endpoint
```

### 3. Test Your Deployment

```bash
# Check health
curl https://yourapp.railway.app/health

# Should return:
{"status": "healthy", "timestamp": "2024-12-15T..."}

# Test setup page
open https://yourapp.railway.app/setup
```

### 4. Onboard First User (You)

```bash
# Run setup command
curl -sSL https://yourapp.railway.app/install.sh | bash

# Follow prompts:
# 1. Browser opens
# 2. Sign in with Google
# 3. Enter Fathom API key (optional)
# 4. Setup completes
# 5. Restart Claude Desktop

# Test in Claude
"What emails need my attention?"
```

### 5. Onboard Team Members

Send them this message:

```
Hey team! To connect Claude to Gmail/Calendar/Fathom, run this command:

curl -sSL https://yourapp.railway.app/install.sh | bash

It takes 5 minutes and walks you through the setup. Let me know if you need help!
```

---

## 🔄 Update Workflow

```bash
# Make changes locally
git add .
git commit -m "Add new feature"
git push origin main

# Railway automatically:
# - Detects push
# - Builds new version
# - Deploys with zero downtime
# - All users get update immediately (no action needed)
```

---

## 📊 Monitoring & Admin

### View Logs
```bash
# In Railway dashboard
# Click on deployment → View Logs

# Or via CLI
railway logs
```

### List Active Users
```bash
curl https://yourapp.railway.app/admin/users
# TODO: Add authentication to this endpoint
```

### Database Management
```bash
# SSH into Railway container (if needed)
railway run bash

# Check database
sqlite3 ./data/users.db "SELECT email, created_at, last_active FROM users;"
```

---

## 🚧 Next Steps to Complete

### Immediate (Required for MVP)
1. **Finish OAuth Flow** (`src/web_server.py`)
   - Complete `/auth/callback` to properly store credentials
   - Pass credentials through to Fathom form
   - Generate session token and return to user

2. **Create Setup Script** (`static/install.sh`)
   - Bash script that opens browser
   - Polls for completion
   - Writes Claude Desktop config
   - Shows success message

3. **Multi-Tenant MCP Server** (`src/multi_tenant_server.py`)
   - New file that wraps existing `server.py`
   - Accepts HTTP requests with session tokens
   - Routes to user-specific credentials
   - Returns MCP responses

4. **Main Entry Point** (`src/web_server_main.py`)
   - Combines web server + MCP server
   - Single process for Railway

### Nice to Have (Post-MVP)
1. **Admin Dashboard**
   - Web UI to view active users
   - Revoke user access
   - View usage stats

2. **User Self-Service Portal**
   - Update Fathom API key
   - Revoke own access
   - View connection status

3. **Monitoring**
   - Error tracking (Sentry)
   - Usage metrics
   - Uptime monitoring

4. **PostgreSQL Migration**
   - For teams > 50 users
   - Better concurrency
   - Easier backups

---

## 💡 Current File Structure

```
MCP_Gmail/
├── src/
│   ├── server.py              # Original single-user MCP server
│   ├── database.py            # ✅ NEW: User database with encryption
│   ├── web_server.py          # ✅ NEW: OAuth flow & setup pages
│   ├── config.py              # Configuration management
│   ├── auth.py                # Google OAuth (single-user)
│   ├── gmail_client.py        # Gmail API wrapper
│   ├── calendar_client.py     # Calendar API wrapper
│   ├── fathom_client.py       # Fathom API wrapper
│   └── email_analyzer.py      # Email intelligence
│
├── requirements.txt           # ✅ UPDATED: Added Flask, cryptography
├── railway.toml               # ✅ NEW: Railway configuration
├── Procfile                   # ✅ NEW: Process definition
├── .env.example               # TODO: Environment variable template
├── README.md                  # Existing documentation
└── RAILWAY_DEPLOYMENT.md      # ✅ NEW: This file!
```

---

## ❓ Questions & Decisions

### Q: SQLite vs PostgreSQL?
**A:** Start with SQLite (simpler, included). Migrate to PostgreSQL if:
- You exceed 50 concurrent users
- You need better backup/replication
- You want Railway's managed database

### Q: One server or separate MCP + web servers?
**A:** One combined server (simpler deployment, fewer resources)

### Q: How to handle MCP protocol over HTTP?
**A:** Use `@modelcontextprotocol/mcp-client-cli` package on client side

### Q: Session expiry?
**A:** 90 days (can be adjusted). Users re-run setup script if expired.

### Q: What if Google token expires?
**A:** Auto-refresh using refresh token (handled by Google API library)

---

## 📞 Support for Team Members

Create a simple support doc:

```markdown
# MCP Server Setup Help

## Setup Command
curl -sSL https://yourapp.railway.app/install.sh | bash

## Troubleshooting

**"Command not found: curl"**
- Mac: curl is pre-installed
- Contact IT if you see this error

**"Browser didn't open"**
- Manually visit: https://yourapp.railway.app/setup

**"Permission denied"**
- The setup needs to write to: ~/Library/Application Support/Claude/
- Make sure Claude Desktop is installed

**"Tools not appearing in Claude"**
1. Restart Claude Desktop completely (Quit and reopen)
2. Check if setup completed successfully
3. Contact [your-name] for help

## Where's my Fathom API key?
1. Go to https://fathom.video/settings/integrations
2. Click "API" tab
3. Copy the key (starts with "fathom_")
```

---

## 🎉 What You'll Have When Complete

**Team members run ONE command:**
```bash
curl -sSL https://yourapp.railway.app/install.sh | bash
```

**You push updates with ONE command:**
```bash
git push origin main
```

**Zero ongoing maintenance:**
- Auto token refresh
- Auto HTTPS (Railway)
- Auto restarts on errors
- Auto deployments from GitHub

**Scales to 50+ users:**
- Shared rate limits across team
- Individual credentials (proper security)
- Central updates (everyone gets fixes immediately)

---

## 📝 Next Immediate Actions

1. **Generate Encryption Key**
   ```bash
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. **Finish Implementation**
   - Complete web server OAuth flow
   - Create setup script
   - Build multi-tenant MCP wrapper
   - Test locally

3. **Deploy to Railway**
   - Set environment variables
   - Push to GitHub
   - Test with your account
   - Onboard pilot users

**Ready to continue? Let me know and I'll complete the remaining implementation!**
