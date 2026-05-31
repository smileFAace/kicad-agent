"""LLM integration module for AI-driven PCB generation.

Provides natural language to GenerationIntent conversion, component suggestion,
and context assembly for Claude via the Anthropic SDK. Also supports local-first
inference via HybridLLMClient with cloud fallback.

This module requires the ``anthropic`` package. Install with::

    pip install kicad-agent[llm]

For local inference (mlx-lm on Apple Silicon)::

    pip install kicad-agent[local]

Usage::

    from kicad_agent.llm import IntentParser, ComponentSuggester, LLMClient

    client = LLMClient()
    parser = IntentParser()
    intent = parser.parse("Design a 3.3V voltage regulator")

Hybrid local-first mode::

    from kicad_agent.llm import HybridLLMClient
    client = HybridLLMClient()  # local-first with cloud fallback
"""

from __future__ import annotations


def _check_anthropic_available() -> None:
    """Verify anthropic is importable; raise ImportError if not."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        raise ImportError(
            "The 'anthropic' package is required for LLM features. "
            "Install it with: pip install kicad-agent[llm]"
        )


def __getattr__(name: str):
    """Lazy imports that raise ImportError if anthropic is not installed."""
    _lazy = {
        "LLMClient": "kicad_agent.llm.client",
        "IntentParser": "kicad_agent.llm.intent_parser",
        "ComponentSuggester": "kicad_agent.llm.component_suggester",
        "ContextBuilder": "kicad_agent.llm.context_builder",
        "LLMConfigError": "kicad_agent.llm.client",
        "INTENT_TOOL": "kicad_agent.llm.tools",
        "SUGGEST_TOOL": "kicad_agent.llm.tools",
        "COMPONENT_SYSTEM_PROMPT": "kicad_agent.llm.tools",
        "DesignCritic": "kicad_agent.llm.design_critic",
        "CritiqueFinding": "kicad_agent.llm.design_critic",
        "CritiqueReport": "kicad_agent.llm.design_critic",
        "CritiqueSeverity": "kicad_agent.llm.design_critic",
        "CRITIC_SYSTEM_PROMPT": "kicad_agent.llm.design_critic",
        "CRITIC_TOOL": "kicad_agent.llm.design_critic",
        "build_spatial_context": "kicad_agent.llm.design_critic",
        "ErrorFixer": "kicad_agent.llm.error_fixer",
        "FixResult": "kicad_agent.llm.error_fixer",
        "FIX_SYSTEM_PROMPT": "kicad_agent.llm.error_fixer",
        "FIX_TOOL": "kicad_agent.llm.error_fixer",
        "llm_refine_design": "kicad_agent.llm.refinement",
        "LLMRefinementResult": "kicad_agent.llm.refinement",
        "LLMRefinementIteration": "kicad_agent.llm.refinement",
        "llm_generate": "kicad_agent.llm.pipeline",
        "LLMGenerationResult": "kicad_agent.llm.pipeline",
        # New: hybrid backend + text parsers + unified parsers
        "HybridLLMClient": "kicad_agent.llm.backend",
        "HybridResponse": "kicad_agent.llm.backend",
        "LLMBackend": "kicad_agent.llm.backend",
        "ConfidenceScorer": "kicad_agent.llm.confidence",
        "ConfidenceScore": "kicad_agent.llm.confidence",
        "extract_json_from_text": "kicad_agent.llm.text_prompts",
        "TextIntentParser": "kicad_agent.llm.text_parsers",
        "TextErrorFixer": "kicad_agent.llm.text_parsers",
        "TextCritiqueParser": "kicad_agent.llm.text_parsers",
        "UnifiedIntentParser": "kicad_agent.llm.unified_parsers",
        "UnifiedErrorFixer": "kicad_agent.llm.unified_parsers",
        # Provider abstraction
        "LLMProvider": "kicad_agent.llm.provider",
        "AnthropicProvider": "kicad_agent.llm.provider",
        "MockProvider": "kicad_agent.llm.provider",
        "get_provider": "kicad_agent.llm.provider",
    }

    if name not in _lazy:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    # Hybrid/local classes don't require anthropic
    _no_anthropic_required = {
        "HybridLLMClient", "HybridResponse", "LLMBackend",
        "ConfidenceScorer", "ConfidenceScore",
        "extract_json_from_text",
        "TextIntentParser", "TextErrorFixer", "TextCritiqueParser",
        "UnifiedIntentParser", "UnifiedErrorFixer",
        "LLMProvider", "AnthropicProvider", "MockProvider", "get_provider",
    }

    if name not in _no_anthropic_required:
        _check_anthropic_available()

    import importlib

    module_path = _lazy[name]
    module = importlib.import_module(module_path)
    return getattr(module, name)


__all__ = [
    "AnthropicProvider",
    "ComponentSuggester",
    "COMPONENT_SYSTEM_PROMPT",
    "ConfidenceScore",
    "ConfidenceScorer",
    "ContextBuilder",
    "CRITIC_SYSTEM_PROMPT",
    "CRITIC_TOOL",
    "CritiqueFinding",
    "CritiqueReport",
    "CritiqueSeverity",
    "DesignCritic",
    "ErrorFixer",
    "extract_json_from_text",
    "FIX_SYSTEM_PROMPT",
    "FIX_TOOL",
    "FixResult",
    "get_provider",
    "HybridLLMClient",
    "HybridResponse",
    "IntentParser",
    "INTENT_TOOL",
    "LLMBackend",
    "LLMClient",
    "LLMConfigError",
    "LLMGenerationResult",
    "LLMProvider",
    "LLMRefinementIteration",
    "LLMRefinementResult",
    "MockProvider",
    "SUGGEST_TOOL",
    "TextCritiqueParser",
    "TextErrorFixer",
    "TextIntentParser",
    "UnifiedErrorFixer",
    "UnifiedIntentParser",
    "build_spatial_context",
    "llm_generate",
    "llm_refine_design",
]
