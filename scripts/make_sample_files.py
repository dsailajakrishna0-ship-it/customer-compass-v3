"""Regenerates the PDF, Word and Excel sample documents under sample-data/documents (Stage 4.2).

All content is invented. The generated files are committed so nobody needs to run this; it exists so
the files are reproducible and their text is reviewable here. Run it with the API project's
environment (it needs fpdf2, python-docx and openpyxl, all installed there):

    uv run --project apps/api-py python scripts/make_sample_files.py
"""

from pathlib import Path

import docx
import openpyxl
import yaml
from fpdf import FPDF

OUT = Path(__file__).resolve().parents[1] / "sample-data" / "documents"


def sidecar(stem: str, title: str, doc_type: str, company: str) -> None:
    (OUT / f"{stem}.meta.yaml").write_text(
        yaml.safe_dump({"title": title, "type": doc_type, "company": company}, sort_keys=False)
    )


def acme_agreement_pdf() -> None:
    pages = [
        (
            "Acme Fabrication: Service agreement summary",
            "Section 1. Support hours. Acme Fabrication's Premium Operations Plan includes "
            "support from 07:00 to 19:00 on weekdays. Priority 1 incidents, such as a stopped "
            "production line, receive a first response within 30 minutes at any hour.",
            "Section 2. Onboarding. Each new factory floor receives two on-site onboarding "
            "sessions and a remote training day. Additional floors are priced per floor.",
        ),
        (
            "Section 7. Renewal and termination",
            "Clause 7.3. The agreement renews automatically on 1 October for twelve months. "
            "Either party may end it with 60 days' written notice before the renewal date. "
            "Clause 7.4. A price change for the renewal term must be sent to the customer at "
            "least 90 days before the renewal date.",
            "Section 8. Invoicing. Invoice INV-4821 for the Q3 onboarding block is under review "
            "by Acme's finance team; payment terms are 30 days from the corrected invoice.",
        ),
    ]
    pdf = FPDF()
    for heading, *paragraphs in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.multi_cell(0, 10, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=11)
        for paragraph in paragraphs:
            pdf.multi_cell(0, 7, paragraph, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
    pdf.output(str(OUT / "acme-service-agreement.pdf"))
    sidecar(
        "acme-service-agreement",
        "Acme Fabrication service agreement summary",
        "support",
        "Acme Fabrication",
    )


def northstar_rate_card_xlsx() -> None:
    workbook = openpyxl.Workbook()
    rates = workbook.active
    rates.title = "Rate card"
    rates.append(["Plan", "Monthly price (USD)", "Tracked vehicles", "Alert channels"])
    rates.append(["Essentials", 1200, 50, "Email"])
    rates.append(["Fleet Plus", 3400, 250, "Email and SMS"])
    rates.append(["Fleet Enterprise", 9800, 1000, "Email, SMS and webhook"])
    credits = workbook.create_sheet("SLA credits")
    credits.append(["Monthly uptime", "Service credit"])
    credits.append(["99.9% or higher", "None"])
    credits.append(["99.0% to 99.9%", "10% of the monthly price"])
    credits.append(["Below 99.0%", "25% of the monthly price"])
    workbook.save(OUT / "northstar-rate-card.xlsx")
    sidecar(
        "northstar-rate-card",
        "Northstar Logistics rate card and SLA credits",
        "product",
        "Northstar Logistics",
    )


def riverside_policy_docx() -> None:
    document = docx.Document()
    document.add_heading("Riverside Health Group: data handling policy", level=1)
    document.add_paragraph(
        "Patient identifiers must never appear in support tickets or in exported reports. "
        "Exports are encrypted and expire after seven days."
    )
    document.add_heading("Access reviews", level=2)
    document.add_paragraph(
        "Accounts with access to clinical data are reviewed every quarter. A reviewer who "
        "finds an unused account disables it within two business days."
    )
    document.save(OUT / "riverside-data-handling-policy.docx")
    sidecar(
        "riverside-data-handling-policy",
        "Riverside Health Group data handling policy",
        "support",
        "Riverside Health Group",
    )


if __name__ == "__main__":
    acme_agreement_pdf()
    northstar_rate_card_xlsx()
    riverside_policy_docx()
    print(f"wrote 3 documents and their metadata to {OUT}")
