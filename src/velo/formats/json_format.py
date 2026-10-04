"""JSON adapter.

The file is never re-serialised. A small scanner records, for every scalar
value, its path and its exact position in the text; the output is the
original text with only the chosen spans replaced. Everything else
(whitespace, key order, duplicate keys, escapes, number spelling such as
'1.10' or '1e5') is byte-for-byte the input.

Paths: object keys joined by '.', '[]' for "every element of this array",
e.g. 'clienti[].anagrafica.nome'. Characters . [ ] \\ " inside a key are
escaped with a backslash, an empty key is written "", a scalar root is '$'.
Ids are only compared with the ones computed from the file, never parsed.
"""

from __future__ import annotations

import codecs
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..errors import UnsupportedFileError, VeloError
from ..model import ApplyReport, FieldInfo, Inspection, Plan, Replacer
from .base import SAMPLE_SIZE, FormatAdapter, check_plan, preview_text
from .text import decode_bytes

_WS = " \t\n\r"
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"', re.S)
_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][-+]?\d+)?")
_KEY_SPECIAL = re.compile(r'([.\[\]\\"])')
_NON_ASCII_ESCAPE = re.compile(r"\\u(?!00[0-7])[0-9a-fA-F]{4}")
_LITERALS = (("true", True), ("false", False), ("null", None))

ARRAY = None  # path segment meaning "any element of the array"


class JsonNumber(Decimal):
    """A JSON number that remembers how it was written ('1.10', '1e5', '-0').

    Behaves as an exact Decimal for whoever replaces it; `raw` lets the
    restore step write back the original spelling.
    """

    raw: str

    def __new__(cls, raw: str):
        obj = super().__new__(cls, raw)
        obj.raw = raw
        return obj


class JsonString(str):
    """A JSON string that remembers its exact spelling in the file ('\\u00e8', '\\/')."""

    raw: str

    def __new__(cls, value: str, raw: str):
        obj = super().__new__(cls, value)
        obj.raw = raw
        return obj


@dataclass(frozen=True)
class Scalar:
    path: tuple[str | None, ...]
    start: int
    end: int
    value: Any  # str, JsonNumber, bool or None


def render_path(path: tuple[str | None, ...]) -> str:
    out = ""
    for seg in path:
        if seg is ARRAY:
            out += "[]"
        else:
            key = '""' if seg == "" else _KEY_SPECIAL.sub(r"\\\1", seg)
            out += ("." if out else "") + key
    return out or "$"


def _reject_constant(name: str):
    raise ValueError(f"{name} non è ammesso in JSON standard")


def scan(text: str) -> list[Scalar]:
    """Validate `text` as strict JSON and return its scalars in document order."""
    try:
        json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise UnsupportedFileError(f"JSON non valido: {exc}") from exc

    out: list[Scalar] = []
    n = len(text)

    def ws(i: int) -> int:
        while i < n and text[i] in _WS:
            i += 1
        return i

    def value(i: int, path: tuple) -> int:
        i = ws(i)
        c = text[i]
        if c == "{":
            i = ws(i + 1)
            if text[i] == "}":
                return i + 1
            while True:
                m = _STRING.match(text, i)
                key = json.loads(m.group())
                i = ws(m.end()) + 1  # skip ':'
                i = ws(value(i, path + (key,)))
                if text[i] == ",":
                    i = ws(i + 1)
                    continue
                return i + 1  # '}'
        if c == "[":
            i = ws(i + 1)
            if text[i] == "]":
                return i + 1
            while True:
                i = ws(value(i, path + (ARRAY,)))
                if text[i] == ",":
                    i += 1
                    continue
                return i + 1  # ']'
        if c == '"':
            m = _STRING.match(text, i)
            out.append(Scalar(path, i, m.end(), JsonString(json.loads(m.group()), m.group())))
            return m.end()
        for word, val in _LITERALS:
            if text.startswith(word, i):
                out.append(Scalar(path, i, i + len(word), val))
                return i + len(word)
        m = _NUMBER.match(text, i)
        out.append(Scalar(path, i, m.end(), JsonNumber(m.group())))
        return m.end()

    value(0, ())
    return out


