import json
from decimal import Decimal

import pytest

from factories import identity, tag
from velo.errors import PlanError, UnsupportedFileError
from velo.formats import get_adapter
from velo.formats.json_format import JsonAdapter, JsonNumber
from velo.model import Category, FieldChoice, Mode

A = JsonAdapter()

DATA = {
    "clienti": [
        {
            "anagrafica": {"nome": "Mario Rossi", "cf": "RSSMRA80B01H501U"},
            "importo": 1.1,
            "tel": 3331234567,
            "vip": True,
            "note": None,
        },
        {
            "anagrafica": {"nome": "Lucia Bianchi", "cf": ""},
            "importo": 99.9,
            "tel": None,
            "vip": False,
            "note": "richiama",
        },
    ],
    "azienda": {"nome": "Acme S.r.l.", "città": "Forlì"},
}


def choice(fid, cat=Category.TEXT, mode=Mode.FAKE):
    return FieldChoice(fid, cat, mode)


def put(tmp_path, raw: bytes, name="in.json"):
    p = tmp_path / name
    p.write_bytes(raw)
    return p


def run(tmp_path, raw: bytes, plan, replacer, **params):
    dst = tmp_path / "out.json"
    rep = A.apply(put(tmp_path, raw), dst, plan, replacer, params or None)
    return dst.read_bytes(), rep


# -- the identity roundtrip must be byte-for-byte, whatever the formatting -----

CASES = {
    "python_indent2": json.dumps(DATA, indent=2, ensure_ascii=False).encode(),
    "python_indent4_ascii": json.dumps(DATA, indent=4).encode(),
    "compact": json.dumps(DATA, separators=(",", ":"), ensure_ascii=False).encode(),
    "tabs_crlf": json.dumps(DATA, indent="\t", ensure_ascii=False).replace("\n", "\r\n").encode(),
    "bom": b"\xef\xbb\xbf" + json.dumps(DATA, ensure_ascii=False).encode(),
    "cp1252": '{"città": "Forlì"}'.encode("cp1252"),
    "hand_formatted": b'{ "a" :[1,  2 ,\n3] ,"b":{ } ,"c":[ ]}\n\n',
    "number_spellings": b'{"n":[1.10, 1e5, 1E+2, -0, 0.000, 12345678901234567890, 1.5e-10]}',
    "escapes": b'{"url":"http:\\/\\/x.it","s":"\\u00e8 \\"q\\" \\n"}',
    "duplicate_keys": b'{"nome":"A","nome":"B"}',
    "root_array": b'[{"nome":"A"},{"nome":"B"}]',
    "root_scalar": b'"solo testo"',
}


@pytest.mark.parametrize("name", CASES)
def test_identity_roundtrip_is_byte_identical(tmp_path, name):
    raw = CASES[name]
    out, _ = run(tmp_path, raw, {}, identity)
    assert out == raw


@pytest.mark.parametrize("name", CASES)
def test_every_field_through_identity_is_still_byte_identical(tmp_path, name):
    """Replacing every field with itself must not change a byte either."""
    raw = CASES[name]
    ids = [f.id for f in A.inspect(put(tmp_path, raw, "x.json")).fields]
    out, _ = run(tmp_path, raw, {i: choice(i) for i in ids}, identity)
    assert out == raw


# -- paths ------------------------------------------------------------------------


def test_paths_of_nested_structure(tmp_path):
    p = put(tmp_path, json.dumps(DATA).encode())
    ids = [f.id for f in A.inspect(p).fields]
    assert ids == [
        "clienti[].anagrafica.nome",
        "clienti[].anagrafica.cf",
        "clienti[].importo",
        "clienti[].tel",
        "clienti[].vip",
        "clienti[].note",
        "azienda.nome",
        "azienda.città",
    ]


@pytest.mark.parametrize(
    "raw, expected",
    [
        (b'[{"nome":"A"}]', ["[].nome"]),
        (b'{"m":[[1,2],[3]]}', ["m[][]"]),
        (b'"x"', ["$"]),
        (b'{"a.b":1,"a":{"b":2}}', ["a\\.b", "a.b"]),
        (b'{"":1,"x[]":2,"q\\"":3}', ['""', "x\\[\\]", 'q\\"']),
        (b'{"l":[1,{"k":2}]}', ["l[]", "l[].k"]),
    ],
)
def test_path_rendering_is_unambiguous(tmp_path, raw, expected):
    assert [f.id for f in A.inspect(put(tmp_path, raw)).fields] == expected


