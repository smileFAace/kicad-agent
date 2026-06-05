# AGENTS.md - Project Notes for AI Agents

This project provides AI-safe structural editing for KiCad files. The core rule is that agents should not directly edit KiCad S-expression files (`.kicad_sch`, `.kicad_pcb`, `.kicad_sym`, `.kicad_mod`) as raw text. Build validated JSON operations and run them through the Python backend so parsing, AST mutation, serialization, rollback, and ERC/DRC validation stay in the controlled path.

## Read First

- `README.md` explains the product direction, CLI usage, architecture, training pipeline, and MCP component search server.
- `skills/SKILL.md` is the Claude Code skill entry point for `/kicad-agent`.
- `skills/prompt.md` documents operation payloads and examples. Treat this as useful guidance, but verify against the Python schema when exact fields matter.
- `.claude/CLAUDE.md` contains local workflow notes and KiCad CLI commands.
- `src/kicad_agent/ops/schema.py` is the source of truth for supported operation models.
- `src/kicad_agent/ops/executor.py` is the source of truth for operation dispatch and execution behavior.

## Source of Truth

The implementation currently registers 75 operation types in `src/kicad_agent/ops/schema.py`. `skills/prompt.md` should mirror that schema for agent-facing field documentation, but when there is a conflict, trust the code schema and executor first.

Use the current operation envelope everywhere:

```json
{"root": {"op_type": "add_component", "target_file": "example.kicad_sch"}}
```

Avoid fixed local paths in examples. Commands should run from the current repository or rely on the installed `kicad-agent` package.

## Development Rules

- Prefer existing operation handlers, schema models, parsers, serializers, and validation utilities over ad hoc file manipulation.
- Read the target KiCad file before constructing an operation so references, coordinates, nets, and library IDs are grounded in the current design.
- Keep each operation atomic: one mutation, one target file, unless using an existing cross-file operation that explicitly models a multi-file change.
- After schematic edits, run ERC when KiCad CLI is available. After PCB edits, run DRC when KiCad CLI is available. Report clearly when validation cannot be run.
- Do not edit generated cache files such as `__pycache__` artifacts.

## Current Schematic Editing Lessons

The backend is valuable for AI-safe KiCad editing: agents can create projects and schematics, create and embed symbols, place components, add power symbols and wires, swap symbols, serialize through the normalizer, and run structural validation without raw S-expression editing. Use those capabilities first.

The current gap is schematic connectivity at the circuit-intent level. `add_wire` only draws a wire between explicit coordinates, and existing repair/snapping only adjusts endpoints already close to real pins. There is no operation that connects by semantic pin or net intent, such as `connect_pins(U1.34, J3.2)` or `connect_net("+3V3", ["U1.24", "C1.1"])`. Do not rely on hand-estimated coordinates for nontrivial schematics; KiCad ERC will catch the mismatch.

Next implementation target: add a backend operation that resolves real pin endpoints from embedded/library symbols via `SchematicIR.get_pin_positions()`, accepts reference/pin descriptors, generates exact wire endpoints or labels, and verifies the result with KiCad CLI ERC. This should become the preferred path for building minimal systems and other schematic workflows.

## Useful Commands

```bash
python -m pytest
ruff check src tests
mypy src
kicad-agent --schema
kicad-agent --dry-run operation.json
kicad-cli sch erc <file.kicad_sch>
kicad-cli pcb drc <file.kicad_pcb>
```

