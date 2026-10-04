"""Common interface and helpers for the format adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..errors import PlanError
from ..model import ApplyReport, Inspection, Plan, Replacer

SAMPLE_SIZE = 5
SAMPLE_WIDTH = 60


class FormatAdapter(ABC):
    name: str
    extensions: tuple[str, ...]

    @abstractmethod
    def inspect(self, path: Path) -> Inspection:
        """List the fields of the file and the parameters needed to rewrite it."""

    @abstractmethod
    def apply(
        self,
        src: Path,
        dst: Path,
        plan: Plan,
        replacer: Replacer,
        params: dict[str, Any] | None = None,
    ) -> ApplyReport:
        """Write `dst` as a copy of `src` where only the fields in `plan` change.

        `params` overrides the parameters detected by `inspect` (e.g. encoding).
        """


def unique_labels(labels: Iterable[str]) -> list[str]:
    """Make labels unique by suffixing duplicates: 'a', 'a#2', 'a#3'."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for label in labels:
        seen[label] = seen.get(label, 0) + 1
        out.append(label if seen[label] == 1 else f"{label}#{seen[label]}")
    return out


def preview_text(value: Any) -> str:
    """Short text version of a cell/field value for the preview."""
    if isinstance(value, (datetime, date)):
        text = value.isoformat()
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= SAMPLE_WIDTH else text[: SAMPLE_WIDTH - 1] + "…"


def check_plan(plan: Plan, available_ids: Iterable[str]) -> None:
    """Fail loudly if the plan names fields the file does not have.

    Silently ignoring them would let the user believe a field was
    anonymised when it was not.
    """
    available = set(available_ids)
    unknown = sorted(set(plan) - available)
    if unknown:
        raise PlanError("Campi scelti ma non presenti nel file: " + ", ".join(unknown))
