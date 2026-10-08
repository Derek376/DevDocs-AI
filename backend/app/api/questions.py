"""RAG answers with generated text separate from retrieved evidence."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from app.ai.llm import LLMProvider
from app.api.documents import SessionDependency
from app.api.search import ProviderDependency, SearchRequest
from app.services.rag import answer_question

router = APIRouter(tags=["questions"])


def get_llm_provider(request: Request) -> LLMProvider:
    return request.app.state.llm_provider


LLMDependency = Annotated[LLMProvider, Depends(get_llm_provider)]


class CitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: str
    chunk_id: UUID
    document_id: UUID
    filename: str
    position: int
    source_page: int | None
    text: str
    similarity: float
    truncated: bool


class AnswerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    answer: str
    status: Literal["answered", "insufficient_evidence"]
    citations: list[CitationResponse]
    llm_model: str
    embedding_model: str


@router.post("/questions", summary="Answer a question using indexed documents")
async def ask_question(
    body: SearchRequest,
    session: SessionDependency,
    embeddings: ProviderDependency,
    llm: LLMDependency,
) -> AnswerResponse:
    result = await answer_question(session, body.question, embeddings, llm)
    return AnswerResponse.model_validate(result)
