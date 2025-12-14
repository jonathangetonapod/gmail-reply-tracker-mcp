# Complete Beginner's Setup Guide
## For People Who Have Never Coded Before

This guide assumes you know NOTHING about coding, Python, GitHub, or technical stuff. We'll walk through every single step. If you can use a computer and follow instructions, you can do this!

**Time Required:** About 30-45 minutes
**Difficulty:** Easy (just follow the steps!)

---

## Part 1: What Computer Do You Have?

First, figure out what kind of computer you have:
- **Mac** - Has an Apple logo, says "macOS" or "Mac"
- **Windows** - Most other laptops, says "Windows" when you start it

The instructions are slightly different for each. Follow the section for YOUR computer.

---

## Part 2: Install Python (The Language This Runs On)

### For Mac Users:

1. **Check if you already have Python:**
   - Click the magnifying glass 🔍 in the top-right corner of your screen
   - Type: `Terminal`
   - Press Enter (a black or white window will open - don't worry!)
   - Type exactly: `python3 --version`
   - Press Enter
   - If you see something like "Python 3.11" or higher, **SKIP to Part 3**
   - If you see an error, continue below

2. **Install Python:**
   - Open your web browser (Safari, Chrome, etc.)
   - Go to: https://www.python.org/downloads/
   - Click the big yellow button that says "Download Python 3.XX"
   - Wait for the download (it's about 25-30 MB)
   - Find the downloaded file (usually in Downloads folder)
   - Double-click the file (looks like: `python-3.XX.pkg`)
   - Click "Continue" → "Continue" → "Agree" → "Install"
   - Enter your Mac password when asked
   - Click "Close" when done
   - **Close the Terminal window if you had it open**

### For Windows Users:

1. **Check if you already have Python:**
   - Click the Windows Start button (bottom-left corner)
   - Type: `cmd`
   - Press Enter (a black window will open)
   - Type exactly: `python --version`
   - Press Enter
   - If you see "Python 3.11" or higher, **SKIP to Part 3**
   - If you see an error, continue below

2. **Install Python:**
   - Open your web browser
   - Go to: https://www.python.org/downloads/
   - Click the big yellow button "Download Python 3.XX"
   - Wait for download
   - Find the downloaded file (usually in Downloads folder)
   - Double-click the file (looks like: `python-3.XX-amd64.exe`)
   - **IMPORTANT:** Check the box that says "Add Python to PATH" at the bottom
   - Click "Install Now"
   - Wait for it to finish (might take 2-3 minutes)
   - Click "Close"
   - **Close the CMD window if you had it open**

---

## Part 3: Download This Code

You need to get the code onto your computer. Here's the EASIEST way (no Git needed):

1. **Go to GitHub:**
   - Open your web browser
   - Go to: https://github.com/jonathangetonapod/gmail-reply-tracker-mcp

2. **Download the code:**
   - Look for a green button that says **"<> Code"**
   - Click it
   - Click **"Download ZIP"** at the bottom of the menu
   - Wait for the download (it's small, should be quick)

3. **Unzip the file:**
   - Go to your Downloads folder
   - Find the file called `gmail-reply-tracker-mcp-main.zip`
   - **Mac:** Double-click it (it will unzip automatically)
   - **Windows:** Right-click it → "Extract All" → "Extract"

4. **Move it somewhere safe:**
   - Create a folder on your Desktop called "MyMCPServer" (or any name you like)
   - Move the unzipped folder into that new folder
   - **Remember where you put it!**

---

## Part 4: Open Terminal (The Command Line)

This is where you'll type commands. Don't worry, I'll tell you exactly what to type!

### Mac Users:
1. Click the magnifying glass 🔍 (top-right corner)
2. Type: `Terminal`
3. Press Enter
4. A window opens with white or black background
5. **Keep this window open!**

### Windows Users:
1. Click the Start button (bottom-left)
2. Type: `cmd`
3. Press Enter
4. A black window opens
5. **Keep this window open!**

---

## Part 5: Navigate to the Code Folder

Now we need to go to where you saved the code:

1. **In your Terminal/CMD window, type these commands ONE AT A TIME:**

   **Mac Users - Type these exactly:**
   ```bash
   cd Desktop/MyMCPServer/gmail-reply-tracker-mcp-main
   ```
   Press Enter after typing

   **Windows Users - Type these exactly:**
   ```cmd
   cd Desktop\MyMCPServer\gmail-reply-tracker-mcp-main
   ```
   Press Enter after typing

2. **If you get an error:**
   - You might have put the folder somewhere else
   - Try this instead:

   **Mac:**
   ```bash
   cd ~/Downloads/gmail-reply-tracker-mcp-main
   ```

   **Windows:**
   ```cmd
   cd %USERPROFILE%\Downloads\gmail-reply-tracker-mcp-main
   ```

3. **Verify you're in the right place:**
   - Type: `ls` (Mac) or `dir` (Windows)
   - Press Enter
   - You should see files like: `README.md`, `requirements.txt`, `src`
   - If you don't see these, you're in the wrong folder!

---

## Part 6: Install the Required Software Packages

The code needs some extra tools to work. Let's install them:

1. **Mac Users - Type this exactly:**
   ```bash
   python3 -m venv venv
   ```
   Press Enter and wait (might take 30 seconds)

2. **Then type:**
   ```bash
   source venv/bin/activate
   ```
   Press Enter
   - You should now see `(venv)` at the start of your line - this is GOOD!

3. **Then type:**
   ```bash
   pip install -r requirements.txt
   ```
   Press Enter and wait (might take 1-2 minutes, lots of text will scroll by - this is normal!)

---

**Windows Users - Type this exactly:**

1. **Type:**
   ```cmd
   python -m venv venv
   ```
   Press Enter and wait

2. **Then type:**
   ```cmd
   venv\Scripts\activate
   ```
   Press Enter
   - You should see `(venv)` at the start - this is GOOD!

3. **Then type:**
   ```cmd
   pip install -r requirements.txt
   ```
   Press Enter and wait (1-2 minutes)

---

## Part 7: Set Up Google Account Access

This is the trickiest part, but I'll walk you through it step-by-step.

### Step 7.1: Create a Google Cloud Project

1. **Go to Google Cloud Console:**
   - Open your browser
   - Go to: https://console.cloud.google.com
   - Sign in with your Gmail account
   - Accept the terms if asked

2. **Create a New Project:**
   - Look at the top of the page
   - Click where it says "Select a project" or the project name
   - Click **"NEW PROJECT"** (top-right of the popup)
   - Project name: Type `My MCP Server` (or anything you like)
   - Click **"CREATE"**
   - Wait 10-20 seconds for it to create

3. **Make sure you're in your new project:**
   - Click "Select a project" again at the top
   - Click on your new project name
   - You should see your project name at the top now

### Step 7.2: Enable the Gmail and Calendar APIs

1. **Enable Gmail API:**
   - In the left menu, look for **"APIs & Services"**
   - Click **"Library"**
   - In the search box at top, type: `Gmail API`
   - Click on **"Gmail API"** when it appears
   - Click the blue **"ENABLE"** button
   - Wait for it to enable (a few seconds)

2. **Enable Calendar API:**
   - Click the back arrow or go back to Library
   - In the search box, type: `Google Calendar API`
   - Click on **"Google Calendar API"**
   - Click the blue **"ENABLE"** button
   - Wait for it to enable

### Step 7.3: Create OAuth Credentials

1. **Go to Credentials:**
   - In the left menu, click **"Credentials"**
   - Click **"+ CREATE CREDENTIALS"** at the top
   - Click **"OAuth client ID"**

2. **Configure Consent Screen (if asked):**
   - If it says "Configure Consent Screen", click that button
   - Choose **"External"** (unless you have Google Workspace)
   - Click **"CREATE"**

   **Fill out the form:**
   - App name: `My MCP Server`
   - User support email: Choose your email from dropdown
   - Scroll down to Developer contact
   - Developer email: Type your email
   - Click **"SAVE AND CONTINUE"** (bottom)

   **Add Scopes:**
   - Click **"ADD OR REMOVE SCOPES"**
   - In the filter box, type: `gmail`
   - Check these boxes:
     - `https://www.googleapis.com/auth/gmail.modify`
     - `https://www.googleapis.com/auth/gmail.readonly`
   - In the filter box, type: `calendar`
   - Check this box:
     - `https://www.googleapis.com/auth/calendar`
   - Click **"UPDATE"** at bottom
   - Click **"SAVE AND CONTINUE"**

   **Add Test Users:**
   - Click **"+ ADD USERS"**
   - Type your Gmail address
   - Click **"ADD"**
   - Click **"SAVE AND CONTINUE"**
   - Click **"BACK TO DASHBOARD"**

3. **Now create the OAuth client:**
   - Click **"Credentials"** in the left menu again
   - Click **"+ CREATE CREDENTIALS"**
   - Click **"OAuth client ID"**
   - Application type: Choose **"Desktop app"**
   - Name: Type `My MCP Desktop`
   - Click **"CREATE"**
   - A popup appears - click **"DOWNLOAD JSON"**
   - Save the file (it downloads to your Downloads folder)

### Step 7.4: Put the Credentials File in the Right Place

1. **Find the downloaded file:**
   - Go to your Downloads folder
   - Look for a file with a long name like: `client_secret_XXXXX.json`

2. **Rename it:**
   - Right-click the file
   - Choose "Rename"
   - Change the name to exactly: `credentials.json`

3. **Move it to the right folder:**
   - Go back to where you saved the MCP code
   - Example: `Desktop/MyMCPServer/gmail-reply-tracker-mcp-main`
   - Look for a folder called `credentials`
   - **Drag and drop** `credentials.json` into that `credentials` folder

---

## Part 8: Get Your Fathom API Key (Optional)

If you want meeting transcripts and summaries, follow these steps. If you don't use Fathom, skip to Part 9.

1. **Log into Fathom:**
   - Go to: https://fathom.video
   - Sign in to your account

2. **Go to Settings:**
   - Click your profile picture or icon (top-right)
   - Click **"Settings"**

3. **Find API section:**
   - Look for **"API"** or **"Integrations"** in the settings menu
   - Click it

4. **Generate API Key:**
   - Click **"Generate API Key"** or **"Create New Key"**
   - Copy the key (it's a long string of letters and numbers)
   - **SAVE THIS SOMEWHERE SAFE** - you'll need it in the next step!

---

## Part 9: Create Configuration File

Now we need to tell the code where to find everything:

1. **Go back to your Terminal/CMD window**
   - Make sure you're still in the project folder
   - You should still see `(venv)` at the start of the line

2. **Mac Users - Type these commands:**
   ```bash
   touch .env
   open -e .env
   ```
   This opens a text editor

3. **Windows Users - Type this:**
   ```cmd
   notepad .env
   ```
   If it asks "Create new file?", click Yes

4. **Copy and paste this into the text editor:**
   ```
   # Gmail & Calendar Settings
   GMAIL_CREDENTIALS_PATH=./credentials/credentials.json
   GMAIL_TOKEN_PATH=./credentials/token.json
   GMAIL_OAUTH_SCOPES=https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar

   # Server Settings
   MCP_SERVER_NAME=gmail-calendar-fathom
   LOG_LEVEL=INFO
   GMAIL_API_MAX_REQUESTS_PER_MINUTE=60

   # Fathom API Key (paste your key after the = sign)
   FATHOM_API_KEY=YOUR_FATHOM_KEY_HERE
   ```

5. **If you have a Fathom API key:**
   - Find the line that says `FATHOM_API_KEY=YOUR_FATHOM_KEY_HERE`
   - Replace `YOUR_FATHOM_KEY_HERE` with your actual key
   - Example: `FATHOM_API_KEY=abc123xyz789...`

6. **Save the file:**
   - **Mac:** Press Command+S, then close the window
   - **Windows:** Click File → Save, then close Notepad

---

## Part 10: Test the Setup

Let's make sure everything works:

1. **In your Terminal/CMD (should still have `(venv)`):**
   ```bash
   python setup_oauth.py
   ```
   Press Enter

2. **What happens next:**
   - A web browser window will open automatically
   - Google will ask you to sign in (if not already)
   - It will say "Google hasn't verified this app" - **THIS IS NORMAL!**

3. **Click "Advanced"** (at the bottom left)

4. **Click "Go to My MCP Server (unsafe)"**
   - Don't worry, this is YOUR app, it's safe!
   - Google just shows this warning for unverified apps

5. **Click "Continue" or "Allow"** on each screen
   - It will ask for Gmail permissions - click "Continue"
   - It will ask for Calendar permissions - click "Continue"

6. **Success message:**
   - You should see "Authentication successful!" in your browser
   - Your Terminal/CMD should show "Successfully connected to Gmail!"
   - If you see this, YOU'RE DONE with the hard part! 🎉

7. **If something went wrong:**
   - Make sure the `credentials.json` file is in the `credentials` folder
   - Make sure you enabled the Gmail API and Calendar API in Google Cloud
   - Make sure you added your email as a test user
   - Try running `python setup_oauth.py` again

---

## Part 11: Install Claude Desktop

1. **Download Claude Desktop:**
   - Go to: https://claude.ai/download
   - Click the download button for your computer (Mac or Windows)
   - Install it like any other app

2. **Open Claude Desktop for the first time:**
   - Sign in with your account
   - Close it after signing in

---

## Part 12: Connect Everything to Claude

This is the final step!

### Mac Users:

1. **Open Finder**
2. **Press these keys together:** Command + Shift + G
3. **Type exactly:**
   ```
   ~/Library/Application Support/Claude/
   ```
4. **Press Enter**
5. **Look for a file called:** `claude_desktop_config.json`
6. **Right-click it and choose "Open With" → "TextEdit"**

### Windows Users:

1. **Press Windows key + R** (opens "Run" dialog)
2. **Type exactly:**
   ```
   %APPDATA%\Claude\
   ```
3. **Press Enter**
4. **Look for a file called:** `claude_desktop_config.json`
5. **Right-click it and choose "Open with" → "Notepad"**

---

### Edit the Configuration File:

**IMPORTANT:** You need to change the paths below to match WHERE YOU SAVED THE CODE!

1. **If the file is empty, paste this:**
   ```json
   {
     "mcpServers": {
     }
   }
   ```

2. **Add this inside the `mcpServers` section:**
   ```json
   {
     "mcpServers": {
       "gmail-calendar-fathom": {
         "command": "python",
         "args": [
           "/FULL/PATH/TO/YOUR/gmail-reply-tracker-mcp-main/src/server.py"
         ],
         "env": {
           "GMAIL_CREDENTIALS_PATH": "/FULL/PATH/TO/YOUR/gmail-reply-tracker-mcp-main/credentials/credentials.json",
           "GMAIL_TOKEN_PATH": "/FULL/PATH/TO/YOUR/gmail-reply-tracker-mcp-main/credentials/token.json",
           "GMAIL_OAUTH_SCOPES": "https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar",
           "FATHOM_API_KEY": "YOUR_FATHOM_KEY_IF_YOU_HAVE_ONE"
         }
       }
     }
   }
   ```

3. **CRITICAL: Replace the paths!**

   **Mac Example:**
   ```json
   "/Users/yourname/Desktop/MyMCPServer/gmail-reply-tracker-mcp-main/src/server.py"
   ```

   **Windows Example:**
   ```json
   "C:\\Users\\YourName\\Desktop\\MyMCPServer\\gmail-reply-tracker-mcp-main\\src\\server.py"
   ```

   **Note for Windows:** Use `\\` (two backslashes) instead of `\` (one)

4. **How to find your full path:**

   **Mac:**
   - Open Terminal
   - Type: `cd ~/Desktop/MyMCPServer/gmail-reply-tracker-mcp-main`
   - Then type: `pwd`
   - Copy the path it shows
   - Use that path and add `/src/server.py` or `/credentials/credentials.json` at the end

   **Windows:**
   - Open File Explorer
   - Go to where you saved the code
   - Click in the address bar at the top
   - Copy the path
   - Replace `\` with `\\` in the config file

5. **Save the file and close it**

---

## Part 13: Start Using It!

1. **Quit Claude Desktop completely** (don't just close the window)
   - **Mac:** Right-click Claude icon in dock → Quit
   - **Windows:** Right-click Claude in taskbar → Close

2. **Open Claude Desktop again**

3. **Start a new chat**

4. **Try asking Claude:**
   ```
   What emails do I need to reply to?
   ```

   Or:
   ```
   What's on my calendar this week?
   ```

   Or:
   ```
   List my recent Fathom meetings
   ```

5. **If it works, you'll see Claude using tools to check your emails!** 🎉

---

## Troubleshooting

### "I don't see the tools working"
- Make sure you quit and reopened Claude Desktop
- Check that your paths in the config file are correct
- Try restarting your computer

### "Authentication failed"
- Run `python setup_oauth.py` again
- Make sure you allowed all the permissions

### "Can't find python command"
- **Mac:** Try using `python3` instead of `python`
- **Windows:** Make sure you checked "Add Python to PATH" when installing

### "Still stuck?"
Check out these resources:
- Google Cloud Console: https://console.cloud.google.com
- Python Download: https://www.python.org/downloads/
- Claude Desktop: https://claude.ai/download

---

## What You Can Do Now

Ask Claude things like:
- "What emails haven't I replied to?"
- "Schedule a meeting with john@email.com tomorrow at 2pm"
- "Show me my calendar for next week"
- "Get the transcript from my meeting yesterday"
- "What action items came out of my last meeting?"
- "Send an email to sarah@email.com about the project update"

Have fun! 🚀
