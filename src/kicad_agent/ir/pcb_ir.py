"""PCB IR -- thin wrapper over a kiutils Board object with mutation tracking.

D-05: Holds reference to kiutils Board (not a copy).
D-06: Tracks mutations, dirty flag.
D-07: PCB-specific IR.

CRITICAL: kiutils drops all UUID tokens from PCB files (only handles legacy tstamp).
_uuid_map is required for serialization. The PCB IR constructor enforces this
requirement.

Usage:
    from kicad_agent.ir.pcb_ir import PcbIR
    from kicad_agent.parser import parse_pcb
    from kicad_agent.parser.uuid_extractor import extract_uuids

    result = parse_pcb(Path("my_board.kicad_pcb"))
    uuid_map = extract_uuids(result.raw_content, "pcb")
    ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)
    footprints = ir.footprints
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from kiutils.board import Board
from kiutils.footprint import Footprint
from kiutils.items.common import Net, Position, Property, Effects

from kicad_agent.ir.base import BaseIR
from kicad_agent.parser.types import ParseResult
from kicad_agent.parser.uuid_extractor import UUIDMap


@dataclass
class PcbIR(BaseIR):
    """Thin wrapper over a kiutils Board object with mutation tracking.

    D-05: Holds reference to kiutils Board (not a copy).
    D-06: Tracks mutations, dirty flag, UUID map reference.
    D-07: PCB-specific IR.

    CRITICAL: kiutils drops all UUID tokens from PCB files. _uuid_map is
    required for serialization.
    """

    _raw_written: bool = False  # Set when raw sexp manipulation writes the file directly

    def __post_init__(self) -> None:
        """Validate file type matches PCB and UUID map is provided."""
        super().__post_init__()
        if self.file_type != "pcb":
            raise ValueError(
                f"Expected file_type='pcb', got {self.file_type!r}"
            )
        if self._uuid_map is None:
            raise ValueError(
                "PcbIR requires a UUID map for serialization. "
                "kiutils drops all UUID tokens from PCB files. "
                "Use extract_uuids() from kicad_agent.parser.uuid_extractor."
            )

    @property
    def board(self) -> Board:
        """Direct access to the kiutils Board object."""
        return self._parse_result.kiutils_obj

    @property
    def footprints(self) -> list:
        """Access to PCB footprints."""
        return self._parse_result.kiutils_obj.footprints

    @property
    def nets(self) -> list:
        """Access to PCB nets."""
        return self._parse_result.kiutils_obj.nets

    @property
    def trace_items(self) -> list:
        """Access to PCB trace items (segments, arcs, vias)."""
        return self._parse_result.kiutils_obj.traceItems

    # -------------------------------------------------------------------
    # Net mutation methods
    # -------------------------------------------------------------------

    def add_net(self, net_name: str = "", net_number: Optional[int] = None) -> Net:
        """Add a new net to the PCB.

        Args:
            net_name: Net name. Empty string triggers auto-generation as "N_<number>".
            net_number: Explicit net number. None triggers auto-assignment (max existing + 1).

        Returns:
            The created Net object.

        Raises:
            ValueError: If net_name already exists (when explicitly named).
        """
        # Auto-assign net number: max existing + 1
        if net_number is None:
            max_num = max((n.number for n in self.board.nets), default=0)
            net_number = max_num + 1

        # Auto-generate name if empty
        if net_name == "":
            net_name = f"N_{net_number}"

        # Check for duplicate name
        if self.get_net_by_name(net_name) is not None:
            raise ValueError(f"Net '{net_name}' already exists")

        # Check for duplicate net number
        for n in self.board.nets:
            if n.number == net_number:
                raise ValueError(f"Net number {net_number} already in use by '{n.name}'")

        net = Net(number=net_number, name=net_name)
        self.board.nets.append(net)
        self._record_mutation("add_net", {
            "net_name": net_name,
            "net_number": net_number,
        })
        return net

    def remove_net(self, net_name: str) -> None:
        """Remove a net from the PCB, disconnecting all pads.

        Raises:
            ValueError: If net_name not found, or net_name is "" (net 0 is reserved).
        """
        if net_name == "":
            raise ValueError("Cannot remove net 0 (reserved unconnected net)")

        net = self.get_net_by_name(net_name)
        if net is None:
            raise ValueError(f"Net '{net_name}' not found")

        # Disconnect all pads connected to this net
        for fp in self.board.footprints:
            for pad in fp.pads:
                if pad.net is not None and pad.net.name == net_name:
                    pad.net = None

        # Remove the net from the board in-place (avoids stale list references)
        self.board.nets[:] = [n for n in self.board.nets if n.name != net_name]
        self._record_mutation("remove_net", {"net_name": net_name})

    def rename_net(self, old_name: str, new_name: str) -> None:
        """Rename a net, propagating to all connected pads.

        Raises:
            ValueError: If old_name not found or new_name already exists.
        """
        net = self.get_net_by_name(old_name)
        if net is None:
            raise ValueError(f"Net '{old_name}' not found")

        if self.get_net_by_name(new_name) is not None:
            raise ValueError(f"Net '{new_name}' already exists")

        # Update the net in board.nets
        for i, n in enumerate(self.board.nets):
            if n.name == old_name:
                self.board.nets[i] = Net(number=n.number, name=new_name)
                break

        # Propagate to all connected pads (create new Net to avoid shared reference)
        for fp in self.board.footprints:
            for pad in fp.pads:
                if pad.net is not None and pad.net.name == old_name:
                    pad.net = Net(number=pad.net.number, name=new_name)

        self._record_mutation("rename_net", {
            "old_name": old_name,
            "new_name": new_name,
        })

    def get_net_by_name(self, net_name: str) -> Optional[Net]:
        """Find a net by name. Returns None if not found."""
        for n in self.board.nets:
            if n.name == net_name:
                return n
        return None

    def get_net_pads(self, net_name: str) -> list[tuple[str, str]]:
        """Get all (footprint_libId, pad_number) tuples for pads on the named net.

        Returns:
            List of (footprint_libId, pad_number) tuples.
            Empty list if net not found or no pads connected.
        """
        pads: list[tuple[str, str]] = []
        for fp in self.board.footprints:
            for pad in fp.pads:
                if pad.net is not None and pad.net.name == net_name:
                    pads.append((fp.libId, pad.number))
        return pads

    # -------------------------------------------------------------------
    # Footprint query and mutation methods
    # -------------------------------------------------------------------

    def get_footprint_by_ref(self, reference: str) -> Optional[Any]:
        """Find a PCB footprint by its reference designator.

        KiCad footprints store the reference in the properties dict with
        key 'Reference'.

        Args:
            reference: Reference designator to search for (e.g. "J1").

        Returns:
            kiutils Footprint object, or None if not found.
        """
        for fp in self.board.footprints:
            ref = fp.properties.get("Reference", "")
            if ref == reference:
                return fp
        return None

    def swap_footprint(self, reference: str, new_footprint_lib_id: str) -> dict[str, Any]:
        """Swap a footprint while preserving all pad-to-net connections.

        This changes the footprint's libId but preserves pad.net assignments
        for pads that exist in the new footprint (by matching pad numbers).

        IMPORTANT: This does NOT reload the footprint geometry from the library.
        It only updates the libId string and preserves pad net connections.

        Args:
            reference: Reference designator of the footprint to swap.
            new_footprint_lib_id: New footprint library reference.

        Returns:
            Dict with 'old_lib_id', 'new_lib_id', 'preserved_nets' count.

        Raises:
            ValueError: If reference not found.
        """
        fp = self.get_footprint_by_ref(reference)
        if fp is None:
            raise ValueError(f"Footprint '{reference}' not found")

        old_lib_id = fp.libId

        # Save current pad-to-net mapping
        pad_nets: dict[str, Any] = {}
        for pad in fp.pads:
            if pad.net is not None:
                pad_nets[pad.number] = Net(number=pad.net.number, name=pad.net.name)

        # Update the libId
        fp.libId = new_footprint_lib_id

        # Restore pad nets for matching pad numbers
        preserved_count = 0
        for pad in fp.pads:
            if pad.number in pad_nets:
                pad.net = Net(number=pad_nets[pad.number].number, name=pad_nets[pad.number].name)
                preserved_count += 1
            else:
                pad.net = None

        self._record_mutation("swap_footprint", {
            "reference": reference,
            "old_lib_id": old_lib_id,
            "new_lib_id": new_footprint_lib_id,
            "preserved_nets": preserved_count,
        })

        return {
            "old_lib_id": old_lib_id,
            "new_lib_id": new_footprint_lib_id,
            "preserved_nets": preserved_count,
        }

    def update_footprint_from_library(
        self,
        reference: str,
        lib_id_override: Optional[str] = None,
        pcb_path: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Reload a footprint's geometry from the library, preserving placement.

        Loads the fresh footprint definition from the library .kicad_mod file
        and replaces the geometry in the PCB while preserving position, rotation,
        reference designator, value, and pad-to-net connections.

        This uses raw S-expression replacement rather than kiutils serialization
        to avoid data loss (kiutils drops UUIDs and reformats the entire file).

        Args:
            reference: Reference designator of the footprint to update.
            lib_id_override: Optional new lib_id. None = refresh from existing library.
            pcb_path: Path to the PCB file (needed for library resolution).

        Returns:
            Dict with update details: lib_id, preserved_nets, lost_nets, new_pads.

        Raises:
            ValueError: If reference not found or library cannot be resolved.
        """
        from kicad_agent.lib_resolver import resolve_footprint_path

        fp = self.get_footprint_by_ref(reference)
        if fp is None:
            raise ValueError(f"Footprint '{reference}' not found")

        lib_id = lib_id_override or fp.libId

        # --- Save state to preserve ---
        saved_angle = fp.position.angle if fp.position.angle is not None else 0.0
        saved_position = f"(at {fp.position.X} {fp.position.Y}"
        if saved_angle != 0.0:
            saved_position += f" {saved_angle}"
        saved_position += ")"

        saved_reference = fp.properties.get("Reference", "")
        saved_value = fp.properties.get("Value", "")
        saved_layer = fp.layer
        saved_lib_id = fp.libId

        # Save pad-to-net mapping
        pad_nets: dict[str, tuple[str, str]] = {}  # pad_number -> (net_name, raw_net_sexp)
        for pad in fp.pads:
            if pad.net is not None:
                pad_nets[pad.number] = (pad.net.name, "")

        # --- Save PCB-embedded-only fields from raw content ---
        # These fields exist only in PCB-embedded footprints, not in library .kicad_mod files
        raw_content = self._parse_result.raw_content
        old_fp_start, old_fp_end = _find_footprint_block(raw_content, reference)
        if old_fp_start is None:
            raise ValueError(
                f"Could not find footprint block for '{reference}' in raw content"
            )
        old_raw_block = raw_content[old_fp_start:old_fp_end]

        # Extract PCB-embedded-only fields and dedent by one tab level.
        # Old block lines are at \t\t level; after embedding adds one tab,
        # they'd become \t\t\t. Dedenting to \t ensures correct \t\t after embedding.
        saved_uuid = _extract_field(old_raw_block, r'^\t\t\(uuid "([^"]+)"\)', 'footprint UUID')
        saved_path_line = _dedent_one_tab(_extract_raw_line(old_raw_block, r'^\t\t\(path '))
        saved_sheetname_line = _dedent_one_tab(_extract_raw_line(old_raw_block, r'^\t\t\(sheetname '))
        saved_sheetfile_line = _dedent_one_tab(_extract_raw_line(old_raw_block, r'^\t\t\(sheetfile '))
        saved_units_block = _dedent_one_tab(_extract_raw_block(old_raw_block, r'^\t\t\(units'))
        saved_ki_fp_filters = _dedent_one_tab(_extract_raw_line(old_raw_block, r'^\t\t\(property ki_fp_filters'))

        # --- Resolve and load library footprint ---
        if pcb_path is None:
            pcb_path = self._parse_result.file_path
        mod_path = resolve_footprint_path(lib_id, pcb_path)
        lib_content = mod_path.read_text(encoding="utf-8")

        # --- Build replacement footprint S-expression ---
        # Build the new footprint from library content
        # The library .kicad_mod is a complete footprint file - extract the top-level sexp
        new_fp_sexpr = lib_content.strip()

        # Strip library-only fields that don't belong in embedded PCB footprints
        new_fp_sexpr = _strip_library_metadata(new_fp_sexpr)

        # Inject preserved state into the new footprint S-expression
        new_fp_sexpr = _inject_lib_id(new_fp_sexpr, lib_id)
        new_fp_sexpr = _inject_at_position(new_fp_sexpr, saved_position)
        new_fp_sexpr = _inject_layer(new_fp_sexpr, saved_layer)
        new_fp_sexpr = _inject_reference(new_fp_sexpr, saved_reference)
        new_fp_sexpr = _inject_value(new_fp_sexpr, saved_value)

        # Re-inject PCB-embedded-only fields
        if saved_uuid:
            new_fp_sexpr = _insert_after_field(new_fp_sexpr, r'^\t\(layer "[^"]*"\)', f'\n\t(uuid "{saved_uuid}")')
        if saved_path_line:
            new_fp_sexpr = _insert_before_attr(new_fp_sexpr, saved_path_line)
        if saved_sheetname_line:
            new_fp_sexpr = _insert_before_attr(new_fp_sexpr, saved_sheetname_line)
        if saved_sheetfile_line:
            new_fp_sexpr = _insert_before_attr(new_fp_sexpr, saved_sheetfile_line)
        if saved_units_block:
            new_fp_sexpr = _insert_before_attr(new_fp_sexpr, saved_units_block)
        if saved_ki_fp_filters:
            new_fp_sexpr = _insert_before_attr(new_fp_sexpr, saved_ki_fp_filters)

        # Restore pad net assignments
        preserved_count = 0
        lost_nets: list[str] = []
        new_pad_numbers: list[str] = []
        for pad_num, (net_name, _) in pad_nets.items():
            result = _inject_pad_net(new_fp_sexpr, pad_num, net_name)
            if result is not None:
                new_fp_sexpr = result
                preserved_count += 1
            else:
                lost_nets.append(f"{pad_num}:{net_name}")

        # Check for pads in new footprint that weren't in old
        old_pad_nums = set(pad_nets.keys())
        new_fp_pads = _extract_pad_numbers(new_fp_sexpr)
        for pn in new_fp_pads:
            if pn not in old_pad_nums:
                new_pad_numbers.append(pn)

        # --- Replace in raw content ---
        # The footprint block must be indented with one tab (top-level under kicad_pcb)
        new_fp_indented = "\t" + new_fp_sexpr.replace("\n", "\n\t")
        new_raw = raw_content[:old_fp_start] + new_fp_indented + raw_content[old_fp_end:]

        # Write back atomically: write to temp, then rename
        file_path = self._parse_result.file_path
        tmp = file_path.with_suffix('.tmp')
        tmp.write_text(new_raw, encoding="utf-8")
        tmp.rename(file_path)
        self._raw_written = True

        self._record_mutation("update_footprint_from_library", {
            "reference": reference,
            "lib_id": lib_id,
            "old_lib_id": saved_lib_id,
            "preserved_nets": preserved_count,
            "lost_nets": lost_nets,
            "new_pads": new_pad_numbers,
        })

        return {
            "reference": reference,
            "lib_id": lib_id,
            "old_lib_id": saved_lib_id,
            "preserved_nets": preserved_count,
            "lost_nets": lost_nets,
            "new_pads": new_pad_numbers,
        }

    def get_footprint_pads(self, reference: str) -> list[tuple[str, str]]:
        """Get (pad_number, net_name) tuples for a footprint.

        Args:
            reference: Reference designator of the footprint.

        Returns:
            List of (pad_number, net_name) tuples. Unconnected pads have net_name="".
        """
        fp = self.get_footprint_by_ref(reference)
        if fp is None:
            return []
        result: list[tuple[str, str]] = []
        for pad in fp.pads:
            net_name = pad.net.name if pad.net is not None else ""
            result.append((pad.number, net_name))
        return result

    def get_board_bounds(self) -> tuple[float, float, float, float] | None:
        """Extract board outline bounds as (x_min, y_min, x_max, y_max).

        Uses the first graphic line on Edge.Cuts to approximate bounds.
        Returns None if no board outline is found.

        Returns:
            Tuple of (x_min, y_min, x_max, y_max) in mm, or None.
        """
        segments: list[tuple[float, float]] = []
        for graphic in self.board.graphicItems:
            if hasattr(graphic, 'layer') and graphic.layer == "Edge.Cuts":
                if hasattr(graphic, 'start') and hasattr(graphic, 'end'):
                    segments.append((graphic.start.X, graphic.start.Y))
                    segments.append((graphic.end.X, graphic.end.Y))
                elif hasattr(graphic, 'center'):
                    cx, cy = graphic.center.X, graphic.center.Y
                    r = getattr(graphic, 'radius', getattr(graphic, 'end', None))
                    if r is not None:
                        radius = r.X - cx if hasattr(r, 'X') else float(r)
                        segments.append((cx - radius, cy - radius))
                        segments.append((cx + radius, cy + radius))

        # Also check footprint graphics on Edge.Cuts
        for fp in self.footprints:
            for graphic in fp.graphicItems:
                if hasattr(graphic, 'layer') and graphic.layer == "Edge.Cuts":
                    if hasattr(graphic, 'start') and hasattr(graphic, 'end'):
                        fp_x = fp.position.X if hasattr(fp.position, 'X') else 0
                        fp_y = fp.position.Y if hasattr(fp.position, 'Y') else 0
                        segments.append((graphic.start.X + fp_x, graphic.start.Y + fp_y))
                        segments.append((graphic.end.X + fp_x, graphic.end.Y + fp_y))

        if not segments:
            return None

        xs = [s[0] for s in segments]
        ys = [s[1] for s in segments]
        return (min(xs), min(ys), max(xs), max(ys))

    def extract_netlist(self) -> dict[str, list[tuple[float, float]]]:
        """Extract netlist mapping net names to pad positions.

        Returns:
            Dict mapping net name to list of (x, y) pad positions in mm.
        """
        netlist: dict[str, list[tuple[float, float]]] = {}
        for fp in self.footprints:
            fp_x = fp.position.X if hasattr(fp.position, 'X') else 0
            fp_y = fp.position.Y if hasattr(fp.position, 'Y') else 0
            for pad in fp.pads:
                if pad.net is not None and pad.net.name:
                    pad_x = fp_x + (pad.position.X if hasattr(pad.position, 'X') else 0)
                    pad_y = fp_y + (pad.position.Y if hasattr(pad.position, 'Y') else 0)
                    net_name = pad.net.name
                    if net_name not in netlist:
                        netlist[net_name] = []
                    netlist[net_name].append((round(pad_x, 4), round(pad_y, 4)))
        return netlist

    def insert_track_segments(self, sexpr_block: str) -> None:
        """Insert track segment S-expressions into the PCB file.

        Appends the segments before the closing ) of the .kicad_pcb file.

        Args:
            sexpr_block: Block of (segment ...) S-expressions.
        """
        raw = self._parse_result.raw_content
        # Find the last closing paren of the file
        last_close = raw.rfind(')')
        if last_close == -1:
            return
        insertion = "\n" + sexpr_block + "\n"
        new_raw = raw[:last_close] + insertion + raw[last_close:]
        self._parse_result = self._parse_result._replace(raw_content=new_raw)
        self._raw_written = True
        self._mark_dirty()


