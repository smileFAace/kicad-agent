# Architecture Research

**Domain:** KiCad automation agent (structural S-expression editing via AI-safe operations)
**Researched:** 2026-05-17
**Confidence:** HIGH

---

## System Overview

```
+-------------------------------------------------------------------+
|                        GSD Skill Layer                             |
|   Claude Code skill at ~/.claude/skills/kicad-agent/               |
|   Invoked via /kicad-agent from any KiCad project                  |
+-------+---------------------------+-------------------------------+
        |                           |
        v                           v
+-------------------+   +------------------------+
| Operation Schema  |   |  Result Renderer        |
| (JSON intent API) |   |  (diff, summary, ERC/DRC|
| AddComponent,     |   |   report formatting)    |
| DeleteNet, etc.   |   +------------------------+
+-------+-----------+
        |
        v
+-------------------------------------------------------------------+
|                     Intermediate Representation (IR)               |
|   Canonical Python dataclasses: Component, Net, Pin, Sheet, Bus,  |
|   Footprint, Placement, Constraint, Hierarchy                     |
|   Bidirectional: KiCad S-expr <--> IR <--> Operation intent       |
+-------+---------------------------+-------------------------------+
        |                           |
        v                           v
+-------------------+   +------------------------+
|  Parser Layer     |   |  Serializer Layer       |
|  kiutils primary  |   |  kiutils to_sexpr()     |
|  sexpdata fallback|   |  sexpdata dumps()        |
|  for edge cases   |   |  for raw patching        |
+-------+-----------+   +-----------+------------+
        |                           |
        v                           v
+-------------------------------------------------------------------+
|                        KiCad Files on Disk                         |
|   .kicad_sch  .kicad_pcb  .kicad_sym  .kicad_mod                 |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|                     Validation Pipeline                            |
|   kicad-cli erc  |  kicad-cli drc  |  kicad-cli drc --erc        |
|   Structural: round-trip fidelity, UUID integrity, net consistency|
|   Every edit must pass ALL gates before committing changes        |
+-------------------------------------------------------------------+
```

### Why This Architecture

The core insight is that the LLM must never produce or modify raw S-expressions. The architecture enforces this by inserting two insulating layers between the AI and the file system:

1. **Operation Schema** -- The LLM emits structured JSON intents, not text. Each intent is validated against a schema before any mutation occurs.

2. **IR Layer** -- The parser converts KiCad S-expressions into canonical Python objects. Mutations happen on these objects, not on text. The serializer converts them back. This guarantees structural validity at every step.

kiutils provides the heavy lifting for parsing and serialization because it already understands KiCad's data model (dataclasses with `from_sexpr()` / `to_sexpr()`). sexpdata serves as a fallback for edge cases kiutils cannot handle (custom or future KiCad syntax). networkx provides graph analysis for net connectivity, dependency ordering, and change impact analysis.

---

## Component Responsibilities

| Component | Responsibility | Implementation |
|-----------|----------------|----------------|
| **GSD Skill** | Entry point for Claude Code invocations; skill manifest + prompt template at `~/.claude/skills/kicad-agent/` | YAML manifest + Markdown prompt |
| **Operation Schema** | Defines the JSON operation format the LLM emits; validates intents before execution | Pydantic models, JSON Schema |
| **Operation Router** | Dispatches validated operations to the correct IR mutator; handles operation composition and transactions | Python dispatcher pattern |
| **IR Layer** | Canonical Python dataclass representation of KiCad entities; bidirectional mapping to/from S-expressions | Python dataclasses, `@dataclass` |
| **Parser Layer** | Converts KiCad S-expression files into IR objects; handles all file types | kiutils (primary), sexpdata (fallback) |
| **Serializer Layer** | Converts IR objects back to valid KiCad S-expression files; preserves ordering and formatting | kiutils `to_sexpr()` (primary) |
| **Mutator Layer** | Applies operations to IR objects; enforces invariants (UUID uniqueness, ref uniqueness, net consistency) | Pure functions on IR dataclasses |
| **Validation Pipeline** | Runs ERC, DRC, structural checks after every mutation; rejects changes that fail any gate | kicad-cli subprocess + Python checks |
| **Diff Engine** | Produces structural diffs between original and modified files; syntax-aware, not line-based | difftastic (external), fallback to custom S-expr differ |
| **Graph Analyzer** | Net connectivity analysis, dependency graphs, change impact analysis | networkx directed graphs |
| **Result Renderer** | Formats results (diffs, summaries, error reports) for return to the LLM | Python string formatting |

