# Phase 15: AI Generation Wiring - Research

**Researched:** 2026-05-23
**Domain:** LLM integration with existing KiCad generation pipeline (Anthropic SDK, structured generation, spatial reasoning)
**Confidence:** HIGH

## Summary

Phase 15 wires an actual LLM (Claude via Anthropic SDK) into the existing Phase 10 generation pipeline. The generation pipeline is already fully functional: `GenerationIntent` converts to operations, `generate_design()` produces valid KiCad projects, `refine_design()` runs ERC/DRC auto-fixes, and `evaluate_design()` scores results. The missing piece is an LLM layer that converts natural language to `GenerationIntent`, suggests components, critiques designs using spatial data, and drives error-fixing during refinement.

The Anthropic Python SDK v0.61.0 is already installed locally (not yet in pyproject.toml). It supports tool use with JSON Schema input/output, extended thinking for complex reasoning, and prompt caching for efficiency. The existing `get_operation_schema()` exports a 51KB JSON Schema directly usable as a Claude tool definition, and `GenerationIntent.model_json_schema()` exports a 7KB schema for structured intent output.

**Primary recommendation:** Use Anthropic SDK tool use as the integration primitive. Define Claude tools for each phase capability (intent parsing, component suggestion, design critique, error fixing) with JSON Schema contracts derived from existing Pydantic models. This avoids custom parsing, gets type-safe structured output, and leverages Claude's built-in understanding of tool semantics.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| NL to GenerationIntent conversion | API / Backend | -- | LLM call + Pydantic validation; no UI involvement |
| Component suggestion | API / Backend | Database / Storage | LLM generates candidates, validated against KiCad symbol libraries |
| Design critique | API / Backend | Database / Storage | LLM interprets spatial data from SpatialQueryEngine + ERC/DRC results |
| Iterative refinement | API / Backend | -- | Loop runs server-side: validate -> classify -> LLM fix -> validate |
| Context window management | API / Backend | -- | Token budgeting and prompt assembly; no client involvement |
| Skill handler routing | Browser / Client | API / Backend | Claude constructs tool calls in skill context, routed to Python backend |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| anthropic | 0.61.0 | Claude API client with tool use support | Official SDK; supports structured output via tool use, extended thinking, prompt caching [VERIFIED: pip3 show] |
| pydantic | 2.12.5 | Schema definition and validation for LLM I/O | Already used throughout codebase; `model_json_schema()` exports directly as Claude tool `input_schema` [VERIFIED: pip3 show] |
| httpx | 0.28.1 | HTTP client (already a dependency; used by anthropic internally) | Existing dependency; anthropic SDK uses httpx [VERIFIED: pip3 show] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| kiutils | 1.4.8 | KiCad file parsing for symbol library search | Component suggestion: read symbol libraries to validate pin/footprint compatibility [VERIFIED: pip3 show] |
| networkx | 3.4.2 | Net connectivity graph analysis | Design critique: analyze net topology for routing congestion [VERIFIED: pip3 show] |
| shapely | (via spatial module) | Spatial geometry for design critique | Already integrated in SpatialQueryEngine [VERIFIED: codebase] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Anthropic SDK tool use | OpenAI function calling + openrouter | Would require dual SDK support; tool use is model-specific. Stick with Anthropic for Phase 15 |
| Claude structured output (JSON mode) | Instructor library for type-safe output | Instructor adds a dependency; tool use already provides type-safe structured output natively |
| Local model (Ollama) | Claude API | Lower cost, no API key needed, but worse at structured JSON, no tool use. Recommend Claude API as primary, local as future fallback |

**Installation:**
```bash
# anthropic is already installed locally, needs adding to pyproject.toml
# No new packages required beyond what's already available
```

**Version verification:**
```
anthropic==0.61.0 (installed 2026-05-23, not in pyproject.toml yet)
pydantic==2.12.5 (in pyproject.toml as >=2.0)
httpx==0.28.1 (in pyproject.toml as >=0.28.0)
kiutils==1.4.8 (in pyproject.toml as >=1.4.8)
networkx==3.4.2 (in pyproject.toml as >=3.0)
```

## Architecture Patterns

### System Architecture Diagram

