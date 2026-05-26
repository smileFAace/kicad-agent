# Requirements: kicad-agent

**Defined:** 2026-05-17
**Core Value:** LLM -> intent JSON -> AST mutation -> valid KiCad file. Zero corruption, every time.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Foundation

- [x] **FND-01**: Parse .kicad_sch files into structured AST with full property coverage
- [x] **FND-02**: Parse .kicad_pcb files into structured AST with full property coverage
- [x] **FND-03**: Parse .kicad_sym (symbol library) files into structured AST
- [x] **FND-04**: Parse .kicad_mod (footprint library) files into structured AST
- [x] **FND-05**: Round-trip fidelity: parse -> serialize produces byte-identical or semantically equivalent output for all file types
- [x] **FND-06**: UUID integrity preservation across all operations (no dangling references)
- [x] **FND-07**: Transaction-based mutation with rollback capability
- [x] **FND-08**: Deterministic, SCM-friendly serialization (stable output ordering)

### Operation Schema

- [x] **OPS-01**: JSON operation schema for all edit intents (Pydantic v2 models with JSON Schema export)
- [x] **OPS-02**: Operation validation: reject structurally invalid intents before mutation
- [x] **OPS-03**: Operation execution: translate validated intent -> IR mutation -> serialized file

### Component Operations

- [x] **COMP-01**: Add component to schematic with symbol reference and property defaults
- [x] **COMP-02**: Remove component from schematic (with net stub cleanup)
- [x] **COMP-03**: Duplicate component or section with new UUIDs and references
- [x] **COMP-04**: Replicate component in array pattern (linear, circular, matrix)
- [x] **COMP-05**: Move/reposition component with coordinate precision (4 decimal schematic, 6 decimal PCB)
- [x] **COMP-06**: Modify component properties (value, footprint, reference, custom fields)

### Net Operations

- [x] **NET-01**: Add net with named or auto-generated net name
- [x] **NET-02**: Remove net with pin disconnect and stub cleanup
- [x] **NET-03**: Rename net with propagation to all connected pins
- [x] **NET-04**: Bus operations: add/remove/rename bus with member net management
- [x] **NET-05**: Net connectivity graph analysis via networkx

### Reference Management

- [x] **REF-01**: Renumber references with configurable prefix and sequencing
- [x] **REF-02**: Validate reference uniqueness across schematic sheets
- [x] **REF-03**: Cross-reference check: verify symbol references resolve to valid library entries
- [x] **REF-04**: Annotate schematic: auto-assign references to unannotated components

### Footprint Management

- [x] **FP-01**: Assign footprint to component with library nickname resolution
- [x] **FP-02**: Swap footprint on existing component (preserves connections)
- [x] **FP-03**: Validate footprint existence in configured library paths
- [x] **FP-04**: Footprint-to-symbol pin mapping verification

### Validation

- [x] **VAL-01**: ERC gate via kicad-cli with structured result parsing (pass/fail/warning)
- [x] **VAL-02**: DRC gate via kicad-cli with structured result parsing
- [x] **VAL-03**: Net consistency verification between schematic and PCB netlists
- [x] **VAL-04**: Structural/syntax-aware diff generation for S-expressions (difftastic integration)
- [x] **VAL-05**: Pre-mutation structural validation (catch invalid operations before execution)
- [x] **VAL-06**: Automated error recovery: rollback to last valid state on validation failure
- [x] **VAL-07**: Round-trip fidelity regression test suite (parse -> serialize -> compare)

### Cross-File Operations

- [ ] **XFILE-01**: Schematic <-> PCB atomic operations (maintain consistency during edits)
- [x] **XFILE-02**: Symbol library reference update propagation
- [x] **XFILE-03**: Footprint library reference update propagation
- [x] **XFILE-04**: Project context detection: auto-discover project root, libraries, configuration

### GSD Skill Integration

- [x] **SKILL-01**: GSD Skill manifest with kicad-agent capabilities
- [x] **SKILL-02**: Skill handler: route operations from Claude to Python backend
- [x] **SKILL-03**: CLI wrapper for direct terminal usage (independent of Claude)
- [x] **SKILL-04**: Project context renderer: summarize KiCad project state for AI context

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Hierarchical Sheets