---

## Recommended Project Structure

```
~/apps/kicad-agent/
+-- pyproject.toml                  # Project metadata, dependencies, entry points
+-- src/
|   +-- kicad_agent/
|       +-- __init__.py
|       +-- schema/                 # Operation schema definitions
|       |   +-- __init__.py
|       |   +-- operations.py       # Pydantic models for all operation types
|       |   +-- types.py            # Shared types (FileRef, ComponentRef, NetRef, etc.)
|       |   +-- validators.py       # Pre-mutation validation rules
|       +-- ir/                     # Intermediate representation
|       |   +-- __init__.py
|       |   +-- schematic.py        # Schematic IR: Component, Net, Pin, Sheet, Bus, Label
|       |   +-- pcb.py              # PCB IR: Footprint, Pad, Trace, Via, Zone
|       |   +-- library.py          # Library IR: Symbol, FootprintLib
|       |   +-- common.py           # Shared IR: Position, UUID, Property, Constraint
|       |   +-- mapping.py          # Bidirectional S-expr <--> IR converters
|       +-- parser/                 # File parsing
|       |   +-- __init__.py
|       |   +-- schematic_parser.py # .kicad_sch parsing via kiutils
|       |   +-- pcb_parser.py       # .kicad_pcb parsing via kiutils
|       |   +-- symbol_parser.py    # .kicad_sym parsing via kiutils
|       |   +-- footprint_parser.py # .kicad_mod parsing via kiutils
|       |   +-- raw_parser.py       # sexpdata fallback for edge cases
|       +-- serializer/             # File serialization
|       |   +-- __init__.py
|       |   +-- schematic_ser.py    # IR -> .kicad_sch
|       |   +-- pcb_ser.py          # IR -> .kicad_pcb
|       |   +-- symbol_ser.py       # IR -> .kicad_sym
|       |   +-- footprint_ser.py    # IR -> .kicad_mod
|       +-- mutator/                # IR mutation operations
|       |   +-- __init__.py
|       |   +-- component_ops.py    # add, delete, duplicate, array, move components
|       |   +-- net_ops.py          # add, delete, reroute nets, bus operations
|       |   +-- footprint_ops.py    # assign, swap, validate footprints
|       |   +-- reference_ops.py    # renumber, validate, cross-reference
|       |   +-- hierarchy_ops.py    # hierarchical sheet operations
|       |   +-- transaction.py      # Transaction wrapper (commit/rollback)
|       +-- validation/             # Validation pipeline
|       |   +-- __init__.py
|       |   +-- erc.py              # ERC via kicad-cli
|       |   +-- drc.py              # DRC via kicad-cli
|       |   +-- structural.py       # UUID integrity, ref uniqueness, net consistency
|       |   +-- roundtrip.py        # Parse-serialize-parse identity check
|       |   +-- pipeline.py         # Orchestrates all validation gates
|       +-- analysis/               # Graph and diff analysis
|       |   +-- __init__.py
|       |   +-- connectivity.py     # Net connectivity graph (networkx)
|       |   +-- dependency.py       # Component dependency ordering
|       |   +-- impact.py           # Change impact analysis
|       |   +-- differ.py           # Structural S-expression diffing
|       +-- skill/                  # GSD Skill integration
|       |   +-- __init__.py
|       |   +-- handler.py          # Main entry point called by Claude Code
|       |   +-- renderer.py         # Result formatting for LLM consumption
|       |   +-- context.py          # Project context detection and loading
|       +-- utils/                  # Shared utilities
|           +-- __init__.py
|           +-- sexpr_helpers.py    # S-expression manipulation helpers
|           +-- file_utils.py       # File I/O, backup, atomic writes
|           +-- errors.py           # Custom exception hierarchy
+-- tests/
|   +-- conftest.py                 # Shared fixtures, test KiCad files
|   +-- fixtures/                   # Sample .kicad_sch, .kicad_pcb files for testing
|   +-- test_schema/
|   +-- test_ir/
|   +-- test_parser/
|   +-- test_serializer/
|   +-- test_mutator/
|   +-- test_validation/
|   +-- test_analysis/
|   +-- test_roundtrip/             # Critical: parse -> modify -> serialize -> parse
+-- skills/                         # GSD Skill definition
    +-- kicad-agent/
        +-- manifest.yaml           # Skill metadata
        +-- prompt.md               # System prompt template
```

