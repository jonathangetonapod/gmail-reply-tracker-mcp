# Bison Sequence Upload Tool

## Overview

The `create_bison_sequence` tool automates uploading email sequences to Bison campaigns, eliminating the need to manually copy sequences, spintax, and configure each step.

## How to Use in Claude

Simply tell Claude to create a sequence for a Bison client. Claude will ask to confirm the campaign name before creating it.

### Example Prompts

**From formatted copy docs:**
```
"Upload these speaker outreach sequences to Michael Hernandez"

[Then paste your copy doc]
```

Claude will ask:
- "I see 3 variations. Should I upload these as separate sequences or as a 3-step sequence?"
- "What should I name the campaign? (default: 'Speaker Outreach')"

**From simple instructions:**
```
"Create a 3-step cold outreach sequence for Jeff Mikolai"
"Add sequences to Derek Hobbs' existing campaign 42"
```

### Important: A/B/C Variations

If you have multiple versions of Email 1 (like Version A, B, C), Claude will:
1. Ask how you want to handle them
2. Options:
   - **Separate campaigns:** Each variation gets its own campaign (best for true A/B testing)
   - **3-step sequence:** Upload as Email 1, 2, 3 (not recommended for variations)
   - **Pick one:** Choose which version to upload

## Working with Your Copy Docs

You can paste your formatted copy docs directly! Here's an example:

### Your Copy Doc Format
```
Campaign 1: Validation Fatigue
Audience: Medical Device QA/Regulatory Leaders

Email 1
Subject: Your validation cycle: 6 weeks or 6 days?
Hi [Name],
Most QA/RA teams spend 4-6 weeks on validation...
Best,

Email 2
Subject: Quick question
Hi [Name],
Quick question: what's your current timeline...
Best,
```

### Just Tell Claude:
```
"Upload this Validation Fatigue campaign to Jeff Mikolai's campaign 42,
set first email to wait 1 day, second email to wait 3 days and reply in thread"

[paste your copy doc above]
```

Claude will:
1. Parse your copy doc format
2. Extract subjects and bodies
3. Apply the wait times you specified
4. Configure thread replies
5. Upload to Bison automatically

## Real Example

**User:** "Upload this to Adam Mazel's campaign 15, first email wait 1 day, second wait 3 days in thread, third wait 5 days in thread"

**Paste:**
```
Campaign 2: Disconnected Systems
Audience: Operations Leaders

Email 1
Subject: Your ERP and QMS don't talk. Should they?
Hi [Name],
I'm guessing your team manually moves data between systems...
Cheers,

Email 2
Subject: Re: Your ERP and QMS don't talk. Should they?
Hi [Name],
Following up on system integration...
Best,

Email 3
Subject: Re: Your ERP and QMS don't talk. Should they?
Hi [Name],
Last follow-up...
Best,
```

**Claude will create:**
- Sequence title: "Disconnected Systems"
- 3 email steps with proper wait times
- Thread replies configured on emails 2 and 3
- All uploaded to campaign 15

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

## Example Sequence Format (JSON)

Here's what gets sent to the Bison API:

```json
{
  "client_name": "Jeff Mikolai",
  "campaign_id": 42,
  "sequence_title": "Validation Fatigue",
  "steps": [
    {
      "email_subject": "Your validation cycle: 6 weeks or 6 days?",
      "email_body": "Hi {FIRST_NAME},\n\nMost QA/RA teams spend 4-6 weeks on validation for every software update...\n\nBest,",
      "order": 1,
      "wait_in_days": 1,
      "thread_reply": false
    },
    {
      "email_subject": "Re: Your validation cycle: 6 weeks or 6 days?",
      "email_body": "Hi {FIRST_NAME},\n\nQuick question: what's your current timeline...\n\nBest,",
      "order": 2,
      "wait_in_days": 3,
      "thread_reply": true
    }
  ]
}
```

## Variables in Email Content

You can use Bison variables in your subject lines and email bodies. Claude will automatically convert common placeholders:

**Your copy docs:**
- `[Name]` → `{FIRST_NAME}`
- `[Company]` → `{COMPANY_NAME}`
- `[Title]` → `{TITLE}`

**Bison variables:**
- `{FIRST_NAME}` - Lead's first name
- `{LAST_NAME}` - Lead's last name
- `{COMPANY_NAME}` - Company name
- `{TITLE}` - Job title
- `{CUSTOM_FIELD}` - Any custom field you've set up

