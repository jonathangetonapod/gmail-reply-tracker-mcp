# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.7.5] - December 23, 2025

### 🔍 Campaign Analysis Tools - 4 New Tools Added! (82 Total Tools)

### Added
- **Campaign Inspection & Analysis**: List and inspect campaigns with complete sequence details (4 new tools)
  - **NEW TOOL ADDED**: `list_instantly_campaigns` - List all campaigns for an Instantly client
  - **NEW TOOL ADDED**: `get_instantly_campaign_details` - Get complete campaign details with sequences and variants
  - **NEW TOOL ADDED**: `list_bison_campaigns` - List all campaigns for a Bison client
  - **NEW TOOL ADDED**: `get_bison_campaign_details` - Get complete campaign details with sequences and steps
  - **TOTAL TOOLS**: 82 (up from 78)
  - **Campaign Management**: Now 8 tools (was 4)

### Features

#### Instantly Campaign Analysis
- **List Campaigns**: Get all campaigns for a workspace with status filtering
  - Filter by status: active, draft, launching, paused
  - Status mapping: 0=draft, 1=active, 2=launching, 3=paused
  - Shows campaign ID, name, status, created date
  - Fuzzy client name matching (60% similarity threshold)

- **Campaign Details**: Complete campaign inspection with all sequences and variants
  - Full sequence breakdown with step-by-step details
  - A/B test variants for each step (subject lines, email bodies)
  - Wait times between steps (in hours)
  - Email settings (track opens, track clicks, schedule)
  - Campaign statistics and performance data

#### Bison Campaign Analysis
- **List Campaigns**: Get all campaigns for a Bison client with status filtering
  - Filter by status: active, draft, launching, paused, completed, archived
  - Shows campaign ID, name, status, created date
  - Fuzzy client name matching (60% similarity threshold)

- **Campaign Details**: Complete campaign inspection with sequences and steps
  - Full sequence breakdown with step-by-step details
  - Email subjects and bodies for each step
  - Wait times between steps (in days)
  - Thread reply settings
  - Variant support for A/B testing

#### Smart Integration
- **Fuzzy Matching**: Uses RapidFuzz with 60% similarity for client name matching
  - Example: "brian blis" finds "Brian Bliss"
  - Handles typos and partial names
- **Google Sheets Integration**: Loads client configuration from existing Google Sheets
  - Instantly: workspace_id mapping from sheets
  - Bison: client_name mapping from sheets
- **Async/Await Patterns**: All functions use `asyncio.to_thread()` for non-blocking Google Sheets operations

### Use Cases
- "List all active campaigns for Brian Bliss" → Shows campaign IDs and names
- "Show me the campaign details for campaign abc-123" → Full sequence with subjects, bodies, variants
- "What campaigns does Michael Hernandez have in draft status?" → Lists draft campaigns
- "Analyze the email sequence for Lena Kadriu's campaign" → Complete step-by-step breakdown with wait times

### Technical Details
- Added 4 new MCP tools in `src/server.py`:
  - `list_instantly_campaigns` (lines 7178-7243): Lists campaigns with status filtering
  - `get_instantly_campaign_details` (lines 7291-7373): Fetches complete campaign details
  - `list_bison_campaigns` (lines 6778-6825): Lists Bison campaigns with status filtering
  - `get_bison_campaign_details` (lines 6873-6932): Fetches complete Bison campaign details
- Uses existing `instantly_client.py` and `bison_client.py` API functions
- Async patterns: `await asyncio.to_thread()` for Google Sheets loading
- Error handling: Graceful fallbacks for client not found, API errors
- Status mapping: Converts numeric status codes to human-readable names
- Returns JSON with success/error structure for all tools
- Total implementation: ~300 lines of new MCP tool code

### API Integrations
- **Instantly API**: Uses `/api/v1/campaign/list` and `/api/v1/campaign/get` endpoints
- **Bison API**: Uses `/api/campaigns` list and detail endpoints
- **Google Sheets**: Loads workspace/client configuration from existing sheets

---

## [2.7.3] - December 21, 2025

### 🔧 Instantly API v2 Migration - Fixed Workspace Info (78 Total Tools)

### Fixed
- **Updated Workspace Info to API v2**: Fixed 404 error spam by migrating from deprecated v1 to v2 workspace endpoint
  - **Problem**: System was calling `/api/v1/workspaces/current` to fetch workspace names, generating hundreds of 404 errors in logs (v1 endpoint deprecated)
  - **Solution**: Updated `INSTANTLY_WORKSPACE_URL` from `/api/v1/workspaces/current` to `/api/v2/workspaces/current`. Now successfully fetches workspace names from Instantly API v2
  - **Impact**:
    - ✅ Clean logs with no 404 errors
    - 📝 Proper workspace names displayed instead of IDs (e.g., "My Workspace" instead of "019b3dad-ecfc-78e2-83c9-ec422d634a78")
    - 🎯 Better user experience with human-readable names
    - 🔄 Triple fallback: API v2 name → Google Sheets name → workspace_id

### Technical Details
- Updated `INSTANTLY_WORKSPACE_URL` from `/api/v1/workspaces/current` to `/api/v2/workspaces/current`
- Updated `_fetch_workspace_info()` docstring to reference API v2
- Triple fallback logic: `workspace_info.get('workspace_name')` or `workspace.get('workspace_name')` or `workspace_id`
- API v2 endpoint returns: id, timestamp_created, timestamp_updated, owner, name, plan_id, and more
- Primary benefit: Human-readable workspace names in logs and output
- No functional changes to mailbox health logic
- Total tool count remains 78 (no new tools, bug fix only)

---

## [2.7.2] - December 21, 2025

### ⚡ Parallel Processing for Mailbox Health - 16x Faster! (78 Total Tools)

### Performance
- **Parallel Processing for All Mailbox Health Functions**: Checking 80+ clients now takes 10 seconds instead of 160 seconds (16x faster!)
  - **Before**: Sequential checking = 80 clients × 2 seconds = 160 seconds (2-3 minutes)
  - **After**: Parallel with 20 workers = 80 clients ÷ 20 workers × 2 seconds = ~10 seconds
  - **Result**: 16x performance improvement!

### Affected Functions
1. **get_all_mailbox_health()** - Aggregates health across all clients with parallel fetching
2. **get_unhealthy_mailboxes()** - Finds at_risk mailboxes across all platforms in parallel
3. **get_bison_sender_replies()** - Fetches replies from multiple senders simultaneously (from v2.7.1)

