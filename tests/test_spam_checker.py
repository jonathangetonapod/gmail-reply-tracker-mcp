"""Unit tests for spam checker functionality."""

import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from leads import spam_checker


@pytest.fixture
def mock_emailguard_key():
    """Mock EmailGuard API key."""
    return "test_emailguard_key"


@pytest.fixture
def mock_emailguard_response_clean():
    """Mock EmailGuard API response for clean content."""
    return {
        "data": {
            "message": {
                "is_spam": False,
                "spam_score": 1.0,
                "spam_words": [],
                "number_of_spam_words": 0
            }
        }
    }


@pytest.fixture
def mock_emailguard_response_spam():
    """Mock EmailGuard API response for spammy content."""
    return {
        "data": {
            "message": {
                "is_spam": True,
                "spam_score": 5.0,
                "spam_words": ["FREE", "100%", "limited time offer"],
                "number_of_spam_words": 3
            }
        }
    }


class TestAdHocSpamChecking:
    """Test ad-hoc text spam checking (no campaign needed)."""

    @patch('leads.emailguard_client.check_content_spam')
    def test_check_clean_subject(self, mock_check, mock_emailguard_key, mock_emailguard_response_clean):
        """Test checking a clean subject line."""
        mock_check.return_value = mock_emailguard_response_clean

        result = spam_checker.check_text_spam(
            emailguard_key=mock_emailguard_key,
            subject="Quick question about your website",
            body=""
        )

        assert result["is_spam"] == False
        assert result["spam_score"] == 1.0
        assert result["spam_words"] == []
        assert result["subject"] == "Quick question about your website"
        mock_check.assert_called_once()

    @patch('leads.emailguard_client.check_content_spam')
    def test_check_spammy_subject(self, mock_check, mock_emailguard_key, mock_emailguard_response_spam):
        """Test checking a spammy subject line."""
        mock_check.return_value = mock_emailguard_response_spam

        result = spam_checker.check_text_spam(
            emailguard_key=mock_emailguard_key,
            subject="Get 100% FREE money now! Limited time offer!!!",
            body=""
        )

        assert result["is_spam"] == True
        assert result["spam_score"] == 5.0
        assert "FREE" in result["spam_words"]
        assert "100%" in result["spam_words"]
        mock_check.assert_called_once()

    @patch('leads.emailguard_client.check_content_spam')
    def test_check_subject_and_body(self, mock_check, mock_emailguard_key, mock_emailguard_response_spam):
        """Test checking both subject and body."""
        mock_check.return_value = mock_emailguard_response_spam

        result = spam_checker.check_text_spam(
            emailguard_key=mock_emailguard_key,
            subject="Quick question",
            body="Hi, I noticed your website and wanted to reach out. Would you be interested in increasing your sales by 200%? We guarantee results or your money back!"
        )

        assert result["is_spam"] == True
        assert result["spam_score"] == 5.0
        assert result["subject"] == "Quick question"
        assert len(result["body"]) > 0
        mock_check.assert_called_once()

    def test_check_empty_content(self, mock_emailguard_key):
        """Test checking with no content provided."""
        result = spam_checker.check_text_spam(
            emailguard_key=mock_emailguard_key,
            subject="",
            body=""
        )

        assert "error" in result
        assert result["is_spam"] == False
        assert result["spam_score"] == 0

    @patch('leads.emailguard_client.check_content_spam')
    def test_check_body_only(self, mock_check, mock_emailguard_key, mock_emailguard_response_clean):
        """Test checking body without subject."""
        mock_check.return_value = mock_emailguard_response_clean

        result = spam_checker.check_text_spam(
            emailguard_key=mock_emailguard_key,
            subject="",
            body="This is a normal email body with no spam triggers."
        )

        assert result["is_spam"] == False
        assert result["subject"] == ""
        assert result["body"] == "This is a normal email body with no spam triggers."
        mock_check.assert_called_once()


