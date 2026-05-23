# Phase 13: Real-World PCB Training Pipeline - Research

**Researched:** 2026-05-23
**Domain:** GitHub data mining, PCB graph extraction, training dataset engineering
**Confidence:** HIGH

## Summary

Phase 13 builds a data pipeline that discovers real KiCad repositories on GitHub, clones them, parses their schematic+PCB file pairs into structured graph representations, and exports the resulting dataset in a format compatible with the Phase 9 GRPO training pipeline. This transforms the project from training on synthetic maze-routing puzzles to training on real-world board designs with actual component topologies, net connectivity patterns, and spatial layouts.

The core technical challenge is bridging three layers: (1) GitHub API discovery with rate-limit-aware pagination, (2) kicad-agent's existing parser stack (SchematicIR, PcbIR, spatial extractors, NetGraph) to produce per-board graph structures, and (3) normalization into a frozen-dataclass + JSONL dataset format that follows the established MazeSample/MazeDataset pattern. Each layer has well-understood solutions -- PyGithub for GitHub access, networkx for graph representation (already a project dependency), and the existing training dataset infrastructure for serialization.

**Primary recommendation:** Use PyGithub 2.9.1 for GitHub discovery, reuse kicad-agent's existing IR layer and spatial extractors for graph construction, represent boards as networkx graphs with JSON serialization, and output a `RealBoardDataset` with JSONL format mirroring MazeDataset's structure. PyTorch Geometric export is optional and deferred to the training consumer.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| GitHub repo discovery | API / Backend | -- | HTTP client calling GitHub REST API, no browser involvement |
| File cloning/extraction | API / Backend | -- | git clone or GitHub Contents API for .kicad_sch/.kicad_pcb files |
| Schematic parsing | API / Backend | -- | SchematicIR wraps kiutils -- pure Python parsing |
| PCB parsing | API / Backend | -- | PcbIR wraps kiutils -- pure Python parsing |
| Graph construction | API / Backend | -- | networkx in-memory graph from parsed IR objects |
| Spatial feature extraction | API / Backend | -- | Existing spatial/primitives.py + spatial/extractor.py |
| Dataset serialization | API / Backend | Database / Storage | JSONL files to disk, following MazeDataset pattern |
| GRPO format export | API / Backend | -- | JSONL output consumed by Phase 9 training pipeline |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| PyGithub | 2.9.1 | GitHub REST API client | Most mature Python GitHub client; handles auth, pagination, rate limits [VERIFIED: pip3 index] |
| networkx | 3.4.2 | Graph representation (component/net topology) | Already a project dependency; used in connectivity.py [VERIFIED: pip3 show] |
| kiutils | 1.4.8 | KiCad file parsing | Already a project dependency; used in SchematicIR/PcbIR [VERIFIED: pip3 show] |
| pydantic | 2.12.5 | Schema validation for dataset metadata | Already a project dependency; used for operation schemas [VERIFIED: pip3 show] |
| shapely | 2.1.1 | Spatial geometry (bounding boxes, intersections) | Already a project dependency; used in spatial/primitives.py [VERIFIED: pip3 show] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx | 0.28.1 | HTTP client (fallback for raw GitHub API calls) | Already a project dependency; used if PyGithub pagination insufficient [VERIFIED: pip3 show] |
| PyTorch Geometric (torch-geometric) | 2.7.0 | GNN training data format (HeteroData) | Optional export format for Phase 9 GRPO consumer; not a hard dependency [VERIFIED: pip3 index] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| PyGithub | ghapi (fastai) | ghapi is faster but less mature, less documentation. PyGithub has battle-tested pagination and rate limit handling. |
| PyGithub | raw httpx REST calls | More control but must hand-roll pagination, rate limit tracking, auth, error retry. Not worth it. |
| networkx native format | PyG HeteroData | PyG is ML-specific but adds heavy torch dependency. Export as optional converter, not primary format. |
| JSONL | HDF5 / Parquet | HDF5/Parquet are better for very large datasets (100k+). At 1k-50k boards, JSONL is simpler and matches MazeDataset. |

