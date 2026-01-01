"""Google Sheets API client wrapper with error handling and rate limiting."""

import time
import logging
import threading
from typing import List, Dict, Any, Optional
from collections import deque

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials


logger = logging.getLogger(__name__)


class RateLimiter:
    """Thread-safe token bucket rate limiter for Google Sheets API calls."""

    def __init__(self, max_requests_per_minute: int = 300):
        """
        Initialize rate limiter.

        Args:
            max_requests_per_minute: Maximum API requests per minute
        """
        self.max_requests = max_requests_per_minute
        self.window = 60.0  # seconds
        self.requests = deque()
        self.lock = threading.Lock()

    def wait_if_needed(self):
        """Wait if rate limit would be exceeded. Thread-safe."""
        wait_time = 0

        # Check if we need to wait (hold lock only for checking)
        with self.lock:
            now = time.time()

            # Remove requests outside the window
            while self.requests and self.requests[0] < now - self.window:
                self.requests.popleft()

            # Check if we've hit the limit
            if len(self.requests) >= self.max_requests:
                # Calculate wait time
                oldest_request = self.requests[0]
                wait_time = (oldest_request + self.window) - now

        # Sleep OUTSIDE the lock to avoid blocking other threads
        if wait_time > 0:
            logger.warning(
                "Rate limit reached. Waiting %.2f seconds...",
                wait_time
            )
            time.sleep(wait_time)

        # Now record this request (acquire lock again)
        with self.lock:
            # Clean up after waiting
            now = time.time()
            while self.requests and self.requests[0] < now - self.window:
                self.requests.popleft()

            # Record this request
            self.requests.append(time.time())


