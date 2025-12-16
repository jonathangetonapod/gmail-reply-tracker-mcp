# 🚀 Deploy to Railway - Step by Step

Follow these steps to deploy your multi-tenant MCP server to Railway.

---

## ✅ Pre-Deployment Checklist

- [x] Database schema created (`src/database.py`)
- [x] Web server created (`src/web_server.py`)
- [x] Entry point created (`src/web_server_main.py`)
- [x] Railway config created (`railway.toml`, `Procfile`)
- [x] Dependencies updated (`requirements.txt`)
- [x] Encryption key generated

---

## 📋 Step 1: Set Up Google Cloud Project (15 minutes)

### 1.1 Create Project

1. Go to: https://console.cloud.google.com
2. Click "Select a project" → "New Project"
3. **Project name:** `yourcompany-mcp-server`
4. Click "Create"

### 1.2 Enable APIs

1. In left sidebar → "APIs & Services" → "Enable APIs and Services"
2. Search and enable:
   - **Gmail API**
   - **Google Calendar API**
   - **People API** (for user profile info)

### 1.3 Configure OAuth Consent Screen

1. Left sidebar → "OAuth consent screen"
2. **User Type:** External
3. Click "Create"

**App Information:**
- **App name:** `YourCompany MCP Integration`
- **User support email:** your-email@company.com
- **Developer contact:** your-email@company.com

**Scopes:** (Click "Add or Remove Scopes")
- `https://www.googleapis.com/auth/gmail.modify`
- `https://www.googleapis.com/auth/calendar`
- `https://www.googleapis.com/auth/userinfo.email`

