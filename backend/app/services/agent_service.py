"""Agent orchestration service placeholder.

Future home of the agent graph invocation logic (LangGraph or similar).

Planned responsibilities:
- Construct and execute the ReAct / tool-calling agent graph.
- Manage conversation state and memory per session.
- Route tool calls to external services (Google Places, Google Routes).
- Stream token chunks to the chat endpoint via Server-Sent Events.
"""

# TODO: Implement agent graph once S04 (chat pipeline) begins.
# Expected interface:
#   class AgentService:
#       async def invoke(self, session_id: str, message: str) -> ChatResponse: ...
#       async def stream(self, session_id: str, message: str) -> AsyncIterator[str]: ...
