"""Tests for KiCad 6 to KiCad 10 format converter.

SCHREPAIR-04: Multi-pass format conversion with section-based reassembly.
"""

from pathlib import Path

import pytest

from kicad_agent.ops.format_convert import (
    convert_kicad6_to_10,
    _fix_header,
    _fix_missing_rotation,
    _fix_stroke_format,
    _quote_uuids,
    _fix_fields_autoplaced,
    _remove_net_elements,
    _remove_semicolon_comments,
    _replace_tabs,
    _unwrap_pins_wrapper,
    _unwrap_schematic_objects,
)
from kicad_agent.validation.format_check import validate_kicad10_format


# ---------------------------------------------------------------------------
# Fixture loading helper
# ---------------------------------------------------------------------------

FIXTURE_PATH = Path("tests/data/kicad6_test.kicad_sch")


# ---------------------------------------------------------------------------
# Individual helper tests
# ---------------------------------------------------------------------------


def test_fix_header():
    """_fix_header converts single-line header to multi-line KiCad 10 format."""
    content = '(kicad_sch (version 20211123) (generator eeschema)\n  (uuid a1b2c3d4-e5f6-7890-abcd-ef1234567890)\n)'
    result = _fix_header(content)
    assert "(version 20250114)" in result
    assert '(generator "kicad-agent")' in result
    assert "(generator_version" in result
    assert "a1b2c3d4-e5f6-7890-abcd-ef1234567890" in result


def test_quote_uuids():
    """_quote_uuids quotes bare UUIDs but not already-quoted ones."""
    # Bare UUID gets quoted
    content = '(uuid a1b2c3d4-e5f6-7890-abcd-ef1234567890)'
    result = _quote_uuids(content)
    assert result == '(uuid "a1b2c3d4-e5f6-7890-abcd-ef1234567890")'

    # Already-quoted UUID stays the same
    content = '(uuid "a1b2c3d4-e5f6-7890-abcd-ef1234567890")'
    result = _quote_uuids(content)
    assert result == '(uuid "a1b2c3d4-e5f6-7890-abcd-ef1234567890")'


def test_remove_semicolon_comments():
    """_remove_semicolon_comments removes ;; comments."""
    content = ";; this is a comment\n(symbol ...)  ;; inline comment"
    result = _remove_semicolon_comments(content)
    lines = result.split("\n")
    assert lines[0] == ""  # Full-line comment replaced with blank
    assert ";;" not in lines[1]  # Inline comment removed
    assert "(symbol ...)" in lines[1]


def test_replace_tabs():
    """_replace_tabs converts tabs to 2 spaces."""
    content = "\t\tsymbol"
    result = _replace_tabs(content)
    assert result == "    symbol"
    assert "\t" not in result


def test_remove_net_elements():
    """_remove_net_elements removes (net (code ...)) elements."""
    content = '(net (code 1) (name "VCC")\n  (node (ref "R1") (pin "1") (pin_function ""))\n)\n(wire ...)'
    result = _remove_net_elements(content)
    assert "(net (code" not in result
    assert "(wire ...)" in result


def test_format_check_allows_xy_only_no_connect_and_junction():
    """No-connect markers and junctions are valid with two-coordinate at forms."""
    content = """
(kicad_sch (version 20250114) (generator "kicad-agent")
  (uuid "a1b2c3d4-e5f6-7890-abcd-ef1234567890")
  (no_connect (at 10 20) (uuid "11111111-1111-1111-1111-111111111111"))
  (junction (at 30 40) (diameter 0) (color 0 0 0 0) (uuid "22222222-2222-2222-2222-222222222222"))
  (symbol (lib_id "Device:R") (at 50 60 0) (uuid "33333333-3333-3333-3333-333333333333"))
)
"""
    result = validate_kicad10_format(content, Path("test.kicad_sch"))
    at_check = next(check for check in result.checks if check.name == "at_has_rotation")
    assert at_check.passed


