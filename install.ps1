# Gmail MCP Server - Automated Setup Script (Windows)
# Usage:
#   $token = "YOUR_SESSION_TOKEN"
#   Invoke-WebRequest -Uri "https://mcp-gmail-multi-tenant-production.up.railway.app/install.ps1" -UseBasicParsing | Invoke-Expression

param(
    [Parameter(Mandatory=$false)]
    [string]$SessionToken,

    [Parameter(Mandatory=$false)]
    [string]$UserEmail
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
        Write-Host '  $env:MCP_SESSION_TOKEN = "YOUR_SESSION_TOKEN"; $env:MCP_USER_EMAIL = "YOUR_EMAIL"'
        Write-Host '  Invoke-WebRequest -Uri "' + $SERVER_URL + '/install.ps1" -UseBasicParsing | Invoke-Expression'
        Write-Host ""
        Write-Host "To get your install command:"
        Write-Host "  1. Visit: $SERVER_URL/setup"
        Write-Host "  2. Authorize with Google"
        Write-Host "  3. Copy the install command from the page"
        Write-Host ""
        exit 1
    }
}

# Check if user email provided
if (-not $UserEmail) {
    if ($env:MCP_USER_EMAIL) {
        $UserEmail = $env:MCP_USER_EMAIL
    } else {
        Write-Header
        Write-Error-Message "No email provided!"
        Write-Host ""
        Write-Host "Usage:"
        Write-Host '  $env:MCP_SESSION_TOKEN = "YOUR_SESSION_TOKEN"; $env:MCP_USER_EMAIL = "YOUR_EMAIL"'
        Write-Host '  Invoke-WebRequest -Uri "' + $SERVER_URL + '/install.ps1" -UseBasicParsing | Invoke-Expression'
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
    Write-Warning-Message "Node.js is not installed. Installing now..."

    # Try winget first (Windows 10+)
    try {
        Write-Step "Installing Node.js via winget..."
        $wingetResult = winget install -e --id OpenJS.NodeJS --silent 2>&1

        # Refresh PATH - multiple times to ensure it's loaded
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

        # Add common Node.js installation paths
        $env:Path = "C:\Program Files\nodejs;" + $env:Path
        $env:Path = "$env:ProgramFiles\nodejs;" + $env:Path
        $env:Path = "${env:ProgramFiles(x86)}\nodejs;" + $env:Path

        # Wait a moment for installation to complete
        Start-Sleep -Seconds 2

        # Check if installation succeeded
        try {
            $nodeVersion = & node --version 2>&1
            Write-Success "Node.js installed successfully!"
        } catch {
            Write-Warning-Message "Node.js installed but not immediately available. Trying again..."
            # Refresh PATH one more time
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            try {
                $nodeVersion = & node --version 2>&1
                Write-Success "Node.js is now available!"
            } catch {
                throw "Node.js installation verification failed"
            }
        }
    } catch {
        # Try chocolatey as fallback
        if (Get-Command choco -ErrorAction SilentlyContinue) {
            Write-Step "Installing Node.js via Chocolatey..."
            choco install nodejs -y

            # Refresh PATH
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

            # Add common Node.js installation paths
            $env:Path = "C:\Program Files\nodejs;" + $env:Path
            $env:Path = "$env:ProgramFiles\nodejs;" + $env:Path
            $env:Path = "${env:ProgramFiles(x86)}\nodejs;" + $env:Path

            # Wait for installation to complete
            Start-Sleep -Seconds 2

            # Check if installation succeeded
            try {
                $nodeVersion = & node --version 2>&1
                Write-Success "Node.js installed successfully!"
            } catch {
                Write-Warning-Message "Node.js installed but not immediately available. Trying again..."
                # Refresh PATH one more time
                $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
                try {
                    $nodeVersion = & node --version 2>&1
                    Write-Success "Node.js is now available!"
                } catch {
                    Write-Error-Message "Failed to install Node.js"
                    Write-Host ""
                    Write-Host "Please close this PowerShell window and open a new one, then re-run:"
                    Write-Host '  $env:MCP_SESSION_TOKEN = "' + $SessionToken + '"; $env:MCP_USER_EMAIL = "' + $UserEmail + '"'
                    Write-Host '  Invoke-WebRequest -Uri "https://mcp-gmail-multi-tenant-production.up.railway.app/install.ps1" -UseBasicParsing | Invoke-Expression'
                    Write-Host ""
                    exit 1
                }
            }
        } else {
            Write-Error-Message "Could not install Node.js automatically"
            Write-Host ""
            Write-Host "Please install Node.js manually:"
            Write-Host "  Visit: https://nodejs.org/"
            Write-Host ""
            Write-Host "Or install winget/chocolatey first:"
            Write-Host "  Winget: Included in Windows 10+ (update Windows)"
            Write-Host "  Chocolatey: https://chocolatey.org/install"
            Write-Host ""
            exit 1
        }
    }
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
    # Extract domain from email
    if ($UserEmail -match '@([^@]+)$') {
        $domain = $matches[1]
        # Remove TLD and use first part as identifier
        $domainName = $domain.Split('.')[0]
    } else {
        $domainName = "default"
    }

    $config = Get-Content $CONFIG_FILE -Raw | ConvertFrom-Json

    # Ensure mcpServers exists
    if (-not $config.mcpServers) {
        $config | Add-Member -NotePropertyName mcpServers -NotePropertyValue @{} -Force
    }

    # Generate server name
    # If gmail-calendar-fathom doesn't exist, use it
    # Otherwise use gmail-calendar-fathom-DOMAIN
    $serverName = "gmail-calendar-fathom"
    if ($config.mcpServers.PSObject.Properties.Name -contains $serverName) {
        # Check if it's pointing to our server
        $existingArgs = $config.mcpServers.$serverName.args
        if ($existingArgs -and $existingArgs[1] -match [regex]::Escape($SERVER_URL)) {
            # It's already our server, use domain-based name
            $serverName = "gmail-calendar-fathom-$domainName"
        } else {
            # Different server, use domain-based name
            $serverName = "gmail-calendar-fathom-$domainName"
        }
    }

    # Add our server (or update if exists)
    $config.mcpServers | Add-Member -NotePropertyName $serverName -NotePropertyValue @{
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
    Write-Host "  Server name: $serverName" -ForegroundColor Cyan
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
