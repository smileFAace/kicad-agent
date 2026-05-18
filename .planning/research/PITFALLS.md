# Domain Pitfalls

**Domain:** KiCad automation agent (S-expression structural editing via AI-safe JSON intent layer)
**Researched:** 2026-05-18
**Confidence:** HIGH (official KiCad dev-docs, kiutils GitHub issues, verified local kiutils 1.4.8 + sexpdata 1.0.0)

## Critical Pitfalls

Mistakes that cause rewrites or major issues.

---

### Pitfall 1: Symbol Text Angle Units -- Tenths of a Degree vs. Degrees

**What goes wrong:**
KiCad stores symbol `text` ANGLE values in tenths of a degree. All other ANGLE values throughout the entire KiCad file format are stored in plain degrees. Code that applies the same angle parsing/formatting to symbol text that it uses for footprints, board graphics, and positions will silently corrupt rotation values by a factor of 10. A 90-degree rotation becomes 9 degrees or 900 degrees depending on direction.

**Why it happens:**
The KiCad S-expression spec documents this asymmetry in a single warning note: "Symbol text ANGLEs are stored in tenth's of a degree. All other ANGLEs are stored in degrees." This is easy to miss because the `(at X Y ANGLE)` position identifier syntax looks identical everywhere -- only the semantic interpretation differs for symbol text. kiutils does not abstract away this difference; the raw value flows through from the parsed S-expression to the dataclass field.

**Consequences:**
- Symbol text appears rotated incorrectly after round-trip parse/serialize
- DRC/ERC passes but visual layout is wrong
- Diff against original file shows spurious angle changes, masking real edits
- Extremely hard to debug because the values look "close to correct" (off by 10x)

**Prevention:**
1. Create explicit `SymbolTextAngle` and `StandardAngle` types (or wrapper functions) that convert between storage format (tenths vs degrees) and canonical degrees on parse/serialize
2. Unit test: parse a known symbol with text at 90 degrees, verify the angle value reads as 90 (not 900), serialize, verify round-trip fidelity
3. Never reuse footprint/board angle formatting code for symbol text without the conversion layer

**Detection:**
- Round-trip diff shows `(at X Y 900)` where original had `(at X Y 90)` in symbol text contexts
- Visual inspection: symbol text labels appear nearly horizontal when they should be vertical

**Phase to address:** Phase 1 (Parser) -- angle handling must be correct before any symbol editing operations are possible.

---

### Pitfall 2: Coordinate Precision Truncation -- PCB vs. Schematic

**What goes wrong:**
KiCad uses different coordinate precision for different file types. PCB and footprint files have nanometer precision (6 decimal places). Schematic and symbol library files have nanometer precision (4 decimal places). Serializing a coordinate with too many decimal places causes KiCad to truncate the value, which accumulates across round-trips. Worse, mixing precision contexts (e.g., copying a footprint coordinate to a schematic position) silently loses precision.

**Why it happens:**
The KiCad spec states: "The minimum internal unit for printed circuit board and footprint files is one nanometer so there is maximum resolution of six decimal places" and "The minimum internal unit for schematic and symbol library files is one nanometer so there is maximum resolution of four decimal places." The word "nanometer" appears in both, but the decimal place limits differ because KiCad's internal unit system uses different scales for board vs. schematic coordinates.

**Consequences:**
- Round-trip fidelity breaks: parse -> serialize produces subtly different coordinates
- Accumulated drift over multiple edit cycles causes components to shift position
- DRC violations emerge from coordinates that drifted off-grid

**Prevention:**
1. Use context-aware serialization: `format_coordinate(value, context='pcb')` vs `format_coordinate(value, context='schematic')`
2. PCB coordinates: format to 6 decimal places max. Schematic/symbol coordinates: format to 4 decimal places max
3. Round-trip test suite: parse every supported file type, serialize, diff against original. Any coordinate difference is a bug
4. Never pass PCB-precision coordinates into schematic operations without rounding

**Detection:**
- `diff original.kicad_pcb roundtrip.kicad_pcb` shows coordinate drift in the 5th or 6th decimal place
- `diff original.kicad_sch roundtrip.kicad_sch` shows coordinate drift in the 5th decimal place

**Phase to address:** Phase 1 (Parser + Serializer) -- coordinate formatting must be correct before any file modification is attempted.

