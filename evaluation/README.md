# Evaluating DevDocs AI — Milestone 8

This is a small diagnostic dataset, not a general-purpose benchmark. AtlasDocs and
AtlasDB are fictional services. Their rules are defined entirely by the six corpus
files; no current framework knowledge or private user uploads are needed.

The nine questions cover uncommitted transactions, committed changes, version
filters, file formats, HTTP settings, combining two documents, missing database
retry settings, an unspecified version, and an undocumented Python runtime.
Three questions expect `insufficient_evidence`. The duplicate transaction document
exercises context deduplication during collection-wide search; the answerable
transaction cases use explicit document filters so their gold provenance is stable.

## Run and review

From `backend/`, using the existing environment and locked dependencies:

```bash
uv run --locked python -m evals validate
uv run --locked python -m evals run --output ../evaluation/runs/baseline/run.json
uv run --locked python -m evals review-template ../evaluation/runs/baseline/run.json --output ../evaluation/runs/baseline/review.json
```

`validate`, `review-template`, and `score` are offline. Only `run` uses PostgreSQL,
OpenAI embeddings and generation. Live runs incur normal API usage. PostgreSQL
must be running and the configured role must be able to create databases and
enable pgvector, as in the integration tests. Set OPENAI_API_KEY in the root .env.
Backend/frontend servers need not be running.
Credentials come from the existing root `.env`; never put them in commands or
evaluation files.

The runner creates a random `devdocs_eval_<uuid>` database, migrates it, ingests
and indexes only the corpus, then removes that database in `finally`. It does not
write to the application's document database. Exceptions also trigger cleanup;
an OS kill or unavailable PostgreSQL during cleanup can still leave an orphan.
There is no option to evaluate against or drop an existing named database.

The run report includes questions, references, actual answers, errors, actual
prompt excerpts, used citations, timings, model aliases, retrieval/chunk settings,
and dataset/corpus and system-prompt fingerprints. It explicitly omits credentials
and connection URLs. `database_removed: true` is written only after cleanup succeeds.
Per-question provider/database failures are recorded as errors and produce exit
code 1; setup/input failures produce exit code 2. Successful execution is exit 0,
not a declaration that every quality metric passed. Existing output files are
never overwritten. New ad hoc runs are ignored by Git; the checked-in synthetic
baseline is deliberately public.

Fill the review template by reading each answer and the **supplied context**, not
just the reference answer. For each answered case:

1. Split every factual statement into atomic claims, including extra statements
   the model added. Use literal substrings from the recorded answer.
2. Set `supported` to true only if the supplied context supports the claim without
   relying on outside knowledge. False includes contradictions and absent evidence.
   An observation that an excerpt omits a detail can be checked by inspecting the
   complete supplied excerpts; do not infer that the detail does not exist anywhere.
3. Map the actual inline citation group to each claim it accompanies. A marker at
   the end of a compound sentence applies to its constituent claims. Judge each
   claim/source pair separately: `supports_claim` requires that particular excerpt
   to support that particular claim. An unrelated extra citation is false even if
   another citation supports the claim. Never add citations the model did not use.
4. Include uncited factual claims with an empty `citations` list. Record notes for
   disputed judgements. Set `complete: true` only after covering the whole answer,
   and identify the reviewer. `null` judgements and incomplete cases remain pending.

Example claim inside a completed case review:

```json
{
  "text": "The maximum upload size in AtlasDocs version 2 is 10 MiB",
  "supported": true,
  "citations": [{"label": "S1", "supports_claim": true}],
  "notes": "S1 explicitly states the version 2 limit."
}
```

Then score it:

```bash
uv run --locked python -m evals score ../evaluation/runs/baseline/run.json --review ../evaluation/runs/baseline/review.json --output ../evaluation/runs/baseline/summary.json
```

Without `--review`, semantic metrics remain `null`. A review is bound to a SHA256
of the full report, including exact outputs, so it cannot silently grade a rerun.
The scorer validates spans, references, uniqueness and completed judgements. It
cannot prove that a human listed every claim or made the right semantic judgement.

## Metric definitions

| Metric | Calculation | What it tells us |
| --- | --- | --- |
| Retrieval precision | Selected excerpts containing a gold quote from its labelled file / selected excerpts | How much final context is labelled useful |
| Evidence recall | Unique covered gold evidence units / all gold units | Whether requested evidence survives retrieval and context construction |
| Groundedness | Supported reviewed claims / reviewed factual claims | Whether output is supported by the actual supplied evidence |
| Citation correctness | Supporting reviewed claim/source pairs / reviewed pairs | Whether each cited excerpt supports its associated claim |
| Citation validity | Answers with matching inline labels and exact context provenance / checked answers | Deterministic references; does **not** establish semantic support |
| Claim citation coverage | Reviewed claims with at least one mapped inline citation / reviewed claims | Whether factual claims are cited at all |
| Expected-status accuracy | Cases matching the labelled answer/refusal status / all cases | Answering/refusal policy compliance; errors count as failures |

