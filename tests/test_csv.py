import pytest

from factories import CSV_IT, identity, tag, write_csv
from velo.errors import EncodingError, PlanError, UnsupportedFileError
from velo.formats import get_adapter
from velo.formats.csv_format import CsvAdapter
from velo.model import Category, FieldChoice, Mode

A = CsvAdapter()


def choice(fid, cat=Category.TEXT):
    return FieldChoice(fid, cat, Mode.FAKE)


def roundtrip(tmp_path, raw: bytes, name="in.csv"):
    src = tmp_path / name
    src.write_bytes(raw)
    dst = tmp_path / "out.csv"
    A.apply(src, dst, {}, identity)
    return dst.read_bytes()


# -- the identity roundtrip must be byte-for-byte, whatever the dialect --------

CASES = {
    "it_cp1252_crlf": CSV_IT.encode("cp1252"),
    "utf8_bom_lf_comma": b"\xef\xbb\xbfa,b,c\n1,2,3\n4,5,6\n",
    "utf8_tab": "a\tb\nè\tù\n".encode(),
    "pipe": b"a|b|c\n1|2|3\n",
    "no_final_newline": b"a;b\r\n1;2",
    "quoted_embedded_newline": b'a;b\r\n"riga1\r\nriga2";x\r\n',
    "quoted_delimiter": b'a;b\r\n"1;5";x\r\n',
    "quote_all": b'"a";"b"\r\n"1";"2"\r\n',
    "blank_and_ragged": b"a;b;c\r\n1;2\r\n\r\n1;2;3;4\r\n",
    "doubled_quotes": b'a;b\r\n"dice ""ciao""";x\r\n',
    "cr_only": b"a;b\r1;2\r",
    "header_needs_quotes_body_does_not": b'";";""""\r\n;',
}


@pytest.mark.parametrize("name", CASES)
def test_identity_roundtrip_is_byte_identical(tmp_path, name):
    raw = CASES[name]
    assert roundtrip(tmp_path, raw) == raw


# -- detection ------------------------------------------------------------------


def test_detects_italian_dialect(tmp_path):
    p = write_csv(tmp_path / "a.csv", CSV_IT, "cp1252")
    insp = A.inspect(p)
    assert insp.params["delimiter"] == ";"
    assert insp.params["encoding"] == "cp1252"
    assert insp.params["lineterminator"] == "\r\n"
    assert [f.id for f in insp.fields] == ["Nome", "Cognome", "Importo", "Citta", "Data"]
    assert insp.fields[2].sample == ("1.234,56", "99,9", "0,5")  # decimal commas kept as text
    assert insp.fields[1].non_empty == 2  # the empty value is not counted


def test_decimal_comma_does_not_fool_delimiter(tmp_path):
    p = tmp_path / "a.csv"
    p.write_bytes(b"x;y\r\n1,5;2,5\r\n3,5;4,5\r\n")
    assert A.inspect(p).params["delimiter"] == ";"


def test_utf8_vs_cp1252_vs_bom(tmp_path):
    assert A.inspect(write_csv(tmp_path / "1.csv", "a;b\nè;ù\n")).params["encoding"] == "utf-8"
    assert A.inspect(write_csv(tmp_path / "2.csv", "a;b\nè;ù\n", "cp1252")).params["encoding"] == "cp1252"
    assert A.inspect(write_csv(tmp_path / "3.csv", "a;b\nè;ù\n", bom=True)).params["bom"] is True


def test_ascii_only_is_flagged(tmp_path):
    insp = A.inspect(write_csv(tmp_path / "a.csv", "a;b\n1;2\n"))
    assert insp.params["ascii_only"] and insp.warnings


def test_duplicate_and_blank_headers(tmp_path):
    p = write_csv(tmp_path / "a.csv", "a;a; \n1;2;3\n")
    assert [f.id for f in A.inspect(p).fields] == ["a", "a#2", "Colonna 3"]


@pytest.mark.parametrize("raw", [b"", b"\xff\xfea\x00;\x00b\x00", b"a;b\n\x81\x8d;x\n"])
def test_unreadable_files_are_refused(tmp_path, raw):
    p = tmp_path / "a.csv"
    p.write_bytes(raw)
    with pytest.raises(UnsupportedFileError):
        A.inspect(p)