---

### Pitfall 3: UUID Collision from mt19937 Mersenne Twister

**What goes wrong:**
KiCad generates UUIDs using the mt19937 Mersenne Twister algorithm, not a cryptographically random source. mt19937 has a known state recovery attack: after observing 624 consecutive outputs, an attacker can predict all future outputs. More practically for automation: generating many UUIDs in rapid succession from the same seed state produces UUIDs that are less random than expected. If the automation tool generates UUIDs using Python's default `uuid.uuid4()` (which uses OS-level randomness), the UUIDs are structurally compatible but generated via a different algorithm, which may cause issues with tools that validate UUID provenance.

**Why it happens:**
The KiCad file format spec explicitly states: "The UUID attribute is a Version 4 (random) UUID that should be globally unique. KiCad UUIDs are generated using the mt19937 Mersenne Twister algorithm." Additionally: "Files converted from legacy versions of KiCad (prior to 6.0) have their locally-unique timestamps re-encoded in UUID format." Legacy timestamp UUIDs are NOT globally unique -- they are deterministic based on file creation order.

**Consequences:**
- Duplicate UUIDs when operating on legacy-converted files
- UUID collision between new objects created by the tool and existing objects (unlikely but possible with mt19937 under rapid generation)
- KiCad's internal UUID validation may reject or merge objects with colliding UUIDs

**Prevention:**
1. Always generate new UUIDs using Python's `uuid.uuid4()` (OS-level randomness), not mt19937
2. Before adding any new object, scan all existing UUIDs in the file to verify the new UUID does not collide
3. For legacy files (pre-6.0 converted), treat UUIDs as "locally unique within this file" not globally unique. Never copy objects between files without regenerating UUIDs
4. Include UUID uniqueness validation in the integrity check pipeline

**Detection:**
- ERC reports "duplicate UUID" warnings
- KiCad opens the file but merges or drops objects with identical UUIDs
- `grep -c` on UUID values returns > 1 in a single file

**Phase to address:** Phase 1 (Parser) for UUID scanning, Phase 2 (Operations) for UUID generation in new objects.

---

### Pitfall 4: kiutils Round-Trip Fidelity Gaps -- Hidden Property Fields

**What goes wrong:**
kiutils v1.4.8 has a known bug where opening and saving a schematic file silently drops the `hide` text effect from symbol property fields. Hidden properties become visible after a parse/serialize cycle. This means the most basic operation -- parse a file and save it unchanged -- produces a file that is visually and structurally different from the original.

**Why it happens:**
GitHub issue mvnmgrx/kiutils#120 documents this: the `hide` token in symbol property effects is not properly preserved through kiutils' dataclass representation. The parser reads the hide state but the serializer does not emit it back. This is a kiutils-specific bug, not a KiCad format limitation.

**Consequences:**
- Any file that passes through the tool has its hidden properties revealed
- Schematics with dozens of hidden power flags, no-connect markers, or internal labels suddenly show all of them
- Visual clutter makes the schematic unusable in KiCad's GUI
- Downstream tools (BOM generators, netlist exporters) may behave differently

**Prevention:**
1. Run the full kiutils test suite against target KiCad version before trusting it
2. Implement round-trip fidelity tests BEFORE writing any editing operations: parse every file type, serialize, binary diff against original
3. Patch kiutils locally or contribute upstream fixes for known serialization gaps
4. Consider a post-serialization validation step that compares token-by-token with the original for fields the tool did not intentionally modify
5. Track kiutils issues: #120 (hidden properties), #121 (S-expression formatting), #113 (KiCad 8 compatibility), #107 (dimensions not handled), #102 (pad layers quoted)

**Detection:**
- `diff original.kicad_sch saved.kicad_sch` shows removed `(hide)` tokens
- KiCad opens the file and properties that were hidden are now visible
- Automated round-trip test fails

**Phase to address:** Phase 1 (Parser) -- round-trip fidelity must be verified and any kiutils bugs patched before ANY editing operations are built on top.

---

### Pitfall 5: Library Identifier Nickname Resolution -- Not Stored in Library Files

