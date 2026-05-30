# Roadmap: kicad-agent

## Overview

Build an AI-safe KiCad structural editing tool across multiple milestones. First achieve zero-diff round-trip parsing for all file types, define the operation schema that insulates the LLM from raw S-expressions, install validation gates, build editing operations from simple to complex, add visual primitives and GRPO training for spatial reasoning, AI-driven generative capabilities, LTspice integration, ADI footprint library access, real-world training data, bidirectional LTspice bridge, AI generation wiring, component placement AI, package/distribution, CI/CD, interactive routing, SFT/GRPO fine-tuning, agent integration, schematic repair, council audit remediation, and finally fill the remaining operation gaps for complete CRUD coverage.

## Milestones

- **v1.0 Foundation** - Phases 1-7 (shipped 2026-05-18)
- **v1.1 Ecosystem** - Phases 8-12 (shipped 2026-05-23)
- **v2.0 Production AI** - Phases 13-22 (shipped 2026-05-28)
- **v2.1 Audit** - Phases 23-24 (shipped 2026-05-29)
- **v2.2 Complete-Ops** - Phases 25-29 (shipped 2026-05-29)
- **v2.3 MCP-Server** - Phases 30-31 (shipped 2026-05-29)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>v1.0 Foundation (Phases 1-7) - SHIPPED 2026-05-18</summary>

- [x] **Phase 1: Foundation -- Parse, Serialize, Round-trip** - Parse all 4 KiCad file types with zero-diff round-trip fidelity
- [x] **Phase 2: Operation Schema and IR Layer** - Define the JSON intent contract and IR dataclasses that insulates the LLM from raw S-expressions
- [x] **Phase 3: Validation Pipeline** - ERC/DRC gates, structural checks, and error recovery before any mutation
- [x] **Phase 4: Component Operations** - Add, remove, duplicate, move, and modify components with transaction safety
- [x] **Phase 5: Net, Reference, and Footprint Operations** - Net CRUD, bus operations, reference management, footprint assignment
- [x] **Phase 6: Cross-File Operations and Analysis** - Schematic-to-PCB consistency, library propagation, structural diffs, connectivity analysis
- [x] **Phase 7: GSD Skill Integration** - Claude skill manifest, handler, CLI wrapper, and project context renderer

</details>

<details>
<summary>v1.1 Ecosystem (Phases 8-12) - SHIPPED 2026-05-23</summary>

- [x] **Phase 8: Visual Primitives for PCB Spatial Reasoning** - AI that points while it reasons -- coordinate-grounded DRC, routing guidance, and spatial analysis
- [x] **Phase 9: GRPO Spatial Reasoning Training** - DeepSeek-style RL training with coordinate-grounded reward signals on synthetic PCB maze data
- [x] **Phase 10: AI-Driven PCB Generation** - Generative AI that creates schematics and PCB layouts from natural language intent
- [x] **Phase 11: LTspice Integration** - Parse LTspice .asc schematics, extract components/nets/simulation commands
- [x] **Phase 12: ADI Footprint Library** - On-demand ADI footprint/symbol download, library management, manufacturer part integration

</details>

<details>
<summary>v2.0 Production AI (Phases 13-22) - SHIPPED 2026-05-28</summary>

- [x] **Phase 13: Real-World PCB Training Pipeline** - GitHub crawler for KiCad repos, structured graph datasets
- [x] **Phase 14: Bidirectional KiCad-LTspice** - KiCad schematic to .asc writer, close the simulation loop
- [x] **Phase 15: AI Generation Wiring** - LLM-driven component suggestion, design critique, natural language to operations
- [x] **Phase 16: Component Placement AI** - Predict optimal component placement from schematic netlist
- [x] **Phase 17: Package & Distribution** - PyPI publish, CLI entry point, pip install kicad-agent
- [x] **Phase 18: CI/CD Pipeline** - GitHub Actions for test suite, linting, coverage gate, release automation
- [x] **Phase 19: Interactive Routing Suggestions** - Spatial primitives + training data for trace routing on real boards
- [x] **Phase 20: SFT Data Preparation + Training Infrastructure** - ChatML conversion, quality filtering, SFT baseline on Qwen2.5-1.5B
- [x] **Phase 21: GRPO RL Fine-Tuning** - GRPO fine-tuning with reward model as critic
- [x] **Phase 22: Agent Integration + End-to-End Evaluation** - Wire fine-tuned model into kicad-agent as reasoning engine

</details>

<details>
<summary>v2.1 Audit (Phases 23-24) - SHIPPED 2026-05-29</summary>

- [x] **Phase 23: Schematic Repair Operations** - 8 schematic manipulation operations from real backplane repair sessions
- [x] **Phase 24: Council Audit Remediation & Security Hardening** - Fix all 56 findings from Council of Ricks all-hands audit

</details>

### v2.2 Complete-Ops (SHIPPED 2026-05-29)

**Milestone Goal:** Fill the five operation gaps so kicad-agent handles real-world KiCad projects with hierarchical designs and full CRUD capabilities. Zero new dependencies. **1673 tests, 57 operation types, 14 schema sub-modules.**

- [x] **Phase 25: Remove Operations** - remove_wire, remove_label, remove_junction, remove_no_connect with adjacency checks and list-filter pattern
- [x] **Phase 26: Connectivity Query** - query_connectivity exposing existing NetGraph through read-only handler with 5 query types
- [x] **Phase 27: Footprint Creation** - create_footprint with PadSpec schema, UUID-preserving serialization, courtyard generation
- [x] **Phase 28: Hierarchical Sheet Operations** - add_sheet, add_sheet_pin, navigate_hierarchy with UUID path management and nested hierarchy
- [x] **Phase 29: Cross-File Atomic Operations** - propagate_symbol_change via AtomicOperation, new cross-file executor dispatch path

