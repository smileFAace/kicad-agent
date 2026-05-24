"""KiCad schematic to LTspice .asc file writer.

Converts a kiutils Schematic into a valid LTspice .asc file using SpiceLib
AscEditor for output. Handles coordinate transformation (KiCad mm to LTspice
internal units with Y-axis flip), symbol mapping, and net label translation.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from spicelib import AscEditor
from spicelib.editor.asc_editor import ASC_ROTATION_DICT, Text, TextTypeEnum
from spicelib.editor.asc_editor import asc_text_align_set
from spicelib.editor.base_schematic import ERotation, Line, Point, SchematicComponent

from kicad_agent.ltspice.asc_parser import ASY_STUBS_DIR
from kicad_agent.ltspice.sim_commands import SimulationCommand, serialize_sim_command
from kicad_agent.ltspice.symbol_mapper import SymbolMapper

logger = logging.getLogger(__name__)

_MINIMAL_ASC_TEMPLATE = """Version 4
SHEET 1 880 680
"""


@dataclass(frozen=True)
class CoordinateTransformer:
    """Convert KiCad mm coordinates to LTspice internal units.

    KiCad uses mm with Y increasing downward (screen coordinates).
    LTspice uses internal units with Y increasing upward (math coords).
    Default scale: 16 LTspice units per mm.
    Grid alignment: all outputs rounded to multiples of 16.
    """

    scale: int = 16
    sheet_height_mm: float = 297.0  # A4 height

    def mm_to_ltspice(
        self, kicad_x_mm: float, kicad_y_mm: float
    ) -> tuple[int, int]:
        """Transform KiCad mm coordinates to LTspice internal units.

        Args:
            kicad_x_mm: X coordinate in mm (KiCad convention).
            kicad_y_mm: Y coordinate in mm (KiCad convention, down = positive).

        Returns:
            Tuple of (ltspice_x, ltspice_y) aligned to 16-unit grid.
        """
        raw_x = kicad_x_mm * self.scale
        raw_y = (self.sheet_height_mm - kicad_y_mm) * self.scale
        ltspice_x = int(round(raw_x / 16)) * 16
        ltspice_y = int(round(raw_y / 16)) * 16
        return (ltspice_x, ltspice_y)


def _sanitize_net_name(text: str) -> str:
    """Clean a KiCad net name for LTspice FLAG usage.

    Strips leading "/" used by KiCad hierarchical labels and decodes
    the "{slash}" token back to "/".

    Args:
        text: Raw KiCad net label text.

    Returns:
        Sanitized net name suitable for LTspice FLAG.
    """
    # Strip whitespace first so leading slash detection works on padded input
    text = text.strip()
    # Strip leading slash (KiCad hierarchical prefix)
    if text.startswith("/"):
        text = text[1:]
    # Decode {slash} token back to /
    text = text.replace("{slash}", "/")
    return text


def _rotation_from_kicad(angle: float | None, mirror: str | None) -> ERotation:
    """Map KiCad rotation angle and mirror to LTspice ERotation.

    Args:
        angle: KiCad rotation angle (0, 90, 180, 270). None treated as 0.
        mirror: KiCad mirror specifier (e.g. "x", "y"). None = no mirror.

    Returns:
        ERotation enum value for LTspice.
    """
    if angle is None:
        angle = 0.0
    # Normalize angle to nearest 90
    angle_rounded = int(round(angle / 90.0)) * 90
    angle_rounded = angle_rounded % 360

    is_mirrored = mirror is not None
    rotation_key = f"M{angle_rounded}" if is_mirrored else f"R{angle_rounded}"

    return ASC_ROTATION_DICT.get(rotation_key, ERotation.R0)


class AscWriter:
    """Convert a KiCad schematic to LTspice .asc format.

    Iterates over KiCad schematic symbols, wires, and labels, translating
    each to the corresponding LTspice representation via SymbolMapper and
    CoordinateTransformer.
    """

    def __init__(
        self,
        schematic,
        symbol_mapper: SymbolMapper,
        coordinate_transformer: CoordinateTransformer,
        simulation_commands: Sequence[SimulationCommand] = (),
    ) -> None:
        """Initialize the writer.

        Args:
            schematic: A kiutils Schematic object.
            symbol_mapper: SymbolMapper for KiCad->LTspice symbol translation.
            coordinate_transformer: CoordinateTransformer for mm->internal units.
            simulation_commands: Simulation commands to inject as directives.
        """
        self._schematic = schematic
        self._mapper = symbol_mapper
        self._transformer = coordinate_transformer
        self._sim_commands = list(simulation_commands)

    def write(self, output_path: str | Path) -> Path:
        """Export the KiCad schematic to an LTspice .asc file.

        Args:
            output_path: Destination path for the .asc file.

        Returns:
            Path to the written .asc file.

        Raises:
            ValueError: If output_path contains traversal sequences.
        """
        output = Path(output_path).resolve()
        # Path traversal protection (same pattern as asc_parser._validate_path)
        parts = Path(output_path).parts
        if ".." in parts:
            raise ValueError(
                f"Output path contains traversal sequences: {output_path}"
            )

        # Configure bundled .asy stubs for symbol resolution
        AscEditor.set_custom_library_paths(str(ASY_STUBS_DIR))

        template_path: str | None = None
        try:
            # Create minimal template in temp file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".asc", delete=False
            ) as tmp:
                tmp.write(_MINIMAL_ASC_TEMPLATE)
                template_path = tmp.name

            editor = AscEditor(template_path)

            # Process schematic symbols
            self._write_components(editor)

            # Process wires (Connection graphical items)
            self._write_wires(editor)

            # Process net labels
            self._write_labels(editor)

            # Inject simulation commands as directives
            self._write_sim_commands(editor)

            # Save output
            editor.save_netlist(str(output))

        finally:
            # Clean up temp file
            if template_path is not None:
                try:
                    Path(template_path).unlink()
                except OSError:
                    pass

        return output

    def _write_components(self, editor: AscEditor) -> None:
        """Map KiCad symbols to LTspice components and flags."""
        for sym in self._schematic.schematicSymbols:
            lib_id = sym.libId
            mapping = self._mapper.map_symbol(lib_id)

            # Extract position from KiCad symbol
            kicad_x = sym.position.X
            kicad_y = sym.position.Y
            lt_x, lt_y = self._transformer.mm_to_ltspice(kicad_x, kicad_y)

            if mapping.mapping_type == "component":
                self._add_component(editor, sym, mapping.ltspice_symbol, lt_x, lt_y)
            elif mapping.mapping_type == "flag":
                self._add_flag(editor, lt_x, lt_y, mapping.ltspice_symbol)
            else:
                logger.warning(
                    "Skipping unmapped symbol %s (libId: %s)",
                    getattr(sym, "libId", "unknown"),
                    lib_id,
                )

    def _add_component(
        self,
        editor: AscEditor,
        sym,
        ltspice_symbol: str,
        lt_x: int,
        lt_y: int,
    ) -> None:
        """Add a single LTspice component from a KiCad symbol."""
        # Extract reference and value from symbol properties
        reference = self._get_property(sym, "Reference", "U?")
        value = self._get_property(sym, "Value", "")

        comp = SchematicComponent(editor, "")
        comp.reference = reference
        comp.symbol = ltspice_symbol
        comp.position = Point(lt_x, lt_y)
        comp.rotation = _rotation_from_kicad(
            sym.position.angle, sym.mirror
        )
        if value:
            comp.attributes["Value"] = value

        editor.add_component(comp)

    def _add_flag(
        self,
        editor: AscEditor,
        lt_x: int,
        lt_y: int,
        flag_text: str,
    ) -> None:
        """Add a FLAG (net label) entry."""
        editor.labels.append(
            Text(
                coord=Point(lt_x, lt_y),
                text=flag_text,
                size=2,
                type=TextTypeEnum.LABEL,
            )
        )

    def _write_wires(self, editor: AscEditor) -> None:
        """Convert KiCad Connection items to LTspice wires."""
        for item in self._schematic.graphicalItems:
            # Only process Connection (wire) items
            if not hasattr(item, "points"):
                continue
            if not hasattr(item, "type"):
                continue
            if item.type != "wire":
                continue

            points = item.points
            # A wire needs at least 2 points
            if len(points) < 2:
                continue

            # Each consecutive pair of points forms a wire segment
            for i in range(len(points) - 1):
                p1 = points[i]
                p2 = points[i + 1]
                lt_x1, lt_y1 = self._transformer.mm_to_ltspice(p1.X, p1.Y)
                lt_x2, lt_y2 = self._transformer.mm_to_ltspice(p2.X, p2.Y)
                editor.wires.append(Line(Point(lt_x1, lt_y1), Point(lt_x2, lt_y2)))

    def _write_labels(self, editor: AscEditor) -> None:
        """Convert KiCad labels and globalLabels to LTspice FLAGs."""
        # Local labels
        for label in self._schematic.labels:
            text = _sanitize_net_name(label.text)
            if not text:
                continue
            lt_x, lt_y = self._transformer.mm_to_ltspice(
                label.position.X, label.position.Y
            )
            self._add_flag(editor, lt_x, lt_y, text)

        # Global labels
        for label in self._schematic.globalLabels:
            text = _sanitize_net_name(label.text)
            if not text:
                continue
            lt_x, lt_y = self._transformer.mm_to_ltspice(
                label.position.X, label.position.Y
            )
            self._add_flag(editor, lt_x, lt_y, text)

    def _write_sim_commands(self, editor: AscEditor) -> None:
        """Inject simulation commands as LTspice TEXT directives."""
        for cmd in self._sim_commands:
            directive_text = serialize_sim_command(cmd)
            d = Text(
                coord=Point(384, 48),
                text=directive_text,
                size=2,
                type=TextTypeEnum.DIRECTIVE,
            )
            d = asc_text_align_set(d, "Left")
            editor.directives.append(d)

    def add_simulation_command(self, cmd: SimulationCommand) -> None:
        """Add a simulation command to be injected during write().

        Args:
            cmd: A SimulationCommand dataclass to serialize as a directive.
        """
        self._sim_commands.append(cmd)

    @staticmethod
    def _get_property(sym, key: str, default: str = "") -> str:
        """Extract a property value from a KiCad symbol.

        Args:
            sym: kiutils SchematicSymbol.
            key: Property key (e.g. "Reference", "Value").
            default: Default value if property not found.

        Returns:
            Property value string.
        """
        for prop in sym.properties:
            if prop.key == key:
                return prop.value
        return default


def export_schematic_to_asc(
    kicad_sch_path: str | Path,
    output_path: str | Path,
    custom_mappings: dict[str, str] | None = None,
) -> Path:
    """Export a KiCad schematic to LTspice .asc format.

    Convenience function that loads the KiCad schematic, creates a
    SymbolMapper and CoordinateTransformer, and delegates to AscWriter.

    Args:
        kicad_sch_path: Path to .kicad_sch file.
        output_path: Path for output .asc file.
        custom_mappings: Optional custom symbol mappings.

    Returns:
        Path to the written .asc file.
    """
    # Lazy import to match project pattern for optional dependencies
    from kiutils.schematic import Schematic  # noqa: F811

    schematic = Schematic.from_file(str(kicad_sch_path))
    mapper = SymbolMapper(custom_mappings=custom_mappings)
    transformer = CoordinateTransformer()
    writer = AscWriter(schematic, mapper, transformer)
    return writer.write(output_path)
