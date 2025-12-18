"""
Test cases for the false positive bugs found in James Mccoy analysis.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from leads.interest_analyzer import analyze_reply_with_keywords


class TestAutoReplyDetection:
    """Test that auto-replies are NOT flagged as interested leads."""

    def test_out_of_office_not_hot(self):
        """Out of office should be AUTO_REPLY, not HOT."""
        reply = "Thank you for your email. I am currently out of the office until 16 December 2025."
        result = analyze_reply_with_keywords(reply)

        assert result["category"] == "auto_reply", f"Expected auto_reply, got {result['category']}"
        assert result["confidence"] >= 90

    def test_automatic_reply_subject(self):
        """Subject line with 'Automatic reply:' should trigger auto-reply detection."""
        reply = "Thank you for your email. A member of the team will follow up."
        subject = "Automatic reply: outgrowing Sheets for budgeting"
        result = analyze_reply_with_keywords(reply, subject=subject)

        assert result["category"] == "auto_reply", f"Expected auto_reply, got {result['category']}"

    def test_left_organization_not_hot(self):
        """'Left the organization' should be AUTO_REPLY, not HOT."""
        reply = "Thank you for your email. I have now left the organisation. Please direct any emails to finance@company.com."
        result = analyze_reply_with_keywords(reply)

        assert result["category"] == "auto_reply", f"Expected auto_reply, got {result['category']}"

    def test_retired_not_hot(self):
        """'Retired' should be AUTO_REPLY, not HOT."""
        reply = "Thank you for your message. Chris Cherry has retired from Wesley Housing as of November 3, 2025."
        result = analyze_reply_with_keywords(reply)

        assert result["category"] == "auto_reply", f"Expected auto_reply, got {result['category']}"

    def test_unmonitored_mailbox_not_hot(self):
        """Unmonitored mailbox should be AUTO_REPLY, not HOT."""
        reply = "This mailbox is an un-monitored mailbox. Any emails to this address will not be returned."
        result = analyze_reply_with_keywords(reply)

        assert result["category"] == "auto_reply", f"Expected auto_reply, got {result['category']}"

    def test_mailbox_not_accepting_not_hot(self):
        """Mailbox not accepting messages should be AUTO_REPLY, not HOT."""
        reply = "This is an automated reply: the mailbox howard@company.com is currently not accepting messages."
        result = analyze_reply_with_keywords(reply)

        assert result["category"] == "auto_reply", f"Expected auto_reply, got {result['category']}"

    def test_standard_response_time_not_hot(self):
        """Standard response time message should be AUTO_REPLY, not HOT."""
        reply = "Thank you for your email. We will aim to respond to your enquiry in our standard response time of 5-7 working days."
        result = analyze_reply_with_keywords(reply)

        assert result["category"] == "auto_reply", f"Expected auto_reply, got {result['category']}"

    def test_all_day_meeting_not_hot(self):
        """'In an all day meeting' should be AUTO_REPLY, not HOT."""
        reply = "Thank you for your email. I am in an all day meeting and will reply to calls and emails at the end of the day."
        result = analyze_reply_with_keywords(reply)

        assert result["category"] == "auto_reply", f"Expected auto_reply, got {result['category']}"


class TestRejectionDetection:
    """Test that rejections are properly flagged as COLD."""

    def test_no_thanks_is_cold(self):
        """'No thanks' should be COLD, not HOT."""
        reply = "No thanks"
        result = analyze_reply_with_keywords(reply)

        assert result["category"] == "cold", f"Expected cold, got {result['category']}"
        assert result["confidence"] >= 85

    def test_unsubscribe_is_cold(self):
        """Unsubscribe request should be COLD."""
        reply = "Please unsubscribe me from this list."
        subject = "UNSUBSCRIBE"
        result = analyze_reply_with_keywords(reply, subject=subject)

        assert result["category"] == "cold", f"Expected cold, got {result['category']}"


class TestJamesMccoyFalsePositives:
    """Test the actual false positives from James Mccoy analysis."""

    def test_tony_dudley_no_thanks(self):
        """tony.dudley@seermedical.com - 'No thanks' should NOT be HOT."""
        reply = "No thanks"
        result = analyze_reply_with_keywords(reply)

        assert result["category"] != "hot", f"'No thanks' should not be HOT! Got: {result['category']}"

    def test_nathan_sloane_ooo(self):
        """nathan.sloane - Out of office should NOT be HOT."""
        reply = """Thank you for your email. Penrith Christian School values a healthy life balance
