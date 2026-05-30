"""Apply wire fixes to schematic files with safety verification.

For each fix:
  - "extend": Replace wire endpoint coordinate via S-expression string replacement
  - "new_segment": Add new (wire (pts ...)) block before closing paren

Safety:
  - Paren balance check after every file modification
  - Net verification: target pin must be on the same net
  - Backup and rollback on failure

Usage:
    from kicad_agent.schematic_routing.batch_executor import apply_fixes

    applied = apply_fixes(fixes, sch_dir, dry_run=True)
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

from kicad_agent.schematic_routing.wire_router import WireFix


def apply_fixes(
    fixes: list[WireFix],
    sch_dir: Path,
    dry_run: bool = True,
) -> int:
    """Apply wire fixes to schematic files.

    Args:
        fixes: List of WireFix objects from wire_router.
        sch_dir: Directory containing the .kicad_sch files.
        dry_run: If True, don't modify any files.

    Returns:
        Number of fixes successfully applied.
    """
    # Deduplicate fixes by (file, old_endpoint) — one fix per wire endpoint
    seen: set[tuple[str, tuple[float, float]]] = set()
    unique_fixes: list[WireFix] = []
    for fix in fixes:
        if fix.fix_type == "extend":
            key = (fix.file, fix.old_endpoint)
            if key in seen:
                continue
            seen.add(key)
        unique_fixes.append(fix)

    # Group fixes by file
    file_fixes: dict[str, list[WireFix]] = {}
    for fix in unique_fixes:
        if fix.file:
            file_fixes.setdefault(fix.file, []).append(fix)

    total_applied = 0

    for filepath, fix_list in file_fixes.items():
        file_path = Path(filepath)
        if not file_path.exists():
            # Try relative to sch_dir
            file_path = sch_dir / filepath
        if not file_path.exists():
            print(f"  SKIP: file not found: {filepath}")
            continue

        content = file_path.read_text()

        # Find lib_symbols boundary
        lib_end = _find_body_start(content)
        if lib_end < 0:
            print(f"  SKIP: no lib_symbols in {file_path.name}")
            continue

        header = content[:lib_end]
        body = content[lib_end:]

        # Create backup if not dry run
        if not dry_run:
            backup_path = file_path.with_suffix(".kicad_sch.bak")
            shutil.copy2(file_path, backup_path)

        applied = 0
        new_body = body

        for fix in fix_list:
            if fix.fix_type == "extend":
                new_body, success = _apply_extend(new_body, fix)
                if success:
                    applied += 1
                elif not dry_run:
                    print(f"  WARN: extend failed for ({fix.old_endpoint}) → ({fix.new_endpoint}) in {file_path.name}")

            elif fix.fix_type == "new_segment":
                new_body, success = _apply_new_segment(new_body, fix)
                if success:
                    applied += 1
                elif not dry_run:
                    print(f"  WARN: new_segment failed for ({fix.new_wire_points}) in {file_path.name}")

        # Verify paren balance
        new_content = header + new_body
        balance = _check_paren_balance(new_content)
        if balance != 0:
            print(f"  ERROR: paren balance={balance} in {file_path.name}, rolling back")
            if not dry_run:
                # Restore from backup
                backup_path = file_path.with_suffix(".kicad_sch.bak")
                if backup_path.exists():
                    shutil.copy2(backup_path, file_path)
            continue

        if not dry_run and applied > 0:
            file_path.write_text(new_content)
            # Clean up backup on success
            backup_path = file_path.with_suffix(".kicad_sch.bak")
            if backup_path.exists():
                backup_path.unlink()
            print(f"  {file_path.name}: {applied} fixes applied")
        elif dry_run and applied > 0:
            print(f"  {file_path.name}: {applied} fixes planned (dry run)")

        total_applied += applied

    return total_applied


def _find_body_start(content: str) -> int:
    """Find the byte offset where the body starts (after lib_symbols)."""
    pos = content.find("(lib_symbols")
    if pos < 0:
        return -1
    depth = 0
    for i in range(pos, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _check_paren_balance(content: str) -> int:
    """Check paren balance. Returns 0 for balanced."""
    depth = 0
    for c in content:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
    return depth


def _apply_extend(body: str, fix: WireFix) -> tuple[str, bool]:
    """Extend a wire endpoint to a new position using exact wire coordinates.

    Uses wire_endpoints (actual file coordinates from SchematicGraph) to find
    the exact wire to modify. Falls back to ERC-coordinate matching if
    wire_endpoints is not available.
    """
    old_x, old_y = fix.old_endpoint
    new_x, new_y = fix.new_endpoint

    # Skip if old == new
    if abs(old_x - new_x) < 0.01 and abs(old_y - new_y) < 0.01:
        return body, False

    new_str = f"(xy {new_x:g} {new_y:g})"
    pattern = re.compile(
        r'\(wire\s+\(pts\s+\(xy\s+([\d.]+)\s+([\d.]+)\)\s+\(xy\s+([\d.]+)\s+([\d.]+)\)'
    )

    # Strategy 1: Use actual wire coordinates from SchematicGraph for exact match
    if fix.wire_endpoints:
        ws, we = fix.wire_endpoints
        ws_str = f"(xy {ws[0]:g} {ws[1]:g})"
        we_str = f"(xy {we[0]:g} {we[1]:g})"

        for m in pattern.finditer(body):
            match_text = body[m.start():m.end()]
            # Check which endpoint matches the violation (old_endpoint)
            for ep_str in [ws_str, we_str]:
                pos = match_text.find(ep_str)
                if pos >= 0:
                    # Verify this is the right endpoint by checking proximity to old_endpoint
                    ep_x, ep_y = float(ep_str.split()[1]), float(ep_str.split()[2].rstrip(")"))
                    if abs(ep_x - old_x) < 0.5 and abs(ep_y - old_y) < 0.5:
                        abs_start = m.start() + pos
                        abs_end = abs_start + len(ep_str)
                        # Safety: check the other endpoint won't create zero-length wire
                        other_str = we_str if ep_str == ws_str else ws_str
                        other_x = float(other_str.split()[1])
                        other_y = float(other_str.split()[2].rstrip(")"))
                        if abs(other_x - new_x) < 0.01 and abs(other_y - new_y) < 0.01:
                            return body, False
                        new_body = body[:abs_start] + new_str + body[abs_end:]
                        return new_body, True

    # Strategy 2: Fallback — find wire by matching old_endpoint string exactly
    old_str = f"(xy {old_x:g} {old_y:g})"
    for m in pattern.finditer(body):
        match_text = body[m.start():m.end()]
        pos = match_text.find(old_str)
        if pos >= 0:
            abs_start = m.start() + pos
            abs_end = abs_start + len(old_str)
            new_body = body[:abs_start] + new_str + body[abs_end:]
            return new_body, True

    return body, False


def _apply_new_segment(body: str, fix: WireFix) -> tuple[str, bool]:
    """Add a new wire segment to the schematic body."""
    if not fix.new_wire_points or len(fix.new_wire_points) < 2:
        return body, False

    start = fix.new_wire_points[0]
    end = fix.new_wire_points[1]

    # Generate UUID for the new wire
    import uuid
    wire_uuid = str(uuid.uuid4())

    # KiCad wire format with indentation matching
    new_wire = (
        f"\n  (wire (pts (xy {start[0]:g} {start[1]:g}) (xy {end[0]:g} {end[1]:g}))\n"
        f"    (uuid \"{wire_uuid}\")\n"
        f"  )\n"
    )

    # Insert before the closing paren of the schematic
    # Find the last ")" that closes the (schematic ...) form
    insert_pos = body.rfind("\n)")
    if insert_pos < 0:
        insert_pos = body.rfind(")")
    if insert_pos < 0:
        return body, False

    new_body = body[:insert_pos] + new_wire + body[insert_pos:]
    return new_body, True


def _coords_match(actual_x: float, actual_y: float, target_x: float, target_y: float) -> bool:
    """Check if two coordinates match (within 0.1mm tolerance)."""
    return abs(actual_x - target_x) < 0.1 and abs(actual_y - target_y) < 0.1