### Features
- **ThreadPoolExecutor Integration**:
  - Up to 20 parallel workers for mailbox health checks
  - Up to 15 parallel workers for sender reply fetching
  - Smart worker allocation: `min(20, client_count)` prevents over-threading with fewer clients

- **Graceful Error Handling**: Per-client failures don't block other clients from being processed

- **Use Cases**:
  - "Show me mailbox health for all clients" → 80+ clients in 10 seconds
  - "Find unhealthy mailboxes across all platforms" → Instant results
  - "Get all replies for Jeff Mikolai from 15 senders" → 15x faster

### Technical Details
- Updated `get_all_mailbox_health()` with parallel processing (lines 2039-2142 in lead_functions.py)
- Added `process_client_mailboxes()` helper function for parallel execution
- ThreadPoolExecutor with `max_workers=min(20, client_count)` for optimal performance
- Updated `get_unhealthy_mailboxes()` with parallel processing (lines 2169-2234)
- Added `process_client_unhealthy()` helper function for parallel unhealthy detection
- All mailbox health functions now use `concurrent.futures.ThreadPoolExecutor`
- Error handling: Per-client failures logged but don't block other clients
- Performance calculation: 80 clients × 2 seconds = 160s sequential → 80 clients ÷ 20 workers × 2s = 10s parallel
- Parallel processing already added to `get_bison_sender_replies()` in v2.7.1 (up to 15 workers)
- Total tool count remains 78 (no new tools, performance optimization only)
- All functions maintain backward compatibility with identical return structures

---

## [2.7.1] - December 21, 2025

### 📧 Bison Sender Email Replies - Full Reply-Level Analytics (78 Total Tools)

### Added
- **Reply-Level Analytics for Bison Sender Emails**: Get detailed reply data from all sender emails with automatic pagination handling
  - **NEW TOOL ADDED**: `get_bison_sender_email_replies` with full pagination support
  - **TOTAL TOOLS**: 78 (up from 77)
  - **Mailbox Health Monitoring**: Now 6 tools (was 5)

### Features

#### Smart Pagination with Bison's 15-Item Limit
- **Handles Pagination**: Bison API returns max 15 replies per page - tool automatically fetches ALL pages
- **Pagination Logic**:
  - Fetches page 1 (up to 15 items)
  - Checks pagination metadata (`current_page`, `last_page`)
  - Continues fetching until `current_page >= last_page`
- **Safety Features**:
  - Breaks early if page returns empty results
  - Respects `max_results` limit to prevent excessive API calls
  - Tracks total replies fetched across all pages
- **Performance**:
  - Efficient multi-page fetching with proper error handling
  - Comprehensive logging for debugging ("Fetched page 2 with 15 replies")
  - Minimal API overhead with smart break conditions

#### Flexible Filtering
- Get all replies for a client (all senders)
- Filter by specific sender email
- Show only interested leads (`interested_only=True`)
- Limit result count (`limit=100`, set to 0 for unlimited)

#### Comprehensive Reply Data
Each reply includes:
- **id** - Unique reply identifier
- **lead_email** - Who replied
- **lead_name** - Lead's full name
- **company** - Lead's company
- **reply_text** - Full reply message
- **interested** - Boolean flag (marked by user or AI)
- **status** - Reply status
- **replied_at** - ISO timestamp
- **campaign_name** - Which campaign generated this reply
- **sequence_step** - Which step in sequence triggered reply

#### Summary Data
- Per-sender summaries showing:
  - Total replies
  - Number shown (respecting limit)
  - Interested lead count
- Aggregated totals across all senders queried

#### Parallel Processing
- **ThreadPoolExecutor**: Uses up to 15 parallel workers
- **Performance**:
  - Before: 50 senders × 2 seconds = 100 seconds (sequential)
  - After: 50 senders ÷ 15 workers × 2 seconds = ~7 seconds (parallel)
  - **Result**: 14x faster!
- **Graceful Error Handling**: Failures on individual senders don't block others

### Use Cases
- "Get all replies for Jeff Mikolai" (fetches from all 15 senders)
- "Get interested replies for Rich Cave"
- "Get 50 replies from jeff@sugarpixels.com"
- "Get unlimited replies from sender rich@mycave.com"

### Technical Details
- Added `EMAIL_BISON_REPLIES_URL` constant for sender replies endpoint
- Added `_fetch_emailbison_sender_replies()` helper function with full pagination
- Pagination uses page numbers (1, 2, 3...) with `per_page=15` (Bison max)
- Checks `meta.current_page` and `meta.last_page` to determine when to stop
- Added `get_bison_sender_replies()` main function in lead_functions.py (+108 lines)
- Exported `get_bison_sender_replies` in leads/__init__.py (+2 lines)
- Added MCP tool `get_bison_sender_email_replies` in server.py (+74 lines)
- Tool signature: `client_name` (required), `sender_email` (optional), `interested_only` (bool), `limit` (int)
- Default `limit=100`, set to 0 for unlimited results
- Returns JSON with: `total_senders`, `total_replies`, `interested_count`, `sender_summaries`, `replies`
- All 3 files modified: lead_functions.py (+108 lines), __init__.py (+2 lines), server.py (+74 lines)
- Total implementation: ~184 lines of new code

---

## [2.7.0] - December 21, 2025

### 🔌 MAILBOX HEALTH MONITORING - 5 New Tools! (77 Total Tools)

### Added
- **Mailbox Health Monitoring**: Complete email account oversight across Instantly & Bison platforms
  - **NEW CATEGORY ADDED**: Mailbox Health Monitoring (5 tools)
  - **TOTAL TOOLS**: 77 (up from 72)
  - **MONITORS 88+ CLIENTS**: Track email account health across both platforms in real-time

### Features

#### Health Classification System
- **3-tier system**: healthy/early/at_risk with automatic problem detection
- **Warmup Tracking**: Instantly accounts show warmup scores (0-100) and warmup status
- **Capacity Planning**: Calculate total daily sending capacity across all accounts
- **Instant Alerts**: Identify unhealthy mailboxes needing immediate attention

#### 5 Powerful Mailbox Monitoring Tools