for its staff and therefore staff are not expected to check or respond to emails
outside of regular hours or on their non-working days."""
        result = analyze_reply_with_keywords(reply)

        assert result["category"] == "auto_reply", f"OOO message should be auto_reply! Got: {result['category']}"

    def test_tim_arc_inspirations_left(self):
        """tim@arcinspirations.com - 'I have left' should NOT be HOT."""
        reply = "As of 9th June I have left Arc Inspirations. If you wish to contact someone in the business call the office."
        result = analyze_reply_with_keywords(reply)

        assert result["category"] == "auto_reply", f"'Left company' should be auto_reply! Got: {result['category']}"

    def test_eric_easton_all_day_meeting(self):
        """eric.easton - All day meeting should NOT be HOT."""
        reply = "Thank you for your email. I am in an all day meeting and will reply to calls and emails at the end of the day."
        subject = "Automatic reply: outgrowing Sheets for budgeting"
        result = analyze_reply_with_keywords(reply, subject=subject)

        assert result["category"] == "auto_reply", f"All day meeting should be auto_reply! Got: {result['category']}"

    def test_michael_melisi_team_followup(self):
        """michael.melisi - Auto-forward message should NOT be HOT."""
        reply = "Thank you for your email. A member of the team will follow up."
        subject = "Automatic reply: outgrowing Sheets for budgeting"
        result = analyze_reply_with_keywords(reply, subject=subject)

        assert result["category"] == "auto_reply", f"Auto-forward should be auto_reply! Got: {result['category']}"

    def test_mseuring_unsubscribe(self):
        """mseuring - UNSUBSCRIBE should NOT be HOT."""
        reply = "Michael Seuring Senior Vice President and Chief Financial Officer"
        subject = "UNSUBSCRIBE"
        result = analyze_reply_with_keywords(reply, subject=subject)

        # This one might not be detected by subject alone, but shouldn't be HOT
        assert result["category"] != "hot", f"UNSUBSCRIBE should not be HOT! Got: {result['category']}"

    def test_kanaifeh_unmonitored(self):
        """kanaifeh - Unmonitored mailbox should NOT be HOT."""
        reply = "This mailbox is an un-monitored mailbox. Any emails to this address will not be returned."
        subject = "Automatic reply: outgrowing Sheets for budgeting"
        result = analyze_reply_with_keywords(reply, subject=subject)

        assert result["category"] == "auto_reply", f"Unmonitored mailbox should be auto_reply! Got: {result['category']}"


class TestKeywordContextAwareness:
    """Test that keywords like 'budget', 'call', 'meeting' don't trigger in wrong contexts."""

    def test_budget_in_auto_reply_not_hot(self):
        """'budget' in auto-reply context should NOT be HOT."""
        reply = "Thank you for your email about budget. I am out of office until Monday."
        result = analyze_reply_with_keywords(reply)

        assert result["category"] == "auto_reply", "Auto-reply should override keyword matches"

    def test_call_in_auto_reply_not_hot(self):
        """'call' in auto-reply context should NOT be HOT."""
        reply = "If your enquiry is urgent, please call 0800 917 6077. I am currently out of the office."
        result = analyze_reply_with_keywords(reply)

        assert result["category"] == "auto_reply", "Auto-reply should override keyword matches"

    def test_meeting_in_auto_reply_not_hot(self):
        """'meeting' in auto-reply context should NOT be HOT."""
        reply = "I am in an all day meeting and will reply when I return."
        result = analyze_reply_with_keywords(reply)

        assert result["category"] == "auto_reply", "Auto-reply should override keyword matches"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
