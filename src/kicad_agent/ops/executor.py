"""Operation executor -- dispatches validated Operation intents to handlers.

Establishes the pattern (executor dispatch, handler function, Transaction
wrapping, IR mutation, serialization) that all subsequent operations follow.

Security (threat model):
- T-04-06: Dispatch uses exact op_type matching; unknown raises ValueError
- T-04-01: UUID generated server-side in handlers

Usage:
    from kicad_agent.ops.executor import OperationExecutor
    from kicad_agent.ops.schema import Operation

    executor = OperationExecutor(base_dir=Path("/project"))
    result = executor.execute(op)
"""

import logging
from pathlib import Path
from typing import Any, Callable

from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ir.transaction import Transaction
from kicad_agent.ops.schema import Operation
from kicad_agent.parser import parse_pcb, parse_schematic
from kicad_agent.parser.uuid_extractor import extract_uuids
from kicad_agent.serializer import normalize_kicad_output, serialize_pcb, serialize_schematic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Handler registries: op_type -> callable(op, ir, file_path) -> dict
# ---------------------------------------------------------------------------

# Schematic handlers: (op, SchematicIR, file_path) -> dict
_SCHEMATIC_HANDLERS: dict[str, Callable] = {}

# PCB handlers: (op, PcbIR, file_path) -> dict
_PCB_HANDLERS: dict[str, Callable] = {}

# Project handlers: (op, file_path) -> dict
_PROJECT_HANDLERS: dict[str, Callable] = {}

# Create handlers: (op, file_path) -> dict -- no IR, no Transaction
_CREATE_HANDLERS: dict[str, Callable] = {}

# Set of op_types that create new files (bypass file-existence check)
_CREATE_OP_TYPES = {"create_schematic", "create_pcb", "create_project", "create_symbol"}


def register_schematic(op_type: str) -> Callable:
    """Decorator to register a schematic operation handler."""
    def decorator(fn: Callable) -> Callable:
        _SCHEMATIC_HANDLERS[op_type] = fn
        return fn
    return decorator


def register_pcb(op_type: str) -> Callable:
    """Decorator to register a PCB operation handler."""
    def decorator(fn: Callable) -> Callable:
        _PCB_HANDLERS[op_type] = fn
        return fn
    return decorator


def register_project(op_type: str) -> Callable:
    """Decorator to register a project-file operation handler."""
    def decorator(fn: Callable) -> Callable:
        _PROJECT_HANDLERS[op_type] = fn
        return fn
    return decorator


def register_create(op_type: str) -> Callable:
    """Decorator to register a file-creation operation handler."""
    def decorator(fn: Callable) -> Callable:
        _CREATE_HANDLERS[op_type] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Schematic handler implementations
# ---------------------------------------------------------------------------


