"""
Unit tests for workspace/client management functionality.

Tests:
- Loading workspaces from Google Sheets
- Client searching and filtering
- Bison workspace loading
- Instantly workspace loading
- Fuzzy matching for client names
"""

import pytest
from unittest.mock import Mock, patch
from src.leads import sheets_client


class TestLoadWorkspacesFromSheets:
    """Tests for loading workspace configurations from Google Sheets."""

    @patch('src.leads.sheets_client.requests.get')
    def test_load_instantly_workspaces(self, mock_get):
        """Test loading Instantly workspaces from Google Sheets."""
        # Mock CSV response
        csv_content = """Workspace ID,API Key,Workspace Name,Client Name,Client Email,Action
abc-123,key123,Source 1 Parcel,Brian Bliss,brian@example.com,Active
def-456,key456,ACME Corp,John Doe,john@example.com,Active"""

        mock_response = Mock()
        mock_response.text = csv_content
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = sheets_client.load_instantly_workspaces_from_sheet()

        # Verify the request
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "export?format=csv" in call_args[0][0]

        # Verify the response
        assert len(result) == 2
        assert result[0]["workspace_id"] == "abc-123"
        assert result[0]["api_key"] == "key123"
        assert result[0]["workspace_name"] == "Source 1 Parcel"
        assert result[0]["client_name"] == "Brian Bliss"
        assert result[0]["client_email"] == "brian@example.com"
        assert result[0]["action"] == "Active"

        assert result[1]["workspace_id"] == "def-456"
        assert result[1]["client_name"] == "John Doe"

    @patch('src.leads.sheets_client.requests.get')
    def test_load_bison_workspaces(self, mock_get):
        """Test loading Bison workspaces from Google Sheets."""
        csv_content = """Client Name,API Key
ABC Corp,key123
XYZ Ltd,key456"""

        mock_response = Mock()
        mock_response.text = csv_content
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = sheets_client.load_bison_workspaces_from_sheet()

        # Verify the response
        assert len(result) == 2
        assert result[0]["client_name"] == "ABC Corp"
        assert result[0]["api_key"] == "key123"
        assert result[1]["client_name"] == "XYZ Ltd"
        assert result[1]["api_key"] == "key456"

    @patch('src.leads.sheets_client.requests.get')
    def test_skip_header_row(self, mock_get):
        """Test that header rows are correctly skipped."""
        csv_content = """Workspace ID,API Key
abc-123,key123"""

        mock_response = Mock()
        mock_response.text = csv_content
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = sheets_client.load_workspaces_from_sheet()

        # Should only return data rows, not header
        assert len(result) == 1
        assert result[0]["workspace_id"] == "abc-123"

    @patch('src.leads.sheets_client.requests.get')
    def test_skip_empty_rows(self, mock_get):
        """Test that empty rows are correctly skipped."""
        csv_content = """Workspace ID,API Key
abc-123,key123
,
def-456,key456"""

        mock_response = Mock()
        mock_response.text = csv_content
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = sheets_client.load_workspaces_from_sheet()

        # Should skip empty row
        assert len(result) == 2
        assert result[0]["workspace_id"] == "abc-123"
        assert result[1]["workspace_id"] == "def-456"

    @patch('src.leads.sheets_client.requests.get')
    def test_handle_missing_optional_fields(self, mock_get):
        """Test handling rows with missing optional fields."""
        csv_content = """Workspace ID,API Key,Workspace Name,Client Name
abc-123,key123,,
def-456,key456,ACME,John"""

        mock_response = Mock()
        mock_response.text = csv_content
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = sheets_client.load_instantly_workspaces_from_sheet()

        # Should handle missing fields gracefully
        assert len(result) == 2
        assert result[0]["workspace_name"] == ""
        assert result[1]["workspace_name"] == "ACME"

    @patch('src.leads.sheets_client.requests.get')
    def test_custom_sheet_url_and_gid(self, mock_get):
        """Test using custom sheet URL and GID."""
        mock_response = Mock()
        mock_response.text = "ID,Key\n123,abc"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        custom_url = "https://docs.google.com/spreadsheets/d/CUSTOM_ID/edit"
        custom_gid = "999"

        sheets_client.load_workspaces_from_sheet(
            sheet_url=custom_url,
            gid=custom_gid
        )

        # Verify custom URL and GID were used
        call_args = mock_get.call_args
        assert "CUSTOM_ID" in call_args[0][0]
        assert "gid=999" in call_args[0][0]