def _restore_properties(
    fp: Footprint, reference: str, value: str
) -> None:
    """Restore Reference and Value properties on a freshly-loaded footprint.

    kiutils stores footprint properties as a plain dict.
    """
    fp.properties["Reference"] = reference
    fp.properties["Value"] = value


# ---------------------------------------------------------------------------
# Raw S-expression helpers for PCB footprint replacement
# ---------------------------------------------------------------------------


def _find_footprint_block(content: str, reference: str) -> tuple[Optional[int], Optional[int]]:
    """Find the start and end positions of a footprint block by reference.

    Scans for ``(footprint ...`` blocks and checks their Reference property.
    Returns (start, end) byte offsets, or (None, None) if not found.
    """

    # Find all top-level footprint blocks (one tab indent)
    for match in re.finditer(r'^\t\(footprint ', content, re.MULTILINE):
        start = match.start()
        end = _find_matching_close(content, start + 1)  # +1 to skip the opening (
        if end is None:
            continue

        block = content[start:end + 1]

        # Check if this block has the target reference
        ref_match = re.search(r'\(property "Reference" "' + re.escape(reference) + r'"', block)
        if ref_match:
            return start, end + 1

    return None, None


def _find_matching_close(content: str, open_pos: int) -> Optional[int]:
    """Find the matching closing paren for an S-expression starting at open_pos.

    Handles nested parens and quoted strings.
    """
    depth = 0
    i = open_pos
    in_string = False

    while i < len(content):
        c = content[i]

        if in_string:
            if c == '"':
                # Check for escaped quote
                if i + 1 < len(content) and content[i + 1] == '"':
                    i += 2
                    continue
                in_string = False
            i += 1
            continue

        if c == '"':
            in_string = True
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1

    return None


