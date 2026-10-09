# DevDocs AI

A technical documentation assistant that retrieves relevant passages from uploaded
documents and uses a language model to produce answers with source citations.

**Status:** Milestone 9 — production engineering complete. Backend/frontend images,
ordered Docker Compose startup, CI, structured request logging and safe errors are
implemented and locally verified. The project remains a local single-user MVP.
See [production setup and decisions](docs/production.md) and the
[evaluation baseline](evaluation/README.md).
This project is built one milestone at a time, with explanations and verification
before continuing.

## Problem and intended outcome

Developers need to find answers in technical documentation without losing the
ability to check the original source. DevDocs AI will make that process easier
by combining semantic retrieval with source-grounded generation.

The project also serves as an engineering learning portfolio: design decisions,
tests, evaluation results, and limitations will be documented alongside code.

## MVP requirements

- Upload UTF-8 `.txt`, `.md`, and text-based PDF documents.
- Validate file type, size, and extracted content; return useful errors for
  unsupported, empty, corrupt, or oversized files. Initial upload limit: 10 MiB.
- List uploaded documents and their ingestion status.
- Extract text, divide it into chunks, and store document and chunk metadata.
- Generate and persist embeddings for chunks.
- Accept one question per request and retrieve relevant chunks.
- Generate an answer using retrieved evidence, with citations identifying the
  document and chunk; retain PDF page references where extraction permits.
- Return the cited source excerpts separately from the generated answer so users
  can verify the claims.
- Explain when the available evidence does not support an answer.
- Provide a React interface with upload, document list, questions, answers,
  citations, and clear loading/error states.

The first usable RAG backend arrives in Milestone 5; the browser MVP arrives in
Milestone 6. Evidence handling is strengthened in Milestone 7 and measured in
Milestone 8. Portfolio readiness includes the later engineering and polish work.

### Initial scope boundaries

One user working with one shared document collection in a local development
environment. Questions are independent; conversation memory is outside the MVP.
There is no authentication or tenant isolation, so the initial system is not
intended for public deployment with private documents.

OCR for scanned PDFs, website crawling, document editing/deletion, streaming,
hybrid search, reranking, and distributed ingestion workers are outside the MVP.
Tool calling is reserved for Milestone 10. A simple RAG system comes first.

### Acceptance criteria

1. A supported document uploads, becomes searchable, and appears in the list.
2. A question whose answer exists in that document returns a relevant answer and
   citations that resolve to stored chunks and source excerpts.
3. A question without supporting evidence produces an explicit insufficient-
   evidence response; this behaviour is evaluated, not assumed.
4. Invalid uploads and provider failures return understandable errors without
   exposing credentials or internal stack traces.
5. Meaningful automated tests cover ingestion, retrieval, and answer/citation
   handling as those features are introduced.
6. Documented setup and CI checks make the finished project reproducible.

## Planned architecture

Use a modular monolith: one backend process with clear internal responsibilities.
This keeps deployment simple while allowing components to be tested separately.

```mermaid
flowchart LR
    User[User] --> UI[React + Vite frontend]
    UI -->|REST / HTTP| API[FastAPI routes]
    API --> Services[Ingestion and question services]
    Services --> Persistence[Persistence layer]
    Persistence --> DB[(PostgreSQL + pgvector)]
    Services --> Embeddings[Embedding provider interface]
    Services --> LLM[LLM provider interface]
```

### Two flows

**Ingestion:** upload → validate → extract text → chunk → embed → persist.

**Question answering:** question → embed → retrieve chunks → construct context
→ prompt LLM → validate citation references → return answer and sources.

Document status will distinguish processing, ready, and failed documents. Only
ready documents should contribute retrieval results. Ingestion starts with a
bounded request-based flow; a durable job queue is a later option if processing
times require it. Async HTTP code alone does not make CPU-heavy work nonblocking.

### Responsibilities and decisions

| Area | Responsibility and reason |
| --- | --- |
| API | Validate request/response shapes and map failures to HTTP responses. Keep orchestration out of route handlers. |
| Services | Coordinate ingestion and questions. Keep business rules testable without a browser. |
| Persistence | Store and query documents, chunks, and vectors. Keep database details out of provider code. |
| AI | Separate embedding and generation providers. Replacing an LLM should not require rewriting upload or database logic. |
| PostgreSQL + pgvector | Keep relational metadata and searchable vectors in one database, reducing infrastructure for this project. |
| React + Vite | Use the familiar frontend stack for a focused upload and question interface. |
| Configuration | Read environment settings in the backend; never send provider secrets to the browser. |
| Testing | Use deterministic provider substitutes for normal automated tests; run live-provider quality evaluations separately. |

Embeddings represent text as numerical vectors. Semantic search compares those
vectors to find passages related in meaning to a question. The LLM then generates
text using the retrieved passages. Retrieval and generation are separate steps
with separate failure modes.

Switching embedding models can change vector dimensions and the meaning of the
vector coordinates. Stored chunks must be re-embedded when the embedding model
changes; provider replacement is not automatically a configuration-only change.
Record model identity and chunking settings with ingestion data when implemented.

### Grounding and trust

Retrieved text is evidence, not executable instructions. Prompts will separate
the user's question from source passages and tell the model to answer only from
the supplied evidence. Citations will use stable chunk identifiers, and the
backend will check that references belong to the retrieved set. This checks
reference validity; evaluating whether a cited passage actually supports a
claim is a separate quality task. RAG reduces unsupported answers but does not
eliminate them.

### Database model — implemented in Milestone 2

- **Document:** UUID, filename, media type, size in bytes, processing/ready/failed
  status, optional safe error message, and timezone-aware creation/update times.
- **Chunk:** UUID, document UUID, zero-based position, text, optional one-based PDF
  page reference, and creation time.

One document has many chunks. A foreign key prevents orphan chunks; a unique
constraint prevents two chunks occupying the same position in a document. Its
index also supports querying chunks by document. Database check constraints
reject invalid sizes, statuses, positions, empty text/filenames, and page numbers.
Deleting a document cascades to its chunks; no deletion API is implemented yet.
UUIDs provide stable source identifiers independent of filename or text changes.
`updated_at` is refreshed by SQLAlchemy updates, not a database trigger; direct SQL
writers must set it themselves.

Each chunk now has a nullable `embedding` vector and `embedding_model` identifier.
Migration `0002` preserves existing text with null embedding fields; the explicit
indexing endpoint fills them. A database constraint requires both fields to be
present or both absent. Chunking metadata and approximate indexes remain future
work. Source text and identifiers are unchanged by re-indexing.

## Directory structure

Current layout:

