# Production engineering — Milestone 9

The application now has service images, an ordered Compose startup, CI checks,
structured application logging and safe API error handling. It remains a local,
single-user MVP. These foundations do not add authentication, tenant isolation,
TLS termination, backups, deployment or an agent.

## Run the containers

Use Docker Engine/Desktop with Docker Compose v2 or newer. Keep your existing
ignored root `.env`; if starting fresh, copy `.env.example` to `.env` and set
`POSTGRES_PASSWORD`. For OpenAI embeddings and generation, set `LLM_PROVIDER=openai`,
`LLM_MODEL=gpt-5.4-mini` and `OPENAI_API_KEY` there. Model names and keys belong
in runtime configuration, not Dockerfiles or build arguments.

From the repository root:

```bash
docker compose up --build --detach --wait --wait-timeout 120
docker compose ps --all
docker compose logs --follow backend
```

- UI: <http://localhost:8080>
- Backend documentation: <http://localhost:8000/docs>
- Backend liveness: <http://localhost:8000/health>
- Database readiness through the frontend proxy: <http://localhost:8080/api/ready>

The frontend serves the built Vite bundle, not a development server. Nginx strips
`/api/` when forwarding to FastAPI. Same-origin requests avoid needing CORS for
this deployment. Use the direct backend URL for Swagger documentation.

Compose starts PostgreSQL, waits for its health check, runs `alembic upgrade head`
in a one-shot migration container, then starts the backend. The frontend waits
for backend database readiness. A failed migration prevents the backend from
starting. Separate migrations avoid multiple API workers racing to migrate a
schema; this project still runs one API worker. Alembic is also how later schema
changes are applied to an existing volume.

The container backend uses `POSTGRES_HOST=db` and port 5432. The host-side database
port can differ. `BACKEND_PORT` and `FRONTEND_PORT` change the published ports;
all three services publish only on `127.0.0.1`. Stop local servers occupying those
ports or choose different ports before starting Compose. The default project
reuses its existing `postgres_data` volume, so existing uploaded documents persist.

Stop without deleting data:

```bash
docker compose down
```

Do not add `--volumes` to the normal project unless you intend to erase its
database. Docker images and containers are replaceable; a volume holds durable
document text and vectors. Changing `.env` passwords does not reset credentials
inside an already initialized PostgreSQL volume.

## External model services

The backend uses OpenAI for both `text-embedding-3-small` embeddings and
`gpt-5.4-mini` generation. No local model server, downloaded model weights or
host gateway is required. The API key is read at runtime from the ignored root
`.env` and is never passed to the frontend or image builds.

