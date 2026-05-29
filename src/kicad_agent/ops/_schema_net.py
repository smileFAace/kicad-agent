"""Net operation schemas -- add, remove, rename."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import TargetFile


class AddNetOp(BaseModel):
    """Add a net to a PCB.

    Attributes:
        op_type: Discriminator literal ``"add_net"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        net_name: Net name. Empty string triggers auto-generation as ``"N_<number>"``.
        net_number: Explicit net number. None triggers auto-assignment.
    """

    op_type: Literal["add_net"] = "add_net"
    target_file: TargetFile
    net_name: str = Field(
        default="",
        max_length=64,
        description="Net name. Empty triggers auto-generation.",
    )
    net_number: Optional[int] = Field(
        default=None,
        description="Explicit net number. None = auto-assign.",
    )

    @field_validator("net_name")
    @classmethod
    def _reject_whitespace_only(cls, v: str) -> str:
        if v.strip() == "" and len(v) > 0:
            raise ValueError("Net name must not be whitespace-only")
        return v


class RemoveNetOp(BaseModel):
    """Remove a net from a PCB, disconnecting all pads.

    Attributes:
        op_type: Discriminator literal ``"remove_net"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        net_name: Name of the net to remove.
    """

    op_type: Literal["remove_net"] = "remove_net"
    target_file: TargetFile
    net_name: str = Field(
        min_length=1,
        max_length=64,
        description="Name of the net to remove",
    )

    @field_validator("net_name")
    @classmethod
    def _reject_whitespace_only(cls, v: str) -> str:
        if v.strip() == "":
            raise ValueError("Net name must not be whitespace-only")
        return v


class RenameNetOp(BaseModel):
    """Rename a net, propagating to all connected pads.

    Attributes:
        op_type: Discriminator literal ``"rename_net"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        old_name: Current net name.
        new_name: Desired new net name.
    """

    op_type: Literal["rename_net"] = "rename_net"
    target_file: TargetFile
    old_name: str = Field(min_length=1, max_length=64)
    new_name: str = Field(min_length=1, max_length=64)

    @field_validator("old_name", "new_name")
    @classmethod
    def _reject_whitespace_only(cls, v: str) -> str:
        if v.strip() == "":
            raise ValueError("Net name must not be whitespace-only")
        return v