def to_literal(value: Any, ensure_ascii: bool) -> str:
    """JSON text for a replacement value."""
    if isinstance(value, (JsonNumber, JsonString)):
        return value.raw
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (float, Decimal)):
        if not math.isfinite(value):
            raise VeloError(f"Valore numerico non rappresentabile in JSON: {value}")
        return repr(value) if isinstance(value, float) else format(value, "f")
    if isinstance(value, (datetime, date)):
        value = value.isoformat()
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=ensure_ascii)
    raise VeloError(f"Tipo di valore non scrivibile in JSON: {type(value).__name__}")


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return "booleano"
    if isinstance(value, (int, float, Decimal)):
        return "numero"
    return "testo"


def _unchanged(new: Any, old: Any) -> bool:
    return new is old or (type(new) is type(old) is str and new == old)


def _is_empty(value: Any) -> bool:
    return value is None or value == ""


class JsonAdapter(FormatAdapter):
    name = "json"
    extensions = (".json",)

    def _read(self, path: Path) -> tuple[str, list[Scalar], dict[str, Any], list[str]]:
        text, params = decode_bytes(Path(path).read_bytes())
        warnings: list[str] = []
        if params["encoding"] != "utf-8":
            warnings.append(
                "Il JSON non è in UTF-8 come richiede lo standard: l'output "
                "mantiene la codifica originale (Windows-1252)."
            )
        has_raw_non_ascii = not text.isascii()
        params["ensure_ascii"] = not has_raw_non_ascii and bool(_NON_ASCII_ESCAPE.search(text))
        return text, scan(text), params, warnings

    def inspect(self, path: Path) -> Inspection:
        _, scalars, params, warnings = self._read(path)
        fields: dict[str, dict[str, Any]] = {}
        for s in scalars:
            pid = render_path(s.path)
            f = fields.setdefault(pid, {"sample": [], "non_empty": 0})
            if _is_empty(s.value):
                continue
            f["non_empty"] += 1
            if len(f["sample"]) < SAMPLE_SIZE:
                shown = s.value.raw if isinstance(s.value, JsonNumber) else s.value
                f["sample"].append(preview_text(shown))
        return Inspection(
            "json",
            [
                FieldInfo(
                    id=pid, label=pid, container=None, sample=tuple(f["sample"]), non_empty=f["non_empty"]
                )
                for pid, f in fields.items()
            ],
            params,
            warnings,
        )

    def apply(
        self,
        src: Path,
        dst: Path,
        plan: Plan,
        replacer: Replacer,
        params: dict[str, Any] | None = None,
    ) -> ApplyReport:
        text, scalars, detected, warnings = self._read(src)
        p = {**detected, **(params or {})}
        ids = [render_path(s.path) for s in scalars]
        check_plan(plan, ids)

        replaced = {fid: 0 for fid in plan}
        changed_kind: set[str] = set()
        pieces: list[str] = []
        pos = 0
        for s, pid in zip(scalars, ids):
            choice = plan.get(pid)
            if choice is None or _is_empty(s.value):
                continue
            new = replacer(choice, s.value)
            if _unchanged(new, s.value):
                literal = text[s.start : s.end]  # keep the original spelling/escapes
            else:
                literal = to_literal(new, p["ensure_ascii"])
                try:
                    literal.encode(p["encoding"])
                except UnicodeEncodeError:
                    literal = to_literal(new, ensure_ascii=True)  # \\uXXXX is valid JSON
            if _kind(new) != _kind(s.value):
                changed_kind.add(pid)
            pieces += [text[pos : s.start], literal]
            pos = s.end
            replaced[pid] += 1
        pieces.append(text[pos:])
        out = "".join(pieces)

        for fid, n in replaced.items():
            if n == 0:
                warnings.append(f"Il campo '{fid}' non conteneva valori da sostituire.")
        for fid in sorted(changed_kind):
            warnings.append(
                f"Nel campo '{fid}' il tipo del valore è cambiato (per esempio da "
                "numero a testo): chi legge il file potrebbe aspettarsi il tipo originale."
            )

        data = out.encode(p["encoding"])
        if p["bom"]:
            data = codecs.BOM_UTF8 + data
        Path(dst).write_bytes(data)
        return ApplyReport(replaced=replaced, warnings=warnings)