### v2.3 MCP Server

**Milestone Goal:** Expose all 57 kicad-agent operations as MCP tools so any AI agent (Claude, Cursor, etc.) can invoke KiCad file edits directly. Zero new dependencies. ~250 lines new code.

- [ ] **Phase 30: MCP Operations Server** - Dynamic tool generation from Pydantic schemas, stdio transport, meta-tools for schema discovery and project context
- [ ] **Phase 31: Validation Integration** - erc_check and drc_check convenience MCP tools wrapping kicad-cli

## Phase Details

<details>
<summary>v1.0 Foundation Phase Details</summary>

### Phase 1: Foundation -- Parse, Serialize, Round-trip
**Goal**: All four KiCad file types parse into structured AST and serialize back to byte-identical or semantically equivalent output
**Depends on**: Nothing (first phase)
**Requirements**: FND-01, FND-02, FND-03, FND-04, FND-05, FND-06, VAL-07
**Success Criteria** (what must be TRUE):
  1. A .kicad_sch file parses and serializes to zero-diff output
  2. A .kicad_pcb file parses and serializes to zero-diff output
  3. A .kicad_sym file parses and serializes to zero-diff output
  4. A .kicad_mod file parses and serializes to zero-diff output
  5. All UUIDs are preserved without dangling references through parse/serialize cycles
  6. The regression test suite passes for all four file types with real KiCad 10 sample files
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 01-01-PLAN.md -- Parser layer for all 4 KiCad file types with raw content preservation
- [x] 01-02-PLAN.md -- UUID extraction/re-injection, serializers, and round-trip stability validator
- [x] 01-03-PLAN.md -- Comprehensive round-trip fidelity regression test suite with fixture files

### Phase 2: Operation Schema and IR Layer
**Goal**: The LLM has a well-defined JSON contract for expressing edit intents, and the tool layer can translate those intents into IR mutations
**Depends on**: Phase 1
**Requirements**: OPS-01, OPS-02, OPS-03, FND-07, FND-08
**Success Criteria** (what must be TRUE):
  1. A JSON operation intent validates against the Pydantic schema (rejects invalid intents, accepts valid ones)
  2. A validated intent translates to an IR mutation on a parsed file
  3. The mutated IR serializes to a deterministic, SCM-friendly output
  4. A failed mutation rolls back to the pre-mutation state (transaction with rollback)
  5. The JSON Schema is exportable for LLM consumption
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 02-01-PLAN.md -- Pydantic operation schema with discriminated union and JSON Schema export
- [x] 02-02-PLAN.md -- IR base class and four file-type IR wrappers with mutation tracking
- [x] 02-03-PLAN.md -- Transaction engine with rollback and KiCad output normalizer

### Phase 3: Validation Pipeline
**Goal**: Every mutation passes through ERC, DRC, and structural validation gates before being committed to disk
**Depends on**: Phase 2
**Requirements**: VAL-01, VAL-02, VAL-03, VAL-05, VAL-06
**Success Criteria** (what must be TRUE):
  1. An ERC check via kicad-cli returns structured pass/fail/warning results
  2. A DRC check via kicad-cli returns structured pass/fail/warning results
  3. A pre-mutation structural validation catches invalid operations before execution
  4. A validation failure triggers automatic rollback to the last valid state
  5. Net consistency between schematic and PCB can be verified programmatically
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 03-01-PLAN.md -- kicad-cli ERC/DRC wrappers with structured result parsing
- [x] 03-02-PLAN.md -- Pre-mutation structural validator and UUID uniqueness checker
- [x] 03-03-PLAN.md -- Error recovery pipeline with automatic rollback on validation failure

### Phase 4: Component Operations
**Goal**: Users can add, remove, duplicate, move, and modify components in a schematic with full validation safety
**Depends on**: Phase 3
**Requirements**: COMP-01, COMP-02, COMP-03, COMP-04, COMP-05, COMP-06
**Success Criteria** (what must be TRUE):
  1. A new component is added with correct symbol reference, properties, and valid UUID
  2. A component is removed with net stubs cleaned up (no dangling wires)
  3. A component or section is duplicated with fresh UUIDs and incremented references
  4. Components are replicated in linear, circular, and matrix array patterns
  5. A component is moved to specified coordinates with correct precision
  6. Component properties are modified and the file passes ERC
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 04-01-PLAN.md -- Operation executor, add_component and remove_component handlers
- [x] 04-02-PLAN.md -- Duplicate and array replicate handlers with linear/circular/matrix patterns
- [x] 04-03-PLAN.md -- Move/reposition and property modification handlers

### Phase 5: Net, Reference, and Footprint Operations
**Goal**: Users can manage nets, buses, references, and footprints across schematic and PCB
**Depends on**: Phase 4
**Requirements**: NET-01, NET-02, NET-03, NET-04, NET-05, REF-01, REF-02, REF-03, REF-04, FP-01, FP-02, FP-03, FP-04
**Success Criteria** (what must be TRUE):
  1. A net is added with a named or auto-generated name and connects to specified pins
  2. A net is removed with all pins disconnected and stubs cleaned up
  3. A net is renamed and the change propagates to all connected pins
  4. References are renumbered with configurable prefix and sequencing
  5. A footprint is assigned with library nickname resolution and pin mapping verification
  6. Net connectivity graph is analyzable via networkx
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 05-01-PLAN.md -- Net CRUD and bus operations
- [x] 05-02-PLAN.md -- Reference management (renumber, validate, annotate, cross-reference)
- [x] 05-03-PLAN.md -- Footprint management (assign, swap, validate, pin mapping)
- [x] 05-04-PLAN.md -- Net connectivity graph analysis via networkx