- **HIER-01**: Parse and navigate hierarchical sheet structure
- **HIER-02**: Propagate changes across sheet boundaries
- **HIER-03**: Sheet pin/bus interface management

### Advanced Analysis

- **ANAL-01**: BOM generation from schematic
- **ANAL-02**: Cost estimation with component pricing
- **ANAL-03**: Design rule recommendations based on board constraints

### Multi-Project

- **MPROJ-01**: Workspace support for multi-board projects
- **MPROJ-02**: Cross-board net and reference management

### Visual Primitives (Phase 8)

Inspired by DeepSeek's "Thinking with Visual Primitives" — interleave spatial coordinates (points, bounding boxes, paths, regions) into AI reasoning chains about PCB layouts. Close the "Reference Gap" where natural language fails to precisely describe spatial relationships on a board.

- [ ] **VP-01**: Render PCB layers as images with coordinate grid overlay (KiCad Python API → rasterized images with mm-coordinate mapping)
- [ ] **VP-02**: Extract spatial primitives from parsed KiCad files: pin positions as points, component outlines as bounding boxes, trace routes as path trajectories, copper pours/keepouts as regions
- [ ] **VP-03**: Define visual primitive vocabulary for PCB: `<point x,y>`, `<box x1,y1,x2,y2>`, `<path [points...]>`, `<region x1,y1,x2,y2 type>`
- [ ] **VP-04**: Generate procedural PCB "maze routing" tasks — synthetic boards where the AI must find valid trace paths around obstacles using coordinate-grounded reasoning
- [ ] **VP-05**: Generate cold-start reasoning chains from DRC/ERC violation reports with spatial grounding (violation → coordinate → fix recommendation)
- [x] **VP-06**: Build spatial query API: "find all traces within X mm of point Y", "list components in region Z", "check clearance between component A and net B"
- [x] **VP-07**: AI review pipeline that outputs spatially-grounded DRC findings: "The via at <point> [45.2, 22.1] is 0.15mm from the trace <path> [...] — violates minimum clearance"
- [x] **VP-08**: Integration with existing Rick agents (SI Rick, PI Rick, EMC Rick, DFM Rick) to produce coordinate-grounded reports instead of text-only findings

### GRPO Spatial Reasoning Training (Phase 9)

DeepSeek-style RL training pipeline with coordinate-grounded reward signals on synthetic PCB maze data. Trains a reward model to score reasoning chains, then uses GRPO to optimize a policy for PCB spatial reasoning.

- [ ] **GRPO-01**: Synthetic data pipeline generating 100k+ maze-routing samples from the Phase 8 maze generator, with verified solutions and difficulty grading (easy/medium/hard/adversarial)
- [ ] **GRPO-02**: Cold-start reasoning chain synthesis at scale — DFS exploration traces, verified chains with coordinate grounding, difficulty-graded samples from maze solutions
- [ ] **GRPO-03**: Reward model architecture with per-step dense rewards (format correctness, reasoning quality, coordinate accuracy), multi-stage reward signals, and smooth penalty functions
- [ ] **GRPO-04**: GRPO training loop — policy generates chains, reward model scores them, policy updates via group-relative optimization
- [ ] **GRPO-05**: Reward hacking prevention — smooth penalty functions, multi-stage reward architecture, anomaly detection on reward distributions
- [ ] **GRPO-06**: Evaluation harness — held-out maze-routing tasks, baseline comparison, measurable improvement metrics, ablation studies
- [ ] **GRPO-07**: Reproducible training pipeline — single-command execution, configurable hyperparameters, deterministic seeding, training checkpoints

### AI-Driven PCB Generation (Phase 10)

Two-tier phase: first close the practical operations gap, then build generative AI on top. Tier 1 operations are independently valuable — a user who can "export Gerber files" or "fix all ERC errors" gets value immediately. Tier 2 generation requires Tier 1 as foundation.

**Tier 1: Complete the Operations Layer**

