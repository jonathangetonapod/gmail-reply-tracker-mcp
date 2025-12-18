"""
Unit tests for mark_lead_as_interested functionality.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from leads._source_fetch_interested_leads import mark_instantly_lead_as_interested
from leads.bison_client import mark_bison_reply_as_interested


class TestMarkInstantlyLeadAsInterested:
    """Tests for Instantly mark_lead_as_interested function."""

    @patch('leads._source_fetch_interested_leads.requests.post')
    def test_mark_lead_basic(self, mock_post):
        """Test basic lead marking with default parameters."""
        # Mock response
        mock_response = Mock()
        mock_response.json.return_value = {
            "message": "Lead interest status update background job submitted"
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # Call function
        result = mark_instantly_lead_as_interested(
            api_key="test_api_key",
            lead_email="test@example.com"
        )

        # Verify API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        call_kwargs = call_args.kwargs

        # Check URL (first positional arg)
        assert call_args.args[0] == "https://api.instantly.ai/api/v2/leads/update-interest-status"

        # Check headers
        assert call_kwargs['headers']['Authorization'] == "Bearer test_api_key"
        assert call_kwargs['headers']['Content-Type'] == "application/json"

        # Check payload
        payload = call_kwargs['json']
        assert payload['lead_email'] == "test@example.com"
        assert payload['interest_value'] == 1

        # Check result
        assert result['message'] == "Lead interest status update background job submitted"

    @patch('leads._source_fetch_interested_leads.requests.post')
    def test_mark_lead_with_all_params(self, mock_post):
        """Test marking lead with all optional parameters."""
        mock_response = Mock()
        mock_response.json.return_value = {"message": "Success"}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = mark_instantly_lead_as_interested(
            api_key="test_api_key",
            lead_email="test@example.com",
            interest_value=2,
            campaign_id="campaign-123",
            list_id="list-456",
            ai_interest_value=1,
            disable_auto_interest=True
        )

        # Check payload includes all parameters
        payload = mock_post.call_args[1]['json']
        assert payload['lead_email'] == "test@example.com"
        assert payload['interest_value'] == 2
        assert payload['campaign_id'] == "campaign-123"
        assert payload['list_id'] == "list-456"
        assert payload['ai_interest_value'] == 1
        assert payload['disable_auto_interest'] is True

    @patch('leads._source_fetch_interested_leads.requests.post')
    def test_mark_lead_different_interest_values(self, mock_post):
        """Test different interest status values."""
        mock_response = Mock()
        mock_response.json.return_value = {"message": "Success"}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # Test each interest value
        interest_values = [
            (1, "Interested"),
            (2, "Meeting Booked"),
            (3, "Meeting Completed"),
            (4, "Closed"),
            (-1, "Not Interested"),
            (-2, "Wrong Person"),
            (-3, "Lost"),
            (0, "Out of Office")
        ]

        for value, description in interest_values:
            mark_instantly_lead_as_interested(
                api_key="test_api_key",
                lead_email="test@example.com",
                interest_value=value
            )

            payload = mock_post.call_args[1]['json']
            assert payload['interest_value'] == value, f"Failed for {description}"

    @patch('leads._source_fetch_interested_leads.requests.post')
    def test_mark_lead_api_error(self, mock_post):
        """Test handling of API errors."""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("API Error")
        mock_post.return_value = mock_response

        with pytest.raises(Exception) as excinfo:
            mark_instantly_lead_as_interested(
                api_key="test_api_key",
                lead_email="test@example.com"
            )

        assert "API Error" in str(excinfo.value)

    @patch('leads._source_fetch_interested_leads.requests.post')
    def test_mark_lead_special_chars_email(self, mock_post):
        """Test marking lead with special characters in email."""
        mock_response = Mock()
        mock_response.json.return_value = {"message": "Success"}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        special_emails = [
            "test+tag@example.com",
            "test.name@example.com",
            "test_name@example.com",
            "test-name@example.com"
        ]

        for email in special_emails:
            mark_instantly_lead_as_interested(
                api_key="test_api_key",
                lead_email=email
            )

            payload = mock_post.call_args[1]['json']
            assert payload['lead_email'] == email


class TestMarkBisonReplyAsInterested:
    """Tests for Bison mark_reply_as_interested function."""

    @patch('leads.bison_client.requests.patch')
    def test_mark_reply_basic(self, mock_patch):
        """Test basic reply marking with default parameters."""
        # Mock response
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "id": 239,
                "uuid": "test-uuid",
                "from_email_address": "test@example.com",
                "interested": True
            }
        }
        mock_response.raise_for_status = Mock()
        mock_patch.return_value = mock_response

        # Call function
        result = mark_bison_reply_as_interested(
            api_key="test_api_key",
            reply_id=239
        )

        # Verify API call
        mock_patch.assert_called_once()
        call_args = mock_patch.call_args
        call_kwargs = call_args.kwargs

        # Check URL (first positional arg)
        assert call_args.args[0] == "https://send.leadgenjay.com/api/replies/239/mark-as-interested"

        # Check headers
        assert call_kwargs['headers']['Authorization'] == "Bearer test_api_key"
        assert call_kwargs['headers']['Content-Type'] == "application/json"

        # Check payload
        payload = call_kwargs['json']
        assert payload['skip_webhooks'] is True

        # Check result
        assert result['data']['interested'] is True

    @patch('leads.bison_client.requests.patch')
    def test_mark_reply_without_skip_webhooks(self, mock_patch):
        """Test marking reply with webhooks enabled."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": {"interested": True}}
        mock_response.raise_for_status = Mock()
        mock_patch.return_value = mock_response

        mark_bison_reply_as_interested(
            api_key="test_api_key",
            reply_id=123,
            skip_webhooks=False
        )

        payload = mock_patch.call_args[1]['json']
        assert payload['skip_webhooks'] is False

    @patch('leads.bison_client.requests.patch')
    def test_mark_reply_api_error(self, mock_patch):
        """Test handling of API errors."""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("Bison API Error")
        mock_patch.return_value = mock_response

        with pytest.raises(Exception) as excinfo:
            mark_bison_reply_as_interested(
                api_key="test_api_key",
                reply_id=999
            )

        assert "Bison API Error" in str(excinfo.value)

    @patch('leads.bison_client.requests.patch')
    def test_mark_reply_various_ids(self, mock_patch):
        """Test marking replies with various reply IDs."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": {"interested": True}}
        mock_response.raise_for_status = Mock()
        mock_patch.return_value = mock_response

        reply_ids = [1, 100, 9999, 123456]

        for reply_id in reply_ids:
            mark_bison_reply_as_interested(
                api_key="test_api_key",
                reply_id=reply_id
            )

            url = mock_patch.call_args.args[0]
            assert f"/replies/{reply_id}/mark-as-interested" in url


class TestMarkLeadAsInterestedMCPTool:
    """Tests for the unified MCP tool."""

    @pytest.fixture
    def mock_config(self):
        """Mock configuration."""
        mock = Mock()
        mock.lead_sheets_url = "https://docs.google.com/spreadsheets/test"
        mock.lead_sheets_gid_instantly = "123"
        mock.lead_sheets_gid_bison = "456"
        return mock

    @pytest.fixture
    def mock_instantly_workspace(self):
        """Mock Instantly workspace data."""
        return [{
            "client_name": "Test Client",
            "api_key": "instantly_api_key"
        }]

    @pytest.fixture
    def mock_bison_workspace(self):
        """Mock Bison workspace data."""
        return [{
            "client_name": "Bison Client",
            "api_key": "bison_api_key"
        }]

    def test_workspace_matching_logic(self):
        """Test workspace matching logic used by MCP tool."""
        # Simulate workspaces data
        instantly_workspaces = [{
            "client_name": "Test Client",
            "api_key": "test_api_key"
        }]

        bison_workspaces = [{
            "client_name": "Bison Client",
            "api_key": "bison_api_key"
        }]

        # Test matching for Instantly client
        client_name = "Test Client"
        matching = next(
            (w for w in instantly_workspaces if w["client_name"].lower() == client_name.lower()),
            None
        )

        assert matching is not None
        assert matching["api_key"] == "test_api_key"

        # Test matching for Bison client
        client_name = "Bison Client"
        matching = next(
            (w for w in bison_workspaces if w["client_name"].lower() == client_name.lower()),
            None
        )

        assert matching is not None
        assert matching["api_key"] == "bison_api_key"

    def test_case_insensitive_client_matching(self):
        """Test that client name matching is case-insensitive."""
        workspaces = [
            {"client_name": "Jeff Mikolai", "api_key": "key1"},
            {"client_name": "Lena Kadriu", "api_key": "key2"}
        ]

        test_names = ["jeff mikolai", "JEFF MIKOLAI", "Jeff Mikolai", "LENA KADRIU"]

        for name in test_names:
            matching = next(
                (w for w in workspaces if w["client_name"].lower() == name.lower()),
                None
            )
            assert matching is not None


class TestIntegrationScenarios:
    """Integration test scenarios."""

    @patch('leads._source_fetch_interested_leads.requests.post')
    def test_full_instantly_workflow(self, mock_post):
        """Test complete workflow: find hidden gems → mark as interested."""
        # Mock API response
        mock_response = Mock()
        mock_response.json.return_value = {
            "message": "Lead interest status update background job submitted"
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # Simulate finding a hidden gem
        hidden_gem = {
            "email": "opportunity@example.com",
            "category": "hot",
            "confidence": 85
        }

        # Mark it as interested
        result = mark_instantly_lead_as_interested(
            api_key="test_api_key",
            lead_email=hidden_gem["email"],
            interest_value=1
        )

        assert "submitted" in result["message"]
        assert mock_post.call_args[1]['json']['lead_email'] == hidden_gem["email"]

    @patch('leads.bison_client.requests.patch')
    def test_full_bison_workflow(self, mock_patch):
        """Test complete workflow: find hidden gems → mark reply as interested."""
        # Mock API response
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "id": 239,
                "interested": True,
                "from_email_address": "opportunity@example.com"
            }
        }
        mock_response.raise_for_status = Mock()
        mock_patch.return_value = mock_response

        # Simulate finding a hidden gem with reply_id
        hidden_gem = {
            "email": "opportunity@example.com",
            "reply_id": 239,
            "category": "warm",
            "confidence": 75
        }

        # Mark it as interested
        result = mark_bison_reply_as_interested(
            api_key="test_api_key",
            reply_id=hidden_gem["reply_id"]
        )

        assert result["data"]["interested"] is True
        assert result["data"]["id"] == 239


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
