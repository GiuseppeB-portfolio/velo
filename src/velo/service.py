"""High-level operations used by the web UI (and, later, a CLI)."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .engine import FAKER_VERSION, Pseudonymizer
from .errors import VeloError
from .formats import get_adapter
from .keystore import ephemeral_key, key_id, load_or_create_project_key
from .mapping import MAPPING_SUFFIX, MappingFile, Restorer
from .model import ApplyReport, Plan


@dataclass
class PseudonymizeResult:
    output: Path
    mapping: Path
    report: ApplyReport
    warnings: list[str] = field(default_factory=list)
    key_mode: str = "ephemeral"
    key_id: str = ""


@dataclass
class RestoreResult:
    output: Path
    restored: dict[str, int]
    unknown: dict[str, int]
    warnings: list[str] = field(default_factory=list)
    identical_to_original: bool | None = None  # None: no hash available


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _refuse_overwrite(path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise VeloError(f"Il file '{path.name}' esiste già: non lo sovrascrivo.")


def pseudonymize(
    src: Path,
    out_dir: Path,
    plan: Plan,
    key_mode: str = "ephemeral",
    key_dir: Path | None = None,
    params: dict[str, Any] | None = None,
    overwrite: bool = False,
) -> PseudonymizeResult:
    src, out_dir = Path(src), Path(out_dir)
    if not plan:
        raise VeloError("Nessun campo scelto: non c'è niente da pseudonimizzare.")
    if key_mode not in ("ephemeral", "project"):
        raise VeloError(f"Modalità chiave sconosciuta: {key_mode}")
    adapter = get_adapter(src)
    source_params = adapter.inspect(src).params  # the dialect of the ORIGINAL file
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / f"{src.stem}.pseudo{src.suffix}"
    mapping_path = out_dir / (output.name + MAPPING_SUFFIX)
    _refuse_overwrite(output, overwrite)
    _refuse_overwrite(mapping_path, overwrite)

    key = load_or_create_project_key(key_dir) if key_mode == "project" else ephemeral_key()
    engine = Pseudonymizer(key)
    tmp = out_dir / f".{output.name}.part"
    try:
        report = adapter.apply(src, tmp, plan, engine, params)
        MappingFile(
            meta={
                "created": datetime.now(UTC).isoformat(timespec="seconds"),
                "tool_version": __version__,
                "faker_version": FAKER_VERSION,
                "key": {"mode": key_mode, "id": key_id(key)},
                "source": {"name": src.name, "format": adapter.name, "sha256": _sha256(src)},
                "output": {"name": output.name},
                "source_params": source_params,
            },
            plan={fid: {"category": c.category.value, "mode": c.mode.value} for fid, c in plan.items()},
            entries=engine.entries(),
        ).save(mapping_path)
        os.replace(tmp, output)
    except BaseException:
        tmp.unlink(missing_ok=True)
        if not overwrite:
            mapping_path.unlink(missing_ok=True)
        raise
    return PseudonymizeResult(
        output,
        mapping_path,
        report,
        warnings=report.warnings + engine.notes(),
        key_mode=key_mode,
        key_id=key_id(key),
    )


def restore(
    pseudonymized: Path,
    mapping_path: Path,
    dst: Path,
    params: dict[str, Any] | None = None,
    overwrite: bool = False,
) -> RestoreResult:
    pseudonymized, dst = Path(pseudonymized), Path(dst)
    mapping = MappingFile.load(mapping_path)
    if dst.resolve() == pseudonymized.resolve():
        raise VeloError("Il file ripristinato coinciderebbe con quello pseudonimizzato.")
    _refuse_overwrite(dst, overwrite)
    adapter = get_adapter(pseudonymized)
    if adapter.name != mapping.meta.get("source", {}).get("format"):
        raise VeloError("Il formato del file non corrisponde a quello del dizionario.")
    restorer = Restorer(mapping.entries)
    tmp = dst.with_name(f".{dst.name}.part")
    try:
        # Restore in the dialect of the original (e.g. Windows-1252 even if the
        # pseudonymised text happens to be pure ASCII).
        stored = mapping.meta.get("source_params") or {}
        report = adapter.apply(pseudonymized, tmp, mapping.to_plan(), restorer, {**stored, **(params or {})})
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    warnings = list(report.warnings)
    for fid, n in sorted(restorer.unknown.items()):
        warnings.append(f"Campo '{fid}': {n} valori non sono nel dizionario e sono rimasti com'erano.")
    original_hash = mapping.meta.get("source", {}).get("sha256")
    return RestoreResult(
        dst,
        dict(restorer.restored),
        dict(restorer.unknown),
        warnings,
        identical_to_original=(_sha256(dst) == original_hash) if original_hash else None,
    )
