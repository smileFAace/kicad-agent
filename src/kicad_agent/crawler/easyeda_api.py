"""EasyEDA / JLCPCB API client for component discovery and CAD data.

Provides anonymous access to:
- JLCPCB component search (keyword, category, pagination)
- EasyEDA component shape data (pin positions, packages, footprints)
- EasyEDA component SVGs (pre-rendered symbols and footprints)

No authentication required for any endpoint.

Usage:
    from kicad_agent.crawler.easyeda_api import EasyEdaClient

    client = EasyEdaClient()
    # Search JLCPCB for STM32 components
    results = client.search_jlcpcb("STM32", page_size=25)
    # Get full CAD data for a component
    cad = client.get_component_cad_data("C83700")
"""

from __future__ import annotations

import gzip
import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# API endpoints (all anonymous, no auth required)
EASYEDA_COMPONENT_API = "https://easyeda.com/api/products/{lcsc_id}/components"
JLCPCB_SEARCH_API = (
    "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
)


@dataclass(frozen=True)
class JlcpcbComponent:
    """A component from JLCPCB search results.

    Attributes:
        lcsc: LCSC part number (e.g., "C83700").
        name: Component name.
        brand: Manufacturer brand.
        package: Package specification (e.g., "LQFP-48").
        category: Component category.
        stock: Current stock count.
        part_type: "Basic" or "Extended".
        price: Unit price (lowest tier).
        datasheet: Datasheet URL.
        attributes: Technical specifications as list of {name, value} dicts.
    """

    lcsc: str
    name: str
    brand: str
    package: str
    category: str
    stock: int
    part_type: str
    price: float | None
    datasheet: str
    attributes: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class EasyEdaPin:
    """A parsed pin from EasyEDA component shape data.

    Attributes:
        pin_number: Pin number (KiCad-compatible).
        pin_name: Pin name/label.
        pos_x: X position in schematic coordinates.
        pos_y: Y position in schematic coordinates.
        rotation: Rotation in degrees.
        pin_type: Pin type (0=unspecified, 1=input, 2=output, 3=bidirectional, 4=power).
    """

    pin_number: str
    pin_name: str
    pos_x: float
    pos_y: float
    rotation: int
    pin_type: int


@dataclass(frozen=True)
class EasyEdaFootprintPad:
    """A parsed pad from EasyEDA footprint data.

    Attributes:
        pad_number: Pad number.
        pos_x: X position relative to footprint center.
        pos_y: Y position relative to footprint center.
        width: Pad width.
        height: Pad height.
        layer: Layer ID (1=top, 31=bottom).
        shape: Pad shape string.
        net: Net name if assigned.
    """

    pad_number: str
    pos_x: float
    pos_y: float
    width: float
    height: float
    layer: int
    shape: str
    net: str = ""


@dataclass(frozen=True)
class EasyEdaComponentData:
    """Full parsed component data from EasyEDA API.

    Attributes:
        lcsc: LCSC part number.
        title: Component title.
        package: Package specification.
        pins: Schematic pins.
        pads: Footprint pads.
        data_str: Raw shape data string.
    """

    lcsc: str
    title: str
    package: str
    pins: tuple[EasyEdaPin, ...] = ()
    pads: tuple[EasyEdaFootprintPad, ...] = ()
    data_str: str = ""


