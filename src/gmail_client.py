"""Gmail API client wrapper with error handling and rate limiting."""

import time
import logging
from typing import List, Dict, Any, Optional
from collections import deque

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials


logger = logging.getLogger(__name__)


class RateLimiter:
    """Token bucket rate limiter for Gmail API calls."""

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


class GmailClient:
    """Wrapper for Gmail API with error handling and rate limiting."""

    def __init__(self, credentials: Credentials, max_requests_per_minute: int = 60):
        """
        Initialize Gmail API client.

        Args:
            credentials: OAuth 2.0 credentials
            max_requests_per_minute: Maximum API requests per minute
        """
        self.credentials = credentials
        self.service = build('gmail', 'v1', credentials=credentials)
        self.rate_limiter = RateLimiter(max_requests_per_minute)
        self._user_email: Optional[str] = None

    def _execute_with_retry(self, request, max_retries: int = 3):
        """
        Execute Gmail API request with retry logic.

        Args:
            request: Gmail API request object
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

    def get_user_profile(self) -> Dict[str, Any]:
        """
        Get the authenticated user's Gmail profile.

        Returns:
            Profile dict with emailAddress, messagesTotal, threadsTotal, etc.

        Raises:
            HttpError: If API request fails
        """
        if self._user_email is None:
            request = self.service.users().getProfile(userId='me')
            profile = self._execute_with_retry(request)
            self._user_email = profile.get('emailAddress')
            logger.info("Retrieved user profile: %s", self._user_email)
            return profile
        else:
            # Return cached profile with email
            return {'emailAddress': self._user_email}

    def get_user_email(self) -> str:
        """
        Get the authenticated user's email address.

        Returns:
            Email address string

        Raises:
            HttpError: If API request fails
        """
        if self._user_email is None:
            profile = self.get_user_profile()
            self._user_email = profile.get('emailAddress')

        return self._user_email

    def list_threads(self, query: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """
        List threads matching a query.

        Args:
            query: Gmail search query (e.g., "after:2024/01/01 -in:sent")
            max_results: Maximum number of threads to return

        Returns:
            List of thread objects (with 'id' and 'snippet')

        Raises:
            HttpError: If API request fails
        """
        request = self.service.users().threads().list(
            userId='me',
            q=query,
            maxResults=max_results,
            includeSpamTrash=False
        )

        response = self._execute_with_retry(request)
        threads = response.get('threads', [])

        logger.info("Found %d threads matching query: %s", len(threads), query)
        return threads

    def get_thread(self, thread_id: str) -> Dict[str, Any]:
        """
        Get a complete thread with all messages.

        Args:
            thread_id: Thread ID

        Returns:
            Thread object with messages

        Raises:
            HttpError: If API request fails or thread not found
        """
        request = self.service.users().threads().get(
            userId='me',
            id=thread_id,
            format='full',
            metadataHeaders=['From', 'To', 'Subject', 'Date', 'Message-ID', 'In-Reply-To']
        )

        thread = self._execute_with_retry(request)
        logger.debug("Retrieved thread %s with %d messages", thread_id, len(thread.get('messages', [])))
        return thread

    def list_messages(self, query: str, max_results: int = 20) -> List[Dict[str, Any]]:
        """
        List messages matching a query.

        Args:
            query: Gmail search query
            max_results: Maximum number of messages to return

        Returns:
            List of message objects (with 'id' and 'threadId')

        Raises:
            HttpError: If API request fails
        """
        request = self.service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_results,
            includeSpamTrash=False
        )

        response = self._execute_with_retry(request)
        messages = response.get('messages', [])

        logger.info("Found %d messages matching query: %s", len(messages), query)
        return messages

    def get_message(self, message_id: str) -> Dict[str, Any]:
        """
        Get a single message with full details.

        Args:
            message_id: Message ID

        Returns:
            Message object with headers and payload

        Raises:
            HttpError: If API request fails or message not found
        """
        request = self.service.users().messages().get(
            userId='me',
            id=message_id,
            format='full'
        )

        message = self._execute_with_retry(request)
        logger.debug("Retrieved message %s", message_id)
        return message

    def batch_get_messages(self, message_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Get multiple messages efficiently.

        Note: This is a simple implementation that fetches messages one by one.
        For production, consider using batch requests for better performance.

        Args:
            message_ids: List of message IDs

        Returns:
            List of message objects

        Raises:
            HttpError: If any API request fails
        """
        messages = []
        for message_id in message_ids:
            try:
                message = self.get_message(message_id)
                messages.append(message)
            except HttpError as e:
                if e.resp.status == 404:
                    logger.warning("Message %s not found, skipping", message_id)
                else:
                    raise

        logger.info("Retrieved %d/%d messages", len(messages), len(message_ids))
        return messages
