"""Stage 4.2: reading PDF, Word, Excel and Markdown files into located text (no network, no key)."""

from pathlib import Path

import docx
import openpyxl
import pytest
from fpdf import FPDF

from app.rag import parse
from app.rag.ingest import chunk_segments
from app.rag.retrieve import RetrievedChunk, build_context

SAMPLES = Path(__file__).resolve().parents[3] / "sample-data" / "documents"


def meta(path: Path, title="A title", doc_type="note", company="Acme Fabrication") -> None:
    lines = [f"title: {title}", f"type: {doc_type}"] + ([f"company: {company}"] if company else [])
    path.with_name(path.stem + parse.SIDECAR_SUFFIX).write_text("\n".join(lines))


def make_pdf(path: Path, pages: list[str]) -> None:
    pdf = FPDF()
    for text in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.multi_cell(0, 8, text)
    pdf.output(str(path))


def test_a_pdf_gives_one_segment_per_page_numbered_from_one(tmp_path):
    path = tmp_path / "a.pdf"
    make_pdf(path, ["first page text", "second page text"])
    meta(path)
    parsed = parse.parse_file(path)
    assert [(s.page, s.sheet) for s in parsed.segments] == [(1, None), (2, None)]
    assert "first page" in parsed.segments[0].text and "second page" in parsed.segments[1].text
    assert (parsed.title, parsed.doc_type, parsed.company_name) == (
        "A title",
        "note",
        "Acme Fabrication",
    )


def test_a_pdf_page_without_text_is_skipped_but_numbering_keeps_the_real_page(tmp_path):
    path = tmp_path / "a.pdf"
    make_pdf(path, ["page one", "", "page three"])
    meta(path)
    assert [s.page for s in parse.parse_file(path).segments] == [1, 3]


def test_a_spreadsheet_gives_one_segment_per_sheet_with_its_name(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.active.title = "Deals"
    workbook.active.append(["Deal", "Amount"])
    workbook.active.append(["Renewal", 10000])
    workbook.create_sheet("Notes").append(["Call about onboarding"])
    path = tmp_path / "a.xlsx"
    workbook.save(path)
    meta(path, doc_type="product", company="")
    parsed = parse.parse_file(path)
    assert [s.sheet for s in parsed.segments] == ["Deals", "Notes"]
    assert all(s.page is None for s in parsed.segments)
    assert "Renewal" in parsed.segments[0].text and "10000" in parsed.segments[0].text
    assert parsed.company_name is None


def test_a_word_file_is_one_segment_without_a_page(tmp_path):
    document = docx.Document()
    document.add_heading("Policy", level=1)
    document.add_paragraph("Refunds within 30 days.")
    path = tmp_path / "a.docx"
    document.save(path)
    meta(path)
    [segment] = parse.parse_file(path).segments
    assert (segment.page, segment.sheet) == (None, None)
    assert "Refunds within 30 days." in segment.text


def test_markdown_still_reads_its_own_front_matter(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("---\ntitle: T\ntype: call\ncompany: Acme Fabrication\n---\n\nBody text.\n")
    parsed = parse.parse_file(path)
    assert (parsed.title, parsed.doc_type) == ("T", "call")
    assert parsed.segments == [parse.Segment("Body text.")]


def test_a_non_markdown_file_without_its_metadata_file_is_refused_clearly(tmp_path):
    path = tmp_path / "a.pdf"
    make_pdf(path, ["text"])
    with pytest.raises(ValueError, match=r"a\.meta\.yaml"):
        parse.parse_file(path)


def test_bad_metadata_is_refused(tmp_path):
    path = tmp_path / "a.pdf"
    make_pdf(path, ["text"])
    meta(path, doc_type="memo")  # not one of the known document types
    with pytest.raises(ValueError, match="missing required metadata"):
        parse.parse_file(path)


def test_only_supported_files_that_are_not_sidecars_are_documents():
    assert parse.is_document(Path("a.pdf")) and parse.is_document(Path("a.MD"))
    assert not parse.is_document(Path("a.meta.yaml"))
    assert not parse.is_document(Path("a.txt"))


def test_chunks_keep_the_page_or_sheet_of_their_segment_and_numbering_runs_on():
    segments = [
        parse.Segment("x" * 700, page=1),  # two chunks (600 characters, overlap 100)
        parse.Segment("short text", page=2),
    ]
    chunks = chunk_segments(segments)
    assert [chunk.index for _segment, chunk in chunks] == [0, 1, 2]
    assert [segment.page for segment, _chunk in chunks] == [1, 1, 2]


def test_a_citation_names_the_page_or_sheet():
    def chunk(**where):
        return RetrievedChunk(1, 1, "Agreement", "a.pdf", "support", None, 0, "text", 0.8, **where)

    assert chunk(page=3).location == "page 3"
    assert chunk(sheet="Deals").location == "sheet Deals"
    assert chunk().location == ""
    assert "Source: Agreement (support, page 3)" in build_context([chunk(page=3)])
    assert "Source: Agreement (support)\n" in build_context([chunk()])  # markdown: unchanged


def test_the_committed_sample_files_parse_with_the_expected_locations():
    pdf = parse.parse_file(SAMPLES / "acme-service-agreement.pdf")
    assert [s.page for s in pdf.segments] == [1, 2]
    assert "Clause 7.3" in pdf.segments[1].text  # page 2 holds the renewal clauses
    sheets = parse.parse_file(SAMPLES / "northstar-rate-card.xlsx")
    assert [s.sheet for s in sheets.segments] == ["Rate card", "SLA credits"]
    word = parse.parse_file(SAMPLES / "riverside-data-handling-policy.docx")
    assert "Patient identifiers" in word.segments[0].text
