#!/bin/bash

echo "🔄 Initializing session with Railway MCP server..."
RESPONSE=$(curl -s -X POST "https://mcp-gmail-multi-tenant-dev-enviroment.up.railway.app/mcp" \
  -H "Content-Type: application/json" \
  -D /tmp/mcp_headers.txt \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}}}')

SESSION_ID=$(grep -i "mcp-session-id:" /tmp/mcp_headers.txt | cut -d: -f2 | tr -d ' \r')

echo "✅ Session ID: $SESSION_ID"
echo ""
echo "📋 Listing all tools..."
echo ""

curl -s -X POST "https://mcp-gmail-multi-tenant-dev-enviroment.up.railway.app/mcp" \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | python3 -c "
import json, sys
data = json.load(sys.stdin)
tools = data['result']['tools']
print(f'✅ Total tools available: {len(tools)}')
print()
print('Tool names:')
for i, tool in enumerate(tools, 1):
    print(f'  {i}. {tool[\"name\"]}')
"

echo ""
echo "🧪 Testing a tool (get_inbox_summary)..."
echo ""

curl -s -X POST "https://mcp-gmail-multi-tenant-dev-enviroment.up.railway.app/mcp" \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_inbox_summary","arguments":{}}}' | python3 -m json.tool | head -50
