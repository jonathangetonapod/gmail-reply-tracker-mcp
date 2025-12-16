#!/usr/bin/env python3
"""List all available MCP tools on the server."""

import json
import requests

SERVER_URL = "https://mcp-gmail-multi-tenant-production.up.railway.app/mcp"
SESSION_TOKEN = "sess_3ArfabzB4Yh67IRyq6nKQuKTi1F5pdoAfmQ0IIMU1ic"

# Initialize
init_request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "1.0.0"}
    }
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {SESSION_TOKEN}"
}

# Initialize
response = requests.post(SERVER_URL, json=init_request, headers=headers)
print("Initialization:", "OK" if response.status_code == 200 else "FAILED")

# List tools
list_request = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
}

response = requests.post(SERVER_URL, json=list_request, headers=headers)
data = response.json()

if "result" in data:
    tools = data["result"]["tools"]
    print(f"\nFound {len(tools)} tools:\n")
    for i, tool in enumerate(tools, 1):
        print(f"{i}. {tool['name']}")
        print(f"   {tool.get('description', 'No description')[:80]}...")
        print()
else:
    print("Error:", data)
