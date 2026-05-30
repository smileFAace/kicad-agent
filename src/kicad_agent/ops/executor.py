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

import dataclasses
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from kicad_agent.crossfile.atomic import AtomicOperation
from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ir.transaction import Transaction
from kicad_agent.ops.schema import Operation
from kicad_agent.parser import parse_pcb, parse_schematic
from kicad_agent.parser.uuid_extractor import extract_uuids
from kicad_agent.ops.ir_cache import CacheEntry, IRCache
from kicad_agent.ops.undo_stack import UndoStack
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

# Query handlers: (op, PcbIR, file_path) -> dict -- read-only, no Transaction, no serialization
_QUERY_HANDLERS: dict[str, Callable] = {}

# Cross-file handlers: (op, dict[Path, BaseIR], base_dir) -> dict
_CROSSFILE_HANDLERS: dict[str, Callable] = {}

# Set of op_types that use cross-file dispatch path
_CROSS_FILE_OP_TYPES = {"propagate_symbol_change"}

# Set of op_types that create new files (bypass file-existence check)
_CREATE_OP_TYPES = {"create_schematic", "create_pcb", "create_project", "create_symbol", "create_footprint"}


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


def register_query(op_type: str) -> Callable:
    """Decorator to register a read-only query operation handler."""
    def decorator(fn: Callable) -> Callable:
        _QUERY_HANDLERS[op_type] = fn
        return fn
    return decorator


def register_crossfile(op_type: str) -> Callable:
    """Decorator to register a cross-file operation handler."""
    def decorator(fn: Callable) -> Callable:
        _CROSSFILE_HANDLERS[op_type] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Shared handler helpers
# ---------------------------------------------------------------------------


def _validate_footprint_impl(footprint_lib_id: str, file_path: Path) -> dict[str, Any]:
    """Validate that a footprint exists in the available libraries.

    Parses the fp-lib-table to resolve the library nickname and checks
    if the footprint .kicad_mod file exists on disk.

    Args:
        footprint_lib_id: Footprint library reference, e.g. "Library:Footprint".
        file_path: Path to the target KiCad file (used to locate fp-lib-table).

    Returns:
        Dict with footprint_lib_id, valid (bool), and library_path or error.
    """
    from kicad_agent.lib_resolver import resolve_footprint_path

    try:
        resolved = resolve_footprint_path(footprint_lib_id, file_path)
        return {
            "footprint_lib_id": footprint_lib_id,
            "valid": True,
            "library_path": str(resolved),
        }
    except (ValueError, FileNotFoundError) as exc:
        return {
            "footprint_lib_id": footprint_lib_id,
            "valid": False,
            "error": str(exc),
        }


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
    return _validate_footprint_impl(op.footprint_lib_id, file_path)


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
    from kicad_agent.ops.erc_parser import parse_erc
    violations = parse_erc(file_path)
    return {"violations": [dataclasses.asdict(v) for v in violations]}


