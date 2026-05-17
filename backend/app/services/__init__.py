"""Application service layer package.

Services encapsulate external integrations (Langfuse, Qdrant) and
business logic (agent orchestration).  Each service is initialized
during lifespan startup and cleaned up on shutdown.
"""

from app.services.langfuse_service import init_langfuse

__all__ = ["init_langfuse"]