### Structure Rationale

- **`schema/` first** -- The operation schema is the contract between LLM and tool layer. Everything else depends on it. Build it first, validate it independently.

- **`ir/` second** -- The IR layer is the heart of the system. Once schema defines what operations exist, IR defines what they operate on. The `mapping.py` module handles bidirectional conversion between kiutils objects and IR dataclasses.

- **`parser/` and `serializer/` are separated** -- Parsing reads files into IR; serialization writes IR back to files. They have different error modes and testing strategies. Keep them separate even though they share the kiutils dependency.

- **`mutator/` depends on IR only** -- Mutators are pure functions that take IR objects and return new IR objects (immutable pattern). They never touch files directly. This makes them trivially testable.

- **`validation/` is a pipeline, not a monolith** -- Each validation type (ERC, DRC, structural, round-trip) is independent. The `pipeline.py` orchestrates them. This lets us run subsets of validation during development and the full pipeline before commit.

- **`analysis/` is optional for v1** -- networkx graph analysis adds value but is not on the critical path. Can be added incrementally.

- **`skill/` is thin** -- The GSD Skill handler is a thin adapter. It parses the LLM's operation JSON, routes through the system, and formats the result. No business logic here.

---

## Architectural Patterns

### Pattern 1: Intent-Based Mutation (Never Raw Text)

**What:** The LLM emits a JSON operation intent. The tool layer validates the intent, loads the file into IR, applies the mutation, serializes, and validates the result. The LLM never sees or produces S-expression text.

**When to use:** Always. This is the core invariant of the system.

**Trade-offs:**
- Pro: Guarantees structural validity. Impossible to produce malformed S-expressions from the LLM side.
- Pro: Operations are auditable, replayable, and composable.
- Con: Every new operation type requires schema definition + IR mutator + tests before the LLM can use it.
- Con: Unusual operations not covered by the schema require extending the system.

**Example operation:**
```python
# LLM emits this JSON:
{
    "operation": "add_component",
    "file": "motor-driver.kicad_sch",
    "component": {
        "library_id": "Device:R_Small_US",
        "reference": "R?",
        "value": "10k",
        "position": {"x": 50.0, "y": 30.0, "angle": 0}
    }
}

# Schema validates it (Pydantic):
class AddComponentOp(BaseModel):
    operation: Literal["add_component"]
    file: str
    component: ComponentSpec

# Router dispatches to mutator:
def add_component(schematic: SchematicIR, spec: ComponentSpec) -> SchematicIR:
    # 1. Load symbol from library
    # 2. Create IR Component with UUID
    # 3. Append to schematic.components
    # 4. Return new schematic (immutable)
    ...

# Serializer writes result:
schematic.to_file()
# Validation pipeline runs:
# kicad-cli erc, structural checks, round-trip check
```

### Pattern 2: Bidirectional IR Mapping

**What:** Every KiCad entity has a canonical IR representation. The mapping between IR and S-expressions is bidirectional and lossless. Parse to IR, mutate IR, serialize from IR.

**When to use:** For all file types. The IR is the single source of truth during mutation.

**Trade-offs:**
- Pro: Mutations operate on clean Python objects, not nested lists.
- Pro: Type-safe, IDE-friendly, testable.
- Pro: Can add derived fields (computed connectivity, validation state) without polluting the S-expression model.
- Con: Must maintain mapping for every KiCad entity type.
- Con: kiutils already provides dataclass-like objects; the IR adds a second layer. Justified because kiutils objects closely mirror S-expression structure (which is implementation-oriented, not operation-oriented).

