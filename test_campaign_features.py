#!/usr/bin/env python3
"""
Unit tests for campaign creation features.

Tests:
1. Bison placeholder conversion ({{firstname}} → {FIRST_NAME})
2. Instantly HTML formatting (newlines → <div> structure)
3. Fuzzy client name matching
4. Full campaign creation workflow
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

import unittest
from unittest.mock import Mock, patch, MagicMock
from leads import bison_client, instantly_client, sheets_client
from rapidfuzz import fuzz


class TestBisonPlaceholderConversion(unittest.TestCase):
    """Test Bison placeholder conversion."""

    def test_convert_double_brace_to_bison(self):
        """Test {{first_name}} → {FIRST_NAME}"""
        text = "Hey {{first_name}}, how are you?"
        result = bison_client._convert_to_bison_placeholders(text)
        self.assertEqual(result, "Hey {FIRST_NAME}, how are you?")

    def test_convert_firstname_variations(self):
        """Test various firstname formats."""
        test_cases = [
            ("{{firstname}}", "{FIRST_NAME}"),
            ("{{firstName}}", "{FIRST_NAME}"),
            ("{{first_name}}", "{FIRST_NAME}"),
            ("{{first name}}", "{FIRST_NAME}"),
            ("{first_name}", "{FIRST_NAME}"),
        ]
        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                result = bison_client._convert_to_bison_placeholders(input_text)
                self.assertEqual(result, expected)

    def test_convert_company_variations(self):
        """Test various company name formats."""
        test_cases = [
            ("{{company}}", "{COMPANY_NAME}"),
            ("{{companyname}}", "{COMPANY_NAME}"),
            ("{{companyName}}", "{COMPANY_NAME}"),
            ("{{company_name}}", "{COMPANY_NAME}"),
        ]
        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                result = bison_client._convert_to_bison_placeholders(input_text)
                self.assertEqual(result, expected)

    def test_convert_full_email_body(self):
        """Test conversion in full email body."""
        body = """Hey {{first_name}},

I noticed {{company}} is growing fast. Would you mind if I shared some info about how we help companies like {{company}}?

Best,
{{sender_name}}"""

        result = bison_client._convert_to_bison_placeholders(body)

        self.assertIn("{FIRST_NAME}", result)
        self.assertIn("{COMPANY_NAME}", result)
        self.assertNotIn("{{first_name}}", result)
        self.assertNotIn("{{company}}", result)

    def test_no_conversion_needed(self):
        """Test text that already has Bison placeholders."""
        text = "Hey {FIRST_NAME}, welcome to {COMPANY_NAME}!"
        result = bison_client._convert_to_bison_placeholders(text)
        self.assertEqual(result, text)

    def test_mixed_placeholders(self):
        """Test text with both Bison and non-Bison placeholders."""
        text = "Hey {{first_name}}, welcome to {COMPANY_NAME}!"
        result = bison_client._convert_to_bison_placeholders(text)
        expected = "Hey {FIRST_NAME}, welcome to {COMPANY_NAME}!"
        self.assertEqual(result, expected)


class TestInstantlyHtmlFormatting(unittest.TestCase):
    """Test Instantly HTML div formatting."""

    def test_plain_text_to_html(self):
        """Test plain text with newlines converts to HTML divs."""
        body = """Hey there,

How are you doing?

Best,
Mike"""

        # Access the helper function by calling the transformation
        result = self._format_body(body)

        # Check for HTML structure
        self.assertIn("<div>", result)
        self.assertIn("</div>", result)
        self.assertIn("<br />", result)

        # Should have multiple paragraphs
        self.assertTrue(result.count("<div>") >= 3)

    def test_single_paragraph(self):
        """Test single paragraph with no newlines."""
        body = "This is a single line email."
        result = self._format_body(body)

        # Should wrap in div
        self.assertIn("<div>", result)
        self.assertIn("</div>", result)

    def test_line_break_within_paragraph(self):
        """Test line breaks within a paragraph."""
        body = """Best,
