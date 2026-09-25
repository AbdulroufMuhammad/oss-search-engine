"""Per-API-key rate limiting: fixed 60-second window, Valkey/Redis-backed
when available (correct across multiple instances), falling back to an
in-process counter otherwise (fine for one instance, e.g. local dev).

Behavior either way: each key gets `limit_per_minute` requests per rolling
60-second clock window. Going over returns a `retry_after` of at most 60
seconds until the window resets - there's no penalty, lockout, or backoff
for having been rate limited; the very next window starts at full quota.
"""

import logging
import time
from collections import defaultdict

import valkey.exceptions

from api import valkeydb

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60

# In-process fallback, used only when Valkey isn't configured/reachable.
_windows: dict[str, dict[int, int]] = defaultdict(dict)


async def check_and_increment(key_id: str, limit_per_minute: int) -> tuple[bool, int]:
    """Records one request against `key_id`'s current window.

    Returns (allowed, retry_after_seconds). retry_after_seconds is 0 when
    allowed is True.
    """
    valkey_client = valkeydb.client()
    if valkey_client is None:
        return _check_and_increment_local(key_id, limit_per_minute)

    try:
        return await _check_and_increment_valkey(valkey_client, key_id, limit_per_minute)
    except valkey.exceptions.ValkeyError:
        # Valkey/Redis had a blip: fail open rather than blocking every
        # request in the deployment because the rate limiter's backing
        # store hiccuped. Rate limiting is a soft protection, not a
        # security boundary.
        logger.warning("valkey error during rate limit check; allowing request", exc_info=True)
        return True, 0


async def _check_and_increment_valkey(valkey_client, key_id: str, limit_per_minute: int) -> tuple[bool, int]:
    window = int(time.time() // _WINDOW_SECONDS)
    redis_key = f"ratelimit:{key_id}:{window}"

    count = await valkey_client.incr(redis_key)
    if count == 1:
        # Only the request that created this window's counter sets its
        # TTL. A crash between INCR and EXPIRE would leave that one
        # window's key without a TTL - self-healing, since the next
        # window uses a fresh key with its own counter.
        await valkey_client.expire(redis_key, _WINDOW_SECONDS)

    if count > limit_per_minute:
        ttl = await valkey_client.ttl(redis_key)
        retry_after = ttl if ttl and ttl > 0 else _WINDOW_SECONDS
        return False, retry_after

    return True, 0


def _check_and_increment_local(key_id: str, limit_per_minute: int) -> tuple[bool, int]:
    now = time.time()
    window = int(now // _WINDOW_SECONDS)

    windows = _windows[key_id]
    for stale_window in [w for w in windows if w != window]:
        del windows[stale_window]

    count = windows.get(window, 0)
    if count >= limit_per_minute:
        retry_after = int((window + 1) * _WINDOW_SECONDS - now) + 1
        return False, retry_after

    windows[window] = count + 1
    return True, 0
