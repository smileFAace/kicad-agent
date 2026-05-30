"""Parse KiCad sub-sheet .kicad_sch files into a connectivity graph.

Extracts:
  - Wires with endpoints
  - Symbol pin positions (absolute, including wire-end point)
  - Labels (global, local, hierarchical)
  - Junctions
  - Symbol reference → lib_id mapping

This is the foundation for net resolution: tracing a wire endpoint through
connected wires/labels/pins to determine its net name.

Usage:
    from kicad_agent.schematic_routing.schematic_graph import SchematicGraph

    graph = SchematicGraph.from_file("eq-stage.kicad_sch")
    targets = graph.get_connection_targets()
    net = graph.trace_endpoint_to_net((148.59, 111.76), pin_index)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from kicad_agent.schematic_routing.netlist_parser import parse_netlist


Pos = tuple[float, float]  # (x_mm, y_mm)


@dataclass
class Wire:
    """A schematic wire segment."""
    start: Pos
    end: Pos
    file_offset: int = 0  # byte offset in file for targeted replacement
    length: int = 0  # byte length of the wire S-expression


@dataclass
class PinPosition:
    """Absolute position of a symbol pin's wire connection point."""
    ref: str
    pin_number: str
    pin_name: str
    position: Pos  # wire connection point (body + length in pin direction)
    body_position: Pos  # pin body position (for label placement)


@dataclass
class Label:
    """A net label at a position."""
    name: str
    position: Pos
    label_type: str  # "global", "local", "hierarchical"