**What goes wrong:**
KiCad library identifiers use the format `"LIBRARY_NICKNAME:ENTRY_NAME"`. The LIBRARY_NICKNAME is assigned in the project's symbol or footprint library table (sym-lib-table / fp-lib-table), NOT in the library file itself. A `.kicad_sym` file only contains ENTRY_NAME values. When the automation tool reads a library file in isolation, it cannot know the library nickname. When it reads a schematic that references `"MyLib:LM7805"`, it must resolve "MyLib" through the project's library table to find the actual `.kicad_sym` file path.

**Why it happens:**
The KiCad format spec explicitly warns: "The LIBRARY_NICKNAME is not stored in the library files because a library cannot know what the assigned library table nickname is in advance. Only the ENTRY_NAME is saved in the library files." This is a design decision for library portability -- the same library can have different nicknames in different projects.

**Consequences:**
- Cannot validate symbol references without the project's library table
- Cannot find the actual library file for a symbol without resolving the nickname
- Copying symbols between projects breaks if the target project uses a different nickname for the same library
- Symbol existence verification requires loading the project context, not just the library file

**Prevention:**
1. Always load the project's `sym-lib-table` and `fp-lib-table` alongside the schematic/PCB being edited
2. Build a nickname-to-path resolver that maps library nicknames to filesystem paths
3. When creating operations that reference symbols or footprints, validate that the library nickname exists in the project's table before emitting the edit
4. Never assume a library nickname from the library filename

**Detection:**
- ERC reports "library not found" for symbols that exist in the library but under a different nickname
- Automation tool cannot locate symbol definition for a valid library reference

**Phase to address:** Phase 1 (Parser) for library table parsing, Phase 2 (Operations) for symbol resolution during edits.

---

### Pitfall 6: Layer Name Canonicalization -- User Names vs. Canonical Names

**What goes wrong:**
KiCad allows users to rename layers for display purposes. The internal file format always uses canonical layer names (e.g., `F.Cu`, `In1.Cu`, `B.SilkS`), but users see and interact with display names (e.g., "Top Copper", "Inner 1", "Bottom Silkscreen"). If the automation tool accepts user-facing layer names in operation JSON, it must translate them to canonical names before writing to the file. KiCad has 60 total layers (32 copper) with specific canonical names, and wildcard patterns like `*.Cu`.

**Why it happens:**
The KiCad spec states: "Internally, all layer names are canonical. User defined layer names are only used for display and output purposes." The layer definition in the file format uses canonical names, but the KiCad GUI and user mental model use display names. The automation tool bridges both worlds.

**Consequences:**
- Operations referencing layers by display name produce invalid S-expressions
- Layer validation fails because canonical name lookup returns nothing for display names
- Wildcard patterns (`*.Cu`) are valid in file format but must be expanded correctly

**Prevention:**
1. Build a canonical layer name registry with all 60 layers mapped from the KiCad spec
2. If accepting user-facing names in operations, require a project-specific layer name mapping
3. Validate layer references against the canonical name list before writing
4. Support wildcard expansion (`*.Cu` -> all copper layers) for operations that target multiple layers

**Detection:**
- KiCad reports "unknown layer" when opening a file with non-canonical layer names
- DRC fails with layer-related errors

**Phase to address:** Phase 1 (Parser) for layer name parsing, Phase 2 (Operations) for layer validation.

---

### Pitfall 7: S-Expression Token Ordering Constraints

**What goes wrong:**
KiCad S-expressions have strict token ordering within each form. For example, in a `(footprint ...)` form, the library link must come first, then `locked`, then `placed`, then `layer`, then `tedit`, then `uuid`, then position, and so on. Reordering tokens produces a file that is semantically identical but structurally different from what KiCad expects. KiCad may reject the file or silently misinterpret tokens.

**Why it happens:**
Unlike JSON where key ordering is insignificant, S-expressions are positional. The `(at X Y ANGLE)` form has X at position 1, Y at position 2, and ANGLE at position 3. The `(pad "NUMBER" TYPE SHAPE POSITION ...)` form has a specific sequence of 28+ optional and required tokens in a defined order. Optional tokens have specific positions relative to required tokens.

**Consequences:**
- KiCad rejects the file outright with parse errors
- KiCad opens the file but misinterprets token values (reads a UUID as a position, etc.)
- Round-trip fidelity breaks because the serializer emits tokens in a different order than the original

