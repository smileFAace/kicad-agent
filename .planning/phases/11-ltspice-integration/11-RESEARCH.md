# Phase 11: LTspice Integration - Research

**Researched:** 2026-05-23
**Domain:** LTspice file format parsing, SpiceLib Python library, net connectivity derivation
**Confidence:** HIGH

## Summary

Phase 11 adds LTspice integration to kicad-agent, enabling parsing of `.asc` schematic files, extraction of components/nets/simulation commands, derivation of net connectivity graphs from wire geometry, and reading of `.raw` simulation result files. The primary library is SpiceLib v1.5.1 (already installed), which provides `AscEditor` for `.asc` parsing and `RawRead` for `.raw` file reading. A critical discovery is that `AscEditor` requires `.asy` symbol definition files to be available alongside `.asc` files -- without them, parsing fails with `FileNotFoundError`. This means the phase must either bundle minimal `.asy` stub files for common components or implement a custom `.asc` text parser that does not depend on `.asy` files for basic extraction.

Net connectivity is not directly provided by SpiceLib's `AscEditor` -- it must be derived geometrically by tracing wire segments, matching FLAG positions to net names, and computing component pin positions from symbol pin offsets plus component position/rotation. This is a meaningful algorithm that requires a union-find or graph-based approach similar to the existing `NetGraph` in `analysis/connectivity.py`.

The `.raw` file reader (`RawRead`) is straightforward and provides direct access to voltage/current traces by node name, with numpy array output and pandas DataFrame export support.

**Primary recommendation:** Use SpiceLib v1.5.1 as the parsing engine, bundle a set of minimal `.asy` stub files for the ~15 most common LTspice components (res, cap, ind, voltage, current, diode, npn, pnp, etc.), and build a custom `LTspiceNetGraph` that derives connectivity from wire geometry using networkx (consistent with existing Phase 5 patterns).

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LTSPICE-01 | A .asc file parses into structured component/net/simulation data via SpiceLib | SpiceLib AscEditor confirmed working; .asy stub files needed for common components |
| LTSPICE-02 | Components with values, positions, orientations, and node connections are extractable | AscEditor.get_component(), get_component_position(), get_component_value() confirmed; node connections require custom net derivation |
| LTSPICE-03 | Net connectivity graph is derivable from WIRE and FLAG statements | Must be custom-built; union-find on wire segments + FLAG name assignment + pin position matching |
| LTSPICE-04 | Simulation commands (.tran, .ac, .dc, .noise) are extractable and parseable | AscEditor.directives list contains TEXT entries with type=DIRECTIVE; regex parsing for each command type |
| LTSPICE-05 | .raw simulation results are readable (voltage/current traces by node) | SpiceLib RawRead.get_trace(), get_wave(), get_trace_names() confirmed working |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| .asc file parsing | API / Backend | -- | Text file parsing, no UI component |
| Component extraction | API / Backend | -- | Data extraction from parsed structure |
| Net connectivity derivation | API / Backend | -- | Graph algorithm on wire geometry |
| Simulation command parsing | API / Backend | -- | Text/regex parsing of directives |
| .raw result reading | API / Backend | -- | Binary file parsing |
| KiCad<->LTspice bridge | API / Backend | -- | Data model mapping between formats |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| spicelib | 1.5.1 | .asc parsing (AscEditor), .raw reading (RawRead) | Most comprehensive LTspice Python library; already installed [VERIFIED: pip show spicelib] |
| networkx | 3.4.2 | Net connectivity graph for LTspice nets | Already used in Phase 5 NetGraph; consistent pattern [VERIFIED: pip show networkx] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | 1.26.4 | Array handling for .raw trace data | Returned by RawRead.get_wave(); already a spicelib dependency [VERIFIED: pip show numpy] |
| shapely | 2.1.1 | Spatial queries on LTspice coordinates | If spatial analysis of LTspice schematics is needed; already used in Phase 8 [VERIFIED: pip show shapely] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SpiceLib AscEditor | Custom .asc text parser | Custom parser avoids .asy dependency but reimplements SpiceLib's parsing; use SpiceLib with bundled .asy stubs instead |
| SpiceLib RawRead | ltspice package (v1.0.6) | ltspice package is less comprehensive; RawRead is superior and part of SpiceLib |
| SpiceLib | PyLTSpice v5.5.1 | PyLTSpice wraps SpiceLib; adds LTspice-specific simulation automation; we only need parsing, so SpiceLib directly is cleaner |

