"""Secret keys for the HMAC that drives fake-value generation.

Two modes:
- ephemeral: a random key that lives only in memory. Consistency holds inside
  one run; different runs/files are not linkable to each other.
- project: a key saved on this computer. The same real value gets the same
  fake value in every file processed with it. The key is as sensitive as the
  restore dictionary: whoever has it can test candidate names against an output.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import os
import secrets
import sys
from pathlib import Path

KEY_BYTES = 32
KEY_FILE = "project.key"


def default_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "velo"


def ephemeral_key() -> bytes:
    return secrets.token_bytes(KEY_BYTES)


def load_or_create_project_key(directory: Path | None = None) -> bytes:
    directory = Path(directory) if directory else default_dir()
    path = directory / KEY_FILE
    if path.exists():
        key = bytes.fromhex(path.read_text().strip())
        if len(key) != KEY_BYTES:
            raise ValueError(f"Chiave non valida in {path}")
        return key
    directory.mkdir(parents=True, exist_ok=True)
    key = ephemeral_key()
    path.write_text(key.hex())
    with contextlib.suppress(OSError):
        path.chmod(0o600)  # no-op in practice on Windows
    return key


def key_id(key: bytes) -> str:
    """Short public identifier: lets the user see whether two outputs share a key."""
    return hmac.new(key, b"velo:key-id", hashlib.sha256).hexdigest()[:8]
