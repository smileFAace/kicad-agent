"""Parse, serialize, and edit .kicad_dru design rule files.

KiCad .kicad_dru files contain custom design rules and net class definitions.
They use S-expression format with version, net_class, and rule entries.

Security (threat model):
- T-10-02: Validate dimension values are positive floats
- Net class names validated against safe identifier pattern
- Cap net classes at 100, custom rules at 200

Usage:
    from kicad_agent.project.design_rules import parse_design_rules, NetClassDef

    dru = parse_design_rules(Path("board.kicad_dru"))
    dru.add_net_class(NetClassDef(name="Power", track_width=0.5, clearance=0.3))
    dru.to_file(Path("board.kicad_dru"))
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import sexpdata

from kicad_agent.serializer.normalizer import normalize_kicad_output

logger = logging.getLogger(__name__)

# Safe identifier pattern for net class and rule names
_SAFE_ID_PATTERN = re.compile(r'^[A-Za-z0-9_\-:.#/]+$')

# Maximum entries (DoS mitigation)
MAX_NET_CLASSES = 100
MAX_CUSTOM_RULES = 200


@dataclass(frozen=True)
class NetClassDef:
    """A net class definition with track/via/clearance dimensions.

    Attributes:
        name: Net class name (e.g. "Default", "Power", "HighSpeed").
        description: Optional description string.
        clearance: Minimum clearance in mm.
        track_width: Default track width in mm.
        via_diameter: Default via diameter in mm.
        via_drill: Default via drill diameter in mm.
        uvia_diameter: Micro-via diameter in mm.
        uvia_drill: Micro-via drill diameter in mm.
        diff_pair_width: Differential pair track width in mm.
        diff_pair_gap: Differential pair gap in mm.
    """

    name: str
    description: str = ""
    clearance: float = 0.0
    track_width: float = 0.0
    via_diameter: float = 0.0
    via_drill: float = 0.0
    uvia_diameter: float = 0.0
    uvia_drill: float = 0.0
    diff_pair_width: float = 0.0
    diff_pair_gap: float = 0.0

    def to_sexp(self) -> str:
        """Serialize this net class to S-expression format.

        Returns:
            S-expression string for the net_class entry.
        """
        lines = [f'(net_class "{self.name}" "{self.description}"']
        if self.clearance > 0:
            lines.append(f"  (clearance {self.clearance})")
        if self.track_width > 0:
            lines.append(f"  (trace_width {self.track_width})")
        if self.via_diameter > 0:
            lines.append(f"  (via_dia {self.via_diameter})")
        if self.via_drill > 0:
            lines.append(f"  (via_drill {self.via_drill})")
        if self.uvia_diameter > 0:
            lines.append(f"  (uvia_dia {self.uvia_diameter})")
        if self.uvia_drill > 0:
            lines.append(f"  (uvia_drill {self.uvia_drill})")
        if self.diff_pair_width > 0:
            lines.append(f"  (diff_pair_width {self.diff_pair_width})")
        if self.diff_pair_gap > 0:
            lines.append(f"  (diff_pair_gap {self.diff_pair_gap})")
        lines.append(")")
        return "\n".join(lines)


@dataclass(frozen=True)
class DesignRule:
    """A custom DRC rule with constraint and condition.

    Attributes:
        name: Rule name (e.g. "HV_clearance").
        constraint_type: Type of constraint (e.g. "clearance", "width").
        constraint_values: Key-value pairs for constraint parameters.
        condition: KiCad condition expression string.
        layer: Optional layer restriction.
        disabled: Whether the rule is disabled.
    """

    name: str
    constraint_type: str
    constraint_values: dict[str, str] = field(default_factory=dict)
    condition: str = ""
    layer: str = ""
    disabled: bool = False

    def to_sexp(self) -> str:
        """Serialize this rule to S-expression format.

        Returns:
            S-expression string for the rule entry.
        """
        parts = [f'(rule "{self.name}"']
        if self.disabled:
            parts.append("  (disabled)")

        # Build constraint expression
        constraint_parts = [f"  (constraint {self.constraint_type}"]
        for key, value in self.constraint_values.items():
            constraint_parts.append(f"({key} {value})")
        constraint_parts.append("  )")
        parts.append(" ".join(constraint_parts))

        if self.condition:
            parts.append(f'  (condition "{self.condition}")')
        if self.layer:
            parts.append(f'  (layer "{self.layer}")')
        parts.append(")")
        return "\n".join(parts)


@dataclass
class DesignRulesFile:
    """A parsed .kicad_dru design rules file.

    Mutable container for net classes and custom DRC rules.

    Attributes:
        net_classes: List of net class definitions.
        custom_rules: List of custom DRC rules.
        version: DRU file version string.
    """

    net_classes: list[NetClassDef] = field(default_factory=list)
    custom_rules: list[DesignRule] = field(default_factory=list)
    version: str = "20240517"

    def add_net_class(self, nc: NetClassDef) -> None:
        """Add a net class. Validates no duplicate name.

        Args:
            nc: The NetClassDef to add.

        Raises:
            ValueError: If duplicate name or exceeds MAX_NET_CLASSES.
        """
        if len(self.net_classes) >= MAX_NET_CLASSES:
            raise ValueError(
                f"Exceeded maximum net classes ({MAX_NET_CLASSES})."
            )
        for existing in self.net_classes:
            if existing.name == nc.name:
                raise ValueError(
                    f"Net class '{nc.name}' already exists."
                )
        self.net_classes.append(nc)

    def remove_net_class(self, name: str) -> NetClassDef:
        """Remove a net class by name.

        Args:
            name: Net class name to remove.

        Returns:
            The removed NetClassDef.

        Raises:
            KeyError: If no net class with the given name exists.
        """
        for i, nc in enumerate(self.net_classes):
            if nc.name == name:
                return self.net_classes.pop(i)
        raise KeyError(f"Net class '{name}' not found.")

    def add_rule(self, rule: DesignRule) -> None:
        """Add a custom DRC rule.

        Args:
            rule: The DesignRule to add.

        Raises:
            ValueError: If exceeds MAX_CUSTOM_RULES.
        """
        if len(self.custom_rules) >= MAX_CUSTOM_RULES:
            raise ValueError(
                f"Exceeded maximum custom rules ({MAX_CUSTOM_RULES})."
            )
        self.custom_rules.append(rule)

    def remove_rule(self, name: str) -> DesignRule:
        """Remove a custom DRC rule by name.

        Args:
            name: Rule name to remove.

        Returns:
            The removed DesignRule.

        Raises:
            KeyError: If no rule with the given name exists.
        """
        for i, rule in enumerate(self.custom_rules):
            if rule.name == name:
                return self.custom_rules.pop(i)
        raise KeyError(f"Design rule '{name}' not found.")

    def modify_net_class(self, name: str, **updates: float) -> NetClassDef:
        """Modify an existing net class by name.

        Uses dataclasses.replace to create a new frozen instance with only
        the specified (non-None) fields updated.

        Args:
            name: Net class name to modify.
            **updates: Keyword arguments of dimension fields to update.

        Returns:
            The new NetClassDef with updated fields.

        Raises:
            KeyError: If no net class with the given name exists.
        """
        import dataclasses as _dc
        for i, nc in enumerate(self.net_classes):
            if nc.name == name:
                filtered = {k: v for k, v in updates.items() if v is not None}
                new_nc = _dc.replace(nc, **filtered)
                self.net_classes[i] = new_nc
                return new_nc
        raise KeyError(f"Net class '{name}' not found.")

    def modify_rule(self, name: str, **updates) -> DesignRule:
        """Modify an existing custom DRC rule by name.

        Uses dataclasses.replace to create a new frozen instance with only
        the specified (non-None) fields updated.

        Args:
            name: Rule name to modify.
            **updates: Keyword arguments of rule fields to update.

        Returns:
            The new DesignRule with updated fields.

        Raises:
            KeyError: If no rule with the given name exists.
        """
        import dataclasses as _dc
        for i, rule in enumerate(self.custom_rules):
            if rule.name == name:
                filtered = {k: v for k, v in updates.items() if v is not None}
                new_rule = _dc.replace(rule, **filtered)
                self.custom_rules[i] = new_rule
                return new_rule
        raise KeyError(f"Design rule '{name}' not found.")

    def to_sexp(self) -> str:
        """Serialize the design rules to S-expression format.

        Returns:
            Complete S-expression string for the .kicad_dru file.
        """
        lines = [f"(version {self.version})"]
        for nc in self.net_classes:
            lines.append("")
            lines.append(nc.to_sexp())
        for rule in self.custom_rules:
            lines.append("")
            lines.append(rule.to_sexp())
        return "\n".join(lines) + "\n"

    def to_file(self, path: Path) -> None:
        """Write the design rules to a file.

        Args:
            path: File path to write.
        """
        content = self.to_sexp()
        normalized = normalize_kicad_output(content)
        path.write_text(normalized, encoding="utf-8")


def _validate_name(name: str) -> None:
    """Validate a net class or rule name is safe.

    Args:
        name: Name to validate.

    Raises:
        ValueError: If the name contains unsafe characters.
    """
    if not _SAFE_ID_PATTERN.match(name):
        raise ValueError(
            f"Name '{name}' contains unsafe characters."
        )


def _validate_dimensions(nc: NetClassDef) -> None:
    """Validate that dimension values are positive floats (T-10-02).

    Zero is allowed (means "use default"). Negative is rejected.

    Args:
        nc: NetClassDef to validate.

    Raises:
        ValueError: If any dimension is negative.
    """
    dims = {
        "clearance": nc.clearance,
        "track_width": nc.track_width,
        "via_diameter": nc.via_diameter,
        "via_drill": nc.via_drill,
        "uvia_diameter": nc.uvia_diameter,
        "uvia_drill": nc.uvia_drill,
        "diff_pair_width": nc.diff_pair_width,
        "diff_pair_gap": nc.diff_pair_gap,
    }
    for dim_name, value in dims.items():
        if value < 0:
            raise ValueError(
                f"Net class '{nc.name}' has negative {dim_name}: {value}"
            )


def _parse_top_level_forms(content: str) -> list[list]:
    """Parse multiple top-level S-expressions from a DRU file.

    DRU files contain multiple top-level forms (version, net_class, rule)
    that are NOT wrapped in an outer S-expression. sexpdata.loads() expects
    a single top-level form, so we wrap the content in parentheses to make
    it a single form, then extract the individual items.

    Args:
        content: Raw text content of the .kicad_dru file.

    Returns:
        List of parsed top-level S-expression items.
    """
    wrapped = f"({content})"
    parsed = sexpdata.loads(wrapped)
    if not isinstance(parsed, list):
        return []
    return parsed


def parse_design_rules(path: Path) -> DesignRulesFile:
    """Parse a .kicad_dru design rules file.

    Args:
        path: Path to the .kicad_dru file.

    Returns:
        Parsed DesignRulesFile with net classes and custom rules.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file content is malformed.
    """
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {path}")

    content = resolved.read_text(encoding="utf-8")
    if not content.strip():
        # Empty file with just a version
        return DesignRulesFile()

    version = "20240517"
    net_classes: list[NetClassDef] = []
    custom_rules: list[DesignRule] = []

    items = _parse_top_level_forms(content)

    for item in items:
        if not isinstance(item, list) or len(item) == 0:
            continue
        key = item[0]
        if isinstance(key, sexpdata.Symbol):
            key_str = str(key)
            if key_str == "version":
                version = str(item[1]) if len(item) > 1 else "20240517"
            elif key_str == "net_class":
                nc = _parse_net_class(item)
                net_classes.append(nc)
            elif key_str == "rule":
                rule = _parse_design_rule(item)
                custom_rules.append(rule)

    return DesignRulesFile(
        net_classes=net_classes,
        custom_rules=custom_rules,
        version=version,
    )


def _parse_net_class(sexp: list) -> NetClassDef:
    """Parse a (net_class ...) S-expression into a NetClassDef.

    Args:
        sexp: Parsed S-expression for the net_class entry.

    Returns:
        NetClassDef with extracted fields.
    """
    name = ""
    description = ""
    clearance = 0.0
    track_width = 0.0
    via_diameter = 0.0
    via_drill = 0.0
    uvia_diameter = 0.0
    uvia_drill = 0.0
    diff_pair_width = 0.0
    diff_pair_gap = 0.0

    # First two positional args after keyword: name (quoted) and description (quoted)
    if len(sexp) > 1:
        name = str(sexp[1])
    if len(sexp) > 2:
        description = str(sexp[2])

    for child in sexp[3:]:
        if not isinstance(child, list) or len(child) < 2:
            continue
        key = child[0]
        if isinstance(key, sexpdata.Symbol):
            key_str = str(key)
            value = child[1]
            try:
                val_float = float(str(value))
            except (ValueError, TypeError):
                continue

            if key_str == "clearance":
                clearance = val_float
            elif key_str == "trace_width":
                track_width = val_float
            elif key_str == "via_dia":
                via_diameter = val_float
            elif key_str == "via_drill":
                via_drill = val_float
            elif key_str == "uvia_dia":
                uvia_diameter = val_float
            elif key_str == "uvia_drill":
                uvia_drill = val_float
            elif key_str == "diff_pair_width":
                diff_pair_width = val_float
            elif key_str == "diff_pair_gap":
                diff_pair_gap = val_float

    return NetClassDef(
        name=name,
        description=description,
        clearance=clearance,
        track_width=track_width,
        via_diameter=via_diameter,
        via_drill=via_drill,
        uvia_diameter=uvia_diameter,
        uvia_drill=uvia_drill,
        diff_pair_width=diff_pair_width,
        diff_pair_gap=diff_pair_gap,
    )


def _parse_design_rule(sexp: list) -> DesignRule:
    """Parse a (rule ...) S-expression into a DesignRule.

    Args:
        sexp: Parsed S-expression for the rule entry.

    Returns:
        DesignRule with extracted fields.
    """
    name = ""
    constraint_type = ""
    constraint_values: dict[str, str] = {}
    condition = ""
    layer = ""
    disabled = False

    # First positional arg after keyword: rule name (quoted)
    if len(sexp) > 1:
        name = str(sexp[1])

    for child in sexp[2:]:
        if not isinstance(child, list) or len(child) == 0:
            continue
        key = child[0]
        if isinstance(key, sexpdata.Symbol):
            key_str = str(key)
            if key_str == "constraint":
                # constraint_type is the first child, values follow
                if len(child) > 1:
                    constraint_type = str(child[1])
                for param in child[2:]:
                    if isinstance(param, list) and len(param) >= 2:
                        param_key = str(param[0])
                        param_val = str(param[1])
                        constraint_values[param_key] = param_val
            elif key_str == "condition":
                if len(child) > 1:
                    condition = str(child[1])
            elif key_str == "layer":
                if len(child) > 1:
                    layer = str(child[1])
            elif key_str == "disabled":
                disabled = True

    return DesignRule(
        name=name,
        constraint_type=constraint_type,
        constraint_values=constraint_values,
        condition=condition,
        layer=layer,
        disabled=disabled,
    )


def serialize_design_rules(dru: DesignRulesFile, path: Path) -> None:
    """Serialize a DesignRulesFile to a file.

    Args:
        dru: The DesignRulesFile to serialize.
        path: File path to write.
    """
    dru.to_file(path)