```
User NL Input
     |
     v
+-------------------+     +------------------------+
| IntentParser      |---->| GenerationIntent       |
| (Claude tool use) |     | (Pydantic model)       |
+-------------------+     +------------------------+
     |                            |
     v                            v
+-------------------+     +------------------------+
| ComponentSuggester|     | generate_design()      |
| (Claude tool use) |     | (Phase 10 pipeline)    |
+-------------------+     +------------------------+
     |                            |
     |                            v
     |                    +------------------------+
     |                    | refine_design()        |
     |                    | (ERC/DRC validate)     |
     |                    +------------------------+
     |                            |
     |                    ERC/DRC violations
     |                            |
     |                            v
     |                    +------------------------+
     +------------------->| ErrorFixer             |
                          | (Claude tool use)      |
                          +------------------------+
                                   |
                                   v
                          +------------------------+
                          | DesignCritic           |
                          | (spatial + violations) |
                          +------------------------+
                                   |
                                   v
                          Valid .kicad_sch + .kicad_pcb
```

**Data flow:** NL input -> Claude tool call returns structured GenerationIntent -> existing pipeline generates board -> ERC/DRC validates -> Claude interprets violations and generates fix operations -> loop until clean -> spatial critic reviews placement quality.

### Recommended Project Structure
```
src/kicad_agent/llm/
    __init__.py              # Public API: IntentParser, ComponentSuggester, DesignCritic, ErrorFixer
    client.py                # Anthropic client singleton, config, retry logic
    intent_parser.py         # NL -> GenerationIntent via Claude tool use
    component_suggester.py   # Functional description -> KiCad component candidates
    design_critic.py         # Spatial analysis + ERC/DRC -> critique report
    error_fixer.py           # ERC/DRC violations -> fix operations via Claude
    context_builder.py       # Prompt assembly, token budgeting, caching
    tools.py                 # Claude tool definitions (JSON Schema from Pydantic models)
```

### Pattern 1: Tool Use for Structured Output
**What:** Define Claude tools with JSON Schema derived from existing Pydantic models. Claude fills tool parameters, SDK returns structured dict, Pydantic validates.
**When to use:** Every LLM call that produces structured data (intent parsing, component suggestion, error fixing).
**Example:**
```python
# Source: Anthropic SDK docs (tool use pattern) [CITED: docs.anthropic.com]
import anthropic
from kicad_agent.generation.intent import GenerationIntent

client = anthropic.Anthropic()

# Use GenerationIntent's JSON Schema as tool input_schema
intent_tool = {
    "name": "generate_design_intent",
    "description": "Convert a natural language circuit description into a structured design intent",
    "input_schema": GenerationIntent.model_json_schema(),
}

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4096,
    tools=[intent_tool],
    tool_choice={"type": "tool", "name": "generate_design_intent"},
    messages=[{"role": "user", "content": "Design a 3.3V voltage regulator with input filtering"}],
)

# Extract structured intent from tool use block
for block in response.content:
    if block.type == "tool_use" and block.name == "generate_design_intent":
        intent = GenerationIntent.model_validate(block.input)
        break
```

### Pattern 2: Extended Thinking for Design Critique
**What:** Use Claude's extended thinking for complex spatial reasoning tasks where the model needs to reason about coordinates, clearances, and thermal patterns.
**When to use:** Design critique that requires multi-step spatial reasoning. NOT for simple intent parsing.
**Example:**
```python
# Source: Anthropic SDK docs (extended thinking) [CITED: docs.anthropic.com]
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=16000,
    thinking={"type": "enabled", "budget_tokens": 8000},
    messages=[{
        "role": "user",
        "content": f"Analyze this PCB layout for clearance issues:\n{spatial_context}"
    }],
)
# Thinking blocks contain the spatial reasoning chain
# Text blocks contain the final critique
```

### Pattern 3: Prompt Caching for Repeated Context
**What:** Cache large, static context (operation schema, spatial data) across multiple LLM calls in a refinement loop.
**When to use:** Iterative refinement where the board state changes slowly between iterations.
**Example:**
```python
# Source: Anthropic docs (prompt caching) [CITED: docs.anthropic.com]
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4096,
    system=[
        {
            "type": "text",
            "text": operation_schema_context,  # 51KB schema, cached across calls
            "cache_control": {"type": "ephemeral"},
        }
    ],
    messages=[{"role": "user", "content": "Fix these ERC errors: ..."}],
)
# First call: cache write at 1.25x input price
# Subsequent calls: cache hit at 0.1x input price
```

