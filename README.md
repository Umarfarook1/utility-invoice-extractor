# Utility invoice extraction with an LLM

Ten real utility bills (electricity, gas, water) from 8 countries in 6 languages, turned into one clean CSV
by an LLM. Then every extracted value is checked by plain code against the text it was read from, and given
a computed confidence and a review flag.

**Walkthrough site: https://utility-invoice-extractor.vercel.app** (pick an invoice, hover a value: its quote
lights up in the text the model read, in the original language)

**Outputs:** [`output/invoices.csv`](output/invoices.csv) · audit trail [`output/extractions.jsonl`](output/extractions.jsonl) · [`output/eval_report.md`](output/eval_report.md)

## Results

| | |
|---|---|
| Input | 10 real specimen bills: US, UK, Germany, France, Italy, Brazil, Belgium, Australia ([sources](samples/SOURCES.md)) |
| Languages | English, German, French, Italian, Portuguese, Dutch |
| Output | 15 CSV rows: one per (invoice, utility service); 4 bills carry two or three utilities |
| Field accuracy | **116 / 120 (96.7%)** of the eight required fields, against hand labels |
| Misses | 4: three dates on one PDF whose text layer hides a second bill (see below), one usage value that was flagged for review |
| Tests | 75 offline tests, under 2 s, no API key needed |
| LLM | one call per invoice, about 12k tokens, Google Gemini Flash on the free tier |

## Why it is built this way

These numbers become Scope 1 (gas) and Scope 2 (electricity) activity data, so a value that cannot be traced
back to the bill is a liability. Three decisions follow from that:

1. **Quote, then verify.** The model returns every field as `(value, source_text, page)`. Code then checks
   that the quote really is in the document. A value whose quote is not there is treated as invented.
2. **Confidence is computed, not self-reported.** LLM self-confidence is poorly calibrated. Each field starts
   at 1.0 and loses weight for every independent check it fails (grounding, a locale-aware re-parse of the
   quote, business rules). A row is as trustworthy as its weakest required field.
3. **Null beats a guess.** Missing fields stay empty and go to review. A plausible invented address or date
   silently corrupts an inventory; an empty one gets fixed.

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 1. Replay the committed run offline: no API key needed, answers come from cache/
python -m invoice_extractor --offline

# 2. Or run live (uses the cache, calls the API only for new or changed documents)
cp .env.example .env                                  # then set GEMINI_API_KEY (free at aistudio.google.com)
python -m invoice_extractor samples/invoices
python -m invoice_extractor bill.pdf --provider openai --model gpt-5-mini   # OPENAI_API_KEY instead

# 3. Score against the hand-labelled ground truth, and run the tests
python -m eval.evaluate
python -m pytest -q
```

Any PDF, TXT or MD file works as input: `python -m invoice_extractor path/to/bill.pdf other/folder`.

## Output

One row per **(invoice, utility service)**: a dual-fuel bill produces two rows sharing the invoice fields.

| column | meaning |
|---|---|
| `vendor_name` | utility that issued the bill, as printed |
| `invoice_date` | issue date, ISO 8601 |
| `service_address` | where the utility is delivered; empty if not printed |
| `utility_type` | `electricity`, `gas` or `water` |
| `usage_amount`, `usage_unit` | consumption billed for the period; unit canonicalized (`kWh`, `m3`, `therms`, `CCF`, `ML`...) |
| `billing_period_start`, `billing_period_end` | consumption period, ISO 8601 |
| `usage_standardized`, `usage_standardized_unit` | usage in kWh (energy) or m3 (water) when the conversion is a fixed factor |
| `source_file`, `invoice_number`, `total_amount`, `currency` | context for reconciliation |
| `language`, `country` | ISO 639-1 / ISO 3166-1 |
| `confidence` | 0 to 1, computed from the checks below |
| `needs_review`, `review_reasons` | flag plus machine-readable reasons, e.g. `usage_amount:quote_not_in_document` |
| `notes`, `model` | the model's notes on ambiguities, and which model answered |

`extractions.jsonl` keeps everything behind each row: the verbatim quote and page for every field, the result
of each check, token counts.

## Architecture

```
 PDF/TXT ─► ingest ─► detect language ─► LLM extraction ────────► ground ─► re-parse ─► validate ─► score ─► CSV
           text layer  local, second      strict JSON schema,      quote in   locale-     business    field     + JSONL
           per page    opinion            value + quote + page     document?  aware       rules       confidence  audit
                                          model ladder, cached
