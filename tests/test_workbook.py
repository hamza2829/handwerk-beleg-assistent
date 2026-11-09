import json

import pytest

from handwerk import store
from handwerk.workbook import amount_to_cents, read_jobs

from .conftest import workbook


def test_import_reads_exact_cents_and_stores_audit(tmp_path, jobs_file):
    rows = read_jobs(jobs_file)
    assert rows.issues == []
    assert [job.amount_cents for job in rows.jobs] == [12345, 3000]
    path = tmp_path / "jobs.sqlite"
    store.initialize(path)
    with store.connect(path) as db:
        result = store.import_jobs(db, rows, jobs_file.name)
        assert (result.inserted, result.updated) == (2, 0)
        assert store.jobs(db)[0] == {
            "job_id": "AUF-1", "customer": "Musterkunde Eins", "status": "offen",
            "amount_cents": 12345, "documents": 0,
        }
        audit = db.execute("SELECT * FROM imports").fetchone()
        assert audit["source"] == "auftraege.xlsx"
        assert json.loads(audit["issues"]) == []


def test_reimport_preserves_status_edits_and_reports_duplicates(tmp_path, jobs_file):
    path = tmp_path / "jobs.sqlite"
    store.initialize(path)
    with store.connect(path) as db:
        store.import_jobs(db, read_jobs(jobs_file), jobs_file.name)
        store.change_status(db, "AUF-1", "abgeschlossen")
        revised = workbook(tmp_path / "new.xlsx", [
            ("AUF-1", " Neuer Name ", "offen", 90),
            ("AUF-1", "Duplikat", "offen", 1),
            (None, None, None, None),
            ("AUF-3", "Neuer Auftrag", "offen", 0),
        ])
        result = store.import_jobs(db, read_jobs(revised), revised.name)
        assert (result.inserted, result.updated) == (1, 1)
        assert [(issue.row, issue.message) for issue in result.issues] == [
            (3, "duplicate auftragsnr AUF-1"),
        ]
        job = store.jobs(db)[0]
        assert (job["customer"], job["status"], job["amount_cents"]) == (
            "Neuer Name", "abgeschlossen", 9000,
        )
        audit = db.execute("SELECT issues FROM imports ORDER BY id DESC").fetchone()
        assert json.loads(audit["issues"])[0]["row"] == 3


@pytest.mark.parametrize(("invalid", "message"), [
    (("auf-1", "Name", "offen", 1), "auftragsnr"),
    (("AUF-1", " ", "offen", 1), "kunde"),
    (("AUF-1", "Name", "pending", 1), "status"),
    (("AUF-1", "Name", "offen", "1,02"), "betrag_eur"),
    (("AUF-1", "Name", "offen", 1.123), "betrag_eur"),
    (("AUF-1", "Name", "offen", -1), "betrag_eur"),
    (("AUF-1", "Name", "offen", True), "betrag_eur"),
    (("AUF-1", "Name", "offen", "=SUM(1,2)"), "formula cells"),
    (("AUF-1", "Name", "offen", 1, "extra"), "unexpected value"),
])
def test_bad_rows_include_row_numbers_and_valid_rows_survive(tmp_path, invalid, message):
    path = workbook(tmp_path / "bad-row.xlsx", [invalid, ("AUF-2", "Muster", "offen", 5)])
    rows = read_jobs(path)
    assert [job.job_id for job in rows.jobs] == ["AUF-2"]
    assert len(rows.issues) == 1 and rows.issues[0].row == 2
    assert message in rows.issues[0].message


@pytest.mark.parametrize(("kwargs", "message"), [
    ({"sheet": "Other"}, "expected worksheet"),
    ({"headers": ("job", "kunde", "status", "betrag_eur")}, "expected columns"),
])
def test_bad_workbook_structure(tmp_path, kwargs, message):
    path = workbook(tmp_path / "wrong.xlsx", [], **kwargs)
    with pytest.raises(ValueError, match=message):
        read_jobs(path)


def test_corrupt_excel_has_path_in_error(tmp_path):
    path = tmp_path / "corrupt.xlsx"
    path.write_text("bad archive", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt.xlsx"):
        read_jobs(path)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 10_000_001])
def test_amount_validation_rejects_nonfinite_or_out_of_range(value):
    with pytest.raises(ValueError, match="betrag_eur"):
        amount_to_cents(value)
