# Simple documentation assistant — Milestone 10

The optional assistant chooses one of three read-only tools with `gpt-5.4-mini`.
The ordinary `/questions` RAG endpoint remains the default. This extends the existing
FastAPI/OpenAI stack: no agent framework, local model, extra dependency, database
migration, background worker or multi-agent system is needed.

## Try it

Start the backend and frontend using the commands in the root README. Choose
**Choose a documentation tool** under **Assistant mode** in the question panel.
Use the library's **Use for questions** button to select a document.

| Request | Expected tool | Evidence / prerequisite |
| --- | --- | --- |
| “How do I discard uncommitted changes?” | `retrieve_documentation` | Indexed chunks, semantic search and the normal evidence cutoff |
| “Show this document's file size, format and chunk count.” | `inspect_document_metadata` | Selected document; verified PostgreSQL fields |
| “Summarize the selected document.” | `summarize_document` | Selected document with ready stored text; indexing is unnecessary |

These are expected choices, not guaranteed classification accuracy. The UI displays
the action actually used. Without a selection, metadata/summary requests return
`selection_required` and ask the user to choose a document. A selected document
restricts retrieval to that document. Agent retrieval uses server defaults for
top-k and similarity; the ordinary Q&A mode retains its per-request controls.

```bash
curl http://127.0.0.1:8000/agent/questions \
  -H 'Content-Type: application/json' \
  -d '{"question":"Summarize this document","selected_document_id":"DOCUMENT_UUID"}'
```

Replace `DOCUMENT_UUID` with an uploaded document's UUID. Swagger at `/docs` also
provides the request/response schema. The response includes `answer`, `status`,
`citations`, model identifiers, `tool`, verified `document` metadata where relevant,
and `context_truncated`. A missing selected document is 404; bad request fields
are 422; provider/invalid tool/citation failures are useful 502 errors with the
existing request ID. Database errors keep the existing 503 contract.

## LLM calls, RAG, tool calling and agents

| Concept | What it does in this project |
| --- | --- |
| Normal LLM call | Sends instructions/input to a model to generate text; the model does not automatically read our database |
| RAG | A fixed program embeds the question, retrieves relevant chunks, builds context, then generates and validates a cited answer |
| Tool calling | The model returns a named function request and JSON arguments; application code validates and executes it |
| Agent | A bounded orchestration layer lets the model choose the next operation, executes it, and uses the observed result to respond |

This is a **single-step agent**. Each request allows one decision and one tool.
Retrieval and summary then allow one final generation call; metadata is returned
directly without an LLM rewrite. The model never executes Python, SQL, commands,
network addresses or arbitrary code. There is no repeat-until-success loop,
automatic repair retry, conversation memory, persistent plan or autonomous work.
It cannot combine metadata, retrieval and summary in one request; ask separately.

The provider sends strict function schemas to the Responses API with
`tool_choice: required` and `parallel_tool_calls: false`. It validates the
completed output contains exactly one allowlisted function call and typed
arguments. Strict schemas constrain shape; they do not grant authority.
The service independently checks that `document_id` exactly equals the user's
selection, including null. A model cannot invent an ID or widen the chosen scope.

