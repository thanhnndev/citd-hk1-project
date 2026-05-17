"""Rate limiter middleware placeholder.

Reserved for future slowapi integration.  Will provide per-IP and
per-user rate limits once the Redis connection pool is established in
S04.

Planned features:
- Per-IP rate limit (e.g. 100 req/min for anonymous requests).
- Per-user rate limit (higher quotas for authenticated users).
- Redis-backed counters for distributed rate limiting.
"""

# TODO: Integrate slowapi.Limiter with Redis backend once
# app/core/database.py provides the Redis connection pool.
#
# Example (future):
#   from slowapi import Limiter
#   from slowapi.util import get_remote_address
#   limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
