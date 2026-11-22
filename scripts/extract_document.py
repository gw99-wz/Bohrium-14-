#!/usr/bin/env python3
"""Extract a page-indexed, offset-exact document model from a PDF (or text file).

    python scripts/extract_document.py --input paper.pdf --out work/document.json

The output is the canonical text every later step quotes from.  Nothing is
paraphrased here: the extractor only decides where paragraphs and sentences
begin and end, and records Unicode code-point offsets.

Exit codes:
    0  extracted, text layer present
    3  extracted, but no usable text layer (scanned PDF) -- caller must degrade
    2  bad input / unreadable file
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

from docmodel import (
    PIPELINE_VERSION,
    build_page_text,
    join_lines,
    sha256_bytes,
    sha256_file,
    write_json,
)

MIN_TEXT_CHARS = 200


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _open_pdf(path: str):
    try:
        import pymupdf as fitz  # PyMuPDF >= 1.24
    except ImportError:  # pragma: no cover - older installs
        import fitz  # type: ignore
    return fitz.open(path)


def _pdf_blocks(page) -> list:
    """Paragraph texts for one page, in the reader's order.

    PyMuPDF returns blocks already ordered by its layout analysis, which is what
    two-column papers need; we keep that order rather than re-sorting by y.
    """
    raw = page.get_text("blocks") or []
    blocks = []
    for block in raw:
        # (x0, y0, x1, y1, text, block_no, block_type); block_type 0 == text
        if len(block) >= 7 and block[6] != 0:
            continue
        text = block[4] if len(block) >= 5 else ""
        if not text or not text.strip():
            continue
        lines = text.splitlines()
        joined = join_lines(lines)
        if joined:
            blocks.append(joined)
    return blocks


def _pdf_metadata(path: str) -> dict:
    try:
        fitz = _open_pdf(path)
    except Exception:
        return {}
    meta = {}
    try:
        raw = fitz.metadata or {}
        meta["title"] = (raw.get("title") or "").strip() or None
        meta["author"] = (raw.get("author") or "").strip() or None
        meta["producer"] = (raw.get("producer") or "").strip() or None
        meta["creationDate"] = (raw.get("creationDate") or "").strip() or None
        meta["page_count"] = fitz.page_count
    finally:
        fitz.close()
    return meta


def extract_pdf(path: str) -> dict:
    doc = _open_pdf(path)
    pages = []
    warnings = []
    total_chars = 0
    try:
        for pno in range(doc.page_count):
            page = doc.load_page(pno)
            blocks = _pdf_blocks(page)
            built = build_page_text(blocks, pno + 1)
            total_chars += len(built["text"].strip())
            pages.append(
                {
                    "page": pno + 1,
                    "char_length": built["char_length"],
                    "text": built["text"],
                    "blocks": built["blocks"],
                }
            )
    finally:
        doc.close()

    text_layer = total_chars >= MIN_TEXT_CHARS
    if text_layer and total_chars < 1500:
        warnings.append(
            f"only {total_chars} text characters across {len(pages)} pages; "
            "check that the PDF is not a partial scan"
        )
    return {
        "pages": pages,
        "text_layer": text_layer,
        "total_chars": total_chars,
        "warnings": warnings,
        "page_count": len(pages),
    }


def extract_text(path: str) -> dict:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    chunks = [c for c in raw.split("\f") if c.strip()]
    pages = []
    for pno, chunk in enumerate(chunks or [raw]):
        paragraphs = [join_lines(p.splitlines()) for p in chunk.split("\n\n")]
        built = build_page_text([p for p in paragraphs if p], pno + 1)
        pages.append(
            {
                "page": pno + 1,
                "char_length": built["char_length"],
                "text": built["text"],
                "blocks": built["blocks"],
            }
        )
    total = sum(len(p["text"].strip()) for p in pages)
    return {
        "pages": pages,
        "text_layer": total >= MIN_TEXT_CHARS,
        "total_chars": total,
        "warnings": [],
        "page_count": len(pages),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Extract an offset-exact document model.")
    ap.add_argument("--input", required=True, help="PDF or UTF-8 text file")
    ap.add_argument("--out", required=True, help="document.json output path")
    ap.add_argument("--title", default=None, help="paper title, if the case supplies it")
    ap.add_argument("--authors", default=None, help="comma separated authors, if supplied")
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--doi", default=None)
    ap.add_argument("--url", default=None)
    ap.add_argument("--venue", default=None)
    args = ap.parse_args(argv)

    if not os.path.exists(args.input):
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 2

    ext = os.path.splitext(args.input)[1].lower()
    try:
        if ext == ".pdf":
            data = extract_pdf(args.input)
            meta = _pdf_metadata(args.input)
            extractor = "pymupdf"
        else:
            data = extract_text(args.input)
            meta = {}
            extractor = "plain-text"
    except Exception as exc:  # corrupt PDF, encrypted, missing dependency
        print(f"error: cannot read {args.input}: {exc}", file=sys.stderr)
        return 2

    doc_meta = {
        "title": args.title or meta.get("title"),
        "authors": [a.strip() for a in (args.authors or "").split(",") if a.strip()]
        if args.authors
        else ([meta.get("author")] if meta.get("author") else []),
        "year": args.year,
        "venue": args.venue,
        "doi": args.doi,
        "url": args.url,
        "pdf_producer": meta.get("producer"),
        "pdf_creation_date": meta.get("creationDate"),
    }

    payload = {
        "schema_version": "nanopub-document/1.0",
        "extracted_at": _now(),
        "pipeline_version": PIPELINE_VERSION,
        "input": {
            "path": args.input,
            "filename": os.path.basename(args.input),
            "bytes": os.path.getsize(args.input),
            "sha256": sha256_file(args.input),
            "kind": "pdf" if ext == ".pdf" else "text",
        },
        "extractor": extractor,
        "metadata": doc_meta,
        "document": {
            "pages": data["page_count"],
            "text_layer": data["text_layer"],
            "total_chars": data["total_chars"],
        },
        "pages": data["pages"],
        "warnings": data["warnings"],
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    write_json(args.out, payload)

    summary = {
        "status": "ok" if data["text_layer"] else "no_text_layer",
        "out": args.out,
        "pages": data["page_count"],
        "text_layer": data["text_layer"],
        "total_chars": data["total_chars"],
        "sentences": sum(len(b["sentences"]) for p in data["pages"] for b in p["blocks"]),
        "warnings": data["warnings"],
    }
    print(json.dumps(summary, ensure_ascii=False))

    if not data["text_layer"]:
        print(
            "warning: no usable text layer (scanned PDF?). The pipeline must report "
            "status=uncertain/partial instead of inventing text.",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