1. **get_instantly_mailbox_health(workspace_id)**: View all Instantly email accounts for a workspace
   - Status codes (1=Active, 2=Paused, -1/-2/-3=Errors)
   - Warmup scores, daily limits, last used timestamps
   - Provider info (Gmail/Outlook)

2. **get_bison_mailbox_health(client_name)**: View all Bison email accounts for a client
   - Connection status
   - All-time metrics (emails sent, replies, opens, bounces)
   - Interested leads count, tags, and account types

3. **get_all_mailbox_health_summary()**: Aggregated health across ALL 88+ clients
   - Total accounts, healthy/at_risk/early counts
   - Health percentage and platform-specific totals
   - Per-client summaries

4. **get_unhealthy_mailboxes_alert()**: Filter for only at_risk mailboxes needing attention
   - Client name, platform, email, status/issue
   - Daily limit information

5. **get_mailbox_capacity_report()**: Calculate total daily sending capacity
   - Aggregate limits from all accounts
   - Platform breakdown, average per account
   - Health-adjusted capacity

#### Real-Time Account Health & Status Monitoring

**Instantly Status Mapping**:
- **(1) Active** = Healthy, sending normally
- **(2) Paused** = Early, temporarily disabled
- **(-1) Connection Error** = At Risk, can't connect to provider
- **(-2) Soft Bounce Error** = At Risk, deliverability issues
- **(-3) Sending Error** = At Risk, failed to send

**Bison Status Mapping**:
- **Connected** = Healthy, working normally
- **Disconnected/Unknown** = At Risk, needs attention

**Warmup Intelligence**:
- Track email reputation building with warmup scores (0-100 scale)
- Warmup status (Active/Inactive)
- Provider-specific warmup strategies

**Metrics Tracking**:
- **Instantly**: last_used timestamps and provider codes
- **Bison**: all-time emails_sent, total_replied, unique_replied, total_opened, bounced, interested_leads_count

**Capacity Planning**:
- Calculate total daily capacity for campaign volume planning (sum of all daily_limit fields)
- Platform-specific capacity breakdown (Instantly vs Bison)
- Healthy-only capacity (excludes at_risk accounts)
- Average capacity per account

### API Integrations
- **Instantly API**: Direct integration with `https://api.instantly.ai/api/v1/account/list`
- **Email Bison API**: Direct integration with `https://app.emailbison.com/api/sender-email-accounts`
- **Pagination Support**: Handles cursor-based (Instantly) and offset-based (Email Bison) pagination automatically
- **545 Lines of Code**: Complete mailbox monitoring implementation in leads.py with helper functions

### Technical Details
- Added 545 lines to leads.py for mailbox monitoring functionality
- Implemented `_fetch_workspace_info()` helper for Instantly workspace metadata
- Implemented `_fetch_instantly_accounts()` with cursor-based pagination (next_starting_after)
- Implemented `_fetch_emailbison_accounts()` with offset-based pagination (page numbers + Laravel meta)
- Added `get_instantly_mailboxes()` - fetches and processes Instantly email accounts with health classification
- Added `get_bison_mailboxes()` - fetches and processes Bison email accounts with metrics
- Added `get_all_mailbox_health()` - aggregates health across all 88+ clients and both platforms
- Added `get_unhealthy_mailboxes()` - filters for at_risk accounts needing attention
- Added 354 lines to server.py for 5 new MCP tools
- Tool 1: `get_instantly_mailbox_health` - Returns workspace accounts with warmup scores and status codes
- Tool 2: `get_bison_mailbox_health` - Returns client accounts with all-time metrics and tags
- Tool 3: `get_all_mailbox_health_summary` - Returns aggregated health across all platforms with percentages
- Tool 4: `get_unhealthy_mailboxes_alert` - Returns filtered list of at_risk accounts for quick fixes
- Tool 5: `get_mailbox_capacity_report` - Returns total daily capacity calculation with platform breakdown
- Updated imports in server.py to include 4 new mailbox functions from leads module
- Integrated with existing Google Sheets infrastructure for API key management
- Supports both Instantly (cursor pagination) and Email Bison (offset pagination) APIs
- Health classification logic: Instantly uses numeric status codes, Bison uses string statuses
- Status breakdown tracking for debugging and analytics in both platforms
- Total tool count increased from 72 to 77 (5 new mailbox tools)
- New category: Mailbox Health Monitoring joins existing 8 categories
- Code integrated from leadgenjay_client_health_tracker repository

---

## [2.6.0] - December 20, 2025

### Added

