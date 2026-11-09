import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .classify import Sorter
from .domain import DOCUMENT_TYPES, DocumentType
from .pdf import extract
from .synthetic import MANIFEST_FIELDS


@dataclass(frozen=True)
class Example:
    file: str
    expected: DocumentType
    profile: str


@dataclass(frozen=True)
class Failure:
    file: str
    expected: DocumentType
    predicted: DocumentType
    profile: str
    confidence: float
    engine: str
    needs_review: bool


@dataclass(frozen=True)
class Result:
    total: int
    correct: int
    accuracy_pct: float
    flagged: int
    unflagged_errors: int
    engines: dict[str, int]
    failures: list[Failure]


def labeled_examples(root: Path) -> list[Example]:
    path = root / "manifest.csv"
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            if tuple(reader.fieldnames or ()) != MANIFEST_FIELDS:
                raise ValueError("unexpected manifest columns")
            seen = set()
            cases = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"invalid manifest row {reader.line_num}")
                name = row["file"]
                if not re.fullmatch(r"beleg-[0-9]{3}\.pdf", name) or name in seen:
                    raise ValueError(f"invalid or duplicate filename on row {reader.line_num}")
                seen.add(name)
                if row["expected"] not in DOCUMENT_TYPES[:-1] or row["split"] not in {
                    "benchmark", "demo",
                } or row["profile"] not in {"standard", "alias", "mixed", "misleading", "sparse"}:
                    raise ValueError(f"invalid label, profile or split on row {reader.line_num}")
                if row["split"] == "benchmark":
                    cases.append(Example(name, row["expected"], row["profile"]))
    except (OSError, ValueError, csv.Error) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if not cases:
        raise ValueError(f"{path}: no benchmark examples")
    return cases


def evaluate(root: Path, sorter: Sorter) -> Result:
    cases = labeled_examples(root)
    failures = []
    flagged = 0
    engines: dict[str, int] = {}
    for case in cases:
        result = sorter.classify(extract((root / "pdf" / case.file).read_bytes()))
        prediction = result.prediction
        engines[result.engine] = engines.get(result.engine, 0) + 1
        flagged += result.needs_review
        if prediction.document_type != case.expected:
            failures.append(Failure(
                case.file, case.expected, prediction.document_type, case.profile,
                prediction.confidence, result.engine, result.needs_review,
            ))
    correct = len(cases) - len(failures)
    return Result(len(cases), correct, correct * 100 / len(cases), flagged,
                  sum(not item.needs_review for item in failures), engines, failures)


def report(result: Result) -> str:
    engines = ", ".join(f"`{name}` {count}" for name, count in sorted(result.engines.items()))
    lines = [
        "# Synthetic PDF classification benchmark", "",
        "The pipeline uses exact heading rules and a deterministic mock. "
        "All benchmark documents are generated from labeled fictional scenarios. "
        "Documents flagged for review still count in accuracy.", "",
        f"- Exact type accuracy: **{result.accuracy_pct:.2f}% ({result.correct}/{result.total})**.",
        f"- Flagged for review: {result.flagged}/{result.total}.",
        f"- Incorrect types: {len(result.failures)}. Incorrect types without a review flag: "
        f"{result.unflagged_errors}.",
        f"- Classification engines: {engines}.", "",
        "## Every failure", "",
        "| PDF | Expected | Predicted | Scenario | Score | Engine | Review |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for item in result.failures:
        lines.append(f"| {item.file} | {item.expected} | {item.predicted} | {item.profile} | "
                     f"{item.confidence:.2f} | {item.engine} | "
                     f"{'yes' if item.needs_review else 'no'} |")
    lines.extend([
        "", "Mixed and sparse text can leave the type unresolved. A misleading header can "
        "trigger an incorrect rule result with a high score. Scores are heuristic.", "",
    ])
    return "\n".join(lines)


def write_evaluation(out: Path, result: Result) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark.json").write_text(
        json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8",
    )
    (out / "benchmark.md").write_text(report(result), encoding="utf-8")
