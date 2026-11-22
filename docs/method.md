# Method

## The four problems, and where each is answered

The task names four failure modes. Each maps to a specific mechanism here — not to a
prompt sentence asking an agent to "be careful".

| Problem | Mechanism | Failure it prevents |
|-|-|-|
| 拆得细 (grain) | One assertion per claim; `claim_count`, `conditions[]`; QC-01 flags bundled or absolute claims | A whole paragraph stuffed into one "assertion" field |
| 对得上 (alignment) | `locate_quote` finds the literal span; `page_text[char_start:char_end] == quote` is enforced twice (build + validate) | Evidence that is plausible but not actually in the text |
| 追得回 (provenance) | `src:` id from the document hash, `evd:`/`asrt:`/`np:` derived from content, page + block + sentence locators | A claim nobody can walk back to a page |
| 读得懂 (machine-readable) | JSON Schema with `additionalProperties: false`; closed vocabularies; fixed status enum | Structure that needs hand-cleaning before use |

## Why the agent/script split is where it is

Semantic judgement — is this one claim or two, is this relation `outperforms` or
`achieves`, is this span sufficient — is what language models are good at and what
regexes are bad at. Mechanical bookkeeping — offsets, ids, schema, replay — is what
scripts are good at and what models are unreliable at. Splitting the work along that
line is what makes the output both flexible and auditable.

A fully deterministic extractor would produce low-quality assertions (a sentence
splitter is not a semantic parser). A fully agentic pipeline would produce
unauditable ones (no offsets, no ids, no replay). The boundary is drawn at
"verifiable or not verifiable", not at "easy or hard".

## Assertion grain: the working criteria

An assertion is at the right grain when:

1. **One truth value.** Negating it negates exactly one thing. "X improves BLEU and
   lowers perplexity" fails: BLEU up with perplexity down are two facts.
2. **Standalone truth-apt.** It can be checked without the surrounding paragraph,
   which means the subject cannot be a pronoun and the conditions cannot be implicit.
3. **Conditions travel with it.** Benchmark, dataset split, model size, sample size,
   training budget belong in `conditions[]`. Stripping them is how a correct sentence
   becomes an incorrect claim.
4. **Metrically specific.** Prefer "28.4 BLEU on WMT 2014 EN-DE newstest2014" to
   "strong results". A number that is in the paper stays in the assertion.

## Evidence: minimal sufficiency

The span must satisfy both:

- **Sufficient** — read alone, without the next sentence, it supports the claim.
  If it needs a table elsewhere, cite the table as a second span rather than
  stretching the first.
- **Minimal** — it does not also support three other claims. Quoting a whole
  paragraph satisfies "sufficient" trivially and defeats the point: a reviewer cannot
  tell which words do the work.

When two assertions share a clause ("This hurts perplexity, … but improves accuracy
and BLEU"), the clause is cited twice. Duplicating a span is free; bundling two claims
is what costs points.

## Identifiers: content-derived, not counters

```
src:  sha256(document bytes)[:16]
asrt: sha256(source_id, assertion_text)[:16]
evd:  sha256(assertion_id, quote, page)[:16]
np:   sha256(schema_version, source_id, all assertion ids)[:16]
```

Consequences that matter operationally:

- A rerun on unchanged input reproduces every id, so diffs show only real changes.
- Editing an assertion changes `asrt:` and therefore `np:` — the nanopublication id is
  a commitment to the exact set of claims.
- Two independent runs can be joined on `asrt:` without a registry.

## Status derivation, and why it is not cosmetic

`status` is computed from counts and checks, never set by the producer:

```
no assertions                  -> refused
text_layer == false            -> uncertain
QC-02/QC-08 fail, or any
  unverified span, or missing
  provenance                   -> partial
otherwise                      -> success
```

The ordering encodes the epistemic rule the task asks for: **uncertainty outranks
optimism**. A run that produced excellent assertions from a document it could not read
is `uncertain`, not `success`. Because `validate_result.py` independently re-checks
`status=success ⇒ 0 unverified spans`, a dishonest status is caught by the validator
rather than trusted.

## Conflict handling

The pipeline never reconciles two statements. If §6.3 says 41.0 and the abstract and
Table 2 say 41.8, both are quoted, both assertions are emitted, the confidence of the
prose one drops to `medium`, and a `conflicting_statements` uncertainty records the
disagreement with both numbers. A human picks; the machine does not silently average
or prefer.

## What is actually new here

Not nanopublication serialisation — that is a solved format. What is different:

1. **Replay is a first-class check, not a claim.** The validator re-extracts the PDF
   and re-slices every span; `PASS` means the offsets reproduce, not that the producer
   said so.
2. **Degradation is specified per defect.** No text layer, missing quote, unresolved
   pronoun, absent number — each has a named status and a named uncertainty kind, so
   a downstream consumer can branch on the defect instead of on free text.
3. **Locator cross-check.** Human-navigable locators (`block_id`, `sentence_ids`) are
   validated against machine offsets. This caught a real cross-page mis-binding in
   development that offsets alone could not see (`references/qc-rules.md`).
4. **Content-derived identity for nanopublications.** The `np:` id commits to the exact
   assertion set, which is what makes "has this claim set changed?" a hash comparison
   instead of a diff review.

## Deliberate limits

- Support is judged by the agent. Verification proves a quote exists and is located,
  not that it entails the claim. QC-05/QC-07 catch the two commonest ways that goes
  wrong; nothing catches the rest.
- Sentence splitting is rule-based, English+Chinese, conservative by design.
- Reading order is PyMuPDF's; complex tables and multi-column figures degrade.
- No cross-document deduplication in this version: the same claim in two papers
  yields two assertions with different `src:` ids. The `asrt:` scheme is the hook for
  adding it.
