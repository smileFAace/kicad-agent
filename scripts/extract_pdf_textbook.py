#!/usr/bin/env python3
"""Extract domain knowledge from electronics textbooks into training data.

Reads PDF textbooks, extracts text by chapter/section, chunks into
~800-token sections, deduplicates, and writes train/val/test JSONL splits.

Usage:
    python3 scripts/extract_pdf_textbook.py \
        --pdf "/path/to/Small Signal Audio Design.pdf" \
        --output-dir training_data_textbook

    # Multiple PDFs
    python3 scripts/extract_pdf_textbook.py \
        --pdf book1.pdf book2.pdf \
        --titles "Book One" "Book Two" \
        --output-dir training_data_textbook
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.training.text_corpus import (
    TextCorpusDataset,
    TextCorpusSample,
    dedup_text_samples,
    extract_pdf_chunks,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("extract_pdf_textbook")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract training data from electronics textbook PDFs",
    )
    parser.add_argument(
        "--pdf",
        nargs="+",
        required=True,
        type=Path,
        help="Path(s) to PDF textbook file(s)",
    )
    parser.add_argument(
        "--titles",
        nargs="*",
        default=[],
        help="Title(s) for each PDF (default: filename)",
    )
    parser.add_argument(
        "--authors",
        nargs="*",
        default=[],
        help="Author(s) for each PDF",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training_data_textbook"),
        help="Output directory for JSONL splits",
    )
    parser.add_argument(
        "--max-chunk-tokens",
        type=int,
        default=800,
        help="Approximate max tokens per chunk (default: 800)",
    )
    parser.add_argument(
        "--min-chunk-chars",
        type=int,
        default=100,
        help="Minimum characters for a valid chunk (default: 100)",
    )
    args = parser.parse_args()

    # Validate PDFs exist
    for pdf_path in args.pdf:
        if not pdf_path.exists():
            logger.error("PDF not found: %s", pdf_path)
            return 1

    # Pad titles/authors to match PDF count
    titles = list(args.titles)
    while len(titles) < len(args.pdf):
        titles.append(args.pdf[len(titles)].stem)

    authors = list(args.authors)
    while len(authors) < len(args.pdf):
        authors.append("")

    # Extract chunks from each PDF
    all_samples: list[TextCorpusSample] = []
    sample_id = 0

    for pdf_path, title, author in zip(args.pdf, titles, authors):
        logger.info("Processing: %s (%s)", title, pdf_path.name)

        chunks = extract_pdf_chunks(
            pdf_path=pdf_path,
            source_title=title,
            author=author,
            max_chunk_tokens=args.max_chunk_tokens,
            min_chunk_chars=args.min_chunk_chars,
        )

        # Reassign sequential IDs
        for chunk in chunks:
            all_samples.append(TextCorpusSample(
                sample_id=sample_id,
                source=chunk.source,
                author=chunk.author,
                chapter=chunk.chapter,
                section=chunk.section,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                content=chunk.content,
                content_type=chunk.content_type,
                content_hash=chunk.content_hash,
            ))
            sample_id += 1

        logger.info("  Extracted %d chunks from %s", len(chunks), title)

    if not all_samples:
        logger.warning("No samples extracted from any PDF")
        return 0

    # Dedup
    n_before = len(all_samples)
    deduped = dedup_text_samples(all_samples)
    n_deduped = len(deduped)
    logger.info("Dedup: %d -> %d samples", n_before, n_deduped)

    # Build dataset
    from collections import Counter
    chapter_counts = dict(Counter(s.chapter for s in deduped))
    content_types = dict(Counter(s.content_type for s in deduped))

    metadata = {
        "source": "textbook",
        "n_pdfs": len(args.pdf),
        "n_raw": n_before,
        "n_deduped": n_deduped,
        "n_duplicates_removed": n_before - n_deduped,
        "chapter_counts": chapter_counts,
        "content_type_counts": content_types,
        "total_chars": sum(len(s.content) for s in deduped),
        "avg_chunk_chars": sum(len(s.content) for s in deduped) // max(len(deduped), 1),
    }

    dataset = TextCorpusDataset(samples=deduped, metadata=metadata)

    # Split and write
    output_dir = args.output_dir
    train_ds, val_ds, test_ds = dataset.split()
    train_ds.to_jsonl(output_dir / "train.jsonl")
    val_ds.to_jsonl(output_dir / "val.jsonl")
    test_ds.to_jsonl(output_dir / "test.jsonl")

    print(f"\n{'='*60}")
    print(f"Textbook extraction complete: {len(dataset)} samples")
    print(f"  PDFs processed:      {len(args.pdf)}")
    print(f"  Raw chunks:          {n_before}")
    print(f"  Duplicates removed:  {n_before - n_deduped}")
    print(f"  Total content:       {metadata['total_chars']:,} chars")
    print(f"  Avg chunk size:      {metadata['avg_chunk_chars']:,} chars")
    print(f"  Chapters:            {len(chapter_counts)}")
    print(f"  Splits:              {len(train_ds)} train / {len(val_ds)} val / {len(test_ds)} test")
    print(f"  Output:              {output_dir}/")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
