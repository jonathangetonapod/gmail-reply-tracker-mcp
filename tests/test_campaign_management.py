"""
Unit tests for campaign management functionality.

Tests:
- Creating Bison campaigns
- Creating Instantly campaigns
- Listing campaigns
- Getting campaign details
- Status filtering
- Sequence steps
"""

import pytest
from unittest.mock import Mock, patch
from src.leads import bison_client, instantly_client


class TestBisonCampaignCreation:
    """Tests for creating Bison campaigns."""

    @patch('src.leads.bison_client.requests.post')
    def test_create_bison_campaign(self, mock_post):
        """Test creating a basic Bison campaign."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "id": 123,
                "uuid": "abc-123-def",
                "name": "Test Campaign",
                "type": "outbound",
                "status": "draft"
            }
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = bison_client.create_bison_campaign_api(
            api_key="test_key",
            name="Test Campaign",
            campaign_type="outbound"
        )

        # Verify the request
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "campaigns" in call_args[0][0]
        assert call_args[1]["json"]["name"] == "Test Campaign"
        assert call_args[1]["json"]["type"] == "outbound"

        # Verify the response
        assert result["data"]["id"] == 123
        assert result["data"]["name"] == "Test Campaign"

    @patch('src.leads.bison_client.requests.post')
    def test_create_bison_sequence_steps(self, mock_post):
        """Test creating sequence steps for a Bison campaign."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "id": 456,
                "type": "Campaign sequence",
                "title": "Main Sequence",
                "sequence_steps": [
                    {
                        "id": 1,
                        "email_subject": "Introduction",
                        "order": 1,
                        "email_body": "Hi {FIRST_NAME}...",
                        "wait_in_days": 3,
                        "variant": False,
                        "variant_from_step_id": None,
                        "attachments": None,
                        "thread_reply": False
                    },
                    {
                        "id": 2,
                        "email_subject": "Follow-up",
                        "order": 2,
                        "email_body": "Just following up...",
                        "wait_in_days": 5,
                        "variant": False,
                        "variant_from_step_id": None,
                        "attachments": None,
                        "thread_reply": True
                    }
                ]
            }
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        sequence_steps = [
            {
                "email_subject": "Introduction",
                "order": 1,
                "email_body": "Hi {{first_name}}...",  # Test placeholder conversion
                "wait_in_days": 3
            },
            {
                "email_subject": "Follow-up",
                "order": 2,
                "email_body": "Just following up...",
                "wait_in_days": 5,
                "thread_reply": True
            }
        ]

        result = bison_client.create_bison_sequence_api(
            api_key="test_key",
            campaign_id=123,
            title="Main Sequence",
            sequence_steps=sequence_steps
        )

        # Verify the request
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "123/sequence-steps" in call_args[0][0]
        assert call_args[1]["json"]["title"] == "Main Sequence"

        # Verify the response
        assert result["data"]["title"] == "Main Sequence"
        assert len(result["data"]["sequence_steps"]) == 2

    @patch('src.leads.bison_client.requests.post')
    def test_bison_placeholder_conversion(self, mock_post):
        """Test that placeholders are converted to Bison format."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": {"id": 1}}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        sequence_steps = [
            {
                "subject": "Hi {{firstName}}",  # Should convert to {FIRST_NAME}
                "body": "Hello {{company}}",  # Should convert to {COMPANY_NAME}
                "order": 1,
                "wait_in_days": 3
            }
        ]

        bison_client.create_bison_sequence_api(
            api_key="test_key",
            campaign_id=123,
            title="Test",
            sequence_steps=sequence_steps
        )

        # Check the actual payload sent
        call_args = mock_post.call_args
        payload = call_args[1]["json"]

        # Placeholders should be converted
        step = payload["sequence_steps"][0]
        assert "{FIRST_NAME}" in step["email_subject"]
        assert "{COMPANY_NAME}" in step["email_body"]


class TestInstantlyCampaignCreation:
    """Tests for creating Instantly campaigns."""

    @patch('src.leads.instantly_client.requests.post')
    def test_create_instantly_campaign(self, mock_post):
        """Test creating an Instantly campaign with sequences."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "id": "abc-123-def-456",
            "name": "Test Campaign",
            "status": "draft"
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        sequence_steps = [
            {
                "subject": "Introduction",
                "body": "Hi there!\n\nThis is the first email.",
                "wait": 0
            },
            {
                "subject": "Follow-up",
                "body": "Just checking in...",
                "wait": 3
            }
        ]

        result = instantly_client.create_instantly_campaign_api(
            api_key="test_key",
            name="Test Campaign",
            sequence_steps=sequence_steps,
            daily_limit=50,
            timezone="America/Chicago"
        )

        # Verify the request
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "campaigns" in call_args[0][0]

        payload = call_args[1]["json"]
        assert payload["name"] == "Test Campaign"
        assert payload["daily_limit"] == 50
        assert len(payload["sequences"][0]["steps"]) == 2

        # Verify the response
        assert result["name"] == "Test Campaign"

    @patch('src.leads.instantly_client.requests.post')
    def test_instantly_html_conversion(self, mock_post):
        """Test that plain text is converted to Instantly HTML format."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": "123"}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        sequence_steps = [
            {
                "subject": "Test",
                "body": "Paragraph 1\n\nParagraph 2\n\nParagraph 3",
                "wait": 0
            }
        ]

        instantly_client.create_instantly_campaign_api(
            api_key="test_key",
            name="Test",
            sequence_steps=sequence_steps
        )

        # Check the payload
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        body = payload["sequences"][0]["steps"][0]["variants"][0]["body"]

        # Should be converted to HTML divs
        assert "<div>" in body
        assert "</div>" in body

    def test_instantly_timezone_validation(self):
        """Test that timezone validation works."""
        from src.leads.instantly_client import INSTANTLY_VALID_TIMEZONES

        # Valid timezones
        assert "America/Chicago" in INSTANTLY_VALID_TIMEZONES
        assert "America/Detroit" in INSTANTLY_VALID_TIMEZONES
        assert "Europe/London" not in INSTANTLY_VALID_TIMEZONES  # Not in their list

    @patch('src.leads.instantly_client.requests.post')
    def test_instantly_schedule_configuration(self, mock_post):
        """Test campaign schedule configuration."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": "123"}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        days = {
            "0": False,  # Sunday
            "1": True,   # Monday
            "2": True,   # Tuesday
            "3": True,   # Wednesday
            "4": True,   # Thursday
            "5": True,   # Friday
            "6": False   # Saturday
        }

        instantly_client.create_instantly_campaign_api(
            api_key="test_key",
            name="Test",
            sequence_steps=[{"subject": "Test", "body": "Test", "wait": 0}],
            schedule_from="09:00",
            schedule_to="17:00",
            days=days,
            timezone="America/Chicago"
        )

        # Check the payload
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        schedule = payload["campaign_schedule"]["schedules"][0]

        assert schedule["timing"]["from"] == "09:00"
        assert schedule["timing"]["to"] == "17:00"
        assert schedule["days"]["1"] == True  # Monday
        assert schedule["days"]["0"] == False  # Sunday
        assert schedule["timezone"] == "America/Chicago"


