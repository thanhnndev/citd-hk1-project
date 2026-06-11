"""Seed verified development admin and user accounts."""

from __future__ import annotations

import argparse
import asyncio
import os

from app.services.user_service import UserService


def _required_env(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    if not value:
        raise RuntimeError(f"{name} must not be empty")
    return value


async def seed(only: str) -> None:
    service = await UserService.create()
    try:
        accounts = {
            "admin": {
                "username": _required_env("SEED_ADMIN_USERNAME", "admin"),
                "email": _required_env("SEED_ADMIN_EMAIL", "admin@hamninh.vn"),
                "password": _required_env("SEED_ADMIN_PASSWORD", "Admin@123"),
                "is_admin": True,
            },
            "user": {
                "username": _required_env("SEED_USER_USERNAME", "user"),
                "email": _required_env("SEED_USER_EMAIL", "user@hamninh.vn"),
                "password": _required_env("SEED_USER_PASSWORD", "User@123"),
                "is_admin": False,
            },
        }

        selected = accounts if only == "all" else {only: accounts[only]}
        for account_type, values in selected.items():
            user = await service.seed_user(**values)
            print(
                f"Seeded {account_type}: "
                f"email={user.email} username={user.username} is_admin={user.is_admin}"
            )
    finally:
        await service.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=("all", "admin", "user"),
        default="all",
        help="Choose which development account to seed.",
    )
    args = parser.parse_args()
    asyncio.run(seed(args.only))


if __name__ == "__main__":
    main()