@register_schematic("extract_violation_positions")
def _handle_extract_violation_positions(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.erc_parser import extract_violation_positions
    positions = extract_violation_positions(file_path, op.violation_type)
    return {"positions": [dataclasses.asdict(p) for p in positions], "count": len(positions)}


@register_schematic("validate_hlabels")
def _handle_validate_hlabels(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
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
    from kicad_agent.ops.root_sheet import rebuild_root_sheet
    results = rebuild_root_sheet(file_path)
    return {
        "sheets_processed": len(results),
        "details": [dataclasses.asdict(r) for r in results],
    }


@register_schematic("embed_symbol")
def _handle_embed_symbol(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.swap_symbol import embed_symbol
    return embed_symbol(op, ir, file_path)


@register_schematic("swap_symbol")
def _handle_swap_symbol(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.swap_symbol import swap_symbol
    return swap_symbol(op, ir, file_path)


@register_schematic("remove_wire")
def _handle_remove_wire(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.remove_ops import remove_wire
    return remove_wire(op, ir, file_path, file_path.parent)


@register_schematic("remove_label")
def _handle_remove_label(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.remove_ops import remove_label
    return remove_label(op, ir, file_path, file_path.parent)


@register_schematic("remove_junction")
def _handle_remove_junction(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.remove_ops import remove_junction
    return remove_junction(op, ir, file_path, file_path.parent)


@register_schematic("remove_no_connect")
def _handle_remove_no_connect(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.remove_ops import remove_no_connect
    return remove_no_connect(op, ir, file_path, file_path.parent)


@register_schematic("add_sheet")
def _handle_add_sheet(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.sheet_ops import add_sheet
    return add_sheet(op, ir, file_path)


@register_schematic("add_sheet_pin")
def _handle_add_sheet_pin(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.sheet_ops import add_sheet_pin
    return add_sheet_pin(op, ir, file_path)


@register_schematic("navigate_hierarchy")
def _handle_navigate_hierarchy(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.sheet_ops import navigate_hierarchy
    return navigate_hierarchy(op, ir, file_path)


@register_schematic("update_symbols_from_library")
def _handle_update_symbols_from_library(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair import update_symbols_from_library
    return update_symbols_from_library(
        ir, file_path,
        references=op.references,
        dry_run=op.dry_run,
    )


@register_schematic("fix_shorted_nets")
def _handle_fix_shorted_nets(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair import fix_shorted_nets
    return fix_shorted_nets(
        ir, file_path,
        strategy=op.strategy,
        keep_nets=op.keep_nets,
        dry_run=op.dry_run,
    )


@register_schematic("fix_pin_type_mismatches")
def _handle_fix_pin_type_mismatches(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair import fix_pin_type_mismatches
    return fix_pin_type_mismatches(
        ir, file_path,
        pin_type_map=op.pin_type_map,
        dry_run=op.dry_run,
    )


@register_schematic("place_missing_units")
def _handle_place_missing_units(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair import place_missing_units
    return place_missing_units(
        ir, file_path,
        references=op.references,
        offset_x=op.offset_x,
        offset_y=op.offset_y,
        dry_run=op.dry_run,
    )


@register_schematic("remove_dangling_wires")
def _handle_remove_dangling_wires(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair import remove_dangling_wires
    return remove_dangling_wires(
        ir, file_path,
        max_length_mm=op.max_length_mm,
        dry_run=op.dry_run,
    )


@register_schematic("break_wire_shorts")
def _handle_break_wire_shorts(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair import break_wire_shorts
    return break_wire_shorts(
        ir, file_path,
        net_pairs=op.net_pairs,
        strategy=op.strategy,
        dry_run=op.dry_run,
    )


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
    return _validate_footprint_impl(op.footprint_lib_id, file_path)


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


@register_create("create_footprint")
def _handle_create_footprint(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.create_file import create_footprint
    return create_footprint(op, file_path)


# ---------------------------------------------------------------------------
# Query handler implementations (read-only, no Transaction, no serialization)
# ---------------------------------------------------------------------------


@register_query("query_connectivity")
def _handle_query_connectivity(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.connectivity_query import handle_connectivity_query
    return handle_connectivity_query(op, ir, file_path)


# ---------------------------------------------------------------------------
# Cross-file handler implementations
# ---------------------------------------------------------------------------


@register_crossfile("propagate_symbol_change")
def _handle_propagate_symbol_change(
    op: Any, ir_map: dict[Path, Any], base_dir: Path
) -> dict[str, Any]:
    from kicad_agent.crossfile.propagation import (
        propagate_footprint_ref,
        propagate_symbol_ref,
    )
    from kicad_agent.ir.pcb_ir import PcbIR
    from kicad_agent.ir.schematic_ir import SchematicIR

    results = []
    for file_path, ir in ir_map.items():
        if isinstance(ir, SchematicIR):
            result = propagate_symbol_ref(ir, op.old_lib_id, op.new_lib_id)
            results.append({"file": str(file_path.name), "type": "schematic", "updated": result.updated_count})
        elif isinstance(ir, PcbIR):
            result = propagate_footprint_ref(ir, op.old_lib_id, op.new_lib_id)
            results.append({"file": str(file_path.name), "type": "pcb", "updated": result.updated_count})
    return {"files_modified": results, "total_updated": sum(r["updated"] for r in results)}


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

    def __init__(self, base_dir: Path, *, cache: Optional[IRCache] = None, undo_stack: Optional[UndoStack] = None) -> None:
        self._base_dir = base_dir
        self._cache = cache
        self._undo_stack = undo_stack

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

        # Security (T-24-01): path confinement — reject paths that escape project dir
        resolved = file_path.resolve()
        base_resolved = self._base_dir.resolve()
        if not resolved.is_relative_to(base_resolved):
            raise ValueError(
                f"Security: path escapes project directory: {root.target_file}"
            )

        # Cross-file operations: coordinate multiple files atomically
        if root.op_type in _CROSS_FILE_OP_TYPES:
            return self._execute_cross_file(op, file_path)

        # Create operations: file does not exist yet (bypass existence check)
        if root.op_type in _CREATE_OP_TYPES:
            return self._execute_create(op, file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Target file not found: {file_path}")

        # Query operations: read-only, no Transaction, no serialization
        if root.op_type in _QUERY_HANDLERS:
            return self._execute_query(op, file_path)

        # Clear IR registry to avoid stale registrations across operations
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

    def _execute_query(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute a read-only query operation (no Transaction, no serialization).

        Query operations parse the file and build IR, but skip Transaction
        wrapping, serialization, and file writes. The file mtime is unchanged.

        Args:
            op: Validated Operation from the schema.
            file_path: Resolved path to the target file.

        Returns:
            Dict with: success, operation, target_file, details.
        """
        root = op.root

        cached_entry = self._cache.get(file_path) if self._cache else None
        if cached_entry is not None:
            parse_result = cached_entry.parse_result
            uuid_map = cached_entry.uuid_map
        else:
            parse_result = parse_pcb(file_path)
            uuid_map = extract_uuids(parse_result.raw_content, "pcb")
            if self._cache:
                self._cache.put(file_path, CacheEntry(parse_result=parse_result, uuid_map=uuid_map))

        ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)
        details = self._dispatch_query(root.op_type, root, ir, file_path)
        return {
            "success": True,
            "operation": root.op_type,
            "target_file": root.target_file,
            "details": details,
        }

    def _dispatch_query(
        self,
        op_type: str,
        op: Any,
        ir: PcbIR,
        file_path: Path,
    ) -> dict[str, Any]:
        """Dispatch query operations via registry.

        Args:
            op_type: The operation type string.
            op: The operation's root model.
            ir: PcbIR for the target PCB file.
            file_path: Resolved path to the target file.

        Returns:
            Handler result dict.

        Raises:
            ValueError: For unknown op_type.
        """
        handler = _QUERY_HANDLERS.get(op_type)
        if handler is not None:
            return handler(op, ir, file_path)
        raise ValueError(f"Unknown query op_type: {op_type!r}")

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
        # Security (T-24-01): path confinement for create operations too
        resolved = file_path.resolve()
        base_resolved = self._base_dir.resolve()
        if not resolved.is_relative_to(base_resolved):
            raise ValueError(
                f"Security: path escapes project directory: {op.root.target_file}"
            )

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

        # Capture pre-mutation content for undo stack
        pre_content: Optional[str] = None
        if self._undo_stack is not None:
            pre_content = file_path.read_text(encoding="utf-8")

        cached_entry = self._cache.get(file_path) if self._cache else None
        if cached_entry is not None:
            parse_result = cached_entry.parse_result
        else:
            parse_result = parse_schematic(file_path)
            if self._cache:
                self._cache.put(file_path, CacheEntry(parse_result=parse_result))

        ir = SchematicIR(_parse_result=parse_result)

        with Transaction(file_path) as txn:
            details = self._dispatch(root.op_type, root, ir, file_path)
            serialize_schematic(parse_result, file_path)
            content = file_path.read_text(encoding="utf-8")
            normalized = normalize_kicad_output(content)
            file_path.write_text(normalized, encoding="utf-8")
            txn.commit()

            # Capture post-mutation content for undo stack
            if self._undo_stack is not None and pre_content is not None:
                post_content = file_path.read_text(encoding="utf-8")
                post_mtime = file_path.stat().st_mtime_ns
                self._undo_stack.push(file_path, pre_content, post_content, root.op_type, post_mtime)

        # Invalidate old cache entry and store fresh one after write
        if self._cache:
            self._cache.invalidate(file_path)
            self._cache.put(file_path, CacheEntry(parse_result=parse_result))

        return {
            "success": True,
            "operation": root.op_type,
            "target_file": root.target_file,
            "details": details,
        }

    def _execute_pcb(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute an operation targeting a PCB file."""
        root = op.root

        # Capture pre-mutation content for undo stack
        pre_content: Optional[str] = None
        if self._undo_stack is not None:
            pre_content = file_path.read_text(encoding="utf-8")

        cached_entry = self._cache.get(file_path) if self._cache else None
        if cached_entry is not None:
            parse_result = cached_entry.parse_result
            uuid_map = cached_entry.uuid_map
        else:
            parse_result = parse_pcb(file_path)
            uuid_map = extract_uuids(parse_result.raw_content, "pcb")
            if self._cache:
                self._cache.put(file_path, CacheEntry(parse_result=parse_result, uuid_map=uuid_map))

        ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)

        with Transaction(file_path) as txn:
            details = self._dispatch_pcb(root.op_type, root, ir, file_path)

            # Skip kiutils serialization if the IR method already wrote directly
            # via raw S-expression manipulation (avoids data loss from kiutils)
            if not ir._raw_written:
                serialize_pcb(parse_result, file_path, uuid_map=uuid_map)

            txn.commit()

            # Capture post-mutation content for undo stack
            if self._undo_stack is not None and pre_content is not None:
                post_content = file_path.read_text(encoding="utf-8")
                post_mtime = file_path.stat().st_mtime_ns
                self._undo_stack.push(file_path, pre_content, post_content, root.op_type, post_mtime)

        # Invalidate old cache entry and store fresh one after write
        if self._cache:
            self._cache.invalidate(file_path)
            self._cache.put(file_path, CacheEntry(parse_result=parse_result, uuid_map=uuid_map))

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
        pre_content: Optional[str] = None
        if self._undo_stack is not None and file_path.exists():
            pre_content = file_path.read_text(encoding="utf-8")
        details = self._dispatch_project(root.op_type, root, file_path)
        if self._undo_stack is not None and pre_content is not None:
            post_content = file_path.read_text(encoding="utf-8")
            post_mtime = file_path.stat().st_mtime_ns
            self._undo_stack.push(file_path, pre_content, post_content, root.op_type, post_mtime)
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

    def _execute_cross_file(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute a cross-file operation targeting multiple files atomically."""
        root = op.root

        # Resolve all target file paths relative to base_dir
        file_paths = self._resolve_cross_file_paths(root)
        if not file_paths:
            raise ValueError(f"Cross-file operation {root.op_type!r} requires at least one target file")

        # Security (T-24-01): path confinement for ALL files in cross-file operation
        base_resolved = self._base_dir.resolve()
        for fp in file_paths:
            if not fp.resolve().is_relative_to(base_resolved):
                raise ValueError(
                    f"Security: path escapes project directory in cross-file op: {fp}"
                )
            if not fp.exists():
                raise FileNotFoundError(f"Cross-file target not found: {fp}")

        # Clear IR registry to avoid stale registrations
        _clear_registry()

        # Phase 1: Parse all files and build IR map (XFILE-07: validate before Transaction)
        ir_map: dict[Path, Any] = {}
        for fp in file_paths:
            if fp.suffix == ".kicad_pcb":
                parse_result = parse_pcb(fp)
                uuid_map = extract_uuids(parse_result.raw_content, "pcb")
                ir_map[fp] = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)
            elif fp.suffix == ".kicad_sch":
                parse_result = parse_schematic(fp)
                ir_map[fp] = SchematicIR(_parse_result=parse_result)
            else:
                raise ValueError(f"Cross-file operation unsupported file type: {fp.suffix}")

        # Phase 2: Capture pre-mutation content for undo stack
        pre_contents: dict[Path, str] = {}
        if self._undo_stack is not None:
            for fp in file_paths:
                if fp.exists():
                    pre_contents[fp] = fp.read_text(encoding="utf-8")

        # Phase 3: Open AtomicOperation and execute handler
        with AtomicOperation(file_paths) as atomic:
            handler = _CROSSFILE_HANDLERS.get(root.op_type)
            if handler is None:
                raise ValueError(f"Unknown cross-file op_type: {root.op_type!r}")

            details = handler(root, ir_map, self._base_dir)

            # Phase 4: Serialize all dirty IRs
            for fp, ir in ir_map.items():
                if ir.dirty:
                    if isinstance(ir, PcbIR):
                        parse_result = ir._parse_result
                        uuid_map = ir.uuid_map
                        if not ir._raw_written:
                            serialize_pcb(parse_result, fp, uuid_map=uuid_map)
                    elif isinstance(ir, SchematicIR):
                        serialize_schematic(ir._parse_result, fp)
                        content = fp.read_text(encoding="utf-8")
                        normalized = normalize_kicad_output(content)
                        fp.write_text(normalized, encoding="utf-8")

            # Phase 5: Commit atomic operation
            atomic_result = atomic.commit()
            if not atomic_result.success:
                return {
                    "success": False,
                    "operation": root.op_type,
                    "details": details,
                    "error": atomic_result.error,
                }

        # Push undo entries for all dirty files after successful commit
        if self._undo_stack is not None:
            for fp, ir in ir_map.items():
                if ir.dirty and fp in pre_contents:
                    post_content = fp.read_text(encoding="utf-8")
                    post_mtime = fp.stat().st_mtime_ns
                    self._undo_stack.push(fp, pre_contents[fp], post_content, root.op_type, post_mtime)

        return {
            "success": True,
            "operation": root.op_type,
            "details": details,
        }

    def _resolve_cross_file_paths(self, op: Any) -> list[Path]:
        """Resolve file paths from a cross-file operation schema."""
        if hasattr(op, "target_files"):
            return [self._base_dir / tf for tf in op.target_files]
        return []

    # ------------------------------------------------------------------
    # Batch execution: single parse/write per file
    # ------------------------------------------------------------------

    def execute_batch(self, ops: list[Operation]) -> dict[str, Any]:
        """Execute multiple operations with single parse/write per file.

        Groups ops by target file, parses each once, applies all mutations,
        serializes once per file. Validates ALL operations before executing ANY.

        Not supported: cross-file ops and create ops -- use execute() for those.

        Args:
            ops: List of validated Operation instances to execute.

        Returns:
            Dict with: success, results (list of per-op result dicts).
            On validation failure: success=False, validation_errors list.
        """
        # Early return for empty batch
        if not ops:
            return {"success": True, "results": []}

        # Reject unsupported op types
        unsupported: list[str] = []
        for op in ops:
            root = op.root
            if root.op_type in _CROSS_FILE_OP_TYPES:
                unsupported.append(root.op_type)
            elif root.op_type in _CREATE_OP_TYPES:
                unsupported.append(root.op_type)
        if unsupported:
            return {
                "success": False,
                "results": [],
                "error": f"Batch rejected: unsupported op types: {sorted(set(unsupported))}",
            }

        # Security (T-24-01): path confinement — validate all paths first
        base_resolved = self._base_dir.resolve()
        for op in ops:
            file_path = self._base_dir / op.root.target_file
            resolved = file_path.resolve()
            if not resolved.is_relative_to(base_resolved):
                return {
                    "success": False,
                    "results": [],
                    "error": f"Security: path escapes project directory: {op.root.target_file}",
                }

        # Group by target file
        file_ops: dict[Path, list[Operation]] = {}
        file_order: list[Path] = []
        for op in ops:
            fp = (self._base_dir / op.root.target_file).resolve()
            if fp not in file_ops:
                file_ops[fp] = []
                file_order.append(fp)
            file_ops[fp].append(op)

        # Clear IR registry once for the entire batch
        _clear_registry()

        # Phase 1 — Parse and validate ALL operations
        ir_map: dict[Path, Any] = {}
        parse_result_map: dict[Path, Any] = {}  # file_path -> parse_result
        uuid_map_store: dict[Path, Any] = {}  # file_path -> uuid_map (PCB only)
        validation_errors: list[str] = []

        for file_path in file_order:
            ops_for_file = file_ops[file_path]

            if not file_path.exists():
                for op in ops_for_file:
                    validation_errors.append(
                        f"Target file not found: {op.root.target_file}"
                    )
                continue

            # Parse the file (with cache if available)
            if file_path.suffix == ".kicad_pcb":
                cached_entry = self._cache.get(file_path) if self._cache else None
                if cached_entry is not None:
                    parse_result = cached_entry.parse_result
                    uuid_map = cached_entry.uuid_map
                else:
                    parse_result = parse_pcb(file_path)
                    uuid_map = extract_uuids(parse_result.raw_content, "pcb")
                    if self._cache:
                        self._cache.put(
                            file_path,
                            CacheEntry(parse_result=parse_result, uuid_map=uuid_map),
                        )
                parse_result_map[file_path] = parse_result
                uuid_map_store[file_path] = uuid_map
                ir_map[file_path] = PcbIR(
                    _parse_result=parse_result, _uuid_map=uuid_map
                )
            else:
                # Schematic (default)
                cached_entry = self._cache.get(file_path) if self._cache else None
                if cached_entry is not None:
                    parse_result = cached_entry.parse_result
                else:
                    parse_result = parse_schematic(file_path)
                    if self._cache:
                        self._cache.put(
                            file_path, CacheEntry(parse_result=parse_result)
                        )
                parse_result_map[file_path] = parse_result
                ir_map[file_path] = SchematicIR(_parse_result=parse_result)

            # Validate handlers exist for all ops targeting this file
            for op in ops_for_file:
                root = op.root
                if file_path.suffix == ".kicad_pcb":
                    handler = _PCB_HANDLERS.get(root.op_type)
                elif self._is_project_file(file_path):
                    handler = _PROJECT_HANDLERS.get(root.op_type)
                else:
                    handler = _SCHEMATIC_HANDLERS.get(root.op_type)

                if handler is None:
                    validation_errors.append(
                        f"No handler for op_type '{root.op_type}' on "
                        f"{file_path.suffix or file_path.name}"
                    )

        if validation_errors:
            return {
                "success": False,
                "results": [],
                "validation_errors": validation_errors,
                "error": f"Batch rejected: {len(validation_errors)} validation "
                f"failure{'s' if len(validation_errors) != 1 else ''}",
            }

        # Phase 2 — Capture pre-mutation content for undo stack
        pre_contents: dict[Path, str] = {}
        if self._undo_stack is not None:
            for file_path in file_order:
                if file_path.exists():
                    pre_contents[file_path] = file_path.read_text(encoding="utf-8")

        # Phase 3 — Apply mutations and serialize (once per file)
        all_results: list[dict[str, Any]] = []

        for file_path in file_order:
            ops_for_file = file_ops[file_path]
            ir = ir_map[file_path]
            parse_result = parse_result_map[file_path]

            with Transaction(file_path) as txn:
                for op in ops_for_file:
                    root = op.root
                    if file_path.suffix == ".kicad_pcb":
                        details = self._dispatch_pcb(root.op_type, root, ir, file_path)
                    elif self._is_project_file(file_path):
                        details = self._dispatch_project(
                            root.op_type, root, file_path
                        )
                    else:
                        details = self._dispatch(root.op_type, root, ir, file_path)

                    all_results.append({
                        "success": True,
                        "operation": root.op_type,
                        "target_file": root.target_file,
                        "details": details,
                    })

                # Serialize once per file
                if file_path.suffix == ".kicad_pcb":
                    uuid_map = uuid_map_store.get(file_path)
                    if not ir._raw_written:
                        serialize_pcb(parse_result, file_path, uuid_map=uuid_map)
                elif not self._is_project_file(file_path):
                    serialize_schematic(parse_result, file_path)
                    content = file_path.read_text(encoding="utf-8")
                    normalized = normalize_kicad_output(content)
                    file_path.write_text(normalized, encoding="utf-8")

                txn.commit()

                # Push undo entry for this file (M-05: synthetic batch op_type)
                if self._undo_stack is not None and file_path in pre_contents:
                    post_content = file_path.read_text(encoding="utf-8")
                    post_mtime = file_path.stat().st_mtime_ns
                    op_type = f"batch[{len(ops_for_file)}]"
                    self._undo_stack.push(file_path, pre_contents[file_path], post_content, op_type, post_mtime)

            # Invalidate old cache entry and store fresh one after write
            if self._cache:
                self._cache.invalidate(file_path)
                if file_path.suffix == ".kicad_pcb":
                    self._cache.put(
                        file_path,
                        CacheEntry(
                            parse_result=parse_result,
                            uuid_map=uuid_map_store.get(file_path),
                        ),
                    )
                elif not self._is_project_file(file_path):
                    self._cache.put(
                        file_path, CacheEntry(parse_result=parse_result)
                    )

        return {"success": True, "results": all_results}

    # ------------------------------------------------------------------
    # Undo/redo methods
    # ------------------------------------------------------------------

    def undo(self, target_file: Optional[str] = None) -> dict[str, Any]:
        """Undo the most recent mutation for a file.

        Args:
            target_file: Relative path to the file. If None, undoes the latest
                mutation across all files.

        Returns:
            Dict with success, undone_op, target_file on success.
            Dict with success=False, error on failure.
        """
        if self._undo_stack is None:
            return {"success": False, "error": "Undo stack not enabled"}

        if target_file is not None:
            file_path = (self._base_dir / target_file).resolve()
            entry = self._undo_stack.pop_undo(file_path)
        else:
            entry = self._undo_stack.pop_latest_undo()

        if entry is None:
            return {"success": False, "error": "No operations to undo"}

        # H-04: Symlink protection (mirrors Transaction H-02 control)
        if entry.file_path.is_symlink():
            return {"success": False, "error": "Security: target file is a symlink"}

        # M-08: Check parent directory exists before writing
        if not entry.file_path.parent.exists():
            return {"success": False, "error": "Cannot undo: parent directory no longer exists"}

        # L-05: Warn if file was modified externally since snapshot
        if entry.post_mtime and entry.file_path.exists():
            current_mtime = entry.file_path.stat().st_mtime_ns
            if current_mtime != entry.post_mtime:
                logger.warning(
                    "Undo: file modified externally since snapshot: %s",
                    entry.file_path,
                )

        # L-04: Use newline="" to preserve exact byte content (LF line endings)
        try:
            entry.file_path.write_text(entry.pre_content, encoding="utf-8", newline="")
        except OSError as e:
            # Reverse: pop_redo moves entry back to undo so user can retry
            self._undo_stack.pop_redo(entry.file_path)
            return {"success": False, "error": f"Write error during undo: {e}"}

        # Invalidate cache for this file
        if self._cache:
            self._cache.invalidate(entry.file_path)

        return {
            "success": True,
            "undone_op": entry.op_type,
            "target_file": str(entry.file_path.relative_to(self._base_dir)),
        }

    def redo(self, target_file: Optional[str] = None) -> dict[str, Any]:
        """Redo the most recently undone mutation for a file.

        Args:
            target_file: Relative path to the file. If None, redoes the latest
                undone mutation across all files.

        Returns:
            Dict with success, redone_op, target_file on success.
            Dict with success=False, error on failure.
        """
        if self._undo_stack is None:
            return {"success": False, "error": "Undo stack not enabled"}

        if target_file is not None:
            file_path = (self._base_dir / target_file).resolve()
            entry = self._undo_stack.pop_redo(file_path)
        else:
            entry = self._undo_stack.pop_latest_redo()

        if entry is None:
            return {"success": False, "error": "No operations to redo"}

        # H-04: Symlink protection
        if entry.file_path.is_symlink():
            return {"success": False, "error": "Security: target file is a symlink"}

        # M-08: Check parent directory exists before writing
        if not entry.file_path.parent.exists():
            return {"success": False, "error": "Cannot redo: parent directory no longer exists"}

        # L-05: Warn if file was modified externally since snapshot
        if entry.post_mtime and entry.file_path.exists():
            current_mtime = entry.file_path.stat().st_mtime_ns
            if current_mtime != entry.post_mtime:
                logger.warning(
                    "Redo: file modified externally since snapshot: %s",
                    entry.file_path,
                )

        # L-04: Use newline="" to preserve exact byte content
        try:
            entry.file_path.write_text(entry.post_content, encoding="utf-8", newline="")
        except OSError as e:
            # Reverse: pop_undo moves entry back to redo so user can retry
            self._undo_stack.pop_undo(entry.file_path)
            return {"success": False, "error": f"Write error during redo: {e}"}

        # Invalidate cache for this file
        if self._cache:
            self._cache.invalidate(entry.file_path)

        return {
            "success": True,
            "redone_op": entry.op_type,
            "target_file": str(entry.file_path.relative_to(self._base_dir)),
        }