@dataclass
class SchematicGraph:
    """Parsed connectivity elements from a .kicad_sch file."""

    filepath: str = ""
    wires: list[Wire] = field(default_factory=list)
    pins: list[PinPosition] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    junctions: set[Pos] = field(default_factory=set)
    ref_to_libid: dict[str, str] = field(default_factory=dict)

    # Derived indexes
    _pin_pos_index: dict[Pos, PinPosition] = field(default_factory=dict, repr=False)
    _label_pos_index: dict[Pos, Label] = field(default_factory=dict, repr=False)
    _wire_endpoint_index: dict[Pos, list[Wire]] = field(default_factory=dict, repr=False)

    @classmethod
    def from_file(cls, filepath: str | Path) -> SchematicGraph:
        """Parse a .kicad_sch file into a SchematicGraph."""
        filepath = str(filepath)
        content = Path(filepath).read_text()
        graph = cls(filepath=filepath)

        lib_start, lib_end = _find_lib_symbols_range(content)
        if lib_start == lib_end:
            return graph

        lib_section = content[lib_start:lib_end]
        body = content[lib_end:]

        # Parse lib symbols for pin geometry
        lib_symbols = _parse_lib_pins(lib_section)

        # Parse wires
        graph.wires = _parse_wires(body)
        graph._build_wire_endpoint_index()

        # Parse placed symbols and compute pin positions
        graph.pins = _parse_symbol_pins(body, lib_symbols)
        graph.ref_to_libid = _parse_symbol_refs(body)

        # Build pin position index
        for pin in graph.pins:
            graph._pin_pos_index[_round_pos(pin.position)] = pin

        # Parse labels
        graph.labels = _parse_labels(body)
        for label in graph.labels:
            graph._label_pos_index[_round_pos(label.position)] = label

        # Parse junctions
        graph.junctions = _parse_junctions(body)

        return graph

    def _build_wire_endpoint_index(self) -> None:
        """Index wire endpoints for fast lookup."""
        for wire in self.wires:
            for ep in (wire.start, wire.end):
                key = _round_pos(ep)
                self._wire_endpoint_index.setdefault(key, []).append(wire)

    def get_connection_targets(self) -> set[Pos]:
        """Get all positions where a wire endpoint could legally connect."""
        targets = set()
        for pin in self.pins:
            targets.add(_round_pos(pin.position))
        for label in self.labels:
            targets.add(_round_pos(label.position))
        for junc in self.junctions:
            targets.add(_round_pos(junc))
        return targets

    def is_connected(self, pos: Pos) -> bool:
        """Check if a position is already connected to something."""
        key = _round_pos(pos)
        if key in self._pin_pos_index:
            return True
        if key in self._label_pos_index:
            return True
        if key in self.junctions:
            return True
        # Shared wire endpoint (junction-like)
        if len(self._wire_endpoint_index.get(key, [])) > 1:
            return True
        return False

    def trace_endpoint_to_net(
        self,
        endpoint: Pos,
        pin_index: dict[tuple[str, str], str],
    ) -> Optional[str]:
        """Trace a dangling wire endpoint to its net name.

        Strategy:
        1. Find the wire containing this endpoint
        2. Look at the OTHER endpoint (the connected end)
        3. If connected end is on a label → net = label name
        4. If connected end is on a pin → lookup (ref, pin) in pin_index
        5. If connected end is a junction (shared by multiple wires) → BFS
        """
        key = _round_pos(endpoint)

        # Find all wires touching this endpoint
        touching_wires = self._wire_endpoint_index.get(key, [])
        if not touching_wires:
            return None

        for wire in touching_wires:
            # Get the OTHER endpoint
            other = _round_pos(wire.end if key == _round_pos(wire.start) else wire.start)
            net = self._resolve_position(other, pin_index, visited=set())
            if net:
                return net

        return None

    def _resolve_position(
        self,
        pos: Pos,
        pin_index: dict[tuple[str, str], str],
        visited: set[Pos],
    ) -> Optional[str]:
        """Resolve a position to a net name, with BFS for junctions.

        Uses proximity matching (within 1.27mm) for pins and labels,
        since KiCad considers wires connected if they touch within this radius.
        """
        if pos in visited:
            return None
        visited.add(pos)

        # Check if on a label (exact then proximity)
        label = self._label_pos_index.get(pos)
        if not label:
            label = self._find_nearby_label(pos, tolerance=1.27)
        if label:
            return label.name

        # Check if on a pin (exact then proximity)
        pin = self._pin_pos_index.get(pos)
        if not pin:
            pin = self._find_nearby_pin(pos, tolerance=1.27)
        if pin:
            net = pin_index.get((pin.ref, pin.pin_number))
            if net:
                return net

        # BFS through connected wires (junction)
        touching = self._wire_endpoint_index.get(pos, [])
        for wire in touching:
            other = _round_pos(wire.end if pos == _round_pos(wire.start) else wire.start)
            net = self._resolve_position(other, pin_index, visited)
            if net:
                return net

        return None

    def _find_nearby_pin(self, pos: Pos, tolerance: float = 1.27) -> Optional[PinPosition]:
        """Find a pin whose wire connection point is within tolerance of pos."""
        for pin in self.pins:
            pin_pos = _round_pos(pin.position)
            d = ((pin_pos[0] - pos[0]) ** 2 + (pin_pos[1] - pos[1]) ** 2) ** 0.5
            if d <= tolerance:
                return pin
        return None

    def _find_nearby_label(self, pos: Pos, tolerance: float = 1.27) -> Optional[Label]:
        """Find a label whose position is within tolerance of pos."""
        for label in self.labels:
            label_pos = _round_pos(label.position)
            d = ((label_pos[0] - pos[0]) ** 2 + (label_pos[1] - pos[1]) ** 2) ** 0.5
            if d <= tolerance:
                return label
        return None

    def get_sheet_refs(self) -> set[str]:
        """Get all component references in this sheet."""
        return set(self.ref_to_libid.keys())

    def find_wire_at(self, endpoint: Pos) -> Optional[Wire]:
        """Find the wire that has this position as an endpoint."""
        key = _round_pos(endpoint)
        for wire in self._wire_endpoint_index.get(key, []):
            if _round_pos(wire.start) == key or _round_pos(wire.end) == key:
                return wire
        return None


def _round_pos(pos: Pos) -> Pos:
    """Round position to 2 decimal places for consistent comparison."""
    return (round(pos[0], 2), round(pos[1], 2))


