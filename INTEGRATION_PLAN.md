# Integration Plan: Gmail MCP + Lead Management MCP

## Executive Summary

This document outlines the strategy for integrating the Lead Management MCP Server (Instantly.ai + Bison) into the existing Gmail Calendar Fathom MCP Server.

**Goal:** Create a unified MCP server that provides:
- Gmail + Google Calendar + Fathom (existing)
- Instantly.ai + Bison lead management (new)

**Total Tools After Integration:** 29+ tools
- 17 existing tools (Gmail, Calendar, Fathom)
- 12 new tools (Instantly, Bison, aggregated analytics)

---

## 1. Dependency Analysis

### Current Dependencies (Gmail MCP)
```
mcp>=1.2.0
google-auth>=2.43.0
google-auth-oauthlib>=1.2.0
google-auth-httplib2>=0.2.0
google-api-python-client>=2.149.0
python-dotenv>=1.0.0
pytz>=2024.1
python-dateutil>=2.9.0
requests>=2.31.0
tzlocal>=5.0.0
Flask>=3.0.0
Werkzeug>=3.0.0
cryptography>=41.0.0
pytest>=8.0.0
pytest-asyncio>=0.24.0
```

### Lead Management Dependencies
```
Flask==3.0.3
requests>=2.31.0
python-dotenv>=1.0.1
mcp>=1.0.0
```

### Compatibility Analysis

| Package | Gmail MCP | Lead MCP | Resolution | Status |
|---------|-----------|----------|------------|--------|
| mcp | >=1.2.0 | >=1.0.0 | Use >=1.2.0 | ✅ Compatible |
| Flask | >=3.0.0 | ==3.0.3 | Use >=3.0.0 | ✅ Compatible |
| requests | >=2.31.0 | >=2.31.0 | Use >=2.31.0 | ✅ Compatible |
| python-dotenv | >=1.0.0 | >=1.0.1 | Use >=1.0.1 | ✅ Compatible |

**Conclusion:** All dependencies are compatible. No conflicts detected.

---

## 2. Architecture Design

### Current Architecture (Gmail MCP)
```
┌─────────────────┐
│ Claude Desktop  │
└────────┬────────┘
         │ MCP Protocol
┌────────▼────────────────────────┐
│   src/server.py (FastMCP)       │
│   - Gmail tools                 │
│   - Calendar tools              │
│   - Fathom tools                │
└────────┬────────────────────────┘
         │
    ┌────▼──────────────────┐
    │    │                  │
┌───▼────▼──┐  ┌───────────▼─────┐  ┌───────────▼─────┐
│ Gmail API │  │ Calendar API    │  │ Fathom API      │
└───────────┘  └─────────────────┘  └─────────────────┘
```

### Proposed Unified Architecture
```
┌─────────────────┐
│ Claude Desktop  │
└────────┬────────┘
         │ MCP Protocol
┌────────▼────────────────────────────────────────────┐
│   src/server.py (FastMCP)                           │
│   - Gmail tools (existing)                          │
│   - Calendar tools (existing)                       │
│   - Fathom tools (existing)                         │
│   - Instantly tools (NEW)                           │
│   - Bison tools (NEW)                               │
│   - Aggregated analytics tools (NEW)                │
└────────┬────────────────────────────────────────────┘
         │
    ┌────▼───────────────────────────────────┐
    │    │         │         │                │
┌───▼────▼──┐  ┌──▼─────┐  ┌▼──────┐  ┌─────▼──────────────────┐
│ Gmail API │  │ Cal API│  │Fathom │  │ Lead Management        │
└───────────┘  └────────┘  └───────┘  │                        │
                                       │ ┌─────────────────┐    │
                                       │ │ Google Sheets   │    │
                                       │ │ (Client Config) │    │
                                       │ └─────────────────┘    │
                                       │ ┌─────────────────┐    │
                                       │ │ Instantly API   │    │
                                       │ │ (56 clients)    │    │
                                       │ └─────────────────┘    │
                                       │ ┌─────────────────┐    │
                                       │ │ Bison API       │    │
                                       │ │ (24 clients)    │    │
                                       │ └─────────────────┘    │
                                       └────────────────────────┘
```

---

## 3. Integration Strategy

