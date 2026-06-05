"""Pydantic v2 operation schema -- the JSON contract the LLM uses to express edit intents.

Design decisions (from CONTEXT.md):
  D-01: One Pydantic model per operation type (not a generic dict).
  D-02: Atomic operations -- one mutation per operation, no compound ops.
  D-03: Single file per operation via ``target_file`` field.
  D-04: Export full JSON Schema via ``model_json_schema()`` for LLM consumption.

Security mitigations (Council review):
  H-01: TargetFile type rejects path traversal (``..``), absolute paths,
        null bytes, and non-KiCad extensions.
  M-04: All string fields enforce min_length / max_length to prevent abuse.

Usage::

    from kicad_agent.ops import Operation

    op = Operation.model_validate({
        "root": {
            "op_type": "add_component",
            "target_file": "motor-driver.kicad_sch",
            "library_id": "Device:R_Small_US",
            "position": {"x": 50.0, "y": 30.0},
        }
    })

    # Export schema for LLM tool contract
    schema = op.model_json_schema()
"""

from pathlib import Path
from typing import Annotated, Literal, Optional
import re

from pydantic import BaseModel, BeforeValidator, Field, field_validator


# ---------------------------------------------------------------------------
# Shared validators (Council H-1, H-2: S-expression safety constraints)
# ---------------------------------------------------------------------------

# Safe characters for KiCad identifiers: alphanumeric, underscore, dash, colon, dot, hash
_SAFE_ID_PATTERN = r'^[A-Za-z0-9_\-:.#+/]+$'


def _validate_safe_identifier(v: str, field_name: str) -> str:
    """Reject strings containing characters unsafe for S-expression output."""
    if not re.match(_SAFE_ID_PATTERN, v):
        raise ValueError(
            f"{field_name} contains unsafe characters. "
            f"Allowed: alphanumeric, underscore, dash, colon, dot, hash, forward slash."
        )
    return v


_UNSAFE_SEXPR_CHARS = re.compile(r'[\(\)\"\n]')


def _validate_sexpr_safe_string(v: str) -> str:
    """Reject strings containing characters that break S-expression parsing."""
    if _UNSAFE_SEXPR_CHARS.search(v):
        raise ValueError(
            "Value contains unsafe S-expression characters "
            "(parentheses, quotes, or newlines)"
        )
    return v


# ---------------------------------------------------------------------------
# Shared field types
# ---------------------------------------------------------------------------


class PositionSpec(BaseModel):
    """Position specification for place operations.

    Attributes:
        x: X coordinate in mm.
        y: Y coordinate in mm.
        angle: Rotation angle in degrees (default 0).
    """

    x: float
    y: float
    angle: float = 0.0

    @field_validator("x", "y", "angle")
    @classmethod
    def _reject_non_finite(cls, v: float) -> float:
        import math
        if math.isnan(v) or math.isinf(v):
            raise ValueError("Coordinate values must be finite (not NaN or Infinity)")
        return v


class PropertySpec(BaseModel):
    """A named property with a string value.

    Attributes:
        name: Property key (e.g. ``"Value"``, ``"Footprint"``).
        value: Property value string.
    """

    name: str = Field(min_length=1, max_length=128)
    value: str = Field(max_length=1024)


class PinSpec(BaseModel):
    """Pin definition for symbol creation.

    Attributes:
        number: Pin number (e.g. ``"1"``, ``"A1"``).
        name: Pin name (e.g. ``"VCC"``, ``"DOUT"``).
        electrical_type: KiCad pin electrical type.
        position: Pin position relative to symbol origin.
        length: Pin length in mm (default 2.54).
        graphical_style: Pin graphical style.
        hide: Whether the pin is hidden.
    """

    number: str = Field(min_length=1, max_length=32, description="Pin number")
    name: str = Field(min_length=1, max_length=128, description="Pin name")
    electrical_type: Literal[
        "input", "output", "bidirectional", "tri_state", "passive",
        "free", "unspecified", "power_in", "power_out",
        "open_collector", "open_emitter", "no_connect",
    ] = Field(default="passive", description="Pin electrical type")
    position: PositionSpec
    length: float = Field(default=2.54, gt=0, le=50, description="Pin length in mm")
    graphical_style: Literal[
        "line", "inverted", "clock", "inverted_clock",
        "input_low", "clock_low", "output_low", "edge_clock_high",
        "non_logic",
    ] = Field(default="line", description="Pin graphical style")
    hide: bool = Field(default=False, description="Whether pin is hidden")


