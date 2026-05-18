"""Base IR class with mutation tracking for all file-type IR wrappers.

D-05: Holds reference to ParseResult (which contains kiutils obj), not a copy.
D-06: Tracks mutations, UUID map reference, dirty flag.

IMPORTANT: One IR instance per ParseResult. The registry enforces this
at construction time -- creating a second IR for the same ParseResult
raises RuntimeError. Never share kiutils objects between IR instances
-- mutations would affect all references (Pitfall 2).

Usage:
    from kicad_agent.ir.schematic_ir import SchematicIR
    from kicad_agent.parser import parse_schematic

    result = parse_schematic(Path("my_schematic.kicad_sch"))
    ir = SchematicIR(_parse_result=result)
    assert not ir.dirty
    components = ir.components
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from kicad_agent.parser.types import ParseResult
from kicad_agent.parser.uuid_extractor import UUIDMap

logger = logging.getLogger(__name__)

# Council HIGH: Registry to enforce one-IR-per-ParseResult invariant.
# Uses id() of ParseResult for lookup since dataclass IR instances are unhashable.
_ir_registry: set[int] = set()


def _clear_registry() -> None:
    """Clear the IR registry. For testing only."""
    _ir_registry.clear()


@dataclass
class BaseIR:
    """Base class for all IR types. Tracks mutation state.

    D-05: Holds reference to kiutils object (not a copy).
    D-06: Tracks mutations, UUID map reference, dirty flag.

    IMPORTANT: One IR instance per ParseResult. The registry enforces this
    at construction time -- creating a second IR for the same ParseResult
    raises RuntimeError. Never share kiutils objects between IR instances
    -- mutations would affect all references (Pitfall 2).

    IMPORTANT: The kiutils_obj property provides READ-ONLY access to the
    underlying kiutils object. All mutations must go through IR methods
    that call _record_mutation(). Direct mutation of kiutils_obj fields
    bypasses audit tracking (Council LOW).
    """

    _parse_result: ParseResult
    _uuid_map: Optional[UUIDMap] = None
    _dirty: bool = False
    _mutation_log: list[dict[str, Any]] = field(default_factory=list)

    # Council M-02: Maximum mutation log entries before eviction
    _MAX_MUTATION_LOG = 1000

    def __post_init__(self) -> None:
        """Enforce one-IR-per-ParseResult invariant (Council HIGH)."""
        pr_id = id(self._parse_result)
        if pr_id in _ir_registry:
            raise RuntimeError(
                "ParseResult already has an IR wrapper. "
                "Create only one IR per ParseResult to prevent shared-reference bugs."
            )
        _ir_registry.add(pr_id)

    @property
    def file_path(self) -> Any:
        """Source file path from the ParseResult."""
        return self._parse_result.file_path

    @property
    def file_type(self) -> str:
        """File type string from the ParseResult."""
        return self._parse_result.file_type

    @property
    def dirty(self) -> bool:
        """Whether any mutations have been recorded."""
        return self._dirty

    @property
    def kiutils_obj(self) -> Any:
        """READ-ONLY access to the underlying kiutils object.

        Mutations to this object bypass audit tracking. Use IR methods
        that call _record_mutation() for all modifications (Council LOW).
        """
        return self._parse_result.kiutils_obj

    @property
    def raw_content(self) -> str:
        """Raw file content from the ParseResult."""
        return self._parse_result.raw_content

    @property
    def uuid_map(self) -> Optional[UUIDMap]:
        """UUID map for PCB/footprint serialization."""
        return self._uuid_map

    def _record_mutation(self, description: str, details: dict[str, Any]) -> None:
        """Record a mutation for audit/diagnostic purposes.

        Note: D-08 uses file-level snapshots for actual rollback, not per-field undo.
        This log is for audit trail only.

        Council M-02: Log is capped at _MAX_MUTATION_LOG entries. When the
        cap is reached, the oldest entry is evicted and a warning is logged.
        """
        if len(self._mutation_log) >= self._MAX_MUTATION_LOG:
            evicted = self._mutation_log.pop(0)
            logger.warning(
                "Mutation log cap reached (%d). Evicted oldest entry: %s",
                self._MAX_MUTATION_LOG,
                evicted.get("description", "unknown"),
            )
        self._mutation_log.append({"description": description, **details})
        self._dirty = True

    @property
    def mutation_log(self) -> list[dict[str, Any]]:
        """Read-only access to mutation history.

        Returns a copy to prevent external mutation of the internal log.
        """
        return list(self._mutation_log)
