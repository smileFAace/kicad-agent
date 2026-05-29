"""File creation operation schemas -- schematic, PCB, project, symbol, embed."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
