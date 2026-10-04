import re
from datetime import date, datetime
from decimal import Decimal

import pytest

from velo.engine import Pseudonymizer
from velo.errors import VeloError
from velo.formats.json_format import JsonNumber, JsonString
from velo.model import Category as C
from velo.model import FieldChoice, Mode
from velo.validators import is_valid_fiscal_code, is_valid_iban, is_valid_vat

KEY = bytes(range(32))


def ch(cat, mode=Mode.FAKE, fid="f"):
    return FieldChoice(fid, cat, mode)


@pytest.fixture
def eng():
    return Pseudonymizer(KEY)


# -- determinism and coherence ------------------------------------------------------


def test_same_key_same_value_same_fake_across_instances():
    a, b = Pseudonymizer(KEY), Pseudonymizer(KEY)
    names = [f"Persona{i} Test" for i in range(50)]
    assert [a(ch(C.FULLNAME), n) for n in names] == [b(ch(C.FULLNAME), n) for n in names]


def test_order_of_arrival_does_not_change_fakes_without_collisions():
    a, b = Pseudonymizer(KEY), Pseudonymizer(KEY)
    names = [f"Persona{i} Test" for i in range(30)]
    fa = {n: a(ch(C.FULLNAME), n) for n in names}
    fb = {n: b(ch(C.FULLNAME), n) for n in reversed(names)}
    assert fa == fb


def test_other_key_other_fakes():
    other = Pseudonymizer(b"\x01" * 32)
    mine = Pseudonymizer(KEY)
    names = [f"Persona{i}" for i in range(20)]
    assert [mine(ch(C.FULLNAME), n) for n in names] != [other(ch(C.FULLNAME), n) for n in names]


def test_same_value_same_fake_in_different_fields(eng):
    assert eng(ch(C.FULLNAME, fid="Clienti!Nome"), "Mario Rossi") == eng(
        ch(C.FULLNAME, fid="Ordini!Cliente"), "Mario Rossi"
    )


def test_same_text_in_different_categories_is_independent(eng):
    assert eng(ch(C.FIRST_NAME), "Marco") != eng(ch(C.LAST_NAME), "Marco")


def test_fake_never_equals_real(eng):
    for i in range(300):
        v = f"Mario{i}"
        assert eng(ch(C.FIRST_NAME), v) != v


# -- injectivity (needed for restore) ---------------------------------------------------


def test_fakes_are_unique_for_many_distinct_values(eng):
    originals = [f"Persona{i} Cognome{i}" for i in range(6000)]
    fakes = [eng(ch(C.FULLNAME), v) for v in originals]
    assert len(set(fakes)) == len(originals)
    assert len(eng.entries()["fullname"]) == len(originals)


def test_small_pools_fall_back_to_numeric_suffix_and_say_so(eng):
    originals = [f"Nome{i}" for i in range(2500)]  # more than distinct Faker first names
    fakes = [eng(ch(C.FIRST_NAME), v) for v in originals]
    assert len(set(fakes)) == 2500
    assert eng.suffixed["first_name"] > 0
    assert any("numero finale" in n for n in eng.notes())


def test_placeholders_are_unique_and_shaped(eng):
    ph = [eng(ch(C.FULLNAME, Mode.PLACEHOLDER), f"P{i}") for i in range(3000)]
    assert len(set(ph)) == 3000
    assert all(re.fullmatch(r"\[FULLNAME_[A-Z2-7]{5}\]", p) for p in ph)
    assert eng(ch(C.FIRST_NAME, Mode.PLACEHOLDER), "x").startswith("[FIRST_NAME_")


def test_fixed_format_categories_have_no_suffix_fallback(eng):
    assert Pseudonymizer(KEY)(ch(C.FISCAL_CODE), "RSSMRA80A01H501U")  # works
    # exhausting is practically impossible; the guard exists for correctness
    from velo.generators import SUFFIXABLE

    assert C.FISCAL_CODE not in SUFFIXABLE and C.IBAN not in SUFFIXABLE


# -- identifiers --------------------------------------------------------------------------


def test_fiscal_codes_are_valid_and_keep_case(eng):
    outs = [eng(ch(C.FISCAL_CODE), f"RSSMRA80A01H{i:03d}X") for i in range(300)]
    assert all(is_valid_fiscal_code(o) for o in outs)
    assert is_valid_fiscal_code(eng(ch(C.FISCAL_CODE), "rssmra80a01h501u").upper())
    assert eng(ch(C.FISCAL_CODE), "rssmra80a01h501a").islower()


def test_validators_reject_wrong_values():
    assert (
        not is_valid_fiscal_code("RSSMRA80A01H501") and not is_valid_iban("IT00X") and not is_valid_vat("123")
    )
    assert is_valid_iban("IT60X0542811101000000123456")
    assert not is_valid_iban("IT61X0542811101000000123456")
    assert is_valid_vat("IT12345678903") and not is_valid_vat("12345678904")
    assert is_valid_fiscal_code("MRTMTT91D08F205J") and not is_valid_fiscal_code("MRTMTT91D08F205K")


