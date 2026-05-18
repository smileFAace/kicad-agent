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
- [ ] **NET-05**: Net connectivity graph analysis via networkx

### Reference Management

- [x] **REF-01**: Renumber references with configurable prefix and sequencing
- [x] **REF-02**: Validate reference uniqueness across schematic sheets
- [x] **REF-03**: Cross-reference check: verify symbol references resolve to valid library entries
- [x] **REF-04**: Annotate schematic: auto-assign references to unannotated components

### Footprint Management

- [ ] **FP-01**: Assign footprint to component with library nickname resolution
- [ ] **FP-02**: Swap footprint on existing component (preserves connections)
- [ ] **FP-03**: Validate footprint existence in configured library paths
- [ ] **FP-04**: Footprint-to-symbol pin mapping verification

### Validation

- [x] **VAL-01**: ERC gate via kicad-cli with structured result parsing (pass/fail/warning)
- [x] **VAL-02**: DRC gate via kicad-cli with structured result parsing
- [x] **VAL-03**: Net consistency verification between schematic and PCB netlists
- [ ] **VAL-04**: Structural/syntax-aware diff generation for S-expressions (difftastic integration)
- [x] **VAL-05**: Pre-mutation structural validation (catch invalid operations before execution)
- [x] **VAL-06**: Automated error recovery: rollback to last valid state on validation failure
- [x] **VAL-07**: Round-trip fidelity regression test suite (parse -> serialize -> compare)

### Cross-File Operations

- [ ] **XFILE-01**: Schematic <-> PCB atomic operations (maintain consistency during edits)
- [ ] **XFILE-02**: Symbol library reference update propagation
- [ ] **XFILE-03**: Footprint library reference update propagation
- [ ] **XFILE-04**: Project context detection: auto-discover project root, libraries, configuration

### GSD Skill Integration

- [ ] **SKILL-01**: GSD Skill manifest with kicad-agent capabilities
- [ ] **SKILL-02**: Skill handler: route operations from Claude to Python backend
- [ ] **SKILL-03**: CLI wrapper for direct terminal usage (independent of Claude)
- [ ] **SKILL-04**: Project context renderer: summarize KiCad project state for AI context

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
| NET-05 | Phase 5: Net/Ref/FP Operations | Pending |
| REF-01 | Phase 5: Net/Ref/FP Operations | Complete |
| REF-02 | Phase 5: Net/Ref/FP Operations | Complete |
| REF-03 | Phase 5: Net/Ref/FP Operations | Complete |
| REF-04 | Phase 5: Net/Ref/FP Operations | Complete |
| FP-01 | Phase 5: Net/Ref/FP Operations | Pending |
| FP-02 | Phase 5: Net/Ref/FP Operations | Pending |
| FP-03 | Phase 5: Net/Ref/FP Operations | Pending |
| FP-04 | Phase 5: Net/Ref/FP Operations | Pending |
| XFILE-01 | Phase 6: Cross-File + Analysis | Pending |
| XFILE-02 | Phase 6: Cross-File + Analysis | Pending |
| XFILE-03 | Phase 6: Cross-File + Analysis | Pending |
| XFILE-04 | Phase 6: Cross-File + Analysis | Pending |
| VAL-04 | Phase 6: Cross-File + Analysis | Pending |
| SKILL-01 | Phase 7: GSD Skill Integration | Pending |
| SKILL-02 | Phase 7: GSD Skill Integration | Pending |
| SKILL-03 | Phase 7: GSD Skill Integration | Pending |
| SKILL-04 | Phase 7: GSD Skill Integration | Pending |

**Coverage:**
- v1 requirements: 44 total
- Mapped to phases: 44
- Unmapped: 0

---
*Requirements defined: 2026-05-17*
*Last updated: 2026-05-18 after 05-01 plan completion*
