# Minimal example — 示例，非正式结果

> **This is a worked example, not a case result.** The input text is synthetic and
> explicitly states that its numbers are invented. The output here exists to show the
> interface end to end; it must not be read as an answer to any real case.

## Input

| file | what it is |
|-|-|
| `paper.txt` | 887-character synthetic text, one page, with a standing disclaimer |
| `case.json` | a minimal `case.json` with `case_id` and `output_contract` |
| `assertions.draft.json` | five assertions authored by reading `document.json`, plus two declared uncertainties |

## Reproduce

```bash
S=scripts
python $S/extract_document.py --input examples/minimal/paper.txt --out examples/minimal/document.json
python $S/resolve_quotes.py --document examples/minimal/document.json \
    --draft examples/minimal/assertions.draft.json --out examples/minimal/assertions.json
python $S/build_nanopub.py --case examples/minimal/case.json \
    --document examples/minimal/document.json --assertions examples/minimal/assertions.json \
    --out examples/minimal/result.json --qc-out examples/minimal/qc.json \
    --csv-out examples/minimal/evidence.csv
python $S/validate_result.py --result examples/minimal/result.json \
    --document examples/minimal/document.json
```

Expected: build exits `0` with `status=success`, 5 assertions, 5/5 spans verified;
validate prints `"verdict": "PASS"`.

## Generated files (shown so the shape is inspectable)

| file | what to look at |
|-|-|
| `document.json` | page text plus `blocks[]` / `sentences[]` with page-scoped ids (`p001-b002-s001`) and code-point offsets |
| `result.json` | the seven layers in one object: assertion, subject/relation/object, evidence quote, locator, `source`, `confidence`, identifiers |
| `qc.json` | QC-01…QC-09 verdicts and the two declared uncertainties |
| `evidence.csv` | one row per assertion-evidence pair |

## What the example is meant to show

1. **Grain.** The claim "PruneFormer is 1.1 BLEU below the baseline" is emitted with the
   baseline as *subject* and `outperforms` as the relation, so the direction reads
   correctly; the note records why the entities were swapped relative to the source
   sentence.
2. **Honest absence.** The baseline's absolute BLEU is never reported in the input, so a
   `not_reported_in_source` uncertainty is recorded instead of a computed number.
3. **Declared scope.** "No significance claimed" appears as `out_of_scope`, so a reviewer
   can see the omission was deliberate.
4. **Known warning.** QC-05 warns on some assertions because the source names
   "PruneFormer" while other spans say "the pruning"; that warning is the rule working
   as intended.
