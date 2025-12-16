# Gmail MCP Server - Automated Setup Script (Windows)
# Usage:
#   $token = "YOUR_SESSION_TOKEN"
#   Invoke-WebRequest -Uri "https://mcp-gmail-multi-tenant-production.up.railway.app/install.ps1" -UseBasicParsing | Invoke-Expression

param(
    [Parameter(Mandatory=$false)]
    [string]$SessionToken
)

# Configuration
$SERVER_URL = "https://mcp-gmail-multi-tenant-production.up.railway.app"

# Functions
function Write-Header {
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Blue
    Write-Host "  Gmail MCP Server - Automated Setup" -ForegroundColor Blue
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Blue
    Write-Host ""
}

function Write-Step {
    param([string]$Message)
    Write-Host "▸ $Message" -ForegroundColor Green
}

function Write-Error-Message {
    param([string]$Message)
    Write-Host "✗ $Message" -ForegroundColor Red
}

function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Write-Warning-Message {
    param([string]$Message)
    Write-Host "⚠ $Message" -ForegroundColor Yellow
}

# Check if session token provided
if (-not $SessionToken) {
    if ($env:MCP_SESSION_TOKEN) {
        $SessionToken = $env:MCP_SESSION_TOKEN
    } else {
        Write-Header
        Write-Error-Message "No session token provided!"
        Write-Host ""
        Write-Host "Usage:"
        Write-Host '  $env:MCP_SESSION_TOKEN = "YOUR_SESSION_TOKEN"'
        Write-Host '  Invoke-WebRequest -Uri "' + $SERVER_URL + '/install.ps1" -UseBasicParsing | Invoke-Expression'
        Write-Host ""
        Write-Host "To get your session token:"
        Write-Host "  1. Visit: $SERVER_URL/setup"
        Write-Host "  2. Authorize with Google"
        Write-Host "  3. Copy your session token from the page"
        Write-Host ""
        exit 1
    }
}

Write-Header

# Detect config directory
Write-Step "Detecting configuration directory..."
$CONFIG_DIR = "$env:APPDATA\Claude"
$INSTALL_DIR = "$CONFIG_DIR\mcp-clients"
Write-Success "Config directory: $CONFIG_DIR"

# Check if Node.js is installed
Write-Step "Checking for Node.js..."
try {
    $nodeVersion = & node --version 2>&1
    Write-Success "Node.js $nodeVersion found"
} catch {
    Write-Error-Message "Node.js is not installed!"
    Write-Host ""
    Write-Host "Please install Node.js first:"
    Write-Host "  Visit: https://nodejs.org/"
    Write-Host ""
    exit 1
}

# Create installation directory
Write-Step "Creating installation directory..."
New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null
Write-Success "Directory created: $INSTALL_DIR"

# Download http-mcp-client.js
Write-Step "Downloading MCP client..."
$CLIENT_PATH = "$INSTALL_DIR\http-mcp-client.js"
try {
    Invoke-WebRequest -Uri "$SERVER_URL/download/http-mcp-client.js" -OutFile $CLIENT_PATH -UseBasicParsing
    Write-Success "Downloaded to: $CLIENT_PATH"
} catch {
    Write-Error-Message "Failed to download client: $_"
    exit 1
}

# Check if config file exists
$CONFIG_FILE = "$CONFIG_DIR\claude_desktop_config.json"
Write-Step "Looking for Claude Desktop config..."
if (-not (Test-Path $CONFIG_FILE)) {
    Write-Warning-Message "Config file doesn't exist, creating new one..."
    New-Item -ItemType Directory -Force -Path $CONFIG_DIR | Out-Null
    '{"mcpServers":{}}' | Out-File -FilePath $CONFIG_FILE -Encoding UTF8
}
Write-Success "Found: $CONFIG_FILE"

# Backup existing config
Write-Step "Backing up existing configuration..."
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BACKUP_FILE = "$CONFIG_FILE.backup.$timestamp"
Copy-Item $CONFIG_FILE $BACKUP_FILE
Write-Success "Backup saved: $BACKUP_FILE"

# Update configuration
Write-Step "Updating Claude Desktop configuration..."
try {
    $config = Get-Content $CONFIG_FILE -Raw | ConvertFrom-Json

    # Ensure mcpServers exists
    if (-not $config.mcpServers) {
        $config | Add-Member -NotePropertyName mcpServers -NotePropertyValue @{} -Force
    }

    # Add our server (or update if exists)
    $config.mcpServers | Add-Member -NotePropertyName "gmail-calendar-fathom" -NotePropertyValue @{
        command = "node"
        args = @(
            $CLIENT_PATH,
            "$SERVER_URL/mcp",
            $SessionToken
        )
    } -Force

    # Write updated config
    $config | ConvertTo-Json -Depth 10 | Out-File -FilePath $CONFIG_FILE -Encoding UTF8
    Write-Success "Configuration updated successfully!"
} catch {
    Write-Error-Message "Failed to update configuration: $_"
    Write-Warning-Message "Restoring backup..."
    Copy-Item $BACKUP_FILE $CONFIG_FILE -Force
    exit 1
}

# Success!
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host "  ✓ Setup Complete!" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Restart Claude Desktop"
Write-Host "  2. Try asking Claude:"
Write-Host "     • 'Show me my unreplied emails from the last 3 days'"
Write-Host "     • 'List my calendar events for next week'"
Write-Host ""
Write-Host "Files installed:"
Write-Host "  • Client: $CLIENT_PATH"
Write-Host "  • Config: $CONFIG_FILE"
Write-Host "  • Backup: $BACKUP_FILE"
Write-Host ""
