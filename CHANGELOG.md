# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed - December 18, 2025
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
