#!/usr/bin/env python3
"""Lead management functions for Instantly.ai and Bison platforms."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import pandas as pd
from io import StringIO
import requests

logger = logging.getLogger(__name__)


def _convert_sheets_url_to_csv(sheet_url: str, gid: str = None) -> str:
    """
    Convert Google Sheets URL to CSV export URL.

    Args:
        sheet_url: Google Sheets URL
        gid: Sheet GID (optional, for specific tabs)

    Returns:
        CSV export URL
    """
    # Extract spreadsheet ID from URL
    if "/d/" in sheet_url:
        spreadsheet_id = sheet_url.split("/d/")[1].split("/")[0]
    else:
        raise ValueError(f"Invalid Google Sheets URL: {sheet_url}")

    # Build CSV export URL
    csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv"
    if gid:
        csv_url += f"&gid={gid}"

    return csv_url


def _fetch_sheet_data(sheet_url: str, gid: str = None) -> pd.DataFrame:
    """
    Fetch data from Google Sheets as a DataFrame.

    Args:
        sheet_url: Google Sheets URL
        gid: Sheet GID (optional, for specific tabs)

    Returns:
        DataFrame with sheet data
    """
    csv_url = _convert_sheets_url_to_csv(sheet_url, gid)

    try:
        response = requests.get(csv_url, timeout=30)
        response.raise_for_status()

        # Parse CSV data
        df = pd.read_csv(StringIO(response.text))

        return df

    except Exception as e:
        logger.error(f"Error fetching sheet data: {e}")
        raise


def _parse_date_column(df: pd.DataFrame, column_name: str) -> pd.DataFrame:
    """
    Parse a date column in the DataFrame.

    Args:
        df: DataFrame
        column_name: Name of the date column

    Returns:
        DataFrame with parsed date column
    """
    if column_name in df.columns:
        df[column_name] = pd.to_datetime(df[column_name], errors='coerce')
    return df


def _filter_by_date_range(
    df: pd.DataFrame,
    date_column: str,
    days: int = None,
    start_date: str = None,
    end_date: str = None
) -> pd.DataFrame:
    """
    Filter DataFrame by date range.

    Args:
        df: DataFrame
        date_column: Name of the date column
        days: Number of days to look back
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Filtered DataFrame
    """
    if date_column not in df.columns:
        return df

    # Parse date column
    df = _parse_date_column(df, date_column)

    # Calculate date range
    if start_date and end_date:
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
    elif days:
        end = datetime.now()
        start = end - timedelta(days=days)
    else:
        return df

    # Filter by date range
    mask = (df[date_column] >= start) & (df[date_column] <= end)
    return df[mask]


# ============================================================================
# INSTANTLY.AI FUNCTIONS
# ============================================================================

def get_client_list(sheet_url: str) -> Dict[str, Any]:
    """
    Get list of all Instantly.ai clients/workspaces.

    Args:
        sheet_url: Google Sheets URL

    Returns:
        Dictionary with client list
    """
    try:
        df = _fetch_sheet_data(sheet_url)

        # Assume columns: workspace_id, client_name
        if 'workspace_id' not in df.columns or 'client_name' not in df.columns:
            # Try to find the right columns
            if len(df.columns) >= 2:
                df.columns = ['workspace_id', 'client_name'] + list(df.columns[2:])

        # Get unique clients
        clients = []
        for _, row in df.iterrows():
            if pd.notna(row.get('workspace_id')) and pd.notna(row.get('client_name')):
                clients.append({
                    'workspace_id': str(row['workspace_id']),
                    'client_name': str(row['client_name'])
                })

        # Remove duplicates based on workspace_id
        seen = set()
        unique_clients = []
        for client in clients:
            if client['workspace_id'] not in seen:
                seen.add(client['workspace_id'])
                unique_clients.append(client)

        return {
            'total_clients': len(unique_clients),
            'clients': unique_clients
        }

    except Exception as e:
        logger.error(f"Error getting client list: {e}")
        raise


def get_lead_responses(
    sheet_url: str,
    gid: str,
    workspace_id: str,
    days: int = 7,
    start_date: str = None,
    end_date: str = None
) -> Dict[str, Any]:
    """
    Get lead responses for a specific Instantly.ai workspace.

    Args:
        sheet_url: Google Sheets URL
        gid: Sheet GID
        workspace_id: Workspace ID
        days: Number of days to look back
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Dictionary with lead responses
    """
    try:
        df = _fetch_sheet_data(sheet_url, gid)

        # Filter by workspace_id
        if 'workspace_id' in df.columns:
            df = df[df['workspace_id'] == workspace_id]

        # Filter by date if date column exists
        date_columns = ['date', 'reply_date', 'response_date', 'created_at']
        for col in date_columns:
            if col in df.columns:
                df = _filter_by_date_range(df, col, days, start_date, end_date)
                break

        # Format lead responses
        leads = []
        for _, row in df.iterrows():
            lead = {col: str(row[col]) if pd.notna(row[col]) else None for col in df.columns}
            leads.append(lead)

        return {
            'workspace_id': workspace_id,
            'total_leads': len(leads),
            'leads': leads,
            'date_range': {
                'start': start_date or (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d'),
                'end': end_date or datetime.now().strftime('%Y-%m-%d')
            }
        }

    except Exception as e:
        logger.error(f"Error getting lead responses: {e}")
        raise


def get_campaign_stats(
    sheet_url: str,
    gid: str,
    workspace_id: str,
    days: int = 7,
    start_date: str = None,
    end_date: str = None
) -> Dict[str, Any]:
    """
    Get campaign statistics for a specific Instantly.ai workspace.

    Args:
        sheet_url: Google Sheets URL
        gid: Sheet GID
        workspace_id: Workspace ID
        days: Number of days to look back
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Dictionary with campaign statistics
    """
    try:
        df = _fetch_sheet_data(sheet_url, gid)

        # Filter by workspace_id
        if 'workspace_id' in df.columns:
            df = df[df['workspace_id'] == workspace_id]

        # Filter by date
        date_columns = ['date', 'sent_date', 'created_at']
        for col in date_columns:
            if col in df.columns:
                df = _filter_by_date_range(df, col, days, start_date, end_date)
                break

        # Calculate statistics
        stats = {
            'workspace_id': workspace_id,
            'total_records': len(df)
        }

        # Count various metrics if columns exist
        metric_columns = {
            'sent': ['sent', 'emails_sent', 'total_sent'],
            'opens': ['opens', 'opened', 'total_opens'],
            'replies': ['replies', 'replied', 'total_replies'],
            'interested_leads': ['interested', 'interested_leads', 'positive_replies']
        }

        for metric, possible_cols in metric_columns.items():
            for col in possible_cols:
                if col in df.columns:
                    stats[metric] = int(df[col].sum()) if pd.api.types.is_numeric_dtype(df[col]) else len(df[df[col].notna()])
                    break
            if metric not in stats:
                stats[metric] = 0

        # Calculate rates
        if stats.get('sent', 0) > 0:
            stats['open_rate'] = round((stats.get('opens', 0) / stats['sent']) * 100, 2)
            stats['reply_rate'] = round((stats.get('replies', 0) / stats['sent']) * 100, 2)
            stats['interested_rate'] = round((stats.get('interested_leads', 0) / stats['sent']) * 100, 2)
        else:
            stats['open_rate'] = 0
            stats['reply_rate'] = 0
            stats['interested_rate'] = 0

        return stats

    except Exception as e:
        logger.error(f"Error getting campaign stats: {e}")
        raise


def get_workspace_info(sheet_url: str, workspace_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific Instantly.ai workspace.

    Args:
        sheet_url: Google Sheets URL
        workspace_id: Workspace ID

    Returns:
        Dictionary with workspace information
    """
    try:
        df = _fetch_sheet_data(sheet_url)

        # Filter by workspace_id
        if 'workspace_id' in df.columns:
            workspace_data = df[df['workspace_id'] == workspace_id]

            if len(workspace_data) > 0:
                row = workspace_data.iloc[0]
                return {
                    'workspace_id': str(row['workspace_id']),
                    'client_name': str(row.get('client_name', 'Unknown')),
                    'info': {col: str(row[col]) if pd.notna(row[col]) else None for col in df.columns}
                }

        return {
            'workspace_id': workspace_id,
            'client_name': 'Unknown',
            'error': 'Workspace not found'
        }

    except Exception as e:
        logger.error(f"Error getting workspace info: {e}")
        raise


