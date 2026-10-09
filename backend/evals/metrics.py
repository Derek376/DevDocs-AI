"""Separate automated reference checks from human semantic judgements."""

import hashlib
import json
import re
from statistics import mean

from pydantic import Field

from evals.dataset import Case, StrictModel, normalize


def digest_report(report: dict) -> str:
    return hashlib.sha256(
        json.dumps(report, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def retrieval_metrics(case: Case, context: list[dict]) -> dict:
    if not case.evidence:
        return {"precision": None, "evidence_recall": None}
    matches = [
        [
            index
            for index, gold in enumerate(case.evidence)
            if source["filename"] == gold.document
            and normalize(gold.quote) in normalize(source["text"])
        ]
        for source in context
    ]
    covered = {index for indices in matches for index in indices}
    return {
        "precision": sum(bool(indices) for indices in matches) / len(context)
        if context
        else 0.0,
        "evidence_recall": len(covered) / len(case.evidence),
    }


def citation_validity(result: dict) -> bool | None:
    if result["status"] == "error":
        return None
    if result["status"] == "insufficient_evidence":
        return None  # No accepted answer claims to check.
    markers = set(re.findall(r"\[(S\d+)\]", result["answer"]))
    citations = result["citations"]
    labels = {source["label"] for source in citations}
    context = {source["label"]: source for source in result["context"]}
    return (
        bool(markers)
        and markers == labels
        and len(labels) == len(citations)
        and all(context.get(source["label"]) == source for source in citations)
    )


class CitationJudgement(StrictModel):
    label: str = Field(pattern=r"^S[1-9]\d*$")
    supports_claim: bool | None = None


class ClaimJudgement(StrictModel):
    text: str = Field(min_length=1)
    supported: bool | None = None
    citations: list[CitationJudgement]
    notes: str = ""


class CaseReview(StrictModel):
    case_id: str
    complete: bool = False
    claims: list[ClaimJudgement] = Field(default_factory=list)


class Review(StrictModel):
    report_sha256: str
    reviewer: str = ""
    cases: list[CaseReview]


def review_template(report: dict) -> dict:
    return Review(
        report_sha256=digest_report(report),
        cases=[
            CaseReview(case_id=result["case_id"])
            for result in report["cases"]
            if result["status"] == "answered"
        ],
    ).model_dump()


def score_report(report: dict, review: Review | None = None) -> dict:
    results = report["cases"]
    if not results or len({r["case_id"] for r in results}) != len(results):
        raise ValueError("Report needs unique, nonempty cases.")
    answered = {r["case_id"]: r for r in results if r["status"] == "answered"}
    supported: list[bool] = []
    correct: list[bool] = []
    cited: list[bool] = []
    reviewed = 0
    if review is not None:
        if review.report_sha256 != digest_report(report):
            raise ValueError("Review belongs to a different report.")
        ids = [r.case_id for r in review.cases]
        if len(set(ids)) != len(ids) or set(ids) != set(answered):
            raise ValueError("Review must contain each answered case exactly once.")
        for item in review.cases:
            if not item.complete:
                continue  # Pending cases never count as zero or perfect support.
            if not review.reviewer.strip() or not item.claims:
                raise ValueError(
                    "Completed reviews need a reviewer and factual claims."
                )
            result = answered[item.case_id]
            seen: set[str] = set()
            for claim in item.claims:
                markers = set(re.findall(r"\[(S\d+)\]", claim.text))
                labels = [c.label for c in claim.citations]
                available = {c["label"] for c in result["citations"]}
                if (
                    claim.text not in result["answer"]
                    or claim.text in seen
                    or claim.supported is None
                    or len(labels) != len(set(labels))
                    # Atomic claims can precede a shared sentence-end marker.
                    # The reviewer maps that marker group to each claim.
                    or not markers.issubset(labels)
                    or not set(labels).issubset(available)
                    or any(c.supports_claim is None for c in claim.citations)
                ):
                    raise ValueError(f"Incomplete or invalid claim in {item.case_id}.")
                seen.add(claim.text)
                supported.append(claim.supported)
                cited.append(bool(labels))
                correct.extend(c.supports_claim for c in claim.citations)
            reviewed += 1
    validity = [citation_validity(r) for r in results]
    checked = [v for v in validity if v is not None]
    retrieval = [r["retrieval"] for r in results if r["retrieval"] is not None]
    precision = [r["precision"] for r in retrieval if r["precision"] is not None]
    recall = [
        r["evidence_recall"] for r in retrieval if r["evidence_recall"] is not None
    ]
    return {
        "cases": len(results),
        "errors": sum(r["status"] == "error" for r in results),
        "expected_status_accuracy": mean(
            r["status"] == r["expected_status"] for r in results
        ),
        "retrieval_precision_macro": mean(precision) if precision else None,
        "evidence_recall_macro": mean(recall) if recall else None,
        "retrieval_scored_cases": len(precision),
        "citation_validity": mean(checked) if checked else None,
        "citation_validity_answers": len(checked),
        "reviewed_answers": reviewed,
        "answered_cases": len(answered),
        "review_complete": reviewed == len(answered),
        "reviewed_claims": len(supported),
        "groundedness": mean(supported) if supported else None,
        "claim_citation_coverage": mean(cited) if cited else None,
        "reviewed_citation_pairs": len(correct),
        "citation_correctness": mean(correct) if correct else None,
    }
