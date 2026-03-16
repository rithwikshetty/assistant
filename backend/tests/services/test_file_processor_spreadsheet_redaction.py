import asyncio
import io

import openpyxl
import pytest

from app.services.files.file_processor import FileProcessor


def _build_workbook_bytes(cell_value: str) -> bytes:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet["A1"] = cell_value
    payload = io.BytesIO()
    workbook.save(payload)
    workbook.close()
    return payload.getvalue()


def test_redact_spreadsheet_file_content_xlsx_rewrites_cell_text() -> None:
    raw = _build_workbook_bytes("Owner: Alice Smith")

    result = asyncio.run(
        FileProcessor.redact_spreadsheet_file_content(
            raw,
            "xlsx",
            user_redaction_list=["Alice Smith"],
        )
    )

    assert result.redaction_performed is True
    assert "Alice Smith" in result.redaction_hits

    workbook = openpyxl.load_workbook(io.BytesIO(result.file_content), read_only=True, data_only=False)
    try:
        cell_value = workbook.active["A1"].value
        assert isinstance(cell_value, str)
        assert "[REDACTED NAME]" in cell_value
        assert "Alice Smith" not in cell_value
    finally:
        workbook.close()


def test_redact_spreadsheet_file_content_csv_rewrites_bytes() -> None:
    raw = b"name,amount\nAlice,10\n"

    result = asyncio.run(
        FileProcessor.redact_spreadsheet_file_content(
            raw,
            "csv",
            user_redaction_list=["Alice"],
        )
    )

    assert result.redaction_performed is True
    assert result.file_content.decode("utf-8") == "name,amount\n[REDACTED NAME],10\n"
    assert result.redaction_hits == ["Alice"]


def test_redact_spreadsheet_file_content_rejects_unsupported_format() -> None:
    with pytest.raises(ValueError, match="Use XLSX, XLSM, CSV, or TSV"):
        asyncio.run(
            FileProcessor.redact_spreadsheet_file_content(
                b"raw-bytes",
                "xlsb",
                user_redaction_list=["Alice"],
            )
        )
