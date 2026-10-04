"""Local web interface (Flask), bound to 127.0.0.1 only.

Protections that matter for a local app that handles personal data:
- Host header check (blocks DNS rebinding: a web page cannot talk to this server);
- a random token required on every POST (blocks cross-site form posts);
- strict Content-Security-Policy, no external resources, no caching;
- files live in a private temporary folder, removed on exit or on request.
"""

from __future__ import annotations

import argparse
import atexit
import hmac
import secrets
import shutil
import signal
import sys
import tempfile
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Flask, abort, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from .. import __version__
from ..checks import find_mismatches, signature
from ..errors import VeloError
from ..formats import get_adapter
from ..keystore import default_dir
from ..model import Category, FieldChoice, FieldInfo, Mode
from ..service import PseudonymizeResult, RestoreResult, pseudonymize, restore

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_UPLOAD_MB = 200

CATEGORIES: list[tuple[str, str]] = [
    (Category.FULLNAME.value, "Nome e cognome"),
    (Category.FIRST_NAME.value, "Nome"),
    (Category.LAST_NAME.value, "Cognome"),
    (Category.FISCAL_CODE.value, "Codice fiscale"),
    (Category.IBAN.value, "IBAN"),
    (Category.VAT_ID.value, "Partita IVA"),
    (Category.EMAIL.value, "Email"),
    (Category.PHONE.value, "Telefono"),
    (Category.ADDRESS.value, "Indirizzo"),
    (Category.CITY.value, "Città"),
    (Category.POSTCODE.value, "CAP"),
    (Category.DATE.value, "Data"),
    (Category.AMOUNT.value, "Importo"),
    (Category.TEXT.value, "Testo generico"),
]
CATEGORY_LABELS = dict(CATEGORIES)

ERROR_TITLES = {
    400: "Richiesta non valida",
    403: "Richiesta non autorizzata",
    404: "Pagina non trovata",
    413: "File troppo grande",
    500: "Errore interno",
}
ERROR_TEXT = {
    400: "La richiesta non è stata accettata.",
    403: "La pagina è scaduta o la richiesta non arriva da questa applicazione. Torna all'inizio e riprova.",
    404: "Questa pagina non esiste o i file sono stati eliminati.",
    413: f"Il limite è {MAX_UPLOAD_MB} MB per file.",
    500: "L'operazione non è riuscita per un errore imprevisto. Nessun file è stato inviato altrove.",
}


@dataclass
class Session:
    sid: str
    dir: Path
    filename: str
    format: str
    fields: list[FieldInfo]
    warnings: list[str]
    result: PseudonymizeResult | None = None
    restored: RestoreResult | None = None
    confirmed: list[str] | None = None  # mismatches the user chose to proceed with


