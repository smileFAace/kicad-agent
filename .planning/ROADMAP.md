# Roadmap: kicad-agent

## Overview

Build an AI-safe KiCad structural editing tool in 12 phases: first achieve zero-diff round-trip parsing for all file types, then define the operation schema that insulates the LLM from raw S-expressions, then install validation gates before any mutation is attempted, then build editing operations from simple (components) to complex (nets, cross-file), add read-only analysis tools, wrap it all in a GSD Skill for Claude integration, add visual primitives for spatial reasoning, train a GRPO-based reward model for PCB spatial reasoning using synthetic training data, build AI-driven generative capabilities for schematic capture and PCB layout, integrate LTspice for SPICE simulation bridge, and add ADI footprint library access for on-demand manufacturer footprint fetching.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation -- Parse, Serialize, Round-trip** - Parse all 4 KiCad file types with zero-diff round-trip fidelity
- [x] **Phase 2: Operation Schema and IR Layer** - Define the JSON intent contract and IR dataclasses that insulates the LLM from raw S-expressions
- [x] **Phase 3: Validation Pipeline** - ERC/DRC gates, structural checks, and error recovery before any mutation
- [x] **Phase 4: Component Operations** - Add, remove, duplicate, move, and modify components with transaction safety
- [x] **Phase 5: Net, Reference, and Footprint Operations** - Net CRUD, bus operations, reference management, footprint assignment
- [x] **Phase 6: Cross-File Operations and Analysis** - Schematic-to-PCB consistency, library propagation, structural diffs, connectivity analysis
- [x] **Phase 7: GSD Skill Integration** - Claude skill manifest, handler, CLI wrapper, and project context renderer
- [x] **Phase 8: Visual Primitives for PCB Spatial Reasoning** - AI that points while it reasons — coordinate-grounded DRC, routing guidance, and spatial analysis
- [x] **Phase 9: GRPO Spatial Reasoning Training** - DeepSeek-style RL training with coordinate-grounded reward signals on synthetic PCB maze data
- [x] **Phase 10: AI-Driven PCB Generation** - Generative AI that creates schematics and PCB layouts from natural language intent, closing the gap from critic to creator
- [ ] **Phase 11: LTspice Integration** - Parse LTspice .asc schematics, extract components/nets/simulation commands, bridge KiCad-LTspice workflows
- [ ] **Phase 12: ADI Footprint Library** - On-demand ADI footprint/symbol download, library management, and manufacturer part integration

## Phase Details

### Phase 1: Foundation -- Parse, Serialize, Round-trip
**Goal**: All four KiCad file types parse into structured AST and serialize back to byte-identical or semantically equivalent output
**Depends on**: Nothing (first phase)
**Requirements**: FND-01, FND-02, FND-03, FND-04, FND-05, FND-06, VAL-07
**Success Criteria** (what must be TRUE):
  1. A .kicad_sch file parses and serializes to zero-diff output (unchanged file round-trips identically)
  2. A .kicad_pcb file parses and serializes to zero-diff output
  3. A .kicad_sym file parses and serializes to zero-diff output
  4. A .kicad_mod file parses and serializes to zero-diff output
  5. All UUIDs are preserved without dangling references through parse/serialize cycles
  6. The regression test suite passes for all four file types with real KiCad 10 sample files
**Plans**: 3 plans

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
  3. The mutated IR serializes to a deterministic, SCM-friendly output (stable ordering across runs)
  4. A failed mutation rolls back to the pre-mutation state (transaction with rollback)
  5. The JSON Schema is exportable for LLM consumption (Claude can discover available operations)
**Plans**: 3 plans

Plans:
- [x] 02-01-PLAN.md -- Pydantic operation schema with discriminated union and JSON Schema export (OPS-01, OPS-02)
- [x] 02-02-PLAN.md -- IR base class and four file-type IR wrappers with mutation tracking (OPS-03)
- [x] 02-03-PLAN.md -- Transaction engine with rollback and KiCad output normalizer (FND-07, FND-08)

