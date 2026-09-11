import random
import uuid
from datetime import datetime, time
from importlib.metadata import version

from django.db import transaction
from django.db.models import Min
from django.utils import timezone
from fsrs import Card, Rating, Scheduler

from .catalog import filter_entries
from .models import CardState, Entry, PracticeAttempt, Profile, ReviewEvent, StudySession, normalize


class StudyConflict(ValueError):
    pass


def scheduler():
    return Scheduler(desired_retention=0.9)


def day_start(now):
    return datetime.combine(
        timezone.localtime(now).date(), time.min, timezone.get_current_timezone()
    )


def daily_remaining(profile, now):
    introduced = (
        CardState.objects.filter(profile=profile, introduced_at__isnull=False)
        .values("entry_id")
        .annotate(first_introduced=Min("introduced_at"))
        .filter(first_introduced__gte=day_start(now), first_introduced__lte=now)
        .count()
    )
    return max(0, profile.daily_new - introduced)


def quiz_options(entry, candidates):
    # Same reading with different meanings is ambiguous without kanji/context.
    meanings = {
        normalize(e.english).casefold()
        for e in candidates
        if normalize(e.kana) == normalize(entry.kana)
    }
    if len(meanings) != 1:
        return []
    target = normalize(entry.english).casefold()
    glosses = {p.strip() for p in target.split(";")}
    options, used = [entry.english], {target}
    shuffled = list(candidates)
    random.shuffle(shuffled)
    for other in shuffled:
        meaning = normalize(other.english).casefold()
        if meaning in used or normalize(other.kana) == normalize(entry.kana):
            continue
        if glosses & {p.strip() for p in meaning.split(";")}:
            continue
        used.add(meaning)
        options.append(other.english)
        if len(options) == 4:
            random.shuffle(options)
            return options
    return []


