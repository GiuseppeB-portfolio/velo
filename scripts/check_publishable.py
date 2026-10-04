"""Check that the files about to be published contain no data, keys or personal traces.

Run it before every commit that you intend to push:

    python scripts/check_publishable.py

It looks at the files tracked by git (or, outside a git repository, at the
folder, skipping virtual environments and caches) and fails if it finds a
restore dictionary, a key, a data file, a secret, a personal path, or an
email address, IBAN or fiscal code that is not on the allow-list below.
Everything on the allow-list is synthetic. Adding to it is a conscious act.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_FILES = {".coverage"}
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    "build",
    "dist",
}
THIS_FILE = Path(__file__).resolve()

FORBIDDEN_FILES = {
    "dizionario di ripristino": re.compile(r"\.velo-map\.json$"),
    "chiave": re.compile(r"(^|/)project\.key$|\.key$|\.pem$"),
    "file di ambiente": re.compile(r"(^|/)\.env(\.|$)"),
    "output pseudonimizzato": re.compile(r"\.pseudo\.[A-Za-z]+$"),
    "file di dati": re.compile(r"\.(xlsx|xlsm|xls|csv|tsv|parquet|sqlite|db)$", re.I),
}

CONTENT_PATTERNS = {
    "token GitHub": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "chiave privata": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "chiave AWS": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "percorso Windows personale": re.compile(r"[A-Za-z]:\\Users\\(?!<|\.\.\.|nome|utente)[^\\\s\"']+", re.I),
    "percorso personale macOS/Linux": re.compile(
        r"(?<![\w.])/(?:Users|home)/(?!claude\b|runner\b|<)[a-z][\w.-]*/"
    ),
    "indirizzo email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "IBAN": re.compile(r"\bIT\d{2}[A-Z]\d{22}\b"),
    "codice fiscale": re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b"),
}

# Synthetic values that are allowed to appear (documentation examples and test inputs).
ALLOWED_DOMAINS = ("example.com", "example.net", "example.org", "users.noreply.github.com")
ALLOWED_DOMAIN_SUFFIXES = (".test", ".invalid", ".example")
ALLOWED_VALUES = {
    "IT60X0542811101000000123456",  # the IBAN used in public documentation
    "IT61X0542811101000000123456",  # same, with a wrong check digit (negative test)
    "RSSMRA80A01H501U",  # the classic invented fiscal code
    "MRTMTT91D08F205J",  # invented fiscal code with a valid control letter
    "BNCLCU75S55D704K",  # invented
    "BRGPPZ17H50G145Y",  # invented
    "RSSMRA80B01H501U",  # invented (JSON test data)
    "MRTMTT91D08F205K",  # MRTMTT91D08F205J with a wrong control letter (negative test)
}


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
        ).stdout.decode("utf-8")
        files = [ROOT / p for p in out.split("\0") if p]
        if files:
            return files
    except (OSError, subprocess.CalledProcessError):
        pass
    return [
        p
        for p in ROOT.rglob("*")
        if p.is_file() and p.name not in SKIP_FILES and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS)
    ]


def allowed(kind: str, value: str) -> bool:
    if kind == "indirizzo email":
        domain = value.rsplit("@", 1)[1].lower()
        return domain in ALLOWED_DOMAINS or domain.endswith(ALLOWED_DOMAIN_SUFFIXES)
    return value in ALLOWED_VALUES


def scan(files: list[Path], root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        for kind, rx in FORBIDDEN_FILES.items():
            if rx.search(rel):
                problems.append(f"{rel}: {kind} (non va pubblicato)")
        if path.resolve() == THIS_FILE or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            problems.append(f"{rel}: file binario o non leggibile (controllalo a mano)")
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for kind, rx in CONTENT_PATTERNS.items():
                for m in rx.finditer(line):
                    if not allowed(kind, m.group()):
                        problems.append(f"{rel}:{lineno}: {kind}: {m.group()}")
    return problems


def main() -> int:
    files = tracked_files()
    problems = scan(files)
    if problems:
        print(f"NON PUBBLICARE: {len(problems)} problemi in {len(files)} file\n")
        print("\n".join(problems))
        return 1
    print(f"OK: {len(files)} file controllati, nessun dato, chiave o segreto trovato.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