def test_preview_counts_and_samples(tmp_path):
    fields = {f.id: f for f in A.inspect(put(tmp_path, CASES["number_spellings"])).fields}
    assert fields["n[]"].sample == ("1.10", "1e5", "1E+2", "-0", "0.000")  # as written
    fields = {f.id: f for f in A.inspect(put(tmp_path, json.dumps(DATA).encode())).fields}
    assert fields["clienti[].anagrafica.cf"].non_empty == 1  # "" not counted
    assert fields["clienti[].note"].non_empty == 1  # null not counted


# -- replacing --------------------------------------------------------------------


def test_only_chosen_spans_change(tmp_path):
    raw = json.dumps(DATA, indent=2, ensure_ascii=False).encode()
    out, rep = run(tmp_path, raw, {"clienti[].anagrafica.nome": choice("clienti[].anagrafica.nome")}, tag)
    expected = raw.replace(b'"Mario Rossi"', b'"X[Mario Rossi]"').replace(
        b'"Lucia Bianchi"', b'"X[Lucia Bianchi]"'
    )
    assert out == expected
    assert b'"Acme S.r.l."' in out  # same key name elsewhere, different path: intact
    assert rep.replaced == {"clienti[].anagrafica.nome": 2}


def test_numbers_reach_the_replacer_exact_and_untouched_ones_keep_spelling(tmp_path):
    raw = b'{"a":1.10,"b":1.10,"c":12345678901234567890}'
    seen = []

    def rec(ch, v):
        seen.append(v)
        return v

    out, _ = run(tmp_path, raw, {"a": choice("a"), "c": choice("c")}, rec)
    assert out == raw
    assert all(isinstance(v, JsonNumber) for v in seen)
    assert seen[0] == Decimal("1.10") and seen[0].raw == "1.10"
    assert seen[1] == Decimal(12345678901234567890)  # no float rounding


def test_replacement_numbers_are_written_as_numbers(tmp_path):
    raw = b'{"a":1.10,"b":7}'
    out, rep = run(
        tmp_path,
        raw,
        {"a": choice("a"), "b": choice("b")},
        lambda c, v: Decimal("2.50") if c.field_id == "a" else 8,
    )
    assert out == b'{"a":2.50,"b":8}' and not rep.warnings


def test_placeholder_in_numeric_field_changes_type_and_warns(tmp_path):
    out, rep = run(
        tmp_path,
        b'{"tel":3331234567}',
        {"tel": choice("tel", Category.PHONE, Mode.PLACEHOLDER)},
        lambda c, v: "[PHONE_K7Q2M]",
    )
    assert out == b'{"tel":"[PHONE_K7Q2M]"}'
    assert any("tipo del valore" in w for w in rep.warnings)


def test_null_and_empty_strings_are_not_replaced_booleans_are(tmp_path):
    raw = b'{"x":[null,"",true,"a"]}'
    out, rep = run(
        tmp_path, raw, {"x[]": choice("x[]")}, lambda c, v: (not v) if isinstance(v, bool) else "Z"
    )
    assert out == b'{"x":[null,"",false,"Z"]}'
    assert rep.replaced == {"x[]": 2}


def test_duplicate_keys_are_all_replaced(tmp_path):
    out, rep = run(tmp_path, CASES["duplicate_keys"], {"nome": choice("nome")}, tag)
    assert out == b'{"nome":"X[A]","nome":"X[B]"}'


def test_unicode_style_follows_the_file(tmp_path):
    escaped, _ = run(tmp_path, b'{"c":"Forl\\u00ec","n":"x"}', {"n": choice("n")}, lambda c, v: "Niccolò")
    assert escaped == b'{"c":"Forl\\u00ec","n":"Niccol\\u00f2"}'
    raw_utf8, _ = run(tmp_path, '{"c":"Forlì","n":"x"}'.encode(), {"n": choice("n")}, lambda c, v: "Niccolò")
    assert raw_utf8 == '{"c":"Forlì","n":"Niccolò"}'.encode()


