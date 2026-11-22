# Controlled vocabularies

Closed lists. A value outside them is reported (`in_vocabulary: false`, QC-04 warn)
rather than silently renamed — the point is that a downstream program can rely on the
set of values it may receive.

## Relations (`references/relations.json`)

Loaded by `build_nanopub.py --vocab`; edit that file to extend the list.

| type | 中文 | Use when |
|-|-|-|
| `reports` | 报告 | The sentence states/claims the object. Default for "the paper says X". |
| `measures` | 测量 | The subject quantifies the object (metric, quantity). |
| `achieves` | 达到 | The subject attains a stated performance or value. |
| `outperforms` | 优于 | The subject performs better than the object, on a stated metric and setting. |
| `improves_over` | 相对改善 | An improvement relative to the object, possibly partial. |
| `equals` | 等同 | Stated equivalence on the stated dimension. |
| `causes` | 导致 | The subject causes or produces the object. |
| `correlates_with` | 相关 | Co-variation only; no causal claim. |
| `predicts` | 预测 | The subject predicts the object. |
| `requires` | 需要 | The subject depends on / requires the object. |
| `uses` | 使用 | The subject uses or is built from the object. |
| `trained_on` | 训练于 | Trained on the object (dataset, corpus, split). |
| `evaluated_on` | 评测于 | Evaluated on the object (benchmark, split). |
| `composed_of` | 由…组成 | The subject is composed of the object. |
| `assumes` | 假设 | The subject presupposes the object as a condition. |
| `has_limitation` | 有局限 | The subject has the object as a limitation / failure mode. |
| `contradicts` | 相矛盾 | Incompatible with the object. |
| `derived_from` | 源自 | Derived from the object. |

**Direction.** `subject --relation--> object` must read as a sentence:
"Transformer (big) --outperforms--> previous best results". If your reading needs the
reverse, swap the entities rather than picking an approximate relation.

**Choosing between near-synonyms.** `outperforms` requires a stated comparison
("better than X") on the same metric and setting; `achieves` only needs the subject to
hit a value; `improves_over` is for a partial or qualified improvement. When in doubt,
`reports` is the honest fallback, with the specifics in `text`.

## Evidence types

| type | Use when |
|-|-|
| `direct` | The quote states the claim itself. |
| `indirect_inference` | The claim follows from the quote by one explicit step; say why in `confidence.basis`. |
| `tabular` | The quote is a table row or cell. |
| `figure_caption` | The quote is a figure or table caption. |
| `meta_claim` | The claim is about the paper itself (scope, availability, limitations). |

## Confidence levels

| level | Criterion |
|-|-|
| `high` | One sentence states it directly, or several spans agree. |
| `medium` | Needs a table/figure reading, a second span, or a small inference. |
| `low` | Agent judgement, pronoun resolution, or an unverified span. |

`derived_from` records *how* the level was reached: `direct_statement`,
`table_or_figure`, `multi_span_synthesis`, `inference`, `agent_judgement`.

## Run status

| status | Criterion (enforced by `build_nanopub.py`) |
|-|-|
| `success` | ≥1 assertion, all spans verified, no `fail` on QC-02/QC-08, provenance complete. |
| `partial` | Output produced, but a span is unverified, evidence is missing, or provenance is incomplete. |
| `uncertain` | `document.text_layer == false`, or the material cannot settle the question. |
| `refused` | No assertion survived validation. |

## Uncertainty kinds

| kind | Meaning |
|-|-|
| `not_reported_in_source` | The paper does not state the fact. Never fill by computation. |
| `conflicting_statements` | Two parts of the paper disagree; both are quoted, neither reconciled. |
| `evidence_not_found` | A declared quote is not in the extracted text. |
| `ambiguous_subject` | The antecedent (e.g. "our model", "this") is not pinned by the sentence. |
| `partial_page_coverage` | Only some pages were read. |
| `no_text_layer` | Scan or otherwise no machine-readable text. |
| `out_of_scope` | Deliberately not extracted in this run (declared, not omitted). |

## Entity types

`model`, `dataset`, `metric`, `phenomenon`, `method`, `organism`, `material`,
`quantity`, `system`, `other`.

Pick the type of the *thing named*, not of the sentence: "28.4 BLEU" is a `quantity`
when it is a value and a `metric` when it is the measure. Record the choice in the
entity's `identifiers` if it matters downstream.
