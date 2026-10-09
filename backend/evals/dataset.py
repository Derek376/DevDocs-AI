"""Versioned questions and stable evidence quotes, independent of chunk UUIDs."""

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_DATASET = Path(__file__).resolve().parents[2] / "evaluation/dataset.json"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GoldEvidence(StrictModel):
    document: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class Case(StrictModel):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=2000)
    expected_status: Literal["answered", "insufficient_evidence"]
    evidence: list[GoldEvidence]
    reference_answer: str = Field(min_length=1)
    documents: list[str] | None = Field(default=None, min_length=1)


class Dataset(StrictModel):
    version: str = Field(min_length=1)
    documents: list[str] = Field(min_length=1)
    cases: list[Case] = Field(min_length=1)


def normalize(text: str) -> str:
    """Whitespace-insensitive quote matching; not semantic entailment."""
    return " ".join(text.split())


def load_dataset(path: Path) -> tuple[Dataset, dict[str, bytes], str]:
    raw = path.read_bytes()
    dataset = Dataset.model_validate_json(raw)
    if len(set(dataset.documents)) != len(dataset.documents):
        raise ValueError("Duplicate document filenames.")
    if len({case.id for case in dataset.cases}) != len(dataset.cases):
        raise ValueError("Duplicate case IDs.")
    corpus: dict[str, bytes] = {}
    digest = hashlib.sha256(raw)
    root = (path.parent / "corpus").resolve()
    for name in dataset.documents:
        target = (root / name).resolve()
        if target.parent != root or target.suffix != ".md":
            raise ValueError("Corpus documents must be Markdown files inside corpus/.")
        corpus[name] = target.read_bytes()
        digest.update(name.encode())
        digest.update(corpus[name])
    for case in dataset.cases:
        if case.documents is not None and (
            len(set(case.documents)) != len(case.documents)
            or not set(case.documents).issubset(corpus)
        ):
            raise ValueError(f"Invalid document filter in {case.id}.")
        if case.expected_status == "answered" and not case.evidence:
            raise ValueError(f"Answerable case {case.id} needs gold evidence.")
        seen: set[tuple[str, str]] = set()
        for gold in case.evidence:
            key = (gold.document, normalize(gold.quote))
            if (
                gold.document not in corpus
                or not key[1]
                or key in seen
                or key[1] not in normalize(corpus[gold.document].decode("utf-8"))
                or (case.documents is not None and gold.document not in case.documents)
            ):
                raise ValueError(f"Invalid or duplicate gold evidence in {case.id}.")
            seen.add(key)
    return dataset, corpus, digest.hexdigest()