### Pattern 4: Error Fixing via Operation Sequence
**What:** Feed ERC/DRC violations to Claude with the operation schema as context. Claude returns fix operations as tool calls.
**When to use:** Iterative refinement loop -- replacing the current deterministic auto-fix with LLM-driven fixes for the "other" error category.
**Example:**
```python
from kicad_agent.ops.schema import get_operation_schema

# Provide operation schema as context for fix generation
fix_tool = {
    "name": "apply_fix_operations",
    "description": "Apply a sequence of operations to fix schematic/PCB errors",
    "input_schema": {
        "type": "object",
        "properties": {
            "operations": {
                "type": "array",
                "items": get_operation_schema(),  # Reuse existing operation schema
            }
        },
        "required": ["operations"],
    },
}
```

### Anti-Patterns to Avoid
- **String parsing LLM output:** Never parse raw LLM text. Always use tool use for structured output. Raw text is for freeform critique only.
- **Giant monolithic prompts:** Don't stuff 51KB of operation schema into every call. Use prompt caching and only include relevant context per call type.
- **Synchronous LLM calls in hot loops:** The refinement loop must have iteration caps and timeouts. Never call Claude in an unbounded loop.
- **Ignoring Pydantic validation:** Claude can produce structurally valid but semantically wrong JSON. Always validate tool output through Pydantic models before passing to the pipeline.
- **Hardcoding model names:** Model names change (claude-sonnet-4-20250514 will be superseded). Use a config constant or environment variable.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Structured JSON output from LLM | Custom prompt engineering + regex parsing | Anthropic SDK tool use with `tool_choice` | Tool use guarantees JSON Schema compliance; custom parsing breaks on edge cases |
| Retry logic for API failures | Custom retry with sleep loops | `anthropic` built-in retry (or tenacity library) | Rate limiting, backoff, and idempotency are subtle; SDK handles 429/529 automatically |
| Token counting and budgeting | Manual character counting | `client.count_tokens()` or tiktoken estimate | Accurate token counting requires model-specific tokenizer; character-based estimates are wildly wrong for code/JSON |
| Prompt caching invalidation | Manual cache key management | Anthropic's `cache_control` parameter | Cache invalidation is handled by the API based on content matching; manual keys are error-prone |
| Component library search | Custom string matching against symbol names | kiutils `SymbolLibTable` + filtered enumeration | KiCad library structure is complex (nested libraries, aliases); kiutils handles it correctly |
| Spatial context assembly | Manual coordinate string formatting | `SpatialQueryEngine` JSON export + `to_json()` on primitives | SpatialPoint/SpatialBox already have `to_json()` for LLM consumption; Shapely handles all geometry |

**Key insight:** The existing codebase already has all the hard parts (parsing, validation, spatial queries, operation execution). Phase 15 is primarily an integration layer that connects Claude's reasoning to these existing capabilities via well-defined JSON Schema contracts.

## Common Pitfalls

### Pitfall 1: Claude Hallucinating Invalid library_id Values
**What goes wrong:** Claude generates `ComponentSpec(library_id="Device:Resistor")` which is not a valid KiCad symbol library ID. The actual ID would be `Device:R_Small_US` or `Device:R`.
**Why it happens:** Claude doesn't know KiCad's exact library naming conventions without context.
**How to avoid:** Provide a curated list of common component library IDs in the system prompt. Validate all `library_id` values against the actual KiCad symbol library table before accepting them. The `ComponentSuggester` tool should enumerate available libraries as part of its output.
**Warning signs:** `ComponentSpec` validation errors; components that fail `REF-03` cross-reference checks.

### Pitfall 2: Context Window Overflow on Large Designs
**What goes wrong:** A design with 50+ components generates spatial data, operation sequences, and ERC/DRC output that exceeds Claude's context window (200K tokens).
**Why it happens:** The operation schema alone is 51KB. Spatial data for a complex board can be 20-50KB. ERC/DRC violations can be verbose.
**How to avoid:** Implement token budgeting in `context_builder.py`. Truncate spatial data to only relevant regions. Summarize ERC violations by category rather than listing every individual violation. Use prompt caching so the schema doesn't count against the budget after the first call.
**Warning signs:** `ValidationError` from the SDK about token limits; truncated responses; `stop_reason: "max_tokens"`.