```text
DevDocs AI/
├── README.md
├── .gitignore
├── .env.example
├── compose.yaml             # database, migrations, backend and frontend
├── .github/workflows/ci.yml # backend/frontend/container checks
├── docs/production.md       # container setup, operations and CI decisions
├── scripts/smoke_compose.py # HTTP integration smoke for a disposable stack
├── backend/
│   ├── pyproject.toml       # dependencies and test/lint configuration
│   ├── uv.lock              # exact resolved dependency versions
│   ├── alembic.ini          # migration configuration
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── migrations/          # env.py, revision template, and versioned schema
│   ├── evals/               # dataset validation, live runner, scoring CLI
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py          # create_app factory
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── health.py    # liveness/readiness routes
│   │   │   ├── documents.py # upload and inspection routes
│   │   │   ├── document_schemas.py
│   │   │   ├── search.py    # index and semantic retrieval routes
│   │   │   └── questions.py # RAG answer and citation contracts
│   │   ├── ai/
│   │   │   ├── __init__.py
│   │   │   ├── embeddings.py # provider contract and vector validation
│   │   │   ├── openai.py     # embedding and Responses API adapters
│   │   │   └── llm.py        # generation contract and structured output
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py    # typed environment settings
│   │   │   ├── logging.py   # allowlisted JSON application logs
│   │   │   └── middleware.py # correlation and safe unexpected-error boundary
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── ingestion.py
│   │   │   ├── extraction.py
│   │   │   ├── chunking.py
│   │   │   ├── document_errors.py
│   │   │   ├── search.py     # indexing and retrieval orchestration
│   │   │   └── rag.py        # context, prompt, generation, citation resolution
│   │   └── persistence/
│   │       ├── __init__.py
│   │       ├── database.py # connection pool and request sessions
│   │       ├── models.py   # document and chunk tables
│   │       ├── documents.py # persistence queries
│   │       └── search.py    # pgvector cosine query
│   └── tests/
│       ├── conftest.py
│       ├── test_health.py
│       ├── test_config.py
│       ├── test_database_config.py
│       ├── test_readiness.py
│       ├── test_chunking.py
│       ├── test_extraction.py
│       ├── test_document_api.py
│       ├── test_embeddings.py
│       ├── test_search_api.py
│       ├── test_llm.py
│       ├── test_openai_llm.py
│       ├── test_rag.py
│       ├── test_retrieval_quality.py
│       ├── test_evaluation.py
│       ├── test_operations.py
│       └── integration/
│           └── test_database.py
├── evaluation/
│   ├── README.md            # scoring definitions, review rubric, limitations
│   ├── dataset.json         # questions, expected status and stable gold quotes
│   ├── corpus/              # six fictional documentation files
│   └── baseline/            # recorded run, claim review and metric summary
└── frontend/
    ├── Dockerfile
    ├── .dockerignore
    ├── nginx.conf           # static files and same-origin API proxy
    ├── package.json         # dev, build, lint, and test commands
    ├── package-lock.json    # exact npm dependency versions
    ├── index.html           # browser entry point
    ├── vite.config.ts       # React, API proxy, and Vitest configuration
    ├── tsconfig.json        # strict TypeScript checks
    ├── eslint.config.js     # TypeScript and React rules
    └── src/
        ├── main.tsx         # React root and StrictMode
        ├── App.tsx          # workspace composition
        ├── api.ts           # typed HTTP requests and safe errors
        ├── styles.css       # responsive styles and focus states
        ├── components/
        │   ├── DocumentPanel.tsx
        │   ├── QuestionPanel.tsx
        │   └── AnswerCard.tsx
        ├── App.test.tsx     # user workflows
        ├── api.test.ts      # HTTP boundary cases
        └── test/setup.ts    # DOM matchers and cleanup
```

Planned backend layout, created only as each part becomes necessary:

```text
backend/
├── app/
│   ├── main.py        # application entry point
│   ├── api/           # routes and request/response schemas
│   ├── core/          # configuration and shared error/logging setup
│   ├── services/      # ingestion and question orchestration
│   ├── persistence/   # database models, connection, and queries
│   └── ai/            # embedding and LLM provider boundaries
├── tests/
└── migrations/
```

CI workflows and evaluation data are now present. Compose runs PostgreSQL,
a one-shot migration service, FastAPI and the built React frontend; see
[container setup](docs/production.md).
Prefer small modules and simple functions/classes; do not introduce a generic
framework or a separate service for every responsibility.