**Example mapping:**
```python
# kiutils gives us this (implementation-oriented):
# board.footprints[0].pads[0].position.X

# IR gives us this (operation-oriented):
# component = schematic_ir.get_component_by_ref("R1")
# component.position.x, component.position.y
# component.pins["1"].net_name

# The mapping layer:
class SchematicMapping:
    @staticmethod
    def from_kiutils(sch: kiutils.schematic.Schematic) -> SchematicIR:
        """Convert kiutils schematic to canonical IR."""
        components = [
            ComponentIR(
                uuid=sym.uuid,
                reference=...,  # extract from properties
                lib_id=sym.libId,
                position=PositionIR(x=sym.position.X, y=sym.position.Y),
                pins=[PinIR(...) for pin in sym.pins],
            )
            for sym in sch.schematicSymbols
        ]
        return SchematicIR(components=components, ...)

    @staticmethod
    def to_kiutils(ir: SchematicIR) -> kiutils.schematic.Schematic:
        """Convert IR back to kiutils object for serialization."""
        ...
```

### Pattern 3: Transaction-Based Mutation

**What:** Mutations are wrapped in transactions. A transaction captures the original state, applies mutations, runs validation, and either commits (writes to disk) or rolls back (restores original).

**When to use:** For every file-modifying operation.

**Trade-offs:**
- Pro: Failed validation never leaves the file in a broken state.
- Pro: Enables operation composition (batch multiple operations, validate once).
- Pro: Natural rollback on any failure.
- Con: Memory overhead from keeping original state. Acceptable for KiCad file sizes.

**Example:**
```python
class Transaction:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.original_content = file_path.read_text()
        self.ir_original = parse(file_path)
        self.ir_modified = self.ir_original
        self.operations: list[Operation] = []

    def apply(self, operation: Operation) -> 'Transaction':
        """Apply an operation, return new transaction (immutable)."""
        self.ir_modified = execute_op(self.ir_modified, operation)
        self.operations.append(operation)
        return self

    def commit(self) -> TransactionResult:
        """Serialize, validate, write. Rollback on any failure."""
        try:
            serialized = serialize(self.ir_modified, self.file_path)
            result = validation_pipeline.run(self.file_path)
            if result.passed:
                return TransactionResult(success=True, validation=result)
            else:
                self.rollback()
                return TransactionResult(success=False, validation=result)
        except Exception:
            self.rollback()
            raise

    def rollback(self):
        """Restore original file content."""
        self.file_path.write_text(self.original_content)
```

### Pattern 4: Validation Pipeline with Hard Gates

**What:** Every mutation passes through a multi-stage validation pipeline. If any stage fails, the change is rejected and rolled back. Validation is non-negotiable.

**When to use:** After every `commit()`. Different pipelines for different file types (schematics get ERC, PCBs get DRC).

**Trade-offs:**
- Pro: Catches errors before they compound across files.
- Pro: kicad-cli is the official validation -- no reimplementing KiCad's own rules.
- Con: kicad-cli invocation has latency (~1-5 seconds per check).
- Con: Requires KiCad 10+ installed on the system.

**Validation stages:**
```
1. Structural checks (fast, Python-only)
   - UUID uniqueness
   - Reference uniqueness
   - Required fields present
   - S-expression well-formedness

2. Round-trip fidelity (fast, Python-only)
   - parse(file) -> serialize() -> parse(serialized) -> compare IR
   - Catches serializer bugs immediately

3. ERC (schematic files only, ~1-5s)
   - kicad-cli erc <file>
   - Parses output for errors (warnings are informational)

4. DRC (PCB files only, ~5-30s depending on board complexity)
   - kicad-cli drc <file>
   - Parses output for errors

5. Net consistency (when both sch and pcb exist)
   - Compare netlists between schematic and PCB
   - Flag unmatched nets, missing connections
```

### Pattern 5: kiutils-First, sexpdata-Fallback Parsing

**What:** Use kiutils as the primary parser for all standard KiCad file types. Fall back to sexpdata only when kiutils cannot parse a construct (custom properties, future syntax, non-standard elements).

**When to use:** Always start with kiutils. Only use sexpdata when kiutils raises a parse error or returns incomplete data.

**Trade-offs:**
- Pro: kiutils understands KiCad's data model natively -- dataclasses, types, named fields.
- Pro: No need to manually parse S-expression lists into structured objects.
- Pro: kiutils is maintained alongside KiCad releases.
- Con: kiutils may lag behind KiCad 10 syntax additions.
- Con: sexpdata fallback requires manual S-expression list traversal.

