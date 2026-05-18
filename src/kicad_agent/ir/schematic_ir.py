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

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Optional

from kiutils.schematic import Schematic

from kicad_agent.ir.base import BaseIR
from kicad_agent.parser.types import ParseResult
from kicad_agent.parser.uuid_extractor import UUIDMap

# Regex for parsing reference designators: prefix (alpha + optional #) + numeric suffix or '?'
_REF_PATTERN = re.compile(r"^([#A-Za-z]+)(\d+|\?)$")


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

    def get_all_references(self) -> list[tuple[str, str]]:
        """Get all (reference, libId) pairs from schematic symbols.

        Returns:
            List of (reference, libId) tuples for every component.
        """
        result: list[tuple[str, str]] = []
        for sym in self._parse_result.kiutils_obj.schematicSymbols:
            ref = self.get_component_property(sym, "Reference")
            if ref is None:
                ref = ""
            result.append((ref, sym.libId))
        return result

    def _set_component_reference(self, component: Any, new_ref: str) -> None:
        """Update the Reference property on a schematic symbol.

        Args:
            component: A kiutils SchematicSymbol.
            new_ref: The new reference designator string.
        """
        for prop in component.properties:
            if prop.key == "Reference":
                prop.value = new_ref
                return

    def renumber_references(
        self, prefix: str = "", start_index: int = 1, step: int = 1
    ) -> list[tuple[str, str]]:
        """Renumber component references with configurable prefix and sequencing.

        Args:
            prefix: Only renumber components with this prefix (e.g. "R", "U").
                    Empty string means renumber all components, grouped by prefix.
            start_index: Starting index for numbering (default 1).
            step: Step between indices (default 1).

        Returns:
            List of (old_ref, new_ref) tuples showing what changed.
        """
        all_refs = self.get_all_references()
        components = self._parse_result.kiutils_obj.schematicSymbols

        # Parse refs into (prefix, numeric_suffix) pairs, skipping unannotated
        parsed: list[tuple[str, int, Any]] = []
        for i, (ref, _lib_id) in enumerate(all_refs):
            m = _REF_PATTERN.match(ref)
            if m and m.group(2) != "?":
                parsed.append((m.group(1), int(m.group(2)), components[i]))

        # Group by prefix
        groups: dict[str, list[tuple[int, Any]]] = {}
        for ref_prefix, num, comp in parsed:
            groups.setdefault(ref_prefix, []).append((num, comp))

        # Filter to target prefix if specified
        if prefix:
            groups = {k: v for k, v in groups.items() if k == prefix}

        changes: list[tuple[str, str]] = []
        for grp_prefix, members in groups.items():
            # Sort by current numeric suffix
            members.sort(key=lambda x: x[0])
            for idx, (old_num, comp) in enumerate(members):
                new_num = start_index + idx * step
                old_ref = f"{grp_prefix}{old_num}"
                new_ref = f"{grp_prefix}{new_num}"
                if old_ref != new_ref:
                    self._set_component_reference(comp, new_ref)
                    self._record_mutation(
                        "renumber_reference",
                        {"old_ref": old_ref, "new_ref": new_ref},
                    )
                    changes.append((old_ref, new_ref))

        return changes

    def validate_reference_uniqueness(self) -> list[str]:
        """Check that all references are unique.

        Returns:
            List of reference strings that appear more than once. Empty if all unique.
        """
        all_refs = self.get_all_references()
        ref_strs = [r for r, _ in all_refs]
        counts = Counter(ref_strs)
        return [ref for ref, count in counts.items() if count > 1]

    def annotate_components(self, prefix_filter: str = "") -> list[tuple[str, str]]:
        """Auto-assign references to unannotated components (refs ending in '?').

        Args:
            prefix_filter: Only annotate components with this prefix (e.g. "R").
                           Empty string means annotate all unannotated.

        Returns:
            List of (old_ref, new_ref) tuples showing what was annotated.
        """
        all_refs = self.get_all_references()
        components = self._parse_result.kiutils_obj.schematicSymbols

        # Find unannotated refs (ending in '?')
        unannotated: list[tuple[str, Any]] = []
        for i, (ref, _lib_id) in enumerate(all_refs):
            if ref.endswith("?"):
                unannotated.append((ref, components[i]))

        # Apply prefix filter
        if prefix_filter:
            unannotated = [
                (ref, comp)
                for ref, comp in unannotated
                if ref.startswith(prefix_filter)
            ]

        if not unannotated:
            return []

        # Find max existing numeric suffix per prefix across all annotated refs
        max_per_prefix: dict[str, int] = {}
        for ref, _ in all_refs:
            m = _REF_PATTERN.match(ref)
            if m and m.group(2) != "?":
                max_per_prefix[m.group(1)] = max(
                    max_per_prefix.get(m.group(1), 0), int(m.group(2))
                )

        changes: list[tuple[str, str]] = []
        # Track per-prefix counter for this annotation pass
        counters: dict[str, int] = {
            p: max_per_prefix.get(p, 0) for p in max_per_prefix
        }
        # Also include prefixes that only appear in unannotated refs
        for ref, _ in unannotated:
            m = _REF_PATTERN.match(ref)
            if m:
                p = m.group(1)
                if p not in counters:
                    counters[p] = 0

        for old_ref, comp in unannotated:
            m = _REF_PATTERN.match(old_ref)
            if not m:
                continue
            p = m.group(1)
            counters[p] = counters.get(p, 0) + 1
            new_ref = f"{p}{counters[p]}"
            self._set_component_reference(comp, new_ref)
            self._record_mutation(
                "annotate_component",
                {"old_ref": old_ref, "new_ref": new_ref},
            )
            changes.append((old_ref, new_ref))

        return changes

    def cross_reference_check(self) -> list[tuple[str, str]]:
        """Verify all symbol libIds resolve to entries in the embedded libSymbols.

        Returns:
            List of (reference, libId) tuples for unresolved symbols. Empty if all resolve.
        """
        all_refs = self.get_all_references()
        components = self._parse_result.kiutils_obj.schematicSymbols

        # Build set of valid libIds from embedded libSymbols
        valid_lib_ids: set[str] = set()
        lib_symbols = self._parse_result.kiutils_obj.libSymbols
        if lib_symbols:
            for sym in lib_symbols:
                if hasattr(sym, "libId") and sym.libId:
                    valid_lib_ids.add(sym.libId)
                # Also check extends chain
                if hasattr(sym, "extends") and sym.extends:
                    # The extending symbol inherits from the parent
                    pass

        unresolved: list[tuple[str, str]] = []
        for i, (ref, lib_id) in enumerate(all_refs):
            if lib_id and lib_id not in valid_lib_ids:
                unresolved.append((ref, lib_id))

        return unresolved
