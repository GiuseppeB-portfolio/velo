"""Format adapters and lookup by file extension."""

from __future__ import annotations

from pathlib import Path

from ..errors import UnsupportedFileError
from .base import FormatAdapter
from .csv_format import CsvAdapter
from .excel import ExcelAdapter
from .json_format import JsonAdapter

_ADAPTERS: tuple[FormatAdapter, ...] = (ExcelAdapter(), CsvAdapter(), JsonAdapter())


def get_adapter(path: Path | str) -> FormatAdapter:
    suffix = Path(path).suffix.lower()
    for adapter in _ADAPTERS:
        if suffix in adapter.extensions:
            return adapter
    raise UnsupportedFileError(
        f"Formato '{suffix or '?'}' non supportato. Formati ammessi: .xlsx, .csv, .json"
    )
