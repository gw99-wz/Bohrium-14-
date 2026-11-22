---
name: nanopublication-reading
description: "Turn a paper's prose into checkable nanopublication-style assertions: split a paragraph into single falsifiable claims, bind each claim to the minimal sufficient evidence span with page and character locator, attach paper/author/year/version provenance, and export a schema-valid result.json plus an assertion-evidence table. Use when a task asks to read a paper and answer with evidence, to build a nanopublication, to verify whether a claim is supported by a source, to extract structured claims from a PDF, or to audit assertion-evidence alignment. Triggers on: nanopublication, assertion extraction, evidence binding, claim verification, 断言拆解, 证据绑定, 纳米出版, 结构化抽取, 阅读论文并给出依据."
---

# Nanopublication Reading

## What this skill does

It converts a paper into a **nanopublication-style knowledge unit**: a set of
single, falsifiable assertions, where each assertion carries its subject-relation-object,
a verbatim evidence span with a page and character locator, source provenance,
a confidence level with its basis, and stable identifiers.

The split of labour is deliberate:

- **You (the agent) do the semantic work** — decide what the claims are, how to
  split a compound sentence, which words form the minimal sufficient evidence, and
  what the relation between subject and object is.
- **The scripts do the mechanical work that cannot be argued with** — locate each
  quote in the source, compute page and code-point offsets, mint content-derived
  identifiers, run the quality checks, and refuse to mark anything "verified" that
  does not literally appear in the text.

Nothing in this skill invents a claim. If the material does not settle a question,
the output says so (`uncertainty[]`, `run.status = partial`), and if the input is
unusable it says that too (`run.status = refused`).

## When to use

Use it when the task is "read this paper and give me the claims with the evidence",
and the answer must be checkable by someone else. Typical triggers: nanopublication
construction, assertion-level summarisation, claim verification, evidence grounding,
literature QA with citations.

Do not use it to write a narrative review, to rank papers, or when no source
document is available — there is nothing to verify against.

## Pipeline

Four steps. Steps 1, 3 and 4 are scripts; step 2 is your reading.

```
scripts/extract_document.py   PDF  -> document.json     (canonical text + offsets)
      you                     document.json -> assertions.draft.json
scripts/resolve_quotes.py     optional: sentence ids -> literal quotes
scripts/build_nanopub.py      document + assertions -> result.json + qc.json + evidence.csv
scripts/validate_result.py    independent replay of every evidence span
```

### 1. Extract the document

```bash
python scripts/extract_document.py --input /input/paper.pdf --out /app/work/document.json \
  --title "..." --authors "A, B" --year 2017 --doi "..." --url "..."
```

Pass provenance you already know from the case; the extractor never guesses it.
Exit code `3` means **no usable text layer** (scanned PDF) — go to *Failure modes*.

Read `document.json`. Each page has `text`, and `blocks[]` with `block_id`,
`char_start`, `char_end`, and `sentences[]` whose `sentence_id` looks like
`p003-b015-s002` (page 3, block 15, sentence 2). Those ids are globally unique and
are what you cite in step 2 if you prefer ids over copied text.

### 2. Decompose into assertions (your job)

Write `assertions.draft.json`:

```json
{
  "assertions": [
    {
      "text": "One claim that can be true or false on its own.",
      "subject": {"label": "Transformer (big)", "entity_type": "model", "normalized": "transformer-big"},
      "relation": {"type": "outperforms"},
      "object": {"label": "previous best results on WMT 2014 English-to-German", "entity_type": "other"},
      "claim_count": 1,
      "conditions": ["WMT 2014 English-to-German", "newstest2014"],
      "scope": "one benchmark, one model size",
      "evidence": [
        {"sentence_ids": ["p001-b015-s004"], "evidence_type": "direct"},
        {"sentence_ids": ["p008-b011-s000"], "evidence_type": "tabular"}
      ],
      "confidence": {
        "level": "high",
        "basis": "Abstract gives the number; Table 2 attributes it to the big model, so two spans agree.",
        "derived_from": "multi_span_synthesis"
      }
    }
  ],
  "uncertainty": [
    {
      "kind": "ambiguous_subject",
      "description": "The abstract says 'our model' without naming the size; Table 2 is what fixes it.",
      "related_assertion_text": "One claim that can be true or false on its own.",
      "human_takeover": "Re-read Table 2 line 1 if the base model is the intended subject."
    }
  ]
}
```

Rules that make the output score well:

1. **One claim per assertion.** "X improves accuracy and lowers perplexity" is two
   assertions, each independently falsifiable. Put the number in `claim_count` only
   if you truly cannot split it; QC-01 will flag it.
2. **Keep conditions.** Benchmark, dataset, model size, temperature, sample size,
   training budget — anything that narrows the claim goes in `conditions[]`, not in
   the trash. A claim stripped of its conditions becomes over-broad and is flagged by
   QC-07.
3. **Evidence is the minimal sufficient span.** Quote the sentence (or the clause)
   that, read alone, supports the claim. Do not quote three paragraphs; do not
   paraphrase. If one clause supports two different claims, cite it twice — that is
   cheaper and more honest than one bundled claim.
4. **Relations come from the controlled vocabulary** (`references/relations.json`).
   If none fits, use the closest and record why in `notes`; QC-04 reports it rather
   than silently accepting a new label.
5. **Confidence needs a basis.** `high` means the sentence states it directly;
   `medium` means a table, figure or a second span is needed; `low` means inference.
   A confidence with no `basis` is downgraded to `low` by the builder.
