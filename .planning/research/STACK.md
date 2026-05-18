# Stack Research

**Domain:** KiCad 10+ automation agent (Python library + GSD Skill)
**Researched:** 2026-05-17
**Confidence:** HIGH

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.11+ | Runtime | Best KiCad library ecosystem, dataclass support, type hints, match statements. 3.11 is the sweet spot of features and compatibility. |
| kiutils | 1.4.8 | Primary KiCad file parser/serializer | KiCad-specific dataclass-based AST. Handles .kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod natively. SCM-friendly (deterministic output). Actively maintained with KiCad 10 format additions (knockout, net_tie_pad_groups, private_layers, bus_alias). HIGH confidence. |
| pydantic | 2.12.5 | JSON operation schema validation | Validates LLM intent JSON against strict schemas before any AST mutation. Generates JSON Schema for skill definitions. v2 is significantly faster than v1 with Rust core. HIGH confidence. |
| kicad-cli | 10.0.1 | ERC/DRC validation gates | Official KiCad CLI tool. Runs ERC on schematics and DRC on PCBs. The authoritative validation source — not reimplemented checks. Installed locally at /usr/local/bin/kicad-cli. HIGH confidence. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sexpdata | 1.0.0 | Raw S-expression parser/serializer | Fallback for KiCad file structures kiutils does not yet cover. Handles arbitrary S-expressions when you need to parse unknown or custom KiCad syntax. Also useful for parsing kicad-cli output. MEDIUM confidence (stable but not KiCad-specific). |
| networkx | 3.4.2 | Graph analysis for net connectivity | Analyzing net connectivity, component relationships, bus topology, and dependency graphs. Essential for net consistency verification between schematic and PCB. HIGH confidence. |
| difftastic | latest | Syntax-aware diffs | Structural diffs for S-expressions. Far superior to text-based diff for deeply nested KiCad files. Not yet installed locally — needs `brew install difftastic`. HIGH confidence for the tool, LOW confidence on exact version (not yet installed). |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest | Test framework | Use with pytest-cov for coverage reporting. Test fixtures should include sample .kicad_sch, .kicad_pcb files for round-trip validation. |
| mypy | Static type checking | Enforce type safety on Pydantic models and kiutils dataclass interactions. Use `--strict` mode. |
| ruff | Linter + formatter | Replaces both flake8 and black. Fast, opinionated, zero-config. |
| kicad-cli | Validation gate | Run ERC/DRC in test suite via subprocess. Available on PATH at /usr/local/bin/kicad-cli. |

## Installation

