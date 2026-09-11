import uuid

from django import forms
from django.db.models import Count
from django.urls import reverse

from .models import Annotation, Collection, Entry, Lesson, Profile


class PreferencesForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = [
            "name",
            "theme",
            "font_size",
            "examples",
            "daily_new",
            "session_size",
            "direction",
            "ordering",
        ]
        labels = {
            "font_size": "Japanese text size (24–64 px)",
            "examples": "Show example sentences",
            "daily_new": "New words per day",
            "session_size": "Cards per session",
        }


class LessonChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        label = "Extra vocabulary" if obj.label == "Extra" else f"Lesson {obj.label}"
        return f"N{obj.dataset.level} · {label}"


class StudyForm(forms.Form):
    session_token = forms.UUIDField(required=False, widget=forms.HiddenInput, initial=uuid.uuid4)
    mode = forms.ChoiceField(
        choices=[
            ("flashcards", "Flashcards — all selected words, repeat anytime"),
            ("cards", "Scheduled reviews — due cards and daily new words"),
            ("typing", "Typing practice"),
            ("quiz", "Quick quiz"),
        ]
    )
    level = forms.TypedChoiceField(
        coerce=int,
        empty_value=None,
        required=False,
        choices=[("", "All levels"), *[(i, f"N{i}") for i in range(5, 0, -1)]],
    )
    lesson = LessonChoiceField(
        required=False, queryset=Lesson.objects.none(), empty_label="All lessons"
    )
    batch = forms.TypedChoiceField(
        required=False, coerce=int, empty_value=None, choices=[("", "All batches")]
    )
    collection = forms.ModelChoiceField(required=False, queryset=Collection.objects.none())
    q = forms.CharField(required=False, max_length=200, label="Search words or meanings")
    tag = forms.CharField(required=False, max_length=100)
    bookmarked = forms.BooleanField(required=False, label="Bookmarked words only")
    direction = forms.ChoiceField(choices=Profile._meta.get_field("direction").choices)
    ordering = forms.ChoiceField(choices=Profile._meta.get_field("ordering").choices)
    session_size = forms.IntegerField(min_value=1, max_value=100)
    preset_name = forms.CharField(
        required=False, max_length=100, label="Save these choices as a preset (optional)"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["collection"].queryset = Collection.objects.filter(profile_id=1)
        selected = self.data if self.is_bound else self.initial
        lessons = Lesson.objects.select_related("dataset").order_by(
            "-dataset__level", "position", "pk"
        )
        if str(selected.get("level", "")) in {"1", "2", "3", "4", "5"}:
            lessons = lessons.filter(dataset__level=int(selected["level"]))
        self.fields["lesson"].queryset = lessons
        lesson_id = selected.get("lesson")
        lesson = lessons.filter(pk=int(lesson_id)).first() if str(lesson_id).isdigit() else None
        if lesson:
            batches = (
                Entry.objects.filter(lesson=lesson)
                .values("batch")
                .annotate(count=Count("pk"))
                .order_by("batch")
            )
            self.fields["batch"].choices = [
                ("", "All batches"),
                *[
                    (row["batch"], f"Batch {row['batch']} · {row['count']} words")
                    for row in batches
                ],
            ]
        else:
            self.fields["batch"].help_text = "Choose a lesson to select one of its batches."
        for name in ("level", "lesson"):
            self.fields[name].widget.attrs.update(
                {
                    "hx-get": reverse("study_options"),
                    "hx-trigger": "change",
                    "hx-include": "closest form",
                    "hx-target": "#study-scope",
                    "hx-swap": "outerHTML",
                    "hx-sync": "closest form:replace",
                    "hx-vals": '{"changed":"' + name + '"}',
                }
            )

    @property
    def other_fields(self):
        return [
            field
            for field in self.visible_fields()
            if field.name not in {"level", "lesson", "batch"}
        ]

    def filters(self):
        result = dict(self.cleaned_data)
        result.pop("preset_name", None)
        result.pop("session_token", None)
        for name in ("collection", "lesson"):
            if result[name]:
                result[name] = result[name].pk
        return result


class ImportForm(forms.Form):
    workbook = forms.FileField()
    level = forms.TypedChoiceField(coerce=int, choices=[(i, f"N{i}") for i in range(5, 0, -1)])
    dataset_key = forms.SlugField(
        max_length=100, help_text="Reuse this key when updating a workbook, e.g. jlpt-n5."
    )

    def clean_workbook(self):
        value = self.cleaned_data["workbook"]
        if not value.name.lower().endswith(".xlsx") or value.size > 10 * 1024 * 1024:
            raise forms.ValidationError("Choose an .xlsx workbook under 10 MB.")
        return value


class AnnotationForm(forms.ModelForm):
    collections = forms.ModelMultipleChoiceField(
        queryset=Collection.objects.none(), required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = Annotation
        fields = ["note", "tags", "bookmarked"]
        widgets = {"note": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["collections"].queryset = Collection.objects.filter(profile_id=1)


class CollectionForm(forms.Form):
    name = forms.CharField(max_length=100)
