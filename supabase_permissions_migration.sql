-- Team Member Permissions Table
-- Tracks which team members have access to which tool categories from team subscriptions

CREATE TABLE IF NOT EXISTS team_member_permissions (
    permission_id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    team_id TEXT NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    tool_category TEXT NOT NULL,
    assigned_by_user_id TEXT REFERENCES users(user_id),
    assigned_at TIMESTAMPTZ DEFAULT NOW(),

    -- Ensure unique permission per user per team per category
    UNIQUE(user_id, team_id, tool_category)
);

-- Indexes for fast lookups
CREATE INDEX idx_team_member_permissions_user_id ON team_member_permissions(user_id);
CREATE INDEX idx_team_member_permissions_team_id ON team_member_permissions(team_id);
CREATE INDEX idx_team_member_permissions_category ON team_member_permissions(tool_category);

-- Row Level Security (optional)
ALTER TABLE team_member_permissions ENABLE ROW LEVEL SECURITY;

-- Policy: Users can read their own permissions
CREATE POLICY "Users can read own permissions"
    ON team_member_permissions FOR SELECT
    USING (auth.uid()::text = user_id);

-- Policy: Team admins can manage permissions
CREATE POLICY "Team admins can manage permissions"
    ON team_member_permissions FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM team_members
            WHERE team_members.team_id = team_member_permissions.team_id
            AND team_members.user_id = auth.uid()::text
            AND team_members.role IN ('owner', 'admin')
        )
    );

-- Add comment
COMMENT ON TABLE team_member_permissions IS 'Controls which team members can access which tool categories from team subscriptions';