def _strip_library_metadata(sexp: str) -> str:
    """Remove library-only fields that don't belong in embedded PCB footprints.

    KiCad library .kicad_mod files include version/generator/compatibility fields
    that are not valid inside a PCB's embedded footprint blocks.
    """
    # Remove (version ...), (generator "..."), (generator_version "...")
    # In the library file these are at single-tab indent under (footprint ...)
    for pattern in [
        r'^\t\(version [^\)]*\)\s*\n',
        r'^\t\(generator "[^"]*"\)\s*\n',
        r'^\t\(generator_version "[^"]*"\)\s*\n',
        r'^\t\(compatibility "[^"]*"\s*\([^\)]*\)\)\s*\n',
    ]:
        sexp = re.sub(pattern, '', sexp, flags=re.MULTILINE)
    return sexp


def _inject_lib_id(sexp: str, lib_id: str) -> str:
    """Replace the footprint's lib_id in the (footprint "LIB:NAME" ...) S-expression."""
    return re.sub(
        r'^\(footprint "([^"]*)"',
        f'(footprint "{lib_id}"',
        sexp,
        count=1,
    )


def _inject_at_position(sexp: str, at_sexp: str) -> str:
    """Replace or insert the (at ...) position in the footprint S-expression.

    Library footprints don't have (at ...), so we insert it after (layer "...").
    """

    # Try to replace existing (at ...)
    at_pattern = re.compile(r'^\t\(at [^\)]*\)', re.MULTILINE)
    if at_pattern.search(sexp):
        return at_pattern.sub(f'\t{at_sexp}', sexp, count=1)

    # No existing (at ...) — insert after (layer "...") line
    layer_match = re.search(r'^\t\(layer "[^"]*"\)\s*$', sexp, re.MULTILINE)
    if layer_match:
        insert_pos = layer_match.end()
        return sexp[:insert_pos] + f'\n\t{at_sexp}' + sexp[insert_pos:]

    # Fallback: insert after the first (property ...) block
    prop_match = re.search(r'^\t\(property ', sexp, re.MULTILINE)
    if prop_match:
        insert_pos = prop_match.start()
        return sexp[:insert_pos] + f'\t{at_sexp}\n' + sexp[insert_pos:]

    return sexp


