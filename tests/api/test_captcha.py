"""
Unit Tests for CAPTCHA Resolver API

Tests for:
- POST /api/v1/captcha/tasks - Create task
- GET /api/v1/captcha/tasks - List tasks
- GET /api/v1/captcha/tasks/{id} - Get task
- POST /api/v1/captcha/tasks/{id}/assign - Assign task
- POST /api/v1/captcha/tasks/{id}/solve - Submit solution
- POST /api/v1/captcha/tasks/{id}/mark-unsolvable - Mark unsolvable
- GET /api/v1/captcha/sessions/{domain} - Get cached session
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient

# Mark all tests as async
pytestmark = pytest.mark.asyncio


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.publish = AsyncMock(return_value=1)
    redis.keys = AsyncMock(return_value=[])
    return redis


@pytest.fixture
def sample_task_data():
    """Sample data for creating a CAPTCHA task."""
    return {
        "url": "https://example.com/protected-page",
        "challenge_type": "cloudflare",
        "error_message": "Cloudflare challenge detected",
        "request_id": "req-123",
        "priority": 7,
        "proxy_url": "http://proxy:8080",
        "user_agent": "Mozilla/5.0 Chrome/124",
        "metadata": {"source": "titan_worker"},
    }


@pytest.fixture
def sample_solution_data():
    """Sample data for submitting a solution."""
    return {
        "type": "cookie",
        "payload": [
            {
                "name": "cf_clearance",
                "value": "abc123xyz",
                "domain": ".example.com",
                "path": "/",
                "secure": True,
                "http_only": True,
            }
        ],
        "user_agent": "Mozilla/5.0 Chrome/124",
        "notes": "Solved manually via iframe",
    }


# ============================================================================
# Task Creation Tests
# ============================================================================


class TestCreateCaptchaTask:
    """Tests for POST /api/v1/captcha/tasks"""

    async def test_create_task_success(self, client: AsyncClient, mock_redis, sample_task_data):
        """Test successful task creation."""
        response = await client.post("/api/v1/captcha/tasks", json=sample_task_data)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()

        assert data["url"] == sample_task_data["url"]
        assert data["domain"] == "example.com"
        assert data["status"] == "pending"
        assert data["priority"] == sample_task_data["priority"]
        assert "uuid" in data
        assert "id" in data

    async def test_create_task_extracts_domain(self, client: AsyncClient, mock_redis):
        """Test that domain is extracted from URL."""
        response = await client.post(
            "/api/v1/captcha/tasks",
            json={"url": "https://sub.example.org:8080/path?query=1"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["domain"] == "sub.example.org:8080"

    async def test_create_task_default_priority(self, client: AsyncClient, mock_redis):
        """Test that default priority is 5."""
        response = await client.post("/api/v1/captcha/tasks", json={"url": "https://example.com/"})

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["priority"] == 5

    async def test_create_task_updates_existing_pending(self, client: AsyncClient, mock_redis):
        """Test that creating a task for existing pending domain updates it."""
        # Create first task
        response1 = await client.post(
            "/api/v1/captcha/tasks",
            json={"url": "https://example.com/page1", "priority": 3},
        )
        assert response1.status_code == status.HTTP_201_CREATED
        task1 = response1.json()

        # Create second task for same domain with higher priority
        response2 = await client.post(
            "/api/v1/captcha/tasks",
            json={"url": "https://example.com/page2", "priority": 8},
        )
        assert response2.status_code == status.HTTP_201_CREATED
        task2 = response2.json()

        # Should be same task, updated
        assert task1["uuid"] == task2["uuid"]
        assert task2["priority"] == 8  # Updated to higher priority
        assert task2["attempts"] == 1  # Incremented

    async def test_create_task_validates_priority_range(self, client: AsyncClient, mock_redis):
        """Test that priority must be 1-10."""
        response = await client.post(
            "/api/v1/captcha/tasks",
            json={"url": "https://example.com/", "priority": 15},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ============================================================================
# Task Listing Tests
# ============================================================================


class TestListCaptchaTasks:
    """Tests for GET /api/v1/captcha/tasks"""

    async def test_list_tasks_empty(self, client: AsyncClient, mock_redis):
        """Test listing tasks when empty."""
        response = await client.get("/api/v1/captcha/tasks")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["tasks"] == []
        assert data["total"] == 0

    async def test_list_tasks_with_data(self, client: AsyncClient, mock_redis):
        """Test listing tasks with data."""
        # Create some tasks
        for i in range(3):
            await client.post("/api/v1/captcha/tasks", json={"url": f"https://domain{i}.com/"})

        response = await client.get("/api/v1/captcha/tasks")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["tasks"]) == 3
        assert data["total"] == 3

    async def test_list_tasks_filter_by_status(self, client: AsyncClient, mock_redis):
        """Test filtering tasks by status."""
        # Create a task
        await client.post("/api/v1/captcha/tasks", json={"url": "https://example.com/"})

        # Filter for solved (should be empty)
        response = await client.get("/api/v1/captcha/tasks?status=solved")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 0

        # Filter for pending (should have 1)
        response = await client.get("/api/v1/captcha/tasks?status=pending")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 1

    async def test_list_tasks_pagination(self, client: AsyncClient, mock_redis):
        """Test task list pagination."""
        # Create 5 tasks
        for i in range(5):
            await client.post("/api/v1/captcha/tasks", json={"url": f"https://domain{i}.com/"})

        # Get first page
        response = await client.get("/api/v1/captcha/tasks?page=1&limit=2")
        data = response.json()
        assert len(data["tasks"]) == 2
        assert data["total"] == 5
        assert data["has_more"] is True

        # Get second page
        response = await client.get("/api/v1/captcha/tasks?page=2&limit=2")
        data = response.json()
        assert len(data["tasks"]) == 2
        assert data["has_more"] is True

        # Get third page
        response = await client.get("/api/v1/captcha/tasks?page=3&limit=2")
        data = response.json()
        assert len(data["tasks"]) == 1
        assert data["has_more"] is False


# ============================================================================
# Task Assignment Tests
# ============================================================================


class TestAssignCaptchaTask:
    """Tests for POST /api/v1/captcha/tasks/{id}/assign"""

    async def test_assign_task_success(self, client: AsyncClient, mock_redis):
        """Test successful task assignment."""
        # Create task
        create_response = await client.post("/api/v1/captcha/tasks", json={"url": "https://example.com/"})
        task_uuid = create_response.json()["uuid"]

        # Assign task
        response = await client.post(
            f"/api/v1/captcha/tasks/{task_uuid}/assign",
            json={"operator_id": "operator-123"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["task"]["assigned_to"] == "operator-123"
        assert data["task"]["status"] == "in_progress"
        assert "lock_expires_at" in data

    async def test_assign_task_conflict(self, client: AsyncClient, mock_redis):
        """Test assigning already-assigned task returns conflict."""
        # Create and assign task
        create_response = await client.post("/api/v1/captcha/tasks", json={"url": "https://example.com/"})
        task_uuid = create_response.json()["uuid"]

        await client.post(
            f"/api/v1/captcha/tasks/{task_uuid}/assign",
            json={"operator_id": "operator-1"},
        )

        # Try to assign to different operator
        response = await client.post(
            f"/api/v1/captcha/tasks/{task_uuid}/assign",
            json={"operator_id": "operator-2"},
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_assign_task_not_found(self, client: AsyncClient, mock_redis):
        """Test assigning non-existent task."""
        fake_uuid = str(uuid4())
        response = await client.post(
            f"/api/v1/captcha/tasks/{fake_uuid}/assign",
            json={"operator_id": "operator-123"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# Solution Submission Tests
# ============================================================================


class TestSubmitSolution:
    """Tests for POST /api/v1/captcha/tasks/{id}/solve"""

    async def test_submit_solution_success(self, client: AsyncClient, mock_redis, sample_solution_data):
        """Test successful solution submission."""
        # Create task
        create_response = await client.post("/api/v1/captcha/tasks", json={"url": "https://example.com/"})
        task_uuid = create_response.json()["uuid"]

        # Submit solution
        response = await client.post(f"/api/v1/captcha/tasks/{task_uuid}/solve", json=sample_solution_data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["task"]["status"] == "solved"
        assert data["session_cached"] is True

    async def test_submit_solution_extracts_cf_clearance(self, client: AsyncClient, mock_redis):
        """Test that cf_clearance is extracted from cookie payload."""
        create_response = await client.post("/api/v1/captcha/tasks", json={"url": "https://example.com/"})
        task_uuid = create_response.json()["uuid"]

        response = await client.post(
            f"/api/v1/captcha/tasks/{task_uuid}/solve",
            json={
                "type": "cookie",
                "payload": [
                    {
                        "name": "cf_clearance",
                        "value": "secret123",
                        "domain": ".example.com",
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["task"]["cf_clearance"] == "secret123"

    async def test_submit_solution_already_solved(self, client: AsyncClient, mock_redis, sample_solution_data):
        """Test submitting solution to already-solved task."""
        # Create and solve task
        create_response = await client.post("/api/v1/captcha/tasks", json={"url": "https://example.com/"})
        task_uuid = create_response.json()["uuid"]

        await client.post(f"/api/v1/captcha/tasks/{task_uuid}/solve", json=sample_solution_data)

        # Try to solve again
        response = await client.post(f"/api/v1/captcha/tasks/{task_uuid}/solve", json=sample_solution_data)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["message"] == "Task already solved"


# ============================================================================
# Mark Unsolvable Tests
# ============================================================================


class TestMarkUnsolvable:
    """Tests for POST /api/v1/captcha/tasks/{id}/mark-unsolvable"""

    async def test_mark_unsolvable_success(self, client: AsyncClient, mock_redis):
        """Test marking task as unsolvable."""
        create_response = await client.post("/api/v1/captcha/tasks", json={"url": "https://example.com/"})
        task_uuid = create_response.json()["uuid"]

        response = await client.post(
            f"/api/v1/captcha/tasks/{task_uuid}/mark-unsolvable",
            json={"reason": "Turnstile requires specific browser conditions"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["task"]["status"] == "unsolvable"
        assert data["task"]["last_error"] == "Turnstile requires specific browser conditions"


# ============================================================================
# Session Cache Tests
# ============================================================================


class TestCachedSession:
    """Tests for GET /api/v1/captcha/sessions/{domain}"""

    async def test_get_session_no_cache(self, client: AsyncClient, mock_redis):
        """Test getting session when not cached."""
        response = await client.get("/api/v1/captcha/sessions/example.com")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["domain"] == "example.com"
        assert data["has_session"] is False
        assert data["session"] is None

    async def test_get_session_after_solve(self, client: AsyncClient, mock_redis):
        """Test getting session after task is solved."""
        # Create and solve task
        create_response = await client.post("/api/v1/captcha/tasks", json={"url": "https://example.com/page"})
        task_uuid = create_response.json()["uuid"]

        await client.post(
            f"/api/v1/captcha/tasks/{task_uuid}/solve",
            json={
                "type": "cookie",
                "payload": [
                    {
                        "name": "cf_clearance",
                        "value": "cached123",
                        "domain": ".example.com",
                    }
                ],
            },
        )

        # Get cached session
        response = await client.get("/api/v1/captcha/sessions/example.com")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["has_session"] is True
        assert data["session"]["cf_clearance"] == "cached123"


# ============================================================================
# Proxy Render Tests
# ============================================================================


class TestProxyRender:
    """Tests for GET /api/v1/captcha/proxy/render/{task_id}"""

    async def test_proxy_render_not_found(self, client: AsyncClient, mock_redis):
        """Test proxy render with non-existent task."""
        fake_uuid = str(uuid4())
        response = await client.get(f"/api/v1/captcha/proxy/render/{fake_uuid}")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.skip(reason="Requires curl_cffi and network access")
    async def test_proxy_render_success(self, client: AsyncClient, mock_redis):
        """Test successful proxy render."""
        # This test requires actual network access and curl_cffi
        pass


# ============================================================================
# Cleanup Tests
# ============================================================================


class TestCleanup:
    """Tests for DELETE /api/v1/captcha/expired"""

    async def test_cleanup_expired_tasks(self, client: AsyncClient, mock_redis):
        """Test cleanup endpoint."""
        response = await client.delete("/api/v1/captcha/expired")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "expired_count" in data
        assert data["message"] == "Cleanup completed"