# ---------------------------------------------------------------------------
# TargetFile -- path-safe type (Council H-01)
# ---------------------------------------------------------------------------


def _validate_target_file(v: str) -> str:
    """Reject path traversal, absolute paths, null bytes, and non-KiCad extensions."""
    if "\x00" in v:
        raise ValueError("target_file contains null bytes")
    if v.startswith("/"):
        raise ValueError("target_file must be a relative path")
    parts = Path(v).parts
    if ".." in parts:
        raise ValueError("target_file must not contain '..' path traversal")
    valid_extensions = (
        ".kicad_sch", ".kicad_pcb", ".kicad_sym", ".kicad_mod",
        ".kicad_dru", ".kicad_pro",
    )
    valid_names = ("sym-lib-table", "fp-lib-table")
    if not v.endswith(valid_extensions) and Path(v).name not in valid_names:
        raise ValueError("target_file must be a KiCad file type")
    return v


TargetFile = Annotated[
    str,
    Field(min_length=1, max_length=512),
    BeforeValidator(_validate_target_file),
]


# ---------------------------------------------------------------------------
# Re-export Op classes from sub-modules
# ---------------------------------------------------------------------------

from kicad_agent.ops._schema_component import (  # noqa: E402
    AddComponentOp,
    RemoveComponentOp,
    MoveComponentOp,
    ModifyPropertyOp,
    DuplicateComponentOp,
    ArrayReplicateOp,
)
from kicad_agent.ops._schema_net import (  # noqa: E402
    AddNetOp,
    RemoveNetOp,
    RenameNetOp,
)
from kicad_agent.ops._schema_reference import (  # noqa: E402
    RenumberRefsOp,
    ValidateRefsOp,
    AnnotateOp,
    CrossRefCheckOp,
)
from kicad_agent.ops._schema_footprint import (  # noqa: E402
    AssignFootprintOp,
    SwapFootprintOp,
    ValidateFootprintOp,
    VerifyPinMapOp,
    UpdateFootprintFromLibraryOp,
)
from kicad_agent.ops._schema_wire import (  # noqa: E402
    AddWireOp,
    ConnectPinsOp,
    AddLabelOp,
    AddPowerOp,
    AddNoConnectOp,
    AddJunctionOp,
)
from kicad_agent.ops._schema_remove import (  # noqa: E402
    RemoveWireOp,
    RemoveLabelOp,
    RemoveJunctionOp,
    RemoveNoConnectOp,
)
from kicad_agent.ops._schema_query import (  # noqa: E402
    QueryConnectivityOp,
)
from kicad_agent.ops._schema_library import (  # noqa: E402
    AddLibEntryOp,
    RemoveLibEntryOp,
    ListLibEntriesOp,
)
from kicad_agent.ops._schema_pcb import (  # noqa: E402
    AddNetClassOp,
    AddDesignRuleOp,
    AddCopperZoneOp,
    SetBoardOutlineOp,
    AssignNetClassOp,
    AutoRouteOp,
    ModifyNetClassOp,
    RemoveNetClassOp,
    ListNetClassesOp,
    ModifyDesignRuleOp,
    RemoveDesignRuleOp,
    ListDesignRulesOp,
    ModifyProjectSettingsOp,
    ModifyCopperZoneOp,
    RemoveCopperZoneOp,
)
from kicad_agent.ops._schema_validation import (  # noqa: E402
    ValidatePowerNetsOp,
    ValidateSchematicOp,
    ParseErcOp,
    ExtractViolationPositionsOp,
    ValidateHlabelsOp,
)
from kicad_agent.ops._schema_create import (  # noqa: E402
    CreateSchematicOp,
    CreatePcbOp,
    CreateProjectOp,
    CreateSymbolOp,
    EmbedSymbolOp,
    CreateFootprintOp,
    FootprintPadSpec,
)
from kicad_agent.ops._schema_repair import (  # noqa: E402
    RepairSchematicOp,
    ConvertKicad6To10Op,
    SnapToGridOp,
    AddPowerFlagOp,
    RebuildRootSheetOp,
    SwapSymbolOp,
    UpdateSymbolsFromLibraryOp,
    FixShortedNetsOp,
    FixPinTypeMismatchesOp,
    PlaceMissingUnitsOp,
    RemoveDanglingWiresOp,
    BreakWireShortsOp,
    ErcAutoFixOp,
)
from kicad_agent.ops._schema_sheet import (  # noqa: E402
    AddSheetOp,
    AddSheetPinOp,
    NavigateSheetsOp,
)
from kicad_agent.ops._schema_crossfile import (  # noqa: E402
    PropagateSymbolChangeOp,
)


