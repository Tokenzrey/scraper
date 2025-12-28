"""
Integration tests for Scraper API endpoints.

These tests verify the API layer behavior with mocked queue.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.app.main import app


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_queue_pool() -> MagicMock:
    """Create mock queue pool."""
    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    return pool


class TestCreateScrapeTask:
    """Tests for POST /api/v1/scrape endpoint."""

    def test_create_task_success(self, client: TestClient, mock_queue_pool: MagicMock) -> None:
        """Test successful task creation."""
        mock_job = MagicMock()
        mock_job.job_id = "test-job-123"
        mock_queue_pool.enqueue_job.return_value = mock_job

        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = mock_queue_pool

            response = client.post(
                "/api/v1/scrape",
                json={"url": "https://example.com"},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["job_id"] == "test-job-123"
        assert data["status"] == "queued"

    def test_create_task_with_strategy(self, client: TestClient, mock_queue_pool: MagicMock) -> None:
        """Test task creation with specific strategy."""
        mock_job = MagicMock()
        mock_job.job_id = "test-job-456"
        mock_queue_pool.enqueue_job.return_value = mock_job

        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = mock_queue_pool

            response = client.post(
                "/api/v1/scrape",
                json={
                    "url": "https://example.com",
                    "strategy": "browser",
                },
            )

        assert response.status_code == 201
        # Verify task_data passed to enqueue includes strategy
        call_args = mock_queue_pool.enqueue_job.call_args
        task_data = call_args[0][1]
        assert task_data["strategy"] == "browser"

    def test_create_task_with_options(self, client: TestClient, mock_queue_pool: MagicMock) -> None:
        """Test task creation with full options."""
        mock_job = MagicMock()
        mock_job.job_id = "test-job-789"
        mock_queue_pool.enqueue_job.return_value = mock_job

        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = mock_queue_pool

            response = client.post(
                "/api/v1/scrape",
                json={
                    "url": "https://example.com/page",
                    "strategy": "auto",
                    "options": {
                        "proxy_url": "http://proxy:8080",
                        "headers": {"X-Custom": "value"},
                        "cookies": {"session": "abc123"},
                        "block_images": True,
                        "wait_selector": "#content",
                        "wait_timeout": 15,
                    },
                },
            )

        assert response.status_code == 201

    def test_create_task_invalid_url(self, client: TestClient) -> None:
        """Test task creation with invalid URL."""
        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = MagicMock()

            response = client.post(
                "/api/v1/scrape",
                json={"url": "not-a-valid-url"},
            )

        assert response.status_code == 422  # Validation error

    def test_create_task_invalid_strategy(self, client: TestClient) -> None:
        """Test task creation with invalid strategy."""
        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = MagicMock()

            response = client.post(
                "/api/v1/scrape",
                json={
                    "url": "https://example.com",
                    "strategy": "invalid",
                },
            )

        assert response.status_code == 422

    def test_create_task_queue_unavailable(self, client: TestClient) -> None:
        """Test task creation when queue is unavailable."""
        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = None

            response = client.post(
                "/api/v1/scrape",
                json={"url": "https://example.com"},
            )

        assert response.status_code == 503
        assert "not available" in response.json()["detail"]

    def test_create_task_enqueue_fails(self, client: TestClient, mock_queue_pool: MagicMock) -> None:
        """Test task creation when enqueue fails."""
        mock_queue_pool.enqueue_job.return_value = None

        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = mock_queue_pool

            response = client.post(
                "/api/v1/scrape",
                json={"url": "https://example.com"},
            )

        assert response.status_code == 500
        assert "Failed to create" in response.json()["detail"]


class TestGetScrapeTask:
    """Tests for GET /api/v1/scrape/{task_id} endpoint."""

    def test_get_task_queued(self, client: TestClient, mock_queue_pool: MagicMock) -> None:
        """Test getting a queued task."""
        mock_job_info = MagicMock()
        mock_job_info.status = "queued"
        mock_job_info.result = None
        mock_job_info.enqueue_time = None
        mock_job_info.start_time = None
        mock_job_info.finish_time = None

        mock_job = MagicMock()
        mock_job.info = AsyncMock(return_value=mock_job_info)

        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = mock_queue_pool
            with patch("src.app.api.v1.scraper.ArqJob", return_value=mock_job):
                response = client.get("/api/v1/scrape/test-job-123")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "test-job-123"
        assert data["status"] == "queued"
        assert data["result"] is None

    def test_get_task_complete_with_result(self, client: TestClient, mock_queue_pool: MagicMock) -> None:
        """Test getting a completed task with result."""
        mock_job_info = MagicMock()
        mock_job_info.status = "complete"
        mock_job_info.result = {
            "status": "success",
            "content": "<html>Test</html>",
            "strategy_used": "request",
            "execution_time_ms": 150,
            "fallback_used": False,
            "url": "https://example.com",
        }
        mock_job_info.enqueue_time = None
        mock_job_info.start_time = None
        mock_job_info.finish_time = None

        mock_job = MagicMock()
        mock_job.info = AsyncMock(return_value=mock_job_info)

        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = mock_queue_pool
            with patch("src.app.api.v1.scraper.ArqJob", return_value=mock_job):
                response = client.get("/api/v1/scrape/test-job-123")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "complete"
        assert data["result"]["status"] == "success"
        assert data["result"]["content"] == "<html>Test</html>"

    def test_get_task_not_found(self, client: TestClient, mock_queue_pool: MagicMock) -> None:
        """Test getting a non-existent task."""
        mock_job = MagicMock()
        mock_job.info = AsyncMock(return_value=None)

        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = mock_queue_pool
            with patch("src.app.api.v1.scraper.ArqJob", return_value=mock_job):
                response = client.get("/api/v1/scrape/nonexistent")

        assert response.status_code == 404


class TestGetScrapeResult:
    """Tests for GET /api/v1/scrape/{task_id}/result endpoint."""

    def test_get_result_success(self, client: TestClient, mock_queue_pool: MagicMock) -> None:
        """Test getting result of completed task."""
        mock_job_info = MagicMock()
        mock_job_info.status = "complete"
        mock_job_info.result = {
            "status": "success",
            "content": "<html>Result</html>",
            "content_type": "text/html",
            "strategy_used": "request",
            "execution_time_ms": 200,
            "http_status_code": 200,
            "error": None,
            "fallback_used": False,
            "url": "https://example.com",
        }

        mock_job = MagicMock()
        mock_job.info = AsyncMock(return_value=mock_job_info)

        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = mock_queue_pool
            with patch("src.app.api.v1.scraper.ArqJob", return_value=mock_job):
                response = client.get("/api/v1/scrape/test-job-123/result")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["content"] == "<html>Result</html>"

    def test_get_result_not_complete(self, client: TestClient, mock_queue_pool: MagicMock) -> None:
        """Test getting result of incomplete task."""
        mock_job_info = MagicMock()
        mock_job_info.status = "in_progress"

        mock_job = MagicMock()
        mock_job.info = AsyncMock(return_value=mock_job_info)

        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = mock_queue_pool
            with patch("src.app.api.v1.scraper.ArqJob", return_value=mock_job):
                response = client.get("/api/v1/scrape/test-job-123/result")

        assert response.status_code == 404
        assert "not complete" in response.json()["detail"]


class TestCancelScrapeTask:
    """Tests for DELETE /api/v1/scrape/{task_id} endpoint."""

    def test_cancel_queued_task(self, client: TestClient, mock_queue_pool: MagicMock) -> None:
        """Test cancelling a queued task."""
        mock_job_info = MagicMock()
        mock_job_info.status = "queued"

        mock_job = MagicMock()
        mock_job.info = AsyncMock(return_value=mock_job_info)
        mock_job.abort = AsyncMock()

        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = mock_queue_pool
            with patch("src.app.api.v1.scraper.ArqJob", return_value=mock_job):
                response = client.delete("/api/v1/scrape/test-job-123")

        assert response.status_code == 204
        mock_job.abort.assert_called_once()

    def test_cancel_in_progress_task_fails(self, client: TestClient, mock_queue_pool: MagicMock) -> None:
        """Test cancelling an in-progress task fails."""
        mock_job_info = MagicMock()
        mock_job_info.status = "in_progress"

        mock_job = MagicMock()
        mock_job.info = AsyncMock(return_value=mock_job_info)

        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = mock_queue_pool
            with patch("src.app.api.v1.scraper.ArqJob", return_value=mock_job):
                response = client.delete("/api/v1/scrape/test-job-123")

        assert response.status_code == 409
        assert "in progress" in response.json()["detail"]

    def test_cancel_complete_task_fails(self, client: TestClient, mock_queue_pool: MagicMock) -> None:
        """Test cancelling a completed task fails."""
        mock_job_info = MagicMock()
        mock_job_info.status = "complete"

        mock_job = MagicMock()
        mock_job.info = AsyncMock(return_value=mock_job_info)

        with patch("src.app.api.v1.scraper.queue") as mock_queue:
            mock_queue.pool = mock_queue_pool
            with patch("src.app.api.v1.scraper.ArqJob", return_value=mock_job):
                response = client.delete("/api/v1/scrape/test-job-123")

        assert response.status_code == 409
        assert "already completed" in response.json()["detail"]