**Prevention:**
1. Never construct S-expressions by string concatenation or ad-hoc ordering
2. Use kiutils' serializer (which handles ordering) rather than writing custom S-expression emission
3. Where kiutils does not cover a token, follow the exact order from the KiCad format spec
4. Validate output with kicad-cli after every write operation -- it catches ordering errors

**Detection:**
- kicad-cli reports parse errors on the output file
- KiCad GUI shows "unexpected token" warnings on load
- Round-trip diff shows reordered tokens

**Phase to address:** Phase 1 (Serializer) -- token ordering must be correct before any file write is attempted.

---

### Pitfall 8: Net Connectivity Graph Consistency Between Schematic and PCB

**What goes wrong:**
KiCad maintains separate net representations in schematics (.kicad_sch) and PCBs (.kicad_pcb). The netlist is the bridge between them. An operation that modifies a net in the schematic (adding a connection, renaming a net) must be reflected in the PCB, and vice versa. The automation tool can easily create inconsistencies: rename a net in the schematic without updating the PCB, and the netlist import will create a new net instead of matching the renamed one.

**Why it happens:**
Nets are not referenced by a single global ID. In the schematic, nets are identified by name. In the PCB, nets have both a numeric ID and a name. The netlist export from schematic to PCB matches by name. Renaming a net in one without the other breaks the match. Additionally, buses in schematics create hierarchical net naming that must be resolved correctly.

**Consequences:**
- Netlist import creates duplicate nets (old name persists in PCB, new name from schematic)
- DRC reports thousands of "unconnected pins" that were previously connected
- Board becomes unsyncable with schematic without manual cleanup

**Prevention:**
1. Any net operation must be applied to BOTH schematic and PCB in a single transaction
2. After net modifications, run netlist export and compare net counts/names before and after
3. Build a net consistency validator that compares schematic nets against PCB nets
4. For net renames: update all references in both files, including zone net_name fields, pad net references, and label text

**Detection:**
- Net count differs between schematic and PCB
- DRC reports unconnected pins that were previously connected
- kicad-cli netlist diff shows additions/removals

**Phase to address:** Phase 2 (Net Operations) -- net consistency validation must be built alongside the first net editing operation.

---

### Pitfall 9: AI-Generated S-Expression Corruption

**What goes wrong:**
The entire architecture exists because LLMs cannot reliably produce valid S-expressions. Common corruption patterns include: unbalanced parentheses, missing closing quotes on strings, token values in wrong positions, numeric values in string fields, UUIDs with invalid format, missing required tokens, and extra tokens that KiCad ignores but which change the file hash. Even with the JSON intent layer, the serializer that converts intents to S-expressions can introduce these errors if not rigorously validated.

**Why it happens:**
S-expressions are deeply nested (a typical footprint has 10+ levels of nesting), positionally significant, and contain mixed types (strings, numbers, tokens, UUIDs, coordinate pairs). LLMs trained primarily on JSON/Python lack the pattern recognition for balanced-parentheses counting across hundreds of lines. The JSON intent layer prevents direct LLM-to-S-expression emission, but the intent-to-AST mutation step can still produce invalid structures if the mutation code has bugs.

**Consequences:**
- KiCad cannot open the file at all (parse failure)
- KiCad opens the file but objects are missing or corrupted
- Silent data loss: objects present in the original but omitted from the corrupted output

**Prevention:**
1. The LLM NEVER emits S-expressions -- only JSON intents. Enforce this at the architecture level
2. The serializer that converts AST to S-expressions must be a deterministic, tested component with 100% round-trip fidelity
3. Run kicad-cli ERC/DRC validation after EVERY edit, not just at the end
4. Implement a S-expression linter/validator that checks: balanced parens, quoted strings closed, valid UUIDs, required tokens present, token ordering correct
5. Keep the original file as a backup before every mutation -- never mutate in place

**Detection:**
- kicad-cli exits non-zero on the output file
- Parentheses count mismatch between original and output
- Objects missing from output that were in original (count comparison)

**Phase to address:** Phase 1 (Architecture + Parser) -- the LLM-never-touches-raw-files invariant must be enforced from day one.

---

### Pitfall 10: kicad-cli Version Compatibility

