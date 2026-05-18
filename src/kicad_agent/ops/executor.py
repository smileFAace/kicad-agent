"""Operation executor -- dispatches validated Operation intents to handlers.

Establishes the pattern (executor dispatch, handler function, Transaction
wrapping, IR mutation, serialization) that all subsequent operations follow.

Security (threat model):
- T-04-06: Dispatch uses exact op_type matching; unknown raises ValueError
- T-04-01: UUID generated server-side in handlers

Usage:
    from kicad_agent.ops.executor import OperationExecutor
    from kicad_agent.ops.schema import Operation

    executor = OperationExecutor(base_dir=Path("/project"))
    result = executor.execute(op)
"""

import logging
from pathlib import Path
from typing import Any

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ir.transaction import Transaction
from kicad_agent.ops.schema import Operation
from kicad_agent.parser import parse_schematic
from kicad_agent.serializer import normalize_kicad_output, serialize_schematic

logger = logging.getLogger(__name__)


class OperationExecutor:
    """Dispatches validated Operation intents to mutation handlers.

    Each handler call is wrapped in a Transaction for rollback on failure.
    The executor parses the file, creates SchematicIR, calls the handler,
    serializes, normalizes, and commits.

    Args:
        base_dir: Base directory for resolving relative target_file paths.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def execute(self, op: Operation) -> dict[str, Any]:
        """Execute a validated operation with Transaction wrapping.

        Parses the target file, creates IR, dispatches to handler,
        serializes result, normalizes output, and commits transaction.

        Args:
            op: Validated Operation from the schema.

        Returns:
            Dict with: success, operation, target_file, details.

        Raises:
            ValueError: For unknown op_type (T-04-06).
            FileNotFoundError: If target_file does not exist.
        """
        root = op.root
        file_path = self._base_dir / root.target_file

        if not file_path.exists():
            raise FileNotFoundError(f"Target file not found: {file_path}")

        # Clear IR registry to avoid stale registrations across operations
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        # Parse the schematic file
        parse_result = parse_schematic(file_path)
        ir = SchematicIR(_parse_result=parse_result)

        # Wrap in Transaction for rollback on failure
        with Transaction(file_path) as txn:
            # Dispatch to appropriate handler
            details = self._dispatch(
                root.op_type,
                root,
                ir,
                file_path,
            )

            # Serialize mutated IR back to file
            serialize_schematic(parse_result, file_path)

            # Normalize the serialized output
            content = file_path.read_text(encoding="utf-8")
            normalized = normalize_kicad_output(content)
            file_path.write_text(normalized, encoding="utf-8")

            # Commit the transaction
            txn.commit()

        return {
            "success": True,
            "operation": root.op_type,
            "target_file": root.target_file,
            "details": details,
        }

    def _dispatch(
        self,
        op_type: str,
        op: Any,
        ir: SchematicIR,
        file_path: Path,
    ) -> dict[str, Any]:
        """Dispatch to the appropriate handler based on op_type.

        T-04-06: Exact string matching. Unknown op_type raises ValueError.

        Args:
            op_type: The operation type string.
            op: The operation's root model (e.g. AddComponentOp).
            ir: SchematicIR for the target file.
            file_path: Resolved path to the target file.

        Returns:
            Handler result dict.

        Raises:
            ValueError: For unknown op_type.
            NotImplementedError: For not-yet-implemented operations.
        """
        if op_type == "add_component":
            from kicad_agent.ops.add_component import add_component
            return add_component(op, ir, file_path)

        if op_type == "remove_component":
            from kicad_agent.ops.remove_component import remove_component
            return remove_component(op, ir)

        if op_type == "duplicate_component":
            from kicad_agent.ops.duplicate_component import duplicate_component
            return duplicate_component(op, ir)

        if op_type == "array_replicate":
            from kicad_agent.ops.array_replicate import array_replicate
            return array_replicate(op, ir)

        if op_type == "move_component":
            from kicad_agent.ops.move_component import move_component
            file_type = ir.file_type
            return move_component(op, ir, file_type=file_type)

        if op_type == "modify_property":
            from kicad_agent.ops.modify_property import modify_property
            return modify_property(op, ir)

        raise ValueError(f"Unknown op_type: {op_type!r}")
