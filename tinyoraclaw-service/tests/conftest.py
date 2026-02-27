"""Test configuration and shared fixtures for TinyOraClaw service tests.

Uses mock services by default so tests can run without an Oracle database.
Set TINYORACLAW_TEST_LIVE=1 + provide Oracle credentials to run against a real DB.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tinyoraclaw_service.config import TinyoraclawSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**overrides) -> TinyoraclawSettings:
    defaults = {
        "oracle_mode": "freepdb",
        "oracle_user": "test",
        "oracle_password": "test",
        "oracle_host": "localhost",
        "oracle_port": 1521,
        "oracle_service": "FREEPDB1",
        "oracle_pool_min": 1,
        "oracle_pool_max": 2,
        "oracle_onnx_model": "ALL_MINILM_L12_V2",
        "auto_init": False,
    }
    defaults.update(overrides)
    return TinyoraclawSettings(**defaults)


# ---------------------------------------------------------------------------
# Mock pool & connection
# ---------------------------------------------------------------------------

class MockCursor:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    async def execute(self, sql, params=None):
        pass

    async def fetchall(self):
        return self._rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None


class MockConnection:
    def __init__(self):
        self._execute_results = {}

    def cursor(self):
        return MockCursor()

    async def execute(self, sql, params=None):
        return MockCursor()

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockPool:
    def __init__(self):
        self.min = 1
        self.max = 2
        self.busy = 0
        self.opened = 1
        self._conn = MockConnection()

    def acquire(self):
        return self._conn

    async def close(self):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def settings():
    return _make_settings()


@pytest.fixture
def mock_pool():
    return MockPool()


@pytest_asyncio.fixture
async def app_no_db():
    """FastAPI app with pool=None (no database). Services unavailable (503)."""
    from tinyoraclaw_service.main import app

    app.state.settings = _make_settings()
    app.state.pool = None
    yield app


@pytest_asyncio.fixture
async def app_with_mocks():
    """FastAPI app with mock pool."""
    from tinyoraclaw_service.main import app

    app.state.settings = _make_settings()
    app.state.pool = MockPool()
    yield app


@pytest_asyncio.fixture
async def client_no_db(app_no_db):
    """AsyncClient hitting the app with no database."""
    transport = ASGITransport(app=app_no_db)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def client(app_with_mocks):
    """AsyncClient hitting the app with mocked services."""
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