### Phase 6: Cross-File Operations and Analysis
**Goal**: Users can perform atomic operations across schematic and PCB files, propagate library changes, and analyze diffs and connectivity
**Depends on**: Phase 5
**Requirements**: XFILE-01, XFILE-02, XFILE-03, XFILE-04, VAL-04
**Success Criteria** (what must be TRUE):
  1. An atomic operation maintains consistency between schematic and PCB
  2. A symbol library reference update propagates to all schematic instances
  3. A footprint library reference update propagates to all components
  4. Project context is auto-detected from any KiCad file path
  5. A structural diff shows syntax-aware, semantically meaningful differences
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 06-01-PLAN.md -- Cross-file atomic operations
- [x] 06-02-PLAN.md -- Library reference propagation
- [x] 06-03-PLAN.md -- Project context detection and auto-discovery
- [x] 06-04-PLAN.md -- Structural diff generation with difftastic integration

### Phase 7: GSD Skill Integration
**Goal**: The kicad-agent is invokable from any KiCad project via the GSD Skill interface and from the terminal via CLI
**Depends on**: Phase 6
**Requirements**: SKILL-01, SKILL-02, SKILL-03, SKILL-04
**Success Criteria** (what must be TRUE):
  1. A GSD Skill manifest declares all kicad-agent capabilities
  2. An operation request from Claude routes through the skill handler to the Python backend
  3. The CLI wrapper runs any operation directly from the terminal
  4. A project context summary is renderable for any KiCad project directory
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 07-01-PLAN.md -- GSD Skill manifest and prompt template
- [x] 07-02-PLAN.md -- Skill handler routing and result rendering
- [x] 07-03-PLAN.md -- CLI wrapper for direct terminal usage
- [x] 07-04-PLAN.md -- Project context renderer

</details>

<details>
<summary>v1.1 Ecosystem Phase Details</summary>

### Phase 8: Visual Primitives for PCB Spatial Reasoning
**Goal**: AI reasons about PCB layouts using coordinate-grounded visual primitives -- points for pins/vias, bounding boxes for components, paths for traces, regions for net classes
**Depends on**: Phase 7
**Requirements**: VP-01, VP-02, VP-03, VP-04, VP-05, VP-06, VP-07, VP-08
**Success Criteria** (what must be TRUE):
  1. A PCB layer renders to a rasterized image with a mm-coordinate grid overlay
  2. Spatial primitives are extractable from any parsed KiCad file
  3. A procedural maze-routing generator creates synthetic PCB puzzles
  4. DRC violations produce spatially-grounded reports with coordinates
  5. Spatial queries return results: "find traces within 2mm of point (10, 15)"
  6. Rick agents produce coordinate-grounded findings
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 08-01-PLAN.md -- PCB image renderer with coordinate grid overlay and spatial primitive extraction
- [x] 08-02-PLAN.md -- Procedural maze-routing generator and cold-start reasoning chain synthesis
- [x] 08-03-PLAN.md -- Spatial query API and coordinate-grounded DRC/ERC report pipeline
- [x] 08-04-PLAN.md -- Rick agent integration: coordinate-grounded findings

### Phase 9: GRPO Spatial Reasoning Training
**Goal**: Train a reward model for PCB spatial reasoning using GRPO on synthetic maze-routing data
**Depends on**: Phase 8
**Requirements**: GRPO-01, GRPO-02, GRPO-03, GRPO-04, GRPO-05, GRPO-06, GRPO-07
**Success Criteria** (what must be TRUE):
  1. 100k+ synthetic PCB maze-routing samples generated with verified solutions
  2. Cold-start reasoning chains synthesized at scale with DFS exploration traces
  3. A reward model scores chains with per-step dense rewards (format, quality, accuracy)
  4. GRPO training loop runs end-to-end
  5. Reward hacking is prevented via smooth penalty functions
  6. Trained model shows measurable improvement on held-out tasks vs baseline
  7. Training pipeline is reproducible with a single command
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 09-01-PLAN.md -- Synthetic data pipeline at scale
- [x] 09-02-PLAN.md -- Cold-start reasoning chain synthesis at scale
- [x] 09-03-PLAN.md -- Reward model architecture
- [x] 09-04-PLAN.md -- GRPO training loop

### Phase 10: AI-Driven PCB Generation
**Goal**: Two-tier phase -- close practical operations gap, then build generative AI capabilities on top
**Depends on**: Phase 9
**Requirements**: GEN-01 through GEN-12
**Success Criteria** (what must be TRUE):
  1. sym-lib-table and fp-lib-table can be parsed, queried, and modified
  2. Manufacturing files can be exported via kicad-cli wrappers
  3. Schematic ERC errors can be auto-repaired
  4. Power net validation detects unconnected power pins
  5. Copper zones can be added and filled on PCB layouts
  6. Net classes and custom DRC rules can be set
  7. GenerationIntent schema converts natural language to structured operation sequences
  8. Template board generation creates valid .kicad_pcb files
  9. Component placement engine places components with clearance validation
  10. End-to-end pipeline: intent -> template -> operations -> validation -> export
  11. Iterative refinement loop until clean
  12. Generated boards achieve DRC pass on simple designs
**Plans**: 6 plans (6/6 complete)

Plans:
- [x] 10-01-PLAN.md -- Project file parsers and library management
- [x] 10-02-PLAN.md -- Manufacturing export wrappers
- [x] 10-03-PLAN.md -- Schematic repair, validation gates, and PCB operations
- [x] 10-04-PLAN.md -- GenerationIntent schema and template board generator
- [x] 10-05-PLAN.md -- Component placement engine and operation-sequence planning
- [x] 10-06-PLAN.md -- End-to-end generation pipeline with iterative refinement

