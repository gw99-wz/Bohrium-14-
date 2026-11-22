#!/usr/bin/env python3
"""Independently validate a result.json.

Two layers, deliberately separate:

1. **Schema** -- the file must satisfy ``schemas/result.schema.json``.
2. **Replay** -- every evidence span is looked up again in the *source document*,
   re-extracted from the PDF when ``--pdf`` is given.  A span passes only if the
   recorded ``(page, char_start, char_end)`` slice equals the recorded quote and
   the quote really occurs on that page.  This is the check a reviewer would do
   by hand; here it is mechanical.

    python scripts/validate_result.py --result out/result.json --pdf paper.pdf

Exit codes: 0 everything verified, 1 at least one failure, 2 unusable input.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from docmodel import read_json

DEFAULT_SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schemas", "result.schema.json")


def _load_pages(result_path: str, document_path: str | None, pdf_path: str | None):
    """(page text, page object) maps, from document.json or a fresh extraction."""
    if document_path and os.path.exists(document_path):
        doc = read_json(document_path)
        pages = doc.get("pages", [])
        return {p["page"]: p["text"] for p in pages}, {p["page"]: p for p in pages}
    if pdf_path and os.path.exists(pdf_path):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from extract_document import extract_pdf  # noqa: WPS433

        data = extract_pdf(pdf_path)
        pages = data["pages"]
        return {p["page"]: p["text"] for p in pages}, {p["page"]: p for p in pages}
    return {}, {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate a reading result against schema and source.")
    ap.add_argument("--result", required=True)
    ap.add_argument("--schema", default=DEFAULT_SCHEMA)
    ap.add_argument("--document", default=None, help="document.json used to build the result")
    ap.add_argument("--pdf", default=None, help="re-extract from the original PDF instead")
    args = ap.parse_args(argv)

    if not os.path.exists(args.result):
        print(f"error: result not found: {args.result}", file=sys.stderr)
        return 2

    result = read_json(args.result)
    failures: list = []
    checks: list = []

    # ---- layer 1: schema
    schema_ok = True
    try:
        import jsonschema

        schema = read_json(args.schema)
        validator_cls = jsonschema.validators.validator_for(schema)
        validator = validator_cls(schema)
        errors = sorted(validator.iter_errors(result), key=lambda e: list(e.absolute_path))
        if errors:
            schema_ok = False
            for err in errors[:20]:
                failures.append(f"schema: {'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}")
    except ImportError:
        failures.append("schema: jsonschema is not installed; schema layer skipped")
        schema_ok = False
    checks.append(
        {
            "check": "schema",
            "result": "pass" if schema_ok else "fail",
            "detail": f"{len(failures)} schema error(s)" if not schema_ok else "result.json matches schemas/result.schema.json",
        }
    )

    # ---- structural expectations the schema cannot express
    np_ = result.get("nanopublication", {})
    assertions = np_.get("assertions", [])
    ids = [a.get("assertion_id") for a in assertions]
    dup_ids = sorted({i for i in ids if ids.count(i) > 1})
    checks.append(
        {
            "check": "unique-assertion-ids",
            "result": "fail" if dup_ids else "pass",
            "detail": f"duplicated: {dup_ids}" if dup_ids else f"{len(ids)} unique assertion id(s)",
        }
    )
    if dup_ids:
        failures.append(f"duplicate assertion ids: {dup_ids}")

    counts = result.get("run", {}).get("counts", {})
    real_spans = sum(len(a.get("evidence", [])) for a in assertions)
    real_verified = sum(1 for a in assertions for e in a.get("evidence", []) if e.get("verification", {}).get("verified"))
    count_ok = (
        counts.get("assertions") == len(assertions)
        and counts.get("evidence_spans") == real_spans
        and counts.get("verified_spans") == real_verified
    )
    checks.append(
        {
            "check": "declared-counts-match-content",
            "result": "pass" if count_ok else "fail",
            "detail": f"declared {counts}, actual assertions={len(assertions)} spans={real_spans} verified={real_verified}",
        }
    )
    if not count_ok:
        failures.append("run.counts does not match the assertions actually present")

    status = result.get("run", {}).get("status")
    if status == "success" and real_verified != real_spans:
        failures.append("status=success but some evidence spans are unverified")
    checks.append(
        {
            "check": "status-consistent",
            "result": "fail" if (status == "success" and real_verified != real_spans) else "pass",
            "detail": f"status={status}, verified {real_verified}/{real_spans}",
        }
    )

    # ---- layer 2: replay against the source
    pages, page_by_no = _load_pages(args.result, args.document, args.pdf)
    replay_checked = 0
    replay_failed: list = []
    if not pages:
        checks.append(
            {
                "check": "evidence-replay",
                "result": "warn",
                "detail": "no source document supplied; spans not re-checked against the original",
            }
        )
    else:
        for assertion in assertions:
            for ev in assertion.get("evidence", []):
                loc = ev.get("locator", {})
                page_no = loc.get("page")
                page_text = pages.get(page_no)
                if page_text is None:
                    replay_failed.append(f"{assertion.get('assertion_id')}: page {page_no} not in source")
                    continue
                slice_text = page_text[loc.get("char_start", 0): loc.get("char_end", 0)]
                replay_checked += 1
                if slice_text != ev.get("quote"):
                    replay_failed.append(
                        f"{assertion.get('assertion_id')}: slice != quote at page {page_no} "
                        f"[{loc.get('char_start')}:{loc.get('char_end')}]"
                    )
                elif ev.get("quote", "") not in page_text:
                    replay_failed.append(f"{assertion.get('assertion_id')}: quote absent from page {page_no}")

        # The locator's human-navigable part must agree with its offsets, otherwise
        # a reviewer following block/sentence ids lands somewhere else.
        meta_bad: list = []
        for assertion in assertions:
            for ev in assertion.get("evidence", []):
                loc = ev.get("locator", {})
                page_no = loc.get("page")
                page = page_by_no.get(page_no)
                if page is None:
                    continue
                start, end = loc.get("char_start", 0), loc.get("char_end", 0)
                block_id = loc.get("block_id")
                if block_id:
                    block = next((b for b in page.get("blocks", []) if b["block_id"] == block_id), None)
                    if block is None:
                        meta_bad.append(f"{assertion.get('assertion_id')}: block {block_id} not on page {page_no}")
                    elif not (block["char_start"] <= start < block["char_end"]):
                        meta_bad.append(f"{assertion.get('assertion_id')}: span outside block {block_id}")
                for sent_id in loc.get("sentence_ids") or []:
                    sent = next(
                        (s for b in page.get("blocks", []) for s in b.get("sentences", []) if s["sentence_id"] == sent_id),
                        None,
                    )
                    if sent is None:
                        meta_bad.append(f"{assertion.get('assertion_id')}: sentence {sent_id} not on page {page_no}")
                    elif not (sent["char_end"] > start and sent["char_start"] < end):
                        meta_bad.append(f"{assertion.get('assertion_id')}: span does not overlap sentence {sent_id}")
        checks.append(
            {
                "check": "locator-metadata-consistent",
                "result": "pass" if not meta_bad else "fail",
                "detail": f"{len(meta_bad)} block/sentence locator mismatch(es)",
            }
        )
        failures.extend(meta_bad[:20])
        checks.append(
            {
                "check": "evidence-replay",
                "result": "pass" if not replay_failed else "fail",
                "detail": f"{replay_checked} span(s) re-located in the source; {len(replay_failed)} mismatch(es)",
            }
        )
        failures.extend(replay_failed[:20])

    # ---- provenance
    source = result.get("source", {})
    prov_ok = bool(source.get("source_id")) and bool(source.get("document", {}).get("sha256"))
    checks.append(
        {
            "check": "provenance-anchored",
            "result": "pass" if prov_ok else "fail",
            "detail": f"source_id={source.get('source_id')} doc_sha256={(source.get('document') or {}).get('sha256', '')[:16]}…",
        }
    )
    if not prov_ok:
        failures.append("source_id or document sha256 missing")

    verdict = {
        "result_file": args.result,
        "schema_valid": schema_ok,
        "source_checked": bool(pages),
        "spans_replayed": replay_checked,
        "checks": checks,
        "failures": failures,
        "verdict": "PASS" if not failures else "FAIL",
    }
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
