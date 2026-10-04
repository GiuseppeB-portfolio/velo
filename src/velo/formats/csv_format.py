"""CSV adapter.

Detects encoding (UTF-8 with/without BOM, Windows-1252), delimiter, line
terminator and final newline, and writes the output with the same parameters.
Values are always handled as text: nothing is interpreted as number or date,
so columns that are not chosen come back exactly as they were (e.g. '1.234,56').
"""

from __future__ import annotations

import codecs
import csv
import io
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ..errors import EncodingError, UnsupportedFileError
from ..model import ApplyReport, FieldInfo, Inspection, Plan, Replacer
from .base import (
    SAMPLE_SIZE,
    FormatAdapter,
    check_plan,
    preview_text,
    unique_labels,
)
from .text import decode_bytes

csv.field_size_limit(2**24)

DELIMITERS = (";", ",", "\t", "|")  # order = preference on ties (Italy: ';')
SNIFF_BYTES = 64 * 1024
SNIFF_ROWS = 200
ENCODINGS = ("utf-8", "cp1252")


_EOL = re.compile(r"(\r\n|\n|\r)$")


def parse_records(text: str, delimiter: str) -> tuple[list[list[str]], list[str]]:
    """Parse the text and return (rows, line terminator that closed each row).

    A newline inside a quoted field is part of the value, not a record
    terminator, so the terminators are read from the physical line that
    actually ends each record. The last record may have none ('').
    """
    seen: list[str] = []

    def lines():
        for line in io.StringIO(text, newline=""):
            m = _EOL.search(line)
            seen.append(m.group(1) if m else "")
            yield line

    rows, terminators = [], []
    for row in csv.reader(lines(), delimiter=delimiter, quotechar='"'):
        rows.append(row)
        terminators.append(seen[-1])  # the reader never reads ahead of the record it yields
    return rows, terminators


def pick_line_terminator(terminators: list[str]) -> tuple[str, bool]:
    """Return (terminator, mixed)."""
    counts = Counter(t for t in terminators if t)
    if not counts:
        return "\r\n", False
    return counts.most_common(1)[0][0], len(counts) > 1


def detect_delimiter(text: str) -> str:
    """Pick the delimiter that splits the sample into the most regular table.

    Score = (share of rows with the most common column count, that column
    count, preference order). A decimal comma cannot win over ';' because
    splitting on ',' gives irregular rows.
    """
    sample = text[:SNIFF_BYTES]
    if len(text) > SNIFF_BYTES and "\n" in sample:
        sample = sample[: sample.rfind("\n")]  # drop a possibly cut last row
    best, best_score = ";", (-1.0, -1, 0)
    for rank, delim in enumerate(DELIMITERS):
        rows = []
        for row in csv.reader(io.StringIO(sample, newline=""), delimiter=delim):
            if row:
                rows.append(row)
            if len(rows) >= SNIFF_ROWS:
                break
        if not rows:
            continue
        n_cols, freq = Counter(len(r) for r in rows).most_common(1)[0]
        if n_cols < 2:
            continue
        score = (round(freq / len(rows), 3), n_cols, -rank)
        if score > best_score:
            best, best_score = delim, score
    return best


def detect_quote_all(text: str, delimiter: str, n_cols: int) -> bool:
    """True if the header line has every field in quotes."""
    first = text.split("\n", 1)[0].rstrip("\r")
    return (
        n_cols > 0
        and first.startswith('"')
        and first.endswith('"')
        and first.count(f'"{delimiter}"') == n_cols - 1
    )


def serialize_rows(rows, delimiter: str, terminator: str, quote_all: bool, final_newline: bool) -> str:
    buf = io.StringIO(newline="")
    csv.writer(
        buf,
        delimiter=delimiter,
        quotechar='"',
        lineterminator=terminator,
        quoting=csv.QUOTE_ALL if quote_all else csv.QUOTE_MINIMAL,
    ).writerows(rows)
    text = buf.getvalue()
    if not final_newline and text.endswith(terminator):
        text = text[: -len(terminator)]
    return text


