"""Tests for SFT ChatML converter, templates, and quality filter.

Covers:
- Chain-to-ChatML conversion for correct and incorrect chains
- ChatML format output with <|im_start|>/<|im_end|> markers
- Task template selection based on chain metadata
- Reward model quality filtering (top 75% kept)
- Train/val/test split ratios (80/10/10)
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.training.sft.converter import ChatMLSample, convert_chain_to_chatml
from kicad_agent.training.sft.quality_filter import filter_by_reward_model, split_and_save
from kicad_agent.training.sft.templates import (
    SYSTEM_PROMPT_SPATIAL,
    TASK_TEMPLATES,
    get_template_for_chain,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chain_dict(
    sample_id: int = 1,
    is_correct: bool = True,
    difficulty: str = "medium",
    chain_text: str | None = None,
) -> dict:
    """Build a minimal chain dict matching chains_100k.jsonl format."""
    if chain_text is None:
        chain_text = (
            "Board is 30x30mm with 15 obstacles. Source via at <point 7.5,7.5>, "
            "target via at <point 22.5,22.5>.\n"
            "The path from source to target must navigate around 15 obstacles.\n"
            "Solution path: <point 7.5,7.5> -> <point 22.5,22.5> (5 steps).\n"
            "The optimal route requires 5 steps across the board.\n"
            "Route trace from source to target in 5 steps."
        )
    return {
        "sample_id": sample_id,
        "difficulty": difficulty,
        "chain_text": chain_text,
        "steps": [],
        "coordinates_referenced": [[7.5, 7.5], [22.5, 22.5]],
        "is_correct": is_correct,
        "exploration_branches": 0,
    }


# ---------------------------------------------------------------------------
# Test 1: convert_chain_to_chatml returns ChatMLSample with 3 messages
# ---------------------------------------------------------------------------

def test_convert_correct_chain():
    """Correct chain converts to ChatMLSample with system/user/assistant messages."""
    chain = _make_chain_dict(is_correct=True)
    result = convert_chain_to_chatml(chain)

    assert result is not None, "Should return a ChatMLSample for correct chains"
    assert isinstance(result, ChatMLSample)
    assert len(result.messages) == 3

    roles = [m["role"] for m in result.messages]
    assert roles == ["system", "user", "assistant"]

    # System message contains spatial reasoning prompt
    assert "PCB" in result.messages[0]["content"] or "spatial" in result.messages[0]["content"].lower()

    # User message contains context from chain
    assert "30x30mm" in result.messages[1]["content"] or "obstacle" in result.messages[1]["content"].lower()

    # Assistant message contains the full chain text
    assert result.messages[2]["content"] == chain["chain_text"]

    assert result.source == "chain"
    assert result.source_id == chain["sample_id"]


# ---------------------------------------------------------------------------
# Test 2: convert_chain_to_chatml returns None for incorrect chains
# ---------------------------------------------------------------------------

def test_convert_incorrect_chain_returns_none():
    """Incorrect chains are filtered out (returns None)."""
    chain = _make_chain_dict(is_correct=False)
    result = convert_chain_to_chatml(chain)
    assert result is None


# ---------------------------------------------------------------------------
# Test 3: ChatMLSample.to_text produces ChatML format
# ---------------------------------------------------------------------------

def test_chatml_format():
    """to_text produces ChatML format with <|im_start|> and <|im_end|> markers."""
    chain = _make_chain_dict(is_correct=True)
    result = convert_chain_to_chatml(chain)
    assert result is not None

    # Use a mock tokenizer with apply_chat_template
    mock_tokenizer = MagicMock()
    mock_tokenizer.apply_chat_template.return_value = (
        "<|im_start|>system\nYou are a PCB spatial reasoning assistant.<|im_end|>\n"
        "<|im_start|>user\nAnalyze the PCB routing problem:<|im_end|>\n"
        "<|im_start|>assistant\nBoard is 30x30mm.<|im_end|>"
    )

    text = result.to_text(mock_tokenizer)
    assert "<|im_start|>" in text
    assert "<|im_end|>" in text
    mock_tokenizer.apply_chat_template.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4: get_template_for_chain returns correct template key
# ---------------------------------------------------------------------------

def test_template_selection():
    """get_template_for_chain returns correct template based on chain metadata."""
    # Default maze chain should return spatial_reasoning
    chain = _make_chain_dict()
    key = get_template_for_chain(chain)
    assert key == "spatial_reasoning"

    # Verify TASK_TEMPLATES has all 4 expected keys
    assert "spatial_reasoning" in TASK_TEMPLATES
    assert "board_analysis" in TASK_TEMPLATES
    assert "routing_assessment" in TASK_TEMPLATES
    assert "component_knowledge" in TASK_TEMPLATES

    # Verify SYSTEM_PROMPT_SPATIAL is non-empty
    assert len(SYSTEM_PROMPT_SPATIAL) > 50

    # Verify templates contain {context} placeholder
    for name, template in TASK_TEMPLATES.items():
        assert "{context}" in template, f"Template '{name}' missing {{context}} placeholder"


# ---------------------------------------------------------------------------
# Test 5: filter_by_reward_model keeps top 75%
# ---------------------------------------------------------------------------

def test_quality_filter_keeps_top_fraction():
    """Quality filter removes bottom 25% of chains by composite score."""
    # Create 20 samples with predictable content
    samples = []
    for i in range(20):
        sample = ChatMLSample(
            messages=(
                {"role": "system", "content": "PCB assistant"},
                {"role": "user", "content": f"Analyze board {i}"},
                {"role": "assistant", "content": f"Chain text {i} with coordinates"},
            ),
            source="chain",
            source_id=i,
        )
        samples.append(sample)

    # Mock predict_reward to return known scores based on content
    def mock_predict(model, text):
        # Extract number from "Chain text N"
        idx = int(text.split("Chain text ")[1].split(" ")[0])
        # Bottom 5 (0-4) should be removed, top 15 (5-19) kept
        score = 0.3 if idx < 5 else 0.8
        from kicad_agent.training.reward_model import PredictedReward
        return PredictedReward(
            format_score=score,
            quality_score=score,
            accuracy_score=score,
        )

    with patch("kicad_agent.training.sft.quality_filter.predict_reward", side_effect=mock_predict), \
         patch("kicad_agent.training.sft.quality_filter.RewardModel") as MockRM:
        mock_instance = MagicMock()
        MockRM.load_trained.return_value = mock_instance

        result = filter_by_reward_model(
            samples,
            model_dir="/fake/model",
            keep_fraction=0.75,
            batch_size=32,
        )

    assert len(result) == 15, f"Expected 15 samples kept, got {len(result)}"

    # All retained samples should have quality_score set
    for s in result:
        assert s.quality_score is not None
        assert s.quality_score > 0


# ---------------------------------------------------------------------------
# Test 6: split_and_save produces 3 JSONL files with correct split ratios
# ---------------------------------------------------------------------------

def test_split_ratios():
    """split_and_save produces train/val/test with 80/10/10 ratios."""
    # Create 100 samples
    samples = []
    for i in range(100):
        sample = ChatMLSample(
            messages=(
                {"role": "system", "content": "PCB assistant"},
                {"role": "user", "content": f"Prompt {i}"},
                {"role": "assistant", "content": f"Response {i}"},
            ),
            source="chain",
            source_id=i,
            quality_score=0.8,
        )
        samples.append(sample)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        counts = split_and_save(samples, output_dir, seed=42)

        # Verify files exist
        assert (output_dir / "train.jsonl").exists()
        assert (output_dir / "val.jsonl").exists()
        assert (output_dir / "test.jsonl").exists()

        # Verify counts sum to total
        total = counts["train"] + counts["val"] + counts["test"]
        assert total == 100

        # Verify approximate ratios (80/10/10)
        assert counts["train"] == 80
        assert counts["val"] == 10
        assert counts["test"] == 10

        # Verify JSONL format
        with open(output_dir / "train.jsonl") as f:
            line = f.readline()
            data = json.loads(line)
            assert "messages" in data
            assert len(data["messages"]) == 3
            assert "quality_score" in data
            assert "source" in data
