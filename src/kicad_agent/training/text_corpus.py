"""Textbook domain knowledge corpus for electronics design training.

Extracts structured knowledge from electronics textbooks (PDF) into
JSONL training data. Supports:
- Section chunks: Organized by chapter/section for knowledge infusion
- Q&A pairs: Generated from content for supervised fine-tuning
- Design rules: Specific equations, values, and principles

Compatible with the same JSONL split infrastructure as RealBoardDataset.

Usage:
    from kicad_agent.training.text_corpus import TextCorpusSample, TextCorpusDataset

    sample = TextCorpusSample(
        sample_id=0,
        source="Small Signal Audio Design",
        chapter="Op-Amps",
        section="Noise in Op-Amps",
        content="...",
        content_type="section",
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextCorpusSample:
    """A single text chunk from a textbook or technical document.

    Attributes:
        sample_id: Sequential index in dataset.
        source: Book/document title.
        author: Author name(s).
        chapter: Chapter title.
        section: Section or subsection title.
        page_start: Starting page number.
        page_end: Ending page number.
        content: Extracted text content.
        content_type: "section", "qa_pair", or "design_rule".
        content_hash: SHA256 hex digest for dedup.
    """

    sample_id: int
    source: str
    author: str
    chapter: str
    section: str
    page_start: int
    page_end: int
    content: str
    content_type: str  # "section" | "qa_pair" | "design_rule"
    content_hash: str


@dataclass
class TextCorpusDataset:
    """Collection of text corpus samples with metadata.

    Follows the same JSONL split pattern as RealBoardDataset.
    """

    samples: list[TextCorpusSample] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.samples)

    @property
    def chapter_counts(self) -> dict[str, int]:
        """Count of samples per chapter."""
        return dict(Counter(s.chapter for s in self.samples))

    def to_jsonl(self, path: Path) -> int:
        """Write samples as JSONL."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(path, "w") as f:
            for sample in self.samples:
                f.write(json.dumps(_sample_to_dict(sample)) + "\n")
                count += 1
        return count

    @staticmethod
    def from_jsonl(path: Path) -> TextCorpusDataset:
        """Load samples from a JSONL file."""
        path = Path(path)
        samples: list[TextCorpusSample] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    samples.append(_dict_to_sample(json.loads(line)))
        return TextCorpusDataset(samples=samples)

    def split(
        self,
        train: float = 0.8,
        val: float = 0.1,
        test: float = 0.1,
    ) -> tuple[TextCorpusDataset, TextCorpusDataset, TextCorpusDataset]:
        """Deterministic train/val/test split."""
        total = train + val + test
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Split fractions must sum to 1.0, got {total}")

        n = len(self.samples)
        import random
        rng = random.Random(42)
        indices = list(range(n))
        rng.shuffle(indices)
        shuffled = [self.samples[i] for i in indices]
        train_end = int(n * train)
        val_end = train_end + int(n * val)

        return (
            TextCorpusDataset(samples=shuffled[:train_end]),
            TextCorpusDataset(samples=shuffled[train_end:val_end]),
            TextCorpusDataset(samples=shuffled[val_end:]),
        )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _sample_to_dict(s: TextCorpusSample) -> dict:
    """Convert TextCorpusSample to a JSON-serializable dict."""
    return {
        "sample_id": s.sample_id,
        "source": s.source,
        "author": s.author,
        "chapter": s.chapter,
        "section": s.section,
        "page_start": s.page_start,
        "page_end": s.page_end,
        "content": s.content,
        "content_type": s.content_type,
        "content_hash": s.content_hash,
    }