- [ ] **GEN-01**: Parse and modify project-level files: sym-lib-table, fp-lib-table (add/remove/list library entries), .kicad_dru (read/write custom DRC rules), .kicad_pro (read/modify project settings)
- [x] **GEN-02**: Manufacturing export wrappers via kicad-cli: Gerber, drill, BOM (with field customization and grouping), netlist (kicadsexpr, kicadxml), position files (ASCII, CSV), STEP 3D, PDF/SVG documentation, board statistics
- [ ] **GEN-03**: Schematic ERC repair: auto-fix wire snapping to pins, remove orphaned labels, detect shorted nets, fix pin_not_connected errors with no-connect markers
- [ ] **GEN-04**: Power net validation: check all power pins have connected power symbols, verify power nets span hierarchical sheets, detect missing GND/+3V3 before PCB work begins
- [ ] **GEN-05**: PCB copper zone operations: add/modify/fill copper pour zones with net assignment, layer selection, clearance, and priority settings
- [ ] **GEN-06**: Net class and design rule operations: assign net classes (Default, Power, etc.) with track width/via size/clearance, add custom DRC rules to .kicad_dru, board outline definition

**Tier 2: Build Generation on Top**

- [x] **GEN-07**: GenerationIntent schema (Pydantic) for converting natural language design parameters to structured operation sequences with board specs, component lists, and connection topology
- [x] **GEN-08**: Template board generator extending maze_generator pattern to create valid .kicad_pcb and .kicad_sch files from high-level parameters (board size, layer count, component list, net topology)
- [x] **GEN-09**: Component placement engine with clearance validation, spatial scoring, decoupling cap proximity heuristics, and LLM-driven operation-sequence planning
- [x] **GEN-10**: End-to-end generation pipeline: intent → template board → operation sequence → validation → manufacturing export, single-command execution
- [x] **GEN-11**: Iterative refinement loop: generate → validate (ERC/DRC) → feed violations back for fixes → repeat until clean (max 5 iterations)
- [x] **GEN-12**: Generation evaluation: DRC pass rate on simple designs (5-10 components), manufacturing output completeness check, comparison vs manual baseline

### LTspice Integration (Phase 11)

Parse LTspice .asc schematic files, extract components/nets/simulation commands, read .raw simulation results, and build net connectivity graphs from wire geometry.

- [x] **LTSPICE-01**: Parse LTspice .asc schematic files into structured component/net/simulation data via SpiceLib AscEditor
- [x] **LTSPICE-02**: Extract components with values, positions, orientations from .asc files
- [x] **LTSPICE-03**: Derive net connectivity graph from WIRE and FLAG statements using networkx
- [x] **LTSPICE-04**: Extract and parse simulation commands (.tran, .ac, .dc, .noise) from directives
- [x] **LTSPICE-05**: Read .raw simulation result files with voltage/current traces by node name

### ADI Footprint Library (Phase 12)

On-demand fetching of ADI manufacturer footprints, symbols, and 3D models into KiCad library format, with caching and library management.

- [ ] **ADI-01**: ADI footprints discoverable by part number via SamacSys Component Search Engine HTTP client; returns structured SearchResult with download availability or clear error message
- [ ] **ADI-02**: .kicad_mod footprint files download from SamacSys (or user-provided ZIP), validate with kiutils, and import into local footprint library registered in fp-lib-table
- [ ] **ADI-03**: .kicad_sym symbol files download from SamacSys (or user-provided ZIP), validate for KiCad format, and import into local symbol library registered in sym-lib-table
- [x] **ADI-04**: Library cache with JSON manifest prevents re-downloading previously fetched parts; cache persists across sessions and supports both automated and manual imports

### LLM Fine-Tuning (Phase 20)

SFT data preparation and supervised fine-tuning of a small LLM for PCB spatial reasoning.