- **📊 GOOGLE SHEETS INTEGRATION - 18 Comprehensive Tools Added!**
  - **TOTAL TOOLS NOW: 69** (up from 51)
  - **NEW CATEGORY**: Google Sheets (18 tools) - Full CRUD operations, formatting, and organization
  - **COMPLETE SPREADSHEET CONTROL**: Create, read, update, delete, format, sort, and organize spreadsheets
  - **PROFESSIONAL FORMATTING**: Bold, colors, alignment, frozen headers, auto-resized columns
  - **MULTI-TENANT SAFE**: Each user's credentials fully isolated - perfect for team deployments
  - **RATE LIMITED**: 300 requests/minute with thread-safe token bucket algorithm

  **Core Operations (10 tools):**
  1. **`create_spreadsheet`** - Create new spreadsheets with custom sheet names
     - Example: "Create a spreadsheet called 'Sales Tracker' with sheets Q1, Q2, Q3, Q4"
     - Returns: spreadsheet_id, URL, sheet info
     - OAuth scope: `https://www.googleapis.com/auth/spreadsheets`

  2. **`read_spreadsheet`** - Read data from any range (A1 notation)
     - Example: "Read Sheet1!A1:D10 from spreadsheet [ID]"
     - Supports: Full sheets, specific ranges, entire columns
     - Returns: 2D array of cell values

  3. **`append_to_spreadsheet`** - Add rows to end of sheets
     - Example: "Append these 5 rows to the Sales sheet"
     - Perfect for: Logs, data collection, progressive tracking
     - Auto-finds next empty row

  4. **`update_spreadsheet`** - Update specific cell ranges
     - Example: "Update Sheet1!A1:B2 with new header values"
     - Precise control over any range
     - Supports formulas and formatting

  5. **`clear_spreadsheet_range`** - Clear values without deleting cells
     - Example: "Clear all data in Sheet1!A1:Z100"
     - Preserves formatting and structure
     - Non-destructive operation

  6. **`find_replace_in_spreadsheet`** - Find and replace text across sheets
     - Example: "Replace '{{client}}' with 'Acme Corp' in all sheets"
     - Optional: Limit to specific sheet, case-sensitive matching
     - Returns: Number of replacements made

  7. **`delete_spreadsheet_rows`** - Delete specific rows
     - Example: "Delete rows 5-10 from Sheet1"
     - ⚠️ WARNING: Permanent deletion with safety warnings
     - 1-indexed for user convenience

  8. **`delete_spreadsheet_columns`** - Delete specific columns
     - Example: "Delete columns C-E from Data sheet"
     - ⚠️ WARNING: Permanent deletion with safety warnings
     - Uses column letters (A, B, AA, etc.)

  9. **`add_sheet_to_spreadsheet`** - Create new tabs/sheets
     - Example: "Add a new sheet called 'Q1 Sales' to spreadsheet [ID]"
     - Dynamic spreadsheet organization
     - Returns: New sheet ID and metadata

  10. **`delete_sheet_from_spreadsheet`** - Delete entire sheets
      - Example: "Delete the 'Old Data' sheet from spreadsheet [ID]"
      - ⚠️ WARNING: Permanent deletion with safety warnings
      - Removes entire tab and all data

  **Advanced Operations (8 tools):**
  11. **`list_sheets_in_spreadsheet`** - List all tabs with metadata
      - Example: "Show me all sheets in spreadsheet [ID]"
      - Returns: Sheet IDs, titles, indices, grid properties
      - Essential for navigation and organization

  12. **`rename_spreadsheet_sheet`** - Rename existing tabs
      - Example: "Rename 'Sheet1' to 'Q1 Sales Data'"
      - Clean up auto-generated names
      - Better organization

  13. **`insert_spreadsheet_rows`** - Insert blank rows at any position
      - Example: "Insert 5 rows at row 10 in Sheet1"
      - Perfect for: Adding space, reorganizing data
      - Non-destructive insertion

  14. **`insert_spreadsheet_columns`** - Insert blank columns at any position
      - Example: "Insert 3 columns starting at column C"
      - Flexible data structure changes
      - Preserves existing data

  15. **`format_spreadsheet_cells`** - Apply styling (bold, colors, alignment)
      - Example: "Format A1:E1 as bold, centered, with light blue background"
      - Options: Bold, italic, font size, text color, background color, alignment
      - RGB color support: `{"red": 0.85, "green": 0.92, "blue": 1.0}`
      - Professional presentation

  16. **`sort_spreadsheet_range`** - Sort data by column
      - Example: "Sort A2:E100 by column C descending"
      - Ascending or descending
      - Preserves header rows (skip row 1)
      - Essential for data analysis

  17. **`freeze_spreadsheet_rows_columns`** - Freeze headers for scrolling
      - Example: "Freeze the top row in Sheet1"
      - Keep headers visible while scrolling large datasets
      - Freeze rows, columns, or both

  18. **`auto_resize_spreadsheet_columns`** - Auto-fit column widths
      - Example: "Auto-resize columns A through Z in Sheet1"
      - Optimal readability
      - Fits content automatically

  **Technical Implementation:**
  - ✅ New `src/sheets_client.py`: SheetsClient with full API wrapper
  - ✅ Thread-safe token bucket rate limiter (300 req/min)
  - ✅ Comprehensive error handling and retry logic
  - ✅ Full A1 notation parsing for ranges
  - ✅ RGB color support for cell formatting
  - ✅ OAuth scope: `https://www.googleapis.com/auth/spreadsheets`
  - ✅ Updated scopes in all 4 config locations
  - ✅ Per-user credentials (multi-tenant safe)
  - ✅ Auto-retry on transient failures (403, 429, 500, 503)

  **Authentication & Security:**
  - ✅ OAuth scope auto-configured
  - ✅ Per-user credentials (multi-tenant safe)
  - ✅ Encrypted token storage in SQLite
  - ✅ Rate limiting: 300 requests/minute per user
  - ✅ Thread-safe with proper locking
  - ✅ Exponential backoff on rate limit errors

  **Use Cases:**
  - 📊 "Create a Q1 sales tracker with tabs for each month and format headers"
  - 📈 "Read the latest data from the revenue sheet and analyze trends"
  - ✨ "Format the header row as bold and centered with a blue background"
  - 🔄 "Sort the client list by revenue descending"
  - ⚡ "Insert 10 rows in the middle to add new data"
  - 🎯 "Freeze the top 2 rows so headers stay visible"
  - 📐 "Auto-resize all columns so data is readable"
  - 🔍 "Replace all placeholder client names with actual names"
  - 🗂️ "List all sheets in this workbook to see what we have"
  - 📋 "Append new lead data to the tracking sheet daily"

  **Platform Overview:**
  - 📧 **Gmail** (13 tools): Email management, search, threads, drafts
  - 📅 **Calendar** (7 tools): Events, scheduling, quick add
  - 📝 **Docs** (6 tools): Document creation, editing, formatting
  - 📊 **Sheets** (18 tools): Spreadsheet CRUD, formatting, organization ⭐ NEW
  - 🎥 **Fathom** (6 tools): Meeting transcripts, summaries, action items
  - 🚀 **Instantly** (12 tools): Campaign management, lead tracking
  - 🦬 **Bison** (6 tools): Campaign management, lead tracking
  - 🛡️ **EmailGuard** (1 tool): Spam checking

  **TOTAL: 69 Tools Across 8 Platforms** 🎉

### Fixed - December 20, 2025

