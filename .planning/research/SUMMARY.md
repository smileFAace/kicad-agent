# Research Summary: kicad-agent

**Domain:** KiCad 10+ automation agent (AI-safe structural editing of schematic, PCB, symbol library, and footprint library files)
**Researched:** 2026-05-18
**Overall confidence:** HIGH

## Executive Summary

kicad-agent fills a gap that no existing tool in the KiCad ecosystem addresses: AI-safe structural editing of existing KiCad designs through validated AST mutations. The KiCad file format is S-expression based with deep nesting, strict token ordering, fragile UUID references, and implicit electrical relationships. Generic LLMs fail catastrophically on these files because they cannot maintain balanced parentheses across hundreds of lines, respect positional token semantics, or preserve the fragile web of cross-references that makes a KiCad project coherent.

The solution architecture is a three-layer insulation between the LLM and the filesystem: (1) an Operation Schema where the LLM emits structured JSON intents instead of raw text, (2) an Intermediate Representation (IR) layer of canonical Python dataclasses that mutations operate on, and (3) a Validation Pipeline using kicad-cli for authoritative ERC/DRC checks after every mutation. The LLM never touches S-expressions. The tool layer guarantees structural validity at every intermediate state.

The technology stack is Python 3.11+ with kiutils 1.4.8 as the primary parser (KiCad-specific dataclass AST for all four file types), sexpdata 1.0.0 as a fallback for edge cases, pydantic 2.12.5 for JSON operation schema validation, networkx 3.4.2 for net connectivity graph analysis, and kicad-cli 10.0.1 for validation gates. All are verified installed locally except difftastic (needs `brew install difftastic`).

Critical pitfalls center on kiutils round-trip fidelity gaps (hidden property fields silently unhidden on save, dimension objects causing parse crashes), KiCad's inconsistent coordinate precision (4 decimal places for schematics vs 6 for PCBs), symbol text angle units stored in tenths of degrees while everything else uses degrees, and the library identifier system where nicknames are resolved through project-level tables rather than stored in the library files themselves. Each of these can silently corrupt files or break round-trip fidelity, and each requires explicit handling in the parser and serializer layers before any editing operations are built.

## Key Findings

**Stack:** Python 3.11+ / kiutils 1.4.8 (primary parser) / pydantic 2.12.5 (schema) / kicad-cli 10.0.1 (validation) / networkx 3.4.2 (graph analysis) / sexpdata 1.0.0 (fallback parser).

**Architecture:** Three-layer insulation -- LLM emits JSON intents, tool layer mutates IR dataclasses, serializer writes validated S-expressions. Transaction-based mutation with rollback on validation failure. kiutils-first parsing with sexpdata fallback.

**Critical pitfall:** kiutils v1.4.8 has known bugs that silently corrupt files on round-trip (hidden properties revealed, dimension objects crash parsing, scientific notation in floats). These must be patched or worked around before building any editing operations on top.

## Implications for Roadmap

Based on research, suggested phase structure:

1. **Phase 1: Foundation -- Parser, Serializer, Round-trip Fidelity**
   - Addresses: Parse all file types, round-trip fidelity, coordinate precision, angle units, token ordering
   - Avoids: Pitfall 1 (angle units), Pitfall 2 (coordinate precision), Pitfall 4 (kiutils round-trip gaps), Pitfall 7 (token ordering), Pitfall 13 (scientific notation)
   - Rationale: Everything else depends on correct parsing and lossless serialization. If parse/modify/save does not produce an identical file for unchanged data, no editing operation can be trusted. This phase must achieve zero-diff round-trip for all four file types before moving on.
   - Deliverables: Parser for all 4 file types, serializer with context-aware precision, round-trip test suite, kiutils bug patches/workarounds

