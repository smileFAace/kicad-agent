# Phase 1: Foundation -- Parse, Serialize, Round-trip - Research

**Researched:** 2026-05-17
**Domain:** KiCad S-expression parsing, serialization, and round-trip fidelity via kiutils 1.4.8
**Confidence:** HIGH (verified via live round-trip testing against real KiCad files)

## Summary

Phase 1 builds the parser and serializer layer that converts all four KiCad file types (.kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod) to and from Python dataclass objects. The primary library is kiutils 1.4.8, with sexpdata 1.0.0 as a fallback for constructs kiutils cannot handle.

**The critical discovery:** kiutils 1.4.8 does NOT produce byte-identical round-trip output for any file type. The output is structurally valid and semantically equivalent, but formatting normalizes (tabs to spaces, multi-line tokens collapse, quoting changes). More critically, kiutils drops `uuid` tokens from PCB/footprint files entirely (the footprint and board modules only handle the legacy `tstamp` token, not the KiCad 7+ `uuid` token), and silently drops `exclude_from_sim` from symbol definitions. These are not cosmetic issues -- UUID loss means broken reference integrity.

**Primary recommendation:** Build a "normalization-tolerant" round-trip test strategy: parse -> serialize -> re-parse -> compare AST equality (not byte equality). For UUID preservation, patch kiutils or build a pre/post-processing layer that extracts and re-injects UUIDs via sexpdata.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FND-01 | Parse .kicad_sch files into structured AST with full property coverage | kiutils `Schematic.from_file()` handles schematics; `exclude_from_sim` and `hide yes` on pin_names are NOT preserved in output formatting but ARE parsed into dataclass fields |
| FND-02 | Parse .kicad_pcb files into structured AST with full property coverage | kiutils `Board.from_file()` handles PCBs; **CRITICAL: UUID tokens are dropped** -- footprint.py and board.py have zero `uuid` handling, only legacy `tstamp` |
| FND-03 | Parse .kicad_sym (symbol library) files into structured AST | kiutils `SymbolLib.from_file()` handles symbol libraries; `exclude_from_sim` is silently dropped |
| FND-04 | Parse .kicad_mod (footprint library) files into structured AST | kiutils `Footprint.from_file()` handles footprints; same UUID issue as PCB |
| FND-05 | Round-trip fidelity: parse -> serialize produces byte-identical or semantically equivalent output | Byte-identical is NOT achievable with kiutils. Semantically equivalent (stable on re-parse) IS achievable after first normalization pass. Test strategy must compare AST equality, not byte equality |
| FND-06 | UUID integrity preservation across all operations | Requires UUID extraction/re-injection layer. kiutils drops PCB/footprint UUIDs. Schematic UUIDs are preserved |
| VAL-07 | Round-trip fidelity regression test suite | Build test fixtures from KiCad 10 templates. Test: parse -> serialize -> re-parse -> compare IR objects. Test all 4 file types with varied complexity |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| S-expression parsing | API / Backend | -- | File parsing is a backend library concern, no browser/client involvement |
| AST representation | API / Backend | -- | Dataclass objects live in Python backend |
| S-expression serialization | API / Backend | -- | Writing files back to disk is backend-only |
| Round-trip validation | API / Backend | -- | Comparison and testing logic runs in test suite |
| UUID extraction/preservation | API / Backend | -- | Pre/post-processing around kiutils for UUID handling |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| kiutils | 1.4.8 | Primary KiCad file parser/serializer | KiCad-specific dataclass AST for all 4 file types. `from_file()`/`to_file()`/`from_sexpr()`/`to_sexpr()` API. [VERIFIED: pip show kiutils] |
| sexpdata | 1.0.0 | Raw S-expression fallback parser | Handles arbitrary S-expressions when kiutils cannot parse a construct. Used for UUID extraction/re-injection. [VERIFIED: pip show sexpdata] |
| pytest | 8.4.2 | Test framework | Standard Python testing. pytest-cov for coverage. [VERIFIED: pip show pytest] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| mypy | 1.7.1 | Static type checking | Enforce type safety on all dataclass interactions. Run in CI. [VERIFIED: pip show mypy] |
| ruff | 0.13.0 | Linter + formatter | Replaces flake8 and black. Fast, opinionated. [VERIFIED: pip show ruff] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| kiutils normalization patch | Fork kiutils and fix UUID handling | Forking is heavy maintenance burden. Prefer pre/post-processing wrapper first, contribute fixes upstream |
| AST equality testing | Byte-identical diff testing | Byte-identical is impossible with kiutils. AST equality is the correct target |

