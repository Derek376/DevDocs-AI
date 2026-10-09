"""Run with python -m evals; only 'run' contacts databases/model providers."""

import argparse
import asyncio
import json
from pathlib import Path

from app.core.config import Settings
from evals.dataset import DEFAULT_DATASET, load_dataset
from evals.metrics import Review, review_template, score_report
from evals.runner import run_live


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents silently overwriting a baseline or its review.
    with path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    run = commands.add_parser("run", help="Uses configured providers; API costs apply.")
    run.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--top-k", type=int, choices=range(1, 21))
    run.add_argument("--min-similarity", type=float)
    template = commands.add_parser("review-template")
    template.add_argument("report", type=Path)
    template.add_argument("--output", type=Path, required=True)
    score = commands.add_parser("score")
    score.add_argument("report", type=Path)
    score.add_argument("--review", type=Path)
    score.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            dataset, _, fingerprint = load_dataset(args.dataset)
            print(f"Valid: {len(dataset.cases)} cases; SHA256 {fingerprint}")
            return
        if args.command == "run":
            if args.output.exists():
                parser.error("Output exists; choose a new report path.")
            overrides = {}
            if args.top_k is not None:
                overrides["retrieval_top_k"] = args.top_k
            if args.min_similarity is not None:
                overrides["retrieval_min_similarity"] = args.min_similarity
            report = asyncio.run(run_live(args.dataset, Settings(**overrides)))
            write_json(args.output, report)
            print(json.dumps(score_report(report), indent=2))
            if any(case["status"] == "error" for case in report["cases"]):
                raise SystemExit(1)
        else:
            report = json.loads(args.report.read_text())
            if args.command == "review-template":
                write_json(args.output, review_template(report))
            else:
                review = (
                    Review.model_validate_json(args.review.read_text())
                    if args.review
                    else None
                )
                summary = score_report(report, review)
                if args.output:
                    write_json(args.output, summary)
                print(json.dumps(summary, indent=2))
    except (ValueError, OSError):
        # Avoid logging validation inputs (Settings can contain credentials).
        parser.exit(
            2, "Evaluation failed: invalid input, configuration, or file access.\n"
        )
    except Exception:
        # Provider/connection setup failures must not expose SQL URLs or secrets.
        parser.exit(
            2, "Evaluation setup failed. Check PostgreSQL and model providers.\n"
        )


if __name__ == "__main__":
    main()
