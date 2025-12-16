# Gmail MCP Server - Simple Team Setup

## For Team Members (5 minutes)

### Step 1: Authorize Your Account
Visit: **https://mcp-gmail-multi-tenant-production.up.railway.app/setup**

1. Click "Authorize with Google"
2. Log in with your work email
3. Optionally add your Fathom API key (if you have one)
4. Follow the 3 steps shown on the success page

### Step 2: What You'll Be Able to Do

Once set up, you can ask Claude Desktop to:

- **"Show me my unreplied emails from the last 3 days"**
- **"List my calendar events for next week"**
- **"Search my emails for messages about [topic]"**
- **"Send an email to [person] about [subject]"**
- **"Create a meeting for tomorrow at 2pm with [person]"**
- **"Reply to the email from [person]"**
- **"Get the transcript from my last Fathom meeting"** *(if configured)*

### Need Help?

Contact your team admin if you have any issues during setup.

---

## For Team Admins

### Quick Deploy Instructions

The server is already deployed at:
**https://mcp-gmail-multi-tenant-production.up.railway.app**

Team members just need to:
1. Visit `/setup` endpoint
2. Authorize with Google
3. Download the client file
4. Copy the config into Claude Desktop
5. Restart Claude

### Updates

When you push changes to the main branch, Railway automatically:
- Rebuilds the server
- Deploys the update
- All team members get the update automatically (no reconfiguration needed!)

### Security

- Each user's credentials are encrypted in the database
- OAuth tokens are refreshed automatically
- Session tokens are used for API authentication
- Credentials never leave the Railway server