**What goes wrong:**
kicad-cli behavior and command-line flags differ between KiCad versions. The tool targets KiCad 10+, but during development and testing, developers may have KiCad 8 or 9 installed. Commands that work on KiCad 10 may fail or produce different output on earlier versions. ERC/DRC command syntax, output format, and exit codes may change between major versions.

**Why it happens:**
kicad-cli is not a stable public API -- it is a CLI frontend to KiCad's internal validation engine. KiCad's development team does not guarantee CLI compatibility across major versions. The tool's validation pipeline depends on kicad-cli producing consistent, parseable output.

**Consequences:**
- Validation passes locally (KiCad 8) but fails in CI (KiCad 10)
- ERC/DRC output format changes break the result parser
- False positives/negatives in validation due to version-specific DRC rules

**Prevention:**
1. Detect kicad-cli version at startup and refuse to proceed if not KiCad 10+
2. Parse `kicad-cli --version` output and validate major version
3. Pin the kicad-cli output parser to KiCad 10's documented format
4. Document the minimum kicad-cli version in the tool's requirements

**Detection:**
- kicad-cli output parsing fails (unexpected format)
- DRC rules differ between local and CI environments
- `kicad-cli --version` reports version < 10

**Phase to address:** Phase 1 (Validation Pipeline) -- version detection must be the first thing the validation module does.

---

## Moderate Pitfalls

---

### Pitfall 11: Footprint Pad Layer Quoting Inconsistency

**What goes wrong:**
kiutils issue #102 documents that pad layer tokens may be quoted in the source file but kiutils strips the quotes during parsing. On serialization, the layers are emitted unquoted. While KiCad accepts both forms, this creates spurious diffs in version control and breaks the "zero-diff round-trip" goal.

**Prevention:**
Track the original quoting style during parsing and reproduce it during serialization, or accept that layer quoting may cause minor cosmetic diffs.

---

### Pitfall 12: Dimension Objects Not Fully Handled

**What goes wrong:**
kiutils issue #107 reports that dimension objects cause parse errors: "Dimensions are not yet handled! Please report this bug along with the file being parsed." If a PCB contains dimension annotations, kiutils cannot parse the file at all. This means any real-world PCB with dimensions is inaccessible to the automation tool.

**Prevention:**
1. Test kiutils against real-world PCBs containing dimensions before trusting it
2. If dimensions are not supported, handle the parse error gracefully and document the limitation
3. Consider contributing dimension parsing support to kiutils upstream
4. Alternative: use sexpdata for raw S-expression parsing when kiutils fails, then layer domain logic on top

---

### Pitfall 13: Small Numbers in Scientific Notation

**What goes wrong:**
kiutils issue #14 documents that very small floating-point numbers are serialized in scientific notation (e.g., `1.5e-07` instead of `0.00000015`). KiCad's file format states "Exponential floating point values are not used for readability purposes." Scientific notation in the output file breaks KiCad's parser or causes unexpected behavior.

**Prevention:**
Force all floating-point output to use fixed-point notation with appropriate precision. Never allow Python's default float-to-string conversion to produce scientific notation.

---

### Pitfall 14: Group Member UUID References

**What goes wrong:**
KiCad groups reference member objects by UUID. When the automation tool moves, copies, or deletes objects, it must update group membership lists accordingly. Deleting an object without removing its UUID from all group member lists creates dangling references. KiCad may crash or behave unpredictably with dangling group member UUIDs.

**Prevention:**
1. When deleting any object, scan all groups for its UUID and remove it
2. When copying objects, create new UUIDs AND add them to the appropriate groups
3. Validate group membership integrity as part of the post-edit validation pipeline

---

### Pitfall 15: Exponential Floating-Point Drift Over Multiple Edits

**What goes wrong:**
Each coordinate serialization truncates to the appropriate precision (4 or 6 decimal places). Over multiple edit cycles (parse -> mutate -> serialize -> parse -> mutate -> serialize), the truncation accumulates. A coordinate that starts at exactly 1.0000 may drift to 0.9999 or 1.0001 after enough cycles. With 6 decimal places, this takes many more cycles, but with 4 decimal places (schematic), drift is visible after 3-5 cycles.

**Prevention:**
1. Track original coordinates separately from mutated coordinates
2. When a mutation does not intentionally change a coordinate, preserve the original string representation (not the parsed float)
3. Consider storing coordinates as strings or Decimal types to avoid float representation issues
4. Round-trip test: run 100 parse/serialize cycles on a file and verify coordinates have not drifted

