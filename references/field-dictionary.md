# Field dictionary

Every field in `result.json`. Types are JSON types; `?` marks an optional field.
Identifiers are content-derived: the same input yields the same id, so a rerun is
diffable and two runs can be compared without guessing what changed.

## Envelope

| Field | Type | Meaning |
|-|-|-|
| `schema_version` | string | Always `nanopub-reading-result/1.0`. |
| `case_id` | string | The case this run answered. Echoed from `case.json`, never invented. |
| `task.instruction` | string | The instruction the run was given. |
| `task.question` | string | The question, when the case poses one. |
| `task.output_contract_fields` | string[] | Field names found in the case's `output_contract`. |
| `task.materials` | string[] | Files the case supplied. |

## `run` — how the run went

| Field | Type | Meaning |
|-|-|-|
| `run.status` | enum | `success` \| `partial` \| `uncertain` \| `refused`. Derived from the checks, never set by hand. |
| `run.status_reason` | string | Why that status, in one sentence, naming the counts that decided it. |
| `run.pipeline_version` | string | Version of these scripts. |
| `run.started_at`, `run.finished_at` | ISO-8601 string | Wall-clock bounds of the build. |
| `run.inputs[]` | object[] | Each input actually used: `path`, `sha256`, `kind`, `bytes`. |
| `run.counts` | object | `assertions`, `evidence_spans`, `verified_spans`, `unverified_spans`. |
| `run.limits.pages_read` | integer[] | Pages that were searched. |
| `run.limits.pages_skipped` | integer[] | Pages deliberately not searched (empty when the whole document was read). |
| `run.limits.notes` | string[] | Machine-readable caveats (offset convention, coverage). |

## `source` — 来源元数据

| Field | Type | Meaning |
|-|-|-|
| `source.source_id` | string | `src:` + 16 hex of the document sha256. The join key every assertion points at. |
| `source.title` | string? | From the case if supplied, else PDF metadata, else `null`. |
| `source.authors` | string[] | Same precedence. Empty when unknown — never guessed. |
| `source.year` | integer? | Publication year. |
| `source.venue` | string? | Journal / conference. |
| `source.version` | string? | Version or revision identifier, when the case names one. |
| `source.doi`, `source.url` | string? | Persistent identifiers. |
| `source.document.path` | string | The file that was read. |
| `source.document.sha256` | string | Hash of that file; pins the exact bytes behind every quote. |
| `source.document.pages` | integer | Page count of the document. |
| `source.document.text_layer` | boolean | `false` means the PDF had no usable text (scan). |
| `source.document.extractor` | string | `pymupdf` or `plain-text`. |
| `source.missing_fields` | string[] | Provenance fields the material did not provide. A non-empty list forces `status=partial`. |

## `nanopublication` — 断言集合

| Field | Type | Meaning |
|-|-|-|
| `nanopublication.id` | string | `np:` + 16 hex over schema version, source id and all assertion ids. Changes if any assertion changes. |
| `nanopublication.created_at` | string | Build time. |
| `nanopublication.generator` | string | Pipeline that produced it. |
| `nanopublication.assertions[]` | object[] | The assertions, in reading order. |

### Each assertion