@register_schematic("add_component")
def _handle_add_component(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.add_component import add_component
    return add_component(op, ir, file_path)


@register_schematic("remove_component")
def _handle_remove_component(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.remove_component import remove_component
    return remove_component(op, ir)


@register_schematic("duplicate_component")
def _handle_duplicate_component(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.duplicate_component import duplicate_component
    return duplicate_component(op, ir)


@register_schematic("array_replicate")
def _handle_array_replicate(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.array_replicate import array_replicate
    return array_replicate(op, ir)


@register_schematic("move_component")
def _handle_move_component(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.move_component import move_component
    return move_component(op, ir, file_type=ir.file_type)


@register_schematic("modify_property")
def _handle_modify_property(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.modify_property import modify_property
    return modify_property(op, ir)


@register_schematic("add_net")
def _handle_sch_add_net(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    net = ir.add_net(net_name=op.net_name, net_number=op.net_number)
    return {"net_name": net.name, "net_number": net.number}


@register_schematic("remove_net")
def _handle_sch_remove_net(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    ir.remove_net(net_name=op.net_name)
    return {"removed_net": op.net_name}


@register_schematic("rename_net")
def _handle_sch_rename_net(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    ir.rename_net(old_name=op.old_name, new_name=op.new_name)
    return {"old_name": op.old_name, "new_name": op.new_name}


@register_schematic("renumber_refs")
def _handle_renumber_refs(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    changes = ir.renumber_references(
        prefix=op.prefix, start_index=op.start_index, step=op.step
    )
    return {"changes": [{"old": o, "new": n} for o, n in changes]}


@register_schematic("validate_refs")
def _handle_validate_refs(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    duplicates = ir.validate_reference_uniqueness()
    return {"duplicates": duplicates, "valid": len(duplicates) == 0}


@register_schematic("annotate")
def _handle_annotate(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    changes = ir.annotate_components(prefix_filter=op.prefix_filter)
    return {"annotated": [{"old": o, "new": n} for o, n in changes]}


@register_schematic("cross_ref_check")
def _handle_cross_ref_check(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    unresolved = ir.cross_reference_check()
    return {"unresolved": [{"ref": r, "lib_id": l} for r, l in unresolved]}


@register_schematic("assign_footprint")
def _handle_assign_footprint(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    ir.assign_footprint(reference=op.reference, footprint_lib_id=op.footprint_lib_id)
    return {"reference": op.reference, "footprint": op.footprint_lib_id}


@register_schematic("swap_footprint")
def _handle_sch_swap_footprint(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.swap_footprint(reference=op.reference, new_footprint_lib_id=op.new_footprint_lib_id)


@register_schematic("validate_footprint")
def _handle_sch_validate_footprint(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return {"footprint_lib_id": op.footprint_lib_id, "valid": True}


@register_schematic("verify_pin_map")
def _handle_verify_pin_map(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.verify_pin_map(reference=op.reference, footprint_lib_id=op.footprint_lib_id)


@register_schematic("add_wire")
def _handle_add_wire(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_wire(
        start_x=op.start_x, start_y=op.start_y,
        end_x=op.end_x, end_y=op.end_y,
    )


@register_schematic("add_label")
def _handle_add_label(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_label(
        name=op.name,
        label_type=op.label_type,
        x=op.position.x, y=op.position.y,
        angle=op.position.angle,
        shape=op.shape,
    )


@register_schematic("add_power")
def _handle_add_power(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_power_symbol(
        name=op.name,
        x=op.position.x, y=op.position.y,
        angle=op.position.angle,
    )


@register_schematic("add_no_connect")
def _handle_add_no_connect(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_no_connect(x=op.position.x, y=op.position.y)


@register_schematic("add_junction")
def _handle_add_junction(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_junction(x=op.position.x, y=op.position.y)


@register_schematic("add_bus")
def _handle_add_bus(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    raise NotImplementedError("Bus operations not yet implemented")


@register_schematic("remove_bus")
def _handle_remove_bus(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    raise NotImplementedError("Bus operations not yet implemented")


@register_schematic("repair_schematic")
def _handle_repair_schematic(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair import (
        place_no_connects,
        remove_orphaned_labels,
        repair_wire_snapping,
        snap_to_grid,
    )
    details: dict[str, Any] = {}
    if op.snap_wires:
        details["wire_snapping"] = repair_wire_snapping(ir, file_path)
    if op.remove_orphans:
        details["orphan_removal"] = remove_orphaned_labels(ir)
    if op.place_no_connects:
        details["no_connects"] = place_no_connects(ir)
    if op.snap_to_grid:
        details["snap_to_grid"] = snap_to_grid(ir, grid_mm=0.01)
    return details


@register_schematic("validate_power_nets")
def _handle_validate_power_nets(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.validation_gates import validate_power_nets
    return validate_power_nets(ir)


@register_schematic("validate_schematic")
def _handle_validate_schematic(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.validation_gates import validate_schematic_completeness
    return validate_schematic_completeness(
        file_path,
        check_symbol_resolution=op.check_symbol_resolution,
        check_format=op.check_format,
        check_power_nets=op.check_power_nets,
        check_annotation=op.check_annotation,
    )


@register_schematic("parse_erc")
def _handle_parse_erc(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    import dataclasses
    from kicad_agent.ops.erc_parser import parse_erc
    violations = parse_erc(file_path)
    return {"violations": [dataclasses.asdict(v) for v in violations]}


@register_schematic("extract_violation_positions")
def _handle_extract_violation_positions(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    import dataclasses
    from kicad_agent.ops.erc_parser import extract_violation_positions
    positions = extract_violation_positions(file_path, op.violation_type)
    return {"positions": [dataclasses.asdict(p) for p in positions], "count": len(positions)}


@register_schematic("validate_hlabels")
def _handle_validate_hlabels(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    import dataclasses
    from kicad_agent.ops.hlabel_guard import validate_hlabels
    expected = set(op.expected_labels) if op.expected_labels else None
    result = validate_hlabels(ir, expected_labels=expected)
    return dataclasses.asdict(result)


@register_schematic("convert_kicad6_to_10")
def _handle_convert_kicad6_to_10(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.format_convert import convert_kicad6_to_10
    content = file_path.read_text(encoding="utf-8")
    converted = convert_kicad6_to_10(content)
    file_path.write_text(converted, encoding="utf-8")
    return {"converted": True, "file_path": str(file_path)}


@register_schematic("snap_to_grid")
def _handle_snap_to_grid(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair import snap_to_grid
    return snap_to_grid(ir, grid_mm=op.grid_mm)


@register_schematic("add_power_flag")
def _handle_add_power_flag(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair import add_power_flags
    return add_power_flags(ir, file_path)


@register_schematic("rebuild_root_sheet")
def _handle_rebuild_root_sheet(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    import dataclasses
    from kicad_agent.ops.root_sheet import rebuild_root_sheet
    results = rebuild_root_sheet(file_path)
    return {
        "sheets_processed": len(results),
        "details": [dataclasses.asdict(r) for r in results],
    }


# ---------------------------------------------------------------------------
# PCB handler implementations
# ---------------------------------------------------------------------------


@register_pcb("update_footprint_from_library")
def _handle_update_footprint(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    return ir.update_footprint_from_library(
        reference=op.reference,
        lib_id_override=op.footprint_lib_id,
        pcb_path=file_path,
    )


@register_pcb("swap_footprint")
def _handle_pcb_swap_footprint(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    return ir.swap_footprint(
        reference=op.reference,
        new_footprint_lib_id=op.new_footprint_lib_id,
    )


@register_pcb("add_net")
def _handle_pcb_add_net(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    net = ir.add_net(net_name=op.net_name, net_number=op.net_number)
    return {"net_name": net.name, "net_number": net.number}


@register_pcb("remove_net")
def _handle_pcb_remove_net(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    ir.remove_net(net_name=op.net_name)
    return {"removed_net": op.net_name}


@register_pcb("rename_net")
def _handle_pcb_rename_net(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    ir.rename_net(old_name=op.old_name, new_name=op.new_name)
    return {"old_name": op.old_name, "new_name": op.new_name}


@register_pcb("validate_footprint")
def _handle_pcb_validate_footprint(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    return {"footprint_lib_id": op.footprint_lib_id, "valid": True}


@register_pcb("add_copper_zone")
def _handle_add_copper_zone(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.pcb_ops import add_copper_zone
    return add_copper_zone(
        ir, file_path,
        net_name=op.net_name,
        layer=op.layer,
        clearance=op.clearance,
        min_width=op.min_width,
        priority=op.priority,
    )


@register_pcb("set_board_outline")
def _handle_set_board_outline(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.pcb_ops import set_board_outline
    return set_board_outline(ir, width=op.width, height=op.height)


@register_pcb("assign_net_class")
def _handle_assign_net_class(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.pcb_ops import assign_net_class
    return assign_net_class(
        ir, file_path,
        net_name=op.net_name,
        net_class_name=op.net_class_name,
    )


@register_pcb("auto_route")
def _handle_auto_route(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.routing.bridge import route_to_segments, segments_to_sexpr
    from kicad_agent.routing.constraints import RoutingConstraints
    from kicad_agent.routing.pathfinder import build_routing_graph, route_all_nets

    constraints = RoutingConstraints()

    bounds = ir.get_board_bounds()
    if bounds is None:
        raise ValueError("Cannot auto-route: board outline not set")

    netlist = ir.extract_netlist()
    if not netlist:
        return {"routed_nets": 0, "segments": 0, "message": "No nets to route"}

    if op.nets:
        netlist = {n: pins for n, pins in netlist.items() if n in op.nets}

    routing_graph = build_routing_graph(bounds, constraints=constraints)
    results = route_all_nets(routing_graph, netlist)

    segments = route_to_segments(results, constraints, layer=op.layer)
    segment_count = len(segments)
    routed_nets = len(segments) and len({s.net for s in segments})

    if segments:
        sexpr_block = segments_to_sexpr(segments)
        ir.insert_track_segments(sexpr_block)

    return {
        "routed_nets": routed_nets,
        "segments": segment_count,
        "failed_nets": [
            n for n in netlist
            if n not in results or not results[n].success
        ],
    }


# ---------------------------------------------------------------------------
# Project handler implementations
# ---------------------------------------------------------------------------


@register_project("add_lib_entry")
def _handle_add_lib_entry(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.lib_table import (
        LibEntry,
        parse_lib_table,
        serialize_lib_table,
    )
    table = parse_lib_table(file_path)
    entry = LibEntry(
        name=op.lib_name,
        type=op.lib_type,
        uri=op.uri,
        options=op.options,
        descr=op.description,
    )
    table.add(entry)
    serialize_lib_table(table, file_path)
    return {"lib_name": op.lib_name, "action": "added"}


@register_project("remove_lib_entry")
def _handle_remove_lib_entry(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.lib_table import (
        parse_lib_table,
        serialize_lib_table,
    )
    table = parse_lib_table(file_path)
    removed = table.remove(op.lib_name)
    serialize_lib_table(table, file_path)
    return {"lib_name": removed.name, "action": "removed"}


@register_project("add_net_class")
def _handle_add_net_class(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.design_rules import (
        NetClassDef,
        parse_design_rules,
        serialize_design_rules,
    )
    dru = parse_design_rules(file_path)
    nc = NetClassDef(
        name=op.name,
        clearance=op.clearance,
        track_width=op.track_width,
        via_diameter=op.via_diameter,
        via_drill=op.via_drill,
    )
    dru.add_net_class(nc)
    serialize_design_rules(dru, file_path)
    return {"net_class": op.name, "action": "added"}


@register_project("add_design_rule")
def _handle_add_design_rule(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.design_rules import (
        DesignRule,
        parse_design_rules,
        serialize_design_rules,
    )
    dru = parse_design_rules(file_path)
    rule = DesignRule(
        name=op.name,
        constraint_type=op.constraint_type,
        constraint_values=op.constraint_values,
        condition=op.condition,
    )
    dru.add_rule(rule)
    serialize_design_rules(dru, file_path)
    return {"rule_name": op.name, "action": "added"}


# ---------------------------------------------------------------------------
# Create handler implementations (no IR, no Transaction)
# ---------------------------------------------------------------------------


@register_create("create_schematic")
def _handle_create_schematic(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.create_file import create_schematic
    return create_schematic(op, file_path)


@register_create("create_pcb")
def _handle_create_pcb(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.create_file import create_pcb
    return create_pcb(op, file_path)


@register_create("create_project")
def _handle_create_project(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.create_file import create_project
    return create_project(op, file_path)


@register_create("create_symbol")
def _handle_create_symbol(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.create_file import create_symbol
    return create_symbol(op, file_path)


# ---------------------------------------------------------------------------
# Executor class
# ---------------------------------------------------------------------------


class OperationExecutor:
    """Dispatches validated Operation intents to mutation handlers.

    Each handler call is wrapped in a Transaction for rollback on failure.
    The executor parses the file, creates SchematicIR, calls the handler,
    serializes, normalizes, and commits.

    Args:
        base_dir: Base directory for resolving relative target_file paths.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def execute(self, op: Operation) -> dict[str, Any]:
        """Execute a validated operation with Transaction wrapping.

        Routes to schematic or PCB execution path based on file extension.

        Args:
            op: Validated Operation from the schema.

        Returns:
            Dict with: success, operation, target_file, details.

        Raises:
            ValueError: For unknown op_type (T-04-06).
            FileNotFoundError: If target_file does not exist.
        """
        root = op.root
        file_path = self._base_dir / root.target_file

        # Create operations: file does not exist yet (bypass existence check)
        if root.op_type in _CREATE_OP_TYPES:
            return self._execute_create(op, file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Target file not found: {file_path}")

        # Clear IR registry to avoid stale registrations across operations
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        # Branch on file type
        if file_path.suffix == ".kicad_pcb":
            return self._execute_pcb(op, file_path)
        elif self._is_project_file(file_path):
            return self._execute_project(op, file_path)
        else:
            return self._execute_schematic(op, file_path)

    @staticmethod
    def _is_project_file(file_path: Path) -> bool:
        """Check if the file is a project-level file (not schematic/PCB)."""
        name = file_path.name
        suffix = file_path.suffix
        return (
            name in ("sym-lib-table", "fp-lib-table")
            or suffix in (".kicad_dru", ".kicad_pro")
        )

    def _execute_create(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute a file-creation operation (no Transaction, no IR).

        Create operations generate new files from scratch. They do not need
        Transaction wrapping since there is nothing to roll back to.

        Args:
            op: Validated Operation from the schema.
            file_path: Resolved path for the new file.

        Returns:
            Dict with: success, operation, target_file, details.
        """
        root = op.root
        handler = _CREATE_HANDLERS.get(root.op_type)
        if handler is None:
            raise ValueError(f"Unknown create op_type: {root.op_type!r}")

        details = handler(root, file_path)
        return {
            "success": True,
            "operation": root.op_type,
            "target_file": root.target_file,
            "details": details,
        }

    def _execute_schematic(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute an operation targeting a schematic file."""
        root = op.root

        parse_result = parse_schematic(file_path)
        ir = SchematicIR(_parse_result=parse_result)

        with Transaction(file_path) as txn:
            details = self._dispatch(root.op_type, root, ir, file_path)
            serialize_schematic(parse_result, file_path)
            content = file_path.read_text(encoding="utf-8")
            normalized = normalize_kicad_output(content)
            file_path.write_text(normalized, encoding="utf-8")
            txn.commit()

        return {
            "success": True,
            "operation": root.op_type,
            "target_file": root.target_file,
            "details": details,
        }

    def _execute_pcb(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute an operation targeting a PCB file."""
        root = op.root

        parse_result = parse_pcb(file_path)
        uuid_map = extract_uuids(parse_result.raw_content, "pcb")
        ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)

        with Transaction(file_path) as txn:
            details = self._dispatch_pcb(root.op_type, root, ir, file_path)

            # Skip kiutils serialization if the IR method already wrote directly
            # via raw S-expression manipulation (avoids data loss from kiutils)
            if not ir._raw_written:
                serialize_pcb(parse_result, file_path, uuid_map=uuid_map)

            txn.commit()

        return {
            "success": True,
            "operation": root.op_type,
            "target_file": root.target_file,
            "details": details,
        }

    def _dispatch(
        self,
        op_type: str,
        op: Any,
        ir: SchematicIR,
        file_path: Path,
    ) -> dict[str, Any]:
        """Dispatch to the appropriate schematic handler via registry.

        T-04-06: Exact string matching. Unknown op_type raises ValueError.

        Args:
            op_type: The operation type string.
            op: The operation's root model (e.g. AddComponentOp).
            ir: SchematicIR for the target file.
            file_path: Resolved path to the target file.

        Returns:
            Handler result dict.

        Raises:
            ValueError: For unknown op_type.
        """
        handler = _SCHEMATIC_HANDLERS.get(op_type)
        if handler is not None:
            return handler(op, ir, file_path)
        raise ValueError(f"Unknown op_type: {op_type!r}")

    def _dispatch_pcb(
        self,
        op_type: str,
        op: Any,
        ir: PcbIR,
        file_path: Path,
    ) -> dict[str, Any]:
        """Dispatch PCB-specific operations via registry.

        Args:
            op_type: The operation type string.
            op: The operation's root model.
            ir: PcbIR for the target PCB file.
            file_path: Resolved path to the target PCB file.

        Returns:
            Handler result dict.

        Raises:
            ValueError: For unknown op_type.
        """
        handler = _PCB_HANDLERS.get(op_type)
        if handler is not None:
            return handler(op, ir, file_path)
        raise ValueError(f"Unknown PCB op_type: {op_type!r}")

    def _execute_project(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute an operation targeting a project-level file.

        Handles sym-lib-table, fp-lib-table, .kicad_dru, and .kicad_pro files
        using the project module parsers and editors.

        Args:
            op: Validated Operation from the schema.
            file_path: Resolved path to the target file.

        Returns:
            Dict with: success, operation, target_file, details.
        """
        root = op.root
        details = self._dispatch_project(root.op_type, root, file_path)
        return {
            "success": True,
            "operation": root.op_type,
            "target_file": root.target_file,
            "details": details,
        }

    def _dispatch_project(
        self,
        op_type: str,
        op: Any,
        file_path: Path,
    ) -> dict[str, Any]:
        """Dispatch project-file operations via registry.

        Args:
            op_type: The operation type string.
            op: The operation's root model.
            file_path: Resolved path to the target file.

        Returns:
            Handler result dict.

        Raises:
            ValueError: For unknown op_type.
        """
        handler = _PROJECT_HANDLERS.get(op_type)
        if handler is not None:
            return handler(op, file_path)
        raise ValueError(f"Unknown project op_type: {op_type!r}")
