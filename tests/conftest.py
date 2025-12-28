import re
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from faker import Faker
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session
from uuid6 import uuid7

from src.app.core.config import settings
from src.app.core.db.database import async_get_db
from src.app.core.utils.cache import async_get_redis
from src.app.main import app
from src.app.models.captcha import CaptchaStatus

DATABASE_URI = settings.POSTGRES_URI
DATABASE_PREFIX = settings.POSTGRES_SYNC_PREFIX

sync_engine = create_engine(DATABASE_PREFIX + DATABASE_URI)
local_session = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


fake = Faker()


@pytest_asyncio.fixture(scope="session")
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as _client:
        yield _client
    app.dependency_overrides = {}
    sync_engine.dispose()


@pytest.fixture
def db() -> Generator[Session, Any, None]:
    session = local_session()
    yield session
    session.close()


def override_dependency(dependency: Callable[..., Any], mocked_response: Any) -> None:
    app.dependency_overrides[dependency] = lambda: mocked_response


# ============== Helper functions for mock_db to reduce complexity ==============
_MOCK_DB_STATUSES = ["pending", "in_progress", "solving", "solved", "expired", "failed", "unsolvable"]


def _mock_db_filter_by_status(store: list, s: str, s_low: str) -> list | None:
    """Filter store by status from query string."""
    for st in _MOCK_DB_STATUSES:
        if f"'{st}'" in s_low or f'"{st}"' in s:
            return [o for o in store if getattr(getattr(o, "status", None), "value", None) == st]
    return None


def _mock_db_find_by_uuid(store: list, s: str) -> Any | None:
    """Find object by UUID in query string."""
    for obj in store:
        try:
            if str(obj.uuid) in s:
                return obj
        except Exception:
            pass
    return None


def _mock_db_find_by_domain(store: list, s: str) -> Any | None:
    """Find object by domain in query string."""
    for obj in store:
        try:
            if obj.domain:
                clean = s.replace("'", "").replace('"', "").lower()
                if obj.domain.lower() in clean or obj.domain in s:
                    return obj
        except Exception:
            pass
    return None


def _mock_db_apply_pagination(data: list, s_low: str) -> list:
    """Apply limit/offset pagination to data list."""
    limit_match = re.search(r"limit\s+(\d+)", s_low)
    offset_match = re.search(r"offset\s+(\d+)", s_low)
    limit = int(limit_match.group(1)) if limit_match else None
    offset = int(offset_match.group(1)) if offset_match else 0
    if limit is None:
        return data
    return data[offset : offset + limit]


class _FakeResult:
    """Fake SQLAlchemy result object for mock_db."""

    def __init__(self, scalar_one=None, scalar_val=0, scalars_list=None, rowcount=0):
        self._scalar_one = scalar_one
        self._scalar = scalar_val
        self._scalars = scalars_list or []
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._scalar_one

    def scalar(self):
        return self._scalar

    def scalars(self):
        class _S:
            def __init__(self, data):
                self._data = data

            def all(self):
                return list(self._data)

        return _S(self._scalars)


def _mock_db_refresh_obj(obj: Any, store_len: int) -> None:
    """Simulate DB defaults populated during refresh."""
    if not getattr(obj, "id", None):
        obj.id = store_len + 1
    if not getattr(obj, "uuid", None):
        obj.uuid = uuid7()
    if not getattr(obj, "status", None):
        obj.status = CaptchaStatus.PENDING
    obj.attempts = int(getattr(obj, "attempts", 0) or 0)
    if not getattr(obj, "created_at", None):
        obj.created_at = datetime.now(UTC)


