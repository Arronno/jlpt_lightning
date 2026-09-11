from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.db import OperationalError

from learning import study
from learning.models import CardState, ReviewEvent, StudySession

NOW = datetime(2026, 9, 11, 14, 59, tzinfo=timezone.utc)


@pytest.mark.django_db
@pytest.mark.parametrize("rating", [1, 2, 3, 4])
def test_grade_idempotency_revision_undo(profile, entries, study_filters, rating):
    session = study.start_session(profile, study_filters, NOW)
    item = session.queue[0]
    event = study.grade(session.pk, item["request_id"], 0, rating, NOW)
    assert study.grade(session.pk, item["request_id"], 0, rating, NOW).pk == event.pk
    card = CardState.objects.get(pk=item["card"])
    assert card.due > NOW
    assert card.introduced_at == NOW
    assert card.revision == 1
    assert event.scheduler["desired_retention"] == 0.9
    assert event.scheduler_version
    study.undo_review(session.pk)
    card.refresh_from_db()
    session.refresh_from_db()
    assert card.introduced_at is None and card.due is None and card.state == {}
    assert card.revision == 2
    assert session.cursor == 0
    assert session.queue[0]["request_id"] != item["request_id"]
    assert study.grade(session.pk, item["request_id"], 0, rating, NOW).undone
    with pytest.raises(study.StudyConflict):
        study.grade(session.pk, session.queue[0]["request_id"], 0, rating, NOW)


@pytest.mark.django_db
def test_daily_boundary_directions_and_siblings(profile, entries, study_filters):
    profile.daily_new = 1
    profile.save()
    session = study.start_session(profile, {**study_filters, "direction": "both"}, NOW)
    assert len({i["entry"] for i in session.queue}) == 1
    # The lone sibling is deferred instead of placed consecutively.
    assert len(session.queue) == 1
    study.grade(session.pk, session.queue[0]["request_id"], 0, 3, NOW)
    assert study.daily_remaining(profile, NOW) == 0
    assert study.daily_remaining(profile, NOW + timedelta(minutes=2)) == 1
    reverse = study.start_session(profile, {**study_filters, "direction": "en_ja"}, NOW)
    assert len(reverse.queue) == 1
    assert CardState.objects.get(pk=reverse.queue[0]["card"]).direction == "en_ja"
    assert CardState.objects.filter(entry=entries[0]).count() == 2
    next_day = NOW + timedelta(minutes=2)
    study.grade(reverse.pk, reverse.queue[0]["request_id"], 0, 3, next_day)
    assert study.daily_remaining(profile, next_day) == 1


@pytest.mark.django_db
def test_atomic_failure_restart_skip_suspend(profile, entries, study_filters):
    session = study.start_session(profile, study_filters, NOW)
    item = session.queue[0]
    with patch(
        "learning.study.ReviewEvent.objects.create", side_effect=OperationalError("disk failed")
    ):
        with pytest.raises(OperationalError):
            study.grade(session.pk, item["request_id"], 0, 3, NOW)
    card = CardState.objects.get(pk=item["card"])
    assert card.revision == 0 and card.due is None
    assert ReviewEvent.objects.count() == 0
    recovered = StudySession.objects.get(pk=session.pk)
    assert recovered.cursor == 0 and recovered.active
    study.skip(session.pk, item["request_id"], suspend=True)
    card.refresh_from_db()
    assert card.suspended
    with pytest.raises(study.StudyConflict):
        study.grade(session.pk, item["request_id"], 0, 3, NOW)


@pytest.mark.django_db
def test_new_session_rejects_old_tab(profile, entries, study_filters):
    old = study.start_session(profile, study_filters, NOW)
    current = study.start_session(profile, study_filters, NOW)
    with pytest.raises(study.StudyConflict):
        study.grade(old.pk, old.queue[0]["request_id"], 0, 3, NOW)
    assert current.active


@pytest.mark.django_db
def test_practice_normalization_ambiguity_and_separation(profile, entries, study_filters):
    entries[0].kana = "カタカナ"
    entries[0].save()
    session = study.start_session(profile, {**study_filters, "mode": "typing"})
    item = session.queue[0]
    attempt = study.practice_answer(session.pk, item["request_id"], " ｶﾀｶﾅ ")
    assert attempt.correct
    assert study.practice_answer(session.pk, item["request_id"], "wrong").pk == attempt.pk
    study.practice_continue(session.pk, item["request_id"], True)
    assert not CardState.objects.exists()
    assert not ReviewEvent.objects.exists()
    assert study.normalize("かたかな") != study.normalize("カタカナ")
    assert len(study.quiz_options(entries[1], entries)) == 4
    entries[2].kana = entries[1].kana
    assert study.quiz_options(entries[1], entries) == []
