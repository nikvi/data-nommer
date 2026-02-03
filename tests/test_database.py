import pytest
from unittest.mock import patch, MagicMock

class TestDatabase:
    @patch('app.database.psycopg2.connect')
    def test_get_connection(self, mock_connect):
        from app.database import get_connection

        get_connection()
        mock_connect.assert_called_once()

    @patch('app.database.get_connection')
    def test_init_db_creates_table(self, mock_conn):
        from app.database import init_db

        mock_cursor = MagicMock()
        mock_conn.return_value.cursor.return_value = mock_cursor

        init_db()

        # Verify CREATE TABLE was called
        call_args = mock_cursor.execute.call_args[0][0]
        assert 'CREATE TABLE IF NOT EXISTS pdf_content' in call_args
        mock_conn.return_value.commit.assert_called_once()