class TestClientSearching:
    """Tests for client searching and filtering."""

    @patch('src.leads.sheets_client.requests.get')
    def test_search_by_client_name(self, mock_get):
        """Test searching for clients by name."""
        csv_content = """Client Name,API Key
Ryan Bandolik,key1
Brian Bliss,key2
Ryne Bandolik - Jobsdone,key3"""

        mock_response = Mock()
        mock_response.text = csv_content
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        workspaces = sheets_client.load_bison_workspaces_from_sheet()

        # Test exact match
        matches = [w for w in workspaces if "Ryan" in w["client_name"]]
        assert len(matches) == 1

        # Test partial match
        matches = [w for w in workspaces if "Bandolik" in w["client_name"]]
        assert len(matches) == 2

    @patch('src.leads.sheets_client.requests.get')
    def test_case_insensitive_search(self, mock_get):
        """Test case-insensitive client name search."""
        csv_content = """Client Name,API Key
Brian Bliss,key1"""

        mock_response = Mock()
        mock_response.text = csv_content
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        workspaces = sheets_client.load_bison_workspaces_from_sheet()

        # Test case insensitive
        matches = [w for w in workspaces if "brian bliss".lower() in w["client_name"].lower()]
        assert len(matches) == 1

    def test_fuzzy_matching_scenarios(self):
        """Test various fuzzy matching scenarios."""
        from rapidfuzz import fuzz

        # Test name variations
        search = "Ryan Bandolik"
        candidates = [
            "Ryan Swan",
            "Ryne Bandolik - Jobsdone",
            "Brian Bliss"
        ]

        scores = [(name, fuzz.WRatio(search, name)) for name in candidates]

        # Ryne Bandolik should have highest score
        best_match = max(scores, key=lambda x: x[1])
        assert "Bandolik" in best_match[0]

    def test_filtering_by_workspace_id(self):
        """Test filtering workspaces by UUID."""
        workspaces = [
            {"workspace_id": "abc-123", "client_name": "Client A"},
            {"workspace_id": "def-456", "client_name": "Client B"}
        ]

        # Filter by workspace ID
        result = [w for w in workspaces if w["workspace_id"] == "abc-123"]
        assert len(result) == 1
        assert result[0]["client_name"] == "Client A"


class TestWorkspaceFieldMapping:
    """Tests for workspace field mapping and display names."""

    @patch('src.leads.sheets_client.requests.get')
    def test_client_name_priority(self, mock_get):
        """Test client name priority (Column D > Column C > Column A)."""
        csv_content = """Workspace ID,API Key,Workspace Name,Client Name
abc-123,key123,Workspace Name,Preferred Name"""

        mock_response = Mock()
        mock_response.text = csv_content
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = sheets_client.load_instantly_workspaces_from_sheet()

        # Should prefer Column D (Client Name) for display
        assert result[0]["client_name"] == "Preferred Name"
        assert result[0]["workspace_name"] == "Workspace Name"

    @patch('src.leads.sheets_client.requests.get')
    def test_fallback_to_workspace_name(self, mock_get):
        """Test fallback when client name is missing."""
        csv_content = """Workspace ID,API Key,Workspace Name,Client Name
abc-123,key123,Fallback Name,"""

        mock_response = Mock()
        mock_response.text = csv_content
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = sheets_client.load_instantly_workspaces_from_sheet()

        # Should fallback to Workspace Name
        assert result[0]["client_name"] == "Fallback Name"

    @patch('src.leads.sheets_client.requests.get')
    def test_fallback_to_workspace_id(self, mock_get):
        """Test fallback to workspace ID when all names are missing."""
        csv_content = """Workspace ID,API Key,Workspace Name,Client Name
abc-123,key123,,"""

        mock_response = Mock()
        mock_response.text = csv_content
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = sheets_client.load_instantly_workspaces_from_sheet()

        # Should fallback to Workspace ID
        assert result[0]["client_name"] == "abc-123"


class TestErrorHandling:
    """Tests for error handling in workspace loading."""

    @patch('src.leads.sheets_client.requests.get')
    def test_handle_network_error(self, mock_get):
        """Test handling network errors."""
        mock_get.side_effect = Exception("Network error")

        with pytest.raises(Exception) as exc_info:
            sheets_client.load_workspaces_from_sheet()

        assert "Network error" in str(exc_info.value)

    @patch('src.leads.sheets_client.requests.get')
    def test_handle_invalid_csv(self, mock_get):
        """Test handling malformed CSV data."""
        mock_response = Mock()
        mock_response.text = "Invalid,CSV\nData"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Should not crash, just return empty or partial results
        result = sheets_client.load_workspaces_from_sheet()
        assert isinstance(result, list)

    @patch('src.leads.sheets_client.requests.get')
    def test_handle_http_error(self, mock_get):
        """Test handling HTTP errors."""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("403 Forbidden")
        mock_get.return_value = mock_response

        with pytest.raises(Exception) as exc_info:
            sheets_client.load_workspaces_from_sheet()

        assert "403" in str(exc_info.value)


class TestMultipleWorkspaces:
    """Tests for handling multiple workspaces."""

    @patch('src.leads.sheets_client.requests.get')
    def test_load_many_workspaces(self, mock_get):
        """Test loading a large number of workspaces."""
        # Generate CSV with 100 workspaces
        csv_lines = ["Workspace ID,API Key,Client Name"]
        for i in range(100):
            csv_lines.append(f"ws-{i},key-{i},Client {i}")

        mock_response = Mock()
        mock_response.text = "\n".join(csv_lines)
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = sheets_client.load_instantly_workspaces_from_sheet()

        # Should load all 100 workspaces
        assert len(result) == 100
        assert result[0]["workspace_id"] == "ws-0"
        assert result[99]["workspace_id"] == "ws-99"

    @patch('src.leads.sheets_client.requests.get')
    def test_duplicate_workspace_ids(self, mock_get):
        """Test handling duplicate workspace IDs."""
        csv_content = """Workspace ID,API Key,Client Name
abc-123,key1,Client A
abc-123,key2,Client B"""

        mock_response = Mock()
        mock_response.text = csv_content
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = sheets_client.load_instantly_workspaces_from_sheet()

        # Should load both (even though IDs are duplicate)
        assert len(result) == 2
        assert result[0]["workspace_id"] == result[1]["workspace_id"]
        assert result[0]["client_name"] != result[1]["client_name"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