class SheetsClient:
    """Thread-safe wrapper for Google Sheets API with error handling and rate limiting."""

    def __init__(self, credentials: Credentials, max_requests_per_minute: int = 300):
        """
        Initialize Google Sheets API client.

        Args:
            credentials: OAuth 2.0 credentials
            max_requests_per_minute: Maximum API requests per minute (default: 300)
        """
        self.credentials = credentials
        self.service = build('sheets', 'v4', credentials=credentials)
        self.rate_limiter = RateLimiter(max_requests_per_minute)
        self.service_lock = threading.Lock()

    def _execute_with_retry(self, request, max_retries: int = 3):
        """
        Execute Google Sheets API request with retry logic.

        Args:
            request: Google Sheets API request object
            max_retries: Maximum number of retry attempts

        Returns:
            API response

        Raises:
            HttpError: If request fails after retries
        """
        self.rate_limiter.wait_if_needed()

        for attempt in range(max_retries):
            try:
                return request.execute()
            except HttpError as e:
                if e.resp.status in [403, 429, 500, 503] and attempt < max_retries - 1:
                    # Rate limit or server error - retry with exponential backoff
                    wait_time = (2 ** attempt)
                    logger.warning(
                        "API error %d on attempt %d. Retrying in %d seconds...",
                        e.resp.status, attempt + 1, wait_time
                    )
                    time.sleep(wait_time)
                else:
                    raise

    def create_spreadsheet(self, title: str, sheet_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Create a new Google Spreadsheet.

        Args:
            title: Title of the spreadsheet
            sheet_names: Optional list of sheet names to create (default: single sheet named "Sheet1")

        Returns:
            Spreadsheet object containing spreadsheetId, spreadsheetUrl, and sheet info

        Example:
            sheet = client.create_spreadsheet("My New Spreadsheet", ["Sales", "Marketing"])
            print(f"Created: {sheet['spreadsheetUrl']}")
        """
        logger.info(f"Creating spreadsheet: {title}")

        body = {
            'properties': {
                'title': title
            }
        }

        # Add custom sheet names if provided
        if sheet_names:
            body['sheets'] = [
                {'properties': {'title': name}}
                for name in sheet_names
            ]

        request = self.service.spreadsheets().create(body=body)
        spreadsheet = self._execute_with_retry(request)

        logger.info(f"Created spreadsheet with ID: {spreadsheet['spreadsheetId']}")
        return spreadsheet

    def get_spreadsheet(self, spreadsheet_id: str) -> Dict[str, Any]:
        """
        Get spreadsheet metadata and properties.

        Args:
            spreadsheet_id: The ID of the spreadsheet

        Returns:
            Spreadsheet metadata including sheets, properties, etc.

        Example:
            metadata = client.get_spreadsheet("1abc...")
            print(f"Title: {metadata['properties']['title']}")
        """
        logger.info(f"Getting spreadsheet: {spreadsheet_id}")

        request = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id)
        spreadsheet = self._execute_with_retry(request)

        return spreadsheet

    def read_range(self, spreadsheet_id: str, range_name: str) -> List[List[Any]]:
        """
        Read data from a range in the spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            range_name: A1 notation range (e.g., "Sheet1!A1:D10" or "Sheet1")

        Returns:
            2D list of cell values

        Example:
            values = client.read_range("1abc...", "Sheet1!A1:D10")
            for row in values:
                print(row)
        """
        logger.info(f"Reading range '{range_name}' from spreadsheet: {spreadsheet_id}")

        request = self.service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        )
        result = self._execute_with_retry(request)

        values = result.get('values', [])
        logger.info(f"Read {len(values)} rows")
        return values

    def append_rows(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: List[List[Any]],
        value_input_option: str = 'USER_ENTERED'
    ) -> Dict[str, Any]:
        """
        Append rows to the end of a sheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            range_name: A1 notation range (e.g., "Sheet1!A1")
            values: 2D list of values to append
            value_input_option: How to interpret values:
                - 'RAW': Values stored as-is
                - 'USER_ENTERED': Parse as if user typed (formulas, dates, etc.)

        Returns:
            API response with update details

        Example:
            result = client.append_rows(
                "1abc...",
                "Sheet1",
                [["John", "Doe", 30], ["Jane", "Smith", 25]]
            )
        """
        logger.info(f"Appending {len(values)} rows to '{range_name}' in spreadsheet: {spreadsheet_id}")

        body = {
            'values': values
        }

        request = self.service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption=value_input_option,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully appended {result['updates']['updatedRows']} rows")
        return result

    def update_range(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: List[List[Any]],
        value_input_option: str = 'USER_ENTERED'
    ) -> Dict[str, Any]:
        """
        Update cells in a specific range.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            range_name: A1 notation range (e.g., "Sheet1!A1:C3")
            values: 2D list of values to write
            value_input_option: How to interpret values ('RAW' or 'USER_ENTERED')

        Returns:
            API response with update details

        Example:
            result = client.update_range(
                "1abc...",
                "Sheet1!A1:B2",
                [["Name", "Age"], ["John", 30]]
            )
        """
        logger.info(f"Updating range '{range_name}' in spreadsheet: {spreadsheet_id}")

        body = {
            'values': values
        }

        request = self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption=value_input_option,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully updated {result['updatedCells']} cells")
        return result

    def clear_range(self, spreadsheet_id: str, range_name: str) -> Dict[str, Any]:
        """
        Clear values from a range without deleting the cells.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            range_name: A1 notation range (e.g., "Sheet1!A1:D10")

        Returns:
            API response with cleared range

        Example:
            result = client.clear_range("1abc...", "Sheet1!A1:D10")
        """
        logger.info(f"Clearing range '{range_name}' in spreadsheet: {spreadsheet_id}")

        request = self.service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            body={}
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully cleared range")
        return result

    def find_replace(
        self,
        spreadsheet_id: str,
        find_text: str,
        replace_text: str,
        sheet_id: Optional[int] = None,
        match_case: bool = False
    ) -> Dict[str, Any]:
        """
        Find and replace text in the spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            find_text: Text to find
            replace_text: Text to replace with
            sheet_id: Optional sheet ID to limit search (None = all sheets)
            match_case: Whether to match case

        Returns:
            API response with number of replacements

        Example:
            result = client.find_replace("1abc...", "{{name}}", "John")
            print(f"Replaced {result['replies'][0]['findReplace']['occurrencesChanged']} cells")
        """
        logger.info(f"Finding and replacing '{find_text}' with '{replace_text}' in spreadsheet: {spreadsheet_id}")

        find_replace_request = {
            'find': find_text,
            'replacement': replace_text,
            'matchCase': match_case,
            'allSheets': sheet_id is None
        }

        if sheet_id is not None:
            find_replace_request['sheetId'] = sheet_id

        requests = [{
            'findReplace': find_replace_request
        }]

        body = {'requests': requests}
        request = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully completed find and replace")
        return result

    def delete_rows(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        start_index: int,
        end_index: int
    ) -> Dict[str, Any]:
        """
        Delete rows from a sheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet_id: The ID of the sheet (get from get_spreadsheet)
            start_index: Starting row index (0-based, inclusive)
            end_index: Ending row index (0-based, exclusive)

        Returns:
            API response

        Example:
            # Delete rows 5-10 (0-indexed, so rows 6-11 in the UI)
            result = client.delete_rows("1abc...", sheet_id=0, start_index=5, end_index=10)
        """
        logger.info(f"Deleting rows {start_index}-{end_index} from sheet {sheet_id} in spreadsheet: {spreadsheet_id}")

        requests = [{
            'deleteDimension': {
                'range': {
                    'sheetId': sheet_id,
                    'dimension': 'ROWS',
                    'startIndex': start_index,
                    'endIndex': end_index
                }
            }
        }]

        body = {'requests': requests}
        request = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully deleted rows")
        return result

    def delete_columns(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        start_index: int,
        end_index: int
    ) -> Dict[str, Any]:
        """
        Delete columns from a sheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet_id: The ID of the sheet (get from get_spreadsheet)
            start_index: Starting column index (0-based, inclusive)
            end_index: Ending column index (0-based, exclusive)

        Returns:
            API response

        Example:
            # Delete columns C-E (indices 2-5)
            result = client.delete_columns("1abc...", sheet_id=0, start_index=2, end_index=5)
        """
        logger.info(f"Deleting columns {start_index}-{end_index} from sheet {sheet_id} in spreadsheet: {spreadsheet_id}")

        requests = [{
            'deleteDimension': {
                'range': {
                    'sheetId': sheet_id,
                    'dimension': 'COLUMNS',
                    'startIndex': start_index,
                    'endIndex': end_index
                }
            }
        }]

        body = {'requests': requests}
        request = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully deleted columns")
        return result

    def batch_update(
        self,
        spreadsheet_id: str,
        requests: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Execute multiple update requests in a batch.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            requests: List of request objects

        Returns:
            API response with batch update results

        Example:
            requests = [
                {'updateCells': {...}},
                {'deleteDimension': {...}}
            ]
            result = client.batch_update("1abc...", requests)
        """
        logger.info(f"Executing batch update with {len(requests)} requests on spreadsheet: {spreadsheet_id}")

        body = {'requests': requests}
        request = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully completed batch update")
        return result

    def get_sheet_id(self, spreadsheet_id: str, sheet_name: str) -> Optional[int]:
        """
        Get the sheet ID for a sheet by name.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet_name: Name of the sheet

        Returns:
            Sheet ID (integer) or None if not found

        Example:
            sheet_id = client.get_sheet_id("1abc...", "Sheet1")
        """
        logger.info(f"Getting sheet ID for '{sheet_name}' in spreadsheet: {spreadsheet_id}")

        spreadsheet = self.get_spreadsheet(spreadsheet_id)

        for sheet in spreadsheet.get('sheets', []):
            if sheet['properties']['title'] == sheet_name:
                sheet_id = sheet['properties']['sheetId']
                logger.info(f"Found sheet ID: {sheet_id}")
                return sheet_id

        logger.warning(f"Sheet '{sheet_name}' not found")
        return None

    def get_spreadsheet_url(self, spreadsheet_id: str) -> str:
        """
        Get the Google Sheets URL for a spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet

        Returns:
            Full URL to open the spreadsheet in Google Sheets

        Example:
            url = client.get_spreadsheet_url("1abc...")
            print(f"Open spreadsheet at: {url}")
        """
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"

    def create_sheet(self, spreadsheet_id: str, sheet_name: str) -> Dict[str, Any]:
        """
        Add a new sheet to an existing spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet_name: Name for the new sheet

        Returns:
            API response with new sheet info

        Example:
            result = client.create_sheet("1abc...", "Q1 Sales")
        """
        logger.info(f"Creating sheet '{sheet_name}' in spreadsheet: {spreadsheet_id}")

        requests = [{
            'addSheet': {
                'properties': {
                    'title': sheet_name
                }
            }
        }]

        body = {'requests': requests}
        request = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully created sheet")
        return result

    def delete_sheet(self, spreadsheet_id: str, sheet_id: int) -> Dict[str, Any]:
        """
        Delete a sheet from a spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet_id: The ID of the sheet to delete

        Returns:
            API response

        Example:
            result = client.delete_sheet("1abc...", sheet_id=123456)
        """
        logger.info(f"Deleting sheet {sheet_id} from spreadsheet: {spreadsheet_id}")

        requests = [{
            'deleteSheet': {
                'sheetId': sheet_id
            }
        }]

        body = {'requests': requests}
        request = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully deleted sheet")
        return result

    def list_sheets(self, spreadsheet_id: str) -> List[Dict[str, Any]]:
        """
        List all sheets/tabs in a spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet

        Returns:
            List of sheet info dicts with sheetId, title, index, etc.

        Example:
            sheets = client.list_sheets("1abc...")
            for sheet in sheets:
                print(f"{sheet['title']} (ID: {sheet['sheetId']})")
        """
        logger.info(f"Listing sheets in spreadsheet: {spreadsheet_id}")

        spreadsheet = self.get_spreadsheet(spreadsheet_id)

        sheets_info = []
        for sheet in spreadsheet.get('sheets', []):
            props = sheet['properties']
            sheets_info.append({
                'sheetId': props['sheetId'],
                'title': props['title'],
                'index': props['index'],
                'sheetType': props.get('sheetType', 'GRID'),
                'gridProperties': props.get('gridProperties', {})
            })

        logger.info(f"Found {len(sheets_info)} sheets")
        return sheets_info

    def rename_sheet(self, spreadsheet_id: str, sheet_id: int, new_name: str) -> Dict[str, Any]:
        """
        Rename a sheet/tab.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet_id: The ID of the sheet to rename
            new_name: New name for the sheet

        Returns:
            API response

        Example:
            result = client.rename_sheet("1abc...", sheet_id=0, new_name="Q1 Sales")
        """
        logger.info(f"Renaming sheet {sheet_id} to '{new_name}' in spreadsheet: {spreadsheet_id}")

        requests = [{
            'updateSheetProperties': {
                'properties': {
                    'sheetId': sheet_id,
                    'title': new_name
                },
                'fields': 'title'
            }
        }]

        body = {'requests': requests}
        request = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully renamed sheet")
        return result

    def insert_rows(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        start_index: int,
        num_rows: int
    ) -> Dict[str, Any]:
        """
        Insert blank rows at a specific position.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet_id: The ID of the sheet
            start_index: Row index where to insert (0-based)
            num_rows: Number of rows to insert

        Returns:
            API response

        Example:
            # Insert 5 blank rows starting at row 10 (0-indexed, so row 11 in UI)
            result = client.insert_rows("1abc...", sheet_id=0, start_index=10, num_rows=5)
        """
        logger.info(f"Inserting {num_rows} rows at index {start_index} in sheet {sheet_id}")

        requests = [{
            'insertDimension': {
                'range': {
                    'sheetId': sheet_id,
                    'dimension': 'ROWS',
                    'startIndex': start_index,
                    'endIndex': start_index + num_rows
                },
                'inheritFromBefore': False
            }
        }]

        body = {'requests': requests}
        request = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully inserted {num_rows} rows")
        return result

    def insert_columns(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        start_index: int,
        num_columns: int
    ) -> Dict[str, Any]:
        """
        Insert blank columns at a specific position.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet_id: The ID of the sheet
            start_index: Column index where to insert (0-based, A=0, B=1, etc.)
            num_columns: Number of columns to insert

        Returns:
            API response

        Example:
            # Insert 3 blank columns starting at column C (index 2)
            result = client.insert_columns("1abc...", sheet_id=0, start_index=2, num_columns=3)
        """
        logger.info(f"Inserting {num_columns} columns at index {start_index} in sheet {sheet_id}")

        requests = [{
            'insertDimension': {
                'range': {
                    'sheetId': sheet_id,
                    'dimension': 'COLUMNS',
                    'startIndex': start_index,
                    'endIndex': start_index + num_columns
                },
                'inheritFromBefore': False
            }
        }]

        body = {'requests': requests}
        request = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully inserted {num_columns} columns")
        return result

    def format_cells(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_col: int,
        end_col: int,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        font_size: Optional[int] = None,
        background_color: Optional[Dict[str, float]] = None,
        text_color: Optional[Dict[str, float]] = None,
        horizontal_alignment: Optional[str] = None,
        vertical_alignment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Format cells with styling (bold, colors, alignment, etc.).

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet_id: The ID of the sheet
            start_row: Start row index (0-based)
            end_row: End row index (0-based, exclusive)
            start_col: Start column index (0-based)
            end_col: End column index (0-based, exclusive)
            bold: Make text bold
            italic: Make text italic
            font_size: Font size in points
            background_color: Cell background color as RGB dict (e.g., {'red': 1.0, 'green': 0.0, 'blue': 0.0})
            text_color: Text color as RGB dict
            horizontal_alignment: 'LEFT', 'CENTER', 'RIGHT'
            vertical_alignment: 'TOP', 'MIDDLE', 'BOTTOM'

        Returns:
            API response

        Example:
            # Format header row (row 1) as bold, centered, with light blue background
            result = client.format_cells(
                "1abc...",
                sheet_id=0,
                start_row=0,
                end_row=1,
                start_col=0,
                end_col=5,
                bold=True,
                horizontal_alignment='CENTER',
                background_color={'red': 0.85, 'green': 0.92, 'blue': 1.0}
            )
        """
        logger.info(f"Formatting cells in sheet {sheet_id}")

        cell_format = {}
        text_format = {}
        fields = []

        # Build text format
        if bold is not None:
            text_format['bold'] = bold
            fields.append('textFormat.bold')
        if italic is not None:
            text_format['italic'] = italic
            fields.append('textFormat.italic')
        if font_size is not None:
            text_format['fontSize'] = font_size
            fields.append('textFormat.fontSize')
        if text_color is not None:
            text_format['foregroundColor'] = {'red': text_color.get('red', 0), 'green': text_color.get('green', 0), 'blue': text_color.get('blue', 0)}
            fields.append('textFormat.foregroundColor')

        if text_format:
            cell_format['textFormat'] = text_format

        # Build cell format
        if background_color is not None:
            cell_format['backgroundColor'] = {'red': background_color.get('red', 0), 'green': background_color.get('green', 0), 'blue': background_color.get('blue', 0)}
            fields.append('backgroundColor')

        if horizontal_alignment is not None:
            cell_format['horizontalAlignment'] = horizontal_alignment
            fields.append('horizontalAlignment')

        if vertical_alignment is not None:
            cell_format['verticalAlignment'] = vertical_alignment
            fields.append('verticalAlignment')

        requests = [{
            'repeatCell': {
                'range': {
                    'sheetId': sheet_id,
                    'startRowIndex': start_row,
                    'endRowIndex': end_row,
                    'startColumnIndex': start_col,
                    'endColumnIndex': end_col
                },
                'cell': {
                    'userEnteredFormat': cell_format
                },
                'fields': ','.join(fields)
            }
        }]

        body = {'requests': requests}
        request = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully formatted cells")
        return result

    def sort_range(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_col: int,
        end_col: int,
        sort_column: int,
        ascending: bool = True
    ) -> Dict[str, Any]:
        """
        Sort a range of data by a specific column.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet_id: The ID of the sheet
            start_row: Start row index (0-based)
            end_row: End row index (0-based, exclusive)
            start_col: Start column index (0-based)
            end_col: End column index (0-based, exclusive)
            sort_column: Column index to sort by (0-based, relative to start_col)
            ascending: Sort ascending (True) or descending (False)

        Returns:
            API response

        Example:
            # Sort rows 2-100 by column B (index 1), descending
            result = client.sort_range(
                "1abc...",
                sheet_id=0,
                start_row=1,  # Skip header row
                end_row=100,
                start_col=0,
                end_col=5,
                sort_column=1,  # Column B
                ascending=False
            )
        """
        logger.info(f"Sorting range in sheet {sheet_id} by column {sort_column}")

        requests = [{
            'sortRange': {
                'range': {
                    'sheetId': sheet_id,
                    'startRowIndex': start_row,
                    'endRowIndex': end_row,
                    'startColumnIndex': start_col,
                    'endColumnIndex': end_col
                },
                'sortSpecs': [{
                    'dimensionIndex': start_col + sort_column,
                    'sortOrder': 'ASCENDING' if ascending else 'DESCENDING'
                }]
            }
        }]

        body = {'requests': requests}
        request = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully sorted range")
        return result

    def freeze_rows_columns(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        frozen_row_count: int = 0,
        frozen_column_count: int = 0
    ) -> Dict[str, Any]:
        """
        Freeze rows and/or columns to keep them visible while scrolling.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet_id: The ID of the sheet
            frozen_row_count: Number of rows to freeze from top (default: 0)
            frozen_column_count: Number of columns to freeze from left (default: 0)

        Returns:
            API response

        Example:
            # Freeze top row (header) and first column
            result = client.freeze_rows_columns("1abc...", sheet_id=0, frozen_row_count=1, frozen_column_count=1)
        """
        logger.info(f"Freezing {frozen_row_count} rows and {frozen_column_count} columns in sheet {sheet_id}")

        requests = [{
            'updateSheetProperties': {
                'properties': {
                    'sheetId': sheet_id,
                    'gridProperties': {
                        'frozenRowCount': frozen_row_count,
                        'frozenColumnCount': frozen_column_count
                    }
                },
                'fields': 'gridProperties.frozenRowCount,gridProperties.frozenColumnCount'
            }
        }]

        body = {'requests': requests}
        request = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully froze rows and columns")
        return result

    def auto_resize_columns(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        start_col: int,
        end_col: int
    ) -> Dict[str, Any]:
        """
        Auto-resize columns to fit content.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet_id: The ID of the sheet
            start_col: Start column index (0-based)
            end_col: End column index (0-based, exclusive)

        Returns:
            API response

        Example:
            # Auto-resize columns A-E (indices 0-5)
            result = client.auto_resize_columns("1abc...", sheet_id=0, start_col=0, end_col=5)
        """
        logger.info(f"Auto-resizing columns {start_col}-{end_col} in sheet {sheet_id}")

        requests = [{
            'autoResizeDimensions': {
                'dimensions': {
                    'sheetId': sheet_id,
                    'dimension': 'COLUMNS',
                    'startIndex': start_col,
                    'endIndex': end_col
                }
            }
        }]

        body = {'requests': requests}
        request = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        )

        result = self._execute_with_retry(request)
        logger.info(f"Successfully auto-resized columns")
        return result
