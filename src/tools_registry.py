"""Tools Registry - Auto-discover and register all MCP tools."""

import inspect
import logging
from typing import List, Dict, Any, Callable
from pathlib import Path
import sys

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

logger = logging.getLogger(__name__)


def get_all_tools_from_server() -> List[Dict[str, Any]]:
    """
    Extract all tools from the existing server.py module.

    Returns a list of tool definitions with:
    - name: Tool name
    - function: The actual function object
    - description: Tool description from docstring
    - parameters: Parameter schema extracted from type hints
    """
    try:
        # Import the server module to get access to the MCP instance
        import server

        tools = []

        # FastMCP stores tools in the _tools attribute
        if hasattr(server.mcp, '_tools'):
            mcp_tools = server.mcp._tools
            logger.info(f"Found {len(mcp_tools)} tools in server.mcp._tools")

            for tool_name, tool_func in mcp_tools.items():
                # Get the function signature
                sig = inspect.signature(tool_func)

                # Extract parameters from signature
                parameters = {
                    "type": "object",
                    "properties": {},
                    "required": []
                }

                for param_name, param in sig.parameters.items():
                    # Skip self/cls parameters
                    if param_name in ('self', 'cls'):
                        continue

                    # Determine parameter type from annotation
                    param_type = "string"  # default
                    if param.annotation != inspect.Parameter.empty:
                        annotation = param.annotation
                        if annotation == int:
                            param_type = "integer"
                        elif annotation == float:
                            param_type = "number"
                        elif annotation == bool:
                            param_type = "boolean"
                        elif annotation == list:
                            param_type = "array"
                        elif annotation == dict:
                            param_type = "object"

                    param_schema = {"type": param_type}

                    # Add default value if present
                    if param.default != inspect.Parameter.empty:
                        param_schema["default"] = param.default
                    else:
                        # No default means required
                        parameters["required"].append(param_name)

                    parameters["properties"][param_name] = param_schema

                # Extract description from docstring
                description = ""
                if tool_func.__doc__:
                    # Get first line or paragraph of docstring
                    doc_lines = tool_func.__doc__.strip().split('\n')
                    description = doc_lines[0].strip() if doc_lines else ""

                tools.append({
                    "name": tool_name,
                    "function": tool_func,
                    "description": description,
                    "parameters": parameters
                })

        logger.info(f"Successfully registered {len(tools)} tools")
        return tools

    except Exception as e:
        logger.error(f"Error extracting tools from server: {e}")
        raise


def create_tool_handler(tool_func: Callable) -> Callable:
    """
    Create a wrapper for a tool function that handles async/sync execution.

    Args:
        tool_func: The original tool function

    Returns:
        Async wrapper function that can handle both sync and async tool functions
    """
    async def handler(**kwargs):
        """Execute the tool function with provided arguments."""
        try:
            if inspect.iscoroutinefunction(tool_func):
                result = await tool_func(**kwargs)
            else:
                result = tool_func(**kwargs)
            return result
        except Exception as e:
            logger.error(f"Error executing tool {tool_func.__name__}: {e}")
            raise

    return handler


# Cache the tools list so we don't re-parse on every request
_TOOLS_CACHE: List[Dict[str, Any]] = None


def get_all_tools() -> List[Dict[str, Any]]:
    """
    Get all tools (cached).

    Returns:
        List of tool definitions
    """
    global _TOOLS_CACHE

    if _TOOLS_CACHE is None:
        _TOOLS_CACHE = get_all_tools_from_server()

    return _TOOLS_CACHE


def get_tool_by_name(name: str) -> Dict[str, Any]:
    """
    Get a specific tool by name.

    Args:
        name: Tool name

    Returns:
        Tool definition dict or None if not found
    """
    tools = get_all_tools()
    for tool in tools:
        if tool["name"] == name:
            return tool
    return None


if __name__ == "__main__":
    # Test tool discovery
    logging.basicConfig(level=logging.INFO)

    tools = get_all_tools()
    print(f"\nDiscovered {len(tools)} tools:\n")

    for tool in tools:
        print(f"  - {tool['name']}: {tool['description'][:80]}...")
        print(f"    Parameters: {len(tool['parameters']['properties'])} args, "
              f"{len(tool['parameters']['required'])} required")
