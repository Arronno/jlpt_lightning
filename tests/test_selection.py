import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.urls import reverse
from django.utils import timezone

from learning import study
from learning.forms import StudyForm
from learning.models import CardState, Dataset, Entry, Lesson, PracticeAttempt, StudySession

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def plain_static(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


def test_scope_options_and_validation(client, profile, entries, study_filters):
    lesson = entries[0].lesson
    Entry.objects.filter(pk__in=[entry.pk for entry in entries[3:]]).update(batch=2)
    dataset = Dataset.objects.create(key="test-n4", level=4)
    other_lesson = Lesson.objects.create(dataset=dataset, label="26", position=0)
    selected = {**study_filters, "level": 5, "lesson": lesson.pk, "batch": 2}
    form = StudyForm(selected)
    assert form.is_valid(), form.errors
    assert form.filters()["lesson"] == lesson.pk
    session = study.start_session(profile, form.filters())
    assert [item["entry"] for item in session.queue] == [entry.pk for entry in entries[3:]]
    for invalid in [{"level": 4}, {"lesson": other_lesson.pk}, {"batch": 99}, {"lesson": ""}]:
        response = client.post("/study/", {**selected, **invalid})
        assert response.status_code == 200
        assert response.context["form"].errors
    assert StudySession.objects.count() == 1
    response = client.get("/study/options/", {**selected, "level": 4, "changed": "level"})
    form = response.context["form"]
    assert form["lesson"].value() == "" and form["batch"].value() == ""
    assert list(form.fields["lesson"].queryset) == [other_lesson]
    response = client.get("/study/options/", {**selected, "changed": "lesson"})
    assert response.context["form"]["batch"].value() == ""
    assert len(response.context["form"].fields["batch"].choices) == 3


def test_empty_start_keeps_active_and_undo(client, profile, entries, study_filters):
    session = study.start_session(profile, study_filters)
    item = session.queue[0]
    study.grade(session.pk, item["request_id"], 0, 3)
    empty = study.start_session(profile, {**study_filters, "level": 1})
    session.refresh_from_db()
    assert not empty.active and session.active
    response = client.get(reverse("session", args=[empty.pk]))
    assert response.context["resume_session"] == session
    assert b"No vocabulary matches" in response.content
    study.undo_review(session.pk)
    session.refresh_from_db()
    assert session.cursor == 0 and session.active


def test_start_retry_does_not_replace_newer_session(client, profile, entries, study_filters):
    token = str(uuid.uuid4())
    post = {**study_filters, "session_token": token}
    first = client.post("/study/", post)
    second = client.post("/study/", post)
    assert first.url == second.url
    assert StudySession.objects.count() == 1
    newer = study.start_session(profile, study_filters)
    retry = client.post("/study/", post)
    assert retry.url == first.url
    newer.refresh_from_db()
    assert newer.active
    conflict = client.post("/study/", {**post, "session_size": 1})
    assert conflict.context["form"].non_field_errors()
    replaced = client.get(first.url)
    assert b"This session was replaced" in replaced.content


@pytest.mark.parametrize("direction", ["ja_en", "en_ja", "both"])
def test_completed_batch_replays_without_schedule_or_allowance_changes(
    profile, entries, study_filters, direction
):
    now = timezone.now()
    profile.daily_new = 0
    profile.save()
    Entry.objects.filter(pk__in=[entry.pk for entry in entries[3:]]).update(batch=2)
    for entry in entries:
        CardState.objects.create(
            profile=profile,
            entry=entry,
            direction="ja_en",
            introduced_at=now,
            due=now + timedelta(days=30),
            suspended=True,
        )
    original_states = list(CardState.objects.values())
    filters = {
        **study_filters,
        "mode": "flashcards",
        "direction": direction,
        "level": 5,
        "lesson": entries[0].lesson_id,
        "batch": 2,
    }
    expected = [entry.pk for entry in entries[3:]] * (2 if direction == "both" else 1)
    for _ in range(2):
        session = study.start_session(profile, filters)
        assert sorted(item["entry"] for item in session.queue) == sorted(expected)
        if direction == "both":
            assert all(a["entry"] != b["entry"] for a, b in zip(session.queue, session.queue[1:]))
        else:
            assert [item["entry"] for item in session.queue] == expected
        for index, item in enumerate(session.queue):
            rating = index % 4 + 1
            attempt = study.practice_grade(session.pk, item["request_id"], rating)
            assert study.practice_grade(session.pk, item["request_id"], rating).pk == attempt.pk
            recovered = StudySession.objects.get(pk=session.pk)
            assert recovered.cursor == index + 1
        assert not recovered.active
    assert PracticeAttempt.objects.count() == len(expected) * 2
    assert list(CardState.objects.values()) == original_states
    assert study.daily_remaining(profile, now) == 0


def test_practice_failure_stale_tab_and_reveal(client, profile, entries, study_filters):
    filters = {**study_filters, "mode": "flashcards"}
    old = study.start_session(profile, filters)
    session = study.start_session(profile, filters)
    with pytest.raises(study.StudyConflict):
        study.practice_grade(old.pk, old.queue[0]["request_id"], 3)
    item = session.queue[0]
    with patch("learning.study.advance", side_effect=OperationalError("disk failed")):
        with pytest.raises(OperationalError):
            study.practice_grade(session.pk, item["request_id"], 3)
    session.refresh_from_db()
    assert session.cursor == 0 and not PracticeAttempt.objects.exists()
    post = {"action": "practice_grade", "request_id": item["request_id"], "rating": 3}
    url = reverse("session_action", args=[session.pk])
    response = client.post(url, post)
    assert b"Reveal the answer" in response.content
    assert not PracticeAttempt.objects.exists()
    response = client.post(url, {**post, "revealed": "yes"})
    assert response.status_code == 302
    assert PracticeAttempt.objects.count() == 1


def test_due_siblings_can_use_new_word_separator(profile, entries, study_filters):
    now = timezone.now()
    for direction in ("ja_en", "en_ja"):
        CardState.objects.create(
            profile=profile,
            entry=entries[0],
            direction=direction,
            introduced_at=now,
            due=now - timedelta(days=1),
        )
    session = study.start_session(
        profile, {**study_filters, "direction": "both", "session_size": 3}, now
    )
    assert len(session.queue) == 3
    assert session.queue[0]["entry"] == session.queue[2]["entry"] == entries[0].pk
    assert session.queue[1]["entry"] != entries[0].pk


def test_flashcard_size_limit_keeps_both_directions(profile, entries, study_filters):
    session = study.start_session(
        profile, {**study_filters, "mode": "flashcards", "direction": "both", "session_size": 4}
    )
    assert len(session.queue) == 4
    assert {item["direction"] for item in session.queue} == {"ja_en", "en_ja"}
    assert len({(item["entry"], item["direction"]) for item in session.queue}) == 4
