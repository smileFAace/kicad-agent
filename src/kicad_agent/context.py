"""Project context renderer for summarizing KiCad project state.

Given any directory containing KiCad files, discovers file types, counts
components and nets, and produces a human-readable summary suitable for
AI context injection.

Threat model mitigations:
- T-07-10: Recursive glob on KiCad projects (typically small directories)
- T-07-11: Parse errors caught and skipped (try/except + logging.warning)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from kicad_agent.ir import SchematicIR, PcbIR
from kicad_agent.parser import parse_schematic, parse_pcb
from kicad_agent.parser.uuid_extractor import extract_uuids

logger = logging.getLogger(__name__)

# KiCad file extensions mapped to their category
_KICAD_GLOB_PATTERNS: dict[str, str] = {
    "schematic_files": "**/*.kicad_sch",
    "pcb_files": "**/*.kicad_pcb",
    "symbol_lib_files": "**/*.kicad_sym",
    "footprint_files": "**/*.kicad_mod",
}


@dataclass(frozen=True)
class ProjectSummary:
    """Immutable snapshot of a KiCad project's file structure with counts.

    Attributes:
        project_dir: Absolute path to the project directory.
        schematic_files: Relative paths to .kicad_sch files.
        pcb_files: Relative paths to .kicad_pcb files.
        symbol_lib_files: Relative paths to .kicad_sym files.
        footprint_files: Relative paths to .kicad_mod files.
        component_count: Total components across all schematics.
        net_count: Total nets across all PCBs.
        footprint_count: Total footprints placed on PCBs.
    """

    project_dir: Path
    schematic_files: tuple[str, ...]
    pcb_files: tuple[str, ...]
    symbol_lib_files: tuple[str, ...]
    footprint_files: tuple[str, ...]
    component_count: int = 0
    net_count: int = 0
    footprint_count: int = 0

    @property
    def has_kicad_files(self) -> bool:
        """True if any KiCad files were found."""
        return self.total_files > 0

    @property
    def total_files(self) -> int:
        """Total count of all KiCad files found."""
        return (
            len(self.schematic_files)
            + len(self.pcb_files)
            + len(self.symbol_lib_files)
            + len(self.footprint_files)
        )


def discover_kicad_files(project_dir: Path) -> ProjectSummary:
    """Discover all KiCad files in a project directory.

    Recursively globs for all four KiCad file extensions and returns
    a ProjectSummary with file lists and zero counts (no enrichment).

    Args:
        project_dir: Path to the directory to scan.

    Returns:
        ProjectSummary with discovered files and zero counts.

    Raises:
        FileNotFoundError: If project_dir does not exist or is not a directory.
    """
    resolved = project_dir.resolve()

    if not resolved.is_dir():
        raise FileNotFoundError(
            f"Path does not exist or is not a directory: {project_dir}"
        )

    file_lists: dict[str, tuple[str, ...]] = {}
    for attr_name, pattern in _KICAD_GLOB_PATTERNS.items():
        found = sorted(resolved.glob(pattern))
        file_lists[attr_name] = tuple(
            str(f.relative_to(resolved)) for f in found
        )

    return ProjectSummary(
        project_dir=resolved,
        schematic_files=file_lists["schematic_files"],
        pcb_files=file_lists["pcb_files"],
        symbol_lib_files=file_lists["symbol_lib_files"],
        footprint_files=file_lists["footprint_files"],
    )


def enrich_summary(summary: ProjectSummary) -> ProjectSummary:
    """Enrich a ProjectSummary with component, net, and footprint counts.

    Parses each schematic and PCB file to extract counts. Files that
    fail to parse are skipped with a warning log.

    Args:
        summary: A ProjectSummary from discover_kicad_files.

    Returns:
        New ProjectSummary with enriched counts.
    """
    component_count = 0
    net_count = 0
    footprint_count = 0

    # Count components from schematics
    for rel_path in summary.schematic_files:
        abs_path = summary.project_dir / rel_path
        try:
            result = parse_schematic(abs_path)
            ir = SchematicIR(_parse_result=result)
            component_count += len(ir.components)
        except Exception as exc:
            logger.warning("Failed to parse schematic %s: %s", rel_path, exc)

    # Count footprints and nets from PCBs
    for rel_path in summary.pcb_files:
        abs_path = summary.project_dir / rel_path
        try:
            result = parse_pcb(abs_path)
            uuid_map = extract_uuids(result.raw_content, "pcb")
            ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)
            footprint_count += len(ir.footprints)
            net_count += len(ir.nets)
        except Exception as exc:
            logger.warning("Failed to parse PCB %s: %s", rel_path, exc)

    return ProjectSummary(
        project_dir=summary.project_dir,
        schematic_files=summary.schematic_files,
        pcb_files=summary.pcb_files,
        symbol_lib_files=summary.symbol_lib_files,
        footprint_files=summary.footprint_files,
        component_count=component_count,
        net_count=net_count,
        footprint_count=footprint_count,
    )


def render_project_context(project_dir: Path, enrich: bool = True) -> str:
    """Render a human-readable summary of a KiCad project directory.

    Discovers KiCad files, optionally enriches with component/net counts,
    and produces formatted text suitable for AI context injection.

    Args:
        project_dir: Path to the directory to summarize.
        enrich: If True, parse files to count components and nets.

    Returns:
        Formatted text summary of the project.
    """
    summary = discover_kicad_files(project_dir)

    if not summary.has_kicad_files:
        return f"No KiCad files found in {project_dir}"

    if enrich:
        summary = enrich_summary(summary)

    lines: list[str] = []
    lines.append(f"KiCad Project: {summary.project_dir.name}")
    lines.append(f"Location: {summary.project_dir}")
    lines.append(
        f"Files: {summary.total_files} total "
        f"({len(summary.schematic_files)} schematics, "
        f"{len(summary.pcb_files)} PCBs, "
        f"{len(summary.symbol_lib_files)} symbol libs, "
        f"{len(summary.footprint_files)} footprint libs)"
    )
    lines.append("")
    lines.append(f"Components: {summary.component_count} across all schematics")
    lines.append(f"Nets: {summary.net_count} across all PCBs")
    lines.append(f"Footprints: {summary.footprint_count} placed on PCBs")
    lines.append("")
    lines.append("Files:")

    if summary.schematic_files:
        lines.append("  Schematics:")
        for f in summary.schematic_files:
            lines.append(f"    - {f}")

    if summary.pcb_files:
        lines.append("  PCBs:")
        for f in summary.pcb_files:
            lines.append(f"    - {f}")

    if summary.symbol_lib_files:
        lines.append("  Symbol Libraries:")
        for f in summary.symbol_lib_files:
            lines.append(f"    - {f}")

    if summary.footprint_files:
        lines.append("  Footprint Libraries:")
        for f in summary.footprint_files:
            lines.append(f"    - {f}")

    return "\n".join(lines)