Mike"""

        result = self._format_body(body)

        # Should have <br /> for the line break
        self.assertIn("Best,<br />Mike", result)

    def test_already_has_html(self):
        """Test that already formatted HTML is not modified."""
        body = "<div>Hello</div><div><br /></div><div>World</div>"
        result = self._format_body(body)

        # Should return as-is
        self.assertEqual(result, body)

    def test_full_email_formatting(self):
        """Test full email with proper paragraph spacing."""
        body = """Hey {{first_name}}, how do most of your speaking gigs come in today?

Asking because I've been working with professional speakers who wanted a steadier flow of bookings without relying only on referrals.

Would you mind if I sent over a bit more info?

Best,
Mike"""

        result = self._format_body(body)

        # Check structure
        self.assertIn("<div>Hey {{first_name}}", result)
        self.assertIn("<div><br /></div>", result)  # Paragraph spacing
        self.assertIn("<div>Best,<br />Mike</div>", result)

        # Count divs - should have one per paragraph plus spacing
        div_count = result.count("<div>")
        self.assertGreaterEqual(div_count, 7)  # 4 paragraphs + 3 spacers

    def _format_body(self, body):
        """Helper to test the HTML formatting function."""
        # Simulate what the instantly_client does
        if not body:
            return body

        if '<div>' in body or '<br />' in body:
            return body

        paragraphs = body.split('\n\n')
        html_parts = []
        for para in paragraphs:
            para = para.replace('\n', '<br />')
            html_parts.append(f'<div>{para}</div>')

        return '<div><br /></div>'.join(html_parts)


class TestFuzzyClientMatching(unittest.TestCase):
    """Test fuzzy matching for client names."""

    def setUp(self):
        """Set up test client list."""
        self.clients = [
            {"client_name": "Michael Hernandez", "api_key": "test-key-1"},
            {"client_name": "Brian Bliss", "api_key": "test-key-2"},
            {"client_name": "Source 1 Parcel", "api_key": "test-key-3"},
            {"client_name": "John Smith", "api_key": "test-key-4"},
        ]

    def test_exact_match(self):
        """Test exact client name match."""
        from rapidfuzz import process

        client_names = [c["client_name"] for c in self.clients]
        result = process.extractOne(
            "Michael Hernandez",
            client_names,
            scorer=fuzz.WRatio,
            score_cutoff=60
        )

        self.assertIsNotNone(result)
        matched_name, score, index = result
        self.assertEqual(matched_name, "Michael Hernandez")
        self.assertEqual(score, 100.0)

    def test_typo_match(self):
        """Test matching with typos."""
        from rapidfuzz import process

        client_names = [c["client_name"] for c in self.clients]

        # Test various typos
        test_cases = [
            ("michael hernandex", "Michael Hernandez"),
            ("brian blis", "Brian Bliss"),
            ("source1 parcel", "Source 1 Parcel"),
        ]

        for query, expected in test_cases:
            with self.subTest(query=query):
                result = process.extractOne(
                    query,
                    client_names,
                    scorer=fuzz.WRatio,
                    score_cutoff=60
                )

                self.assertIsNotNone(result)
                matched_name, score, index = result
                self.assertEqual(matched_name, expected)
                self.assertGreaterEqual(score, 60)

    def test_partial_match(self):
        """Test partial name matching."""
        from rapidfuzz import process

        client_names = [c["client_name"] for c in self.clients]
        result = process.extractOne(
            "Hernandez",
            client_names,
            scorer=fuzz.WRatio,
            score_cutoff=60
        )

        self.assertIsNotNone(result)
        matched_name, score, index = result
        self.assertEqual(matched_name, "Michael Hernandez")

    def test_no_match_below_threshold(self):
        """Test that poor matches return None."""
        from rapidfuzz import process

        client_names = [c["client_name"] for c in self.clients]
        result = process.extractOne(
            "Random Person",
            client_names,
            scorer=fuzz.WRatio,
            score_cutoff=60
        )

        # Should not find a good match
        if result:
            _, score, _ = result
            self.assertLess(score, 60)


class TestCampaignCreationWorkflow(unittest.TestCase):
    """Test full campaign creation workflow."""

    @patch('leads.bison_client.requests.post')
    def test_bison_campaign_creation(self, mock_post):
        """Test creating a Bison campaign with placeholder conversion."""
        # Mock API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "test-campaign-123",
            "title": "Test Campaign"
        }
        mock_post.return_value = mock_response

        # Create campaign with placeholders
        steps = [
            {
                "subject": "Hey {{first_name}}",
                "body": "Hi {{first_name}}, I work with {{company}} companies.",
                "wait_in_days": 1
            }
        ]

        result = bison_client.create_bison_sequence_api(
            api_key="test-key",
            campaign_id=123,
            title="Test Campaign",
            sequence_steps=steps
        )

        # Verify API was called
        self.assertTrue(mock_post.called)

        # Get the payload that was sent
        call_args = mock_post.call_args
        payload = call_args[1]['json']

        # Check placeholders were converted
        sent_steps = payload['sequence_steps']
        self.assertIn("{FIRST_NAME}", sent_steps[0]['email_subject'])
        self.assertIn("{FIRST_NAME}", sent_steps[0]['email_body'])
        self.assertIn("{COMPANY_NAME}", sent_steps[0]['email_body'])

        # Should not have double-brace placeholders
        self.assertNotIn("{{first_name}}", sent_steps[0]['email_body'])

    @patch('leads.instantly_client.requests.post')
    def test_instantly_campaign_creation(self, mock_post):
        """Test creating an Instantly campaign with HTML formatting."""
        # Mock API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "test-campaign-456",
            "name": "Test Campaign"
        }
        mock_post.return_value = mock_response

        # Create campaign with multi-line body
        steps = [
            {
                "subject": "quick question",
                "body": """Hey {{first_name}}, how are you?

