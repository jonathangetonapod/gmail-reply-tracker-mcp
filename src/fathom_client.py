"""Fathom AI API client wrapper with error handling and rate limiting."""

import time
import logging
import requests
from typing import List, Dict, Any, Optional
from collections import deque


logger = logging.getLogger(__name__)


class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, max_requests_per_minute: int = 60):
        """
        Initialize rate limiter.

        Args:
            max_requests_per_minute: Maximum API requests per minute
        """
        self.max_requests = max_requests_per_minute
        self.window = 60.0  # seconds
        self.requests = deque()

    def wait_if_needed(self):
        """Wait if rate limit would be exceeded."""
        now = time.time()

        # Remove requests outside the window
        while self.requests and self.requests[0] < now - self.window:
            self.requests.popleft()

        # Check if we've hit the limit
        if len(self.requests) >= self.max_requests:
            # Calculate wait time
            oldest_request = self.requests[0]
            wait_time = (oldest_request + self.window) - now

            if wait_time > 0:
                logger.warning(
                    "Rate limit reached. Waiting %.2f seconds...",
                    wait_time
                )
                time.sleep(wait_time)

                # Clean up after waiting
                now = time.time()
                while self.requests and self.requests[0] < now - self.window:
                    self.requests.popleft()

        # Record this request
        self.requests.append(time.time())


