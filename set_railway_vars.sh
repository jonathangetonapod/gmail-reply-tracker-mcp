#!/bin/bash
# Set Railway environment variables

echo "Setting Railway environment variables..."

# Infrastructure variables (always needed)
railway variables set TOKEN_ENCRYPTION_KEY="fpAcXAQ8xJxA46Ry90lNrj62IxKIw0PVtTrWadQGeLo="
railway variables set SESSION_SECRET="0jKSNLfkTmZLJ_NtRSRCVVpcNxDo_i5V_F2WoOAad0c"
railway variables set DATABASE_PATH="./data/users.db"
railway variables set PORT="8080"
railway variables set GOOGLE_OAUTH_SCOPES="https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar,https://www.googleapis.com/auth/userinfo.email"

echo "✓ Infrastructure variables set"
echo ""
echo "Now you need to set Google OAuth credentials:"
echo "1. Get your Railway app URL: railway domain"
echo "2. Go to Google Cloud Console and get OAuth credentials"
echo "3. Run these commands with your actual values:"
echo ""
echo "railway variables set GOOGLE_CLIENT_ID='your-client-id.apps.googleusercontent.com'"
echo "railway variables set GOOGLE_CLIENT_SECRET='your-client-secret'"
echo "railway variables set GOOGLE_REDIRECT_URI='https://YOUR-APP-URL.railway.app/auth/callback'"
echo ""
echo "After setting those, run: railway up"
