"""Swap symbol and embed symbol operation handlers.

swap_symbol: Replace a component's lib_id in-place, preserving position and properties.
embed_symbol: Copy a symbol definition from a .kicad_sym library into a schematic's
              embedded lib_symbols section.

Security (threat model):
- T-04-06: Exact op_type matching via executor dispatch
- T-04-12: All string fields validated by schema with max_length constraints
- Library paths are resolved relative to the schematic's base directory

Usage:
    from kicad_agent.ops.swap_symbol import swap_symbol, embed_symbol
    from kicad_agent.ops.schema import SwapSymbolOp, EmbedSymbolOp

    # Embed a symbol definition
    result = embed_symbol(embed_op, ir, file_path)

    # Swap a component's symbol
    result = swap_symbol(swap_op, ir, file_path)
"""

import copy
import logging
from pathlib import Path
from typing import Any

from kiutils.symbol import Symbol, SymbolLib

logger = logging.getLogger(__name__)


class SwapSymbolError(Exception):
    """Error raised when swap_symbol operation fails."""


class EmbedSymbolError(Exception):
    """Error raised when embed_symbol operation fails."""


def embed_symbol(
    op: Any,
    ir: Any,
    file_path: Path,
) -> dict[str, Any]:
    """Embed a symbol definition from a .kicad_sym library into the schematic.

    Extracts the symbol definition from the specified library file and injects it
    into the schematic's embedded lib_symbols section. If the symbol already exists
    (matching libId), the operation is a no-op.

    Args:
        op: EmbedSymbolOp with lib_id, library_path.
        ir: SchematicIR wrapping the parsed schematic.
        file_path: Resolved path to the target schematic file.

    Returns:
        Dict with lib_id and action ("embedded" or "already_exists").

    Raises:
        EmbedSymbolError: If library file not found or symbol not found in library.
    """
    sch = ir._parse_result.kiutils_obj

    # Parse lib_id into library nickname and symbol name
    lib_id = op.lib_id
    if ":" in lib_id:
        lib_nick, symbol_name = lib_id.split(":", 1)
    else:
        lib_nick = ""
        symbol_name = lib_id

    # Check if already embedded
    for existing in sch.libSymbols:
        if existing.libId == lib_id:
            return {"lib_id": lib_id, "action": "already_exists"}

    # Resolve library path relative to the schematic's directory
    lib_path = file_path.parent / op.library_path
    if not lib_path.exists():
        raise EmbedSymbolError(
            f"Library file not found: {lib_path}"
        )

    # Load the library
    try:
        lib = SymbolLib.from_file(str(lib_path))
    except Exception as exc:
        raise EmbedSymbolError(
            f"Cannot parse library file {lib_path}: {exc}"
        ) from exc

    # Find the symbol by name
    source_symbol = None
    for sym in lib.symbols:
        if sym.entryName == symbol_name or sym.libId == lib_id:
            source_symbol = sym
            break

    if source_symbol is None:
        # List available symbols for helpful error message
        available = [s.entryName for s in lib.symbols]
        raise EmbedSymbolError(
            f"Symbol {symbol_name!r} not found in {lib_path.name}. "
            f"Available: {', '.join(available[:20])}"
        )

    # Deep copy the symbol to avoid shared references
    new_symbol = copy.deepcopy(source_symbol)

    # Set the library nickname so libId resolves correctly
    new_symbol.libraryNickname = lib_nick

    # Add to schematic's lib_symbols
    sch.libSymbols.append(new_symbol)

    # Record mutation for audit trail
    ir._record_mutation(
        "embed_symbol",
        {
            "lib_id": lib_id,
            "library_path": op.library_path,
            "action": "embedded",
        },
    )

    return {"lib_id": lib_id, "action": "embedded"}


def swap_symbol(
    op: Any,
    ir: Any,
    file_path: Path,
) -> dict[str, Any]:
    """Swap a component's symbol (lib_id) in-place.

    Replaces the component's lib_id reference with a new one. If library_path
    is provided, the symbol definition is embedded into the schematic's
    lib_symbols section first (if not already present).

    Position, reference, and other properties are preserved by default.

    Args:
        op: SwapSymbolOp with reference, new_lib_id, optional library_path.
        ir: SchematicIR wrapping the parsed schematic.
        file_path: Resolved path to the target schematic file.

    Returns:
        Dict with reference, old_lib_id, new_lib_id, and symbol_embedded flag.

    Raises:
        SwapSymbolError: If component not found or embed fails.
    """
    sch = ir._parse_result.kiutils_obj

    # Find the component by reference
    component = ir.get_component_by_ref(op.reference)
    if component is None:
        raise SwapSymbolError(
            f"Component not found: {op.reference!r}"
        )

    old_lib_id = component.libId
    new_lib_id = op.new_lib_id

    # No-op if already the correct symbol
    if old_lib_id == new_lib_id:
        return {
            "reference": op.reference,
            "old_lib_id": old_lib_id,
            "new_lib_id": new_lib_id,
            "symbol_embedded": False,
            "action": "no_op",
        }

    # Optionally embed the new symbol definition
    symbol_embedded = False
    if op.library_path:
        # Check if already in lib_symbols
        already_embedded = any(
            ls.libId == new_lib_id for ls in sch.libSymbols
        )
        if not already_embedded:
            from kicad_agent.ops.schema import EmbedSymbolOp
            embed_op = EmbedSymbolOp(
                target_file=op.target_file,
                lib_id=new_lib_id,
                library_path=op.library_path,
            )
            embed_result = embed_symbol(embed_op, ir, file_path)
            symbol_embedded = embed_result.get("action") == "embedded"
        else:
            symbol_embedded = False  # Was already there

    # Swap the lib_id on the component
    component.libId = new_lib_id

    # Also update libName to match the new lib_id
    component.libName = new_lib_id

    # Record mutation for audit trail
    ir._record_mutation(
        "swap_symbol",
        {
            "reference": op.reference,
            "old_lib_id": old_lib_id,
            "new_lib_id": new_lib_id,
            "symbol_embedded": symbol_embedded,
            "preserve_position": op.preserve_position,
            "preserve_properties": op.preserve_properties,
        },
    )

    return {
        "reference": op.reference,
        "old_lib_id": old_lib_id,
        "new_lib_id": new_lib_id,
        "symbol_embedded": symbol_embedded,
        "action": "swapped",
    }
