"""Chain-to-ChatML conversion pipeline for SFT data preparation.

Converts MazeReasoningChain dicts from chains_100k.jsonl into ChatML-formatted
instruction-following samples suitable for supervised fine-tuning with TRL SFTTrainer.

Each correct chain becomes a ChatMLSample with system/user/assistant turns.
Incorrect chains are filtered out.

Usage:
    from kicad_agent.training.sft.converter import (
        ChatMLSample,
        convert_chain_to_chatml,
        convert_chains_to_chatml,
    )

    samples = convert_chains_to_chatml(Path("training_output/chains_100k.jsonl"))
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kicad_agent.training.sft.templates import (
    SYSTEM_PROMPT_SPATIAL,
    TASK_TEMPLATES,
    get_template_for_chain,
)


@dataclass(frozen=True)
class ChatMLSample:
    """A ChatML-formatted training sample for SFT.

    Attributes:
        messages: Tuple of role/content dicts (system, user, assistant).
        source: Origin of the sample (e.g., "chain").
        source_id: Original sample ID for traceability.
        quality_score: Optional reward model score (set during filtering).
    """

    messages: tuple[dict[str, str], ...]
    source: str
    source_id: int
    quality_score: float | None = None

    def to_text(self, tokenizer) -> str:
        """Format messages using tokenizer's chat template.

        Args:
            tokenizer: A HuggingFace tokenizer with apply_chat_template method.

        Returns:
            ChatML-formatted string with <|im_start|>/<|im_end|> markers.
        """
        return tokenizer.apply_chat_template(
            list(self.messages),
            tokenize=False,
        )


def convert_chain_to_chatml(
    chain_dict: dict[str, Any],
) -> ChatMLSample | None:
    """Convert a single chain dict to ChatML format.

    Filters out incorrect chains (is_correct=False). Builds a user prompt
    from the first line of chain_text (observation line) wrapped in the
    appropriate task template. The full chain_text becomes the assistant response.

    Args:
        chain_dict: Chain dictionary with is_correct, chain_text, sample_id fields.

    Returns:
        ChatMLSample for correct chains, None for incorrect chains.
    """
    if not chain_dict.get("is_correct", False):
        return None

    chain_text = chain_dict["chain_text"]
    if not chain_text or not chain_text.strip():
        return None

    # Select template based on chain metadata
    template_key = get_template_for_chain(chain_dict)
    template = TASK_TEMPLATES[template_key]

    # Extract observation (first line) as user context
    first_line = chain_text.split("\n")[0]
    user_content = template.format(context=first_line)

    messages: tuple[dict[str, str], ...] = (
        {"role": "system", "content": SYSTEM_PROMPT_SPATIAL},
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": chain_text},
    )

    return ChatMLSample(
        messages=messages,
        source="chain",
        source_id=chain_dict["sample_id"],
    )


def convert_chains_to_chatml(
    input_path: Path,
    output_path: Path | None = None,
    max_samples: int = 0,
) -> list[ChatMLSample]:
    """Stream chains from JSONL and convert correct ones to ChatML.

    Reads chain dicts from input JSONL, converts correct chains to ChatML
    format, optionally writes to output JSONL. Each output line is a JSON
    object with messages, source, and source_id fields.

    Args:
        input_path: Path to chains_100k.jsonl (or similar).
        output_path: Optional path to write converted samples as JSONL.
        max_samples: Max converted samples to process (0 = all).

    Returns:
        List of ChatMLSample objects (only correct chains).
    """
    samples: list[ChatMLSample] = []
    output_file = None

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_file = open(output_path, "w")  # noqa: SIM115

    try:
        with open(input_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                chain_dict = json.loads(line)
                sample = convert_chain_to_chatml(chain_dict)

                if sample is not None:
                    samples.append(sample)

                    if output_file is not None:
                        record = {
                            "messages": [
                                {"role": m["role"], "content": m["content"]}
                                for m in sample.messages
                            ],
                            "source": sample.source,
                            "source_id": sample.source_id,
                        }
                        output_file.write(json.dumps(record) + "\n")

                    if max_samples > 0 and len(samples) >= max_samples:
                        break
    finally:
        if output_file is not None:
            output_file.close()

    return samples