### Phase 3: Validation Pipeline
**Goal**: Every mutation passes through ERC, DRC, and structural validation gates before being committed to disk
**Depends on**: Phase 2
**Requirements**: VAL-01, VAL-02, VAL-03, VAL-05, VAL-06
**Success Criteria** (what must be TRUE):
  1. An ERC check via kicad-cli returns structured pass/fail/warning results for a schematic
  2. A DRC check via kicad-cli returns structured pass/fail/warning results for a PCB
  3. A pre-mutation structural validation catches invalid operations (e.g., adding a component to a non-existent sheet) before execution
  4. A validation failure triggers automatic rollback to the last valid state
  5. Net consistency between schematic and PCB can be verified programmatically
**Plans**: 3 plans

Plans:
- [x] 03-01-PLAN.md -- kicad-cli ERC/DRC wrappers with structured result parsing (VAL-01, VAL-02)
- [x] 03-02-PLAN.md -- Pre-mutation structural validator and UUID uniqueness checker (VAL-05)
- [x] 03-03-PLAN.md -- Error recovery pipeline with automatic rollback on validation failure (VAL-03, VAL-06)

### Phase 4: Component Operations
**Goal**: Users can add, remove, duplicate, move, and modify components in a schematic with full validation safety
**Depends on**: Phase 3
**Requirements**: COMP-01, COMP-02, COMP-03, COMP-04, COMP-05, COMP-06
**Success Criteria** (what must be TRUE):
  1. A new component is added to a schematic with correct symbol reference, properties, and valid UUID
  2. A component is removed from a schematic with net stubs cleaned up (no dangling wires)
  3. A component or section is duplicated with fresh UUIDs and incremented references
  4. Components are replicated in linear, circular, and matrix array patterns
  5. A component is moved to specified coordinates with correct precision (4 decimal schematic, 6 decimal PCB)
  6. Component properties (value, footprint, reference, custom fields) are modified and the file passes ERC
**Plans**: 3 plans

Plans:
- [x] 04-01-PLAN.md -- Operation executor, add_component and remove_component handlers (COMP-01, COMP-02)
- [x] 04-02-PLAN.md -- Duplicate and array replicate handlers with linear/circular/matrix patterns (COMP-03, COMP-04)
- [x] 04-03-PLAN.md -- Move/reposition and property modification handlers (COMP-05, COMP-06)

### Phase 5: Net, Reference, and Footprint Operations
**Goal**: Users can manage nets, buses, references, and footprints across schematic and PCB
**Depends on**: Phase 4
**Requirements**: NET-01, NET-02, NET-03, NET-04, NET-05, REF-01, REF-02, REF-03, REF-04, FP-01, FP-02, FP-03, FP-04
**Success Criteria** (what must be TRUE):
  1. A net is added with a named or auto-generated name and connects to specified pins
  2. A net is removed with all pins disconnected and stubs cleaned up
  3. A net is renamed and the change propagates to all connected pins
  4. References are renumbered with configurable prefix and sequencing, and uniqueness is validated
  5. A footprint is assigned to a component with library nickname resolution, and pin mapping is verified
  6. Net connectivity graph is analyzable via networkx (path finding, connectivity queries)
**Plans**: 4 plans

Plans:
- [x] 05-01-PLAN.md -- Net CRUD and bus operations (NET-01, NET-02, NET-03, NET-04)
- [x] 05-02-PLAN.md -- Reference management (renumber, validate, annotate, cross-reference) (REF-01, REF-02, REF-03, REF-04)
- [x] 05-03-PLAN.md -- Footprint management (assign, swap, validate, pin mapping) (FP-01, FP-02, FP-03, FP-04)
- [x] 05-04-PLAN.md -- Net connectivity graph analysis via networkx (NET-05)