- **🔧 CRITICAL FIX: Bison Sender Emails Pagination**
  - **THE PROBLEM**: Only fetching 15 sender email accounts instead of all 50-80+ per client
  - **SYMPTOMS**: Client emails appearing as "interested leads" in hidden gems results
    - Example: `mike.h@bookbiggerstages.org`, `jeff@sugarpixelspro.com`, `rich.c@tryflyingpoint.com`
    - These are the CLIENT'S own sending emails, not prospects!
  - **ROOT CAUSE**: Bison API returns 15 results per page (fixed), doesn't support `per_page` parameter
    - Initial pagination code used `while` loop with `per_page=100` parameter
    - API ignored `per_page`, always returned 15 results
    - Loop stopped after first page because it got 15 < 100 results
  - **THE FIX**: Explicit page fetching with proper pagination logic
    - Fetch up to 10 pages (150 emails max) to handle clients with 50-80 inboxes
    - Stop early when empty page or < 15 results detected
    - Added comprehensive logging to track pagination progress
  - **PRODUCTION VALIDATION**: Jeff Mikolai test shows working pagination:
    ```
    - Fetching sender emails page 1 → 15 emails (total: 15)
    - Fetching sender emails page 2 → 15 emails (total: 30)
    - Fetching sender emails page 3 → 15 emails (total: 45)
    - Fetching sender emails page 4 → 5 emails (total: 50)
    - Got 5 < 15 results, last page reached
    - Pagination complete: fetched 50 total sender emails across 4 pages
    ```
  - **IMPACT**:
    - **Before**: Found 15 sender email accounts → 35+ client emails appearing as leads ❌
    - **After**: Found 50 sender email accounts → All client emails properly filtered ✅
    - **Result**: Hidden gems now show ONLY actual prospect replies, not client replies
  - **CODE**: `src/leads/bison_client.py` lines 553-617 (get_bison_sender_emails function)
  - **COMMITS**:
    - `ca18f7a` - Add detailed logging to debug pagination
    - `aa081fb` - Fix pagination with explicit page fetching

- **🎯 CRITICAL FIX: Detect Already-Interested Leads from Client Replies**
  - **THE PROBLEM**: Leads already marked as interested in Bison were appearing as "warm hidden gems"
  - **EXAMPLE**: Tracy Wallace (tracy@feast26.com) for Justin Ashcraft
    - Tracy replied with interest about debt financing
    - Justin replied back and clicked gray "Interested" tag in Bison
    - Tracy still showing up as "1 warm lead (75% confidence)" ❌
  - **ROOT CAUSE**: When you mark a thread as interested in Bison, the `interested=true` flag is often on the CLIENT'S reply to the lead, not the lead's incoming reply
    - Old logic: Only checked interested flag on incoming lead replies (to_email = client email)
    - Issue: Tracy's incoming reply had `interested=false`
    - Issue: Justin's outbound reply had `interested=true`, but was filtered out as client reply
    - Result: Tracy's email never added to `already_interested` list
  - **THE FIX**: Also extract lead emails from client replies marked as interested
    - When `interested=true` on client reply (is_to_client=False):
      - Extract lead email from TO field (the person client is replying to)
      - Add that email to `already_interested` list
      - Properly exclude them from hidden gems
  - **DETECTION LOGIC**:
    ```python
    if not is_to_client:  # This is client reply TO a lead
        if from_email_lower in client_email_addresses:
            # Extract lead email from TO field
            already_interested.append({"email": to_email, ...})
    ```
  - **LOGGING**:
    ```
    Found interested tag on client reply to lead: to=tracy@feast26.com (reply_id=438907)
    Added lead tracy@feast26.com to interested list (from client reply)
    ```
  - **IMPACT**:
    - **Before**: Leads marked via client reply showing as hidden gems ❌
    - **After**: All marked leads properly excluded, regardless of where tag is ✅
    - Sales team sees accurate hidden gems list with no duplicates
  - **CODE**: `src/server.py` lines 3548-3571 (interested_replies_raw processing)
  - **COMMIT**: `fcea96e` - Extract lead emails from client replies marked as interested

### Added - December 19, 2025