### Phase 11: LTspice Integration
**Goal**: Parse LTspice .asc schematic files and build KiCad-LTspice bridge
**Depends on**: Phase 1
**Requirements**: LTSPICE-01 through LTSPICE-05
**Success Criteria** (what must be TRUE):
  1. A .asc file parses into structured component/net/simulation data
  2. Components with values, positions, orientations are extractable
  3. Net connectivity graph is derivable from WIRE and FLAG statements
  4. Simulation commands are extractable and parseable
  5. .raw simulation results are readable
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 11-01-PLAN.md -- .asc parser with SpiceLib
- [x] 11-02-PLAN.md -- .raw simulation result reader
- [x] 11-03-PLAN.md -- Net connectivity graph derivation from wire geometry

### Phase 12: ADI Footprint Library
**Goal**: On-demand fetching of ADI manufacturer footprints with caching and library management
**Depends on**: Phase 5, Phase 10
**Requirements**: ADI-01, ADI-02, ADI-03, ADI-04
**Success Criteria** (what must be TRUE):
  1. ADI footprints are discoverable by part number
  2. .kicad_mod footprints download and import into local library
  3. .kicad_sym symbols download and import into local library
  4. Library cache avoids re-downloading previously fetched parts
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 12-01-PLAN.md -- Type definitions, filesystem cache with JSON manifest
- [x] 12-02-PLAN.md -- SamacSys HTTP client for part search and KiCad library download
- [x] 12-03-PLAN.md -- Fetch orchestrator wiring cache/client/lib_table

</details>

<details>
<summary>v2.0 Production AI Phase Details</summary>

### Phase 13: Real-World PCB Training Pipeline
**Goal**: GitHub crawler and data pipeline for real-world training data to complement synthetic mazes
**Depends on**: Phase 8, Phase 9
**Requirements**: RW-01 through RW-05
**Success Criteria** (what must be TRUE):
  1. GitHub search API discovers KiCad repos with both .kicad_sch and .kicad_pcb files
  2. Schematic+PCB pairs parse into structured graph format
  3. Dataset normalized with deduplication and quality filtering
  4. 1,000+ real board pairs ingestible in a single pipeline run
  5. Output format compatible with GRPO training pipeline
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 13-01-PLAN.md -- GitHub repo discovery and KiCad file pair extraction
- [x] 13-02-PLAN.md -- Schematic+PCB graph parser with spatial feature extraction
- [x] 13-03-PLAN.md -- Dataset normalization, deduplication, and GRPO training format export

### Phase 14: Bidirectional KiCad-LTspice
**Goal**: KiCad -> .asc export, enabling design in KiCad, simulate in LTspice
**Depends on**: Phase 11, Phase 2
**Requirements**: BIDI-01 through BIDI-04
**Success Criteria** (what must be TRUE):
  1. A KiCad schematic exports to a valid .asc file that LTspice can open
  2. Component symbol mapping between KiCad symbols and LTspice .asy types
  3. Net labels transfer correctly between KiCad and LTspice naming conventions
  4. Simulation commands attach correctly to exported schematics
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 14-01-PLAN.md -- KiCad component to LTspice symbol mapping table and converter
- [x] 14-02-PLAN.md -- .asc writer: KiCad schematic to LTspice .asc export
- [x] 14-03-PLAN.md -- Simulation command injection and round-trip validation

### Phase 15: AI Generation Wiring
**Goal**: Wire an LLM into the generation pipeline for component suggestions, schematic drafting, design critique
**Depends on**: Phase 10, Phase 8
**Requirements**: AIGEN-01 through AIGEN-05
**Success Criteria** (what must be TRUE):
  1. Natural language design intent produces a structured GenerationIntent with validated operations
  2. LLM suggests components given a functional description
  3. Design critique identifies spatial issues
  4. Iterative refinement loop: generate -> validate -> LLM fix -> repeat
  5. End-to-end demo: "design a voltage regulator circuit" produces a valid .kicad_sch passing ERC
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 15-01-PLAN.md -- LLM integration layer
- [x] 15-02-PLAN.md -- Design critic with spatial reasoning
- [x] 15-03-PLAN.md -- Iterative refinement loop with LLM-driven error fixing
- [x] 15-04-PLAN.md -- End-to-end generation pipeline demo and validation

### Phase 16: Component Placement AI
**Goal**: Predict optimal component placement from schematic netlist using spatial reasoning
**Depends on**: Phase 8, Phase 9, Phase 13
**Requirements**: PLACE-01 through PLACE-05
**Success Criteria** (what must be TRUE):
  1. Schematic netlist converts to placement graph
  2. Placement model predicts (x, y, rotation) for each component
  3. Suggested placements pass DRC clearance checks
  4. Placement quality scores comparable to manual placement
  5. Interactive mode: user places some components, AI places the rest
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 16-01-PLAN.md -- Schematic netlist to placement graph converter
- [x] 16-02-PLAN.md -- Placement prediction model architecture and training
- [x] 16-03-PLAN.md -- DRC-aware placement validation and scoring
- [x] 16-04-PLAN.md -- Interactive placement mode with constraint propagation

### Phase 17: Package & Distribution
**Goal**: Make kicad-agent installable via pip with a proper CLI entry point and PyPI package
**Depends on**: Phase 7
**Requirements**: DIST-01, DIST-02, DIST-03, DIST-04
**Success Criteria** (what must be TRUE):
  1. `pip install kicad-agent` installs a working package with CLI entry point
  2. `kicad-agent` CLI command runs operations, validation, and project context
  3. Package metadata is correct on PyPI
  4. README and API documentation cover all public interfaces
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 17-01-PLAN.md -- Package structure, pyproject.toml updates, CLI entry point
- [x] 17-02-PLAN.md -- PyPI publishing workflow and version management
- [x] 17-03-PLAN.md -- README, API documentation, and usage examples