class FathomClient:
    """Wrapper for Fathom AI API with error handling and rate limiting."""

    BASE_URL = "https://api.fathom.ai/external/v1"

    def __init__(self, api_key: str, max_requests_per_minute: int = 60):
        """
        Initialize Fathom API client.

        Args:
            api_key: Fathom API key
            max_requests_per_minute: Maximum API requests per minute
        """
        self.api_key = api_key
        self.rate_limiter = RateLimiter(max_requests_per_minute)
        self.session = requests.Session()
        self.session.headers.update({
            'X-Api-Key': api_key,
            'Content-Type': 'application/json'
        })

    def _execute_with_retry(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Execute Fathom API request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (without base URL)
            params: Query parameters
            json_data: JSON body data
            max_retries: Maximum number of retry attempts

        Returns:
            API response as dictionary

        Raises:
            requests.HTTPError: If request fails after retries
        """
        self.rate_limiter.wait_if_needed()

        url = f"{self.BASE_URL}/{endpoint}"

        for attempt in range(max_retries):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                    timeout=30
                )

                # Handle different status codes
                if response.status_code == 200:
                    return response.json()

                elif response.status_code == 401:
                    logger.error("Authentication error: Invalid API key")
                    raise requests.HTTPError(
                        "Authentication failed. Check your Fathom API key.",
                        response=response
                    )

                elif response.status_code == 404:
                    logger.error("Resource not found: %s", url)
                    raise requests.HTTPError(
                        f"Resource not found: {endpoint}",
                        response=response
                    )

                elif response.status_code == 429:
                    # Rate limit - wait and retry
                    wait_time = 2 ** attempt
                    logger.warning(
                        "Rate limit error (attempt %d/%d). Waiting %d seconds...",
                        attempt + 1,
                        max_retries,
                        wait_time
                    )
                    time.sleep(wait_time)
                    continue

                elif response.status_code >= 500:
                    # Server error - retry
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.warning(
                            "Server error (attempt %d/%d). Waiting %d seconds...",
                            attempt + 1,
                            max_retries,
                            wait_time
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error("Server error after %d attempts", max_retries)
                        raise requests.HTTPError(
                            f"Server error: {response.status_code}",
                            response=response
                        )

                else:
                    # Other errors - don't retry
                    logger.error("HTTP error %d: %s", response.status_code, response.text)
                    raise requests.HTTPError(
                        f"HTTP {response.status_code}: {response.text}",
                        response=response
                    )

            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    logger.warning("Request timeout (attempt %d/%d)", attempt + 1, max_retries)
                    continue
                else:
                    logger.error("Request timeout after %d attempts", max_retries)
                    raise

            except requests.exceptions.RequestException as e:
                logger.error("Request exception: %s", str(e))
                raise

        # Should not reach here
        raise Exception("Request failed after all retries")

    def list_meetings(
        self,
        limit: int = 50,
        cursor: Optional[str] = None,
        calendar_invitees_domains_type: str = "all",
        created_after: Optional[str] = None,
        created_before: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List meetings with pagination support.

        Args:
            limit: Maximum number of meetings to return per page (default: 50)
            cursor: Pagination cursor from previous response
            calendar_invitees_domains_type: Filter by domain type
                - "all": All meetings
                - "internal_only": Only meetings with internal attendees
                - "one_or_more_external": Meetings with at least one external attendee
            created_after: Filter to meetings created after this timestamp (ISO 8601 format)
                Example: "2025-01-01T00:00:00Z"
            created_before: Filter to meetings created before this timestamp (ISO 8601 format)
                Example: "2025-12-31T23:59:59Z"

        Returns:
            Dictionary with 'items' (list of meetings), 'limit', and 'next_cursor'

        Raises:
            requests.HTTPError: If API request fails
        """
        params = {
            'limit': limit,
            'calendar_invitees_domains_type': calendar_invitees_domains_type
        }

        if cursor:
            params['cursor'] = cursor

        if created_after:
            params['created_after'] = created_after

        if created_before:
            params['created_before'] = created_before

        response = self._execute_with_retry('GET', 'meetings', params=params)

        items = response.get('items', [])
        logger.info("Retrieved %d meetings", len(items))

        return response

    def get_meeting_transcript(self, recording_id: int) -> Dict[str, Any]:
        """
        Get transcript for a specific recording.

        Args:
            recording_id: Fathom recording ID

        Returns:
            Dictionary with 'transcript' containing list of transcript segments

        Raises:
            requests.HTTPError: If API request fails or recording not found
        """
        response = self._execute_with_retry(
            'GET',
            f'recordings/{recording_id}/transcript'
        )

        logger.info("Retrieved transcript for recording %d", recording_id)
        return response

    def get_meeting_summary(self, recording_id: int) -> Dict[str, Any]:
        """
        Get summary for a specific recording.

        Args:
            recording_id: Fathom recording ID

        Returns:
            Dictionary with 'summary' containing template_name and markdown_formatted

        Raises:
            requests.HTTPError: If API request fails or recording not found
        """
        response = self._execute_with_retry(
            'GET',
            f'recordings/{recording_id}/summary'
        )

        logger.info("Retrieved summary for recording %d", recording_id)
        return response

    def search_meetings_by_title(
        self,
        search_term: str,
        limit: int = 50,
        calendar_invitees_domains_type: str = "all",
        created_after: Optional[str] = None,
        created_before: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search meetings by title.

        Args:
            search_term: Search term to match in meeting titles
            limit: Maximum number of meetings to search through
            calendar_invitees_domains_type: Filter by domain type
            created_after: Filter to meetings created after this timestamp (ISO 8601 format)
            created_before: Filter to meetings created before this timestamp (ISO 8601 format)

        Returns:
            List of meetings matching the search term

        Raises:
            requests.HTTPError: If API request fails
        """
        meetings = self.list_meetings(
            limit=limit,
            calendar_invitees_domains_type=calendar_invitees_domains_type,
            created_after=created_after,
            created_before=created_before
        )

        items = meetings.get('items', [])
        search_term_lower = search_term.lower()

        matched = [
            meeting for meeting in items
            if search_term_lower in meeting.get('title', '').lower()
            or search_term_lower in meeting.get('meeting_title', '').lower()
        ]

        logger.info("Found %d meetings matching '%s'", len(matched), search_term)
        return matched

    def search_meetings_by_attendee(
        self,
        email: str,
        limit: int = 50,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Find meetings with a specific attendee.

        Args:
            email: Email address to search for
            limit: Maximum number of meetings to search through
            created_after: Filter to meetings created after this timestamp (ISO 8601 format)
            created_before: Filter to meetings created before this timestamp (ISO 8601 format)

        Returns:
            List of meetings with the specified attendee

        Raises:
            requests.HTTPError: If API request fails
        """
        meetings = self.list_meetings(
            limit=limit,
            created_after=created_after,
            created_before=created_before
        )
        items = meetings.get('items', [])
        email_lower = email.lower()

        matched = []
        for meeting in items:
            attendees = meeting.get('calendar_invitees', [])
            for attendee in attendees:
                if email_lower in attendee.get('email', '').lower():
                    matched.append(meeting)
                    break

        logger.info("Found %d meetings with attendee '%s'", len(matched), email)
        return matched

    def get_all_meetings(
        self,
        max_meetings: int = 200,
        calendar_invitees_domains_type: str = "all",
        created_after: Optional[str] = None,
        created_before: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch all meetings with pagination handling.

        Args:
            max_meetings: Maximum total meetings to fetch
            calendar_invitees_domains_type: Filter by domain type
            created_after: Filter to meetings created after this timestamp
            created_before: Filter to meetings created before this timestamp

        Returns:
            List of all meetings

        Raises:
            requests.HTTPError: If API request fails
        """
        all_meetings = []
        cursor = None

        while len(all_meetings) < max_meetings:
            remaining = max_meetings - len(all_meetings)
            limit = min(50, remaining)

            response = self.list_meetings(
                limit=limit,
                cursor=cursor,
                calendar_invitees_domains_type=calendar_invitees_domains_type,
                created_after=created_after,
                created_before=created_before
            )

            items = response.get('items', [])
            if not items:
                break

            all_meetings.extend(items)

            cursor = response.get('next_cursor')
            if not cursor:
                break

        logger.info("Fetched %d total meetings", len(all_meetings))
        return all_meetings
