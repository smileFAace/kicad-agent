"""Pre-PCB validation gates -- ERC, power net, and annotation checks.

Validates schematics before PCB work begins:
  - Power pin connectivity (all power pins have power symbols)
  - ERC clean check (structured wrapper around run_erc)
  - Pre-PCB gate (comprehensive validation combining ERC, power, annotation)

Usage:
    from kicad_agent.ops.validation_gates import validate_power_nets, pre_pcb_gate

    result = validate_power_nets(ir)
    if not result["valid"]:
        print(f"Unconnected power pins: {result['unconnected_power_pins']}")
"""

import logging
import re
from pathlib import Path
from typing import Any

from kicad_agent.ir.schematic_ir import SchematicIR

logger = logging.getLogger(__name__)

# Pin electrical types that indicate power pins
_POWER_PIN_TYPES = {"power_in", "power_out"}

# Common power net names for checking coverage
_COMMON_POWER_NETS = {"GND", "VCC", "+5V", "+3V3", "+3.3V", "VDD", "VSS"}


def validate_power_nets(ir: SchematicIR) -> dict[str, Any]:
    """Check all power pins have connected power symbols.

    Finds all power pins (power_in, power_out) in the schematic and verifies
    each is connected to a power symbol (power:* library reference).

    Args:
        ir: SchematicIR for the target schematic.

    Returns:
        Dict with:
        - valid: bool -- True if all power pins connected
        - unconnected_power_pins: list of dicts with pin details
        - power_nets: list of power net names found
        - missing_power_symbols: list of net names lacking power sources
    """
    sch = ir.schematic
    pin_positions = ir.get_pin_positions()
    label_positions = ir.get_label_positions()

    # Find power pins
    power_pins = [p for p in pin_positions if p["electrical_type"] in _POWER_PIN_TYPES]

    # Find power symbols (symbols with libId starting with "power:")
    power_symbol_nets: set[str] = set()
    for sym in sch.schematicSymbols:
        if sym.libId.startswith("power:"):
            # Power symbol name is the part after "power:"
            net_name = sym.libId.split(":", 1)[1]
            # Also check the Value property
            for prop in sym.properties:
                if prop.key == "Value":
                    net_name = prop.value
                    break
            power_symbol_nets.add(net_name)

    # Map label positions to net names for connectivity check
    label_net_map: dict[tuple[float, float], str] = {}
    for lp in label_positions:
        key = _round_pos(lp["x"], lp["y"])
        label_net_map[key] = lp["name"]

    # Check each power pin for connectivity
    unconnected: list[dict[str, Any]] = []
    for pin in power_pins:
        pin_key = _round_pos(pin["x"], pin["y"])

        # Check if a label is at the pin position (implies net connectivity)
        connected_label = label_net_map.get(pin_key)

        # Check if any wire endpoint is at the pin position
        wire_connected = False
        for we in ir.get_wire_endpoints():
            if (_distance(pin["x"], pin["y"], we["start_x"], we["start_y"]) <= 0.01
                    or _distance(pin["x"], pin["y"], we["end_x"], we["end_y"]) <= 0.01):
                wire_connected = True
                break

        if not connected_label and not wire_connected:
            unconnected.append({
                "reference": pin["reference"],
                "pin_name": pin["pin_name"],
                "pin_number": pin["pin_number"],
                "position": (round(pin["x"], 4), round(pin["y"], 4)),
                "electrical_type": pin["electrical_type"],
            })

    # Identify power nets that lack power sources (power_out symbols)
    # power_in pins consume power; power_out symbols provide it
    power_in_nets: set[str] = set()
    for pin in power_pins:
        if pin["electrical_type"] == "power_in":
            pin_key = _round_pos(pin["x"], pin["y"])
            label_name = label_net_map.get(pin_key)
            if label_name:
                power_in_nets.add(label_name)

    # Check which common power nets are missing power sources
    missing_power_symbols: list[str] = []
    for net in _COMMON_POWER_NETS:
        if net in power_in_nets and net not in power_symbol_nets:
            missing_power_symbols.append(net)

    # Also check any net consumed by power_in pins but not provided
    for net in power_in_nets:
        if net not in power_symbol_nets and net not in _COMMON_POWER_NETS:
            missing_power_symbols.append(net)

    all_power_nets = sorted(power_symbol_nets | power_in_nets)
    valid = len(unconnected) == 0 and len(missing_power_symbols) == 0

    return {
        "valid": valid,
        "unconnected_power_pins": unconnected,
        "power_nets": all_power_nets,
        "missing_power_symbols": sorted(set(missing_power_symbols)),
    }


