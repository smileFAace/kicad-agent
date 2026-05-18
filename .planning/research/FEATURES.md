# Feature Research

**Domain:** KiCad automation agent (structural editing via AI-safe AST mutation)
**Researched:** 2026-05-17
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Parse all KiCad 10+ file types | Without parsing, nothing else works. Users expect .kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod support. | HIGH | kiutils handles parsing for all four types. S-expression grammar is deep and ordering-constrained. Must preserve comments, formatting, and whitespace to maintain diffability. |
| Round-trip fidelity | Parse -> modify -> serialize must produce a valid KiCad file that KiCad itself can open without errors. Users will not trust a tool that corrupts files. | HIGH | kiutils provides load/modify/save round-trips. Must test against kicad-cli `export` commands as validation. Ordering preservation is the hardest part -- KiCad is sensitive to token order in some contexts. |
| ERC/DRC validation gates | Any EDA automation tool must validate electrical and design rules. Users expect errors to be caught before they compound. | MEDIUM | kicad-cli provides `erc` and `drc` subcommands. Parse the JSON output for structured error reporting. Must run after every edit batch, not just at the end. |
| Component CRUD operations | Add, delete, modify, duplicate, replicate components. Core operation for any schematic/PCB editing tool. | MEDIUM | kiutils exposes symbol instances on schematics and footprints on PCBs. Operations must maintain UUID uniqueness, reference designator conventions, and library link integrity. |
| Net operations | Add/remove/rename nets, bus operations. Schematic connectivity is the core data model. | MEDIUM | Nets are implicit in KiCad (connection by name or wire, not explicit net objects in all cases). Must trace wire connectivity and pin connections to determine net membership. Bus operations add another layer. |
| Reference management | Renumber refs (R1, R2, C1...), validate uniqueness, cross-reference between schematic and PCB. | LOW | Straightforward string manipulation with kiutils. The tricky part is maintaining symbol instance mapping across hierarchical sheets. |
| Schematic-to-PCB net consistency | Verify the netlist is consistent between schematic and PCB. If they diverge, the board is broken. | MEDIUM | Requires parsing both file types and comparing net membership. KiCad's netlist is the bridge -- must understand the netlist format to do this correctly. |
| Footprint assignment and validation | Assign footprints to symbols, verify footprint exists in library, swap footprints. | LOW | kiutils provides footprint library parsing. Validation is a lookup against available libraries. Swapping is a property update on the symbol instance. |

### Differentiators (Competitive Advantage)

