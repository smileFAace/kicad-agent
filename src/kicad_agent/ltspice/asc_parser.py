"""LTspice .asc schematic file parser using SpiceLib AscEditor.

Provides parse_asc() to convert .asc files into structured LTspiceSchematic
frozen dataclasses with components, wires, flags, and directives.
"""

from __future__ import annotations

from pathlib import Path

from spicelib import AscEditor
from spicelib.editor.asc_editor import ASC_INV_ROTATION_DICT
from spicelib.editor.asc_editor import TextTypeEnum

from kicad_agent.ltspice.sim_commands import parse_simulation_command
from kicad_agent.ltspice.types import (
    LTspiceComponent,
    LTspiceDirective,
    LTspiceFlag,
    LTspiceSchematic,
    LTspiceWire,
)

ASY_STUBS_DIR: Path = Path(__file__).parent / "asy_stubs"


def _validate_path(asc_path: str | Path) -> Path:
    """Resolve and validate the .asc file path.

    Args:
        asc_path: Raw path to validate.

    Returns:
        Resolved absolute Path.

    Raises:
        FileNotFoundError: If the resolved path does not exist.
        ValueError: If the path contains traversal sequences.
    """
    resolved = Path(asc_path).resolve()

    # Path traversal protection: reject ".." components in the original path
    parts = Path(asc_path).parts
    if ".." in parts:
        raise ValueError(
            f"Path contains traversal sequences: {asc_path}"
        )

    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {resolved}")

    return resolved


def parse_asc(asc_path: str | Path) -> LTspiceSchematic:
    """Parse an LTspice .asc file into a structured LTspiceSchematic.

    Uses SpiceLib AscEditor for robust .asc parsing with bundled .asy
    symbol stubs so parsing works without LTspice installed.

    Args:
        asc_path: Path to the .asc file to parse.

    Returns:
        LTspiceSchematic with components, wires, flags, and directives.

    Raises:
        FileNotFoundError: If the .asc file does not exist.
        ValueError: If the path contains traversal sequences.
    """
    resolved = _validate_path(asc_path)

    # Configure bundled .asy stubs for symbol resolution
    AscEditor.set_custom_library_paths(str(ASY_STUBS_DIR))

    editor = AscEditor(str(resolved))

    # Extract components
    components: list[LTspiceComponent] = []
    for ref in editor.get_components():
        comp = editor.get_component(ref)
        pos, rot = editor.get_component_position(ref)
        value = editor.get_component_value(ref)
        info = editor.get_component_info(ref)

        # Rotation enum to string (e.g. ERotation.R0 -> "R0")
        rotation_str = ASC_INV_ROTATION_DICT.get(rot, str(rot))

        # Symbol name from component attributes or reference prefix
        symbol = getattr(comp, "name", "") or ""
        if not symbol:
            # Fallback: derive from reference prefix
            symbol = _symbol_from_ref(ref)

        # Prefix from reference designator
        prefix = _prefix_from_ref(ref)

        # Extract extra parameters from info dict
        params_list: list[tuple[str, str]] = []
        if info:
            for k, v in info.items():
                if k not in ("Value", "InstName"):
                    params_list.append((str(k), str(v)))

        components.append(
            LTspiceComponent(
                reference=ref,
                symbol=symbol,
                value=value,
                position_x=int(pos.X),
                position_y=int(pos.Y),
                rotation=rotation_str,
                prefix=prefix,
                parameters=tuple(params_list),
            )
        )

    # Extract wires
    wires: list[LTspiceWire] = []
    for wire in editor.wires:
        wires.append(
            LTspiceWire(
                x1=int(wire.V1.X),
                y1=int(wire.V1.Y),
                x2=int(wire.V2.X),
                y2=int(wire.V2.Y),
            )
        )

    # Extract flags (net labels)
    flags: list[LTspiceFlag] = []
    for label in editor.labels:
        flags.append(
            LTspiceFlag(
                x=int(label.coord.X),
                y=int(label.coord.Y),
                text=label.text,
            )
        )

    # Extract directives
    directives: list[LTspiceDirective] = []
    sim_commands: list = []
    for directive in editor.directives:
        dir_type = "DIRECTIVE" if directive.type == TextTypeEnum.DIRECTIVE else "COMMENT"
        directives.append(
            LTspiceDirective(
                text=directive.text,
                directive_type=dir_type,
            )
        )
        # Attempt to parse simulation commands from directive text
        parsed_cmd = parse_simulation_command(directive.text)
        if parsed_cmd is not None:
            sim_commands.append(parsed_cmd)

    return LTspiceSchematic(
        components=tuple(components),
        wires=tuple(wires),
        flags=tuple(flags),
        directives=tuple(directives),
        source_path=str(resolved),
        simulation_commands=tuple(sim_commands),
    )


def _prefix_from_ref(ref: str) -> str:
    """Extract the prefix letter from a component reference.

    Example: "R1" -> "R", "C10" -> "C", "V1" -> "V".
    """
    for i, ch in enumerate(ref):
        if ch.isdigit():
            return ref[:i] if i > 0 else ref
    return ref


def _symbol_from_ref(ref: str) -> str:
    """Derive a symbol name from a component reference.

    Maps common prefixes to symbol names. Used as fallback when
    SpiceLib does not provide a symbol name.
    """
    prefix_map = {
        "R": "res",
        "C": "cap",
        "L": "ind",
        "V": "voltage",
        "I": "current",
        "D": "diode",
        "Q": "npn",
        "M": "nmos",
        "X": "opamp",
        "G": "gnd",
    }
    prefix = _prefix_from_ref(ref)
    return prefix_map.get(prefix, prefix.lower())