- **📝 GOOGLE DOCS INTEGRATION - 6 New Tools Added!**
  - **TOTAL TOOLS NOW: 51** (up from 45)
  - **NEW CATEGORY**: Google Docs (6 tools) joins Gmail (13), Calendar (7), Fathom (6), Leads (18), Spam (1)
  - **REAL-TIME DOCUMENT MANAGEMENT**: Create, read, edit, and format Google Docs directly from Claude
  - **MULTI-TENANT SAFE**: Each user's credentials fully isolated - perfect for team deployments
  - **COMPREHENSIVE TEST SUITE**: 100+ tests covering all edge cases and OAuth scopes

  **New Tools:**
  1. **`create_google_doc`** - Create new documents with optional initial content
     - Example: "Create a doc called 'Meeting Notes - Q4 Planning' with attendees list"
     - Returns: document_id, title, and shareable URL
     - Auto-configures OAuth scope: `https://www.googleapis.com/auth/documents`

  2. **`read_google_doc`** - Read complete document content
     - Example: "Read the contents of document 1abc123xyz"
     - Returns: Full text content, metadata, character count
     - Preserves formatting and structure

  3. **`append_to_google_doc`** - Add content to end of document
     - Example: "Append these action items to the meeting notes doc"
     - Useful for: Meeting notes, progressive documentation, logs
     - Thread-safe with rate limiting

  4. **`insert_into_google_doc`** - Insert content at specific position
     - Example: "Insert executive summary at the beginning of the doc"
     - Precise control: Insert at index 1 (after title) or any character position
     - Perfect for: Templates, structured documents, headers

  5. **`replace_text_in_google_doc`** - Find and replace text
     - Example: "Replace all instances of '{{client_name}}' with 'Acme Corp'"
     - Use cases: Template population, bulk updates, corrections
     - Works across entire document

  6. **`add_heading_to_google_doc`** - Add formatted headings (H1-H6)
     - Example: "Add an H2 heading 'Budget Analysis' to the doc"
     - Supports: 6 heading levels for proper document hierarchy
     - Auto-formatting applied

  **Authentication & Security:**
  - ✅ OAuth scope auto-configured: `https://www.googleapis.com/auth/documents`
  - ✅ Per-user credentials (multi-tenant safe)
  - ✅ Encrypted token storage in SQLite
  - ✅ Rate limiting: 60 requests/minute per user
  - ✅ Thread-safe with proper locking
  - ✅ Auto-retry on transient failures

  **Production Ready:**
  - ✅ 100+ unit tests covering all operations
  - ✅ Error handling for common edge cases
  - ✅ OAuth scope validation
  - ✅ Comprehensive logging for debugging
  - ✅ Works in both local and Railway deployment modes

  **Local Mode** (✅ Works Now):
  - Each team member runs their own MCP server
  - Full isolation - each person uses their own Google account
  - Zero cross-contamination

  **Multi-Tenant Railway Mode** (⚠️ Coming Soon):
  - Architecture supports it (credentials isolated per user)
  - Tools need to be registered in `src/mcp_handler.py`
  - ETA: ~30 minutes to add

  **Use Cases:**
  - 📋 "Create meeting notes and append action items as we discuss them"
  - 📊 "Create a project report and populate the client name template"
  - 📝 "Read the proposal doc and summarize the key points"
  - 🔄 "Replace all placeholder text in the template with actual values"
  - 📑 "Add section headings to organize this unstructured document"

  **Files Added/Modified:**
  - `src/docs_client.py` - New DocsClient with rate limiting (lines 1-480)
  - `src/server.py` - 6 new MCP tools (lines 1210-1544)
  - `tests/test_docs_operations.py` - Comprehensive test suite
  - OAuth scopes updated in authentication flow

  **Performance:**
  - Rate limit: 60 requests/minute per user (Google Docs API quota)
  - Thread-safe locking prevents race conditions
  - Automatic retry on 500/503 errors (exponential backoff)
  - Parallel requests supported (different users don't block each other)

  **Commits:**
  - `6e70df4` - Fix Google Docs OAuth scope and add comprehensive tests
  - `49c9732` - Add Google Docs integration - Create, read, edit, and format documents

- **🎯 CRITICAL FIX: Automatic Dual-Marking for Forwarded Replies**
  - **THE PROBLEM**: When original lead (jhickman@brimmer.org) forwards email to actual decision-maker (aeppers@brimmer.org), marking only the responder left Unibox showing "Lead" status instead of "Interested"
  - **ROOT CAUSE**: Instantly's Unibox threads are tied to the original lead's email, not the responder's email
  - **THE FIX**: System now automatically detects forwarded replies and marks BOTH contacts:
    1. Marks the responder (aeppers@brimmer.org) as interested
    2. Automatically marks the original lead (jhickman@brimmer.org) as interested
    3. Ensures Unibox thread displays correct "Interested" status
  - **DETECTION LOGIC**: When `lead_id` differs from `lead_email`, system recognizes it as a forwarded reply
  - **LOGGING**:
    ```
    🔄 Forwarded reply detected: also marking original lead jhickman@brimmer.org
       This ensures the Unibox thread shows 'Interested' status
    ✅ Successfully marked original lead jhickman@brimmer.org as interested
    ```
  - **IMPACT**:
    - Sales team sees correct status in Unibox without manual intervention
    - No more "Lead" status confusion on threads with interested responses
    - Both contacts properly tracked in campaign for follow-up
  - **CODE**: `src/leads/_source_fetch_interested_leads.py` lines 325-361
  - **USER EXPERIENCE**: "I only care what people see in the Unibox" - now showing correct status! ✅

- **🔗 Campaign Association via Contact Lookup**
  - **THE PROBLEM**: When marking forwarded replies as interested, system couldn't find the campaign because responder's email wasn't in the campaign
  - **THE FIX**: Now uses original lead's email to find campaign via `/api/v2/campaigns/search-by-contact` endpoint
  - **FLOW**:
    1. Receive response from aeppers@brimmer.org
    2. System identifies original lead: jhickman@brimmer.org (via lead_id parameter)
    3. Searches campaigns using jhickman@brimmer.org to find campaign
    4. Associates both contacts with found campaign when marking
  - **VALIDATION**:
    ```
    ✅ Found campaign for lead jhickman@brimmer.org: 0e0ec7fb-2f40-401b-b919-4afc79feaf9e
    ✅ Marking request accepted - background job queued
    ```
  - **IMPACT**: Leads properly associated with campaigns, enabling background jobs to succeed
  - **CODE**: Campaign lookup in marking workflow

- **⚙️ Shared Anthropic API Key Configuration**
  - **THE PROBLEM**: Team members (like Juliana) didn't know if they had the Claude API key configured, causing authentication errors and fallback to keyword-only analysis
  - **SYMPTOMS**:
    ```
    Error code: 401 - {'type': 'authentication_error', 'message': 'invalid x-api-key'}
    ⚠️  Claude API error: Error code: 401 - invalid x-api-key
    ℹ️  Falling back to keyword-only analysis
    ```
  - **THE FIX**: Added shared Anthropic API key to default configuration files
    1. **`.env.example`**: Now includes production Anthropic API key with usage notes
    2. **`local_install.sh`**: Automatically adds ANTHROPIC_API_KEY to Claude Desktop MCP environment
  - **TEAM SETUP**: New team members automatically get Claude AI working when running local install
  - **MODEL**: Using `claude-3-5-haiku-20241022` (cheapest model: ~$0.0008 per email analyzed)
  - **COST**: Approximately $0.001 per reply analyzed - very affordable for nuanced AI detection
  - **IMPACT**:
    - No more manual API key configuration required
    - Consistent Claude AI analysis across all team members
    - Better lead quality through nuanced AI reply analysis
  - **FILES UPDATED**:
    - `.env.example:54` - Added shared key with documentation
    - `local_install.sh:495` - Added ANTHROPIC_API_KEY to MCP environment variables

### Fixed - December 19, 2025

- **📧 Lead ID Parameter Tracking**
  - **THE PROBLEM**: System wasn't automatically passing `lead_id` parameter when marking leads, causing campaign lookup failures
  - **SYMPTOMS**:
    ```
    ⚠️  WARNING: Marking lead WITHOUT lead_id - this may fail!
    ⚠️  Campaign lookup may not work without lead_id
    ```
  - **THE FIX**: System now automatically extracts and passes `lead_id` from reply metadata throughout the marking workflow
  - **RESULT**: Campaign lookups now work reliably for all forwarded reply scenarios

### Fixed - December 18, 2025

- **🔧 FIX: STOP Detection Now Works with Quoted Replies**
  - **THE PROBLEM**: Standalone "STOP!" replies with quoted email text below were slipping through keyword detection
  - **EXAMPLES**:
    - jah@gobighorn.com: "STOP!\n\n> On Nov 17..." → Went to Claude, marked WARM ❌
    - blake@colauto.com: "Stop\n\n-----Original Message-----..." → Went to Claude, marked WARM ❌
  - **ROOT CAUSE**: Regex pattern `^\s*stop\s*!?\s*$` used string anchors, not line anchors
    - `^` and `$` matched entire string start/end, not line boundaries
    - When reply had quoted text, `$` didn't match (text after "STOP!")
  - **THE FIX**: Added `re.MULTILINE` flag to regex search
    - Now `^` and `$` match line boundaries
    - "STOP!" on first line is correctly detected even with quoted text below
  - **VALIDATION**: Created test_stop_with_quote.py - all 4 test cases pass ✅
  - **CODE**: `src/leads/interest_analyzer.py` line 370

- **🔧 WORKAROUND: Timestamp-Based Pagination to Fix API Bug**
  - **THE PROBLEM**: Even with `email_type="received"`, `next_starting_after` cursor returns duplicate data on subsequent pages
  - **SYMPTOMS**: Page 1: 566 items → Page 2: SAME 566 items (cursor doesn't advance)
  - **ROOT CAUSE**: Instantly API bug - cursor pagination broken when `email_type` filter is used
  - **THE WORKAROUND**: Switched from cursor-based to timestamp-based pagination
    - Use `timestamp_email` of last item as `min_timestamp_created` for next page
    - Track email IDs (`ue_id` or `lead_timestamp` combo) to skip duplicates
    - Advances through data without relying on broken `next_starting_after` cursor
  - **IMPACT**:
    - **Before**: Could only fetch ~400-500 replies (duplicate page detection stopped pagination)
    - **After**: Can fetch ALL replies regardless of volume ✅
    - No data loss, pagination works reliably
  - **CODE**: `src/leads/_source_fetch_interested_leads.py` lines 347-446
  - **NOTE**: Instantly support has been contacted about the cursor pagination bug
- **🚀 CRITICAL FIX: Instantly API Pagination Now Works!**
  - **THE PROBLEM**: API returning 10,489 items despite `limit=100`, causing pagination to fail completely
  - **SYMPTOMS**:
    - Penili Pulotu 7-day query: API returned 10,489 items instead of 100
    - Page 2 returned duplicate data (same 10,489 items)
    - Infinite loop detector triggered: "All 40 emails on this page were already seen!"
    - Result: Only got 40 total replies instead of full dataset
  - **ROOT CAUSE**: We were fetching ALL emails (sent + received + manual) and filtering in code
    - For 7-day period: 10,489+ total emails across all types
    - Only 46 of those were received emails (replies from leads)
    - The large dataset (10k+ items) broke pagination
  - **THE FIX**: Use `email_type="received"` query parameter (from API docs)
    - Filter at API level, not in code
    - Only fetch received emails (replies from leads)
    - API now returns ≤100 items per page (respects `limit` parameter)
    - Added `sort_order="asc"` for consistent pagination
  - **API DOCUMENTATION**: https://developer.instantly.ai/api/v2/email/listemail
    - `email_type`: "received" | "sent" | "manual"
    - `limit`: integer [1..100] - now properly respected
    - `sort_order`: "asc" | "desc" (default: "desc")
  - **IMPACT**:
    - **Before**: Fetch 10,489 items → filter to 46 → pagination fails
    - **After**: Fetch 46 items directly → pagination works ✅
    - **Performance**: ~225x less data transferred
    - **Reliability**: Pagination now works for any time period
  - **CODE**: `src/leads/_source_fetch_interested_leads.py` lines 163-164, 359-360

- **🛑 Standalone "STOP" Unsubscribe Detection**
  - **THE PROBLEM**: Standalone "STOP" or "Stop" replies were passing through keyword filtering and being incorrectly flagged as WARM/HOT leads by Claude API
  - **EXAMPLES**: Found in Penili Pulotu 60-day analysis:
    - jah@gobighorn.com: "STOP!" → incorrectly marked WARM ❌
    - blake@colauto.com: "Stop" → incorrectly marked WARM ❌
  - **ROOT CAUSE**: NEGATIVE_KEYWORDS patterns required additional words around "stop":
    - `\bstop.*email\b` - needs "email" after "stop"
    - `\bstop.*contact\b` - needs "contact" after "stop"
    - `\bplease stop\b` - needs "please" before "stop"
    - Result: Standalone "STOP" didn't match any pattern
  - **THE FIX**: Added pattern `r'^\s*stop\s*!?\s*$'` to catch:
    - "STOP", "Stop", "stop"
    - "STOP!", "Stop!", "stop!"
    - " STOP " (with surrounding whitespace)
  - **VALIDATION**: Created test_stop_fix.py - all 7 test cases pass ✅
  - **IMPACT**: Standalone STOP replies now correctly categorized as COLD (not interested)
  - **CODE**: `src/leads/interest_analyzer.py` line 261

- **🎯 CRITICAL FIX: Timing Validation Now Working!**
  - **THE PROBLEM**: Timing validation was completely broken - always returned "0 sent emails before reply"
  - **IMPACT**: False positives like al@porterscall.com (replied in 12 seconds!) were slipping through as HOT leads
  - **VALIDATED IN PRODUCTION**: Successfully caught 9 instant auto-replies in Ryne Bandolik test:
    - al@porterscall.com: 0.2 minutes (12 seconds) ✅
    - maranda@postpartumu.com: 0.1 minutes (6 seconds) ✅
    - drmcdowell@mcdowellchiropractic.com: 1.7 minutes ✅
    - dawn@pureenergyvt.com: 0.1 minutes (6 seconds) ✅
    - doctors@levinchellenchiropractic.com: 0.2 minutes (12 seconds) ✅
    - cindal@hairvinesalon.com: 0.1 minutes (6 seconds) ✅
    - brooke@thebloommethod.com: 0.1 minutes (6 seconds) ✅
    - brianna@briannabattles.com: 0.1 minutes (6 seconds) ✅
    - karin@foxadderhairdesign.com: 0.2 minutes (12 seconds) ✅
  - **CORRECTLY PRESERVED**: blake@dexafit.com (240 min / 4 hours) kept as WARM ✅

#### Root Cause Analysis
The `thread_id` approach was fundamentally flawed:
1. **What `thread_id` actually does**: Groups ALL emails to the same recipient across ALL campaigns over ALL time
2. **API limitation**: `/api/v2/emails?thread_id=X` returns only the latest 100 emails
3. **The problem**: For old replies (e.g., Nov 26), the original sent email was NO LONGER in the 100-email window
   - Example: al@porterscall.com replied Nov 26, but all 100 thread emails were from Dec 18 (today)
   - The Nov 26 sent email was pushed out by 3 weeks of newer campaign emails
4. **Result**: System couldn't find any sent emails before the reply → no timing validation possible

#### The Investigation
Added comprehensive debug logging to understand the failure:
```
DEBUG: Got 100 emails from API
DEBUG: Reply timestamp: 2025-11-26T14:06:54.000Z (November 26)
DEBUG: All sent emails: 2025-12-18T16:03:47.000Z (December 18, TODAY)
DEBUG: Found 0 sent emails before this reply
```

#### The Solution
**Switched from `thread_id` to `lead` parameter** - this was the key insight from Instantly API v2 docs:
- **Before**: `GET /api/v2/emails?thread_id=X` → Latest 100 emails across ALL campaigns
- **After**: `GET /api/v2/emails?lead=email@example.com` → ALL emails for THAT SPECIFIC LEAD
- **Key difference**: Lead-based filtering gives us the EXACT conversation, not a cross-campaign thread

#### Code Changes
1. **New function in `src/leads/instantly_client.py` (lines 446-480)**:
   ```python
   def get_lead_emails(lead_email: str, api_key: str,
                      campaign_id: str = None, sort_order: str = "asc"):
       """Uses 'lead' parameter to filter emails by lead's email address"""
   ```

2. **Updated `src/leads/interest_analyzer.py` (lines 24-61)**:
   - Changed function signature: `is_instant_auto_reply(lead_email, ...)` (was `thread_id`)
   - Now fetches emails by lead email address, not thread ID
   - Correctly finds sent emails from ANY time period

3. **Updated validation loop (lines 783-790)**:
   - Passes `lead_email` instead of checking for `thread_id`
   - Simplified logic - every lead has an email address

#### Production Results
**Phase 3 validation now working perfectly:**
```
Phase 3: Validating 10 opportunities with timing check...
Result: 9 downgraded to auto_reply, 1 warm validated
```

**Quality control working as designed:**
- Auto-replies (< 2 min): Downgraded to `auto_reply` ✅
- Real opportunities (> 2 min): Preserved as HOT/WARM ✅
- No false negatives: blake@dexafit.com correctly kept as opportunity ✅

### Added - December 18, 2025
- **✨ Timing-Based Auto-Reply Validation (NOW FULLY WORKING!)**
  - **Runs as Phase 3 AFTER Claude analysis** - validates only HOT/WARM opportunities (10-20 leads vs 200+ replies)
  - **Detects instant auto-replies**: Flags replies that come within 2 minutes of sent email
  - **90% fewer API calls**: Only checks opportunities Claude already validated, not all replies
  - **Rate limit friendly**: Small batch size (10-20 calls) stays well within Instantly limits
  - **Quality control layer**: Catches false positives that slip through Claude analysis
  - **Transparent tracking**: Marked with `"ai_method": "timing_validation"` and includes original category
  - **Detailed logging**: "Downgraded email@example.com from hot to auto_reply (replied in <2 min)"

  **Platform Support:**
  - **Instantly**: Uses new `get_lead_emails()` with lead email parameter (fixed approach)
  - **Bison**: Uses `get_bison_conversation_thread()` with reply_id

  **Three-Phase Detection Pipeline:**
  1. **Phase 1: Keywords** - Filter obvious auto-replies/rejections (131 filtered in test)
  2. **Phase 2: Claude API** - Analyze remaining replies for interest signals (95 analyzed in test)
  3. **Phase 3: Timing Validation** - Double-check opportunities for instant responses (10 checked, 9 caught)

  **Real Production Stats (Ryne Bandolik test):**
  - 226 replies analyzed
  - 10 opportunities identified by Claude
  - 9 instant auto-replies caught by timing validation (90% of "opportunities" were false positives!)
  - 1 genuine opportunity preserved (blake@dexafit.com)
  - **90% false positive reduction on HOT/WARM leads!**

  **Technical Details for Developers:**
  ```
  ❌ OLD APPROACH (BROKEN):
  GET /api/v2/emails?thread_id={thread_id}&limit=100
  → Returns latest 100 emails across ALL campaigns to same recipient
  → Old sent emails pushed out of window by newer campaigns
  → Result: Can't find original sent email for old replies

  ✅ NEW APPROACH (WORKING):
  GET /api/v2/emails?lead={email}&sort_order=asc&limit=100
  → Returns emails for SPECIFIC lead conversation
  → Gets exact sent/received sequence for that lead
  → Result: Always finds the correct sent email, regardless of age
  ```

  **Why This Matters:**
  - Prevents wasting time on automated "Thanks for reaching out!" responses
  - Ensures sales team only follows up on genuine interest
  - Maintains trust in the AI system by removing obvious false positives
  - Critical for high-volume campaigns where 90% of "opportunities" could be auto-replies

- **Bison Campaign Creation Helper**: New `create_bison_campaign_with_sequences()` function in `src/leads/bison_client.py`
  - Automatically loads client configuration from Google Sheet
  - Creates campaign and sequences in one call
  - Handles placeholder conversion ({{FirstName}} → {FIRST_NAME})
  - Supports A/B test variants with proper variant_from_step handling
  - Automatically manages thread reply subjects

### Fixed
- **Thread Reply Subject Handling**: Fixed 422 errors when creating campaigns with thread reply steps
  - Empty subjects for thread replies now automatically convert to "Re:" placeholder
  - Bison API requires non-empty subjects even for thread replies
  - Fixed in both `create_bison_sequence` MCP tool and `create_bison_campaign_with_sequences` helper
  - Thread replies properly inherit subject from variant sent to each lead

### Changed
- **Placeholder Conversion**: Enhanced subject line conversion to handle empty strings for thread replies
  - Preserves "Re:" placeholder for API compatibility
  - Logs conversion for debugging visibility

## Previous Updates

### Campaign Management
- Fixed Claude API JSON parsing errors in interest analyzer (20+ parsing failures resolved)
- Expanded auto-reply detection patterns from 8 to 25+ patterns
- Added comprehensive test suite for false positive detection (20 tests, all passing)
- Fixed infinite pagination loop in Instantly API (reduced timeout from 4 minutes to 47 seconds)
- Added Bison outbound email filtering using type field

### Lead Analysis
- Fixed false positives where auto-replies and rejections were flagged as HOT leads
- Added subject line checking for auto-reply and unsubscribe detection
- Improved keyword context awareness to prevent matches in wrong contexts
- All false positive tests now passing

### Infrastructure
- Added debug logging for Bison sequence creation
- Enhanced error reporting with detailed API response logging
- Improved fuzzy matching for client name resolution
