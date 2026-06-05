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

## Project Capability Map

Every module below is in `src/kicad_agent/`. Use these before writing ad-hoc code.

| Domain | Module | What it does |
|--------|--------|-------------|
| **Component Data** | `crawler/easyeda_api.py` | Search JLCPCB/EasyEDA for components (LCSC numbers), download CAD data with real pin coordinates and footprints |
| | `crawler/bulk_fetcher.py` | Batch-fetch CAD data for multiple LCSC parts |
| | `crawler/github_discovery.py` | Discover KiCad libraries from GitHub |
| | `mcp/server.py` | MCP stdio server exposing 4 tools: `search_components`, `get_component_details`, `search_fetch`, `suggest_components` |
| | `mcp/tools.py` | Formatted search/fetch tool implementations wrapping EasyEdaClient |
| | `llm/component_suggester.py` | LLM-based component suggestion from functional descriptions, returns validated `library_id` values |
| | `project/adi_library/` | ADI (Analog Devices) footprint/symbol library: SamacSys client, local cache, fetcher, KiCad lib-table registration |
| **File Operations** | `ops/schema.py` | 75 Pydantic operation models (add_component, create_symbol, connect_pins, repair, validate, etc.) |
| | `ops/executor.py` | Operation dispatch with per-type handlers, transaction support, undo |
| | `ops/create_file.py` | Create `.kicad_sch`, `.kicad_pcb`, `.kicad_pro`, `.kicad_sym` files |
| | `ops/add_component.py` | Add schematic/PCB components with library resolution |
| | `ops/_schema_wire.py` | `add_wire`, `add_label`, `add_power`, `add_no_connect`, `add_junction`, `connect_pins` |
| | `ops/repair.py` | wire_snapping, orphaned label removal, no-connect placement, power flag, symbol library update, shorted net fix, pin type fix |
| | `ops/swap_symbol.py` | `swap_symbol`, `embed_symbol` (copy symbol from library into schematic) |
| | `ops/remove_ops.py` | Remove wires, labels, junctions, no-connects, components |
| | `ops/array_replicate.py` | Array-replicate components in grid/linear patterns |
| | `ops/duplicate_component.py` | Clone a component instance |
| | `ops/connectivity_query.py` | Query connectivity components, net adjacency |
| **Placement** | `placement/engine.py` | Hybrid placement: ML prediction → rule-based fallback → DRC validation → scoring |
| | `placement/graph.py` | Netlist-to-graph conversion for placement optimization |
| | `placement/interactive.py` | Interactive placement with user-fixed components and keepout zones |
| | `placement/scoring.py` | Wire-length, clearance, edge penalties for placement quality |
| | `placement/validation.py` | DRC clearance checks for placed components |
| **Schematic Routing** | `schematic_routing/target_finder.py` | Find same-net pins as routing targets within distance |
| | `schematic_routing/wire_router.py` | Generate L-shape/same-axis wire modifications toward targets |
| | `schematic_routing/schematic_graph.py` | Parse schematic wire/pin/junction geometry into a routing graph |
| | `schematic_routing/net_resolver.py` | Resolve which components belong to which nets |
| | `schematic_routing/netlist_parser.py` | Parse KiCad netlist for connectivity info |
| | `schematic_routing/batch_executor.py` | Batch-wire connections with net verification |
| **PCB Routing** | `routing/pathfinder.py` | A* pathfinding over routing graph |
| | `routing/graph.py` | Build routing grid with obstacle avoidance |
| | `routing/bridge.py` | Route-to-segments conversion for PCB traces |
| | `routing/constraints.py` | Clearance, width, via constraints |
| | `routing/diff_pair.py` | Differential pair routing |
| **Generation** | `generation/intent.py` | `GenerationIntent`: structured design spec with components, nets, power |
| | `generation/pipeline.py` | `generate_design()`: intent → template board → operations → validation → export |
| | `generation/template_schematic.py` | Auto-generate schematic from intent: placement, wiring, power symbols |
| | `generation/template_board.py` | Auto-generate PCB from intent: board outline, component placement |
| | `generation/op_planner.py` | Dependency-ordered operation sequences from intent |
| | `generation/placement.py` | Component placement utilities for generated designs |
| | `generation/refinement.py` | ERC/DRC-driven refinement loop |
| **Validation** | `validation/format_check.py` | KiCad 10 format compliance (at rotation, wire stroke, UUIDs, parens) |
| | `validation/symbol_resolution.py` | Check symbol lib_ids resolve against embedded, project, and global tables |
| | `validation/symbol_mismatch.py` | Compare embedded symbols against library originals |
| | `validation/grid_check.py` | Off-grid pin/wire endpoint detection |
| | `validation/structural.py` | Structural operation pre-validation (library_id format, required fields) |
| | `validation/erc_drc.py` | Run KiCad CLI ERC/DRC and parse reports |
| | `validation/spatial_drc.py` | Spatial DRC: clearance violations, overlapping footprints |
| | `validation/pipeline.py` | End-to-end validation pipeline (structural → format → ERC) |
| | `validation/roundtrip.py` | Parse → serialize → re-parse round-trip verification |
| **LLM Integration** | `llm/intent_parser.py` | Parse natural language design intents into GenerationIntent |
| | `llm/design_critic.py` | LLM board layout review: clearance, thermal, routing issues |
| | `llm/error_fixer.py` | LLM ERC/DRC error fix suggestions with operation sequences |
| | `llm/pipeline.py` | Full LLM design pipeline |
| | `llm/refinement.py` | ERC/DRC-driven iterative refinement with LLM fixes |
| | `llm/backend.py` | Multi-provider LLM backend (Claude, OpenAI, local) |
| | `llm/tools.py` | LLM tool definitions for component suggestion |
| **Analysis** | `analysis/connectivity.py` | Net connectivity graph via networkx |
| **Spatial** | `spatial/query.py` | Shapely STRtree spatial queries (proximity, containment, clearance) |
| | `spatial/primitives.py` | Bounding boxes, spatial primitives |
| | `spatial/extractor.py` | Extract spatial data from PCB/schematic files |
| | `spatial/reasoning_chains.py` | Chain-of-thought spatial reasoning for layout issues |
| **Cross-file** | `crossfile/propagation.py` | Propagate symbol/footprint library changes across all project files |
| | `crossfile/atomic.py` | Atomic operations spanning multiple KiCad files |
| | `crossfile/diff.py` | Structural diffs for change tracking |
| | `crossfile/project_context.py` | Project file discovery, library path extraction from `.kicad_pro` |
| **Export** | `export/bom.py` | Bill of materials generation |
| | `export/gerber.py` | Gerber file export |
| | `export/general.py` | General export utilities |
| **LTspice** | `ltspice/` | Parse/write LTspice `.asc` files, net graph, KiCad symbol → LTspice mapping |
| **Training** | `training/` | GRPO training, board/schematic chains, reward models, dataset generation |
| **AI Tracking** | `ai_tracking/` | AI agent operation tracking, gap analysis, statistics |
| **Infrastructure** | `ir/` | SchematicIR, PcbIR, SymbolLibIR, Transaction, undo stack |
| | `parser/` | Parse all KiCad file types (schematic, PCB, symbol lib, footprint) |
| | `serializer/` | Serialize with normalizer (sci notation → fixed, at rotation, whitespace) |
| | `handler.py` | Top-level `handle_operation()` entry point |

