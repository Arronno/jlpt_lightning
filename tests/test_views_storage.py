import json
import sqlite3

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from learning.models import Collection, ReviewEvent
from learning.storage import backup_database, restore_database


@pytest.fixture(autouse=True)
def plain_static(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.mark.django_db
def test_pages_and_settings(client, profile, entries):
    for url in [
        "/",
        "/lessons/",
        "/lessons/?level=1",
        "/library/",
        "/collections/",
        "/study/",
        "/settings/",
        "/data/",
        f"/word/{entries[0].pk}/",
    ]:
        response = client.get(url)
        assert response.status_code == 200, url
        assert response["Cache-Control"] == "no-store"
    assert b"No vocabulary imported" in client.get("/lessons/?level=1").content
    response = client.post(
        "/settings/",
        {
            "name": "Test learner",
            "theme": "dark",
            "font_size": 48,
            "daily_new": 5,
            "session_size": 12,
            "direction": "both",
            "ordering": "shuffle",
            "examples": "on",
        },
    )
    assert response.status_code == 302
    profile.refresh_from_db()
    assert profile.theme == "dark" and profile.daily_new == 5
    assert client.post("/settings/", {"font_size": 999}).status_code == 200


@pytest.mark.django_db
def test_csrf_and_request_validation(profile, entries):
    guarded = Client(enforce_csrf_checks=True)
    assert guarded.post(f"/word/{entries[0].pk}/bookmark/").status_code == 403
    assert guarded.get("/lessons/?level=abc").status_code == 400


@pytest.mark.django_db
def test_collections_presets_and_export(client, profile, entries, study_filters):
    collection = Collection.objects.create(profile=profile, name="Travel")
    response = client.post(
        reverse("word", args=[entries[0].pk]),
        {
            "note": "My personal hint",
            "tags": "travel, nouns",
            "bookmarked": "on",
            "collections": [collection.pk],
        },
    )
    assert response.status_code == 302
    assert collection.entries.get().pk == entries[0].pk
    response = client.post(
        "/study/", {**study_filters, "collection": collection.pk, "preset_name": "Travel cards"}
    )
    assert response.status_code == 302
    # A fresh browser session finds persisted progress without login cookies.
    assert b"Resume session" in Client().get("/").content
    payload = json.loads(client.get("/data/export/json/").content)
    assert payload["version"] == 1 and payload["format"] == "jlpt-lightning"
    assert any(
        o["model"] == "learning.annotation" and o["fields"]["note"] == "My personal hint"
        for o in payload["objects"]
    )
    assert "ねこ" in client.get("/data/export/csv/").content.decode("utf-8-sig")
    assert b"Travel" in client.get("/study/").content


@pytest.mark.django_db
def test_reveal_gate_and_fragment(client, profile, entries, study_filters):
    from learning.study import start_session

    session = start_session(profile, study_filters)
    item = session.queue[0]
    url = reverse("session_action", args=[session.pk])
    post = {"action": "grade", "request_id": item["request_id"], "revision": 0, "rating": 3}
    response = client.post(url, post, HTTP_HX_REQUEST="true")
    assert b"Reveal the answer" in response.content
    assert ReviewEvent.objects.count() == 0
    response = client.post(url, {**post, "revealed": "yes"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and b'id="study-panel"' in response.content
    assert b"<!doctype" not in response.content
    assert ReviewEvent.objects.count() == 1
    client.post(url, {**post, "revealed": "yes"}, HTTP_HX_REQUEST="true")
    assert ReviewEvent.objects.count() == 1


@pytest.mark.filterwarnings("ignore:Overriding setting DATABASES:UserWarning")
def test_backup_restore_integrity(tmp_path, settings):
    # Exercise SQLite's backup API against a real file, including WAL state.
    database = tmp_path / "live.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA journal_mode=WAL")
        for name in [
            "learning_profile",
            "learning_entry",
            "learning_reviewevent",
            "django_migrations",
        ]:
            db.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY, payload TEXT)")
        db.execute("INSERT INTO learning_profile VALUES (1, 'my preferences')")
        db.execute("INSERT INTO learning_entry VALUES (1, 'ねこ')")
        db.execute("INSERT INTO learning_reviewevent VALUES (1, 'review history')")
    with override_settings(
        DATA_DIR=tmp_path,
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": database}},
    ):
        saved = backup_database()
        with sqlite3.connect(database) as db:
            db.execute("DELETE FROM learning_reviewevent")
        restore_database(saved)
        with sqlite3.connect(database) as db:
            assert (
                db.execute("SELECT payload FROM learning_reviewevent").fetchone()[0]
                == "review history"
            )
            assert db.execute("SELECT payload FROM learning_entry").fetchone()[0] == "ねこ"
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert list((tmp_path / "backups").glob("before-restore-*"))
