#!/usr/bin/env python3
"""Self-contained test suite for the reading pipeline.

Every test runs the real scripts in-process against files it creates in a
temporary directory, so the suite needs no network and no bundled paper.

    python tests/run_tests.py

Scenarios
    A  clean run          -> status success, every span verified, validator PASS
    B  corrupted quote    -> status partial, span unverified, confidence downgraded
    C  missing evidence   -> status partial, QC-02 fails, validator FAILs
    D  no text layer      -> extractor exit 3, build status uncertain
    E  empty assertions   -> status refused, nothing invented

Exit code 0 only when every scenario behaves as specified.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import build_nanopub  # noqa: E402
import extract_document  # noqa: E402
import resolve_quotes  # noqa: E402
import validate_result  # noqa: E402
from docmodel import read_json, write_json  # noqa: E402

PARAGRAPHS = [
    "We study whether a sparse attention pattern preserves translation quality on a small benchmark. "
    "The sparse model reaches 27.1 BLEU on the development set, which is 0.8 BLEU below the dense baseline. "
    "These numbers were obtained with three seeds per configuration.",
    "Training used eight GPUs for two days with a batch size of 4096 tokens. "
    "We report the mean over three seeds and do not claim significance. "
    "Ablating the sparse pattern raises BLEU to 27.5, so the pattern is not neutral.",
    "We conclude that sparsity trades 0.8 BLEU for a 1.6x decoding speedup in this setting. "
    "The speedup was measured on the same hardware as the training runs.",
]


def _make_pdf(path: str, paragraphs, with_text: bool = True) -> None:
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page()
    if with_text:
        y = 64.0
        for para in paragraphs:
            page.insert_textbox(fitz.Rect(56, y, 540, y + 150), para, fontsize=10, align=0)
            y += 130
    else:  # a page with ink but no text layer, like a scan
        page.draw_rect(fitz.Rect(80, 80, 500, 300), color=(0, 0, 0), width=2)
        page.draw_line(fitz.Point(100, 340), fitz.Point(460, 340), color=(0, 0, 0), width=1)
    # Serialise in memory and write with plain Python: PyMuPDF's own save() is
    # refused under some file sandboxes even when the directory is writable.
    data = doc.tobytes()
    doc.close()
    with open(path, "wb") as fh:
        fh.write(data)


def _quiet(fn, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = fn(argv)
    return rc, buf.getvalue()


def _draft_from_document(document: dict) -> dict:
    """Author three assertions straight from the extracted sentences."""
    sents = [s for p in document["pages"] for b in p["blocks"] for s in b["sentences"] if len(s["text"]) > 40]
    picks = [sents[0], sents[1], sents[2]]
    subjects = ["sparse attention model", "training setup", "sparsity trade-off"]
    objects = ["27.1 BLEU on the development set", "eight GPUs for two days", "0.8 BLEU for a 1.6x decoding speedup"]
    relations = ["achieves", "uses", "reports"]
    assertions = []
    for sent, subj, obj, rel in zip(picks, subjects, objects, relations):
        assertions.append(
            {
                "text": sent["text"].rstrip(".") + ".",
                "subject": {"label": subj, "entity_type": "method"},
                "relation": {"type": rel},
                "object": {"label": obj, "entity_type": "metric"},
                "claim_count": 1,
                "conditions": ["development set"],
                "evidence": [{"sentence_ids": [sent["sentence_id"]], "evidence_type": "direct"}],
                "confidence": {"level": "high", "basis": "stated verbatim in the source", "derived_from": "direct_statement"},
            }
        )
    return {"assertions": assertions}


def main() -> int:
    # Work inside the repository: some sandboxes allow creating a directory in the
    # system temp area but refuse writing files into it.
    base = os.environ.get("NANOPUB_TEST_DIR") or os.path.join(ROOT, ".test-work")
    os.makedirs(base, exist_ok=True)
    # A fixed subdirectory rather than tempfile.mkdtemp: some file sandboxes deny
    # writes inside freshly randomised temp directories while allowing os.makedirs.
    work = os.path.join(base, "run")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    results = []

    def record(name, expected, got, ok, note=""):
        results.append({"scenario": name, "expected": expected, "got": got, "pass": bool(ok), "note": note})

    try:
        pdf = os.path.join(work, "fixture.pdf")
        blank = os.path.join(work, "blank.pdf")
        doc_json = os.path.join(work, "document.json")
        blank_json = os.path.join(work, "blank-document.json")
        case_json = os.path.join(work, "case.json")
        draft_json = os.path.join(work, "assertions.draft.json")
        assertions_json = os.path.join(work, "assertions.json")
        result_json = os.path.join(work, "result.json")

        _make_pdf(pdf, PARAGRAPHS, with_text=True)
        _make_pdf(blank, [], with_text=False)
        write_json(
            case_json,
            {
                "case_id": "selftest-01",
                "instruction": "decompose the paper into falsifiable assertions with evidence",
                "title": "Self-test fixture",
                "authors": ["Test Author"],
                "year": 2026,
                "output_contract": {"fields": [{"name": "assertion"}, {"name": "evidence_span"}]},
            },
        )

        # ---------------------------------------------------------------- scenario A
        rc_extract, _ = _quiet(extract_document.main, ["--input", pdf, "--out", doc_json])
        document = read_json(doc_json)
        write_json(draft_json, _draft_from_document(document))
        rc_resolve, _ = _quiet(resolve_quotes.main, ["--document", doc_json, "--draft", draft_json, "--out", assertions_json])
        rc_build, _ = _quiet(
            build_nanopub.main,
            ["--case", case_json, "--document", doc_json, "--assertions", assertions_json, "--out", result_json,
             "--qc-out", os.path.join(work, "qc.json")],
        )
        result = read_json(result_json)
        rc_valid, _ = _quiet(validate_result.main, ["--result", result_json, "--document", doc_json])
        record(
            "A clean run",
            "extract=0 resolve=0 build=0 status=success verified=all validate=0",
            f"extract={rc_extract} resolve={rc_resolve} build={rc_build} status={result['run']['status']} "
            f"verified={result['run']['counts']['verified_spans']}/{result['run']['counts']['evidence_spans']} validate={rc_valid}",
            rc_extract == 0 and rc_resolve == 0 and rc_build == 0 and rc_valid == 0
            and result["run"]["status"] == "success"
            and result["run"]["counts"]["unverified_spans"] == 0,
        )

        # ---------------------------------------------------------------- scenario B
        broken = json.loads(json.dumps(read_json(assertions_json)))
        broken["assertions"][0]["evidence"][0]["quote"] = "this sentence was never in the paper"
        broken_json = os.path.join(work, "assertions-broken.json")
        write_json(broken_json, broken)
        rc_build_b, _ = _quiet(
            build_nanopub.main,
            ["--case", case_json, "--document", doc_json, "--assertions", broken_json, "--out", os.path.join(work, "result-b.json")],
        )
        result_b = read_json(os.path.join(work, "result-b.json"))
        downgraded = result_b["nanopublication"]["assertions"][0]["confidence"]["level"] != "high"
        uncertain_kinds = {u["kind"] for u in result_b["uncertainty"]}
        rc_valid_b, _ = _quiet(validate_result.main, ["--result", os.path.join(work, "result-b.json"), "--document", doc_json])
        record(
            "B corrupted quote",
            "status=partial unverified>=1 confidence downgraded uncertainty has evidence_not_found",
            f"status={result_b['run']['status']} unverified={result_b['run']['counts']['unverified_spans']} "
            f"downgraded={downgraded} kinds={sorted(uncertain_kinds)} validate={rc_valid_b}",
            result_b["run"]["status"] == "partial"
            and result_b["run"]["counts"]["unverified_spans"] >= 1
            and downgraded
            and "evidence_not_found" in uncertain_kinds,
        )

        # ---------------------------------------------------------------- scenario C
        no_ev = json.loads(json.dumps(read_json(assertions_json)))
        no_ev["assertions"][1]["evidence"] = []
        no_ev_json = os.path.join(work, "assertions-noev.json")
        write_json(no_ev_json, no_ev)
        rc_build_c, _ = _quiet(
            build_nanopub.main,
            ["--case", case_json, "--document", doc_json, "--assertions", no_ev_json, "--out", os.path.join(work, "result-c.json")],
        )
        result_c = read_json(os.path.join(work, "result-c.json"))
        qc02 = next(c for c in result_c["quality_control"]["checks"] if c["rule_id"] == "QC-02-evidence-present")
        record(
            "C missing evidence",
            "status=partial QC-02=fail",
            f"status={result_c['run']['status']} QC-02={qc02['result']}",
            result_c["run"]["status"] == "partial" and qc02["result"] == "fail",
        )

        # ---------------------------------------------------------------- scenario D
        rc_extract_d, _ = _quiet(extract_document.main, ["--input", blank, "--out", blank_json])
        rc_build_d, _ = _quiet(
            build_nanopub.main,
            ["--case", case_json, "--document", blank_json, "--assertions", assertions_json, "--out", os.path.join(work, "result-d.json")],
        )
        result_d = read_json(os.path.join(work, "result-d.json"))
        kinds_d = {u["kind"] for u in result_d["uncertainty"]}
        record(
            "D no text layer",
            "extract=3 build status=uncertain uncertainty has no_text_layer",
            f"extract={rc_extract_d} status={result_d['run']['status']} kinds={sorted(kinds_d)}",
            rc_extract_d == 3 and result_d["run"]["status"] == "uncertain" and "no_text_layer" in kinds_d,
        )

        # ---------------------------------------------------------------- scenario E
        empty_json = os.path.join(work, "assertions-empty.json")
        write_json(empty_json, {"assertions": []})
        rc_build_e, _ = _quiet(
            build_nanopub.main,
            ["--case", case_json, "--document", doc_json, "--assertions", empty_json, "--out", os.path.join(work, "result-e.json")],
        )
        result_e = read_json(os.path.join(work, "result-e.json"))
        record(
            "E empty assertions",
            "status=refused build=5",
            f"status={result_e['run']['status']} build={rc_build_e}",
            result_e["run"]["status"] == "refused" and rc_build_e == 5,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)

    passed = sum(1 for r in results if r["pass"])
    print(f"{'SCENARIO':<22} {'RESULT':<7} DETAIL")
    for r in results:
        print(f"{r['scenario']:<22} {'PASS' if r['pass'] else 'FAIL':<7} {r['got']}")
    print()
    print(json.dumps({"scenarios": len(results), "passed": passed, "failed": len(results) - passed}, ensure_ascii=False))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
