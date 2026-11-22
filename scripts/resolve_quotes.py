#!/usr/bin/env python3
"""Optional authoring aid: turn sentence references into literal quotes.

An agent reading ``document.json`` can point at ``sentence_id`` values instead of
retyping a quote, which removes copy errors on long or hyphenated spans.  This
script expands those references into the exact ``quote`` (plus a ``page`` hint)
and writes a normal ``assertions.json``.

It does **not** weaken verification: ``build_nanopub.py`` still searches for the
literal quote in the page text and marks it unverified if it cannot find it.

    python scripts/resolve_quotes.py --document work/document.json \
        --draft work/assertions.draft.json --out work/assertions.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys

from docmodel import read_json, write_json


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Expand sentence_id references into literal quotes.")
    ap.add_argument("--document", required=True)
    ap.add_argument("--draft", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    document = read_json(args.document)
    draft = read_json(args.draft)

    # sentence_id -> (page, text); ids must be globally unique
    index = {}
    duplicates: list = []
    for page in document.get("pages", []):
        for block in page.get("blocks", []):
            for sent in block.get("sentences", []):
                if sent["sentence_id"] in index:
                    duplicates.append(sent["sentence_id"])
                index[sent["sentence_id"]] = (page["page"], sent["text"])
    if duplicates:
        print(
            f"error: sentence_id is not unique across the document: {sorted(set(duplicates))[:5]}; "
            "re-extract so that ids embed the page number",
            file=sys.stderr,
        )
        return 1

    out = copy.deepcopy(draft)
    resolved = 0
    missing: list = []
    for assertion in out.get("assertions", []):
        for ev in assertion.get("evidence", []) or []:
            sent_ids = ev.pop("sentence_ids", None)
            if not sent_ids:
                continue
            pieces = []
            page_no = None
            for sent_id in sent_ids:
                hit = index.get(sent_id)
                if hit is None:
                    missing.append(sent_id)
                    continue
                page_no, text = hit
                pieces.append(text)
            if pieces:
                ev["quote"] = " ".join(pieces)
                if page_no is not None and "page" not in ev:
                    ev["page"] = page_no
                resolved += 1

    if missing:
        print(f"error: unknown sentence_id(s): {missing}", file=sys.stderr)
        return 1

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    write_json(args.out, out)
    print(json.dumps({"out": args.out, "evidence_spans_resolved": resolved}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
