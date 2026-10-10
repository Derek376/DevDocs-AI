# Verification guide

Run these checks from a configured local clone. Unit and frontend tests use fake
providers: they do not spend API credits. Never paste a real key into a test command.

## Backend

From `backend/`:

```bash
uv sync --locked
uv run --locked ruff check . ../scripts
uv run --locked ruff format --check . ../scripts
uv run --locked pytest -q
uv run --locked python -m evals validate
```

Without `TEST_DATABASE_URL`, the 30 PostgreSQL integration tests skip explicitly.
For the full suite, start the database (`docker compose up --detach db` from the
repository root), then run this from `backend/`:

```bash
uv run --locked python - <<'PY'
import os
import pytest
from app.core.config import Settings

# Read the ignored .env; do not print the connection string or password.
os.environ['TEST_DATABASE_URL'] = Settings().database_url.render_as_string(
    hide_password=False
)
raise SystemExit(pytest.main(['-q']))
PY
```

The integration fixture uses that connection to create random `devdocs_test_*`
databases, apply real migrations and install pgvector. It drops those databases
on teardown; it does not migrate or clear the configured application database.
Use a local test PostgreSQL role with database creation and extension privileges,
never production credentials. If your existing database uses a different password,
fix your local configuration rather than deleting its volume.

Tests cover extraction limits, chunk boundaries, embedding validation, atomic
indexing, compatible-vector retrieval, evidence budgets, citation rejection,
provider errors, agent scope validation, migrations and HTTP error contracts.
A passing mock-provider test establishes application behavior, not LLM accuracy.

## Frontend

From `frontend/`:

```bash
npm ci
npm test
npm run lint
npm run build
```

Interaction tests exercise upload/index failures, scope controls, citations,
loading states and assistant results. The build includes TypeScript checking.

## Containers and live demo

Follow [the Docker setup](../README.md#quick-start-with-docker), then the
[reproducible demo](demo.md). The smoke script uploads a synthetic fixture and
leaves it in its target database, so run it against a disposable Compose project:

```bash
python scripts/smoke_compose.py --base-url http://127.0.0.1:18081
```

The normal smoke checks proxy routing, readiness, validation, upload, listing and
chunk persistence. Live indexing and generated answers are checked separately by
the browser demo. `--expect-provider-unavailable` additionally tests safe AI error
responses when the backend intentionally has no API key, as in the container CI job.

## Recorded Milestone 11 checks

263 backend tests, including 30 PostgreSQL integration tests, and 29 frontend
tests passed locally. Ruff lint/format, ESLint, TypeScript/Vite build, evaluation
fixture validation, Docker image builds and isolated Compose startup/smoke passed.
The live demo used OpenAI embeddings and generation; screenshots preserve those
specific results. These checks are not a current-model evaluation dataset or a
claim that all future model answers will be correct.

[CI configuration](../.github/workflows/ci.yml) runs backend, frontend and container
checks without paid API calls. Confirm its hosted run in GitHub before claiming
CI passed remotely. [Evaluation methodology and historical baseline](../evaluation/README.md)
explain the separate manual quality assessment.