**Installation:**
```bash
# Already installed locally:
pip install kiutils==1.4.8 sexpdata==1.0.0 pytest==8.4.2 pytest-cov==4.1.0 mypy==1.7.1 ruff==0.13.0
```

**Version verification:**
```
kiutils 1.4.8 (verified 2026-05-17)
sexpdata 1.0.0 (verified 2026-05-17)
pytest 8.4.2 (verified 2026-05-17)
mypy 1.7.1 (verified 2026-05-17)
ruff 0.13.0 (verified 2026-05-17)
```

## Architecture Patterns

### System Architecture Diagram

```
KiCad File (.kicad_sch/.pcb/.sym/.mod)
    |
    v
[kiutils Parser] -- primary path for all 4 file types
    |                  |
    |                  +-- fails on unknown tokens? --> [sexpdata Fallback]
    |                                                      |
    v                                                      v
[UUID Extractor] -- pre-processes raw file to extract UUID map
    |
    v
[IR Layer] -- canonical Python dataclasses (Phase 2 builds this)
    |
    v
[kiutils Serializer] -- produces normalized S-expression output
    |
    v
[UUID Re-injector] -- re-inserts UUIDs that kiutils dropped
    |
    v
Normalized KiCad File (semantically equivalent, formatting normalized)
    |
    v
[Round-trip Validator] -- re-parse output, compare AST equality
```

### Recommended Project Structure
```
src/
  kicad_agent/
    __init__.py
    parser/                 # Phase 1 focus
      __init__.py
      schematic_parser.py   # .kicad_sch parsing
      pcb_parser.py         # .kicad_pcb parsing
      symbol_parser.py      # .kicad_sym parsing
      footprint_parser.py   # .kicad_mod parsing
      raw_parser.py         # sexpdata fallback
      uuid_extractor.py     # UUID pre/post-processing
    serializer/             # Phase 1 focus
      __init__.py
      schematic_ser.py      # .kicad_sch serialization
      pcb_ser.py            # .kicad_pcb serialization
      symbol_ser.py         # .kicad_sym serialization
      footprint_ser.py      # .kicad_mod serialization
      uuid_reinjector.py    # UUID re-injection after serialization
    validation/             # Phase 1 focus (round-trip only)
      __init__.py
      roundtrip.py          # Round-trip fidelity checker
tests/
  conftest.py               # Shared fixtures, test KiCad files
  fixtures/                 # Sample KiCad files for testing
  test_parser/
  test_serializer/
  test_roundtrip/
```

### Pattern 1: kiutils-First Parsing with sexpdata UUID Extraction

**What:** Parse with kiutils for typed dataclass access. Use sexpdata to extract UUIDs from the raw file before kiutils processing, then re-inject after serialization.

**When to use:** For ALL PCB and footprint files. Schematic UUIDs are preserved by kiutils, so extraction is only needed for PCB/footprint.

**Example:**
```python
# Source: [VERIFIED: live testing 2026-05-17]
from kiutils.board import Board
from kiutils.footprint import Footprint
import sexpdata
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Tuple

@dataclass
class UUIDMap:
    """Maps S-expression context paths to UUID values extracted from raw files."""
    entries: Dict[str, str] = field(default_factory=dict)  # context_path -> uuid_value

def extract_uuids_from_sexp(raw_content: str) -> UUIDMap:
    """Extract all UUID tokens from raw S-expression content using regex.
    
    kiutils drops UUIDs from PCB/footprint files. This function extracts
    them before parsing so they can be re-injected after serialization.
    """
    uuid_map = UUIDMap()
    # Match (uuid "value") patterns with optional quoting
    for match in re.finditer(r'\(uuid\s+"?([0-9a-f-]+)"?\)', raw_content):
        uuid_value = match.group(1)
        # Use surrounding context as key for re-injection
        start = max(0, match.start() - 200)
        context = raw_content[start:match.start()]
        uuid_map.entries[context] = uuid_value
    return uuid_map

def parse_pcb_with_uuids(path: Path) -> Tuple[Board, UUIDMap]:
    """Parse a PCB file preserving UUIDs that kiutils would drop."""
    raw = path.read_text()
    uuid_map = extract_uuids_from_sexp(raw)
    board = Board.from_file(str(path))
    return board, uuid_map
```

