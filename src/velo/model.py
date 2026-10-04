"""Shared data types. No logic here, only the vocabulary of the project."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class Category(StrEnum):
    """What kind of value a field holds; drives the fake-value generator."""

    FULLNAME = "fullname"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    FISCAL_CODE = "fiscal_code"
    IBAN = "iban"
    VAT_ID = "vat_id"
    EMAIL = "email"
    PHONE = "phone"
    ADDRESS = "address"
    CITY = "city"
    POSTCODE = "postcode"
    DATE = "date"
    AMOUNT = "amount"
    TEXT = "text"


class Mode(StrEnum):
    FAKE = "fake"
    PLACEHOLDER = "placeholder"


@dataclass(frozen=True)
class FieldChoice:
    """The user's decision for one field."""

    field_id: str
    category: Category
    mode: Mode = Mode.FAKE


# field id -> choice. Fields not in the plan are never touched.
Plan = dict[str, FieldChoice]


@dataclass(frozen=True)
class FieldInfo:
    """A field found in a file, as shown to the user before choosing."""

    id: str
    label: str
    container: str | None  # sheet name for Excel, None otherwise
    sample: tuple[str, ...]  # first non-empty values, as text
    non_empty: int
    formula_cells: int = 0  # Excel only: cells that will never be touched


@dataclass
class Inspection:
    format: str
    fields: list[FieldInfo]
    params: dict[str, Any]  # detected parameters, reused when writing
    warnings: list[str] = field(default_factory=list)


@dataclass
class ApplyReport:
    replaced: dict[str, int]
    skipped_formulas: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class Replacer(Protocol):
    """Maps a real value to its replacement (or back, when restoring).

    Receives the raw value as read by the format adapter (str, int, float,
    datetime, ...) and returns the value to write.
    """

    def __call__(self, choice: FieldChoice, value: Any) -> Any: ...
