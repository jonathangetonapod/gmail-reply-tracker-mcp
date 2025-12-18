# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
