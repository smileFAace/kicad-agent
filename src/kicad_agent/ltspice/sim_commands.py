"""Simulation command parser for LTspice directives.

Parses SPICE simulation commands (.tran, .ac, .dc, .noise, .op) from
directive text into frozen dataclasses with engineering notation support.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Engineering notation SI prefix multipliers
_SI_PREFIXES: dict[str, float] = {
    "T": 1e12,
    "G": 1e9,
    "M": 1e6,
    "k": 1e3,
    "m": 1e-3,
    "u": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
}

# Regex for engineering notation: number + optional SI prefix + optional trailing unit chars
_ENG_VALUE_RE = re.compile(r"^([\d.]+)\s*([TGMkmunpf])([a-zA-Z]*)$|^([\d.]+)$")


@dataclass(frozen=True)
class TranCommand:
    """Transient analysis command.

    LTspice format: .tran <Tstep> <Tstop> [Tstart [dTmax]] [modifiers]
    """

    tstart: float
    tstop: float
    tstart_meas: float
    tstep: float


@dataclass(frozen=True)
class AcCommand:
    """AC analysis command.

    LTspice format: .ac <oct|dec|lin> <npoints> <fstart> <fstop>
    """

    sweep: str
    npoints: int
    fstart: float
    fstop: float


@dataclass(frozen=True)
class DcCommand:
    """DC sweep command.

    LTspice format: .dc <src> <start> <stop> <incr>
    """

    source: str
    start: float
    stop: float
    step: float


@dataclass(frozen=True)
class NoiseCommand:
    """Noise analysis command.

    LTspice format: .noise V(<out>) <src> <oct|dec|lin> <npoints> <fstart> <fstop>
    """

    output: str
    source: str
    sweep: str
    npoints: int
    fstart: float
    fstop: float


@dataclass(frozen=True)
class OpCommand:
    """Operating point analysis command.

    LTspice format: .op
    """


SimulationCommand = TranCommand | AcCommand | DcCommand | NoiseCommand | OpCommand


def parse_eng_value(text: str) -> float:
    """Parse an engineering notation value to float.

    Handles SI prefixes: T, G, M, k, m, u, n, p, f.
    Standalone numbers without suffix are returned as-is.

    Args:
        text: Value string (e.g. "1k", "100n", "1ms", "3.3").

    Returns:
        Numeric float value.

    Raises:
        ValueError: If the text cannot be parsed.
    """
    text = text.strip()
    match = _ENG_VALUE_RE.match(text)
    if not match:
        raise ValueError(f"Cannot parse engineering value: {text!r}")

    # Group 1: number with prefix, Group 2: prefix, Group 3: trailing unit
    # Group 4: standalone number
    if match.group(4) is not None:
        # Standalone number, no prefix
        return float(match.group(4))

    number_str = match.group(1)
    prefix = match.group(2)
    number = float(number_str)

    if prefix in _SI_PREFIXES:
        return number * _SI_PREFIXES[prefix]
    return number


def parse_simulation_command(text: str) -> SimulationCommand | None:
    """Parse a SPICE simulation command string into a typed dataclass.

    Supports .tran, .ac, .dc, .noise, and .op commands.
    Returns None if the text is not a recognized simulation command.

    Args:
        text: Raw directive text (e.g. ".tran 0 1ms 0 1u").

    Returns:
        Typed dataclass for the command, or None if unrecognized.
    """
    stripped = text.strip()

    # Match command type
    cmd_match = re.match(r"^\.(tran|ac|dc|noise|op)\b", stripped, re.IGNORECASE)
    if not cmd_match:
        return None

    cmd_type = cmd_match.group(1).lower()
    args_str = stripped[cmd_match.end():].strip()
    args = args_str.split() if args_str else []

    if cmd_type == "op":
        return OpCommand()

    if cmd_type == "tran":
        return _parse_tran(args)

    if cmd_type == "ac":
        return _parse_ac(args)

    if cmd_type == "dc":
        return _parse_dc(args)

    if cmd_type == "noise":
        return _parse_noise(args)

    return None


def _parse_tran(args: list[str]) -> TranCommand:
    """Parse .tran arguments.

    LTspice format: .tran <Tstart> <Tstop> [Tstart_meas [Tstep]]
    When 4 args are given, the order is tstart, tstop, tstart_meas, tstep.
    With 2 args, only tstart and tstop are specified.
    """
    if len(args) < 2:
        raise ValueError(f".tran requires at least 2 arguments, got {len(args)}")

    tstart = parse_eng_value(args[0])
    tstop = parse_eng_value(args[1])
    tstart_meas = parse_eng_value(args[2]) if len(args) > 2 else 0.0
    tstep = parse_eng_value(args[3]) if len(args) > 3 else 0.0

    return TranCommand(
        tstart=tstart,
        tstop=tstop,
        tstart_meas=tstart_meas,
        tstep=tstep,
    )


def _parse_ac(args: list[str]) -> AcCommand:
    """Parse .ac arguments.

    Format: .ac <oct|dec|lin> <npoints> <fstart> <fstop>
    """
    if len(args) < 4:
        raise ValueError(f".ac requires 4 arguments, got {len(args)}")

    return AcCommand(
        sweep=args[0],
        npoints=int(args[1]),
        fstart=parse_eng_value(args[2]),
        fstop=parse_eng_value(args[3]),
    )


def _parse_dc(args: list[str]) -> DcCommand:
    """Parse .dc arguments.

    Format: .dc <src> <start> <stop> <incr>
    """
    if len(args) < 4:
        raise ValueError(f".dc requires 4 arguments, got {len(args)}")

    return DcCommand(
        source=args[0],
        start=parse_eng_value(args[1]),
        stop=parse_eng_value(args[2]),
        step=parse_eng_value(args[3]),
    )


def _parse_noise(args: list[str]) -> NoiseCommand:
    """Parse .noise arguments.

    Format: .noise V(<out>) <src> <oct|dec|lin> <npoints> <fstart> <fstop>
    """
    if len(args) < 6:
        raise ValueError(f".noise requires 6 arguments, got {len(args)}")

    return NoiseCommand(
        output=args[0],
        source=args[1],
        sweep=args[2],
        npoints=int(args[3]),
        fstart=parse_eng_value(args[4]),
        fstop=parse_eng_value(args[5]),
    )
