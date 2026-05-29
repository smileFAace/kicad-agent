"""Skill handler: validates JSON operation requests, routes them, and executes mutations.

The handler is the bridge between the GSD Skill interface and the
kicad-agent Python backend.  It receives a JSON string from Claude,
validates it against the Pydantic operation schema, dispatches it to
the OperationExecutor for file mutation, and returns a structured result.

Public API::

    from kicad_agent.handler import validate_operation, handle_operation, format_result
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

from pydantic import ValidationError

from kicad_agent.ops.schema import Operation
from kicad_agent.result import OperationError, OperationResult


def validate_operation(
    json_str: str,
) -> tuple[Operation | None, OperationError | None]:
    """Parse and validate a JSON operation string.

    Args:
        json_str: Raw JSON string from the skill interface.

    Returns:
        ``(Operation, None)`` on success, ``(None, OperationError)``
        on failure.  Error messages include actionable suggestions.
    """
    # -- Step 1: Parse JSON --
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as exc:
        return None, OperationError(
            success=False,
            operation_type="unknown",
            error=f"Invalid JSON syntax: {exc}",
            suggestion="Check that your JSON is well-formed. Ensure all strings are quoted, brackets are closed, and there are no trailing commas.",
        )

    # -- Step 2: Validate against Pydantic schema --
    try:
        op = Operation.model_validate({"root": parsed})
    except ValidationError as exc:
        # Extract a readable error message from the first error
        first_err = exc.errors()[0] if exc.errors() else {}
        field = first_err.get("loc", ("unknown",))
        field_name = field[-1] if field else "unknown"
        msg = first_err.get("msg", str(exc))
        error_type = first_err.get("type", "value_error")

        # Determine the op_type if available for better error context
        op_type = parsed.get("op_type", "unknown")

        # Provide targeted suggestions based on error type
        if "path" in str(msg).lower() or "traversal" in str(msg).lower() or "'.'" in str(msg):
            suggestion = "Use a relative path without '..' components. Only .kicad_sch, .kicad_pcb, .kicad_sym, and .kicad_mod files are allowed."
        elif error_type == "missing":
            # Designer-friendly field descriptions
            _field_names = {
                "position": "component position",
                "target_file": "target file path",
                "reference": "reference designator (e.g. R1, U3)",
                "footprint_lib_id": "footprint library ID (e.g. Resistor_SMD:R_0805)",
                "net_name": "net name",
                "lib_id": "symbol library ID",
                "op_type": "operation type",
            }
            friendly = _field_names.get(str(field_name), str(field_name))
            suggestion = f"Missing {friendly}. Add '{field_name}' to your operation."
        elif "literal" in error_type.lower() or "op_type" in str(field):
            suggestion = f"Unknown operation '{parsed.get('op_type', '?')}'. Use one of: add_component, remove_component, move_component, auto_route, etc."
        else:
            suggestion = f"Check the operation fields against the schema. Error in '{field_name}': {msg}"

        return None, OperationError(
            success=False,
            operation_type=op_type,
            error=f"Validation error: {msg}",
            suggestion=suggestion,
        )
    except (TypeError, AttributeError) as exc:
        return None, OperationError(
            success=False,
            operation_type=parsed.get("op_type", "unknown"),
            error=f"Unexpected error: {exc}",
            suggestion="Check your operation JSON structure and try again.",
        )

    return op, None


def handle_operation(
    json_str: str,
    project_dir: Path | None = None,
) -> Union[OperationResult, OperationError]:
    """Validate an operation, execute it, and return a structured result.

    Validates the operation against the schema, then dispatches to the
    OperationExecutor for actual file mutation. Transactions provide
    automatic rollback on failure.

    Args:
        json_str: Raw JSON string from the skill interface.
        project_dir: Optional project directory for file resolution.

    Returns:
        ``OperationResult`` on success, ``OperationError`` on failure.
    """
    op, err = validate_operation(json_str)
    if err is not None:
        return err

    # Resolve project directory
    base_dir = Path(project_dir) if project_dir else Path.cwd()

    # Execute the operation via the executor
    try:
        from kicad_agent.ops.executor import OperationExecutor
        executor = OperationExecutor(base_dir=base_dir)
        result = executor.execute(op)
        return OperationResult(
            success=True,
            operation_type=result["operation"],
            target_file=result["target_file"],
            message=f"Operation {result['operation']} executed successfully",
            details=result.get("details", {}),
        )
    except FileNotFoundError as exc:
        concrete = op.root
        return OperationError(
            success=False,
            operation_type=concrete.op_type,
            error=str(exc),
            suggestion=f"File '{concrete.target_file}' not found. Check the path is correct relative to the project directory.",
        )
    except NotImplementedError as exc:
        concrete = op.root
        return OperationError(
            success=False,
            operation_type=concrete.op_type,
            error=str(exc),
            suggestion="This operation is not yet available. Try a different approach.",
        )
    except ValueError as exc:
        concrete = op.root
        return OperationError(
            success=False,
            operation_type=concrete.op_type,
            error=str(exc),
            suggestion="Check the operation parameters and try again.",
        )
    except (RuntimeError, OSError, KeyError) as exc:
        concrete = op.root
        return OperationError(
            success=False,
            operation_type=concrete.op_type,
            error=f"Execution failed: {exc}",
            suggestion="The operation validated but failed during execution. Check the file format and parameters.",
        )


def format_result(result: Union[OperationResult, OperationError]) -> str:
    """Format a result into a human-readable string.

    Args:
        result: An ``OperationResult`` or ``OperationError``.

    Returns:
        Formatted text suitable for display.
    """
    return result.to_text()
