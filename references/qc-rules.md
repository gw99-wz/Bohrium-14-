# Quality-control rules

Nine checks, run by `build_nanopub.py` on every build. Each rule states its criterion
so a reviewer — or a competing implementation — can reproduce the verdict. Rules are
heuristics: `warn` means "a human should look", `fail` means "this is a defect".

| id | result affects status | criterion |
|-|-|-|
| QC-01 | no (warn) | atomicity |
| QC-02 | **yes** | evidence present |
| QC-03 | yes | evidence verified |
| QC-04 | no | relation in vocabulary |
| QC-05 | no | subject appears in its evidence |
| QC-06 | yes (via `source.missing_fields`) | provenance complete |
| QC-07 | no | over-broad wording |
| QC-08 | **yes** | locator precision |
| QC-09 | no | duplicates |

---

## QC-01-atomicity — 拆得细

**Criterion.** An assertion is flagged when any of:

- `atomicity.claim_count > 1`, or
- `len(text) > 320` characters, or
- the statement splits into more than one sentence under the same conservative
  splitter used for the source (`docmodel.split_sentences`), so decimal points
  ("28.4"), abbreviations ("et al.") and version numbers do not count as endings.

**Why the length cap.** A 320-character "claim" cannot normally be judged true or
false as a unit; in practice it bundles two or more assertions. The cap is generous
on purpose — it is a warning, not a gate.

**What to do.** Split into several assertions that share the same evidence span.
Sharing a span is cheap and correct; bundling is what the task penalises.

**Known false negatives.** Two claims joined by "and" inside one sentence with one
terminal period pass this rule. Only the semantic reading catches those, which is why
the rule is a `warn`.

## QC-02-evidence-present

**Criterion.** `fail` when any assertion has `evidence == []`.

**What to do.** Either find the supporting sentence, or drop the assertion and record
a `not_reported_in_source` uncertainty. An unsupported claim must not be shipped with
a fabricated citation.

## QC-03-evidence-verified

**Criterion.** For each assertion, look at its spans:

- `pass` — every span verified;
- `warn` — at least one span verified and at least one not;
- `fail` — spans exist but none verified, or there are none.

A span is verified when `docmodel.locate_quote` finds it in the page text, either
byte-exact (`exact_substring`) or after collapsing whitespace runs
(`whitespace_normalized`). The method is recorded so a reviewer knows how strict the
match was.

**What to do.** Re-read the page. The usual causes are a paraphrase instead of a
quote, a span that crosses a page break, or a table read as loose cells.

## QC-04-relation-vocabulary

**Criterion.** `relation.type` must be a key of `references/relations.json`.
Otherwise `in_vocabulary: false` and the rule warns.

**Why not fail.** An honest new relation is better than a wrong existing one; the
warning makes it visible without blocking the submission. If you add a relation, add
it to `relations.json` and bump `vocabulary` so downstream programs can see it.

## QC-05-subject-in-evidence

**Criterion.** The subject's `label` (lowercased) must occur literally in at least one
of the assertion's quotes. Otherwise warn.

**What it catches.** The most common evidence-alignment error: the quote says "our
model" or "This improves …", and the assertion silently attributes it to a specific
model. That is a real subject-confusion risk, so it is worth a warning — but it is
often legitimate, because a pronoun is the paper's own way of naming the subject.

**What to do.** Resolve the antecedent explicitly and write it in `notes`. If the
antecedent is genuinely unclear, declare `ambiguous_subject` instead of guessing.

## QC-06-provenance-complete

**Criterion.** `title`, `authors` and `year` must all be present; the missing ones are
listed in `source.missing_fields`. A non-empty list forces `status = partial`.

**Why it matters.** Without provenance an assertion cannot be traced back, which is
one of the four things the task scores. Values are only taken from the case or the
document metadata — never inferred from context.

## QC-07-overbroad-language

**Criterion.** The assertion text matches an absolute marker — `all`, `every`,
`always`, `never`, `proves`, `universally`, `entirely`, `completely`, `only`
(English), or 总是／所有／必然／完全／始终 (Chinese) — **and** `conditions_kept` is empty.

**Why.** Absolute wording without a recorded condition is the signature of an
over-broad claim. The fix is usually to put the condition back, not to soften the
word: "the Transformer beats all previously published models **on WMT 2014 EN-DE
newstest2014, single model**" is defensible; "the Transformer beats all models" is not.

## QC-08-locator-precision

**Criterion.** For every verified span, `char_end > char_start` and `page >= 1` must
hold. Empty or inverted ranges fail.

**Why a fail, not a warn.** A span whose range does not contain its quote cannot be
replayed; it breaks the "traceable" property outright. This is the rule that turns a
pretty JSON into a checkable one.

## QC-09-duplicates

**Criterion.** Compare assertion texts after lowercasing and collapsing whitespace; a
second occurrence warns, and the ids of the later duplicates are listed.

**Why.** Duplicates usually mean two sentences of the paper say the same thing and the
agent recorded both. Keep one, and mention the second location in `notes`.

---

## Checks performed by `validate_result.py` (independent of the above)

These are not QC rules; they are acceptance tests that must pass before shipping:

| check | criterion |
|-|-|
| `schema` | file validates against `schemas/result.schema.json` |
| `unique-assertion-ids` | no duplicated `assertion_id` |
| `declared-counts-match-content` | `run.counts` equals what the assertions actually contain |
| `status-consistent` | `status=success` implies zero unverified spans |
| `locator-metadata-consistent` | `block_id`/`sentence_ids` exist on the recorded page **and** physically overlap the recorded character range |
| `evidence-replay` | re-extracting the source reproduces `page_text[char_start:char_end] == quote` |
| `provenance-anchored` | `source_id` and the document `sha256` are present |

`locator-metadata-consistent` exists because of a real failure found during
development: a page-local sentence id scheme made every page contain `p015s002`, so
evidence was silently bound to the wrong page while remaining self-consistent. Offsets
alone did not catch it; cross-checking the human-navigable locator against the offsets
did.