- [ ] **LLM-01**: 15K training chains converted to ChatML instruction format with task-specific prompt templates (board analysis, routing assessment, spatial reasoning, component knowledge)
- [ ] **LLM-02**: Reward model quality filter scores all chains and removes bottom quartile (retain ~11K high-quality samples)
- [ ] **LLM-03**: QLoRA training infrastructure set up with HuggingFace transformers, 4-bit quantization, LoRA adapters (rank=16, alpha=32)
- [ ] **LLM-04**: SFT training on Qwen2.5-1.5B-Instruct completes with measurable improvement over base model on held-out test chains

### GRPO RL Fine-Tuning (Phase 21)

Reinforcement learning fine-tuning using the reward model as critic.

- [ ] **LLM-05**: GRPO training loop generates N chains per sample, scores with reward model, computes group-relative advantages
- [ ] **LLM-06**: Policy updates via PPO-clip with KL divergence penalty prevent catastrophic forgetting
- [ ] **LLM-07**: GRPO model achieves >85% discrimination rate (correct > corrupted) on held-out test set (up from 75% baseline)
- [ ] **LLM-08**: GRPO model scores higher than SFT baseline on all three reward dimensions (format, quality, accuracy)

### Agent Integration (Phase 22)

Wire the fine-tuned model into kicad-agent as its reasoning engine.

- [ ] **LLM-09**: Inference wrapper loads GRPO model and generates PCB reasoning chains in <2s per chain on MPS
- [ ] **LLM-10**: Best-of-N selection (N=4) picks chains scoring 20%+ higher than single-sample generation
- [ ] **LLM-11**: kicad-agent CLI `analyze` subcommand and Python API `generate_analysis(pcb_path)` expose fine-tuned model
- [ ] **LLM-12**: GSD Skill integration: Claude invokes `/kicad-agent analyze <pcb>` and receives scored spatial reasoning chain

## Out of Scope

