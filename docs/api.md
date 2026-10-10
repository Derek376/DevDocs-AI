# REST API reference

Use `http://localhost:8000` directly with the Docker defaults. The frontend uses
`http://localhost:8080/api`, whose proxy removes `/api`. FastAPI serves Swagger at
`/docs`, ReDoc at `/redoc`, and its authoritative schema at `/openapi.json`.
[The committed snapshot](openapi.json) is generated from the application factory,
not independently maintained definitions. Routes currently have no authentication.

## Document lifecycle

```bash
curl http://localhost:8000/documents \
  -F 'file=@examples/atlasdb-transactions.md;type=text/markdown'
```

`POST /documents` returns 201 metadata: `id`, `filename`, `media_type`, `size_bytes`,
`status`, `created_at`, `updated_at`, `chunk_count`. Copy the returned UUID into
`DOCUMENT_ID` below. This stores extracted text but does not call embeddings.

```bash
DOCUMENT_ID=replace-with-returned-uuid
curl -X POST "http://localhost:8000/documents/$DOCUMENT_ID/index"
curl "http://localhost:8000/documents/$DOCUMENT_ID/chunks?limit=20&offset=0"
curl 'http://localhost:8000/documents?limit=20&offset=0'
```

Indexing returns `document_id`, `embedded_chunk_count`, `model` and `dimensions`.
It replaces existing vectors after every embedding batch validates. Chunk responses
contain `id`, `document_id`, zero-based `position`, `text` and nullable one-based
`source_page`. Both listing routes default to limit 20/offset 0; limit is 1–100.
Document listing is newest-first, with an ID tie-breaker; chunks are position-ordered.
Offset pagination can shift if documents are uploaded between requests.

## Search and fixed RAG

```bash
curl http://localhost:8000/questions \
  -H 'Content-Type: application/json' \
  -d '{"question":"How do I discard uncommitted changes?","top_k":3}'
```

`POST /search` accepts the same body and returns retrieval results without an LLM
answer. Required `question`: nonblank, at most 2000 characters, trimmed by the API.
Optional fields: integer `top_k` 1–20, `document_ids` containing 1–50 UUIDs, and
`media_type` (`text/plain`, `text/markdown`, `application/pdf`). Document/type
filters combine. Unknown request fields are rejected. The minimum similarity
cutoff comes from backend settings, not the HTTP body.

`/search` returns `model` and `matches`, each with chunk/document UUIDs, filename,
position, page, text and numeric similarity. It returns 200 with an empty list
when nothing qualifies. Raw matches differ from the deduplicated, budgeted RAG
context and the subset of sources cited in the answer.

A representative `/questions` response, with abbreviated illustrative identifiers:

```json
{
  "answer": "Use ROLLBACK to discard uncommitted changes. [S1]",
  "status": "answered",
  "llm_model": "openai:gpt-5.4-mini",
  "embedding_model": "openai:text-embedding-3-small",
  "citations": [{
    "label": "S1",
    "chunk_id": "<chunk UUID>",
    "document_id": "<document UUID>",
    "filename": "atlasdb-transactions.md",
    "position": 0,
    "source_page": null,
    "text": "<actual supplied excerpt>",
    "similarity": 0.7,
    "truncated": false
  }]
}
```

The example is a contract illustration, not a recorded similarity measurement.
The live screenshot is in [the demo guide](demo.md). `answered` means schema and
citation reference checks passed; it is not an accuracy certificate. Only cited
source excerpts appear in `citations`. Insufficient evidence returns HTTP 200,
`status: insufficient_evidence`, a fixed explanation and an empty citation list.
A malformed/unknown citation instead produces a useful 502 failure.

## Optional assistant

```bash
curl http://localhost:8000/agent/questions \
  -H 'Content-Type: application/json' \
  -d "{\"question\":\"Summarize this document\",\"selected_document_id\":\"$DOCUMENT_ID\"}"
```

The request accepts only `question` and optional `selected_document_id` (UUID or
null). Question limits match fixed RAG. Callers cannot set a tool name, search
query, file path or database query. The model chooses one allowlisted operation;
the backend validates the exact selected scope.

The response adds `tool`, `document` and `context_truncated` to the answer fields.
Statuses are `answered`, `insufficient_evidence`, `metadata` and
`selection_required`. Metadata comes from PostgreSQL with no generated rewrite.
Summaries use ordered stored text; their citation similarity is null because no
similarity search occurred. `embedding_model` identifies configured embeddings;
metadata and summary do not use them. Retrieval uses the server's top-k/cutoff.
[Agent contracts and limits](agent.md).

## Errors and operational checks

| HTTP status | Meaning |
| --- | --- |
| 400 | Invalid/empty/corrupt document content |
| 404 | Missing document or route |
| 413 | Backend upload/extracted-content limit, or proxy request limit |
| 415 | Unsupported extension or mismatched declared content type |
| 422 | Request field/shape validation failure |
| 500 | Safe unexpected application failure |
| 502 | Provider, malformed output or citation-contract failure; proxy connectivity failures also use 502 |
| 503 | Database unavailable/unconfigured or failed operation |

Most operational failures return `{"detail":"Useful message"}`. Validation errors
return a detail array with field `loc`, `msg` and `type`, excluding submitted values.
Backend responses carry `X-Request-ID`; report that reference when troubleshooting.
Proxy-generated errors do not necessarily contain a backend request ID. Provider
response bodies, keys and stack traces are not returned to the UI.

`GET /health` returns `{"status":"ok"}` when the API process responds. `GET /ready`
executes a database connectivity check. Neither checks model access, embedding
compatibility, table/migration state or RAG quality. A successful health check
therefore does not imply that a question can be answered.