**Implementation strategy:**
```python
def parse_kicad_file(path: Path) -> IR:
    """Try kiutils first, fall back to sexpdata."""
    try:
        return parse_with_kiutils(path)
    except kiutilsParseError:
        logger.warning(f"kiutils failed on {path}, trying sexpdata fallback")
        return parse_with_sexpdata(path)

def parse_with_kiutils(path: Path) -> IR:
    """Parse using kiutils typed accessors."""
    suffix = path.suffix
    if suffix == '.kicad_sch':
        raw = kiutils.schematic.Schematic.from_file(str(path))
        return SchematicMapping.from_kiutils(raw)
    elif suffix == '.kicad_pcb':
        raw = kiutils.board.Board.from_file(str(path))
        return BoardMapping.from_kiutils(raw)
    # ... etc.

def parse_with_sexpdata(path: Path) -> IR:
    """Fallback: parse raw S-expressions, manually extract fields."""
    content = path.read_text()
    parsed = sexpdata.loads(content)
    return SExpressionMapping.from_raw(parsed)
```

---

## Data Flow

### Edit Operation Flow (Primary Path)

```
LLM emits JSON intent
    |
    v
[Schema Validation] -- invalid? --> Return error to LLM
    |
    v
[Transaction begins] -- capture original file state
    |
    v
[Parser] -- kiutils/sexpdata --> IR objects
    |
    v
[Mutator] -- apply operation to IR --> Modified IR
    |
    v
[Serializer] -- IR back to S-expression --> Temporary file
    |
    v
[Validation Pipeline]
    |-- Structural checks
    |-- Round-trip fidelity
    |-- kicad-cli ERC/DRC
    |
    +-- PASS --> [Commit: atomic write to disk]
    |                |
    |                v
    |           [Diff Engine] --> Structural diff
    |                |
    |                v
    |           [Result Renderer] --> Formatted result to LLM
    |
    +-- FAIL --> [Rollback: restore original]
                     |
                     v
                [Result Renderer] --> Error report to LLM
```

### Read/Query Operation Flow

```
LLM emits JSON query
    |
    v
[Schema Validation]
    |
    v
[Parser] -- kiutils --> IR objects
    |
    v
[Query Engine] -- traverse IR --> Extracted data
    |
    v
[Graph Analyzer] (optional) -- networkx --> Connectivity info
    |
    v
[Result Renderer] --> Formatted result to LLM
```

### Project Context Detection Flow

```
/kicad-agent invoked
    |
    v
[Context Detection] -- scan cwd for KiCad files
    |
    +-- Found .kicad_sch --> Schematic context
    +-- Found .kicad_pcb --> PCB context
    +-- Found .kicad_sym --> Symbol library context
    +-- Found .kicad_mod --> Footprint library context
    +-- Found .kicad_pro --> Project root detected
    |
    v
[Context Object] -- file paths, project name, KiCad version
    |
    v
[Skill Handler] -- pass context to all operations
```

### State Management

```
No persistent state between invocations.

Each invocation:
1. Loads files from disk into IR (fresh)
2. Applies mutations in memory
3. Validates
4. Writes to disk (or rolls back)
5. Returns result

Rationale: KiCad files are the source of truth.
No database, no cache, no state file needed.
```

---

## Build Order and Dependency Analysis

### Dependency Graph (What Must Be Built First)

```
schema/          (no dependencies -- pure Pydantic models)
    |
    v
ir/common.py     (depends on: schema types)
    |
    +---> ir/schematic.py  (depends on: ir/common.py)
    +---> ir/pcb.py        (depends on: ir/common.py)
    +---> ir/library.py    (depends on: ir/common.py)
              |
              v
         ir/mapping.py      (depends on: all ir/*, kiutils knowledge)
              |
              v
    +---> parser/*          (depends on: ir/mapping.py, kiutils, sexpdata)
    +---> serializer/*      (depends on: ir/mapping.py, kiutils)
              |
              v
         mutator/*          (depends on: ir/*, schema/*)
              |
              v
         validation/structural.py  (depends on: ir/*)
         validation/roundtrip.py   (depends on: parser/*, serializer/*)
         validation/erc.py         (depends on: kicad-cli binary)
         validation/drc.py         (depends on: kicad-cli binary)
         validation/pipeline.py    (depends on: all validation/*)
              |
              v
         skill/handler.py   (depends on: everything above)
         analysis/*         (depends on: ir/*, networkx) [can be deferred]
```

### Recommended Build Order