| Feature | Reason |
|---------|--------|
| Auto-routing | Separate concern -- routing-rick agent handles this |
| Raw S-expression editing | Defeats the purpose of structural safety |
| KiCad 8.x/9.x backward compatibility | KiCad 10+ only, no legacy burden |
| GUI/editor integration | CLI and skill interface only for v1 |
| SPICE simulation | Separate concern, different toolchain |
| 3D model manipulation | Out of scope for v1 |
| CI/CD pipeline integration | KiBot's domain -- don't duplicate |
| Visual BOM generation | InteractiveHtmlBom's domain |
| Code-driven design (Python -> KiCad) | Circuit-Synth/atopile's domain |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FND-01 | Phase 1: Foundation | Complete |
| FND-02 | Phase 1: Foundation | Complete |
| FND-03 | Phase 1: Foundation | Complete |
| FND-04 | Phase 1: Foundation | Complete |
| FND-05 | Phase 1: Foundation | Complete |
| FND-06 | Phase 1: Foundation | Complete |
| VAL-07 | Phase 1: Foundation | Complete |
| FND-07 | Phase 2: Schema + IR | Complete |
| FND-08 | Phase 2: Schema + IR | Complete |
| OPS-01 | Phase 2: Schema + IR | Complete |
| OPS-02 | Phase 2: Schema + IR | Complete |
| OPS-03 | Phase 2: Schema + IR | Complete |
| VAL-01 | Phase 3: Validation Pipeline | Complete |
| VAL-02 | Phase 3: Validation Pipeline | Complete |
| VAL-03 | Phase 3: Validation Pipeline | Complete |
| VAL-05 | Phase 3: Validation Pipeline | Complete |
| VAL-06 | Phase 3: Validation Pipeline | Complete |
| COMP-01 | Phase 4: Component Operations | Complete |
| COMP-02 | Phase 4: Component Operations | Complete |
| COMP-03 | Phase 4: Component Operations | Complete |
| COMP-04 | Phase 4: Component Operations | Complete |
| COMP-05 | Phase 4: Component Operations | Complete |
| COMP-06 | Phase 4: Component Operations | Complete |
| NET-01 | Phase 5: Net/Ref/FP Operations | Complete |
| NET-02 | Phase 5: Net/Ref/FP Operations | Complete |
| NET-03 | Phase 5: Net/Ref/FP Operations | Complete |
| NET-04 | Phase 5: Net/Ref/FP Operations | Complete |
| NET-05 | Phase 5: Net/Ref/FP Operations | Complete |
| REF-01 | Phase 5: Net/Ref/FP Operations | Complete |
| REF-02 | Phase 5: Net/Ref/FP Operations | Complete |
| REF-03 | Phase 5: Net/Ref/FP Operations | Complete |
| REF-04 | Phase 5: Net/Ref/FP Operations | Complete |
| FP-01 | Phase 5: Net/Ref/FP Operations | Complete |
| FP-02 | Phase 5: Net/Ref/FP Operations | Complete |
| FP-03 | Phase 5: Net/Ref/FP Operations | Complete |
| FP-04 | Phase 5: Net/Ref/FP Operations | Complete |
| XFILE-01 | Phase 6: Cross-File + Analysis | Pending |
| XFILE-02 | Phase 6: Cross-File + Analysis | Complete |
| XFILE-03 | Phase 6: Cross-File + Analysis | Complete |
| XFILE-04 | Phase 6: Cross-File + Analysis | Complete |
| VAL-04 | Phase 6: Cross-File + Analysis | Complete |
| SKILL-01 | Phase 7: GSD Skill Integration | Complete |
| SKILL-02 | Phase 7: GSD Skill Integration | Complete |
| SKILL-03 | Phase 7: GSD Skill Integration | Complete |
| SKILL-04 | Phase 7: GSD Skill Integration | Complete |
| VP-01 | Phase 8: Visual Primitives | Complete | 08-01 |
| VP-02 | Phase 8: Visual Primitives | Complete | 08-01 |
| VP-03 | Phase 8: Visual Primitives | Complete | 08-01 |
| VP-04 | Phase 8: Visual Primitives | Complete | 08-02 |
| VP-05 | Phase 8: Visual Primitives | Complete | 08-02 |
| VP-06 | Phase 8: Visual Primitives | Complete | 08-03 |
| VP-07 | Phase 8: Visual Primitives | Complete | 08-03 |
| VP-08 | Phase 8: Visual Primitives | Complete | 08-04 |
| GRPO-01 | Phase 9: GRPO Spatial Reasoning Training | Pending | 09-01 |
| GRPO-02 | Phase 9: GRPO Spatial Reasoning Training | Pending | 09-02 |
| GRPO-03 | Phase 9: GRPO Spatial Reasoning Training | Pending | 09-03 |
| GRPO-04 | Phase 9: GRPO Spatial Reasoning Training | Pending | 09-04 |
| GRPO-05 | Phase 9: GRPO Spatial Reasoning Training | Pending | 09-03 |
| GRPO-06 | Phase 9: GRPO Spatial Reasoning Training | Pending | 09-04 |
| GRPO-07 | Phase 9: GRPO Spatial Reasoning Training | Pending | 09-04 |
| GEN-01 | Phase 10: AI-Driven PCB Generation | Pending | 10-01 |
| GEN-02 | Phase 10: AI-Driven PCB Generation | Complete | 10-02 |
| GEN-03 | Phase 10: AI-Driven PCB Generation | Pending | 10-03 |
| GEN-04 | Phase 10: AI-Driven PCB Generation | Pending | 10-03 |
| GEN-05 | Phase 10: AI-Driven PCB Generation | Pending | 10-03 |
| GEN-06 | Phase 10: AI-Driven PCB Generation | Pending | 10-01, 10-03 |
| GEN-07 | Phase 10: AI-Driven PCB Generation | Complete | 10-04 |
| GEN-08 | Phase 10: AI-Driven PCB Generation | Complete | 10-04 |
| GEN-09 | Phase 10: AI-Driven PCB Generation | Complete | 10-05 |
| GEN-10 | Phase 10: AI-Driven PCB Generation | Complete | 10-06 |
| GEN-11 | Phase 10: AI-Driven PCB Generation | Complete | 10-06 |
| GEN-12 | Phase 10: AI-Driven PCB Generation | Complete | 10-06 |
| LTSPICE-01 | Phase 11: LTspice Integration | Complete | 11-01 |
| LTSPICE-02 | Phase 11: LTspice Integration | Complete | 11-01 |
| LTSPICE-03 | Phase 11: LTspice Integration | Complete | 11-03 |
| LTSPICE-04 | Phase 11: LTspice Integration | Complete | 11-01 |
| LTSPICE-05 | Phase 11: LTspice Integration | Complete | 11-02 |
| ADI-01 | Phase 12: ADI Footprint Library | Pending | 12-02, 12-03 |
| ADI-02 | Phase 12: ADI Footprint Library | Pending | 12-03 |
| ADI-03 | Phase 12: ADI Footprint Library | Pending | 12-03 |
| ADI-04 | Phase 12: ADI Footprint Library | Complete | 12-01, 12-03 |
| RW-01 | Phase 13: Real-World Training Pipeline | Complete | 13-01 |
| RW-02 | Phase 13: Real-World Training Pipeline | Complete | 13-02 |
| RW-03 | Phase 13: Real-World Training Pipeline | Complete | 13-02 |
| RW-04 | Phase 13: Real-World Training Pipeline | Complete | 13-03 |
| RW-05 | Phase 13: Real-World Training Pipeline | Complete | 13-03 |
| BIDI-01 | Phase 14: Bidirectional KiCad-LTspice | Complete | 14-02 |
| BIDI-02 | Phase 14: Bidirectional KiCad-LTspice | Complete | 14-01 |
| BIDI-03 | Phase 14: Bidirectional KiCad-LTspice | Complete | 14-02 |
| BIDI-04 | Phase 14: Bidirectional KiCad-LTspice | Complete | 14-03 |
| AIGEN-01 | Phase 15: AI Generation Wiring | Complete | 15-01 |
| AIGEN-02 | Phase 15: AI Generation Wiring | Complete | 15-01 |
| AIGEN-03 | Phase 15: AI Generation Wiring | Complete | 15-02 |
| AIGEN-04 | Phase 15: AI Generation Wiring | Complete | 15-03 |
| AIGEN-05 | Phase 15: AI Generation Wiring | Complete | 15-04 |
| PLACE-01 | Phase 16: Component Placement AI | Complete | 16-01 |
| PLACE-02 | Phase 16: Component Placement AI | Complete | 16-02 |
| PLACE-03 | Phase 16: Component Placement AI | Complete | 16-03 |
| PLACE-04 | Phase 16: Component Placement AI | Complete | 16-02 |
| PLACE-05 | Phase 16: Component Placement AI | Complete | 16-04 |
| DIST-01 | Phase 17: Package & Distribution | Complete | 17-01 |
| DIST-02 | Phase 17: Package & Distribution | Complete | 17-01 |
| DIST-03 | Phase 17: Package & Distribution | Complete | 17-02 |
| ROUTE-01 | Phase 19: Interactive Routing Suggestions | Complete | 19-01 |
| ROUTE-02 | Phase 19: Interactive Routing Suggestions | Complete | 19-01 |
| ROUTE-03 | Phase 19: Interactive Routing Suggestions | Complete | 19-02 |
| ROUTE-04 | Phase 19: Interactive Routing Suggestions | Complete | 19-03 |
| LLM-01 | Phase 20: SFT Data Preparation | Pending | 20-01 |
| LLM-02 | Phase 20: SFT Data Preparation | Pending | 20-01 |
| LLM-03 | Phase 20: SFT Data Preparation | Pending | 20-02 |
| LLM-04 | Phase 20: SFT Data Preparation | Pending | 20-02 |
| LLM-05 | Phase 21: GRPO RL Fine-Tuning | Pending | 21-01 |
| LLM-06 | Phase 21: GRPO RL Fine-Tuning | Pending | 21-01 |
| LLM-07 | Phase 21: GRPO RL Fine-Tuning | Pending | 21-02 |
| LLM-08 | Phase 21: GRPO RL Fine-Tuning | Pending | 21-02 |
| LLM-09 | Phase 22: Agent Integration | Pending | 22-01 |
| LLM-10 | Phase 22: Agent Integration | Pending | 22-01 |
| LLM-11 | Phase 22: Agent Integration | Pending | 22-01 |
| LLM-12 | Phase 22: Agent Integration | Pending | 22-02 |

