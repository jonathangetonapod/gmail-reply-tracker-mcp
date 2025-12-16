# OAuth Credentials Directory

This directory contains your OAuth 2.0 credentials for accessing Gmail API.

## Important Files

- **`credentials.json`** - OAuth client credentials from Google Cloud Console (you must download this)
- **`token.json`** - Access token (auto-generated during setup)

**Both files are gitignored and should NEVER be committed to version control.**

## How to Get credentials.json

### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Click "Select a project" > "New Project"
3. Enter project name: `Gmail Reply Tracker` (or any name)
4. Click "Create"

### Step 2: Enable Gmail API

1. In the Google Cloud Console, select your project
2. Go to **APIs & Services** > **Library**
3. Search for "Gmail API"
4. Click on it and click **Enable**

### Step 3: Configure OAuth Consent Screen

1. Go to **APIs & Services** > **OAuth consent screen**
2. Choose user type:
   - **External** if using a personal Gmail account
   - **Internal** if using Google Workspace (organization only)
3. Click "Create"
4. Fill in required information:
   - **App name**: `Gmail Reply Tracker`
   - **User support email**: Your email
   - **Developer contact information**: Your email
5. Click "Save and Continue"
6. On the "Scopes" page:
   - Click "Add or Remove Scopes"
   - Search for "Gmail API"
   - Select: `https://www.googleapis.com/auth/gmail.readonly`
   - Click "Update"
   - Click "Save and Continue"
7. On the "Test users" page:
   - Click "+ Add Users"
   - Enter your Gmail address
   - Click "Add"
   - Click "Save and Continue"
8. Review and click "Back to Dashboard"

### Step 4: Create OAuth 2.0 Credentials

1. Go to **APIs & Services** > **Credentials**
2. Click **+ CREATE CREDENTIALS** at the top
3. Select **OAuth client ID**
4. For "Application type", select: **Desktop app**
5. Name: `Gmail Reply Tracker Client`
6. Click **Create**
7. **IMPORTANT: Configure Redirect URIs**
   - After creating, click on your OAuth client to edit it
   - Under "Authorized redirect URIs", click **+ ADD URI**
   - Add: `http://localhost:8080`
   - Click **+ ADD URI** again
   - Add: `http://localhost:8080/`
   - Click **Save**
   - **Note:** Both URIs (with and without trailing slash) are required for OAuth to work correctly
8. Click **Download JSON** (or the download icon)
9. The file will be named something like `client_secret_xxx.json`

### Step 5: Place the File Here

1. Rename the downloaded file to `credentials.json`
2. Move it to this directory (`credentials/credentials.json`)

**On macOS/Linux:**
```bash
mv ~/Downloads/client_secret_*.json ./credentials/credentials.json
```

**On Windows:**
```cmd
move %USERPROFILE%\Downloads\client_secret_*.json credentials\credentials.json
```

### Step 6: Run OAuth Setup

Once `credentials.json` is in place, run:

```bash
python setup_oauth.py
```

This will:
- Open a browser for authorization
- Generate `token.json` automatically
- Test the connection to Gmail

## File Permissions

For security, token files are created with restricted permissions (600 - owner only).

## Troubleshooting

### OAuth timeout or "Failed to authorize"

If the OAuth flow times out or fails to complete:

**Cause:** Missing or incorrect redirect URIs in Google Cloud Console

**Fix:**
1. Go to [Google Cloud Console Credentials](https://console.cloud.google.com/apis/credentials)
2. Click on your OAuth client ID
3. Under "Authorized redirect URIs", ensure you have:
   - `http://localhost:8080`
   - `http://localhost:8080/`
4. Click **Save**
5. Download the updated `credentials.json` and replace your existing one
6. Delete `token.json` if it exists
7. Run `python setup_oauth.py` again

### "The app is not verified" warning

When authorizing, you may see a warning that the app is not verified. This is normal for apps in development.

**To proceed:**
1. Click "Advanced"
2. Click "Go to Gmail Reply Tracker (unsafe)"
3. Review the permissions
4. Click "Allow"

This is safe because you're only granting access to your own app.

### Token expired or invalid

If you see authentication errors:

1. Delete `token.json`:
   ```bash
   rm credentials/token.json
   ```

2. Re-run the setup:
   ```bash
   python setup_oauth.py
   ```

### Wrong Gmail account

To switch to a different Gmail account:

1. Delete `token.json`
2. Run `python setup_oauth.py`
3. When the browser opens, sign in with the desired account

### Scope changes

If you modify the OAuth scopes in `.env`:

1. Delete `token.json`
2. Run `python setup_oauth.py` to get a new token with updated scopes

## Security Notes

- **Never share** `credentials.json` or `token.json`
- **Never commit** these files to git (they're gitignored)
- **Revoke access** anytime at: https://myaccount.google.com/permissions
- Token file has **read-only** access to Gmail (cannot send/delete emails)

## Need Help?

See the main [README.md](../README.md) for detailed setup instructions and troubleshooting.