| Phase | What to Build | Why This Order |
|-------|---------------|----------------|
| **1a** | `schema/operations.py`, `schema/types.py` | Contract-first. Everything depends on operation definitions. Testable immediately with Pydantic validation. |
| **1b** | `ir/common.py` | Position, UUID, Property -- shared by all IR types. Small, foundational. |
| **1c** | `ir/schematic.py` | First concrete IR. Schematics are the most common edit target. |
| **2a** | `ir/mapping.py` (schematic only) | Bidirectional conversion for schematics. Enables parser and serializer. |
| **2b** | `parser/schematic_parser.py` | Read .kicad_sch files into IR. Can test with real KiCad files immediately. |
| **2c** | `serializer/schematic_ser.py` | Write IR back to .kicad_sch. Enables round-trip testing. |
| **2d** | `validation/roundtrip.py` | Critical early test: parse -> serialize -> parse must be identity. |
| **3a** | `mutator/component_ops.py` | First mutation: add_component. Proves the full pipeline works. |
| **3b** | `validation/structural.py` | UUID uniqueness, ref checks. Needed before complex mutations. |
| **3c** | `validation/erc.py`, `validation/pipeline.py` | kicad-cli integration. Full validation after every edit. |
| **4a** | `mutator/net_ops.py`, `mutator/reference_ops.py` | Net and reference operations build on component foundation. |
| **4b** | `ir/pcb.py`, `parser/pcb_parser.py`, `serializer/pcb_ser.py` | Extend to PCB files. Reuses patterns from schematic. |
| **4c** | `mutator/footprint_ops.py` | Footprint management requires PCB IR. |
| **5a** | `ir/library.py`, `parser/symbol_parser.py`, `parser/footprint_parser.py` | Library file support. |
| **5b** | `analysis/*` | Graph analysis. Optional but valuable. networkx integration. |
| **6a** | `skill/handler.py`, `skill/renderer.py`, `skill/context.py` | GSD Skill integration. Thin layer over the core library. |
| **6b** | `analysis/differ.py` | Structural diffs. Depends on stable parser/serializer. |

### Key Build Order Insight

**Schematics first, PCBs second, libraries third.** Schematics are the most frequently edited file type and have the richest structure (components, nets, hierarchy, buses). Building the full pipeline for schematics first proves the architecture works end-to-end. PCBs reuse most patterns. Libraries are simpler (CRUD on symbol/footprint definitions).

**Round-trip testing must come early.** The `validation/roundtrip.py` check is the single most important test in the system. If parse -> serialize -> parse does not produce identical IR, nothing else matters. Build it in Phase 2d, before any mutations.

---

## Anti-Patterns

### Anti-Pattern 1: String-Based S-Expression Editing

**What people do:** Use regex or string replacement to modify KiCad files directly.

**Why it is wrong:** KiCad S-expressions have deep nesting, ordering constraints, and context-sensitive syntax. A regex that replaces `(at 50 30)` will match inside property text, graphic items, and pad definitions simultaneously. String editing corrupts files.

**Do this instead:** Parse into IR, mutate IR objects, serialize back. Never touch the text representation.

### Anti-Pattern 2: Bypassing Validation for "Simple" Changes

**What people do:** Skip ERC/DRC for "obviously safe" changes like moving a component.

**Why it is wrong:** Moving a component can overlap another component, violate clearance rules, or break a differential pair. No change is safe without validation.

**Do this instead:** Every mutation goes through the full validation pipeline. No exceptions. The pipeline is the safety net.

### Anti-Pattern 3: Mutable IR Objects

**What people do:** Modify IR objects in place (e.g., `component.position.x = 100`).

**Why it is wrong:** Makes rollback impossible. Makes change tracking unreliable. Makes testing harder (shared mutable state).

**Do this instead:** Mutators return new IR objects. Use `dataclasses.replace()` or frozen dataclasses.

```python
# Wrong:
component.position.x = 100  # mutation in place

# Right:
moved = dataclasses.replace(
    component,
    position=PositionIR(x=100, y=component.position.y)
)
```

### Anti-Pattern 4: UUID Generation Without Registry

**What people do:** Generate a random UUID for each new entity without tracking what exists.

**Why it is wrong:** UUID collisions are theoretically rare but practically possible in large projects. Duplicate UUIDs corrupt KiCad files silently.

