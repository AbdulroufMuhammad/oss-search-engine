import os
import tempfile

# Must run before any `api.*` module is imported anywhere in the test
# session, since api/config.py reads these from the environment at import
# time. conftest.py is loaded before test collection, so this is safe.
_tmp_dir = tempfile.mkdtemp(prefix="seekly_test_db_")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_tmp_dir}/seekly_test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production-use-0000000000")

import functools
import http.server
import pathlib
import socket
import threading

import pytest
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest_asyncio.fixture
async def client():
    from api.app import app

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.fixture(scope="session")
def crawl_fixture_url():
    """Serves api_tests/fixtures/crawl_site/ over plain HTTP on 127.0.0.1
    for crawler tests - a real fetch against a real (if tiny, local) site,
    not a mocked transport, since the crawl engine's own HTTP stack
    (Scrapling/curl_cffi) doesn't support httpx's MockTransport."""
    directory = pathlib.Path(__file__).parent / "fixtures" / "crawl_site"
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Wait until it actually accepts connections before handing back the URL.
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            pass
    else:
        server.shutdown()
        pytest.skip("crawl fixture server did not start in time")

    yield f"http://127.0.0.1:{port}"

    server.shutdown()
    thread.join(timeout=5)