**Installation:**
```bash
pip install PyGithub>=2.9.1
```

Note: networkx, kiutils, pydantic, shapely, httpx are already in project dependencies. Only PyGithub is a new addition.

**Version verification:**
```
PyGithub: 2.9.1 (latest, verified 2026-05-23 via pip3 index)
networkx: 3.4.2 (installed, verified 2026-05-23)
kiutils: 1.4.8 (installed, verified 2026-05-23)
pydantic: 2.12.5 (installed, verified 2026-05-23)
shapely: 2.1.1 (installed, verified 2026-05-23)
httpx: 0.28.1 (installed, verified 2026-05-23)
```

## Architecture Patterns

### System Architecture Diagram

```
GitHub REST API
      |
      v
+------------------+     +-------------------+
| GitHub Discovery |---->| Rate Limiter      |
| (PyGithub)       |     | (token bucket)    |
+------------------+     +-------------------+
      |
      v  (repo list with .kicad_sch + .kicad_pcb)
+------------------+
| File Fetcher     |--- git clone sparse or Contents API
+------------------+
      |
      v  (raw .kicad_sch, .kicad_pcb files)
+------------------+     +-------------------+
| SchematicIR      |     | PcbIR             |
| (kiutils parse)  |     | (kiutils parse)   |
+------------------+     +-------------------+
      |                        |
      v                        v
+------------------+     +-------------------+
| Net Graph        |     | Spatial Extractor |
| (connectivity.py)|     | (extractor.py)    |
+------------------+     +-------------------+
      |                        |
      +----------+-------------+
                 |
                 v
      +---------------------+
      | Board Graph Builder |--- merges schematic net graph
      |                     |    with PCB spatial features
      +---------------------+
                 |
                 v
      +---------------------+
      | Dedup / Quality     |--- SHA256 content hash
      | Filter              |    min component/net thresholds
      +---------------------+
                 |
                 v
      +---------------------+
      | RealBoardDataset    |--- frozen dataclass + JSONL
      | (dataset.py)        |    train/val/test split
      +---------------------+
                 |
                 v  (optional)
      +---------------------+
      | PyG Exporter        |--- HeteroData converter
      |                     |    for GRPO training
      +---------------------+
```

### Recommended Project Structure
```
src/kicad_agent/
├── training/
│   ├── dataset.py          # MazeSample, MazeDataset (EXISTING)
│   ├── real_dataset.py     # RealBoardSample, RealBoardDataset (NEW)
│   ├── graph_builder.py    # Schematic+PCB -> networkx graph (NEW)
│   └── ...
├── crawler/
│   ├── __init__.py          # NEW module
│   ├── github_discovery.py  # GitHub repo search (RW-01)
│   ├── file_fetcher.py      # Clone/download KiCad files (RW-01)
│   └── rate_limiter.py      # Token bucket for API limits
└── ...
```

### Pattern 1: Frozen Dataclass + JSONL Dataset (follows MazeSample pattern)
**What:** Each real board is a frozen dataclass with JSONL serialization, matching the established training dataset convention.
**When to use:** All dataset types in the training module.

The existing `MazeSample` uses this exact pattern:
```python
@dataclass(frozen=True)
class MazeSample:
    sample_id: int
    seed: int
    board_width_mm: float
    # ... all fields are primitive/serializable
    board_hash: str  # SHA256 for dedup
```

The new `RealBoardSample` should follow identically:
```python
@dataclass(frozen=True)
class RealBoardSample:
    sample_id: int
    repo_url: str
    repo_name: str
    schematic_path: str
    pcb_path: str
    component_count: int
    net_count: int
    board_hash: str  # SHA256 of schematic+pcb content
    graph_json: str  # serialized networkx graph as JSON string
    difficulty: str  # "easy"/"medium"/"hard" based on component count
    # ... spatial summary fields
```

