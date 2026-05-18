"""Schematic IR -- thin wrapper over a kiutils Schematic object with mutation tracking.

D-05: Holds reference to kiutils Schematic (not a copy).
D-06: Tracks mutations, dirty flag.
D-07: Schematic-specific IR.

Usage:
    from kicad_agent.ir.schematic_ir import SchematicIR
    from kicad_agent.parser import parse_schematic

    result = parse_schematic(Path("my_schematic.kicad_sch"))
    ir = SchematicIR(_parse_result=result)
    component = ir.get_component_by_ref("U1")
"""

from dataclasses import dataclass
from typing import Any, Optional

from kiutils.schematic import Schematic

from kicad_agent.ir.base import BaseIR
from kicad_agent.parser.types import ParseResult
from kicad_agent.parser.uuid_extractor import UUIDMap


@dataclass
class SchematicIR(BaseIR):
    """Thin wrapper over a kiutils Schematic object with mutation tracking.

    D-05: Holds reference to kiutils Schematic (not a copy).
    D-06: Tracks mutations, dirty flag.
    D-07: Schematic-specific IR.
    """

    def __post_init__(self) -> None:
        """Validate file type matches schematic."""
        super().__post_init__()
        if self.file_type != "schematic":
            raise ValueError(
                f"Expected file_type='schematic', got {self.file_type!r}"
            )

    @property
    def schematic(self) -> Schematic:
        """Direct access to the kiutils Schematic object."""
        return self._parse_result.kiutils_obj

    @property
    def components(self) -> list:
        """Access to schematic symbols (components)."""
        return self._parse_result.kiutils_obj.schematicSymbols

    def get_component_by_ref(self, reference: str) -> Optional[Any]:
        """Find a component by its reference designator.

        Args:
            reference: The reference designator to search for (e.g. "U1", "R3").

        Returns:
            The matching kiutils SchematicSymbol, or None if not found.
        """
        for sym in self._parse_result.kiutils_obj.schematicSymbols:
            for prop in sym.properties:
                if prop.key == "Reference" and prop.value == reference:
                    return sym
        return None

    def get_component_property(self, component: Any, property_key: str) -> Optional[str]:
        """Get a specific property value from a component.

        Args:
            component: A kiutils SchematicSymbol object.
            property_key: The property key to look up (e.g. "Reference", "Value").

        Returns:
            The property value string, or None if not found.
        """
        for prop in component.properties:
            if prop.key == property_key:
                return prop.value
        return None

    def get_labels_by_name(self, name: str) -> list:
        """Find all local labels with matching text.

        Args:
            name: Label text to search for.

        Returns:
            List of kiutils LocalLabel objects with text matching the name.
        """
        return [
            label
            for label in self._parse_result.kiutils_obj.labels
            if label.text == name
        ]

    @property
    def bus_aliases(self) -> list:
        """Access to schematic bus aliases (KiCad 10+)."""
        return self._parse_result.kiutils_obj.busAliases