2. **Phase 2: Operation Schema and IR Layer**
   - Addresses: Intent-based JSON operation schema, IR dataclasses, bidirectional mapping
   - Avoids: Pitfall 9 (AI-generated corruption), Pitfall 5 (library identifier resolution), Pitfall 6 (layer name canonicalization)
   - Rationale: The operation schema is the contract between LLM and tool layer. The IR layer is what mutations operate on. Both must be designed and validated before any editing features are built. This phase defines the API surface.
   - Deliverables: Pydantic operation models, IR dataclasses for all entity types, bidirectional kiutils-to-IR mapping, schema documentation for LLM consumption

3. **Phase 3: Validation Pipeline**
   - Addresses: ERC/DRC gates, structural checks, UUID integrity, net consistency
   - Avoids: Pitfall 3 (UUID collision), Pitfall 8 (net inconsistency), Pitfall 10 (kicad-cli version compatibility)
   - Rationale: Validation must be in place before any mutation is attempted. The pipeline catches errors before they compound. kicad-cli version detection, structural validation, and ERC/DRC invocation must all be tested and reliable.
   - Deliverables: Validation pipeline orchestrator, ERC wrapper, DRC wrapper, structural validator, UUID uniqueness checker, kicad-cli version detection

4. **Phase 4: Component Operations**
   - Addresses: Component CRUD, reference management, footprint assignment
   - Avoids: Pitfall 14 (group member UUID references), Pitfall 16 (concurrent file access)
   - Rationale: Component operations are the most common editing task. They exercise the full pipeline (parse, mutate, serialize, validate) on a single file type first. Flat schematics only -- hierarchical sheets deferred.
   - Deliverables: Add/delete/duplicate/move component operations, reference renumbering, footprint assignment, transaction wrapper, backup/rollback mechanism

5. **Phase 5: Net Operations and Cross-File Consistency**
   - Addresses: Net operations, bus operations, schematic-to-PCB net consistency
   - Avoids: Pitfall 8 (net inconsistency between schematic and PCB), Pitfall 15 (floating-point drift)
   - Rationale: Net operations require understanding connectivity as a graph, not just individual connections. Cross-file consistency requires atomic operations across schematic and PCB. This is the most complex editing phase.
   - Deliverables: Add/delete/rename net operations, bus operations, net connectivity graph, schematic-to-PCB consistency validator, cross-file atomic transactions

6. **Phase 6: Structural Diffs and Analysis**
   - Addresses: Structural diffs, change impact analysis, connectivity analysis
   - Rationale: Diffs and analysis are valuable for verification but do not mutate files. They can be built once the editing pipeline is stable and tested.
   - Deliverables: difftastic integration, KiCad-semantic diff layer, networkx connectivity analysis, change impact reporter

7. **Phase 7: GSD Skill Integration**
   - Addresses: Skill manifest, prompt template, result rendering, project context detection
   - Rationale: The skill interface is thin -- it maps LLM requests to JSON operations and formats results. It depends on a stable Python library API, so it comes last.
   - Deliverables: Skill manifest and prompt at ~/.claude/skills/kicad-agent/, handler, renderer, context detection

**Phase ordering rationale:**
- Phase 1 must come first because everything depends on correct parsing and serialization
- Phase 2 (schema/IR) must come before Phase 3 (validation) because validation checks IR invariants
- Phase 3 must come before Phase 4 (operations) because operations must be validated before committing
- Phase 4 (component ops) before Phase 5 (net ops) because component operations are simpler and exercise the full pipeline on single files
- Phase 6 (diffs/analysis) is independent of Phases 4-5 but benefits from a tested editing pipeline
- Phase 7 (skill) comes last because it wraps the stable library API