6. **Declare what you could not settle.** Conflicts between abstract and body text,
   pronoun subjects, missing numbers — all belong in `uncertainty[]`, linked by the
   assertion text. Do not smooth them over.

### 3. Build the result

```bash
python scripts/resolve_quotes.py --document /app/work/document.json \
  --draft /app/work/assertions.draft.json --out /app/work/assertions.json

python scripts/build_nanopub.py --case /input/case.json \
  --document /app/work/document.json --assertions /app/work/assertions.json \
  --out /app/output/result.json --qc-out /app/output/qc.json --csv-out /app/output/evidence.csv
```

(`resolve_quotes.py` is optional: it expands `sentence_ids` into literal quotes. If
you already have literal quotes in `evidence[].quote`, skip it — the builder accepts
either, and always re-verifies the literal text.)

The builder:

- searches every quote in the page text (exact first, then whitespace-normalised),
  recording `char_start`/`char_end`, `block_id` and `sentence_ids`;
- mints `np:`, `asrt:`, `evd:`, `src:` identifiers from content hashes, so reruns of
  the same input produce the same ids;
- downgrades confidence when a span cannot be located, and records the reason;
- runs QC-01 … QC-09 and derives `run.status`.

Exit codes tell you the status without parsing JSON:
`0` success, `1` partial, `4` uncertain, `5` refused.

### 4. Validate independently

```bash
python scripts/validate_result.py --result /app/output/result.json --pdf /input/paper.pdf
```

This re-extracts the PDF from scratch and checks that every recorded
`(page, char_start, char_end)` slice equals its quote, that block/sentence locators
agree with the offsets, that ids are unique, that `run.counts` matches the content,
and that the file matches `schemas/result.schema.json`. `verdict: PASS` with
`failures: []` is the bar. Exit code `1` means something is wrong — fix it, do not
ship it.

## Output contract

`result.json` (schema: `schemas/result.schema.json`) is organised by the seven layers
the task demands, plus an envelope:

| Layer | Where | Content |
|-|-|-|
| 断言 | `nanopublication.assertions[].text` | one falsifiable claim, conditions preserved |
| 主体与关系 | `.subject`, `.relation`, `.object` | entity labels, controlled relation type, direction |
| 证据片段 | `.evidence[].quote` | verbatim, minimal sufficient span |
| 证据位置 | `.evidence[].locator` | page + code-point range + block/sentence ids |
| 来源元数据 | `source` | title, authors, year, venue, doi, document hash |
| 置信度依据 | `.confidence` | level + basis + how it was derived |
| 标识符 | `nanopublication.id`, `asrt:`, `evd:`, `src:` | content-derived, stable across reruns |

Envelope: `case_id`, `run.status`, `run.counts`, `run.limits`, `uncertainty[]`,
`quality_control`, `change_log`.

See `references/field-dictionary.md` for every field and its meaning.

## Status semantics

| status | meaning | when |
|-|-|-|
| `success` | every assertion has verified evidence | nothing unverified, no critical QC failure |
| `partial` | real output, declared gaps | some span unverified, evidence missing, or provenance incomplete |
| `uncertain` | material did not settle it | no text layer, or the question needs facts the document does not contain |
| `refused` | nothing asserted | input unreadable, or no assertion survived validation |

Never upgrade a status by hand. It is derived from the checks.

## Failure modes and what to do

| Situation | Detected by | Action |
|-|-|-|
| Scanned PDF, no text layer | extract exit `3`, `document.text_layer=false` | report `uncertain` with `no_text_layer`; OCR first, then rerun. Do not transcribe from memory. |
| Quote not found | `evidence[].verification.verified=false`, `evidence_not_found` | re-read the page, fix the quote, rerun. Never edit the source text to match the claim. |
| Claim needs several paragraphs | QC-01 warn, `claim_count>1` | split into several assertions sharing the evidence |
| Subject is a pronoun ("This improves …") | QC-05 warn | resolve the antecedent from the previous sentence and record it in `notes` |
| Two parts of the paper disagree | you declare `conflicting_statements` | quote both, keep both, let a human pick — do not reconcile silently |
| Number needed but not reported | `not_reported_in_source` | state it is not reported; do not compute or guess it |
| Relation outside vocabulary | QC-04 warn | map to the closest controlled relation, explain in `notes` |

## Limits (state these in your answer)

- Text extraction follows PyMuPDF's reading order. Two-column layouts and tables are
  usually right but not guaranteed; a table parsed as loose cells yields weak quotes —
  prefer the caption or the sentence that interprets the table.
- Sentence splitting is rule-based and conservative (English + Chinese punctuation).
  Abbreviations like "et al." and "Fig." are protected, but unusual notation can
  still merge or split a sentence.
- Character offsets are Unicode code points into `document.json`, not byte offsets and
  not PDF coordinates.
- The skill verifies that a quote **exists** and that it is **located**. It does not
  prove that the quote supports the claim — that judgement is yours, and QC-05/QC-07
  only flag the common ways it goes wrong.
- Quality checks are heuristics with a documented rationale (`references/qc-rules.md`),
  not a proof of correctness.

## Files

```
SKILL.md                          this file
schemas/result.schema.json        machine-readable output contract
references/field-dictionary.md    every field, type and meaning
references/controlled-vocabularies.md  relations, evidence types, statuses
references/relations.json         the relation vocabulary the builder loads
references/qc-rules.md            QC-01..QC-09, with reproducible criteria
docs/method.md                    why the design is shaped this way
docs/setup.md                     dependencies and versions
examples/minimal/                 one tiny input/output pair (an example, not a result)
tests/run_tests.py                five self-contained scenarios, including the degradations
```