def _inject_layer(sexp: str, layer: str) -> str:
    """Replace the (layer "...") in the footprint S-expression."""
    return re.sub(
        r'^\t\(layer "[^"]*"\)',
        f'\t(layer "{layer}")',
        sexp,
        count=1,
        flags=re.MULTILINE,
    )


def _escape_sexpr_value(s: str) -> str:
    """Escape special characters for safe embedding in S-expression strings."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _inject_reference(sexp: str, reference: str) -> str:
    """Replace the Reference property value in the footprint S-expression."""
    safe = _escape_sexpr_value(reference)
    return re.sub(
        r'\(property "Reference" "[^"]*"',
        f'(property "Reference" "{safe}"',
        sexp,
        count=1,
    )


def _inject_value(sexp: str, value: str) -> str:
    """Replace the Value property value in the footprint S-expression."""
    safe = _escape_sexpr_value(value)
    return re.sub(
        r'\(property "Value" "[^"]*"',
        f'(property "Value" "{safe}"',
        sexp,
        count=1,
    )


def _inject_pad_net(sexp: str, pad_number: str, net_name: str) -> Optional[str]:
    """Inject or replace the (net ...) in a specific pad of the footprint.

    Finds the pad by number and injects/replaces its net assignment.
    Returns the modified sexp, or None if the pad wasn't found.
    """

    # Find pad blocks by number - pads look like (pad "N" ...  )
    # We need to find the specific pad and inject (net "name") before its closing paren
    # Pad format: (pad "NUMBER" TYPE SHAPE (at X Y) (size W H) ... (net "NAME") ...)

    # Strategy: find all pad blocks, match by number, inject net
    # This is tricky because pads are nested. Let's use a simpler approach:
    # Find (pad "NUMBER" ... and then find the matching close paren
    pattern = re.compile(r'\(pad "' + re.escape(pad_number) + r'"')

    for match in pattern.finditer(sexp):
        pad_start = match.start()
        pad_end = _find_matching_close(sexp, pad_start)
        if pad_end is None:
            continue

        pad_block = sexp[pad_start:pad_end + 1]

        # Check if pad already has a net assignment
        if '(net ' in pad_block:
            # Replace existing net
            new_pad = re.sub(
                r'\(net "[^"]*"\)',
                f'(net "{net_name}")',
                pad_block,
                count=1,
            )
        else:
            # Insert net before the closing paren
            # Strip trailing whitespace, remove closing ), then add net + closing
            trimmed = pad_block.rstrip()
            new_pad = trimmed[:-1] + f'\n\t\t(net "{net_name}")\n\t)'

        return sexp[:pad_start] + new_pad + sexp[pad_end + 1:]

    return None


def _extract_pad_numbers(sexp: str) -> list[str]:
    """Extract all pad numbers from a footprint S-expression."""
    return re.findall(r'\(pad "([^"]+)"', sexp)


def _extract_field(block: str, pattern: str, desc: str = "") -> Optional[str]:
    """Extract a single captured group from a regex match in a block."""
    match = re.search(pattern, block, re.MULTILINE)
    return match.group(1) if match else None


def _extract_raw_line(block: str, pattern: str) -> Optional[str]:
    """Extract a full matching line from a block."""
    match = re.search(pattern + r'[^\n]*', block, re.MULTILINE)
    return match.group(0) if match else None


def _dedent_one_tab(text: Optional[str]) -> Optional[str]:
    """Strip one leading tab from each line in text.

    Used when extracting PCB-embedded fields from the old footprint block
    (which are at 2-tab level) for re-injection into the library footprint
    (at 1-tab level before embedding adds one tab back).
    """
    if text is None:
        return None
    return "\n".join(
        line[1:] if line.startswith("\t") else line
        for line in text.split("\n")
    )


def _extract_raw_block(block: str, start_pattern: str) -> Optional[str]:
    """Extract a balanced S-expression block starting with the given pattern."""
    match = re.search(start_pattern, block, re.MULTILINE)
    if not match:
        return None
    start = match.start()
    end = _find_matching_close(block, start + 1)
    if end is None:
        return None
    return block[start:end + 1]


def _insert_after_field(sexp: str, field_pattern: str, insertion: str) -> str:
    """Insert text after the line matching field_pattern."""
    match = re.search(field_pattern, sexp, re.MULTILINE)
    if match:
        pos = match.end()
        return sexp[:pos] + insertion + sexp[pos:]
    return sexp


def _insert_before_attr(sexp: str, line_to_insert: str) -> str:
    """Insert a line before the (attr ...) line in the footprint."""
    attr_match = re.search(r'^\t\(attr ', sexp, re.MULTILINE)
    if attr_match:
        pos = attr_match.start()
        return sexp[:pos] + line_to_insert + '\n' + sexp[pos:]
    # Fallback: insert before (pad ...) blocks
    pad_match = re.search(r'^\t\(pad ', sexp, re.MULTILINE)
    if pad_match:
        pos = pad_match.start()
        return sexp[:pos] + line_to_insert + '\n' + sexp[pos:]
    return sexp