```bash
# Core parsing and validation
pip install kiutils==1.4.8 pydantic==2.12.5

# S-expression fallback and graph analysis
pip install sexpdata==1.0.0 networkx==3.4.2

# Dev dependencies
pip install -D pytest pytest-cov mypy ruff

# System dependencies (macOS)
brew install difftastic
# kicad-cli is already installed with KiCad 10.0.1
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| kiutils | sexpdata (alone) | Only if kiutils cannot parse a specific KiCad 10 construct. sexpdata is lower-level and requires you to build your own AST layer. Never as primary parser. |
| kiutils | kigadgets | kigadgets wraps the pcbnew SWIG bindings, providing a higher-level scripting API. It is NOT an AST-level parser — it operates through KiCad's internal API. Different paradigm entirely. Useful if you need interactive scripting, not file-level editing. |
| kiutils | pcbnew Python API | The pcbnew module (SWIG bindings) requires a running KiCad instance or at minimum the KiCad Python environment. Not suitable for headless CI/CD or standalone tooling. Use only for interactive plugin development. |
| pydantic v2 | marshmallow | marshmallow is more flexible for complex serialization but slower and less type-safe. Pydantic v2's Rust core and native JSON Schema generation make it the clear choice for LLM intent validation. |
| pydantic v2 | jsonschema (stdlib) | jsonschema only validates — it does not give you typed Python objects with IDE autocomplete. Pydantic gives both validation AND typed access. |
| kicad-cli | Custom ERC/DRC implementation | Reimplementing KiCad's electrical and design rule checks is a multi-year project. kicad-cli is the official, maintained, authoritative source. No contest. |
| difftastic | standard git diff | Standard diff treats S-expressions as text, producing noisy, meaningless line-level changes. difftastic understands syntax structure, producing meaningful structural diffs. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Regex-based KiCad parsing | KiCad S-expressions are deeply nested with context-dependent syntax. Regex cannot handle arbitrary nesting depth. Every edge case becomes a new regex bug. | kiutils for structured parsing, sexpdata for raw S-expression handling |
| Direct text/string manipulation of KiCad files | A single misplaced parenthesis corrupts the entire file. UUID references, symbol links, and net connections are fragile. The LLM must never emit raw text edits. | AST mutation via kiutils objects, validated through operation schema |
| Raw LLM text output as KiCad content | LLMs cannot reliably produce valid S-expressions. Parentheses nesting, UUID format, ordering constraints, and symbol references will all break. | JSON operation schema (Pydantic) that the tool layer translates to AST mutations |
| kigadgets as primary parser | It wraps pcbnew SWIG bindings, not the file format. Requires KiCad runtime. Not suitable for headless file editing. | kiutils for file-level parsing and serialization |
| circuit-synth | Different paradigm — it generates KiCad files from Python code (code-to-KiCad), not edits existing files (KiCad-to-AST-to-KiCad). Not applicable to this project's mutation-focused architecture. | kiutils + pydantic operation schema |
| atopile | Declarative HDL for PCB design. Generates designs from descriptions. Not a KiCad file editor. Different problem space entirely. | kiutils + pydantic operation schema |
| BeautifulSoup / HTML parsers | Not S-expression parsers. Will not work on KiCad file format. | kiutils or sexpdata |
| dataclasses (stdlib) for operation schema | No built-in validation, no JSON Schema generation, no serialization control. | pydantic v2 — dataclasses with validation superpowers |

## Stack Patterns by Variant

**If kiutils cannot parse a specific KiCad 10 construct:**
- Use sexpdata to parse the raw S-expression
- Build a minimal internal representation
- Report the gap upstream to kiutils
- This should be rare — kiutils 1.4.8 covers KiCad 10 format additions

**If a file type is not supported by kiutils:**
- Use sexpdata as the universal fallback parser
- Build a thin dataclass wrapper for the unknown file type
- Serialize back through sexpdata
- Contribute the parser back to kiutils if it proves useful

**If running in CI/CD without KiCad installed:**
- All parsing and mutation works without KiCad (kiutils is standalone)
- ERC/DRC validation is the only step requiring kicad-cli
- Structure tests as: parse, mutate, serialize, validate-structure
- Skip ERC/DRC gates in CI if kicad-cli unavailable, but flag it

**If difftastic is not available:**
- Fall back to standard git diff with increased context lines (-U10)
- Accept noisier diffs as a temporary compromise
- Install difftastic as soon as possible

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| kiutils 1.4.8 | KiCad 10.0.x | Latest release includes KiCad 10 format additions. Track releases for new KiCad format features. |
| kiutils 1.4.8 | Python 3.8+ | Requires Python 3.8 minimum, but 3.11+ recommended for this project. |
| pydantic 2.12.x | Python 3.8+ | v2 is a major breaking change from v1. Use v2 exclusively. |
| sexpdata 1.0.0 | Python 3.x | Stable, simple, no compatibility concerns. |
| networkx 3.4.x | Python 3.10+ | v3.x dropped Python 3.9 support. Compatible with 3.11+. |
| kicad-cli 10.0.1 | KiCad 10.0.x | Ships with KiCad installation. Version matches KiCad installation. |
| difftastic | Any | System tool, no Python dependency. Install via brew on macOS. |

## Confidence Assessment

| Technology | Confidence | Justification |
|------------|------------|---------------|
| kiutils as primary parser | HIGH | Context7 docs confirm KiCad-specific AST, active maintenance, KiCad 10 support. Verified locally installed v1.4.8. |
| pydantic v2 for schema | HIGH | Industry standard, verified locally at v2.12.5. Rust core for performance. JSON Schema generation for skill definitions. |
| kicad-cli for validation | HIGH | Official KiCad tool. Verified locally at v10.0.1. Only authoritative ERC/DRC source. |
| sexpdata as fallback | MEDIUM | Stable generic S-expression parser, but not KiCad-specific. May need wrapper logic for KiCad-specific constructs. |
| networkx for graph analysis | HIGH | Standard Python graph library. Net connectivity and topology analysis is a textbook graph problem. Verified locally at v3.4.2. |
| difftastic for diffs | HIGH (tool) / LOW (install) | Tool is correct for the job. Not yet installed locally — needs `brew install difftastic`. |

## Sources

- Context7 library `kiutils` — fetched parser API, file type support, SCM-friendly design
- Context7 library `pydantic` — fetched v2 model validation, JSON Schema generation
- Context7 library `networkx` — fetched graph analysis APIs
- GitHub `manufactureq/kiutils` releases — confirmed v1.4.8 latest, KiCad 10 format additions
- GitHub `oilshell/oilseed` (sexpdata) — confirmed v1.0.0, stable maintenance
- Local verification — `pip show kiutils sexpdata networkx pydantic`, `kicad-cli --version`, `which difftastic`
- KiCad 10.0.0 release notes — confirmed release date 2026-03-20
- kiutils README — confirmed .kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod support

---
*Stack research for: kicad-agent (KiCad 10+ automation agent)*
*Researched: 2026-05-17*
