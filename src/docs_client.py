"""Google Docs API client wrapper with error handling and rate limiting."""

import time
import logging
import threading
from typing import List, Dict, Any, Optional
from collections import deque

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials


logger = logging.getLogger(__name__)


class RateLimiter:
    """Thread-safe token bucket rate limiter for Google Docs API calls."""

    def __init__(self, max_requests_per_minute: int = 60):
        """
        Initialize rate limiter.

        Args:
            max_requests_per_minute: Maximum API requests per minute
        """
        self.max_requests = max_requests_per_minute
        self.window = 60.0  # seconds
        self.requests = deque()
        self.lock = threading.Lock()

    def wait_if_needed(self):
        """Wait if rate limit would be exceeded. Thread-safe."""
        wait_time = 0

        # Check if we need to wait (hold lock only for checking)
        with self.lock:
            now = time.time()

            # Remove requests outside the window
            while self.requests and self.requests[0] < now - self.window:
                self.requests.popleft()

            # Check if we've hit the limit
            if len(self.requests) >= self.max_requests:
                # Calculate wait time
                oldest_request = self.requests[0]
                wait_time = (oldest_request + self.window) - now

        # Sleep OUTSIDE the lock to avoid blocking other threads
        if wait_time > 0:
            logger.warning(
                "Rate limit reached. Waiting %.2f seconds...",
                wait_time
            )
            time.sleep(wait_time)

        # Now record this request (acquire lock again)
        with self.lock:
            # Clean up after waiting
            now = time.time()
            while self.requests and self.requests[0] < now - self.window:
                self.requests.popleft()

            # Record this request
            self.requests.append(time.time())