For content tools, the final request contains the function call and a
`function_call_output` with the matching `call_id`. The tool output contains only
bounded source snapshots and coverage information; it is untrusted evidence, not
instructions. A strict `GeneratedAnswer` schema controls the final shape, and
`resolve_citations` verifies labels against the exact supplied excerpts. An empty
retrieval or uncited generation returns the fixed insufficient-evidence response.
Metadata is displayed as **Verified database fields**, separate from generated
text and source excerpts. These controls follow the official
[OpenAI function calling guide](https://developers.openai.com/api/docs/guides/function-calling).

## Important code and decisions

- `backend/app/ai/tools.py`: provider-independent `ToolProvider`, the three names,
  strict `ToolArguments` and a concrete routing prompt. Arguments carry only the
  selected document ID; the application retains the original user question.
- `backend/app/ai/openai.py`: shares authenticated HTTP/error handling between
  ordinary generation, tool selection and final tool-result generation. It uses
  the existing model configuration and `store: false`, with no silent fallback.
- `backend/app/services/agent.py`: validates the decision and dispatches explicit
  branches. No dynamic function lookup, execution or model-controlled database
  query is used. It reuses the existing semantic search, context construction
  and citation validation rather than making a second RAG implementation.
- `backend/app/persistence/documents.py`: reads one selected document and its chunk
  count. ORM values become immutable snapshots before rolling back the read
  transaction. Database connections are not held while waiting on either LLM call.
- `backend/app/api/agent.py`: validates HTTP inputs, injects providers/session,
  returns the typed response and handles missing documents. Business decisions
  remain in the service.
- React's existing question panel offers the opt-in mode. Answer results retain
  their action and selection even if the next request's controls change. The
  existing safe text rendering, loading/error handling and citation navigation
  remain in use.

Summaries read the first **five chunks** in document order and supply at most
**5000 excerpt characters**, reusing overlap/duplicate cleanup. This is a bounded
excerpt summary, not whole-document summarization for large documents. Omitted
chunks or shortened excerpts set `context_truncated`; the UI shows a coverage
notice independently of what the model says. Omitted duplicate chunks can also
conservatively mark coverage as partial. Summary citations have `similarity: null`
because they were selected in document order, not by semantic similarity. Retrieval
citations still contain their actual score. Character limits are not token limits.

Metadata/summary require no embedding requests. Routing still sends the user's
question and selected UUID to OpenAI; summarization sends the selected excerpts.
Content routes usually cost two generation calls, so choosing a tool adds latency
and API usage compared with the fixed RAG route. Ordinary Q&A remains the default
for that reason. Per-call timeouts and output caps remain in configuration/code.

## Verification and limits

263 backend tests passed, including 30 real PostgreSQL integration cases. The
29 frontend tests, Ruff, ESLint, TypeScript/Vite and both Docker image builds passed.
Tests exercise all three branches, scope tampering, unknown/multiple/malformed
calls, missing selection/documents, no evidence, invalid/uncited answers,
transaction release before model calls, and summary chunk/character boundaries.
UI tests cover metadata separation, partial coverage, source navigation and mode
changes; HTTP tests cover the new request shape.

A live `gpt-5.4-mini` check selected all three expected tools using a tiny synthetic
transaction document in a disposable database. Metadata matched stored fields;
a cited summary worked before indexing; after indexing, the retrieval tool
returned a cited ROLLBACK answer. The disposable database was removed. No normal
application documents were modified. This smoke check establishes API wiring,
not broad routing accuracy or groundedness. The historical Milestone 8 scores do
not evaluate this new agent or the current embedding model. Model decisions and
semantic citation correctness remain probabilistic; inspect the actual evidence.

## Exact file manifest

Created:

- `backend/app/ai/tools.py`
- `backend/app/api/agent.py`
- `backend/app/services/agent.py`
- `backend/tests/test_agent.py`
- `backend/tests/test_agent_api.py`
- `backend/tests/test_openai_tools.py`
- `docs/agent.md`

Changed:

- `README.md`
- `backend/app/ai/openai.py`
- `backend/app/api/questions.py`
- `backend/app/main.py`
- `backend/app/persistence/documents.py`
- `backend/app/services/rag.py`
- `backend/tests/integration/test_database.py`
- `frontend/src/api.ts`
- `frontend/src/api.test.ts`
- `frontend/src/App.test.tsx`
- `frontend/src/components/QuestionPanel.tsx`
- `frontend/src/components/AnswerCard.tsx`
- `frontend/src/styles.css`

## Interview talking points

Explain that a function call is a model **request**, not execution or permission.
Describe why a server allowlist and scope validation are necessary even with a
strict schema. Trace a selected tool through the service to persistence and back
to `function_call_output`; explain the role of `call_id`. Explain how a one-tool
budget bounds cost and behaviour, why metadata does not need generation, and why
summarization can use stored text without embeddings. Distinguish valid citation
identifiers from factual support, and a partial excerpt summary from complete
document coverage. Explain how deterministic tests and live quality evaluation
answer different questions.

Suggested commit: `feat: add bounded documentation agent with three read-only tools`
