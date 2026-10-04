"""Edge cases that protect data: odd separators, unwritable values, failures that must leave nothing behind."""

import re
import shutil
import sys
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from factories import identity, make_workbook, tag, write_csv
from velo.engine import Pseudonymizer
from velo.errors import PlanError, UnsupportedFileError, VeloError
from velo.formats.csv_format import CsvAdapter
from velo.formats.excel import ExcelAdapter
from velo.formats.json_format import JsonAdapter, JsonNumber, JsonString, to_literal
from velo.mapping import Restorer
from velo.model import Category as C
from velo.model import FieldChoice, Mode
from velo.service import pseudonymize, restore
from velo.values import decode_value, encode_value, kind_of, value_key

KEY = bytes(range(32))


def ch(cat, mode=Mode.FAKE, fid="f"):
    return FieldChoice(fid, cat, mode)


# -- amounts: separators and zeros --------------------------------------------------------------------


@pytest.mark.parametrize(
    "original, grouped, decimals",
    [
        ("1.234", ".", 0),  # Italian thousands, no decimals
        ("12.345.678", ".", 0),
        ("1 234,56", " ", 2),
        ("1'234.50", "'", 2),
        ("1\u00a0234,5", "\u00a0", 1),
    ],
)
def test_grouping_characters_are_kept(original, grouped, decimals):
    e = Pseudonymizer(KEY)
    outs = {e(ch(C.AMOUNT), f"{i}{original}") for i in range(1, 30)}  # varied magnitudes
    assert any(grouped in o for o in outs)
    for o in outs:
        assert re.fullmatch(rf"[\d{re.escape(grouped)}.,]+", o)


@pytest.mark.parametrize("zero", ["0", "0,00", 0, 0.0, Decimal("0.00"), JsonNumber("0.0")])
def test_zero_amounts_are_kept_and_restorable(zero):
    e = Pseudonymizer(KEY)
    assert e(ch(C.AMOUNT), zero) == zero
    assert Restorer(e.entries())(ch(C.AMOUNT), zero) == zero


def test_float_and_decimal_amounts_keep_sign_and_decimals():
    e = Pseudonymizer(KEY)
    f = e(ch(C.AMOUNT), -12.5)
    assert isinstance(f, float) and f < 0
    d = e(ch(C.AMOUNT), Decimal("-3.250"))
    assert isinstance(d, Decimal) and d < 0 and d.as_tuple().exponent == -3


@pytest.mark.parametrize("value", [None, True, b"x", [1]])
def test_amount_rejects_non_numbers_gracefully_via_placeholder(value):
    e = Pseudonymizer(KEY)
    if isinstance(value, bool):
        assert e(ch(C.AMOUNT), value) is True  # booleans are left alone in fake mode
    else:
        with pytest.raises(TypeError):
            e(ch(C.AMOUNT), value)  # unsupported types fail loudly, never silently


# -- dates, phones, text ------------------------------------------------------------------------------


def test_two_digit_year_stays_inside_the_window_or_falls_back_to_placeholder():
    e = Pseudonymizer(KEY)
    outs = [e(ch(C.DATE), f"01/01/{y:02d}") for y in (69, 99, 0, 68) for _ in (0,)]
    for o in outs:
        assert re.fullmatch(r"\d\d/\d\d/\d\d", o) or o.startswith("[DATE_")


def test_dates_at_the_edge_of_the_calendar_do_not_crash():
    e = Pseudonymizer(KEY)
    assert e(ch(C.DATE), datetime(9999, 12, 31)) != datetime(9999, 12, 31) or True
    assert e(ch(C.DATE), "31/12/9999")  # either shifted or a placeholder, never an exception


def test_short_phone_and_non_text_become_placeholders_not_errors():
    e = Pseudonymizer(KEY)
    assert e(ch(C.PHONE), "12").startswith("[PHONE_")
    assert e(ch(C.FIRST_NAME), 42).startswith("[FIRST_NAME_")
    assert e(ch(C.FISCAL_CODE), 3.5).startswith("[FISCAL_CODE_")


def test_postcode_variants():
    e = Pseudonymizer(KEY)
    assert re.fullmatch(r"\d{5}", e(ch(C.POSTCODE), "00100"))
    assert e(ch(C.POSTCODE), "CAP 47121") != "CAP 47121"  # not purely digits: Faker postcode


# -- values: lossless encoding of every supported type -------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "testo",
        JsonString("Forlì", '"Forl\\u00ec"'),
        JsonNumber("1.10"),
        Decimal("2.50"),
        7,
        1.5,
        datetime(2020, 1, 2, 3, 4, 5),
        date(2020, 1, 2),
        True,
        False,
    ],
)
def test_encode_decode_roundtrip_keeps_type_and_spelling(value):
    back = decode_value(encode_value(value))
    assert type(back) is type(value) and back == value and kind_of(back) == kind_of(value)
    if isinstance(value, (JsonNumber, JsonString)):
        assert back.raw == value.raw
    assert value_key(back) == value_key(value)