### Pattern 2: GitHub Search with Rate Limit Awareness
**What:** PyGithub search with exponential backoff on rate limit hits.
**When to use:** All GitHub API interactions.

```python
# PyGithub search pattern
from github import Github, GithubException

g = Github(token)  # OAuth token for 5000 req/hr

# Search repos containing KiCad files
repos = g.search_repositories(
    query="kicad_pcb language:kicad",
    sort="stars",
    order="desc"
)

# Paginate with rate limit awareness
for repo in repos:
    if repo.remaining < 100:
        # Sleep until rate limit resets
        core_rate_limit = g.get_rate_limit().core
        sleep_seconds = (core_rate_limit.reset - datetime.now()).total_seconds()
        time.sleep(max(sleep_seconds, 0))
```

### Pattern 3: Graph Construction from Existing IR
**What:** Build networkx graph by composing SchematicIR (net connectivity) + PcbIR (spatial layout).
**When to use:** Every board pair ingestion.

```python
# Leverage existing infrastructure
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.analysis.connectivity import NetGraph
from kicad_agent.spatial.extractor import extract_all

# Parse files (existing code)
sch_ir = SchematicIR.from_file("board.kicad_sch")
pcb_ir = PcbIR.from_file("board.kicad_pcb")

# Build connectivity graph (existing code)
net_graph = NetGraph.from_pcb_ir(pcb_ir)

# Extract spatial features (existing code)
spatial = extract_all(pcb_ir)

# Merge into unified graph (NEW code)
board_graph = build_board_graph(sch_ir, pcb_ir, net_graph, spatial)
```

### Anti-Patterns to Avoid
- **Cloning entire repos:** Many KiCad repos are 100MB+ with git history. Use sparse checkout or Contents API to fetch only .kicad_sch/.kicad_pcb files.
- **Parsing on the main thread:** Large boards take 1-5 seconds to parse. Use concurrent.futures for parallel parsing of downloaded file pairs.
- **Storing parsed objects in dataset:** Dataset samples must contain serializable data (JSON strings, primitives), not live kiutils objects. Serialize immediately after parsing.
- **Assuming all repos have valid pairs:** Many repos have orphaned .kicad_pcb files without matching .kicad_sch (or vice versa). Always validate both files exist before ingestion.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| GitHub API pagination | Manual page iteration | PyGithub PaginatedList | Handles Link headers, rate limits, incomplete results |
| Rate limiting | Sleep with hardcoded values | PyGithub `get_rate_limit()` + calculated sleep | Reset time varies; PyGithub exposes exact reset timestamp |
| KiCad file parsing | Custom S-expression parser | kiutils via SchematicIR/PcbIR | Already handles format version differences, UUID preservation |
| Net connectivity graph | Manual adjacency lists | NetGraph.from_pcb_ir() | Already handles pad-level connectivity with networkx |
| Spatial feature extraction | Manual coordinate math | spatial/extractor.py (extract_all) | Already handles rotation-aware positioning, mm coordinates |
| Content deduplication | Filename comparison | SHA256 content hash | Same board appears in many repos; only content hash catches duplicates |
| JSONL serialization | Custom write format | MazeDataset.to_jsonl pattern | Battle-tested with Phase 9; handles train/val/test split |

**Key insight:** Phase 13's primary work is the crawler and dataset assembly, not the parsing or graph construction. The parsing stack already exists (Phases 1-8). The graph representation already exists (NetGraph, spatial extractors). The dataset format already exists (MazeDataset JSONL). Phase 13 connects these pieces and adds the GitHub discovery layer.

## Common Pitfalls

### Pitfall 1: GitHub Search API Rate Limits
**What goes wrong:** Unauthenticated search is limited to 10 requests/minute. Authenticated search is 30 requests/minute. Exceeding limits returns 403 with no useful data.
**Why it happens:** Developers assume GitHub Search has the same limits as Core API (5000/hr authenticated). Search has separate, stricter limits.
**How to avoid:** Use authenticated requests (GITHUB_TOKEN env var). Monitor `X-RateLimit-Remaining` header via PyGithub's `get_rate_limit().search`. Implement exponential backoff.
**Warning signs:** 403 responses, `API rate limit exceeded` messages, incomplete search results.

