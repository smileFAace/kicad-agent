"""Frozen dataclass types for LTspice .asc schematic parsing.

Provides immutable, hashable data structures representing components,
wires, flags, directives, and the top-level schematic parsed from
LTspice .asc files via SpiceLib AscEditor.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LTspiceComponent:
    """A parsed component from an LTspice .asc schematic.

    Attributes:
        reference: Component reference designator (e.g. "R1", "C1").
        symbol: Symbol name from .asy file (e.g. "res", "cap").
        value: Component value string (e.g. "1k", "100n").
        position_x: X coordinate in LTspice internal units.
        position_y: Y coordinate in LTspice internal units.
        rotation: Rotation string (e.g. "R0", "R90", "M0").
        prefix: Component prefix letter (e.g. "R", "C", "L").
        parameters: Additional parameters as immutable tuple of (key, value) pairs.
    """

    reference: str
    symbol: str
    value: str
    position_x: int
    position_y: int
    rotation: str
    prefix: str
    parameters: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class LTspiceWire:
    """A wire segment connecting two points in an LTspice schematic.

    Attributes:
        x1: Start X coordinate in LTspice internal units.
        y1: Start Y coordinate in LTspice internal units.
        x2: End X coordinate in LTspice internal units.
        y2: End Y coordinate in LTspice internal units.
    """

    x1: int
    y1: int
    x2: int
    y2: int


@dataclass(frozen=True)
class LTspiceFlag:
    """A net label (flag) placed at a coordinate in an LTspice schematic.

    Attributes:
        x: X coordinate in LTspice internal units.
        y: Y coordinate in LTspice internal units.
        text: Net label text (e.g. "0" for GND, "VCC").
    """

    x: int
    y: int
    text: str


@dataclass(frozen=True)
class LTspiceDirective:
    """A text directive or comment in an LTspice schematic.

    Attributes:
        text: The directive text content (e.g. ".tran 0 1ms 0 1u").
        directive_type: Either "DIRECTIVE" or "COMMENT".
    """

    text: str
    directive_type: str


@dataclass(frozen=True)
class LTspiceSchematic:
    """Top-level parsed result from an LTspice .asc schematic file.

    All collections are immutable tuples for frozen dataclass compatibility.

    Attributes:
        components: Parsed components as an immutable tuple.
        wires: Wire segments as an immutable tuple.
        flags: Net labels/flags as an immutable tuple.
        directives: Text directives as an immutable tuple.
        simulation_commands: Parsed simulation commands (populated in plan 02).
        source_path: Absolute path to the source .asc file.
    """

    components: tuple[LTspiceComponent, ...]
    wires: tuple[LTspiceWire, ...]
    flags: tuple[LTspiceFlag, ...]
    directives: tuple[LTspiceDirective, ...]
    source_path: str
    simulation_commands: tuple = ()  # Updated in Task 2