### Pitfall 3: Refinement Loop Not Converging
**What goes wrong:** The LLM-driven refinement loop applies fixes that introduce new errors, creating an oscillating pattern that never converges.
**Why it happens:** LLM lacks visibility into what it tried before. Each iteration is stateless from the model's perspective.
**How to avoid:** Include iteration history in each refinement call (what was tried, what happened). Track cumulative fix operations to avoid re-applying failed fixes. Keep the existing hard cap of 10 iterations. Add a "give up" threshold: if 3 consecutive iterations have the same error count, stop.
**Warning signs:** Iteration count hitting the cap; error counts oscillating between values; LLM suggesting the same fix repeatedly.

### Pitfall 4: Prompt Injection via Design Content
**What goes wrong:** A malicious `.kicad_sch` file contains text that looks like instructions to the LLM, causing it to generate unexpected operations.
**Why it happens:** KiCad files contain user-defined text fields (component values, net names, text labels) that get included in LLM prompts.
**How to avoid:** Sanitize all file content before including it in LLM prompts. Wrap file data in明确的data boundaries. Never include raw file content as instructions.
**Warning signs:** LLM generating operations unrelated to the user's request; unexpected tool calls.

### Pitfall 5: API Key Management
**What goes wrong:** Hardcoded API keys, keys committed to git, or keys not available at runtime.
**Why it happens:** Quick prototyping leads to hardcoded values; CI/CD doesn't have the key configured.
**How to avoid:** Use `ANTHROPIC_API_KEY` environment variable exclusively. Add `anthropic` as an optional dependency group (`[llm]`) so the base package doesn't require it. Fail gracefully with a clear error message when the key is missing.
**Warning signs:** `AuthenticationError` at runtime; keys in git diff.

### Pitfall 6: Model Version Lock-in
**What goes wrong:** Code hardcodes `claude-sonnet-4-20250514` which gets deprecated, breaking all LLM calls.
**Why it happens:** Model version strings are not stable; Anthropic releases new versions regularly.
**How to avoid:** Define model name as a config constant (`LLM_MODEL = os.environ.get("KICAD_AGENT_MODEL", "claude-sonnet-4-20250514")`). Use the latest stable model by default but allow override.
**Warning signs:** `NotFoundError` from the SDK; deprecated model warnings in API responses.

## Code Examples

### IntentParser: NL to GenerationIntent
```python
# Tool definition using existing GenerationIntent schema
from kicad_agent.generation.intent import GenerationIntent

INTENT_TOOL = {
    "name": "create_design_intent",
    "description": (
        "Convert a natural language circuit description into a structured "
        "design intent with board specs, components, nets, and power requirements"
    ),
    "input_schema": GenerationIntent.model_json_schema(),
}

# Parser implementation
class IntentParser:
    def __init__(self, model: str | None = None):
        self._client = anthropic.Anthropic()
        self._model = model or os.environ.get("KICAD_AGENT_MODEL", "claude-sonnet-4-20250514")

    def parse(self, description: str) -> GenerationIntent:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            tools=[INTENT_TOOL],
            tool_choice={"type": "tool", "name": "create_design_intent"},
            messages=[{"role": "user", "content": description}],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "create_design_intent":
                return GenerationIntent.model_validate(block.input)
        raise ValueError("LLM did not return a tool_use block")
```