# ============================================================================
# BISON FUNCTIONS
# ============================================================================

def get_bison_client_list(sheet_url: str, gid: str) -> Dict[str, Any]:
    """
    Get list of all Bison clients.

    Args:
        sheet_url: Google Sheets URL
        gid: Sheet GID

    Returns:
        Dictionary with client list
    """
    try:
        df = _fetch_sheet_data(sheet_url, gid)

        # Assume column: client_name
        if 'client_name' not in df.columns:
            if len(df.columns) >= 1:
                df.columns = ['client_name'] + list(df.columns[1:])

        # Get unique clients
        clients = []
        if 'client_name' in df.columns:
            unique_names = df['client_name'].dropna().unique()
            clients = [{'client_name': str(name)} for name in unique_names]

        return {
            'total_clients': len(clients),
            'clients': clients
        }

    except Exception as e:
        logger.error(f"Error getting Bison client list: {e}")
        raise


def get_bison_lead_responses(
    sheet_url: str,
    gid: str,
    client_name: str,
    days: int = 7,
    start_date: str = None,
    end_date: str = None
) -> Dict[str, Any]:
    """
    Get lead responses for a specific Bison client.

    Args:
        sheet_url: Google Sheets URL
        gid: Sheet GID
        client_name: Client name
        days: Number of days to look back
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Dictionary with lead responses
    """
    try:
        df = _fetch_sheet_data(sheet_url, gid)

        # Filter by client_name
        if 'client_name' in df.columns:
            df = df[df['client_name'] == client_name]

        # Filter by date
        date_columns = ['date', 'reply_date', 'response_date', 'created_at']
        for col in date_columns:
            if col in df.columns:
                df = _filter_by_date_range(df, col, days, start_date, end_date)
                break

        # Format lead responses
        leads = []
        for _, row in df.iterrows():
            lead = {col: str(row[col]) if pd.notna(row[col]) else None for col in df.columns}
            leads.append(lead)

        return {
            'client_name': client_name,
            'total_leads': len(leads),
            'leads': leads,
            'date_range': {
                'start': start_date or (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d'),
                'end': end_date or datetime.now().strftime('%Y-%m-%d')
            }
        }

    except Exception as e:
        logger.error(f"Error getting Bison lead responses: {e}")
        raise


def get_bison_campaign_stats(
    sheet_url: str,
    gid: str,
    client_name: str,
    days: int = 7,
    start_date: str = None,
    end_date: str = None
) -> Dict[str, Any]:
    """
    Get campaign statistics for a specific Bison client.

    Args:
        sheet_url: Google Sheets URL
        gid: Sheet GID
        client_name: Client name
        days: Number of days to look back
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Dictionary with campaign statistics
    """
    try:
        df = _fetch_sheet_data(sheet_url, gid)

        # Filter by client_name
        if 'client_name' in df.columns:
            df = df[df['client_name'] == client_name]

        # Filter by date
        date_columns = ['date', 'sent_date', 'created_at']
        for col in date_columns:
            if col in df.columns:
                df = _filter_by_date_range(df, col, days, start_date, end_date)
                break

        # Calculate statistics
        stats = {
            'client_name': client_name,
            'total_records': len(df)
        }

        # Count various metrics
        metric_columns = {
            'sent': ['sent', 'emails_sent', 'total_sent'],
            'opens': ['opens', 'opened', 'total_opens'],
            'replies': ['replies', 'replied', 'total_replies'],
            'interested_leads': ['interested', 'interested_leads', 'positive_replies']
        }

        for metric, possible_cols in metric_columns.items():
            for col in possible_cols:
                if col in df.columns:
                    stats[metric] = int(df[col].sum()) if pd.api.types.is_numeric_dtype(df[col]) else len(df[df[col].notna()])
                    break
            if metric not in stats:
                stats[metric] = 0

        # Calculate rates
        if stats.get('sent', 0) > 0:
            stats['open_rate'] = round((stats.get('opens', 0) / stats['sent']) * 100, 2)
            stats['reply_rate'] = round((stats.get('replies', 0) / stats['sent']) * 100, 2)
            stats['interested_rate'] = round((stats.get('interested_leads', 0) / stats['sent']) * 100, 2)
        else:
            stats['open_rate'] = 0
            stats['reply_rate'] = 0
            stats['interested_rate'] = 0

        return stats

    except Exception as e:
        logger.error(f"Error getting Bison campaign stats: {e}")
        raise


# ============================================================================
# COMBINED PLATFORM FUNCTIONS
# ============================================================================

def get_all_clients(
    sheet_url: str,
    instantly_gid: str,
    bison_gid: str
) -> Dict[str, Any]:
    """
    Get list of all clients from both Instantly.ai and Bison platforms.

    Args:
        sheet_url: Google Sheets URL
        instantly_gid: Instantly sheet GID
        bison_gid: Bison sheet GID

    Returns:
        Dictionary with all clients from both platforms
    """
    try:
        # Get Instantly clients
        instantly_result = get_client_list(sheet_url)
        instantly_clients = [
            {**client, 'platform': 'instantly'}
            for client in instantly_result.get('clients', [])
        ]

        # Get Bison clients
        bison_result = get_bison_client_list(sheet_url, bison_gid)
        bison_clients = [
            {**client, 'platform': 'bison'}
            for client in bison_result.get('clients', [])
        ]

        all_clients = instantly_clients + bison_clients

        return {
            'total_clients': len(all_clients),
            'instantly_count': len(instantly_clients),
            'bison_count': len(bison_clients),
            'clients': all_clients
        }

    except Exception as e:
        logger.error(f"Error getting all clients: {e}")
        raise


def get_all_platform_stats(
    sheet_url: str,
    instantly_gid: str,
    bison_gid: str,
    days: int = 7
) -> Dict[str, Any]:
    """
    Get aggregated statistics across both platforms.

    Args:
        sheet_url: Google Sheets URL
        instantly_gid: Instantly sheet GID
        bison_gid: Bison sheet GID
        days: Number of days to look back

    Returns:
        Dictionary with aggregated platform statistics
    """
    try:
        # Get all clients
        all_clients = get_all_clients(sheet_url, instantly_gid, bison_gid)

        # Aggregate stats
        total_stats = {
            'sent': 0,
            'opens': 0,
            'replies': 0,
            'interested_leads': 0
        }

        instantly_stats = {'sent': 0, 'opens': 0, 'replies': 0, 'interested_leads': 0}
        bison_stats = {'sent': 0, 'opens': 0, 'replies': 0, 'interested_leads': 0}

        # Aggregate Instantly stats
        for client in all_clients['clients']:
            if client['platform'] == 'instantly':
                try:
                    stats = get_campaign_stats(
                        sheet_url, instantly_gid,
                        client['workspace_id'], days
                    )
                    for key in ['sent', 'opens', 'replies', 'interested_leads']:
                        value = stats.get(key, 0)
                        total_stats[key] += value
                        instantly_stats[key] += value
                except Exception as e:
                    logger.warning(f"Error getting stats for {client}: {e}")

            elif client['platform'] == 'bison':
                try:
                    stats = get_bison_campaign_stats(
                        sheet_url, bison_gid,
                        client['client_name'], days
                    )
                    for key in ['sent', 'opens', 'replies', 'interested_leads']:
                        value = stats.get(key, 0)
                        total_stats[key] += value
                        bison_stats[key] += value
                except Exception as e:
                    logger.warning(f"Error getting stats for {client}: {e}")

        # Calculate overall rates
        if total_stats['sent'] > 0:
            total_stats['open_rate'] = round((total_stats['opens'] / total_stats['sent']) * 100, 2)
            total_stats['reply_rate'] = round((total_stats['replies'] / total_stats['sent']) * 100, 2)
            total_stats['interested_rate'] = round((total_stats['interested_leads'] / total_stats['sent']) * 100, 2)
        else:
            total_stats['open_rate'] = 0
            total_stats['reply_rate'] = 0
            total_stats['interested_rate'] = 0

        return {
            'days': days,
            'total': total_stats,
            'instantly': instantly_stats,
            'bison': bison_stats,
            'total_clients': all_clients['total_clients']
        }

    except Exception as e:
        logger.error(f"Error getting platform stats: {e}")
        raise


def get_top_performing_clients(
    sheet_url: str,
    instantly_gid: str,
    bison_gid: str,
    limit: int = 10,
    metric: str = "interested_leads",
    days: int = 7
) -> Dict[str, Any]:
    """
    Get the top performing clients based on a specific metric.

    Args:
        sheet_url: Google Sheets URL
        instantly_gid: Instantly sheet GID
        bison_gid: Bison sheet GID
        limit: Maximum number of clients to return
        metric: Metric to rank by
        days: Number of days to look back

    Returns:
        Dictionary with top performing clients
    """
    try:
        # Get all clients
        all_clients = get_all_clients(sheet_url, instantly_gid, bison_gid)

        # Get stats for each client
        client_stats = []

        for client in all_clients['clients']:
            try:
                if client['platform'] == 'instantly':
                    stats = get_campaign_stats(
                        sheet_url, instantly_gid,
                        client['workspace_id'], days
                    )
                    client_stats.append({
                        **client,
                        **stats
                    })
                elif client['platform'] == 'bison':
                    stats = get_bison_campaign_stats(
                        sheet_url, bison_gid,
                        client['client_name'], days
                    )
                    client_stats.append({
                        **client,
                        **stats
                    })
            except Exception as e:
                logger.warning(f"Error getting stats for {client}: {e}")

        # Sort by metric
        sorted_clients = sorted(
            client_stats,
            key=lambda x: x.get(metric, 0),
            reverse=True
        )[:limit]

        return {
            'metric': metric,
            'days': days,
            'limit': limit,
            'clients': sorted_clients
        }

    except Exception as e:
        logger.error(f"Error getting top performing clients: {e}")
        raise


def get_underperforming_clients(
    sheet_url: str,
    instantly_gid: str,
    bison_gid: str,
    threshold: int = 5,
    metric: str = "interested_leads",
    days: int = 7
) -> Dict[str, Any]:
    """
    Get list of underperforming clients based on a specific metric threshold.

    Args:
        sheet_url: Google Sheets URL
        instantly_gid: Instantly sheet GID
        bison_gid: Bison sheet GID
        threshold: Minimum acceptable value for the metric
        metric: Metric to evaluate
        days: Number of days to look back

    Returns:
        Dictionary with underperforming clients
    """
    try:
        # Get all clients
        all_clients = get_all_clients(sheet_url, instantly_gid, bison_gid)

        # Get stats for each client
        underperforming = []

        for client in all_clients['clients']:
            try:
                if client['platform'] == 'instantly':
                    stats = get_campaign_stats(
                        sheet_url, instantly_gid,
                        client['workspace_id'], days
                    )
                elif client['platform'] == 'bison':
                    stats = get_bison_campaign_stats(
                        sheet_url, bison_gid,
                        client['client_name'], days
                    )
                else:
                    continue

                # Check if below threshold
                if stats.get(metric, 0) < threshold:
                    underperforming.append({
                        **client,
                        **stats
                    })

            except Exception as e:
                logger.warning(f"Error getting stats for {client}: {e}")

        # Sort by metric (lowest first)
        sorted_clients = sorted(
            underperforming,
            key=lambda x: x.get(metric, 0)
        )

        return {
            'metric': metric,
            'threshold': threshold,
            'days': days,
            'count': len(sorted_clients),
            'clients': sorted_clients
        }

    except Exception as e:
        logger.error(f"Error getting underperforming clients: {e}")
        raise


def get_weekly_summary(
    sheet_url: str,
    instantly_gid: str,
    bison_gid: str
) -> Dict[str, Any]:
    """
    Get a comprehensive weekly summary of lead generation activities.

    Args:
        sheet_url: Google Sheets URL
        instantly_gid: Instantly sheet GID
        bison_gid: Bison sheet GID

    Returns:
        Dictionary with weekly summary
    """
    try:
        days = 7

        # Get platform stats
        platform_stats = get_all_platform_stats(
            sheet_url, instantly_gid, bison_gid, days
        )

        # Get top performers
        top_clients = get_top_performing_clients(
            sheet_url, instantly_gid, bison_gid,
            limit=5, metric='interested_leads', days=days
        )

        # Get underperformers
        underperformers = get_underperforming_clients(
            sheet_url, instantly_gid, bison_gid,
            threshold=5, metric='interested_leads', days=days
        )

        return {
            'period': 'Last 7 days',
            'total_leads': platform_stats['total']['interested_leads'],
            'total_sent': platform_stats['total']['sent'],
            'total_replies': platform_stats['total']['replies'],
            'overall_reply_rate': platform_stats['total']['reply_rate'],
            'overall_interested_rate': platform_stats['total']['interested_rate'],
            'platform_breakdown': {
                'instantly': platform_stats['instantly'],
                'bison': platform_stats['bison']
            },
            'top_performers': top_clients['clients'],
            'underperformers': underperformers['clients'],
            'total_clients': platform_stats['total_clients']
        }

    except Exception as e:
        logger.error(f"Error generating weekly summary: {e}")
        raise