def _find_lib_symbols_range(content: str) -> tuple[int, int]:
    """Return (start, end) byte offsets of the (lib_symbols ...) block."""
    pos = content.find("(lib_symbols")
    if pos < 0:
        return 0, 0
    depth = 0
    for i in range(pos, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return pos, i + 1
    return pos, len(content)


def _parse_lib_pins(lib_section: str) -> dict[str, list[tuple]]:
    """Extract pin data from lib_symbols section.

    Returns: {symbol_name: [(type, px, py, angle, length, pin_name, pin_number), ...]}
    """
    symbols: dict[str, list[tuple]] = {}
    for sym_match in re.finditer(r'\(symbol\s+"([^"]+)"', lib_section):
        sym_name = sym_match.group(1)
        sym_start = sym_match.start()
        # Find end of this symbol block
        depth = 0
        sym_end = sym_start
        for i in range(sym_start, len(lib_section)):
            if lib_section[i] == "(":
                depth += 1
            elif lib_section[i] == ")":
                depth -= 1
                if depth == 0:
                    sym_end = i + 1
                    break

        sym_block = lib_section[sym_start:sym_end]
        # Parse pins: (pin <type> <shape> (at X Y ANGLE) (length L) (name "N") ... (number "N"))
        pins = re.findall(
            r'\(pin\s+(\w+)\s+\w+\s+\(at\s+([\d.-]+)\s+([\d.-]+)\s+(\d+)\)\s+'
            r'\(length\s+([\d.]+)\)\s+\(name\s+"([^"]*)"[\s\S]*?\(number\s+"(\d+)"',
            sym_block,
        )
        if pins:
            symbols[sym_name] = [
                (p[0], float(p[1]), float(p[2]), float(p[3]), float(p[4]), p[5], p[6])
                for p in pins
            ]
    return symbols


def _parse_wires(body: str) -> list[Wire]:
    """Parse wire segments from schematic body."""
    wires = []
    # KiCad wire format is multi-line:
    # (wire (pts (xy X1 Y1) (xy X2 Y2)) ...)
    pattern = re.compile(
        r'\(wire\s+\(pts\s+\(xy\s+([\d.]+)\s+([\d.]+)\)\s+\(xy\s+([\d.]+)\s+([\d.]+)\)'
    )
    for m in pattern.finditer(body):
        wire = Wire(
            start=(float(m.group(1)), float(m.group(2))),
            end=(float(m.group(3)), float(m.group(4))),
            file_offset=m.start(),
            length=m.end() - m.start(),
        )
        wires.append(wire)
    return wires


def _parse_symbol_pins(body: str, lib_symbols: dict[str, list[tuple]]) -> list[PinPosition]:
    """Parse placed symbols and compute absolute pin wire-end positions."""
    pins = []
    for sym_match in re.finditer(
        r'\(symbol\s+\(lib_id\s+"([^"]+)"\)\s+\(at\s+([\d.]+)\s+([\d.]+)\s+([\d.-]+)\)',
        body,
    ):
        lib_id = sym_match.group(1)
        sx, sy, sa = float(sym_match.group(2)), float(sym_match.group(3)), float(sym_match.group(4))

        # Get reference designator from the same symbol block
        sym_start = sym_match.start()
        # Find end of this symbol instance
        depth = 0
        sym_end = sym_start
        for i in range(sym_start, len(body)):
            if body[i] == "(":
                depth += 1
            elif body[i] == ")":
                depth -= 1
                if depth == 0:
                    sym_end = i + 1
                    break

        sym_block = body[sym_start:sym_end]

        # Extract reference
        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', sym_block)
        if not ref_match:
            continue
        ref = ref_match.group(1)
        # Skip power symbols (refs like #PWR01, #FLG01)
        if ref.startswith("#"):
            continue

        # Find matching lib symbol definition
        lib_pins = lib_symbols.get(lib_id)
        if not lib_pins:
            # Try matching by short name (after colon)
            short_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id
            for k in lib_symbols:
                if k.split(":")[-1] == short_name or k == short_name:
                    lib_pins = lib_symbols[k]
                    break
        if not lib_pins:
            continue

        # Calculate absolute pin positions
        rad = math.radians(sa)
        cos_a, sin_a = math.cos(rad), math.sin(rad)

        for pin_data in lib_pins:
            _, px, py, pa, pl, pin_name, pin_number = pin_data

            # Rotate pin offset by symbol angle
            rot_px = px * cos_a - py * sin_a
            rot_py = px * sin_a + py * cos_a

            # Absolute body position
            body_x = round(sx + rot_px, 2)
            body_y = round(sy + rot_py, 2)

            # Wire connection point extends from body by pin_length in pin direction
            total_angle = pa + sa
            end_rad = math.radians(total_angle)
            wire_x = round(body_x + pl * math.cos(end_rad), 2)
            wire_y = round(body_y + pl * math.sin(end_rad), 2)

            pins.append(PinPosition(
                ref=ref,
                pin_number=pin_number,
                pin_name=pin_name,
                position=(wire_x, wire_y),
                body_position=(body_x, body_y),
            ))

    return pins


def _parse_symbol_refs(body: str) -> dict[str, str]:
    """Parse symbol reference → lib_id mapping."""
    refs = {}
    for sym_match in re.finditer(
        r'\(symbol\s+\(lib_id\s+"([^"]+)"\)\s+\(at\s+[\d.]+\s+[\d.]+\s+[\d.-]+\)',
        body,
    ):
        lib_id = sym_match.group(1)
        sym_start = sym_match.start()
        depth = 0
        sym_end = sym_start
        for i in range(sym_start, len(body)):
            if body[i] == "(":
                depth += 1
            elif body[i] == ")":
                depth -= 1
                if depth == 0:
                    sym_end = i + 1
                    break

        sym_block = body[sym_start:sym_end]
        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', sym_block)
        if ref_match:
            ref = ref_match.group(1)
            if not ref.startswith("#"):
                refs[ref] = lib_id
    return refs


def _parse_labels(body: str) -> list[Label]:
    """Parse all labels from schematic body."""
    labels = []

    # Global labels: (global_label "NAME" ... (at X Y ANGLE))
    for m in re.finditer(r'\(global_label\s+"([^"]+)"[\s\S]*?\(at\s+([\d.]+)\s+([\d.]+)', body):
        labels.append(Label(
            name=m.group(1),
            position=(float(m.group(2)), float(m.group(3))),
            label_type="global",
        ))

    # Local labels: (label "NAME" ... (at X Y ANGLE))
    for m in re.finditer(r'\(label\s+"([^"]+)"[\s\S]*?\(at\s+([\d.]+)\s+([\d.]+)', body):
        # Skip if this is actually a global_label or hierarchical_label (they're matched above)
        match_start = m.start()
        # Check the character before to ensure it's a standalone (label not (global_label
        prefix = body[max(0, match_start - 10):match_start]
        if "global_label" in prefix or "hierarchical_label" in prefix:
            continue
        labels.append(Label(
            name=m.group(1),
            position=(float(m.group(2)), float(m.group(3))),
            label_type="local",
        ))

    # Hierarchical labels: (hierarchical_label "NAME" ... (at X Y ANGLE))
    for m in re.finditer(r'\(hierarchical_label\s+"([^"]+)"[\s\S]*?\(at\s+([\d.]+)\s+([\d.]+)', body):
        labels.append(Label(
            name=m.group(1),
            position=(float(m.group(2)), float(m.group(3))),
            label_type="hierarchical",
        ))

    return labels


def _parse_junctions(body: str) -> set[Pos]:
    """Parse junction positions."""
    junctions = set()
    for m in re.finditer(r'\(junction\s+\(at\s+([\d.]+)\s+([\d.]+)\)', body):
        junctions.add((round(float(m.group(1)), 2), round(float(m.group(2)), 2)))
    return junctions
