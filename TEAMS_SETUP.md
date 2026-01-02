# 🚀 Team Functionality Setup Guide

## Overview

Team functionality allows multiple users to share subscriptions under one billing account. The team owner pays for tool categories, and all team members get access.

## Benefits

- **Cost Savings**: One subscription covers entire team (vs per-user pricing)
- **Centralized Billing**: Owner manages subscriptions for whole team
- **Easy Onboarding**: Invite members via email, they join instantly
- **Secure**: Per-user OAuth preserved, data isolation maintained

## Architecture

```
TEAM STRUCTURE:
- Owner: Creates team, manages billing, cannot be removed
- Admin: Can invite/remove members (future feature)
- Member: Can use all team subscriptions

SUBSCRIPTIONS:
- Personal: User subscribes individually
- Team: Owner subscribes for entire team

ACCESS CONTROL:
User has access to a tool if:
  ✅ They have a personal subscription, OR
  ✅ They belong to a team with that subscription
```

## Step 1: Run Database Migration

### Go to Supabase SQL Editor

1. Open your Supabase project: https://supabase.com/dashboard
2. Click "SQL Editor" in left sidebar
3. Click "New Query"
4. Copy the contents of `add_teams_schema.sql`
5. Paste into SQL Editor
6. Click "Run" (or press Cmd/Ctrl + Enter)

### Expected Output

```
✅ Team functionality schema created successfully!
   - Teams table created
   - Team members table created
   - Team invitations table created
   - Subscriptions table updated for team support
   - Indexes created for performance
   - RLS policies enabled for security
   - Helper functions created
```

### Verify Tables Were Created

Run this query to verify:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN ('teams', 'team_members', 'team_invitations');
```

You should see 3 rows returned.

## Step 2: Verify Database Methods

The following methods are now available in `database.py`:

```python
# Team CRUD
db.create_team(team_name, owner_user_id, billing_email)
db.get_user_teams(user_id)
db.get_team_members(team_id)

# Invitations
db.invite_team_member(team_id, email, invited_by_user_id)
db.get_team_invitation(invitation_id)
db.accept_team_invitation(invitation_id, user_id)

# Member Management
db.remove_team_member(team_id, user_id, removed_by_user_id)

# Subscriptions
db.get_team_subscriptions(team_id)
db.get_user_all_subscriptions(user_id)  # Personal + Team
db.create_team_subscription(team_id, tool_category, ...)
```

## Step 3: Test Basic Functionality (Optional)

### Create a Test Team

Run this in Supabase SQL Editor to create a test team:

```sql
-- Replace with your actual user_id
INSERT INTO teams (team_id, team_name, owner_user_id, billing_email)
VALUES ('team_test123', 'Test Team', 'YOUR_USER_ID', 'test@example.com');

-- Add owner as team member
INSERT INTO team_members (team_id, user_id, role)
VALUES ('team_test123', 'YOUR_USER_ID', 'owner');
```

### Verify Team Was Created

```sql
SELECT * FROM teams WHERE team_id = 'team_test123';
SELECT * FROM team_members WHERE team_id = 'team_test123';
```

### Create a Test Team Subscription

```sql
INSERT INTO subscriptions (
    team_id,
    tool_category,
    status,
    is_team_subscription
) VALUES (
    'team_test123',
    'gmail',
    'active',
    TRUE
);
```

### Verify User Has Access

```sql
-- Check if user has access to gmail through team
SELECT user_has_tool_access('YOUR_USER_ID', 'gmail');
-- Should return TRUE

