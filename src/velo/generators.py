"""One generator per category.

A generator receives a seeded Faker, a seeded random.Random, the real value
and an attempt number (0, 1, 2... when earlier candidates collided), and
returns the fake value in the same shape as the original: same type, same
case, same separators. It raises Unparsable when it cannot read the value
(the engine then falls back to a placeholder) and Keep when the value
carries no information worth hiding (zero).
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any

from faker import Faker

from .model import Category


class Unparsable(Exception):
    """The value does not look like what its category says."""


class Keep(Exception):
    """Leave the value unchanged (e.g. an amount of zero)."""


Generator = Callable[[Faker, random.Random, Any, int], Any]


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise Unparsable(f"atteso testo, trovato {type(value).__name__}")
    return value


def match_case(fake: str, original: str) -> str:
    letters = [c for c in original if c.isalpha()]
    if letters and original.isupper():
        return fake.upper()
    if letters and original.islower():
        return fake.lower()
    return fake


# -- names, places, contacts -----------------------------------------------------


def gen_fullname(fk, rng, value, attempt):
    return match_case(f"{fk.first_name()} {fk.last_name()}", _text(value))


def gen_first_name(fk, rng, value, attempt):
    return match_case(fk.first_name(), _text(value))


def gen_last_name(fk, rng, value, attempt):
    return match_case(fk.last_name(), _text(value))


def gen_city(fk, rng, value, attempt):
    return match_case(fk.city(), _text(value))


def gen_address(fk, rng, value, attempt):
    return match_case(fk.street_address(), _text(value))


def gen_email(fk, rng, value, attempt):
    _text(value)
    return match_case(fk.safe_email(), value)  # reserved example.* domains only


def gen_fiscal_code(fk, rng, value, attempt):
    return match_case(fk.ssn(), _text(value))


def gen_iban(fk, rng, value, attempt):
    original = _text(value)
    iban = fk.iban()
    if " " in original.strip():
        iban = " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))
    return match_case(iban, original)


def vat_check_digit(first_ten: str) -> str:
    total = 0
    for i, ch in enumerate(first_ten):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def gen_vat_id(fk, rng, value, attempt):
    """Built here, not with Faker: Faker's vat_id() has a random check digit."""
    original = _text(value)
    body = "".join(str(rng.randint(0, 9)) for _ in range(7)) + f"{rng.randint(1, 100):03d}"
    vat = body + vat_check_digit(body)
    if original.strip().upper().startswith("IT"):
        vat = "IT" + vat
    return match_case(vat, original)


def _digits(rng: random.Random, n: int, first: str | None = None) -> str:
    head = first if first is not None else str(rng.randint(1, 9))
    return head + "".join(str(rng.randint(0, 9)) for _ in range(n - 1))


_IT_PREFIX = re.compile(r"^(\s*(?:\+|00)39[\s.\-]*)")


def gen_phone(fk, rng, value, attempt):
    """Keeps the layout, the +39/0039 prefix and the first digit (3 = mobile, 0 = landline)."""
    if isinstance(value, int) and not isinstance(value, bool):
        s = str(value)
        return int(_digits(rng, len(s), s[0]))
    original = _text(value)
    m = _IT_PREFIX.match(original)
    prefix = m.group(1) if m else ""
    body = original[len(prefix) :]
    digits = [i for i, c in enumerate(body) if c.isdigit()]
    if len(digits) < 6:
        raise Unparsable("numero di telefono troppo corto")
    new = _digits(rng, len(digits), body[digits[0]])
    chars = list(body)
    for pos, d in zip(digits, new):
        chars[pos] = d
    return prefix + "".join(chars)


def gen_postcode(fk, rng, value, attempt):
    if isinstance(value, int) and not isinstance(value, bool):
        return int(_digits(rng, len(str(value))))
    original = _text(value)
    if original.isdigit():
        return _digits(rng, len(original), "0" if original.startswith("0") and rng.random() < 0.1 else None)
    return fk.postcode()


def gen_text(fk, rng, value, attempt):
    original = _text(value)
    size = max(5, min(len(original), 1000))
    return fk.text(max_nb_chars=size)


# -- dates ------------------------------------------------------------------------

_DATE_FORMATS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%y",
    "%d-%m-%y",
    "%Y%m%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
)


def _parse_date(text: str) -> tuple[datetime, str]:
    s = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt), fmt
        except ValueError:
            continue
    raise Unparsable("data in un formato non riconosciuto")


def shift_days(rng: random.Random, attempt: int) -> int:
    """Non-zero shift, ±2 years at first, wider after collisions."""
    span = 730 + 10 * attempt
    days = rng.randint(1, span)
    return days if rng.random() < 0.5 else -days


