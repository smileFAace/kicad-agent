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
        # Iterate components directly to avoid index coupling between two lists
        parsed: list[tuple[str, int, Any]] = []
        for comp in self._parse_result.kiutils_obj.schematicSymbols:
            ref = self.get_component_property(comp, "Reference") or ""
            m = _REF_PATTERN.match(ref)
            if m and m.group(2) != "?":
                parsed.append((m.group(1), int(m.group(2)), comp))

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
        symbols = self._parse_result.kiutils_obj.schematicSymbols

        # Find unannotated refs (ending in '?') by iterating symbols directly
        unannotated: list[tuple[str, Any]] = []
        for comp in symbols:
            ref = self.get_component_property(comp, "Reference") or ""
            if ref.endswith("?"):
                unannotated.append((ref, comp))

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
        for comp in symbols:
            ref = self.get_component_property(comp, "Reference") or ""
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

    def assign_footprint(self, reference: str, footprint_lib_id: str) -> None:
        """Assign a footprint to a component by updating the Footprint property.

        Args:
            reference: Component reference designator (e.g. "U1").
            footprint_lib_id: Footprint library reference (e.g. "Package_DIP:DIP-8_W7.62mm").

        Raises:
            ValueError: If reference not found.
        """
        comp = self.get_component_by_ref(reference)
        if comp is None:
            raise ValueError(f"Component '{reference}' not found")

        for prop in comp.properties:
            if prop.key == "Footprint":
                prop.value = footprint_lib_id
                self._record_mutation("assign_footprint", {
                    "reference": reference,
                    "footprint_lib_id": footprint_lib_id,
                })
                return

        # No Footprint property exists — create it
        from kiutils.items.common import Property, Position, Effects
        comp.properties.append(Property(
            key="Footprint",
            value=footprint_lib_id,
            id=len(comp.properties),
            position=Position(X=0.0, Y=0.0, angle=0.0),
            effects=Effects(),
        ))
        self._record_mutation("assign_footprint", {
            "reference": reference,
            "footprint_lib_id": footprint_lib_id,
            "created_property": True,
        })

    def get_component_footprint(self, reference: str) -> Optional[str]:
        """Get the current footprint libId for a component.

        Args:
            reference: Component reference designator.

        Returns:
            Footprint library string, or None if not set or component not found.
        """
        comp = self.get_component_by_ref(reference)
        if comp is None:
            return None
        return self.get_component_property(comp, "Footprint")

    def verify_pin_map(self, reference: str, footprint_lib_id: str) -> dict[str, Any]:
        """Verify that symbol pin numbers match footprint pad numbers.

        Checks the component's libId against the embedded libSymbols to find
        pin definitions, then compares against the footprint's pad numbers.

        Args:
            reference: Component reference designator.
            footprint_lib_id: Footprint library reference to verify against.

        Returns:
            Dict with:
            - 'symbol_pins': set of pin numbers from the symbol
            - 'footprint_pads': set of pad numbers (empty if no PCB loaded)
            - 'missing_in_footprint': pin numbers in symbol but not footprint
            - 'extra_in_footprint': pad numbers in footprint but not symbol
            - 'match': bool - True if all symbol pins have corresponding pads
        """
        comp = self.get_component_by_ref(reference)
        symbol_pins: set[str] = set()

        if comp is not None:
            # Look up the component's libId in embedded libSymbols
            comp_lib_id = comp.libId
            lib_symbols = self._parse_result.kiutils_obj.libSymbols
            if lib_symbols:
                for lib_sym in lib_symbols:
                    if lib_sym.libId == comp_lib_id:
                        # Collect pin numbers from all units
                        for unit in lib_sym.units:
                            for pin in unit.pins:
                                if pin.number:
                                    symbol_pins.add(pin.number)
                        break

        # Footprint pads: without a loaded PCB, we can't check the actual
        # pad numbers. Return empty set for footprint_pads.
        footprint_pads: set[str] = set()

        missing_in_footprint = symbol_pins - footprint_pads
        extra_in_footprint = footprint_pads - symbol_pins

        return {
            "symbol_pins": symbol_pins,
            "footprint_pads": footprint_pads,
            "missing_in_footprint": missing_in_footprint,
            "extra_in_footprint": extra_in_footprint,
            "match": len(missing_in_footprint) == 0,
        }

    def cross_reference_check(self) -> list[tuple[str, str]]:
        """Verify all symbol libIds resolve to entries in the embedded libSymbols.

        Returns:
            List of (reference, libId) tuples for unresolved symbols. Empty if all resolve.
        """
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
        for comp in self._parse_result.kiutils_obj.schematicSymbols:
            ref = self.get_component_property(comp, "Reference") or ""
            lib_id = comp.libId
            if lib_id and lib_id not in valid_lib_ids:
                unresolved.append((ref, lib_id))

        return unresolved

    def add_wire(
        self, start_x: float, start_y: float, end_x: float, end_y: float
    ) -> dict[str, Any]:
        """Add a wire segment between two points.

        Args:
            start_x: Start X coordinate in mm.
            start_y: Start Y coordinate in mm.
            end_x: End X coordinate in mm.
            end_y: End Y coordinate in mm.

        Returns:
            Dict with wire details.
        """
        import uuid
        from kiutils.items.schitems import Connection
        from kiutils.items.common import Position, Stroke

        wire = Connection(
            type="wire",
            points=[
                Position(X=start_x, Y=start_y),
                Position(X=end_x, Y=end_y),
            ],
            stroke=Stroke(width=0.0),
            uuid=str(uuid.uuid4()),
        )
        self._parse_result.kiutils_obj.graphicalItems.append(wire)
        self._record_mutation("add_wire", {
            "start": [start_x, start_y],
            "end": [end_x, end_y],
        })
        return {
            "start": [start_x, start_y],
            "end": [end_x, end_y],
        }

    def connect_pins(self, source: str, target: str, route: str = "orthogonal") -> dict[str, Any]:
        """Connect two pins by semantic REF.PIN descriptors.

        Args:
            source: Source pin descriptor, e.g. ``"U1.34"`` or ``"J3.Pin_2"``.
            target: Target pin descriptor, e.g. ``"J3.2"`` or ``"U1.SWDIO"``.

        Returns:
            Dict with resolved endpoints and wire details.
        """
        source_pin = self._resolve_pin_ref(source)
        target_pin = self._resolve_pin_ref(target)

        if source_pin["x"] == target_pin["x"] and source_pin["y"] == target_pin["y"]:
            raise ValueError(f"Cannot connect {source!r} to {target!r}: endpoints are identical")

        if route == "direct" or source_pin["x"] == target_pin["x"] or source_pin["y"] == target_pin["y"]:
            wires = [self.add_wire(
                start_x=source_pin["x"],
                start_y=source_pin["y"],
                end_x=target_pin["x"],
                end_y=target_pin["y"],
            )]
        elif route == "orthogonal":
            corner_x = target_pin["x"]
            corner_y = source_pin["y"]
            wires = [
                self.add_wire(
                    start_x=source_pin["x"],
                    start_y=source_pin["y"],
                    end_x=corner_x,
                    end_y=corner_y,
                ),
                self.add_wire(
                    start_x=corner_x,
                    start_y=corner_y,
                    end_x=target_pin["x"],
                    end_y=target_pin["y"],
                ),
            ]
            junction = self._add_junction_if_missing(corner_x, corner_y)
        else:
            raise ValueError(f"Unsupported route style: {route!r}")

        result = {
            "source": source,
            "target": target,
            "route": route,
            "source_pin": source_pin,
            "target_pin": target_pin,
            "wires": wires,
        }
        if route == "orthogonal" and source_pin["x"] != target_pin["x"] and source_pin["y"] != target_pin["y"]:
            result["junction"] = junction
        return result

    def _add_junction_if_missing(self, x: float, y: float) -> Optional[dict[str, Any]]:
        """Add a junction at an orthogonal wire corner unless one exists."""
        for junction in self.schematic.junctions:
            if junction.position.X == x and junction.position.Y == y:
                return None
        return self.add_junction(x=x, y=y)

    def _resolve_pin_ref(self, pin_ref: str) -> dict[str, Any]:
        """Resolve a REF.PIN descriptor to one absolute pin endpoint."""
        ref, pin_id = pin_ref.split(".", 1)
        matches = [
            pin for pin in self.get_pin_positions()
            if pin["reference"] == ref
            and (str(pin["pin_number"]) == pin_id or str(pin["pin_name"]) == pin_id)
        ]
        if not matches:
            raise ValueError(f"Pin not found: {pin_ref!r}")
        if len(matches) > 1:
            raise ValueError(f"Pin reference is ambiguous: {pin_ref!r}")
        return matches[0]

    def add_label(
        self,
        name: str,
        label_type: str = "local",
        x: float = 0.0,
        y: float = 0.0,
        angle: float = 0.0,
        shape: str = "input",
    ) -> dict[str, Any]:
        """Add a net label to the schematic.

        Args:
            name: Label text.
            label_type: One of "local", "global", "hierarchical".
            x: X coordinate in mm.
            y: Y coordinate in mm.
            angle: Rotation angle in degrees.
            shape: Shape for global/hierarchical labels.

        Returns:
            Dict with label details.
        """
        import uuid
        from kiutils.items.common import Position
        from kiutils.items.schitems import LocalLabel, GlobalLabel, HierarchicalLabel

        pos = Position(X=x, Y=y, angle=angle)

        if label_type == "global":
            label = GlobalLabel(
                text=name,
                shape=shape,
                position=pos,
                uuid=str(uuid.uuid4()),
            )
            self._parse_result.kiutils_obj.globalLabels.append(label)
        elif label_type == "hierarchical":
            label = HierarchicalLabel(
                text=name,
                shape=shape,
                position=pos,
                uuid=str(uuid.uuid4()),
            )
            self._parse_result.kiutils_obj.hierarchicalLabels.append(label)
        else:
            label = LocalLabel(
                text=name,
                position=pos,
                uuid=str(uuid.uuid4()),
            )
            self._parse_result.kiutils_obj.labels.append(label)

        self._record_mutation("add_label", {
            "name": name,
            "label_type": label_type,
            "position": [x, y, angle],
        })
        return {
            "name": name,
            "label_type": label_type,
            "position": [x, y],
        }

    def add_power_symbol(
        self,
        name: str,
        x: float = 0.0,
        y: float = 0.0,
        angle: float = 0.0,
    ) -> dict[str, Any]:
        """Add a power symbol (from the power library) to the schematic.

        Power symbols (e.g. +5V, GND) are placed as SchematicSymbol objects
        with libId ``power:<name>``. They carry a single power-output pin
        that connects to the named net.

        Args:
            name: Power net name (e.g. "+5V", "GND", "+3V3").
            x: X coordinate in mm.
            y: Y coordinate in mm.
            angle: Rotation angle in degrees.

        Returns:
            Dict with the placed power symbol details.
        """
        import uuid
        from kiutils.items.common import Position, Property, Effects, Font
        from kiutils.items.schitems import SchematicSymbol

        lib_id = f"power:{name}"
        pos = Position(X=x, Y=y, angle=angle)
        sym_uuid = str(uuid.uuid4())

        sym = SchematicSymbol(
            libraryNickname="power",
            entryName=name,
            position=pos,
            uuid=sym_uuid,
            properties=[
                Property(
                    key="Reference",
                    value="#PWR?",
                    id=0,
                    position=Position(X=0.0, Y=0.0, angle=0.0),
                    effects=Effects(font=Font()),
                ),
                Property(
                    key="Value",
                    value=name,
                    id=1,
                    position=Position(X=0.0, Y=0.0, angle=0.0),
                    effects=Effects(font=Font()),
                ),
                Property(
                    key="Footprint",
                    value="",
                    id=2,
                    position=Position(X=0.0, Y=0.0, angle=0.0),
                    effects=Effects(font=Font()),
                ),
            ],
        )
        self._parse_result.kiutils_obj.schematicSymbols.append(sym)
        self._record_mutation("add_power_symbol", {
            "name": name,
            "lib_id": lib_id,
            "position": [x, y, angle],
        })
        return {
            "name": name,
            "lib_id": lib_id,
            "position": [x, y],
        }

    def add_no_connect(self, x: float = 0.0, y: float = 0.0) -> dict[str, Any]:
        """Add a no-connect flag at a position.

        Args:
            x: X coordinate in mm.
            y: Y coordinate in mm.

        Returns:
            Dict with position details.
        """
        import uuid
        from kiutils.items.common import Position
        from kiutils.items.schitems import NoConnect

        nc = NoConnect(
            position=Position(X=x, Y=y),
            uuid=str(uuid.uuid4()),
        )
        self._parse_result.kiutils_obj.noConnects.append(nc)
        self._record_mutation("add_no_connect", {"position": [x, y]})
        return {"position": [x, y]}

    def add_junction(self, x: float = 0.0, y: float = 0.0) -> dict[str, Any]:
        """Add a junction dot at a wire intersection.

        Args:
            x: X coordinate in mm.
            y: Y coordinate in mm.

        Returns:
            Dict with position details.
        """
        import uuid
        from kiutils.items.common import Position
        from kiutils.items.schitems import Junction

        jct = Junction(
            position=Position(X=x, Y=y),
            uuid=str(uuid.uuid4()),
        )
        self._parse_result.kiutils_obj.junctions.append(jct)
        self._record_mutation("add_junction", {"position": [x, y]})
        return {"position": [x, y]}

    # -------------------------------------------------------------------
    # Pin / wire / label position helpers (for repair operations)
    # -------------------------------------------------------------------

    def get_pin_positions(self) -> list[dict[str, Any]]:
        """Return all pin absolute positions with symbol reference and pin name.

        Computes absolute pin positions using the Y-inversion pattern:
            absolute = (sx + rotated_px, sy - rotated_py)
        where (sx, sy) is the symbol placement position and (px, py) is the
        pin offset in the library definition. Rotation is applied to (px, py)
        before translation.

        T-10-11: Explicit Y-inversion via (sx+px, sy-py).

        Returns:
            List of dicts with keys: reference, pin_name, pin_number, x, y,
            electrical_type.
        """
        import math

        sch = self._parse_result.kiutils_obj

        # Build libId -> list of pin definitions from embedded libSymbols
        lib_pin_map: dict[str, list] = {}
        for lib_sym in sch.libSymbols:
            lib_id = getattr(lib_sym, "libId", "")
            pins: list = []
            pins.extend(getattr(lib_sym, "pins", []))
            for unit in lib_sym.units:
                pins.extend(unit.pins)
            lib_pin_map[lib_id] = pins

        result: list[dict[str, Any]] = []
        for sym in sch.schematicSymbols:
            ref = self.get_component_property(sym, "Reference") or ""
            lib_id = sym.libId
            sx = sym.position.X
            sy = sym.position.Y
            angle_deg = sym.position.angle or 0.0
            angle_rad = math.radians(angle_deg)

            pin_defs = lib_pin_map.get(lib_id, [])
            for pin_def in pin_defs:
                px = pin_def.position.X
                py = pin_def.position.Y

                # Apply rotation to pin offset, then translate.
                # Y-inversion: KiCad pin Y is inverted relative to sheet coords.
                rot_px = px * math.cos(angle_rad) - py * math.sin(angle_rad)
                rot_py = px * math.sin(angle_rad) + py * math.cos(angle_rad)

                # T-10-11: pin absolute position = (sx + rot_px, sy - rot_py)
                abs_x = sx + rot_px
                abs_y = sy - rot_py

                result.append({
                    "reference": ref,
                    "pin_name": pin_def.name,
                    "pin_number": pin_def.number,
                    "x": abs_x,
                    "y": abs_y,
                    "electrical_type": pin_def.electricalType,
                })

        return result

    def get_wire_endpoints(self) -> list[dict[str, Any]]:
        """Return all wire start/end positions from graphicalItems.

        Wires are Connection objects with type='wire' in graphicalItems.

        Returns:
            List of dicts with keys: start_x, start_y, end_x, end_y, uuid,
            wire_index.
        """
        result: list[dict[str, Any]] = []
        sch = self._parse_result.kiutils_obj
        from kiutils.items.schitems import Connection

        for idx, item in enumerate(sch.graphicalItems):
            if isinstance(item, Connection) and item.type == "wire":
                if len(item.points) >= 2:
                    result.append({
                        "start_x": item.points[0].X,
                        "start_y": item.points[0].Y,
                        "end_x": item.points[1].X,
                        "end_y": item.points[1].Y,
                        "uuid": item.uuid,
                        "wire_index": idx,
                    })
        return result

    def get_label_positions(self) -> list[dict[str, Any]]:
        """Return all label positions with names.

        Includes local labels, global labels, and hierarchical labels.

        Returns:
            List of dicts with keys: name, x, y, label_type.
        """
        result: list[dict[str, Any]] = []
        sch = self._parse_result.kiutils_obj

        for label in sch.labels:
            result.append({
                "name": label.text,
                "x": label.position.X,
                "y": label.position.Y,
                "label_type": "local",
            })

        for label in sch.globalLabels:
            result.append({
                "name": label.text,
                "x": label.position.X,
                "y": label.position.Y,
                "label_type": "global",
            })

        for label in sch.hierarchicalLabels:
            result.append({
                "name": label.text,
                "x": label.position.X,
                "y": label.position.Y,
                "label_type": "hierarchical",
            })

        return result

    # -------------------------------------------------------------------
    # UUID-based lookup helpers (for remove operations)
    # -------------------------------------------------------------------

    def get_wire_by_uuid(self, uuid: str) -> Optional[Any]:
        """Find a wire Connection object by its UUID.

        Wires are Connection objects with type='wire' stored in graphicalItems.

        Args:
            uuid: The UUID string to search for.

        Returns:
            The matching kiutils Connection (wire), or None if not found.
        """
        from kiutils.items.schitems import Connection

        for item in self._parse_result.kiutils_obj.graphicalItems:
            if isinstance(item, Connection) and item.type == "wire":
                if item.uuid == uuid:
                    return item
        return None

    def get_label_by_uuid(self, uuid: str) -> Optional[Any]:
        """Find a label object by its UUID.

        Searches local labels, global labels, and hierarchical labels.

        Args:
            uuid: The UUID string to search for.

        Returns:
            The matching kiutils label object, or None if not found.
        """
        sch = self._parse_result.kiutils_obj

        for label in sch.labels:
            if label.uuid == uuid:
                return label

        for label in sch.globalLabels:
            if label.uuid == uuid:
                return label

        for label in sch.hierarchicalLabels:
            if label.uuid == uuid:
                return label

        return None

    def get_junction_by_uuid(self, uuid: str) -> Optional[Any]:
        """Find a Junction object by its UUID.

        Args:
            uuid: The UUID string to search for.

        Returns:
            The matching kiutils Junction, or None if not found.
        """
        for jct in self._parse_result.kiutils_obj.junctions:
            if jct.uuid == uuid:
                return jct
        return None

    def get_no_connect_by_uuid(self, uuid: str) -> Optional[Any]:
        """Find a NoConnect object by its UUID.

        Args:
            uuid: The UUID string to search for.

        Returns:
            The matching kiutils NoConnect, or None if not found.
        """
        for nc in self._parse_result.kiutils_obj.noConnects:
            if nc.uuid == uuid:
                return nc
        return None

    def get_adjacent_wires(
        self, wire_uuid: str, tolerance: float = 0.0001
    ) -> list:
        """Find wires that share an endpoint with the specified wire.

        Two wires are adjacent when the start or end coordinates of one
        match the start or end coordinates of the other within tolerance.

        Args:
            wire_uuid: UUID of the reference wire.
            tolerance: Maximum coordinate distance to consider as touching
                       (default 0.0001 mm).

        Returns:
            List of kiutils Connection (wire) objects adjacent to the
            reference wire, excluding the reference wire itself.
        """
        from kiutils.items.schitems import Connection

        ref = self.get_wire_by_uuid(wire_uuid)
        if ref is None or len(ref.points) < 2:
            return []

        ref_coords = {
            (ref.points[0].X, ref.points[0].Y),
            (ref.points[1].X, ref.points[1].Y),
        }

        adjacent: list = []
        for item in self._parse_result.kiutils_obj.graphicalItems:
            if not isinstance(item, Connection) or item.type != "wire":
                continue
            if item.uuid == wire_uuid or len(item.points) < 2:
                continue

            item_coords = [
                (item.points[0].X, item.points[0].Y),
                (item.points[1].X, item.points[1].Y),
            ]

            for ix, iy in item_coords:
                for rx, ry in ref_coords:
                    if abs(ix - rx) <= tolerance and abs(iy - ry) <= tolerance:
                        adjacent.append(item)
                        break
                else:
                    continue
                break

        return adjacent