### ComponentSuggester: Functional Description to KiCad Parts
```python
# Tool for component suggestion (simpler schema than full GenerationIntent)
SUGGEST_TOOL = {
    "name": "suggest_components",
    "description": "Given a functional description, suggest KiCad components with valid library_id values",
    "input_schema": {
        "type": "object",
        "properties": {
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "library_id": {"type": "string", "description": "KiCad symbol library ID (e.g., Device:R_Small_US)"},
                        "value": {"type": "string", "description": "Component value (e.g., 10k, 100nF)"},
                        "reference_prefix": {"type": "string", "description": "Reference prefix (e.g., R, C, U)"},
                        "rationale": {"type": "string", "description": "Why this component was suggested"},
                    },
                    "required": ["library_id", "value", "reference_prefix"],
                },
            }
        },
        "required": ["suggestions"],
    },
}

# System prompt with common KiCad library IDs
COMPONENT_SYSTEM_PROMPT = """You suggest KiCad components. Use these common library IDs:
- Resistors: Device:R_Small_US, Device:R_Small, Device:R
- Capacitors: Device:C_Small, Device:C, Device:C_Polarized
- LEDs: Device:LED, Device:LED_Small
- Diodes: Device:D, Device:D_Schottky, Device:D_Zener
- Inductors: Device:L, Device:L_Small
- Transistors: Device:Q_NPN_BCE, Device:Q_PNP_BCE, Device:Q_NMOS_GDS
- Regulators: Regulator_Linear:AMS1117-3.3, Regulator_Linear:LM7805_TO220
- MCUs: MCU_Microchip:ATtiny202, MCU_ST_STM32:STM32F103C8Tx
- Crystals: Device:Crystal, Device:Crystal_Small
- Switches: Switch:SW_Push
Always use Device: prefix for passive components."""
```

### DesignCritic: Spatial Reasoning with Extended Thinking
```python
# Build spatial context from SpatialQueryEngine
from kicad_agent.spatial.query import SpatialQueryEngine
from kicad_agent.spatial.primitives import SpatialPoint, SpatialBox
import json

def build_spatial_context(engine: SpatialQueryEngine) -> str:
    """Build a compact spatial summary for LLM consumption."""
    parts = []

    # Board-level summary
    all_entities = engine.proximity(0, 0, radius_mm=10000)
    parts.append(f"Total entities on board: {len(all_entities)}")

    # Group by entity type
    by_type: dict[str, list] = {}
    for e in all_entities:
        by_type.setdefault(e.entity_type, []).append(e)

    for etype, entities in by_type.items():
        parts.append(f"\n{etype}: {len(entities)} entities")
        # Include bounding boxes for components
        if etype == "component":
            for e in entities[:20]:  # Cap at 20 to manage context
                if isinstance(e, SpatialBox):
                    parts.append(
                        f"  {e.entity_id}: box({e.x1:.1f},{e.y1:.1f},{e.x2:.1f},{e.y2:.1f}) "
                        f"layer={e.layer} ref={e.reference}"
                    )

    return "\n".join(parts)
```