@pytest.fixture
def mock_db():
    """In-memory fake AsyncSession for unit tests.

    This fake session records added objects and attempts to respond to
    `execute()` calls used by the captcha endpoints. It supports:
    - select(func.count(...)) -> returns total count
    - select(CaptchaTask) without WHERE -> returns all stored tasks
    - select(CaptchaTask).where(CaptchaTask.uuid == '...') -> returns matching task
    - select(CaptchaTask).where(CaptchaTask.domain == '...') -> returns matching task(s)
    The implementation compiles statements with literal binds using the test
    `sync_engine` dialect to inspect literal values for matching.
    """

    class FakeAsyncSession:
        def __init__(self):
            self.store: list = []

        async def execute(self, stmt):
            # Try to render literal binds to inspect query values
            try:
                compiled = stmt.compile(dialect=sync_engine.dialect, compile_kwargs={"literal_binds": True})
                s = str(compiled)
            except Exception:
                s = str(stmt)

            s_low = s.lower()

            # COUNT query
            if "count(" in s_low:
                filtered = list(self.store)
                status_filtered = _mock_db_filter_by_status(filtered, s, s_low)
                if status_filtered is not None:
                    filtered = status_filtered
                # Domain filter
                domain_match = re.search(r"where .*domain\s*=\s*'([^']+)'", s, flags=re.IGNORECASE)
                if domain_match:
                    dom = domain_match.group(1)
                    filtered = [o for o in filtered if getattr(o, "domain", None) == dom]
                return _FakeResult(scalar_one=None, scalar_val=len(filtered), scalars_list=filtered)

            # Select all tasks (no where)
            if "where" not in s_low and "select" in s_low:
                return _FakeResult(
                    scalar_one=None,
                    scalar_val=len(self.store),
                    scalars_list=_mock_db_apply_pagination(self.store, s_low),
                )

            # Lookup by uuid
            uuid_obj = _mock_db_find_by_uuid(self.store, s)
            if uuid_obj is not None:
                return _FakeResult(scalar_one=uuid_obj, scalar_val=1, scalars_list=[uuid_obj])

            # Status filter: check for status literal in query
            status_filtered = _mock_db_filter_by_status(self.store, s, s_low)
            if status_filtered is not None:
                return _FakeResult(
                    scalar_one=None,
                    scalar_val=len(status_filtered),
                    scalars_list=_mock_db_apply_pagination(status_filtered, s_low),
                )

            # Lookup by domain
            domain_obj = _mock_db_find_by_domain(self.store, s)
            if domain_obj is not None:
                return _FakeResult(scalar_one=domain_obj, scalar_val=1, scalars_list=[domain_obj])

            # Default empty
            return _FakeResult(scalar_one=None, scalar_val=0, scalars_list=[])

        async def commit(self):
            return None

        async def refresh(self, obj):
            # Simulate DB defaults populated during refresh
            _mock_db_refresh_obj(obj, len(self.store))

        def add(self, obj):
            # Record the object in store for later queries
            try:
                # Ensure basic defaults exist so representations work
                if not getattr(obj, "uuid", None):
                    obj.uuid = uuid7()
            except Exception:
                pass
            self.store.append(obj)

    return FakeAsyncSession()


@pytest.fixture
def mock_redis():
    """Mock Redis connection for unit tests."""
    mock_redis = Mock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.setex = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=True)
    mock_redis.publish = AsyncMock(return_value=1)
    mock_redis.keys = AsyncMock(return_value=[])
    return mock_redis


@pytest.fixture(autouse=True)
def override_db_and_redis(mock_db, mock_redis):
    """Automatically override DB and Redis dependencies for tests."""
    app.dependency_overrides[async_get_db] = lambda: mock_db
    app.dependency_overrides[async_get_redis] = lambda: mock_redis
    yield
    app.dependency_overrides.pop(async_get_db, None)
    app.dependency_overrides.pop(async_get_redis, None)


@pytest.fixture
def sample_user_data():
    """Generate sample user data for tests."""
    return {
        "name": fake.name(),
        "username": fake.user_name(),
        "email": fake.email(),
        "password": fake.password(),
    }


@pytest.fixture
def sample_user_read():
    """Generate a sample UserRead object."""
    from uuid6 import uuid7

    from src.app.schemas.user import UserRead

    return UserRead(
        id=1,
        uuid=uuid7(),
        name=fake.name(),
        username=fake.user_name(),
        email=fake.email(),
        profile_image_url=fake.image_url(),
        is_superuser=False,
        created_at=fake.date_time(),
        updated_at=fake.date_time(),
        tier_id=None,
    )


@pytest.fixture
def current_user_dict():
    """Mock current user from auth dependency."""
    return {
        "id": 1,
        "username": fake.user_name(),
        "email": fake.email(),
        "name": fake.name(),
        "is_superuser": False,
    }
