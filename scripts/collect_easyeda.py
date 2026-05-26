#!/usr/bin/env python3
"""Collect component knowledge from JLCPCB / EasyEDA into training data.

Searches JLCPCB for popular component categories, fetches full CAD data
(pin positions, packages, specs) from EasyEDA, and writes JSONL training
splits.

No GitHub token required. All APIs are anonymous.

Usage:
    python3 scripts/collect_easyeda.py --output-dir training_data_easyeda --max-components 5000

    # Search specific categories
    python3 scripts/collect_easyeda.py --categories "STM32" "ESP32" "NE555" "op-amp"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.crawler.easyeda_api import EasyEdaClient, JlcpcbComponent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("collect_easyeda")

# Popular component categories for broad coverage
DEFAULT_CATEGORIES = [
    "STM32",
    "ESP32",
    "NE555",
    "op-amp",
    "voltage regulator",
    "mosfet N-channel",
    "mosfet P-channel",
    "capacitor 100nF",
    "resistor 10k",
    "LED",
    "USB-C",
    "EEPROM",
    "ADC",
    "DAC",
    "RS485",
    "CAN transceiver",
    "LDO regulator",
    "buck converter",
    "audio amplifier",
    "relay",
    "crystal oscillator",
    "diode schottky",
    "transistor NPN",
    "transistor PNP",
    "connector",
    "electrolytic capacitor",
    "inductor",
    "ferrite bead",
    "TVS diode",
    "level shifter",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect component knowledge from JLCPCB/EasyEDA",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training_data_easyeda"),
        help="Output directory for JSONL splits",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".easyeda_cache"),
        help="Cache directory for API responses",
    )
    parser.add_argument(
        "--categories",
        nargs="*",
        default=None,
        help="Search categories (default: built-in list)",
    )
    parser.add_argument(
        "--max-components",
        type=int,
        default=5000,
        help="Maximum total components to collect",
    )
    parser.add_argument(
        "--pages-per-category",
        type=int,
        default=5,
        help="Max pages to fetch per search category",
    )
    args = parser.parse_args()

    categories = args.categories or DEFAULT_CATEGORIES
    client = EasyEdaClient(cache_dir=args.cache_dir)

    all_samples: list[dict] = []
    seen_lcsc: set[str] = set()
    sample_id = 0
    n_searched = 0
    n_fetched = 0
    n_failed = 0

    for cat_idx, keyword in enumerate(categories):
        if len(all_samples) >= args.max_components:
            logger.info("Reached max %d components, stopping", args.max_components)
            break

        logger.info(
            "Category %d/%d: '%s' (%d collected so far)",
            cat_idx + 1, len(categories), keyword, len(all_samples),
        )

        for page in range(1, args.pages_per_category + 1):
            components, total = client.search_jlcpcb(
                keyword=keyword,
                page=page,
                page_size=25,
            )
            n_searched += len(components)

            if not components:
                break

            for comp in components:
                if comp.lcsc in seen_lcsc:
                    continue
                seen_lcsc.add(comp.lcsc)

                # Fetch CAD data (pins, pads, footprint)
                cad = client.get_component_cad_data(comp.lcsc)

                # Build training sample
                attrs_dict = {a["name"]: a["value"] for a in comp.attributes}

                sample = {
                    "sample_id": sample_id,
                    "source": "jlcpcb_easyeda",
                    "lcsc": comp.lcsc,
                    "name": comp.name,
                    "brand": comp.brand,
                    "package": comp.package,
                    "category": comp.category,
                    "stock": comp.stock,
                    "part_type": comp.part_type,
                    "price": comp.price,
                    "datasheet": comp.datasheet,
                    "pin_count": len(cad.pins) if cad else 0,
                    "pad_count": len(cad.pads) if cad else 0,
                    "pins": [
                        {
                            "number": p.pin_number,
                            "name": p.pin_name,
                            "x": p.pos_x,
                            "y": p.pos_y,
                            "type": p.pin_type,
                        }
                        for p in (cad.pins if cad else ())
                    ],
                    "pads": [
                        {
                            "number": p.pad_number,
                            "x": p.pos_x,
                            "y": p.pos_y,
                            "width": p.width,
                            "height": p.height,
                            "layer": p.layer,
                            "shape": p.shape,
                        }
                        for p in (cad.pads if cad else ())
                    ],
                    "attributes": attrs_dict,
                    "content_hash": hashlib.sha256(
                        f"{comp.lcsc}:{comp.name}:{comp.package}".encode()
                    ).hexdigest(),
                }

                all_samples.append(sample)
                sample_id += 1
                n_fetched += 1

                if cad:
                    logger.debug(
                        "  %s %s: %d pins, %d pads",
                        comp.lcsc, comp.name[:40], len(cad.pins), len(cad.pads),
                    )
                else:
                    n_failed += 1

                if len(all_samples) >= args.max_components:
                    break

                # Rate limit: be gentle
                time.sleep(0.3)

            if len(all_samples) >= args.max_components:
                break

            # Rate limit between pages
            time.sleep(0.5)

        logger.info(
            "  Category '%s' done: %d total components collected",
            keyword, len(all_samples),
        )

    if not all_samples:
        logger.warning("No components collected")
        return 0

    # Dedup by LCSC (already done in memory, but double-check)
    seen: set[str] = set()
    unique: list[dict] = []
    for s in all_samples:
        if s["lcsc"] not in seen:
            seen.add(s["lcsc"])
            unique.append(s)

    # Write JSONL splits
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    import random
    rng = random.Random(42)
    indices = list(range(len(unique)))
    rng.shuffle(indices)
    shuffled = [unique[i] for i in indices]

    train_end = int(len(shuffled) * 0.8)
    val_end = train_end + int(len(shuffled) * 0.1)

    for name, subset in [
        ("train", shuffled[:train_end]),
        ("val", shuffled[train_end:val_end]),
        ("test", shuffled[val_end:]),
    ]:
        path = output_dir / f"{name}.jsonl"
        with open(path, "w") as f:
            for s in subset:
                f.write(json.dumps(s) + "\n")

    # Stats
    with_pins = sum(1 for s in unique if s["pin_count"] > 0)
    categories_found = len(set(s["category"] for s in unique))
    brands_found = len(set(s["brand"] for s in unique))

    print(f"\n{'='*60}")
    print(f"EasyEDA collection complete: {len(unique)} components")
    print(f"  Categories searched: {len(categories)}")
    print(f"  JLCPCB results:      {n_searched}")
    print(f"  CAD data fetched:    {n_fetched}")
    print(f"  CAD fetch failed:    {n_failed}")
    print(f"  With pin data:       {with_pins}")
    print(f"  Unique categories:   {categories_found}")
    print(f"  Unique brands:       {brands_found}")
    print(f"  Splits:              {train_end} train / {val_end - train_end} val / {len(shuffled) - val_end} test")
    print(f"  Output:              {output_dir}/")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
