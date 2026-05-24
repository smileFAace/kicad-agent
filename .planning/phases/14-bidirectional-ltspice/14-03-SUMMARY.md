---
phase: 14-bidirectional-ltspice
plan: 03
subsystem: ltspice
tags: [ltspice, spice, simulation, serialization, round-trip, bidirectional]

# Dependency graph
requires:
  - phase: 14-02
    provides: AscWriter with CoordinateTransformer for KiCad-to-LTspice export
  - phase: 11-ltspice-integration
    provides: parse_simulation_command() and sim command dataclasses
provides:
  - serialize_sim_command() for SimulationCommand -> directive text
  - Sim command injection into AscWriter export pipeline
  - Full round-trip validation: KiCad + sim commands -> .asc -> parse back
affects: [15-ai-generation-wiring, bidirectional-export]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "serialize-then-parse round-trip for simulation command fidelity"
    - "editor.directives.append() for SpiceLib directive injection"

key-files:
  created: []
  modified:
    - src/kicad_agent/ltspice/sim_commands.py
    - src/kicad_agent/ltspice/asc_writer.py
    - src/kicad_agent/ltspice/__init__.py
    - tests/test_ltspice_writer.py

key-decisions:
  - "Plain float formatting in serialize_sim_command (not engineering notation) for simplicity and determinism"
  - "Extended parse_eng_value() to handle scientific notation (1e-06) for round-trip correctness"

patterns-established:
  - "Serialize -> parse round-trip pattern for command dataclasses"
  - "SimulationCommand injection via editor.directives.append() with asc_text_align_set"

requirements-completed: [BIDI-04]

# Metrics
duration: 4min
completed: 2026-05-24
---

# Phase 14 Plan 03: Simulation Command Serialization and Round-Trip Summary

**Simulation command serialization, injection into .asc export pipeline, and full KiCad-to-LTspice round-trip validation**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-24T00:08:45Z
- **Completed:** 2026-05-24T00:12:44Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- serialize_sim_command() serializes all 5 command types (Tran, Ac, Dc, Noise, Op) to LTspice directive text
- Simulation commands inject into exported .asc files via editor.directives.append()
- Full round-trip validated: KiCad schematic + TranCommand -> export .asc -> parse_asc() -> command recovered
- AscWriter.add_simulation_command() enables post-construction command injection
- 1013 total tests passing, 0 regressions

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing tests for serialize_sim_command** - `28c0364` (test)
2. **Task 1 (GREEN): serialize_sim_command with sci notation support** - `ca2c783` (feat)
3. **Task 2: Sim command injection and full round-trip** - `6ce239d` (feat)

## Files Created/Modified
- `src/kicad_agent/ltspice/sim_commands.py` - Added serialize_sim_command() and scientific notation support in parse_eng_value()
- `src/kicad_agent/ltspice/asc_writer.py` - Added simulation_commands parameter, _write_sim_commands(), add_simulation_command()
- `src/kicad_agent/ltspice/__init__.py` - Exported serialize_sim_command
- `tests/test_ltspice_writer.py` - Added TestSimCommandSerialization (8 tests), TestSimCommandInjection (3 tests), TestFullRoundTrip (1 test)

## Decisions Made
- Plain float formatting in serialize_sim_command rather than engineering notation -- LTspice accepts both, plain floats keep output simple and deterministic
- Extended parse_eng_value() to accept scientific notation (e.g. "1e-06") to ensure round-trip fidelity when Python formats small floats in f-strings

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] parse_eng_value() fails on scientific notation**
- **Found during:** Task 1 (GREEN phase -- round-trip TranCommand test)
- **Issue:** Python formats 0.000001 as "1e-06" in f-strings, but parse_eng_value() regex only matched digits+dots, not scientific notation
- **Fix:** Extended _ENG_VALUE_RE regex with `([\d.]+[eE][+-]?\d+)` group and updated parse_eng_value() to handle group 4 (scientific) and group 5 (plain number)
- **Files modified:** src/kicad_agent/ltspice/sim_commands.py
- **Verification:** All 8 TestSimCommandSerialization tests pass including round-trip tests
- **Committed in:** ca2c783 (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Auto-fix was necessary for round-trip correctness. No scope creep.

## Issues Encountered
None beyond the auto-fix above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Bidirectional LTspice bridge complete (Phase 14 all 3 plans done)
- serialize_sim_command() + parse_simulation_command() enable full round-trip
- Ready for Phase 15: AI generation wiring can use the export pipeline with simulation commands

---
*Phase: 14-bidirectional-ltspice*
*Completed: 2026-05-24*

## Self-Check: PASSED

All files verified present: sim_commands.py, asc_writer.py, __init__.py, test_ltspice_writer.py, 14-03-SUMMARY.md
All commits verified: 28c0364 (RED), ca2c783 (GREEN), 6ce239d (Task 2)