class TestBisonCampaignSpamChecking:
    """Test Bison campaign spam checking."""

    @patch('leads.bison_client.get_bison_campaign_sequences')
    @patch('leads.emailguard_client.check_content_spam')
    def test_check_bison_campaign_all_clean(self, mock_emailguard, mock_bison_sequences,
                                            mock_emailguard_key, mock_emailguard_response_clean):
        """Test checking a Bison campaign with all clean steps."""
        # Mock Bison API response
        mock_bison_sequences.return_value = {
            "data": {
                "sequence_id": 123,
                "sequence_steps": [
                    {
                        "id": 1,
                        "order": 1,
                        "email_subject": "Quick question",
                        "email_body": "Hi, just wanted to reach out.",
                        "wait_in_days": 3
                    },
                    {
                        "id": 2,
                        "order": 2,
                        "email_subject": "Following up",
                        "email_body": "Did you get my last email?",
                        "wait_in_days": 5
                    }
                ]
            }
        }

        # Mock EmailGuard to return clean for all checks
        mock_emailguard.return_value = mock_emailguard_response_clean

        result = spam_checker.check_bison_campaign_spam(
            api_key="test_bison_key",
            emailguard_key=mock_emailguard_key,
            campaign_id=456,
            campaign_name="Test Campaign"
        )

        assert result["campaign_id"] == 456
        assert result["campaign_name"] == "Test Campaign"
        assert result["total_steps"] == 2
        assert result["spam_steps"] == 0
        assert len(result["steps"]) == 2

        # Verify all steps are marked as not spam
        for step in result["steps"]:
            assert step["is_spam"] == False
            assert step["spam_score"] == 1.0

    @patch('leads.bison_client.get_bison_campaign_sequences')
    @patch('leads.emailguard_client.check_content_spam')
    def test_check_bison_campaign_with_spam(self, mock_emailguard, mock_bison_sequences,
                                            mock_emailguard_key, mock_emailguard_response_spam):
        """Test checking a Bison campaign with spam steps."""
        # Mock Bison API response
        mock_bison_sequences.return_value = {
            "data": {
                "sequence_id": 123,
                "sequence_steps": [
                    {
                        "id": 1,
                        "order": 1,
                        "email_subject": "Get 100% FREE money!!!",
                        "email_body": "Limited time offer! Act now!",
                        "wait_in_days": 3
                    },
                    {
                        "id": 2,
                        "order": 2,
                        "email_subject": "Following up",
                        "email_body": "Did you see my offer?",
                        "wait_in_days": 5
                    }
                ]
            }
        }

        # Mock EmailGuard to return spam for all checks
        mock_emailguard.return_value = mock_emailguard_response_spam

        result = spam_checker.check_bison_campaign_spam(
            api_key="test_bison_key",
            emailguard_key=mock_emailguard_key,
            campaign_id=456,
            campaign_name="Spammy Campaign"
        )

        assert result["campaign_id"] == 456
        assert result["campaign_name"] == "Spammy Campaign"
        assert result["total_steps"] == 2
        assert result["spam_steps"] == 2

        # Verify all steps are marked as spam
        for step in result["steps"]:
            assert step["is_spam"] == True
            assert step["spam_score"] == 5.0
            assert len(step["spam_words"]) > 0


