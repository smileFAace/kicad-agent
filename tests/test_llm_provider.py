"""Tests for LLMProvider protocol, AnthropicProvider, MockProvider, and get_provider() factory.

Covers:
- Protocol compliance (LLMProvider and LLMBackend isinstance checks)
- MockProvider deterministic responses, call counting, embed
- AnthropicProvider delegation to LLMClient
- Factory function get_provider() with caching and validation
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.llm.backend import LLMBackend
from kicad_agent.llm.provider import (
    AnthropicProvider,
    LLMProvider,
    MockProvider,
    get_provider,
)
from tests.conftest_llm import FakeMessage, FakeTextBlock


# ---------------------------------------------------------------------------
# TestMockProvider
# ---------------------------------------------------------------------------


class TestMockProvider:
    """Tests for MockProvider deterministic behavior."""

    def test_generate_default_response(self) -> None:
        """MockProvider.generate() returns 'mock response' by default."""
        provider = MockProvider()
        result = provider.generate("hello")
        assert result == "mock response"

    def test_generate_custom_responses(self) -> None:
        """MockProvider.generate() returns sequential custom responses."""
        provider = MockProvider(responses=["first", "second", "third"])
        assert provider.generate("prompt 1") == "first"
        assert provider.generate("prompt 2") == "second"
        assert provider.generate("prompt 3") == "third"

    def test_generate_repeats_last_response(self) -> None:
        """When responses are exhausted, MockProvider repeats the last one."""
        provider = MockProvider(responses=["only"])
        provider.generate("prompt 1")
        result = provider.generate("prompt 2")
        assert result == "only"

    def test_embed_returns_zero_vector(self) -> None:
        """MockProvider.embed() returns a 768-dimensional zero vector."""
        provider = MockProvider()
        result = provider.embed("some text")
        assert len(result) == 768
        assert all(v == 0.0 for v in result)

    def test_create_message_returns_content(self) -> None:
        """MockProvider.create_message() returns object with .content[0].text."""
        provider = MockProvider(responses=["hello world"])
        msg = provider.create_message(max_tokens=100, messages=[])
        assert msg.content[0].type == "text"
        assert msg.content[0].text == "hello world"

    def test_call_count_tracked(self) -> None:
        """MockProvider tracks call_count incremented by generate and create_message."""
        provider = MockProvider()
        assert provider.call_count == 0
        provider.generate("first")
        assert provider.call_count == 1
        provider.create_message(messages=[])
        assert provider.call_count == 2
        provider.generate("third")
        assert provider.call_count == 3

    def test_model_property(self) -> None:
        """MockProvider.model returns 'mock-provider'."""
        provider = MockProvider()
        assert provider.model == "mock-provider"


# ---------------------------------------------------------------------------
# TestAnthropicProvider
# ---------------------------------------------------------------------------


class TestAnthropicProvider:
    """Tests for AnthropicProvider delegation to LLMClient."""

    def test_generate_returns_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AnthropicProvider.generate() calls LLMClient and extracts text."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        fake_msg = FakeMessage([FakeTextBlock("generated text")])

        with patch("kicad_agent.llm.client.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = fake_msg
            mock_anthropic.Anthropic.return_value = mock_client

            provider = AnthropicProvider()
            result = provider.generate("hello", system="you are helpful")

        assert result == "generated text"
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["messages"] == [
            {"role": "user", "content": "hello"}
        ]
        assert call_kwargs["system"] == "you are helpful"
        assert call_kwargs["max_tokens"] == 4096

    def test_embed_raises_not_implemented(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AnthropicProvider.embed() raises NotImplementedError."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        with patch("kicad_agent.llm.client.anthropic"):
            provider = AnthropicProvider()

        with pytest.raises(NotImplementedError, match="Anthropic does not offer"):
            provider.embed("text")

    def test_create_message_delegates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AnthropicProvider.create_message() delegates to LLMClient passthrough."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        fake_msg = FakeMessage([FakeTextBlock("passthrough")])

        with patch("kicad_agent.llm.client.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = fake_msg
            mock_anthropic.Anthropic.return_value = mock_client

            provider = AnthropicProvider()
            result = provider.create_message(
                max_tokens=1024,
                messages=[{"role": "user", "content": "test"}],
                tools=[{"name": "my_tool"}],
            )

        assert result is fake_msg

    def test_model_property(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AnthropicProvider.model returns the model string from LLMClient."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        with patch("kicad_agent.llm.client.anthropic"):
            provider = AnthropicProvider()

        assert provider.model == "claude-sonnet-4-20250514"

    def test_model_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AnthropicProvider accepts model override."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        with patch("kicad_agent.llm.client.anthropic"):
            provider = AnthropicProvider(model="claude-haiku-4-20250414")

        assert provider.model == "claude-haiku-4-20250414"


# ---------------------------------------------------------------------------
# TestGetProvider
# ---------------------------------------------------------------------------


class TestGetProvider:
    """Tests for get_provider() factory function."""

    def setup_method(self) -> None:
        """Clear the provider cache before each test."""
        import kicad_agent.llm.provider as mod

        mod._provider_cache.clear()

    def test_default_returns_anthropic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_provider() with default env returns AnthropicProvider."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.delenv("KICAD_LLM_PROVIDER", raising=False)

        with patch("kicad_agent.llm.client.anthropic"):
            provider = get_provider()

        assert isinstance(provider, AnthropicProvider)

    def test_mock_env_returns_mock_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_provider() with KICAD_LLM_PROVIDER=mock returns MockProvider."""
        monkeypatch.setenv("KICAD_LLM_PROVIDER", "mock")

        provider = get_provider()

        assert isinstance(provider, MockProvider)

    def test_explicit_mock_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_provider(name='mock') returns MockProvider regardless of env."""
        monkeypatch.setenv("KICAD_LLM_PROVIDER", "anthropic")

        provider = get_provider(name="mock")

        assert isinstance(provider, MockProvider)

    def test_caching_returns_same_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_provider() caches -- second call returns same instance."""
        monkeypatch.setenv("KICAD_LLM_PROVIDER", "mock")

        first = get_provider()
        second = get_provider()

        assert first is second

    def test_invalid_name_raises_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_provider() with invalid name raises ValueError."""
        monkeypatch.delenv("KICAD_LLM_PROVIDER", raising=False)

        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider(name="nonexistent")


# ---------------------------------------------------------------------------
# TestProtocolCompliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    """Tests for protocol isinstance checks."""

    def test_anthropic_provider_is_llm_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AnthropicProvider satisfies LLMProvider protocol."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        with patch("kicad_agent.llm.client.anthropic"):
            provider = AnthropicProvider()

        assert isinstance(provider, LLMProvider)

    def test_mock_provider_is_llm_provider(self) -> None:
        """MockProvider satisfies LLMProvider protocol."""
        provider = MockProvider()
        assert isinstance(provider, LLMProvider)

    def test_anthropic_provider_is_llm_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AnthropicProvider satisfies LLMBackend protocol."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        with patch("kicad_agent.llm.client.anthropic"):
            provider = AnthropicProvider()

        assert isinstance(provider, LLMBackend)

    def test_mock_provider_is_llm_backend(self) -> None:
        """MockProvider satisfies LLMBackend protocol."""
        provider = MockProvider()
        assert isinstance(provider, LLMBackend)
