"""End-to-end acceptance audit on disposable data, never on the learner's database.

Run through uv from the project root. Uses installed Edge on Windows, Chromium elsewhere.
Artifacts and measurement results are written to .runtime/acceptance.
"""
# ruff: noqa: E402 -- initialize the isolated Django settings before model imports.

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / ".runtime" / "acceptance" / str(uuid.uuid4())
RUN.mkdir(parents=True)
sys.path.insert(0, str(ROOT))
os.environ["JLPT_DATA_DIR"] = str(RUN / "data")
os.environ["DJANGO_SETTINGS_MODULE"] = "lightning.settings"

import django

django.setup()

from django.core.management import call_command
from playwright.sync_api import sync_playwright

from learning.models import Annotation, Collection, Entry, Profile
from learning.storage import backup_database
from learning.study import grade, start_session


def main():
    call_command("local", "setup")
    assert Entry.objects.count() == 5736
    profile = Profile.local()
    entry = Entry.objects.first()
    Annotation.objects.create(profile=profile, entry=entry, note="Backup round-trip note")
    collection = Collection.objects.create(profile=profile, name="Acceptance collection")
    collection.entries.add(entry)
    session = start_session(
        profile, {"mode": "cards", "direction": "ja_en", "ordering": "source", "session_size": 20}
    )
    grade(session.pk, session.queue[0]["request_id"], 0, 3)
    saved = backup_database("acceptance")
    restored = RUN / "restored"
    subprocess.run(
        [sys.executable, "manage.py", "local", "restore", "--source", str(saved)],
        cwd=ROOT,
        env={**os.environ, "JLPT_DATA_DIR": str(restored)},
        check=True,
    )
    with sqlite3.connect(restored / "learning.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM learning_entry").fetchone()[0] == 5736
        assert db.execute("SELECT COUNT(*) FROM learning_reviewevent").fetchone()[0] == 1
        assert (
            db.execute("SELECT note FROM learning_annotation").fetchone()[0]
            == "Backup round-trip note"
        )
        assert db.execute("SELECT COUNT(*) FROM learning_collection_entries").fetchone()[0] == 1
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with (RUN / "server.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [sys.executable, "manage.py", "local", "serve", "--port", str(port)],
            cwd=ROOT,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("Server exited; inspect server.log")
                try:
                    with urlopen(base, timeout=1) as response:
                        assert response.status == 200
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Server did not start")
            times = []
            for _ in range(40):
                start = time.perf_counter()
                with urlopen(f"{base}/study/{session.pk}/") as response:
                    response.read()
                    assert response.headers["Cache-Control"] == "no-store"
                times.append((time.perf_counter() - start) * 1000)
            p95 = sorted(times)[37]
            assert p95 < 200, f"Study request p95 is {p95:.1f} ms"
            # The running server must reject concurrent restore/maintenance.
            rejected = subprocess.run(
                [sys.executable, "manage.py", "local", "restore", "--source", str(saved)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            assert rejected.returncode != 0 and "Stop the running" in rejected.stderr
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge" if os.name == "nt" else None)
                page = browser.new_page(viewport={"width": 1440, "height": 1050})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base)
                page.screenshot(path=str(RUN / "today-desktop.png"), full_page=True)
                page.goto(f"{base}/study/{session.pk}/")
                page.get_by_role("button", name="Reveal answer").click()
                page.screenshot(path=str(RUN / "flashcard-desktop.png"), full_page=True)
                assert page.locator(".card-answer").is_visible()
                page.set_viewport_size({"width": 390, "height": 844})
                page.goto(base)
                page.screenshot(path=str(RUN / "today-mobile.png"), full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                assert not errors, errors
                browser.close()
            results = {
                "corpus_rows": 5736,
                "backup_restored": True,
                "maintenance_lock": True,
                "study_get_p95_ms": round(p95, 2),
                "study_get_samples": len(times),
                "browser_errors": errors,
            }
            (RUN / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(json.dumps({**results, "artifacts": str(RUN)}, indent=2))
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