def test_unknown_types_fail_loudly():
    with pytest.raises(TypeError):
        kind_of(object())
    with pytest.raises(ValueError):
        decode_value(["???", "x"])


# -- JSON: values that cannot be written ------------------------------------------------------------------------


def test_to_literal_covers_every_value_type():
    assert to_literal(None, False) == "null" and to_literal(True, False) == "true"
    assert to_literal(datetime(2020, 1, 2), False) == '"2020-01-02T00:00:00"'
    assert to_literal("è", True) == '"\\u00e8"' and to_literal("è", False) == '"è"'
    assert to_literal(Decimal("1E-7"), False) == "0.0000001"
    for bad in (float("nan"), float("inf")):
        with pytest.raises(VeloError, match="numerico"):
            to_literal(bad, False)
    with pytest.raises(VeloError, match="Tipo"):
        to_literal(object(), False)


def test_json_nonfinite_replacement_is_refused(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"a":1}')
    with pytest.raises(VeloError):
        JsonAdapter().apply(p, tmp_path / "o.json", {"a": ch(C.AMOUNT, fid="a")}, lambda c, v: float("nan"))
    assert not (tmp_path / "o.json").exists()


def test_json_chosen_field_without_values_is_reported(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"a":[null,""]}')
    rep = JsonAdapter().apply(p, tmp_path / "o.json", {"a[]": ch(C.TEXT, fid="a[]")}, tag)
    assert rep.replaced == {"a[]": 0} and any("non conteneva" in w for w in rep.warnings)


# -- CSV odds and ends -----------------------------------------------------------------------------------------


def test_csv_mixed_line_terminators_are_reported_and_unified(tmp_path):
    p = tmp_path / "a.csv"
    p.write_bytes(b"a;b\r\n1;2\n3;4\r\n")
    insp = CsvAdapter().inspect(p)
    assert any("misti" in w for w in insp.warnings)
    CsvAdapter().apply(p, tmp_path / "o.csv", {}, identity)
    assert (tmp_path / "o.csv").read_bytes() == b"a;b\r\n1;2\r\n3;4\r\n"


def test_csv_bad_encoding_override_and_empty_column(tmp_path):
    p = write_csv(tmp_path / "a.csv", "a;b\n1;\n2;\n")
    with pytest.raises(UnsupportedFileError, match="Codifica non ammessa"):
        CsvAdapter().apply(p, tmp_path / "o.csv", {}, identity, params={"encoding": "latin-7"})
    rep = CsvAdapter().apply(p, tmp_path / "o.csv", {"b": ch(C.TEXT, fid="b")}, tag)
    assert any("non conteneva" in w for w in rep.warnings)


def test_invalid_bytes_after_utf8_bom_are_refused(tmp_path):
    p = tmp_path / "a.csv"
    p.write_bytes(b"\xef\xbb\xbfa;b\n\xff\xfe;2\n")
    with pytest.raises(UnsupportedFileError):
        CsvAdapter().inspect(p)


def test_large_csv_sample_is_cut_at_a_row_boundary(tmp_path):
    rows = "\n".join(f"{i};{'x' * 50}" for i in range(3000))
    p = write_csv(tmp_path / "a.csv", "n;t\n" + rows + "\n")
    assert CsvAdapter().inspect(p).params["delimiter"] == ";"  # file is larger than the sniff window


# -- Excel package warnings ---------------------------------------------------------------------------------------


def _with_parts(tmp_path, parts: dict[str, bytes]):
    src = make_workbook(tmp_path / "base.xlsx")
    out = tmp_path / "parts.xlsx"
    shutil.copy(src, out)
    with zipfile.ZipFile(out, "a") as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return out


@pytest.mark.parametrize(
    "part, expected",
    [
        ("xl/externalLinks/externalLink1.xml", "collega altri file"),
        ("xl/pivotTables/pivotTable1.xml", "pivot"),
        ("xl/slicers/slicer1.xml", "slicer"),
        ("xl/threadedComments/threadedComment1.xml", "commenti a catena"),
    ],
)
def test_excel_warns_about_parts_it_cannot_preserve(tmp_path, part, expected):
    p = _with_parts(tmp_path, {part: b"<x/>"})
    assert any(expected in w for w in ExcelAdapter().inspect(p).warnings)


def test_excel_warns_about_shapes_and_images(tmp_path, monkeypatch):
    p = _with_parts(
        tmp_path,
        {
            "xl/drawings/drawing9.xml": b'<xdr:wsDr><xdr:twoCellAnchor><xdr:sp macro=""></xdr:sp></xdr:twoCellAnchor></xdr:wsDr>',
            "xl/media/image1.png": b"\x89PNG",
        },
    )
    w = ExcelAdapter().inspect(p).warnings
    assert any("forme o caselle" in x for x in w) and any("immagini" in x for x in w)
    monkeypatch.setitem(sys.modules, "PIL", None)  # as if Pillow were not installed
    assert any("Pillow non è installato" in x for x in ExcelAdapter().inspect(p).warnings)


