# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Timing Validation Bug**: Fixed critical bug where timing validation always returned "0 sent emails before reply"
  - **Root Cause**: Using `thread_id` parameter fetched latest 100 emails across ALL campaigns to same recipient
  - Old sent emails (weeks ago) were pushed out of 100-email window by newer campaign emails
  - **Solution**: Switch from `thread_id` to `lead` parameter to filter emails by lead's email address
  - Now correctly finds sent emails before replies for accurate timing detection
  - Added new `get_lead_emails()` function in `instantly_client.py`
  - Updated `is_instant_auto_reply()` to use `lead_email` instead of `thread_id`

### Added
- **Timing-Based Auto-Reply Validation**: Post-Claude validation to catch automated responses
  - **Runs as Phase 3 AFTER Claude analysis** (validates HOT/WARM opportunities only)
  - Detects replies that come within 2 minutes of sent email (highly likely automated)
  - **Works with both Instantly and Bison platforms** via platform-specific thread APIs
  - Instantly: uses `get_thread_emails()` with thread_id
  - Bison: uses `get_bison_conversation_thread()` with reply_id
  - **90% fewer API calls**: Only checks 10-20 opportunities vs 200+ replies
  - **Rate limit friendly**: Small batch size stays well within Instantly limits
  - **Quality control**: Downgrades false positives (e.g., "Thanks!" automated responses)
  - **Transparent tracking**: Marked with `"ai_method": "timing_validation"` and includes original category
  - Logs all downgrades: "Downgraded email@example.com from hot to auto_reply"
  - Added `is_instant_auto_reply()` and `is_bison_instant_auto_reply()` functions
  - Three-phase detection: keywords → Claude API → timing validation

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
