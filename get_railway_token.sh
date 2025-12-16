#!/bin/bash

echo "============================================"
echo "Railway MCP Server - Get Your Token"
echo "============================================"
echo ""
echo "Opening browser to authorize..."
echo ""
open "https://mcp-gmail-multi-tenant-production.up.railway.app/setup"
echo ""
echo "After authorizing with Google, copy your token from the page."
echo ""
read -p "Paste your token here: " TOKEN
echo ""
echo "Your token is: $TOKEN"
echo ""
echo "Now I'll update your Claude Desktop config..."
echo ""

# Create a temporary Python script to update the JSON
python3 << EOF
import json

config_path = "/Users/jonathangarces/Library/Application Support/Claude/claude_desktop_config.json"

with open(config_path, 'r') as f:
    config = json.load(f)

# Add the Railway server
config['mcpServers']['gmail-railway'] = {
    "command": "npx",
    "args": [
        "-y",
        "@modelcontextprotocol/server-fetch",
        "https://mcp-gmail-multi-tenant-production.up.railway.app/mcp",
        "--header",
        f"Authorization: Bearer $TOKEN"
    ]
}

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print("✅ Claude Desktop config updated!")
print("")
print("Restart Claude Desktop to use the new server.")
EOF

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Restart Claude Desktop"
echo "2. The 'gmail-railway' server will be available"
echo ""