Features that set the product apart. Not required, but valuable.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Intent-based JSON operation schema | The LLM never touches raw S-expressions. It emits structured JSON intents that the tool layer executes as AST mutations. This is the core differentiator -- it prevents the class of errors that killed all previous attempts at LLM KiCad editing. | HIGH | Must define a complete operation schema covering all file types and operation types. Schema validation must happen before any AST mutation. Operations should be composable -- a single intent can trigger multiple mutations. |
| AST-safe structural editing | All mutations go through a validated AST layer, not string manipulation. Guarantees structural validity at every intermediate state. | HIGH | Build on kiutils' AST representation. Wrap every mutation in a transaction -- if validation fails, roll back to the previous valid state. This is what makes the tool trustworthy. |
| Automated error recovery | When an edit fails ERC/DRC, automatically attempt to fix the error or roll back to the last valid state. Users should never be left with a broken file. | MEDIUM | Requires structured error parsing from kicad-cli output, then mapping errors to corrective operations. Start with rollback-only (safe), add automated fix attempts later. |
| Structural diffs (syntax-aware) | S-expression-aware diffs that understand KiCad structure, not line-based diffs. Shows what actually changed semantically, not just textually. | MEDIUM | difftastic provides syntax-aware diffing. Must integrate it and add KiCad-specific semantic layer (e.g., "capacitor value changed from 100nF to 220nF" not just "token 47 changed"). |
| UUID integrity verification | Every edit preserves and validates UUID references across all file types. KiCad's internal linking depends on UUIDs being stable. | LOW | UUIDs are managed by kiutils. Verification is a graph traversal -- every UUID referenced in a PCB must exist in the corresponding schematic and symbol library. |
| Cross-file-type atomic operations | A single operation can touch schematic + PCB + symbol library atomically. E.g., "add this component" creates the symbol instance, places the footprint, and adds the net connections in one transaction. | HIGH | Requires a transaction coordinator that tracks mutations across multiple file objects. All-or-nothing semantics -- if any part fails, roll back everything. |
| GSD Skill integration | Invoke from any KiCad project via /kicad-agent skill. Works with Council of Ricks for multi-perspective review, Beads for tracking, Confucius for pattern memory. | LOW | Standard GSD skill definition. The skill interface maps user requests to JSON operations. Integration is primarily configuration, not architecture. |
| Natural language to schematic changes | User describes what they want in plain English, the agent translates to JSON operations, executes, and validates. The entire workflow is conversational. | HIGH | Depends on a well-designed operation schema and comprehensive error messages. The LLM must understand KiCad concepts (nets, symbols, footprints, design rules) to generate correct operations. Prompt engineering is the primary challenge. |
| Hierarchical sheet support | Navigate and edit multi-sheet hierarchical schematics. Most real designs use hierarchy, but most tools ignore it. | HIGH | Hierarchical sheets in KiCad have complex reference propagation, label scoping, and instance tracking. Must understand sheet pins, hierarchical labels, and how symbols instantiate across sheets. |
| Design rule constraint validation | Beyond ERC/DRC -- check custom design rules, differential pair constraints, length matching, impedance requirements. | MEDIUM | KiCad 10 has extended DRC rules. Parse custom rule files and validate against them. This catches errors that standard DRC misses. |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Auto-routing | Users want automated PCB routing. | Fundamentally different problem (NP-hard optimization, geometric constraints, manufacturing rules). Scope explosion that would consume the entire project.-routing-rick agent handles this separately. | Delegate to routing-rick agent. kicad-agent provides the structural editing primitives that routing-rick consumes. |
| Raw S-expression editing | "Just let me edit the text directly, it's faster." | LLMs generate structurally invalid S-expressions at high rates. Deeply nested parentheses, ordering constraints, and UUID references make raw text editing unreliable. This is exactly the problem kicad-agent exists to solve. | JSON operation schema. Every edit goes through validated AST mutations. |
| KiCad 8.x/9.x backward compatibility | Users on older KiCad want support. | File format differences between versions are significant (token names, structure, UUID formats). Supporting multiple versions doubles the parser complexity and halves the test coverage per version. | KiCad 10+ only. Users can upgrade KiCad (it's free). Focus effort on one version done right. |
| GUI/editor integration | "Can you show me the schematic in a window?" | Rendering a schematic editor is an entire application (tens of thousands of lines). KiCad's own GUI is Qt-based and deeply coupled. This is not an automation tool's job. | CLI and skill interface only. Users view results in KiCad itself. kicad-agent modifies files, KiCad displays them. |
| SPICE simulation | "Run simulations on the circuit." | Simulation requires understanding SPICE models, simulation kernels, convergence analysis. Entirely separate domain from structural editing. | Out of scope. KiCad's built-in simulator handles this. |
| 3D model manipulation | "Place and orient 3D models." | 3D model handling involves rendering, collision detection, STEP file manipulation. Different skill set and tooling from S-expression editing. | Out of scope for v1. May be a future extension if demand exists. |
| CI/CD pipeline generation | "Generate my GitHub Actions workflow." | KiBot already does this excellently. Duplicating KiBot's CI/CD capabilities is wasted effort. | Recommend KiBot for CI/CD. kicad-agent focuses on structural editing, not pipeline generation. |
| Visual BOM generation | "Show me an interactive HTML BOM." | InteractiveHtmlBom does this and is mature (4.4k stars). Not kicad-agent's value proposition. | Recommend InteractiveHtmlBom. kicad-agent can export BOM data in a format that InteractiveHtmlBom consumes. |
| Code-driven circuit design | "Define my circuit in Python/declarative language." | Circuit-Synth and atopile already own this space. kicad-agent's value is editing existing designs, not creating new design paradigms. | Focus on structural editing of existing KiCad files. Users who want code-driven design should use Circuit-Synth or atopile. |

## Feature Dependencies

```
[Parse All File Types]
    |
    +--requires--> [Round-trip Fidelity]
    |                  |
    |                  +--requires--> [ERC/DRC Validation Gates]
    |                  |                  |
    |                  |                  +--enables--> [Automated Error Recovery]
    |                  |
    |                  +--requires--> [Component CRUD Operations]
    |                  |                  |
    |                  |                  +--requires--> [Reference Management]
    |                  |                  |
    |                  |                  +--enables--> [Cross-file-type Atomic Operations]
    |                  |
    |                  +--requires--> [Net Operations]
    |                  |                  |
    |                  |                  +--requires--> [Schematic-to-PCB Net Consistency]
    |                  |
    |                  +--requires--> [Footprint Assignment and Validation]
    |
    +--requires--> [UUID Integrity Verification]
    |
    +--enables--> [Intent-based JSON Operation Schema]
                      |
                      +--enables--> [Natural Language to Schematic Changes]
                      |
                      +--enables--> [GSD Skill Integration]

[Component CRUD] --enhances--> [Hierarchical Sheet Support]

[Structural Diffs] --independent--> (can be built in parallel)

[Design Rule Constraint Validation] --extends--> [ERC/DRC Validation Gates]

[Auto-routing] --conflicts--> [Core Scope] (separate agent)
[Raw S-expression Editing] --conflicts--> [Intent-based Schema] (fundamentally opposed)
```

### Dependency Notes

- **Parse All File Types requires Round-trip Fidelity:** Without reliable round-trip, parsing is useless. The parse/modify/serialize pipeline must be validated end-to-end before any editing features are built.
- **ERC/DRC Validation Gates requires Round-trip Fidelity:** You cannot validate a file that cannot be serialized correctly. Validation runs on the output, so serialization must work first.
- **Automated Error Recovery enables via ERC/DRC Validation Gates:** Error recovery needs structured error output from kicad-cli to know what to fix. The validation gate provides the error signal.
- **Cross-file-type Atomic Operations requires Component CRUD:** Atomic multi-file operations are compositions of single-file CRUD operations. Each single-file operation must be reliable before composing them.
- **Intent-based JSON Operation Schema enables Natural Language to Schematic Changes:** The JSON schema is the contract between the LLM and the tool layer. Without it, there is no structured way to translate natural language to file mutations.
- **GSD Skill Integration enables via Intent-based Schema:** The skill interface maps user requests to JSON operations. The schema IS the skill's API.
- **Component CRUD enhances Hierarchical Sheet Support:** Hierarchical sheets multiply the complexity of component operations (sheet-local refs, propagation, instance tracking). CRUD must work on flat sheets first.
- **Structural Diffs is independent:** Diff generation does not mutate files. It can be built in parallel with the editing pipeline. It is still valuable from day one for verifying edit correctness.
- **Auto-routing conflicts with Core Scope:** Auto-routing is a fundamentally different problem class. Including it would expand scope beyond what is achievable in v1. routing-rick agent owns this.
- **Raw S-expression Editing conflicts with Intent-based Schema:** These are architecturally opposed. The entire point of kicad-agent is that the LLM never touches raw text. Allowing raw editing undermines the safety guarantee.

## MVP Definition

### Launch With (v1)

Minimum viable product -- what is needed to validate the concept.

- [ ] Parse all KiCad 10+ file types (.kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod) -- without this, nothing else matters
- [ ] Round-trip fidelity (parse -> modify -> serialize produces valid files KiCad can open) -- the core trust proposition
- [ ] Intent-based JSON operation schema -- the API contract that makes AI-safe editing possible
- [ ] Component CRUD operations on flat schematics -- the most common editing operation
- [ ] ERC/DRC validation gates via kicad-cli -- catch errors before they compound
- [ ] UUID integrity verification -- KiCad files are unusable with broken UUIDs

### Add After Validation (v1.x)

Features to add once core is working.

- [ ] Net operations and bus operations -- trigger: component CRUD is stable and users need connectivity changes
- [ ] Schematic-to-PCB net consistency checks -- trigger: both file types are reliably parsed and modified
- [ ] Automated error recovery (rollback-only first) -- trigger: ERC/DRC gates are proven reliable
- [ ] Structural diffs via difftastic -- trigger: users need to verify what changed after edits
- [ ] Cross-file-type atomic operations -- trigger: single-file operations are proven stable
- [ ] GSD Skill integration -- trigger: the Python library API is stable enough to expose as a skill
- [ ] Reference renumbering and validation -- trigger: component operations are stable

### Future Consideration (v2+)

Features to defer until product-market fit is established.

- [ ] Hierarchical sheet support -- complex reference propagation, most users start with flat sheets
- [ ] Natural language to schematic changes -- requires mature operation schema and extensive prompt engineering
- [ ] Automated error recovery with fix attempts -- rollback-only is safe; attempting fixes requires confidence in corrective operations
- [ ] Design rule constraint validation (beyond standard ERC/DRC) -- KiCad 10 custom rules
- [ ] Footprint library management operations -- separate concern from schematic editing
- [ ] Array/replicate sections -- composition of basic CRUD operations, add when basic ops are proven

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Parse all KiCad 10+ file types | HIGH | HIGH | P1 |
| Round-trip fidelity | HIGH | HIGH | P1 |
| Intent-based JSON operation schema | HIGH | HIGH | P1 |
| ERC/DRC validation gates | HIGH | MEDIUM | P1 |
| UUID integrity verification | HIGH | LOW | P1 |
| Component CRUD operations | HIGH | MEDIUM | P1 |
| Structural diffs | MEDIUM | MEDIUM | P2 |
| Net operations | HIGH | MEDIUM | P2 |
| Schematic-to-PCB net consistency | MEDIUM | MEDIUM | P2 |
| Reference management | MEDIUM | LOW | P2 |
| Automated error recovery (rollback) | MEDIUM | MEDIUM | P2 |
| GSD Skill integration | MEDIUM | LOW | P2 |
| Cross-file-type atomic operations | MEDIUM | HIGH | P3 |
| Natural language to schematic changes | HIGH | HIGH | P3 |
| Hierarchical sheet support | MEDIUM | HIGH | P3 |
| Footprint assignment and validation | LOW | LOW | P2 |
| Design rule constraint validation | LOW | MEDIUM | P3 |
| Automated error recovery (with fixes) | MEDIUM | HIGH | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | KiBot | Circuit-Synth | atopile | Kigadgets | kiutils | Our Approach |
|---------|-------|---------------|---------|-----------|---------|--------------|
| File parsing | No (operates on existing files) | No (generates from code) | No (generates from .ato) | No (wraps pcbnew API) | Yes (all KiCad types) | Build on kiutils AST, add mutation layer |
| Structural editing | No (export/generation only) | Partial (code-driven generation) | Partial (code-driven generation) | Yes (via pcbnew wrapper) | Partial (load/modify/save) | Intent-based JSON -> AST mutation. kiutils does the parse/serialize, we add the safe mutation layer |
| ERC/DRC validation | Yes (preflights, DRC checks) | No | No | Partial (via pcbnew) | No | kicad-cli ERC/DRC after every edit. Structured error parsing for automated feedback |
| AI integration | No | Yes (Claude Code agents for circuit design) | No | No | No | LLM emits JSON operations, never touches files. AI at the intent layer, not the editing layer |
| Round-trip fidelity | N/A (read-only/export) | N/A (generates new projects) | N/A (generates new projects) | Partial | Yes (primary purpose) | Strict round-trip testing against kicad-cli. Every mutation validated before commit |
| Cross-file consistency | Partial (BoM consolidation) | No | No | No | No | Atomic transactions across schematic + PCB + libraries. All-or-nothing semantics |
| CI/CD integration | Yes (primary strength: GitHub Actions, Docker) | No | Partial (VS Code) | No | No | Explicitly out of scope. Recommend KiBot for CI/CD |
| Hierarchical sheets | No | No | No | No | Partial (parses them) | Full hierarchical support in v2. Flat sheets first |
| Diff generation | No | No | No | No | No | difftastic for syntax-aware diffs + KiCad semantic layer |
| Error recovery | No | No | No | No | No | Rollback to last valid state on failure. Attempted fixes in v2 |

### Competitive Position

**kicad-agent occupies a gap that no existing tool fills:** AI-safe structural editing of existing KiCad designs.

- **KiBot** owns export/fabrication/CI/CD. Do not compete here.
- **Circuit-Synth** owns code-driven circuit creation from scratch. Do not compete here.
- **atopile** owns declarative circuit design. Do not compete here.
- **Kigadgets** provides a simplified Python API for pcbnew. Complementary, not competitive.
- **kiutils** is the parsing foundation we build on. It is a library, not a tool.

The gap is: an AI-facing tool that can safely modify existing KiCad designs through structured operations, with validation gates that catch errors before they corrupt files. Nothing in the ecosystem does this today.

## Sources

- KiBot v1.8.4 GitHub README and ReadTheDocs -- fabrication/export automation, CI/CD integration, preflights
- Circuit-Synth (Context7 score 83.8) -- AI-native code-driven circuit design, Claude Code agent integration
- atopile (Context7 score 78.5) -- declarative language for circuit design, constraint solving
- Kigadgets/kicad-python (Context7 score 77.1) -- simplified pcbnew wrapper
- kiutils (Context7 score 44.55) -- KiCad file parsing library, load/modify/save round-trips
- KiCad Pcbnew Python API (Context7 score 56.2) -- full scripting API for board manipulation
- InteractiveHtmlBom (GitHub 4.4k stars) -- visual BOM generation with PCB overlay
- PROJECT.md at ~/apps/kicad-agent/.planning/PROJECT.md -- project definition and requirements

---
*Feature research for: kicad-agent (KiCad automation agent)*
*Researched: 2026-05-17*