### Phase 6: Cross-File Operations and Analysis
**Goal**: Users can perform atomic operations across schematic and PCB files, propagate library changes, and analyze diffs and connectivity
**Depends on**: Phase 5
**Requirements**: XFILE-01, XFILE-02, XFILE-03, XFILE-04, VAL-04
**Success Criteria** (what must be TRUE):
  1. An atomic operation maintains consistency between schematic and PCB (e.g., adding a component updates both files)
  2. A symbol library reference update propagates to all schematic instances using that symbol
  3. A footprint library reference update propagates to all components using that footprint
  4. Project context is auto-detected (project root, library paths, configuration) from any KiCad file path
  5. A structural diff between two KiCad files shows syntax-aware, semantically meaningful differences
**Plans**: 4 plans

Plans:
- [x] 06-01-PLAN.md -- Cross-file atomic operations (schematic-to-PCB consistency)
- [x] 06-02-PLAN.md -- Library reference propagation (symbol and footprint)
- [x] 06-03-PLAN.md -- Project context detection and auto-discovery
- [x] 06-04-PLAN.md -- Structural diff generation with difftastic integration

### Phase 7: GSD Skill Integration
**Goal**: The kicad-agent is invokable from any KiCad project via the GSD Skill interface, and from the terminal via CLI
**Depends on**: Phase 6
**Requirements**: SKILL-01, SKILL-02, SKILL-03, SKILL-04
**Success Criteria** (what must be TRUE):
  1. A GSD Skill manifest exists at ~/.claude/skills/kicad-agent/ declaring all kicad-agent capabilities
  2. An operation request from Claude routes through the skill handler to the Python backend and returns a formatted result
  3. The CLI wrapper runs any operation directly from the terminal without Claude
  4. A project context summary is renderable for any KiCad project directory (file types, component count, net count, validation status)
**Plans**: 4 plans

Plans:
- [x] 07-01-PLAN.md -- GSD Skill manifest and prompt template (SKILL-01)
- [x] 07-02-PLAN.md -- Skill handler routing and result rendering (SKILL-02)
- [x] 07-03-PLAN.md -- CLI wrapper for direct terminal usage (SKILL-03)
- [x] 07-04-PLAN.md -- Project context renderer (SKILL-04)

### Phase 8: Visual Primitives for PCB Spatial Reasoning
**Goal**: AI reasons about PCB layouts using coordinate-grounded visual primitives -- points for pins/vias, bounding boxes for components, paths for traces, regions for net classes. Closes the Reference Gap where natural language fails to precisely describe spatial relationships.
**Depends on**: Phase 7
**Requirements**: VP-01, VP-02, VP-03, VP-04, VP-05, VP-06, VP-07, VP-08
**Success Criteria** (what must be TRUE):
  1. A PCB layer renders to a rasterized image with a mm-coordinate grid overlay
  2. Spatial primitives (points, boxes, paths, regions) are extractable from any parsed KiCad file
  3. A procedural maze-routing generator creates synthetic PCB puzzles solvable only by coordinate-grounded reasoning
  4. DRC violations produce spatially-grounded reports: "The via at `<point>` [45.2, 22.1] violates clearance from `<path>` [...]"
  5. Spatial queries return results: "find traces within 2mm of point (10, 15)"
  6. Rick agents (SI, PI, EMC, DFM) produce coordinate-grounded findings instead of text-only reports
**Plans**: 4 plans

Plans:
- [x] 08-01-PLAN.md -- PCB image renderer with coordinate grid overlay and spatial primitive extraction (VP-01, VP-02, VP-03)
- [x] 08-02-PLAN.md -- Procedural maze-routing generator and cold-start reasoning chain synthesis (VP-04, VP-05)
- [x] 08-03-PLAN.md -- Spatial query API and coordinate-grounded DRC/ERC report pipeline (VP-06, VP-07)
- [x] 08-04-PLAN.md -- Rick agent integration: coordinate-grounded findings for SI/PI/EMC/DFM reports (VP-08)

