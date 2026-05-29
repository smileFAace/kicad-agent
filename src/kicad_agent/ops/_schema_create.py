"""File creation operation schemas -- schematic, PCB, project, symbol, embed, footprint."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from kicad_agent.ops.schema import (
    PinSpec,
    PositionSpec,
    PropertySpec,
    TargetFile,
    _validate_safe_identifier,
)


class CreateSchematicOp(BaseModel):
    """Create a new empty .kicad_sch file.

    Attributes:
        op_type: Discriminator literal ``"create_schematic"``.
        target_file: Relative path for the new .kicad_sch file (must not exist).
        paper: Paper size (default ``"A4"``).
        title: Optional title block title.
    """

    op_type: Literal["create_schematic"] = "create_schematic"
    target_file: TargetFile
    paper: str = Field(default="A4", max_length=16, description="Paper size (A4, A3, etc.)")
    title: str = Field(default="", max_length=256, description="Schematic title")


class CreatePcbOp(BaseModel):
    """Create a new empty .kicad_pcb file.

    Attributes:
        op_type: Discriminator literal ``"create_pcb"``.
        target_file: Relative path for the new .kicad_pcb file (must not exist).
        title: Optional title block title.
    """

    op_type: Literal["create_pcb"] = "create_pcb"
    target_file: TargetFile
    title: str = Field(default="", max_length=256, description="PCB title")


class CreateProjectOp(BaseModel):
    """Create a new empty .kicad_pro project file.

    Attributes:
        op_type: Discriminator literal ``"create_project"``.
        target_file: Relative path for the new .kicad_pro file (must not exist).
    """

    op_type: Literal["create_project"] = "create_project"
    target_file: TargetFile


class CreateSymbolOp(BaseModel):
    """Create a new symbol definition in a .kicad_sym library file.

    If the library file does not exist, it is created. If it exists, the
    symbol is appended. Duplicate symbol names are rejected.

    Attributes:
        op_type: Discriminator literal ``"create_symbol"``.
        target_file: Relative path to the .kicad_sym library file.
        symbol_name: Name of the new symbol.
        reference_prefix: Reference prefix (e.g. ``"R"``, ``"U"``, ``"C"``).
        value: Default value for the symbol.
        pins: List of pin definitions.
        properties: Additional custom properties.
        body_width: Width of the default rectangle body in mm.
        body_height: Height of the default rectangle body in mm.
    """

    op_type: Literal["create_symbol"] = "create_symbol"
    target_file: TargetFile
    symbol_name: str = Field(min_length=1, max_length=128, description="Symbol name")
    reference_prefix: str = Field(
        default="U", min_length=1, max_length=8,
        description="Reference prefix (e.g. R, U, C)",
    )
    value: str = Field(default="", max_length=256, description="Default symbol value")
    pins: list[PinSpec] = Field(
        default_factory=list,
        max_length=200,
        description="Pin definitions",
    )
    properties: list[PropertySpec] = Field(
        default_factory=list,
        max_length=50,
        description="Additional custom properties",
    )
    body_width: float = Field(
        default=10.16, gt=0, le=200,
        description="Body rectangle width in mm",
    )
    body_height: float = Field(
        default=10.16, gt=0, le=200,
        description="Body rectangle height in mm",
    )

    @field_validator("symbol_name")
    @classmethod
    def _validate_symbol_name(cls, v: str) -> str:
        return _validate_safe_identifier(v, "symbol_name")

    @field_validator("reference_prefix")
    @classmethod
    def _validate_reference_prefix(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference_prefix")


class EmbedSymbolOp(BaseModel):
    """Embed a symbol definition from a .kicad_sym library into a schematic's lib_symbols.

    Extracts the symbol definition from the specified library file and injects it
    into the schematic's embedded lib_symbols section. This is required before a
    symbol can be used in the schematic (KiCad resolves symbols from lib_symbols first).

    If the symbol already exists in the schematic's lib_symbols (same libId), the
    operation is a no-op and returns success.

    Attributes:
        op_type: Discriminator literal ``"embed_symbol"``.
        target_file: Relative path to the .kicad_sch file.
        lib_id: Library ID of the symbol to embed (e.g. ``"Analog-Ecosystem-SMD:RP2350B"``).
        library_path: Relative path to the .kicad_sym library file containing the symbol.
    """

    op_type: Literal["embed_symbol"] = "embed_symbol"
    target_file: TargetFile
    lib_id: str = Field(
        min_length=1, max_length=256,
        description="Library:symbol ID to embed (e.g. 'Library:SymbolName')",
    )
    library_path: str = Field(
        min_length=1, max_length=512,
        description="Relative path to .kicad_sym library file",
    )

    @field_validator("lib_id")
    @classmethod
    def _validate_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "lib_id")


class FootprintPadSpec(BaseModel):
    """Pad definition for footprint creation.

    Attributes:
        number: Pad number or designator (e.g. "1", "A1", "EP").
        pad_type: Pad type -- SMD, through-hole, or edge connector.
        shape: Pad shape -- rectangle, rounded-rectangle, oval, circle, or custom.
        position: Pad center position relative to footprint origin.
        size_x: Pad width in mm.
        size_y: Pad height in mm.
        drill_diameter: Drill diameter in mm. Required for thru_hole, forbidden for smd/connect.
        drill_offset_x: Drill offset X in mm (for off-center drills).
        drill_offset_y: Drill offset Y in mm (for off-center drills).
        layers: Copper/technique layers this pad appears on.
    """

    number: str = Field(min_length=1, max_length=32, description="Pad number")
    pad_type: Literal["smd", "thru_hole", "connect"] = Field(
        description="Pad type: SMD, through-hole, or edge connector",
    )
    shape: Literal["rect", "roundrect", "oval", "circle", "custom"] = Field(
        description="Pad shape",
    )
    position: PositionSpec
    size_x: float = Field(gt=0, le=50, description="Pad width in mm")
    size_y: float = Field(gt=0, le=50, description="Pad height in mm")
    drill_diameter: Optional[float] = Field(
        default=None, gt=0, le=10,
        description="Drill diameter in mm (required for thru_hole)",
    )
    drill_offset_x: Optional[float] = Field(
        default=None, description="Drill offset X in mm",
    )
    drill_offset_y: Optional[float] = Field(
        default=None, description="Drill offset Y in mm",
    )
    layers: list[
        Literal[
            "F.Cu", "B.Cu", "F.Paste", "B.Paste",
            "F.SilkS", "B.SilkS", "F.Mask", "B.Mask",
            "F.CrtYd", "B.CrtYd", "F.Fab", "B.Fab",
            "Edge.Cuts", "Dwgs.User", "Cmts.User",
            "Eco1.User", "Eco2.User",
            "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu",
            "In5.Cu", "In6.Cu", "In7.Cu", "In8.Cu",
            "In9.Cu", "In10.Cu", "In11.Cu", "In12.Cu",
            "In13.Cu", "In14.Cu", "In15.Cu", "In16.Cu",
            "In17.Cu", "In18.Cu", "In19.Cu", "In20.Cu",
            "In21.Cu", "In22.Cu", "In23.Cu", "In24.Cu",
            "In25.Cu", "In26.Cu", "In27.Cu", "In28.Cu",
            "In29.Cu", "In30.Cu",
            "*.Cu", "*.Mask", "*.Paste", "*.SilkS",
        ]
    ] = Field(min_length=1, max_length=32, description="KiCad layer names")

    @model_validator(mode="after")
    def _validate_drill_for_pad_type(self) -> "FootprintPadSpec":
        """thru_hole pads must have drill_diameter; smd/connect must not."""
        if self.pad_type == "thru_hole" and self.drill_diameter is None:
            raise ValueError("drill_diameter is required for thru_hole pads")
        if self.pad_type in ("smd", "connect") and self.drill_diameter is not None:
            raise ValueError("drill_diameter must be None for smd/connect pads")
        return self


class CreateFootprintOp(BaseModel):
    """Create a new footprint definition in a .kicad_mod file.

    Creates a single footprint with the specified pads, reference/value text,
    optional body outline, and optional courtyard. The footprint is written
    as a standalone .kicad_mod file.

    Per FOOT-02: Serialization uses raw S-expression construction (not kiutils
    Footprint.to_file()) because kiutils 1.4.8 drops UUIDs from .kicad_mod files.

    Attributes:
        op_type: Discriminator literal ``"create_footprint"``.
        target_file: Relative path for the new .kicad_mod file (must not exist).
        footprint_name: Name of the footprint (e.g. "MY_DIP-8", "SOT-23-3").
        reference_prefix: Reference designator prefix (default "U").
        value: Default value text.
        pads: List of pad definitions.
        courtyard_margin: Margin in mm around pad bounding box for courtyard generation.
        attributes: Footprint attributes (through_hole, smd, or board_only).
    """

    op_type: Literal["create_footprint"] = "create_footprint"
    target_file: TargetFile
    footprint_name: str = Field(min_length=1, max_length=128, description="Footprint name")
    reference_prefix: str = Field(
        default="U", min_length=1, max_length=8,
        description="Reference prefix (e.g. U, R, C)",
    )
    value: str = Field(default="", max_length=256, description="Default footprint value")
    pads: list[FootprintPadSpec] = Field(
        default_factory=list,
        max_length=500,
        description="Pad definitions",
    )
    courtyard_margin: float = Field(
        default=0.25, ge=0, le=5.0,
        description="Courtyard margin in mm around pad bounding box (0 = no courtyard)",
    )
    attributes: Literal["through_hole", "smd", "board_only"] = Field(
        default="through_hole",
        description="Footprint attributes",
    )

    @field_validator("footprint_name")
    @classmethod
    def _validate_footprint_name(cls, v: str) -> str:
        return _validate_safe_identifier(v, "footprint_name")