---

## Known Pitfalls

The following mistakes caused real failures during schematic construction. Do not repeat them.

1. **Don't skip the project's component search capabilities.** The project has a working MCP component search server (`src/kicad_agent/mcp/server.py`) for JLCPCB/EasyEDA, an EasyEDA crawler API (`src/kicad_agent/crawler/easyeda_api.py`), and an LLM component suggester (`src/kicad_agent/llm/component_suggester.py`). Never hand-write custom symbols for off-the-shelf ICs when these tools can retrieve real CAD data including pin definitions. Also has an ADI library fetcher (`src/kicad_agent/project/adi_library/`).

2. **Verify library IDs exist on this machine before `add_component`.** Standard KiCad library names vary across versions. On KiCad 10, connectors are `Connector:Conn_01x02_Pin` (not `_Male`), polarized capacitors are `Device:C_Polarized_Small` (not `Device:CP`). Check `validate_schematic` output for unresolved references before building connections, and use `swap_symbol` when needed.

3. **Never hand-estimate pin coordinates for wiring.** Use `connect_pins` (or `SchematicIR.get_pin_positions()` for custom scripts). Hand-drawn coordinate wires produced 334 ERC violations on first run. The `repair_wire_snapping` operation only snaps endpoints within 0.01mm tolerance -- it cannot fix wires placed at guessed positions.

4. **Prefer orthogonal routing.** `connect_pins` defaults to orthogonal (horizontal then vertical). Direct diagonal wires cause `wire_dangling` ERC errors in KiCad unless endpoints align perfectly. Orthogonal corners automatically get junctions.

5. **Run KiCad CLI ERC early and often.** The project's internal `validate_schematic` checks structure (format, resolution, power symbols, annotation) but does NOT catch KiCad's native electrical rule violations. `pin_not_connected`, `wire_dangling`, `power_pin_not_driven`, `endpoint_off_grid` all require `kicad-cli sch erc`.

6. **Symbol pin spacing must match KiCad grid.** Our STM32F103C8T6 custom symbol used 2.5 mm pin spacing instead of 2.54 mm, causing 155 off-grid warnings. When creating symbols in-house, pin coordinates should be multiples of 1.27 mm (50 mil) at minimum.

7. **Normalizer rules must exclude XY-only KiCad elements.** `no_connect` and `junction` in KiCad 10 accept only two-coordinate `(at x y)`, not `(at x y 0)`. The normalizer's `_fix_at_rotation` must skip these. Same for the format checker.

8. **`get_pin_positions()` originally missed custom symbol pins.** It only collected pins from `lib_sym.units[*].pins`, but symbols created by `create_symbol` (like our STM32/AMS1117) store pins directly on `lib_sym.pins`. Fixed now -- verify custom symbol pins appear in position queries before building large connection lists.

9. **On Windows, use `os.replace` not `os.rename` in atomic writes.** `os.rename` fails on Windows when the target already exists. `create_file.py` was fixed to use `os.replace` with resolved paths.

10. **Clean old hand-drawn wires before rebuilding with `connect_pins`.** Old estimated wires create phantom endpoints that confuse ERC even after new correct wires are added. Remove them via `remove_dangling_wires` or by clearing `graphicalItems`.

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