def test_cp1252_never_fails_on_unencodable_replacement(tmp_path):
    raw = '{"città":"Forlì","n":"x"}'.encode("cp1252")
    out, rep = run(tmp_path, raw, {"n": choice("n")}, lambda c, v: "Łukasz è")
    assert out == '{"città":"Forlì","n":"\\u0141ukasz \\u00e8"}'.encode("cp1252")
    assert json.loads(out.decode("cp1252"))["n"] == "Łukasz è"


def test_replacement_strings_are_escaped(tmp_path):
    out, _ = run(tmp_path, b'{"n":"x"}', {"n": choice("n")}, lambda c, v: 'a"b\\c\n')
    assert json.loads(out)["n"] == 'a"b\\c\n'


def test_output_is_always_valid_json_with_same_shape(tmp_path):
    raw = json.dumps(DATA, indent=2).encode()
    ids = [f.id for f in A.inspect(put(tmp_path, raw, "x.json")).fields]
    out, _ = run(tmp_path, raw, {i: choice(i) for i in ids}, lambda c, v: "Z" if isinstance(v, str) else v)

    def shape(o):
        if isinstance(o, dict):
            return {k: shape(v) for k, v in o.items()}
        if isinstance(o, list):
            return [shape(v) for v in o]
        return None

    assert shape(json.loads(out)) == shape(DATA)


def test_reverse_replacement_restores_original_bytes(tmp_path):
    """What the restore step will do: forward with a map, then back."""
    raw = CASES["number_spellings"]
    forward = {}

    def fwd(c, v):
        fake = f"F{len(forward)}"
        forward[fake] = v
        return fake

    out, _ = run(tmp_path, raw, {"n[]": choice("n[]")}, fwd)
    restored = tmp_path / "restored.json"
    A.apply(put(tmp_path, out, "pseudo.json"), restored, {"n[]": choice("n[]")}, lambda c, v: forward[v])
    assert restored.read_bytes() == raw


# -- errors -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{",
        b'{"a":1,}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b"{'a':1}",
        b'{"a":1} x',
    ],
)
def test_invalid_json_is_refused(tmp_path, raw):
    with pytest.raises(UnsupportedFileError):
        A.inspect(put(tmp_path, raw))


def test_unknown_path_is_an_error(tmp_path):
    with pytest.raises(PlanError, match="clienti.nome"):
        run(tmp_path, json.dumps(DATA).encode(), {"clienti.nome": choice("clienti.nome")}, tag)
    assert not (tmp_path / "out.json").exists()


def test_adapter_lookup():
    assert get_adapter("dati.JSON").name == "json"


# -- randomised documents ---------------------------------------------------------


def _random_doc(rng, depth=0):
    kind = rng.choice(["obj", "arr", "str", "num", "lit"] if depth < 4 else ["str", "num", "lit"])
    if kind == "obj":
        keys = ["nome", "a.b", "", "x[]", 'q"', "città", "k"]
        return {
            rng.choice(keys) + str(rng.randint(0, 2)): _random_doc(rng, depth + 1)
            for _ in range(rng.randint(0, 4))
        }
    if kind == "arr":
        return [_random_doc(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    if kind == "str":
        return rng.choice(["", "Mario", "è/ù", 'a"b', "\n\t", "😀"])
    if kind == "num":
        return rng.choice([0, -1, 1.1, 1e-7, 10**20, 2.5e300])
    return rng.choice([True, False, None])


def test_random_documents(tmp_path):
    import random

    rng = random.Random(1234)
    for _ in range(300):
        doc = _random_doc(rng)
        raw = json.dumps(
            doc, indent=rng.choice([None, 1, 4, "\t"]), ensure_ascii=rng.choice([True, False])
        ).encode()
        out, _ = run(tmp_path, raw, {}, identity)
        assert out == raw
        ids = [f.id for f in A.inspect(put(tmp_path, raw, "x.json")).fields]
        out, _ = run(
            tmp_path, raw, {i: choice(i) for i in ids}, lambda c, v: f"<{v}>" if isinstance(v, str) else v
        )
        reparsed = json.loads(out)

        def strip(o):  # undo the tagging to compare with the original
            if isinstance(o, dict):
                return {k: strip(v) for k, v in o.items()}
            if isinstance(o, list):
                return [strip(v) for v in o]
            if isinstance(o, str) and o.startswith("<") and o.endswith(">"):
                return o[1:-1]
            return o

        assert strip(reparsed) == json.loads(raw)
