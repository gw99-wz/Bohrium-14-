# Setup and usage

## Requirements

| Piece | Version used | Notes |
|-|-|-|
| Python | 3.10+ (tested 3.15.0) | uses `str \| None` annotations |
| PyMuPDF (`pymupdf`) | 1.28.2 (tested) | PDF text + block/sentence layout; `import pymupdf` with a fallback to `import fitz` |
| `jsonschema` | 4.26.0 (tested) | Draft 2020-12 validation in `validate_result.py` |

```bash
pip install "pymupdf>=1.24" "jsonschema>=4.18"
```

No network access is needed at run time. No model API is called by the scripts.

## Install as a skill

Copy this directory to the skill root the harness expects (the platform mounts it as
`/skills/weekly-skill`), keeping the layout:

```
SKILL.md  schemas/  references/  scripts/  docs/  examples/  tests/
```

Scripts resolve their data files relative to their own location
(`scripts/../references/relations.json`, `scripts/../schemas/result.schema.json`), so
the directory can live anywhere. Run them from the skill directory or pass absolute
paths.

## One complete run

```bash
# 0. where you are
SKILL_DIR=/skills/weekly-skill          # or the checkout path

# 1. extract
python "$SKILL_DIR/scripts/extract_document.py" \
  --input /input/paper.pdf --out /app/work/document.json \
  --title "Paper title" --authors "A. Author, B. Author" --year 2017 \
  --doi "10.xxxx/yyyy" --url "https://..."

# 2. read /app/work/document.json, write /app/work/assertions.draft.json
#    (this is the agent's semantic step; see SKILL.md step 2)

# 3. expand sentence ids into quotes (optional)
python "$SKILL_DIR/scripts/resolve_quotes.py" \
  --document /app/work/document.json \
  --draft /app/work/assertions.draft.json --out /app/work/assertions.json

# 4. build the structured result
python "$SKILL_DIR/scripts/build_nanopub.py" \
  --case /input/case.json \
  --document /app/work/document.json \
  --assertions /app/work/assertions.json \
  --out /app/output/result.json \
  --qc-out /app/output/qc.json \
  --csv-out /app/output/evidence.csv

# 5. independent check
python "$SKILL_DIR/scripts/validate_result.py" \
  --result /app/output/result.json --pdf /input/paper.pdf
```

`case.json` is optional for the builder (`--case` may be omitted, in which case
`case_id` falls back to the document filename), but supply it: it carries the id and
`output_contract` the result must echo back.

## Exit codes

| script | code | meaning |
|-|-|-|
| `extract_document.py` | 0 | text layer present |
| | 3 | extracted but no usable text (scan) — degrade, do not invent |
| | 2 | unreadable input |
| `build_nanopub.py` | 0 / 1 / 4 / 5 | `success` / `partial` / `uncertain` / `refused` |
| `validate_result.py` | 0 | all checks pass |
| | 1 | at least one failure |
| `resolve_quotes.py` | 1 | unknown or non-unique `sentence_id` |

## Self-test

```bash
python tests/run_tests.py
```

Five scenarios, all run in-process against PDFs the suite generates: clean run,
corrupted quote, missing evidence, no text layer, empty assertions. Exit code 0 only
if all five behave as specified.

The suite works under `.test-work/` inside the repository rather than the system temp
directory: some file sandboxes allow creating a directory in temp but refuse writing
files into it, and `tempfile.mkdtemp` produces directories that may inherit a
restrictive ACL.

## Files it writes

| file | content |
|-|-|
| `document.json` | canonical text, blocks, sentences, offsets, input hash |
| `assertions.json` | your assertions with literal quotes |
| `result.json` | the deliverable, schema-valid |
| `qc.json` | QC-01…QC-09 verdicts + uncertainty, without the bulk |
| `evidence.csv` | one row per assertion-evidence pair, for spreadsheet review |

## Troubleshooting

| Symptom | Cause | Fix |
|-|-|-|
| `extract` exit 3, `text_layer: false` | scanned PDF | OCR first; report `uncertain` meanwhile |
| `QC-03` warn on a table claim | table read as loose cells | cite the caption or the interpreting sentence instead |
| `QC-05` warn | pronoun subject ("This improves …") | resolve antecedent, add `notes` |
| `resolve_quotes` says ids not unique | document.json from an older version | re-extract |
| `validate_result` `evidence-replay` fail | quote edited after building | rebuild from `assertions.json`; never patch `result.json` by hand |
| `jsonschema` missing | dependency not installed | `pip install jsonschema` |