-- Get all team subscriptions for user
SELECT * FROM get_user_team_subscriptions('YOUR_USER_ID');
-- Should return gmail subscription with team name
```

### Clean Up Test Data

```sql
DELETE FROM subscriptions WHERE team_id = 'team_test123';
DELETE FROM team_members WHERE team_id = 'team_test123';
DELETE FROM teams WHERE team_id = 'team_test123';
```

## Step 4: Next Development Steps

Now that the database layer is ready, here's what's next:

### A. API Endpoints (In Progress)
- [ ] POST /teams - Create team
- [ ] GET /teams - List user's teams
- [ ] GET /teams/{team_id} - Get team details
- [ ] POST /teams/{team_id}/invite - Invite member
- [ ] GET /invitations/{invitation_id} - View invitation
- [ ] POST /invitations/{invitation_id}/accept - Accept invitation
- [ ] DELETE /teams/{team_id}/members/{user_id} - Remove member

### B. Dashboard UI
- [ ] "Create Team" button in dashboard
- [ ] Team settings page (members, subscriptions)
- [ ] Invitation acceptance page
- [ ] Team switcher dropdown
- [ ] Team billing management

### C. RequestContext Update
- [ ] Check team subscriptions in addition to personal
- [ ] Use `get_user_all_subscriptions()` instead of `get_active_subscriptions()`

### D. Stripe Integration
- [ ] Team Stripe customers (separate from personal)
- [ ] Team subscription checkout
- [ ] Team billing portal

## Database Schema Diagram

```
┌─────────────────┐
│     teams       │
├─────────────────┤
│ team_id (PK)    │
│ team_name       │
│ owner_user_id   │─────┐
│ stripe_cust_id  │     │
│ billing_email   │     │
└─────────────────┘     │
         │              │
         │              │
         │              │
    ┌────▼──────────────▼───┐
    │   team_members        │
    ├───────────────────────┤
    │ team_id (FK)          │
    │ user_id (FK) ──────┐  │
    │ role               │  │
    │ joined_at          │  │
    └────────────────────│──┘
                         │
                         │
                    ┌────▼─────┐
                    │  users   │
                    └──────────┘

┌────────────────────────┐
│  team_invitations      │
├────────────────────────┤
│ invitation_id (PK)     │
│ team_id (FK)           │
│ email                  │
│ invited_by_user_id(FK) │
│ status                 │
│ expires_at             │
└────────────────────────┘

┌────────────────────────┐
│    subscriptions       │
├────────────────────────┤
│ id (PK)                │
│ user_id (FK) ────────┐ │
│ team_id (FK) ────┐   │ │
│ tool_category    │   │ │
│ status           │   │ │
│ is_team_sub      │   │ │
└──────────────────│───│─┘
                   │   │
                   │   └─> Personal subscription
                   └────> Team subscription
```

## Pricing Model

```
INDIVIDUAL PRICING:
- User subscribes: $5/category/month
- Only that user has access

TEAM PRICING:
- Owner subscribes: $5/category/month
- ALL team members have access

EXAMPLE:
Team of 5 people:
- Gmail subscription: $5/month
- All 5 people can use Gmail tools
- Savings: $20/month (80% off vs individual subscriptions)
```

## Security Features

✅ **Row Level Security (RLS)** - Users can only see teams they belong to
✅ **Role-based permissions** - Only owners/admins can manage members
✅ **Invitation expiry** - Invitations expire after 7 days
✅ **Cannot remove owner** - Team owner cannot be removed
✅ **Per-user OAuth** - Each user still uses their own Google account
✅ **Data isolation** - Team subscriptions don't expose user data

## Troubleshooting

### "relation 'teams' does not exist"
- You haven't run the SQL migration yet
- Go to Step 1 and run `add_teams_schema.sql`

### "column 'team_id' does not exist in subscriptions"
- The migration didn't complete successfully
- Drop the tables and re-run migration:
```sql
DROP TABLE IF EXISTS team_invitations CASCADE;
DROP TABLE IF EXISTS team_members CASCADE;
DROP TABLE IF EXISTS teams CASCADE;
-- Then run add_teams_schema.sql again
```

### RLS policies blocking queries
- Make sure you're using the service role key (not anon key)
- Service role key bypasses RLS policies

## Questions?

Common questions about team functionality:

**Q: Can a user be in multiple teams?**
A: Yes! Users can be members of multiple teams simultaneously.

**Q: Can teams share personal subscriptions?**
A: No. Personal subscriptions are user-specific. Team subscriptions are team-wide.

**Q: What happens if user leaves team?**
A: They lose access to team subscriptions but keep their personal subscriptions.

**Q: Can team owner transfer ownership?**
A: Not yet - this feature is planned for future release.

**Q: Is there a team size limit?**
A: No! Teams can have unlimited members.

---

**Status:** ✅ Database layer complete
**Next:** API endpoints and dashboard UI
**ETA:** API endpoints ready within 2-3 hours