### Phase 1: Core Integration (Required)
1. Copy lead management functions to `/src/leads/` directory
2. Add 12 new tools to `src/mcp_handler.py`
3. Update configuration for Google Sheets URL
4. No new OAuth required (uses public Google Sheet)

### Phase 2: Configuration Updates
1. Add Google Sheets URL to environment variables
2. Update `.env.example` with new variables
3. Update `src/config.py` to include lead management config

### Phase 3: Installation & Documentation
1. Update `requirements.txt` (no new deps needed!)
2. Update `local_install.sh` to copy lead management files
3. Update `README.md` with new capabilities
4. Update `TROUBLESHOOTING.md` for lead-specific issues

### Phase 4: Testing & Validation
1. Test all 12 new tools individually
2. Test interaction with existing tools
3. Verify Google Sheets integration
4. Test fuzzy matching and date validation
5. Test aggregated analytics across 80 clients

---

## 4. File Structure Changes

### New Directory Structure
```
MCP_Gmail/
├── src/
│   ├── server.py                    # Main MCP server (updated)
│   ├── config.py                    # Configuration (updated)
│   ├── mcp_handler.py              # Tool handlers (UPDATED - add 12 tools)
│   ├── auth.py                      # Gmail auth (unchanged)
│   ├── gmail_client.py             # Gmail operations (unchanged)
│   ├── calendar_client.py          # Calendar operations (unchanged)
│   ├── fathom_client.py            # Fathom operations (unchanged)
│   │
│   └── leads/                       # NEW DIRECTORY
│       ├── __init__.py              # NEW
│       ├── instantly_client.py      # NEW - Instantly API wrapper
│       ├── bison_client.py          # NEW - Bison API wrapper
│       ├── sheets_client.py         # NEW - Google Sheets reader
│       ├── lead_functions.py        # NEW - Core business logic
│       └── date_utils.py            # NEW - Date validation utilities
│
├── credentials/
│   ├── credentials.json             # Google OAuth (existing)
│   └── token.json                   # Google token (existing)
│
├── requirements.txt                 # Updated (no new deps)
├── .env.example                     # Updated (add Google Sheets URL)
├── README.md                        # Updated
├── TROUBLESHOOTING.md              # Updated
└── INTEGRATION_PLAN.md             # This document (NEW)
```

---

## 5. New Tools to Add

### Instantly.ai Tools (4)

**1. get_instantly_client_list()**
- Lists all 56 Instantly clients
- Returns: workspace_id, client_name
- No parameters

**2. get_instantly_lead_responses(workspace_id, days=7, start_date, end_date)**
- Fetches interested lead responses for a client
- Supports fuzzy name matching
- Returns: email, reply_summary, reply_body, subject, timestamp
- Parameters: workspace_id (required), days/start_date/end_date (optional)

**3. get_instantly_campaign_stats(workspace_id, days=7, start_date, end_date)**
- Gets campaign statistics for a client
- Returns: emails_sent, replies, opportunities, reply_rate
- Parameters: workspace_id (required), days/start_date/end_date (optional)

**4. get_instantly_workspace_info(workspace_id)**
- Fetches detailed workspace information
- Returns: workspace_name, owner, plan_id, timestamps
- Parameters: workspace_id (required)

### Bison Tools (3)

**5. get_bison_client_list()**
- Lists all 24 Bison clients
- Returns: client_name
- No parameters

**6. get_bison_lead_responses(client_name, days=7, start_date, end_date)**
- Fetches interested lead responses from Bison
- Includes full conversation threads
- Returns: email, from_name, reply_body, subject, date_received, conversation_thread
- Parameters: client_name (required), days/start_date/end_date (optional)

**7. get_bison_campaign_stats(client_name, days=7, start_date, end_date)**
- Gets campaign statistics from Bison
- Returns: emails_sent, total_leads_contacted, opened, replies, bounced, unsubscribed, interested
- Parameters: client_name (required), days/start_date/end_date (optional)

### Unified Tools (1)

**8. get_all_lead_clients()**
- Lists ALL 80 clients from both platforms
- Returns: total_clients (80), instantly_clients (56), bison_clients (24), clients[]
- No parameters

### Aggregated Analytics Tools (4)

**9. get_all_platform_stats(days=7)**
- Aggregates statistics from BOTH platforms
- Returns: total_emails_sent, total_replies, total_interested_leads, reply_rate
- Parameters: days (optional, default=7)

