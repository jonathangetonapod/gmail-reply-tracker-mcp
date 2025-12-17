# Bison Sequence Upload Tool

## Overview

The `create_bison_sequence` tool automates uploading email sequences to Bison campaigns, eliminating the need to manually copy sequences, spintax, and configure each step.

## How to Use in Claude

Simply tell Claude to create a sequence for a Bison client. Claude will use the `create_bison_sequence` tool automatically.

### Example Prompts

```
"Create a 3-step cold outreach sequence for Jeff Mikolai's campaign ID 42"

"Upload this email sequence to Adam Mazel's Bison campaign 15:
- Step 1: Introduction email with subject 'Quick question about [COMPANY]'
- Step 2: Follow-up after 3 days
- Step 3: Final touch after 5 days"

"Add a new sequence titled 'Q1 2025 Outreach' to Derek Hobbs' campaign 8"
```

## Tool Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `client_name` | string | Yes | Name of the Bison client (e.g., "Jeff Mikolai") |
| `campaign_id` | number | Yes | The Bison campaign ID |
| `sequence_title` | string | Yes | Title for the sequence |
| `steps` | array | Yes | Array of 2-3 email sequence steps |

### Step Object Parameters

Each step in the `steps` array should have:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email_subject` | string | Yes | Subject line |
| `email_body` | string | Yes | Email body content |
| `order` | number | Yes | Step order (1, 2, 3, etc.) |
| `wait_in_days` | number | Yes | Days to wait before sending |
| `thread_reply` | boolean | No | Reply in same thread (default: false) |
| `variant` | boolean | No | Whether this is a variant (default: false) |
| `variant_from_step` | number | No | Which step this is a variant of |

## Example Sequence Format

Here's what a typical 3-step cold outreach sequence looks like:

```json
{
  "client_name": "Jeff Mikolai",
  "campaign_id": 42,
  "sequence_title": "Cold Outreach - V2",
  "steps": [
    {
      "email_subject": "Quick question about {COMPANY_NAME}",
      "email_body": "Hi {FIRST_NAME},\n\nI noticed your company is in the [industry] space...\n\nBest,\nJohn",
      "order": 1,
      "wait_in_days": 1,
      "thread_reply": false
    },
    {
      "email_subject": "Re: Quick question about {COMPANY_NAME}",
      "email_body": "Hi {FIRST_NAME},\n\nJust following up on my previous email...",
      "order": 2,
      "wait_in_days": 3,
      "thread_reply": true
    },
    {
      "email_subject": "Re: Quick question about {COMPANY_NAME}",
      "email_body": "Hi {FIRST_NAME},\n\nOne final follow-up before I close this out...",
      "order": 3,
      "wait_in_days": 5,
      "thread_reply": true
    }
  ]
}
```

## Variables in Email Content

You can use Bison variables in your subject lines and email bodies:

- `{FIRST_NAME}` - Lead's first name
- `{LAST_NAME}` - Lead's last name
- `{COMPANY_NAME}` - Company name
- `{CUSTOM_FIELD}` - Any custom field you've set up

## Thread Replies

- **First email** (`order: 1`): Set `thread_reply: false`
- **Follow-ups** (`order: 2+`): Set `thread_reply: true` to reply in the same thread

## Variants (A/B Testing)

To create A/B test variants:

```json
{
  "steps": [
    {
      "email_subject": "Version A subject",
      "order": 1,
      "variant": false,
      ...
    },
    {
      "email_subject": "Version B subject",
      "order": 1,
      "variant": true,
      "variant_from_step": 1,
      ...
    }
  ]
}
```

## Response Format

Success response:
```json
{
  "success": true,
  "message": "Successfully created sequence 'Cold Outreach - V2' with 3 steps",
  "sequence_id": 123,
  "steps_created": 3
}
```

Error response:
```json
{
  "success": false,
  "error": "Client 'Unknown Client' not found"
}
```

## Tips

1. **Test first**: Always test with a small sequence (1-2 steps) before uploading long sequences
2. **Check campaign ID**: Make sure you have the correct campaign ID from Bison
3. **Variables**: Use Bison's variable syntax `{VARIABLE_NAME}` in all caps
4. **Wait times**: Typical wait times are 1-5 days between steps
5. **Client names**: Use exact client names as they appear in the Bison sheet

## Common Use Cases

### 1. Cold Outreach Sequence
- Step 1: Initial introduction (wait 1 day)
- Step 2: Value proposition follow-up (wait 3 days)
- Step 3: Final breakup email (wait 5 days)

### 2. Warm Follow-up Sequence
- Step 1: Reference previous conversation (wait 2 days)
- Step 2: Share case study/resource (wait 4 days)

### 3. Event Invitation Sequence
- Step 1: Event invitation (wait 1 day)
- Step 2: Event reminder (wait 2 days)
- Step 3: Last chance to register (wait 1 day)

## Troubleshooting

**"Client not found" error:**
- Check the exact spelling of the client name
- Try using just the first name: "Jeff" instead of "Jeff Mikolai"

**"Invalid campaign_id" error:**
- Verify the campaign ID exists in Bison
- Check that the campaign belongs to the specified client

**"Unauthorized" error:**
- The client's API key may be expired or invalid
- Contact admin to update the API key in the Google Sheet

## Technical Details

This tool:
1. Looks up the client's API key from the Bison Google Sheet
2. Calls the Bison API: `POST /api/campaigns/v1.1/{campaign_id}/sequence-steps`
3. Creates all sequence steps in a single API call
4. Returns the sequence ID and confirmation

API Endpoint: `https://send.leadgenjay.com/api/campaigns/v1.1/{campaign_id}/sequence-steps`
