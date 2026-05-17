"""Health check endpoints for liveness and readiness probes.

GET /health     — liveness: is the process running?
GET /health/ready — readiness: can we talk to PostgreSQL, Redis, and Qdrant?

Used by compose.yaml healthcheck and orchestrator readiness gates.
"""

import asyncio
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import asyncpg
import redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter()
log = get_logger()

# Thread pool for blocking sync checks (Redis ping, Qdrant HTTP).
_executor = ThreadPoolExecutor(max_workers=2)


def _parse_asyncpg_dsn(dsn: str) -> dict[str, Any]:
    """Extract asyncpg connection params from a SQLAlchemy-style DSN.

    get_settings().postgres_dsn returns 'postgresql+asyncpg://user:pass@host:port/db'.
    asyncpg.connect() wants 'postgresql://user:pass@host:port/db' or individual kwargs.
    """
    clean = dsn.replace("postgresql+asyncpg://", "postgresql://")
    parts = clean.replace("postgresql://", "", 1)
    # Split off the database name
    host_port_db = parts
    if "@" in host_port_db:
        _, host_port_db = host_port_db.split("@", 1)
    host_port, db = host_port_db.rsplit("/", 1)
    host, port = host_port.rsplit(":", 1)
    return {"host": host, "port": int(port), "database": db}


async def _check_postgres(settings: Any) -> str:
    """Verify PostgreSQL connectivity via asyncpg SELECT 1."""
    try:
        params = _parse_asyncpg_dsn(settings.postgres_dsn)
        conn = await asyncpg.connect(
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            **params,
        )
        try:
            await conn.execute("SELECT 1")
        finally:
            await conn.close()
        return "ok"
    except Exception as exc:
        log.warning("postgres.health.check.failed", error=str(exc))
        return str(exc)


def _check_redis_sync(redis_url: str) -> str:
    """Verify Redis connectivity via blocking ping (runs in executor)."""
    try:
        client = redis.Redis.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3)
        client.ping()
        client.close()
        return "ok"
    except Exception as exc:
        log.warning("redis.health.check.failed", error=str(exc))
        return str(exc)


def _check_qdrant_sync(qdrant_url: str) -> str:
    """Verify Qdrant connectivity via HTTP GET /collections (runs in executor)."""
    try:
        url = f"{qdrant_url}/collections"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                return "ok"
            return f"unexpected status {resp.status}"
    except Exception as exc:
        log.warning("qdrant.health.check.failed", error=str(exc))
        return str(exc)


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — returns 200 if the process is running."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness() -> JSONResponse:
    """Readiness probe — verifies connectivity to all infrastructure services.

    Returns 200 when all services are reachable, 503 when any are down.
    Checks run concurrently with a 5-second overall timeout.
    """
    settings = get_settings()

    async def _postgres_task() -> tuple[str, str]:
        return "postgres", await _check_postgres(settings)

    def _redis_task() -> tuple[str, str]:
        return "redis", _check_redis_sync(settings.redis_url)

    def _qdrant_task() -> tuple[str, str]:
        return "qdrant", _check_qdrant_sync(settings.qdrant_url)

    # Run all checks concurrently: one native async, two in thread pool.
    loop = asyncio.get_running_loop()
    tasks = [
        _postgres_task(),
        loop.run_in_executor(_executor, _redis_task),
        loop.run_in_executor(_executor, _qdrant_task),
    ]

    try:
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
    except asyncio.TimeoutError:
        log.error("health.check.timeout", overall_timeout=5)
        services = {"postgres": "timeout", "redis": "timeout", "qdrant": "timeout"}
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "services": services},
        )

    services: dict[str, str] = dict(results)
    all_ok = all(v == "ok" for v in services.values())

    log.info(
        "health.check.complete",
        status="ready" if all_ok else "degraded",
        services=services,
    )

    if all_ok:
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "services": services},
        )
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", "services": services},
    )
