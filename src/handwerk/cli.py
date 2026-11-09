import argparse
import json
from dataclasses import asdict
from pathlib import Path

from . import store
from .benchmark import evaluate, write_evaluation
from .classify import MockLLM, Sorter
from .synthetic import generate
from .workbook import read_jobs


def main() -> int:
    parser = argparse.ArgumentParser(description="Sort fictional trade documents and track jobs")
    parser.add_argument("--db", type=Path, default=Path("handwerk.sqlite"))
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("generate", help="Generate synthetic PDFs and an Excel workbook")
    make.add_argument("--out", type=Path, required=True)
    make.add_argument("--seed", type=int, default=2829)
    import_excel = commands.add_parser("import-jobs", help="Import valid job rows and list row errors")
    import_excel.add_argument("workbook", type=Path)
    load = commands.add_parser("load-demo", help="Load the generated demo into SQLite")
    load.add_argument("dataset", type=Path)
    test = commands.add_parser("evaluate", help="Measure the offline classifier on benchmark PDFs")
    test.add_argument("dataset", type=Path)
    test.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.command == "generate":
            generate(args.out, args.seed)
            print(f"Wrote synthetic PDFs and jobs to {args.out}")
            return 0

        if args.command == "evaluate":
            result = evaluate(args.dataset, Sorter(MockLLM()))
            write_evaluation(args.out, result)
            print(f"Exact type accuracy {result.accuracy_pct:.2f}% ({result.correct}/{result.total}), "
                  f"{len(result.failures)} errors, {result.unflagged_errors} unflagged")
            return 0

        path = args.workbook if args.command == "import-jobs" else args.dataset / "auftraege.xlsx"
        rows = read_jobs(path)
        store.initialize(args.db)
        with store.connect(args.db) as db:
            imported = store.import_jobs(db, rows, path.name)
            if args.command == "import-jobs":
                print(json.dumps(asdict(imported), ensure_ascii=False, indent=2))
                return 2 if imported.issues else 0
            pdfs = sorted((args.dataset / "pdf").glob("*.pdf"))
            if not pdfs:
                raise ValueError("demo directory contains no PDFs")
            sorter = Sorter(MockLLM())
            added = sum(store.ingest(db, file.name, file.read_bytes(), sorter)[1] for file in pdfs)
        print(f"Demo loaded. {added} PDFs added, {len(rows.jobs)} valid job rows.")
        return 2 if imported.issues else 0
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