### Pitfall 2: KiCad Format Version Incompatibility
**What goes wrong:** Some repos contain KiCad 5 or KiCad 6 format files. kicad-agent targets KiCad 10+. kiutils may throw on older formats.
**Why it happens:** GitHub search returns all repos matching "kicad_pcb" regardless of format version. KiCad 5 files use different syntax than KiCad 7+.
**How to avoid:** Validate format version during parsing. Wrap in try/except and skip boards that fail to parse. Log skipped boards with parse error details. Filter by file header ("kicad_sexpr" vs legacy format).
**Warning signs:** `ValueError` or `TypeError` from kiutils during parsing. Files starting with `(module ...` instead of `(footprint ...`.

### Pitfall 3: Orphaned Schematic/PCB Files
**What goes wrong:** A repo has .kicad_pcb but no .kicad_sch (or vice versa). Attempting to pair them produces incomplete graph data.
**Why it happens:** Many hardware projects only publish PCB files (gerbers + .kicad_pcb) without schematics. Some only publish schematics.
**How to avoid:** For RW-02/03 (graph parser), both files are required. For RW-01 (discovery), catalog repos with EITHER file type but mark pairs as complete only when both exist. Set clear expectations: the dataset will have fewer entries than repos discovered because pairing is required.
**Warning signs:** Count of discovered repos >> count of valid board pairs.

### Pitfall 4: Large Repos Blocking Pipeline
**What goes wrong:** git clone on a 500MB repo with full history blocks the pipeline for minutes. At 1000+ repos, this becomes hours of waiting.
**Why it happens:** Hardware repos often include 3D models, gerbers, documentation, and git history spanning years.
**How to avoid:** Use GitHub Contents API to fetch individual files instead of git clone. If clone is necessary, use `--depth 1` (shallow) and `--filter=blob:none` (sparse). PyGithub's `get_contents()` method retrieves individual files without cloning.
**Warning signs:** Pipeline run taking >10 minutes for <100 repos. Disk space growing rapidly.

### Pitfall 5: Non-Deterministic Deduplication
**What goes wrong:** SHA256 hash of serialized KiCad files changes between runs due to kiutils non-deterministic serialization (noted in STATE.md: "kiutils serialization non-determinism means board_hash differs across runs with same seed").
**Why it happens:** kiutils may reorder properties or adjust whitespace during serialization.
**How to avoid:** Hash the RAW file content (before kiutils parsing), not the re-serialized output. This is already established in MazeSample -- use raw content read before kiutils parsing (per STATE.md decision: "Raw content read before kiutils parsing to preserve PCB/footprint UUIDs").
**Warning signs:** Same board produces different hashes on consecutive runs.

### Pitfall 6: Memory Exhaustion at Scale
**What goes wrong:** Loading 1000+ board graphs into memory simultaneously causes OOM.
**Why it happens:** Each networkx graph with component nodes, net edges, and spatial features can be 1-10MB in memory. 1000 boards = 1-10GB.
**How to avoid:** Stream processing -- parse one board, serialize to JSONL, discard from memory, move to next. Follow JSONL streaming pattern already established in training module (STATE.md: "JSONL streaming for dataset/chain I/O to avoid memory exhaustion at 100k+ scale").
**Warning signs:** Memory usage growing linearly with board count. System swapping.

## Code Examples

### GitHub Repo Discovery (PyGithub)
```python
# Source: PyGithub 2.9.1 API docs (https://pygithub.readthedocs.io/)
from github import Github, Auth
import os

# Authenticated client (5000 core req/hr, 30 search req/min)
auth = Auth.Token(os.environ["GITHUB_TOKEN"])
g = Github(auth=auth)

# Discover repos with KiCad PCB files
# Use multiple search queries to maximize coverage
queries = [
    "kicad_pcb filename:kicad_pcb",
    "kicad_sch filename:kicad_sch",
    "extension:kicad_pcb extension:kicad_sch",
    "topic:kicad",
    "topic:pcb-design",
]

discovered_repos = set()
for query in queries:
    results = g.search_repositories(query, sort="stars", order="desc")
    for repo in results:
        discovered_repos.add((repo.full_name, repo.html_url, repo.stargazers_count))
```

