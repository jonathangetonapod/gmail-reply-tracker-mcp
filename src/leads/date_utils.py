"""
Date validation and utility functions for lead management.
"""

from datetime import datetime, timedelta


def validate_and_parse_dates(start_date: str = None, end_date: str = None, days: int = 7):
    """
    Validate and parse date parameters with safeguards to prevent common errors.

    Safeguards:
    1. Warns if dates are more than 6 months old
    2. Ensures start_date is before end_date
    3. Warns if dates are in the future
    4. Validates date format
    5. Returns properly formatted dates

    Args:
        start_date: Start date string (YYYY-MM-DD or ISO format)
        end_date: End date string (YYYY-MM-DD or ISO format)
        days: Number of days to look back if dates not provided

    Returns:
        (start_date_str, end_date_str, warnings_list)

    Raises:
        ValueError: If dates are invalid
    """
    warnings = []
    current_time = datetime.now()

    # If no dates provided, calculate from days
    if not start_date or not end_date:
        end = current_time
        start = end - timedelta(days=days)
        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")
        print(f"[Date Validation] Using date range: {start_date} to {end_date} (last {days} days)")
        return start_date, end_date, warnings

    # Parse provided dates
    try:
        # Handle ISO format (with time) and simple YYYY-MM-DD format
        if 'T' in start_date:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        else:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")

        if 'T' in end_date:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        else:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(
            f"Invalid date format. Please use YYYY-MM-DD format.\n"
            f"Start date: {start_date}\n"
            f"End date: {end_date}\n"
            f"Error: {e}"
        )

    # Safeguard 1: Check if start_date is before end_date
    if start_dt > end_dt:
        raise ValueError(
            f"Start date ({start_date}) must be before end date ({end_date})"
        )

    # Safeguard 2: Warn if dates are more than 6 months old
    six_months_ago = current_time - timedelta(days=180)
    if end_dt.replace(tzinfo=None) < six_months_ago:
        age_days = (current_time - end_dt.replace(tzinfo=None)).days
        warnings.append(
            f"WARNING: End date ({end_date}) is {age_days} days old (more than 6 months). "
            f"Did you mean {end_dt.year + 1} instead of {end_dt.year}?"
        )

    # Safeguard 3: Warn if start date is from previous year but we're in the same month
    if start_dt.year < current_time.year and start_dt.month == current_time.month:
        warnings.append(
            f"WARNING: Start date uses year {start_dt.year} but current year is {current_time.year}. "
            f"Did you mean {current_time.year}-{start_dt.month:02d}-{start_dt.day:02d}?"
        )

    # Safeguard 4: Warn if dates are in the future
    if start_dt.replace(tzinfo=None) > current_time:
        warnings.append(
            f"WARNING: Start date ({start_date}) is in the future"
        )
    if end_dt.replace(tzinfo=None) > current_time:
        warnings.append(
            f"WARNING: End date ({end_date}) is in the future"
        )

    # Log validation results
    if warnings:
        print(f"[Date Validation] Using dates: {start_date} to {end_date}")
        for warning in warnings:
            print(f"[Date Validation] {warning}")
    else:
        print(f"[Date Validation] Dates validated: {start_date} to {end_date}")

    # Return dates in YYYY-MM-DD format
    return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"), warnings