**Installation:**
```bash
# Already installed -- spicelib 1.5.1 (includes numpy, scipy, matplotlib as deps)
pip install spicelib>=1.5.1
```

**Version verification:**
```
spicelib 1.5.1 (LATEST, installed 2026-05-23)
PyLTSpice 5.5.1 (installed, wraps spicelib -- not directly needed)
```

## Architecture Patterns

### System Architecture Diagram

```
.asc file --> AscEditor (spicelib) ---+---> LTspiceComponent[] (frozen dataclasses)
                                       |---> LTspiceWire[] (wire segments)
                                       |---> LTspiceDirective[] (sim commands)
                                       +---> LTspiceFlag[] (net labels)
                                                    |
                                      +-------------+
                                      |
                              LTspiceNetGraph (networkx)
                              (union-find on wire geometry +
                               FLAG name assignment +
                               pin position matching)
                                      |
                                      v
                              LTspiceNet[] (named nets with connected pins)

.raw file --> RawRead (spicelib) ----> LTspiceTrace[] (voltage/current by node)

KiCad .kicad_sch <---> LTspiceBridge ----> .asc file
     |                                        ^
     v                                        |
  PcbIR / SchIR                     LTspiceSchematic data model
```

### Recommended Project Structure
```
src/kicad_agent/
├── ltspice/                    # New module for LTspice integration
│   ├── __init__.py             # Barrel exports
│   ├── asc_parser.py           # .asc file parsing via SpiceLib AscEditor
│   ├── raw_reader.py           # .raw file reading via SpiceLib RawRead
│   ├── types.py                # Frozen dataclasses: LTspiceComponent, LTspiceWire, etc.
│   ├── net_graph.py            # Net connectivity derivation from wire geometry
│   ├── sim_commands.py         # Simulation command parsing (.tran, .ac, .dc, .noise)
│   └── bridge.py               # KiCad<->LTspice data model mapping
├── parser/                     # Existing KiCad parsers (unchanged)
├── analysis/                   # Existing NetGraph (pattern reference)
tests/
├── fixtures/
│   └── ltspice/                # LTspice test fixtures
│       ├── basic_rc.asc        # Simple RC circuit
│       ├── basic_rc.asy/       # Bundled .asy stubs
│       └── basic_rc.raw        # Simulation results (if available)
├── test_ltspice_parser.py      # .asc parsing tests
├── test_ltspice_raw.py         # .raw reading tests
├── test_ltspice_net_graph.py   # Net connectivity tests
└── test_ltspice_bridge.py      # KiCad<->LTspice bridge tests
```

### Pattern 1: SpiceLib AscEditor with Bundled .asy Stubs
**What:** Use SpiceLib's AscEditor for .asc parsing, but provide a set of minimal `.asy` stub files for common LTspice components so parsing succeeds without requiring a full LTspice installation.
**When to use:** All .asc file parsing.
**Example:**
```python
# Source: [VERIFIED: spicelib 1.5.1 AscEditor tested 2026-05-23]
from pathlib import Path
from spicelib import AscEditor

# Set custom library paths to include bundled .asy stubs
LTSPICE_STUBS_DIR = Path(__file__).parent / "asy_stubs"
AscEditor.set_custom_library_paths(str(LTSPICE_STUBS_DIR))

editor = AscEditor("circuit.asc")
components = editor.get_components()  # ['R1', 'C1', 'V1']
for ref in components:
    comp = editor.get_component(ref)
    pos, rot = editor.get_component_position(ref)
    value = editor.get_component_value(ref)
```

### Pattern 2: Frozen Dataclass Result Types (Consistent with Existing Patterns)
**What:** Use frozen dataclasses for all parsed LTspice data, matching `ParseResult` and `SpatialPoint` patterns.
**When to use:** All result types returned from LTspice parsing.
**Example:**
```python
# Source: [Pattern from src/kicad_agent/parser/types.py and spatial/primitives.py]
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class LTspiceComponent:
    """A parsed component from an LTspice .asc file."""
    reference: str        # e.g. "R1"
    symbol: str           # e.g. "res"
    value: str            # e.g. "1k"
    position_x: int       # LTspice internal units
    position_y: int       # LTspice internal units
    rotation: str         # e.g. "R0", "R90", "M0"
    prefix: str           # e.g. "R", "C", "L", "V"
    parameters: dict[str, str]  # Additional parameters
```

