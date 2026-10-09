"""Evaluation must expose failures, missing judgements and stale reviews."""

import copy
import json
from pathlib import Path

import pytest

from evals.dataset import DEFAULT_DATASET, Case, load_dataset
from evals.metrics import (
    Review,
    citation_validity,
    retrieval_metrics,
    review_template,
    score_report,
)


def example_report() -> dict:
    source = {"label": "S1", "filename": "guide.md", "text": "Timeout is 30 seconds."}
    return {
        "cases": [
            {
                "case_id": "timeout",
                "expected_status": "answered",
                "status": "answered",
                "answer": "Timeout is 999 seconds [S1].",
                "context": [source],
                "citations": [source],
                "retrieval": {"precision": 1.0, "evidence_recall": 1.0},
            }
        ],
    }


def completed_review(report: dict) -> dict:
    review = review_template(report)
    review["reviewer"] = "Test reviewer"
    review["cases"][0].update(
        complete=True,
        claims=[
            {
                "text": "Timeout is 999 seconds [S1].",
                "supported": False,
                "citations": [{"label": "S1", "supports_claim": False}],
            }
        ],
    )
    return review


def test_valid_citation_is_not_groundedness_or_correctness() -> None:
    report = example_report()
    score = score_report(report, Review.model_validate(completed_review(report)))
    assert score["citation_validity"] == 1
    assert score["groundedness"] == 0
    assert score["citation_correctness"] == 0
    assert score["reviewed_claims"] == score["reviewed_citation_pairs"] == 1


def test_pending_review_does_not_invent_semantic_scores() -> None:
    report = example_report()
    score = score_report(report, Review.model_validate(review_template(report)))
    assert score["groundedness"] is None
    assert score["citation_correctness"] is None
    assert score["review_complete"] is False


def test_atomic_claim_can_use_its_shared_sentence_end_citation() -> None:
    report = example_report()
    review = completed_review(report)
    review["cases"][0]["claims"][0]["text"] = "Timeout is 999 seconds"
    score = score_report(report, Review.model_validate(review))
    assert score["groundedness"] == 0
    assert score["claim_citation_coverage"] == 1


def test_partial_reviews_show_the_denominator() -> None:
    report = example_report()
    second = copy.deepcopy(report["cases"][0])
    second["case_id"] = "second"
    report["cases"].append(second)
    review = completed_review(report)
    score = score_report(report, Review.model_validate(review))
    assert score["answered_cases"] == 2
    assert score["reviewed_answers"] == 1
    assert score["review_complete"] is False
    assert score["reviewed_claims"] == 1


def test_recording_preserves_context_when_generation_fails() -> None:
    import asyncio

    from app.ai.llm import LLMError
    from evals.runner import RecordingLLM

    class FailedLLM:
        model_id = "test:failed"

        async def generate(self, system_prompt: str, user_prompt: str):
            raise LLMError("Safe provider error")

    recorder = RecordingLLM(FailedLLM())
    context = [{"label": "S1", "filename": "guide.md", "text": "Evidence"}]
    with pytest.raises(LLMError):
        asyncio.run(recorder.generate("system", json.dumps({"sources": context})))
    assert recorder.context == context


def test_refusal_is_not_perfect_groundedness() -> None:
    report = example_report()
    report["cases"][0].update(
        status="insufficient_evidence",
        answer="No evidence.",
        citations=[],
        retrieval=None,
    )
    score = score_report(report)
    assert score["expected_status_accuracy"] == 0
    assert score["citation_validity"] is None
    assert score["groundedness"] is None
    assert score["citation_correctness"] is None


def test_errors_count_as_status_failures_not_refusals() -> None:
    report = example_report()
    report["cases"][0].update(status="error", retrieval=None)
    score = score_report(report)
    assert score["errors"] == 1
    assert score["expected_status_accuracy"] == 0
    assert score["retrieval_precision_macro"] is None


