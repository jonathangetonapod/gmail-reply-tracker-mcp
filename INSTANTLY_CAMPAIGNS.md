# Instantly Campaign Creation Tool

## Overview

The `create_instantly_campaign` tool automates creating campaigns in Instantly.ai with sequences, scheduling, and A/B testing - no manual setup in the UI needed.

## How to Use in Claude

Simply tell Claude to create an Instantly campaign. Claude will handle the API integration automatically.

### Example Prompts

**Basic campaign:**
```
"Create an Instantly campaign for [client name]:
- Campaign name: Speaker Outreach 2025
- Email 1: [paste email copy]
- Email 2: [paste follow-up] (wait 72 hours)
- Email 3: [paste final follow-up] (wait 120 hours)"
```

**With A/B testing:**
```
"Create an Instantly campaign for [client name] with A/B testing:
- Campaign name: Outreach Test
- Email 1A: [version A copy]
- Email 1B: [version B copy]
- Email 1C: [version C copy]
- Email 2: [same for all] (wait 48 hours)"
```

**Custom settings:**
```
"Create an Instantly campaign for [client name]:
- Campaign name: Weekend Outreach
- Send 7 days/week including weekends
- Daily limit: 100 emails
- Timezone: America/Chicago
- Hours: 8am-6pm
- Text-only emails
- [paste sequences]"
```

## Tool Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `client_name` | string | Yes | - | Name of Instantly client |
| `campaign_name` | string | Yes | - | Campaign name |
| `steps` | array | Yes | - | Email sequence steps (1-3 typically) |
| `email_accounts` | array | No | None | List of email addresses to send from |
| `daily_limit` | number | No | 50 | Daily emails per account |
| `timezone` | string | No | America/Chicago | Schedule timezone (see list below) |
| `schedule_from` | string | No | 09:00 | Start time (HH:MM) |
| `schedule_to` | string | No | 17:00 | End time (HH:MM) |
| `stop_on_reply` | boolean | No | true | Stop when lead replies |
| `text_only` | boolean | No | false | Send as plain text |

### Step Object Parameters

Each step in `steps` array:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `subject` | string | Yes | Email subject line |
| `body` | string | Yes | Email body content |
| `wait` | number | No | Hours to wait before sending (0 for first email) |
| `variants` | array | No | A/B test variants (each with subject/body) |

## Valid Timezones

Instantly API supports these specific timezones:

### Americas
- `America/Anchorage` - Alaska
- `America/Dawson` - Yukon
- `America/Creston` - Mountain (no DST)
- `America/Chihuahua` - Mexican Mountain
- `America/Boise` - Mountain
- `America/Belize` - Central (no DST)
- `America/Chicago` - Central (default)
- `America/Bahia_Banderas` - Mexican Central
- `America/Regina` - Central (no DST)
- `America/Bogota` - Colombia
- `America/Detroit` - Eastern
- `America/Indiana/Marengo` - Eastern
- `America/Caracas` - Venezuela
- `America/Asuncion` - Paraguay
- `America/Glace_Bay` - Atlantic
- `America/Campo_Grande` - Amazon
- `America/Anguilla` - Atlantic
- `America/Santiago` - Chile
- `America/St_Johns` - Newfoundland
- `America/Sao_Paulo` - Brasilia
- `America/Argentina/La_Rioja` - Argentina
- `America/Araguaina` - Brasilia
- `America/Godthab` - West Greenland
- `America/Montevideo` - Uruguay
- `America/Bahia` - Brasilia
- `America/Noronha` - Fernando de Noronha
- `America/Scoresbysund` - East Greenland
- `America/Danmarkshavn` - GMT

### Atlantic & Africa
- `Atlantic/Cape_Verde` - Cape Verde
- `Atlantic/Canary` - Canary Islands
- `Africa/Casablanca` - Morocco
- `Africa/Abidjan` - West Africa
- `Africa/Ceuta` - North Africa
- `Africa/Algiers` - Central Africa
- `Africa/Windhoek` - Namibia
- `Africa/Cairo` - Egypt
- `Africa/Blantyre` - Central Africa
- `Africa/Tripoli` - Libya
- `Africa/Addis_Ababa` - East Africa

### Europe
- `Europe/Isle_of_Man` - UK
- `Europe/Belgrade` - Central Europe
- `Europe/Sarajevo` - Central Europe
- `Europe/Bucharest` - Eastern Europe
- `Europe/Helsinki` - Eastern Europe
- `Europe/Istanbul` - Turkey
- `Europe/Kaliningrad` - Russia
- `Europe/Kirov` - Russia
- `Europe/Astrakhan` - Russia
- `Arctic/Longyearbyen` - Svalbard