### Pattern 3: NetworkX Net Connectivity (Consistent with Phase 5)
**What:** Build a networkx graph from wire geometry to derive net connectivity, using the same pattern as `NetGraph.from_pcb_ir()`.
**When to use:** Deriving net connectivity from LTspice wire segments and flags.
**Example:**
```python
# Source: [Pattern from src/kicad_agent/analysis/connectivity.py]
import networkx as nx

class LTspiceNetGraph:
    """Connectivity graph for LTspice schematic built from wire geometry.

    Nodes are (x, y) coordinate points. Edges connect wire endpoints.
    FLAG statements assign net names to coordinate points.
    """
    graph: nx.Graph
    _net_names: dict[tuple[int, int], str]  # position -> net name

    @classmethod
    def from_asc_editor(cls, editor: AscEditor) -> LTspiceNetGraph:
        # 1. Build graph from WIRE segments (union overlapping/connected)
        # 2. Map FLAG positions to net names
        # 3. Compute component pin positions (pos + rotated pin offset)
        # 4. Match pins to nets
        ...
```

### Anti-Patterns to Avoid
- **Don't call get_component_nodes() expecting net names:** AscEditor's `get_component_nodes()` returns an empty list for `.asc` files because node assignment happens during SPICE netlist compilation, not during .asc parsing. Net connectivity must be derived geometrically. [VERIFIED: tested 2026-05-23]
- **Don't assume .asy files are always available:** AscEditor will raise `FileNotFoundError` if the `.asy` symbol file cannot be found in the library search paths. Always configure `custom_lib_paths` or bundle stubs. [VERIFIED: tested 2026-05-23]
- **Don't re-implement .asc parsing from scratch when SpiceLib works:** Use SpiceLib for the heavy lifting (component extraction, wire parsing, flag parsing). Only custom-build the net connectivity derivation on top.
- **Don't treat LTspice coordinates as physical units:** LTspice uses internal units (1 unit ~ 1/256 inch), not millimeters. Coordinate conversion is needed for KiCad bridge mapping.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| .asc file parsing | Custom line-by-line parser | SpiceLib AscEditor | Handles encoding detection, WINDOW/SYMATTR/TEXT parsing, rotation dictionaries, symbol caching |
| .raw file reading | Binary format parser | SpiceLib RawRead | Handles LTspice/QSPICE/NGSPICE/XYCE dialects, binary and ASCII formats, step data |
| .asy symbol reading | Custom parser | SpiceLib AsyReader | Handles PIN, PINATTR, LINE, RECTANGLE, CIRCLE, ARC, SYMATTR parsing |
| Net connectivity graph | Custom graph structure | networkx Graph | Already project standard (Phase 5); provides path finding, connectivity components, stats |
| Component position/rotation | Custom rotation math | SpiceLib's ASC_ROTATION_DICT + Point transformations | Handles R0/R90/R180/R270/M0/M90/M180/M270 correctly |

**Key insight:** SpiceLib handles the .asc/.asy/.raw file format parsing. The custom work this phase needs is (a) net connectivity derivation from wire geometry, (b) simulation command parsing via regex, and (c) KiCad<->LTspice data model mapping.

## Common Pitfalls

### Pitfall 1: Missing .asy Symbol Files
**What goes wrong:** AscEditor raises `FileNotFoundError: File res.asy not found` when parsing .asc files because the LTspice symbol definitions are not available.
**Why it happens:** AscEditor calls `_get_symbol()` during `reset_netlist()` when processing `SYMATTR InstName` lines. It searches the .asc file's directory, current directory, simulator library paths, and custom library paths for the .asy file.
**How to avoid:** Bundle minimal .asy stub files for common LTspice components (res, cap, ind, voltage, current, diode, npn, pnp, etc.) in a dedicated `asy_stubs/` directory. Configure via `AscEditor.set_custom_library_paths()`. For uncommon components, provide clear error messages suggesting the user install LTspice or provide .asy files.
**Warning signs:** `FileNotFoundError` during AscEditor construction; tests failing in CI where LTspice is not installed.

### Pitfall 2: Empty get_component_nodes()
**What goes wrong:** Calling `editor.get_component_nodes("R1")` returns `[]` instead of expected node names like `["VCC", "0"]`.
**Why it happens:** SpiceLib's node assignment happens during SPICE netlist compilation, not during .asc parsing. The .asc file stores wires and flags geometrically; nodes are not explicitly stored per component.
**How to avoid:** Build a custom `LTspiceNetGraph` that derives connectivity from wire segments and FLAG positions. Compute component pin positions from symbol pin offsets + component position + rotation, then match against the wire graph.
**Warning signs:** Node lists always empty; net connectivity tests failing.

