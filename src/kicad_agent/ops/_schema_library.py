"""Library operation schemas -- add and remove library entries."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import (
    TargetFile,
    _validate_safe_identifier,
)


class AddLibEntryOp(BaseModel):
    """Add a library entry to sym-lib-table or fp-lib-table.

    Attributes:
        op_type: Discriminator literal ``"add_lib_entry"``.
        target_file: Relative path to sym-lib-table or fp-lib-table.
        lib_name: Library name (e.g. ``"Device"``, ``"MyLib"``).
        lib_type: Library type (``"KiCad"`` or ``"Legacy"``).
        uri: Library URI path, may contain variables like ``${KIPRJMOD}``.
        options: Library options string (usually empty).
        description: Library description.
    """

    op_type: Literal["add_lib_entry"] = "add_lib_entry"
    target_file: TargetFile
    lib_name: str = Field(
        min_length=1,
        max_length=128,
        description="Library name",
    )
    lib_type: Literal["KiCad", "Legacy"] = "KiCad"
    uri: str = Field(
        min_length=1,
        max_length=512,
        description="Library URI path",
    )
    options: str = Field(default="", max_length=256)
    description: str = Field(default="", max_length=512)

    @field_validator("lib_name")
    @classmethod
    def _validate_lib_name(cls, v: str) -> str:
        return _validate_safe_identifier(v, "lib_name")


class RemoveLibEntryOp(BaseModel):
    """Remove a library entry from sym-lib-table or fp-lib-table.

    Attributes:
        op_type: Discriminator literal ``"remove_lib_entry"``.
        target_file: Relative path to sym-lib-table or fp-lib-table.
        lib_name: Library name to remove.
    """

    op_type: Literal["remove_lib_entry"] = "remove_lib_entry"
    target_file: TargetFile
    lib_name: str = Field(
        min_length=1,
        max_length=128,
        description="Library name to remove",
    )

    @field_validator("lib_name")
    @classmethod
    def _validate_lib_name(cls, v: str) -> str:
        return _validate_safe_identifier(v, "lib_name")