### Phase 18: CI/CD Pipeline
**Goal**: GitHub Actions CI for full test suite, linting, type checking, and coverage gate
**Depends on**: Phase 17
**Requirements**: CI-01, CI-02, CI-03, CI-04
**Success Criteria** (what must be TRUE):
  1. Every PR runs full test suite with pass/fail gate
  2. Linting and type checking run on every push
  3. Coverage report generated and 80%+ gate enforced
  4. Release workflow: tag push -> build -> test -> PyPI publish
**Plans**: 2 plans (2/2 complete)

Plans:
- [x] 18-01-PLAN.md -- GitHub Actions CI: test, lint, type-check, coverage gate
- [x] 18-02-PLAN.md -- Release automation: version bump, changelog, PyPI publish

### Phase 19: Interactive Routing Suggestions
**Goal**: Use spatial primitives and training data to suggest trace routing paths on real PCBs
**Depends on**: Phase 8, Phase 16
**Requirements**: ROUTE-01 through ROUTE-04
**Success Criteria** (what must be TRUE):
  1. Given placed components and netlist, routing suggestions are generated for each net
  2. Suggested routes satisfy DRC clearance and design rule constraints
  3. Differential pair routing respects impedance and length matching constraints
  4. Interactive mode: user approves/rejects suggestions, AI adapts
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 19-01-PLAN.md -- Routing graph model and pathfinding with DRC constraints
- [x] 19-02-PLAN.md -- Differential pair routing with impedance and length matching
- [x] 19-03-PLAN.md -- Interactive routing mode with approval and constraint adaptation

### Phase 20: SFT Data Preparation + Training Infrastructure
**Goal**: Convert 136K correct training chains to ChatML instruction format, quality-filter, and train SFT baseline on Qwen2.5-1.5B
**Depends on**: Phase 9, Phase 13
**Requirements**: LLM-01, LLM-02, LLM-03, LLM-04
**Success Criteria** (what must be TRUE):
  1. 136K correct chains converted to ChatML instruction format with task-specific prompt templates
  2. Bottom quartile filtered out using reward model scoring (retain ~102K high-quality samples)
  3. SFT training completes on Qwen2.5-1.5B with LoRA (fp16 on Apple MPS)
  4. SFT model generates valid PCB reasoning chains on held-out test set
  5. SFT model scores higher than base model on reward model evaluation
**Plans**: 3 plans (3/3 complete)

Plans:
- [x] 20-01-PLAN.md -- Convert 136K correct chains to ChatML + reward model quality filter
- [x] 20-02-PLAN.md -- TRL SFTTrainer + LoRA training on Qwen2.5-1.5B on Apple MPS
- [x] 20-03-PLAN.md -- SFT evaluation: base vs trained model comparison + eval report

### Phase 21: GRPO RL Fine-Tuning
**Goal**: Fine-tune SFT model using GRPO with the trained reward model as critic
**Depends on**: Phase 20, Phase 9
**Requirements**: LLM-05, LLM-06, LLM-07, LLM-08
**Success Criteria** (what must be TRUE):
  1. GRPO loop generates N chains per sample, scores with reward model, computes group advantages
  2. Policy updates via PPO-clip with KL divergence penalty
  3. GRPO model achieves >85% discrimination rate (up from 75% SFT baseline)
  4. GRPO model scores higher than SFT on all three reward dimensions
**Plans**: 2 plans (2/2 complete)

Plans:
- [x] 21-01-PLAN.md -- GRPO training loop implementation
- [x] 21-02-PLAN.md -- GRPO training run + evaluation + Council review gate

### Phase 22: Agent Integration + End-to-End Evaluation
**Goal**: Wire the GRPO-trained LLM into kicad-agent as its reasoning engine with best-of-N generation
**Depends on**: Phase 21, Phase 7
**Requirements**: LLM-09, LLM-10, LLM-11, LLM-12
**Success Criteria** (what must be TRUE):
  1. Fine-tuned model loads and generates chains in <2s per chain on MPS
  2. Best-of-N (N=4) picks chains scoring 20%+ higher than single-sample
  3. kicad-agent CLI has `analyze` subcommand using the fine-tuned model
  4. Python API exposes `generate_analysis(pcb_path)` returning scored chains
  5. GSD Skill: Claude can invoke `/kicad-agent analyze <pcb>` and get spatial reasoning
  6. End-to-end demo: analyze HackRF One and produce quality reasoning chain
**Plans**: 2 plans (2/2 complete)

Plans:
- [x] 22-01-PLAN.md -- Inference wrapper + best-of-N + kicad-agent wiring
- [x] 22-02-PLAN.md -- End-to-end evaluation + Council review + documentation

</details>

<details>
<summary>v2.1 Audit Phase Details</summary>

### Phase 23: Schematic Repair Operations
**Goal**: 8 schematic manipulation operations discovered from real backplane repair sessions
**Depends on**: Phase 10, Phase 3
**Requirements**: SCHREPAIR-01 through SCHREPAIR-08
**Success Criteria** (what must be TRUE):
  1. ERC JSON output parses into structured violation list with positions for targeted repair
  2. Violation positions extractable by type for automated fix workflows
  3. Hierarchical labels validatable against expected set to catch agent deletion
  4. KiCad 6 format schematics convert to valid KiCad 10 passing all 9 format checks
  5. No-connect markers placed at pin_not_connected positions without file corruption
  6. Power flag symbols placed at power_pin_not_driven positions with correct lib definition
  7. Off-grid wire endpoints snapped to grid while preserving connectivity
  8. Root sheet generated from sub-sheet hierarchical labels with correct pin positioning