# ---------------------------------------------------------------------------
# Discriminated union (D-01, D-02, D-03)
# ---------------------------------------------------------------------------


class Operation(BaseModel):
    """Discriminated union of all operation types.

    Per D-02: each operation is atomic (one mutation).
    Per D-03: each operation targets one file via ``target_file``.
    Per D-04: export full JSON Schema via ``model_json_schema()``.
    """

    root: Annotated[
        AddComponentOp
        | RemoveComponentOp
        | MoveComponentOp
        | ModifyPropertyOp
        | DuplicateComponentOp
        | ArrayReplicateOp
        | AddNetOp
        | RemoveNetOp
        | RenameNetOp
        | RenumberRefsOp
        | ValidateRefsOp
        | AnnotateOp
        | CrossRefCheckOp
        | AssignFootprintOp
        | SwapFootprintOp
        | ValidateFootprintOp
        | VerifyPinMapOp
        | UpdateFootprintFromLibraryOp
        | AddWireOp
        | ConnectPinsOp
        | AddLabelOp
        | AddPowerOp
        | AddNoConnectOp
        | AddJunctionOp
        | AddLibEntryOp
        | RemoveLibEntryOp
        | AddNetClassOp
        | AddDesignRuleOp
        | RepairSchematicOp
        | ValidatePowerNetsOp
        | ValidateSchematicOp
        | ParseErcOp
        | ExtractViolationPositionsOp
        | ValidateHlabelsOp
        | ConvertKicad6To10Op
        | SnapToGridOp
        | AddPowerFlagOp
        | RebuildRootSheetOp
        | AddCopperZoneOp
        | SetBoardOutlineOp
        | AssignNetClassOp
        | AutoRouteOp
        | CreateSchematicOp
        | CreatePcbOp
        | CreateProjectOp
        | CreateSymbolOp
        | EmbedSymbolOp
        | SwapSymbolOp
        | RemoveWireOp
        | RemoveLabelOp
        | RemoveJunctionOp
        | RemoveNoConnectOp
        | AddSheetOp
        | AddSheetPinOp
        | NavigateSheetsOp
        | QueryConnectivityOp
        | CreateFootprintOp
        | PropagateSymbolChangeOp
        | ListLibEntriesOp
        | ModifyNetClassOp
        | RemoveNetClassOp
        | ListNetClassesOp
        | ModifyDesignRuleOp
        | RemoveDesignRuleOp
        | ListDesignRulesOp
        | ModifyProjectSettingsOp
        | UpdateSymbolsFromLibraryOp
        | FixShortedNetsOp
        | FixPinTypeMismatchesOp
        | PlaceMissingUnitsOp
        | RemoveDanglingWiresOp
        | BreakWireShortsOp
        | ErcAutoFixOp
        | ModifyCopperZoneOp
        | RemoveCopperZoneOp,
        Field(discriminator="op_type"),
    ]