### Asia
- `Asia/Nicosia` - Cyprus
- `Asia/Beirut` - Lebanon
- `Asia/Damascus` - Syria
- `Asia/Jerusalem` - Israel
- `Asia/Amman` - Jordan
- `Asia/Baghdad` - Iraq
- `Asia/Aden` - Yemen
- `Asia/Tehran` - Iran
- `Asia/Dubai` - UAE
- `Asia/Baku` - Azerbaijan
- `Asia/Tbilisi` - Georgia
- `Asia/Yerevan` - Armenia
- `Asia/Kabul` - Afghanistan
- `Asia/Yekaterinburg` - Russia
- `Asia/Karachi` - Pakistan
- `Asia/Kolkata` - India
- `Asia/Colombo` - Sri Lanka
- `Asia/Kathmandu` - Nepal
- `Asia/Dhaka` - Bangladesh
- `Asia/Rangoon` - Myanmar
- `Asia/Novokuznetsk` - Russia
- `Asia/Hong_Kong` - Hong Kong
- `Asia/Krasnoyarsk` - Russia
- `Asia/Brunei` - Brunei
- `Asia/Taipei` - Taiwan
- `Asia/Choibalsan` - Mongolia
- `Asia/Irkutsk` - Russia
- `Asia/Dili` - East Timor
- `Asia/Pyongyang` - North Korea
- `Asia/Chita` - Russia
- `Asia/Sakhalin` - Russia
- `Asia/Anadyr` - Russia
- `Asia/Kamchatka` - Russia

### Australia & Pacific
- `Australia/Perth` - Western Australia
- `Australia/Adelaide` - South Australia
- `Australia/Darwin` - Northern Territory
- `Australia/Brisbane` - Queensland
- `Australia/Melbourne` - Victoria
- `Australia/Currie` - Tasmania
- `Pacific/Auckland` - New Zealand
- `Pacific/Fiji` - Fiji
- `Pacific/Apia` - Samoa

### Antarctica & Indian Ocean
- `Antarctica/Mawson` - Mawson Station
- `Antarctica/Vostok` - Vostok Station
- `Antarctica/Davis` - Davis Station
- `Antarctica/DumontDUrville` - Dumont d'Urville
- `Antarctica/Macquarie` - Macquarie Island
- `Indian/Mahe` - Seychelles

### GMT Offsets
- `Etc/GMT+12` to `Etc/GMT-13` - Fixed offsets

**Note:** Common timezones like `America/New_York`, `America/Los_Angeles`, `America/Denver`, `US/Pacific`, `US/Eastern`, etc. are NOT supported. Use the specific timezones from the list above.

## Sequence Structure

### Wait Times (in hours)
- First email: `wait: 0` (sends immediately)
- Follow-up emails: Use hours (24h = 1 day, 72h = 3 days, 120h = 5 days)

### Example: 3-Step Sequence
```json
{
  "steps": [
    {
      "subject": "Initial outreach",
      "body": "Hey {{first_name}}, ...",
      "wait": 0
    },
    {
      "subject": "Re: Initial outreach",
      "body": "Following up {{first_name}}...",
      "wait": 72  // 3 days after Email 1
    },
    {
      "subject": "Re: Initial outreach",
      "body": "Last follow-up {{first_name}}...",
      "wait": 120  // 5 days after Email 1 (2 days after Email 2)
    }
  ]
}
```

## A/B Testing

Add variants to test multiple versions:

```json
{
  "steps": [
    {
      "subject": "Version A subject",
      "body": "Hey {{first_name}}, version A...",
      "wait": 0,
      "variants": [
        {
          "subject": "Version B subject",
          "body": "Hi {{first_name}}, version B..."
        },
        {
          "subject": "Version C subject",
          "body": "Hello {{first_name}}, version C..."
        }
      ]
    },
    {
      "subject": "Same follow-up for all",
      "body": "All variants get this follow-up...",
      "wait": 48
    }
  ]
}
```

Instantly will randomly send A, B, or C to each lead, then send the same follow-up to everyone.

## Placeholders

Instantly uses double curly braces for variables:

- `{{first_name}}` - Lead's first name
- `{{last_name}}` - Lead's last name
- `{{company}}` - Company name
- `{{title}}` - Job title
- `{{email}}` - Email address
- `{{custom_field}}` - Any custom field

**Important:** Use `{{first_name}}` (double braces), NOT `{FIRST_NAME}` (single braces with caps). Claude will auto-convert if you use the wrong format.

