#!/usr/bin/env python3
"""Build the structured reading result from agent-authored assertions.

Inputs
    case.json        -- the case handed to the run (case_id, instruction, contract)
    document.json    -- produced by extract_document.py (canonical text + offsets)
    assertions.json  -- the agent's decomposition work (one claim per assertion)

Outputs
    result.json      -- schema-valid structured result (schemas/result.schema.json)
    qc.json          -- every quality check with its verdict and evidence
    evidence.csv     -- flat, reviewable assertion -> evidence table

The point of this program is not to invent assertions.  It is to make the
agent's assertions *checkable*: every quote is located in the source, every
identifier is content-derived, and anything that cannot be confirmed is
downgraded and reported instead of being written as fact.

Exit codes:
    0  success       1  partial       4  uncertain       5  refused
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import os
import re
import sys

from docmodel import (
    PIPELINE_VERSION,
    SCHEMA_VERSION,
    locate_quote,
    make_id,
    read_json,
    sha256_file,
    split_sentences,
    write_json,
)

DEFAULT_VOCAB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references", "relations.json")

OVERBROAD = re.compile(
    r"\b(all|every|always|never|proves?|universally|entirely|completely|only)\b|总是|所有|必然|完全|始终",
    re.IGNORECASE,
)
MAX_ATOMIC_CHARS = 320
CONFIDENCE_ORDER = ["high", "medium", "low"]


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_case(path: str) -> dict:
    """Read case.json defensively: the platform owns its exact shape."""
    if not path or not os.path.exists(path):
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def _case_id(case: dict, fallback: str) -> str:
    for key in ("case_id", "caseId", "id", "case"):
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _contract_fields(case: dict) -> list:
    """Field names the case's output_contract asks for, whatever its shape."""
    contract = case.get("output_contract") or case.get("outputContract") or {}
    fields: list = []
    if isinstance(contract, dict):
        for key, value in contract.items():
            if key in ("fields", "required", "schema") and isinstance(value, (list, dict)):
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            fields.append(item)
                        elif isinstance(item, dict):
                            name = item.get("field") or item.get("name")
                            if name:
                                fields.append(name)
                else:
                    fields.extend(list(value.keys()))
            elif key not in ("schema_version", "version", "description"):
                fields.append(key)
    elif isinstance(contract, list):
        for item in contract:
            if isinstance(item, str):
                fields.append(item)
            elif isinstance(item, dict):
                name = item.get("field") or item.get("name")
                if name:
                    fields.append(name)
    seen, ordered = set(), []
    for field in fields:
        if field not in seen:
            seen.add(field)
            ordered.append(field)
    return ordered


def _downgrade(level: str) -> str:
    try:
        idx = CONFIDENCE_ORDER.index(level)
    except ValueError:
        return "low"
    return CONFIDENCE_ORDER[min(idx + 1, len(CONFIDENCE_ORDER) - 1)]


def _short_id(prefix: str, *parts: str) -> str:
    """12-hex identifier, the width the result schema requires."""
    return make_id(prefix, *parts).replace(f"{prefix}:", f"{prefix}:")[: len(prefix) + 1 + 12]


def _uncertainty(kind: str, description: str, *, assertion_id=None, locator=None, human_takeover=None) -> dict:
    """Uncertainty entry, omitting optional keys instead of writing null."""
    item = {
        "item_id": _short_id("unc", kind, description),
        "kind": kind,
        "description": description,
        "related_assertion_id": assertion_id,
    }
    if locator:
        item["related_locator"] = locator
    if human_takeover:
        item["human_takeover"] = human_takeover
    return item