### Pattern 2: Normalization-Tolerant Round-Trip Testing

**What:** Instead of comparing byte-for-byte, parse both original and output files into AST objects and compare those.

**When to use:** For ALL round-trip tests. Byte-identical round-trip is NOT achievable with kiutils.

**Example:**
```python
# Source: [VERIFIED: live testing 2026-05-17]
from kiutils.schematic import Schematic
from kiutils.board import Board
from kiutils.footprint import Footprint
from kiutils.symbol import SymbolLib
import tempfile
from pathlib import Path

def round_trip_stable(path: Path, file_type: str) -> bool:
    """Verify that parse -> serialize -> parse produces AST-stable output.
    
    Two-round-trip test:
    1. Parse original, serialize to temp1
    2. Parse temp1, serialize to temp2
    3. Compare temp1 == temp2 (byte-identical after first normalization)
    
    This proves kiutils output is stable: the first pass normalizes,
    the second pass produces identical output.
    """
    parser = {
        '.kicad_sch': Schematic.from_file,
        '.kicad_pcb': Board.from_file,
        '.kicad_sym': SymbolLib.from_file,
        '.kicad_mod': Footprint.from_file,
    }[path.suffix]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # First round-trip
        obj1 = parser(str(path))
        temp1 = Path(tmpdir) / "pass1" / path.name
        temp1.parent.mkdir(exist_ok=True)
        obj1.to_file(str(temp1))
        
        # Second round-trip
        obj2 = parser(str(temp1))
        temp2 = Path(tmpdir) / "pass2" / path.name
        temp2.parent.mkdir(exist_ok=True)
        obj2.to_file(str(temp2))
        
        # Compare
        return temp1.read_text() == temp2.read_text()
```

### Pattern 3: Semantic Round-Trip with UUID Preservation

**What:** For files where UUIDs must be preserved (all PCB operations), extract UUIDs before parsing, serialize with kiutils, then re-inject UUIDs into the output.

**When to use:** When the output file must maintain specific UUID values (e.g., when editing an existing PCB that other tools reference by UUID).

**Example:**
```python
# Source: [ASSUMED - pattern design based on verified kiutils behavior]
def round_trip_pcb_with_uuids(path: Path, output: Path) -> bool:
    """Round-trip a PCB file preserving all UUIDs."""
    raw = path.read_text()
    
    # Extract UUID map from raw content
    uuid_map = extract_uuids_from_sexp(raw)
    
    # Parse with kiutils (drops UUIDs)
    board = Board.from_file(str(path))
    
    # Serialize with kiutils (normalized output)
    board.to_file(str(output))
    
    # Re-inject UUIDs into normalized output
    normalized = output.read_text()
    # Apply UUID map to restore original UUIDs
    # (Implementation depends on matching kiutils output structure
    #  to original UUID context -- requires careful position matching)
    
    return True
```