def create_app(port: int = DEFAULT_PORT, workdir: Path | None = None) -> Flask:
    app = Flask(__name__)
    root = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="velo-"))
    root.mkdir(parents=True, exist_ok=True)
    if not workdir:
        atexit.register(shutil.rmtree, root, ignore_errors=True)
    sessions: dict[str, Session] = {}

    app.config.update(
        MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
        CSRF_TOKEN=secrets.token_urlsafe(32),
        ALLOWED_HOSTS={f"{HOST}:{port}", f"localhost:{port}"},
        WORKDIR=root,
    )
    app.extensions["velo_sessions"] = sessions

    # -- protections ------------------------------------------------------------------

    @app.before_request
    def guard():
        if request.host not in app.config["ALLOWED_HOSTS"]:
            abort(400)
        if request.method == "POST":
            sent = request.form.get("csrf", "")
            if not hmac.compare_digest(sent, app.config["CSRF_TOKEN"]):
                abort(403)

    @app.after_request
    def headers(resp):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; script-src 'self'; "
            "img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        return resp

    @app.context_processor
    def inject():
        return {"csrf": app.config["CSRF_TOKEN"], "version": __version__, "labels": CATEGORY_LABELS}

    for code in ERROR_TITLES:
        app.register_error_handler(
            code,
            lambda e, code=code: (
                render_template("error.html", title=ERROR_TITLES[code], message=ERROR_TEXT[code]),
                code,
            ),
        )

    # -- helpers ----------------------------------------------------------------------

    def fail(message: str, status: int = 400):
        return render_template(
            "error.html", title="Impossibile completare l'operazione", message=message
        ), status

    def get_session(sid: str) -> Session:
        sess = sessions.get(sid)
        if sess is None:
            abort(404)
        return sess

    def new_dir() -> tuple[str, Path]:
        sid = secrets.token_urlsafe(16)
        d = root / sid
        (d / "in").mkdir(parents=True)
        (d / "out").mkdir()
        return sid, d

    def save_upload(field: str, dest: Path) -> Path:
        up = request.files.get(field)
        name = secure_filename(up.filename or "") if up else ""
        if not up or not name:
            raise VeloError("Scegli un file da caricare.")
        path = dest / name
        up.save(path)
        return path

    def fields_page(
        sess: Session,
        form: Any = None,
        errors: list[str] | None = None,
        status: int = 200,
        mismatches: list[str] | None = None,
        confirm: str = "",
    ):
        is_csv, is_xlsx = sess.format == "csv", sess.format == "excel"
        return (
            render_template(
                "fields.html",
                sess=sess,
                form=form or {},
                errors=errors or [],
                categories=CATEGORIES,
                is_csv=is_csv,
                is_xlsx=is_xlsx,
                key_dir=str(default_dir()),
                mismatches=mismatches or [],
                confirm=confirm,
            ),
            status,
        )

    # -- routes -----------------------------------------------------------------------

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/upload")
    def upload():
        sid, d = new_dir()
        try:
            path = save_upload("file", d / "in")
            adapter = get_adapter(path)
            inspection = adapter.inspect(path)
        except VeloError as exc:
            shutil.rmtree(d, ignore_errors=True)
            return fail(str(exc))
        if not inspection.fields:
            shutil.rmtree(d, ignore_errors=True)
            return fail("Nel file non ci sono campi da mostrare.")
        sessions[sid] = Session(sid, d, path.name, inspection.format, inspection.fields, inspection.warnings)
        return redirect(url_for("fields", sid=sid))

    @app.get("/s/<sid>")
    def fields(sid):
        return fields_page(get_session(sid))

    @app.post("/s/<sid>/run")
    def run(sid):
        sess = get_session(sid)
        form = request.form
        plan: dict[str, FieldChoice] = {}
        errors: list[str] = []
        for i, f in enumerate(sess.fields):
            if form.get(f"sel_{i}") != "on":
                continue
            try:
                category = Category(form.get(f"cat_{i}", ""))
            except ValueError:
                errors.append(f"Indica che tipo di dato contiene «{f.label}».")
                continue
            try:
                mode = Mode(form.get(f"mode_{i}", Mode.FAKE.value))
            except ValueError:
                mode = Mode.FAKE
            plan[f.id] = FieldChoice(f.id, category, mode)
        if not plan and not errors:
            errors.append("Spunta almeno un campo da sostituire.")
        if errors:
            return fields_page(sess, form, errors, 400)

        try:
            found = find_mismatches(sess.dir / "in" / sess.filename, plan, sess.dir)
        except VeloError as exc:
            return fields_page(sess, form, [str(exc)], 400)
        sig = signature(found) if found else ""
        if found and form.get("confirmed") != sig:
            return fields_page(sess, form, mismatches=[m.message() for m in found], confirm=sig)
        sess.confirmed = [m.message() for m in found] or None

        params: dict[str, Any] = {}
        if sess.format == "csv" and form.get("encoding") == "utf-8":
            params["encoding"] = "utf-8"
        if sess.format == "excel":
            params["scrub_metadata"] = form.get("scrub") == "on"
        key_mode = "project" if form.get("key") == "project" else "ephemeral"
        try:
            sess.result = pseudonymize(
                sess.dir / "in" / sess.filename,
                sess.dir / "out",
                plan,
                key_mode=key_mode,
                params=params,
                overwrite=True,
            )
        except VeloError as exc:
            return fields_page(sess, form, [str(exc)], 400)
        return redirect(url_for("result", sid=sid))

    @app.get("/s/<sid>/result")
    def result(sid):
        sess = get_session(sid)
        if sess.result is None:
            return redirect(url_for("fields", sid=sid))
        return render_template("result.html", sess=sess, r=sess.result, plan_labels=CATEGORY_LABELS)

    @app.get("/s/<sid>/download/<kind>")
    def download(sid, kind):
        sess = get_session(sid)
        path = None
        if kind in ("output", "mapping") and sess.result:
            path = sess.result.output if kind == "output" else sess.result.mapping
        elif kind == "restored" and sess.restored:
            path = sess.restored.output
        if path is None or not path.exists():
            abort(404)
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.post("/s/<sid>/delete")
    def delete(sid):
        sess = get_session(sid)
        shutil.rmtree(sess.dir, ignore_errors=True)
        del sessions[sid]
        return render_template("deleted.html")

    @app.route("/restore", methods=["GET", "POST"])
    def restore_page():
        if request.method == "GET":
            return render_template("restore.html")
        sid, d = new_dir()
        try:
            pseudo = save_upload("pseudonymized", d / "in")
            mapping = save_upload("mapping", d / "in")
            stem = pseudo.stem[: -len(".pseudo")] if pseudo.stem.endswith(".pseudo") else pseudo.stem
            out = d / "out" / f"{stem}.restored{pseudo.suffix}"
            res = restore(pseudo, mapping, out, overwrite=True)
        except VeloError as exc:
            shutil.rmtree(d, ignore_errors=True)
            return fail(str(exc))
        sessions[sid] = Session(sid, d, pseudo.name, "", [], [], restored=res)
        return redirect(url_for("restored", sid=sid))

    @app.get("/s/<sid>/restored")
    def restored(sid):
        sess = get_session(sid)
        if sess.restored is None:
            abort(404)
        return render_template("restore_result.html", sess=sess, r=sess.restored)

    return app


def purge_stale(max_age_hours: float = 24.0, base: Path | None = None) -> int:
    """Remove velo-* temp folders left by sessions that ended abruptly. Returns how many."""
    base = Path(base) if base else Path(tempfile.gettempdir())
    limit = time.time() - max_age_hours * 3600
    removed = 0
    for d in base.glob("velo-*"):
        try:
            if d.is_dir() and d.stat().st_mtime < limit:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def _exit_cleanly(signum, frame):
    sys.exit(0)  # lets atexit run, which removes the temporary folder


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="velo", description="Pseudonimizzazione locale di file Excel, CSV e JSON."
    )
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"porta locale (default {DEFAULT_PORT})")
    p.add_argument("--no-browser", action="store_true", help="non aprire il browser")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    purge_stale()
    for name in ("SIGTERM", "SIGBREAK"):  # SIGBREAK exists on Windows only
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _exit_cleanly)
    app = create_app(port=args.port)
    url = f"http://{HOST}:{args.port}"
    print(f"velo {__version__}: in ascolto su {url} (solo questo computer). Ctrl+C per chiudere.")
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    try:
        app.run(host=HOST, port=args.port, debug=False, threaded=True)
    except OSError as exc:
        raise SystemExit(f"Impossibile usare la porta {args.port}: {exc}. Prova con --port 8766.") from exc