def gen_date(fk, rng, value, attempt):
    delta = timedelta(days=shift_days(rng, attempt))
    try:
        if isinstance(value, datetime):
            return value + delta
        if isinstance(value, date):
            return value + delta
        original = _text(value)
        parsed, fmt = _parse_date(original)
        new = parsed + delta
        if "%y" in fmt and not 1969 <= new.year <= 2068:
            raise Unparsable("anno a due cifre fuori intervallo")
        out = new.strftime(fmt)
        return out.strip() if original == original.strip() else out
    except OverflowError as exc:
        raise Unparsable("data fuori intervallo") from exc


# -- amounts ----------------------------------------------------------------------

_AMOUNT = re.compile(
    r"^(?P<s0>[-+]?)(?P<pre>[^\d\-+]*)(?P<s1>[-+]?)"
    r"(?P<num>\d(?:[\d.,'\u00a0 ]*\d)?)(?P<post>[^\d]*)$"
)


def _analyse_number(num: str) -> tuple[Decimal, int, str, str]:
    """Return (value, decimals, decimal_char, group_char) for '1.234,56', '1 234,56', "1'234.50"."""
    space = next((c for c in num if c in " '\u00a0"), "")  # these are always grouping
    body = num.replace(space, "") if space else num
    seps = [c for c in body if not c.isdigit()]
    dec, grp = "", space
    if seps:
        last = seps[-1]
        after = body[body.rindex(last) + 1 :]
        if "." in seps and "," in seps:
            dec = last
            grp = grp or ("," if last == "." else ".")
        elif seps.count(last) > 1:
            grp = grp or last
        elif space or not (last == "." and len(after) == 3):
            dec = last  # '1,234' is read as a decimal comma
        else:
            grp = last  # '1.234' is thousands in Italian usage
    clean = body.replace(grp, "") if grp and grp in ".," else body
    if dec:
        clean = clean.replace(dec, ".")
    try:
        value = Decimal(clean)
    except InvalidOperation as exc:
        raise Unparsable("importo in un formato non riconosciuto") from exc
    decimals = len(num) - num.rindex(dec) - 1 if dec else 0
    return value, decimals, dec, grp


def _scaled(value: Decimal, decimals: int, rng: random.Random, attempt: int) -> Decimal:
    spread = min(0.5 + 0.05 * attempt, 50.0)
    factor = Decimal(str(round(rng.uniform(max(1 - spread, 0.05), 1 + spread), 4)))
    q = Decimal(1).scaleb(-decimals)
    return (abs(value) * factor).quantize(q, ROUND_HALF_EVEN)


def _group(int_part: str, sep: str) -> str:
    out = []
    while len(int_part) > 3:
        out.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    return sep.join([int_part] + out) if out else int_part


def gen_amount(fk, rng, value, attempt):
    if isinstance(value, bool):
        raise Unparsable("valore booleano")
    if isinstance(value, Decimal):
        exp = value.as_tuple().exponent
        decimals = -exp if isinstance(exp, int) and exp < 0 else 0
        if value == 0:
            raise Keep
        new = _scaled(value, decimals, rng, attempt)
        return -new if value < 0 else new
    if isinstance(value, int):
        if value == 0:
            raise Keep
        new = int(_scaled(Decimal(value), 0, rng, attempt))
        return -new if value < 0 else new
    if isinstance(value, float):
        if value == 0:
            raise Keep
        exp = Decimal(repr(value)).as_tuple().exponent
        decimals = -exp if isinstance(exp, int) and exp < 0 else 0
        new = float(_scaled(Decimal(repr(value)), decimals, rng, attempt))
        return -new if value < 0 else new

    original = _text(value)
    m = _AMOUNT.match(original)
    if not m:
        raise Unparsable("importo in un formato non riconosciuto")
    number, decimals, dec, grp = _analyse_number(m["num"])
    if number == 0:
        raise Keep
    new = _scaled(number, decimals, rng, attempt)
    fixed = f"{new:.{decimals}f}"
    int_part, _, frac = fixed.partition(".")
    if grp:
        int_part = _group(int_part, grp)
    body = int_part + (dec + frac if decimals else "")
    return f"{m['s0']}{m['pre']}{m['s1']}{body}{m['post']}"


GENERATORS: dict[Category, Generator] = {
    Category.FULLNAME: gen_fullname,
    Category.FIRST_NAME: gen_first_name,
    Category.LAST_NAME: gen_last_name,
    Category.FISCAL_CODE: gen_fiscal_code,
    Category.IBAN: gen_iban,
    Category.VAT_ID: gen_vat_id,
    Category.EMAIL: gen_email,
    Category.PHONE: gen_phone,
    Category.ADDRESS: gen_address,
    Category.CITY: gen_city,
    Category.POSTCODE: gen_postcode,
    Category.DATE: gen_date,
    Category.AMOUNT: gen_amount,
    Category.TEXT: gen_text,
}

# Categories with a small pool of Faker values: when every candidate is taken,
# a numeric suffix keeps the mapping one-to-one. All others have huge spaces.
SUFFIXABLE = frozenset(
    {
        Category.FULLNAME,
        Category.FIRST_NAME,
        Category.LAST_NAME,
        Category.CITY,
        Category.ADDRESS,
        Category.TEXT,
    }
)
