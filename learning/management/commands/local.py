import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command

from learning.catalog import apply_import, preview_import
from learning.models import Dataset, Profile
from learning.network import serving_addresses
from learning.storage import backup_database, daily_backup, restore_database


@contextmanager
def exclusive_app_lock():
    """One local server or maintenance process; released automatically after a crash."""
    path = settings.DATA_DIR / "app.lock"
    with path.open("a+b") as handle:
        handle.seek(0)
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise CommandError(
                "Stop the running JLPT Lightning app before maintenance or starting another copy."
            ) from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Command(BaseCommand):
    help = "Set up, serve, back up, or restore the local application."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["setup", "serve", "backup", "restore"])
        parser.add_argument(
            "--source", type=Path, help="SQLite backup to restore (app must be stopped)"
        )
        parser.add_argument("--port", type=int, default=8765)
        parser.add_argument(
            "--lan",
            action="store_true",
            help="Also accept connections on this PC's private LAN addresses.",
        )
        parser.add_argument(
            "--lan-address", help="Use one detected private IPv4 address instead of all of them."
        )

    def handle(self, *args, **options):
        action = options["action"]
        if not 1 <= options["port"] <= 65535:
            raise CommandError("Port must be between 1 and 65535.")
        if (options["lan"] or options["lan_address"]) and action != "serve":
            raise CommandError("LAN options apply only to local serve.")
        try:
            addresses = serving_addresses(options["lan"], options["lan_address"])
        except (ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        settings.ALLOWED_HOSTS = list(dict.fromkeys([*settings.ALLOWED_HOSTS, *addresses]))
        with exclusive_app_lock():
            if action == "restore":
                if not options["source"]:
                    raise CommandError("Pass --source with a full database backup.")
                restore_database(options["source"])
                self.stdout.write(self.style.SUCCESS("Backup restored. Start the app normally."))
                return
            if action == "backup":
                self.stdout.write(str(backup_database()))
                return
            from django.db import connection
            from django.db.migrations.executor import MigrationExecutor

            pending = MigrationExecutor(connection).migration_plan(
                MigrationExecutor(connection).loader.graph.leaf_nodes()
            )
            if pending:
                backup_database("before-migrate")
                call_command("migrate", interactive=False, verbosity=1)
            connection.close()
            with sqlite3.connect(settings.DATABASES["default"]["NAME"]) as db:
                db.execute("PRAGMA journal_mode=WAL")
            Profile.local()
            if action == "setup":
                for level in range(5, 1, -1):
                    path = settings.BASE_DIR / "JLPT_VOCAB" / f"JLPT_N{level}_Vocabulary_Fixed.xlsx"
                    key = f"jlpt-n{level}"
                    if path.exists() and not Dataset.objects.filter(key=key).exists():
                        batch = preview_import(path.read_bytes(), path.name, level, key)
                        if batch.errors:
                            raise CommandError("\n".join(batch.errors))
                        apply_import(batch.pk)
                        self.stdout.write(f"Imported N{level}: {len(batch.payload['rows'])} words")
            daily_backup()
            call_command("collectstatic", interactive=False, verbosity=0)
            call_command("check", verbosity=0)
            if action == "serve":
                from waitress import serve

                from lightning.wsgi import application

                self.stdout.write(
                    self.style.SUCCESS(
                        f"JLPT Lightning is ready at http://127.0.0.1:{options['port']}"
                    )
                )
                self.stdout.write("Press Ctrl+C to stop. Your progress is saved after each review.")
                for address in addresses[1:]:
                    self.stdout.write(
                        self.style.SUCCESS(f"On your phone: http://{address}:{options['port']}")
                    )
                if options["lan"]:
                    self.stdout.write(
                        "Devices on this network share your learner profile. Keep this terminal open while studying."
                    )
                serve(
                    application,
                    listen=" ".join(f"{address}:{options['port']}" for address in addresses),
                    threads=4,
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS("Setup complete. Run .\\scripts\\start.ps1 to study.")
                )
