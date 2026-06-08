"""Tests for Langfuse OpenAI client patching behavior.

Verifies that:
- When Langfuse is enabled, OpenAI client is patched with langfuse.openai for automatic tracing
- When Langfuse is disabled, standard openai.AsyncOpenAI is used (no performance impact)
- The patched client is properly passed to HamNinhGraph for LLM call tracing
"""

from unittest.mock import Mock, patch, MagicMock
import pytest


class TestOpenAIPatchedWhenLangfuseEnabled:
    """Verify OpenAI client is patched when Langfuse is enabled."""

    def test_openai_patched_when_langfuse_enabled(self):
        """When langfuse_client is not None, create_openai_client uses langfuse.openai."""
        # Mock the langfuse.openai.openai namespace that gets imported
        mock_async_openai_class = MagicMock()
        mock_client_instance = MagicMock()
        mock_async_openai_class.return_value = mock_client_instance
        
        # Create a mock namespace for langfuse.openai.openai
        mock_langfuse_openai_namespace = MagicMock()
        mock_langfuse_openai_namespace.AsyncOpenAI = mock_async_openai_class
        
        # Patch at the import location
        with patch('langfuse.openai.openai', mock_langfuse_openai_namespace):
            from app.main import create_openai_client

            # Create a mock langfuse client (non-None = enabled)
            mock_langfuse_client = Mock()
            mock_langfuse_client.public_key = "test-public-key"

            # Call the factory function
            api_key = "test-openai-key"
            client = create_openai_client(mock_langfuse_client, api_key)

            # Verify langfuse.openai.AsyncOpenAI was called
            mock_async_openai_class.assert_called_once_with(api_key=api_key)

            # Verify the returned client is the patched one
            assert client == mock_client_instance


class TestOpenAINotPatchedWhenLangfuseDisabled:
    """Verify standard OpenAI client is used when Langfuse is disabled."""

    def test_openai_not_patched_when_langfuse_disabled(self):
        """When langfuse_client is None, create_openai_client uses standard openai."""
        # Import app.main to get the openai module reference
        import app.main
        
        # Mock the AsyncOpenAI class on the openai module imported in app.main
        mock_async_openai_class = MagicMock()
        mock_client_instance = MagicMock()
        mock_async_openai_class.return_value = mock_client_instance
        
        # Patch the openai.AsyncOpenAI in app.main's namespace
        with patch.object(app.main.openai, 'AsyncOpenAI', mock_async_openai_class):
            from app.main import create_openai_client

            # Pass None for langfuse_client (disabled)
            api_key = "test-openai-key"
            client = create_openai_client(None, api_key)

            # Verify standard openai.AsyncOpenAI was called
            mock_async_openai_class.assert_called_once_with(api_key=api_key)

            # Verify the returned client is the standard one
            assert client == mock_client_instance


class TestHamNinhGraphReceivesLangfuseClient:
    """Verify HamNinhGraph receives langfuse_client for LLM call tracing."""

    @pytest.mark.asyncio
    async def test_ham_ninh_graph_receives_langfuse_client(self):
        """HamNinhGraph constructor receives langfuse_client parameter."""
        from agents.graph.ham_ninh_graph import HamNinhGraph
        from agents.graph.nodes import NodeServices

        # Mock dependencies
        mock_checkpointer = Mock()
        mock_services = Mock(spec=NodeServices)
        mock_langfuse_client = Mock()
        mock_langfuse_client.public_key = "test-key"

        # Patch StateGraph to avoid full graph compilation
        with patch('agents.graph.ham_ninh_graph.StateGraph') as mock_state_graph:
            mock_builder = MagicMock()
            mock_state_graph.return_value = mock_builder
            mock_builder.compile.return_value = MagicMock()

            # Create HamNinhGraph with langfuse_client
            graph = HamNinhGraph(
                checkpointer=mock_checkpointer,
                services=mock_services,
                langfuse_client=mock_langfuse_client,
            )

            # Verify langfuse_client is stored
            assert graph._langfuse_client == mock_langfuse_client

    @pytest.mark.asyncio
    async def test_create_ham_ninh_graph_passes_langfuse_client(self):
        """create_ham_ninh_graph factory passes langfuse_client to HamNinhGraph."""
        from agents.graph.ham_ninh_graph import create_ham_ninh_graph
        from agents.graph.nodes import NodeServices

        # Mock dependencies
        mock_services = Mock(spec=NodeServices)
        mock_langfuse_client = Mock()
        mock_langfuse_client.public_key = "test-key"

        # Patch HamNinhGraph constructor
        with patch('agents.graph.ham_ninh_graph.HamNinhGraph') as mock_graph_class:
            mock_graph_instance = MagicMock()
            mock_graph_class.return_value = mock_graph_instance

            # Call factory with langfuse_client
            graph = await create_ham_ninh_graph(
                checkpoint_mode="memory",
                services=mock_services,
                langfuse_client=mock_langfuse_client,
            )

            # Verify HamNinhGraph was called with langfuse_client
            mock_graph_class.assert_called_once()
            call_kwargs = mock_graph_class.call_args[1]
            assert call_kwargs['langfuse_client'] == mock_langfuse_client
            assert call_kwargs['services'] == mock_services


class TestGracefulDegradation:
    """Verify graceful degradation when Langfuse is unavailable."""

    def test_no_performance_impact_when_disabled(self):
        """When Langfuse is disabled, standard openai client is used without langfuse overhead."""
        import app.main
        
        mock_async_openai_class = MagicMock()
        mock_client_instance = MagicMock()
        mock_async_openai_class.return_value = mock_client_instance
        
        with patch.object(app.main.openai, 'AsyncOpenAI', mock_async_openai_class):
            from app.main import create_openai_client

            # Call with None (disabled)
            client = create_openai_client(None, "test-key")

            # Verify standard openai.AsyncOpenAI was called
            mock_async_openai_class.assert_called_once_with(api_key="test-key")
            assert client == mock_client_instance

    def test_empty_api_key_still_works(self):
        """Even with empty API key, client creation doesn't crash."""
        import app.main
        
        mock_async_openai_class = MagicMock()
        mock_client_instance = MagicMock()
        mock_async_openai_class.return_value = mock_client_instance
        
        with patch.object(app.main.openai, 'AsyncOpenAI', mock_async_openai_class):
            from app.main import create_openai_client

            # Call with empty key
            client = create_openai_client(None, "")

            # Verify it still created a client (OpenAI SDK handles empty keys gracefully)
            mock_async_openai_class.assert_called_once_with(api_key="")
            assert client == mock_client_instance


class TestIntegrationWithNodeServices:
    """Verify the patched client flows through to NodeServices."""

    def test_node_services_receives_patched_client(self):
        """NodeServices.llm_client receives the patched OpenAI client."""
        from agents.graph.nodes import NodeServices

        # Create a mock patched client
        mock_patched_client = MagicMock()
        mock_patched_client.__class__.__name__ = "AsyncOpenAI"

        # Create NodeServices with the patched client
        services = NodeServices(
            llm_client=mock_patched_client,
            model="gpt-4o-mini",
            retriever=None,
            places_service=None,
            cohere_reranker=None,
            llm_answer_service=None,
        )

        # Verify the patched client is stored
        assert services.llm_client == mock_patched_client

        # All node functions that use services.llm_client will now
        # automatically use the patched client for tracing


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
