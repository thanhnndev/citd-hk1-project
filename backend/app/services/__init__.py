"""Backend service layer — infrastructure and auth concerns only.

Agent orchestration lives in the `agents/` package.  This module
contains services that are backend-specific: observability, auth,
email, and user management.
"""

from app.services.langfuse_service import init_langfuse

__all__ = ["init_langfuse"]
