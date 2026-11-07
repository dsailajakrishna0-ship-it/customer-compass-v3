# 0020 — Reading PDF, Word and Excel files: Docling where it is light, `pypdfium2` for PDFs

- **Status:** Accepted
- **Date:** 2026-11-07
- **Roadmap sub-stage:** 4.2

## Context

Until 4.2 every document was Markdown with a front-matter header. Real documents arrive as PDFs, Word files and spreadsheets, and the exit criterion is that citations show the source **and the page or sheet**. The roadmap names Docling. Checking what Docling needs (2026-11-07):

- Installing `docling` pulls PyTorch, CUDA libraries, `transformers`, ONNX and OCR engines (125 packages, a multi-gigabyte image) and downloads layout models at first use.
- Its **PDF** pipeline needs that PyTorch layout model: with only the light `docling-slim` install, converting a PDF fails with `No module named 'torch'`.
- Its **Word and Excel** readers need no model. With `docling-slim[format-docx,format-xlsx]` they work, and Excel keeps each sheet's name.

V3 is cloud-only and runs on free tiers ([ADR 0010](0010-cloud-only-models.md)); a multi-gigabyte machine-learning stack in the API image would slow every build and CI scan and sit unused for the Markdown that is still most of the data.

## Decision

1. **Docling for Word and Excel, via `docling-slim`** (75 small packages, no models). Excel gives one segment per sheet, labelled with the sheet's name.
2. **`pypdfium2` for PDFs**, one segment per page that has text. It is a small library and gives exact page numbers. It reads **text PDFs only**: scanned PDFs (they need OCR) and table structure inside a PDF are not supported yet.
3. **Segments carry the location.** A file is read into segments, each with an optional `page` or `sheet`; every chunk cut from a segment inherits it and stores it in its Qdrant payload. Citations show it ("page 3", "sheet Deals"). Markdown and Word files have neither, and their stored chunks look exactly as before.
4. **Metadata for non-Markdown files sits in a sidecar** (`report.pdf` plus `report.meta.yaml` with `title`, `type`, optional `company`), because only Markdown has a place for a header. A missing or invalid sidecar fails ingestion with a message that names the file.
5. **Our own chunker stays.** Chunking is part of what this project teaches; Docling's chunkers would pull in `transformers`.
6. **The API change is additive:** `/chat/rag` citations gain optional `page` and `sheet`, omitted when absent. The Java edition ports it when it reaches RAG ([port-status](../port-status.md)).
7. **Sample files are generated from a script** (`scripts/make_sample_files.py`), committed, and use invented content: a two-page PDF with a clause on page 2, a two-sheet Excel rate card and a Word policy.

## Alternatives considered

- **Full `docling`.** Best PDF understanding (layout, tables, OCR) but the cost above. Revisit if PDF tables or scans matter; the parser is behind one function, `parse_file`, so it can be swapped for PDFs alone, or run as a separate service.
- **`openpyxl` and `python-docx` directly.** Lighter still, but then Docling would not be used at all and we would lose its single document model.
- **Docling in a separate container (`docling-serve`).** Keeps the API image light and gives full PDF quality, but adds a service to run and to keep in CI. A candidate if PDF quality becomes the bottleneck.

## Consequences

- Three more documents in the corpus (19 files, 33 chunks) change what the retrieval evaluation sees. The golden set still covers only the 16 Markdown documents, so `just eval-retrieval` may move slightly; if it does, the baseline should be re-taken on purpose, and the golden set extended with questions for the new files (a Stage 5 task).
- Scanned PDFs return no text and are skipped with no error; a PDF with no text at all produces a document with no chunks.
- New dependencies in the API image (`docling-slim` and its tree, `pypdfium2`, `lxml`, `pillow`, `pandas`) are covered by the existing dependency and image scans.
- Chunk character offsets are now relative to the segment, not the whole document (they are stored but not used for citations).