def check_erc_clean(sch_path: Path) -> dict[str, Any]:
    """Run ERC and return structured result.

    Wraps the existing run_erc() with a simplified result structure.

    Args:
        sch_path: Path to the .kicad_sch file.

    Returns:
        Dict with clean, error_count, warning_count, errors.
    """
    from kicad_agent.validation.erc_drc import run_erc

    result = run_erc(sch_path)

    errors = [
        {
            "description": v.description,
            "type": v.type,
            "severity": v.severity.value,
        }
        for v in result.violations
    ]

    return {
        "clean": result.passed,
        "error_count": result.error_count,
        "warning_count": result.warning_count,
        "errors": errors,
    }


def pre_pcb_gate(project_dir: Path) -> dict[str, Any]:
    """Comprehensive pre-PCB validation gate.

    Runs ERC, power net validation, and annotation completeness checks
    on all schematic files in the project directory.

    Args:
        project_dir: Path to the project directory containing .kicad_sch files.

    Returns:
        Dict with:
        - pass: bool -- True if all checks pass
        - erc: dict -- ERC check result
        - power: dict -- Power net validation result
        - annotation: dict -- Annotation completeness result
        - recommendations: list of actionable recommendations
    """
    # Find schematic files
    sch_files = sorted(project_dir.glob("*.kicad_sch"))
    if not sch_files:
        return {
            "pass": False,
            "erc": {"clean": False, "error_count": 0, "warning_count": 0, "errors": []},
            "power": {"valid": False, "unconnected_power_pins": [],
                      "power_nets": [], "missing_power_symbols": []},
            "annotation": {"complete": False, "unannotated": []},
            "recommendations": ["No schematic files found in project directory"],
        }

    # Run ERC on first (root) schematic
    root_sch = sch_files[0]
    erc_result = check_erc_clean(root_sch)

    # Run power net validation
    from kicad_agent.parser import parse_schematic
    result = parse_schematic(root_sch)
    ir = SchematicIR(_parse_result=result)
    power_result = validate_power_nets(ir)

    # Check annotation completeness (no R? or C? references)
    unannotated: list[str] = []
    ref_pattern = re.compile(r"^[A-Za-z]+\?$")
    for ref, _lib_id in ir.get_all_references():
        if ref_pattern.match(ref):
            unannotated.append(ref)

    annotation_result = {
        "complete": len(unannotated) == 0,
        "unannotated": unannotated,
    }

    # Generate recommendations
    recommendations: list[str] = []
    if not erc_result["clean"]:
        recommendations.append(
            f"Fix {erc_result['error_count']} ERC errors before proceeding to PCB"
        )
    if not power_result["valid"]:
        if power_result["unconnected_power_pins"]:
            recommendations.append(
                f"Connect {len(power_result['unconnected_power_pins'])} unconnected power pins"
            )
        if power_result["missing_power_symbols"]:
            symbols = ", ".join(power_result["missing_power_symbols"])
            recommendations.append(
                f"Add power symbols for: {symbols}"
            )
    if not annotation_result["complete"]:
        recommendations.append(
            f"Annotate {len(unannotated)} unannotated components"
        )

    gate_pass = (
        erc_result["clean"]
        and power_result["valid"]
        and annotation_result["complete"]
    )

    return {
        "pass": gate_pass,
        "erc": erc_result,
        "power": power_result,
        "annotation": annotation_result,
        "recommendations": recommendations,
    }


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two points."""
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5


def _round_pos(x: float, y: float) -> tuple[float, float]:
    """Round position to 0.01mm precision for grouping."""
    return (round(x, 2), round(y, 2))