class EasyEdaClient:
    """Anonymous API client for JLCPCB search and EasyEDA component data.

    Handles gzip decompression, SSL context, and JSON parsing.
    Optional file-based caching to avoid repeated API calls.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._headers = {
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://easyeda.com/",
        }
        self._ssl_context = ssl.create_default_context()
        self._cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _fetch_json(
        self,
        url: str,
        data: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch JSON from a URL with gzip handling."""
        headers = {**self._headers, **(extra_headers or {})}
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=30, context=self._ssl_context) as resp:
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        if not self._cache_dir:
            return None
        path = self._cache_dir / f"{key}.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def _cache_put(self, key: str, data: dict[str, Any]) -> None:
        if not self._cache_dir:
            return
        path = self._cache_dir / f"{key}.json"
        path.write_text(json.dumps(data, indent=2))

    def search_jlcpcb(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 25,
        part_type: str | None = None,
    ) -> tuple[list[JlcpcbComponent], int]:
        """Search JLCPCB components by keyword.

        Args:
            keyword: Search query (e.g., "STM32", "NE555", "100nF 0402").
            page: Page number (1-indexed).
            page_size: Results per page (max 25).
            part_type: "base" for Basic, "expand" for Extended, None for both.

        Returns:
            Tuple of (component_list, total_results).
        """
        payload: dict[str, Any] = {
            "keyword": keyword,
            "currentPage": page,
            "pageSize": page_size,
        }
        if part_type:
            payload["componentLibraryType"] = part_type

        try:
            raw = self._fetch_json(
                JLCPCB_SEARCH_API,
                data=json.dumps(payload).encode("utf-8"),
                extra_headers={
                    "Content-Type": "application/json",
                    "Origin": "https://jlcpcb.com",
                    "Referer": "https://jlcpcb.com/parts",
                },
            )
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.warning("JLCPCB search failed for '%s': %s", keyword, e)
            return [], 0

        page_info = (raw.get("data") or {}).get("componentPageInfo") or {}
        total = page_info.get("total", 0)
        items: list[dict] = page_info.get("list") or []

        components: list[JlcpcbComponent] = []
        for item in items:
            prices = item.get("componentPrices") or []
            price = float(prices[0]["productPrice"]) if prices else None

            components.append(JlcpcbComponent(
                lcsc=item.get("componentCode", ""),
                name=item.get("componentName", ""),
                brand=item.get("componentBrandEn", ""),
                package=item.get("componentSpecificationEn", ""),
                category=item.get("componentTypeEn", ""),
                stock=item.get("stockCount", 0),
                part_type=(
                    "Basic" if item.get("componentLibraryType") == "base" else "Extended"
                ),
                price=price,
                datasheet=item.get("dataManualUrl", ""),
                attributes=tuple(
                    {"name": a.get("attribute_name_en", ""), "value": a["attribute_value_name"]}
                    for a in (item.get("attributes") or [])
                    if a.get("attribute_value_name") and a["attribute_value_name"] != "-"
                ),
            ))

        return components, total

    def get_component_cad_data(self, lcsc_id: str) -> EasyEdaComponentData | None:
        """Fetch full CAD data for a component by LCSC part number.

        Returns parsed pins, pads, and raw shape data.

        Args:
            lcsc_id: LCSC part number (e.g., "C83700").

        Returns:
            EasyEdaComponentData or None if not found.
        """
        # Check cache
        cached = self._cache_get(f"cad_{lcsc_id}")
        if cached is None:
            try:
                raw = self._fetch_json(
                    EASYEDA_COMPONENT_API.format(lcsc_id=lcsc_id),
                )
            except (urllib.error.URLError, json.JSONDecodeError) as e:
                logger.warning("EasyEDA API failed for %s: %s", lcsc_id, e)
                return None

            if not raw or raw.get("success") is False:
                return None

            self._cache_put(f"cad_{lcsc_id}", raw)
        else:
            raw = cached

        result = raw.get("result", {})
        if not result:
            return None

        # Extract dataStr (can be a dict with 'shape' list or a raw string)
        data_str_raw = result.get("dataStr", "")
        title = result.get("title", "")
        package_hint = ""

        # Normalize to shape list
        if isinstance(data_str_raw, dict):
            shape_list = data_str_raw.get("shape", [])
            head = data_str_raw.get("head", {})
            c_para = head.get("c_para", {})
            package_hint = c_para.get("package", "")
            data_str = "\n".join(shape_list)
        elif isinstance(data_str_raw, str):
            data_str = data_str_raw
        else:
            data_str = ""

        # Parse pin and pad data from shape strings
        pins = _parse_pins(data_str)
        pads = _parse_pads(data_str)

        return EasyEdaComponentData(
            lcsc=lcsc_id,
            title=title,
            package=package_hint,
            pins=pins,
            pads=pads,
            data_str=data_str,
        )


# ---------------------------------------------------------------------------
# Shape data parsing
# ---------------------------------------------------------------------------


def _parse_pins(data_str: str) -> tuple[EasyEdaPin, ...]:
    """Parse schematic pins from EasyEDA delimited shape data.

    Pin format: P~settings^^dot^^path^^name^^num^^dot_bis^^clock
    settings: visibility~type~spice_pin_number~pos_x~pos_y~rotation~id~is_locked
    num: show~x~y~rotation~number~text_anchor~font~font_size
    """
    pins: list[EasyEdaPin] = []

    for line in data_str.split("\n"):
        line = line.strip()
        if not line.startswith("P~"):
            continue

        try:
            segments = line[2:].split("^^")
            if len(segments) < 5:
                continue

            # Parse settings
            settings = segments[0].split("~")
            if len(settings) < 8:
                continue

            pin_type = int(float(settings[1])) if settings[1] else 0
            pos_x = float(settings[3]) if settings[3] else 0.0
            pos_y = float(settings[4]) if settings[4] else 0.0
            rotation = int(float(settings[5])) if settings[5] else 0

            # Parse name (segment 3)
            name_parts = segments[3].split("~") if len(segments) > 3 else []
            pin_name = name_parts[4] if len(name_parts) > 4 else ""

            # Parse number (segment 4) - this is the KiCad pin number
            num_parts = segments[4].split("~") if len(segments) > 4 else []
            pin_number = num_parts[4] if len(num_parts) > 4 else ""

            if pin_number:
                pins.append(EasyEdaPin(
                    pin_number=pin_number,
                    pin_name=pin_name,
                    pos_x=pos_x,
                    pos_y=pos_y,
                    rotation=rotation,
                    pin_type=pin_type,
                ))
        except (ValueError, IndexError):
            continue

    return tuple(pins)


def _parse_pads(data_str: str) -> tuple[EasyEdaFootprintPad, ...]:
    """Parse footprint pads from EasyEDA delimited shape data.

    Pad format: PAD~shape~x~y~width~height~layer~net~id~hole_radius~points~rotation~hole_length~hole_points~plated_hole~hole_x~hole_y~pad_angle
    """
    pads: list[EasyEdaFootprintPad] = []

    for line in data_str.split("\n"):
        line = line.strip()
        if not line.startswith("PAD~"):
            continue

        try:
            parts = line[4:].split("~")
            if len(parts) < 6:
                continue

            shape = parts[0]
            pos_x = float(parts[1]) if parts[1] else 0.0
            pos_y = float(parts[2]) if parts[2] else 0.0
            width = float(parts[3]) if parts[3] else 0.0
            height = float(parts[4]) if parts[4] else 0.0
            layer = int(float(parts[5])) if len(parts) > 5 and parts[5] else 1

            # Pad number is typically in parts[7] or derivable from pad shape data
            pad_number = parts[8] if len(parts) > 8 else ""

            pads.append(EasyEdaFootprintPad(
                pad_number=pad_number,
                pos_x=pos_x,
                pos_y=pos_y,
                width=width,
                height=height,
                layer=layer,
                shape=shape,
            ))
        except (ValueError, IndexError):
            continue

    return tuple(pads)
