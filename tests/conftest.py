import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from handwerk import store
from handwerk.api import create_app
from handwerk.cli import main
from handwerk.synthetic import generate, write_pdf
from handwerk.workbook import HEADERS, SHEET, read_jobs


def workbook(path, rows, *, sheet=SHEET, headers=HEADERS):
    book = Workbook()
    book.active.title = sheet
    book.active.append(headers)
    for row in rows:
        book.active.append(row)
    book.save(path)
    book.close()
    return path


@pytest.fixture
def jobs_file(tmp_path):
    return workbook(tmp_path / "auftraege.xlsx", [
        ("AUF-1", "Musterkunde Eins", "offen", 123.45),
        ("AUF-2", "Musterkunde Zwei", "in_arbeit", 30),
    ])


@pytest.fixture
def invoice(tmp_path):
    path = tmp_path / "invoice.pdf"
    write_pdf(path, "Rechnung", ["Testbeleg.", "Betrag: 123,45 EUR"])
    return path.read_bytes()


@pytest.fixture
def unclear(tmp_path):
    path = tmp_path / "unknown.pdf"
    write_pdf(path, "Unterlage", ["Fiktive Unterlage ohne eindeutigen Typ."])
    return path.read_bytes()


@pytest.fixture
def client(tmp_path, jobs_file):
    path = tmp_path / "app.sqlite"
    with TestClient(create_app(path)) as http:
        with store.connect(path) as db:
            store.import_jobs(db, read_jobs(jobs_file), jobs_file.name)
        yield http


@pytest.fixture(scope="session")
def dataset(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("sample")
    generate(out)
    return out


@pytest.fixture
def invoke(tmp_path, monkeypatch):
    path = tmp_path / "cli.sqlite"

    def run(*args):
        monkeypatch.setattr(sys, "argv", ["beleg-assistent", "--db", str(path), *map(str, args)])
        return main()

    return run, path