## Schedule Configuration

### Days of Week

Control which days to send:

```json
{
  "0": false,  // Sunday
  "1": true,   // Monday
  "2": true,   // Tuesday
  "3": true,   // Wednesday
  "4": true,   // Thursday
  "5": true,   // Friday
  "6": false   // Saturday
}
```

Default: Mon-Fri only

### Time Windows

- `schedule_from`: Start time (e.g., "09:00", "08:00")
- `schedule_to`: End time (e.g., "17:00", "18:00")
- Use 24-hour format (HH:MM)

## Common Use Cases

### 1. Simple Cold Outreach
```
"Create Instantly campaign for Jane Doe:
- Campaign: Cold Outreach Q1
- Email 1: [paste initial email]
- Email 2: [paste follow-up] (wait 48 hours)
- Daily limit: 30"
```

### 2. A/B Testing
```
"Create Instantly campaign for Jane Doe with 3 variants:
- Campaign: A/B Test Outreach
- Test subject lines: 'Quick question', 'Collaboration opportunity', 'Thoughts?'
- Same body for all variants: [paste email]
- Follow-up after 72 hours: [paste follow-up]"
```

### 3. Weekend Sending
```
"Create Instantly campaign for Jane Doe:
- Campaign: 7-Day Outreach
- Send 7 days/week including weekends
- Daily limit: 50
- [paste sequences]"
```

### 4. Text-Only Campaign
```
"Create Instantly campaign for Jane Doe:
- Campaign: Plain Text Outreach
- Text-only emails (no HTML)
- [paste sequences]"
```

### 5. Custom Timezone & Hours
```
"Create Instantly campaign for Jane Doe:
- Campaign: West Coast Outreach
- Timezone: Australia/Sydney
- Hours: 8am-6pm
- [paste sequences]"
```

## Response Format

Success:
```json
{
  "success": true,
  "message": "Successfully created campaign 'Speaker Outreach' with 3 steps",
  "campaign_id": "uuid-here",
  "campaign_name": "Speaker Outreach",
  "steps_created": 3
}
```

Error:
```json
{
  "success": false,
  "error": "Client 'Unknown Client' not found"
}
```

## Testing Results

All 9 scenarios tested successfully:

1. ✅ Single email campaign
2. ✅ Full 3-step sequence
3. ✅ A/B test variants (3 versions)
4. ✅ Full content preservation (549+ chars with signature)
5. ✅ Custom schedule (different timezone & hours)
6. ✅ Weekend sending (7 days/week)
7. ✅ Text-only emails
8. ✅ First email text-only, follow-ups HTML
9. ✅ Continue on reply (don't stop sequence)

## Troubleshooting

**"Client not found" error:**
- Check exact spelling of client name
- Try first name only: "Jane" instead of "Jane Doe"
- Ask Claude: "What Instantly clients do we have?"

**"Invalid timezone" error:**
- Must use exact timezone from list above
- Common names like "America/New_York" are NOT valid
- Use "America/Chicago" for Central, "America/Detroit" for Eastern

**"Unauthorized" error:**
- Client's API key may be expired
- Contact admin to update API key in Google Sheet

## Technical Details

- **API Endpoint:** `https://api.instantly.ai/api/v2/campaigns`
- **Method:** POST
- **Authentication:** Bearer token (API key from Google Sheet)
- **Rate Limits:** Handled by Instantly API
- **Multi-tenant:** Supports 64+ client workspaces

## Differences from Bison

| Feature | Instantly | Bison |
|---------|-----------|-------|
| Wait times | Hours (72h = 3 days) | Days (3 = 3 days) |
| Placeholders | `{{first_name}}` | `{FIRST_NAME}` |
| A/B testing | Built-in variants array | Separate API calls |
| Schedule | Required (timezone + hours) | Optional |
| Default limit | 50/day | No default |
| Campaign creation | Single API call | Multiple calls for variants |

## Pro Tips

1. **Always test first:** Create a test campaign before production
2. **Use conservative limits:** Start with 25-30/day
3. **Validate timezones:** Use exact strings from the timezone list
4. **Check placeholders:** Use `{{first_name}}` not `{FIRST_NAME}`
5. **Wait times in hours:** 24h = 1 day, 72h = 3 days, 120h = 5 days
6. **Weekend sending:** Explicitly set days array for 7-day sending
7. **Content preservation:** Tool preserves full email content including signatures

## Need Help?

Ask Claude:
- "Show me all Instantly clients"
- "What timezones are supported?"
- "Parse this campaign before uploading"
- "Test this campaign structure"