class CsvAdapter(FormatAdapter):
    name = "csv"
    extensions = (".csv",)

    # -- reading ---------------------------------------------------------

    def _parse(self, path: Path) -> tuple[list[list[str]], int, dict[str, Any], list[str]]:
        raw = Path(path).read_bytes()
        text, params = decode_bytes(raw)
        warnings: list[str] = []
        delimiter = detect_delimiter(text)
        rows, terminators = parse_records(text, delimiter)
        terminator, mixed = pick_line_terminator(terminators)
        if mixed:
            warnings.append("Il file usa terminatori di riga misti: nell'output saranno uniformati.")
        header_idx = next((i for i, r in enumerate(rows) if r), None)
        if header_idx is None:
            raise UnsupportedFileError("Il file CSV non contiene righe.")
        n_cols = len(rows[header_idx])
        final_newline = text.endswith(("\n", "\r"))
        params.update(delimiter=delimiter, lineterminator=terminator, final_newline=final_newline)
        # Choose the quoting style that reproduces the input exactly; if none does,
        # say so instead of silently rewriting the quotes.
        quote_all, reproduced = False, False
        for candidate in (False, True):
            if candidate and not (header_idx == 0 and detect_quote_all(text, delimiter, n_cols)):
                continue
            if serialize_rows(rows, delimiter, terminator, candidate, final_newline) == text:
                quote_all, reproduced = candidate, True
                break
        params["quote_all"] = quote_all
        if not reproduced and not mixed:
            warnings.append(
                "Le virgolette del file originale non sono quelle standard: nell'output "
                "verranno riscritte in modo diverso. I valori restano identici."
            )
        if params["ascii_only"]:
            warnings.append(
                "Il file contiene solo caratteri ASCII: la codifica originale non è "
                "determinabile. Se l'output contiene lettere accentate verrà scritto "
                "in UTF-8; Excel italiano potrebbe mostrarle male se il file è "
                "aperto con doppio clic."
            )
        return rows, header_idx, params, warnings

    def inspect(self, path: Path) -> Inspection:
        rows, header_idx, params, warnings = self._parse(path)
        header = rows[header_idx]
        labels = [h.strip() or f"Colonna {i + 1}" for i, h in enumerate(header)]
        labels = unique_labels(labels)
        data = rows[header_idx + 1 :]
        fields = []
        for i, label in enumerate(labels):
            values = [r[i] for r in data if i < len(r) and r[i] != ""]
            fields.append(
                FieldInfo(
                    id=label,
                    label=label,
                    container=None,
                    sample=tuple(preview_text(v) for v in values[:SAMPLE_SIZE]),
                    non_empty=len(values),
                )
            )
        return Inspection("csv", fields, params, warnings)

    # -- writing ---------------------------------------------------------

    def apply(
        self,
        src: Path,
        dst: Path,
        plan: Plan,
        replacer: Replacer,
        params: dict[str, Any] | None = None,
    ) -> ApplyReport:
        rows, header_idx, detected, warnings = self._parse(src)
        p = {**detected, **(params or {})}
        if p["encoding"] not in ENCODINGS:
            raise UnsupportedFileError(f"Codifica non ammessa: {p['encoding']}")

        labels = unique_labels(h.strip() or f"Colonna {i + 1}" for i, h in enumerate(rows[header_idx]))
        check_plan(plan, labels)
        targets = [(labels.index(fid), choice) for fid, choice in plan.items()]

        replaced = {fid: 0 for fid in plan}
        for row in rows[header_idx + 1 :]:
            for col, choice in targets:
                if col < len(row) and row[col] != "":
                    new = replacer(choice, row[col])
                    row[col] = new if isinstance(new, str) else str(new)
                    replaced[choice.field_id] += 1
        for fid, n in replaced.items():
            if n == 0:
                warnings.append(f"Il campo '{fid}' non conteneva valori da sostituire.")

        text = serialize_rows(rows, p["delimiter"], p["lineterminator"], p["quote_all"], p["final_newline"])

        try:
            data = text.encode(p["encoding"])
        except UnicodeEncodeError as exc:
            bad = exc.object[exc.start]
            raise EncodingError(
                f"Il carattere {bad!r} non è rappresentabile in {p['encoding']}. "
                "Scegli UTF-8 come codifica di uscita."
            ) from exc
        if p["bom"]:
            data = codecs.BOM_UTF8 + data
        Path(dst).write_bytes(data)
        return ApplyReport(replaced=replaced, warnings=warnings)