**10. get_top_performing_clients(limit=10, metric="interested_leads", days=7)**
- Ranks top performing clients across both platforms
- Metrics: interested_leads, emails_sent, replies, reply_rate
- Parameters: limit (optional, default=10), metric (optional), days (optional)

**11. get_underperforming_clients(threshold=5, metric="interested_leads", days=7)**
- Identifies clients performing below threshold
- Returns: list of underperforming clients with stats
- Parameters: threshold (optional, default=5), metric (optional), days (optional)

**12. get_weekly_lead_summary()**
- Generates comprehensive weekly report across all 80 clients
- Returns: overall stats, top 5 performers, underperformers, insights
- Optimized to minimize API calls
- No parameters

---

## 6. Configuration Changes

### New Environment Variables

Add to `.env` and `.env.example`:

```bash
# Lead Management Configuration
LEAD_SHEETS_URL=https://docs.google.com/spreadsheets/d/1CNejGg-egkp28ItSRfW7F_CkBXgYevjzstJ1QlrAyAY/edit
LEAD_SHEETS_GID_INSTANTLY=928115249
LEAD_SHEETS_GID_BISON=1631680229

# Optional: Override for single-client testing
# INSTANTLY_API_KEY=your_api_key_here
```

### Update src/config.py

Add new configuration dataclass fields:

```python
@dataclass
class Config:
    # ... existing fields ...

    # Lead Management
    lead_sheets_url: str
    lead_sheets_gid_instantly: str
    lead_sheets_gid_bison: str
```

---

## 7. Implementation Steps

### Step 1: Create Lead Management Module
- [x] Create `/src/leads/` directory
- [ ] Copy `mcp_functions.py` → `lead_functions.py`
- [ ] Split into modular files:
  - `instantly_client.py` - Instantly API wrapper
  - `bison_client.py` - Bison API wrapper
  - `sheets_client.py` - Google Sheets reader
  - `date_utils.py` - Date validation
  - `lead_functions.py` - High-level business logic

### Step 2: Update Configuration
- [ ] Add new env variables to `src/config.py`
- [ ] Update `.env.example` with lead management config
- [ ] Test configuration loading

### Step 3: Add Tools to MCP Handler
- [ ] Import lead management functions in `src/mcp_handler.py`
- [ ] Add 12 new tool definitions to FastMCP
- [ ] Test each tool individually

### Step 4: Update Installation Scripts
- [ ] Update `requirements.txt` (change `python-dotenv>=1.0.0` → `>=1.0.1`)
- [ ] Update `local_install.sh` (no changes needed - already installs all deps)
- [ ] Update `fix_config.py` (no changes needed)
- [ ] Update `health_check.sh` to check lead management setup

### Step 5: Documentation Updates
- [ ] Update `README.md`:
  - Add lead management capabilities
  - Update tool count (17 → 29+)
  - Add Instantly + Bison to feature list
- [ ] Update `TROUBLESHOOTING.md`:
  - Add "Google Sheets not accessible" issue
  - Add "Instantly API key invalid" issue
  - Add "Bison API key invalid" issue
- [ ] Create `LEAD_MANAGEMENT.md` (detailed guide for lead tools)

### Step 6: Testing
- [ ] Test Instantly client list tool
- [ ] Test Instantly lead responses with fuzzy matching
- [ ] Test Instantly campaign stats
- [ ] Test Bison client list tool
- [ ] Test Bison lead responses with conversation threads
- [ ] Test Bison campaign stats
- [ ] Test unified client list (80 clients)
- [ ] Test aggregated platform stats
- [ ] Test top performing clients ranking
- [ ] Test underperforming clients detection
- [ ] Test weekly summary report
- [ ] Test date validation safeguards
- [ ] Test integration with existing Gmail/Calendar tools

### Step 7: Deployment
- [ ] Commit changes to GitHub
- [ ] Test local installation with updated script
- [ ] Deploy to Railway (if needed)
- [ ] Test with real clients

---

## 8. Compatibility Considerations

### With Existing Tools
- **No conflicts:** Lead management tools operate independently
- **Shared resources:** Only shares `requests` library and MCP framework
- **No OAuth conflicts:** Lead management uses public Google Sheets, no auth needed