# ---------------------------------------------------------------------------
# Schema export helper (D-04)
# ---------------------------------------------------------------------------


def get_operation_schema() -> dict:
    """Export the full JSON Schema for LLM consumption (D-04)."""
    return Operation.model_json_schema()


__all__ = [
    # Shared types
    "PositionSpec",
    "PropertySpec",
    "PinSpec",
    "TargetFile",
    # Validators
    "_SAFE_ID_PATTERN",
    "_UNSAFE_SEXPR_CHARS",
    "_validate_safe_identifier",
    "_validate_sexpr_safe_string",
    # Component ops
    "AddComponentOp",
    "RemoveComponentOp",
    "MoveComponentOp",
    "ModifyPropertyOp",
    "DuplicateComponentOp",
    "ArrayReplicateOp",
    # Net ops
    "AddNetOp",
    "RemoveNetOp",
    "RenameNetOp",
    # Reference ops
    "RenumberRefsOp",
    "ValidateRefsOp",
    "AnnotateOp",
    "CrossRefCheckOp",
    # Footprint ops
    "AssignFootprintOp",
    "SwapFootprintOp",
    "ValidateFootprintOp",
    "VerifyPinMapOp",
    "UpdateFootprintFromLibraryOp",
    # Wire ops
    "AddWireOp",
    "ConnectPinsOp",
    "AddLabelOp",
    "AddPowerOp",
    "AddNoConnectOp",
    "AddJunctionOp",
    # Remove ops
    "RemoveWireOp",
    "RemoveLabelOp",
    "RemoveJunctionOp",
    "RemoveNoConnectOp",
    # Library ops
    "AddLibEntryOp",
    "RemoveLibEntryOp",
    "ListLibEntriesOp",
    # PCB ops
    "AddNetClassOp",
    "AddDesignRuleOp",
    "AddCopperZoneOp",
    "SetBoardOutlineOp",
    "AssignNetClassOp",
    "AutoRouteOp",
    "ModifyNetClassOp",
    "RemoveNetClassOp",
    "ListNetClassesOp",
    "ModifyDesignRuleOp",
    "RemoveDesignRuleOp",
    "ListDesignRulesOp",
    "ModifyProjectSettingsOp",
    "ModifyCopperZoneOp",
    "RemoveCopperZoneOp",
    # Validation ops
    "ValidatePowerNetsOp",
    "ValidateSchematicOp",
    "ParseErcOp",
    "ExtractViolationPositionsOp",
    "ValidateHlabelsOp",
    # Create ops
    "CreateSchematicOp",
    "CreatePcbOp",
    "CreateProjectOp",
    "CreateSymbolOp",
    "EmbedSymbolOp",
    "CreateFootprintOp",
    "FootprintPadSpec",
    # Repair ops
    "RepairSchematicOp",
    "ConvertKicad6To10Op",
    "SnapToGridOp",
    "AddPowerFlagOp",
    "RebuildRootSheetOp",
    "SwapSymbolOp",
    "UpdateSymbolsFromLibraryOp",
    "FixShortedNetsOp",
    "FixPinTypeMismatchesOp",
    "PlaceMissingUnitsOp",
    "RemoveDanglingWiresOp",
    "BreakWireShortsOp",
    "ErcAutoFixOp",
    # Sheet ops
    "AddSheetOp",
    "AddSheetPinOp",
    "NavigateSheetsOp",
    # Query ops
    "QueryConnectivityOp",
    # Cross-file ops
    "PropagateSymbolChangeOp",
    # Union and helpers
    "Operation",
    "get_operation_schema",
]