def _dict_to_sample(d: dict) -> TextCorpusSample:
    """Convert a dict back to TextCorpusSample."""
    return TextCorpusSample(
        sample_id=d["sample_id"],
        source=d["source"],
        author=d["author"],
        chapter=d["chapter"],
        section=d["section"],
        page_start=d["page_start"],
        page_end=d["page_end"],
        content=d["content"],
        content_type=d["content_type"],
        content_hash=d["content_hash"],
    )


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def extract_pdf_chunks(
    pdf_path: Path,
    source_title: str = "",
    author: str = "",
    max_chunk_tokens: int = 800,
    min_chunk_chars: int = 100,
) -> list[TextCorpusSample]:
    """Extract text chunks from a PDF textbook.

    Reads all pages, splits into sections by heading patterns,
    and creates TextCorpusSample objects.

    Args:
        pdf_path: Path to PDF file.
        source_title: Title of the book/document.
        author: Author name(s).
        max_chunk_tokens: Approximate max tokens per chunk (chars/4).
        min_chunk_chars: Minimum characters for a valid chunk.

    Returns:
        List of TextCorpusSample objects.
    """
    from PyPDF2 import PdfReader

    pdf_path = Path(pdf_path)
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    logger.info("Extracting text from %d pages of %s", total_pages, pdf_path.name)

    # Extract all page texts
    page_texts: list[tuple[int, str]] = []
    for i in range(total_pages):
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            page_texts.append((i + 1, text))  # 1-indexed pages

    if not page_texts:
        logger.warning("No text extracted from PDF")
        return []

    # Detect chapter boundaries
    # Match "Chapter N: Title" or "Chapter N Title", strip trailing page numbers
    # Title must be <80 chars to avoid matching sentences like "Chapter 11 Table 9.3..."
    chapter_pattern = re.compile(
        r"^Chapter\s+(\d+)\s*[:.]?\s*(.{3,79})$",
        re.MULTILINE | re.IGNORECASE,
    )

    # Strip trailing dots and page numbers from TOC entries like "Title ......... 257"
    _toc_cleanup = re.compile(r"\s*[.]+\s*\d+\s*$")

    def _clean_chapter_title(raw: str) -> str:
        title = _toc_cleanup.sub("", raw).strip()
        # Skip titles that look like sentences (contain "Table", "Figure", etc.)
        _skip_words = ("table", "figure", "the ", "a ", "an ", "this ", "that ")
        if any(title.lower().startswith(w) for w in _skip_words):
            return ""
        return title

    # Normalize title for dedup comparison
    def _normalize_title(title: str) -> str:
        return re.sub(r"[^a-z0-9]", "", title.lower())

    # Parse chapter structure
    chapters: list[dict] = []
    current_chapter = {"number": 0, "title": "Front Matter", "pages": []}

    for page_num, text in page_texts:
        # Check for chapter heading
        match = chapter_pattern.search(text)
        if match:
            ch_num = int(match.group(1))
            ch_title = _clean_chapter_title(match.group(2))

            if not ch_title:
                current_chapter["pages"].append((page_num, text))
                continue

            # Skip if this is a TOC duplicate (normalized title already exists)
            ch_norm = _normalize_title(ch_title)
            is_dup = any(
                c["number"] == ch_num and _normalize_title(c["title"]) == ch_norm
                for c in chapters
            )
            if not is_dup:
                # Save previous chapter
                if current_chapter["pages"]:
                    chapters.append(current_chapter)
                current_chapter = {
                    "number": ch_num,
                    "title": ch_title,
                    "pages": [],
                }
        current_chapter["pages"].append((page_num, text))

    # Don't forget the last chapter
    if current_chapter["pages"]:
        chapters.append(current_chapter)

    logger.info("Found %d chapters", len(chapters))

    # Split chapters into chunks
    max_chunk_chars = max_chunk_tokens * 4  # rough token-to-char ratio
    samples: list[TextCorpusSample] = []
    sample_id = 0

    for ch in chapters:
        ch_title = f"Chapter {ch['number']}: {ch['title']}" if ch["number"] > 0 else ch["title"]
        full_text = "\n\n".join(text for _, text in ch["pages"])

        if len(full_text.strip()) < min_chunk_chars:
            continue

        # Get page range for this chapter
        page_nums = [p for p, _ in ch["pages"]]
        page_start = min(page_nums) if page_nums else 0
        page_end = max(page_nums) if page_nums else 0

        # Split into section-sized chunks
        chunks = _split_into_chunks(full_text, max_chunk_chars, min_chunk_chars)

        for chunk_text, section_title in chunks:
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()

            samples.append(TextCorpusSample(
                sample_id=sample_id,
                source=source_title,
                author=author,
                chapter=ch_title,
                section=section_title,
                page_start=page_start,
                page_end=page_end,
                content=chunk_text,
                content_type="section",
                content_hash=content_hash,
            ))
            sample_id += 1

    logger.info("Extracted %d text chunks from %d chapters", len(samples), len(chapters))
    return samples


def _split_into_chunks(
    text: str,
    max_chars: int,
    min_chars: int,
) -> list[tuple[str, str]]:
    """Split text into chunks at natural boundaries.

    Tries to split at paragraph breaks, then sentence breaks.
    Returns list of (chunk_text, section_title) tuples.
    """
    # Split into paragraphs
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return []

    # Try to detect section headings (capitalized short lines, or numbered headings)
    section_pattern = re.compile(
        r"^([A-Z][A-Za-z\s&,:\-]{2,60}|"
        r"\d+\.\d+\s+.+|"
        r"[A-Z][A-Z\s]{2,50})$"
    )

    chunks: list[tuple[str, str]] = []
    current_title = ""
    current_parts: list[str] = []
    current_len = 0

    for para in paragraphs:
        # Check if this paragraph is a section heading
        lines = para.split("\n")
        first_line = lines[0].strip()

        is_heading = (
            len(first_line) < 80
            and len(lines) <= 2
            and section_pattern.match(first_line)
        )

        if is_heading and current_parts:
            # Flush current chunk
            chunk_text = "\n\n".join(current_parts)
            if len(chunk_text) >= min_chars:
                chunks.append((chunk_text, current_title))
            current_title = first_line
            current_parts = []
            current_len = 0
        elif is_heading and not current_parts:
            current_title = first_line
            continue

        # Check if adding this paragraph would exceed max
        if current_len + len(para) > max_chars and current_parts:
            # Flush current chunk
            chunk_text = "\n\n".join(current_parts)
            if len(chunk_text) >= min_chars:
                chunks.append((chunk_text, current_title))
            current_parts = [para]
            current_len = len(para)
        else:
            current_parts.append(para)
            current_len += len(para)

    # Flush remaining
    if current_parts:
        chunk_text = "\n\n".join(current_parts)
        if len(chunk_text) >= min_chars:
            chunks.append((chunk_text, current_title))

    return chunks


def dedup_text_samples(samples: list[TextCorpusSample]) -> list[TextCorpusSample]:
    """Remove duplicate samples by content_hash."""
    seen: set[str] = set()
    unique: list[TextCorpusSample] = []
    for sample in samples:
        if sample.content_hash in seen:
            continue
        seen.add(sample.content_hash)
        unique.append(sample)
    return unique
