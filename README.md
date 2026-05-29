# kicad-agent

[![PyPI version](https://img.shields.io/pypi/v/kicad-agent.svg)](https://pypi.org/project/kicad-agent/)
[![Python versions](https://img.shields.io/pypi/pyversions/kicad-agent.svg)](https://pypi.org/project/kicad-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-1382+-green.svg)]()

Structural editing of KiCad schematic, PCB, symbol library, and footprint files. The LLM never directly edits KiCad files — it emits structured JSON intents, and the Python backend mutates the AST, serializes valid output, and validates via ERC/DRC gates.

```
Natural language -> JSON intent -> AST mutation -> ERC/DRC validation -> valid KiCad file
```

## Why This Exists

KiCad files are deeply nested S-expressions with strict ordering constraints, fragile UUID/symbol references, and implicit electrical relationships. Generic LLMs fail on KiCad files because:

- Parentheses nesting is deep and ordering matters
- UUIDs and symbol references are fragile — one typo corrupts the file
- Tiny syntax mistakes break the entire design
- Semantic relationships (nets, pins, connectivity) are implicit

kicad-agent solves this with **constrained structural editing** — the AI emits operations, never raw text. Every mutation goes through validation gates before commit.

## What's New

**v2.0 (complete):**
- Visual primitives: spatial query engine with Shapely STRtree for clearance/congestion analysis
- GRPO training: reinforcement learning pipeline with neural reward model for KiCad operations
- AI generation: template board generation with LLM-driven design critique and iterative refinement
- LTspice integration: .asc file parsing, simulation command injection, raw waveform analysis
- ADI footprint library: Analog Devices symbol/footprint resolution with ZIP-based cache

**v2.1 (latest):**
- **Component search MCP server** — search JLCPCB/EasyEDA components from any AI agent (anonymous, no API key)
- **File creation operations** — create_schematic, create_pcb, create_project, create_symbol
- Real-world training data from open-source KiCad projects (71K repos discovered)
- Schematic-only graph builder: connectivity from net labels + wires (no PCB required)
- Domain knowledge corpus: Douglas Self textbooks + DeepSeek visual primitives paper
- Fine-tuned PCB reasoning model (Qwen2.5-0.5B + LoRA, SFT + GRPO on Apple Silicon)
- `kicad-agent analyze` — local PCB analysis, no API key needed
- AI wiring and net routing
- Component placement with attention-based model
- Schematic repair operations: ERC parsing, KiCad 6→10 conversion, automated no-connect/power-flag placement, grid snapping, root sheet generation
- Package distribution (PyPI, docs site)
- CI/CD pipeline

## Supported File Types

| File | Extension | Description |
|------|-----------|-------------|
| Schematic | `.kicad_sch` | Circuit schematics |
| PCB Layout | `.kicad_pcb` | Board layouts |
| Symbol Library | `.kicad_sym` | Component symbol definitions |
| Footprint Library | `.kicad_mod` | Footprint definitions |

**KiCad 10+ only.**

## Install

```bash
# From PyPI (recommended)
pip install kicad-agent

# With documentation build tools
pip install "kicad-agent[docs]"

# With development tools
pip install "kicad-agent[dev]"

# With MCP server support
pip install "kicad-agent[mcp]"

# From source
git clone https://github.com/bretbouchard/kicad-agent.git
cd kicad-agent
pip install .
```

**Requirements:** Python 3.11+, [KiCad 10+](https://www.kicad.org/) (for ERC/DRC validation)

**Dependencies:** [kiutils](https://github.com/mvnmgr/kiutils) (KiCad AST), [sexpdata](https://github.com/tkf/sexpdata) (S-expression parsing), [networkx](https://networkx.org/) (connectivity graphs), [shapely](https://shapely.readthedocs.io/) (spatial queries), [pydantic](https://docs.pydantic.dev/) (operation validation)

## CLI Usage

```bash
# Print the operation JSON Schema (useful for LLM tool definitions)
kicad-agent --schema

# Run an operation from inline JSON
kicad-agent '{"root": {"op_type": "add_component", "target_file": "board.kicad_sch", "library_id": "Device:R_Small_US", "position": {"x": 50.0, "y": 30.0}}}'

# Run an operation from a file
kicad-agent operation.json

# Validate without executing (dry-run)
kicad-agent --dry-run operation.json

# Specify project directory
kicad-agent -p /path/to/kicad-project operation.json

# Verbose output with operation details
kicad-agent -v operation.json
```

### Analyze PCBs with Fine-Tuned Local Model

```bash
# Analyze any KiCad file — runs locally, no API key needed
kicad-agent analyze board.kicad_pcb
kicad-agent analyze schematic.kicad_sch

# Use a specific adapter (GRPO > SFT > base)
kicad-agent analyze board.kicad_pcb --adapter training_output/grpo/iter_2

# Custom base model
kicad-agent analyze board.kicad_pcb --model Qwen/Qwen2.5-1.5B-Instruct
```

Output includes coordinate-grounded spatial analysis with `<point x,y>` tags:
```
Board analysis: 85 components across 62 nets on 4-layer PCB.
Key components (8 of 85): U1 (ATmega328P) at <point 126.7,41.9>; R1 (10k) at <point 118.1,66.1>...
Connectivity: 62 nets with 140 connections.
Spatial distribution: medium complexity board...
Routing assessment: 85 components require 140 trace connections...
```

### Use in Python

```python
from kicad_agent.llm.local_client import LocalLLMClient

client = LocalLLMClient()  # auto-detects best adapter

# Analyze a board
analysis = client.analyze_board(
    board_name="my-board", n_components=85, n_nets=62,
    n_layers=4, width_mm=101.52, height_mm=53.34,
)

# Drop-in replacement for LLMClient (Anthropic-compatible)
result = client.create_message(
    system="You are a PCB design expert.",
    messages=[{"role": "user", "content": "Analyze my board"}],
)
print(result.content[0].text)
```

No API key required. Runs on Apple Silicon GPU (~5 GB memory, ~3s per analysis).

### Component Search MCP Server

Search JLCPCB/EasyEDA components from any MCP-compatible AI agent. No API key required.

```bash
# Install with MCP support
pip install "kicad-agent[mcp]"

# Start the MCP server (stdio transport)
kicad-component-search

# Or via CLI
kicad-agent component-search
```

Add to your Claude Code or Claude Desktop MCP settings:

```json
{
  "mcpServers": {
    "kicad-component-search": {
      "command": "kicad-component-search"
    }
  }
}
```

**4 tools available:**

| Tool | Description |
|------|-------------|
| `search_components` | Search by keyword, returns LCSC numbers, packages, stock, price, datasheets |
| `get_component_details` | Full pin/pad CAD data for a specific LCSC part |
| `search_and_detail` | Combined search + detail in one call |
| `get_component_suggestions` | Lightweight autocomplete suggestions |

Pin types returned as KiCad-compatible strings (`input`, `output`, `bidirectional`, `power_in`, `passive`).

## Claude Code Skill

kicad-agent ships as a Claude Code skill for AI-assisted KiCad editing. Install it by copying the skill definition:

```bash
# Copy skill files to your Claude Code skills directory
mkdir -p ~/.claude/skills/kicad-agent
cp skills/SKILL.md ~/.claude/skills/kicad-agent/
cp skills/prompt.md ~/.claude/skills/kicad-agent/
```

Then invoke from any KiCad project:

```
/kicad-agent add a 10k resistor at position 50,30
/kicad-agent status
/kicad-agent context
/kicad-agent help
```

The skill routes natural language requests through the Python backend — Claude constructs valid JSON operations, the backend validates and executes them, and results are returned as formatted text.

## Operations Reference

53 operations across 6 categories:

### Component Operations

| Operation | Files | Description |
|-----------|-------|-------------|
| `add_component` | sch, pcb | Add a component with library reference, position, value |
| `remove_component` | sch, pcb | Remove a component and clean up net stubs |
| `move_component` | sch, pcb | Move a component to new coordinates |
| `modify_property` | sch, pcb | Change a component property (value, footprint, reference, custom) |
| `duplicate_component` | sch, pcb | Duplicate with fresh UUID and incremented reference |
| `array_replicate` | sch, pcb | Replicate in linear, circular, or matrix pattern |

### Net Operations

| Operation | Files | Description |
|-----------|-------|-------------|
| `add_net` | pcb | Add a named or auto-named net |
| `remove_net` | pcb | Remove a net and disconnect all pads |
| `rename_net` | pcb | Rename a net across all connected pads |

### Reference Operations

| Operation | Files | Description |
|-----------|-------|-------------|
| `renumber_refs` | sch | Renumber references with configurable prefix and sequence |
| `validate_refs` | sch | Check all references are unique |
| `annotate` | sch | Auto-assign references to unannotated components (R? -> R1) |
| `cross_ref_check` | sch | Verify all symbol libIds resolve to embedded libSymbols |

### Footprint Operations

| Operation | Files | Description |
|-----------|-------|-------------|
| `assign_footprint` | sch | Assign a footprint to a schematic component |
| `swap_footprint` | pcb | Swap a PCB footprint preserving pad-to-net connections |
| `validate_footprint` | all | Verify a footprint exists in available libraries |
| `verify_pin_map` | all | Check symbol pin numbers match footprint pad numbers |

### File Creation Operations

| Operation | Files | Description |
|-----------|-------|-------------|
| `create_schematic` | new sch | Create a new empty schematic |
| `create_pcb` | new pcb | Create a new empty PCB |
| `create_project` | new pro | Create a new KiCad project file |
| `create_symbol` | new sym | Create a symbol definition in a library |

### Schematic Repair Operations

| Operation | Files | Description |
|-----------|-------|-------------|
| `parse_erc` | sch | Parse kicad-cli ERC JSON output into structured violation list with positions |
| `extract_violation_positions` | sch | Extract (x,y) positions for specific ERC violation types (pin_not_connected, power_pin_not_driven, etc.) |
| `validate_hlabels` | sch | Verify hierarchical labels match expected set to catch agent deletion |
| `convert_kicad6_to_10` | sch | Convert KiCad 5/6 format schematics to KiCad 10 (headers, UUID quoting, stroke format, 13 fixes) |
| `snap_to_grid` | sch | Move off-grid wire endpoints to nearest grid point while preserving connectivity |
| `add_power_flag` | sch | Place PWR_FLAG symbols at power_pin_not_driven positions with correct lib definition |

### Example: Add a Component

```json
{
  "root": {
    "op_type": "add_component",
    "target_file": "motor-driver.kicad_sch",
    "library_id": "Device:R_Small_US",
    "reference": "R1",
    "value": "10k",
    "position": {"x": 50.0, "y": 30.0, "angle": 90.0}
  }
}
```

### Example: Array Replicate

```json
{
  "root": {
    "op_type": "array_replicate",
    "target_file": "motor-driver.kicad_pcb",
    "source_reference": "LED1",
    "pattern": "matrix",
    "spacing": {"x": 3.0, "y": 3.0},
    "rows": 3,
    "cols": 4
  }
}
```

See the [full operation reference](skills/prompt.md) for all field descriptions, constraints, and examples.

## Architecture

```
LLM / CLI
    |
    v
+-------------+     +-------------+     +-------------+     +-------------+
|   Parser     |---->|     IR      |---->|   Ops       |---->|  Serializer |
|              |     |             |     |             |     |             |
| S-expression |     | Intermediate|     | 47 atomic   |     | Valid KiCad |
| -> AST       |     | representation   | operations  |     | S-expression|
|              |     | + mutation  |     | + executor  |     | + normalize |
| 4 file types |     | tracking    |     |             |     |             |
+-------------+     +-------------+     +------+------+     +-------------+
                                                |
                                    +-----------v-----------+
                                    |      Validation       |
                                    |                       |
                                    | ERC/DRC via kicad-cli |
                                    | Structural checks     |
                                    | Round-trip fidelity   |
                                    | Auto-rollback         |
                                    +-----------------------+
```

### Module Structure

| Module | Purpose |
|--------|---------|
| `kicad_agent.parser` | Parse KiCad files into structured AST (schematic, PCB, symbol, footprint) |
| `kicad_agent.ir` | Intermediate representation with mutation tracking and transactions |
| `kicad_agent.ops` | 47 operation handlers, Pydantic schema, operation executor |
| `kicad_agent.serializer` | Write valid KiCad files with UUID re-injection and normalization |
| `kicad_agent.validation` | ERC/DRC gates via kicad-cli, structural validation, round-trip checks |
| `kicad_agent.analysis` | Net connectivity graph analysis via networkx |
| `kicad_agent.crossfile` | Atomic cross-file operations, library propagation, structural diffs |
| `kicad_agent.spatial` | Spatial query engine with Shapely STRtree for clearance and congestion |
| `kicad_agent.export` | Manufacturing export: Gerber generation, BOM output, kicad-cli integration |
| `kicad_agent.generation` | AI-driven PCB generation with template instantiation and refinement |
| `kicad_agent.ltspice` | LTspice .asc parsing, simulation command injection, waveform analysis |
| `kicad_agent.training` | GRPO reinforcement learning pipeline with neural reward model |
| `kicad_agent.project` | Project-level operations and Analog Devices footprint library |
| `kicad_agent.placement` | Attention-based component placement with hybrid ML/geometric engine |
| `kicad_agent.llm` | LLM integration: Anthropic client, local fine-tuned inference (LocalLLMClient), design critique, intent parsing |
| `kicad_agent.mcp` | Component search MCP server (JLCPCB/EasyEDA, anonymous, stdio transport) |
| `kicad_agent.handler` | Operation validation, execution, and result formatting |
| `kicad_agent.cli` | Terminal interface with schema export, dry-run, and verbose modes |

### Key Design Decisions

- **JSON operation schema** — The LLM emits structured intents, never raw S-expressions. Pydantic validates every operation before execution.
- **Transaction safety** — Every mutation is wrapped in a transaction with automatic rollback on failure.
- **ERC/DRC gates** — Validation runs via `kicad-cli` after every edit. Files that fail validation are rolled back.
- **Round-trip fidelity** — Parse -> modify -> serialize produces byte-identical or semantically equivalent output.
- **UUID integrity** — UUIDs are extracted before parsing and re-injected after serialization to preserve references.
- **Atomic operations** — One mutation per operation, one target file per operation. No compound operations.

## Training

### Prerequisites

- Python 3.11+
- Apple Silicon Mac (M1+, MPS backend) or CUDA GPU
- 16GB+ RAM
- mlx-lm installed (`pip install mlx-lm`)

### Data Sources

Training data comes from 7 sources: real KiCad projects parsed into connectivity graphs, schematic-only graphs (no PCB required), Douglas Self's *Small Signal Audio Design* and *Audio Power Amplifier Design*, DeepSeek's *Thinking with Visual Primitives* paper, gold-standard routing analysis, and EasyEDA component databases.

| Source | Train | Val | Test | Format |
|--------|-------|-----|------|--------|
| PCB graphs (sch+pcb pairs) | 168 | 21 | 21 | `graph_json`, spatial |
| Schematic-only graphs | 3,218 | 402 | 403 | `graph_json`, spatial |
| Textbook knowledge (Self x2 + DeepSeek) | 926 | 115 | 117 | `content`, chapters |
| 100K crawl (in progress) | growing | — | — | `graph_json`, spatial |
| Gold standard routing | 100 | 13 | 13 | routing features, RES scores |
| EasyEDA components | 2,000 | 250 | 250 | pin maps, packages |

**SFT fine-tuning data:** 7,441 ChatML samples from all 7 sources, quality-filtered by reward model (bottom 25th percentile removed). Split into 6,696 train / 372 val / 373 test.

**Textbooks:**
- *Small Signal Audio Design* (Douglas Self, 2010) — 360 chunks, 20 chapters: op-amps, noise, filters, preamps, mixers
- *Audio Power Amplifier Design* (Douglas Self, 2013) — 551 chunks, 41 chapters: power amp classes, distortion, thermal, layout
- *Thinking with Visual Primitives* (DeepSeek-AI, 2025) — 15 chunks: spatial reasoning architecture, coordinate-grounded chains

**Graph data:** Component connectivity graphs from real KiCad projects. PCB graphs include spatial coordinates from footprints; schematic graphs use net labels + wire union-find for connectivity without requiring a PCB layout.

**100K crawl:** 71,431 repos discovered via multi-strategy GitHub search (GraphQL, REST, code search, curated orgs, fork amplification). Sparse-cloned with `--depth 1 --filter=blob:none --sparse`, pre-filtered via tree API, parsed into training samples.

### Step 1: Generate Training Data

```bash
# Generate chains from PCB graphs
python -m kicad_agent.training.chains \
    --data-dir training_data_v3/ \
    --output-file training_output/chains.jsonl \
    --n-samples 1000

# Expected output:
# Generated 1000 chains from 712 boards
# Chain lengths: min=45, median=128, max=312 tokens
# Saved to training_output/chains.jsonl
```

### Step 2: Train Reward Model

```bash
# Train neural reward model on generated chains
python -m kicad_agent.training.reward_model \
    --chains training_output/chains.jsonl \
    --output-dir training_output/reward_model \
    --epochs 10 \
    --batch-size 32 \
    --learning-rate 1e-4

# Expected output:
# Epoch 1/10: train_loss=0.693 val_acc=0.52
# Epoch 5/10: train_loss=0.412 val_acc=0.71
# Epoch 10/10: train_loss=0.287 val_acc=0.75
# Reward model saved to training_output/reward_model/
```

### Step 3: SFT Fine-Tuning

```bash
# Supervised fine-tuning with mlx-lm LoRA
python -m kicad_agent.training.pipeline \
    --data-dir training_data_v3/ \
    --output-dir training_output/sft \
    --epochs 3 \
    --batch-size 4 \
    --learning-rate 2e-5 \
    --lora-rank 16

# Expected output:
# Loaded 6696 train, 372 val, 373 test samples
# Base model: Qwen/Qwen2.5-0.5B-Instruct
# Epoch 1/3: train_loss=2.341 val_loss=2.189
# Epoch 2/3: train_loss=1.892 val_loss=1.756
# Epoch 3/3: train_loss=1.534 val_loss=1.498
# Training complete. Best model saved to training_output/sft/
```

Hardware: Apple M2 Pro with 16GB runs SFT in ~15 minutes. CUDA GPU (8GB+ VRAM) runs in ~5 minutes.

### Step 4: GRPO RL Fine-Tuning (Optional)

```bash
# Reinforcement learning on top of SFT adapter
python -m kicad_agent.training.grpo \
    --base-adapter training_output/sft/ \
    --output-dir training_output/grpo \
    --iterations 2 \
    --samples-per-round 200 \
    --top-k-filter 0.5

# Expected output:
# Iteration 1/2: generating 200 samples...
#   Reward: mean=0.62 std=0.15 | Top-50% mean=0.74
#   Training: 500 steps, loss 0.46 -> 0.35
# Iteration 2/2: generating 200 samples...
#   Reward: mean=0.71 std=0.12 | Top-50% mean=0.81
#   Training: 500 steps, loss 0.38 -> 0.28
# Best adapter saved to training_output/grpo/iter_2/
```

### Step 5: Evaluate

```bash
# Evaluate adapter on held-out test set
python -m kicad_agent.training.evaluation \
    --adapter training_output/grpo/iter_2/ \
    --test-data training_data_v3/test/ \
    --output-dir training_output/eval/

# Expected output:
# Evaluation on 373 test samples
# Format quality:   0.82 (was 0.61 base)
# Reasoning quality: 0.78 (was 0.54 base)
# Factual accuracy:  0.71 (was 0.48 base)
# Composite:         0.77 (was 0.54 base)
# Report saved to training_output/eval/report.json
```

### Pre-Trained Adapters

Skip training and use pre-trained adapters:

- **HuggingFace Hub:** [bretbouchard/kicad-agent-pcb-adapter](https://huggingface.co/bretbouchard/kicad-agent-pcb-adapter)
- **Local SFT:** `training_output/sft/`
- **Local GRPO (best):** `training_output/grpo/iter_2/`

LocalLLMClient auto-downloads from HuggingFace Hub on first use if no local adapter is found.

| Stage | Method | Samples | Iters | Loss | Notes |
|-------|--------|---------|-------|------|-------|
| SFT | Supervised fine-tuning | 6,696 | 1,000 | 2.20 -> 0.69 | ChatML, reward-filtered |
| GRPO | Rejection sampling (ReST) | 200/gen round | 500/round | 0.46 -> 0.28 | 2 iterations, top-50% filter |

**Reward model:** Custom neural reward model trained on 14,912 PCB reasoning chains. Scores chains on format quality, reasoning quality, and factual accuracy. 75% discrimination rate between correct and corrupted chains.

One of the training sources is DeepSeek's paper on spatial reasoning — the methodology paper that describes how to train models for coordinate-grounded reasoning. Training the model on the paper that describes how to train the model. Turtles all the way down.

## Development

```bash
# Install with dev dependencies
pip install ".[dev]"

# Run tests (1382+ tests)
pytest

# Run with coverage
pytest --cov=kicad_agent --cov-report=term-missing

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

## Project Status

v2.0 complete. v2.1 (production-ai) phases 13-22 complete. v2.2 (schematic repair) Phase 23 complete. 1382+ tests passing.

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Parse, serialize, round-trip all 4 file types | Complete |
| 2 | Operation schema and IR layer | Complete |
| 3 | Validation pipeline (ERC/DRC, structural, rollback) | Complete |
| 4 | Component operations (add, remove, duplicate, move, modify) | Complete |
| 5 | Net, reference, and footprint operations | Complete |
| 6 | Cross-file operations and analysis | Complete |
| 7 | GSD Skill integration and CLI | Complete |
| 8 | Visual primitives (spatial engine, coordinate system, DRC/ERC enrichment) | Complete |
| 9 | GRPO training pipeline (dataset, reward model, policy training) | Complete |
| 10 | AI-driven PCB generation (templates, LLM critique, manufacturing) | Complete |
| 11 | LTspice integration (.asc parser, simulation, waveform analysis) | Complete |
| 12 | ADI footprint library (symbol/footprint resolution, cache) | Complete |
| 13-19 | v2.1 production-ai phases (training data, crawling, parsing) | Complete |
| 20 | SFT fine-tuning (data prep + mlx-lm LoRA training) | Complete |
| 21 | GRPO RL fine-tuning (ReST rejection sampling) | Complete |
| 22 | Agent integration (local inference, `analyze` CLI) | Complete |
| 23 | Schematic repair operations (ERC parsing, format conversion, automated fixes, root sheet generation) | Complete |

## License

[MIT](LICENSE)
