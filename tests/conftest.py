from collections.abc import Callable, Generator
import re
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from faker import Faker
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session

from src.app.core.config import settings
from src.app.main import app
from src.app.core.db.database import async_get_db
from src.app.core.utils.cache import async_get_redis
from uuid6 import uuid7
from datetime import datetime, timezone
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


@pytest.fixture
def mock_db():  # noqa: C901  # noqa: C901
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

    class FakeResult:
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

            # Determine pagination if present
            limit_match = re.search(r"limit\s+(\d+)", s_low)
            offset_match = re.search(r"offset\s+(\d+)", s_low)
            limit = int(limit_match.group(1)) if limit_match else None
            offset = int(offset_match.group(1)) if offset_match else 0

            # Helper to apply limit/offset to a list
            def _page(data):
                if limit is None:
                    return data
                return data[offset : offset + limit]

            # COUNT query
            if "count(" in s_low:
                # If there's a WHERE with status or domain, compute filtered count
                filtered = list(self.store)
                # Status filter
                statuses = ["pending", "in_progress", "solving", "solved", "expired", "failed", "unsolvable"]
                for st in statuses:
                    if f"'{st}'" in s_low or f'"{st}"' in s:
                        filtered = [o for o in self.store if getattr(getattr(o, 'status', None), 'value', None) == st]
                        break
                # Domain filter
                domain_match = re.search(r"where .*domain\s*=\s*'([^']+)'", s, flags=re.IGNORECASE)
                if domain_match:
                    dom = domain_match.group(1)
                    filtered = [o for o in filtered if getattr(o, 'domain', None) == dom]
                return FakeResult(scalar_one=None, scalar_val=len(filtered), scalars_list=filtered)

            # Select all tasks (no where)
            if "where" not in s_low and "select" in s_low:
                return FakeResult(scalar_one=None, scalar_val=len(self.store), scalars_list=_page(self.store))

            # Lookup by uuid
            for obj in self.store:
                try:
                    if str(obj.uuid) in s:
                        return FakeResult(scalar_one=obj, scalar_val=1, scalars_list=[obj])
                except Exception:
                    pass

            # Status filter: check for status literal in query
            statuses = ["pending", "in_progress", "solving", "solved", "expired", "failed", "unsolvable"]
            for st in statuses:
                if f"'{st}'" in s_low or f'"{st}"' in s:
                    filtered = [o for o in self.store if getattr(getattr(o, 'status', None), 'value', None) == st]
                    return FakeResult(scalar_one=None, scalar_val=len(filtered), scalars_list=_page(filtered))

            # Lookup by domain
            for obj in self.store:
                try:
                    if obj.domain:
                        # Match domain in various SQL renderings (with or without quotes)
                        clean = s.replace("'", "").replace('"', "").lower()
                        if obj.domain.lower() in clean or obj.domain in s:
                            return FakeResult(scalar_one=obj, scalar_val=1, scalars_list=[obj])
                except Exception:
                    pass

            # Default empty
            return FakeResult(scalar_one=None, scalar_val=0, scalars_list=[])

        async def commit(self):
            return None

        async def refresh(self, obj):
            # Simulate DB defaults populated during refresh
            try:
                if not getattr(obj, "id", None):
                    obj.id = len(self.store) + 1
            except Exception:
                pass
            try:
                if not getattr(obj, "uuid", None):
                    obj.uuid = uuid7()
            except Exception:
                pass
            try:
                if not getattr(obj, "status", None):
                    obj.status = CaptchaStatus.PENDING
            except Exception:
                pass
            try:
                obj.attempts = int(getattr(obj, "attempts", 0) or 0)
            except Exception:
                obj.attempts = 0
            try:
                if not getattr(obj, "created_at", None):
                    obj.created_at = datetime.now(timezone.utc)
            except Exception:
                pass

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