### Pitfall 3: LTspice Coordinate System vs KiCad
**What goes wrong:** Component positions appear wrong when mapping to KiCad coordinates.
**Why it happens:** LTspice uses internal units (approximately 1/256 inch per unit) while KiCad uses millimeters. The Y-axis direction also differs between the two systems.
**How to avoid:** Document the coordinate conversion factor. For display/analysis purposes, keep LTspice coordinates in their native format. Only convert when bridging to KiCad. The conversion factor is approximately 1 LTspice unit = 0.0992mm (1/256 inch).
**Warning signs:** Component positions appear misaligned; bridge tests failing with coordinate mismatches.

### Pitfall 4: Simulation Command Parsing Edge Cases
**What goes wrong:** Simulation commands with complex syntax (nested parameters, stepped simulations) fail to parse.
**Why it happens:** LTspice TEXT directives can contain multi-line SPICE commands, parameter sweeps, and complex expressions. Simple regex may not handle all cases.
**How to avoid:** Start with the four required command types (.tran, .ac, .dc, .noise) using focused regex patterns. For edge cases, store the raw command text and provide a "parse attempted, raw text available" fallback.
**Warning signs:** Parse errors on .asc files with parameterized simulations; missing commands in extraction results.

### Pitfall 5: Class-Level set_custom_library_paths
**What goes wrong:** Calling `AscEditor.set_custom_library_paths()` affects ALL instances of AscEditor, not just the current one.
**Why it happens:** `set_custom_library_paths` is a classmethod that modifies `cls.custom_lib_paths`, which is shared across all instances.
**How to avoid:** Call it once during module initialization or in the parser's `__init__`. If multiple configurations are needed, use instance-level `custom_lib_paths` manipulation instead.
**Warning signs:** Tests interfering with each other; parsing succeeds in one test but fails in another due to path state leakage.

## Code Examples

### Basic .asc Parsing with SpiceLib AscEditor
```python
# Source: [VERIFIED: spicelib 1.5.1, tested 2026-05-23]
from pathlib import Path
from spicelib import AscEditor

# Configure library paths for .asy symbol lookup
stubs_dir = Path(__file__).parent / "asy_stubs"
AscEditor.set_custom_library_paths(str(stubs_dir))

editor = AscEditor("circuit.asc")

# Extract components
for ref in editor.get_components():
    comp = editor.get_component(ref)
    pos, rot = editor.get_component_position(ref)
    value = editor.get_component_value(ref)
    info = editor.get_component_info(ref)
    # info is a dict: {'Value': '1k', 'InstName': 'R1'}

# Extract wires (wire segments)
for wire in editor.wires:
    x1, y1 = wire.V1.X, wire.V1.Y
    x2, y2 = wire.V2.X, wire.V2.Y

# Extract net labels (flags)
for label in editor.labels:
    name = label.text        # e.g. "VCC", "0" (GND)
    x, y = label.coord.X, label.coord.Y

# Extract simulation commands (directives)
for directive in editor.directives:
    command = directive.text  # e.g. ".tran 0 1ms 0 1u"
    # directive.type: TextTypeEnum.DIRECTIVE (3) or COMMENT
```

### Reading .raw Simulation Results
```python
# Source: [VERIFIED: spicelib 1.5.1 RawRead API]
from spicelib import RawRead

raw = RawRead("simulation.raw")

# Get all available trace names
trace_names = raw.get_trace_names()  # ['time', 'V(vcc)', 'I(R1)', ...]

# Get a specific trace
trace = raw.get_trace("V(vcc)")
wave = raw.get_wave("V(vcc)")  # numpy.ndarray of float values

# Get time axis (for transient analysis)
time = raw.get_time_axis()  # numpy.ndarray

# Export to DataFrame
df = raw.to_dataframe()  # pandas DataFrame with all traces

# Get step information (for stepped simulations)
steps = raw.get_steps()
```