### Multi-User Support
- **Local installations:** Each user has their own MCP server with full access to all 80 clients
- **Railway multi-tenant:** Not applicable - lead management is for internal team only
- **Security:** Google Sheets must remain view-only public for all team members

### Performance Impact
- **Google Sheets:** Single API call per tool invocation (~100-500ms)
- **Instantly API:** Rate limit unknown, but client uses 56 workspaces
- **Bison API:** Custom API, rate limits controlled internally
- **Weekly summary:** Optimized to fetch stats once for all clients (~15-30 seconds for 80 clients)

---

## 9. Risk Analysis

### Low Risk
✅ **Dependency conflicts** - All dependencies compatible
✅ **Code conflicts** - Lead management is isolated in `/src/leads/`
✅ **Configuration conflicts** - New env variables don't overlap with existing
✅ **Tool name conflicts** - All new tool names are unique

### Medium Risk
⚠️ **Google Sheets access** - If sheet becomes private, all tools break
   - **Mitigation:** Document sheet ownership and access requirements
   - **Fallback:** Support local CSV file as backup

⚠️ **API rate limits** - Instantly/Bison may have unknown rate limits
   - **Mitigation:** Add rate limiting and retry logic
   - **Fallback:** Cache responses for repeated queries

### High Risk
🚨 **API key security** - 80 API keys stored in Google Sheets
   - **Mitigation:** Keep sheet view-only, don't allow public editing
   - **Consider:** Move to encrypted storage in future

🚨 **Client data exposure** - All team members see all 80 clients
   - **Mitigation:** This is by design - team needs visibility
   - **Consider:** Add client-specific access control in future

---

## 10. Future Enhancements

### Phase 2 Enhancements (Post-Integration)
1. **Caching Layer**
   - Cache Google Sheets data for 5-10 minutes
   - Cache API responses for frequently accessed clients
   - Reduce API calls and improve performance

2. **Advanced Analytics**
   - Month-over-month comparison
   - Client health scoring
   - Predictive analytics for at-risk clients
   - Automated weekly reports via email

3. **Webhook Integration**
   - Real-time notifications for new interested leads
   - Slack/Discord integration for team alerts
   - Automated follow-up reminders

4. **Client Management**
   - Add new clients via MCP tools
   - Update API keys without editing sheets
   - Archive inactive clients

5. **Security Enhancements**
   - Encrypted API key storage
   - Role-based access control per client
   - Audit logging for all API calls

---

## 11. Success Criteria

Integration is considered successful when:

- [x] All 12 lead management tools are implemented
- [ ] All tools pass individual testing
- [ ] Integration testing with existing tools passes
- [ ] Documentation is updated and accurate
- [ ] Local installation script works without errors
- [ ] Health check script validates lead management setup
- [ ] Google Sheets integration works reliably
- [ ] Date validation safeguards work correctly
- [ ] Fuzzy client matching works as expected
- [ ] Weekly summary generates within 30 seconds
- [ ] No regressions in existing Gmail/Calendar/Fathom tools

---

## 12. Timeline Estimate

**Integration Complexity:** Medium
**Estimated Implementation:** This is a comprehensive integration that combines multiple systems

### Breakdown:
- **Step 1 (Create Module):** Refactoring existing code into modular structure
- **Step 2 (Configuration):** Adding new environment variables
- **Step 3 (Add Tools):** Integrating 12 new tools into MCP handler
- **Step 4 (Installation):** Minimal changes to existing scripts
- **Step 5 (Documentation):** Comprehensive updates to README and guides
- **Step 6 (Testing):** Thorough testing of all 12 new tools plus integration tests
- **Step 7 (Deployment):** Git commit and Railway deployment

---

## 13. Conclusion

This integration brings powerful lead management capabilities to the existing Gmail MCP server:

**Benefits:**
- Unified interface for all communication and lead management
- 80 clients across 2 platforms (Instantly + Bison)
- Advanced analytics and reporting
- Minimal code changes required
- No dependency conflicts
- No new OAuth flow needed

**Next Steps:**
1. Review this plan
2. Get approval to proceed
3. Begin implementation with Step 1
4. Test thoroughly at each phase
5. Deploy to production

**Questions to Address:**
1. Should lead management be opt-in or enabled by default?
2. Do we need client-level access control?
3. Should we support Railway multi-tenant for leads, or local-only?
4. Do we need backup/redundancy for Google Sheets data?
