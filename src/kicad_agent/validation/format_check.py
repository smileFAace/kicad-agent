"""KiCad 10 format validator for schematic files.

Validates S-expression format rules specific to KiCad 10. These checks operate
on raw file content (not parsed IR) because many format violations prevent
parsing entirely.

Catches common code-generation mistakes:
  - ;; comments (KiCad 10 parser rejects them)
  - Tab characters (KiCad 10 rejects them)
  - (net ...) auto-generated elements
  - (schematic_objects ...) legacy wrappers
  - (pins ...) wrappers inside sheet elements
  - (at X Y) without rotation value
  - Malformed wire stroke format
  - Unbalanced paren depth
  - Wrong sheet pin format

Usage:
    from kicad_agent.validation.format_check import validate_kicad10_format

    result = validate_kicad10_format(content, file_path)
    if not result.passed:
        for check in result.checks:
            if not check.passed:
                print(f"FAIL: {check.name} - {check.detail}")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled patterns (used in checks that iterate or scan frequently)
# ---------------------------------------------------------------------------

# Lines starting with ;; or containing " ;; " (inline semicolon comments)
_RE_SEMICOLON_LINE = re.compile(r"^;;")
_RE_SEMICOLON_INLINE = re.compile(r" ;; ")

# Auto-generated net elements: (net (code ...))
_RE_NET_ELEMENT = re.compile(r"\(net\s+\(code\s+")

# Legacy KiCad 5 wrapper
_RE_SCHEMATIC_OBJECTS = re.compile(r"\(schematic_objects")

# (pins ...) wrapper inside a sheet element
_RE_PINS_WRAPPER = re.compile(r"\(pins\s*\n")

# (at X Y) with exactly two numeric values (missing rotation)
_RE_AT_NO_ROTATION = re.compile(r"\(at\s+[-\d.]+\s+[-\d.]+\s*\)")

# Correct wire stroke: (stroke (width X) (type Y))
_RE_STROKE_CORRECT = re.compile(r"\(stroke\s+\(width\s+[^\)]+\)\s+\(type\s+[^\)]+\)\)")

# Any stroke element (correct or malformed)
_RE_STROKE_ANY = re.compile(r"\(stroke\b")

# Malformed stroke: (stroke (width X)) (type Y))  -- closing paren after width
# splits the type into a separate form
_RE_STROKE_MALFORMED = re.compile(
    r"\(stroke\s+\(width\s+[^\)]+\)\)\s*\(type\s+[^\)]+\)\)"
)

# Sheet pin with wrong argument order: (type "name" ...) where type is a known
# electrical type keyword that should come AFTER the name.
_PIN_ELECTRICAL_TYPES = frozenset({
    "input", "output", "bidirectional", "tri_state",
    "passive", "unspecified", "power_in", "power_out",
    "open_collector", "open_emitter", "no_connect",
})
_RE_SHEET_PIN_WRONG_ORDER = re.compile(
    r"\(pin\s+\"[^\"]+\"\s+(" + "|".join(_PIN_ELECTRICAL_TYPES) + r")\s"
)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FormatCheck:
    """Result of a single format validation check.

    Attributes:
        name: Machine-readable identifier for the check.
        passed: True if the content passes this check.
        detail: Human-readable description with counts or specifics.
    """

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class FormatCheckResult:
    """Aggregate result of all KiCad 10 format checks.

    Attributes:
        passed: True only if every individual check passed.
        checks: Tuple of individual FormatCheck results.
        file_path: Path to the file that was validated.
    """

    passed: bool
    checks: tuple[FormatCheck, ...]
    file_path: Path


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

def _check_no_semicolon_comments(content: str) -> FormatCheck:
    """Reject ;; comments (KiCad 10 parser rejects them).

    Scans for lines starting with ';;' and for inline ' ;; ' occurrences.
    """
    count = 0
    for line in content.splitlines():
        if _RE_SEMICOLON_LINE.match(line) or _RE_SEMICOLON_INLINE.search(line):
            count += 1

    if count == 0:
        return FormatCheck(
            name="no_semicolon_comments",
            passed=True,
            detail="No semicolon comments found",
        )
    return FormatCheck(
        name="no_semicolon_comments",
        passed=False,
        detail=f"Found {count} line(s) with ;; comments (KiCad 10 rejects these)",
    )


def _check_no_tab_characters(content: str) -> FormatCheck:
    """Reject tab characters (KiCad 10 rejects them)."""
    tab_count = content.count("\t")
    if tab_count == 0:
        return FormatCheck(
            name="no_tab_characters",
            passed=True,
            detail="No tab characters found",
        )
    return FormatCheck(
        name="no_tab_characters",
        passed=False,
        detail=f"Found {tab_count} tab character(s) (KiCad 10 rejects tabs)",
    )


def _check_no_net_elements(content: str) -> FormatCheck:
    """Reject (net (code ...)) auto-generated elements.

    These are produced by older KiCad versions and corrupt on reload in KiCad 10.
    """
    count = len(_RE_NET_ELEMENT.findall(content))
    if count == 0:
        return FormatCheck(
            name="no_net_elements",
            passed=True,
            detail="No auto-generated (net (code ...)) elements found",
        )
    return FormatCheck(
        name="no_net_elements",
        passed=False,
        detail=f"Found {count} auto-generated (net (code ...)) element(s)",
    )


def _check_no_schematic_objects(content: str) -> FormatCheck:
    """Reject (schematic_objects ...) legacy KiCad 5 wrapper."""
    count = len(_RE_SCHEMATIC_OBJECTS.findall(content))
    if count == 0:
        return FormatCheck(
            name="no_schematic_objects",
            passed=True,
            detail="No legacy (schematic_objects ...) wrapper found",
        )
    return FormatCheck(
        name="no_schematic_objects",
        passed=False,
        detail=f"Found {count} legacy (schematic_objects ...) wrapper(s)",
    )


def _check_no_pins_wrapper(content: str) -> FormatCheck:
    """Reject (pins ...) wrappers inside (sheet) elements.

    In KiCad 10, sheet pins must be direct children of (sheet), not wrapped
    in a (pins ...) container.
    """
    # Only flag (pins) that appears to be inside a sheet context.
    # We look for (pins followed by newline which is the wrapper pattern
    # (individual pins look like (pin "name" ...), not (pins\n).
    count = len(_RE_PINS_WRAPPER.findall(content))
    if count == 0:
        return FormatCheck(
            name="no_pins_wrapper",
            passed=True,
            detail="No (pins ...) wrappers found inside sheet elements",
        )
    return FormatCheck(
        name="no_pins_wrapper",
        passed=False,
        detail=f"Found {count} (pins ...) wrapper(s) inside sheet elements",
    )


def _check_at_has_rotation(content: str) -> FormatCheck:
    """Require (at X Y Z) with rotation value for placed elements.

    Every placed symbol and sheet must specify rotation as the third numeric
    value in the (at ...) form.
    """
    matches = [
        m.group(0)
        for m in _RE_AT_NO_ROTATION.finditer(content)
        if not re.search(
            r"\((no_connect|junction)\s+$",
            content[max(0, m.start() - 32):m.start()],
        )
    ]
    count = len(matches)
    if count == 0:
        return FormatCheck(
            name="at_has_rotation",
            passed=True,
            detail="All (at ...) forms include rotation value",
        )
    return FormatCheck(
        name="at_has_rotation",
        passed=False,
        detail=f"Found {count} (at X Y) without rotation value",
    )


def _check_wire_stroke_format(content: str) -> FormatCheck:
    """Validate wire stroke format.

    Correct:   (stroke (width X) (type Y))
    Malformed: (stroke (width X)) (type Y))
    """
    total_strokes = len(_RE_STROKE_ANY.findall(content))
    if total_strokes == 0:
        return FormatCheck(
            name="wire_stroke_format",
            passed=True,
            detail="No wire stroke elements found (nothing to validate)",
        )

    malformed = len(_RE_STROKE_MALFORMED.findall(content))
    correct = len(_RE_STROKE_CORRECT.findall(content))

    # If total != correct + malformed, some strokes have unusual structure;
    # flag the ones we know are malformed.
    if malformed == 0:
        return FormatCheck(
            name="wire_stroke_format",
            passed=True,
            detail=f"All {correct} wire stroke element(s) have correct format",
        )
    return FormatCheck(
        name="wire_stroke_format",
        passed=False,
        detail=f"Found {malformed} malformed wire stroke(s) out of {total_strokes} total",
    )


def _check_balanced_parens(content: str) -> FormatCheck:
    """Verify balanced parentheses throughout the file.

    Tracks paren depth while respecting string literals so that parens
    inside quoted strings do not affect the count.
    """
    depth = 0
    in_string = False
    i = 0
    length = len(content)

    while i < length:
        ch = content[i]

        if in_string:
            if ch == "\\":
                # Escape sequence: skip the next character
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue

        # Not inside a string
        if ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return FormatCheck(
                    name="balanced_parens",
                    passed=False,
                    detail=f"Unbalanced closing paren at character offset {i} (depth went negative)",
                )
        i += 1

    if depth == 0:
        return FormatCheck(
            name="balanced_parens",
            passed=True,
            detail="Parentheses are balanced (depth reaches 0 at EOF)",
        )
    return FormatCheck(
        name="balanced_parens",
        passed=False,
        detail=f"Unbalanced parens: final depth is {depth} (expected 0)",
    )


def _check_sheet_pin_format(content: str) -> FormatCheck:
    """Validate sheet pin argument order.

    KiCad 10 requires: (pin "name" type ...)
    Wrong format:       (pin "name" type ...) where type keyword appears
    in the name position, e.g. (pin input "NET_NAME" ...) is wrong.

    This check detects the inverted form where an electrical type keyword
    appears where a name string is expected.
    """
    # Look for the wrong pattern: (pin <electrical_type> "name" ...)
    # Build a regex that matches (pin input "...") etc. where the type
    # word appears before the quoted name.
    type_words = "|".join(_PIN_ELECTRICAL_TYPES)
    wrong_order_re = re.compile(
        r"\(pin\s+(" + type_words + r")\s+\""
    )
    violations = wrong_order_re.findall(content)

    if not violations:
        return FormatCheck(
            name="sheet_pin_format",
            passed=True,
            detail="All sheet pins use correct (pin \"name\" type ...) format",
        )
    return FormatCheck(
        name="sheet_pin_format",
        passed=False,
        detail=f"Found {len(violations)} sheet pin(s) with wrong argument order: "
               f"types in name position ({', '.join(violations)})",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# All check functions in execution order.
_CHECKS = (
    _check_no_semicolon_comments,
    _check_no_tab_characters,
    _check_no_net_elements,
    _check_no_schematic_objects,
    _check_no_pins_wrapper,
    _check_at_has_rotation,
    _check_wire_stroke_format,
    _check_balanced_parens,
    _check_sheet_pin_format,
)


def validate_kicad10_format(content: str, file_path: Path) -> FormatCheckResult:
    """Run all KiCad 10 format checks against raw schematic content.

    Args:
        content: Raw text content of the KiCad schematic file.
        file_path: Path to the file (used for reporting, not read from disk).

    Returns:
        FormatCheckResult with overall pass/fail and individual check results.
    """
    path = Path(file_path)

    if not content:
        return FormatCheckResult(
            passed=False,
            checks=(
                FormatCheck(
                    name="empty_content",
                    passed=False,
                    detail="File content is empty",
                ),
            ),
            file_path=path,
        )

    checks: list[FormatCheck] = []
    for check_fn in _CHECKS:
        try:
            result = check_fn(content)
        except Exception as exc:
            logger.warning(
                "Format check %s raised exception: %s",
                check_fn.__name__,
                exc,
            )
            result = FormatCheck(
                name=check_fn.__name__,
                passed=False,
                detail=f"Check raised exception: {exc}",
            )
        checks.append(result)

    all_passed = all(c.passed for c in checks)

    if not all_passed:
        failed = [c.name for c in checks if not c.passed]
        logger.info(
            "KiCad 10 format check: %d/%d checks failed for %s (%s)",
            len(failed),
            len(checks),
            path,
            ", ".join(failed),
        )

    return FormatCheckResult(
        passed=all_passed,
        checks=tuple(checks),
        file_path=path,
    )
