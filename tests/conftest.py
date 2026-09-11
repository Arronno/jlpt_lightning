import os
import tempfile
from pathlib import Path

os.environ.setdefault("JLPT_DATA_DIR", str(Path(tempfile.gettempdir()) / "jlpt-lightning-tests"))
# Playwright's synchronous API keeps an event loop in the test runner thread.
# ORM calls in this harness remain synchronous; never enable this in app settings.
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

import pytest
from django.core.management import call_command

from learning.models import Dataset, Entry, Lesson, Profile, normalize


@pytest.fixture
def profile(db):
    return Profile.local()


@pytest.fixture
def entries(db):
    dataset = Dataset.objects.create(key="test-n5", level=5)
    lesson = Lesson.objects.create(dataset=dataset, label="1", position=0)
    values = [
        ("ねこ", "cat"),
        ("いぬ", "dog"),
        ("みず", "water"),
        ("ほん", "book"),
        ("やま", "mountain"),
        ("そら", "sky"),
    ]
    return [
        Entry.objects.create(
            dataset=dataset,
            lesson=lesson,
            serial=i,
            position=i,
            kana=kana,
            english=english,
            search=normalize(kana + " " + english),
        )
        for i, (kana, english) in enumerate(values, 1)
    ]


@pytest.fixture
def study_filters(profile):
    return {"mode": "cards", "direction": "ja_en", "ordering": "source", "session_size": 20}


@pytest.fixture
def browser_assets(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    settings.WHITENOISE_USE_FINDERS = True
    call_command("collectstatic", interactive=False, verbosity=0)