def test_iban_valid_and_layout_kept(eng):
    compact = eng(ch(C.IBAN), "IT60X0542811101000000123456")
    spaced = eng(ch(C.IBAN), "IT60 X054 2811 1010 0000 0123 456")
    assert is_valid_iban(compact) and " " not in compact and len(compact) == 27
    assert is_valid_iban(spaced) and spaced.count(" ") == 6
    assert eng(ch(C.IBAN), "it60x0542811101000000123456").islower()


def test_vat_ids_are_valid_in_bulk(eng):
    assert all(is_valid_vat(eng(ch(C.VAT_ID), f"IT{i:011d}")) for i in range(500))


def test_vat_prefix_follows_original(eng):
    with_it = eng(ch(C.VAT_ID), "IT12345678903")
    without = eng(ch(C.VAT_ID), "12345678903")
    assert with_it.startswith("IT") and is_valid_vat(with_it)
    assert re.fullmatch(r"\d{11}", without) and is_valid_vat(without)


def test_email_uses_reserved_domains_and_keeps_case(eng):
    outs = [eng(ch(C.EMAIL), f"user{i}@posta.test") for i in range(200)]
    assert all(re.fullmatch(r"[^@\s]+@example\.(com|net|org)", o) for o in outs)
    assert eng(ch(C.EMAIL), "MARIO@X.TEST").isupper()


@pytest.mark.parametrize(
    "original",
    [
        "333 1234567",
        "+39 333 1234567",
        "0039 333 1234567",
        "+393331234567",
        "333-123-4567",
        "(055) 123456",
        "0543 123456",
        "3331234567",
    ],
)
def test_phone_layout_prefix_and_first_digit_kept(eng, original):
    out = eng(ch(C.PHONE), original)
    assert out != original
    shape = lambda s: re.sub(r"\d", "9", s)
    assert shape(out) == shape(original)
    m = re.match(r"^(\s*(?:\+|00)39[\s.\-]*)", original)
    prefix = m.group(1) if m else ""
    assert out.startswith(prefix)
    first = lambda s: next(c for c in s[len(prefix) :] if c.isdigit())
    assert first(out) == first(original)


def test_phone_numeric_cell_stays_int(eng):
    out = eng(ch(C.PHONE), 3331234567)
    assert isinstance(out, int) and len(str(out)) == 10 and str(out)[0] == "3"


def test_postcode(eng):
    assert re.fullmatch(r"\d{5}", eng(ch(C.POSTCODE), "47121"))
    assert isinstance(eng(ch(C.POSTCODE), 47121), int)


def test_address_city_text(eng):
    assert eng(ch(C.ADDRESS), "Via Roma 1") != "Via Roma 1"
    assert eng(ch(C.CITY), "FORLÌ").isupper()
    t = eng(ch(C.TEXT), "Il cliente Mario Rossi abita a Forlì e ha chiamato ieri.")
    assert "Mario" not in t and isinstance(t, str) and len(t) <= 56
    assert eng(ch(C.TEXT), "ok")  # shorter than the minimum Faker text


def test_name_case_is_kept(eng):
    assert eng(ch(C.FULLNAME), "ROSSI MARIO").isupper()
    assert eng(ch(C.FULLNAME), "rossi mario").islower()


def test_everything_is_writable_in_windows_1252(eng):
    for i in range(3000):
        for cat in (C.FULLNAME, C.CITY, C.ADDRESS, C.TEXT, C.EMAIL):
            eng(ch(cat), f"valore{i}").encode("cp1252")


# -- dates ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "original, fmt",
    [
        ("01/02/1980", "%d/%m/%Y"),
        ("1980-02-01", "%Y-%m-%d"),
        ("01.02.1980", "%d.%m.%Y"),
        ("01-02-1980", "%d-%m-%Y"),
        ("1980-02-01T10:30:00", "%Y-%m-%dT%H:%M:%S"),
        ("01/02/80", "%d/%m/%y"),
        ("19800201", "%Y%m%d"),
    ],
)
def test_text_dates_keep_format_and_move_by_a_bounded_amount(eng, original, fmt):
    out = eng(ch(C.DATE), original)
    a, b = datetime.strptime(original, fmt), datetime.strptime(out, fmt)
    assert out != original and 0 < abs((a - b).days) <= 730 + 10 * 100


def test_date_types_are_kept(eng):
    d = eng(ch(C.DATE), datetime(1980, 2, 1, 10, 30))
    assert (
        isinstance(d, datetime)
        and d != datetime(1980, 2, 1, 10, 30)
        and d.time() == datetime(1980, 2, 1, 10, 30).time()
    )
    e = eng(ch(C.DATE), date(1980, 2, 1))
    assert type(e) is date and e != date(1980, 2, 1)


