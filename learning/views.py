import csv
import io
import json
import logging
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import OperationalError, transaction
from django.db.models import Count, F
from django.http import FileResponse, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import catalog, study
from .forms import AnnotationForm, CollectionForm, ImportForm, PreferencesForm, StudyForm
from .models import (
    Annotation,
    CardState,
    Collection,
    Dataset,
    Entry,
    ImportBatch,
    Lesson,
    PracticeAttempt,
    Preset,
    Profile,
    ReviewEvent,
    StudySession,
)
from .storage import backup_database, learning_export


def today(request):
    profile = Profile.local()
    now = timezone.now()
    active = StudySession.objects.filter(profile=profile, active=True).first()
    reviews = ReviewEvent.objects.filter(card__profile=profile, undone=False)
    activity = []
    for days in range(6, -1, -1):
        date = timezone.localdate(now) - timezone.timedelta(days=days)
        count = reviews.filter(reviewed_at__date=date).count()
        activity.append(
            {
                "day": date.strftime("%a"),
                "count": count,
                "height": min(10, count // 3 + (1 if count else 0)),
            }
        )
    return render(
        request,
        "today.html",
        {
            "active": active,
            "levels": catalog.catalog_summary(),
            "due": CardState.objects.filter(profile=profile, suspended=False, due__lte=now).count(),
            "remaining": study.daily_remaining(profile, now),
            "introduced": CardState.objects.filter(profile=profile, introduced_at__isnull=False)
            .values("entry")
            .distinct()
            .count(),
            "reviewed": reviews.filter(reviewed_at__gte=study.day_start(now)).count(),
            "activity": activity,
            "total": Entry.objects.count(),
            "presets": Preset.objects.filter(profile=profile),
        },
    )


def lessons(request):
    selected = request.GET.get("level", "5")
    if selected not in {"1", "2", "3", "4", "5"}:
        return HttpResponseBadRequest("Invalid JLPT level")
    level = int(selected)
    groups = []
    for lesson in catalog.catalog_summary()[5 - level]["lessons"]:
        batches = list(
            Entry.objects.filter(lesson_id=lesson["id"])
            .values("batch")
            .annotate(count=Count("pk"))
            .order_by("batch")
        )
        groups.append({**lesson, "batches": batches})
    return render(
        request,
        "lessons.html",
        {"level": level, "groups": groups, "levels": catalog.catalog_summary()},
    )


def library(request):
    filters = {}
    for name in ["level", "lesson", "batch", "collection"]:
        if request.GET.get(name, "").isdigit():
            filters[name] = int(request.GET[name])
    filters.update(
        q=request.GET.get("q", "")[:200],
        tag=request.GET.get("tag", "")[:100],
        bookmarked=request.GET.get("bookmarked") == "1",
    )
    entries = catalog.filter_entries(filters)
    page = Paginator(entries, 40).get_page(request.GET.get("page"))
    bookmarked = set(
        Annotation.objects.filter(
            profile_id=1, bookmarked=True, entry__in=page.object_list
        ).values_list("entry_id", flat=True)
    )
    params = request.GET.copy()
    params.pop("page", None)
    context = {
        "page": page,
        "filters": filters,
        "query": params.urlencode(),
        "bookmarked": bookmarked,
        "collections": Collection.objects.filter(profile_id=1),
    }
    template = (
        "partials/library_results.html" if request.headers.get("HX-Request") else "library.html"
    )
    return render(request, template, context)


def word(request, pk):
    entry = get_object_or_404(Entry.objects.select_related("dataset", "lesson"), pk=pk)
    note, _ = Annotation.objects.get_or_create(profile=Profile.local(), entry=entry)
    form = AnnotationForm(
        request.POST or None,
        instance=note,
        initial={"collections": entry.collections.filter(profile_id=1)},
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            entry.collections.set(form.cleaned_data["collections"])
        messages.success(request, "Your notes and collections are saved.")
        return redirect("word", pk=pk)
    return render(
        request,
        "word.html",
        {"entry": entry, "form": form, "states": entry.cards.filter(profile_id=1)},
    )


@require_POST
def bookmark(request, pk):
    entry = get_object_or_404(Entry, pk=pk)
    with transaction.atomic():
        note, _ = Annotation.objects.get_or_create(profile=Profile.local(), entry=entry)
        note.bookmarked = not note.bookmarked
        note.save(update_fields=["bookmarked"])
    if request.headers.get("HX-Request"):
        return render(
            request, "partials/bookmark.html", {"entry": entry, "is_bookmarked": note.bookmarked}
        )
    return redirect("word", pk=pk)


@require_POST
def unsuspend(request, pk):
    CardState.objects.filter(entry_id=pk, profile_id=1).update(
        suspended=False, revision=F("revision") + 1
    )
    messages.success(request, "Cards returned to your review queue.")
    return redirect("word", pk=pk)


def collections(request):
    profile = Profile.local()
    form = CollectionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        Collection.objects.get_or_create(profile=profile, name=form.cleaned_data["name"])
        return redirect("collections")
    return render(
        request,
        "collections.html",
        {
            "form": form,
            "collections": Collection.objects.filter(profile=profile).annotate(
                count=Count("entries")
            ),
        },
    )


def study_setup(request):
    profile = Profile.local()
    initial = {
        "mode": "flashcards",
        "direction": profile.direction,
        "ordering": profile.ordering,
        "session_size": profile.session_size,
    }
    if request.GET.get("preset", "").isdigit():
        initial.update(get_object_or_404(Preset, pk=request.GET["preset"], profile=profile).filters)
    for field in [
        "mode",
        "direction",
        "ordering",
        "session_size",
        "level",
        "lesson",
        "batch",
        "collection",
        "q",
        "tag",
        "bookmarked",
    ]:
        if field in request.GET:
            initial[field] = request.GET[field]
    form = StudyForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        filters = form.filters()
        if form.cleaned_data["preset_name"]:
            Preset.objects.update_or_create(
                profile=profile,
                name=form.cleaned_data["preset_name"],
                defaults={"filters": filters},
            )
        try:
            session = study.start_session(
                profile, filters, request_id=form.cleaned_data["session_token"]
            )
            return redirect("session", pk=session.pk)
        except study.StudyConflict as exc:
            form.add_error(None, str(exc))
    return render(
        request,
        "study_setup.html",
        {
            "form": form,
            "presets": Preset.objects.filter(profile=profile),
            "active": StudySession.objects.filter(profile=profile, active=True).first(),
            "remaining": study.daily_remaining(profile, timezone.now()),
        },
    )


def study_options(request):
    selected = request.GET.dict()
    if selected.get("changed") == "level":
        selected.update(lesson="", batch="")
    elif selected.get("changed") == "lesson":
        selected["batch"] = ""
    return render(request, "partials/study_scope.html", {"form": StudyForm(initial=selected)})


def selection_label(filters):
    parts = []
    lesson = (
        Lesson.objects.select_related("dataset").filter(pk=filters.get("lesson")).first()
        if filters.get("lesson")
        else None
    )
    if lesson:
        parts.extend(
            [
                f"N{lesson.dataset.level}",
                "Extra vocabulary" if lesson.label == "Extra" else f"Lesson {lesson.label}",
            ]
        )
    else:
        parts.append(f"N{filters['level']}" if filters.get("level") else "All levels")
        parts.append("All lessons")
    parts.append(f"Batch {filters['batch']}" if filters.get("batch") else "All batches")
    return " · ".join(parts)


def session_context(session):
    filters_query = {
        key: value for key, value in session.filters.items() if value is not None and value != ""
    }
    filters_query["bookmarked"] = "1" if filters_query.get("bookmarked") else ""
    context = {
        "session": session,
        "total_cards": len(session.queue),
        "completed": session.cursor,
        "latest_review": ReviewEvent.objects.filter(session=session, undone=False)
        .order_by("-pk")
        .first(),
        "selection": selection_label(session.filters),
        "same_selection_query": urlencode(filters_query),
        "practice_selection_query": urlencode({**filters_query, "mode": "typing"}),
    }
    if session.cursor >= len(session.queue) or not session.active:
        context["finished"] = True
        context["replaced"] = bool(session.queue) and session.cursor < len(session.queue)
        context["resume_session"] = (
            StudySession.objects.filter(profile_id=1, active=True).exclude(pk=session.pk).first()
        )
        context["matching_count"] = catalog.filter_entries(session.filters).count()
        context["remaining"] = study.daily_remaining(Profile.local(), timezone.now())
        context["saved_reviews"] = ReviewEvent.objects.filter(session=session, undone=False).count()
        context["practice_correct"] = PracticeAttempt.objects.filter(
            session=session, correct=True
        ).count()
        return context
    item = session.queue[session.cursor]
    entry = Entry.objects.select_related("dataset", "lesson").get(pk=item["entry"])
    annotation = Annotation.objects.filter(profile_id=1, entry=entry).first()
    context.update(item=item, entry=entry, annotation=annotation, number=session.cursor + 1)
    if session.mode == "cards":
        state = CardState.objects.get(pk=item["card"])
        context.update(state=state, intervals=study.rating_intervals(state))
    elif session.mode == "flashcards":
        context.update(
            state={"direction": item["direction"]},
            intervals=[
                {"value": value, "name": name, "help": help_text}
                for value, name, help_text in [
                    (1, "Again", "Didn't recall"),
                    (2, "Hard", "Recalled with difficulty"),
                    (3, "Good", "Recalled correctly"),
                    (4, "Easy", "Effortless recall"),
                ]
            ],
        )
    else:
        context["attempt"] = PracticeAttempt.objects.filter(
            session=session, request_id=item["request_id"]
        ).first()
    return context


def session_page(request, pk):
    session = get_object_or_404(StudySession, pk=pk, profile_id=1)
    template = (
        "partials/study_panel.html" if request.headers.get("HX-Request") else "study_session.html"
    )
    return render(request, template, session_context(session))


@require_POST
def session_action(request, pk):
    get_object_or_404(StudySession, pk=pk, profile_id=1)
    try:
        action = request.POST.get("action")
        if action == "undo":
            study.undo_review(pk)
        else:
            request_id = UUID(request.POST.get("request_id", ""))
            if action in ("grade", "practice_grade"):
                if request.POST.get("revealed") != "yes":
                    raise ValueError("Reveal the answer before grading.")
                if action == "practice_grade":
                    study.practice_grade(pk, request_id, int(request.POST["rating"]))
                else:
                    study.grade(
                        pk, request_id, int(request.POST["revision"]), int(request.POST["rating"])
                    )
            elif action in ("skip", "suspend"):
                study.skip(pk, request_id, suspend=action == "suspend")
            elif action == "answer":
                study.practice_answer(pk, request_id, request.POST.get("answer", ""))
            elif action == "continue":
                assessment = request.POST.get("assessment")
                study.practice_continue(pk, request_id, {"yes": True, "no": False}.get(assessment))
            else:
                raise ValueError("Unknown study action.")
    except (ValueError, KeyError, PracticeAttempt.DoesNotExist, OperationalError) as exc:
        if isinstance(exc, OperationalError):
            logging.getLogger(__name__).exception("Study write failed")
            error = (
                "Your answer was not confirmed. Retry the same action; it will only be saved once."
            )
        else:
            error = str(exc)
        session = StudySession.objects.get(pk=pk)
        template = (
            "partials/study_panel.html"
            if request.headers.get("HX-Request")
            else "study_session.html"
        )
        return render(request, template, {**session_context(session), "error": error})
    if request.headers.get("HX-Request"):
        return session_page(request, pk)
    return redirect("session", pk=pk)


def settings_page(request):
    form = PreferencesForm(request.POST or None, instance=Profile.local())
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Preferences saved. New sessions will use these defaults.")
        return redirect("settings")
    return render(request, "settings.html", {"form": form})


def data_page(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        workbook = form.cleaned_data["workbook"]
        try:
            batch = catalog.preview_import(
                workbook.read(),
                workbook.name,
                form.cleaned_data["level"],
                form.cleaned_data["dataset_key"],
            )
            return redirect("import_preview", pk=batch.pk)
        except Exception as exc:
            logging.getLogger(__name__).exception("Workbook preview failed")
            form.add_error(
                "workbook",
                str(exc)
                if isinstance(exc, ValueError)
                else "The workbook could not be read. Check its format and try again.",
            )
    backups = sorted((settings.DATA_DIR / "backups").glob("*.sqlite3"), reverse=True)
    return render(
        request,
        "data.html",
        {
            "form": form,
            "datasets": Dataset.objects.all(),
            "backups": [b.name for b in backups[:10]],
            "data_dir": settings.DATA_DIR,
        },
    )


def import_preview(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    if request.method == "POST":
        if request.POST.get("confirm") != "yes":
            messages.error(request, "Confirm that you reviewed these changes.")
        else:
            try:
                catalog.apply_import(pk)
                messages.success(
                    request, "Import complete. Your review history and notes were preserved."
                )
                return redirect("data")
            except Exception as exc:
                logging.getLogger(__name__).exception("Import failed")
                messages.error(
                    request,
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "Import could not be completed. Check the local log; no partial changes were saved.",
                )
    return render(request, "import_preview.html", {"batch": batch})


def export_data(request, kind):
    if kind == "json":
        content = json.dumps(learning_export(), ensure_ascii=False, indent=2)
        response = HttpResponse(content, content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="jlpt-learning-v1.json"'
        return response
    if kind == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(
            ["dataset", "level", "serial", "lesson", "kana", "english", "example", "example_eng"]
        )
        for entry in Entry.objects.select_related("dataset", "lesson"):
            values = [
                entry.dataset.key,
                entry.dataset.level,
                entry.serial,
                entry.lesson.label,
                entry.kana,
                entry.english,
                entry.example,
                entry.example_eng,
            ]
            writer.writerow(
                [
                    "'" + v
                    if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r"))
                    else v
                    for v in values
                ]
            )
        response = HttpResponse(
            "\ufeff" + stream.getvalue(), content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = 'attachment; filename="jlpt-vocabulary.csv"'
        return response
    return HttpResponseBadRequest("Unknown export format")


@require_POST
def backup(request):
    try:
        path = backup_database()
        return FileResponse(path.open("rb"), as_attachment=True, filename=path.name)
    except Exception:
        messages.error(request, "Backup failed. Check the data folder and local log.")
        return redirect("data")
