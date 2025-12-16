#!/bin/bash
# Set Railway environment variables

echo "Setting Railway environment variables..."

# Infrastructure variables (always needed)
railway variables --set "TOKEN_ENCRYPTION_KEY=fpAcXAQ8xJxA46Ry90lNrj62IxKIw0PVtTrWadQGeLo="
railway variables --set "SESSION_SECRET=0jKSNLfkTmZLJ_NtRSRCVVpcNxDo_i5V_F2WoOAad0c"
railway variables --set "DATABASE_PATH=./data/users.db"
railway variables --set "PORT=8080"
railway variables --set "GOOGLE_OAUTH_SCOPES=https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar,https://www.googleapis.com/auth/userinfo.email"

echo "✓ Infrastructure variables set"

# Lead Management variables (for Instantly.ai & Bison integrations)
railway variables --set "LEAD_SHEETS_URL=https://docs.google.com/spreadsheets/d/1CNejGg-egkp28ItSRfW7F_CkBXgYevjzstJ1QlrAyAY/edit"
railway variables --set "LEAD_SHEETS_GID_INSTANTLY=928115249"
railway variables --set "LEAD_SHEETS_GID_BISON=1631680229"

echo "✓ Lead management variables set"
echo ""
echo "✅ All environment variables configured!"
echo "Note: Google OAuth credentials are already set in Railway."
echo ""
echo "Ready to deploy! Run: railway up"