def test_unparsable_date_becomes_placeholder_and_is_reported(eng):
    out = eng(ch(C.DATE, fid="Data"), "n/d")
    assert re.fullmatch(r"\[DATE_[A-Z2-7]{5}\]", out)
    assert any("Data" in n and "segnaposto" in n for n in eng.notes())


# -- amounts --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "original",
    [
        "1.234,56",
        "99,9",
        "1234,5",
        "€ 1.234,56",
        "1.234,56 €",
        "-12,50",
        "(100,00)",
        "1234.5",
        "1,234.56",
        "12",
        "1.234.567,89",
        "0,5",
        "EUR 7",
        "+3,25",
    ],
)
def test_text_amounts_keep_their_format(eng, original):
    out = eng(ch(C.AMOUNT), original)
    assert out != original
    # same separators, symbols and sign; digit groups may differ only in count
    skeleton = lambda s: re.sub(r"\d", "", s)
    if "." in original and "," not in original and len(original.split(".")[-1]) != 3:
        pass
    assert skeleton(out).replace(".", "").replace(",", "") == skeleton(original).replace(".", "").replace(
        ",", ""
    )
    # decimals count is preserved
    dec = lambda s: len(re.search(r"[.,](\d+)\D*$", s).group(1)) if re.search(r"[.,](\d+)\D*$", s) else 0
    if not re.fullmatch(r"[^\d]*\d{1,3}(\.\d{3})+[^\d]*", original):
        assert dec(out) == dec(original)


def test_text_amount_scale_and_sign(eng):
    outs = [eng(ch(C.AMOUNT), f"{1000 + i},00") for i in range(300)]
    values = [float(o.replace(".", "").replace(",", ".")) for o in outs]
    assert all(300 <= v <= 3000 for v in values)  # same order of magnitude
    assert eng(ch(C.AMOUNT), "-12,50").startswith("-")
    assert eng(ch(C.AMOUNT), "(100,00)").startswith("(")


def test_numeric_amounts_keep_type_and_decimals(eng):
    f = eng(ch(C.AMOUNT), 1234.56)
    assert isinstance(f, float) and f != 1234.56 and len(repr(f).split(".")[1]) <= 2
    i = eng(ch(C.AMOUNT), 100)
    assert isinstance(i, int) and i != 100
    d = eng(ch(C.AMOUNT), JsonNumber("1.10"))
    assert (
        isinstance(d, Decimal) and format(d, "f").count(".") == 1 and len(format(d, "f").split(".")[1]) == 2
    )
    assert eng(ch(C.AMOUNT), -5) < 0


def test_zero_stays_zero_and_is_restorable(eng):
    assert eng(ch(C.AMOUNT), "0,00") == "0,00" and eng(ch(C.AMOUNT), 0) == 0
    assert eng(ch(C.AMOUNT), "0,00") == "0,00"  # cached
    assert eng.entries()["amount"]["0,00"] == ["str", "0,00"]


def test_other_amounts_never_land_on_a_used_value(eng):
    outs = [eng(ch(C.AMOUNT), i) for i in range(1, 400)]  # tiny integers collide a lot
    assert len(set(outs)) == len(outs) and all(o != i for o, i in zip(outs, range(1, 400)))


def test_unparsable_amount_becomes_placeholder(eng):
    assert eng(ch(C.AMOUNT, fid="Imp"), "circa dieci euro").startswith("[AMOUNT_")
    assert eng(ch(C.AMOUNT, fid="Imp"), "12 EUR 30").startswith("[AMOUNT_")


def test_booleans_fake_untouched_placeholder_replaced(eng):
    assert eng(ch(C.TEXT, fid="vip"), True) is True
    assert any("booleani" in n for n in eng.notes())
    assert eng(ch(C.TEXT, Mode.PLACEHOLDER), True).startswith("[TEXT_")


def test_json_strings_share_fakes_across_spellings(eng):
    a = eng(ch(C.CITY), JsonString("Forlì", '"Forlì"'))
    b = eng(ch(C.CITY), JsonString("Forlì", '"Forl\\u00ec"'))
    assert a == b


def test_short_key_is_rejected():
    with pytest.raises(ValueError):
        Pseudonymizer(b"short")


def test_exhausted_fixed_format_raises_instead_of_looping(monkeypatch):
    from velo import engine, generators

    monkeypatch.setitem(generators.GENERATORS, C.FISCAL_CODE, lambda fk, rng, v, a: "AAAAAAAAAAAAAAAA")
    monkeypatch.setattr(engine, "GENERATORS", generators.GENERATORS)
    e = Pseudonymizer(KEY)
    e(ch(C.FISCAL_CODE), "RSSMRA80A01H501U")
    with pytest.raises(VeloError, match="esauriti"):
        e(ch(C.FISCAL_CODE), "BNCLCU75S55D704K")


def test_whole_floats_and_ints_share_a_key_because_xlsx_does_not_tell_them_apart():
    from velo.values import value_key

    assert value_key(140.0) == value_key(140) == "140" and value_key(99.9) == "99.9"