| Field | Type | Meaning |
|-|-|-|
| `assertion_id` | string | `asrt:` + 16 hex over `source_id` and the assertion text. |
| `text` | string | 断言 — one claim that can be true or false on its own. Conditions live in `conditions[]`, not in subordinate clauses. |
| `atomicity.claim_count` | integer | Claims bundled in `text`. Should be 1. |
| `atomicity.conditions_kept` | string[] | Benchmark, dataset, model size, budget — the qualifiers that make the claim checkable. |
| `atomicity.scope` | string? | Free-text scope of the claim. |
| `subject.label` | string | 主体 — the entity doing the asserting, as named in the paper. |
| `subject.entity_type` | enum | `model`\|`dataset`\|`metric`\|`phenomenon`\|`method`\|`organism`\|`material`\|`quantity`\|`system`\|`other`. |
| `subject.normalized` | string? | Canonical slug, for cross-paper joins. |
| `subject.identifiers` | object | External ids (DOI, PDB, UniProt, HF model id …). |
| `relation.type` | string | 关系 — controlled type from `references/relations.json`. |
| `relation.vocabulary` | string | Vocabulary version used. |
| `relation.in_vocabulary` | boolean | `false` flags an out-of-vocabulary relation (QC-04). |
| `object.label` | string | The entity the claim is about; direction matters. |
| `object.entity_type`, `object.normalized`, `object.identifiers` | as above | Same semantics as the subject. |
| `evidence[]` | object[] | 证据片段 + 证据位置; may be empty only for an assertion QC-02 will fail. |
| `confidence.level` | enum | 置信度 — `high` \| `medium` \| `low`. |
| `confidence.basis` | string | 依据 — why that level. Missing basis is downgraded to `low`. |
| `confidence.derived_from` | enum | `direct_statement`\|`table_or_figure`\|`multi_span_synthesis`\|`inference`\|`agent_judgement`. |
| `provenance.source_id` | string | 标识符链 — back-pointer to `source`. |
| `provenance.paper_ref` | string? | Human-readable citation of the same source. |
| `notes` | string? | Caveats, e.g. a resolved pronoun. |

### Each evidence span

| Field | Type | Meaning |
|-|-|-|
| `evidence_id` | string | `evd:` + 16 hex over assertion id, quote and page. |
| `quote` | string | 证据片段 — copied verbatim from the source, minimal but sufficient on its own. |
| `locator.page` | integer | 证据位置 — 1-based page number. |
| `locator.char_start`, `locator.char_end` | integer | Unicode code-point range inside that page's text. `page_text[char_start:char_end] == quote`. |
| `locator.block_id` | string? | Paragraph id, e.g. `b015`. |
| `locator.sentence_ids` | string[] | Sentence ids overlapping the span, e.g. `p001-b015-s004`. |
| `locator.section` | string? | Section heading, when the agent supplies it. |
| `locator.figure_or_table` | string? | `Table 2`, `Figure 3` for tabular or caption evidence. |
| `evidence_type` | enum | `direct`\|`indirect_inference`\|`tabular`\|`figure_caption`\|`meta_claim`. |
| `verification.verified` | boolean | Did the quote exist in the page text? |
| `verification.method` | enum | `exact_substring`\|`whitespace_normalized`\|`reported_not_found`\|`unchecked`. |
| `verification.detail` | string | What went wrong, when it did. |

## `uncertainty` — 边界与不确定

| Field | Type | Meaning |
|-|-|-|
| `item_id` | string | `unc:` + 12 hex. |
| `kind` | enum | `not_reported_in_source`\|`conflicting_statements`\|`evidence_not_found`\|`ambiguous_subject`\|`partial_page_coverage`\|`no_text_layer`\|`out_of_scope`. |
| `description` | string | What is unsettled and why. |
| `related_assertion_id` | string? | The assertion it bears on. |
| `related_locator` | object? | Where a human should look. |
| `human_takeover` | string? | The concrete next step for a person. |

## `quality_control`

| Field | Type | Meaning |
|-|-|-|
| `ruleset_version` | string | `qc/1.0`. |
| `checks[].rule_id` | string | `QC-01-atomicity` … `QC-09-duplicates`. |
| `checks[].result` | enum | `pass`\|`warn`\|`fail`\|`not_applicable`. |
| `checks[].detail` | string | Counts and what they mean. |
| `checks[].assertion_ids` | string[] | Which assertions the verdict is about. |
| `summary` | object | `pass` / `warn` / `fail` counts. |

## `change_log`

| Field | Type | Meaning |
|-|-|-|
| `at` | string | When. |
| `change` | string | What changed (e.g. "downgraded confidence of asrt:… from high to medium"). |
| `reason` | string | Why. |

The log exists so an edited artifact can be audited: it records pipeline-side
corrections (confidence downgrades, dropped inputs) rather than hiding them.
