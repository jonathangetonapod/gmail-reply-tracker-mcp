"""Email analysis engine for detecting unreplied emails and automated messages."""

import re
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime


logger = logging.getLogger(__name__)


@dataclass
class SenderInfo:
    """Information about an email sender."""
    email: str
    name: Optional[str]
    domain: str


class EmailAnalyzer:
    """Analyzes emails to detect unreplied messages and automated emails."""

    # Patterns for detecting automated emails
    AUTOMATED_FROM_PATTERNS = [
        r'no[-_]?reply@',
        r'do[-_]?not[-_]?reply@',
        r'noreply@',
        r'automated@',
        r'notifications?@',
        r'alert(s)?@',
        r'bounce@',
        r'mailer[-_]?daemon@',
        r'postmaster@',
        r'newsletter@',
        r'digest@',
        r'updates?@',
        r'marketing@',
        r'info@',
        r'support@.*\.(zendesk|freshdesk|helpscout)',
    ]

    def __init__(self):
        """Initialize the email analyzer."""
        # Compile regex patterns for better performance
        self.automated_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.AUTOMATED_FROM_PATTERNS
        ]

    def is_unreplied(self, thread: Dict[str, Any], user_email: str) -> bool:
        """
        Determine if a thread needs a reply.

        A thread needs a reply if:
        1. The last message is from someone else (not the user)
        2. The user has read it (no UNREAD label)
        3. It's not an automated email

        Args:
            thread: Gmail thread object with messages
            user_email: The authenticated user's email address

        Returns:
            True if thread needs a reply, False otherwise
        """
        messages = thread.get('messages', [])

        if not messages:
            logger.debug("Thread has no messages")
            return False

        # Gmail API returns messages in chronological order (oldest first)
        last_message = messages[-1]

        # Check 1: Is the last message from someone else?
        sender_email = self.extract_sender_email(last_message)
        if not sender_email:
            logger.debug("Could not extract sender email")
            return False

        # Normalize emails for comparison
        sender_email_normalized = sender_email.lower().strip()
        user_email_normalized = user_email.lower().strip()

        if sender_email_normalized == user_email_normalized:
            logger.debug("Last message is from user, no reply needed")
            return False

        # Check 2: Is the message read (not UNREAD)?
        label_ids = set(last_message.get('labelIds', []))
        if 'UNREAD' in label_ids:
            logger.debug("Message is unread, skipping")
            return False

        # Check 3: Is it not an automated email?
        if self.is_automated_email(last_message):
            logger.debug("Message is automated, no reply needed")
            return False

        # All conditions met - needs reply!
        logger.debug("Thread needs reply from %s", sender_email)
        return True

    def is_automated_email(self, message: Dict[str, Any]) -> bool:
        """
        Detect if an email is automated/system-generated.

        Checks:
        1. From address patterns (no-reply@, noreply@, etc.)
        2. Auto-Submitted header (RFC 3834)
        3. Precedence header (bulk, list, junk)
        4. List-Unsubscribe header (newsletters)
        5. X-Auto-Response-Suppress header (Microsoft)

        Args:
            message: Gmail message object

        Returns:
            True if email appears to be automated, False otherwise
        """
        headers = self.parse_headers(message.get('payload', {}).get('headers', []))

        # Check 1: From address patterns
        from_address = headers.get('From', '').lower()

        for pattern in self.automated_patterns:
            if pattern.search(from_address):
                logger.debug("Detected automated email via From pattern: %s", from_address)
                return True

        # Check 2: Auto-Submitted header (RFC 3834)
        auto_submitted = headers.get('Auto-Submitted', '').lower()
        if auto_submitted and auto_submitted != 'no':
            logger.debug("Detected automated email via Auto-Submitted header: %s", auto_submitted)
            return True

        # Check 3: Precedence header
        precedence = headers.get('Precedence', '').lower()
        if precedence in ['bulk', 'junk', 'list']:
            logger.debug("Detected automated email via Precedence header: %s", precedence)
            return True

        # Check 4: List-Unsubscribe header (newsletters)
        if 'List-Unsubscribe' in headers:
            logger.debug("Detected automated email via List-Unsubscribe header")
            return True

        # Check 5: X-Auto-Response-Suppress (Microsoft)
        if 'X-Auto-Response-Suppress' in headers:
            logger.debug("Detected automated email via X-Auto-Response-Suppress header")
            return True

        return False

    def parse_headers(self, headers: List[Dict[str, str]]) -> Dict[str, str]:
        """
        Convert Gmail API header list to dictionary.

        Gmail returns headers as:
        [{'name': 'From', 'value': 'foo@bar.com'}, ...]

        This converts to:
        {'From': 'foo@bar.com', ...}

        Args:
            headers: List of header dicts from Gmail API

        Returns:
            Dictionary mapping header name to value
        """
        return {h['name']: h['value'] for h in headers}

    def extract_sender_email(self, message: Dict[str, Any]) -> Optional[str]:
        """
        Extract email address from From header.

        Handles various formats:
        - "Name" <email@domain.com>
        - Name <email@domain.com>
        - email@domain.com
        - <email@domain.com>

        Args:
            message: Gmail message object

        Returns:
            Email address or None if not found
        """
        headers = self.parse_headers(message.get('payload', {}).get('headers', []))
        from_header = headers.get('From', '')

        if not from_header:
            return None

        # Try to extract email from angle brackets
        match = re.search(r'<([^>]+)>', from_header)
        if match:
            return match.group(1).strip()

        # If no brackets, assume it's just the email
        # Remove any quotes and whitespace
        email = from_header.strip().strip('"').strip("'")

        # Basic validation - must contain @
        if '@' in email:
            return email

        logger.warning("Could not extract email from: %s", from_header)
        return None

    def extract_sender_info(self, message: Dict[str, Any]) -> Optional[SenderInfo]:
        """
        Extract detailed sender information.

        Args:
            message: Gmail message object

        Returns:
            SenderInfo object or None if extraction fails
        """
        headers = self.parse_headers(message.get('payload', {}).get('headers', []))
        from_header = headers.get('From', '')

        if not from_header:
            return None

        email = self.extract_sender_email(message)
        if not email:
            return None

        # Extract name if present
        name = None
        name_match = re.match(r'^"?([^"<]+)"?\s*<', from_header)
        if name_match:
            name = name_match.group(1).strip()

        # Extract domain
        domain = email.split('@')[1] if '@' in email else ''

        return SenderInfo(
            email=email,
            name=name,
            domain=domain
        )

    def filter_unreplied_threads(
        self,
        threads: List[Dict[str, Any]],
        user_email: str
    ) -> List[Dict[str, Any]]:
        """
        Filter a list of threads to only unreplied ones.

        Args:
            threads: List of Gmail thread objects
            user_email: The authenticated user's email address

        Returns:
            List of threads that need replies
        """
        unreplied = []

        for thread in threads:
            if self.is_unreplied(thread, user_email):
                unreplied.append(thread)

        logger.info(
            "Filtered %d/%d threads as unreplied",
            len(unreplied),
            len(threads)
        )

        return unreplied

    def extract_subject(self, message: Dict[str, Any]) -> str:
        """
        Extract subject from a message.

        Args:
            message: Gmail message object

        Returns:
            Subject string (or empty string if not found)
        """
        headers = self.parse_headers(message.get('payload', {}).get('headers', []))
        return headers.get('Subject', '(No Subject)')

    def extract_date(self, message: Dict[str, Any]) -> Optional[str]:
        """
        Extract date from a message.

        Args:
            message: Gmail message object

        Returns:
            Date string from header or None
        """
        headers = self.parse_headers(message.get('payload', {}).get('headers', []))
        return headers.get('Date')

    def extract_received_timestamp(self, message: Dict[str, Any]) -> Optional[int]:
        """
        Extract internalDate (received timestamp) from message.

        Args:
            message: Gmail message object

        Returns:
            Unix timestamp in milliseconds or None
        """
        return message.get('internalDate')

    def format_unreplied_email(
        self,
        thread: Dict[str, Any],
        last_message: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Format unreplied email information for output.

        Args:
            thread: Gmail thread object
            last_message: The last message in the thread

        Returns:
            Dictionary with formatted email information
        """
        sender_info = self.extract_sender_info(last_message)
        subject = self.extract_subject(last_message)
        received_timestamp = self.extract_received_timestamp(last_message)

        # Convert timestamp to ISO format if available
        received_date = None
        if received_timestamp:
            try:
                dt = datetime.fromtimestamp(int(received_timestamp) / 1000.0)
                received_date = dt.isoformat()
            except (ValueError, OSError):
                pass

        return {
            'thread_id': thread.get('id'),
            'message_id': last_message.get('id'),
            'subject': subject,
            'sender': {
                'email': sender_info.email if sender_info else 'unknown',
                'name': sender_info.name if sender_info else None,
                'domain': sender_info.domain if sender_info else ''
            },
            'received_date': received_date,
            'snippet': last_message.get('snippet', ''),
            'labels': last_message.get('labelIds', [])
        }
