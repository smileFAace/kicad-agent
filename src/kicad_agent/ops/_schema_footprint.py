"""Footprint operation schemas -- assign, swap, validate, verify pin map, update."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import (
    TargetFile,
    _validate_safe_identifier,
)


class AssignFootprintOp(BaseModel):
    """Assign a footprint to a schematic component.

    Attributes:
        op_type: Discriminator literal ``"assign_footprint"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        reference: Component reference designator (e.g. ``"U1"``).
        footprint_lib_id: Footprint library reference (e.g. ``"Package_DIP:DIP-8_W7.62mm"``).
    """

    op_type: Literal["assign_footprint"] = "assign_footprint"
    target_file: TargetFile
    reference: str = Field(
        min_length=1,
        max_length=64,
        description="Component reference designator",
    )
    footprint_lib_id: str = Field(
        min_length=1,
        max_length=256,
        description="Footprint library reference, e.g. 'Package_DIP:DIP-8_W7.62mm'",
    )

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")

    @field_validator("footprint_lib_id")
    @classmethod
    def _validate_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "footprint_lib_id")


class SwapFootprintOp(BaseModel):
    """Swap a PCB footprint while preserving pad-to-net connections.

    Attributes:
        op_type: Discriminator literal ``"swap_footprint"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        reference: Reference designator of the footprint to swap.
        new_footprint_lib_id: New footprint library reference.
    """

    op_type: Literal["swap_footprint"] = "swap_footprint"
    target_file: TargetFile
    reference: str = Field(
        min_length=1,
        max_length=64,
        description="Reference designator of the footprint to swap",
    )
    new_footprint_lib_id: str = Field(
        min_length=1,
        max_length=256,
        description="New footprint library reference",
    )

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")

    @field_validator("new_footprint_lib_id")
    @classmethod
    def _validate_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "new_footprint_lib_id")


class ValidateFootprintOp(BaseModel):
    """Validate that a footprint exists in the available libraries.

    Attributes:
        op_type: Discriminator literal ``"validate_footprint"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        footprint_lib_id: Footprint library reference to validate.
    """

    op_type: Literal["validate_footprint"] = "validate_footprint"
    target_file: TargetFile
    footprint_lib_id: str = Field(
        min_length=1,
        max_length=256,
        description="Footprint library reference to validate",
    )

    @field_validator("footprint_lib_id")
    @classmethod
    def _validate_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "footprint_lib_id")


class VerifyPinMapOp(BaseModel):
    """Verify that symbol pin numbers match footprint pad numbers.

    Attributes:
        op_type: Discriminator literal ``"verify_pin_map"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        reference: Component reference designator.
        footprint_lib_id: Footprint library reference to verify against.
    """

    op_type: Literal["verify_pin_map"] = "verify_pin_map"
    target_file: TargetFile
    reference: str = Field(
        min_length=1,
        max_length=64,
        description="Component reference designator",
    )
    footprint_lib_id: str = Field(
        min_length=1,
        max_length=256,
        description="Footprint library reference to verify against",
    )

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")

    @field_validator("footprint_lib_id")
    @classmethod
    def _validate_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "footprint_lib_id")


class UpdateFootprintFromLibraryOp(BaseModel):
    """Reload a PCB footprint's geometry from the library, preserving placement.

    Reads the fresh footprint definition from the library ``.kicad_mod`` file
    and replaces the geometry in the PCB while preserving position, rotation,
    reference designator, value, and pad-to-net connections.

    This is the programmatic equivalent of KiCad's GUI
    ``Tools > Update Footprints from Library`` command.

    Attributes:
        op_type: Discriminator literal ``"update_footprint_from_library"``.
        target_file: Relative path to the KiCad PCB file (H-01 validated).
        reference: Reference designator of the footprint to update (e.g. ``"U2"``).
        footprint_lib_id: Optional override footprint library reference.
            If omitted, uses the footprint's existing ``libId`` (refresh from same library).
            If provided, also swaps to a different footprint (swap + update combined).
    """

    op_type: Literal["update_footprint_from_library"] = "update_footprint_from_library"
    target_file: TargetFile
    reference: str = Field(
        min_length=1,
        max_length=64,
        description="Reference designator of the footprint to update",
    )
    footprint_lib_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="Optional override lib_id. None = refresh from existing library.",
    )

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")

    @field_validator("footprint_lib_id")
    @classmethod
    def _validate_lib_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_safe_identifier(v, "footprint_lib_id")
        return v
