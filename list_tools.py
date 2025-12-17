#!/usr/bin/env python3
"""List all registered MCP tools."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

import asyncio
from server import mcp

async def list_tools():
    print("Registered MCP Tools:")
    print("=" * 60)

    # Get all tool names from the FastMCP instance
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]

    # Sort alphabetically
    tool_names.sort()

    # Print with numbering
    for idx, name in enumerate(tool_names, 1):
        print(f"{idx:2}. {name}")

    print("=" * 60)
    print(f"Total tools: {len(tool_names)}")

    # Check for campaign automation tools
    campaign_tools = [t for t in tool_names if 'campaign' in t.lower() or 'sequence' in t.lower()]
    if campaign_tools:
        print(f"\nCampaign Automation Tools Found:")
        for tool in campaign_tools:
            print(f"  ✓ {tool}")
    else:
        print("\n⚠️  WARNING: No campaign automation tools found!")

if __name__ == "__main__":
    asyncio.run(list_tools())