**Coverage:**
- Total requirements: 98 (44 v1 + 8 Phase 8 + 7 Phase 9 + 12 Phase 10 + 5 Phase 11 + 4 Phase 12 + 5 Phase 13 + 4 Phase 14 + 5 Phase 16 + 4 Phase 19)
- Mapped to phases: 98
- Unmapped: 0

---

## v2.1 Requirements

### Real-World PCB Training Pipeline (Phase 13)

- [x] **RW-01**: GitHub search API discovers KiCad repos with both .kicad_sch and .kicad_pcb files
- [x] **RW-02**: Schematic+PCB pairs parse into structured graph format (component nodes, net edges)
- [x] **RW-03**: Spatial features extracted from PCB and attached to graph node attributes
- [x] **RW-04**: Dataset normalized with SHA256 deduplication and quality filtering (min 3 components, 2 nets)
- [x] **RW-05**: JSONL output format compatible with Phase 9 GRPO training pipeline with train/val/test split

---
*Requirements defined: 2026-05-17*
*Last updated: 2026-05-24 — Phase 16 Component Placement AI added*

### Bidirectional KiCad-LTspice (Phase 14)

- [x] **BIDI-01**: KiCad schematic exports to valid .asc file that LTspice can open
- [x] **BIDI-02**: Component symbol mapping between KiCad symbols and LTspice .asy types
- [x] **BIDI-03**: Net labels transfer correctly between KiCad and LTspice naming conventions
- [x] **BIDI-04**: Simulation commands (.tran, .ac, .dc) attach correctly to exported schematics

