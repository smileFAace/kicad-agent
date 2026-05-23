"""LTspice integration for .asc schematic parsing, net connectivity, and .raw simulation results."""

from kicad_agent.ltspice.asc_parser import parse_asc
from kicad_agent.ltspice.net_graph import LTspiceNetGraph
from kicad_agent.ltspice.raw_reader import read_raw
from kicad_agent.ltspice.sim_commands import (
    AcCommand,
    DcCommand,
    NoiseCommand,
    OpCommand,
    TranCommand,
    parse_simulation_command,
)
from kicad_agent.ltspice.symbol_mapper import SymbolMapper
from kicad_agent.ltspice.types import (
    LTspiceComponent,
    LTspiceDirective,
    LTspiceFlag,
    LTspiceSchematic,
    LTspiceTrace,
    LTspiceWire,
    SimulationResult,
    SymbolMappingResult,
    SymbolMappingType,
)

__all__ = [
    "AcCommand",
    "DcCommand",
    "LTspiceComponent",
    "LTspiceDirective",
    "LTspiceFlag",
    "LTspiceNetGraph",
    "LTspiceSchematic",
    "LTspiceTrace",
    "LTspiceWire",
    "NoiseCommand",
    "OpCommand",
    "SimulationResult",
    "SymbolMapper",
    "SymbolMappingResult",
    "SymbolMappingType",
    "TranCommand",
    "parse_asc",
    "parse_simulation_command",
    "read_raw",
]
