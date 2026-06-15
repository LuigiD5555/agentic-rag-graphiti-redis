"""Pytest coverage for the PDF loader fixes."""

from pathlib import Path

import pytest

from src.workflows.ingestion.loaders.errors import LoaderFileNotFoundError, LoaderInvalidFormatError
from src.workflows.ingestion.loaders.pdf_loader import PDFLoader
from pytest_readable import readable



def _build_pdf_bytes(text: str) -> bytes:
    stream = f"BT\n/F1 24 Tf\n72 120 Td\n({text}) Tj\nET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
            "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    parts = [b"%PDF-1.4\n"]
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(sum(len(part) for part in parts))
        parts.append(f"{index} 0 obj\n{obj}\nendobj\n".encode("ascii"))

    xref_start = sum(len(part) for part in parts)
    xref_entries = ["0000000000 65535 f "]
    for offset in offsets:
        xref_entries.append(f"{offset:010d} 00000 n ")
    xref = "xref\n0 {count}\n{entries}\n".format(
        count=len(objects) + 1,
        entries="\n".join(xref_entries),
    )

    trailer = (
        "trailer\n<< /Root 1 0 R /Size {size} >>\n"
        "startxref\n{xref_start}\n%%EOF\n"
    ).format(size=len(objects) + 1, xref_start=xref_start)

    parts.append(xref.encode("ascii"))
    parts.append(trailer.encode("ascii"))
    return b"".join(parts)


@readable(
    intent="Verify pdf loader reads text.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the pdf loader reads text behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_pdf_loader_reads_text(tmp_path: Path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(_build_pdf_bytes("Hello PDF"))

    loader = PDFLoader(str(pdf_path))
    # Tiny synthetic PDF content may be flagged as scanned by the heuristic;
    # force text path for this unit test.
    loader._is_scanned_pdf = lambda _docs: False
    documents = loader.load()

    assert documents
    assert any("Hello PDF" in doc.page_content for doc in documents)


@readable(
    intent="Verify pdf loader missing file.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the pdf loader missing file behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_pdf_loader_missing_file():
    loader = PDFLoader("/tmp/nonexistent_file.pdf")

    with pytest.raises(LoaderFileNotFoundError):
        loader.load()


@readable(
    intent="Verify pdf loader invalid file.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the pdf loader invalid file behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_pdf_loader_invalid_file(tmp_path: Path):
    invalid_path = tmp_path / "not_pdf.txt"
    invalid_path.write_text("This is not a PDF file", encoding="utf-8")

    loader = PDFLoader(str(invalid_path))

    with pytest.raises(LoaderInvalidFormatError):
        loader.load()
