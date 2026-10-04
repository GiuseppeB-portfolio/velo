"""Soft consistency check between the type the user chose and the values found.

It never changes a choice and never guesses: it only counts the values of a
chosen field that do not look like the chosen category (a 'Totale' label in
an IBAN column, a text in a date column) so the user can decide with the
facts in hand.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .formats import get_adapter
from .formats.base import preview_text
from .generators import _AMOUNT, Unparsable, _parse_date
from .model import Category as C
from .model import FieldChoice, Plan
from .validators import is_valid_fiscal_code, is_valid_iban, is_valid_vat

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PHONE = re.compile(r"[+()\d\s./-]{6,25}")
MAX_EXAMPLES = 3

PHRASES: dict[C, str] = {
    C.FULLNAME: "un nome e cognome",
    C.FIRST_NAME: "un nome",
    C.LAST_NAME: "un cognome",
    C.CITY: "una città",
    C.FISCAL_CODE: "un codice fiscale valido",
    C.IBAN: "un IBAN valido",
    C.VAT_ID: "una partita IVA valida",
    C.EMAIL: "un indirizzo email",
    C.PHONE: "un numero di telefono",
    C.POSTCODE: "un CAP",
    C.DATE: "una data riconoscibile",
    C.AMOUNT: "un importo",
}


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _digits_only(v: Any) -> str:
    return "".join(c for c in str(v) if c.isdigit())


def _fiscal(v: Any) -> bool:
    if not isinstance(v, str):
        return False
    s = v.strip()
    return is_valid_fiscal_code(s) or (s.isdigit() and len(s) == 11 and is_valid_vat(s))


def _vat(v: Any) -> bool:
    if isinstance(v, int) and not isinstance(v, bool):
        return is_valid_vat(str(v).zfill(11))  # Excel drops leading zeros
    return isinstance(v, str) and is_valid_vat(v)


def _phone(v: Any) -> bool:
    if isinstance(v, int) and not isinstance(v, bool):
        return 6 <= len(str(v)) <= 15
    return isinstance(v, str) and bool(_PHONE.fullmatch(v.strip())) and 6 <= len(_digits_only(v)) <= 15


def _postcode(v: Any) -> bool:
    """3-5 digits: a Rome CAP such as 00100 becomes 100 when Excel stores it as a number."""
    if isinstance(v, int) and not isinstance(v, bool):
        return 3 <= len(str(v)) <= 5
    return isinstance(v, str) and v.strip().isdigit() and 3 <= len(v.strip()) <= 5


def _date(v: Any) -> bool:
    if isinstance(v, (datetime, date)):
        return True
    if not isinstance(v, str):
        return False
    try:
        _parse_date(v)
    except Unparsable:
        return False
    return True


def _amount(v: Any) -> bool:
    return _is_number(v) or (isinstance(v, str) and bool(_AMOUNT.match(v)))


def _name(v: Any) -> bool:
    return isinstance(v, str) and not any(c.isdigit() for c in v)


CHECKS: dict[C, Callable[[Any], bool]] = {
    C.FISCAL_CODE: _fiscal,
    C.IBAN: lambda v: isinstance(v, str) and is_valid_iban(v),
    C.VAT_ID: _vat,
    C.EMAIL: lambda v: isinstance(v, str) and bool(_EMAIL.fullmatch(v.strip())),
    C.PHONE: _phone,
    C.POSTCODE: _postcode,
    C.DATE: _date,
    C.AMOUNT: _amount,
    C.FULLNAME: _name,
    C.FIRST_NAME: _name,
    C.LAST_NAME: _name,
    C.CITY: _name,
    # ADDRESS and TEXT: anything goes, so no check
}


def looks_like(category: C, value: Any) -> bool:
    check = CHECKS.get(category)
    return True if check is None else bool(check(value))


@dataclass(frozen=True)
class Mismatch:
    field_id: str
    category: C
    total: int
    bad: int
    examples: tuple[str, ...]

    def message(self) -> str:
        one = self.bad == 1
        examples = ", ".join(f"«{e}»" for e in self.examples)
        return (
            f"«{self.field_id}»: {self.bad} {'valore' if one else 'valori'} su {self.total} "
            f"non {'sembra' if one else 'sembrano'} {PHRASES[self.category]}, per esempio {examples}."
        )


class _Probe:
    """A Replacer that records what it sees and changes nothing."""

    def __init__(self) -> None:
        self.seen: dict[str, list[Any]] = defaultdict(list)

    def __call__(self, choice: FieldChoice, value: Any) -> Any:
        self.seen[choice.field_id].append(value)
        return value


def find_mismatches(src: Path, plan: Plan, workdir: Path | None = None) -> list[Mismatch]:
    """Dry run over the chosen fields: the same cells the real run would touch."""
    src = Path(src)
    adapter = get_adapter(src)
    probe = _Probe()
    with tempfile.TemporaryDirectory(dir=workdir, prefix=".check-") as tmp:
        adapter.apply(src, Path(tmp) / f"probe{src.suffix}", plan, probe)
    out = []
    for fid, choice in plan.items():
        if choice.category not in CHECKS:
            continue
        values = probe.seen.get(fid, [])
        bad = [v for v in values if not looks_like(choice.category, v)]
        if bad:
            examples = tuple(dict.fromkeys(preview_text(v)[:40] for v in bad))[:MAX_EXAMPLES]
            out.append(Mismatch(fid, choice.category, len(values), len(bad), examples))
    return out


def signature(mismatches: list[Mismatch]) -> str:
    """Identifies this exact set of warnings, so a confirmation cannot outlive a changed choice."""
    raw = "|".join(f"{m.field_id}:{m.category.value}:{m.bad}/{m.total}" for m in mismatches)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
