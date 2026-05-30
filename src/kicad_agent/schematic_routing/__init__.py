"""Netlist-aware schematic wire router for fixing unconnected_wire_endpoint violations.

4-phase pipeline:
  1. Net Resolution — trace each dangling wire endpoint to its net name
  2. Target Discovery — find nearest same-net pins within range
  3. Wire Routing — extend or add wire segments to connect
  4. Apply + Verify — modify files, re-run ERC, confirm decrease

Usage:
    from kicad_agent.schematic_routing import run_router

    results = run_router(
        schematic_path="analog-board.kicad_sch",
        netlist_path="analog-board.net",
        erc_json_path="erc.json",
        dry_run=True,
    )
"""

from kicad_agent.schematic_routing.netlist_parser import parse_netlist
from kicad_agent.schematic_routing.schematic_graph import SchematicGraph
from kicad_agent.schematic_routing.net_resolver import resolve_violation_nets
from kicad_agent.schematic_routing.target_finder import find_targets
from kicad_agent.schematic_routing.wire_router import generate_fixes
from kicad_agent.schematic_routing.batch_executor import apply_fixes

__all__ = [
    "parse_netlist",
    "SchematicGraph",
    "resolve_violation_nets",
    "find_targets",
    "generate_fixes",
    "apply_fixes",
    "run_router",
]


def run_router(
    schematic_path: str,
    netlist_path: str,
    erc_json_path: str,
    dry_run: bool = True,
    max_distance: float = 25.4,
    grid: float = 2.54,
) -> dict:
    """Run the full netlist-aware wire routing pipeline.

    Args:
        schematic_path: Path to the root .kicad_sch file.
        netlist_path: Path to exported netlist (.net).
        erc_json_path: Path to ERC JSON report.
        dry_run: If True, plan fixes without modifying files.
        max_distance: Maximum distance (mm) for wire extension.
        grid: Grid spacing (mm) for coordinate snapping.

    Returns:
        Dict with keys: violations, resolved_nets, targets, fixes, applied, erc_delta.
    """
    # Phase 1: Parse netlist → {net_name: [(ref, pin), ...]}
    net_index, pin_index = parse_netlist(netlist_path)

    # Phase 2: Parse ERC JSON → violation positions
    import json
    from pathlib import Path

    with open(erc_json_path) as f:
        erc_data = json.load(f)

    violations = _parse_erc_violations(erc_data)

    # Phase 3: Parse sub-sheets and resolve nets
    sch_dir = Path(schematic_path).parent
    resolved = resolve_violation_nets(violations, net_index, pin_index, sch_dir)

    # Phase 4: Find targets and generate fixes
    targets = find_targets(resolved, net_index, pin_index, sch_dir, max_distance)
    fixes = generate_fixes(targets, grid=grid)

    # Phase 5: Apply and verify
    applied = apply_fixes(fixes, sch_dir, dry_run=dry_run)

    return {
        "violations": len(violations),
        "resolved_nets": len(resolved),
        "targets": len(targets),
        "fixes": len(fixes),
        "applied": applied,
    }


def _parse_erc_violations(erc_data: dict) -> list[dict]:
    """Extract unconnected_wire_endpoint violations from ERC JSON."""
    violations = []
    for sheet in erc_data.get("sheets", []):
        for violation in sheet.get("violations", []):
            if violation.get("type") == "unconnected_wire_endpoint":
                for item in violation.get("items", []):
                    pos = item.get("pos", {})
                    # ERC JSON says "mm" but values are actually mm/100
                    # Multiply by 100 to match schematic file coordinates
                    violations.append({
                        "x": pos.get("x", 0) * 100,
                        "y": pos.get("y", 0) * 100,
                        "sheet": sheet.get("path", "/"),
                        "description": item.get("description", ""),
                        "uuid": item.get("uuid", ""),
                    })
    return violations