@transaction.atomic
def start_session(profile, filters, now=None, request_id=None):
    if request_id:
        previous = StudySession.objects.filter(pk=request_id, profile=profile).first()
        if previous:
            if previous.filters != filters:
                raise StudyConflict(
                    "This form already started a different session. Reload Study to choose again."
                )
            return previous
    now = now or timezone.now()
    entries = list(filter_entries(filters))
    size = filters.get("session_size", profile.session_size)
    mode = filters.get("mode", "cards")
    queue = []
    if mode == "cards":
        directions = (
            ["ja_en", "en_ja"] if filters["direction"] == "both" else [filters["direction"]]
        )
        entry_ids = [e.pk for e in entries]
        states = list(
            CardState.objects.filter(
                profile=profile, entry_id__in=entry_ids, direction__in=directions
            ).select_related("entry")
        )
        due = sorted(
            [s for s in states if not s.suspended and s.due and s.due <= now], key=lambda s: s.due
        )
        queued = list(due)
        known = {(s.entry_id, s.direction): s for s in states}
        already_introduced = set(
            CardState.objects.filter(profile=profile, introduced_at__isnull=False).values_list(
                "entry_id", flat=True
            )
        )
        allowance = daily_remaining(profile, now)
        new_entries = set()
        new_count = 0
        if filters.get("ordering") == "shuffle":
            random.shuffle(entries)
        for entry in entries:
            if new_count >= size:
                break
            for direction in directions:
                state = known.get((entry.pk, direction))
                if state and (state.suspended or state.introduced_at):
                    continue
                if entry.pk not in already_introduced and entry.pk not in new_entries:
                    if len(new_entries) >= allowance:
                        continue
                    new_entries.add(entry.pk)
                if state is None:
                    state = CardState.objects.create(
                        profile=profile, entry=entry, direction=direction
                    )
                queued.append(state)
                new_count += 1
                if new_count >= size:
                    break
        # Keep due-first order where possible, deferring a sibling if no separator exists.
        while queued and len(queue) < size:
            index = next(
                (i for i, s in enumerate(queued) if not queue or s.entry_id != queue[-1]["entry"]),
                None,
            )
            if index is None:
                break
            state = queued.pop(index)
            queue.append(
                {"card": state.pk, "entry": state.entry_id, "request_id": str(uuid.uuid4())}
            )
    elif mode == "flashcards":
        if filters.get("ordering") == "shuffle":
            random.shuffle(entries)
        directions = (
            ["ja_en", "en_ja"] if filters["direction"] == "both" else [filters["direction"]]
        )
        # Reserve room for each requested direction within the card limit, then
        # separate siblings by walking the selected words once per direction.
        selected = entries[: (size + len(directions) - 1) // len(directions)]
        for direction in directions:
            for entry in selected:
                if len(queue) >= size:
                    break
                queue.append(
                    {"entry": entry.pk, "direction": direction, "request_id": str(uuid.uuid4())}
                )
    else:
        if filters.get("ordering") == "shuffle":
            random.shuffle(entries)
        candidates = list(Entry.objects.all()) if mode == "quiz" else []
        for entry in entries:
            choices = quiz_options(entry, candidates) if mode == "quiz" else []
            if mode == "quiz" and not choices:
                continue
            queue.append({"entry": entry.pk, "choices": choices, "request_id": str(uuid.uuid4())})
            if len(queue) >= size:
                break
    if queue:
        StudySession.objects.filter(profile=profile, active=True).update(active=False)
    return StudySession.objects.create(
        id=request_id or uuid.uuid4(),
        profile=profile,
        mode=mode,
        filters=filters,
        queue=queue,
        active=bool(queue),
    )


def card_snapshot(state):
    return {
        "state": state.state,
        "due": state.due.isoformat() if state.due else None,
        "introduced_at": state.introduced_at.isoformat() if state.introduced_at else None,
        "revision": state.revision,
    }


def fsrs_card(state, now):
    return Card.from_dict(state.state) if state.state else Card(card_id=state.pk, due=now)


def interval_label(delta):
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "<1 min"
    if seconds < 3600:
        return f"{seconds // 60} min"
    if seconds < 86400:
        return f"{seconds // 3600} hr"
    return f"{seconds // 86400} days"


def rating_intervals(state, now=None):
    now = now or timezone.now()
    engine = scheduler()
    result = []
    for rating, help_text in [
        (Rating.Again, "Didn't recall"),
        (Rating.Hard, "Recalled with difficulty"),
        (Rating.Good, "Recalled correctly"),
        (Rating.Easy, "Effortless recall"),
    ]:
        updated, _ = engine.review_card(fsrs_card(state, now), rating, review_datetime=now)
        result.append(
            {
                "value": rating.value,
                "name": rating.name,
                "help": help_text,
                "interval": interval_label(updated.due - now),
            }
        )
    return result


def validate_current(session, request_id):
    if not session.active or session.cursor >= len(session.queue):
        raise StudyConflict("This session has ended. Start or resume a session from Today.")
    item = session.queue[session.cursor]
    if item["request_id"] != str(request_id):
        raise StudyConflict("This card has already changed in another tab. Reload to continue.")
    return item


def advance(session):
    session.cursor += 1
    session.active = session.cursor < len(session.queue)
    session.save(update_fields=["cursor", "active"])


@transaction.atomic
def grade(session_id, request_id, revision, rating, now=None):
    now = now or timezone.now()
    duplicate = ReviewEvent.objects.filter(request_id=request_id).first()
    if duplicate:
        if str(duplicate.session_id) != str(session_id):
            raise StudyConflict("Review request belongs to a different session.")
        return duplicate
    session = StudySession.objects.get(pk=session_id, profile_id=1)
    item = validate_current(session, request_id)
    if session.mode != "cards":
        raise StudyConflict("This is a practice session.")
    state = CardState.objects.get(pk=item["card"], profile_id=1)
    if state.revision != revision or state.suspended:
        raise StudyConflict("This card changed in another tab. Reload to continue.")
    profile = Profile.local()
    if (
        not state.introduced_at
        and not CardState.objects.filter(
            profile=profile, entry=state.entry, introduced_at__isnull=False
        ).exists()
        and not daily_remaining(profile, now)
    ):
        raise StudyConflict(
            "Your daily new-word allowance is complete. Skip this card or adjust Settings."
        )
    before = card_snapshot(state)
    engine = scheduler()
    updated, _ = engine.review_card(fsrs_card(state, now), Rating(rating), review_datetime=now)
    state.state, state.due = updated.to_dict(), updated.due
    state.introduced_at = state.introduced_at or now
    state.revision += 1
    state.save()
    event = ReviewEvent.objects.create(
        request_id=request_id,
        card=state,
        session=session,
        rating=rating,
        reviewed_at=now,
        before=before,
        after=card_snapshot(state),
        scheduler=engine.to_dict(),
        scheduler_version=version("fsrs"),
        session_cursor=session.cursor,
    )
    advance(session)
    return event


@transaction.atomic
def undo_review(session_id):
    event = ReviewEvent.objects.filter(card__profile_id=1, undone=False).order_by("-pk").first()
    if not event or str(event.session_id) != str(session_id):
        raise StudyConflict("Only the latest review can be undone.")
    session = StudySession.objects.get(pk=session_id)
    state = CardState.objects.get(pk=event.card_id)
    if state.revision != event.after["revision"] or session.cursor != event.session_cursor + 1:
        raise StudyConflict("A later action superseded this review.")
    if (
        StudySession.objects.filter(profile_id=1, created_at__gt=session.created_at)
        .exclude(queue=[])
        .exists()
    ):
        raise StudyConflict("A newer session superseded this review.")
    state.state = event.before["state"]
    state.due = datetime.fromisoformat(event.before["due"]) if event.before["due"] else None
    state.introduced_at = (
        datetime.fromisoformat(event.before["introduced_at"])
        if event.before["introduced_at"]
        else None
    )
    state.revision += 1
    state.save()
    event.undone = True
    event.save(update_fields=["undone"])
    session.cursor = event.session_cursor
    session.queue[session.cursor]["request_id"] = str(uuid.uuid4())
    session.active = True
    session.save()


@transaction.atomic
def skip(session_id, request_id, suspend=False):
    session = StudySession.objects.get(pk=session_id, profile_id=1)
    item = validate_current(session, request_id)
    if suspend and session.mode == "cards":
        state = CardState.objects.get(pk=item["card"])
        state.suspended = True
        state.revision += 1
        state.save()
    advance(session)


@transaction.atomic
def practice_answer(session_id, request_id, answer):
    attempt = PracticeAttempt.objects.filter(request_id=request_id).first()
    if attempt:
        if str(attempt.session_id) != str(session_id):
            raise StudyConflict("Practice request belongs to another session.")
        return attempt
    session = StudySession.objects.get(pk=session_id, profile_id=1)
    item = validate_current(session, request_id)
    entry = Entry.objects.get(pk=item["entry"])
    if session.mode not in ("typing", "quiz"):
        raise StudyConflict("This is a scheduled review.")
    if session.mode == "quiz" and answer not in item["choices"]:
        raise ValueError("Choose one of the displayed answers.")
    expected = entry.kana if session.mode == "typing" else entry.english
    return PracticeAttempt.objects.create(
        request_id=request_id,
        session=session,
        entry=entry,
        answer=answer[:10000],
        correct=normalize(answer) == normalize(expected),
    )


@transaction.atomic
def practice_grade(session_id, request_id, rating):
    if rating not in (1, 2, 3, 4):
        raise ValueError("Choose Again, Hard, Good, or Easy.")
    attempt = PracticeAttempt.objects.filter(request_id=request_id).first()
    if attempt:
        if str(attempt.session_id) != str(session_id):
            raise StudyConflict("Practice request belongs to another session.")
        return attempt
    session = StudySession.objects.get(pk=session_id, profile_id=1)
    item = validate_current(session, request_id)
    if session.mode != "flashcards":
        raise StudyConflict("This is not a flashcard practice session.")
    attempt = PracticeAttempt.objects.create(
        request_id=request_id,
        session=session,
        entry_id=item["entry"],
        answer=str(rating),
        correct=rating >= 3,
        self_assessment=rating >= 3,
    )
    advance(session)
    return attempt


@transaction.atomic
def practice_continue(session_id, request_id, assessment=None):
    session = StudySession.objects.get(pk=session_id, profile_id=1)
    validate_current(session, request_id)
    attempt = PracticeAttempt.objects.get(session=session, request_id=request_id)
    attempt.self_assessment = assessment
    attempt.save(update_fields=["self_assessment"])
    advance(session)
