"""Word-level tokenizer for reasoning chains.

Replaces the character-level tokenizer in reward_model.py with a vocabulary-
aware word tokenizer that preserves semantic structure. Key tokens like
`<point 5.0,10.0>`, `Observation:`, `via` become single IDs, enabling
the transformer to learn meaningful patterns.

Usage:
    from kicad_agent.training.tokenizer import ChainTokenizer

    tok = ChainTokenizer()
    tok.train(chain_texts)
    ids, mask = tok.encode("Observation: via at <point 5.0,10.0>")
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Sequence

# Special token IDs
_PAD_TOKEN = 0
_UNK_TOKEN = 1
_BOS_TOKEN = 2
_EOS_TOKEN = 3

_MAX_SEQ_LEN = 512


class ChainTokenizer:
    """Word-level tokenizer trained on reasoning chain corpus.

    Splits text into semantically meaningful tokens:
      - Coordinate tags: ``<point 5.0,10.0>`` → single token
      - Words: ``Observation``, ``via``, ``obstacle`` → single tokens
      - Numbers: ``5.0``, ``10.0`` → single tokens
      - Punctuation: ``:``, ``,``, ``-`` → single tokens

    Vocabulary is built from training corpus frequency, capped at
    ``vocab_size``. Unknown words map to ``<unk>``.
    """

    def __init__(self, vocab_size: int = 8000, max_seq_len: int = _MAX_SEQ_LEN):
        self.vocab_size = vocab_size
        self.max_seq_len = max_seq_len
        self.token_to_id: dict[str, int] = {
            "<pad>": _PAD_TOKEN,
            "<unk>": _UNK_TOKEN,
            "<bos>": _BOS_TOKEN,
            "<eos>": _EOS_TOKEN,
        }
        self.id_to_token: dict[int, str] = {v: k for k, v in self.token_to_id.items()}
        self._trained = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    @property
    def pad_token_id(self) -> int:
        return _PAD_TOKEN

    # ------------------------------------------------------------------
    # Tokenization primitives
    # ------------------------------------------------------------------

    @staticmethod
    def _split(text: str) -> list[str]:
        """Split text into word-level tokens preserving semantic units.

        Coordinate tags like ``<point 5.0,10.0>`` stay as one token.
        Words, numbers, and punctuation are separate tokens.
        """
        tokens: list[str] = []
        for word in text.split():
            # Extract coordinate tags, words, numbers, and punctuation
            parts = re.findall(
                r"<[^>]+>"       # coordinate tags: <point 5.0,10.0>
                r"|[a-zA-Z_]+"  # words: Observation, via
                r"|[0-9]+\.?[0-9]*"  # numbers: 5.0, 10
                r"|[^a-zA-Z0-9\s]",  # punctuation: : , -
                word,
            )
            tokens.extend(parts)
        return tokens

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, texts: Sequence[str]) -> None:
        """Build vocabulary from training texts.

        Args:
            texts: Chain text corpus to build vocabulary from.
        """
        word_counts: Counter[str] = Counter()
        for text in texts:
            word_counts.update(self._split(text))

        # Reserve 4 special tokens, fill rest from corpus
        n_tokens = self.vocab_size - 4
        for word, _ in word_counts.most_common(n_tokens):
            idx = len(self.token_to_id)
            self.token_to_id[word] = idx
            self.id_to_token[idx] = word

        self._trained = True

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    def encode(self, text: str) -> tuple[list[int], list[int]]:
        """Encode text to token IDs and attention mask.

        Args:
            text: Input chain text.

        Returns:
            (token_ids, attention_mask) tuple, padded to max_seq_len.
        """
        words = self._split(text)
        ids = [self.token_to_id.get(w, _UNK_TOKEN) for w in words[: self.max_seq_len]]
        # Pad
        attention_mask = [1] * len(ids) + [0] * (self.max_seq_len - len(ids))
        ids = ids + [_PAD_TOKEN] * (self.max_seq_len - len(ids))
        return ids[: self.max_seq_len], attention_mask[: self.max_seq_len]

    def encode_batch(self, texts: Sequence[str]) -> tuple[list[list[int]], list[list[int]]]:
        """Encode a batch of texts.

        Args:
            texts: Sequence of chain texts.

        Returns:
            (all_ids, all_masks) lists.
        """
        all_ids: list[list[int]] = []
        all_masks: list[list[int]] = []
        for text in texts:
            ids, mask = self.encode(text)
            all_ids.append(ids)
            all_masks.append(mask)
        return all_ids, all_masks

    @property
    def vocab_size_actual(self) -> int:
        """Actual vocabulary size (may be less than vocab_size if corpus is small)."""
        return len(self.token_to_id)