class DocsClient:
    """Thread-safe wrapper for Google Docs API with error handling and rate limiting."""

    def __init__(self, credentials: Credentials, max_requests_per_minute: int = 60):
        """
        Initialize Google Docs API client.

        Args:
            credentials: OAuth 2.0 credentials
            max_requests_per_minute: Maximum API requests per minute
        """
        self.credentials = credentials
        self.service = build('docs', 'v1', credentials=credentials)
        self.rate_limiter = RateLimiter(max_requests_per_minute)
        self.service_lock = threading.Lock()

    def _execute_with_retry(self, request, max_retries: int = 3):
        """
        Execute Google Docs API request with retry logic.

        Args:
            request: Google Docs API request object
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
                if e.resp.status in [403, 429, 500, 503] and attempt < max_retries - 1:
                    # Rate limit or server error - retry with exponential backoff
                    wait_time = (2 ** attempt)
                    logger.warning(
                        "API error %d on attempt %d. Retrying in %d seconds...",
                        e.resp.status, attempt + 1, wait_time
                    )
                    time.sleep(wait_time)
                else:
                    raise

    def create_document(self, title: str) -> Dict[str, Any]:
        """
        Create a new Google Doc.

        Args:
            title: Title of the document

        Returns:
            Document object containing documentId and title

        Example:
            doc = client.create_document("My New Document")
            print(f"Created doc: {doc['title']} with ID: {doc['documentId']}")
        """
        logger.info(f"Creating document: {title}")

        body = {
            'title': title
        }

        request = self.service.documents().create(body=body)
        doc = self._execute_with_retry(request)

        logger.info(f"Created document with ID: {doc['documentId']}")
        return doc

    def get_document(self, document_id: str) -> Dict[str, Any]:
        """
        Get a document's content and metadata.

        Args:
            document_id: The ID of the document

        Returns:
            Document object with full content

        Example:
            doc = client.get_document("1abc...")
            print(doc['title'])
        """
        logger.info(f"Getting document: {document_id}")

        request = self.service.documents().get(documentId=document_id)
        doc = self._execute_with_retry(request)

        return doc

    def insert_text(self, document_id: str, text: str, index: int = 1) -> Dict[str, Any]:
        """
        Insert text at a specific index in the document.

        Args:
            document_id: The ID of the document
            text: Text to insert
            index: Character index where to insert (default: 1, which is after title)

        Returns:
            Result of the batch update

        Example:
            result = client.insert_text("1abc...", "Hello World", index=1)
        """
        logger.info(f"Inserting text at index {index} in document: {document_id}")

        requests = [{
            'insertText': {
                'location': {
                    'index': index
                },
                'text': text
            }
        }]

        body = {'requests': requests}
        request = self.service.documents().batchUpdate(
            documentId=document_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully inserted text")
        return result

    def append_text(self, document_id: str, text: str) -> Dict[str, Any]:
        """
        Append text to the end of the document.

        Args:
            document_id: The ID of the document
            text: Text to append

        Returns:
            Result of the batch update

        Example:
            result = client.append_text("1abc...", "\\n\\nNew paragraph at the end")
        """
        logger.info(f"Appending text to document: {document_id}")

        # Get current document to find end index
        doc = self.get_document(document_id)
        end_index = doc['body']['content'][-1]['endIndex']

        # Insert at end (minus 1 because end_index is exclusive)
        return self.insert_text(document_id, text, index=end_index - 1)

    def replace_all_text(self, document_id: str, old_text: str, new_text: str) -> Dict[str, Any]:
        """
        Replace all occurrences of text in the document.

        Args:
            document_id: The ID of the document
            old_text: Text to find
            new_text: Text to replace with

        Returns:
            Result of the batch update

        Example:
            result = client.replace_all_text("1abc...", "{{name}}", "John Smith")
        """
        logger.info(f"Replacing '{old_text}' with '{new_text}' in document: {document_id}")

        requests = [{
            'replaceAllText': {
                'containsText': {
                    'text': old_text,
                    'matchCase': False
                },
                'replaceText': new_text
            }
        }]

        body = {'requests': requests}
        request = self.service.documents().batchUpdate(
            documentId=document_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully replaced text")
        return result

    def format_text(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        font_size: Optional[int] = None,
        foreground_color: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Apply formatting to a range of text.

        Args:
            document_id: The ID of the document
            start_index: Start of the range
            end_index: End of the range
            bold: Make text bold
            italic: Make text italic
            font_size: Font size in points
            foreground_color: Text color as RGB dict, e.g., {'red': 1.0, 'green': 0.0, 'blue': 0.0}

        Returns:
            Result of the batch update

        Example:
            # Make first 10 characters bold and red
            result = client.format_text(
                "1abc...",
                start_index=1,
                end_index=11,
                bold=True,
                foreground_color={'red': 1.0, 'green': 0.0, 'blue': 0.0}
            )
        """
        logger.info(f"Formatting text from {start_index} to {end_index} in document: {document_id}")

        text_style = {}
        if bold is not None:
            text_style['bold'] = bold
        if italic is not None:
            text_style['italic'] = italic
        if font_size is not None:
            text_style['fontSize'] = {
                'magnitude': font_size,
                'unit': 'PT'
            }
        if foreground_color is not None:
            text_style['foregroundColor'] = {
                'color': {
                    'rgbColor': foreground_color
                }
            }

        requests = [{
            'updateTextStyle': {
                'range': {
                    'startIndex': start_index,
                    'endIndex': end_index
                },
                'textStyle': text_style,
                'fields': ','.join(text_style.keys())
            }
        }]

        body = {'requests': requests}
        request = self.service.documents().batchUpdate(
            documentId=document_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully formatted text")
        return result

    def insert_paragraph(
        self,
        document_id: str,
        text: str,
        index: int = 1,
        heading: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Insert a paragraph with optional heading style.

        Args:
            document_id: The ID of the document
            text: Paragraph text
            index: Where to insert
            heading: Heading style: "HEADING_1", "HEADING_2", "HEADING_3", etc., or None for normal text

        Returns:
            Result of the batch update

        Example:
            result = client.insert_paragraph("1abc...", "Introduction", index=1, heading="HEADING_1")
        """
        logger.info(f"Inserting paragraph at index {index} in document: {document_id}")

        # Add newline after text if not present
        if not text.endswith('\n'):
            text += '\n'

        requests = [{
            'insertText': {
                'location': {'index': index},
                'text': text
            }
        }]

        # If heading style is specified, add styling request
        if heading:
            requests.append({
                'updateParagraphStyle': {
                    'range': {
                        'startIndex': index,
                        'endIndex': index + len(text)
                    },
                    'paragraphStyle': {
                        'namedStyleType': heading
                    },
                    'fields': 'namedStyleType'
                }
            })

        body = {'requests': requests}
        request = self.service.documents().batchUpdate(
            documentId=document_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully inserted paragraph")
        return result

    def extract_text(self, document_id: str) -> str:
        """
        Extract all text content from a document.

        Args:
            document_id: The ID of the document

        Returns:
            Plain text content of the document

        Example:
            text = client.extract_text("1abc...")
            print(text)
        """
        logger.info(f"Extracting text from document: {document_id}")

        doc = self.get_document(document_id)

        text_parts = []
        for element in doc.get('body', {}).get('content', []):
            if 'paragraph' in element:
                for text_run in element['paragraph'].get('elements', []):
                    if 'textRun' in text_run:
                        text_parts.append(text_run['textRun']['content'])

        return ''.join(text_parts)

    def get_document_url(self, document_id: str) -> str:
        """
        Get the Google Docs URL for a document.

        Args:
            document_id: The ID of the document

        Returns:
            Full URL to open the document in Google Docs

        Example:
            url = client.get_document_url("1abc...")
            print(f"Open doc at: {url}")
        """
        return f"https://docs.google.com/document/d/{document_id}/edit"
