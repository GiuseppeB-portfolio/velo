"""The replacement engine: HMAC-seeded, consistent, collision-free.

For every (category, real value) the fake value is derived from
HMAC-SHA256(key, category | mode | type | value | attempt), which seeds Faker.
Same key + same value -> same fake, in every sheet and, with a saved
project key, in every file.

The mapping must be one-to-one so that the original can be restored, so a
candidate already taken by another value (or equal to the real value) is
discarded and the next attempt is tried. When a small Faker pool runs out
(first names, cities), a numeric suffix keeps values distinct.
Note: when collisions happen, which value gets which attempt depends on the
order in which values were met, so stability across files holds except for
the (few) values that collided.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import random
from collections import Counter, defaultdict
from typing import Any

import faker as faker_pkg
from faker import Faker

from .errors import VeloError
from .generators import GENERATORS, SUFFIXABLE, Keep, Unparsable
from .model import Category, FieldChoice, Mode
from .values import encode_value, kind_of, value_key

MAX_ATTEMPTS = 100
MAX_ATTEMPTS_SMALL_POOL = 12  # suffixable categories: a miss is likely a saturated pool, fail fast
FAKER_VERSION = faker_pkg.VERSION


class Pseudonymizer:
    """A Replacer. One instance per run: it remembers every value it has seen."""

    def __init__(self, key: bytes, locale: str = "it_IT"):
        if len(key) < 16:
            raise ValueError("La chiave è troppo corta.")
        self._key = key
        self._faker = Faker(locale)
        # (category, mode, kind, real key) -> final value
        self._fwd: dict[tuple[str, str, str, str], Any] = {}
        # category -> final key -> encoded real value
        self._rev: dict[str, dict[str, list[str]]] = defaultdict(dict)
        self.suffixed: Counter[str] = Counter()
        self.fallbacks: Counter[tuple[str, str]] = Counter()

    # -- the Replacer interface ---------------------------------------------------

    def __call__(self, choice: FieldChoice, value: Any) -> Any:
        cat, mode = choice.category, choice.mode
        kind, okey = kind_of(value), value_key(value)
        ck = (cat.value, mode.value, kind, okey)
        if ck in self._fwd:
            return self._fwd[ck]

        if kind == "bool" and mode is Mode.FAKE:
            self.fallbacks[(choice.field_id, "valori booleani lasciati invariati")] += 1
            return self._keep(ck, cat, value, okey)
        try:
            if mode is Mode.PLACEHOLDER:
                final = self._unique(cat, okey, lambda a: self._placeholder(cat, kind, okey, a))
            else:
                final = self._unique(cat, okey, lambda a: self._fake(cat, mode, kind, value, okey, a))
        except Keep:
            return self._keep(ck, cat, value, okey)
        except Unparsable as exc:
            self.fallbacks[(choice.field_id, f"{exc}: sostituiti con segnaposto")] += 1
            final = self._unique(cat, okey, lambda a: self._placeholder(cat, kind, okey, a))

        self._fwd[ck] = final
        self._rev[cat.value][value_key(final)] = encode_value(value)
        return final

    # -- internals -----------------------------------------------------------------

    def _keep(self, ck, cat, value, okey):
        self._fwd[ck] = value
        self._rev[cat.value].setdefault(okey, encode_value(value))
        return value

    def _digest(self, cat: Category, mode: Mode, kind: str, okey: str, attempt: int) -> bytes:
        msg = "\x1f".join((cat.value, mode.value, kind, okey, str(attempt))).encode("utf-8")
        return hmac.new(self._key, msg, hashlib.sha256).digest()

    def _fake(self, cat, mode, kind, value, okey, attempt):
        seed = int.from_bytes(self._digest(cat, mode, kind, okey, attempt)[:8], "big")
        self._faker.seed_instance(seed)
        return GENERATORS[cat](self._faker, random.Random(seed), value, attempt)

    def _placeholder(self, cat, kind, okey, attempt):
        digest = self._digest(cat, Mode.PLACEHOLDER, kind, okey, attempt)
        code = base64.b32encode(digest[:4]).decode()[:5]
        return f"[{cat.name}_{code}]"

    def _unique(self, cat: Category, okey: str, make) -> Any:
        taken = self._rev[cat.value]
        first = None
        limit = MAX_ATTEMPTS_SMALL_POOL if cat in SUFFIXABLE else MAX_ATTEMPTS
        for attempt in range(limit):
            cand = make(attempt)
            if first is None:
                first = cand
            ckey = value_key(cand)
            if ckey != okey and ckey not in taken:
                return cand
        if cat in SUFFIXABLE and isinstance(first, str):
            for n in range(2, 1_000_000):
                cand = f"{first} {n}"
                if cand not in taken:
                    self.suffixed[cat.value] += 1
                    return cand
        raise VeloError(
            f"Valori finti esauriti per la categoria '{cat.value}': scegli il segnaposto per questo campo."
        )

    # -- results -------------------------------------------------------------------

    def entries(self) -> dict[str, dict[str, list[str]]]:
        """Restore dictionary: category -> fake value -> real value (typed)."""
        return {c: dict(m) for c, m in self._rev.items() if m}

    def notes(self) -> list[str]:
        out = []
        for (fid, reason), n in sorted(self.fallbacks.items()):
            out.append(f"Campo '{fid}': {n} valori — {reason}.")
        for cat, n in sorted(self.suffixed.items()):
            out.append(
                f"Categoria '{cat}': {n} valori hanno ricevuto un numero finale "
                "perché i valori finti disponibili erano finiti."
            )
        return out
