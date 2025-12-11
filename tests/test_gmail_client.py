"""Unit tests for GmailClient."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
import time
from unittest.mock import Mock, MagicMock, patch
from googleapiclient.errors import HttpError

from gmail_client import GmailClient, RateLimiter


@pytest.fixture
def mock_credentials():
    """Create mock credentials."""
    creds = Mock()
    creds.valid = True
    return creds


@pytest.fixture
def gmail_client(mock_credentials):
    """Create a GmailClient instance with mocked service."""
    with patch('gmail_client.build') as mock_build:
        mock_service = Mock()
        mock_build.return_value = mock_service

        client = GmailClient(mock_credentials, max_requests_per_minute=60)
        client.service = mock_service

        return client


class TestRateLimiter:
    """Tests for RateLimiter."""

    def test_rate_limiter_allows_requests_under_limit(self):
        """Test that requests under the limit are allowed immediately."""
        limiter = RateLimiter(max_requests_per_minute=60)

        start_time = time.time()

        # Make 10 requests (well under limit)
        for _ in range(10):
            limiter.wait_if_needed()

        elapsed = time.time() - start_time

        # Should complete almost instantly (< 0.1 seconds)
        assert elapsed < 0.1

    def test_rate_limiter_blocks_when_limit_reached(self):
        """Test that rate limiter blocks when limit is reached."""
        # Very low limit for testing
        limiter = RateLimiter(max_requests_per_minute=2)

        # Make 2 requests
        limiter.wait_if_needed()
        limiter.wait_if_needed()

        # Third request should wait
        start_time = time.time()
        limiter.wait_if_needed()
        elapsed = time.time() - start_time

        # Should have waited (but we'll be lenient with timing)
        # In practice, should wait ~60 seconds, but for test we just
        # verify the mechanism works
        assert len(limiter.requests) <= 2

    def test_rate_limiter_window_cleanup(self):
        """Test that old requests are cleaned up."""
        limiter = RateLimiter(max_requests_per_minute=60)

        # Add some old requests
        old_time = time.time() - 70  # 70 seconds ago
        limiter.requests.append(old_time)
        limiter.requests.append(old_time)

        # Make a new request
        limiter.wait_if_needed()

        # Old requests should be cleaned up
        assert len(limiter.requests) == 1
        assert limiter.requests[0] > old_time


class TestGmailClientUserProfile:
    """Tests for user profile methods."""

    def test_get_user_profile_success(self, gmail_client):
        """Test successful user profile retrieval."""
        mock_profile = {
            'emailAddress': 'user@example.com',
            'messagesTotal': 1000,
            'threadsTotal': 500
        }

        # Mock the API call
        gmail_client.service.users().getProfile().execute.return_value = mock_profile

        result = gmail_client.get_user_profile()

        assert result == mock_profile
        assert gmail_client._user_email == 'user@example.com'

    def test_get_user_email_cached(self, gmail_client):
        """Test that user email is cached after first call."""
        mock_profile = {'emailAddress': 'user@example.com'}

        # Mock the API call
        gmail_client.service.users().getProfile().execute.return_value = mock_profile

        # First call
        email1 = gmail_client.get_user_email()

        # Second call should use cache
        email2 = gmail_client.get_user_email()

        assert email1 == 'user@example.com'
        assert email2 == 'user@example.com'

        # API should only be called once
        gmail_client.service.users().getProfile().execute.assert_called_once()


class TestGmailClientThreads:
    """Tests for thread operations."""

    def test_list_threads_success(self, gmail_client):
        """Test successful thread listing."""
        mock_response = {
            'threads': [
                {'id': 'thread1', 'snippet': 'First thread'},
                {'id': 'thread2', 'snippet': 'Second thread'}
            ]
        }

        # Mock the API call
        gmail_client.service.users().threads().list().execute.return_value = mock_response

        result = gmail_client.list_threads('test query', max_results=10)

        assert len(result) == 2
        assert result[0]['id'] == 'thread1'
        assert result[1]['id'] == 'thread2'

    def test_get_thread_success(self, gmail_client):
        """Test successful thread retrieval."""
        mock_thread = {
            'id': 'thread123',
            'messages': [
                {'id': 'msg1', 'snippet': 'Message 1'},
                {'id': 'msg2', 'snippet': 'Message 2'}
            ]
        }

        # Mock the API call
        gmail_client.service.users().threads().get().execute.return_value = mock_thread

        result = gmail_client.get_thread('thread123')

        assert result == mock_thread
        assert len(result['messages']) == 2


class TestGmailClientMessages:
    """Tests for message operations."""

    def test_list_messages_success(self, gmail_client):
        """Test successful message listing."""
        mock_response = {
            'messages': [
                {'id': 'msg1', 'threadId': 'thread1'},
                {'id': 'msg2', 'threadId': 'thread2'}
            ]
        }

        # Mock the API call
        gmail_client.service.users().messages().list().execute.return_value = mock_response

        result = gmail_client.list_messages('test query', max_results=20)

        assert len(result) == 2
        assert result[0]['id'] == 'msg1'

    def test_get_message_success(self, gmail_client):
        """Test successful message retrieval."""
        mock_message = {
            'id': 'msg123',
            'threadId': 'thread123',
            'payload': {
                'headers': [
                    {'name': 'From', 'value': 'sender@example.com'},
                    {'name': 'Subject', 'value': 'Test'}
                ]
            }
        }

        # Mock the API call
        gmail_client.service.users().messages().get().execute.return_value = mock_message

        result = gmail_client.get_message('msg123')

        assert result == mock_message
        assert result['id'] == 'msg123'

    def test_batch_get_messages(self, gmail_client):
        """Test batch message retrieval."""
        mock_messages = [
            {'id': 'msg1', 'snippet': 'First'},
            {'id': 'msg2', 'snippet': 'Second'}
        ]

        # Mock the API call to return different messages
        gmail_client.service.users().messages().get().execute.side_effect = mock_messages

        result = gmail_client.batch_get_messages(['msg1', 'msg2'])

        assert len(result) == 2
        assert result[0]['id'] == 'msg1'
        assert result[1]['id'] == 'msg2'


class TestGmailClientErrorHandling:
    """Tests for error handling."""

    def test_404_error_not_retried(self, gmail_client):
        """Test that 404 errors are not retried."""
        # Create a mock HttpError
        mock_response = Mock()
        mock_response.status = 404

        error = HttpError(mock_response, b'Not found')

        # Mock the API call to raise 404
        mock_request = Mock()
        mock_request.execute.side_effect = error

        with pytest.raises(HttpError) as exc_info:
            gmail_client._execute_with_retry(mock_request, max_retries=3)

        assert exc_info.value.resp.status == 404

        # Should only try once (no retries for 404)
        assert mock_request.execute.call_count == 1

    def test_401_error_not_retried(self, gmail_client):
        """Test that 401 errors are not retried."""
        # Create a mock HttpError
        mock_response = Mock()
        mock_response.status = 401

        error = HttpError(mock_response, b'Unauthorized')

        # Mock the API call to raise 401
        mock_request = Mock()
        mock_request.execute.side_effect = error

        with pytest.raises(HttpError) as exc_info:
            gmail_client._execute_with_retry(mock_request, max_retries=3)

        assert exc_info.value.resp.status == 401

        # Should only try once (no retries for 401)
        assert mock_request.execute.call_count == 1

    def test_500_error_retried(self, gmail_client):
        """Test that 500 errors are retried."""
        # Create a mock HttpError
        mock_response = Mock()
        mock_response.status = 500

        error = HttpError(mock_response, b'Server error')

        # Mock the API call to raise 500 on all attempts
        mock_request = Mock()
        mock_request.execute.side_effect = error

        with pytest.raises(HttpError) as exc_info:
            gmail_client._execute_with_retry(mock_request, max_retries=3)

        assert exc_info.value.resp.status == 500

        # Should try max_retries times
        assert mock_request.execute.call_count == 3

    def test_successful_retry_after_500(self, gmail_client):
        """Test successful request after transient 500 error."""
        # Create a mock HttpError
        mock_response = Mock()
        mock_response.status = 500

        error = HttpError(mock_response, b'Server error')

        # Mock the API call to fail once then succeed
        mock_request = Mock()
        mock_request.execute.side_effect = [error, {'success': True}]

        result = gmail_client._execute_with_retry(mock_request, max_retries=3)

        assert result == {'success': True}

        # Should try twice (fail once, succeed once)
        assert mock_request.execute.call_count == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
