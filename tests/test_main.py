import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Tests for  FastAPI endpoints

@pytest.fixture
def client():
    with patch('app.main.init_db'):
        from app.main import app
        with TestClient(app) as test_client:
            yield test_client


class TestHealthEndpoint:
    @patch('app.main.redis_client')
    @patch('app.main.get_connection')
    def test_health_returns_healthy(self, mock_db, mock_redis, client):
        mock_redis.ping.return_value = True
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()['status'] == 'healthy'

    @patch('app.main.get_connection')
    def test_health_db_failure(self, mock_db, client):
        mock_db.side_effect = Exception("DB down")
        response = client.get("/health")
        assert response.status_code == 503


class TestSyncEndpoint:
    @patch('app.main.process_pdf_task')
    @patch('app.main.slack_client')
    @patch('app.main.get_connection')
    def test_sync_queues_pdfs(self, mock_db, mock_slack, mock_task, client):
        # Mock DB returns no previous timestamp
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = [None]
        mock_db.return_value.cursor.return_value = mock_cursor

        # Mock Slack returns 2 PDF files
        mock_slack.conversations_history.return_value = {
            'messages': [{
                'files': [
                    {'filetype': 'pdf', 'name': 'a.pdf', 'url_private_download': 'http://a', 'id': 'F1'},
                    {'filetype': 'pdf', 'name': 'b.pdf', 'url_private_download': 'http://b', 'id': 'F2'},
                ]
            }]
        }

        response = client.post("/sync/C123")

        assert response.json()['files_queued'] == 2
        assert mock_task.delay.call_count == 2

    @patch('app.main.process_pdf_task')
    @patch('app.main.slack_client')
    @patch('app.main.get_connection')
    def test_sync_ignores_non_pdf(self, mock_db, mock_slack, mock_task, client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = [None]
        mock_db.return_value.cursor.return_value = mock_cursor

        mock_slack.conversations_history.return_value = {
            'messages': [{'files': [{'filetype': 'png', 'name': 'img.png'}]}]
        }

        response = client.post("/sync/C123")
        assert response.json()['files_queued'] == 0


class TestDocumentsEndpoint:
    @patch('app.main.get_connection')
    def test_documents_returns_all(self, mock_db, client):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ('Title 1', '2024-01-01', 'doc1.pdf'),
            ('Title 2', '2024-02-01', 'doc2.pdf'),
        ]
        mock_db.return_value.cursor.return_value = mock_cursor

        response = client.get("/documents")

        assert len(response.json()) == 2
        assert response.json()[0]['title'] == 'Title 1'

    @patch('app.main.get_connection')
    def test_documents_with_query_filter(self, mock_db, client):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [('Report', '2024-01-01', 'report.pdf')]
        mock_db.return_value.cursor.return_value = mock_cursor

        response = client.get("/documents?query=Report")

        # Verify ILIKE query was used
        call_args = mock_cursor.execute.call_args
        assert 'ILIKE' in call_args[0][0]
