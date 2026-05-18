"""Round-trip stability validator for KiCad files.

Implements the two-pass stability test:
1. Parse original, serialize to pass1 (with UUID re-injection for PCB/footprint)
2. Parse pass1, serialize to pass2
3. Compare pass1 == pass2 byte-for-byte

The first pass normalizes formatting (tabs to spaces, collapses multi-line
tokens). The second pass produces identical output if serialization is
deterministic -- which proves the round-trip is stable.

Usage:
    from kicad_agent.validation.roundtrip import round_trip_stable, round_trip_compare

    stable = round_trip_stable(path, tmp_dir)
    result = round_trip_compare(path, tmp_dir)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from kicad_agent.parser.schematic_parser import parse_schematic
from kicad_agent.parser.pcb_parser import parse_pcb
from kicad_agent.parser.symbol_parser import parse_symbol_lib
from kicad_agent.parser.footprint_parser import parse_footprint
from kicad_agent.parser.uuid_extractor import extract_uuids
from kicad_agent.serializer.schematic_ser import serialize_schematic
from kicad_agent.serializer.pcb_ser import serialize_pcb
from kicad_agent.serializer.symbol_ser import serialize_symbol_lib
from kicad_agent.serializer.footprint_ser import serialize_footprint
from kicad_agent.validation.constants import SUFFIX_MAP

# Dispatch table mapping file_type to (parse_func, serialize_func)
_DISPATCH_TABLE: dict[str, tuple[object, object]] = {
    "schematic": (parse_schematic, serialize_schematic),
    "pcb": (parse_pcb, serialize_pcb),
    "symbol_lib": (parse_symbol_lib, serialize_symbol_lib),
    "footprint": (parse_footprint, serialize_footprint),
}


def _get_parse_func(file_type: str):
    """Get the parse function for a file type."""
    if file_type not in _DISPATCH_TABLE:
        raise ValueError(f"Unknown file type: {file_type}")
    return _DISPATCH_TABLE[file_type][0]


def _get_serialize_func(file_type: str):
    """Get the serialize function for a file type."""
    if file_type not in _DISPATCH_TABLE:
        raise ValueError(f"Unknown file type: {file_type}")
    return _DISPATCH_TABLE[file_type][1]


@dataclass(frozen=True)
class RoundTripResult:
    """Detailed result of a two-pass round-trip stability test.

    Attributes:
        is_stable: True if pass1 output is byte-identical to pass2 output.
        original_path: Path to the original file.
        pass1_path: Path to the first parse->serialize output.
        pass2_path: Path to the second parse->serialize output.
        file_type: One of 'schematic', 'pcb', 'symbol_lib', 'footprint'.
        uuid_preserved: True if UUID count matches (PCB/footprint only).
        error: Error message if any step failed.
    """

    is_stable: bool
    original_path: Path
    pass1_path: Optional[Path] = None
    pass2_path: Optional[Path] = None
    file_type: str = ""
    uuid_preserved: Optional[bool] = None
    error: Optional[str] = None


def _do_pass(
    input_path: Path,
    output_path: Path,
    file_type: str,
    needs_uuid: bool,
) -> None:
    """Execute a single parse->serialize pass.

    Args:
        input_path: File to parse.
        output_path: Where to write serialized output.
        file_type: One of 'schematic', 'pcb', 'symbol_lib', 'footprint'.
        needs_uuid: Whether to extract/re-inject UUIDs (PCB/footprint).
    """
    parse_func = _get_parse_func(file_type)
    serialize_func = _get_serialize_func(file_type)

    parse_result = parse_func(input_path)

    if needs_uuid:
        uuid_map = extract_uuids(parse_result.raw_content, file_type)
        serialize_func(parse_result, output_path, uuid_map=uuid_map)
    else:
        serialize_func(parse_result, output_path)


def round_trip_stable(path: Path, tmp_dir: Path) -> bool:
    """Test two-pass round-trip stability for a KiCad file.

    Parse->serialize->parse->serialize. If pass1 output is byte-identical
    to pass2 output, the serialization is stable.

    Args:
        path: Path to a KiCad file (.kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod).
        tmp_dir: Temporary directory for intermediate files.

    Returns:
        True if pass1 == pass2 (byte-identical), False otherwise.
    """
    suffix = path.suffix
    if suffix not in SUFFIX_MAP:
        raise ValueError(f"Unknown KiCad file type: {suffix}")

    file_type, needs_uuid = SUFFIX_MAP[suffix]

    pass1_dir = tmp_dir / "pass1"
    pass2_dir = tmp_dir / "pass2"
    pass1_dir.mkdir(parents=True, exist_ok=True)
    pass2_dir.mkdir(parents=True, exist_ok=True)

    pass1_path = pass1_dir / path.name
    pass2_path = pass2_dir / path.name

    # First pass: parse original -> serialize -> pass1
    _do_pass(path, pass1_path, file_type, needs_uuid)

    # Second pass: parse pass1 -> serialize -> pass2
    _do_pass(pass1_path, pass2_path, file_type, needs_uuid)

    # Compare
    return pass1_path.read_text(encoding="utf-8") == pass2_path.read_text(
        encoding="utf-8"
    )


def round_trip_compare(path: Path, tmp_dir: Path) -> RoundTripResult:
    """Detailed two-pass round-trip comparison for a KiCad file.

    Same logic as round_trip_stable but returns a detailed RoundTripResult
    with all intermediate file paths, UUID preservation status, and errors.

    Args:
        path: Path to a KiCad file.
        tmp_dir: Temporary directory for intermediate files.

    Returns:
        RoundTripResult with stability status and details.
    """
    suffix = path.suffix
    if suffix not in SUFFIX_MAP:
        return RoundTripResult(
            is_stable=False,
            original_path=path,
            error=f"Unknown KiCad file type: {suffix}",
        )

    file_type, needs_uuid = SUFFIX_MAP[suffix]

    pass1_dir = tmp_dir / "pass1"
    pass2_dir = tmp_dir / "pass2"
    pass1_dir.mkdir(parents=True, exist_ok=True)
    pass2_dir.mkdir(parents=True, exist_ok=True)

    pass1_path = pass1_dir / path.name
    pass2_path = pass2_dir / path.name

    try:
        # First pass
        _do_pass(path, pass1_path, file_type, needs_uuid)

        # Second pass
        _do_pass(pass1_path, pass2_path, file_type, needs_uuid)

        # Compare
        pass1_text = pass1_path.read_text(encoding="utf-8")
        pass2_text = pass2_path.read_text(encoding="utf-8")
        is_stable = pass1_text == pass2_text

        # Check UUID preservation for PCB/footprint
        uuid_preserved: Optional[bool] = None
        if needs_uuid:
            original_uuid_map = extract_uuids(
                path.read_text(encoding="utf-8"), file_type
            )
            pass2_uuid_map = extract_uuids(pass2_text, file_type)
            uuid_preserved = len(original_uuid_map.entries) == len(
                pass2_uuid_map.entries
            )

        return RoundTripResult(
            is_stable=is_stable,
            original_path=path,
            pass1_path=pass1_path,
            pass2_path=pass2_path,
            file_type=file_type,
            uuid_preserved=uuid_preserved,
        )

    except Exception as e:
        return RoundTripResult(
            is_stable=False,
            original_path=path,
            pass1_path=pass1_path if pass1_path.exists() else None,
            pass2_path=pass2_path if pass2_path.exists() else None,
            file_type=file_type,
            error=str(e),
        )