FastAPI supports grouping routes in modules using `APIRouter`; see its
[Bigger Applications guide](https://fastapi.tiangolo.com/tutorial/bigger-applications/).

## Configuration and secrets

The backend reads optional settings from `.env` in the repository root. Its path
is resolved relative to `config.py`, so it does not depend on the shell's working
directory. Copy `.env.example` to `.env` if you want to change defaults.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `DevDocs AI` | API title in generated documentation; must be nonempty. |
| `APP_ENV` | `development` | Environment label: `development`, `test`, or `production`. |
| `LOG_LEVEL` | `INFO` | JSON application log threshold: `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |
| `POSTGRES_HOST` | `127.0.0.1` | Host address used by the locally running backend. |
| `POSTGRES_PORT` | `5432` | Host port; valid range 1–65535. |
| `POSTGRES_DB` | `devdocs` | Database name. |
| `POSTGRES_USER` | `devdocs` | Local database user. |
| `POSTGRES_PASSWORD` | unset | Required for database setup; set a nonempty local value. |
| `MAX_UPLOAD_BYTES` | `10485760` | Maximum file content size: 10 MiB. |
| `MAX_EXTRACTED_CHARS` | `1000000` | Maximum extracted document characters. |
| `MAX_PDF_PAGES` | `200` | Maximum PDF page count. |
| `CHUNK_SIZE` | `1000` | Characters per chunk; valid range 100–10000. |
| `CHUNK_OVERLAP` | `150` | Repeated characters; must be nonnegative and smaller than chunk size. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model for indexing and search. |
| `EMBEDDING_DIMENSIONS` | `1536` | Expected output size; mismatches reject indexing/search. |
| `EMBEDDING_BATCH_SIZE` | `32` | Number of chunks per model request, valid range 1–128. |
| `EMBEDDING_TIMEOUT_SECONDS` | `120` | Timeout per embedding request. |
| `LLM_PROVIDER` | `openai` | Only OpenAI is enabled in the current application. |
| `LLM_MODEL` | `gpt-5.4-mini` | OpenAI answer-generation model. |
| `OPENAI_API_KEY` | unset | Backend-only secret for OpenAI embeddings and generation; blank is treated as missing. |
| `LLM_TIMEOUT_SECONDS` | `120` | Timeout per answer-generation request. |
| `RETRIEVAL_TOP_K` | `5` | Default maximum source count, 1–20; request override available. |
| `RETRIEVAL_MIN_SIMILARITY` | `0.35` | Minimum cosine similarity, 0–1; a heuristic, not confidence. |
| `BACKEND_PORT` / `FRONTEND_PORT` | `8000` / `8080` | Compose published host ports; not FastAPI settings. |

`APP_ENV` does not automatically enable production security or change logging.
`LOG_LEVEL` configures structured application logs independently. Configuration
precedence is explicit constructor values → environment variables → `.env` →
defaults. Invalid values prevent application creation rather than silently using
a fallback. Unknown dotenv keys are ignored so the root file can eventually hold
settings for other components.

A developer's `.env` is ignored by Git. Real keys must never appear in tracked
files, logs, screenshots, or frontend configuration.

## Development and verification

Prerequisites: Python 3.12–3.14, [uv](https://docs.astral.sh/uv/), Node.js
22.12+ (verified with Node 24), npm, and Docker with Compose. Docker Desktop must be running for database commands.
The backend is an application, not a published Python package. Commands below
run from `backend/`; uv manages its ignored `.venv` directory. The checked-in
lockfile pins resolved versions; `--locked` rejects stale dependency metadata.

From the repository root:

```sh
cp -n .env.example .env
# Edit .env and set POSTGRES_PASSWORD to your own nonempty local password.
docker compose up -d --wait db
cd backend
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:create_app --factory --reload --no-access-log
```

If `.env` already exists, keep it and add the database settings instead of copying
over it. A blank password is invalid; omitting the password allows liveness-only
API use and causes `/ready` to return 503. Compose requires the password.
If port 5432 is occupied, change `POSTGRES_PORT` in `.env`; both the port mapping
and backend connection use it.

Visit [interactive API docs](http://127.0.0.1:8000/docs), or check:

```sh
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

The server uses Uvicorn, which runs the FastAPI ASGI application. `--factory`
invokes `create_app()` at startup; `--reload` is for local development.
`GET /health` is a **liveness** check: HTTP 200 means the API can respond. It does
not verify database connectivity or AI provider availability. `GET /ready` executes
`SELECT 1` and returns 200 if the database is reachable, or a useful 503 response
if it is unavailable/unconfigured. It does not verify migration state or AI
provider availability. Apply migrations before using future database features.

Run checks from `backend/`:

```sh
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Tests use FastAPI's in-process `TestClient`; no network server is needed. They
check the health response and OpenAPI contract, configuration defaults and source
precedence, rejection of invalid environments, and settings supplied to the
application factory. Fixtures isolate tests from developer environment settings.
Frontend checks are documented below. The backend is not built as a Python package.

Without `TEST_DATABASE_URL`, 27 database integration cases are explicitly skipped;
187 non-integration tests still run. To exercise all 214 tests against the local
Compose database, run this from `backend/` (it reads `.env` without printing the
password):

```sh
uv run --locked python - <<'PYTEST'
import os
import pytest
from app.core.config import Settings

os.environ["TEST_DATABASE_URL"] = Settings().database_url.render_as_string(
    hide_password=False
)
raise SystemExit(pytest.main(["-q"]))
PYTEST
```

Alternatively supply `TEST_DATABASE_URL` using the `postgresql+psycopg` scheme
through your environment. Use a local/test server and a user allowed to create
and drop databases and enable pgvector. Each integration case creates a uniquely
named disposable database and drops only that database after the test. Cases
verify extension availability, migration downgrade/reapply, model/schema
agreement, persistence, constraints, cascade deletion, readiness, and request
session commit/rollback, upload-to-chunk persistence, pagination, and atomic
rollback on failed chunk writes. SQLite cannot validate these PostgreSQL-specific features.

Milestone 2 verification: all 28 tests passed on Python 3.14.7 with PostgreSQL 17
and pgvector 0.8.2; Ruff lint/format checks and `alembic check` passed.

Documentation consulted: [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/),
[Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/),
and [uv projects](https://docs.astral.sh/uv/guides/projects/).

## Roadmap

| Milestone | Deliverable | Status |
| --- | --- | --- |
| 0 | Requirements, MVP scope, architecture, repository skeleton | Complete |
| 1 | FastAPI, health endpoint, configuration, pytest foundation | Complete |
| 2 | Compose database, PostgreSQL + pgvector, models, migrations | Complete |
| 3 | Validated uploads, text extraction, metadata, chunking | Complete |
| 4 | Embeddings, vector persistence, semantic retrieval | Complete |
| 5 | Basic RAG pipeline with source citations | Complete |
| 6 | React upload, document list, questions, answers, and sources | Complete |
| 7 | Retrieval settings, filters, context cleanup, insufficient-evidence handling | Complete |
| 8 | Evaluation dataset: retrieval relevance, groundedness, citation correctness | Complete |
| 9 | Service containers, CI, automated checks, logging, error/secrets handling | Complete |
| 10 | Simple assistant using retrieval, metadata, and summary tools | Planned |
| 11 | Setup guide, screenshots, API docs, decisions, limitations, interview notes | Planned |

## Evaluation — Milestone 8

A versioned six-document corpus and nine questions include missing and ambiguous
evidence. The opt-in runner uses the production ingestion/indexing/RAG services
in a disposable PostgreSQL database and records the exact context supplied to
the model. Offline scoring separates quote-based retrieval metrics, deterministic
citation validity, and manually reviewed semantic support. Pending reviews remain
unscored; review fingerprints prevent grading a changed run with old judgements.

The historical `gpt-5.4-mini`/`embeddinggemma` baseline has 63.6% macro retrieval
precision and 100% evidence recall across seven gold-labelled cases. One Codex
manual review found 15/15 claims grounded and 16/18 individual citation pairs
supporting their associated claim. Expected answer/refusal status matched 8/9
cases; the remaining answer explained both version limits instead of declining.
This is a policy mismatch, not invented evidence. The tiny synthetic dataset and
single reviewer cannot establish general accuracy.

See [the evaluation guide](evaluation/README.md) for runnable commands, exact
denominators, review instructions, saved artifacts, limitations and interview
talking points. No runtime API, frontend, model or prompt behaviour changes in
this milestone.

## Limitations and future work

The backend exposes document ingestion/inspection, health, database readiness,
and generated API documentation. It embeds text, retrieves evidence, and generates
answers with source references. Groundedness is not guaranteed by citation validity. The MVP scope excludes scanned PDFs and multi-user access. Model context limits, provider cost/latency, upload processing
time, prompt injection, and retrieval quality will inform later decisions.
Embeddings and generation use OpenAI APIs; no local model server is required.
Model services remain external to the application images.

## Interview notes — Milestone 0

- Explain why a modular monolith fits the project better than multiple services.
- Trace ingestion and question answering as separate flows.
- Explain why embeddings retrieve evidence while the LLM generates an answer.
- Explain why a valid citation identifier does not prove a claim is supported.
- Explain why model changes can require re-embedding the stored collection.

Screenshots, detailed API documentation, measured results, and final interview
talking points will be added once the relevant features exist.


## Interview notes — Milestone 1

- **Application factory:** `create_app()` constructs a fresh API and loads settings
  only when called. Tests can inject configuration without import-time side effects.
- **Typed response:** `HealthResponse` describes the public JSON contract; FastAPI
  uses the return annotation for response validation and OpenAPI documentation.
- **HTTP semantics:** the health check uses GET because it reads status without
  changing data, and returns 200 when the API responds successfully.
- **Configuration:** separate deployment settings from code and validate them at
  startup. Never return the full settings object through an API endpoint.
- **Async:** the health route uses `async def` and does no blocking work. Async
  becomes useful for waiting on I/O; it does not speed up CPU-heavy extraction.
- **Testing:** in-process HTTP tests exercise routing and serialization. They do
  not replace testing a real server; a local server smoke check covers startup.
- **Dependencies:** `pyproject.toml` declares supported ranges; `uv.lock` records
  exact versions. Development tools are separated from runtime dependencies.


## Database operations and design decisions — Milestone 2

The Compose service uses `pgvector/pgvector:0.8.2-pg17-trixie`: PostgreSQL 17 with
the extension installed. Migration `0001` enables it in the application database
with `CREATE EXTENSION IF NOT EXISTS vector`. The named volume keeps database
files across container recreation. Only localhost can reach the published port.
The Compose health check tests server availability; it does not apply migrations.
See the [Compose service reference](https://docs.docker.com/reference/compose-file/services/)
and [pgvector documentation](https://github.com/pgvector/pgvector).

From the repository root, `docker compose stop db` stops the service while
retaining its volume; `docker compose up -d --wait db` starts it again.
The initial `POSTGRES_*` values initialize a new volume. Changing those values in
`.env` does not change credentials or database names inside an existing volume.
This local setup uses the image's administrative user. A deployed application
should use a restricted runtime role and a separate migration role.

SQLAlchemy's async engine owns a reusable connection pool. FastAPI's lifespan
creates it once and disposes it at shutdown. `pool_pre_ping` checks pooled
connections before reuse. An engine is not a session: each request receives a
new `AsyncSession`, and successful writes must explicitly commit. Closing the
session rolls back uncommitted work, including when a handler raises an error.
A session must not be shared across concurrent requests. `expire_on_commit=False`
keeps loaded values accessible after commit without an implicit async reload.
See [SQLAlchemy async support](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html).

Alembic applies versioned schema changes separately from server startup:

```sh
# From backend/
uv run --locked alembic current
uv run --locked alembic upgrade head
uv run --locked alembic check
# For later schema changes, generate and review a candidate migration:
uv run --locked alembic revision --autogenerate -m "describe schema change"
```

Autogeneration is a starting point requiring review; extension operations are
written explicitly. The revision template supports future migrations.
`alembic downgrade base` drops documents and chunks, so it should only be used
on disposable databases; tests exercise it there. The downgrade deliberately
retains pgvector because unrelated tables could depend on it.
See [Alembic's async migration recipe](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic).

## Interview notes — Milestone 2

- **Vector database:** stores numerical representations and finds neighbours by
  a distance/similarity metric. An embedding model produces the numbers; the
  database stores and searches them. It does not generate embeddings itself.
- **pgvector:** adds vector types and similarity operations to PostgreSQL, so
  relational document metadata and vectors can share transactions and joins.
- **Migration vs model:** the model describes the desired mapping; a migration
  records how to change an existing database. Editing a model does not alter a table.
- **Foreign key vs validation:** API checks give useful errors; database constraints
  protect integrity even if writes bypass the API.
- **Transaction:** a group of writes either commits or rolls back. In later ingestion
  work this helps prevent partially saved document/chunk collections.
- **Connection pool vs session:** the pool reuses connections; a session tracks one
  unit of work. Async I/O lets the server handle other requests while waiting for SQL.
- **Scope:** no uploads, vector column, embedding provider, or semantic search yet.


## Document ingestion — Milestone 3

| Method and path | Behaviour |
| --- | --- |
| `POST /documents` | Multipart field `file`; extracts and saves a document and its chunks; returns metadata with HTTP 201. |
| `GET /documents` | Metadata and chunk counts, newest first; `limit` (1–100, default 20) and `offset` (default 0). |
| `GET /documents/{id}/chunks` | Source chunk IDs, text, positions, and PDF pages, ordered by position; same pagination parameters. |

With the API running, from the repository root:

```sh
curl -F 'file=@README.md;type=text/markdown' http://127.0.0.1:8000/documents
curl 'http://127.0.0.1:8000/documents?limit=20&offset=0'
# Replace DOCUMENT_UUID with the id returned by the upload:
curl 'http://127.0.0.1:8000/documents/DOCUMENT_UUID/chunks?limit=100'
```

Upload responses contain `id`, `filename`, canonical `media_type`, `size_bytes`,
`status`, timestamps, and `chunk_count`. Chunk responses contain `id`,
`document_id`, zero-based `position`, `text`, and one-based `source_page` (null for
text/Markdown). A status of `ready` currently means text ingestion is complete;
it does not mean embeddings exist. Indexing is a separate request in Milestone 4;
only indexed chunks for the currently configured model are searched.

### Validation and error behaviour

The server rejects filenames containing paths or controls, unsupported extensions,
conflicting declared MIME types, empty/whitespace-only documents, invalid UTF-8,
and unsupported text controls. UTF-8 BOMs are accepted and newlines are normalized;
Markdown syntax, code indentation, and Unicode text are preserved. Extensions
and MIME types are hints: validation also checks the contents. Generic
`application/octet-stream` is accepted when the supported extension/content match.

PDF validation checks the header, parseability, encryption, page count, readable
text, and extracted-text limits. The parser additionally rejects pages whose
decoded content stream exceeds 5 MiB before text extraction. Blank pages are
skipped while retaining original page numbers. Encrypted, corrupt, and PDFs with
no readable text are rejected. There is no OCR; text order in multi-column PDFs
and tables depends on the parser and may be imperfect.
See [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).

| Status | Meaning |
| --- | --- |
| 400 | Empty, unreadable, corrupt, encrypted, or otherwise invalid content/filename. |
| 413 | File, extracted text, PDF page count, or decoded page stream exceeds a limit. |
| 415 | Unsupported extension or conflicting type/content. |
| 404 | Requested document does not exist. |
| 422 | Missing multipart field or invalid UUID/pagination. |
| 503 | Database is unconfigured or a database operation failed. |

Rejected uploads create no rows. Successful metadata and all chunks are committed
in one transaction; a database failure rolls the transaction back. Since ingestion
finishes within the request, this milestone does not persist intermediate
`processing` or rejected `failed` rows. Duplicate uploads intentionally create
separate documents; deduplication is deferred.

### Chunking and async processing decisions

`chunk_sections()` uses character windows. For size 1000 and overlap 150, the
first window starts at 0, the next at 850, and so on. The final chunk may be
shorter; it does not emit an unnecessary tail containing only overlap. Empty
windows are omitted. PDF pages are chunked separately so a chunk has one precise
source page. This loses some context across page boundaries, a trade-off to
revisit during retrieval evaluation.

Smaller chunks focus the evidence but may separate a concept from its explanation.
Larger chunks retain context but may dilute relevance and use more LLM context.
Overlap reduces boundary loss while increasing repeated text and storage.
Character count is not token count: a tokenizer may represent code or Unicode
with different numbers of tokens. Fixed windows can split sentences and code
blocks; structural/token-aware splitting is a later quality improvement.
Chunk settings currently come from configuration and are not recorded per document.

The API reads at most `MAX_UPLOAD_BYTES + 1` file bytes to detect oversized files,
then closes the upload handle. FastAPI's multipart parser may spool the incoming
upload before the handler runs: this is a file-processing limit, not a total HTTP
body/network limit. Public deployment needs an upstream request-size limit.
See [FastAPI file uploads](https://fastapi.tiangolo.com/tutorial/request-files/).

The service runs extraction and chunking in a worker thread, then uses the async
SQLAlchemy session for persistence. This keeps blocking parsing off the request
event loop; it does not make PDF parsing faster or create a durable background job.
PDF limits reduce ordinary resource use but cannot guarantee a hard CPU/memory
bound during decompression/parsing. Process isolation/time limits are future work
before accepting hostile public uploads. Original files are not retained; only
metadata and extracted chunks are stored.

### Verification and interview notes

Milestone 3 verification: all 70 tests passed, including 18 PostgreSQL integration
cases; Ruff lint and formatting passed. New checks cover overlap/tail handling,
code indentation, PDF pages/encryption/limits, invalid uploads, exact upload-size
boundaries, stored metadata/chunks, pagination, and database-write rollback.

Explain the ingestion flow as: validate → extract → chunk → atomically persist.
Keep HTTP error translation in API routes, orchestration in the ingestion service,
pure extraction/chunking functions in services, and SQL queries in persistence.
Stable chunk IDs and PDF page references prepare us for source citations; they do
not yet prove an answer is grounded. Embeddings and retrieval begin in Milestone 4.


## Embeddings and semantic search — Milestone 4

Indexing and search use OpenAI `text-embedding-3-small` with 1536-dimensional
vectors. Set `OPENAI_API_KEY` in the ignored root `.env`; no local model server
is required. See [OpenAI vector embeddings](https://developers.openai.com/api/docs/guides/embeddings).
Start PostgreSQL and then the backend:

```sh
cd backend
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:create_app --factory --reload --no-access-log
```

After uploading, use the returned document UUID:

```sh
curl -X POST http://127.0.0.1:8000/documents/DOCUMENT_UUID/index
curl -X POST http://127.0.0.1:8000/search \
  -H 'Content-Type: application/json' \
  -d '{"question":"How can I undo database changes after an error?"}'
```

`POST /documents/{id}/index` returns the document UUID, embedded chunk count,
model identifier, and dimensions. It also works for documents uploaded before
Milestone 4. It processes chunks in ordered batches and replaces embeddings only
after every batch succeeds, in one transaction. An existing document with a
failed re-index retains its previous embeddings. Re-indexing deliberately replaces
all vectors, rather than assuming unchanged text means a provider/model is unchanged.
There is one embedding per chunk, not an embedding history.

`POST /search` embeds the question and returns the closest qualifying chunks,
ordered by cosine distance (default maximum: five). Each match contains the chunk/document UUIDs, filename, chunk
position, optional PDF page, source text, and similarity. Search returns an empty
list when no compatible indexed chunks exist. Questions must contain text and
be at most 2000 characters. Configurable retrieval counts, document filters, and
minimum evidence thresholds were added in Milestone 7; see the controls below.
This route returns retrieved sources only. Use `/questions`, introduced in Milestone 5, for generated answers.

### Important code and design decisions

- `ai/embeddings.py`: a small `EmbeddingProvider` protocol exposes model identity,
  dimensions, and `embed(texts)`. Business logic does not depend on a vendor SDK.
- `ai/openai.py`: an async HTTP adapter sends batches to `/v1/embeddings`,
  requests float vectors and checks input indices before mapping them to chunks.
- The FastAPI lifespan owns and closes one pooled HTTP client. It does not load
  model weights or call OpenAI during health checks or text uploads.
- `services/search.py`: snapshots source data, ends the read transaction before
  waiting on the model, validates all batches, and then performs atomic writes.
- `persistence/search.py`: joins documents and chunks and uses pgvector's cosine
  operator. It excludes null vectors, non-ready documents, other model identifiers,
  and other dimensions. It keeps source identifiers for later RAG citations.

Provider responses are checked for vector count, dimensions, numerical/finite
values, representable magnitudes, and nonzero vectors. Vectors are normalized to
unit length before float32 storage; this preserves direction and avoids storing
underflowed tiny vectors as zeros. Provider HTTP/timeouts/malformed responses are
translated into useful 502 errors without exposing response internals. Database
failures remain 503. Missing documents return 404. No placeholder/hash embeddings
are used in runtime code; known vectors exist only in tests.

The `vector` column intentionally has no fixed dimension. This allows a later
model with a different dimension without changing the column type; search still
filters for the configured dimension and model. Same dimension alone does not
make models compatible. Changing the model requires re-indexing every document.
The stored identity is `openai:MODEL_NAME`. Changing providers, model weights or
dimensions requires re-indexing every document. Old incompatible vectors are
excluded from search; source text remains intact. Silent model alias changes
are not automatically detected. A replacement provider can implement the same protocol.

Exact search compares every compatible indexed vector and is appropriate for the
initial corpus. HNSW/IVFFlat indexes trade speed, memory, and recall and should be
introduced with measurements. A dimension-flexible column would require carefully
scoped/cast indexes for each model/dimension. See [pgvector Python SQLAlchemy support](https://github.com/pgvector/pgvector-python#sqlalchemy).

### Interview explanation

An embedding is a learned numerical representation of text. A query such as
"undo changes after an error" can be close to a passage about transaction rollback,
even if the wording differs. This is semantic search, whereas keyword search
primarily matches words. The model determines what meaning is represented;
storing a vector does not create that meaning.

For vectors **a** and **b**, cosine similarity is their dot product divided by the
product of their lengths: `dot(a, b) / (norm(a) * norm(b))`. It measures alignment
of directions and ranges from -1 to 1. pgvector returns cosine **distance**;
we expose `similarity = 1 - distance`. Higher values are closer, but they are not
probabilities or proof that the passage answers the question. Top-ranked matches
can still be irrelevant; insufficient-evidence handling and evaluation come later.

### Verification

All 90 automated tests passed, including 21 PostgreSQL cases. HTTP mock tests
check provider requests, batch ordering, timeouts, and malformed responses.
Database tests verify cosine ordering with known vectors, compatibility filtering,
atomic failed-batch behaviour, and migration preservation. These deterministic
tests validate engineering behaviour; they do not measure a real model's quality.

A historical Milestone 4 HTTP check uploaded three documents, generated local Ollama
768-dimensional embeddings, stored them in pgvector, and queried a rollback
question. Transaction documentation ranked first (similarity approximately 0.529),
ahead of Docker (0.205) and React (0.186). This is a smoke check, not an evaluation
benchmark. The disposable verification database and API process were removed;
the development database migration preserves existing uploads.


## Basic RAG — Milestone 5

The implemented flow is:

```mermaid
flowchart LR
    Q[Question] --> E[Question embedding]
    E --> R[Retrieve up to 5 pgvector matches]
    R --> C[Bound source excerpts and assign labels]
    C --> P[Evidence-only system prompt plus question and sources]
    P --> L[Local LLM structured response]
    L --> V[Validate markers and resolve citations]
    V --> A[Generated answer and separate source evidence]
```

Answer generation uses `gpt-5.4-mini` through OpenAI's Responses API. Generation
and embedding providers use independent interfaces because they perform different
jobs. GPT writes the answer; the embedding model creates vectors for retrieval.

After uploading and indexing a document, with the API running:

```sh
curl -X POST http://127.0.0.1:8000/questions \
  -H 'Content-Type: application/json' \
  -d '{"question":"How can I undo database changes after an error?"}'
```

`POST /questions` accepts the same validated question shape as `/search`. It
returns `answer`, `status`, `citations`, and the configured `llm_model` and
`embedding_model` identifiers. For example, generated text can say
`To undo changes, issue ROLLBACK [S1].`; citation `S1` separately identifies a real
chunk/document UUID, filename, position, PDF page if available, retrieved excerpt,
similarity, and whether that excerpt was truncated. Citations include only the
sources used in the answer, not every retrieved passage.

### What RAG solves

A direct LLM call has the question and the model's training knowledge. It may lack
private documents, changes made after training, or the correct version of an API.
RAG retrieves relevant evidence at request time and supplies it in the prompt.
The model is not retrained by an upload; knowledge is supplied as temporary context.
This makes document-based answers possible and provides inspectable provenance.
It does not eliminate hallucinations or repair missing/incorrect retrieval.

### Important code

- `ai/llm.py` defines a small `LLMProvider` protocol and typed `GeneratedAnswer`.
- `ai/openai.py` calls the Responses API with system/user messages and a strict
  JSON schema for `answer` and `citation_labels`. It checks completion and refusals;
  structured output does not guarantee factual correctness.
- `services/rag.py` retrieves five matches, snapshots plain source data, releases
  the database read transaction, builds the prompt, calls generation, and resolves
  citation labels. Database connections are not held while waiting for the LLM.
- `api/questions.py` defines the public response and translates that service result
  into JSON. Generation failures are mapped to safe 502 responses by the app.

The context builder caps excerpt text at 5000 characters, assigning `S1`, `S2`,
and so on in retrieval order. A shortened excerpt is explicitly marked truncated.
Question, labels, and sources are serialized as JSON in the user message; the
system message says source content is untrusted data and must not be followed as
instructions. A concrete output example shows both inline `[S1]` markers and the
matching label array. See [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

### Citation and failure contracts

The backend checks that the answer's `[S<number>]` markers match its declared
citation labels and that every label belongs to the actual supplied context.
The model never creates the source UUIDs; the backend resolves them. Unknown or
mismatched references produce a 502 rather than being displayed as a valid answer.
Structured schema errors, provider failures/timeouts, incomplete generation, and
output-limit truncation also produce useful 502 errors without internal responses.

If retrieval produces no source excerpts, the LLM is not called. If the model
returns no citation labels, its uncited text is discarded. Both cases return
HTTP 200 with `status: insufficient_evidence`, a fixed explanation, and no
citations. `status: answered` means generation passed the citation contract;
it is not a verified-groundedness score. This is a minimal safety baseline;
retrieval relevance thresholds and stronger refusal instructions were added in Milestone 7.

Citation validity is not citation correctness: a referenced passage can exist and
still fail to support a claim. We do not currently check every claim for semantic
entailment. Prompt isolation also does not prove immunity to prompt injection.
These limitations must be assessed with the Milestone 8 evaluation dataset.

### Context windows and limitations

An LLM context window limits the tokens it can consider, including instructions,
the question, evidence, and output. The 5000-character excerpt cap bounds common
inputs but is not an exact token budget: code and Unicode tokenize differently.
Tokenizer-aware budgeting and context selection are later quality work. The small
1B model is a convenient local baseline, and can fail citation formatting or
reasoning; provider/model changes can be compared during evaluation.

Each question is independent. There is no chat memory, streaming, agent, document
filter, reranker, duplicate-context removal, or configurable retrieval count in
this milestone. Source documents still need the explicit indexing step before
asking questions. Original document permissions are outside the single-user MVP.

### Verification and interview points

All 111 tests passed, including 24 PostgreSQL integration cases. New tests cover
HTTP provider request/response contracts, malformed/incomplete output, citation
matching, context limits, no-source behaviour, suppression of uncited text, and
real database source-reference resolution. Most tests use deterministic providers
so ordinary checks require neither a model server nor probabilistic answers.

A historical Milestone 5 HTTP check used the local embedding and chat models plus a
disposable PostgreSQL database. It uploaded transaction documentation, indexed it,
asked how to undo changes, and received a ROLLBACK answer with `[S1]` resolving to
the stored source text. An initial model response omitted the inline marker;
validation rejected it. Adding an explicit output-format example resolved that
case while keeping validation strict. This is a smoke check, not a RAG-quality
benchmark. The test API and disposable database were cleaned up.

For interviews, trace the whole pipeline and identify each failure mode: poor
retrieval, lost context, unsupported generation, invalid citations, and provider
errors. Explain that prompt engineering includes instructions, evidence boundaries,
output examples, and response contracts, while backend validation enforces only
what can be checked deterministically. RAG supplies evidence; it does not make a
model inherently truthful.


## Browser workspace — Milestone 6

The frontend is a small React + TypeScript application built with Vite. It uses
component-local state and a single HTTP module; no global state library, router,
UI framework, or AI SDK is needed for this one-page interface.

### Run the interface

Start the database, apply migrations, and run the backend as described above.
Set the backend OpenAI API key for embeddings and answer generation. Configure
OpenAI generation below, or use the local chat-model alternative from Milestone 5. In a separate terminal, from the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open [DevDocs AI](http://127.0.0.1:5173/). From `frontend/`, run:

```sh
npm test
npm run lint
npm run build
# Optional: inspect the production bundle locally (backend still required).
npm run preview
```

Vite forwards `/api/*` to `http://127.0.0.1:8000`, removing the `/api` prefix.
The browser sees same-origin requests, so this local setup needs no backend CORS
change. Preview inherits the proxy; it is a local bundle check, not a production
hosting solution. A production host will need equivalent routing for `/api`.
See [Vite proxy configuration](https://vite.dev/config/server-options.html#server-proxy).
No frontend environment variables or secrets are required. Browser-visible
configuration cannot safely hold database passwords or provider credentials.

### Upload and indexing are two operations

“Upload and index” first saves the document through `POST /documents`, then calls
`POST /documents/{id}/index`. Progress distinguishes extraction from embedding.
If indexing fails, the saved document remains in the library and can be retried
with “Index for search”. Re-indexing does not upload another document.

The list API does not expose persistent embedding status. Therefore `ready` is
shown as “Text ready”, and “Indexed this session” appears only after this browser
has observed successful indexing. Reloading resets those badges; it does not
remove database vectors. Existing documents may already be searchable. The list
uses server pagination in groups of 20, refresh, empty states, and load retries.
With no total count in the API, a completely full final page can lead to an empty
next page; Previous remains available.

Client checks give quick feedback for unsupported extensions, empty files, and
files above the default 10 MiB limit. They are convenience checks, not a security
boundary. The backend still validates actual content and enforces its configured
limits. If the backend upload limit changes, update the UI limit and help text.

### Important React and API concepts

- `App.tsx` composes the document and question panels; each owns its local state.
- `DocumentPanel.tsx` keeps upload/index actions in event handlers. Its effect
  synchronizes the library with the selected page. `AbortController` cleanup and
  an aborted-signal check prevent obsolete requests from changing the displayed
  page. React StrictMode exercises effect cleanup during development.
- `QuestionPanel.tsx` uses a controlled textarea: React state is the displayed
  value. Submission trims the question, prevents duplicate pending submissions,
  clears the prior result, and records which question produced the new answer.
  Loading state disables inputs and explains that local generation can be slow.
- `api.ts` mirrors backend response types, sends multipart uploads using
  `FormData`, and parses FastAPI's string or validation-list errors. The browser
  must supply multipart boundaries. TypeScript helps catch contract mistakes at
  build time; the type assertions are not runtime response-schema validation.
- `AnswerCard.tsx` resolves `[S1]` markers against returned citations. Clicking a
  marker opens the corresponding source and focuses its summary. Excerpts show
  filename, human-readable chunk number, PDF page when available, and truncation.
  Plain React text rendering escapes model/document HTML; no HTML injection or
  Markdown renderer is used. Code and Markdown remain readable raw text.
- Native labels, buttons, disclosure elements, live status messages, alerts, and
  visible focus styles support keyboard and assistive-technology use. The layout
  stacks on narrow screens and requires no external fonts or media.

`insufficient_evidence` is an ordinary answer outcome, displayed without invented
citations. Network/provider failures are errors with retry guidance. Generated
text and retrieved evidence have separate labels; neither a valid reference nor
an “answered” status proves that every claim is supported. Each question remains
independent, and the UI displays the latest result without conversation memory.

### Verification and limits

All 20 frontend tests passed, covering upload/index success, partial failure and
retry without another upload, validation, document-load recovery, pagination and
cancellation, pending question state, insufficient evidence, provider retry,
citation navigation, and safe HTML rendering. HTTP tests cover multipart fields,
question JSON, error variants, network failures, and cancellation. Tests use
Vitest, jsdom, and Testing Library, exercising observable user behaviour rather
than CSS snapshots. Lint and the TypeScript/Vite production build passed. All
111 backend tests, including 24 real PostgreSQL integration cases, also passed.

A historical Milestone 6 browser check uploaded and indexed transaction documentation using real FastAPI,
PostgreSQL/pgvector and Ollama embeddings. Two questions to `llama3.2:1b` returned
invalid citation references; strict backend validation rejected them, and the UI
displayed the useful error and allowed retry. Successful answer rendering and
source navigation were then verified through the same HTTP/retrieval pipeline
with a temporary deterministic LLM substitute. This validates frontend wiring;
it does not demonstrate reliable live generation. Desktop (1280px) and mobile
(390px) checks showed no horizontal overflow. Disposable test databases and the
test generation adapter were removed after verification.

For interviews, explain why upload and indexing need separate failure states,
why frontend validation cannot replace server validation, and why asynchronous
responses can race. Trace a user action through React, HTTP, FastAPI, retrieval,
generation, and citation rendering. Distinguish a recoverable provider failure
from an insufficient-evidence result, and explain why deterministic UI tests and
probabilistic RAG evaluation answer different questions. Quality improvements
were added in Milestone 7 below; evaluation remains Milestone 8.


## OpenAI-only model configuration

The official generation model ID is `gpt-5.4-mini` (hyphens and a dot). Both the
code defaults and `.env.example` use OpenAI. Configure the ignored root `.env`:

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=gpt-5.4-mini
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
OPENAI_API_KEY=your-own-api-key
```

Replace the placeholder locally. Keep the key in the backend environment; never
put it in frontend variables or Git. Restart the backend after changing settings:

```sh
cd backend
uv run --locked uvicorn app.main:create_app --factory --reload --no-access-log
```

For containers, recreate the services using `docker compose up --build --detach
--wait`. The frontend needs no model configuration. Both adapters share an async
`httpx` client, so no new SDK dependency is needed. Generation requests a strict
JSON schema, `reasoning.effort: none`, a 1024-token output cap and `store: false`.
The embedding adapter validates response indices, vector counts, dimensions and
values before storage. Missing keys, quota limits, permissions, transport failures
and malformed responses produce useful errors without exposing provider bodies.
Uploads and health checks still work without an API key. There is no local fallback.

**After switching from the previous embedding model, click “Index for search”
for each existing document.** Source text and metadata remain intact; indexing
atomically replaces old vectors. Search excludes vectors from other models or
dimensions. Comparing vectors from different models is meaningless even when
both produce the same number of dimensions. No database migration is required.
The similarity cutoff is model-dependent and should be assessed again using a
fresh evaluation; the saved Milestone 8 baseline used the previous embeddings.

**Data flow:** indexing sends document chunks to OpenAI; search sends the question
for embedding; generation sends the question and retrieved excerpts. These calls
use your API account. `store: false` disables Responses API response storage;
it does not override other provider data policies. See
[OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).

Mocked tests cover batch ordering, invalid vectors/indices, authentication,
missing keys, quota/transport failures, structured answers and app provider wiring.
They make no paid requests. Historical live checks below describe the providers
used at the time, not a quality measurement for the new embeddings.

For interviews, this is a concrete example of dependency inversion: the RAG
service depends on `LLMProvider`, not a particular vendor. Only the application
composition and provider adapter know whether generation is local or remote.
Embeddings, retrieval, persistence, and the frontend retain their contracts.

Sources: [GPT-5.4 Mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini),
[structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).


## Retrieval and evidence controls — Milestone 7

### Why this change

Nearest-neighbour search always ranks the available vectors, even when none are
useful for the question. Returning more chunks can improve recall (finding needed
evidence), but can also lower precision (the fraction of results that are useful).
Repeated excerpts waste the limited context budget. A model can also encounter
related documentation that does not contain the specific requested detail.

This milestone makes retrieval choices explicit and adds deterministic gates plus
stronger prompt instructions. No evaluation dataset, reranker, hybrid search,
automatic citation repair, agent, or deployment/CI work is added.

### Configuration and API contract

Optional root `.env` settings, with defaults shown:

```dotenv
RETRIEVAL_TOP_K=5
RETRIEVAL_MIN_SIMILARITY=0.35
```

Restart the backend after changing them. Existing question-only requests continue
to work. Both `POST /search` and `POST /questions` accept:

```json
{
  "question": "How do I undo changes after a transaction error?",
  "top_k": 3,
  "document_ids": ["00000000-0000-0000-0000-000000000001"],
  "media_type": "text/markdown"
}
```

Replace the example UUID with an uploaded document's UUID. All fields except
`question` are optional. `top_k` must be an integer from 1 to 20, not a numeric
string, fraction or boolean. An omitted/null count uses the configured default.
`document_ids` accepts 1–50 UUIDs; an empty list is rejected rather than silently
broadening the scope. Missing/nonexistent documents produce no matches.
`media_type` supports `text/plain`, `text/markdown`, and `application/pdf`.
Document IDs and format combine with AND; no result causes automatic filter
relaxation. Invalid options return helpful HTTP 422 validation errors.

Metadata filters and the similarity cutoff apply in PostgreSQL **before** ordering
and limiting. Filtering an already-limited global result set could miss a valid
selected-document match. All existing status/model/dimension checks still apply.
Because SQL predicate evaluation order is not guaranteed, a `CASE` guards the
vector distance calculation itself against incompatible vector lengths. The
existing real-database compatibility test caught this issue when the distance
predicate was introduced. See [SQLAlchemy filtering](https://docs.sqlalchemy.org/en/20/orm/queryguide/select.html).

### Candidate count versus useful context

`/search` returns up to `top_k` ranked, threshold-qualified raw matches. `/questions`
retrieves up to `3 × top_k` candidates (at most 60), then selects at most `top_k`
useful excerpts. This bounded surplus allows duplicates to be discarded without
immediately exhausting every source slot. It does not guarantee enough distinct
results: many duplicates can still consume the candidate pool, and the existing
5000-character context cap may reduce the final source count.

Context construction preserves retrieval order and stable document/chunk IDs:

1. Exclude weak and empty passages.
2. Remove exact duplicate text, normalizing only line endings and boundary newlines.
   Preserve case and indentation; `return True` and `return true` are different.
3. Trim exact shared boundaries of 80–1000 characters between consecutively
   numbered chunks from the same document and PDF page, only when the earlier
   chunk has already been selected. Short coincidental matches are retained.
4. Apply the context budget and assign contiguous `S1`, `S2`, … labels afterwards.

Only prompt excerpts change; stored chunks and embeddings are untouched. A
shortened excerpt is marked `truncated`, including overlap removal. Each excerpt
remains an actual contiguous substring of its source chunk. Reverse retrieval
order, different pages/documents, and fuzzy near-duplicates are deliberately not
merged. More aggressive cleanup could lose version differences or source meaning.
Character budgeting is still a coarse bound, not an exact tokenizer budget.

### Insufficient evidence and prompt changes

If no selected passage reaches the cutoff, generation is skipped. The existing
HTTP 200 `insufficient_evidence` response is returned with a fixed explanation and
no citations. An LLM reply with no citation labels is also replaced with that
explanation, so unsupported model text is not displayed.

The prompt now explicitly distinguishes topic similarity from evidence that
answers the question. It instructs the model to decline when a required detail is
missing, excerpts are irrelevant, or sources conflict about the requested
behaviour. It includes a concrete empty-answer/empty-label refusal example and
asks the model to preserve commands, versions and negation. Citation-reference
validation still runs for every accepted answer. No silent repair or weaker
citation contract is introduced.

The default `0.35` cutoff is an initial engineering heuristic for the local
embedding baseline. Cosine scores are model-dependent and are **not probabilities
of correctness**. A higher cutoff can reject useful evidence; a lower cutoff can
admit irrelevant passages. A relevant-looking excerpt can still omit the requested
answer. Prompt compliance and claim support are probabilistic; this milestone
cannot guarantee refusal or semantic citation correctness. Calibrate and measure
these behaviours using the Milestone 8 evaluation dataset.

### Frontend controls and important code

Select “Use for questions” on a library document to scope the next request to that
document. “Search all documents” clears only the document selection. The format
filter remains explicit; selecting a Markdown document and PDF format yields no
evidence rather than searching elsewhere. The maximum-source input accepts 1–20
or blank for the server default. Pending requests disable question controls, and
the displayed answer retains the scope captured at submission even if the next
question's scope changes. There is still no conversation memory.

- API schemas in `api/search.py` validate shared retrieval options; both routes
  pass options/defaults to services without doing SQL or context cleanup.
- `persistence/search.py` owns SQL scope, model compatibility and cosine filtering.
- `services/rag.py` owns bounded candidate retrieval, deterministic context
  selection, evidence-aware prompts and citation resolution.
- `App.tsx` owns the selected document and passes it to both panels. This is
  lifting state to their common parent; no global store is needed. See
  [React shared state](https://react.dev/learn/sharing-state-between-components).
- `QuestionPanel.tsx` snapshots request options and display scope;
  `api.ts` sends the optional fields through the existing HTTP client.

Document filtering is a search feature, not an authorization boundary. The app
remains a single-user local MVP without tenant isolation or access control.

### Verification

All 180 backend tests passed, including 26 PostgreSQL integration cases. New tests
cover settings/request bounds, route defaults and overrides, filtering before
limit, AND-combined filters, unknown document IDs, weak evidence without an LLM
call, retrieval past duplicate candidates, preserved code distinctions, safe
overlap cleanup, context budgets and citation provenance. The 23 frontend tests
passed, including control serialization, clearing scope/defaults, and keeping a
displayed answer's original scope. Ruff lint/format, ESLint, TypeScript and Vite
build checks passed.

Historical Milestone 7 browser smoke checks used a disposable database, local Ollama embeddings and the
configured `gpt-5.4-mini` on synthetic transaction documentation. The model returned
a ROLLBACK answer with valid `[S1]` references, and the UI opened the original
excerpt. A missing `MAX_RETRY_COUNT` question fell below the retrieval cutoff and
returned insufficient evidence without generation. A related transaction/retry
question retrieved a passage at cosine similarity 0.410 (above the 0.35 cutoff),
but the model declined because no retry count was documented. Combining the
selected Markdown document with a PDF filter also returned insufficient evidence
without widening scope. Desktop/mobile controls had no horizontal overflow. The
disposable database and test server were removed, and the normal backend restored. These are small smoke checks, not evidence of overall retrieval or
answer quality; the dedicated evaluation milestone remains next.

For interviews, explain the precision/recall trade-off in top-k and cutoff tuning,
why metadata filtering must precede limiting, why candidates and final context
are different, and why exact cleanup preserves provenance. Distinguish deterministic
validation from probabilistic evidence judgement and explain why quality must be
measured after changing retrieval settings or prompts.


## Production engineering — Milestone 9

From the repository root, with the ignored `.env` configured:

```bash
docker compose up --build --detach --wait --wait-timeout 120
```

Open <http://localhost:8080>. The migration service completes before the backend
starts, and Nginx serves the compiled frontend and forwards `/api` requests.
Model providers remain separately configured. Application images run as non-root
users with read-only filesystems; document data stays in PostgreSQL's volume.

The [production guide](docs/production.md) explains setup, host/container addresses,
request IDs, privacy-aware logs, safe errors, meaningful tests, CI jobs and their
limitations. CI is configured and statically validated; GitHub-hosted execution
will occur after a push or pull request. No deployment or agent was added.