**Plans**: 4 plans (4/4 complete)

Plans:
- [x] 23-01-PLAN.md -- ERC parser, violation position extractor, hierarchical label guard
- [x] 23-02-PLAN.md -- KiCad 6 to KiCad 10 format converter with section-based reassembly
- [x] 23-03-PLAN.md -- Schematic mutation operations: snap_to_grid, add_power_flag, place_no_connects_from_erc
- [x] 23-04-PLAN.md -- Root sheet generator from sub-sheet hierarchical labels

### Phase 24: Council Audit Remediation & Security Hardening
**Goal**: Fix all 56 findings from Council of Ricks all-hands audit
**Depends on**: Phase 10, Phase 15, Phase 17
**Requirements**: SEC-01, SEC-02, SEC-03, SEC-04, SEC-05, SLC-01, SLC-02, SLC-03, QUAL-01, QUAL-02, TEST-01
**Success Criteria** (what must be TRUE):
  1. Path traversal bypass eliminated -- executor confines all file operations to project directory
  2. S-expression injection eliminated -- all interpolated values use _escape_sexpr_value
  3. All 3 SLC violations fixed -- no stubs, no phantom operations, no always-true validators
  4. Prompt-to-schema field mismatches resolved
  5. Exception messages sanitized for MCP clients
  6. Training pipeline integrity gaps addressed
  7. All 79 broad `except Exception` catches narrowed to specific exception types
  8. Code quality issues resolved: schema.py split, dead code removed, duplication consolidated
**Plans**: 5 plans (5/5 complete, Council APPROVED)

Plans:
- [x] 24-01-PLAN.md -- Security hardening: path traversal, S-expression injection, exception sanitization
- [x] 24-02-PLAN.md -- SLC fixes: implement or remove stubs/phantoms, fix prompt-schema mismatches
- [x] 24-03-PLAN.md -- Code quality: split large files, narrow exception catches, remove dead code
- [x] 24-04-PLAN.md -- Testing gaps and training pipeline integrity
- [x] 24-05-PLAN.md -- Architecture gaps and low-priority fixes

</details>

### v2.2 Complete-Ops Phase Details

### Phase 25: Remove Operations
**Goal**: Users can remove wires, labels, junctions, and no-connect markers from schematics with adjacency safety checks and full transaction rollback
**Depends on**: Phase 24 (stable codebase post-audit)
**Requirements**: REMOVE-01, REMOVE-02, REMOVE-03, REMOVE-04, REMOVE-05
**Success Criteria** (what must be TRUE):
  1. A wire segment is removed by UUID and refuses removal if other wires share its endpoints (preventing dangling ERC errors)
  2. A label (global or local) is removed by UUID with net membership validation
  3. A junction marker is removed by UUID without corrupting connected wires
  4. A no-connect marker is removed by UUID cleanly
  5. All four remove operations use the list-filter pattern from remove_component.py, record mutations in Transaction, and preserve round-trip fidelity
**Plans**: 2 plans

Plans:
- [x] 25-01-PLAN.md -- Remove operation schemas (RemoveWireOp, RemoveLabelOp, RemoveJunctionOp, RemoveNoConnectOp) and executor registration (REMOVE-05)
- [x] 25-02-PLAN.md -- Remove handlers with list-filter pattern, wire adjacency check, net membership validation, and tests (REMOVE-01, REMOVE-02, REMOVE-03, REMOVE-04)

### Phase 26: Connectivity Query
**Goal**: Users can query PCB connectivity through the operation executor using the existing NetGraph, with structured JSON results compatible with LLM reasoning chains
**Depends on**: Phase 25 (query pattern established)
**Requirements**: QUERY-01, QUERY-02, QUERY-03, QUERY-04
**Success Criteria** (what must be TRUE):
  1. query_connectivity operation exposes NetGraph through the executor as a read-only handler (no IR mutation, no Transaction registration)
  2. Five query types work: connected_pads, net_stats, are_connected, shortest_path, connected_components
  3. Read-only semantics enforced -- the handler cannot modify IR state or trigger Transaction writes
  4. Results are structured JSON with coordinate-grounded data where applicable, compatible with LLM reasoning chains
**Plans**: 1 plan

Plans:
- [x] 26-01-PLAN.md -- QueryConnectivityOp schema, read-only handler wrapping NetGraph, 5 query types, JSON result formatting, and tests (QUERY-01, QUERY-02, QUERY-03, QUERY-04)

### Phase 27: Footprint Creation
**Goal**: Users can create .kicad_mod footprint files from JSON PadSpec definitions with UUID-preserving serialization and automatic courtyard generation
**Depends on**: Phase 26 (create-path extension pattern validated)
**Requirements**: FOOT-01, FOOT-02, FOOT-03, FOOT-04
**Success Criteria** (what must be TRUE):
  1. A .kicad_mod file is generated from JSON PadSpec definitions (pad number, shape, position, size, layers, drill) that KiCad can open without errors
  2. Footprint serialization preserves UUIDs on pads and graphics using raw S-expression construction (not kiutils Footprint.to_file() which drops UUIDs)
  3. Courtyard is automatically generated from pad bounding box with configurable margin
  4. Pad layer validation rejects invalid layer names -- only valid KiCad layers (F.Cu, B.Cu, F.Paste, etc.) accepted via Literal type
**Plans**: 2 plans

Plans:
- [x] 27-01-PLAN.md -- CreateFootprintOp schema with PadSpec, layer validation via Literal type, executor registration (FOOT-01, FOOT-04)
- [x] 27-02-PLAN.md -- Footprint handler with UUID-preserving raw S-expression serialization, courtyard generation, and tests (FOOT-02, FOOT-03)