---

## Minor Pitfalls

---

### Pitfall 16: Concurrent File Access -- KiCad Lock Files

**What goes wrong:**
KiCad uses lock files to prevent concurrent access to project files. When KiCad has a schematic open, it writes a `.kicad_sch.lck` file. The automation tool must respect these lock files and not modify files that KiCad has open. Conversely, the tool should write its own lock files to prevent KiCad from opening files mid-edit.

**Prevention:**
Check for `.lck` files before any write operation. Fail with a clear message if the file is locked by another process. Create and remove lock files around the tool's own edit operations.

---

### Pitfall 17: Generator and Generator Version Tokens

**What goes wrong:**
KiCad files include `(generator "...")` and `(generator_version "...")` tokens that identify the tool that created/modified the file. If the automation tool strips or changes these tokens, KiCad may apply compatibility transformations or show warnings. If the tool sets them incorrectly, KiCad may reject newer format features.

**Prevention:**
Set generator to the tool's name (e.g., "kicad-agent") and generator_version to a meaningful version string. Preserve existing generator tokens from files the tool did not create.

---

### Pitfall 18: Legacy Token Handling (host, module)

**What goes wrong:**
kiutils issue #81 documents legacy tokens like `host` in schematics. Prior to KiCad 6, footprints used the `module` token instead of `footprint`. Files converted from legacy formats may contain these tokens. The parser must handle or gracefully skip unknown legacy tokens rather than crashing.

**Prevention:**
Implement a forgiving parser that skips unknown tokens with a warning rather than failing. Log skipped tokens for diagnostic purposes.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| S-expression parser | Token ordering violations (Pitfall 7) | Follow KiCad spec ordering exactly; validate with kicad-cli |
| Coordinate handling | Precision truncation mismatch (Pitfall 2) | Context-aware formatting (4 vs 6 decimal places) |
| Symbol text parsing | Angle unit confusion (Pitfall 1) | Explicit SymbolTextAngle vs StandardAngle types |
| UUID management | mt19937 collision risk (Pitfall 3) | Use Python uuid4(); scan for duplicates before insert |
| Round-trip fidelity | kiutils hidden property bug (Pitfall 4) | Round-trip test suite; patch kiutils or contribute fix |
| Library resolution | Nickname not in library file (Pitfall 5) | Always load sym-lib-table and fp-lib-table with project |
| Layer handling | Canonical vs display names (Pitfall 6) | Build canonical name registry; validate before write |
| Net operations | Schematic-PCB consistency (Pitfall 8) | Atomic operations across both files; net consistency validator |
| AI intent processing | S-expression corruption (Pitfall 9) | LLM never touches raw files; kicad-cli validation after every edit |
| Validation pipeline | kicad-cli version mismatch (Pitfall 10) | Version detection at startup; refuse non-10+ versions |
| Footprint editing | Pad layer quoting (Pitfall 11) | Track original quoting; accept cosmetic diffs |
| PCB parsing | Dimension objects crash (Pitfall 12) | Test with real PCBs; fallback to sexpdata for unhandled tokens |
| Number formatting | Scientific notation (Pitfall 13) | Force fixed-point notation for all floats |
| Object deletion | Group member dangling refs (Pitfall 14) | Scan and update all groups on delete |
| Iterative editing | Coordinate drift (Pitfall 15) | Preserve original string representations for unchanged values |
| File I/O | Concurrent access (Pitfall 16) | Check and create .lck files |
| File metadata | Generator tokens (Pitfall 17) | Set correctly; preserve existing |

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip round-trip tests | Faster initial development | kiutils serialization bugs silently corrupt files | Never |
| Ignore symbol text angle conversion | Less code, faster parsing | Symbol text rotation off by 10x | Never |
| Use Python default float formatting | Simpler serialization | Scientific notation breaks KiCad parser | Never |
| Skip library table loading | Parse files in isolation | Cannot resolve library references | Prototype only |
| Allow kicad-cli < 10 | Works with more installations | Validation output format differs, false results | Never |
| Skip .lck file checks | Simpler file I/O | Concurrent modification corruption | Prototype only |
| Trust kiutils round-trip fidelity | No custom serialization needed | Known bugs (hide, layers, dimensions) corrupt files | Never -- verify first |
| Store coordinates as float64 | Standard numeric handling | Precision drift over multiple edit cycles | Acceptable if round-trip string preservation is implemented |

