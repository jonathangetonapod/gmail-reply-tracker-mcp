"""Lead Management Module for MCP Server.

This module provides integration with Instantly.ai and Bison (LeadGenJay) APIs
for tracking client health, campaign statistics, and interested lead responses.
"""

from .lead_functions import (
    # Instantly tools
    get_client_list,
    get_lead_responses,
    get_campaign_stats,
    get_workspace_info,
    # Bison tools
    get_bison_client_list,
    get_bison_lead_responses,
    get_bison_campaign_stats,
    # Unified tools
    get_all_clients,
    # Aggregated analytics
    get_all_platform_stats,
    get_top_performing_clients,
    get_underperforming_clients,
    get_weekly_summary,
)

__all__ = [
    # Instantly tools
    "get_client_list",
    "get_lead_responses",
    "get_campaign_stats",
    "get_workspace_info",
    # Bison tools
    "get_bison_client_list",
    "get_bison_lead_responses",
    "get_bison_campaign_stats",
    # Unified tools
    "get_all_clients",
    # Aggregated analytics
    "get_all_platform_stats",
    "get_top_performing_clients",
    "get_underperforming_clients",
    "get_weekly_summary",
]
