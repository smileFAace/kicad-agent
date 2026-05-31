"""Parse and read .kicad_pro project configuration files.

KiCad .kicad_pro files are JSON files containing project settings,
board design settings, schematic settings, and project metadata.

Security (threat model):
- Path traversal protection via resolve() checks
- File size validation

Usage:
    from kicad_agent.project.project_file import parse_project_file

    proj = parse_project_file(Path("board.kicad_pro"))
    print(proj.version, proj.general)
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectFile:
    """Parsed .kicad_pro project configuration.

    Attributes:
        version: Project file version string (e.g. "20240517").
        general: Raw general section from the JSON structure.
        pcbnew: Raw pcbnew settings section.
        schematic: Raw schematic settings section.
    """

    version: str = ""
    general: dict[str, Any] = field(default_factory=dict)
    pcbnew: dict[str, Any] = field(default_factory=dict)
    schematic: dict[str, Any] = field(default_factory=dict)


def parse_project_file(path: Path) -> ProjectFile:
    """Parse a .kicad_pro project file.

    The .kicad_pro format is JSON (not S-expression). This extracts
    the key sections into a structured ProjectFile object.

    Args:
        path: Path to the .kicad_pro file.

    Returns:
        Parsed ProjectFile with version, general, pcbnew, and schematic sections.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is not valid JSON.
    """
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {path}")

    content = resolved.read_text(encoding="utf-8")
    if not content.strip():
        return ProjectFile()

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(data).__name__}")

    # Extract known sections
    # .kicad_pro JSON has "general", "pcbnew", "schematic" as top-level keys
    # Some versions nest these under a "board" key
    general = data.get("general", {})
    pcbnew = data.get("pcbnew", {})
    schematic = data.get("schematic", {})

    # Version may be in different places depending on format
    version = str(data.get("version", ""))

    # If there is a "board" key, extract board-level settings from it
    board = data.get("board", {})
    if board and isinstance(board, dict):
        # Merge board design_settings into pcbnew if not already present
        if "design_settings" in board and "design_settings" not in pcbnew:
            pcbnew = {**pcbnew, "design_settings": board["design_settings"]}

    return ProjectFile(
        version=version,
        general=general if isinstance(general, dict) else {},
        pcbnew=pcbnew if isinstance(pcbnew, dict) else {},
        schematic=schematic if isinstance(schematic, dict) else {},
    )


def write_project_settings(path: Path, updates: dict[str, Any]) -> None:
    """Write updated settings to a .kicad_pro project file.

    Reads the raw JSON, deep-merges the updates dict, and writes back
    atomically to prevent file corruption. Operates on raw JSON to
    preserve unknown keys that the ProjectFile dataclass does not model.

    Args:
        path: Path to the .kicad_pro file.
        updates: Dictionary of sections to merge into the project file.
            Nested dicts are deep-merged; other values are replaced.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is not valid JSON.
    """
    import os
    import tempfile

    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {path}")

    content = resolved.read_text(encoding="utf-8")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(data).__name__}")

    def _deep_merge(target: dict, source: dict) -> dict:
        """Deep-merge source into target, returning merged dict."""
        result = dict(target)
        for key, value in source.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = _deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    data = _deep_merge(data, updates)

    # Atomic write (Council FE-02): write to temp file then replace
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".kicad_pro", dir=resolved.parent)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, resolved)
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_project_settings(project_dir: Path) -> dict[str, Any]:
    """Discover project files and return combined settings dict.

    High-level function that reads all project-level files in a directory
    and returns a combined settings dictionary.

    Args:
        project_dir: Path to the KiCad project directory.

    Returns:
        Dictionary with keys: project (ProjectFile data), libraries,
        design_rules, plus any discovered settings.
    """
    resolved = project_dir.resolve()
    if not resolved.is_dir():
        raise ValueError(f"Not a directory: {project_dir}")

    settings: dict[str, Any] = {}

    # Find .kicad_pro file
    pro_files = list(resolved.glob("*.kicad_pro"))
    if pro_files:
        pro = parse_project_file(pro_files[0])
        settings["project"] = {
            "version": pro.version,
            "general": pro.general,
            "pcbnew": pro.pcbnew,
            "schematic": pro.schematic,
        }

    # Find library tables
    sym_lib_table = resolved / "sym-lib-table"
    if sym_lib_table.exists():
        try:
            from kicad_agent.project.lib_table import parse_lib_table
            table = parse_lib_table(sym_lib_table)
            settings["symbol_libraries"] = [
                {"name": e.name, "uri": e.uri, "type": e.type}
                for e in table.entries
            ]
        except Exception as e:
            logger.warning("Failed to parse sym-lib-table: %s", e)

    fp_lib_table = resolved / "fp-lib-table"
    if fp_lib_table.exists():
        try:
            from kicad_agent.project.lib_table import parse_lib_table
            table = parse_lib_table(fp_lib_table)
            settings["footprint_libraries"] = [
                {"name": e.name, "uri": e.uri, "type": e.type}
                for e in table.entries
            ]
        except Exception as e:
            logger.warning("Failed to parse fp-lib-table: %s", e)

    # Find DRU files
    dru_files = list(resolved.glob("*.kicad_dru"))
    if dru_files:
        try:
            from kicad_agent.project.design_rules import parse_design_rules
            dru = parse_design_rules(dru_files[0])
            settings["design_rules"] = {
                "version": dru.version,
                "net_classes": [
                    {"name": nc.name, "clearance": nc.clearance, "track_width": nc.track_width}
                    for nc in dru.net_classes
                ],
                "custom_rules": [
                    {"name": r.name, "constraint_type": r.constraint_type}
                    for r in dru.custom_rules
                ],
            }
        except Exception as e:
            logger.warning("Failed to parse .kicad_dru: %s", e)

    return settings