### Phase 9: GRPO Spatial Reasoning Training
**Goal**: Train a reward model for PCB spatial reasoning using GRPO (Group Relative Policy Optimization) on synthetic maze-routing data from Phase 8. The reward model learns to score coordinate-grounded reasoning chains, enabling RL-based training that closes the Reference Gap at scale -- not just for single boards but across arbitrary PCB topologies.
**Depends on**: Phase 8
**Requirements**: GRPO-01, GRPO-02, GRPO-03, GRPO-04, GRPO-05, GRPO-06, GRPO-07
**Success Criteria** (what must be TRUE):
  1. A dataset of 100k+ synthetic PCB maze-routing samples is generated from the Phase 8 maze generator with verified solutions
  2. Cold-start reasoning chains are synthesized at scale (violation -> coordinate -> spatial context -> fix) with DFS exploration traces
  3. A reward model scores coordinate-grounded reasoning chains with per-step dense rewards (format, quality, accuracy)
  4. GRPO training loop runs end-to-end: policy generates chains -> reward model scores -> policy updates
  5. Reward hacking is prevented via smooth penalty functions and multi-stage reward architecture
  6. Trained model shows measurable improvement on held-out maze-routing tasks vs baseline
  7. Training pipeline is reproducible with a single command and configurable hyperparameters
**Plans**: 4 plans

Plans:
- [x] 09-01-PLAN.md -- Synthetic data pipeline at scale (100k+ maze samples with verified solutions and difficulty grading)
- [x] 09-02-PLAN.md -- Cold-start reasoning chain synthesis at scale (DFS traces, verified chains, difficulty-graded samples)
- [x] 09-03-PLAN.md -- Reward model architecture (per-step dense rewards, format/quality/accuracy signals, anti-hacking penalties)
- [x] 09-04-PLAN.md -- GRPO training loop (policy generation, reward scoring, policy updates, evaluation on held-out tasks)

### Phase 10: AI-Driven PCB Generation
**Goal**: Two-tier phase -- first close the practical operations gap (project files, manufacturing exports, schematic repair, PCB operations), then build generative AI capabilities on top. Tier 1 operations are independently valuable; Tier 2 generation requires Tier 1.
**Depends on**: Phase 9
**Requirements**: GEN-01, GEN-02, GEN-03, GEN-04, GEN-05, GEN-06, GEN-07, GEN-08, GEN-09, GEN-10, GEN-11, GEN-12
**Success Criteria** (what must be TRUE):
  1. sym-lib-table and fp-lib-table can be parsed, queried, and modified (add/remove/list libraries)
  2. Manufacturing files (Gerber, drill, BOM, netlist, position) can be exported via kicad-cli wrappers
  3. Schematic ERC errors can be auto-repaired (wire snapping, orphaned labels, shorted nets)
  4. Power net validation detects unconnected power pins before PCB work begins
  5. Copper zones (ground/power pours) can be added and filled on PCB layouts
  6. Net classes and custom DRC rules can be set via .kicad_dru parser
  7. A GenerationIntent schema converts natural language design parameters to structured operation sequences
  8. Template board generation creates valid .kicad_pcb files from high-level parameters (size, layers, components)
  9. Component placement engine places components with clearance validation and spatial scoring
  10. End-to-end pipeline: intent -> template -> operations -> validation -> manufacturing export
  11. Iterative refinement loop: generate -> validate (ERC/DRC) -> fix -> repeat until clean
  12. Generated boards achieve DRC pass on simple designs (5-10 components with valid ERC)
**Plans**: 6 plans

Plans:
- [x] 10-01-PLAN.md -- Project file parsers and library management (sym-lib-table, fp-lib-table, .kicad_dru, .kicad_pro) (GEN-01, GEN-06)
- [x] 10-02-PLAN.md -- Manufacturing export wrappers (Gerber, drill, BOM, netlist, position, STEP, PDF via kicad-cli) (GEN-02)
- [x] 10-03-PLAN.md -- Schematic repair, validation gates, and PCB operations (ERC repair, power validation, copper zones, net classes, board outline) (GEN-03, GEN-04, GEN-05, GEN-06)
- [x] 10-04-PLAN.md -- GenerationIntent schema and template board generator (extends maze_generator pattern for real PCB/schematic creation) (GEN-07, GEN-08)
- [x] 10-05-PLAN.md -- Component placement engine and operation-sequence planning (placement algorithms, spatial validation, LLM-driven operation planning) (GEN-09)
- [x] 10-06-PLAN.md -- End-to-end generation pipeline with iterative refinement (full loop: intent -> board -> validate -> fix -> export) (GEN-10, GEN-11, GEN-12)