### AI Generation Wiring (Phase 15)

- [x] **AIGEN-01**: Natural language design intent produces a structured GenerationIntent with validated operations via Anthropic SDK tool use
- [x] **AIGEN-02**: LLM suggests KiCad components given a functional description with valid library_id values and rationale
- [x] **AIGEN-03**: Design critique identifies spatial issues (clearance violations, routing congestion, thermal hotspots)
- [x] **AIGEN-04**: Iterative refinement loop: generate -> validate (ERC/DRC) -> LLM fix -> repeat until clean
- [x] **AIGEN-05**: End-to-end demo: "design a voltage regulator circuit" produces a valid .kicad_sch passing ERC

### Component Placement AI (Phase 16)

- [x] **PLACE-01**: Schematic netlist converts to bipartite placement graph with component nodes and net nodes, avoiding O(n^2) edge explosion from power nets
- [x] **PLACE-02**: Placement model predicts (x, y, rotation) for each component given board outline and constraints using GNN-based architecture
- [x] **PLACE-03**: Suggested placements pass DRC clearance checks with configurable safety margins
- [x] **PLACE-04**: Placement quality scores on real designs comparable to manual placement (wirelength, congestion metrics)
- [x] **PLACE-05**: Interactive mode: user places some components, AI places the rest respecting constraints

### Package & Distribution (Phase 17)

- [x] **DIST-01**: pyproject.toml has complete [build-system] section with setuptools backend and setuptools-scm dynamic versioning
- [x] **DIST-02**: pip install . produces a wheel with all kicad_agent modules and a kicad-agent console script entry point
- [x] **DIST-03**: GitHub Actions workflows for build verification on push/PR and PyPI publishing on version tag push via Trusted Publishing (OIDC)

### Interactive Routing Suggestions (Phase 19)

- [x] **ROUTE-01**: Routing graph construction from board bounds, obstacles, and DRC constraints with grid-based nodes and clearance-aware edge costs
- [x] **ROUTE-02**: A* pathfinding routes nets individually and in batch (shortest first), producing immutable RouteResult with path waypoints and length
- [x] **ROUTE-03**: Differential pair routing with length matching via accordion serpentining, configurable spacing and mismatch tolerance
- [x] **ROUTE-04**: Interactive routing session with approve/reject/reroute cycles, per-net constraint adaptation, and differential pair coupling