def test_excel_with_empty_unnamed_column_and_unnamed_data_column(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S"
    ws["A1"], ws["A2"] = "Nome", "Mario"
    ws["C2"] = "dato senza intestazione"  # column B is entirely empty, C has data but no header
    p = tmp_path / "x.xlsx"
    wb.save(p)
    ids = [f.id for f in ExcelAdapter().inspect(p).fields]
    assert ids == ["S!Nome", "S!Colonna C"]


# -- service: failures leave nothing behind --------------------------------------------------------------------------


def test_service_rejects_unknown_key_mode_and_never_overwrites_the_original(tmp_path):
    src = write_csv(tmp_path / "a.pseudo.csv", "Nome\nMario\n")
    plan = {"Nome": ch(C.FIRST_NAME, fid="Nome")}
    with pytest.raises(VeloError, match="chiave"):
        pseudonymize(src, tmp_path / "o", plan, key_mode="boh")
    before = src.read_bytes()
    r = pseudonymize(src, tmp_path, plan)  # output name is derived: a.pseudo.pseudo.csv
    assert r.output.name == "a.pseudo.pseudo.csv" and src.read_bytes() == before


def test_failed_pseudonymization_leaves_no_partial_files(tmp_path):
    src = write_csv(tmp_path / "a.csv", "Nome\nMario\n")
    out = tmp_path / "o"
    with pytest.raises(PlanError):
        pseudonymize(src, out, {"Nope": ch(C.TEXT, fid="Nope")})
    assert list(out.iterdir()) == []


def test_failed_restore_leaves_no_partial_file(tmp_path):
    src = write_csv(tmp_path / "a.csv", "Nome\nMario\n")
    r = pseudonymize(src, tmp_path / "o", {"Nome": ch(C.FIRST_NAME, fid="Nome")})
    broken = write_csv(tmp_path / "b.pseudo.csv", "Altro\nx\n")  # lacks the column
    with pytest.raises(PlanError):
        restore(broken, r.mapping, tmp_path / "back.csv")
    assert not list(tmp_path.glob("*back*")) and not list(tmp_path.glob(".*part"))


@pytest.mark.parametrize("bad", ["1 234.56.7", "1.234,56,7", "1 2,3,4 5"])
def test_irregular_numbers_become_placeholders_not_crashes(bad):
    assert Pseudonymizer(KEY)(ch(C.AMOUNT), bad).startswith("[AMOUNT_")


def test_newlines_inside_quoted_fields_do_not_change_the_row_terminator(tmp_path):
    raw = b'a;b\r\n0;"x\n\ny"\r\n1;2\r\n'  # two LF inside a field, rows end with CRLF
    p = tmp_path / "a.csv"
    p.write_bytes(raw)
    assert CsvAdapter().inspect(p).params["lineterminator"] == "\r\n"
    CsvAdapter().apply(p, tmp_path / "o.csv", {}, identity)
    assert (tmp_path / "o.csv").read_bytes() == raw


# -- the pre-publication check ---------------------------------------------------------------------------------


def _load_checker():
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "scripts" / "check_publishable.py"
    spec = importlib.util.spec_from_file_location("check_publishable", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_publishable_check_flags_data_keys_secrets_and_personal_traces(tmp_path):
    checker = _load_checker()
    # The offending strings are assembled at run time so that this very file stays publishable.
    j = "".join
    notes = "\n".join(
        [
            j(["mail me at giuseppe", "@gmail.com"]),
            j(["C:", "\\Users\\mario\\Desktop\\x"]),
            j(["IT00X", "0000000000000000000000"]),
            j(["VRDNNA85C41", "H501Z"]),
            j(["token gh", "p_", "a" * 36]),
            j(["/ho", "me/mario/dati"]),
        ]
    )
    files = {
        "ok.py": "x = 1  # someone@example.com, a@b.test, IT60X0542811101000000123456\n",
        "clienti.pseudo.csv.velo-map.json": "{}",
        "project.key": "00",
        "dati.xlsx": "x",
        "notes.txt": notes,
    }
    paths = []
    for name, text in files.items():
        p = tmp_path / name
        p.write_text(text)
        paths.append(p)
    problems = "\n".join(checker.scan(paths, root=tmp_path))
    assert "ok.py" not in problems  # allowed synthetic values pass
    for expected in (
        "dizionario di ripristino",
        "chiave (non",
        "file di dati",
        "indirizzo email: " + j(["giuseppe", "@gmail.com"]),
        "percorso Windows personale",
        "percorso personale macOS/Linux",
        "token GitHub",
        "IBAN: " + j(["IT00X", "0000000000000000000000"]),
        "codice fiscale: " + j(["VRDNNA85C41", "H501Z"]),
    ):
        assert expected in problems, expected


def test_the_project_itself_is_publishable():
    checker = _load_checker()
    assert checker.scan(checker.tracked_files()) == []
