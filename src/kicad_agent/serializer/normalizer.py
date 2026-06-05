"""Post-process kiutils output to match KiCad-native format.

After kiutils to_file() serialization, run a normalization pass that fixes
property ordering, whitespace, quoting, and token formatting to match
KiCad's native output (D-11 through D-14).

IMPORTANT: Each rule must preserve two-pass round-trip stability.
If pass1 != pass2 after adding a rule, the rule breaks determinism (Pitfall 3).

The normalizer architecture supports incremental rule addition without
breaking existing rules. Phase 2 implements deterministic serialization
(D-12, D-13) with scientific notation fix and whitespace normalization.
Full byte-identical output (D-14) and KiCad-native property ordering
(D-11) require deeper kiutils fixes in later phases.

Usage:
    from kicad_agent.serializer.normalizer import normalize_kicad_output

    normalized = normalize_kicad_output(kiutils_output)
"""

import logging
import re

logger = logging.getLogger(__name__)

# KiCad 10 requires (at X Y angle). kiutils may serialize zero rotation as
# (at X Y), so the normalizer fills in the missing third argument.
_AT_NO_ROTATION = re.compile(r'\(at\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)')

# Scientific notation pattern that avoids matching inside quoted strings.
# Applied only to unquoted segments after string-aware tokenization.
# Requires decimal point in mantissa (e.g. 1.5e-07) to avoid matching
# hex digits in UUID tokens like 000000e95976 (Verifier gap fix).
_SCI_NOTATION = re.compile(r'(?<![a-zA-Z_"(])([-+]?\d+\.\d+)[eE]([-+]?\d+)')


def normalize_kicad_output(content: str) -> str:
    """Post-process kiutils output to match KiCad-native format.

    Applies normalization rules in order:
    1. Fix scientific notation (Pitfall 13) -- e.g. 1.5e-07 -> 0.0000002
    2. Normalize whitespace to spaces with consistent indentation (D-12)
    3. Add missing zero rotation to (at X Y) tokens for KiCad 10 format

    IMPORTANT: Each rule must preserve two-pass round-trip stability.
    If pass1 != pass2 after adding a rule, the rule breaks determinism (Pitfall 3).

    Args:
        content: Serialized S-expression string from kiutils.

    Returns:
        Normalized content string.
    """
    content = _fix_scientific_notation(content)
    content = _normalize_whitespace(content)
    content = _fix_at_rotation(content)
    return content


def _fix_at_rotation(content: str) -> str:
    """Add missing zero rotation to (at X Y) tokens (KiCad 10 format).

    KiCad 10+ requires the rotation angle as a third argument in all
    (at ...) S-expressions. kiutils may serialize position objects
    without rotation as (at X Y). This function appends 0 to these.

    Matches: (at 150 100) -> (at 150 100 0)
    Does NOT match: (at 150 100 0) or (at 150 100 90.0)

    Uses string-aware tokenization to skip quoted strings, same as
    _fix_scientific_notation, to avoid false matches in property values.
    """
    result_parts = []
    i = 0
    while i < len(content):
        if content[i] == '"':
            j = i + 1
            while j < len(content):
                if content[j] == "\\" and j + 1 < len(content):
                    j += 2
                elif content[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            result_parts.append(content[i:j])
            i = j
        else:
            j = content.find('"', i)
            if j == -1:
                j = len(content)
            segment = content[i:j]
            result_parts.append(_AT_NO_ROTATION.sub(r'(at \1 \2 0)', segment))
            i = j
    return "".join(result_parts)


def _fix_scientific_notation(content: str) -> str:
    """Replace scientific notation floats with fixed-point (D-14, Pitfall 13).

    kiutils may output coordinates in scientific notation (e.g. 1.5e-07)
    while KiCad uses fixed-point. This normalizes all scientific notation
    to 6 decimal places, matching KiCad's precision.

    Council M-01: String-aware parsing. S-expression content may contain
    quoted strings with text that looks like scientific notation (e.g.
    property values). This function tokenizes the content to skip quoted
    strings before applying the regex replacement.

    Approach: Split content into quoted and unquoted segments using a
    state machine, apply regex only to unquoted segments, rejoin.
    """

    def _replace_sci(match: re.Match) -> str:
        mantissa = match.group(1)
        exponent = match.group(2)
        value = float(f"{mantissa}e{exponent}")
        return f"{value:.6f}"

    # Council M-01: String-aware tokenization
    result_parts = []
    i = 0
    while i < len(content):
        if content[i] == '"':
            # Find end of quoted string (handle escaped quotes)
            j = i + 1
            while j < len(content):
                if content[j] == '\\' and j + 1 < len(content):
                    j += 2  # Skip escaped character
                elif content[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            # Append quoted string unchanged
            result_parts.append(content[i:j])
            i = j
        else:
            # Find next quote or end of content
            j = content.find('"', i)
            if j == -1:
                j = len(content)
            # Apply sci-notation fix only to unquoted segment
            segment = content[i:j]
            result_parts.append(_SCI_NOTATION.sub(_replace_sci, segment))
            i = j
    return "".join(result_parts)


def _normalize_whitespace(content: str) -> str:
    """Normalize whitespace to spaces with consistent indentation (D-12).

    KiCad uses spaces (not tabs) for indentation. kiutils may produce
    tabs in some contexts. This normalizes all tabs to spaces.

    Does NOT change indentation depth -- kiutils' indentation is already
    close to KiCad's. Only converts tabs to spaces.
    """
    # Replace tabs with spaces (KiCad uses spaces exclusively)
    content = content.replace("\t", "    ")
    return content
