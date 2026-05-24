---
phase: 16-component-placement-ai
plan: 02
subsystem: placement
tags: [gnn, attention, model, training, grpo, dataset, reward, pytorch]
dependency_graph:
  requires: [placement/graph.py, placement/features.py, training/grpo.py, generation/placement.py]
  provides: [placement/model.py, placement/predict.py, placement/training/]
  affects: [placement/model.py (attention mask fix)]
tech_stack:
  added: [pytorch-nn-multiheadattention, scipy-dual-annealing]
  patterns: [attention-gnn, sigmoid-output-scaling, grpo-group-advantages, sa-optimization]
key_files:
  created:
    - src/kicad_agent/placement/model.py
    - src/kicad_agent/placement/predict.py
    - src/kicad_agent/placement/training/__init__.py
    - src/kicad_agent/placement/training/dataset.py
    - src/kicad_agent/placement/training/reward.py
    - src/kicad_agent/placement/training/train.py
    - tests/test_placement_model.py
    - tests/test_placement_training.py
  modified: []
decisions:
  - Sigmoid output scaling to board dimensions guarantees (x,y) within bounds
  - Rotation mapped as sigmoid*360-180 for [-180,180] degree range
  - Attention mask fallback for disconnected components prevents NaN from all-masked softmax
  - Training uses advantage-weighted energy surrogate (non-differentiable reward for advantages, differentiable energy for gradients)
  - Synthetic data uses scipy dual_annealing with 200 iterations for near-optimal positions
  - HPWL + 10x overlap + 5x edge penalty as composite training loss
  - 100k sample cap matches MazeDataset safety pattern
metrics:
  duration: 29 min
  completed: 2026-05-24
  tasks: 2
  files: 8
  tests_added: 31
  tests_passing: 1161
---

# Phase 16 Plan 02: Placement Model and Training Infrastructure Summary

Attention-based GNN placement model with bipartite component-net message passing, sigmoid-scaled (x,y,rotation) outputs, synthetic training data generation with simulated annealing, HPWL/overlap/edge reward signals, and GRPO group-relative training loop.

## Completed Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Placement model architecture and prediction API | a51f85b | model.py, predict.py, test_placement_model.py |
| 2 | Training infrastructure -- dataset, reward, and trainer | 0d5014a | training/__init__.py, dataset.py, reward.py, train.py, test_placement_training.py |

## What Was Built

### placement/model.py
- `BipartiteAttentionLayer`: Multi-head attention for bipartite comp-net message passing with adjacency masking and residual connections. Handles disconnected components via all-masked row fallback to prevent NaN.
- `PlacementModel`: 3-layer GNN with embedding, attention+LayerNorm+ReLU message passing, and sigmoid-scaled per-component output heads for x, y, rotation.

### placement/predict.py
- `PlacementPrediction`: Frozen dataclass with positions dict, raw output array, and model confidence.
- `PlacementPredictor`: Wraps model inference with lazy torch import, graph feature extraction, tensor conversion, and reference mapping back to component designators.

### placement/training/dataset.py
- `PlacementSample`: Frozen dataclass with JSON-serialized components, nets, and optimal positions.
- `PlacementDataset`: JSONL I/O matching MazeDataset pattern, with 100k sample cap.
- `generate_placement_samples()`: Synthetic data generation using scipy.optimize.dual_annealing for near-optimal placement targets with difficulty grading.

### placement/training/reward.py
- `compute_hpwl()`: Half-perimeter wirelength across all nets.
- `compute_overlap_area()`: Pairwise component bounding box intersection area.
- `compute_edge_penalty()`: Board edge proximity violation count.
- `compute_placement_loss()`: Composite loss = HPWL + 10*overlap + 5*edge.
- `placement_reward()`: GRPO reward in [0,1] combining accuracy (0.3), wirelength (0.4), clearance (0.3).

### placement/training/train.py
- `PlacementTrainConfig`: Epochs, batch size, learning rate, group size, seed.
- `PlacementTrainer`: GRPO training with group-relative advantages, advantage-weighted energy loss, gradient clipping at 1.0, AdamW optimizer.

## Verification Results

- `pytest tests/test_placement_model.py`: 14/14 passed
- `pytest tests/test_placement_training.py`: 17/17 passed
- `pytest tests/`: 1161 passed, 1 skipped, 0 failures
- All import checks: OK

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed NaN from all-masked attention rows**
- **Found during:** Task 2 (training tests)
- **Issue:** Components with no net connections produced all-True attention masks, causing NaN from softmax over all -inf values
- **Fix:** Added fallback in BipartiteAttentionLayer: when a component row is fully masked (no net connections), allow attending to all nets instead
- **Files modified:** src/kicad_agent/placement/model.py
- **Commit:** 0d5014a

**2. [Rule 1 - Bug] Fixed NaN from broken gradient chain in training loop**
- **Found during:** Task 2 (training tests)
- **Issue:** Training loop accumulated losses into `torch.tensor(0.0)` without `requires_grad`, breaking the gradient graph and producing NaN losses
- **Fix:** Rewrote loss accumulation to use `torch.stack(parts).mean()` preserving the computational graph from model output through advantage-weighted energy
- **Files modified:** src/kicad_agent/placement/training/train.py
- **Commit:** 0d5014a

## Known Stubs

None.

## Self-Check: PASSED

- src/kicad_agent/placement/model.py: FOUND
- src/kicad_agent/placement/predict.py: FOUND
- src/kicad_agent/placement/training/__init__.py: FOUND
- src/kicad_agent/placement/training/dataset.py: FOUND
- src/kicad_agent/placement/training/reward.py: FOUND
- src/kicad_agent/placement/training/train.py: FOUND
- tests/test_placement_model.py: FOUND
- tests/test_placement_training.py: FOUND
- Commit a51f85b: FOUND
- Commit 0d5014a: FOUND
