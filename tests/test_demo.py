import json
from collections import Counter

import pytest

from handwerk import store
from handwerk.benchmark import evaluate, labeled_examples, write_evaluation
from handwerk.classify import MockLLM, Sorter
from handwerk.pdf import extract
from handwerk.synthetic import generate
from handwerk.workbook import read_jobs

from .conftest import workbook


def test_seeded_demo_count_labels_and_reproduction(dataset, tmp_path):
    other = tmp_path / "recreated"
    generate(other)
    names = sorted((dataset / "pdf").glob("*.pdf"))
    assert len(names) == 152
    assert (dataset / "manifest.csv").read_bytes() == (other / "manifest.csv").read_bytes()
    assert names[0].read_bytes() == (other / "pdf" / names[0].name).read_bytes()
    assert "SYNTHETISCHE DEMODATEN" in extract(names[0].read_bytes())
    cases = labeled_examples(dataset)
    assert Counter(case.expected for case in cases) == {
        "rechnung": 18, "lieferschein": 18, "angebot": 18, "mahnung": 18,
    }
    jobs = read_jobs(dataset / "auftraege.xlsx")
    assert len(jobs.jobs) == 24 and not jobs.issues
    assert jobs == read_jobs(other / "auftraege.xlsx")


def test_generator_rejects_nonempty_directory(dataset):
    with pytest.raises(ValueError, match="empty"):
        generate(dataset)


def test_accuracy_reports_every_failure_and_keeps_reviewed_cases(dataset, tmp_path):
    result = evaluate(dataset, Sorter(MockLLM()))
    assert result.total == 72
    assert result.correct + len(result.failures) == result.total
    assert result.accuracy_pct == pytest.approx(100 * result.correct / result.total)
    assert 0 < result.unflagged_errors < len(result.failures)
    assert {item.profile for item in result.failures} >= {"mixed", "misleading", "sparse"}
    assert result.flagged >= len(result.failures) - result.unflagged_errors
    assert sum(result.engines.values()) == result.total
    write_evaluation(tmp_path, result)
    report = (tmp_path / "benchmark.md").read_text(encoding="utf-8")
    assert "Every failure" in report
    assert all(item.file in report for item in result.failures)
    assert len(json.loads((tmp_path / "benchmark.json").read_text())["failures"]) == len(
        result.failures
    )


@pytest.mark.parametrize(("body", "message"), [
    ("type,name\n", "unexpected manifest columns"),
    ("file,expected,profile,split\n", "no benchmark"),
    ("file,expected,profile,split\nbeleg-001.pdf,mahnung,standard\n", "invalid manifest row"),
    ("file,expected,profile,split\n../bad.pdf,mahnung,standard,benchmark\n", "filename"),
    ("file,expected,profile,split\nbeleg-001.pdf,bad,standard,benchmark\n", "invalid label"),
    ("file,expected,profile,split\nbeleg-001.pdf,mahnung,standard,benchmark\n"
     "beleg-001.pdf,mahnung,standard,demo\n", "duplicate filename"),
])
def test_invalid_benchmark_manifest(tmp_path, body, message):
    (tmp_path / "manifest.csv").write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        labeled_examples(tmp_path)


def test_cli_evaluate_load_and_duplicate_demo(invoke, dataset, tmp_path, capsys):
    call, db_path = invoke
    assert call("evaluate", dataset, "--out", tmp_path / "metrics") == 0
    assert "Exact type accuracy" in capsys.readouterr().out
    assert call("load-demo", dataset) == 0
    assert call("load-demo", dataset) == 0
    assert "0 PDFs added" in capsys.readouterr().out
    with store.connect(db_path) as db:
        assert len(store.documents(db)) == 152
        assert len(store.jobs(db)) == 24


def test_cli_import_returns_row_errors_but_commits_valid_rows(invoke, tmp_path, capsys):
    call, db_path = invoke
    path = workbook(tmp_path / "rows.xlsx", [
        ("AUF-1", "Testkunde", "offen", 0),
        ("AUF-2", "Fehlerhaft", "unknown", 100),
    ])
    assert call("import-jobs", path) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["inserted"] == 1
    assert result["issues"][0]["row"] == 3
    with store.connect(db_path) as db:
        assert [job["job_id"] for job in store.jobs(db)] == ["AUF-1"]


def test_cli_broken_workbook_does_not_create_database(invoke, tmp_path):
    call, db_path = invoke
    with pytest.raises(SystemExit, match="2"):
        call("import-jobs", tmp_path / "missing.xlsx")
    assert not db_path.exists()


def test_cli_generation_and_missing_demo_pdfs(invoke, tmp_path, jobs_file):
    call, _ = invoke
    sample = tmp_path / "new"
    assert call("generate", "--out", sample, "--seed", 77) == 0
    assert (sample / "manifest.csv").is_file()
    assert jobs_file.name == "auftraege.xlsx"
    with pytest.raises(SystemExit, match="2"):
        call("load-demo", tmp_path)