def test_unwrap_schematic_objects():
    """_unwrap_schematic_objects removes wrapper, keeps children."""
    content = '(schematic_objects\n    (symbol (lib_id "Device:R") (at 50 30 0))\n  )\n)'
    result = _unwrap_schematic_objects(content)
    assert "(schematic_objects" not in result
    assert '(symbol (lib_id "Device:R") (at 50 30 0))' in result


def test_unwrap_pins_wrapper():
    """_unwrap_pins_wrapper removes (pins ...) wrapper inside sheets."""
    content = '(sheet (at 100 100) (size 50 50)\n    (pins\n      (pin "SDA" input (at 0 10))\n      (pin "SCL" output (at 0 20))\n    )\n  )'
    result = _unwrap_pins_wrapper(content)
    assert "(pins" not in result
    assert '(pin "SDA" input (at 0 10))' in result
    assert '(pin "SCL" output (at 0 20))' in result


def test_fix_missing_rotation():
    """_fix_missing_rotation adds 0 rotation to (at X Y) forms."""
    content = "(at 50.8 30.48)"
    result = _fix_missing_rotation(content)
    assert result == "(at 50.8 30.48 0)"

    # Already has rotation -- should not change
    content = "(at 50.8 30.48 90)"
    result = _fix_missing_rotation(content)
    assert result == "(at 50.8 30.48 90)"


def test_fix_stroke_format():
    """_fix_stroke_format corrects malformed stroke S-expressions."""
    content = '(stroke (width 0.254)) (type solid))'
    result = _fix_stroke_format(content)
    assert result == '(stroke (width 0.254) (type solid))'


def test_fix_fields_autoplaced():
    """_fix_fields_autoplaced converts bare (fields_autoplaced) to (fields_autoplaced yes)."""
    content = "before\n(fields_autoplaced)\nafter"
    result = _fix_fields_autoplaced(content)
    assert "(fields_autoplaced yes)" in result
    assert "(fields_autoplaced)\n" not in result  # bare version removed
    assert "before" in result
    assert "after" in result


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def test_convert_fixture_passes_format_check():
    """KiCad 6 fixture converts to valid KiCad 10 passing all 9 format checks."""
    content = FIXTURE_PATH.read_text(encoding="utf-8")
    converted = convert_kicad6_to_10(content)

    result = validate_kicad10_format(converted, FIXTURE_PATH)
    if not result.passed:
        failed_checks = [c for c in result.checks if not c.passed]
        details = "\n".join(f"  {c.name}: {c.detail}" for c in failed_checks)
        pytest.fail(
            f"Converted fixture failed format check:\n{details}\n\n"
            f"Converted content:\n{converted}"
        )


def test_convert_empty_content():
    """Empty string returns empty string without error."""
    assert convert_kicad6_to_10("") == ""
    assert convert_kicad6_to_10("  ") == "  "


def test_convert_already_kicad10():
    """Converting already-valid KiCad 10 content produces valid output."""
    kicad10_content = '''(kicad_sch
  (version 20250114)
  (generator "kicad-agent")
  (generator_version "10.0.1")
  (uuid "00000000-0000-0000-0000-000000000001")
  (paper "A4")
  (lib_symbols)
  (sheet_instances
    (path "/" (page "1"))
  )
  (embedded_fonts)
)
'''
    converted = convert_kicad6_to_10(kicad10_content)
    result = validate_kicad10_format(converted, Path("test.kicad_sch"))
    assert result.passed, f"Already-valid KiCad 10 should remain valid after conversion"


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_convert_kicad6_to_10_op_schema():
    """ConvertKicad6To10Op validates correctly."""
    from kicad_agent.ops.schema import ConvertKicad6To10Op, Operation

    op = ConvertKicad6To10Op(
        op_type="convert_kicad6_to_10",
        target_file="legacy.kicad_sch",
    )
    assert op.op_type == "convert_kicad6_to_10"

    # Validate through Operation discriminated union
    wrapped = Operation.model_validate({
        "root": {
            "op_type": "convert_kicad6_to_10",
            "target_file": "legacy.kicad_sch",
        }
    })
    assert wrapped.root.op_type == "convert_kicad6_to_10"
