"""Typed values: lookup keys and a lossless JSON encoding for the restore dictionary."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .formats.json_format import JsonNumber, JsonString


def kind_of(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, JsonString):
        return "jstr"
    if isinstance(v, JsonNumber):
        return "jnum"
    if isinstance(v, Decimal):
        return "dec"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, datetime):
        return "datetime"
    if isinstance(v, date):
        return "date"
    if isinstance(v, str):
        return "str"
    raise TypeError(f"Tipo di valore non gestito: {type(v).__name__}")


def value_key(v: Any) -> str:
    """Exact textual identity of a value (no trimming, no case folding)."""
    kind = kind_of(v)
    if kind == "bool":
        return "true" if v else "false"
    if kind == "jnum":
        return v.raw
    if kind == "dec":
        return format(v, "f")
    if kind == "float":
        # xlsx stores 140.0 as 140 and reads it back as an int: same key for both
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    if kind in ("datetime", "date"):
        return v.isoformat()
    return str(v)


def encode_value(v: Any) -> list[str]:
    kind = kind_of(v)
    if kind == "jstr":
        return [kind, str(v), v.raw]
    return [kind, value_key(v)]


def decode_value(enc: list[str]) -> Any:
    kind, text = enc[0], enc[1]
    if kind == "str":
        return text
    if kind == "jstr":
        return JsonString(text, enc[2])
    if kind == "jnum":
        return JsonNumber(text)
    if kind == "dec":
        return Decimal(text)
    if kind == "int":
        return int(text)
    if kind == "float":
        return float(text)
    if kind == "datetime":
        return datetime.fromisoformat(text)
    if kind == "date":
        return date.fromisoformat(text)
    if kind == "bool":
        return text == "true"
    raise ValueError(f"Tipo sconosciuto nel dizionario: {kind}")