### Checking for File Pairs in a Repo
```python
# Source: PyGithub Contents API
from github import GithubException

def find_kicad_pairs(repo, token: str) -> list[tuple[str, str]]:
    """Find schematic+PCB file pairs in a GitHub repo.

    Returns list of (schematic_path, pcb_path) tuples.
    Uses tree API for efficiency (single request for full file listing).
    """
    try:
        tree = repo.get_git_tree(repo.default_branch, recursive=True)
    except GithubException:
        return []

    sch_files = {}
    pcb_files = {}

    for entry in tree.tree:
        if entry.path.endswith(".kicad_sch"):
            # Key on directory + base name (without extension)
            base = entry.path.rsplit(".", 1)[0]
            sch_files[base] = entry.path
        elif entry.path.endswith(".kicad_pcb"):
            base = entry.path.rsplit(".", 1)[0]
            pcb_files[base] = entry.path

    # Match pairs by shared base name
    pairs = []
    for base in sch_files:
        if base in pcb_files:
            pairs.append((sch_files[base], pcb_files[base]))

    return pairs
```

### Board Graph Construction (reusing existing infrastructure)
```python
# Source: existing kicad-agent modules
import json
import hashlib
import networkx as nx
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.analysis.connectivity import NetGraph
from kicad_agent.spatial.extractor import extract_all


def build_board_graph(
    sch_path: str,
    pcb_path: str,
    raw_sch_content: bytes,
    raw_pcb_content: bytes,
) -> tuple[nx.Graph, str, dict]:
    """Build unified graph from schematic+PCB pair.

    Returns: (networkx_graph, content_hash, metadata_dict)
    """
    # Hash raw content for dedup (before kiutils parsing)
    hasher = hashlib.sha256()
    hasher.update(raw_sch_content)
    hasher.update(raw_pcb_content)
    content_hash = hasher.hexdigest()

    # Parse with existing IR layer
    sch_ir = SchematicIR.from_file(sch_path)
    pcb_ir = PcbIR.from_file(pcb_path)

    # Build connectivity graph (existing NetGraph)
    net_graph = NetGraph.from_pcb_ir(pcb_ir)

    # Extract spatial features (existing spatial module)
    spatial = extract_all(pcb_ir)

    # Build unified graph
    G = nx.Graph()

    # Add component nodes from schematic
    for comp in sch_ir.components:
        G.add_node(
            comp.reference,
            node_type="component",
            value=comp.value if hasattr(comp, "value") else "",
            # Footprint reference if available
            footprint=getattr(comp, "footprint", ""),
        )

    # Add net edges from connectivity graph
    for net_name, pads in net_graph._net_index.items():
        if net_name == "" or net_name == "Net-(...)":
            continue
        # Connect all pads on same net
        for i, pad_a in enumerate(pads):
            for pad_b in pads[i + 1:]:
                ref_a, _ = pad_a
                ref_b, _ = pad_b
                if G.has_node(ref_a) and G.has_node(ref_b):
                    G.add_edge(ref_a, ref_b, net=net_name, edge_type="net")

    # Add spatial features as node attributes
    for point in spatial["points"]:
        # Points are vias/pads with absolute positions
        pass  # Attached during PCB component matching

    metadata = {
        "component_count": len(sch_ir.components),
        "net_count": len(net_graph._net_index),
        "board_hash": content_hash,
        "has_spatial_data": bool(spatial["points"] or spatial["boxes"]),
    }

    return G, content_hash, metadata
```

