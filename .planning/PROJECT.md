# kicad-agent

## What This Is

A full-stack KiCad automation agent — a GSD Skill backed by a Python library that enables AI-safe, structural editing of KiCad schematic, PCB, symbol library, and footprint library files. Works across any KiCad 10+ project.

The LLM never touches raw S-expressions. It emits structured intents (JSON operations), and the Python tool layer mutates the AST, serializes valid KiCad files, and validates via ERC/DRC gates.

## Core Value

**LLM → intent JSON → AST mutation → valid KiCad file.** Zero corruption, every time.

If the AI can't produce structurally valid KiCad files through the tool layer, nothing else matters.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Parse all KiCad 10+ file types (.kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod) into structured AST
- [ ] Component operations: duplicate, replicate, array components/sections
- [ ] Net operations: add/remove/reroute nets, bus operations
- [ ] Footprint management: assign, swap, validate footprints
- [ ] Reference management: renumber, validate, cross-reference checks
- [ ] ERC/DRC validation gates via kicad-cli after every edit
- [ ] Integrity checks: UUID integrity, symbol existence verification
- [ ] Net consistency: verify netlist consistency between schematic and PCB
- [ ] Structural diffs: syntax-aware diffs for S-expressions
- [ ] Round-trip fidelity: parse → modify → serialize produces valid KiCad files
- [ ] GSD Skill integration: invoke from any KiCad project via /kicad-agent
- [ ] Operation schema: well-defined JSON operation format for AI-to-tool communication

### Out of Scope

- KiCad 8.x/9.x backward compatibility — targeting 10+ only
- Direct GUI/editor integration — CLI and skill interface only
- Auto-routing — routing-rick agent handles that separately
- Simulation/SPICE integration — separate concern
- 3D model manipulation — out of scope for v1

## Context

- KiCad files are structured S-expressions with deep nesting, ordering constraints, fragile UUID/symbol references, and implicit electrical relationships
- Generic LLMs fail on KiCad files because: parentheses nesting is deep, ordering matters, UUIDs/symbol references are fragile, tiny syntax mistakes corrupt the file, semantic relationships are implicit, diffs become noisy
- The fix is constrained structural editing — the LLM emits operations, never raw text
- This tool integrates with the existing GSD/AI stack (Council of Ricks, kicad-rick agent, etc.)
- Existing tools: kiutils (Python), sexpdata (Python), kicad-cli for validation, difftastic for diffs
- The tool lives at ~/apps/kicad-agent/ (Python backend) with a skill definition at ~/.claude/skills/kicad-agent/

## Current Milestone: v2.2 complete-ops

**Goal:** Fill the operations gaps so kicad-agent can handle real-world KiCad projects with hierarchical designs and full CRUD capabilities.

**Target features:**
- Hierarchical sheet operations (add_sheet, add_sheet_pin, sheet navigation)
- Remove operations for wires, labels, junctions
- Footprint creation operation (create_footprint)
- Connectivity/netlist query operation
- Cross-file atomic operations wired to executor

## Constraints

- **Tech Stack**: Python 3.11+, kiutils, sexpdata, networkx for graph analysis — **Why: KiCad-native parsing, not regex hacks
- **KiCad Version**: 10+ only — **Why**: Current production version, no backward compat burden
- **AI Interface**: JSON operation schema, never raw text — **Why**: Prevents file corruption
- **Validation**: Every edit must pass ERC/DRC before commit — **Why**: Catch errors before they compound
- **Architecture**: LLM → intent → AST mutation → serializer → validated file — **Why**: Deterministic, diffable, testable, repairable

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| GSD Skill + Python backend | Integrates with existing stack, Python has best KiCad library ecosystem | — Pending |
| kiutils as primary parser | KiCad-specific AST manipulation, not generic S-expression | — Pending |
| Operation/intent JSON schema | LLM never touches raw files, structural safety | — Pending |
| kicad-cli for validation | Official KiCad validation, not reimplemented checks | — Pending |
| difftastic for diffs | Syntax-aware, handles deeply nested parens well | — Pending |
| Full stack in v1 | All file types, all ops, all validation layers | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-29 — Milestone v2.2 started*
