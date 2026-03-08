import pytest

from src.workflows.ingestion.loaders.errors import LoaderFileNotFoundError, LoaderInvalidFormatError
from src.workflows.ingestion.loaders.ppt_loader import PowerPointLoader
from src.workflows.ingestion.loaders.xlsx_loader import ExcelLoader
from src.workflows.ingestion.loaders.helpers import should_skip_path


def test_should_skip_office_lock_file(tmp_path):
    lock_file = tmp_path / "~$temp.xlsx"
    lock_file.write_text("lock", encoding="utf-8")

    assert should_skip_path(str(lock_file))


def test_powerpoint_loader_missing_file_raises_loader_error(tmp_path):
    loader = PowerPointLoader(str(tmp_path / "missing.pptx"))

    with pytest.raises(LoaderFileNotFoundError):
        loader.load()


def test_powerpoint_loader_wraps_invalid_format(monkeypatch, tmp_path):
    ppt_path = tmp_path / "broken.pptx"
    ppt_path.write_text("bad data", encoding="utf-8")

    monkeypatch.setattr(
        "src.workflows.ingestion.loaders.office_client.OfficeToolClient.load_as_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("Package not found")),
    )

    loader = PowerPointLoader(str(ppt_path))
    with pytest.raises(LoaderInvalidFormatError):
        loader.load()


def test_excel_loader_wraps_unstructured_errors(monkeypatch, tmp_path):
    excel_path = tmp_path / "not-really.xlsx"
    excel_path.write_text("123", encoding="utf-8")

    monkeypatch.setattr(
        "src.workflows.ingestion.loaders.office_client.OfficeToolClient.load_as_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("Not a valid XLSX file.")),
    )

    loader = ExcelLoader(str(excel_path))
    with pytest.raises(LoaderInvalidFormatError) as exc:
        loader.load()

    assert "XLSX" in str(exc.value)
