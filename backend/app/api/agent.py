"""Optional assistant endpoint; the ordinary RAG endpoint remains available."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.tools import ToolName, ToolProvider
from app.api.document_schemas import DocumentResponse
from app.api.documents import SessionDependency
from app.api.questions import CitationResponse
from app.api.search import ProviderDependency
from app.services.agent import run_agent
from app.services.search import DocumentNotFoundError

router = APIRouter(prefix="/agent", tags=["agent"])


def get_tool_provider(request: Request) -> ToolProvider:
    return request.app.state.llm_provider


ToolDependency = Annotated[ToolProvider, Depends(get_tool_provider)]


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    selected_document_id: UUID | None = None

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must contain non-whitespace text.")
        return value.strip()


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    answer: str
    status: Literal[
        "answered", "insufficient_evidence", "metadata", "selection_required"
    ]
    citations: list[CitationResponse]
    llm_model: str
    embedding_model: str
    tool: ToolName
    document: DocumentResponse | None
    context_truncated: bool


@router.post("/questions", summary="Choose one read-only documentation tool")
async def ask_agent(
    body: AgentRequest,
    request: Request,
    session: SessionDependency,
    embeddings: ProviderDependency,
    agent: ToolDependency,
) -> AgentResponse:
    try:
        result = await run_agent(
            session,
            body.question,
            body.selected_document_id,
            embeddings,
            agent,
            request.app.state.settings,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AgentResponse.model_validate(result)