def test_changed_run_rejects_old_review() -> None:
    report = example_report()
    review = Review.model_validate(completed_review(report))
    report["cases"][0]["answer"] = "Different answer [S1]."
    with pytest.raises(ValueError, match="different report"):
        score_report(report, review)


@pytest.mark.parametrize(
    "change",
    ["missing", "duplicate", "unknown", "empty", "pending", "marker", "no_reviewer"],
)
def test_invalid_completed_review_is_rejected(change: str) -> None:
    report = example_report()
    review = completed_review(report)
    claim = review["cases"][0]["claims"][0]
    if change == "missing":
        review["cases"] = []
    elif change == "duplicate":
        review["cases"].append(copy.deepcopy(review["cases"][0]))
    elif change == "unknown":
        claim["text"] = "An invented claim [S1]."
    elif change == "empty":
        review["cases"][0]["claims"] = []
    elif change == "pending":
        claim["supported"] = None
    elif change == "marker":
        claim["citations"] = []
    else:
        review["reviewer"] = ""
    with pytest.raises(ValueError):
        score_report(report, Review.model_validate(review))


def test_wrong_source_provenance_fails_automated_validity() -> None:
    result = example_report()["cases"][0]
    result["citations"] = [{"label": "S1", "text": "Invented evidence"}]
    assert citation_validity(result) is False


def test_unique_evidence_recall_and_unpadded_precision() -> None:
    case = Case.model_validate(
        {
            "id": "two",
            "question": "Two facts?",
            "expected_status": "answered",
            "reference_answer": "A and B",
            "evidence": [
                {"document": "guide.md", "quote": "fact A"},
                {"document": "guide.md", "quote": "fact B"},
            ],
        }
    )
    sources = [
        {"filename": "guide.md", "text": "fact\nA"},
        {"filename": "guide.md", "text": "fact A"},
        {"filename": "other.md", "text": "fact B"},
    ]
    assert retrieval_metrics(case, sources) == {
        "precision": 2 / 3,
        "evidence_recall": 0.5,
    }
    assert retrieval_metrics(case, []) == {"precision": 0, "evidence_recall": 0}
    case.evidence = []
    assert retrieval_metrics(case, sources) == {
        "precision": None,
        "evidence_recall": None,
    }


def test_curated_dataset_and_fingerprint_include_corpus(tmp_path: Path) -> None:
    dataset, corpus, original = load_dataset(DEFAULT_DATASET)
    assert len(dataset.cases) == 9
    assert sum(c.expected_status == "insufficient_evidence" for c in dataset.cases) == 3
    (tmp_path / "corpus").mkdir()
    raw = DEFAULT_DATASET.read_text()
    (tmp_path / "dataset.json").write_text(raw)
    for name, data in corpus.items():
        (tmp_path / "corpus" / name).write_bytes(data)
    assert load_dataset(tmp_path / "dataset.json")[2] == original
    with (tmp_path / "corpus" / "security.md").open("a") as output:
        output.write("New policy.\n")
    assert load_dataset(tmp_path / "dataset.json")[2] != original


@pytest.mark.parametrize("change", ["path", "quote", "id", "filter", "evidence"])
def test_bad_dataset_rejected(tmp_path: Path, change: str) -> None:
    raw = json.loads(DEFAULT_DATASET.read_text())
    _, corpus, _ = load_dataset(DEFAULT_DATASET)
    (tmp_path / "corpus").mkdir()
    for name, data in corpus.items():
        (tmp_path / "corpus" / name).write_bytes(data)
    if change == "path":
        raw["documents"][0] = "../outside.md"
    elif change == "quote":
        raw["cases"][0]["evidence"][0]["quote"] = "Missing fact"
    elif change == "id":
        raw["cases"][1]["id"] = raw["cases"][0]["id"]
    elif change == "filter":
        raw["cases"][0]["documents"] = ["unknown.md"]
    else:
        raw["cases"][0]["evidence"] = []
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        load_dataset(path)