### Phase 28: Hierarchical Sheet Operations
**Goal**: Users can create hierarchical sheet instances and pins, navigate sheet hierarchies, and manage nested sub-sheets with correct path resolution and instance tracking
**Depends on**: Phase 27 (sub-file creation pattern validated)
**Requirements**: SHEET-01, SHEET-02, SHEET-03, SHEET-04, SHEET-05, SHEET-06
**Success Criteria** (what must be TRUE):
  1. A hierarchical sheet instance is created with correct fileName (relative to parent directory, not project root), UUID, and position
  2. A hierarchical pin is created with exact-match validation against child sheet labels (case-sensitive, no fuzzy matching)
  3. The sheet hierarchy is navigable returning a tree with UUID paths, pin/label mappings, and file paths
  4. Sheet instances (sheetInstances) are updated alongside sheet creation -- missing instances cause KiCad crashes
  5. Sub-sheet file creation produces valid .kicad_sch with proper header, UUID, and paper settings
  6. Nested hierarchy works: path resolution handles root -> subdir/child -> subdir/subsubdir/grandchild
**Plans**: 3 plans

Plans:
- [x] 28-01-PLAN.md -- AddSheetOp and NavigateSheetsOp schemas, sheet instance tracking, and executor registration (SHEET-01, SHEET-04)
- [x] 28-02-PLAN.md -- add_sheet handler with fileName resolution relative to parent, sheetInstances update, sub-sheet file creation, and navigate_hierarchy handler (SHEET-01, SHEET-03, SHEET-04, SHEET-05, SHEET-06)
- [x] 28-03-PLAN.md -- AddSheetPinOp schema, add_sheet_pin handler with exact-match label validation, nested hierarchy support, and tests (SHEET-02, SHEET-06)

### Phase 29: Cross-File Atomic Operations
**Goal**: Users can propagate symbol changes across all referencing files atomically, with partial failure guarantee that rolls back ALL files if any single mutation fails
**Depends on**: Phase 28 (executor stable, all single-file operations complete)
**Requirements**: XFILE-05, XFILE-06, XFILE-07
**Success Criteria** (what must be TRUE):
  1. propagate_symbol_change operation uses existing AtomicOperation (crossfile/atomic.py) to mutate a symbol across all referencing files atomically
  2. A new `_CROSSFILE_HANDLERS` dispatch path in the executor receives `dict[Path, BaseIR]` instead of single IR, coordinating multiple files
  3. Partial failure guarantee holds -- if any file mutation fails, ALL files roll back via AtomicOperation, validating ALL mutations before opening ANY Transaction
**Plans**: 2 plans

Plans:
- [x] 29-01-PLAN.md -- `_CROSSFILE_HANDLERS` registry and `_execute_cross_file()` dispatch path in executor, PropagateSymbolChangeOp schema (XFILE-05, XFILE-06)
- [x] 29-02-PLAN.md -- propagate_symbol_change handler wiring AtomicOperation, partial failure guarantee with pre-validation, and tests (XFILE-05, XFILE-07)

</details>

### v2.3 MCP-Server Phase Details

### Phase 30: MCP Operations Server
**Goal**: New MCP server binary exposing all 57 kicad-agent operations as individually named tools, with dynamic schema generation, structured error handling, and meta-tools for schema discovery and project context
**Depends on**: Phase 29 (all 57 operations complete and tested)
**Requirements**: MCPSRV-01, MCPSRV-02, MCPSRV-03, MCPSRV-04, MCPSRV-05, MCPSRV-06, MCPSRV-07, META-01, META-02, META-03, PKG-01, PKG-02
**Success Criteria** (what must be TRUE):
  1. All 57 operation types appear as individually named MCP tools with correct input schemas from `model_json_schema()`
  2. MCP server runs on stdio transport via `kicad-agent-edit` CLI entry point
  3. Project base directory configurable via `KICAD_PROJECT_DIR` env var, defaulting to `Path.cwd()`
  4. Synchronous executor calls wrapped in `asyncio.to_thread()` -- event loop never blocks
  5. Failed operations return `CallToolResult` with `isError=True` and structured error JSON
  6. Successful operations return structured JSON matching executor return format
  7. Tool responses exceeding 50KB are truncated with summary trailer
  8. ToolAnnotations auto-assigned: readOnlyHint for query/validation, destructiveHint for remove, idempotentHint for create
  9. `get_operation_schema` meta-tool returns full JSON Schema for all 57 operations
  10. `get_project_context` meta-tool returns project structure, file inventory, and board statistics
  11. `kicad-agent-edit` entry point registered in pyproject.toml with no new dependencies
**Plans**: 1 plan (3 merged)

Plans:
- [x] 30-01-PLAN.md -- All 3 plans merged: server skeleton + dispatcher + meta-tools + tests (MCPSRV-01 through MCPSRV-07, META-01 through META-03, PKG-01, PKG-02)

### Phase 31: Validation Integration
**Goal**: ERC/DRC convenience tools wrapping kicad-cli for MCP clients that want one-call validation without running separate operations
**Depends on**: Phase 30 (MCP server operational)
**Requirements**: MCPVAL-01, MCPVAL-02
**Success Criteria** (what must be TRUE):
  1. `erc_check` MCP tool runs `kicad-cli sch erc` and returns structured violation results (pass/fail/warning with positions)
  2. `drc_check` MCP tool runs `kicad-cli pcb drc` and returns structured violation results (pass/fail/warning with positions)
**Plans**: 1 plan

Plans:
- [x] 31-01-PLAN.md -- erc_check and drc_check MCP tools wrapping kicad-cli validation, structured result parsing, ToolAnnotations (readOnlyHint=True), and tests (MCPVAL-01, MCPVAL-02)

