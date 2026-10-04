"""The restore dictionary (file) and the restorer (a Replacer that goes backwards).

The file is as sensitive as the original data: it contains every real value.
"""

from __future__ import annotations

import contextlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import VeloError
from .model import Category, FieldChoice, Mode, Plan
from .values import decode_value, value_key

MAPPING_VERSION = 1
MAPPING_SUFFIX = ".velo-map.json"

WARNING_TEXT = (
    "ATTENZIONE: questo file contiene i dati originali in chiaro. Tratta questo file "
    "come l'originale: non condividerlo, non caricarlo su servizi esterni o su un'AI, "
    "non inviarlo insieme al file pseudonimizzato. Chi li ha entrambi ricostruisce i dati."
)


@dataclass
class MappingFile:
    meta: dict[str, Any]
    plan: dict[str, dict[str, str]]
    entries: dict[str, dict[str, list[str]]]

    def to_plan(self) -> Plan:
        return {
            fid: FieldChoice(fid, Category(v["category"]), Mode(v["mode"])) for fid, v in self.plan.items()
        }

    def save(self, path: Path) -> None:
        doc = {
            "velo_mapping": MAPPING_VERSION,
            "WARNING": WARNING_TEXT,
            **self.meta,
            "plan": self.plan,
            "entries": self.entries,
        }
        path = Path(path)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        with contextlib.suppress(OSError):
            path.chmod(0o600)  # owner only where the OS supports it

    @classmethod
    def load(cls, path: Path) -> MappingFile:
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
            if doc.get("velo_mapping") != MAPPING_VERSION:
                raise KeyError
            meta = {k: v for k, v in doc.items() if k not in ("velo_mapping", "WARNING", "plan", "entries")}
            return cls(meta, doc["plan"], doc["entries"])
        except (OSError, ValueError, KeyError, AttributeError) as exc:
            raise VeloError(
                "Il file del dizionario non è valido o è di una versione non supportata."
            ) from exc


class Restorer:
    """Maps fake values back to the real ones. Unknown values are left untouched and counted."""

    def __init__(self, entries: dict[str, dict[str, list[str]]]):
        self._entries = entries
        self.unknown: Counter[str] = Counter()
        self.restored: Counter[str] = Counter()

    def __call__(self, choice: FieldChoice, value: Any) -> Any:
        enc = self._entries.get(choice.category.value, {}).get(value_key(value))
        if enc is None:
            self.unknown[choice.field_id] += 1
            return value
        self.restored[choice.field_id] += 1
        return decode_value(enc)