### Phase 11: LTspice Integration
**Goal**: Parse LTspice .asc schematic files, extract components, nets, and simulation commands, and build a bidirectional KiCad-LTspice bridge for simulation-driven design workflows
**Depends on**: Phase 1 (parser infrastructure)
**Requirements**: LTSPICE-01, LTSPICE-02, LTSPICE-03, LTSPICE-04, LTSPICE-05
**Success Criteria** (what must be TRUE):
  1. A .asc file parses into structured component/net/simulation data via SpiceLib
  2. Components with values, positions, orientations, and node connections are extractable
  3. Net connectivity graph is derivable from WIRE and FLAG statements
  4. Simulation commands (.tran, .ac, .dc, .noise) are extractable and parseable
  5. .raw simulation results are readable (voltage/current traces by node)
**Plans**: 3 plans

Plans:
- [x] 11-01-PLAN.md -- .asc parser with SpiceLib, frozen dataclass types, .asy symbol stubs, simulation command parser (LTSPICE-01, LTSPICE-02, LTSPICE-04)
- [x] 11-02-PLAN.md -- .raw simulation result reader with SpiceLib RawRead and trace extraction (LTSPICE-05)
- [x] 11-03-PLAN.md -- Net connectivity graph derivation from wire geometry using networkx (LTSPICE-03)

### Phase 12: ADI Footprint Library
**Goal**: On-demand fetching of ADI manufacturer footprints, symbols, and 3D models into KiCad library format, with caching and library management
**Depends on**: Phase 5 (footprint operations), Phase 10 (library management)
**Requirements**: ADI-01, ADI-02, ADI-03, ADI-04
**Success Criteria** (what must be TRUE):
  1. ADI footprints are discoverable by part number via web search or API
  2. .kicad_mod footprints download and import into local library
  3. .kicad_sym symbols download and import into local library
  4. Library cache avoids re-downloading previously fetched parts
**Plans**: 3 plans

Plans:
- [ ] 12-01-PLAN.md -- Type definitions, filesystem cache with JSON manifest, ZIP extraction safety (ADI-04)
- [ ] 12-02-PLAN.md -- SamacSys HTTP client for part search and KiCad library download (ADI-01)
- [ ] 12-03-PLAN.md -- Fetch orchestrator wiring cache/client/lib_table, integration tests, REQUIREMENTS.md update (ADI-01, ADI-02, ADI-03, ADI-04)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10 -> 11 -> 12

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation -- Parse, Serialize, Round-trip | 3/3 | Complete | 2026-05-18 |
| 2. Operation Schema and IR Layer | 3/3 | Complete | 2026-05-18 |
| 3. Validation Pipeline | 3/3 | Complete | 2026-05-18 |
| 4. Component Operations | 3/3 | Complete | 2026-05-18 |
| 5. Net, Reference, and Footprint Operations | 4/4 | Complete | 2026-05-18 |
| 6. Cross-File Operations and Analysis | 4/4 | Complete | 2026-05-18 |
| 7. GSD Skill Integration | 4/4 | Complete | 2026-05-18 |
| 8. Visual Primitives for PCB Spatial Reasoning | 4/4 | Complete | 2026-05-22 |
| 9. GRPO Spatial Reasoning Training | 4/4 | Complete | 2026-05-22 |
| 10. AI-Driven PCB Generation | 6/6 | Complete | 2026-05-23 |
| 11. LTspice Integration | 3/3 | Complete | 2026-05-23 |
| 12. ADI Footprint Library | 0/3 | Planned | 2026-05-23 |
