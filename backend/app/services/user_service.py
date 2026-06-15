"""User service — registration, authentication, and lookup.

Uses asyncpg directly (matching the project's existing pattern in
the agent runtime) to avoid adding SQLAlchemy as a dependency.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import asyncpg
import bcrypt
import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data class (lightweight, no ORM)
# ---------------------------------------------------------------------------

class UserRecord:
    """In-memory representation of a user row."""

    __slots__ = (
        "id", "username", "email", "hashed_password",
        "is_active", "is_verified", "is_admin", "created_at",
    )

    def __init__(
        self,
        *,
        id: str,
        username: str,
        email: str,
        hashed_password: str,
        is_active: bool = True,
        is_verified: bool = False,
        is_admin: bool = False,
        created_at: datetime | None = None,
    ) -> None:
        self.id = id
        self.username = username
        self.email = email
        self.hashed_password = hashed_password
        self.is_active = is_active
        self.is_verified = is_verified
        self.is_admin = is_admin
        self.created_at = created_at or datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Hash a plain-text password with bcrypt."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# UserService
# ---------------------------------------------------------------------------

class UserService:
    """Async user CRUD backed by PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(cls, dsn: str | None = None) -> "UserService":
        """Factory: create pool, run migrations, return service instance."""
        dsn = dsn or os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL is required for UserService")
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
        service = cls(pool)
        await service._ensure_table()
        return service

    async def _ensure_table(self) -> None:
        """Create the users table if it doesn't exist."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    hashed_password VARCHAR(255) NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE
            """)

    @staticmethod
    def _from_row(row: asyncpg.Record) -> UserRecord:
        """Convert an asyncpg user row into a UserRecord."""
        return UserRecord(
            id=str(row["id"]),
            username=row["username"],
            email=row["email"],
            hashed_password=row["hashed_password"],
            is_active=row["is_active"],
            is_verified=row["is_verified"],
            is_admin=row["is_admin"],
            created_at=row["created_at"],
        )

    async def register(self, username: str, email: str, password: str) -> UserRecord:
        """Register a new user.

        Raises:
            ValueError: If username or email already exists.
        """
        user_id = str(uuid.uuid4())
        hashed = hash_password(password)

        async with self._pool.acquire() as conn:
            # Check existing
            existing = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1 OR username = $2",
                email.lower(),
                username,
            )
            if existing:
                raise ValueError("Username or email already registered.")

            await conn.execute(
                """
                INSERT INTO users (id, username, email, hashed_password, is_active, is_verified)
                VALUES ($1, $2, $3, $4, TRUE, FALSE)
                """,
                user_id,
                username,
                email.lower(),
                hashed,
            )

        logger.info("user.registered", user_id=user_id, username=username)
        return UserRecord(
            id=user_id,
            username=username,
            email=email.lower(),
            hashed_password=hashed,
        )

    async def seed_user(
        self,
        *,
        username: str,
        email: str,
        password: str,
        is_admin: bool,
    ) -> UserRecord:
        """Create or update a verified development account.

        Re-running the seed updates the password and account flags without
        creating duplicate users.
        """
        normalized_email = email.lower()
        hashed = hash_password(password)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                by_email = await conn.fetchrow(
                    "SELECT id FROM users WHERE email = $1",
                    normalized_email,
                )
                by_username = await conn.fetchrow(
                    "SELECT id FROM users WHERE username = $1",
                    username,
                )

                if (
                    by_email is not None
                    and by_username is not None
                    and by_email["id"] != by_username["id"]
                ):
                    raise ValueError(
                        "Seed email and username belong to different existing users."
                    )

                existing = by_email or by_username
                if existing is None:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO users (
                            id, username, email, hashed_password,
                            is_active, is_verified, is_admin
                        )
                        VALUES ($1, $2, $3, $4, TRUE, TRUE, $5)
                        RETURNING *
                        """,
                        str(uuid.uuid4()),
                        username,
                        normalized_email,
                        hashed,
                        is_admin,
                    )
                else:
                    row = await conn.fetchrow(
                        """
                        UPDATE users
                        SET username = $2,
                            email = $3,
                            hashed_password = $4,
                            is_active = TRUE,
                            is_verified = TRUE,
                            is_admin = $5
                        WHERE id = $1
                        RETURNING *
                        """,
                        existing["id"],
                        username,
                        normalized_email,
                        hashed,
                        is_admin,
                    )

        logger.info(
            "user.seeded",
            user_id=str(row["id"]),
            username=username,
            email=normalized_email,
            is_admin=is_admin,
        )
        return self._from_row(row)

    async def authenticate(self, email: str, password: str) -> UserRecord | None:
        """Authenticate by email + password.

        Returns:
            UserRecord if credentials are valid, None otherwise.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE email = $1 AND is_active = TRUE",
                email.lower(),
            )

        if row is None:
            return None

        if not verify_password(password, row["hashed_password"]):
            return None

        return self._from_row(row)

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        """Fetch a user by UUID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE id = $1::uuid",
                user_id,
            )

        if row is None:
            return None

        return self._from_row(row)

    async def get_by_email(self, email: str) -> UserRecord | None:
        """Fetch a user by email address."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE email = $1",
                email.lower(),
            )

        if row is None:
            return None

        return self._from_row(row)

    async def verify_email(self, email: str) -> bool:
        """Mark a user's email as verified.

        Returns:
            True if the user was found and updated, False otherwise.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE users SET is_verified = TRUE WHERE email = $1 AND is_verified = FALSE",
                email.lower(),
            )

        updated = result.split()[-1] != "0"
        if updated:
            logger.info("user.email_verified", email=email)
        return updated

    async def close(self) -> None:
        """Close the connection pool."""
        await self._pool.close()