## "Looks Done But Is Not" Checklist

- [ ] **Round-trip fidelity:** Parse -> serialize produces identical file (diff returns zero) for ALL file types
- [ ] **Symbol text angles:** Values in tenths-of-degree contexts read as degrees, not raw tenths
- [ ] **Hidden properties:** Schematics with hidden properties round-trip without revealing them
- [ ] **Dimension objects:** PCBs with dimensions parse without errors
- [ ] **Scientific notation:** No floats serialized in exponential format
- [ ] **Library nicknames:** Symbol references resolve through project library tables
- [ ] **Layer canonical names:** All 60 layers handled; no display-name-only references in output
- [ ] **UUID uniqueness:** No duplicate UUIDs in any output file
- [ ] **Net consistency:** Schematic and PCB net counts and names match after net operations
- [ ] **Group integrity:** No dangling group member UUIDs after object deletion
- [ ] **kicad-cli version:** Version 10+ detected and enforced before validation
- [ ] **Coordinate precision:** PCB files use 6 decimal places, schematic files use 4

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Symbol text angle corruption | LOW | Re-parse original file. Apply angle conversion to symbol text contexts only. Re-serialize. |
| Coordinate precision drift | LOW | Re-parse original file. Use correct precision formatting. Re-serialize. |
| UUID collision | MEDIUM | Identify colliding UUIDs. Generate new unique UUIDs for each collision. Update all references. |
| Hidden property loss | MEDIUM | Re-open original file. Extract hide state for all properties. Apply to modified file. |
| Library reference breakage | HIGH | Re-resolve all library nicknames through project tables. Fix broken references manually. May require user input. |
| Net consistency failure | HIGH | Re-export netlist from schematic. Re-import to PCB. Manual review of any unmatched nets. |
| S-expression corruption (AI) | CRITICAL | Restore from backup. Re-apply intended operations one at a time with validation after each. |

## Sources

### HIGH Confidence
- **KiCad S-expression file format specification** (dev-docs.kicad.org/en/file-formats/sexpr-intro/): Verified 2026-05-18. Authoritative source for token ordering, coordinate precision, angle units, layer names, library identifiers, UUID generation, and all structural constraints.
- **kiutils GitHub issues** (github.com/mvnmgrx/kiutils/issues): #120 (hidden properties bug), #121 (S-expression formatting), #113 (KiCad 8 compatibility), #107 (dimensions not handled), #102 (pad layer quoting), #81 (legacy tokens), #14 (scientific notation), #60 (fp_arc versioning). Verified 2026-05-18.
- **Local kiutils installation**: kiutils 1.4.8 and sexpdata 1.0.0 verified present on development machine.
- **Context7 kiutils documentation** (library ID: /mvnmgrx/kiutils): Parse/serialize patterns, Board/Schematic/Footprint APIs, Position handling. Verified 2026-05-18.

### MEDIUM Confidence
- **KiCad mt19937 UUID generation**: Documented in the official S-expression spec but the practical collision risk for automation-scale generation (thousands of UUIDs) is inferred from the algorithm's properties, not observed in practice.
- **kicad-cli version compatibility**: Based on general KiCad release patterns and CLI documentation. Specific flag/output differences between KiCad 8/9/10 not exhaustively verified.
- **Net consistency patterns**: Based on KiCad's netlist export/import model. Specific edge cases in bus/ hierarchical net naming not exhaustively tested.

### LOW Confidence
- **Concurrent file access lock file format**: KiCad's .lck file format is not officially documented. Behavior inferred from community reports and file system observation.
- **Legacy file conversion edge cases**: Pre-6.0 timestamp-as-UUID conversion documented in spec but specific failure modes not tested.
- **KiCad 10 specific changes**: KiCad 10 format changes beyond what is documented in the S-expression spec have not been verified against a running KiCad 10 installation.

---
*Pitfalls research for: KiCad automation agent (kicad-agent)*
*Researched: 2026-05-18*
*Confidence: HIGH (official KiCad spec + kiutils issues + Context7 docs + local verification)*
