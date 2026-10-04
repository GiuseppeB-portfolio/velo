"""Builders for test files. All data is fake and known."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation


def csv_rows(raw: bytes, encoding: str = "cp1252", delimiter: str = ";") -> list[list[str]]:
    import csv
    import io

    return list(csv.reader(io.StringIO(raw.decode(encoding), newline=""), delimiter=delimiter))


def assert_cells_changed(original: list[list[str]], output: list[list[str]], columns) -> None:
    """Every non-empty chosen cell must differ from the original, compared by position.

    Never search for the real string inside the output: a fake value can legitimately
    contain it ('Mario' inside 'Mariotti') or equal another person's real value.
    """
    assert len(original) == len(output)
    for row_in, row_out in zip(original[1:], output[1:], strict=True):
        for col in columns:
            if row_in[col]:
                assert row_out[col] != row_in[col], (col, row_in[col])


def identity(choice, value):
    return value


def tag(choice, value):
    """Deterministic replacement used by tests: easy to spot, keeps nothing real."""
    return f"X[{value}]" if isinstance(value, str) else value


CSV_IT = (
    "Nome;Cognome;Importo;Citta;Data\r\n"
    "Mario;Rossi;1.234,56;Perù;01/02/1980\r\n"
    "Lucia;Bianchi;99,9;Forlì;15/11/1975\r\n"
    "Anna;;0,5;Torino;\r\n"
)


def write_csv(path: Path, text: str, encoding="utf-8", bom=False) -> Path:
    data = text.encode(encoding)
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    return path


def make_workbook(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Clienti"
    ws.append(["Nome", "Cognome", "Importo", "Data", "IVA", "Completo", "Note"])
    ws.append(["Mario", "Rossi", 1234.56, datetime(1980, 2, 1), "=C2*0.22", '=A2&" "&B2', "ok"])
    ws.append(["Lucia", "Bianchi", 99.9, datetime(1975, 11, 15), "=C3*0.22", '=A3&" "&B3', None])
    ws.append(["Anna", None, 7, datetime(1990, 5, 5), "=C4*0.22", '=A4&" "&B4', "vip"])
    ws["A5"] = "Ufficio"
    ws.merge_cells("A5:A6")
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in range(2, 5):
        ws[f"C{r}"].number_format = "#,##0.00"
        ws[f"D{r}"].number_format = "DD/MM/YYYY"
    ws.column_dimensions["A"].width = 22
    ws.freeze_panes = "A2"
    dv = DataValidation(type="list", formula1='"ok,vip"')
    ws.add_data_validation(dv)
    dv.add("G2:G4")

    o = wb.create_sheet("Ordini")
    o.append(["Cliente", "Nome", "Quantita", "Nome"])  # duplicate header on purpose
    o.append(["C1", "Mario", 3, "Rossi"])
    o.append(["C2", "Lucia", 10, "Bianchi"])

    h = wb.create_sheet("Archivio")
    h.append(["Nome"])
    h.append(["Segreto"])
    h.sheet_state = "hidden"

    wb.properties.creator = "Giuseppe Bianco"
    wb.properties.lastModifiedBy = "Giuseppe Bianco"
    wb.properties.title = "Clienti Acme"
    wb.save(path)
    return path