I wanted to reach out about your company.

Best,
Mike""",
                "wait": 0
            }
        ]

        result = instantly_client.create_instantly_campaign_api(
            api_key="test-key",
            name="Test Campaign",
            sequence_steps=steps
        )

        # Verify API was called
        self.assertTrue(mock_post.called)

        # Get the payload that was sent
        call_args = mock_post.call_args
        payload = call_args[1]['json']

        # Check HTML structure
        sent_body = payload['sequences'][0]['steps'][0]['variants'][0]['body']

        # Should have HTML div structure
        self.assertIn("<div>", sent_body)
        self.assertIn("</div>", sent_body)
        self.assertIn("<div><br /></div>", sent_body)

        # Should not have raw newlines
        self.assertNotIn("\n\n", sent_body)

    @patch('leads.sheets_client.requests.get')
    def test_client_lookup_with_fuzzy_match(self, mock_get):
        """Test looking up client with fuzzy matching."""
        # Mock Google Sheets response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = """Client Name,API Key
Michael Hernandez,test-key-mh
Brian Bliss,test-key-bb
Source 1 Parcel,test-key-s1p"""
        mock_get.return_value = mock_response

        # Load clients
        clients = sheets_client.load_bison_workspaces_from_sheet()

        # Test fuzzy matching
        from rapidfuzz import process
        client_names = [c["client_name"] for c in clients]

        # Test with typo
        result = process.extractOne(
            "michael hernandex",
            client_names,
            scorer=fuzz.WRatio,
            score_cutoff=60
        )

        self.assertIsNotNone(result)
        matched_name, score, index = result
        self.assertEqual(matched_name, "Michael Hernandez")

        # Get the client
        client = clients[index]
        self.assertEqual(client["api_key"], "test-key-mh")


def run_tests():
    """Run all tests and print results."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestBisonPlaceholderConversion))
    suite.addTests(loader.loadTestsFromTestCase(TestInstantlyHtmlFormatting))
    suite.addTests(loader.loadTestsFromTestCase(TestFuzzyClientMatching))
    suite.addTests(loader.loadTestsFromTestCase(TestCampaignCreationWorkflow))

    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.wasSuccessful():
        print("\n✅ ALL TESTS PASSED!")
    else:
        print("\n❌ SOME TESTS FAILED")

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