### ErrorFixer: ERC/DRC Violations to Fix Operations
```python
from kicad_agent.ops.schema import get_operation_schema
from kicad_agent.validation.erc_drc import ErcResult, DrcResult

def build_error_context(erc_result: ErcResult, drc_result: DrcResult | None) -> str:
    """Build compact error summary for LLM."""
    parts = []
    parts.append(f"ERC: {'PASS' if erc_result.passed else 'FAIL'} ({erc_result.error_count} errors)")
    for v in erc_result.violations[:10]:  # Cap violations
        parts.append(f"  [{v.severity.value}] {v.description}")
    if drc_result:
        parts.append(f"DRC: {'PASS' if drc_result.passed else 'FAIL'} ({drc_result.error_count} errors)")
        for v in drc_result.violations[:10]:
            parts.append(f"  [{v.severity.value}] {v.description}")
    return "\n".join(parts)

# Fix tool using the existing operation schema
FIX_TOOL = {
    "name": "apply_fix_operations",
    "description": "Generate a sequence of KiCad operations to fix the reported errors",
    "input_schema": {
        "type": "object",
        "properties": {
            "fix_description": {
                "type": "string",
                "description": "Human-readable summary of what the fixes do",
            },
            "operations": {
                "type": "array",
                "description": "Ordered list of operations to fix the errors",
                "items": get_operation_schema(),
            },
        },
        "required": ["fix_description", "operations"],
    },
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw text prompting for structured output | Tool use with JSON Schema (guaranteed structure) | Claude 3.5 (2024) | No more parsing fragile text output |
| Manual prompt engineering for reasoning | Extended thinking with budget_tokens | Claude 3.7 (2025) | Better spatial reasoning, visible thinking chain |
| Re-sending full context each call | Prompt caching (ephemeral) | Claude 3.5 (2024) | 10x cost reduction on repeated context |
| Deterministic auto-fix only | LLM-driven error interpretation + fix generation | Phase 15 (new) | Fix broader error categories, handle "other" class |
| Static component lists | LLM-suggested components with rationale | Phase 15 (new) | Natural language component search |

**Deprecated/outdated:**
- Claude 3 (Haiku/Sonnet/Opus) model names: Superseded by Claude 4 family. Use `claude-sonnet-4-20250514` or newer.
- `stop_reason: "stop_sequence"`: Use `stop_reason: "end_turn"` for modern models.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Claude Sonnet 4 is sufficient for intent parsing and error fixing; Opus 4 not needed | Standard Stack | If Sonnet produces lower-quality intents, may need Opus for complex designs (higher cost) |
| A2 | ANTHROPIC_API_KEY will be set via environment variable | Architecture Patterns | If no key available, all LLM features fail; need graceful degradation |
| A3 | The existing 51KB operation schema fits in Claude's context without issues | Common Pitfalls | If schema is too large when combined with other context, may need trimming |
| A4 | KiCad 10 symbol library structure is stable enough to enumerate for component suggestion | Code Examples | If library structure changes between KiCad versions, suggestion tool breaks |
| A5 | Extended thinking budget of 8000 tokens is sufficient for design critique | Code Examples | If spatial reasoning requires more, critique quality degrades |

## Open Questions

1. **Should anthropic be a required or optional dependency?**
   - What we know: anthropic is installed locally (v0.61.0) but not in pyproject.toml
   - What's unclear: Whether Phase 15 features should work without an API key
   - Recommendation: Add as optional dependency group `[llm]` so `pip install kicad-agent[llm]` includes it. Base install remains LLM-free.

2. **What model should be the default?**
   - What we know: Claude Sonnet 4 is fast and cost-effective. Opus 4 is more capable but 5x more expensive.
   - What's unclear: Whether Sonnet 4's spatial reasoning is good enough for design critique
   - Recommendation: Default to Sonnet 4. Allow model override via env var. Benchmark both during Phase 15 execution.

3. **Should the refinement loop keep the existing deterministic auto-fixes as a first pass before LLM?**
   - What we know: `pin_not_connected` and `wire_not_connected` fixes work reliably via deterministic code
   - What's unclear: Whether LLM should handle ALL fixes or just the "other" category
   - Recommendation: Keep deterministic fixes as first pass (faster, cheaper, reliable). LLM handles only what deterministic code cannot fix.

4. **How to handle KiCad symbol library enumeration for component suggestion?**
   - What we know: kiutils can parse symbol library tables; KiCad has 100+ built-in libraries
   - What's unclear: Best way to present library options to Claude without exceeding context limits
   - Recommendation: Curated list of ~50 common component types in system prompt + dynamic search for specific needs

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| anthropic SDK | All LLM features | Installed (not in pyproject.toml) | 0.61.0 | -- |
| ANTHROPIC_API_KEY | All LLM features | Unknown (env var) | -- | Graceful error message |
| kicad-cli | ERC/DRC validation | Available | 10.0.1 | Skip validation (not viable for Phase 15) |
| Python 3.11+ | Runtime | Available | 3.11.11 | -- |
| pydantic v2 | Schema validation | Available | 2.12.5 | -- |
| kiutils | Symbol library parsing | Available | 1.4.8 | -- |

**Missing dependencies with no fallback:**
- `ANTHROPIC_API_KEY` environment variable: Must be set for any LLM feature to work. Plan should include setup documentation and clear error message on missing key.

**Missing dependencies with fallback:**
- anthropic in pyproject.toml: Currently installed but not declared. Plan should add it to `[llm]` optional dependency group.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | pyproject.toml (`[tool.pytest.ini_options]`) |
| Quick run command | `pytest tests/test_llm*.py -x -q` |
| Full suite command | `pytest tests/ -x --tb=short` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AIGEN-01 | NL input produces valid GenerationIntent via tool use | unit (mocked) | `pytest tests/test_llm_intent_parser.py -x` | Wave 0 |
| AIGEN-01 | GenerationIntent validation rejects invalid LLM output | unit | `pytest tests/test_llm_intent_parser.py::test_invalid_intent -x` | Wave 0 |
| AIGEN-02 | Component suggestion returns valid library_id values | unit (mocked) | `pytest tests/test_llm_component_suggester.py -x` | Wave 0 |
| AIGEN-03 | Design critic identifies spatial issues from spatial context | unit (mocked) | `pytest tests/test_llm_design_critic.py -x` | Wave 0 |
| AIGEN-03 | Spatial context builder produces valid LLM input | unit | `pytest tests/test_llm_context_builder.py -x` | Wave 0 |
| AIGEN-04 | Error fixer converts violations to valid operations | unit (mocked) | `pytest tests/test_llm_error_fixer.py -x` | Wave 0 |
| AIGEN-04 | Refinement loop converges within iteration cap | integration (mocked) | `pytest tests/test_llm_refinement.py -x` | Wave 0 |
| AIGEN-05 | End-to-end: NL -> valid .kicad_sch passing ERC | integration | `pytest tests/test_llm_e2e.py::test_voltage_regulator -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_llm*.py -x -q`
- **Per wave merge:** `pytest tests/ -x --tb=short`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_llm_intent_parser.py` -- covers AIGEN-01
- [ ] `tests/test_llm_component_suggester.py` -- covers AIGEN-02
- [ ] `tests/test_llm_design_critic.py` -- covers AIGEN-03
- [ ] `tests/test_llm_error_fixer.py` -- covers AIGEN-04
- [ ] `tests/test_llm_context_builder.py` -- covers AIGEN-03 (spatial context)
- [ ] `tests/test_llm_refinement.py` -- covers AIGEN-04 (loop)
- [ ] `tests/test_llm_e2e.py` -- covers AIGEN-05
- [ ] `tests/conftest_llm.py` -- shared fixtures (mock Anthropic client, sample intents)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | API key via environment variable, never hardcoded |
| V4 Access Control | yes | Token budget enforcement, iteration caps |
| V5 Input Validation | yes | Pydantic model validation on all LLM output |
| V6 Cryptography | no | No cryptographic operations in this phase |
| V8 Data Protection | yes | No user data stored; KiCad files stay local |

