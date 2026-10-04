from datetime import date, datetime
from decimal import Decimal

import openpyxl
import pytest

from factories import write_csv
from velo.checks import CHECKS, PHRASES, find_mismatches, looks_like, signature
from velo.formats.json_format import JsonNumber, JsonString
from velo.model import Category as C
from velo.model import FieldChoice, Mode
from velo.validators import is_valid_fiscal_code

VALID_CF = "MRTMTT91D08F205J"
VALID_IBAN = "IT60X0542811101000000123456"
VALID_VAT = "12345678903"

GOOD = {
    C.FISCAL_CODE: [VALID_CF, VALID_CF.lower(), " " + VALID_CF, VALID_VAT],
    C.IBAN: [VALID_IBAN, "IT60 X054 2811 1010 0000 0123 456"],
    C.VAT_ID: [VALID_VAT, "IT" + VALID_VAT, int(VALID_VAT)],
    C.EMAIL: ["mario.rossi@example.com", " a@b.test "],
    C.PHONE: ["+39 333 1234567", "(055) 123456", "333-123-4567", 3331234567],
    C.POSTCODE: ["47121", "00100", "100", 47121, 118],
    C.DATE: ["01/02/1980", "1980-02-01", datetime(1980, 2, 1), date(1980, 2, 1)],
    C.AMOUNT: ["1.234,56", "€ 99,9", "-12", 5, 5.5, Decimal("1.10"), JsonNumber("1.10")],
    C.FULLNAME: ["Mario Rossi", JsonString("Forlì", '"Forlì"')],
    C.FIRST_NAME: ["Mario"],
    C.LAST_NAME: ["De Rossi"],
    C.CITY: ["Forlì"],
}
BAD = {
    C.FISCAL_CODE: ["Totale", VALID_CF[:-1] + "A", "12345", 5, True],
    C.IBAN: ["Totale", "IT61X0542811101000000123456", 123, None],
    C.VAT_ID: ["Totale", "12345678904", 123, True],
    C.EMAIL: ["Totale", "a@b", "a b@c.test", 5],
    C.PHONE: ["Totale", "12", "abc 333 1234567", True, 12],
    C.POSTCODE: ["Totale", "123456", "12a45", 12, "12", True],
    C.DATE: ["Totale", "boh", "31/02/1980", 19800201.5, True],
    C.AMOUNT: ["Totale", "circa dieci", "12 EUR 30", True],
    C.FULLNAME: ["Mario Rossi 2", 5],
    C.FIRST_NAME: ["Mario3"],
    C.LAST_NAME: ["Rossi1"],
    C.CITY: ["Zona 51"],
}


@pytest.mark.parametrize("cat", GOOD)
def test_good_values_pass(cat):
    assert all(looks_like(cat, v) for v in GOOD[cat]), cat


@pytest.mark.parametrize("cat", BAD)
def test_bad_values_are_flagged(cat):
    assert not any(looks_like(cat, v) for v in BAD[cat]), [v for v in BAD[cat] if looks_like(cat, v)]


def test_free_text_categories_have_no_check():
    assert C.TEXT not in CHECKS and C.ADDRESS not in CHECKS
    assert looks_like(C.TEXT, "qualsiasi cosa 123") and looks_like(C.ADDRESS, 5)


def test_every_checked_category_has_a_phrase():
    assert set(CHECKS) <= set(PHRASES)


def test_omocodia_fiscal_codes_are_accepted():
    base = VALID_CF
    # replace one digit with its omocodia letter and recompute the control letter
    from velo.validators import _CF_ODD

    body = list(base[:15])
    body[14] = "L"  # last digit of the progressive part: 5 -> N? any letter mapping works for the check
    body = "".join(body)
    total = sum(
        _CF_ODD[ch] if i % 2 == 0 else (int(ch) if ch.isdigit() else ord(ch) - 65)
        for i, ch in enumerate(body)
    )
    omocodic = body + chr(65 + total % 26)
    assert is_valid_fiscal_code(omocodic)
    assert not is_valid_fiscal_code(omocodic[:-1] + ("A" if omocodic[-1] != "A" else "B"))


# -- the dry run over real files --------------------------------------------------------------------


def plan_of(*pairs, mode=Mode.FAKE):
    return {fid: FieldChoice(fid, cat, mode) for fid, cat in pairs}


def test_excel_totals_row_is_reported_and_formulas_are_ignored(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Clienti"
    ws.append(["Nome", "IBAN", "Saldo"])
    ws.append(["Mario", VALID_IBAN, 100])
    ws.append(["Lucia", "IT60 X054 2811 1010 0000 0123 456", 200])
    ws.append([None, "Totale", "=SUM(C2:C3)"])
    ws.append([None, "=A2", None])  # a formula in the IBAN column is not a value to judge
    p = tmp_path / "x.xlsx"
    wb.save(p)
    found = find_mismatches(
        p,
        plan_of(("Clienti!IBAN", C.IBAN), ("Clienti!Saldo", C.AMOUNT), ("Clienti!Nome", C.FIRST_NAME)),
        tmp_path,
    )
    assert len(found) == 1
    m = found[0]
    assert (m.field_id, m.bad, m.total, m.examples) == ("Clienti!IBAN", 1, 3, ("Totale",))
    assert m.message() == "«Clienti!IBAN»: 1 valore su 3 non sembra un IBAN valido, per esempio «Totale»."
    assert not list(tmp_path.glob(".check-*"))  # temporary files are gone


def test_csv_and_json_dry_runs(tmp_path):
    csv = write_csv(tmp_path / "a.csv", "Data;Importo\n01/02/1980;10,5\nboh;n/d\nTotale;20\n")
    found = find_mismatches(csv, plan_of(("Data", C.DATE), ("Importo", C.AMOUNT)), tmp_path)
    assert {m.field_id: (m.bad, m.total) for m in found} == {"Data": (2, 3), "Importo": (1, 3)}
    assert found[0].message().startswith("«Data»: 2 valori su 3 non sembrano una data riconoscibile")

    js = tmp_path / "a.json"
    js.write_text('{"c":[{"mail":"a@b.test","n":1.10},{"mail":"zzz","n":null},{"mail":"","n":"x"}]}')
    found = find_mismatches(js, plan_of(("c[].mail", C.EMAIL), ("c[].n", C.AMOUNT)), tmp_path)
    assert {m.field_id: (m.bad, m.total) for m in found} == {"c[].mail": (1, 2), "c[].n": (1, 2)}


def test_clean_data_gives_no_warnings_and_original_file_is_untouched(tmp_path):
    p = write_csv(tmp_path / "a.csv", "Nome;Citta\nMario;Forlì\n", "cp1252")
    before = p.read_bytes()
    assert find_mismatches(p, plan_of(("Nome", C.FIRST_NAME), ("Citta", C.CITY)), tmp_path) == []
    assert p.read_bytes() == before


def test_examples_are_distinct_limited_and_short(tmp_path):
    rows = "\n".join(["Colonna"] + [f"x{i % 5}" + "y" * 80 for i in range(40)])
    p = write_csv(tmp_path / "a.csv", rows + "\n")
    (m,) = find_mismatches(p, plan_of(("Colonna", C.EMAIL)), tmp_path)
    assert m.bad == 40 and len(m.examples) == 3 and all(len(e) <= 40 for e in m.examples)


def test_signature_changes_with_the_warnings():
    from velo.checks import Mismatch

    a = [Mismatch("f", C.IBAN, 6, 1, ("Totale",))]
    b = [Mismatch("f", C.IBAN, 6, 2, ("Totale",))]
    assert signature(a) == signature(list(a)) != signature(b)
