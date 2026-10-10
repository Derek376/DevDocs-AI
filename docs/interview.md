# Explaining DevDocs AI in an interview

## A 60-second project explanation

“I built a documentation assistant with React, FastAPI and PostgreSQL. Uploaded
files are validated, extracted and split into overlapping chunks. A separate
indexing operation embeds those chunks with OpenAI and stores vectors alongside
relational metadata in pgvector. For each question, the backend embeds the query,
retrieves compatible chunks by cosine similarity, builds a bounded context and
asks GPT-5.4 mini for a structured answer. It validates citation labels and returns
the answer separately from inspectable source excerpts. I also added a bounded,
read-only tool assistant, deterministic failure tests, real database integration
tests, Docker startup ordering and GitHub Actions CI. The key limitation is that
valid citations do not prove semantic correctness; retrieval and grounding need
separate evaluation.”

Adapt this to what you can personally explain and demonstrate. Be candid about
AI-assisted development and the engineering decisions you reviewed yourself.

## Concepts and concrete implementation decisions

| Interview topic | Explanation and project evidence |
| --- | --- |
| Embeddings | Numeric representations that place related text near each other. The same model and dimensions must be used for document and query vectors. Changing embedding models requires re-indexing. See [provider validation](../backend/app/ai/embeddings.py). |
| Vector database | Stores vectors and supports similarity queries. pgvector lets this project keep vectors, source text and metadata in one transactional PostgreSQL database. See [models](../backend/app/persistence/models.py). |
| Cosine similarity | Compares vector directions; cosine distance is `1 - similarity`. A high score describes a relationship between texts, not the probability that an answer is correct. See [retrieval query](../backend/app/persistence/search.py). |
| Semantic search | Can match related meanings without identical keywords. It can still miss exact identifiers or return plausible but irrelevant text. Exact vector scanning is adequate here; approximate indexes and hybrid search require measurement first. |
| Chunking | Defaults are 1000 characters with 150-character overlap. Small chunks improve focus but lose context; large chunks preserve context but add noise. Overlap helps boundary coverage and introduces redundancy. This implementation is character-based, not token-aware. See [chunking](../backend/app/services/chunking.py). |
| RAG | Retrieves external evidence before generation. It supplies current, private corpus information and source provenance that a bare model call lacks. It does not retrain the model or guarantee factuality. See [RAG orchestration](../backend/app/services/rag.py). |
| Hallucination | A fluent unsupported claim. Missing retrieval, misleading documents or generation errors can cause it. Abstention and citation checks reduce some failures; manual claim-to-source review remains necessary. |
| Prompt engineering | Describe the task, allowed evidence, abstention and output contract clearly. Structured output controls shape; service validation controls allowed references. Neither alone proves that evidence supports a claim. |
| Context window | The model has a finite token budget for input and output. This project budgets evidence to 5000 characters, which is only a rough proxy for tokens. Too much retrieved context also creates noise. |
| Retrieval quality | Top-k, filters, thresholds, duplicate removal and overlap trimming affect which evidence reaches generation. Evaluate evidence recall and irrelevant results separately from answer quality. |
| LLM API | A remote dependency with latency, rate limits, cost and malformed/error responses. Adapters handle timeouts and validate responses behind typed provider contracts. See [OpenAI adapter](../backend/app/ai/openai.py). |
| Async processing | Awaiting HTTP/database I/O allows other requests to progress. CPU-heavy extraction uses a thread pool. Async endpoints do not create a durable job queue or make expensive work free. |
| REST API | HTTP verbs and status codes describe operations: upload returns 201, validation returns 422, upstream model failures return useful errors. Separate upload/index requests make retries explicit. See [API guide](api.md). |
| Database design | Documents own ordered chunks through a foreign key. Text and embeddings persist together; an index replacement is atomic only after all generated vectors validate. Keep transactions short across external model calls. |
| Testing | Fake providers deterministically test failures and citation contracts; real PostgreSQL tests check SQL, migrations and rollback behavior. Browser smoke checks wiring; evaluation checks AI quality. They answer different questions. |
| Docker | Builds reproducible service environments. Compose waits for database health and successful migrations before serving requests. Containers are disposable; the database volume holds durable data. |
| CI/CD | CI runs tests, lint and builds automatically. This project has CI and manual deployment, rather than an automatic deployment pipeline. A committed workflow is not proof of a successful hosted run. |

## Normal LLM call, RAG, tool calling and an agent

A normal call sends a prompt and receives generated output. RAG adds a predefined
retrieval step before that generation. Tool calling lets a model propose a named
operation and arguments; application code validates and executes it. An agent uses
model decisions to choose actions toward a task. This project's agent chooses
exactly one of three read-only tools, then produces metadata or a grounded result.
It has no autonomous loop, arbitrary execution, writes or conversation memory.
See [the agent guide](agent.md) and [service](../backend/app/services/agent.py).

## Questions to practise with the repository open

- Trace upload → extraction → chunks → atomic indexing → question → cited answer.
- Explain what happens if the second embedding batch fails during re-indexing.
- Show why incompatible embedding models cannot enter the same retrieval result.
- Explain why a valid `[S1]` marker can still accompany an unsupported statement.
- Contrast a metadata result from database facts with a model-generated summary.
- Explain what needs to change for private, multi-user production deployment.
- Distinguish unit tests, database integration tests, live smoke and AI evaluation.

## Be precise about results and limitations

The historical nine-question baseline used a previous embedding model. Its scores
cannot establish current OpenAI embedding quality or agent quality. Show the
[saved evaluation and review](../evaluation/README.md), identify that limitation,
and propose a fresh, larger evaluation before tuning thresholds. Demo screenshots
show real examples, not a benchmark. Do not invent throughput, latency, cost or
accuracy measurements.

The current system has no authentication, tenant isolation, backups or durable
background jobs. Explain the [architecture trade-offs](architecture.md), then
prioritize current-model evaluation and reliable ingestion before adding features.
