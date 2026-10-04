"""Byte-level text decoding shared by the text formats (CSV, JSON)."""

from __future__ import annotations

import codecs
from typing import Any

from ..errors import UnsupportedFileError

_UNSUPPORTED_BOMS = (
    codecs.BOM_UTF32_LE,
    codecs.BOM_UTF32_BE,
    codecs.BOM_UTF16_LE,
    codecs.BOM_UTF16_BE,
)


def decode_bytes(raw: bytes) -> tuple[str, dict[str, Any]]:
    """Return (text, {'encoding', 'bom', 'ascii_only'})."""
    if not raw.strip():
        raise UnsupportedFileError("Il file è vuoto.")
    if raw.startswith(_UNSUPPORTED_BOMS) or b"\x00" in raw[:4096]:
        raise UnsupportedFileError(
            "Codifica UTF-16/UTF-32 o file binario: non supportato. "
            "Salva il file in UTF-8 oppure Windows-1252."
        )
    if raw.startswith(codecs.BOM_UTF8):
        try:
            return raw[3:].decode("utf-8"), {
                "encoding": "utf-8",
                "bom": True,
                "ascii_only": False,
            }
        except UnicodeDecodeError as exc:
            raise UnsupportedFileError(
                "Il file ha l'intestazione UTF-8 ma contiene byte non validi."
            ) from exc
    try:
        return raw.decode("utf-8"), {
            "encoding": "utf-8",
            "bom": False,
            "ascii_only": raw.isascii(),
        }
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1252"), {
            "encoding": "cp1252",
            "bom": False,
            "ascii_only": False,
        }
    except UnicodeDecodeError as exc:
        raise UnsupportedFileError("Codifica non riconosciuta: non è UTF-8 né Windows-1252.") from exc