### Known Threat Patterns for LLM Integration

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection via KiCad file content | Tampering | Sanitize all file content before including in prompts; wrap in data boundaries |
| LLM generating destructive operations | Tampering | Validate all operations through existing Pydantic schema; enforce 1000-op cap |
| API key exposure | Information Disclosure | Environment variable only; never logged or included in error messages |
| Infinite refinement loop (cost attack) | Denial of Service | Hard cap 10 iterations; per-call timeout; token budget limits |
| LLM hallucinating invalid operations | Tampering | Pydantic validation rejects structurally invalid ops; `target_file` path traversal check |

## Sources

### Primary (HIGH confidence)
- Anthropic SDK v0.61.0 installed and verified locally: tool use, extended thinking, prompt caching APIs confirmed via package inspection
- Existing codebase: `generation/intent.py`, `generation/pipeline.py`, `generation/refinement.py`, `generation/evaluation.py`, `ops/schema.py`, `spatial/query.py`, `spatial/primitives.py` -- all read and verified
- `get_operation_schema()` verified to produce valid 51KB JSON Schema with `$defs`, `properties`, `required`, `type` keys
- `GenerationIntent.model_json_schema()` verified to produce valid 7KB JSON Schema

### Secondary (MEDIUM confidence)
- Anthropic tool use documentation: structured output via `tools` parameter with `input_schema` [CITED: docs.anthropic.com/en/docs/build-with-claude/tool-use]
- Anthropic extended thinking documentation: `thinking` parameter with `budget_tokens` [CITED: docs.anthropic.com/en/docs/build-with-claude/extended-thinking]
- Anthropic prompt caching documentation: `cache_control` parameter, 1.25x write / 0.1x hit pricing [CITED: docs.anthropic.com/en/docs/build-with-claude/prompt-caching]

### Tertiary (LOW confidence)
- Model performance comparison (Sonnet 4 vs Opus 4 for spatial reasoning): Not benchmarked; assumed Sonnet 4 sufficient [ASSUMED]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - anthropic SDK verified locally, all existing packages confirmed
- Architecture: HIGH - tool use pattern is standard Anthropic SDK practice; existing codebase provides clear integration points
- Pitfalls: HIGH - based on known LLM integration patterns and verified codebase constraints
- Component suggestion: MEDIUM - KiCad library enumeration approach not yet validated in code
- Spatial reasoning quality: LOW - depends on Claude's spatial reasoning capability, not yet benchmarked

**Research date:** 2026-05-23
**Valid until:** 2026-06-22 (30 days; SDK and API patterns are stable but model names may change)
