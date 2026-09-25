"""Async Valkey/Redis client for the API layer (rate limiting + response cache).

Valkey is a Redis-protocol-compatible fork; the `valkey` client library used
here (and already a dependency for the legacy searx app, see
searx/valkeydb.py) talks to either a Valkey server, a plain Redis server, or
AWS ElastiCache (for Redis or for Valkey) without any code change — only
`VALKEY_URL` differs.

When `VALKEY_URL` is unset, `client()` returns None and callers fall back to
an in-process implementation. That fallback is fine for a single local dev
process but silently gives each instance its own counters/cache once you run
more than one — which is exactly the setup this project runs on AWS. Set
VALKEY_URL there.
"""

import logging

import valkey.asyncio as valkey

from api.config import VALKEY_URL

logger = logging.getLogger(__name__)

_client: valkey.Valkey | None = None
_warned_no_valkey = False


def client() -> valkey.Valkey | None:
    """Returns the shared async Valkey client, or None if unconfigured/unreachable.

    Connection is lazy (the valkey client itself only connects on first
    command), so this doesn't block startup - `initialize()` does the actual
    reachability check.
    """
    return _client


async def initialize() -> bool:
    global _client, _warned_no_valkey  # pylint: disable=global-statement

    if not VALKEY_URL:
        if not _warned_no_valkey:
            logger.warning(
                "VALKEY_URL is not set: rate limiting and the search cache are "
                "in-process only. Fine for local dev; NOT safe for more than one "
                "instance (each gets its own counters/cache) - set VALKEY_URL "
                "before running more than one instance in production."
            )
            _warned_no_valkey = True
        _client = None
        return False

    candidate = valkey.Valkey.from_url(VALKEY_URL)
    try:
        await candidate.ping()
    except valkey.exceptions.ValkeyError:
        logger.exception("could not connect to Valkey/Redis at VALKEY_URL; falling back to in-process state")
        _client = None
        return False

    _client = candidate
    logger.info("connected to Valkey/Redis")
    return True