After changing from the previous embedding model, re-index existing documents
using the UI's “Index for search” button. The stored text is preserved; old vectors
are excluded from retrieval by model and dimension until replaced. The vector
column already supports different dimensions, so no schema migration is needed.
Indexing sends chunks to OpenAI, and questions use its embedding and generation
APIs. See [the model configuration](../README.md#openai-only-model-configuration).

Liveness checks whether the API process responds. Readiness checks database
connectivity. Neither downloads models, spends API credits nor certifies that an
AI provider is healthy. Provider problems return useful 502 responses at indexing
or question time. An unhealthy Compose container is reported as unhealthy; health
checks alone do not restart it. `unless-stopped` restarts an exited application
process, not a temporarily failing external provider.

## Build and configuration decisions

- Backend dependencies are installed from `uv.lock` using `uv sync --locked
  --no-dev`. Only the environment, application and migrations enter the runtime
  image. Test/lint tooling and uv itself stay out of the final stage.
- The frontend build stage uses `npm ci` and runs TypeScript/Vite. The final image
  contains Nginx and static assets; Node and npm stay in the build stage.
- Both application images run as non-root users. Compose makes their filesystems
  read-only and provides writable temporary storage. Application capabilities are
  dropped and privilege escalation is disabled. PostgreSQL retains its writable
  data volume and normal image initialization behaviour.
- Build contexts are allowlisted. Root `.env`, local virtual environments,
  dependencies, evaluation outputs and uploads are excluded. No source directory
  is bind-mounted into a deployed application container.
- Only backend/migration services receive `.env`. Compose overrides their database
  host/port and container model URL. The frontend receives no credentials, and
  there are no browser-visible `VITE_*` secrets. Container environment variables
  are still visible to someone with Docker access; they are not a secret vault.
- Dependency locks and pinned action commits constrain changes. Base image tags
  can still receive updates; a stricter release process would record image digests.

Nginx supports a 12 MiB total request body, allowing multipart overhead around
the default 10 MiB file limit. FastAPI independently validates file contents and
configured limits. If you raise `MAX_UPLOAD_BYTES`, adjust the proxy ceiling and
frontend guidance deliberately. API proxy reads time out after 300 seconds;
large synchronous indexing jobs can exceed this. Queued processing would be a
separate design change, not an implicit guarantee from Docker.

Nginx returns JSON for its own API gateway failures and oversized requests.
Backend error responses pass through unchanged. Missing assets return 404 rather
than the SPA HTML. Versioned asset URLs can be cached for a year; HTML requires
revalidation. Dynamic Docker DNS lets Nginx rediscover a recreated backend.

## Logs and failures

Every backend HTTP response has a fresh `X-Request-ID`; incoming IDs are ignored.
The frontend displays a valid reference with failed requests, which can be matched
to a `request_completed` JSON application log. Fields include UTC timestamp,
level, method, route template, status, duration and optional exception class.
`LOG_LEVEL` accepts `DEBUG`, `INFO`, `WARNING` or `ERROR`. Startup/shutdown events
are logged as well. Container log files are limited to three 10 MiB files for
each application service.

Application logs omit raw paths, query strings, request/response bodies, filenames,
questions, secrets, SQL parameters and exception messages/tracebacks. Uvicorn and
Nginx access logging are disabled in containers to avoid a second raw-URL log.
Server/database/proxy lifecycle and diagnostic logs are separate from these
application JSON records. Nginx diagnostic errors may include request URLs; never
put credentials in URL parameters.

Known errors retain their useful messages: invalid uploads are 400/413/415,
request validation is 422, provider failures are 502, and database failures are
503. Validation responses retain field locations/messages/types without echoing
submitted input. Unexpected failures before response headers become safe JSON
500 responses with a request ID. The boundary consumes that exception so Uvicorn
does not also print sensitive original details. It still records the exception
class and failed route. This deliberately trades raw traceback detail for privacy;
reproduce a failure locally with a debugger for deeper diagnostics.

After response headers have been sent, a new 500 response cannot legally replace
them. The middleware propagates a sanitized error and logs the original exception
class. The client can see an interrupted response. This is tested; it is relevant
when streaming or background work is added later.

For local CLI development, use:

```bash
cd backend
uv run --locked uvicorn app.main:create_app --factory --reload --no-access-log
```

## CI and verification

`.github/workflows/ci.yml` runs on pushes and pull requests with read-only repository
permissions and official actions pinned to verified commits. It has three jobs:

1. Backend: Python 3.12, locked dependencies, Ruff lint/format, all pytest tests
   including a disposable pgvector PostgreSQL service, and dataset validation.
2. Frontend: Node 24, `npm ci`, ESLint, Vitest, TypeScript and the Vite build.
3. Containers: builds both images, starts Compose with disposable public test
   credentials, verifies migrations/readiness and runs an HTTP smoke check.
   A blank OpenAI key verifies a useful configuration error without an API call.
   Services and their test volume are removed even if the job fails.

CI requires no real OpenAI key. It does not execute paid model
evaluation, deploy an application or publish images. Passing engineering checks
does not establish RAG quality; Milestone 8's reviewed evaluation serves that
different purpose. CI protects changes only when checks actually run; GitHub
branch protection would need to require them separately.

After the OpenAI-only change, 221 backend tests passed, including 27 PostgreSQL
integration cases. Ruff lint/format, dataset validation, both Docker image builds
and the container smoke passed. The unchanged frontend previously passed its 25
tests, ESLint and TypeScript/Vite checks. GitHub-hosted CI has not yet run.

A disposable stack with no model server indexed a synthetic transaction document
using `openai:text-embedding-3-small` (1536 dimensions), retrieved it through Nginx,
and generated “Use ROLLBACK to discard uncommitted changes. [S1]” with
`openai:gpt-5.4-mini`. The answer passed source citation validation. This small
integration check verifies the API wiring, not general RAG quality. The missing-key
check returned a useful 502 without sending an OpenAI request. The disposable
stack and its database were removed; normal application documents were untouched.

The gateway-down check returned useful JSON. The oversized-request check exposed
Nginx error-page inheritance: declaring location-level 5xx handlers removed the
server-level 413 handler. The API location now explicitly includes the 413 handler,
and the smoke script guards that behaviour without transmitting a large body.

The smoke script uploads synthetic data and is intended for a disposable project:

```bash
POSTGRES_PORT=15433 BACKEND_PORT=18000 FRONTEND_PORT=18080 OPENAI_API_KEY= docker compose --project-name devdocs-ci-smoke up --build --detach --wait --wait-timeout 120
python3 scripts/smoke_compose.py --base-url http://127.0.0.1:18080 --expect-provider-unavailable
POSTGRES_PORT=15433 BACKEND_PORT=18000 FRONTEND_PORT=18080 docker compose --project-name devdocs-ci-smoke down --volumes
```

That last command deletes **only the named disposable project's data**. Keep its
project name distinct from normal development. Root `.env` is still required;
the blank key prevents the script from calling OpenAI or spending model credits.

## Interview explanations

Explain why multi-stage builds separate compilation dependencies from runtime,
why containers require service DNS rather than host loopback, and why persistent
volumes differ from disposable containers. Distinguish liveness, readiness and
provider availability. Explain how a request ID helps reproduce a UI failure
without logging private document content. Describe CI's unit/integration/container
checks and why mocked AI tests verify engineering behaviour while live reviewed
evaluation assesses probabilistic output quality. This is CI; automated deployment
would add the CD part later.

Implementation references: [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/),
[Compose startup ordering](https://docs.docker.com/compose/how-tos/startup-order/),
[Starlette middleware](https://www.starlette.io/middleware/),
[Nginx upstream DNS resolution](https://nginx.org/en/docs/http/ngx_http_upstream_module.html),
and [uv in GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/).
