# MacBook Setup Guide - Super Simple!
## Get Your AI Email & Calendar Assistant Running in 30 Minutes

**You need:** A MacBook (any recent one works), internet, and a Gmail account.

**What you'll get:** Ask Claude to check your emails, schedule meetings, and read meeting transcripts - all in plain English!

---

## Step 1: Install Python (5 minutes)

Python is the language this runs on. Your Mac might already have it!

1. **Open Spotlight Search:**
   - Click the magnifying glass 🔍 in the top-right corner
   - OR press `Command + Space`

2. **Type:** `Terminal`

3. **Press Enter**
   - A window opens (white or black background with text)
   - This is your "Terminal" - don't worry, it's easy!

4. **Check if you have Python:**
   - Type this exactly: `python3 --version`
   - Press Enter
   - If you see "Python 3.11" or "Python 3.12" → **Skip to Step 2!** ✅
   - If you see an error → Keep reading

5. **Install Python:**
   - Open Safari (or any browser)
   - Go to: **https://www.python.org/downloads/**
   - Click the big yellow button: **"Download Python 3.XX"**
   - Wait for download (about 30 MB, takes 30 seconds)
   - Go to your Downloads folder
   - Find the file: `python-3.XX.pkg`
   - Double-click it
   - Click: **Continue** → **Continue** → **Agree** → **Install**
   - Enter your Mac password
   - Click **Close** when done
   - Close and reopen Terminal

---

## Step 2: Download the Code (2 minutes)

