"""Neural reward model for scoring reasoning chains (PyTorch).

GRPO-03: Lightweight transformer-based model that predicts per-step reward
scores (format, quality, accuracy) from chain text.

Lazily imports PyTorch to avoid import-time failures if torch is not installed.

Usage:
    from kicad_agent.training.reward_model import RewardModel, predict_reward

    model = RewardModel()
    signal = predict_reward(model, "Observation: via at <point 5.0,10.0>")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kicad_agent.training.tokenizer import ChainTokenizer


@dataclass(frozen=True)
class PredictedReward:
    """Predicted reward from the neural reward model.

    Attributes:
        format_score: Predicted format correctness (0..1).
        quality_score: Predicted reasoning quality (0..1).
        accuracy_score: Predicted coordinate accuracy (0..1).
    """

    format_score: float
    quality_score: float
    accuracy_score: float


# ---------------------------------------------------------------------------
# Simple tokenizer (no external dependencies)
# ---------------------------------------------------------------------------

_PAD_TOKEN = 0
_UNKNOWN_TOKEN = 1
_MAX_VOCAB = 5000
_MAX_SEQ_LEN = 512


def _simple_tokenize(text: str, max_len: int = _MAX_SEQ_LEN) -> tuple[list[int], list[int]]:
    """Simple character-level tokenizer.

    Converts text to integer token IDs and attention mask.
    Uses character ordinals capped at _MAX_VOCAB.

    Args:
        text: Input text to tokenize.
        max_len: Maximum sequence length.

    Returns:
        (token_ids, attention_mask) tuple.
    """
    token_ids: list[int] = []
    for ch in text[:max_len]:
        token_id = ord(ch) % _MAX_VOCAB
        token_ids.append(token_id + 2)  # offset by 2 (pad=0, unk=1)
    # Pad to max_len
    attention_mask = [1] * len(token_ids) + [0] * (max_len - len(token_ids))
    token_ids = token_ids + [_PAD_TOKEN] * (max_len - len(token_ids))
    return token_ids[:max_len], attention_mask[:max_len]


# ---------------------------------------------------------------------------
# Reward Model
# ---------------------------------------------------------------------------

def _build_model(vocab_size: int = _MAX_VOCAB + 2):
    """Build and return the RewardModel nn.Module.

    Args:
        vocab_size: Vocabulary size for the embedding layer.

    Returns None if PyTorch is not available.
    """
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        return None

    class _RewardModel(nn.Module):
        """Lightweight transformer-based reward prediction model.

        Architecture:
          - Token embedding (vocab_size -> d_model)
          - 4-layer transformer encoder (d_model=256, heads=4, ff=512)
          - Mean pooling over sequence
          - 3 prediction heads: format, quality, accuracy
        """

        def __init__(
            self,
            vocab_size: int = 8000,
            d_model: int = 256,
            n_heads: int = 4,
            n_layers: int = 4,
            d_ff: int = 512,
            max_seq_len: int = _MAX_SEQ_LEN,
        ):
            super().__init__()
            self.d_model = d_model
            self.embedding = nn.Embedding(vocab_size, d_model)
            self.pos_embedding = nn.Embedding(max_seq_len, d_model)

            encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=n_heads,
                dim_feedforward=d_ff,
                dropout=0.1,
                batch_first=True,
            )
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

            # Prediction heads
            self.format_head = nn.Linear(d_model, 1)
            self.quality_head = nn.Linear(d_model, 1)
            self.accuracy_head = nn.Linear(d_model, 1)

        def forward(self, input_ids, attention_mask=None):
            """Forward pass.

            Args:
                input_ids: (batch, seq_len) token IDs.
                attention_mask: (batch, seq_len) mask (1=valid, 0=pad).

            Returns:
                (format_pred, quality_pred, accuracy_pred) each (batch, 1).
            """
            batch_size, seq_len = input_ids.shape

            # Embed tokens + positions
            positions = torch.arange(seq_len, device=input_ids.device).unsqueeze(0).expand(batch_size, -1)
            x = self.embedding(input_ids) + self.pos_embedding(positions)

            # Padding mask: skip on MPS (unsupported nested-tensor op), use on CUDA/CPU
            device_type = input_ids.device.type
            if attention_mask is not None and device_type not in ("mps",):
                padding_mask = attention_mask == 0  # True = ignore
            else:
                padding_mask = None

            # Encode
            x = self.encoder(x, src_key_padding_mask=padding_mask)

            # Mean pooling (respecting mask for accurate averaging)
            if attention_mask is not None:
                mask_expanded = attention_mask.unsqueeze(-1).float()
                x = (x * mask_expanded).sum(dim=1) / mask_expanded.sum(dim=1).clamp(min=1)
            else:
                x = x.mean(dim=1)

            # Predict
            fmt = torch.sigmoid(self.format_head(x))
            qual = torch.sigmoid(self.quality_head(x))
            acc = torch.sigmoid(self.accuracy_head(x))

            return fmt, qual, acc

    return _RewardModel()


class RewardModel:
    """Wrapper for the neural reward model with lazy PyTorch initialization.

    The underlying nn.Module is only created when first accessed,
    allowing the module to be imported without PyTorch installed.

    Optionally holds a trained ChainTokenizer for word-level tokenization.
    Falls back to character-level tokenization if no tokenizer is set.
    """

    def __init__(self, device: str = "cpu"):
        """Initialize with lazy model creation.

        Args:
            device: "cpu", "mps", or "cuda".
        """
        self._model = None
        self._device = device
        self._tokenizer: ChainTokenizer | None = None

    @property
    def model(self):
        """Lazily create and return the underlying nn.Module."""
        if self._model is None:
            vocab = self._tokenizer.vocab_size_actual if self._tokenizer and self._tokenizer.is_trained else 8000
            self._model = _build_model(vocab_size=vocab)
            if self._model is not None:
                try:
                    import torch
                    self._model.to(self._device)
                    self._model.eval()
                except Exception:
                    pass
        return self._model

    def set_tokenizer(self, tokenizer: ChainTokenizer) -> None:
        """Set a trained tokenizer and rebuild the model to match.

        Must be called before the model is first accessed (before
        ``is_available`` or ``model`` is queried).

        Args:
            tokenizer: A trained ChainTokenizer instance.
        """
        self._tokenizer = tokenizer
        # Force rebuild with new vocab size
        self._model = None

    @property
    def is_available(self) -> bool:
        """Check if PyTorch model is available."""
        return self.model is not None

    def generate(self, sample) -> Any:
        """Generate a chain for a sample using best-of-N selection.

        Generates 1 correct solution chain + 4 corrupted variants, scores each
        with the neural reward model. Correct chains get a strong bonus (+0.25)
        so the model defaults to correct but can override with high confidence.

        As training improves, the model learns to assign higher raw scores to
        correct chains, eventually overriding the bonus on merit alone.

        Args:
            sample: MazeSample to generate a chain for.

        Returns:
            MazeReasoningChain with highest predicted reward.
        """
        from kicad_agent.training.chains import (
            synthesize_maze_chain,
            synthesize_corrupted_chain,
        )

        correct = synthesize_maze_chain(sample)

        # 4 corrupted variants for contrast
        corrupted = [
            synthesize_corrupted_chain(sample, "wrong_coords", rng_seed=sample.seed),
            synthesize_corrupted_chain(sample, "missing_steps", rng_seed=sample.seed + 1),
            synthesize_corrupted_chain(sample, "wrong_order", rng_seed=sample.seed + 2),
            synthesize_corrupted_chain(sample, "vague_reasoning", rng_seed=sample.seed + 3),
        ]

        best_chain = correct
        best_score = -1.0

        # Score correct chain with bonus
        pred = predict_reward(self, correct.chain_text)
        score = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0 + 0.25
        best_score = score

        # Score corrupted chains (no bonus)
        for chain in corrupted:
            pred = predict_reward(self, chain.chain_text)
            score = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0
            if score > best_score:
                best_score = score
                best_chain = chain

        return best_chain


def predict_reward(model: RewardModel, chain_text: str) -> PredictedReward:
    """Predict reward scores for a chain using the neural model.

    Args:
        model: RewardModel instance.
        chain_text: Chain text to score.

    Returns:
        PredictedReward with format, quality, accuracy scores.
        Returns neutral (0.5, 0.5, 0.5) if PyTorch not available.
    """
    if not model.is_available:
        return PredictedReward(format_score=0.5, quality_score=0.5, accuracy_score=0.5)

    import torch

    if model._tokenizer and model._tokenizer.is_trained:
        token_ids, attention_mask = model._tokenizer.encode(chain_text)
    else:
        token_ids, attention_mask = _simple_tokenize(chain_text)
    input_ids = torch.tensor([token_ids], dtype=torch.long, device=model._device)
    attn_mask = torch.tensor([attention_mask], dtype=torch.long, device=model._device)

    with torch.no_grad():
        fmt, qual, acc = model.model(input_ids, attn_mask)

    return PredictedReward(
        format_score=fmt.item(),
        quality_score=qual.item(),
        accuracy_score=acc.item(),
    )


def train_reward_model(
    model: RewardModel,
    train_texts: list[str],
    train_labels: list[tuple[float, float, float]],
    val_texts: list[str] | None = None,
    val_labels: list[tuple[float, float, float]] | None = None,
    n_epochs: int = 5,
    learning_rate: float = 1e-4,
    batch_size: int = 32,
) -> dict:
    """Train the reward model on scored chains.

    Uses MSE loss against ground-truth reward signals (from score_chain).

    Args:
        model: RewardModel instance.
        train_texts: Chain texts for training.
        train_labels: (format, quality, accuracy) tuples for each text.
        val_texts: Optional validation texts.
        val_labels: Optional validation labels.
        n_epochs: Number of training epochs.
        learning_rate: AdamW learning rate.
        batch_size: Training batch size.

    Returns:
        Dict with training history (losses, val_losses).
    """
    if not model.is_available:
        return {"error": "PyTorch not available"}

    import torch
    import torch.nn as nn

    device = model._device
    nn_model = model.model
    nn_model.train()

    optimizer = torch.optim.AdamW(nn_model.parameters(), lr=learning_rate)
    loss_fn = nn.MSELoss()

    # Tokenize training data
    all_ids = []
    all_masks = []
    for text in train_texts:
        if model._tokenizer and model._tokenizer.is_trained:
            ids, mask = model._tokenizer.encode(text)
        else:
            ids, mask = _simple_tokenize(text)
        all_ids.append(ids)
        all_masks.append(mask)

    input_ids_t = torch.tensor(all_ids, dtype=torch.long, device=device)
    attn_mask_t = torch.tensor(all_masks, dtype=torch.long, device=device)
    labels_t = torch.tensor(train_labels, dtype=torch.float32, device=device)

    history: dict[str, list] = {"losses": [], "val_losses": []}

    for epoch in range(n_epochs):
        nn_model.train()
        epoch_loss = 0.0
        n_batches = 0

        # Simple batch iteration
        indices = list(range(len(train_texts)))
        for i in range(0, len(indices), batch_size):
            batch_idx = indices[i:i + batch_size]
            batch_ids = input_ids_t[batch_idx]
            batch_mask = attn_mask_t[batch_idx]
            batch_labels = labels_t[batch_idx]

            fmt, qual, acc = nn_model(batch_ids, batch_mask)
            preds = torch.cat([fmt, qual, acc], dim=1)
            loss = loss_fn(preds, batch_labels)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            epoch_loss += loss.item()
            n_batches += 1

        avg_loss = epoch_loss / max(n_batches, 1)
        history["losses"].append(avg_loss)

    nn_model.eval()
    return history
