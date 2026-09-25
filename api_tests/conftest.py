import os
import tempfile

# Must run before any `api.*` module is imported anywhere in the test
# session, since api/config.py reads these from the environment at import
# time. conftest.py is loaded before test collection, so this is safe.
_tmp_dir = tempfile.mkdtemp(prefix="seekly_test_db_")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_tmp_dir}/seekly_test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production-use-0000000000")

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest_asyncio.fixture
async def client():
    from api.app import app

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