1. **Open your browser**
2. **Go to:** https://github.com/jonathangetonapod/gmail-reply-tracker-mcp
3. **Click the green button** that says **"<> Code"**
4. **Click "Download ZIP"** at the bottom
5. **Wait for download** (it's small, quick!)
6. **Find the file** in your Downloads folder: `gmail-reply-tracker-mcp-main.zip`
7. **Double-click it** to unzip
8. **Drag the unzipped folder** to your Desktop
   - The folder is called: `gmail-reply-tracker-mcp-main`

---

## Step 3: Set Everything Up (5 minutes)

1. **Go back to Terminal** (the window you opened before)

2. **Type this command** (copies it exactly):
   ```bash
   cd ~/Desktop/gmail-reply-tracker-mcp-main
   ```
   Press Enter

3. **Create a virtual environment** (isolates this project):
   ```bash
   python3 -m venv venv
   ```
   Press Enter and wait (30 seconds)

4. **Activate it:**
   ```bash
   source venv/bin/activate
   ```
   Press Enter

   ✅ You should now see `(venv)` at the start of your line - that's good!

5. **Install all the required packages:**
   ```bash
   pip install -r requirements.txt
   ```
   Press Enter and wait (1-2 minutes, you'll see lots of text - this is normal!)

---

## Step 4: Set Up Google Access (10 minutes)

This is the most detailed part, but just follow along!

### Create a Google Cloud Project:

1. **Open your browser**
2. **Go to:** https://console.cloud.google.com
3. **Sign in** with your Gmail
4. **Accept terms** if asked
5. **Click** where it says "Select a project" (top-left area)
6. **Click "NEW PROJECT"** (top-right corner)
7. **Name your project:** `My Email Assistant` (or anything)
8. **Click "CREATE"**
9. **Wait 10 seconds** for it to create

### Enable the APIs (Gmail and Calendar):

1. **Make sure you're in your new project:**
   - Click "Select a project" at the top
   - Click on "My Email Assistant"
   - You should see your project name at the top now ✅

2. **On the left side**, find the hamburger menu (☰ three lines)
3. **Click:** APIs & Services → **Library**

4. **Enable Gmail API:**
   - In the search box, type: `Gmail API`
   - Click on **"Gmail API"**
   - Click the blue **"ENABLE"** button
   - Wait a few seconds

5. **Enable Calendar API:**
   - Click the back arrow ← (top-left)
   - In the search box, type: `Google Calendar API`
   - Click on **"Google Calendar API"**
   - Click the blue **"ENABLE"** button

### Set Up OAuth (Authentication):

1. **Click "Credentials"** in the left menu
2. **Click "+ CREATE CREDENTIALS"** at the top
3. **Click "OAuth client ID"**

4. **If it says "Configure Consent Screen":**
   - Click that blue button
   - Choose **"External"**
   - Click **"CREATE"**

5. **Fill out the consent screen:**
   - **App name:** `My Email Assistant`
   - **User support email:** Pick your email from dropdown
   - Scroll down
   - **Developer email:** Type your email
   - Click **"SAVE AND CONTINUE"**

6. **Add Scopes:**
   - Click **"ADD OR REMOVE SCOPES"**
   - In the search/filter box, type: `gmail`
   - Check these two boxes:
     - ☑ `.../auth/gmail.modify`
     - ☑ `.../auth/gmail.readonly`
   - Clear the search box, type: `calendar`
   - Check this box:
     - ☑ `.../auth/calendar`
   - Click **"UPDATE"** at the bottom
   - Click **"SAVE AND CONTINUE"**

7. **Add yourself as a test user:**
   - Click **"+ ADD USERS"**
   - Type your Gmail address
   - Click **"ADD"**
   - Click **"SAVE AND CONTINUE"**
   - Click **"BACK TO DASHBOARD"**

8. **Create the OAuth credentials:**
   - Click **"Credentials"** in left menu again
   - Click **"+ CREATE CREDENTIALS"**
   - Click **"OAuth client ID"**
   - Application type: Choose **"Desktop app"**
   - Name: `My Mac App`
   - Click **"CREATE"**
   - A popup appears - click **"DOWNLOAD JSON"**
   - The file downloads to your Downloads folder

### Put the credentials in the right place:

1. **Go to your Downloads folder**
2. **Find the file** that starts with `client_secret_` (long name)
3. **Right-click the file** → **Rename**
4. **Change the name to:** `credentials.json` (exactly)
5. **Go to Desktop** → **gmail-reply-tracker-mcp-main** → **credentials** folder
6. **Drag `credentials.json`** into that credentials folder

---

## Step 5: Get Fathom API Key (Optional - 2 minutes)

**Skip this if you don't use Fathom for meeting recordings!**

1. Go to: **https://fathom.video**
2. Sign in
3. Click your profile picture (top-right)
4. Click **Settings**
5. Find **API** section
6. Click **Generate API Key**
7. **COPY the key** (long string of letters/numbers)
8. **Paste it somewhere safe** for the next step

---

## Step 6: Create Configuration File (2 minutes)

1. **Go back to your Terminal** (should still show `(venv)`)

2. **Type this:**
   ```bash
   touch .env
   open -e .env
   ```
   Press Enter - TextEdit opens

3. **Copy and paste this into TextEdit:**
   ```
   # Gmail & Calendar
   GMAIL_CREDENTIALS_PATH=./credentials/credentials.json
   GMAIL_TOKEN_PATH=./credentials/token.json
   GMAIL_OAUTH_SCOPES=https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar

   # Server Settings
   MCP_SERVER_NAME=gmail-calendar-fathom
   LOG_LEVEL=INFO
   GMAIL_API_MAX_REQUESTS_PER_MINUTE=60

   # Fathom API Key (optional - paste your key after the = sign)
   FATHOM_API_KEY=
   ```

4. **If you have a Fathom API key:**
   - Find the last line: `FATHOM_API_KEY=`
   - Paste your key after the `=` sign
   - Example: `FATHOM_API_KEY=LKI3vLL...`
   - If you don't have Fathom, just leave it blank

5. **Save and close:**
   - Press `Command + S`
   - Close the TextEdit window

---

## Step 7: Test Everything Works (2 minutes)

1. **In Terminal** (with `(venv)` showing):
   ```bash
   python3 setup_oauth.py
   ```
   Press Enter

2. **A browser window opens automatically**
   - You'll see Google sign-in
   - It will say **"Google hasn't verified this app"** → This is NORMAL!

3. **Click "Advanced"** (bottom-left)

4. **Click "Go to My Email Assistant (unsafe)"**
   - It's actually safe! It's YOUR app
   - Google just warns about unverified apps

5. **Click "Continue"** for each permission screen:
   - Gmail access → Continue
   - Calendar access → Continue

6. **Success!**
   - Browser says: "Authentication successful!"
   - Terminal says: "Successfully connected to Gmail!"
   - You should see: "✓ Gmail connection working!"

   **If this worked → You're almost done!** 🎉

---

## Step 8: Install Claude Desktop (2 minutes)

1. **Go to:** https://claude.ai/download
2. **Click "Download for Mac"**
3. **Open the downloaded file** (from Downloads)
4. **Drag Claude to Applications** folder
5. **Open Claude Desktop** from Applications
6. **Sign in** with your Claude account
7. **Close Claude** after signing in

---

## Step 9: Connect to Claude (5 minutes)

Almost done! This is the last step!

1. **Open Finder**

2. **Press these keys together:** `Command + Shift + G`

3. **A box appears - type this exactly:**
   ```
   ~/Library/Application Support/Claude/
   ```

4. **Press Enter**

5. **Look for a file:** `claude_desktop_config.json`
   - If you don't see it, create it:
     - Right-click in the folder
     - New → Text File
     - Name it: `claude_desktop_config.json`

6. **Right-click the file** → **Open With** → **TextEdit**

7. **If the file is empty, paste this:**
   ```json
   {
     "mcpServers": {
     }
   }
   ```

8. **Replace everything with this** (or add inside the `mcpServers` section):
   ```json
   {
     "mcpServers": {
       "gmail-calendar-fathom": {
         "command": "python3",
         "args": [
           "/Users/YOUR_USERNAME/Desktop/gmail-reply-tracker-mcp-main/src/server.py"
         ],
         "env": {
           "GMAIL_CREDENTIALS_PATH": "/Users/YOUR_USERNAME/Desktop/gmail-reply-tracker-mcp-main/credentials/credentials.json",
           "GMAIL_TOKEN_PATH": "/Users/YOUR_USERNAME/Desktop/gmail-reply-tracker-mcp-main/credentials/token.json",
           "GMAIL_OAUTH_SCOPES": "https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar",
           "FATHOM_API_KEY": "YOUR_FATHOM_KEY_IF_YOU_HAVE_ONE"
         }
       }
     }
   }
   ```

9. **IMPORTANT - Replace `YOUR_USERNAME`:**
   - Go back to Terminal
   - Type: `whoami`
   - Press Enter
   - It shows your username (like: `john` or `sarah`)
   - Replace `YOUR_USERNAME` in the config with that name

   **Example:** If `whoami` shows `john`, then use:
   ```
   /Users/john/Desktop/gmail-reply-tracker-mcp-main/src/server.py
   ```

10. **If you have a Fathom key:**
    - Replace `YOUR_FATHOM_KEY_IF_YOU_HAVE_ONE` with your actual key
    - Or just delete that line if you don't use Fathom

11. **Save and close:** `Command + S`, then close TextEdit

---

## Step 10: START USING IT! 🚀

1. **Quit Claude Desktop completely:**
   - Right-click the Claude icon in your Dock
   - Click **Quit**

2. **Open Claude Desktop again** from Applications

3. **Start a new chat**

4. **Try asking:**
   ```
   What emails do I need to reply to?
   ```

   Or:
   ```
   What's on my calendar today?
   ```

   Or:
   ```
   Schedule a meeting with john@email.com tomorrow at 2pm
   ```

5. **You should see Claude using tools!**
   - It will show little tool icons
   - It will check your Gmail and Calendar
   - It will give you answers!

**If it works: CONGRATULATIONS! You did it!** 🎉

---

## Quick Troubleshooting

### "Claude doesn't see my tools"
- Make sure you QUIT Claude (not just closed the window)
- Check that your username is correct in the config file
- Restart your Mac and try again

### "Authentication error"
- Go back to Terminal
- Type: `cd ~/Desktop/gmail-reply-tracker-mcp-main`
- Then: `source venv/bin/activate`
- Then: `python3 setup_oauth.py`
- Allow all permissions again

### "Permission denied"
- The credentials.json file might be in the wrong place
- Make sure it's in: `Desktop/gmail-reply-tracker-mcp-main/credentials/credentials.json`

### "Python not found"
- Use `python3` instead of `python` in all commands
- If still doesn't work, reinstall Python from python.org

---

## What Can You Ask Claude Now?

**Email stuff:**
- "What emails haven't I replied to?"
- "Show me emails from john@company.com"
- "Send an email to sarah@email.com saying I'll be late"
- "Draft a reply to this email thread"

**Calendar stuff:**
- "What's on my calendar this week?"
- "Schedule a meeting with alex@email.com Friday at 3pm"
- "Show me all my meetings from last week"
- "Cancel my 2pm meeting"

**Meeting transcripts (if you have Fathom):**
- "List my recent meetings"
- "Get the transcript from yesterday's client call"
- "What action items came from my meeting with the team?"
- "Summarize the Project Phoenix meeting"

**Cross-platform:**
- "What's the status of the marketing project? Check emails and calendar"
- "Find all action items from this week"
- "Who have I been meeting with most?"

---

## Need Help?

- **Python download:** https://www.python.org/downloads/
- **Google Cloud:** https://console.cloud.google.com
- **Claude Desktop:** https://claude.ai/download
- **Fathom API:** https://fathom.video (Settings → API)

**You got this!** Just follow each step carefully and you'll have your AI assistant working in no time! 🚀