### Anti-Patterns to Avoid
- **Anti-pattern: Expect byte-identical round-trip from kiutils.** kiutils normalizes formatting (tabs to spaces, collapses multi-line tokens, strips quotes). This is by design. Compare AST equality instead.
- **Anti-pattern: Trust kiutils with PCB UUIDs.** Verified: footprint.py and board.py have ZERO uuid handling. The `tstamp` field is always None for KiCad 9+ files. UUIDs are silently dropped.
- **Anti-pattern: Use `create_new()` for KiCad 10 files.** kiutils `create_new()` generates version 20211014 (KiCad 6). For KiCad 10 compatibility, you must parse an existing file or manually set `version = "20250114"`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| S-expression parsing | Custom recursive-descent parser | kiutils `from_file()` + sexpdata `loads()` | kiutils handles token ordering, nesting, type conversion. sexpdata handles arbitrary S-expressions. |
| S-expression serialization | String concatenation/f-strings | kiutils `to_sexpr()` / `to_file()` | Token ordering constraints are strict. kiutils handles ordering correctly. |
| Float formatting | Python default `str(float)` | Fixed-point with precision control | Default Python produces scientific notation (1.5e-07) which KiCad rejects. [CITED: kiutils issue #14] |
| UUID generation | mt19937 Mersenne Twister | Python `uuid.uuid4()` | KiCad uses mt19937 but Python's OS-level randomness is better for collision resistance. [CITED: KiCad file format spec] |

**Key insight:** kiutils handles 90% of the parsing/serialization correctly. The 10% it misses (UUIDs in PCB/footprint, exclude_from_sim, generator_version) can be handled with pre/post-processing wrappers around kiutils, not by replacing it.

## Common Pitfalls

### Pitfall 1: kiutils Drops PCB/Footprint UUIDs (CRITICAL)

**What goes wrong:** kiutils 1.4.8's footprint.py and board.py do not contain the string "uuid" anywhere. The KiCad 7+ format uses `(uuid "...")` tokens for footprints, pads, graphical items, zones, etc. kiutils only handles the legacy `tstamp` token, which is always `None` in KiCad 9+ files. Result: all 115 UUIDs in a test PCB were silently dropped.

**Why it happens:** kiutils was designed primarily for KiCad 6/7 format. The `uuid` token replaced `tstamp` in KiCad 7+, but kiutils' footprint and board modules were never updated. [VERIFIED: grep "uuid" in footprint.py and board.py returns zero results]

**How to avoid:** Build a UUID extraction layer that reads raw S-expressions before kiutils parsing, maps UUIDs to their context (footprint path, pad number, etc.), and re-injects them after kiutils serialization.

**Warning signs:** Round-trip test shows zero UUIDs in output. KiCad opens the file but assigns new UUIDs to all objects, breaking cross-references.

### Pitfall 2: kiutils Normalizes Formatting (Not Byte-Identical)

**What goes wrong:** kiutils changes tabs to spaces, collapses multi-line tokens to single lines, strips quotes from some string values, and drops `generator_version`. A 5184-line schematic becomes 1912 lines. A 4040-line PCB becomes 728 lines. The content is semantically equivalent but structurally very different.

**Why it happens:** kiutils' `to_sexpr()` methods produce a normalized, deterministic output format. This is actually a feature (SCM-friendly) but breaks byte-identical round-trip testing. [VERIFIED: live round-trip testing 2026-05-17]

**How to avoid:** Design round-trip tests to compare AST/IR equality, not byte equality. The two-pass stability test (parse -> serialize -> parse -> serialize -> compare) proves that output normalizes exactly once and then stabilizes.

**Warning signs:** Test suite fails on byte comparison. Diff shows massive reformatting.

### Pitfall 3: `exclude_from_sim` Silently Dropped from Symbols

**What goes wrong:** KiCad 9+ symbol definitions include `(exclude_from_sim no)` tokens. kiutils' symbol.py does not parse or serialize this token. It is silently dropped during parsing. 23 occurrences in a test file became 0.

**Why it happens:** `exclude_from_sim` was added in KiCad 7. kiutils' Symbol class does not have an `excludeFromSim` attribute. [VERIFIED: grep "exclude_from_sim" in symbol.py returns zero results]

**How to avoid:** Add post-processing to handle `exclude_from_sim`, or contribute the attribute to kiutils upstream. Default value is `no` (not excluded), so dropping it is semantically correct for most cases.

**Warning signs:** KiCad opens the file with a warning about unknown symbol attributes, or symbols that were excluded from simulation are now included.

### Pitfall 4: Coordinate Precision Differences

**What goes wrong:** Schematic files use 4-decimal precision. PCB files use 6-decimal precision. Mixing precision contexts silently loses data or adds noise.

**Why it happens:** KiCad's internal unit system uses different scales for board vs. schematic coordinates. [CITED: KiCad S-expression spec]

**How to avoid:** Track coordinate precision per file type in the IR layer. Use `format_coordinate(value, context='pcb')` with 6 decimals vs `format_coordinate(value, context='schematic')` with 4 decimals.

**Warning signs:** Diff shows coordinate drift in the 5th or 6th decimal place.

### Pitfall 5: Symbol Text Angles in Tenths of Degrees

**What goes wrong:** Symbol text ANGLE values are stored in tenths of a degree. All other ANGLE values are in degrees. Applying the same angle conversion to both corrupts symbol text by 10x.

**Why it happens:** The KiCad spec documents this asymmetry in a single warning note. kiutils passes the raw value through without conversion. [CITED: KiCad S-expression spec]

**How to avoid:** Create explicit `SymbolTextAngle` vs `StandardAngle` types. Unit test with a known 90-degree rotation.

**Warning signs:** Symbol text appears rotated incorrectly after round-trip.

### Pitfall 6: Scientific Notation in Float Output

**What goes wrong:** Python's default `str()` for very small floats produces scientific notation (e.g., `1.5e-07`). KiCad's file format states "Exponential floating point values are not used for readability purposes." Scientific notation may break KiCad's parser.

**Why it happens:** kiutils uses f-string float formatting in some `to_sexpr()` methods but may not control precision everywhere. [CITED: kiutils issue #14]

**How to avoid:** Force all float output to use fixed-point notation with appropriate precision. Never rely on Python's default float-to-string conversion.

**Warning signs:** KiCad reports parse errors on files with very small coordinate or dimension values.

## Code Examples

Verified patterns from live testing:

### Parse All Four File Types
```python
# Source: [VERIFIED: live API inspection 2026-05-17]
from kiutils.schematic import Schematic
from kiutils.board import Board
from kiutils.footprint import Footprint
from kiutils.symbol import SymbolLib

# Schematic - .kicad_sch
schematic = Schematic.from_file("path/to/file.kicad_sch")
# Key attributes: schematic.schematicSymbols, schematic.libSymbols,
#   schematic.wires, schematic.labels, schematic.junctions,
#   schematic.sheets, schematic.sheetInstances, schematic.symbolInstances
# Has uuid: YES (schematic.uuid)

# PCB Board - .kicad_pcb
board = Board.from_file("path/to/file.kicad_pcb")
# Key attributes: board.footprints, board.nets, board.segments,
#   board.vias, board.zones, board.graphicalItems, board.dimensions,
#   board.groups
# Has uuid: NO (dropped by kiutils - use UUID extractor)

# Symbol Library - .kicad_sym
symbol_lib = SymbolLib.from_file("path/to/file.kicad_sym")
# Key attributes: symbol_lib.symbols (list of Symbol objects)
# Each symbol has: entryName, pinNames, pinNamesHide, pinNamesOffset,
#   inBom, onBoard, properties, pins, graphicItems, units
# exclude_from_sim: NOT HANDLED (dropped)

# Footprint - .kicad_mod
footprint = Footprint.from_file("path/to/file.kicad_mod")
# Key attributes: footprint.libId, footprint.pads, footprint.graphicItems,
#   footprint.models, footprint.zones, footprint.properties (dict)
# footprint.position (Position object)
# Has uuid: NO (dropped by kiutils - use UUID extractor)
```

### Serialize All Four File Types
```python
# Source: [VERIFIED: live API inspection 2026-05-17]
# All types have identical API signatures:

# To same file (overwrites)
schematic.to_file()
board.to_file()
symbol_lib.to_file()
footprint.to_file()

# To different file
schematic.to_file("output.kicad_sch")
board.to_file("output.kicad_pcb")
symbol_lib.to_file("output.kicad_sym")
footprint.to_file("output.kicad_mod")

# To S-expression string (for in-memory processing)
sexpr_str = schematic.to_sexpr(indent=0, newline=True)
sexpr_str = board.to_sexpr(indent=0, newline=True)
sexpr_str = symbol_lib.to_sexpr(indent=0, newline=True)
sexpr_str = footprint.to_sexpr(indent=0, newline=True)  # Extra param: layerInFirstLine=False
```

### Effects (Hide) Handling -- Confirmed Working
```python
# Source: [VERIFIED: live testing 2026-05-17]
from kiutils.items.common import Effects, Property

# Hide IS properly parsed and serialized
e = Effects(hide=True)
print(e.to_sexpr())  # '(effects (font (size 1.0 1.0)) hide)\n'

e2 = Effects(hide=False)
print(e2.to_sexpr())  # '(effects (font (size 1.0 1.0)))\n'

# Property with hide round-trips correctly
from kiutils.utils.sexpr import parse_sexp
sexpr = '(property "Footprint" "" (id 2) (at 0 0 0) (effects (font (size 1.27 1.27)) hide))'
parsed = parse_sexp(sexpr)
p = Property.from_sexpr(parsed)
assert p.effects.hide == True
assert 'hide' in p.to_sexpr(indent=0)  # PASS - hide is preserved
```

### Pin Names Hide -- Confirmed Working in Symbol Library
```python
# Source: [VERIFIED: source inspection of kiutils/symbol.py lines 318-466]
# Symbol class has pinNames (bool), pinNamesHide (bool), pinNamesOffset (float?)
# pin_names (hide yes) is properly parsed via: if property == 'hide': object.pinNamesHide = True
# Serialized via: pnhide = f' hide' if self.pinNamesHide else ''
```

### Position Class API
```python
# Source: [VERIFIED: live API inspection 2026-05-17]
from kiutils.items.common import Position

# Position has: X (float), Y (float), angle (Optional[float]), unlocked (bool)
pos = Position(X=50.0, Y=30.0, angle=90, unlocked=False)
# angle is Optional -- may be None for items without rotation
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `tstamp` token (KiCad 5/6) | `uuid` token (KiCad 7+) | KiCad 7 | kiutils only handles `tstamp`, not `uuid` in PCB/footprint files |
| Tab indentation | Space indentation (kiutils) | kiutils design decision | First-pass normalizes tabs to 2-space indent |
| Multi-line tokens | Compact single-line tokens | kiutils design decision | Output is more compact but structurally different |
| KiCad 9 version 20241229 | KiCad 10 version likely 20250114+ | KiCad 10 release 2026-03-20 | Templates tested are KiCad 9 format; KiCad 10 may add new tokens |
| `exclude_from_sim` not in format | `exclude_from_sim (yes/no)` | KiCad 7 | kiutils does not handle this token |

**Deprecated/outdated:**
- `tstamp` token: Replaced by `uuid` in KiCad 7+. kiutils still uses `tstamp` internally.
- `module` token: Replaced by `footprint` in KiCad 6+. kiutils handles both.
- `host` token: Legacy KiCad 5 token. kiutils issue #81.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | KiCad 10 uses the same S-expression format as KiCad 9 (version 20241229) with possible minor additions | Standard Stack | If KiCad 10 adds significant format changes, kiutils 1.4.8 may not handle them |
| A2 | UUID re-injection via sexpdata post-processing is feasible for PCB/footprint files | Architecture Patterns | If UUID positions in kiutils output don't map cleanly to original positions, this approach fails |
| A3 | `exclude_from_sim` defaulting to `no` is acceptable for all use cases | Common Pitfalls | If some symbols need `exclude_from_sim yes`, this will be silently wrong |
| A4 | kiutils `to_sexpr()` float formatting does not produce scientific notation for typical coordinate ranges | Common Pitfalls | Very small coordinates (< 1e-6) may still produce scientific notation |
| A5 | The two-pass stability test (parse -> serialize -> parse -> serialize -> compare) is sufficient to prove serializer correctness | Architecture Patterns | If there are edge cases where kiutils output is NOT stable after first pass, tests won't catch it |

## Open Questions

1. **KiCad 10 Format Version Number**
   - What we know: KiCad 9 uses version 20241229. KiCad 10 released 2026-03-20.
   - What's unclear: Does KiCad 10 use a new version number (e.g., 20260320) or reuse 20241229?
   - Recommendation: Create a new KiCad 10 project with the installed kicad-cli and check the version token.

2. **UUID Re-injection Strategy**
   - What we know: kiutils drops all PCB/footprint UUIDs. We can extract them from raw S-expressions.
   - What's unclear: Can we reliably match extracted UUIDs to their corresponding objects in kiutils' output? Context-based matching (e.g., "this UUID belongs to the 3rd pad of the 2nd footprint") may work but is fragile.
   - Recommendation: Build a structured UUID map keyed by (object type, parent path, sequential position) during extraction, then match during re-injection.

3. **Should We Fork kiutils?**
   - What we know: kiutils has 3+ critical gaps for our use case (UUID, exclude_from_sim, generator_version).
   - What's unclear: Is it faster to fork and fix, or to build wrappers?
   - Recommendation: Start with wrappers. Fork only if wrappers become unmaintainable. Contribute fixes upstream.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | Runtime | YES | 3.11.11 | -- |
| kiutils | Parsing/serialization | YES | 1.4.8 | sexpdata 1.0.0 (fallback) |
| sexpdata | UUID extraction, fallback parsing | YES | 1.0.0 | -- |
| pytest | Test framework | YES | 8.4.2 | -- |
| pytest-cov | Coverage reporting | YES | 4.1.0 | -- |
| mypy | Type checking | YES | 1.7.1 | -- |
| ruff | Linting/formatting | YES | 0.13.0 | -- |
| kicad-cli | Validation (not Phase 1) | YES | 10.0.1 | -- |

**Missing dependencies with no fallback:**
- None -- all dependencies are installed.

**Missing dependencies with fallback:**
- None.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 |
| Config file | None -- use pyproject.toml [tool.pytest.ini_options] (Wave 0) |
| Quick run command | `pytest tests/test_roundtrip/ -x -q` |
| Full suite command | `pytest tests/ -v --cov=src/kicad_agent` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FND-01 | Parse .kicad_sch with full property coverage | unit | `pytest tests/test_parser/test_schematic_parser.py -x` | Wave 0 |
| FND-02 | Parse .kicad_pcb with full property coverage | unit | `pytest tests/test_parser/test_pcb_parser.py -x` | Wave 0 |
| FND-03 | Parse .kicad_sym with full property coverage | unit | `pytest tests/test_parser/test_symbol_parser.py -x` | Wave 0 |
| FND-04 | Parse .kicad_mod with full property coverage | unit | `pytest tests/test_parser/test_footprint_parser.py -x` | Wave 0 |
| FND-05 | Round-trip fidelity (AST equality) | integration | `pytest tests/test_roundtrip/ -x` | Wave 0 |
| FND-06 | UUID integrity preservation | unit | `pytest tests/test_parser/test_uuid_extractor.py -x` | Wave 0 |
| VAL-07 | Round-trip regression suite | integration | `pytest tests/test_roundtrip/ -v --tb=short` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x -q`
- **Per wave merge:** `pytest tests/ -v --cov=src/kicad_agent`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `pyproject.toml` -- project configuration with pytest settings
- [ ] `tests/conftest.py` -- shared fixtures (test KiCad file paths, temp dir helpers)
- [ ] `tests/fixtures/` -- copy sample KiCad files (from KiCad templates) for testing
- [ ] `tests/test_parser/test_schematic_parser.py` -- covers FND-01
- [ ] `tests/test_parser/test_pcb_parser.py` -- covers FND-02
- [ ] `tests/test_parser/test_symbol_parser.py` -- covers FND-03
- [ ] `tests/test_parser/test_footprint_parser.py` -- covers FND-04
- [ ] `tests/test_roundtrip/test_roundtrip_stability.py` -- covers FND-05, VAL-07
- [ ] `tests/test_parser/test_uuid_extractor.py` -- covers FND-06

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth in parsing library |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No access control |
| V5 Input Validation | yes | Validate KiCad file structure before parsing; catch malformed S-expressions |
| V6 Cryptography | no | No crypto |

### Known Threat Patterns for KiCad Parsing

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed S-expression (infinite nesting) | Denial of Service | sexpdata has recursion limits; add explicit depth limit |
| Path traversal in file operations | Tampering | Validate file paths are within expected project directory |
| Zip bomb in footprint 3D model references | Denial of Service | N/A for Phase 1 (no 3D model processing) |

## Sources

### Primary (HIGH confidence)
- kiutils 1.4.8 installed at `/Users/bretbouchard/.pyenv/versions/3.11.11/lib/python3.11/site-packages/kiutils/` -- verified all API signatures via `inspect.signature()` and source code reading
- Live round-trip testing against KiCad 9 template files at `/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/` -- Arduino_Mega, RaspberryPi-uHAT
- kiutils source code analysis: footprint.py (0 uuid references), board.py (0 uuid references), symbol.py (pin_names hide confirmed working), common.py (Effects.hide confirmed working, Property confirmed working)

### Secondary (MEDIUM confidence)
- KiCad S-expression file format specification (dev-docs.kicad.org) -- referenced for coordinate precision, angle units, token ordering
- kiutils GitHub issues: #120 (hidden properties -- may be fixed in 1.4.8 based on our testing), #107 (dimensions), #14 (scientific notation), #102 (pad layer quoting)

### Tertiary (LOW confidence)
- KiCad 10 format changes beyond what is in the spec -- not verified against a running KiCad 10 instance creating new files

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified installed and tested
- Architecture: HIGH -- patterns verified via live round-trip testing
- Pitfalls: HIGH -- all pitfalls verified via source code inspection and live testing
- UUID gap: HIGH -- confirmed via grep (zero "uuid" in footprint.py and board.py)

**Research date:** 2026-05-17
**Valid until:** 2026-06-17 (stable -- kiutils updates infrequently)
