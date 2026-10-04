"""Format checks with checksum for Italian identifiers (used by tests, and by phase 2)."""

from __future__ import annotations

import re

_CF_ODD = dict(
    zip(
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        [
            1,
            0,
            5,
            7,
            9,
            13,
            15,
            17,
            19,
            21,
            1,
            0,
            5,
            7,
            9,
            13,
            15,
            17,
            19,
            21,
            2,
            4,
            18,
            20,
            11,
            3,
            6,
            8,
            12,
            14,
            16,
            10,
            22,
            25,
            24,
            23,
        ],
    )
)


def is_valid_fiscal_code(value: str) -> bool:
    """Personal Italian fiscal code (16 chars, omocodia allowed) with its control letter."""
    v = value.strip().upper()
    d = "[0-9LMNPQRSTUV]"  # letters stand in for digits in 'omocodia' cases
    if not re.fullmatch(rf"[A-Z]{{6}}{d}{{2}}[A-Z]{d}{{2}}[A-Z]{d}{{3}}[A-Z]", v):
        return False
    total = 0
    for i, ch in enumerate(v[:15]):
        if i % 2 == 0:
            total += _CF_ODD[ch]
        else:
            total += int(ch) if ch.isdigit() else ord(ch) - 65
    return v[15] == chr(65 + total % 26)


def is_valid_vat(value: str) -> bool:
    """Italian partita IVA: 11 digits, Luhn check digit (an 'IT' prefix is accepted)."""
    v = value.strip().upper().replace(" ", "")
    if v.startswith("IT"):
        v = v[2:]
    if not re.fullmatch(r"\d{11}", v):
        return False
    total = 0
    for i, ch in enumerate(v):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def is_valid_iban(value: str) -> bool:
    """IBAN with ISO 13616 mod-97 check."""
    v = value.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", v):
        return False
    moved = v[4:] + v[:4]
    number = "".join(str(int(c, 36)) for c in moved)
    return int(number) % 97 == 1
