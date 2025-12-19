"""Unit tests for DocsClient."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
import time
from unittest.mock import Mock, MagicMock, patch
from googleapiclient.errors import HttpError

from docs_client import DocsClient, RateLimiter


@pytest.fixture
def mock_credentials():
    """Create mock credentials."""
    creds = Mock()
    creds.valid = True
    return creds


@pytest.fixture
def docs_client(mock_credentials):
    """Create a DocsClient instance with mocked service."""
    with patch('docs_client.build') as mock_build:
        mock_service = Mock()
        mock_build.return_value = mock_service

        client = DocsClient(mock_credentials, max_requests_per_minute=60)
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

        # Should complete almost instantly (within 0.5 seconds)
        assert elapsed < 0.5


class TestDocsClient:
    """Tests for DocsClient."""

    def test_create_document_success(self, docs_client):
        """Test creating a new document."""
        # Mock response
        mock_doc = {
            'documentId': '1abc123',
            'title': 'Test Document'
        }

        mock_request = Mock()
        mock_request.execute.return_value = mock_doc
        docs_client.service.documents().create.return_value = mock_request

        # Create document
        result = docs_client.create_document('Test Document')

        # Verify
        assert result['documentId'] == '1abc123'
        assert result['title'] == 'Test Document'
        docs_client.service.documents().create.assert_called_once_with(
            body={'title': 'Test Document'}
        )

    def test_get_document_success(self, docs_client):
        """Test getting a document."""
        # Mock response
        mock_doc = {
            'documentId': '1abc123',
            'title': 'Test Document',
            'body': {
                'content': [
                    {
                        'paragraph': {
                            'elements': [
                                {
                                    'textRun': {
                                        'content': 'Hello World\n'
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        }

        mock_request = Mock()
        mock_request.execute.return_value = mock_doc
        docs_client.service.documents().get.return_value = mock_request

        # Get document
        result = docs_client.get_document('1abc123')

        # Verify
        assert result['documentId'] == '1abc123'
        assert result['title'] == 'Test Document'
        docs_client.service.documents().get.assert_called_once_with(
            documentId='1abc123'
        )

    def test_insert_text_success(self, docs_client):
        """Test inserting text."""
        mock_result = {'replies': [{}]}

        mock_request = Mock()
        mock_request.execute.return_value = mock_result
        docs_client.service.documents().batchUpdate.return_value = mock_request

        # Insert text
        result = docs_client.insert_text('1abc123', 'Hello World', index=1)

        # Verify
        assert result == mock_result
        call_args = docs_client.service.documents().batchUpdate.call_args
        assert call_args[1]['documentId'] == '1abc123'
        assert call_args[1]['body']['requests'][0]['insertText']['text'] == 'Hello World'
        assert call_args[1]['body']['requests'][0]['insertText']['location']['index'] == 1

    def test_append_text_success(self, docs_client):
        """Test appending text to document."""
        # Mock get_document response
        mock_doc = {
            'documentId': '1abc123',
            'body': {
                'content': [
                    {'endIndex': 1},
                    {'endIndex': 100}
                ]
            }
        }

        mock_get_request = Mock()
        mock_get_request.execute.return_value = mock_doc
        docs_client.service.documents().get.return_value = mock_get_request

        # Mock batchUpdate response
        mock_result = {'replies': [{}]}
        mock_update_request = Mock()
        mock_update_request.execute.return_value = mock_result
        docs_client.service.documents().batchUpdate.return_value = mock_update_request

        # Append text
        result = docs_client.append_text('1abc123', '\n\nNew paragraph')

        # Verify
        assert result == mock_result
        call_args = docs_client.service.documents().batchUpdate.call_args
        # Should insert at end_index - 1 (100 - 1 = 99)
        assert call_args[1]['body']['requests'][0]['insertText']['location']['index'] == 99

    def test_replace_all_text_success(self, docs_client):
        """Test replacing text."""
        mock_result = {'replies': [{'replaceAllText': {'occurrencesChanged': 3}}]}

        mock_request = Mock()
        mock_request.execute.return_value = mock_result
        docs_client.service.documents().batchUpdate.return_value = mock_request

        # Replace text
        result = docs_client.replace_all_text('1abc123', '{{name}}', 'John')

        # Verify
        assert result == mock_result
        call_args = docs_client.service.documents().batchUpdate.call_args
        assert call_args[1]['body']['requests'][0]['replaceAllText']['containsText']['text'] == '{{name}}'
        assert call_args[1]['body']['requests'][0]['replaceAllText']['replaceText'] == 'John'

    def test_format_text_success(self, docs_client):
        """Test formatting text."""
        mock_result = {'replies': [{}]}

        mock_request = Mock()
        mock_request.execute.return_value = mock_result
        docs_client.service.documents().batchUpdate.return_value = mock_request

        # Format text
        result = docs_client.format_text(
            '1abc123',
            start_index=1,
            end_index=10,
            bold=True,
            font_size=14
        )

        # Verify
        assert result == mock_result
        call_args = docs_client.service.documents().batchUpdate.call_args
        text_style = call_args[1]['body']['requests'][0]['updateTextStyle']
        assert text_style['range']['startIndex'] == 1
        assert text_style['range']['endIndex'] == 10
        assert text_style['textStyle']['bold'] is True
        assert text_style['textStyle']['fontSize']['magnitude'] == 14

    def test_insert_paragraph_success(self, docs_client):
        """Test inserting a paragraph."""
        mock_result = {'replies': [{}]}

        mock_request = Mock()
        mock_request.execute.return_value = mock_result
        docs_client.service.documents().batchUpdate.return_value = mock_request

        # Insert paragraph
        result = docs_client.insert_paragraph(
            '1abc123',
            'Introduction',
            index=1,
            heading='HEADING_1'
        )

        # Verify
        assert result == mock_result
        call_args = docs_client.service.documents().batchUpdate.call_args
        requests = call_args[1]['body']['requests']
        # Should have 2 requests: insert text + update paragraph style
        assert len(requests) == 2
        assert requests[0]['insertText']['text'] == 'Introduction\n'
        assert requests[1]['updateParagraphStyle']['paragraphStyle']['namedStyleType'] == 'HEADING_1'

    def test_extract_text_success(self, docs_client):
        """Test extracting text from document."""
        # Mock document with multiple paragraphs
        mock_doc = {
            'documentId': '1abc123',
            'body': {
                'content': [
                    {
                        'paragraph': {
                            'elements': [
                                {'textRun': {'content': 'First paragraph\n'}},
                                {'textRun': {'content': 'with multiple runs\n'}}
                            ]
                        }
                    },
                    {
                        'paragraph': {
                            'elements': [
                                {'textRun': {'content': 'Second paragraph\n'}}
                            ]
                        }
                    }
                ]
            }
        }

        mock_request = Mock()
        mock_request.execute.return_value = mock_doc
        docs_client.service.documents().get.return_value = mock_request

        # Extract text
        result = docs_client.extract_text('1abc123')

        # Verify
        assert result == 'First paragraph\nwith multiple runs\nSecond paragraph\n'

    def test_get_document_url(self, docs_client):
        """Test getting document URL."""
        url = docs_client.get_document_url('1abc123')
        assert url == 'https://docs.google.com/document/d/1abc123/edit'

    def test_execute_with_retry_403_error(self, docs_client):
        """Test retry on 403 error."""
        mock_request = Mock()

        # First call raises 403, second succeeds
        mock_response = Mock()
        mock_response.status = 403
        error = HttpError(resp=mock_response, content=b'Rate limit exceeded')

        mock_request.execute.side_effect = [error, {'documentId': '1abc123'}]

        # Should retry and succeed
        result = docs_client._execute_with_retry(mock_request, max_retries=2)

        assert result['documentId'] == '1abc123'
        assert mock_request.execute.call_count == 2

    def test_execute_with_retry_exhausted(self, docs_client):
        """Test retry exhaustion."""
        mock_request = Mock()

        # Always fails with 500
        mock_response = Mock()
        mock_response.status = 500
        error = HttpError(resp=mock_response, content=b'Internal server error')

        mock_request.execute.side_effect = error

        # Should raise after max retries
        with pytest.raises(HttpError):
            docs_client._execute_with_retry(mock_request, max_retries=3)

        # Should have tried 3 times
        assert mock_request.execute.call_count == 3

    def test_execute_with_retry_non_retryable_error(self, docs_client):
        """Test non-retryable error."""
        mock_request = Mock()

        # 400 error should not retry
        mock_response = Mock()
        mock_response.status = 400
        error = HttpError(resp=mock_response, content=b'Bad request')

        mock_request.execute.side_effect = error

        # Should raise immediately without retry
        with pytest.raises(HttpError):
            docs_client._execute_with_retry(mock_request, max_retries=3)

        # Should only try once
        assert mock_request.execute.call_count == 1

    def test_format_text_with_color(self, docs_client):
        """Test formatting text with color."""
        mock_result = {'replies': [{}]}

        mock_request = Mock()
        mock_request.execute.return_value = mock_result
        docs_client.service.documents().batchUpdate.return_value = mock_request

        # Format with color
        result = docs_client.format_text(
            '1abc123',
            start_index=1,
            end_index=10,
            foreground_color={'red': 1.0, 'green': 0.0, 'blue': 0.0}
        )

        # Verify
        call_args = docs_client.service.documents().batchUpdate.call_args
        text_style = call_args[1]['body']['requests'][0]['updateTextStyle']
        color = text_style['textStyle']['foregroundColor']['color']['rgbColor']
        assert color['red'] == 1.0
        assert color['green'] == 0.0
        assert color['blue'] == 0.0

    def test_insert_paragraph_without_heading(self, docs_client):
        """Test inserting paragraph without heading style."""
        mock_result = {'replies': [{}]}

        mock_request = Mock()
        mock_request.execute.return_value = mock_result
        docs_client.service.documents().batchUpdate.return_value = mock_request

        # Insert paragraph without heading
        result = docs_client.insert_paragraph(
            '1abc123',
            'Normal paragraph',
            index=1,
            heading=None
        )

        # Verify
        call_args = docs_client.service.documents().batchUpdate.call_args
        requests = call_args[1]['body']['requests']
        # Should only have 1 request (insert text, no styling)
        assert len(requests) == 1
        assert requests[0]['insertText']['text'] == 'Normal paragraph\n'

    def test_extract_text_empty_document(self, docs_client):
        """Test extracting text from empty document."""
        # Mock empty document
        mock_doc = {
            'documentId': '1abc123',
            'body': {
                'content': []
            }
        }

        mock_request = Mock()
        mock_request.execute.return_value = mock_doc
        docs_client.service.documents().get.return_value = mock_request

        # Extract text
        result = docs_client.extract_text('1abc123')

        # Should return empty string
        assert result == ''


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
