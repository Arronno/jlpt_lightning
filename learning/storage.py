import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.db import connection


def backup_database(reason="manual"):
    path = Path(settings.DATABASES["default"]["NAME"])
    if not path.exists():
        return None
    directory = settings.DATA_DIR / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = directory / f"{reason}-{stamp}.sqlite3"
    try:
        with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup integrity verification failed.")
        logging.getLogger(__name__).info("Backup created: %s", target.name)
        return target
    except Exception:
        logging.getLogger(__name__).exception("Backup failed")
        raise


def daily_backup():
    directory = settings.DATA_DIR / "backups"
    today = datetime.now().strftime("%Y%m%d")
    if not directory.exists() or not list(directory.glob(f"daily-{today}-*.sqlite3")):
        backup_database("daily")
    if directory.exists():
        for old in sorted(directory.glob("daily-*.sqlite3"), reverse=True)[7:]:
            old.unlink()


def restore_database(source):
    source = Path(source).resolve(strict=True)
    target = Path(settings.DATABASES["default"]["NAME"]).resolve()
    if source == target:
        raise ValueError("Choose a backup file, not the active database.")
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as saved:
        if saved.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("The backup is not a healthy SQLite database.")
        tables = {r[0] for r in saved.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {
            "learning_profile",
            "learning_entry",
            "learning_reviewevent",
            "django_migrations",
        }.issubset(tables):
            raise ValueError("This file is not a JLPT Lightning backup.")
        connection.close()
        backup_database("before-restore")
        with sqlite3.connect(target) as destination:
            saved.backup(destination)


def learning_export():
    # Full portable logical export, including source IDs that learning records reference.
    objects = []
    for model in apps.get_app_config("learning").get_models():
        objects.extend(json.loads(serializers.serialize("json", model.objects.all())))
    return {
        "format": "jlpt-lightning",
        "version": 1,
        "exported_at": datetime.now().astimezone().isoformat(),
        "objects": objects,
    }