### RealBoardDataset (following MazeDataset pattern)
```python
# Source: Pattern from kicad_agent/training/dataset.py
from dataclasses import dataclass, field, FrozenInstanceError
from pathlib import Path
import json


@dataclass(frozen=True)
class RealBoardSample:
    """A single real-world board pair with extracted graph data.

    Follows MazeSample pattern: frozen dataclass with primitive/serializable fields.
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
    difficulty: str  # easy/medium/hard
    board_hash: str  # SHA256 of raw schematic+pcb content
    graph_json: str  # networkx graph as JSON (node-link format)


@dataclass
class RealBoardDataset:
    """Collection of real-world board samples with metadata.

    Follows MazeDataset pattern: JSONL serialization, train/val/test split.
    """
    samples: list[RealBoardSample] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_jsonl(self, path: Path) -> int:
        """Write samples as JSONL (one JSON object per line)."""
        count = 0
        with open(path, "w") as f:
            for sample in self.samples:
                f.write(json.dumps({
                    "sample_id": sample.sample_id,
                    "repo_url": sample.repo_url,
                    "repo_name": sample.repo_name,
                    # ... all fields
                    "board_hash": sample.board_hash,
                    "graph_json": sample.graph_json,
                }) + "\n")
                count += 1
        return count

    @classmethod
    def from_jsonl(cls, path: Path) -> RealBoardDataset:
        """Load samples from a JSONL file."""
        samples = []
        with open(path) as f:
            for line in f:
                data = json.loads(line.strip())
                samples.append(RealBoardSample(**data))
        return cls(samples=samples)

    def split(self, train_ratio=0.8, val_ratio=0.1, seed=42):
        """Train/val/test split (matches MazeDataset pattern)."""
        import random
        rng = random.Random(seed)
        shuffled = list(self.samples)
        rng.shuffle(shuffled)
        n = len(shuffled)
        train_end = int(n * train_ratio)
        val_end = int(n * (train_ratio + val_ratio))
        return (
            RealBoardDataset(samples=shuffled[:train_end]),
            RealBoardDataset(samples=shuffled[train_end:val_end]),
            RealBoardDataset(samples=shuffled[val_end:]),
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| GitHub Search v3 (deprecated params) | GitHub REST API v3 with modern pagination | 2023+ | PyGithub 2.x handles modern API correctly |
| Clone entire repos for data mining | Sparse checkout or Contents API | 2020+ | Orders of magnitude faster for single-file extraction |
| Adjacency lists for graph storage | networkx JSON (node-link-data format) | Ongoing | Standard, portable, language-agnostic |
| CSV/TSV for ML datasets | JSONL (JSON Lines) | 2018+ | Line-delimited, streamable, no parse errors on partial files |
| Custom graph ML formats | PyTorch Geometric HeteroData | 2022+ | Standard for heterogeneous GNN training |

**Deprecated/outdated:**
- `github3.py`: Superseded by PyGithub for most use cases
- GraphQL GitHub API for search: Search via GraphQL is more complex with no benefit for repo discovery
- Binary graph formats (pickle, protobuf) for dataset storage: JSONL is more debuggable and portable

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | PyGithub 2.9.1 `search_repositories()` returns repos with KiCad files effectively | Standard Stack | May need additional filtering queries |
| A2 | GitHub Search API can find 1000+ unique KiCad repos with both .kicad_sch and .kicad_pcb files | Architecture | May need supplementary sources (GitLab, local files) |
| A3 | networkx node-link-data format is sufficient for GRPO training pipeline consumption | Standard Stack | May need additional conversion for PyG |
| A4 | SHA256 of raw file content provides stable deduplication across re-runs | Code Examples | STATE.md notes kiutils non-determinism, but raw content hashing should be stable |
| A5 | Most discovered repos will have KiCad 7+ format files (compatible with kiutils) | Common Pitfalls | Many repos may have KiCad 5/6 format requiring skip/filter |
| A6 | PyTorch Geometric export can be deferred to training consumer, not needed at dataset creation time | Standard Stack | GRPO pipeline may need PyG format directly |

**If this table is empty:** All claims in this research were verified or cited -- no user confirmation needed.

## Open Questions

1. **GitHub Token Scope**
   - What we know: Unauthenticated search = 10 req/min. Authenticated = 30 req/min (search) + 5000/hr (core).
   - What's unclear: Does the user have a GitHub personal access token available? What scopes are needed? (Minimum: `public_repo` read)
   - Recommendation: Require `GITHUB_TOKEN` env var. Document token setup in module docstring. Pipeline should fail early with clear message if token missing.

2. **Target Dataset Size**
   - What we know: ROADMAP success criteria says "1000+ real board pairs". Memory notes say 50k-500k is the long-term target.
   - What's unclear: Is 1000 boards the Phase 13 target, or should the pipeline be designed for 50k+ scale from the start?
   - Recommendation: Design for 50k+ scale (streaming, JSONL, hash-based dedup) but Phase 13 success criteria is 1000+ boards in a single run.

3. **GRPO Training Format Compatibility**
   - What we know: Phase 9 GRPO pipeline expects MazeSample-format data (frozen dataclass, JSONL, difficulty grading).
   - What's unclear: Does the GRPO pipeline need the actual graph structure, or just metadata + spatial features? The `MazeSample` has board geometry directly, not abstract graphs.
   - Recommendation: Include graph_json (networkx serialized) in RealBoardSample. Also include flat spatial features (component_count, net_count, board dimensions, difficulty) that can feed into the existing reward model without graph parsing.

4. **Supplementary Data Sources Beyond GitHub**
   - What we know: pcb-training-data-sources.md ranks KiCad official libraries, Mutable Instruments, Open Compute Project, EasyEDA, Hackaday.io as additional sources.
   - What's unclear: Should Phase 13 implement crawlers for these sources, or focus solely on GitHub?
   - Recommendation: Phase 13 focuses on GitHub (RW-01). Other sources are deferred but the architecture should support pluggable data sources.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | Runtime | Yes | 3.11.11 | -- |
| PyGithub | GitHub discovery | No | -- | Raw httpx REST calls (inferior) |
| networkx | Graph representation | Yes | 3.4.2 | -- |
| kiutils | KiCad parsing | Yes | 1.4.8 | -- |
| shapely | Spatial geometry | Yes | 2.1.1 | -- |
| pydantic | Schema validation | Yes | 2.12.5 | -- |
| httpx | HTTP client (fallback) | Yes | 0.28.1 | -- |
| pytest | Testing | Yes | 8.4.2 | -- |
| torch | GRPO training | No | -- | Lazy import (existing pattern) |
| torch-geometric | GNN format export | No | -- | Optional, deferred |

**Missing dependencies with no fallback:**
- PyGithub must be installed before Phase 13 execution begins. Add to pyproject.toml optional dependencies.

**Missing dependencies with fallback:**
- torch/torch-geometric: Already handled via lazy import pattern in training module. GRPO pipeline will need these at training time, but dataset creation does not.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 |
| Config file | pyproject.toml [tool.pytest.ini_options] |
| Quick run command | `pytest tests/test_crawler*.py tests/test_real_dataset*.py -x -q` |
| Full suite command | `pytest -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RW-01 | GitHub search discovers repos with .kicad_pcb and .kicad_sch files | unit (mocked) | `pytest tests/test_crawler_discovery.py -x` | Wave 0 |
| RW-01 | File pair extraction from repo tree | unit (mocked) | `pytest tests/test_crawler_discovery.py::test_find_kicad_pairs -x` | Wave 0 |
| RW-02 | Schematic+PCB parse into networkx graph | unit | `pytest tests/test_graph_builder.py -x` | Wave 0 |
| RW-03 | Spatial features attached to graph nodes | unit | `pytest tests/test_graph_builder.py::test_spatial_features -x` | Wave 0 |
| RW-04 | SHA256 dedup across re-runs | unit | `pytest tests/test_real_dataset.py::test_dedup -x` | Wave 0 |
| RW-04 | Quality filter removes trivial/empty boards | unit | `pytest tests/test_real_dataset.py::test_quality_filter -x` | Wave 0 |
| RW-05 | JSONL output compatible with MazeDataset pattern | unit | `pytest tests/test_real_dataset.py::test_jsonl_roundtrip -x` | Wave 0 |
| RW-05 | Train/val/test split produces correct ratios | unit | `pytest tests/test_real_dataset.py::test_split -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_crawler*.py tests/test_real_dataset*.py tests/test_graph_builder*.py -x -q`
- **Per wave merge:** `pytest -x -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_crawler_discovery.py` -- covers RW-01 (GitHub discovery + file pairing)
- [ ] `tests/test_graph_builder.py` -- covers RW-02, RW-03 (graph construction + spatial features)
- [ ] `tests/test_real_dataset.py` -- covers RW-04, RW-05 (dedup, quality, JSONL, split)
- [ ] PyGithub install: `pip install PyGithub>=2.9.1` -- not yet in pyproject.toml

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | GitHub OAuth token (GITHUB_TOKEN env var) |
| V3 Session Management | no | Stateless API calls, no sessions |
| V4 Access Control | yes | Token scope limited to public_repo read |
| V5 Input Validation | yes | pydantic for dataset schema; kiutils validates KiCad format |
| V6 Cryptography | yes | SHA256 for content hashing (hashlib, stdlib) |

