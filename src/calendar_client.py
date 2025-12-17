"""Google Calendar API client wrapper with error handling and rate limiting."""

import time
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from collections import deque

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials


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


class CalendarClient:
    """Wrapper for Google Calendar API with error handling and rate limiting."""

    def __init__(self, credentials: Credentials, max_requests_per_minute: int = 60):
        """
        Initialize Calendar API client.

        Args:
            credentials: OAuth 2.0 credentials
            max_requests_per_minute: Maximum API requests per minute
        """
        self.credentials = credentials
        self.service = build('calendar', 'v3', credentials=credentials)
        self.rate_limiter = RateLimiter(max_requests_per_minute)

    def _execute_with_retry(self, request, max_retries: int = 3):
        """
        Execute Calendar API request with retry logic.

        Args:
            request: Calendar API request object
            max_retries: Maximum number of retry attempts

        Returns:
            API response

        Raises:
            HttpError: If request fails after retries
        """
        self.rate_limiter.wait_if_needed()

        for attempt in range(max_retries):
            try:
                return request.execute()

            except HttpError as e:
                status_code = e.resp.status

                # 401: Authentication error - don't retry
                if status_code == 401:
                    logger.error("Authentication error: %s", str(e))
                    raise

                # 404: Not found - don't retry
                elif status_code == 404:
                    logger.error("Resource not found: %s", str(e))
                    raise

                # 429: Rate limit - wait and retry
                elif status_code == 429:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(
                        "Rate limit error (attempt %d/%d). Waiting %d seconds...",
                        attempt + 1,
                        max_retries,
                        wait_time
                    )
                    time.sleep(wait_time)
                    continue

                # 500/503: Server error - retry
                elif status_code in [500, 503]:
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
                        logger.error("Server error after %d attempts: %s", max_retries, str(e))
                        raise

                # Other errors - don't retry
                else:
                    logger.error("HTTP error %d: %s", status_code, str(e))
                    raise

        # Should not reach here
        raise Exception("Request failed after all retries")

    def list_calendars(self) -> List[Dict[str, Any]]:
        """
        List all calendars accessible to the user.

        Returns:
            List of calendar objects with id, summary, description, etc.

        Raises:
            HttpError: If API request fails
        """
        request = self.service.calendarList().list()
        response = self._execute_with_retry(request)
        calendars = response.get('items', [])

        logger.info("Found %d calendars", len(calendars))
        return calendars

    def list_events(
        self,
        calendar_id: str = 'primary',
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 50,
        query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List events from a calendar.

        Args:
            calendar_id: Calendar ID (default: 'primary')
            time_min: Start of time range (default: now)
            time_max: End of time range (default: None)
            max_results: Maximum number of events to return
            query: Free text search query

        Returns:
            List of event objects

        Raises:
            HttpError: If API request fails
        """
        # Default to now if not specified
        if time_min is None:
            time_min = datetime.utcnow()

        # Format as RFC3339
        time_min_str = time_min.isoformat() + 'Z'
        time_max_str = time_max.isoformat() + 'Z' if time_max else None

        request_params = {
            'calendarId': calendar_id,
            'timeMin': time_min_str,
            'maxResults': max_results,
            'singleEvents': True,
            'orderBy': 'startTime'
        }

        if time_max_str:
            request_params['timeMax'] = time_max_str

        if query:
            request_params['q'] = query

        request = self.service.events().list(**request_params)
        response = self._execute_with_retry(request)
        events = response.get('items', [])

        logger.info("Found %d events in calendar %s", len(events), calendar_id)
        return events

    def get_event(self, event_id: str, calendar_id: str = 'primary') -> Dict[str, Any]:
        """
        Get a specific event by ID.

        Args:
            event_id: Event ID
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            Event object

        Raises:
            HttpError: If API request fails or event not found
        """
        request = self.service.events().get(
            calendarId=calendar_id,
            eventId=event_id
        )

        event = self._execute_with_retry(request)
        logger.debug("Retrieved event %s", event_id)
        return event

    def create_event(
        self,
        summary: str,
        start_time: datetime,
        end_time: datetime,
        calendar_id: str = 'primary',
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        time_zone: str = 'UTC',
        add_meet_link: bool = False
    ) -> Dict[str, Any]:
        """
        Create a new calendar event.

        Args:
            summary: Event title
            start_time: Event start time
            end_time: Event end time
            calendar_id: Calendar ID (default: 'primary')
            description: Event description
            location: Event location
            attendees: List of attendee email addresses
            time_zone: Time zone (default: 'UTC')
            add_meet_link: If True, automatically add a Google Meet link (default: False)

        Returns:
            Created event object

        Raises:
            HttpError: If API request fails
        """
        event = {
            'summary': summary,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': time_zone,
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': time_zone,
            }
        }

        if description:
            event['description'] = description

        if location:
            event['location'] = location

        if attendees:
            event['attendees'] = [{'email': email} for email in attendees]

        # Add Google Meet conference if requested
        if add_meet_link:
            event['conferenceData'] = {
                'createRequest': {
                    'requestId': f"{summary}-{int(start_time.timestamp())}",  # Unique ID for this request
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            }

        request_params = {
            'calendarId': calendar_id,
            'body': event,
            'sendUpdates': 'all'  # Send email notifications to all attendees
        }

        # If adding Meet link, need to set conferenceDataVersion
        if add_meet_link:
            request_params['conferenceDataVersion'] = 1

        request = self.service.events().insert(**request_params)

        created_event = self._execute_with_retry(request)

        # Log Google Meet link if present
        if add_meet_link and 'conferenceData' in created_event:
            meet_link = created_event['conferenceData'].get('entryPoints', [{}])[0].get('uri', 'N/A')
            logger.info("Created event: %s (ID: %s) with Google Meet: %s", summary, created_event['id'], meet_link)
        else:
            logger.info("Created event: %s (ID: %s)", summary, created_event['id'])

        return created_event

    def update_event(
        self,
        event_id: str,
        calendar_id: str = 'primary',
        summary: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        time_zone: str = 'UTC'
    ) -> Dict[str, Any]:
        """
        Update an existing calendar event.

        Args:
            event_id: Event ID
            calendar_id: Calendar ID (default: 'primary')
            summary: New event title
            start_time: New start time
            end_time: New end time
            description: New description
            location: New location
            time_zone: Time zone (default: 'UTC')

        Returns:
            Updated event object

        Raises:
            HttpError: If API request fails
        """
        # First get the existing event
        event = self.get_event(event_id, calendar_id)

        # Update fields
        if summary is not None:
            event['summary'] = summary

        if start_time is not None:
            event['start'] = {
                'dateTime': start_time.isoformat(),
                'timeZone': time_zone,
            }

        if end_time is not None:
            event['end'] = {
                'dateTime': end_time.isoformat(),
                'timeZone': time_zone,
            }

        if description is not None:
            event['description'] = description

        if location is not None:
            event['location'] = location

        request = self.service.events().update(
            calendarId=calendar_id,
            eventId=event_id,
            body=event,
            sendUpdates='all'  # Send email notifications to all attendees
        )

        updated_event = self._execute_with_retry(request)
        logger.info("Updated event: %s", event_id)
        return updated_event

    def delete_event(self, event_id: str, calendar_id: str = 'primary') -> None:
        """
        Delete a calendar event.

        Args:
            event_id: Event ID
            calendar_id: Calendar ID (default: 'primary')

        Raises:
            HttpError: If API request fails
        """
        request = self.service.events().delete(
            calendarId=calendar_id,
            eventId=event_id
        )

        self._execute_with_retry(request)
        logger.info("Deleted event: %s", event_id)

    def quick_add_event(
        self,
        text: str,
        calendar_id: str = 'primary'
    ) -> Dict[str, Any]:
        """
        Create an event using natural language.

        Args:
            text: Natural language description (e.g., "Dinner with John tomorrow at 7pm")
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            Created event object

        Raises:
            HttpError: If API request fails
        """
        request = self.service.events().quickAdd(
            calendarId=calendar_id,
            text=text
        )

        event = self._execute_with_retry(request)
        logger.info("Quick added event: %s", text)
        return event

    def get_free_busy(
        self,
        calendar_ids: List[str],
        time_min: datetime,
        time_max: datetime
    ) -> Dict[str, Any]:
        """
        Check free/busy information for calendars.

        Args:
            calendar_ids: List of calendar IDs to check
            time_min: Start of time range
            time_max: End of time range

        Returns:
            Free/busy information for each calendar

        Raises:
            HttpError: If API request fails
        """
        body = {
            'timeMin': time_min.isoformat() + 'Z',
            'timeMax': time_max.isoformat() + 'Z',
            'items': [{'id': cal_id} for cal_id in calendar_ids]
        }

        request = self.service.freebusy().query(body=body)
        result = self._execute_with_retry(request)

        logger.info("Retrieved free/busy for %d calendars", len(calendar_ids))
        return result