**Do this instead:** Maintain a UUID registry from the parsed file. Check for collisions before assigning. Use deterministic UUID generation where possible (namespace-based).

### Anti-Pattern 5: Monolithic File Handling

**What people do:** Write one parser that handles all KiCad file types.

**Why it is wrong:** Schematics, PCBs, symbol libraries, and footprint libraries have fundamentally different structures. A monolith becomes unmaintainable.

**Do this instead:** Separate parsers per file type, unified IR interfaces, shared validation pipeline.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| **kicad-cli** | Subprocess invocation (`subprocess.run`) | Must be on PATH. Used for ERC, DRC, netlist export. Parse stdout/stderr for structured results. KiCad 10+ required. |
| **kiutils** | Direct Python import | v1.4.8+ installed. Primary parser for all file types. `from_file()` / `to_file()` / `from_sexpr()` / `to_sexpr()` API. |
| **sexpdata** | Direct Python import | v1.0.0+ installed. Fallback parser for edge cases. `loads()` / `dumps()` API. Returns nested Python lists. |
| **networkx** | Direct Python import | v3.4.2+ installed. Directed graphs for net connectivity and dependency analysis. |
| **difftastic** | Subprocess invocation | Syntax-aware diff tool. Optional but recommended for structural diffs. Falls back to custom differ. |
| **Claude Code Skill API** | YAML manifest + prompt template | Skill definition at `~/.claude/skills/kicad-agent/`. Invoked via `/kicad-agent` command. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Skill Handler <-> Operation Router | Function call (in-process) | Synchronous. Handler validates JSON, router dispatches. |
| Operation Router <-> Mutators | Function call (in-process) | Pure functions. Input IR + operation, output modified IR. |
| Mutators <-> Validation Pipeline | Function call (in-process) | Mutators produce modified IR, pipeline validates serialized output. |
| Validation Pipeline <-> kicad-cli | Subprocess (out-of-process) | Spawn process, capture stdout/stderr, parse results. |
| Parser <-> kiutils | Direct API calls | `kiutils.schematic.Schematic.from_file()` etc. |
| Parser <-> sexpdata | Direct API calls | `sexpdata.loads()` for fallback parsing. |
| IR <-> Graph Analyzer | Function call (in-process) | IR objects fed to networkx graph constructors. |

---

## Scaling Considerations

KiCad files are fundamentally different from web-scale systems. A "large" KiCad project might have 10,000 components. This is not a scaling challenge in the traditional sense.

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Small (< 100 components) | In-memory IR, full file parse/serialize each time. No optimization needed. |
| Medium (100-1,000 components) | Same architecture. kicad-cli DRC may take 5-15 seconds. Acceptable. |
| Large (1,000-10,000 components) | Consider incremental parsing (only re-parse modified sections). Cache IR between operations in the same session. DRC may take 30-60 seconds. |
| Very Large (10,000+ components) | Rare. Consider lazy loading of hierarchical sheets. Batch validation (skip intermediate checks, validate only at session end). |

### Scaling Priorities

1. **First bottleneck: kicad-cli latency.** DRC on a dense board can take 30+ seconds. Mitigation: run validation only at commit time, not after every intermediate mutation. Batch mutations in a single transaction.

2. **Second bottleneck: memory for full-file IR.** A 10,000-component schematic parsed into IR dataclasses might use 50-100MB. Acceptable for modern machines. Only optimize if this becomes a real problem.

3. **Third bottleneck: round-trip check time.** Parse -> serialize -> parse comparison is O(file size). For very large files, consider hashing the serialized output and comparing hashes instead of full IR comparison.

---

## Sources

- kiutils documentation (via Context7): https://github.com/mvnmgrx/kiutils -- `from_file()`, `to_file()`, `from_sexpr()`, `to_sexpr()` patterns, dataclass-based API for all KiCad file types
- KiCad 10 file format specification: https://dev-docs.kicad.org/en/file-formats/sexpr-schematic/ -- S-expression structure for schematics
- sexpdata documentation: https://github.com/tkf/sexpdata -- Generic S-expression parser for Python
- PROJECT.md at `~/apps/kicad-agent/.planning/PROJECT.md` -- Project requirements and constraints
- Verified local installations: kiutils 1.4.8, sexpdata 1.0.0, networkx 3.4.2

---
*Architecture research for: KiCad automation agent*
*Researched: 2026-05-17*
