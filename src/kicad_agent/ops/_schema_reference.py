"""Reference operation schemas -- renumber, validate, annotate, cross-ref check."""

from typing import Literal

from pydantic import BaseModel, Field

from kicad_agent.ops.schema import TargetFile


class RenumberRefsOp(BaseModel):
    """Renumber component references with configurable prefix and sequencing.

    Attributes:
        op_type: Discriminator literal ``"renumber_refs"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        prefix: Only renumber components with this prefix. Empty means all (default).
        start_index: Starting index for numbering (default 1, must be >= 1).
        step: Step between indices (default 1, must be >= 1).
    """

    op_type: Literal["renumber_refs"] = "renumber_refs"
    target_file: TargetFile
    prefix: str = Field(
        default="",
        max_length=16,
        description="Prefix filter. Empty means renumber all prefixes.",
    )
    start_index: int = Field(
        default=1,
        ge=1,
        description="Starting index for numbering",
    )
    step: int = Field(
        default=1,
        ge=1,
        description="Step between sequential indices",
    )


class ValidateRefsOp(BaseModel):
    """Validate that all component references are unique.

    Attributes:
        op_type: Discriminator literal ``"validate_refs"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
    """

    op_type: Literal["validate_refs"] = "validate_refs"
    target_file: TargetFile


class AnnotateOp(BaseModel):
    """Auto-assign references to unannotated components (refs ending in '?').

    Attributes:
        op_type: Discriminator literal ``"annotate"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        prefix_filter: Only annotate components matching this prefix. Empty means all.
    """

    op_type: Literal["annotate"] = "annotate"
    target_file: TargetFile
    prefix_filter: str = Field(
        default="",
        max_length=16,
        description="Prefix filter for annotation. Empty means annotate all.",
    )


class CrossRefCheckOp(BaseModel):
    """Verify all symbol libIds resolve to entries in the embedded libSymbols.

    Attributes:
        op_type: Discriminator literal ``"cross_ref_check"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
    """

    op_type: Literal["cross_ref_check"] = "cross_ref_check"
    target_file: TargetFile
