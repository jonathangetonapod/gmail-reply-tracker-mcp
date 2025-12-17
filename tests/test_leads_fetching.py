"""
Unit tests for leads fetching functionality.

Tests:
- Fetching Bison lead replies
- Fetching Instantly lead responses
- Date filtering
- Status filtering
- Error handling
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
from src.leads import bison_client, instantly_client


class TestBisonLeadReplies:
    """Tests for fetching Bison lead replies."""

    @patch('src.leads.bison_client.requests.get')
    def test_get_bison_replies_interested(self, mock_get):
        """Test fetching interested lead replies from Bison."""
        # Mock successful API response
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": 123,
                    "from_email_address": "lead@example.com",
                    "from_name": "John Doe",
                    "subject": "Re: Your offer",
                    "text_body": "I'm interested!",
                    "html_body": "<p>I'm interested!</p>",
                    "date_received": "2024-12-01T10:00:00Z",
                    "type": "reply",
                    "lead_id": 456,
                    "read": False
                },
                {
                    "id": 124,
                    "from_email_address": "another@example.com",
                    "from_name": "Jane Smith",
                    "subject": "Re: Meeting request",
                    "text_body": "Let's schedule a call",
                    "html_body": "<p>Let's schedule a call</p>",
                    "date_received": "2024-12-02T14:30:00Z",
                    "type": "reply",
                    "lead_id": 457,
                    "read": True
                }
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Call the function
        result = bison_client.get_bison_lead_replies(
            api_key="test_key",
            status="interested",
            folder="all"
        )

        # Verify the request
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "https://send.leadgenjay.com/api/replies" in call_args[0][0]
        assert call_args[1]["params"] == {"folder": "all", "status": "interested"}
        assert call_args[1]["headers"]["Authorization"] == "Bearer test_key"

        # Verify the response
        assert "data" in result
        assert len(result["data"]) == 2
        assert result["data"][0]["from_email_address"] == "lead@example.com"
        assert result["data"][1]["from_name"] == "Jane Smith"

    @patch('src.leads.bison_client.requests.get')
    def test_get_bison_replies_all_statuses(self, mock_get):
        """Test fetching all lead replies regardless of status."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = bison_client.get_bison_lead_replies(
            api_key="test_key",
            status=None,
            folder="inbox"
        )

        # Verify status is not included when None
        call_args = mock_get.call_args
        assert call_args[1]["params"] == {"folder": "inbox"}

    @patch('src.leads.bison_client.requests.get')
    def test_get_bison_replies_empty_results(self, mock_get):
        """Test handling empty results."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = bison_client.get_bison_lead_replies(
            api_key="test_key",
            status="interested"
        )

        assert "data" in result
        assert len(result["data"]) == 0

    @patch('src.leads.bison_client.requests.get')
    def test_get_bison_replies_api_error(self, mock_get):
        """Test handling API errors."""
        mock_get.side_effect = Exception("API Error")

        with pytest.raises(Exception) as exc_info:
            bison_client.get_bison_lead_replies(
                api_key="invalid_key",
                status="interested"
            )

        assert "API Error" in str(exc_info.value)


class TestInstantlyLeadResponses:
    """Tests for fetching Instantly lead responses."""

    @patch('src.leads.instantly_client.fetch_interested_leads')
    def test_get_instantly_responses_with_dates(self, mock_fetch):
        """Test fetching Instantly lead responses with date filtering."""
        # Mock successful API response
        mock_fetch.return_value = {
            "total_count": 2,
            "leads": [
                {
                    "email": "lead1@example.com",
                    "reply_body": "I'm very interested in your product",
                    "reply_summary": "Positive interest",
                    "subject": "Re: Product demo",
                    "timestamp": "2024-12-01T10:00:00Z"
                },
                {
                    "email": "lead2@example.com",
                    "reply_body": "Can we schedule a call?",
                    "reply_summary": "Request for meeting",
                    "subject": "Re: Your solution",
                    "timestamp": "2024-12-02T14:00:00Z"
                }
            ]
        }

        # Call the function
        result = instantly_client.get_instantly_lead_responses(
            api_key="test_key",
            start_date="2024-12-01T00:00:00Z",
            end_date="2024-12-10T23:59:59Z"
        )

        # Verify the call
        mock_fetch.assert_called_once_with(
            api_key="test_key",
            start_date="2024-12-01T00:00:00Z",
            end_date="2024-12-10T23:59:59Z"
        )

        # Verify the response
        assert result["total_count"] == 2
        assert len(result["leads"]) == 2
        assert result["leads"][0]["email"] == "lead1@example.com"
        assert "interested" in result["leads"][0]["reply_body"].lower()

    @patch('src.leads.instantly_client.fetch_interested_leads')
    def test_get_instantly_responses_empty(self, mock_fetch):
        """Test handling empty results from Instantly."""
        mock_fetch.return_value = {
            "total_count": 0,
            "leads": []
        }

        result = instantly_client.get_instantly_lead_responses(
            api_key="test_key",
            start_date="2024-12-01T00:00:00Z",
            end_date="2024-12-10T23:59:59Z"
        )

        assert result["total_count"] == 0
        assert len(result["leads"]) == 0

    @patch('src.leads.instantly_client.fetch_interested_leads')
    def test_get_instantly_responses_api_error(self, mock_fetch):
        """Test handling API errors from Instantly."""
        mock_fetch.side_effect = Exception("Instantly API Error")

        with pytest.raises(Exception) as exc_info:
            instantly_client.get_instantly_lead_responses(
                api_key="invalid_key",
                start_date="2024-12-01T00:00:00Z",
                end_date="2024-12-10T23:59:59Z"
            )

        assert "Instantly API Error" in str(exc_info.value)


class TestBisonConversationThread:
    """Tests for fetching Bison conversation threads."""

    @patch('src.leads.bison_client.requests.get')
    def test_get_conversation_thread(self, mock_get):
        """Test fetching a conversation thread."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "current_reply": {
                    "id": 123,
                    "text_body": "Current message"
                },
                "older_messages": [
                    {"id": 120, "text_body": "Older message 1"},
                    {"id": 121, "text_body": "Older message 2"}
                ],
                "newer_messages": []
            }
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = bison_client.get_bison_conversation_thread(
            api_key="test_key",
            reply_id=123
        )

        # Verify the request
        mock_get.assert_called_once()
        assert "replies/123/conversation-thread" in mock_get.call_args[0][0]

        # Verify the response
        assert "data" in result
        assert "current_reply" in result["data"]
        assert len(result["data"]["older_messages"]) == 2

    @patch('src.leads.bison_client.requests.get')
    def test_get_conversation_thread_not_found(self, mock_get):
        """Test handling non-existent conversation thread."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")
        mock_get.return_value = mock_response

        with pytest.raises(Exception) as exc_info:
            bison_client.get_bison_conversation_thread(
                api_key="test_key",
                reply_id=99999
            )

        assert "404" in str(exc_info.value)


class TestCampaignStats:
    """Tests for fetching campaign statistics."""

    @patch('src.leads.bison_client.requests.get')
    def test_get_bison_campaign_stats(self, mock_get):
        """Test fetching Bison campaign statistics."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "emails_sent": 1000,
                "total_leads_contacted": 500,
                "opened": 300,
                "opened_percentage": 60.0,
                "unique_replies_per_contact": 50,
                "unique_replies_per_contact_percentage": 10.0,
                "bounced": 20,
                "bounced_percentage": 2.0,
                "unsubscribed": 10,
                "unsubscribed_percentage": 1.0,
                "interested": 15,
                "interested_percentage": 3.0
            }
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = bison_client.get_bison_campaign_stats_api(
            api_key="test_key",
            start_date="2024-12-01",
            end_date="2024-12-10"
        )

        # Verify the request
        call_args = mock_get.call_args
        assert call_args[1]["params"]["start_date"] == "2024-12-01"
        assert call_args[1]["params"]["end_date"] == "2024-12-10"

        # Verify the response
        assert result["data"]["emails_sent"] == 1000
        assert result["data"]["interested"] == 15
        assert result["data"]["interested_percentage"] == 3.0

    @patch('src.leads.instantly_client.requests.get')
    def test_get_instantly_campaign_stats(self, mock_get):
        """Test fetching Instantly campaign statistics."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "emails_sent_count": 2000,
            "reply_count_unique": 100,
            "total_opportunities": 25,
            "reply_rate": 5.0
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = instantly_client.get_instantly_campaign_stats(
            api_key="test_key",
            start_date="2024-12-01",
            end_date="2024-12-10"
        )

        # Verify the response
        assert result["emails_sent_count"] == 2000
        assert result["reply_count_unique"] == 100
        assert result["reply_rate"] == 5.0


class TestDateFiltering:
    """Tests for date filtering in lead fetching."""

    def test_date_range_validation(self):
        """Test that date ranges are properly formatted."""
        # ISO format dates
        start = "2024-12-01T00:00:00Z"
        end = "2024-12-10T23:59:59Z"

        assert "T" in start
        assert "Z" in end
        assert start < end

    def test_date_range_last_7_days(self):
        """Test generating date range for last 7 days."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)

        start_iso = start_date.strftime("%Y-%m-%dT00:00:00Z")
        end_iso = end_date.strftime("%Y-%m-%dT23:59:59Z")

        assert start_iso < end_iso

    def test_date_range_last_30_days(self):
        """Test generating date range for last 30 days."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)

        start_iso = start_date.strftime("%Y-%m-%dT00:00:00Z")
        end_iso = end_date.strftime("%Y-%m-%dT23:59:59Z")

        assert start_iso < end_iso


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