**Test Users:** (For now, add your team's emails or leave empty for internal testing)

**Publishing Status:**
- Leave in "Testing" mode for now (up to 100 users)
- Can publish to Production later (unlimited users, requires Google verification)

### 1.4 Create OAuth Credentials

1. Left sidebar → "Credentials"
2. Click "+ CREATE CREDENTIALS" → "OAuth client ID"
3. **Application type:** Web application
4. **Name:** `MCP Server OAuth`

**Authorized redirect URIs:**
- `http://localhost:8080/auth/callback` (for local testing)
- `https://YOUR-APP-NAME.railway.app/auth/callback` (replace YOUR-APP-NAME with your Railway app name)

5. Click "Create"
6. **SAVE THESE:**
   - Client ID (looks like: `123456789-abc123.apps.googleusercontent.com`)
   - Client Secret (looks like: `GOCSPX-abc123xyz...`)

---

## 📋 Step 2: Deploy to Railway (10 minutes)

### 2.1 Connect Railway to GitHub

1. Go to: https://railway.app
2. Sign in with GitHub
3. Click "New Project"
4. Click "Deploy from GitHub repo"
5. Select your repository: `MCP_Gmail`
6. Railway will automatically detect the `railway.toml` and `Procfile`

### 2.2 Set Environment Variables

In Railway dashboard, go to **Variables** tab and add:

```bash
# Copy these exactly (replace values with your actual credentials)

GOOGLE_CLIENT_ID=your-client-id-from-step-1.4.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret-from-step-1.4
GOOGLE_REDIRECT_URI=https://YOUR-APP-NAME.railway.app/auth/callback
GOOGLE_OAUTH_SCOPES=https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar,https://www.googleapis.com/auth/userinfo.email
TOKEN_ENCRYPTION_KEY=fpAcXAQ8xJxA46Ry90lNrj62IxKIw0PVtTrWadQGeLo=
DATABASE_PATH=./data/users.db
PORT=8080
SESSION_SECRET=your-random-secret-here-generate-one
```

**To generate SESSION_SECRET:**
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2.3 Get Your Railway App URL

1. In Railway dashboard, go to **Settings** tab
2. Under "Domains", you'll see your app URL: `https://YOUR-APP-NAME.railway.app`
3. **IMPORTANT:** Go back to Google Cloud Console (Step 1.4) and update the redirect URI with your actual Railway URL

---

## 📋 Step 3: Deploy and Test (5 minutes)

### 3.1 Push to GitHub (Railway Auto-Deploys)

```bash
cd /Users/jonathangarces/Desktop/MCP_Gmail

# Make sure everything is committed
git add .
git commit -m "Add multi-tenant MCP server foundation"
git push origin main
```

Railway will automatically:
- Detect the push
- Build the container
- Install dependencies from `requirements.txt`
- Start the web server (`python src/web_server_main.py`)
- Provide HTTPS endpoint

### 3.2 Watch Deployment

1. In Railway dashboard → "Deployments" tab
2. Watch the build logs
3. Wait for status: "Success" (green checkmark)

### 3.3 Test Health Endpoint

```bash
# Replace YOUR-APP-NAME with your actual Railway app name
curl https://YOUR-APP-NAME.railway.app/health
```

**Expected response:**
```json
{"status": "healthy", "timestamp": "2024-12-15T..."}
```

✅ If you see this, **YOUR SERVER IS LIVE!**

---

## 📋 Step 4: Test Locally First (Optional but Recommended)

Before deploying, test locally:

### 4.1 Create .env File

```bash
cd /Users/jonathangarces/Desktop/MCP_Gmail
cp .env.example .env
```

Edit `.env` with your actual values:
```bash
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8080/auth/callback
GOOGLE_OAUTH_SCOPES=https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar,https://www.googleapis.com/auth/userinfo.email
TOKEN_ENCRYPTION_KEY=fpAcXAQ8xJxA46Ry90lNrj62IxKIw0PVtTrWadQGeLo=
DATABASE_PATH=./data/users.db
PORT=8080
SESSION_SECRET=test-secret-123
```

### 4.2 Install Dependencies

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### 4.3 Run Server Locally

```bash
python src/web_server_main.py
```

**Expected output:**
```
Starting MCP Web Server...
Database path: ./data/users.db
Database initialized successfully
Web server initialized successfully
Starting server on port 8080...
 * Running on http://0.0.0.0:8080
```

### 4.4 Test Locally

Open browser:
- http://localhost:8080/ → Should see homepage
- http://localhost:8080/health → Should see health check
- http://localhost:8080/setup → Should redirect to Google sign-in

---

## 🎉 Success Criteria

After deployment, you should have:

✅ **Railway app running**
- https://YOUR-APP-NAME.railway.app/health returns JSON

✅ **Google OAuth configured**
- OAuth consent screen created
- Credentials created
- Redirect URI matches Railway URL

✅ **Environment variables set**
- All required variables in Railway dashboard
- Encryption key saved securely

---

## 🔍 Troubleshooting

### "Module not found" error in Railway logs

**Check:**
- `requirements.txt` is committed to git
- Railway detected Python project (check build logs)

**Fix:**
```bash
git add requirements.txt
git commit -m "Update dependencies"
git push origin main
```

### "Missing required environment variables"

**Check Railway dashboard → Variables tab:**
- GOOGLE_CLIENT_ID set?
- GOOGLE_CLIENT_SECRET set?
- TOKEN_ENCRYPTION_KEY set?

### "OAuth redirect_uri_mismatch"

**Check Google Cloud Console:**
- Go to Credentials → Your OAuth Client
- Authorized redirect URIs includes: `https://YOUR-APP-NAME.railway.app/auth/callback`
- URL exactly matches (no trailing slash, correct subdomain)

### Health endpoint returns 404

**Check Railway logs:**
```bash
railway logs
```

Look for:
- "Starting MCP Web Server..."
- "Server started on port 8080"
- Any errors?

---

## 📊 What You Have Now

After completing these steps:

1. **Web server running on Railway** ✓
   - Health check working
   - Database initialized
   - OAuth flow ready (partial)

2. **Foundation for multi-tenancy** ✓
   - User database with encryption
   - Session management
   - Per-user credential storage

3. **Ready for next steps:**
   - Complete OAuth callback
   - Build setup script
   - Add MCP endpoint

---

## 🔜 Next Steps (After Deployment)

Once your server is live and healthy, we'll:

1. **Complete OAuth Flow**
   - Finish `/auth/callback` to save credentials
   - Test full sign-in flow

2. **Build Setup Script**
   - `install.sh` for team members
   - Auto-configure Claude Desktop

3. **Add MCP Endpoint**
   - Multi-tenant wrapper
   - Session token authentication
   - Route to user credentials

---

## 💾 Save These Securely

**From Google Cloud Console:**
- Client ID: `_____________________`
- Client Secret: `_____________________`

**Generated Keys:**
- Encryption Key: `fpAcXAQ8xJxA46Ry90lNrj62IxKIw0PVtTrWadQGeLo=`
- Session Secret: `_____________________`

**Railway Info:**
- App URL: `https://_____.railway.app`
- Project ID: `_____________________`

---

## ✅ Ready to Deploy?

Run through the checklist:
- [ ] Google Cloud project created
- [ ] OAuth credentials obtained
- [ ] Railway account ready
- [ ] GitHub repo connected to Railway
- [ ] Environment variables prepared
- [ ] Ready to push code

**Let's do this! Follow the steps above.**

When you're done, test:
```bash
curl https://YOUR-APP-NAME.railway.app/health
```

**If you see `{"status": "healthy"}` → SUCCESS! 🎉**

Then we'll continue with the OAuth flow completion.