## Thread Replies

Claude automatically handles thread replies:
- **First email** (`order: 1`): `thread_reply: false`
- **Follow-ups** (`order: 2+`): `thread_reply: true` (if you mention "in thread")

## Typical Patterns

### Pattern 1: Simple 2-Step
```
"Upload this to [client] campaign [ID], first email wait 1 day, second wait 3 days in thread"
```

### Pattern 2: 3-Step Sequence
```
"Upload this to [client] campaign [ID]:
- Email 1: wait 1 day
- Email 2: wait 3 days, reply in thread
- Email 3: wait 5 days, reply in thread"
```

### Pattern 3: Multiple Campaigns
```
"Upload the Validation Fatigue campaign to campaign 42"
"Upload the Disconnected Systems campaign to campaign 43"
```

## Pro Tips

1. **Copy doc format works as-is**: Just paste your formatted campaigns directly
2. **Claude handles the parsing**: No need to manually format JSON
3. **Specify wait times**: Claude needs you to tell it the wait days (1, 3, 5, etc.)
4. **Thread replies**: Just say "reply in thread" or "in thread" for follow-ups
5. **Test first**: Upload to a test campaign first to verify formatting
6. **Batch upload**: You can upload multiple campaigns in one conversation

## Common Use Cases

### 1. Cold Outreach Sequence
```
"Upload this cold outreach to Jeff Mikolai campaign 42:
- Step 1: wait 1 day
- Step 2: wait 3 days in thread
- Step 3: wait 5 days in thread"

[paste your 3 emails]
```

### 2. Multiple Campaigns at Once
```
"I have 3 campaigns to upload to Adam Mazel's Bison.
Campaign 42: Validation Fatigue
Campaign 43: Disconnected Systems
Campaign 44: Compliance Burden

For all of them: first email 1 day, second 3 days thread, third 5 days thread"

[paste all your campaigns]
```

### 3. A/B Testing Different Campaigns
```
"Upload both of these as separate sequences to campaign 42:
- Title the first one 'Version A - Validation Fatigue'
- Title the second one 'Version B - Validation Fatigue'"

[paste both versions]
```

## Response Format

Success response:
```json
{
  "success": true,
  "message": "Successfully created sequence 'Validation Fatigue' with 3 steps",
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

## Troubleshooting

**"Client not found" error:**
- Check the exact spelling of the client name
- Try using just the first name: "Jeff" instead of "Jeff Mikolai"
- Ask Claude: "What Bison clients do we have?" to see the exact names

**"Invalid campaign_id" error:**
- Verify the campaign ID exists in Bison
- Check that the campaign belongs to the specified client
- Campaign IDs are numbers, not names

**"Unauthorized" error:**
- The client's API key may be expired or invalid
- Contact admin to update the API key in the Google Sheet

**Formatting issues:**
- Make sure email subjects are clear (Claude will extract them)
- If Claude misses something, be more explicit: "Subject line is: X"
- You can always review what Claude parsed before it uploads

## Full Workflow Example

```
You: "I need to upload 2 campaigns for Jeff Mikolai"

Claude: "Sure! What are the campaign IDs and what are the sequences?"

You: "Campaign 42 for Validation Fatigue, Campaign 43 for Disconnected Systems.
For both: first email 1 day, second 3 days thread, third 5 days thread"

[paste your copy docs]

Claude: [Parses both campaigns, shows you the summary, asks for confirmation]

You: "Looks good, upload them"

Claude: [Uploads both sequences]
"✅ Successfully created 'Validation Fatigue' sequence (3 steps) in campaign 42
✅ Successfully created 'Disconnected Systems' sequence (3 steps) in campaign 43"
```

## Technical Details

This tool:
1. Looks up the client's API key from the Bison Google Sheet
2. Calls the Bison API: `POST /api/campaigns/v1.1/{campaign_id}/sequence-steps`
3. Creates all sequence steps in a single API call
4. Returns the sequence ID and confirmation

API Endpoint: `https://send.leadgenjay.com/api/campaigns/v1.1/{campaign_id}/sequence-steps`

## Need Help?

Ask Claude:
- "Show me all Bison clients" - See available clients
- "What campaigns does Jeff Mikolai have?" - See campaign IDs (if you have that data)
- "Can you parse this sequence first before uploading?" - Preview what will be uploaded