def _check(rule_id: str, result: str, detail: str, ids=None) -> dict:
    return {
        "rule_id": rule_id,
        "result": result,
        "detail": detail,
        "assertion_ids": ids or [],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a checkable reading result.")
    ap.add_argument("--case", default=None, help="case.json from the platform")
    ap.add_argument("--document", required=True, help="document.json from extract_document.py")
    ap.add_argument("--assertions", required=True, help="assertions.json authored by the agent")
    ap.add_argument("--out", required=True, help="result.json output path")
    ap.add_argument("--qc-out", default=None, help="optional qc.json output path")
    ap.add_argument("--csv-out", default=None, help="optional evidence.csv output path")
    ap.add_argument("--vocab", default=DEFAULT_VOCAB, help="controlled relation vocabulary")
    args = ap.parse_args(argv)

    started_at = _now()
    for path, label in ((args.document, "document"), (args.assertions, "assertions")):
        if not os.path.exists(path):
            print(f"error: {label} file not found: {path}", file=sys.stderr)
            return 5

    document = read_json(args.document)
    payload = read_json(args.assertions)
    case = _load_case(args.case)

    vocab_types = set()
    try:
        vocab_data = read_json(args.vocab)
        vocab_types = set(vocab_data.get("relations", {}).keys())
    except Exception:
        vocab_types = set()

    pages = {p["page"]: p for p in document.get("pages", [])}
    text_layer = bool(document.get("document", {}).get("text_layer"))
    doc_input = document.get("input", {})
    source_meta = document.get("metadata", {}) or {}

    # Case-supplied provenance wins over PDF metadata (the case knows the paper).
    for key in ("title", "year", "venue", "doi", "url"):
        value = case.get(key)
        if value:
            source_meta[key] = value
    if case.get("authors"):
        supplied = case["authors"]
        source_meta["authors"] = [supplied] if isinstance(supplied, str) else list(supplied)

    source_id = make_id("src", doc_input.get("sha256", "unknown-source"))
    missing_fields = [
        field
        for field in ("title", "authors", "year")
        if not source_meta.get(field)
    ]

    declared = payload.get("assertions", [])
    if isinstance(payload, list):
        declared = payload
    if not isinstance(declared, list):
        declared = []

    assertions: list = []
    uncertainty: list = []
    change_log: list = [
        {
            "at": started_at,
            "change": f"built result from {len(declared)} declared assertion(s)",
            "reason": f"pipeline {PIPELINE_VERSION}",
        }
    ]
    skipped: list = []
    all_ids: list = []

    for raw in declared:
        if not isinstance(raw, dict):
            skipped.append("non-object assertion")
            continue
        text = (raw.get("text") or "").strip()
        subject = raw.get("subject") or {}
        obj = raw.get("object") or {}
        relation = raw.get("relation") or {}
        if not text or not subject.get("label") or not obj.get("label"):
            skipped.append(text[:60] or "assertion missing text/subject/object")
            continue

        assertion_id = make_id("asrt", source_id, text)
        all_ids.append(assertion_id)

        evidence_out: list = []
        verified_count = 0
        for ev in raw.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            quote = ev.get("quote") or ""
            hint = ev.get("page")
            order = []
            if isinstance(hint, int) and hint in pages:
                order.append(hint)
            order.extend(p for p in sorted(pages) if p not in order)

            located = {"verified": False, "method": "unchecked", "detail": "page not searched"}
            hit_page = None
            for page_no in order:
                located = locate_quote(pages[page_no].get("text", ""), quote)
                if located.get("verified"):
                    hit_page = page_no
                    break
            if hit_page is None and pages:
                hit_page = next(iter(sorted(pages)))

            block_id = None
            sentence_ids: list = []
            if hit_page is not None and located.get("verified"):
                for block in pages[hit_page].get("blocks", []):
                    if block["char_start"] <= located["char_start"] < block["char_end"]:
                        block_id = block["block_id"]
                        for sent in block.get("sentences", []):
                            if sent["char_end"] > located["char_start"] and sent["char_start"] < located["char_end"]:
                                sentence_ids.append(sent["sentence_id"])
                        break
                verified_count += 1

            evidence_out.append(
                {
                    "evidence_id": make_id("evd", assertion_id, quote, str(hit_page)),
                    "quote": quote,
                    "locator": {
                        "page": hit_page if hit_page is not None else 1,
                        "char_start": located.get("char_start", 0),
                        "char_end": located.get("char_end", 0),
                        "block_id": block_id,
                        "sentence_ids": sentence_ids,
                        "section": ev.get("section"),
                        "figure_or_table": ev.get("figure_or_table"),
                    },
                    "evidence_type": ev.get("evidence_type") or "direct",
                    "verification": {
                        "verified": bool(located.get("verified")),
                        "method": located.get("method", "unchecked"),
                        "detail": located.get("detail", ""),
                    },
                }
            )

        declared_conf = (raw.get("confidence") or {}).get("level") or "medium"
        confidence_level = declared_conf if declared_conf in CONFIDENCE_ORDER else "medium"
        basis = (raw.get("confidence") or {}).get("basis") or ""
        if not basis:
            basis = "agent did not record a basis; treated as unsupported"
            confidence_level = "low"
        unverified = sum(1 for e in evidence_out if not e["verification"]["verified"])
        if unverified:
            new_level = _downgrade(confidence_level)
            if new_level != confidence_level:
                change_log.append(
                    {
                        "at": started_at,
                        "change": f"downgraded confidence of {assertion_id} from {confidence_level} to {new_level}",
                        "reason": f"{unverified} evidence span(s) could not be located in the source",
                    }
                )
            confidence_level = new_level
            uncertainty.append(
                _uncertainty(
                    "evidence_not_found",
                    f"{unverified} declared evidence span(s) for this assertion are not present in the extracted text.",
                    assertion_id=assertion_id,
                    locator=evidence_out[0]["locator"] if evidence_out else None,
                    human_takeover="Open the cited page, confirm the sentence by hand, then re-quote it verbatim.",
                )
            )

        relation_type = relation.get("type") or "reports"
        atomicity = {
            "claim_count": int(raw.get("claim_count") or 1),
            "conditions_kept": raw.get("conditions") or [],
            "scope": raw.get("scope"),
        }
        assertions.append(
            {
                "assertion_id": assertion_id,
                "text": text,
                "atomicity": atomicity,
                "subject": {
                    "label": subject.get("label"),
                    "entity_type": subject.get("entity_type") or "other",
                    "normalized": subject.get("normalized"),
                    "identifiers": subject.get("identifiers") or {},
                },
                "relation": {
                    "type": relation_type,
                    "vocabulary": "nanopub-relations/1.0",
                    "in_vocabulary": relation_type in vocab_types if vocab_types else False,
                },
                "object": {
                    "label": obj.get("label"),
                    "entity_type": obj.get("entity_type") or "other",
                    "normalized": obj.get("normalized"),
                    "identifiers": obj.get("identifiers") or {},
                },
                "evidence": evidence_out,
                "confidence": {
                    "level": confidence_level,
                    "basis": basis,
                    "derived_from": (raw.get("confidence") or {}).get("derived_from") or "agent_judgement",
                },
                "provenance": {
                    "source_id": source_id,
                    "paper_ref": raw.get("paper_ref") or source_meta.get("title"),
                    "quoted_in_context": None,
                },
                "notes": raw.get("notes"),
            }
        )

    # ---------------------------------------------------------------- quality control
    checks: list = []
    ids = lambda items: [a["assertion_id"] for a in items]  # noqa: E731

    # Uncertainty the agent declares itself (conflicts, gaps, ambiguity).  Linked
    # by assertion *text*, because the ids are content-derived and unknown to the
    # author at writing time.
    allowed_kinds = {
        "not_reported_in_source",
        "conflicting_statements",
        "evidence_not_found",
        "ambiguous_subject",
        "partial_page_coverage",
        "no_text_layer",
        "out_of_scope",
    }
    by_text = {a["text"].strip(): a["assertion_id"] for a in assertions}
    for item in payload.get("uncertainty") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        description = (item.get("description") or "").strip()
        if kind not in allowed_kinds or not description:
            change_log.append(
                {
                    "at": started_at,
                    "change": f"dropped a declared uncertainty entry (kind={kind!r})",
                    "reason": "kind must be one of the controlled uncertainty kinds and description must be non-empty",
                }
            )
            continue
        related = None
        declared_text = (item.get("related_assertion_text") or "").strip()
        if declared_text:
            related = by_text.get(declared_text)
            if related is None:
                change_log.append(
                    {
                        "at": started_at,
                        "change": f"declared uncertainty {kind!r} not linked to an assertion",
                        "reason": "related_assertion_text did not match any built assertion",
                    }
                )
        uncertainty.append(
            _uncertainty(
                kind,
                description,
                assertion_id=related,
                human_takeover=item.get("human_takeover"),
            )
        )

    bundled = [
        a
        for a in assertions
        if a["atomicity"]["claim_count"] > 1
        or len(a["text"]) > MAX_ATOMIC_CHARS
        or len(split_sentences(a["text"])) > 1
    ]
    checks.append(
        _check(
            "QC-01-atomicity",
            "warn" if bundled else "pass",
            f"{len(bundled)} assertion(s) look like more than one claim (claim_count>1, >{MAX_ATOMIC_CHARS} chars, or several sentence endings)",
            ids(bundled),
        )
    )

    no_evidence = [a for a in assertions if not a["evidence"]]
    checks.append(
        _check(
            "QC-02-evidence-present",
            "fail" if no_evidence else "pass",
            f"{len(no_evidence)} assertion(s) carry no evidence span",
            ids(no_evidence),
        )
    )

    partial_ev = [a for a in assertions if a["evidence"] and any(not e["verification"]["verified"] for e in a["evidence"])]
    all_bad = [a for a in assertions if a["evidence"] and not any(e["verification"]["verified"] for e in a["evidence"])]
    if all_bad or no_evidence:
        ev_result = "fail"
    elif partial_ev:
        ev_result = "warn"
    else:
        ev_result = "pass"
    checks.append(
        _check(
            "QC-03-evidence-verified",
            ev_result,
            f"{len(partial_ev)} assertion(s) have at least one unverified span; {len(all_bad)} have none verified",
            ids(partial_ev),
        )
    )

    out_vocab = [a for a in assertions if not a["relation"]["in_vocabulary"]]
    checks.append(
        _check(
            "QC-04-relation-vocabulary",
            "warn" if out_vocab else "pass",
            f"{len(out_vocab)} assertion(s) use a relation outside the controlled vocabulary",
            ids(out_vocab),
        )
    )

    subject_missing = []
    for a in assertions:
        label = (a["subject"]["label"] or "").lower()
        quotes = " ".join(e["quote"].lower() for e in a["evidence"])
        if label and label not in quotes:
            subject_missing.append(a)
    checks.append(
        _check(
            "QC-05-subject-in-evidence",
            "warn" if subject_missing else "pass",
            f"{len(subject_missing)} assertion(s): subject label not literally present in its evidence (possible subject/relation confusion)",
            ids(subject_missing),
        )
    )

    checks.append(
        _check(
            "QC-06-provenance-complete",
            "warn" if missing_fields else "pass",
            "missing source fields: " + (", ".join(missing_fields) if missing_fields else "none"),
            [],
        )
    )

    overbroad = [a for a in assertions if OVERBROAD.search(a["text"]) and not a["atomicity"]["conditions_kept"]]
    checks.append(
        _check(
            "QC-07-overbroad-language",
            "warn" if overbroad else "pass",
            f"{len(overbroad)} assertion(s) use absolute wording with no recorded condition/scope",
            ids(overbroad),
        )
    )

    bad_locator = [
        a
        for a in assertions
        for e in a["evidence"]
        if e["verification"]["verified"] and (e["locator"]["char_end"] <= e["locator"]["char_start"])
    ]
    checks.append(
        _check(
            "QC-08-locator-precision",
            "fail" if bad_locator else "pass",
            f"{len(bad_locator)} verified span(s) have an empty or inverted character range",
            ids(bad_locator),
        )
    )

    seen_text = {}
    dupes = []
    for a in assertions:
        key = re.sub(r"\s+", " ", a["text"].strip().lower())
        if key in seen_text:
            dupes.append(a)
        else:
            seen_text[key] = a["assertion_id"]
    checks.append(
        _check(
            "QC-09-duplicates",
            "warn" if dupes else "pass",
            f"{len(dupes)} duplicated assertion(s)",
            ids(dupes),
        )
    )

    if not text_layer:
        uncertainty.append(
            _uncertainty(
                "no_text_layer",
                "The document has no usable text layer (likely a scan); no quote could be verified against text.",
                human_takeover="Run OCR on the PDF, or supply the publisher HTML/XML, then rerun the pipeline.",
            )
        )
    for text_skipped in skipped:
        uncertainty.append(
            _uncertainty(
                "out_of_scope",
                f"assertion dropped during build: {text_skipped}",
                human_takeover="Fix the assertions.json entry and rerun.",
            )
        )

    total_spans = sum(len(a["evidence"]) for a in assertions)
    verified_spans = sum(1 for a in assertions for e in a["evidence"] if e["verification"]["verified"])
    summary = {
        "pass": sum(1 for c in checks if c["result"] == "pass"),
        "warn": sum(1 for c in checks if c["result"] == "warn"),
        "fail": sum(1 for c in checks if c["result"] == "fail"),
    }

    # ---------------------------------------------------------------------- status
    critical_fail = any(c["rule_id"] in ("QC-02-evidence-present", "QC-08-locator-precision") and c["result"] == "fail" for c in checks)
    if not assertions:
        status = "refused"
        reason = "no assertion survived input validation; nothing can be asserted from this run"
    elif not text_layer:
        status = "uncertain"
        reason = "document has no usable text layer, so no evidence span could be confirmed"
    elif critical_fail or partial_ev or no_evidence:
        status = "partial"
        reason = f"produced {len(assertions)} assertion(s) with declared gaps: {summary['fail']} failing and {summary['warn']} warning check(s)"
    elif missing_fields:
        status = "partial"
        reason = "assertions are evidence-backed but source metadata is incomplete: " + ", ".join(missing_fields)
    else:
        status = "success"
        reason = f"all {len(assertions)} assertion(s) carry verified evidence; {summary['warn']} warning check(s)"

    result = {
        "schema_version": SCHEMA_VERSION,
        "case_id": _case_id(case, os.path.splitext(os.path.basename(args.document))[0]),
        "task": {
            "instruction": str(case.get("instruction") or case.get("task") or case.get("prompt") or ""),
            "question": str(case.get("question") or ""),
            "output_contract_fields": _contract_fields(case),
            "materials": [str(m) for m in (case.get("materials") or case.get("files") or [])],
        },
        "run": {
            "status": status,
            "status_reason": reason,
            "pipeline_version": PIPELINE_VERSION,
            "started_at": started_at,
            "finished_at": _now(),
            "inputs": [
                {
                    "path": doc_input.get("path", args.document),
                    "sha256": doc_input.get("sha256") or sha256_file(args.document),
                    "kind": doc_input.get("kind", "pdf"),
                    "bytes": doc_input.get("bytes") or 0,
                },
                {
                    "path": args.assertions,
                    "sha256": sha256_file(args.assertions),
                    "kind": "assertions",
                    "bytes": os.path.getsize(args.assertions),
                },
            ],
            "counts": {
                "assertions": len(assertions),
                "evidence_spans": total_spans,
                "verified_spans": verified_spans,
                "unverified_spans": total_spans - verified_spans,
            },
            "limits": {
                "pages_read": sorted(pages.keys()),
                "pages_skipped": [],
                "notes": [
                    "char offsets are Unicode code points into the page text of document.json",
                    "only pages present in document.json were searched",
                ],
            },
        },
        "source": {
            "source_id": source_id,
            "title": source_meta.get("title"),
            "authors": source_meta.get("authors") or [],
            "year": source_meta.get("year"),
            "venue": source_meta.get("venue"),
            "version": case.get("version") or document.get("version"),
            "doi": source_meta.get("doi"),
            "url": source_meta.get("url"),
            "document": {
                "path": doc_input.get("path", args.document),
                "sha256": doc_input.get("sha256", ""),
                "pages": document.get("document", {}).get("pages", len(pages)),
                "text_layer": text_layer,
                "extractor": document.get("extractor"),
            },
            "missing_fields": missing_fields,
        },
        "nanopublication": {
            "id": make_id("np", SCHEMA_VERSION, source_id, ",".join(all_ids)),
            "created_at": _now(),
            "generator": PIPELINE_VERSION,
            "assertions": assertions,
        },
        "uncertainty": uncertainty,
        "quality_control": {
            "ruleset_version": "qc/1.0",
            "checks": checks,
            "summary": summary,
        },
        "change_log": change_log,
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    write_json(args.out, result)

    if args.qc_out:
        write_json(
            args.qc_out,
            {
                "case_id": result["case_id"],
                "status": status,
                "summary": summary,
                "checks": checks,
                "uncertainty": uncertainty,
            },
        )

    if args.csv_out:
        with open(args.csv_out, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(
                ["assertion_id", "assertion", "subject", "relation", "object", "page", "char_start", "char_end", "verified", "method", "confidence"]
            )
            for a in assertions:
                if not a["evidence"]:
                    writer.writerow([a["assertion_id"], a["text"], a["subject"]["label"], a["relation"]["type"], a["object"]["label"], "", "", "", "false", "no_evidence", a["confidence"]["level"]])
                for e in a["evidence"]:
                    writer.writerow(
                        [
                            a["assertion_id"],
                            a["text"],
                            a["subject"]["label"],
                            a["relation"]["type"],
                            a["object"]["label"],
                            e["locator"]["page"],
                            e["locator"]["char_start"],
                            e["locator"]["char_end"],
                            str(e["verification"]["verified"]).lower(),
                            e["verification"]["method"],
                            a["confidence"]["level"],
                        ]
                    )

    print(
        json.dumps(
            {
                "status": status,
                "out": args.out,
                "case_id": result["case_id"],
                "assertions": len(assertions),
                "evidence_spans": total_spans,
                "verified_spans": verified_spans,
                "nanopublication_id": result["nanopublication"]["id"],
                "qc": summary,
            },
            ensure_ascii=False,
        )
    )
    return {"success": 0, "partial": 1, "uncertain": 4, "refused": 5}[status]


if __name__ == "__main__":
    sys.exit(main())
