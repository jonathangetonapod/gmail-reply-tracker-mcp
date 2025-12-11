"""Unit tests for EmailAnalyzer."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from email_analyzer import EmailAnalyzer, SenderInfo


@pytest.fixture
def analyzer():
    """Create an EmailAnalyzer instance."""
    return EmailAnalyzer()


@pytest.fixture
def user_email():
    """Test user email."""
    return "user@example.com"


def create_message(from_addr: str, labels: list = None, headers: dict = None):
    """Helper to create a test message."""
    if labels is None:
        labels = []

    base_headers = [
        {'name': 'From', 'value': from_addr},
        {'name': 'Subject', 'value': 'Test Subject'},
        {'name': 'Date', 'value': 'Mon, 1 Jan 2024 12:00:00 +0000'}
    ]

    if headers:
        for key, value in headers.items():
            base_headers.append({'name': key, 'value': value})

    return {
        'id': 'msg123',
        'threadId': 'thread123',
        'labelIds': labels,
        'snippet': 'Test snippet',
        'internalDate': '1704110400000',
        'payload': {
            'headers': base_headers
        }
    }


def create_thread(messages: list):
    """Helper to create a test thread."""
    return {
        'id': 'thread123',
        'messages': messages
    }


class TestExtractSenderEmail:
    """Tests for extract_sender_email."""

    def test_email_with_name_and_brackets(self, analyzer):
        """Test extraction from 'Name <email@domain.com>' format."""
        message = create_message('"John Doe" <john@example.com>')
        result = analyzer.extract_sender_email(message)
        assert result == 'john@example.com'

    def test_email_with_name_no_quotes(self, analyzer):
        """Test extraction from 'Name <email@domain.com>' format without quotes."""
        message = create_message('John Doe <john@example.com>')
        result = analyzer.extract_sender_email(message)
        assert result == 'john@example.com'

    def test_email_plain(self, analyzer):
        """Test extraction from plain 'email@domain.com' format."""
        message = create_message('john@example.com')
        result = analyzer.extract_sender_email(message)
        assert result == 'john@example.com'

    def test_email_with_brackets_only(self, analyzer):
        """Test extraction from '<email@domain.com>' format."""
        message = create_message('<john@example.com>')
        result = analyzer.extract_sender_email(message)
        assert result == 'john@example.com'

    def test_missing_from_header(self, analyzer):
        """Test handling of missing From header."""
        message = {'payload': {'headers': []}}
        result = analyzer.extract_sender_email(message)
        assert result is None


class TestIsAutomatedEmail:
    """Tests for is_automated_email."""

    def test_noreply_address(self, analyzer):
        """Test detection of no-reply addresses."""
        test_cases = [
            'noreply@example.com',
            'no-reply@example.com',
            'no_reply@example.com',
            'donotreply@example.com',
            'do-not-reply@example.com',
        ]

        for from_addr in test_cases:
            message = create_message(from_addr)
            assert analyzer.is_automated_email(message) is True, f"Failed for {from_addr}"

    def test_automated_addresses(self, analyzer):
        """Test detection of automated sender addresses."""
        test_cases = [
            'automated@example.com',
            'notifications@example.com',
            'alerts@example.com',
            'bounce@example.com',
            'mailer-daemon@example.com',
            'newsletter@example.com',
            'updates@example.com',
        ]

        for from_addr in test_cases:
            message = create_message(from_addr)
            assert analyzer.is_automated_email(message) is True, f"Failed for {from_addr}"

    def test_regular_email_not_automated(self, analyzer):
        """Test that regular emails are not marked as automated."""
        test_cases = [
            'john@example.com',
            'support@company.com',
            'hello@startup.io',
            'team@organization.org',
        ]

        for from_addr in test_cases:
            message = create_message(from_addr)
            assert analyzer.is_automated_email(message) is False, f"Failed for {from_addr}"

    def test_auto_submitted_header(self, analyzer):
        """Test detection via Auto-Submitted header."""
        message = create_message(
            'user@example.com',
            headers={'Auto-Submitted': 'auto-generated'}
        )
        assert analyzer.is_automated_email(message) is True

    def test_auto_submitted_no(self, analyzer):
        """Test that Auto-Submitted: no is not treated as automated."""
        message = create_message(
            'user@example.com',
            headers={'Auto-Submitted': 'no'}
        )
        assert analyzer.is_automated_email(message) is False

    def test_precedence_bulk(self, analyzer):
        """Test detection via Precedence header."""
        for value in ['bulk', 'list', 'junk']:
            message = create_message(
                'user@example.com',
                headers={'Precedence': value}
            )
            assert analyzer.is_automated_email(message) is True, f"Failed for Precedence: {value}"

    def test_list_unsubscribe(self, analyzer):
        """Test detection via List-Unsubscribe header (newsletters)."""
        message = create_message(
            'newsletter@example.com',
            headers={'List-Unsubscribe': '<mailto:unsubscribe@example.com>'}
        )
        assert analyzer.is_automated_email(message) is True

    def test_x_auto_response_suppress(self, analyzer):
        """Test detection via X-Auto-Response-Suppress header."""
        message = create_message(
            'user@example.com',
            headers={'X-Auto-Response-Suppress': 'All'}
        )
        assert analyzer.is_automated_email(message) is True


class TestIsUnreplied:
    """Tests for is_unreplied."""

    def test_last_message_from_other_read(self, analyzer, user_email):
        """Test thread where last message is from someone else and read."""
        message = create_message('other@example.com', labels=['INBOX'])
        thread = create_thread([message])

        result = analyzer.is_unreplied(thread, user_email)
        assert result is True

    def test_last_message_from_self(self, analyzer, user_email):
        """Test thread where last message is from user (no reply needed)."""
        message = create_message(user_email, labels=['SENT'])
        thread = create_thread([message])

        result = analyzer.is_unreplied(thread, user_email)
        assert result is False

    def test_last_message_unread(self, analyzer, user_email):
        """Test thread where last message is unread (not yet processed)."""
        message = create_message('other@example.com', labels=['INBOX', 'UNREAD'])
        thread = create_thread([message])

        result = analyzer.is_unreplied(thread, user_email)
        assert result is False

    def test_last_message_automated(self, analyzer, user_email):
        """Test thread where last message is automated (no reply needed)."""
        message = create_message('noreply@example.com', labels=['INBOX'])
        thread = create_thread([message])

        result = analyzer.is_unreplied(thread, user_email)
        assert result is False

    def test_conversation_flow(self, analyzer, user_email):
        """Test realistic conversation flow."""
        # Message 1: Other person initiates
        msg1 = create_message('other@example.com', labels=['INBOX'])

        # Message 2: User replies
        msg2 = create_message(user_email, labels=['SENT'])

        # Message 3: Other person responds
        msg3 = create_message('other@example.com', labels=['INBOX'])

        thread = create_thread([msg1, msg2, msg3])

        result = analyzer.is_unreplied(thread, user_email)
        assert result is True

    def test_empty_thread(self, analyzer, user_email):
        """Test handling of empty thread."""
        thread = create_thread([])

        result = analyzer.is_unreplied(thread, user_email)
        assert result is False

    def test_email_normalization(self, analyzer):
        """Test that email addresses are compared case-insensitively."""
        user_email = "User@Example.COM"

        # Last message from user with different case
        message = create_message('user@example.com', labels=['SENT'])
        thread = create_thread([message])

        result = analyzer.is_unreplied(thread, user_email)
        assert result is False


class TestParseHeaders:
    """Tests for parse_headers."""

    def test_parse_headers(self, analyzer):
        """Test header parsing."""
        headers_list = [
            {'name': 'From', 'value': 'sender@example.com'},
            {'name': 'To', 'value': 'recipient@example.com'},
            {'name': 'Subject', 'value': 'Test Subject'},
        ]

        result = analyzer.parse_headers(headers_list)

        assert result == {
            'From': 'sender@example.com',
            'To': 'recipient@example.com',
            'Subject': 'Test Subject',
        }

    def test_empty_headers(self, analyzer):
        """Test parsing empty headers list."""
        result = analyzer.parse_headers([])
        assert result == {}


class TestExtractSenderInfo:
    """Tests for extract_sender_info."""

    def test_full_sender_info(self, analyzer):
        """Test extraction of full sender information."""
        message = create_message('"John Doe" <john@example.com>')

        result = analyzer.extract_sender_info(message)

        assert result is not None
        assert result.email == 'john@example.com'
        assert result.name == 'John Doe'
        assert result.domain == 'example.com'

    def test_sender_without_name(self, analyzer):
        """Test extraction when no name is provided."""
        message = create_message('john@example.com')

        result = analyzer.extract_sender_info(message)

        assert result is not None
        assert result.email == 'john@example.com'
        assert result.name is None
        assert result.domain == 'example.com'


class TestExtractSubject:
    """Tests for extract_subject."""

    def test_extract_subject(self, analyzer):
        """Test subject extraction."""
        message = create_message('sender@example.com')
        result = analyzer.extract_subject(message)
        assert result == 'Test Subject'

    def test_missing_subject(self, analyzer):
        """Test handling of missing subject."""
        message = {'payload': {'headers': []}}
        result = analyzer.extract_subject(message)
        assert result == '(No Subject)'


class TestFilterUnrepliedThreads:
    """Tests for filter_unreplied_threads."""

    def test_filter_unreplied_threads(self, analyzer, user_email):
        """Test filtering a list of threads."""
        # Thread 1: Needs reply
        thread1 = create_thread([
            create_message('other@example.com', labels=['INBOX'])
        ])

        # Thread 2: User replied last
        thread2 = create_thread([
            create_message(user_email, labels=['SENT'])
        ])

        # Thread 3: Needs reply
        thread3 = create_thread([
            create_message('another@example.com', labels=['INBOX'])
        ])

        threads = [thread1, thread2, thread3]

        result = analyzer.filter_unreplied_threads(threads, user_email)

        assert len(result) == 2
        assert result[0] == thread1
        assert result[1] == thread3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