Precision uses actual context length, not a padded top-k denominator. Retrieval
metrics are averaged equally across scorable cases (macro average); human metrics
pool claim/pair counts (micro average). Denominators and review completion appear
in every summary. Duplicate hits do not increase evidence recall. An empty context
scores zero when gold evidence exists. Questions with no gold evidence have
`null` retrieval metrics, since absence of a reference answer does not label every
topically related passage irrelevant. Errors with unmeasured retrieval are excluded
from retrieval averages and counted separately. Refusals have no generated factual
claims, so they never receive invented perfect groundedness/citation scores.

The recording provider observes the JSON prompt produced by `answer_question`.
We evaluate **final supplied context**, after over-retrieval, cleanup and character
budgeting. Raw `/search` results and the answer's used citations are different
sets, and neither substitutes for that context.

Gold quotes are stable across random document/chunk UUIDs. Matching normalizes
whitespace but requires a quote in the correct file. It is a transparent proxy,
not a semantic relevance classifier: paraphrases, alternative relevant passages,
and quotes split across chunks can be missed. Update gold labels if corpus or
chunk boundaries change. All fixture documents currently fit within one default
chunk; long PDFs, extraction quality and chunk-boundary behaviour are not evaluated
by this dataset.

## Historical recorded baseline

This frozen baseline predates the switch to OpenAI embeddings. Its scores do not
measure the current embedding model; collect and review a new run to compare.

Inspect [run.json](baseline/run.json), [review.json](baseline/review.json), and
[summary.json](baseline/summary.json). The recorded configuration is
`openai:gpt-5.4-mini`, `ollama:embeddinggemma` (768 dimensions), top-k 5, cutoff
0.35, chunk size 1000, overlap 150 and a 5000-character context budget.

| Observation | Result |
| --- | --- |
| Questions / operational errors | 9 / 0 |
| Retrieval precision, macro | 63.6% across 7 labelled cases |
| Evidence recall, macro | 100% across 7 labelled cases |
| Groundedness | 15/15 supported claims |
| Citation correctness | 16/18 supporting claim/source pairs |
| Citation validity | 7/7 accepted answers |
| Claim citation coverage | 15/15 claims |
| Expected-status accuracy | 8/9 cases |

The format and HTTP settings questions retrieved several distractors despite
finding the required evidence. Perfect recall can coexist with low precision.
This supports testing a smaller top-k or higher cutoff; it does not establish
which setting will generalize best. Compare a fresh run, for example:

```bash
uv run --locked python -m evals run --top-k 3 --min-similarity 0.45 --output ../evaluation/runs/top3/run.json
```

The unspecified-version case expected a strict refusal because no single upload
limit could be established. The model instead explained both version limits and
acknowledged missing version-detection guidance. Those claims were grounded, so
this is a **policy mismatch, not a hallucination**. A product that accepts helpful
conditional answers could change that label explicitly in a new dataset version;
we retain the original policy and result here.

That compound answer placed `[S1][S2]` after both version limits. Collectively
the sources cover the sentence, but under our strict per-claim/per-source rubric,
the version 1 source does not support the version 2 claim and vice versa. Those
two pairs are false. This detects citation granularity and unnecessary citations,
not an invented limit. Different citation-group scoring policies can yield different
numbers; define the rubric before comparing systems.

These are one run and one Codex manual review, **not an independent human study**.
Model aliases can change, generation varies, and nine synthetic cases cannot
establish general accuracy. The reports record configured aliases, not provider
model snapshots, embedding weight hashes or a full environment/code snapshot.
For stronger evaluation, obtain a second review, add realistic held-out documents
and adversarial questions, measure answer completeness, and repeat runs. Do not
tune repeatedly on this tiny set and then claim unseen-data quality.

## Engineering and interview explanations

- `dataset.py` validates questions, filters, confined corpus paths and reference
  quotes before any paid calls. Schema validation catches structural mistakes;
  it cannot establish that an expected answer is the right product policy.
- `runner.py` reuses ingestion, indexing and generation services. Its small LLM
  wrapper records the prompt while preserving the provider interface; no second
  RAG pipeline or evaluation-only application behaviour is introduced.
- `metrics.py` separates deterministic matching/provenance from semantic review.
  Review hashes prevent stale judgements from making a changed system look better.
- `__main__.py` keeps live execution opt-in and offline scoring repeatable, with
  explicit output paths and no new framework dependency.

An interview explanation: “I evaluated retrieval and generation separately. My
baseline found all labelled evidence but included distractors. Valid citation IDs
did not guarantee that every individual citation supported its claim. I retained
the failure and documented a strict refusal policy that differed from the model's
conditional answer, rather than calling every fluent answer correct.”

This milestone adds no agent, model changes, API routes, CI or deployment work.
