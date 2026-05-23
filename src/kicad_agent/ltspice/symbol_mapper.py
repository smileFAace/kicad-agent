"""KiCad symbol library ID to LTspice .asy symbol mapping.

Maps KiCad libId strings (e.g., "Device:R") to LTspice .asy symbol names
(e.g., "res"). Handles power symbols as FLAG type instead of SYMBOL.
"""

from __future__ import annotations

from kicad_agent.ltspice.types import SymbolMappingResult, SymbolMappingType

# Standard KiCad Device library symbols -> LTspice .asy names
_DEVICE_MAPPINGS: dict[str, str] = {
    "Device:R": "res",
    "Device:R_Small": "res",
    "Device:R_Small_US": "res",
    "Device:C": "cap",
    "Device:C_Small": "cap",
    "Device:C_Polarized": "cap",
    "Device:L": "ind",
    "Device:L_Small": "ind",
    "Device:D": "diode",
    "Device:D_Zener": "diode",
    "Device:D_Schottky": "diode",
    "Device:LED": "led",
    "Device:Q_NPN": "npn",
    "Device:Q_PNP": "pnp",
    "Device:Q_NMOS": "nmos",
    "Device:Q_PMOS": "pmos",
    "Device:Q_NJFET": "njf",
    "Device:Q_PJFET": "pjf",
    "Device:Opamp": "opamp",
    "Device:Simulation:VOLTAGE": "voltage",
    "Simulation:VOLTAGE": "voltage",
    "Simulation:CURRENT": "current",
}

# Power symbols -> FLAG net label text
_POWER_MAPPINGS: dict[str, str] = {
    "power:GND": "0",
    "power:GNDPWR": "0",
    "power:VCC": "VCC",
    "power:VEE": "VEE",
    "power:+5V": "+5V",
    "power:+3V3": "+3V3",
    "power:+3.3V": "+3.3V",
    "power:+12V": "+12V",
    "power:-12V": "-12V",
    "power:+1V8": "+1V8",
    "power:GNDD": "0",
}

# Prefix for power library detection
_POWER_PREFIX = "power:"


class SymbolMapper:
    """Maps KiCad symbol libId strings to LTspice .asy symbol names.

    Supports:
    - Standard Device library components -> LTspice SYMBOL entries
    - Power library symbols -> LTspice FLAG entries
    - Simulation library sources -> LTspice voltage/current sources
    - Custom user-provided mappings via constructor
    - Unmapped symbols -> UNMAPPED result with empty symbol
    """

    def __init__(self, custom_mappings: dict[str, str] | None = None) -> None:
        """Initialize with optional custom mappings.

        Args:
            custom_mappings: Optional dict of libId -> ltspice_symbol
                            overrides. These take precedence over defaults.
        """
        self._device_map: dict[str, str] = dict(_DEVICE_MAPPINGS)
        self._power_map: dict[str, str] = dict(_POWER_MAPPINGS)
        if custom_mappings:
            for lib_id, symbol in custom_mappings.items():
                if lib_id.startswith(_POWER_PREFIX):
                    self._power_map[lib_id] = symbol
                else:
                    self._device_map[lib_id] = symbol

    def map_symbol(self, lib_id: str) -> SymbolMappingResult:
        """Map a KiCad libId to an LTspice symbol.

        Args:
            lib_id: KiCad symbol library ID (e.g., "Device:R", "power:GND").

        Returns:
            SymbolMappingResult with mapping_type, ltspice_symbol, and is_power.
        """
        # Check power symbols first (they become FLAGs, not SYMBOLs)
        if lib_id in self._power_map:
            return SymbolMappingResult(
                lib_id=lib_id,
                mapping_type=SymbolMappingType.FLAG,
                ltspice_symbol=self._power_map[lib_id],
                is_power=True,
            )

        # Check for power prefix without explicit mapping
        if lib_id.startswith(_POWER_PREFIX):
            # Derive flag text from symbol name: "power:+3V3" -> "+3V3"
            flag_text = lib_id[len(_POWER_PREFIX):]
            return SymbolMappingResult(
                lib_id=lib_id,
                mapping_type=SymbolMappingType.FLAG,
                ltspice_symbol=flag_text,
                is_power=True,
            )

        # Check device mappings
        if lib_id in self._device_map:
            return SymbolMappingResult(
                lib_id=lib_id,
                mapping_type=SymbolMappingType.COMPONENT,
                ltspice_symbol=self._device_map[lib_id],
                is_power=False,
            )

        # Unmapped symbol
        return SymbolMappingResult(
            lib_id=lib_id,
            mapping_type=SymbolMappingType.UNMAPPED,
            ltspice_symbol="",
            is_power=False,
        )
