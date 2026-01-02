-- ============================================================================
-- TEAM FUNCTIONALITY DATABASE SCHEMA
-- ============================================================================
-- Run this in Supabase SQL Editor to add team functionality
-- ============================================================================

-- Teams table
CREATE TABLE IF NOT EXISTS teams (
    team_id TEXT PRIMARY KEY DEFAULT ('team_' || substr(md5(random()::text), 1, 16)),
    team_name TEXT NOT NULL,
    owner_user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    stripe_customer_id TEXT,
    billing_email TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Team members table (junction table)
CREATE TABLE IF NOT EXISTS team_members (
    team_id TEXT NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (team_id, user_id)
);

-- Team invitations table
CREATE TABLE IF NOT EXISTS team_invitations (
    invitation_id TEXT PRIMARY KEY DEFAULT ('inv_' || substr(md5(random()::text), 1, 20)),
    team_id TEXT NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    invited_by_user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'expired', 'declined')),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days'),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    accepted_at TIMESTAMPTZ
);

-- Add team support to subscriptions table
ALTER TABLE subscriptions
ADD COLUMN IF NOT EXISTS team_id TEXT REFERENCES teams(team_id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS is_team_subscription BOOLEAN DEFAULT FALSE;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_teams_owner ON teams(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_teams_stripe_customer ON teams(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_team_members_user ON team_members(user_id);
CREATE INDEX IF NOT EXISTS idx_team_members_team ON team_members(team_id);
CREATE INDEX IF NOT EXISTS idx_team_invitations_email ON team_invitations(email);
CREATE INDEX IF NOT EXISTS idx_team_invitations_team ON team_invitations(team_id);
CREATE INDEX IF NOT EXISTS idx_team_invitations_status ON team_invitations(status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_team ON subscriptions(team_id);

-- Row Level Security (RLS) policies
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_invitations ENABLE ROW LEVEL SECURITY;

-- Policy: Users can see teams they're members of
CREATE POLICY "Users can view teams they belong to"
    ON teams FOR SELECT
    USING (
        team_id IN (
            SELECT team_id FROM team_members WHERE user_id = auth.uid()::text
        )
    );

-- Policy: Only owners can update teams
CREATE POLICY "Team owners can update their teams"
    ON teams FOR UPDATE
    USING (owner_user_id = auth.uid()::text);

-- Policy: Only owners can delete teams
CREATE POLICY "Team owners can delete their teams"
    ON teams FOR DELETE
    USING (owner_user_id = auth.uid()::text);

-- Policy: Users can view team members of their teams
CREATE POLICY "Users can view members of their teams"
    ON team_members FOR SELECT
    USING (
        team_id IN (
            SELECT team_id FROM team_members WHERE user_id = auth.uid()::text
        )
    );

-- Policy: Team owners and admins can manage members
CREATE POLICY "Team owners and admins can manage members"
    ON team_members FOR ALL
    USING (
        team_id IN (
            SELECT team_id FROM team_members
            WHERE user_id = auth.uid()::text
            AND role IN ('owner', 'admin')
        )
    );

-- Policy: Users can view invitations sent to their email
CREATE POLICY "Users can view invitations to their email"
    ON team_invitations FOR SELECT
    USING (email = auth.email() OR invited_by_user_id = auth.uid()::text);

-- Policy: Team owners and admins can create invitations
CREATE POLICY "Team owners and admins can create invitations"
    ON team_invitations FOR INSERT
    WITH CHECK (
        team_id IN (
            SELECT team_id FROM team_members
            WHERE user_id = auth.uid()::text
            AND role IN ('owner', 'admin')
        )
    );

-- Comments for documentation
COMMENT ON TABLE teams IS 'Organizations/teams that can have multiple members sharing subscriptions';
COMMENT ON TABLE team_members IS 'Junction table connecting users to teams with roles';
COMMENT ON TABLE team_invitations IS 'Pending invitations for users to join teams';
COMMENT ON COLUMN subscriptions.team_id IS 'If set, this subscription belongs to a team (not individual user)';
COMMENT ON COLUMN subscriptions.is_team_subscription IS 'Flag to indicate team-wide subscription vs personal';

-- Function to automatically set updated_at
CREATE OR REPLACE FUNCTION update_teams_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update teams.updated_at
CREATE TRIGGER teams_updated_at_trigger
    BEFORE UPDATE ON teams
    FOR EACH ROW
    EXECUTE FUNCTION update_teams_updated_at();

-- Function to get user's team subscriptions
CREATE OR REPLACE FUNCTION get_user_team_subscriptions(p_user_id TEXT)
RETURNS TABLE(
    tool_category TEXT,
    team_name TEXT,
    status TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.tool_category,
        t.team_name,
        s.status
    FROM subscriptions s
    JOIN teams t ON s.team_id = t.team_id
    JOIN team_members tm ON t.team_id = tm.team_id
    WHERE tm.user_id = p_user_id
    AND s.is_team_subscription = TRUE
    AND s.status = 'active';
END;
$$ LANGUAGE plpgsql;

-- Function to check if user has access to a tool category (personal OR team)
CREATE OR REPLACE FUNCTION user_has_tool_access(p_user_id TEXT, p_category TEXT)
RETURNS BOOLEAN AS $$
DECLARE
    has_access BOOLEAN;
BEGIN
    -- Check personal subscriptions
    SELECT EXISTS(
        SELECT 1 FROM subscriptions
        WHERE user_id = p_user_id
        AND tool_category = p_category
        AND status = 'active'
        AND (team_id IS NULL OR is_team_subscription = FALSE)
    ) INTO has_access;

    IF has_access THEN
        RETURN TRUE;
    END IF;

    -- Check team subscriptions
    SELECT EXISTS(
        SELECT 1 FROM subscriptions s
        JOIN team_members tm ON s.team_id = tm.team_id
        WHERE tm.user_id = p_user_id
        AND s.tool_category = p_category
        AND s.status = 'active'
        AND s.is_team_subscription = TRUE
    ) INTO has_access;

    RETURN has_access;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SAMPLE QUERIES (for testing)
-- ============================================================================

-- Get all teams for a user
-- SELECT t.* FROM teams t
-- JOIN team_members tm ON t.team_id = tm.team_id
-- WHERE tm.user_id = 'user_xxx';

-- Get all members of a team
-- SELECT u.email, tm.role, tm.joined_at
-- FROM team_members tm
-- JOIN users u ON tm.user_id = u.user_id
-- WHERE tm.team_id = 'team_xxx';

-- Get all team subscriptions a user has access to
-- SELECT * FROM get_user_team_subscriptions('user_xxx');

-- Check if user has access to a category
-- SELECT user_has_tool_access('user_xxx', 'gmail');

-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE '✅ Team functionality schema created successfully!';
    RAISE NOTICE '   - Teams table created';
    RAISE NOTICE '   - Team members table created';
    RAISE NOTICE '   - Team invitations table created';
    RAISE NOTICE '   - Subscriptions table updated for team support';
    RAISE NOTICE '   - Indexes created for performance';
    RAISE NOTICE '   - RLS policies enabled for security';
    RAISE NOTICE '   - Helper functions created';
END $$;