### v2.4 Production-Hardening Phase Details

### Phase 32: Executor Performance — COMPLETE
**Goal**: IR caching and batch execution for single-parse single-write operation throughput
**Depends on**: Phase 31
**Requirements**: PERF-01, PERF-02, PERF-03, PERF-04
**Success Criteria**:
  1. IRCache with LRU eviction and thread safety
  2. execute_batch() parses each file once, writes each file once
  3. Batch rejects entire batch on validation failure with full error report
  4. 100 property modifications complete in under 10 seconds
**Plans**: 2 plans (2/2 complete)

Plans:
- [x] 32-01-PLAN.md -- IRCache module with LRU eviction and thread safety (PERF-01)
- [x] 32-02-PLAN.md -- execute_batch() with pre-validation and single-write optimization (PERF-02, PERF-03, PERF-04)

### Phase 33: Undo/Redo Stack
**Goal**: Per-project undo/redo stack storing file content snapshots in bounded deque, exposed as MCP meta-tools
**Depends on**: Phase 32
**Requirements**: UNDO-01, UNDO-02, UNDO-03, UNDO-04, UNDO-05
**Success Criteria**:
  1. UndoStack class with bounded deque, thread-safe, stores file content snapshots
  2. undo() restores pre-mutation content, redo() restores post-mutation content
  3. MCP undo/redo meta-tools with destructiveHint=True
  4. Per-file isolation across concurrent projects
  5. Configurable max_size with env var KICAD_UNDO_MAX_SIZE
**Plans**: 2 plans

Plans:
- [ ] 33-01-PLAN.md -- UndoStack module, executor snapshot capture, undo/redo methods (UNDO-01, UNDO-02, UNDO-04, UNDO-05)
- [ ] 33-02-PLAN.md -- MCP undo/redo meta-tools with dispatch and tests (UNDO-03)

### Phase 34: LLM Provider Abstraction
**Goal**: Abstract LLM calls behind a protocol so different providers can be swapped
**Depends on**: Phase 33
**Requirements**: LLM-13, LLM-14, LLM-15, LLM-16, LLM-17
**Plans**: TBD

### Phase 35: Remaining Ops Gaps
**Goal**: Close the five remaining operation gaps for complete CRUD coverage
**Depends on**: Phase 34
**Requirements**: GEN-01, GEN-03, GEN-04, GEN-05, GEN-06
**Plans**: TBD

### Phase 36: Multi-Layer Routing
**Goal**: Multi-layer routing with impedance control and length matching
**Depends on**: Phase 35
**Requirements**: ROUTE-05, ROUTE-06, ROUTE-07
**Plans**: TBD

### Phase 37: Training + Infrastructure
**Goal**: Training pipeline hardening and MCP server infrastructure
**Depends on**: Phase 36
**Requirements**: TRAIN-01, TRAIN-02, TRAIN-03, TRAIN-04, INFRA-01, INFRA-02, INFRA-03
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> ... -> 29 -> 30 -> 31

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 3/3 | Complete | 2026-05-18 |
| 2. Operation Schema + IR | 3/3 | Complete | 2026-05-18 |
| 3. Validation Pipeline | 3/3 | Complete | 2026-05-18 |
| 4. Component Operations | 3/3 | Complete | 2026-05-18 |
| 5. Net/Ref/FP Operations | 4/4 | Complete | 2026-05-18 |
| 6. Cross-File + Analysis | 4/4 | Complete | 2026-05-18 |
| 7. GSD Skill Integration | 4/4 | Complete | 2026-05-18 |
| 8. Visual Primitives | 4/4 | Complete | 2026-05-22 |
| 9. GRPO Training | 4/4 | Complete | 2026-05-22 |
| 10. AI-Driven PCB Gen | 6/6 | Complete | 2026-05-23 |
| 11. LTspice Integration | 3/3 | Complete | 2026-05-23 |
| 12. ADI Footprint Library | 3/3 | Complete | 2026-05-23 |
| 13. Real-World Training | 3/3 | Complete | 2026-05-23 |
| 14. Bidirectional LTspice | 3/3 | Complete | 2026-05-24 |
| 15. AI Generation Wiring | 4/4 | Complete | 2026-05-24 |
| 16. Component Placement AI | 4/4 | Complete | 2026-05-24 |
| 17. Package & Distribution | 3/3 | Complete | 2026-05-24 |
| 18. CI/CD Pipeline | 2/2 | Complete | 2026-05-23 |
| 19. Interactive Routing | 3/3 | Complete | 2026-05-24 |
| 20. SFT Data Prep | 3/3 | Complete | 2026-05-26 |
| 21. GRPO RL Fine-Tuning | 2/2 | Complete | 2026-05-28 |
| 22. Agent Integration | 2/2 | Complete | 2026-05-28 |
| 23. Schematic Repair | 4/4 | Complete | 2026-05-29 |
| 24. Council Audit Remediation | 5/5 | Complete | 2026-05-29 |
| 25. Remove Operations | 2/2 | Complete | 2026-05-29 |
| 26. Connectivity Query | 1/1 | Complete | 2026-05-29 |
| 27. Footprint Creation | 2/2 | Complete | 2026-05-29 |
| 28. Hierarchical Sheet Ops | 3/3 | Complete | 2026-05-29 |
| 29. Cross-File Atomic Ops | 2/2 | Complete | 2026-05-29 |
| 30. MCP Operations Server | 1/1 | Complete | 2026-05-29 |
| 31. Validation Integration | 1/1 | Complete | 2026-05-29 |
| 32. Executor Performance | 2/2 | Complete | 2026-05-30 |
| 33. Undo/Redo Stack | 0/2 | In Progress | -- |
