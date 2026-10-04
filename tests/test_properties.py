"""Property tests: random inputs, strong invariants (round trips and one-to-one mappings)."""

import csv
import io
import json
import os
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from velo.engine import Pseudonymizer
from velo.formats import get_adapter
from velo.formats.csv_format import CsvAdapter
from velo.formats.json_format import JsonAdapter
from velo.mapping import Restorer
from velo.model import Category as C
from velo.model import FieldChoice, Mode
from velo.service import pseudonymize, restore

SETTINGS = settings(
    max_examples=int(os.environ.get("VELO_EXAMPLES", "80")),
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
KEY = bytes(range(32))

# -- CSV -------------------------------------------------------------------------------------------------

cell = st.text(alphabet=st.sampled_from(list("abcXYZ 019;,|\"'\n\té€ù.-")), max_size=12)
tables = st.integers(2, 5).flatmap(
    lambda n: st.lists(st.lists(cell, min_size=n, max_size=n), min_size=2, max_size=8)
)


@SETTINGS
@given(
    table=tables,
    delim=st.sampled_from([";", ",", "\t", "|"]),
    eol=st.sampled_from(["\r\n", "\n"]),
    final_newline=st.booleans(),
    encoding=st.sampled_from(["utf-8", "cp1252"]),
)
def test_csv_identity_roundtrip_is_byte_identical_whenever_the_dialect_is_detected(
    table, delim, eol, final_newline, encoding
):
    assume(all(c.strip() for c in table[0]))  # a header with names
    buf = io.StringIO(newline="")
    csv.writer(buf, delimiter=delim, lineterminator=eol).writerows(table)
    text = buf.getvalue()
    if not final_newline:
        text = text[: -len(eol)]
    raw = text.encode(encoding)
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "a.csv", Path(d) / "o.csv"
        src.write_bytes(raw)
        adapter = CsvAdapter()
        params = adapter.inspect(src).params
        assume(params["delimiter"] == delim)  # a wrong guess is a different (tested) story
        assume(params["encoding"] == encoding or raw.isascii())
        adapter.apply(src, dst, {}, lambda c, v: v)
        assert dst.read_bytes() == raw


# -- JSON, through the whole pipeline ---------------------------------------------------------------------

keys = st.text(alphabet=st.sampled_from(list('abcn.[]\\" èX')), max_size=5)
scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(-(10**12), 10**12),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=12),
)
documents = st.recursive(
    scalars,
    lambda inner: st.one_of(st.lists(inner, max_size=4), st.dictionaries(keys, inner, max_size=4)),
    max_leaves=12,
)


@SETTINGS
@given(
    doc=documents,
    indent=st.sampled_from([None, 1, 2, "\t"]),
    ascii_=st.booleans(),
    mode=st.sampled_from(list(Mode)),
)
def test_json_pseudonymize_then_restore_gives_back_the_exact_bytes(doc, indent, ascii_, mode):
    raw = json.dumps(doc, indent=indent, ensure_ascii=ascii_).encode("utf-8")
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "a.json"
        src.write_bytes(raw)
        fields = [f.id for f in JsonAdapter().inspect(src).fields]
        assume(fields)
        plan = {f: FieldChoice(f, C.TEXT, mode) for f in fields}
        res = pseudonymize(src, Path(d) / "out", plan)
        json.loads(res.output.read_bytes())  # the output is always valid JSON
        back = restore(res.output, res.mapping, Path(d) / "back.json")
        assert (Path(d) / "back.json").read_bytes() == raw
        assert back.identical_to_original is True and not back.unknown


# -- the engine -----------------------------------------------------------------------------------------------

TEXT_CATEGORIES = [
    C.FULLNAME,
    C.FIRST_NAME,
    C.LAST_NAME,
    C.CITY,
    C.ADDRESS,
    C.TEXT,
    C.EMAIL,
    C.FISCAL_CODE,
    C.IBAN,
]


@SETTINGS
@given(
    values=st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=40, unique=True),
    cat=st.sampled_from(TEXT_CATEGORIES),
    mode=st.sampled_from(list(Mode)),
)
def test_engine_is_one_to_one_never_echoes_the_real_value_and_restores_exactly(values, cat, mode):
    eng = Pseudonymizer(KEY)
    choice = FieldChoice("f", cat, mode)
    fakes = [eng(choice, v) for v in values]
    assert len(set(fakes)) == len(values)
    assert all(f != v for f, v in zip(fakes, values))
    assert fakes == [eng(choice, v) for v in values]  # consistent
    restorer = Restorer(eng.entries())
    assert [restorer(choice, f) for f in fakes] == values and not restorer.unknown


amounts = st.builds(
    lambda n, dec, neg, style: (
        (neg and "-" or "")
        + {
            "it": f"{n:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "en": f"{n:,.{dec}f}",
            "plain": f"{n:.{dec}f}".replace(".", ","),
        }[style]
    ),
    st.integers(100, 10**8).map(lambda x: x / 100),
    st.integers(0, 2),
    st.booleans(),
    st.sampled_from(["it", "en", "plain"]),
)


@SETTINGS
@given(values=st.lists(amounts, min_size=1, max_size=30, unique=True))
def test_text_amounts_keep_their_shape_and_restore_exactly(values):
    eng = Pseudonymizer(KEY)
    choice = FieldChoice("f", C.AMOUNT, Mode.FAKE)
    fakes = [eng(choice, v) for v in values]
    assert len(set(fakes)) == len(values)
    for v, f in zip(values, fakes):
        assert f != v and f.startswith("-") == v.startswith("-")
        nondigits = lambda x: set(x) - set("0123456789")
        assert nondigits(f) <= nondigits(v)  # no new separators or symbols appear
    restorer = Restorer(eng.entries())
    assert [restorer(choice, f) for f in fakes] == values


def test_get_adapter_is_used_by_the_service_for_every_format():
    assert {get_adapter(f"x.{e}").name for e in ("csv", "xlsx", "json")} == {"csv", "excel", "json"}