```

| file | job |
|---|---|
| [`ingest.py`](invoice_extractor/ingest.py) | PDF text layer into page-tagged text; layout mode only when it is complete |
| [`language.py`](invoice_extractor/language.py) | local language detection, an independent second opinion |
| [`schema.py`](invoice_extractor/schema.py) | the contract with the model; field descriptions are prompt text |
| [`prompts.py`](invoice_extractor/prompts.py) | system prompt: field definitions, multilingual and "never guess" rules |
| [`llm.py`](invoice_extractor/llm.py) | Gemini and OpenAI behind one interface, model fallback ladder, content-addressed cache |
| [`normalize.py`](invoice_extractor/normalize.py) | locale rules, number and date re-parsing, unit canonicalization and conversion |
| [`verify.py`](invoice_extractor/verify.py) | grounding, validation rules, confidence scoring |
| [`pipeline.py`](invoice_extractor/pipeline.py) | wires it together, one row per service |
| [`eval/evaluate.py`](eval/evaluate.py) | field-level accuracy against hand labels |
| [`web/`](web/) | the static walkthrough site, built from the outputs (`python web/build.py`) |

## How the LLM is used

- **One call per document.** Bills fit comfortably in context; chunking would separate labels from values.
- **Structured output with a JSON schema** generated from Pydantic models, so the reply always parses. Field
  descriptions live in the schema, next to the field they describe.
- **Every field is `(value, source_text, page)`.** The quote is what makes hallucination detectable.
- **The prompt defines the domain, not just the format:** issue date vs due date vs reading date; service
  address vs mailing address; one service per utility (sewer is part of water, dual fuel is two services);
  usage is the billed consumption, never a meter reading or an average; specimen-bill callouts are ignored.
- **The file name is never sent.** Names like `us_en_electricity_pge.pdf` would leak the answer.
- **A model ladder, not a single model.** The free tier allows 20 requests per model per day and new models
  are often overloaded, so the extractor falls through `gemini-3.6-flash`, `3.5-flash`, `3.8-flash`,
  `3.7-flash`, `3.5-flash-lite` on quota or overload errors. A daily quota fails fast instead of retrying,
  and a circuit breaker skips an exhausted model for the rest of the run. Every row records which model
  answered: 6 invoices came from 3.6-flash, 3 from 3.5-flash, 1 from 3.5-flash-lite.
- **Cache:** answers are keyed by a hash of model + system prompt + schema + document text, so any prompt edit
  invalidates stale answers automatically, re-runs are free, and the committed `cache/` replays this exact
  run without a key.
- **Data note:** the free tier is fine here because the inputs are public specimen bills. Customer bills would
  need a paid tier with no-training terms.

## Multilingual handling

1. **Extract in the original language.** No translate-first step: translation costs a second call and corrupts
   exactly the tokens that matter (dates, decimal separators, units, names).
2. **Normalize into language-neutral forms:** ISO dates, dot-decimal numbers, canonical units, an English enum
   for the utility type. Vendor names stay as printed.
3. **Keep the quote verbatim** in its own language and script, for the audit trail.
4. **Re-parse the quote with the bill's locale** and compare with the model's value. `date_order()` and
   `uses_decimal_comma()` map country and language to conventions: 03/04 is April 3 in France and March 4 in
   the US; `12.853 kWh` is twelve thousand in Germany; `3 163 kWh` uses a space in France; Japanese era dates
   (令和6年 = 2024) are converted. Disagreement lowers confidence and flags the row.
5. **Detect the language twice.** A local detector (`langdetect`) and the model each report the language.

## Assumptions

- **"Real invoices" = specimen bills published by real utilities** for customer education. They are real
  documents in the utilities' production layouts, printed with sample customer data, so they carry no one's
  personal information. Sources, URLs and retrieval dates are in [`samples/SOURCES.md`](samples/SOURCES.md).
- **Text is available**, as the brief allows: PDFs are read from their text layer; scans are rejected with a
  clear error rather than OCR'd.
- **Usage = the consumption the charges are calculated on**, for the bill's period. Tiers, time-of-use bands
  and meters of one utility are summed. Where gas is printed in m³ and kWh, the billed quantity wins.
- **One row per utility service**, because one row per invoice breaks on dual-fuel bills.
- **Service address over mailing address**; **invoice date = issue date**, not due date or reading date.
- **Gas volume is not converted to kWh.** That needs the calorific value printed on each bill; a default
  factor would be a silent guess, so `usage_standardized` stays empty.
- Column names are lower snake case (`billing_period_start`, not the brief's `Billing_period_start`).

## Testing approach

**How accuracy was validated.** Every invoice was labelled by hand from the original PDF (rendered pages plus
the text layer), without looking at pipeline output, in [`ground_truth/labels.json`](ground_truth/labels.json).
Each value carries page + verbatim evidence, and each judgement call is written down (for example: Eneco's
"Totaal verbruik" is a euro amount, so usage is empty; Enel Italy's annual consumption is not the period's
usage). `python -m eval.evaluate` scores the eight required fields per service row: dates exactly, usage
within rounding, units after canonicalization, vendor against accepted names, address by word overlap with
every number matching exactly. **An empty field counts as correct only when the bill really does not print
it**, so abstaining is rewarded and inventing is punished.

**Result: 116 / 120 fields (96.7%).** The four misses, all listed in [`output/eval_report.md`](output/eval_report.md):

- **Three dates on invoice 08, not flagged.** That PDF holds two bills: the visible page is an Enel Ceará bill,
  and hidden under white boxes the text layer also carries an older Enel Goiás bill. The model returned the
  hidden bill's dates. Each quote really is in the text layer, so grounding passed. Text-layer checks cannot
  catch a text layer that disagrees with the rendered page; the fix is a render check (rasterize, OCR the
  quoted regions, flag quotes that are not visible).
- **One usage value on invoice 10, flagged.** The text layer prints every character about 13 times over itself
  (fake bold). The value was wrong, its quote was not found and the re-parse disagreed, so it went to review.

**Edge cases in the sample set:** dual-fuel and triple-utility bills (01, 03, 05, 09); a bill that prints no
usage at all (09); decimal commas, dot thousands and space thousands (05, 06, 07, 08); DD/MM vs MM/DD dates;
gas in m³ converted to kWh (03, 05) and CCF converted to therms (02); time-of-use bands to sum (07, 08); water
and sewer on one bill (04); megalitres (10); two companies on one bill (04, 05); a bill printing two different
issue dates (03, both accepted); a hidden text layer (08); an overprinted text layer (10).

**Found by measuring, then fixed:**

- pypdf's layout mode silently dropped up to 78% of the text on two bills (rotated text). Ingest now uses
  layout mode only when it keeps 95% of what plain mode finds.
- Retrying a daily-quota error burned the remaining quota; it now fails fast.
- `langdetect` seeds a global RNG and loads lazily, so concurrent workers could change the language hint in
  the prompt, and with it the cache key. Detection now runs under a lock; offline replay is byte-identical.

**Automated tests** (`python -m pytest`, 75 tests, offline):

- `test_normalize.py`: decimal comma vs point, French space grouping, Swiss apostrophes, full-width digits,
  `m³` not read as the number 3, DMY vs MDY vs YMD, month names in 8 languages, Japanese era dates, a date
  range printed with one year, unit aliases.
- `test_verify.py`: inverted periods, units that do not fit the utility, meter reads that do not add up, future
  dates, grounding that tolerates layout whitespace but catches an invented number.
- `test_pipeline.py`: a scripted LLM drives the full pipeline: dual-fuel split, a hallucinated usage value and
  a day/month swap are both flagged, a missing address stays empty, services never share check state, the
  file name never reaches the prompt.
- `test_llm.py`: schema sent to Gemini, retries on overload, fail-fast and circuit breaker on daily quota, the
  ladder falls through capacity errors but never hides a real error, cache replay without a client.
- `test_ingest.py`, `test_eval.py`: the layout/plain choice, and the scoring rules themselves.

**With more time:**

- The render check above, run on every PDF before extraction.
- A larger labelled set (20 to 50 bills per major vendor template), run in CI on every prompt or model change
  with a per-field accuracy gate.
- Perturbation tests on real bills: delete the address line, convert dates to US format, and assert the
  pipeline abstains or flags instead of guessing.
- Calibration: once there are enough labelled fields, check that a 0.9 confidence is right about 90% of the
  time, and fit the penalty weights to data.
- History checks: usage against the same meter's previous bills.

## Trade-offs

| chose | over | because |
|---|---|---|
| one call per document | chunking, multi-step agents | bills are short; fewer moving parts |
| schema + quotes | free-form JSON | parse failures and invisible hallucinations both disappear |
| computed confidence | model self-rating | measurable, explainable, cheap |
| original-language extraction | translate first | cheaper, and no translation errors in numbers and dates |
| two providers behind one interface | a framework (LangChain etc.) | direct code is easier to read and debug |
| text layer only | vision / OCR | the brief allows it; vision is the fallback for scans and the fix for hidden layers |

## Repository

```
invoice_extractor/   the pipeline
eval/                accuracy evaluation against ground truth
ground_truth/        hand labels for every sample invoice, with evidence
samples/invoices/    the real input bills + SOURCES.md
output/              invoices.csv, extractions.jsonl, eval_report.md
cache/               LLM answers, for offline replay
tests/               offline unit and pipeline tests
web/                 the walkthrough site
```
