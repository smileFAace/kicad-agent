# Roadmap: kicad-agent

## Overview

Build an AI-safe KiCad structural editing tool in 7 phases: first achieve zero-diff round-trip parsing for all file types, then define the operation schema that insulates the LLM from raw S-expressions, then install validation gates before any mutation is attempted, then build editing operations from simple (components) to complex (nets, cross-file), add read-only analysis tools, and finally wrap it all in a GSD Skill for Claude integration.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation -- Parse, Serialize, Round-trip** - Parse all 4 KiCad file types with zero-diff round-trip fidelity
- [x] **Phase 2: Operation Schema and IR Layer** - Define the JSON intent contract and IR dataclasses that insulates the LLM from raw S-expressions
- [x] **Phase 3: Validation Pipeline** - ERC/DRC gates, structural checks, and error recovery before any mutation
- [ ] **Phase 4: Component Operations** - Add, remove, duplicate, move, and modify components with transaction safety
- [ ] **Phase 5: Net, Reference, and Footprint Operations** - Net CRUD, bus operations, reference management, footprint assignment
- [ ] **Phase 6: Cross-File Operations and Analysis** - Schematic-to-PCB consistency, library propagation, structural diffs, connectivity analysis
- [ ] **Phase 7: GSD Skill Integration** - Claude skill manifest, handler, CLI wrapper, and project context renderer

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
- [ ] 04-01-PLAN.md -- Operation executor, add_component and remove_component handlers (COMP-01, COMP-02)
- [ ] 04-02-PLAN.md -- Duplicate and array replicate handlers with linear/circular/matrix patterns (COMP-03, COMP-04)
- [ ] 04-03-PLAN.md -- Move/reposition and property modification handlers (COMP-05, COMP-06)

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
- [ ] 05-01-PLAN.md -- Net CRUD and bus operations (NET-01, NET-02, NET-03, NET-04)
- [ ] 05-02-PLAN.md -- Reference management (renumber, validate, annotate, cross-reference) (REF-01, REF-02, REF-03, REF-04)
- [ ] 05-03-PLAN.md -- Footprint management (assign, swap, validate, pin mapping) (FP-01, FP-02, FP-03, FP-04)
- [ ] 05-04-PLAN.md -- Net connectivity graph analysis via networkx (NET-05)

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
- [ ] 06-01-PLAN.md -- Cross-file atomic operations (schematic-to-PCB consistency)
- [ ] 06-02-PLAN.md -- Library reference propagation (symbol and footprint)
- [ ] 06-03-PLAN.md -- Project context detection and auto-discovery
- [ ] 06-04-PLAN.md -- Structural diff generation with difftastic integration

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
- [ ] 07-01-PLAN.md -- GSD Skill manifest and prompt template (SKILL-01)
- [ ] 07-02-PLAN.md -- Skill handler routing and result rendering (SKILL-02)
- [ ] 07-03-PLAN.md -- CLI wrapper for direct terminal usage (SKILL-03)
- [ ] 07-04-PLAN.md -- Project context renderer (SKILL-04)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation -- Parse, Serialize, Round-trip | 3/3 | Complete | 2026-05-18 |
| 2. Operation Schema and IR Layer | 3/3 | Complete | 2026-05-18 |
| 3. Validation Pipeline | 3/3 | Complete | 2026-05-18 |
| 4. Component Operations | 0/3 | Not started | - |
| 5. Net, Reference, and Footprint Operations | 0/4 | Not started | - |
| 6. Cross-File Operations and Analysis | 0/4 | Not started | - |
| 7. GSD Skill Integration | 0/4 | Not started | - |
