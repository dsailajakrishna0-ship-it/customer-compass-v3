"""Reads one document file into text segments that remember where they came from.

Stage 4.2. Until now every document was Markdown. Real documents arrive as PDFs, Word files and
spreadsheets, and a good citation says *where* in them the answer is ("page 3", "sheet Deals"). So a
file is read into **segments**, each carrying its page (PDF) or sheet (spreadsheet), and every chunk
cut from a segment inherits that location.

Which reader does what, and why (ADR 0020):

- Markdown: the front matter (title, type, company) plus the body, as before.
- PDF: `pypdfium2`, one segment per page. Text PDFs only. Docling's own PDF pipeline needs a
  PyTorch layout model (a multi-gigabyte install and a model download), which this project avoids;
  scanned PDFs (they need OCR) and table structure inside PDFs are therefore not supported yet.
- Word and Excel: Docling (the light `docling-slim` install, no machine-learning models). Excel gives
  one segment per sheet, with the sheet's name.

Only Markdown carries its metadata inside the file. For the other formats the metadata sits in a
small sidecar file next to it: `report.pdf` has `report.meta.yaml` with `title`, `type` and optionally
`company`.
"""

from dataclasses import dataclass
from pathlib import Path

import frontmatter
import yaml

DOCUMENT_TYPES = {"email", "call", "note", "support", "product"}
SUPPORTED_SUFFIXES = {".md", ".pdf", ".docx", ".xlsx"}
SIDECAR_SUFFIX = ".meta.yaml"


@dataclass(frozen=True)
class Segment:
    """A run of text and where it sits in the file."""

    text: str
    page: int | None = None  # PDF page, counting from 1
    sheet: str | None = None  # spreadsheet sheet name


@dataclass(frozen=True)
class ParsedFile:
    title: str
    doc_type: str
    company_name: str | None
    segments: list[Segment]


def is_document(path: Path) -> bool:
    """A file to ingest: a supported format, and not a metadata sidecar."""
    return path.suffix.lower() in SUPPORTED_SUFFIXES and not path.name.endswith(SIDECAR_SUFFIX)


def _check(
    path: Path, title: object, doc_type: object, company: object
) -> tuple[str, str, str | None]:
    if not isinstance(title, str) or doc_type not in DOCUMENT_TYPES:
        raise ValueError(f"Document {path.name} is missing required metadata (title, type).")
    return title, doc_type, company if isinstance(company, str) else None


def parse_markdown(path: Path) -> ParsedFile:
    post = frontmatter.load(path)
    title, doc_type, company = _check(
        path, post.get("title"), post.get("type"), post.get("company")
    )
    return ParsedFile(title, doc_type, company, [Segment(post.content.strip())])


def read_sidecar(path: Path) -> tuple[str, str, str | None]:
    sidecar = path.with_name(path.stem + SIDECAR_SUFFIX)
    if not sidecar.exists():
        raise ValueError(f"Document {path.name} needs a metadata file named {sidecar.name}.")
    data = yaml.safe_load(sidecar.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{sidecar.name} must be a mapping with title and type.")
    return _check(path, data.get("title"), data.get("type"), data.get("company"))


def parse_pdf_pages(path: Path) -> list[Segment]:
    """One segment per page that has text (an empty page, such as a scan, is skipped)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        segments = []
        for number in range(len(pdf)):
            page = pdf[number]
            text = page.get_textpage().get_text_range().strip()
            if text:
                segments.append(Segment(text, page=number + 1))
        return segments
    finally:
        pdf.close()


def parse_word(path: Path) -> list[Segment]:
    """The whole document as one segment (Word files have no fixed pages)."""
    from docling.document_converter import DocumentConverter

    text = DocumentConverter().convert(path).document.export_to_markdown().strip()
    return [Segment(text)] if text else []


def parse_sheets(path: Path) -> list[Segment]:
    """One segment per sheet: that sheet's tables as Markdown, labelled with the sheet's name."""
    from docling.document_converter import DocumentConverter
    from docling_core.types.doc import GroupLabel, TableItem

    document = DocumentConverter().convert(path).document
    names = [g.name for g in document.groups if g.label == GroupLabel.SHEET]
    tables: dict[int, list[str]] = {}
    for item, _level in document.iterate_items():
        if isinstance(item, TableItem) and item.prov:
            tables.setdefault(item.prov[0].page_no, []).append(
                item.export_to_markdown(doc=document)
            )
    segments = []
    for page_no in sorted(tables):
        sheet = names[page_no - 1] if 0 < page_no <= len(names) else f"Sheet {page_no}"
        text = "\n\n".join(tables[page_no]).strip()
        if text:
            segments.append(Segment(f"Sheet: {sheet}\n\n{text}", sheet=sheet))
    return segments


def parse_file(path: Path) -> ParsedFile:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return parse_markdown(path)
    title, doc_type, company = read_sidecar(path)
    if suffix == ".pdf":
        segments = parse_pdf_pages(path)
    elif suffix == ".docx":
        segments = parse_word(path)
    elif suffix == ".xlsx":
        segments = parse_sheets(path)
    else:
        raise ValueError(f"Unsupported document type: {path.name}")
    return ParsedFile(title, doc_type, company, segments)