### Deriving Net Connectivity from Wire Geometry
```python
# Source: [ASSUMED - algorithm design based on LTspice format understanding]
import networkx as nx
from collections import defaultdict

def build_wire_graph(wires: list, flags: list) -> nx.Graph:
    """Build a connectivity graph from LTspice wires and flags.

    Wires are line segments. Any point where two wire endpoints
    touch (same coordinates) forms a connection. Flags assign
    net names to points on the graph.
    """
    graph = nx.Graph()

    for wire in wires:
        p1 = (wire.V1.X, wire.V1.Y)
        p2 = (wire.V2.X, wire.V2.Y)
        graph.add_edge(p1, p2)

    # Map flag positions to net names
    flag_map = {}
    for flag in flags:
        pos = (flag.coord.X, flag.coord.Y)
        flag_map[pos] = flag.text

    return graph, flag_map
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| PyLTSpice standalone | PyLTSpice wraps SpiceLib | PyLTSpice 5.x | Use SpiceLib directly for parsing; PyLTSpice adds simulation automation we don't need |
| Manual .asc parsing | SpiceLib AscEditor | SpiceLib 1.0+ | Robust parsing with encoding detection, symbol caching, rotation handling |
| Binary .raw format guessing | SpiceLib RawRead with dialect detection | SpiceLib 1.3+ | Auto-detects LTspice/QSPICE/NGSPICE/XYCE formats |

**Deprecated/outdated:**
- `ltspice` package v1.0.6: Basic, less comprehensive than SpiceLib. Not maintained as actively.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | LTspice internal units are approximately 1/256 inch per unit | Pitfall 3 | Bridge coordinate conversion would be wrong |
| A2 | ~15 .asy stub files cover the most common LTspice components used in .asc files | Pitfall 1 | Some .asc files may fail to parse if they use components without bundled stubs |
| A3 | Simulation commands (.tran, .ac, .dc, .noise) appear only in TEXT directives with type=DIRECTIVE (exclamation mark prefix in .asc) | Code Examples | Complex multi-line commands or non-standard directives might be missed |
| A4 | Net connectivity can be derived by matching wire endpoints at exact integer coordinates | Pattern 3 | If LTspice uses non-integer coordinates or off-grid wiring, matching would fail |
| A5 | SpiceLib's classmethod set_custom_library_paths is safe for our use case (single-threaded parsing) | Pitfall 5 | In concurrent environments, path state could leak between instances |

## Open Questions

1. **Should we bundle .asy stubs or implement a fallback custom parser?**
   - What we know: SpiceLib AscEditor requires .asy files; ~15 common components cover most cases.
   - What's unclear: Whether users will have .asc files referencing uncommon/custom symbols.
   - Recommendation: Bundle .asy stubs for common components AND provide a clear error message with instructions for custom components. The stubs approach is simpler and more maintainable.

2. **What level of KiCad<->LTspice bridge is needed?**
   - What we know: The roadmap says "bidirectional KiCad-LTspice bridge for simulation-driven design workflows."
   - What's unclear: Whether this means full round-trip editing or just data extraction + mapping.
   - Recommendation: Start with extraction-only (LTspice -> structured data). The bridge should map LTspice components to KiCad-compatible data structures, not necessarily write KiCad files directly.

3. **Should LTspiceNetGraph use the same node representation as NetGraph?**
   - What we know: Phase 5's NetGraph uses `(footprint_reference, pad_number)` tuples as nodes.
   - What's unclear: Whether LTspice nets should use `(reference, pin_name)` or `(x, y)` coordinates as nodes.
   - Recommendation: Use `(reference, pin_name)` for component-pin nodes (matching KiCad pattern) and `(x, y)` for wire junction nodes internally. Expose net membership via a similar API to NetGraph.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11 | Runtime | Available | 3.11.11 | -- |
| spicelib | .asc/.raw parsing | Available | 1.5.1 | -- |
| networkx | Net connectivity graph | Available | 3.4.2 | -- |
| numpy | .raw trace arrays | Available | 1.26.4 | -- |
| shapely | Spatial queries | Available | 2.1.1 | Not required, optional |
| pytest | Test framework | Available | 8.4.2 | -- |
| ruff | Linting | Available | 0.13.0 | -- |
| LTspice application | Running simulations | NOT installed | -- | Not required for parsing; only needed to generate .raw files |
| .asy symbol files | AscEditor parsing | NOT available system-wide | -- | Bundled stubs in asy_stubs/ |

**Missing dependencies with no fallback:**
- None for parsing functionality. All required libraries are installed.

**Missing dependencies with fallback:**
- LTspice application: Not installed, not needed for parsing. Only needed if user wants to run simulations (out of scope for this phase). Test .raw files will be created programmatically or bundled as fixtures.
- System .asy files: Not available. Will bundle minimal .asy stub files in `src/kicad_agent/ltspice/asy_stubs/`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 |
| Config file | pyproject.toml [tool.pytest.ini_options] |
| Quick run command | `pytest tests/test_ltspice_parser.py -x -q` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LTSPICE-01 | .asc file parses into structured data | unit | `pytest tests/test_ltspice_parser.py::test_parse_basic_asc -x` | Wave 0 |
| LTSPICE-01 | .asc with multiple components parses correctly | unit | `pytest tests/test_ltspice_parser.py::test_parse_multi_component -x` | Wave 0 |
| LTSPICE-02 | Component values/positions/orientations extractable | unit | `pytest tests/test_ltspice_parser.py::test_component_extraction -x` | Wave 0 |
| LTSPICE-02 | Component node connections derivable | unit | `pytest tests/test_ltspice_net_graph.py::test_component_nodes -x` | Wave 0 |
| LTSPICE-03 | Net connectivity graph from wires and flags | unit | `pytest tests/test_ltspice_net_graph.py::test_wire_connectivity -x` | Wave 0 |
| LTSPICE-03 | Named nets from FLAG statements | unit | `pytest tests/test_ltspice_net_graph.py::test_flag_net_names -x` | Wave 0 |
| LTSPICE-04 | .tran command parsing | unit | `pytest tests/test_ltspice_parser.py::test_tran_command -x` | Wave 0 |
| LTSPICE-04 | .ac/.dc/.noise command parsing | unit | `pytest tests/test_ltspice_parser.py::test_ac_dc_noise_commands -x` | Wave 0 |
| LTSPICE-05 | .raw file trace reading | unit | `pytest tests/test_ltspice_raw.py::test_read_raw_traces -x` | Wave 0 |
| LTSPICE-05 | .raw voltage/current by node | unit | `pytest tests/test_ltspice_raw.py::test_node_traces -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_ltspice_parser.py tests/test_ltspice_raw.py tests/test_ltspice_net_graph.py -x -q`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/fixtures/ltspice/` -- LTspice test fixture directory with .asc and .asy files
- [ ] `tests/test_ltspice_parser.py` -- covers LTSPICE-01, LTSPICE-02, LTSPICE-04
- [ ] `tests/test_ltspice_raw.py` -- covers LTSPICE-05
- [ ] `tests/test_ltspice_net_graph.py` -- covers LTSPICE-03
- [ ] `tests/test_ltspice_bridge.py` -- covers KiCad<->LTspice mapping
- [ ] `src/kicad_agent/ltspice/asy_stubs/` -- bundled .asy symbol stub files

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No user authentication in parsing library |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No access control |
| V5 Input Validation | yes | Path traversal protection on .asc/.raw file paths (pattern from lib_table.py) |
| V6 Cryptography | no | No cryptography needed |

