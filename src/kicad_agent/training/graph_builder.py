"""Board graph construction from schematic+PCB file pairs.

RW-02: Parses schematic+PCB pairs into unified networkx graphs with
component nodes and net edges.

RW-03: Extracts spatial features from PCB and attaches them to graph
nodes as attributes (bounding box, position, rotation).

Composes existing infrastructure:
- SchematicIR for schematic parsing (component references, values)
- PcbIR for PCB parsing (footprints, pads, traces)
- NetGraph for connectivity (net -> pad adjacency)
- spatial/extractor for spatial primitives (points, boxes, paths)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx

from kicad_agent.analysis.connectivity import NetGraph
from kicad_agent.ir.base import _ir_registry
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.parser.pcb_parser import parse_pcb
from kicad_agent.parser.schematic_parser import parse_schematic
from kicad_agent.parser.uuid_extractor import extract_uuids
from kicad_agent.spatial.extractor import extract_all

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# KiCad format version constants
# ---------------------------------------------------------------------------

# KiCad uses date-based version codes in S-expression files.
# We support versions 6+ (introduced 2021). kiutils handles both v6 and v7+
# S-expression grammars. Pre-v6 formats use a different grammar that is
# not reliably parseable.
KICAD_VERSION_6 = 20211014  # KiCad 6.0
KICAD_VERSION_7 = 20230101  # KiCad 7.0
KICAD_VERSION_8 = 20240106  # KiCad 8.0
KICAD_VERSION_9 = 20241129  # KiCad 9.0
KICAD_VERSION_10 = 20250114  # KiCad 10.0

# Minimum version we support for parsing
MIN_KICAD_VERSION = KICAD_VERSION_6

_VERSION_RE = re.compile(r"\(version\s+(\d{8})\)")


def detect_kicad_version(content: str) -> int | None:
    """Extract KiCad format version from file content.

    KiCad S-expression files contain a ``(version YYYYMMDD)`` field near
    the top. Returns None if no version found (likely legacy format).

    Args:
        content: Raw file text content.

    Returns:
        8-digit version integer (e.g. 20241229) or None.
    """
    match = _VERSION_RE.search(content)
    return int(match.group(1)) if match else None


def is_supported_kicad_version(
    sch_content: str,
    pcb_content: str,
    min_version: int = MIN_KICAD_VERSION,
) -> bool:
    """Check whether both files are a supported KiCad format version.

    Args:
        sch_content: Raw schematic file text.
        pcb_content: Raw PCB file text.
        min_version: Minimum supported version (default: KiCad 7).

    Returns:
        True if both files have version >= min_version.
    """
    sch_ver = detect_kicad_version(sch_content)
    pcb_ver = detect_kicad_version(pcb_content)

    if sch_ver is None or pcb_ver is None:
        return False

    return sch_ver >= min_version and pcb_ver >= min_version


def is_likely_parseable(content: str) -> bool:
    """Quick pre-parse check for structural validity.

    Detects obviously corrupt or empty files before expensive kiutils parsing.
    Checks that the file starts with a valid S-expression opener.

    Args:
        content: Raw file text content.

    Returns:
        True if file appears structurally valid.
    """
    stripped = content.strip()
    if not stripped:
        return False
    if not stripped.startswith("("):
        return False
    if len(stripped) < 20:
        return False
    return True


@dataclass(frozen=True)
class BoardGraphResult:
    """Result of building a unified graph from a schematic+PCB pair.

    All fields are primitives or JSON strings to ensure safe serialization
    to JSONL for downstream ML training pipelines.

    Attributes:
        sample_id: Sequential index in dataset.
        repo_url: Source repository URL (empty for local files).
        repo_name: Source repository full name (empty for local files).
        schematic_path: Path to schematic file.
        pcb_path: Path to PCB file.
        component_count: Number of component nodes in the graph.
        net_count: Number of unique nets in the graph.
        layer_count: Number of PCB layers.
        board_width_mm: PCB width in millimeters (0.0 if unavailable).
        board_height_mm: PCB height in millimeters (0.0 if unavailable).
        difficulty: "easy" (<10 components), "medium" (10-50), "hard" (50+).
        board_hash: SHA256 hex digest of raw schematic+PCB content bytes.
        graph_json: networkx graph serialized as JSON (node-link-data format).
        spatial_summary_json: JSON string with spatial feature counts and extents.
    """

    sample_id: int
    repo_url: str
    repo_name: str
    schematic_path: str
    pcb_path: str
    component_count: int
    net_count: int
    layer_count: int
    board_width_mm: float
    board_height_mm: float
    difficulty: str
    board_hash: str
    graph_json: str
    spatial_summary_json: str


def _grade_difficulty(component_count: int) -> str:
    """Grade board difficulty by component count.

    Args:
        component_count: Number of component nodes in the graph.

    Returns:
        One of "easy", "medium", "hard".
    """
    if component_count < 10:
        return "easy"
    if component_count <= 50:
        return "medium"
    return "hard"


def _compute_board_hash(sch_bytes: bytes, pcb_bytes: bytes) -> str:
    """Compute stable SHA256 hash from raw file bytes.

    Hashing raw bytes BEFORE kiutils parsing ensures stable deduplication
    (kiutils serialization is non-deterministic per STATE.md).

    Args:
        sch_bytes: Raw schematic file content.
        pcb_bytes: Raw PCB file content.

    Returns:
        SHA256 hex digest string.
    """
    return hashlib.sha256(sch_bytes + pcb_bytes).hexdigest()


def _build_spatial_summary(spatial_data: dict[str, list]) -> str:
    """Build spatial summary JSON from extracted spatial primitives.

    Args:
        spatial_data: Dict from extract_all() with keys points, boxes, paths, regions.

    Returns:
        JSON string with counts and bounding box extents.
    """
    points = spatial_data.get("points", [])
    boxes = spatial_data.get("boxes", [])
    paths = spatial_data.get("paths", [])
    regions = spatial_data.get("regions", [])

    # Compute bounding box extents from all points
    all_x: list[float] = []
    all_y: list[float] = []
    for pt in points:
        if hasattr(pt, "x") and hasattr(pt, "y"):
            all_x.append(pt.x)
            all_y.append(pt.y)

    for box in boxes:
        if hasattr(box, "x1"):
            all_x.extend([box.x1, box.x2])
            all_y.extend([box.y1, box.y2])

    summary: dict[str, Any] = {
        "point_count": len(points),
        "box_count": len(boxes),
        "path_count": len(paths),
        "region_count": len(regions),
    }

    if all_x and all_y:
        summary["min_x"] = min(all_x)
        summary["max_x"] = max(all_x)
        summary["min_y"] = min(all_y)
        summary["max_y"] = max(all_y)

    return json.dumps(summary, sort_keys=True)


def build_board_graph(
    sch_path: Path,
    pcb_path: Path,
    sample_id: int = 0,
    repo_url: str = "",
    repo_name: str = "",
    sch_repo_path: str = "",
    pcb_repo_path: str = "",
) -> BoardGraphResult | None:
    """Build unified graph from schematic+PCB pair.

    Parses both files, constructs connectivity graph, extracts spatial
    features, merges into a single networkx Graph, and serializes.

    Returns None if parsing fails (format version, corrupt file, etc).
    All exceptions are caught and logged -- never crashes the pipeline.

    Args:
        sch_path: Path to .kicad_sch file.
        pcb_path: Path to .kicad_pcb file.
        sample_id: Sequential sample index for dataset.
        repo_url: Source repository URL.
        repo_name: Source repository full name.
        sch_repo_path: Relative path of schematic within repo.
        pcb_repo_path: Relative path of PCB within repo.

    Returns:
        BoardGraphResult with unified graph data, or None on parse failure.
    """
    # Track IR registry entries created by this call so we can clean up.
    # The IR registry enforces one-IR-per-ParseResult, which prevents reuse
    # of memory addresses across sequential calls to this function.
    _registered_ids: set[int] = set()
    try:
        # 1. Read raw file contents for hashing BEFORE kiutils parsing
        sch_bytes = sch_path.read_bytes()
        pcb_bytes = pcb_path.read_bytes()

        # 2. Pre-parse validation: check format version and structural integrity
        sch_text = sch_bytes.decode("utf-8", errors="replace")
        pcb_text = pcb_bytes.decode("utf-8", errors="replace")

        if not is_likely_parseable(sch_text):
            logger.warning("Skipping unparseable schematic: %s", sch_path)
            return None
        if not is_likely_parseable(pcb_text):
            logger.warning("Skipping unparseable PCB: %s", pcb_path)
            return None

        if not is_supported_kicad_version(sch_text, pcb_text):
            sch_ver = detect_kicad_version(sch_text)
            pcb_ver = detect_kicad_version(pcb_text)
            logger.warning(
                "Skipping unsupported KiCad version: sch=%s, pcb=%s (need >=%d)",
                sch_ver,
                pcb_ver,
                MIN_KICAD_VERSION,
            )
            return None

        # 3. Compute SHA256 hash from raw bytes (stable dedup)
        board_hash = _compute_board_hash(sch_bytes, pcb_bytes)

        # 4. Parse schematic
        sch_result = parse_schematic(sch_path)
        _registered_ids.add(id(sch_result))
        sch_ir = SchematicIR(_parse_result=sch_result)

        # 5. Parse PCB (requires UUID map)
        pcb_result = parse_pcb(pcb_path)
        _registered_ids.add(id(pcb_result))
        uuid_map = extract_uuids(pcb_result.raw_content, "pcb")
        pcb_ir = PcbIR(_parse_result=pcb_result, _uuid_map=uuid_map)

        # 6. Build connectivity graph from PCB
        net_graph = NetGraph.from_pcb_ir(pcb_ir)

        # 7. Extract spatial features
        spatial_data = extract_all(pcb_ir)

        # 8. Build unified graph
        G = nx.Graph()

        # 8a. Add component nodes from schematic symbols
        for sym in sch_ir.components:
            ref = ""
            value = ""
            footprint = ""
            for prop in sym.properties:
                if prop.key == "Reference":
                    ref = prop.value
                elif prop.key == "Value":
                    value = prop.value
                elif prop.key == "Footprint":
                    footprint = prop.value

            if ref:
                G.add_node(
                    ref,
                    node_type="component",
                    value=value,
                    footprint=footprint,
                )

        # 8b. Add net edges from connectivity graph
        # Group pad refs by component reference to create component-level edges
        net_to_components: dict[str, set[str]] = {}
        for net_name, pad_refs in net_graph._net_index.items():
            component_refs: set[str] = set()
            for fp_ref, _pad_num in pad_refs:
                if fp_ref:
                    component_refs.add(fp_ref)
            if len(component_refs) >= 2:
                net_to_components[net_name] = component_refs

        for net_name, component_refs in net_to_components.items():
            refs_list = sorted(component_refs)
            for i in range(len(refs_list)):
                for j in range(i + 1, len(refs_list)):
                    G.add_edge(refs_list[i], refs_list[j], net=net_name)

        # 8c. Add spatial attributes from PCB footprints
        for fp in pcb_ir.footprints:
            fp_ref = fp.properties.get("Reference", "")
            if fp_ref and fp_ref in G.nodes:
                x_mm = fp.position.X
                y_mm = fp.position.Y
                rotation_deg = (
                    fp.position.angle
                    if hasattr(fp.position, "angle") and fp.position.angle is not None
                    else 0.0
                )

                # Compute bounding box from pad positions
                bbox_width_mm = 0.0
                bbox_height_mm = 0.0
                if fp.pads:
                    pad_xs: list[float] = []
                    pad_ys: list[float] = []
                    for pad in fp.pads:
                        pad_xs.append(pad.position.X)
                        pad_ys.append(pad.position.Y)
                    if pad_xs and pad_ys:
                        bbox_width_mm = max(pad_xs) - min(pad_xs)
                        bbox_height_mm = max(pad_ys) - min(pad_ys)

                G.nodes[fp_ref]["x_mm"] = x_mm
                G.nodes[fp_ref]["y_mm"] = y_mm
                G.nodes[fp_ref]["rotation_deg"] = rotation_deg
                G.nodes[fp_ref]["bbox_width_mm"] = bbox_width_mm
                G.nodes[fp_ref]["bbox_height_mm"] = bbox_height_mm

        # 9. Serialize graph to JSON (node-link-data format)
        graph_data = nx.node_link_data(G)
        graph_json = json.dumps(graph_data, sort_keys=True)

        # 10. Build spatial summary
        spatial_summary_json = _build_spatial_summary(spatial_data)

        # 11. Compute metadata
        component_count = sum(
            1 for _, attrs in G.nodes(data=True)
            if attrs.get("node_type") == "component"
        )
        net_count = len(net_graph._net_index)
        difficulty = _grade_difficulty(component_count)

        # 12. Extract board dimensions from PCB general section
        board_width_mm = 0.0
        board_height_mm = 0.0
        board_obj = pcb_ir.board
        if hasattr(board_obj, "general") and board_obj.general:
            gen = board_obj.general
            if hasattr(gen, "thickness") and gen.thickness:
                # KiCad general section stores thickness, not width/height
                # Use paper/auxOrigin or fall through
                pass

        # Count layers from PCB layer definitions
        layer_count = 0
        if hasattr(board_obj, "layers") and board_obj.layers:
            layer_count = len(board_obj.layers)

        # Determine schematic/PCB path strings
        sch_path_str = sch_repo_path if sch_repo_path else str(sch_path)
        pcb_path_str = pcb_repo_path if pcb_repo_path else str(pcb_path)

        # 13. Return result
        result = BoardGraphResult(
            sample_id=sample_id,
            repo_url=repo_url,
            repo_name=repo_name,
            schematic_path=sch_path_str,
            pcb_path=pcb_path_str,
            component_count=component_count,
            net_count=net_count,
            layer_count=layer_count,
            board_width_mm=board_width_mm,
            board_height_mm=board_height_mm,
            difficulty=difficulty,
            board_hash=board_hash,
            graph_json=graph_json,
            spatial_summary_json=spatial_summary_json,
        )

        # Clean up IR registry entries so id() reuse doesn't block future calls
        _ir_registry.difference_update(_registered_ids)
        return result

    except (ValueError, OSError, KeyError, AttributeError, RuntimeError) as e:
        # Clean up IR registry entries even on failure
        _ir_registry.difference_update(_registered_ids)
        logger.warning(
            "Failed to build board graph for %s + %s: %s",
            sch_path,
            pcb_path,
            e,
        )
        return None
    except Exception as e:
        _ir_registry.difference_update(_registered_ids)
        logger.warning(
            "Unexpected error building board graph for %s + %s: %s",
            sch_path,
            pcb_path,
            e,
            exc_info=True,
        )
        return None
