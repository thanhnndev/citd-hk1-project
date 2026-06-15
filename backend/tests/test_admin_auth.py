"""Tests for admin authorization."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.middleware.auth import get_current_admin


@pytest.mark.asyncio
async def test_get_current_admin_allows_admin():
    admin = SimpleNamespace(is_admin=True)

    assert await get_current_admin(admin) is admin


@pytest.mark.asyncio
async def test_get_current_admin_rejects_regular_user():
    user = SimpleNamespace(is_admin=False)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_admin(user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Admin access required."
