import pytest
import os


@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://test:test@localhost/test')
    monkeypatch.setenv('REDIS_URL', 'redis://localhost:6379/0')
    monkeypatch.setenv('SLACK_BOT_TOKEN', 'xoxb-test-token')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test-key')
