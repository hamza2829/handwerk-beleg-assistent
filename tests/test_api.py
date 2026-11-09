import pytest

from handwerk.pdf import MAX_BYTES


def send(client, content, filename="test.pdf"):
    return client.post("/documents", files={"file": (filename, content, "application/pdf")})


def test_upload_list_get_and_download_original(client, invoice):
    upload = send(client, invoice, "subdir/beleg.pdf")
    assert upload.status_code == 201
    row = upload.json()
    assert row["filename"] == "beleg.pdf"
    assert (row["document_type"], row["status"], row["needs_review"]) == (
        "rechnung", "sortiert", False,
    )
    assert client.get(f"/documents/{row['id']}").json() == row
    assert client.get("/documents").json() == [row]
    assert client.get("/documents?status=pruefen").json() == []
    file = client.get(f"/documents/{row['id']}/file")
    assert file.content == invoice
    assert file.headers["content-type"] == "application/pdf"
    assert file.headers["content-disposition"] == "attachment; filename*=UTF-8''beleg.pdf"
    assert client.get("/healthz").json() == {"status": "ok"}


def test_link_status_and_unlink(client, invoice):
    document_id = send(client, invoice).json()["id"]
    link = client.patch(f"/documents/{document_id}/job", json={"job_id": "AUF-1"})
    assert link.status_code == 200 and link.json()["job_id"] == "AUF-1"
    result = client.patch("/jobs/AUF-1/status", json={"status": "abgeschlossen"})
    assert result.json()["status"] == "abgeschlossen"
    assert result.json()["documents"] == 1
    assert client.get("/jobs").json()[0]["documents"] == 1
    assert "Abgeschlossen" in client.get("/auftraege").text
    unlinked = client.patch(f"/documents/{document_id}/job", json={"job_id": None})
    assert unlinked.json()["job_id"] is None
    assert client.get("/jobs").json()[0]["documents"] == 0


def test_human_review_preserves_prediction_and_duplicate_keeps_review(client, unclear):
    first = send(client, unclear, "C:\\fake\\weg.pdf")
    row = first.json()
    document_id = row["id"]
    assert row["filename"] == "weg.pdf" and row["status"] == "pruefen"
    assert row["needs_review"] and row["predicted_type"] == "unbekannt"
    assert client.get("/documents?status=pruefen").json() == [row]
    fixed = client.patch(f"/documents/{document_id}/review", json={"document_type": "mahnung"})
    assert fixed.json()["predicted_type"] == "unbekannt"
    assert fixed.json()["document_type"] == "mahnung"
    assert fixed.json()["status"] == "geprueft" and not fixed.json()["needs_review"]
    repeated = send(client, unclear, "renamed.pdf")
    assert repeated.status_code == 200
    assert repeated.json() == fixed.json()
    assert len(client.get("/documents").json()) == 1


def test_review_page_escapes_filenames_and_confirms_type(client, unclear):
    document_id = send(client, unclear, "<script>alert(1)<.pdf").json()["id"]
    html = client.get("/").text
    assert "Prüfwarteschlange" in html
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert "Automatischer Vorschlag" in html
    review = client.post(f"/review/{document_id}", data={"document_type": "angebot"},
                         follow_redirects=False)
    assert review.status_code == 303 and review.headers["location"] == "/"
    assert "Keine Belege zur Prüfung" in client.get("/").text
    assert client.get(f"/documents/{document_id}").json()["document_type"] == "angebot"
    assert client.get("/static/app.css").status_code == 200


@pytest.mark.parametrize(("method", "path", "payload"), [
    ("GET", "/documents/999", None),
    ("GET", "/documents/999/file", None),
    ("PATCH", "/documents/999/job", {"job_id": None}),
    ("PATCH", "/documents/999/review", {"document_type": "rechnung"}),
    ("PATCH", "/jobs/AUF-999/status", {"status": "offen"}),
])
def test_missing_records_return_404(client, method, path, payload):
    assert client.request(method, path, json=payload).status_code == 404


def test_link_to_missing_job_is_rolled_back(client, invoice):
    document_id = send(client, invoice).json()["id"]
    assert client.patch(f"/documents/{document_id}/job", json={"job_id": "AUF-1"}).is_success
    missing = client.patch(f"/documents/{document_id}/job", json={"job_id": "AUF-999"})
    assert missing.status_code == 404
    assert client.get(f"/documents/{document_id}").json()["job_id"] == "AUF-1"


@pytest.mark.parametrize(("method", "path", "payload"), [
    ("GET", "/documents?status=invalid", None),
    ("PATCH", "/documents/1/job", {"job_id": "bad id"}),
    ("PATCH", "/documents/1/review", {"document_type": "invoice"}),
    ("PATCH", "/jobs/AUF-1/status", {"status": "done"}),
    ("PATCH", "/jobs/AUF-1/status", {"status": "offen", "amount_cents": 0}),
])
def test_api_validates_enums_and_payloads(client, method, path, payload):
    assert client.request(method, path, json=payload).status_code == 422


@pytest.mark.parametrize(("payload", "status"), [
    (b"wrong type", 422),
    (b"%PDF-1.4\nmalformed", 422),
    (b"x" * (MAX_BYTES + 1), 413),
])
def test_bad_uploads_are_rejected_without_persistence(client, payload, status):
    assert send(client, payload).status_code == status
    assert client.get("/documents").json() == []
