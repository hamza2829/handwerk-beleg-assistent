import csv
from datetime import date, timedelta
from pathlib import Path
from random import Random

from openpyxl import Workbook
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from .domain import DOCUMENT_LABELS, JOB_STATUSES, DocumentType
from .workbook import HEADERS, SHEET

MANIFEST_FIELDS = ("file", "expected", "profile", "split")
TYPES = ("rechnung", "lieferschein", "angebot", "mahnung")
BENCHMARK = ("standard",) * 10 + ("alias",) * 4 + ("mixed",) * 2 + ("misleading", "sparse")
DEMO = ("standard",) * 13 + ("alias",) * 2 + ("mixed",) * 3 + ("misleading", "sparse")
CUSTOMERS = (
    "Musterbetrieb Erlenhof", "Musterkunde Werkstatt Nord", "Beispielhaus Lindenbogen",
    "Musterbau Sonnseite", "Testbetrieb Birkenweg", "Beispielhof Morgenrot",
    "Musterkunde Dach & Holz", "Testwerk Kastanienring",
)
SERVICES = (
    "Austausch eines Türschließers", "Montage einer Ablage im Lager",
    "Wartung der Werkstatttür", "Lieferung von Dichtprofilen",
    "Anpassung eines Fenstergriffs", "Prüfung der Lichtschaltung",
    "Reparatur der Abdeckleiste", "Lieferung von Befestigungsmaterial",
)
SCENARIO_TERMS = {
    "rechnung": ("Leistungsabrechnung", "Rechnungsbetrag", "Summe inklusive Steuer"),
    "lieferschein": ("Warenbegleitschein", "Gelieferte Menge", "Ankunft im Materiallager"),
    "angebot": ("Kostenvoranschlag", "Bindefrist", "Geplanter Gesamtpreis"),
    "mahnung": ("Zahlungserinnerung", "Offener Posten", "Bitte zeitnah überweisen"),
}
STANDARD_FIELDS = {
    "rechnung": ("Zahlungsziel: 14 Tage ab Belegdatum", "Betrag einschließlich Umsatzsteuer."),
    "lieferschein": ("Menge: 3 Stück", "Übergabe im Materiallager, Empfang zur Bestätigung."),
    "angebot": ("Gültigkeit: 21 Tage ab Belegdatum", "Ausführung nach Terminabsprache."),
    "mahnung": ("Zahlungsfrist: 7 Tage ab Belegdatum", "Bezug: zuvor versandter Beleg."),
}
START = date(2025, 2, 3)


def euro(cents: int) -> str:
    whole, decimal = divmod(cents, 100)
    return f'{whole:,}'.replace(",", ".") + f",{decimal:02d} €"


def write_pdf(path: Path, heading: str, lines: list[str]) -> None:
    page = Canvas(str(path), pagesize=A4, invariant=1)
    page.setTitle("Synthetischer Musterbeleg")
    page.setAuthor("Handwerk Beleg-Assistent Demo")
    page.setFillColor(HexColor("#16443A"))
    page.rect(0, 760, A4[0], 82, stroke=0, fill=1)
    page.setFillColor(HexColor("#FFFFFF"))
    page.setFont("Helvetica-Bold", 12)
    page.drawString(44, 797, "MUSTERWERKSTATT | SYNTHETISCHE DEMODATEN")
    page.setFillColor(HexColor("#17382F"))
    page.setFont("Helvetica-Bold", 25)
    page.drawString(44, 706, heading)
    page.setFillColor(HexColor("#293C36"))
    page.setFont("Helvetica", 12)
    for index, line in enumerate(lines):
        page.drawString(44, 654 - index * 27, line)
    page.setFont("Helvetica", 10)
    page.drawString(44, 60, "Fiktiver Vorgang für eine Software-Demo.")
    page.showPage()
    page.save()


def content(kind: DocumentType, profile: str, rng: Random) -> tuple[str, list[str]]:
    neighbor = TYPES[(TYPES.index(kind) + 1) % len(TYPES)]
    own = SCENARIO_TERMS[kind]
    other = SCENARIO_TERMS[neighbor]
    if profile == "standard":
        return DOCUMENT_LABELS[kind], [rng.choice(own).capitalize() + " zur Position unten.",
                                       *STANDARD_FIELDS[kind]]
    if profile == "alias":
        return own[0].capitalize(), [rng.choice(own[1:]).capitalize() + " siehe Position."]
    if profile == "mixed":
        return "Beleg zur Abstimmung", [
            f"Hinweis 1: {rng.choice(own[:2])}.", f"Hinweis 2: {rng.choice(other[:2])}.",
        ]
    if profile == "misleading":
        return DOCUMENT_LABELS[neighbor], [
            f"Verweis im Kopf, Hauptvorgang: {own[0]}.", f"Details: {own[1]}.",
        ]
    return "Unterlage zum Vorgang", ["Bitte die Angaben dem Vorgang zuordnen."]


def generate(out: Path, seed: int = 2829) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError(f"{out}: output directory must be empty")
    rng = Random(seed)
    pdfs = out / "pdf"
    pdfs.mkdir()
    book = Workbook()
    sheet = book.active
    sheet.title = SHEET
    sheet.append(HEADERS)
    job_rows = []
    for number in range(1, 25):
        job = (f"AUF-{1000 + number}", rng.choice(CUSTOMERS), JOB_STATUSES[(number - 1) % 4],
               rng.randint(4500, 465000))
        job_rows.append(job)
        sheet.append((*job[:3], job[3] / 100))
        sheet.cell(number + 1, 4).number_format = '#,##0.00 "EUR"'
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in zip("ABCD", (16, 37, 21, 19), strict=True):
        sheet.column_dimensions[column].width = width
    book.save(out / "auftraege.xlsx")
    book.close()

    scenarios = [
        (kind, profile, split)
        for kind in TYPES for split, profiles in (("benchmark", BENCHMARK), ("demo", DEMO))
        for profile in profiles
    ]
    rng.shuffle(scenarios)
    with (out / "manifest.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(MANIFEST_FIELDS)
        for index, (kind, profile, split) in enumerate(scenarios, 1):
            filename = f"beleg-{index:03d}.pdf"
            heading, detail = content(kind, profile, rng)
            job_id, customer, _, amount = rng.choice(job_rows)
            issued = START + timedelta(days=rng.randrange(120))
            write_pdf(pdfs / filename, heading, [
                f"Belegnummer: SYN-{index:04d}",
                f"Datum: {issued:%d.%m.%Y}",
                f"Auftrag: {job_id}",
                f"Kunde: {customer}",
                f"Position: {rng.choice(SERVICES)}",
                *detail,
                *(["Lieferung für den genannten Auftrag."] if kind == "lieferschein"
                  else [f"Vorgangswert: {euro(amount)}"]),
            ])
            writer.writerow((filename, kind, profile, split))
    (out / "README.txt").write_text(
        f"Synthetische Demodaten, Seed {seed}. Alle Belege, Aufträge und Kunden sind fiktiv.\n",
        encoding="utf-8",
    )
