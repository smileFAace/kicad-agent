"""LLM provider abstraction: protocol, concrete providers, and factory.

Defines the LLMProvider protocol as the primary abstraction for all LLM
consumers.  AnthropicProvider wraps the existing LLMClient, MockProvider
returns deterministic responses for testing, and get_provider() is the
factory that reads KICAD_LLM_PROVIDER to select and cache a provider.

Security (threat model):
  T-34-01: Provider name validated against whitelist in get_provider().
  T-34-02: MockProvider is test-only; default provider is AnthropicProvider.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# LLMProvider protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers.

    A superset of LLMBackend: any class satisfying LLMProvider
    automatically satisfies LLMBackend (which only defines .model
    and .create_message()).

    Methods:
        generate: Convenience method for text-only callers.
        embed: Placeholder for future embedding providers.
        create_message: Full API passthrough for tool_use consumers.
    """

    @property
    def model(self) -> str: ...

    def generate(self, prompt: str, *, system: str | None = None) -> str: ...

    def embed(self, text: str) -> list[float]: ...

    def create_message(self, **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------------------
# AnthropicProvider
# ---------------------------------------------------------------------------


class AnthropicProvider:
    """Provider backed by the Anthropic SDK via LLMClient.

    Delegates create_message() directly to LLMClient for full passthrough
    of tool_use, thinking, and all other Anthropic-specific kwargs.

    Args:
        model: Optional model override forwarded to LLMClient.
    """

    def __init__(self, model: str | None = None) -> None:
        from kicad_agent.llm.client import LLMClient

        self._client = LLMClient(model=model)

    @property
    def model(self) -> str:
        """Model identifier from the underlying LLMClient."""
        return self._client.model

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Generate text from a prompt via Anthropic.

        Builds an Anthropic messages.create call with max_tokens=4096
        and extracts the text content from the response.

        Args:
            prompt: User prompt string.
            system: Optional system prompt.

        Returns:
            The text content of the model response.
        """
        kwargs: dict[str, Any] = {
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system is not None:
            kwargs["system"] = system
        response = self._client.create_message(**kwargs)
        return response.content[0].text

    def embed(self, text: str) -> list[float]:
        """Anthropic does not offer an embeddings API.

        Raises:
            NotImplementedError: Always -- use a different provider.
        """
        raise NotImplementedError(
            "Anthropic does not offer an embeddings API. "
            "Use a different provider for embedding support."
        )

    def create_message(self, **kwargs: Any) -> Any:
        """Delegate directly to LLMClient.create_message().

        Preserves tool_use, thinking, and all other Anthropic-specific
        kwargs with no modification.
        """
        return self._client.create_message(**kwargs)


# ---------------------------------------------------------------------------
# MockProvider
# ---------------------------------------------------------------------------


class _MockContent:
    """Anthropic-compatible text content block for mock responses."""

    __slots__ = ("type", "text")

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _MockMessage:
    """Anthropic-compatible Message wrapper for mock responses."""

    __slots__ = ("content", "model", "stop_reason")

    def __init__(self, text: str) -> None:
        self.content = [_MockContent(text)]
        self.model = "mock-provider"
        self.stop_reason = "end_turn"


class MockProvider:
    """Deterministic provider for testing.

    Returns canned responses and tracks call count for assertion.

    Args:
        responses: List of response strings to return sequentially.
            Defaults to ``["mock response"]``.
    """

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses: list[str] = responses or ["mock response"]
        self._call_count: int = 0

    @property
    def model(self) -> str:
        """Model identifier for the mock provider."""
        return "mock-provider"

    @property
    def call_count(self) -> int:
        """Number of generate() and create_message() calls made."""
        return self._call_count

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Return the next response string from the responses list.

        Increments call_count.  When responses are exhausted, repeats
        the last response.
        """
        self._call_count += 1
        idx = min(self._call_count - 1, len(self._responses) - 1)
        return self._responses[idx]

    def embed(self, text: str) -> list[float]:
        """Return a deterministic 768-dimensional zero vector."""
        return [0.0] * 768

    def create_message(self, **kwargs: Any) -> _MockMessage:
        """Return a mock Anthropic Message with the next response text.

        Increments call_count.
        """
        self._call_count += 1
        idx = min(self._call_count - 1, len(self._responses) - 1)
        return _MockMessage(self._responses[idx])


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_provider_cache: dict[str, LLMProvider] = {}


def get_provider(name: str | None = None) -> LLMProvider:
    """Return a cached LLMProvider instance.

    Reads KICAD_LLM_PROVIDER env var when *name* is not provided.
    Default is "anthropic".

    Args:
        name: Explicit provider name ("anthropic" or "mock").
            When None, reads from KICAD_LLM_PROVIDER env var.

    Returns:
        A cached LLMProvider instance.

    Raises:
        ValueError: If the provider name is not recognised.

    Security (T-34-01):
        Provider names are validated against a whitelist.  Unknown
        names raise ValueError to prevent injection of arbitrary modules.
    """
    provider_name = name or os.environ.get("KICAD_LLM_PROVIDER", "anthropic")

    if provider_name in _provider_cache:
        return _provider_cache[provider_name]

    if provider_name == "anthropic":
        provider: LLMProvider = AnthropicProvider()
    elif provider_name == "mock":
        provider = MockProvider()
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider_name}. Available: anthropic, mock"
        )

    _provider_cache[provider_name] = provider
    return provider