### Known Threat Patterns for LTspice Parsing

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal in file paths | Tampering | resolve() + existence check (pattern from existing parsers) |
| Malformed .asc content | Denial of Service | Size limits + try/except around SpiceLib calls |
| Malicious .asy stub files | Tampering | Bundle only verified .asy stubs; don't execute user-provided .asy |

## Sources

### Primary (HIGH confidence)
- [spicelib 1.5.1 installed locally] - AscEditor, RawRead, AsyReader APIs tested directly
- [spicelib GitHub: github.com/nunobrum/spicelib] - Source code inspection for _get_symbol, reset_netlist
- [VERIFIED: pip show spicelib] - Version 1.5.1 confirmed latest and installed

### Secondary (MEDIUM confidence)
- [VERIFIED: Python testing 2026-05-23] - All code examples tested with actual SpiceLib API calls
- [VERIFIED: pip show PyLTSpice] - Version 5.5.1 installed, wraps spicelib

### Tertiary (LOW confidence)
- [ASSUMED: LTspice coordinate units] - 1 unit = 1/256 inch based on training knowledge, not verified from LTspice source

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - SpiceLib tested directly, already installed, confirmed latest version
- Architecture: HIGH - Follows existing project patterns (frozen dataclasses, networkx graphs, barrel exports)
- Pitfalls: HIGH - All pitfalls discovered through direct testing, not assumed
- Net connectivity derivation: MEDIUM - Algorithm designed based on format understanding, not yet implemented
- Bridge mapping: LOW - KiCad<->LTspice mapping details need more thought during planning

**Research date:** 2026-05-23
**Valid until:** 2026-06-23 (stable domain, SpiceLib releases are infrequent)