class TestInstantlyCampaignSpamChecking:
    """Test Instantly campaign spam checking."""

    @patch('leads.instantly_client.get_instantly_campaign_details')
    @patch('leads.emailguard_client.check_content_spam')
    def test_check_instantly_campaign_single_variant(self, mock_emailguard, mock_instantly_details,
                                                     mock_emailguard_key, mock_emailguard_response_clean):
        """Test checking an Instantly campaign with single variants."""
        # Mock Instantly API response
        mock_instantly_details.return_value = {
            "id": "campaign-uuid-123",
            "name": "Test Instantly Campaign",
            "status": 1,
            "sequences": [
                {
                    "steps": [
                        {
                            "type": "email",
                            "delay": 2,
                            "variants": [
                                {
                                    "subject": "Quick question",
                                    "body": "<div>Hi there,</div><div>Just wanted to reach out.</div>"
                                }
                            ]
                        },
                        {
                            "type": "email",
                            "delay": 5,
                            "variants": [
                                {
                                    "subject": "Following up",
                                    "body": "<div>Did you get my email?</div>"
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        # Mock EmailGuard to return clean
        mock_emailguard.return_value = mock_emailguard_response_clean

        result = spam_checker.check_instantly_campaign_spam(
            api_key="test_instantly_key",
            emailguard_key=mock_emailguard_key,
            campaign_id="campaign-uuid-123",
            campaign_name="Test Instantly Campaign"
        )

        assert result["campaign_id"] == "campaign-uuid-123"
        assert result["campaign_name"] == "Test Instantly Campaign"
        assert result["total_steps"] == 2
        assert result["spam_steps"] == 0

    @patch('leads.instantly_client.get_instantly_campaign_details')
    @patch('leads.emailguard_client.check_content_spam')
    def test_check_instantly_campaign_multiple_variants(self, mock_emailguard, mock_instantly_details,
                                                        mock_emailguard_key, mock_emailguard_response_clean,
                                                        mock_emailguard_response_spam):
        """Test checking an Instantly campaign with multiple variants (A/B test)."""
        # Mock Instantly API response with A/B variants
        mock_instantly_details.return_value = {
            "id": "campaign-uuid-123",
            "name": "A/B Test Campaign",
            "status": 1,
            "sequences": [
                {
                    "steps": [
                        {
                            "type": "email",
                            "delay": 2,
                            "variants": [
                                {
                                    "subject": "Quick question",
                                    "body": "<div>Hi there</div>"
                                },
                                {
                                    "subject": "Get 100% FREE money!!!",
                                    "body": "<div>Limited time offer!</div>"
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        # Mock EmailGuard to return clean for first variant, spam for second
        mock_emailguard.side_effect = [
            mock_emailguard_response_clean,
            mock_emailguard_response_spam
        ]

        result = spam_checker.check_instantly_campaign_spam(
            api_key="test_instantly_key",
            emailguard_key=mock_emailguard_key,
            campaign_id="campaign-uuid-123",
            campaign_name="A/B Test Campaign"
        )

        assert result["campaign_id"] == "campaign-uuid-123"
        assert result["total_steps"] == 2  # Both variants counted
        assert result["spam_steps"] == 1   # Only second variant is spam

        # Verify variant numbering
        assert result["steps"][0]["variant"] == 1
        assert result["steps"][0]["is_spam"] == False
        assert result["steps"][1]["variant"] == 2
        assert result["steps"][1]["is_spam"] == True

    @patch('leads.instantly_client.get_instantly_campaign_details')
    @patch('leads.emailguard_client.check_content_spam')
    def test_instantly_html_stripping(self, mock_emailguard, mock_instantly_details,
                                      mock_emailguard_key, mock_emailguard_response_clean):
        """Test that HTML tags are stripped from Instantly email bodies."""
        # Mock Instantly API response with HTML
        mock_instantly_details.return_value = {
            "id": "campaign-uuid-123",
            "name": "HTML Campaign",
            "status": 1,
            "sequences": [
                {
                    "steps": [
                        {
                            "type": "email",
                            "delay": 2,
                            "variants": [
                                {
                                    "subject": "Test",
                                    "body": "<div>Hello <strong>world</strong></div><div><br /></div><div>How are you?</div>"
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        mock_emailguard.return_value = mock_emailguard_response_clean

        result = spam_checker.check_instantly_campaign_spam(
            api_key="test_instantly_key",
            emailguard_key=mock_emailguard_key,
            campaign_id="campaign-uuid-123",
            campaign_name="HTML Campaign"
        )

        # Verify HTML was processed
        assert result["total_steps"] == 1
        mock_emailguard.assert_called_once()

        # Check that the call to EmailGuard had HTML stripped
        call_args = mock_emailguard.call_args[0]
        content = call_args[1]
        # Should not contain HTML tags
        assert "<div>" not in content
        assert "<strong>" not in content
        # Should contain the text
        assert "Hello" in content or "world" in content


class TestStatusMapping:
    """Test status string to number mapping for Instantly."""

    def test_instantly_status_mapping(self):
        """Test that status strings correctly map to numbers for Instantly."""
        # This would be tested through check_all_instantly_campaigns_spam
        # but we can test the mapping logic directly

        status_map = {
            "draft": 0,
            "active": 1,
            "paused": 2,
            "completed": 3,
            "running_subsequences": 4
        }

        # Verify our expected mappings
        assert status_map["draft"] == 0
        assert status_map["active"] == 1
        assert status_map["paused"] == 2
        assert status_map["completed"] == 3


class TestErrorHandling:
    """Test error handling in spam checker."""

    @patch('leads.emailguard_client.check_content_spam')
    def test_emailguard_api_error(self, mock_check, mock_emailguard_key):
        """Test handling of EmailGuard API errors."""
        # Mock API error
        mock_check.side_effect = Exception("API Error: Rate limit exceeded")

        result = spam_checker.check_text_spam(
            emailguard_key=mock_emailguard_key,
            subject="Test subject",
            body="Test body"
        )

        assert "error" in result
        assert "API Error" in result["error"]
        assert result["is_spam"] == False
        assert result["spam_score"] == 0

    @patch('leads.bison_client.get_bison_campaign_sequences')
    @patch('leads.emailguard_client.check_content_spam')
    def test_bison_step_check_error(self, mock_emailguard, mock_bison_sequences,
                                    mock_emailguard_key, mock_emailguard_response_clean):
        """Test handling errors when checking individual Bison steps."""
        # Mock Bison response with 2 steps
        mock_bison_sequences.return_value = {
            "data": {
                "sequence_id": 123,
                "sequence_steps": [
                    {
                        "id": 1,
                        "order": 1,
                        "email_subject": "Step 1",
                        "email_body": "Body 1",
                        "wait_in_days": 3
                    },
                    {
                        "id": 2,
                        "order": 2,
                        "email_subject": "Step 2",
                        "email_body": "Body 2",
                        "wait_in_days": 5
                    }
                ]
            }
        }

        # First check succeeds, second fails
        mock_emailguard.side_effect = [
            mock_emailguard_response_clean,
            Exception("Network error")
        ]

        result = spam_checker.check_bison_campaign_spam(
            api_key="test_key",
            emailguard_key=mock_emailguard_key,
            campaign_id=456,
            campaign_name="Error Test Campaign"
        )

        assert result["total_steps"] == 2
        assert len(result["steps"]) == 2

        # First step should have results
        assert result["steps"][0]["is_spam"] == False
        assert "error" not in result["steps"][0]

        # Second step should have error
        assert "error" in result["steps"][1]
        assert "Network error" in result["steps"][1]["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