**Research flags for phases:**
- Phase 1: **Critical research needed** -- kiutils round-trip fidelity must be verified against real KiCad 10 files. Known bugs (hidden properties, dimension objects, scientific notation) may require upstream patches or local workarounds. Test with real-world PCBs containing dimensions, hidden properties, and small coordinate values.
- Phase 2: Standard patterns -- Pydantic schema design and IR dataclass modeling are well-understood. Low risk.
- Phase 3: **Needs research** -- kicad-cli output format parsing (ERC/DRC JSON output structure) needs verification against KiCad 10. Exit codes and error formats may differ from documentation.
- Phase 4: Standard patterns -- CRUD operations on dataclasses. Transaction/rollback is a well-known pattern.
- Phase 5: **Moderate research needed** -- KiCad net naming conventions (especially hierarchical bus naming) need verification. Net consistency between schematic and PCB requires understanding the netlist format.
- Phase 6: Standard patterns -- difftastic integration is straightforward. Semantic diff layer requires KiCad domain knowledge.
- Phase 7: Standard patterns -- GSD Skill definitions follow a known format.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All technologies verified locally (kiutils 1.4.8, sexpdata 1.0.0, pydantic 2.12.5, networkx 3.4.2, kicad-cli 10.0.1). Context7 docs consulted for kiutils, pydantic, sexpdata, networkx. |
| Features | HIGH | Feature landscape derived from PROJECT.md requirements and competitive analysis against KiBot, Circuit-Synth, atopile, Kigadgets, kiutils. Table stakes are clear (parsing, round-trip, validation, CRUD). Anti-features are well-defined. |
| Architecture | HIGH | Three-layer architecture (schema/IR/serialization) is standard for AST-mutation tools. kiutils provides the parse/serialize backbone. Transaction-based mutation with validation gates is a proven pattern. |
| Pitfalls | HIGH | 18 pitfalls documented with sources from KiCad official S-expression spec, kiutils GitHub issues, Context7 docs, and local verification. Critical pitfalls (round-trip fidelity gaps, coordinate precision, angle units) are all verified against authoritative sources. |

## Gaps to Address

- **KiCad 10 format changes beyond the spec:** KiCad 10 may have undocumented format changes that the official S-expression specification does not cover. Testing against real KiCad 10 files in Phase 1 will reveal these.
- **kicad-cli ERC/DRC output format:** The exact JSON output format of kicad-cli ERC/DRC commands needs verification against KiCad 10. Error parsing depends on this format.
- **kiutils dimension object support:** kiutils issue #107 indicates dimensions cause parse crashes. Real-world PCBs often contain dimensions. Phase 1 must test this and implement the sexpdata fallback or contribute upstream fixes.
- **Concurrent editing safety:** KiCad's .lck file format is not officially documented. The exact behavior when kicad-agent and KiCad GUI operate on the same project needs testing.
- **Hierarchical sheet reference propagation:** Multi-sheet hierarchical designs have complex reference propagation that the S-expression spec documents but which needs empirical verification during implementation.
- **Performance characteristics:** kicad-cli DRC invocation latency (~5-30s) on large boards may impact the editing workflow. Caching or incremental validation strategies may be needed.

## Sources

### HIGH Confidence
- KiCad S-expression file format specification (dev-docs.kicad.org/en/file-formats/sexpr-intro/) -- authoritative source for token ordering, coordinate precision, angle units, layer names, library identifiers, UUID generation
- kiutils GitHub issues -- #120 (hidden properties), #107 (dimensions), #102 (pad layers), #14 (scientific notation), #81 (legacy tokens)
- Context7 library documentation for kiutils, pydantic, sexpdata, networkx
- Local verification of kiutils 1.4.8, sexpdata 1.0.0, pydantic 2.12.5, networkx 3.4.2, kicad-cli 10.0.1

### MEDIUM Confidence
- KiCad mt19937 UUID collision risk -- documented in spec, practical risk inferred from algorithm properties
- kicad-cli version compatibility -- based on general KiCad release patterns
- Net consistency patterns -- based on KiCad's netlist export/import model
- Competitive feature analysis -- based on GitHub READMEs and Context7 scores for KiBot, Circuit-Synth, atopile, Kigadgets

### LOW Confidence
- KiCad .lck file format -- not officially documented, behavior inferred from community reports
- Legacy file conversion edge cases -- documented in spec but not empirically tested
- KiCad 10 specific undocumented changes -- not verified against running installation

---
*Research summary for: kicad-agent (KiCad 10+ automation agent)*
*Researched: 2026-05-18*
*Confidence: HIGH*
