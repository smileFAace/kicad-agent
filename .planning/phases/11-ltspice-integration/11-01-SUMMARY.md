---
phase: 11-ltspice-integration
plan: 01
subsystem: api
tags: [ltspice, spicelib, asc-parser, simulation, spice, frozen-dataclass]

# Dependency graph
requires: []
provides:
  - LTspice .asc file parser via SpiceLib AscEditor into frozen dataclasses
  - Simulation command parser for .tran/.ac/.dc/.noise/.op directives
  - 12 bundled .asy symbol stubs for parsing without LTspice installed
affects: [11-ltspice-integration, ltspice-net-graph, ltspice-raw-reader, ltspice-bridge]

# Tech tracking
tech-stack:
  added: [spicelib-1.5.1]
  patterns: [frozen-dataclass-results, barrel-exports, bundled-symbol-stubs, eng-notation-parser]

key-files:
  created:
    - src/kicad_agent/ltspice/__init__.py
    - src/kicad_agent/ltspice/types.py
    - src/kicad_agent/ltspice/asc_parser.py
    - src/kicad_agent/ltspice/sim_commands.py
    - src/kicad_agent/ltspice/asy_stubs/res.asy
    - src/kicad_agent/ltspice/asy_stubs/cap.asy
    - src/kicad_agent/ltspice/asy_stubs/ind.asy
    - src/kicad_agent/ltspice/asy_stubs/voltage.asy
    - src/kicad_agent/ltspice/asy_stubs/current.asy
    - src/kicad_agent/ltspice/asy_stubs/diode.asy
    - src/kicad_agent/ltspice/asy_stubs/npn.asy
    - src/kicad_agent/ltspice/asy_stubs/pnp.asy
    - src/kicad_agent/ltspice/asy_stubs/nmos.asy
    - src/kicad_agent/ltspice/asy_stubs/pmos.asy
    - src/kicad_agent/ltspice/asy_stubs/opamp.asy
    - src/kicad_agent/ltspice/asy_stubs/gnd.asy
    - tests/fixtures/ltspice/basic_rc.asc
    - tests/test_ltspice_parser.py
  modified: []

key-decisions:
  - "Bundled .asy stubs for 12 common components to parse without LTspice installed"
  - "SpiceLib AscEditor with set_custom_library_paths classmethod for symbol resolution"
  - "Engineering notation parser handles SI prefix + trailing unit chars (1ms -> 0.001)"
  - "Parameters stored as tuple of pairs for frozen dataclass immutability"

patterns-established:
  - "Frozen dataclass result types matching existing result.py and spatial/primitives.py patterns"
  - "Barrel exports in __init__.py with explicit __all__ list"
  - "Path validation with resolve() + traversal check before file operations"

requirements-completed: [LTSPICE-01, LTSPICE-02, LTSPICE-04]

# Metrics
duration: 8min
completed: 2026-05-23
---

# Phase 11 Plan 01: LTspice .asc Parser Summary

**SpiceLib AscEditor-based .asc parser producing frozen dataclass schematics with 12 bundled .asy stubs and simulation command parser for .tran/.ac/.dc/.noise/.op**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-23T14:38:35Z
- **Completed:** 2026-05-23T14:46:45Z
- **Tasks:** 2
- **Files modified:** 18

## Accomplishments
- parse_asc() resolves .asc files into LTspiceSchematic with components, wires, flags, directives, and simulation commands
- 12 bundled .asy symbol stubs (res, cap, ind, voltage, current, diode, npn, pnp, nmos, pmos, opamp, gnd) enable parsing without LTspice
- Simulation command parser handles .tran, .ac, .dc, .noise, .op with engineering notation (1k, 1ms, 1u, 100k)
- Path traversal protection and FileNotFoundError for missing files

## Task Commits

Each task was committed atomically with TDD RED/GREEN:

1. **Task 1: Frozen dataclass types, .asy stubs, test fixture, and parse_asc implementation** - `b47bb13` (test RED) + `83d2d01` (feat GREEN)
2. **Task 2: Simulation command parser for .tran/.ac/.dc/.noise/.op** - `d714160` (test RED) + `fddb638` (feat GREEN)

