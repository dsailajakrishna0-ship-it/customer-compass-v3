"""Reads the project's own documentation (Markdown pages without front matter) into the same
`ParsedDocument`s the knowledge-base ingestion takes (step 4, ADR 0045).

The CRM documents carry a `title` and a `type` in their front matter and are read by `parse.py`. The
pages of `docs/` do not, so this reader takes the **title from the first `#` heading** (the file name
when a page has none), gives every page the type `product`, and reads **one folder level at a time**
(each configured folder is read without descending into its subfolders), so a knowledge base can be
built from `docs/` and `docs/stages/` without pulling in the ADRs or the superseded V2 pages.
"""

import re
from pathlib import Path

import frontmatter

from app.rag.ingest import ParsedDocument
from app.rag.parse import Segment

DOC_TYPE = "product"
_HEADING = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)
TOP_LEVEL = "."


def page_title(text: str, fallback: str) -> str:
    """The first level-1 heading, or the fallback (the file name without its suffix)."""
    match = _HEADING.search(text)
    return match.group(1).strip() if match else fallback


def folder_paths(source_dir: Path, folder: str) -> list[Path]:
    """The Markdown pages directly inside one configured folder, in file-name order."""
    directory = source_dir if folder == TOP_LEVEL else source_dir / folder
    if not directory.is_dir():
        raise FileNotFoundError(f"Could not find the folder {directory}.")
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".md")


def all_paths(source_dir: Path, folders: tuple[str, ...]) -> list[Path]:
    """Every page of every configured folder, in folder order then file-name order. A page's position
    in this list gives it a document number that stays the same when only one folder is ingested."""
    return [path for folder in folders for path in folder_paths(source_dir, folder)]


def read_page(path: Path, root: Path) -> ParsedDocument:
    body = frontmatter.loads(path.read_text(encoding="utf-8")).content
    return ParsedDocument(
        source_path=str(path.relative_to(root)),
        title=page_title(body, path.stem),
        doc_type=DOC_TYPE,
        company_name=None,
        segments=[Segment(text=body)],
    )
