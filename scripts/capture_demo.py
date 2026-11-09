"""Build the offline landing artifact using screenshots from a live local demo."""

import argparse
from pathlib import Path
from shutil import copytree

from playwright.sync_api import expect, sync_playwright


def capture(base: str, out: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "site"
    copytree(source, out, dirs_exist_ok=True)
    assets = out / "assets"
    assets.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        pending = page.request.get(base + "/documents?status=pruefen").json()
        jobs = page.request.get(base + "/jobs").json()
        assert len(pending) > 3 and jobs
        document_id, job_id = pending[0]["id"], jobs[0]["job_id"]
        linked = page.request.patch(f"{base}/documents/{document_id}/job", data={"job_id": job_id})
        assert linked.ok and linked.json()["job_id"] == job_id
        changed = page.request.patch(f"{base}/jobs/{job_id}/status", data={"status": "in_arbeit"})
        assert changed.ok and changed.json()["status"] == "in_arbeit"

        assert page.goto(base + "/").ok
        expect(page.get_by_role("heading", name="Belege prüfen")).to_be_visible()
        expect(page.locator("#pending-count")).to_have_text(str(len(pending)))
        page.screenshot(path=assets / "review.png", animations="disabled")
        page.get_by_role("link", name="Aufträge", exact=True).click()
        expect(page.get_by_role("heading", name="Aufträge", exact=True)).to_be_visible()
        expect(page.locator(f'[data-job-id="{job_id}"]')).to_contain_text("In Arbeit")
        page.screenshot(path=assets / "jobs.png", animations="disabled")

        page.get_by_role("link", name="Belege prüfen", exact=True).click()
        row = page.locator(f'[data-document-id="{document_id}"]')
        row.get_by_role("combobox").select_option("angebot")
        row.get_by_role("button", name="Bestätigen").click()
        expect(page.locator("#pending-count")).to_have_text(str(len(pending) - 1))
        response = page.request.get(f"{base}/documents/{document_id}")
        assert response.ok and response.json()["status"] == "geprueft"

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto((out / "index.html").resolve().as_uri())
        expect(page.get_by_role("heading", name="Ein Blick in die Anwendung")).to_be_visible()
        assert page.get_by_role("img").count() == 2
        assert page.get_by_role("img").evaluate_all(
            "(images) => images.every(image => image.complete && image.naturalWidth > 0)"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    capture(args.base, args.out)


if __name__ == "__main__":
    main()