# -- replacing ------------------------------------------------------------------


def test_only_chosen_columns_change(tmp_path):
    src = write_csv(tmp_path / "in.csv", CSV_IT, "cp1252")
    dst = tmp_path / "out.csv"
    rep = A.apply(src, dst, {"Nome": choice("Nome"), "Citta": choice("Citta")}, tag)
    out = dst.read_bytes().decode("cp1252")
    assert out == (
        "Nome;Cognome;Importo;Citta;Data\r\n"
        "X[Mario];Rossi;1.234,56;X[Perù];01/02/1980\r\n"
        "X[Lucia];Bianchi;99,9;X[Forlì];15/11/1975\r\n"
        "X[Anna];;0,5;X[Torino];\r\n"
    )
    assert rep.replaced == {"Nome": 3, "Citta": 3}


def test_empty_values_are_not_replaced(tmp_path):
    src = write_csv(tmp_path / "in.csv", CSV_IT, "cp1252")
    rep = A.apply(src, tmp_path / "o.csv", {"Cognome": choice("Cognome")}, tag)
    assert rep.replaced["Cognome"] == 2
    assert ";;" in (tmp_path / "o.csv").read_text("cp1252")


def test_non_string_replacement_is_converted(tmp_path):
    src = write_csv(tmp_path / "in.csv", "a;b\n1;2\n")
    A.apply(src, tmp_path / "o.csv", {"a": choice("a")}, lambda c, v: 42)
    assert (tmp_path / "o.csv").read_text() == "a;b\r\n42;2\n".replace("\r\n", "\n")


def test_unknown_field_is_an_error(tmp_path):
    src = write_csv(tmp_path / "in.csv", CSV_IT, "cp1252")
    with pytest.raises(PlanError, match="Nomee"):
        A.apply(src, tmp_path / "o.csv", {"Nomee": choice("Nomee")}, tag)
    assert not (tmp_path / "o.csv").exists()


def test_unencodable_replacement_is_an_error_not_corruption(tmp_path):
    src = write_csv(tmp_path / "in.csv", CSV_IT, "cp1252")
    with pytest.raises(EncodingError):
        A.apply(src, tmp_path / "o.csv", {"Nome": choice("Nome")}, lambda c, v: "Łukasz")
    assert not (tmp_path / "o.csv").exists()


def test_encoding_override_allows_utf8_output(tmp_path):
    src = write_csv(tmp_path / "in.csv", CSV_IT, "cp1252")
    A.apply(
        src, tmp_path / "o.csv", {"Nome": choice("Nome")}, lambda c, v: "Łukasz", params={"encoding": "utf-8"}
    )
    assert "Łukasz" in (tmp_path / "o.csv").read_text("utf-8")


def test_delimiter_inside_replacement_gets_quoted(tmp_path):
    src = write_csv(tmp_path / "in.csv", "a;b\r\n1;2\r\n")
    A.apply(src, tmp_path / "o.csv", {"a": choice("a")}, lambda c, v: "x;y")
    assert (tmp_path / "o.csv").read_bytes() == b'a;b\r\n"x;y";2\r\n'


def test_get_adapter_by_extension(tmp_path):
    assert get_adapter("x.CSV").name == "csv"
    assert get_adapter("x.xlsx").name == "excel"
    with pytest.raises(UnsupportedFileError):
        get_adapter("x.pdf")


def test_unusual_quoting_is_reported_not_silently_rewritten(tmp_path):
    p = tmp_path / "a.csv"
    p.write_bytes(b'a;b\r\n"1";2\r\n')  # quotes that minimal quoting would not write
    insp = A.inspect(p)
    assert any("virgolette" in w for w in insp.warnings)
    A.apply(p, tmp_path / "o.csv", {}, identity)
    assert (tmp_path / "o.csv").read_bytes() == b"a;b\r\n1;2\r\n"  # values identical, quotes normalised


def test_standard_quoting_gives_no_warning(tmp_path):
    for raw in (b"a;b\r\n1;2\r\n", b'"a";"b"\r\n"1";"2"\r\n', b'a;b\r\n"x;y";2\r\n'):
        p = tmp_path / "a.csv"
        p.write_bytes(raw)
        assert not any("virgolette" in w for w in A.inspect(p).warnings), raw
