"""
Mocked integration tests for Composio connectors (GitHub, Gmail, Notion).
"""

import os
from unittest.mock import patch, MagicMock
import pytest

from connectors.registry import discover_connectors, get_connector
from connectors.github import GitHubConnector, decode_github_content, extract_metadata
from connectors.gmail import GmailConnector
from connectors.notion import NotionConnector, get_page_title


def test_discover_connectors():
    """Verify all registered connectors are auto-discovered."""
    connectors = discover_connectors()
    names = [c.name for c in connectors]
    assert "GitHub" in names
    assert "Gmail" in names
    assert "Notion" in names


def test_github_connector_interface(tmp_path):
    """Test GitHub connector authentication and health checks with mocks."""
    connector = GitHubConnector()
    assert connector.name == "GitHub"
    assert connector.slug == "github"

    with patch("connectors.github.Composio") as mock_composio_cls:
        mock_c = MagicMock()
        mock_s = MagicMock()
        mock_composio_cls.return_value = mock_c
        mock_c.create.return_value = mock_s

        # Mock active toolkit
        mock_tk = MagicMock()
        mock_tk.slug = "github"
        mock_tk.connection.is_active = True
        mock_toolkits = MagicMock()
        mock_toolkits.items = [mock_tk]
        mock_s.toolkits.return_value = mock_toolkits

        assert connector.authenticate() is True
        is_healthy, msg = connector.health()
        assert is_healthy is True
        assert msg == "Connected"


def test_github_helpers():
    """Test GitHub Base64 decoding and metadata extraction."""
    encoded = "SGVsbG8gTWVtb3J5LU9T"
    decoded = decode_github_content(encoded, "base64")
    assert decoded == "Hello Memory-OS"

    data = {
        "name": "test-repo",
        "description": "Repo desc",
        "language": "Python",
        "stargazers_count": 42,
        "forks_count": 5,
        "open_issues_count": 1,
        "default_branch": "main",
        "updated_at": "2026-08-18T00:00:00Z",
        "html_url": "https://github.com/test/test-repo"
    }
    repo_name, desc, lang, vis, stars, forks, issues, branch, updated, url = extract_metadata(data)
    assert repo_name == "test-repo"
    assert desc == "Repo desc"
    assert lang == "Python"
    assert stars == 42


def test_gmail_connector_interface():
    """Test Gmail connector authentication and health checks with mocks."""
    connector = GmailConnector()
    assert connector.name == "Gmail"
    assert connector.slug == "gmail"

    with patch("connectors.gmail.Composio") as mock_composio_cls:
        mock_c = MagicMock()
        mock_s = MagicMock()
        mock_composio_cls.return_value = mock_c
        mock_c.create.return_value = mock_s

        mock_tk = MagicMock()
        mock_tk.slug = "gmail"
        mock_tk.connection.is_active = True
        mock_toolkits = MagicMock()
        mock_toolkits.items = [mock_tk]
        mock_s.toolkits.return_value = mock_toolkits

        assert connector.authenticate() is True
        is_healthy, msg = connector.health()
        assert is_healthy is True
        assert msg == "Connected"


def test_notion_connector_interface():
    """Test Notion connector authentication and page title extraction."""
    connector = NotionConnector()
    assert connector.name == "Notion"
    assert connector.slug == "notion"

    page_data = {
        "id": "page-123",
        "properties": {
            "title": {
                "title": [{"plain_text": "Architecture Guide"}]
            }
        }
    }
    title = get_page_title(page_data)
    assert title == "Architecture Guide"