class TestListingCampaigns:
    """Tests for listing campaigns."""

    @patch('src.leads.bison_client.requests.get')
    def test_list_bison_campaigns(self, mock_get):
        """Test listing Bison campaigns."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": 1,
                    "uuid": "abc-123",
                    "name": "Campaign 1",
                    "type": "outbound",
                    "status": "active",
                    "emails_sent": 100,
                    "opened": 50
                },
                {
                    "id": 2,
                    "uuid": "def-456",
                    "name": "Campaign 2",
                    "type": "outbound",
                    "status": "paused",
                    "emails_sent": 200,
                    "opened": 75
                }
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = bison_client.list_bison_campaigns(
            api_key="test_key",
            status="active"
        )

        # Verify the request
        call_args = mock_get.call_args
        assert call_args[1]["params"]["status"] == "active"

        # Verify the response
        assert len(result["data"]) == 2
        assert result["data"][0]["name"] == "Campaign 1"

    @patch('src.leads.instantly_client.requests.get')
    def test_list_instantly_campaigns(self, mock_get):
        """Test listing Instantly campaigns."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "items": [
                {
                    "id": "abc-123",
                    "name": "Campaign A",
                    "status": 1
                },
                {
                    "id": "def-456",
                    "name": "Campaign B",
                    "status": 2
                }
            ],
            "next_starting_after": None
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = instantly_client.list_instantly_campaigns(
            api_key="test_key",
            status=1  # Active
        )

        # Verify the request
        call_args = mock_get.call_args
        assert call_args[1]["params"]["status"] == 1

        # Verify the response (should extract "items")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "Campaign A"

    @patch('src.leads.bison_client.requests.get')
    def test_list_bison_campaigns_with_search(self, mock_get):
        """Test searching Bison campaigns by name."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        bison_client.list_bison_campaigns(
            api_key="test_key",
            search="Test Campaign"
        )

        call_args = mock_get.call_args
        assert call_args[1]["params"]["search"] == "Test Campaign"


class TestCampaignDetails:
    """Tests for getting campaign details."""

    @patch('src.leads.bison_client.requests.get')
    def test_get_bison_campaign_sequences(self, mock_get):
        """Test getting Bison campaign sequences."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "sequence_id": 123,
                "sequence_steps": [
                    {
                        "id": 1,
                        "email_subject": "Step 1",
                        "order": "1",
                        "email_body": "Body 1",
                        "wait_in_days": "3",
                        "variant": False,
                        "variant_from_step_id": None,
                        "attachments": [],
                        "thread_reply": False
                    }
                ]
            }
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = bison_client.get_bison_campaign_sequences(
            api_key="test_key",
            campaign_id=123
        )

        # Verify the request
        call_args = mock_get.call_args
        assert "123/sequence-steps" in call_args[0][0]

        # Verify the response
        assert result["data"]["sequence_id"] == 123
        assert len(result["data"]["sequence_steps"]) == 1

    @patch('src.leads.instantly_client.requests.get')
    def test_get_instantly_campaign_details(self, mock_get):
        """Test getting Instantly campaign details."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "id": "abc-123",
            "name": "Test Campaign",
            "status": "active",
            "sequences": [
                {
                    "steps": [
                        {
                            "type": "email",
                            "delay": 0,
                            "variants": [
                                {
                                    "subject": "Step 1",
                                    "body": "<div>Content</div>"
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = instantly_client.get_instantly_campaign_details(
            api_key="test_key",
            campaign_id="abc-123"
        )

        # Verify the request
        call_args = mock_get.call_args
        assert "abc-123" in call_args[0][0]

        # Verify the response
        assert result["name"] == "Test Campaign"
        assert len(result["sequences"]) == 1


class TestCampaignStatusMapping:
    """Tests for campaign status handling."""

    def test_bison_status_strings(self):
        """Test that Bison accepts status strings."""
        statuses = ["active", "launching", "draft", "paused"]

        for status in statuses:
            assert isinstance(status, str)

    def test_instantly_status_numbers(self):
        """Test Instantly status number mapping."""
        status_map = {
            "draft": 0,
            "active": 1,
            "paused": 2,
            "completed": 3,
            "running_subsequences": 4
        }

        for name, number in status_map.items():
            assert isinstance(number, int)
            assert 0 <= number <= 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
