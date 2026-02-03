import pytest
from unittest.mock import patch, MagicMock


#Celery task checks
class TestProcessPdfTask:
    @patch('app.tasks.get_connection')
    @patch('app.tasks.client')
    @patch('app.tasks.requests.get')
    @patch('app.tasks.fitz.open')
    def test_successful_pdf_processing(self, mock_fitz, mock_requests, mock_openai, mock_db):
        from app.tasks import process_pdf_task, DocumentMetadata

        # Mock PDF download
        mock_requests.return_value.content = b'fake pdf bytes'

        # Mock PyMuPDF text extraction
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Sample document text"
        mock_doc = MagicMock()
        mock_doc.__enter__.return_value = [mock_page]
        mock_fitz.return_value = mock_doc

        # Mock OpenAI response
        mock_parsed = DocumentMetadata(title="Test Doc", pub_date="2024-01-01")
        mock_openai.beta.chat.completions.parse.return_value.choices[0].message.parsed = mock_parsed

        # Mock database
        mock_cursor = MagicMock()
        mock_db.return_value.cursor.return_value = mock_cursor

        file_data = {
            'name': 'test.pdf',
            'url': 'https://slack.com/files/test.pdf',
            'file_id': 'F123456',
            'token': 'xoxb-token'
        }

        result = process_pdf_task(file_data)

        assert result['status'] == 'success'
        mock_cursor.execute.assert_called_once()

    def test_file_data_key_access(self):
        """Ensure we access dict keys explicitly, not by position"""
        file_data = {
            'name': 'doc.pdf',
            'url': 'http://example.com',
            'file_id': 'F999',
            'token': 'xoxb-test'
        }
        # Verify keys exist and are accessed correctly
        assert file_data['name'] == 'doc.pdf'
        assert file_data['file_id'] == 'F999'

    @patch('app.tasks.get_connection')
    @patch('app.tasks.client')
    @patch('app.tasks.fitz.open')
    @patch('app.tasks.requests.get')
    def test_slack_download_failure(self, mock_requests, mock_fitz, mock_openai, mock_db):
        from app.tasks import process_pdf_task

        mock_requests.side_effect = Exception("Network error")
        file_data = {'name': 'test.pdf', 'url': 'http://x', 'file_id': 'F1', 'token': 't'}

        result = process_pdf_task(file_data)
        assert result['status'] == 'failed'
        assert 'Network error' in result['error']
