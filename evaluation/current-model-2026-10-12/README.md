# Current-model evaluation — 12 October 2026

This is one live run of the existing nine-question synthetic dataset with
`openai:text-embedding-3-small` (1536 dimensions) and `openai:gpt-5.4-mini`.
The six fictional corpus files were freshly ingested and embedded in a newly
created `devdocs_eval_*` database. Cleanup succeeded (`database_removed: true`);
the normal document database was not changed. No Ollama runtime was used.

## Artifacts and reproduction

- [run.json](run.json): actual answers, supplied excerpts, citations, errors,
  timings, configuration and dataset/prompt fingerprints.
- [review.json](review.json): 16 atomic factual claims reviewed against supplied
  context, with literal answer spans and actual citation mappings.
- [summary.json](summary.json): deterministic and reviewed semantic scores.
- [provenance.json](provenance.json): code commit, source/dependency fingerprints,
  Python version and report digest. It contains no credentials or database URL.

From `backend/`, with PostgreSQL running and the existing root `.env` configured:

```bash
LLM_PROVIDER=openai LLM_MODEL=gpt-5.4-mini \
EMBEDDING_MODEL=text-embedding-3-small EMBEDDING_DIMENSIONS=1536 \
uv run --locked python -m evals run --top-k 5 --min-similarity 0.35 \
  --output ../evaluation/runs/current-model-repeat/run.json
uv run --locked python -m evals review-template \
  ../evaluation/runs/current-model-repeat/run.json \
  --output ../evaluation/runs/current-model-repeat/review.json
```

Complete a fresh review before scoring; do not copy this review to another run.
The scorer binds each review to the exact report SHA256. Then run:

```bash
uv run --locked python -m evals score \
  ../evaluation/runs/current-model-repeat/run.json \
  --review ../evaluation/runs/current-model-repeat/review.json \
  --output ../evaluation/runs/current-model-repeat/summary.json
```

Live execution incurs API usage; template generation and scoring are offline.
Existing reports are never overwritten. The database role must have creation and
pgvector extension privileges. See [the evaluation guide](../README.md) for the
rubric, cleanup guarantees and metric definitions.

## Results compared with the frozen historical run

The dataset/corpus fingerprint and system prompt fingerprint match the historical
run. Top-k 5, cutoff 0.35, chunk size 1000, overlap 150 and context budget 5000
characters are unchanged. Generation still uses the same configured model alias;
the historical embeddings were `embeddinggemma`, with 768 dimensions. Historical
code/environment and provider snapshot equality are not established, so this is
a diagnostic comparison rather than a controlled causal experiment.

| Metric | Historical | Current run |
| --- | --- | --- |
| Questions / operational errors | 9 / 0 | 9 / 0 |
| Retrieval precision, macro across 7 labelled cases | 63.6% | 70.0% |
| Evidence recall, macro across 7 labelled cases | 100% | 100% |
| Groundedness | 15/15 claims | 16/16 claims |
| Citation correctness | 16/18 pairs | 16/16 pairs |
| Citation validity | 7/7 answered cases | 7/7 answered cases |
| Claim citation coverage | 15/15 claims | 16/16 claims |
| Expected-status accuracy | 8/9 | 8/9 |

All seven answered cases were reviewed by **one Codex AI reviewer**, reading the
actual supplied context. This is not independent human review or a separate
LLM-as-judge service. A second human reviewer should check the saved spans and
judgements before stronger portfolio accuracy claims. Refusals have no generated
factual claims and are excluded from groundedness/citation denominators.

## What the results mean

- The committed-changes context now contains one relevant excerpt rather than one
  relevant excerpt plus a distractor: precision improved from 0.5 to 1.0 there.
- The file-formats question still retrieves the needed document but now has four
  distractors, giving precision 0.2 instead of 0.25. HTTP settings also remains
  at 0.2. Higher overall precision does not mean every question improved.
- Every labelled evidence unit survived final context construction. That is
  100% recall on this small dataset, not proof that retrieval generalizes.
- The unspecified-version question still violates the strict expected refusal
  policy. It gives grounded conditional limits (2 MiB for version 1, 10 MiB for
  version 2). This is a **policy mismatch**, not an unsupported invented limit.
- In that conditional answer, `[S1]` follows the version 1 claim and `[S2]` follows
  the version 2 claim. This avoids the historical shared citation group that
  produced two incorrect per-claim/source pairs under the same strict rubric.
  Generation varies; do not attribute this single output improvement solely to
  the embedding switch.

The retrieval score is a gold-quote/file matching proxy measured on **final
supplied context**, not raw search results. The set contains only nine synthetic
questions, and every document fits in one default chunk. It does not evaluate
long documents, PDF extraction, chunk boundaries, adversarial robustness, agent
routing, answer completeness or production latency/cost. Model aliases may change.

No prompt, threshold, top-k, dataset, provider adapter or application behavior was
modified to improve these scores. Next work could add held-out realistic questions,
independent review and repeated runs before tuning retrieval or refusal policy.
[OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
provides the broader evaluation rationale.
