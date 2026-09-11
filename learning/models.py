import unicodedata
import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def normalize(value):
    return unicodedata.normalize("NFKC", value).strip()


class Profile(models.Model):
    name = models.CharField(max_length=80, default="Learner")
    theme = models.CharField(
        max_length=10,
        choices=[("system", "System"), ("light", "Light"), ("dark", "Dark")],
        default="system",
    )
    font_size = models.PositiveSmallIntegerField(
        default=40, validators=[MinValueValidator(24), MaxValueValidator(64)]
    )
    examples = models.BooleanField(default=True)
    daily_new = models.PositiveSmallIntegerField(default=10, validators=[MaxValueValidator(100)])
    session_size = models.PositiveSmallIntegerField(
        default=20, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    direction = models.CharField(
        max_length=10,
        choices=[
            ("ja_en", "Japanese → English"),
            ("en_ja", "English → Japanese"),
            ("both", "Both directions"),
        ],
        default="ja_en",
    )
    ordering = models.CharField(
        max_length=10,
        choices=[("source", "Source order"), ("shuffle", "Shuffle new cards")],
        default="source",
    )

    @classmethod
    def local(cls):
        return cls.objects.get_or_create(pk=1)[0]


class Dataset(models.Model):
    key = models.SlugField(max_length=100, unique=True)
    level = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    notes = models.TextField(blank=True)
    revision = models.PositiveIntegerField(default=0)


class Lesson(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.PROTECT)
    label = models.CharField(max_length=100)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["dataset__level", "position"]
        constraints = [
            models.UniqueConstraint(fields=["dataset", "label"], name="unique_source_lesson")
        ]


class Entry(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.PROTECT)
    serial = models.PositiveIntegerField()
    lesson = models.ForeignKey(Lesson, on_delete=models.PROTECT)
    position = models.PositiveIntegerField()
    batch = models.PositiveIntegerField(default=1)
    kana = models.TextField()
    english = models.TextField()
    example = models.TextField(blank=True)
    example_eng = models.TextField(blank=True)
    search = models.TextField()

    class Meta:
        ordering = ["-dataset__level", "lesson__position", "position"]
        constraints = [
            models.UniqueConstraint(fields=["dataset", "serial"], name="unique_source_serial")
        ]
        indexes = [models.Index(fields=["lesson", "batch", "position"])]


class Annotation(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="annotations")
    note = models.TextField(blank=True)
    tags = models.CharField(max_length=500, blank=True)
    bookmarked = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "entry"], name="unique_annotation")
        ]


class Collection(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    entries = models.ManyToManyField(Entry, related_name="collections", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "name"], name="unique_collection_name")
        ]


class Preset(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    filters = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "name"], name="unique_preset_name")
        ]


class ImportBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset_key = models.SlugField(max_length=100)
    level = models.PositiveSmallIntegerField()
    filename = models.CharField(max_length=255)
    digest = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    errors = models.JSONField(default=list)
    base_revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True)


class CardState(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    entry = models.ForeignKey(Entry, on_delete=models.PROTECT, related_name="cards")
    direction = models.CharField(
        max_length=5, choices=[("ja_en", "Japanese → English"), ("en_ja", "English → Japanese")]
    )
    state = models.JSONField(default=dict)
    due = models.DateTimeField(null=True)
    introduced_at = models.DateTimeField(null=True)
    suspended = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "entry", "direction"], name="unique_learner_card"
            )
        ]
        indexes = [models.Index(fields=["profile", "suspended", "due"])]


class StudySession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    mode = models.CharField(max_length=10, default="cards")
    filters = models.JSONField(default=dict)
    queue = models.JSONField(default=list)
    cursor = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ReviewEvent(models.Model):
    request_id = models.UUIDField(unique=True)
    card = models.ForeignKey(CardState, on_delete=models.PROTECT)
    session = models.ForeignKey(StudySession, on_delete=models.PROTECT)
    rating = models.PositiveSmallIntegerField()
    reviewed_at = models.DateTimeField()
    before = models.JSONField()
    after = models.JSONField()
    scheduler = models.JSONField()
    scheduler_version = models.CharField(max_length=40)
    session_cursor = models.PositiveIntegerField()
    undone = models.BooleanField(default=False)


class PracticeAttempt(models.Model):
    request_id = models.UUIDField(unique=True)
    session = models.ForeignKey(StudySession, on_delete=models.CASCADE)
    entry = models.ForeignKey(Entry, on_delete=models.PROTECT)
    answer = models.TextField()
    correct = models.BooleanField()
    self_assessment = models.BooleanField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
