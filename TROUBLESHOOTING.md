# Troubleshooting Guide

Common issues and how to fix them.

## "Server disconnected" Error

**What you see:**
```
MCP gmail-calendar-fathom: Server disconnected
```

**What it means:** Claude Desktop can't find or run the Python server.

**How to fix:**

1. **Did you restart Claude Desktop properly?**
   - Press `⌘Q` (Command-Q) to fully quit Claude Desktop
   - Don't just close the window - you must QUIT the app
   - Then reopen Claude Desktop

2. **Is the installation directory correct?**
   ```bash
   ls ~/gmail-calendar-mcp/src/server.py
   ```
   If you see "No such file or directory", the installation didn't complete.

   **Fix:** Re-run the install command

3. **Run the config fix script:**
   ```bash
   curl -fsSL https://raw.githubusercontent.com/jonathangetonapod/gmail-reply-tracker-mcp/main/fix_config.py | python3
   ```
   Then restart Claude Desktop (⌘Q, then reopen)

---

## "Module not found" Error

**What it means:** Python dependencies aren't installed.

**How to fix:**
```bash
cd ~/gmail-calendar-mcp
./venv/bin/python -m pip install -r requirements.txt
```

Then restart Claude Desktop.

---

## OAuth "This app isn't verified" Warning

**What you see:**
![Google Warning Screen]

**This is NORMAL!** Google shows this for apps that aren't published to their store.

**How to proceed:**
1. Click "Advanced" (small text at bottom left)
2. Click "Go to Gmail Calendar (unsafe)"
3. Click "Continue" when asked for permissions

**Is this safe?**
Yes! The app only accesses YOUR Gmail on YOUR computer. Your credentials never leave your machine.

---

## "Wrong Google Account" Issue

**Problem:** You authorized with your personal email but need your work email.

**How to fix:**
```bash
cd ~/gmail-calendar-mcp
rm -rf credentials/token.json
./venv/bin/python setup_oauth.py
```

This will re-open the browser so you can choose the correct Google account.

---

## "Python not found" Error

**What it means:** Your Python installation is missing or not in PATH.

**How to fix:**

**Option 1:** Re-run the install script (it will install Python for you)
```bash
curl -fsSL https://raw.githubusercontent.com/jonathangetonapod/gmail-reply-tracker-mcp/main/local_install.sh | bash -s YOUR_EMAIL
```

**Option 2:** Install Python manually
- Go to https://www.python.org/downloads/
- Download Python 3.11 or higher
- Install it
- Re-run the install script

---

## "Permission denied" Error

**What you see:**
```
Permission denied
```

**How to fix:**
- **DON'T use `sudo`** with the install script
- If you already did, remove the installation and start over:
  ```bash
  rm -rf ~/gmail-calendar-mcp
  ```
- Re-run install WITHOUT sudo

---

## Claude Desktop Doesn't Show MCP Tools

**Checklist:**

1. **Did you restart Claude Desktop?**
   - ⌘Q to quit (not just close window)
   - Reopen Claude Desktop

2. **Check your config file:**
   ```bash
   cat ~/Library/Application\ Support/Claude/claude_desktop_config.json
   ```

   You should see an entry for `gmail-calendar-fathom`. If not, run:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/jonathangetonapod/gmail-reply-tracker-mcp/main/fix_config.py | python3
   ```

3. **Start a NEW conversation**
   - MCP tools only load when you start a new chat
   - Try: "Show me my unreplied emails"

---

## Emails Not Showing Up

**Problem:** Claude says "No unreplied emails" but you know there are some.

**Possible causes:**

1. **Wrong Google Account**
   - Check which account you authorized:
   ```bash
   cd ~/gmail-calendar-mcp
   ./venv/bin/python -c "from auth import GmailAuthManager; print(GmailAuthManager().get_user_email())"
   ```

   If it's the wrong account, delete token and re-auth:
   ```bash
   rm credentials/token.json
   ./venv/bin/python setup_oauth.py
   ```

2. **OAuth Scopes Missing**
   - Make sure you clicked "Allow" for all permissions during OAuth
   - If you clicked "Deny", you need to re-authorize

---

## "Rate limit exceeded" Error

**What it means:** You've hit Gmail's API quota (10,000 requests/day for free tier).

**How to fix:**
- Wait 24 hours for quota to reset
- Or upgrade to a paid Google Workspace account for higher limits

**How to check quota:**
- Visit: https://console.cloud.google.com/apis/dashboard

---

## Network/VPN Issues

**Problem:** OAuth fails with "Connection refused" or "Timeout"

**How to fix:**

1. **Disconnect from VPN temporarily**
   - OAuth uses localhost redirect
   - Some VPNs block localhost connections
   - Disconnect VPN → Complete OAuth → Reconnect VPN

2. **Check firewall settings**
   - Make sure your firewall allows Python to run a local web server
   - Port 8080 needs to be accessible on localhost

---

## "Installation worked yesterday, broken today"

**Common causes:**

1. **macOS updated Python**
   - System Python might have changed
   - **Fix:** Re-run install script to rebuild venv

2. **OAuth token expired**
   - Google tokens expire after 7 days without use
   - **Fix:** Re-run OAuth setup
   ```bash
   cd ~/gmail-calendar-mcp
   ./venv/bin/python setup_oauth.py
   ```

3. **Claude Desktop updated**
   - Updates can sometimes reset configs
   - **Fix:** Run config fix script
   ```bash
   curl -fsSL https://raw.githubusercontent.com/jonathangetonapod/gmail-reply-tracker-mcp/main/fix_config.py | python3
   ```

---

## Still Having Issues?

**Run the health check:**
```bash
curl -fsSL https://raw.githubusercontent.com/jonathangetonapod/gmail-reply-tracker-mcp/main/health_check.sh | bash
```

This will diagnose common problems and suggest fixes.

**Get logs:**
Check Claude Desktop's logs for error messages:
- Open Claude Desktop
- Press `⌘,` (Command-comma) to open Settings
- Click "Developer" tab
- Click "Open Logs Folder"
- Look for errors related to `gmail-calendar-fathom`

**Ask for help:**
- Create an issue: https://github.com/jonathangetonapod/gmail-reply-tracker-mcp/issues
- Include:
  - Your operating system (macOS version)
  - Error messages from Claude Desktop logs
  - Output of health check script
