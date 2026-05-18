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

from dataclasses import dataclass
from typing import Any, Optional

from kiutils.board import Board
from kiutils.items.common import Net

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

        # Remove the net from the board
        self.board.nets = [n for n in self.board.nets if n.name != net_name]
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