### Known Threat Patterns for GitHub Crawler + Training Data

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Token exposure in logs | Information Disclosure | Never log GITHUB_TOKEN value; use env var, not CLI arg |
| Malicious KiCad files (parsing exploits) | Tampering | Sandbox parsing; catch all exceptions during ingest; validate file size limits |
| Rate limit abuse leading to IP ban | Denial of Service | Token bucket rate limiter; respect X-RateLimit-Remaining |
| Prompt injection via repo descriptions | Tampering | Repo metadata is data, not instructions; sanitize before any LLM consumption |
| Zip slip via malicious repo structure | Elevation of Privilege | Validate extracted paths stay within target directory; use pathlib resolve() check |

## Sources

### Primary (HIGH confidence)
- PyGithub 2.9.1 verified via `pip3 index versions PyGithub` (2026-05-23)
- networkx 3.4.2 verified via `pip3 show networkx` (2026-05-23)
- kiutils 1.4.8 verified via `pip3 show kiutils` (2026-05-23)
- shapely 2.1.1 verified via `pip3 show shapely` (2026-05-23)
- pydantic 2.12.5 verified via `pip3 show pydantic` (2026-05-23)
- httpx 0.28.1 verified via `pip3 show httpx` (2026-05-23)
- pytest 8.4.2 verified via `pip3 show pytest` (2026-05-23)
- kicad-agent source code: training/dataset.py, analysis/connectivity.py, spatial/extractor.py, ir/schematic_ir.py (codebase read)
- .planning/STATE.md accumulated decisions (SHA256 dedup, JSONL streaming, frozen dataclass pattern)

### Secondary (MEDIUM confidence)
- PyGithub search API patterns from pygithub.readthedocs.io (read via webReader)
- GitHub REST API rate limits from docs.github.com/en/rest (read via webReader)
- GitHub Search API syntax from docs.github.com/en/search-github (read via webReader)
- pcb-training-data-sources.md in Confucius memory (ranked data source tiers)

### Tertiary (LOW confidence)
- PyTorch Geometric 2.7.0 availability via `pip3 index versions torch-geometric` (not installed, version verified on PyPI only)
- Scale estimate of 1000+ findable KiCad repos on GitHub (ASSUMED, not verified by actual search)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All core libraries verified installed or available on PyPI with exact versions
- Architecture: HIGH - Reuses existing kicad-agent patterns (MazeDataset, NetGraph, spatial extractors); only new module is the crawler
- Pitfalls: HIGH - Based on known GitHub API constraints and established kicad-agent patterns from STATE.md

**Research date:** 2026-05-23
**Valid until:** 2026-06-23 (stable libraries, GitHub API changes slowly)
