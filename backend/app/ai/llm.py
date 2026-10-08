"""Replaceable generation contract, independent of retrieval and persistence."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class LLMError(RuntimeError):
    """Safe generation or response-contract error."""


class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    answer: str = Field(max_length=8000)
    citation_labels: list[str] = Field(max_length=5)


class LLMProvider(Protocol):
    model_id: str

    async def generate(
        self, system_prompt: str, user_prompt: str
    ) -> GeneratedAnswer: ...