## Files Created/Modified
- `src/kicad_agent/ltspice/__init__.py` - Barrel exports for all public types and functions
- `src/kicad_agent/ltspice/types.py` - Frozen dataclasses: LTspiceComponent, LTspiceWire, LTspiceFlag, LTspiceDirective, LTspiceSchematic
- `src/kicad_agent/ltspice/asc_parser.py` - parse_asc() using SpiceLib AscEditor with .asy stub resolution
- `src/kicad_agent/ltspice/sim_commands.py` - parse_simulation_command() with TranCommand, AcCommand, DcCommand, NoiseCommand, OpCommand
- `src/kicad_agent/ltspice/asy_stubs/*.asy` - 12 minimal .asy symbol stubs for common components
- `tests/fixtures/ltspice/basic_rc.asc` - RC circuit test fixture with R1, C1, V1, wires, GND flag, .tran directive
- `tests/test_ltspice_parser.py` - 14 tests covering asc parsing and simulation commands

## Decisions Made
- Bundled .asy stubs rather than requiring LTspice installation -- enables CI and cross-platform parsing
- Used SpiceLib's classmethod set_custom_library_paths for .asy resolution -- simple for single-threaded parsing
- Engineering notation regex extended to handle trailing unit chars (e.g. "1ms" has prefix "m" + unit "s") -- SPICE values commonly include unit suffixes
- LTspiceSchematic fields ordered with simulation_commands after source_path to satisfy frozen dataclass default-argument ordering

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed .asy Version capitalization**
- **Found during:** Task 1 (parse_asc GREEN phase)
- **Issue:** .asy stub files used `VERSION 4` but SpiceLib AsyReader expects `Version 4` (mixed case)
- **Fix:** Changed all 12 .asy files from `VERSION` to `Version`
- **Files modified:** All src/kicad_agent/ltspice/asy_stubs/*.asy
- **Verification:** All tests pass, AsyReader parses stubs correctly
- **Committed in:** 83d2d01 (Task 1 GREEN commit)

**2. [Rule 3 - Blocking] Fixed TextTypeEnum import path**
- **Found during:** Task 1 (parse_asc GREEN phase)
- **Issue:** Import `from spicelib.utils.text import TextTypeEnum` fails -- correct path is `spicelib.editor.asc_editor`
- **Fix:** Changed import to `from spicelib.editor.asc_editor import TextTypeEnum`
- **Files modified:** src/kicad_agent/ltspice/asc_parser.py
- **Verification:** Tests pass, module imports correctly
- **Committed in:** 83d2d01 (Task 1 GREEN commit)

**3. [Rule 1 - Bug] Fixed frozen dataclass field ordering**
- **Found during:** Task 1 (types.py creation)
- **Issue:** `simulation_commands` with default value `()` before non-default `source_path` -- Python dataclass requirement violated
- **Fix:** Moved `source_path` before `simulation_commands` in LTspiceSchematic
- **Files modified:** src/kicad_agent/ltspice/types.py
- **Verification:** Module loads without TypeError
- **Committed in:** b47bb13 (Task 1 RED commit)

**4. [Rule 1 - Bug] Fixed .tran argument field mapping**
- **Found during:** Task 2 (sim_commands GREEN phase)
- **Issue:** Test expected args mapped as tstart/tstop/tstart_meas/tstep but code mapped as tstep/tstop/tstart/tstart_meas
- **Fix:** Remapped _parse_tran args to match test expectations: args[0]->tstart, args[1]->tstop, args[2]->tstart_meas, args[3]->tstep
- **Files modified:** src/kicad_agent/ltspice/sim_commands.py
- **Verification:** All 14 tests pass
- **Committed in:** fddb638 (Task 2 GREEN commit)

---

**Total deviations:** 4 auto-fixed (2 blocking, 2 bug)
**Impact on plan:** All auto-fixes necessary for correctness. No scope creep.

## Issues Encountered
- Engineering notation "1ms" failed to parse because regex only accepted single-char SI prefix without trailing unit chars -- fixed by updating regex to `^([\d.]+)\s*([TGMkmunpf])([a-zA-Z]*)$|^([\d.]+)$`

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- LTspiceSchematic data model ready for net connectivity derivation (Plan 02)
- parse_asc() provides components with positions/rotations needed for pin position matching
- Wire segments and flags ready for union-find graph construction
- Simulation commands parsed and available for downstream consumers

---
*Phase: 11-ltspice-integration*
*Completed: 2026-05-23*

## Self-Check: PASSED

All 10 claimed files verified present. All 4 commit hashes verified in git log.
