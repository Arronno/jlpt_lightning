import io

import pytest
from django.conf import settings
from openpyxl import Workbook

from learning.catalog import FIELDS, apply_import, preview_import
from learning.models import Annotation, CardState, Entry, Profile


def workbook(rows, header=FIELDS):
    book = Workbook()
    sheet = book.active
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


@pytest.mark.django_db
def test_import_preview_changes_preserve_identity():
    first = preview_import(
        workbook([(1, "1", "はし", "bridge", "", ""), (2, "1", "はし", "chopsticks", "", "")]),
        "n1.xlsx",
        1,
        "n1",
    )
    assert len(first.payload["added"]) == 2
    assert Entry.objects.count() == 0
    apply_import(first.pk, backup=False)
    original = Entry.objects.get(serial=1)
    profile = Profile.local()
    CardState.objects.create(
        profile=profile, entry=original, direction="ja_en", state={"keep": True}
    )
    Annotation.objects.create(profile=profile, entry=original, note="Keep this note")
    second = preview_import(
        workbook([(1, "1", "はし", "a bridge", "Example", "Translation")]), "n1.xlsx", 1, "n1"
    )
    assert len(second.payload["changed"]) == 1
    assert second.payload["missing"] == [2]
    apply_import(second.pk, backup=False)
    original.refresh_from_db()
    assert original.english == "a bridge"
    assert Entry.objects.count() == 2
    assert original.cards.get().state == {"keep": True}
    assert original.annotations.get().note == "Keep this note"
    third = preview_import(
        workbook([(1, "1", "はし", "a bridge", "Example", "Translation")]), "n1.xlsx", 1, "n1"
    )
    assert third.payload["unchanged"] == 1
    apply_import(third.pk, backup=False)
    apply_import(third.pk, backup=False)
    assert Entry.objects.count() == 2


@pytest.mark.django_db
def test_validation_and_stale_preview():
    batch = preview_import(
        workbook(
            [
                (1, "1", "", "cat", "", ""),
                (2, "1", "ねこ", "cat", "", ""),
                (2, "1", "いぬ", "dog", "", ""),
            ]
        ),
        "bad.xlsx",
        5,
        "bad",
    )
    assert len(batch.errors) == 2
    with pytest.raises(ValueError):
        apply_import(batch.pk, backup=False)
    raw = workbook([(1, "1", "ねこ", "cat", "", "")])
    first = preview_import(raw, "a.xlsx", 5, "good")
    stale = preview_import(raw, "b.xlsx", 5, "good")
    apply_import(first.pk, backup=False)
    with pytest.raises(ValueError, match="out of date"):
        apply_import(stale.pk, backup=False)


@pytest.mark.corpus
@pytest.mark.django_db
def test_supplied_corpus():
    for level, count in [(5, 856), (4, 866), (3, 2124), (2, 1890)]:
        path = settings.BASE_DIR / "data" / "vocabulary" / f"JLPT_N{level}_Vocabulary_Fixed.xlsx"
        batch = preview_import(path.read_bytes(), path.name, level, f"jlpt-n{level}")
        assert not batch.errors
        assert len(batch.payload["rows"]) == count
        apply_import(batch.pk, backup=False)
        for row in batch.payload["rows"]:
            entry = Entry.objects.get(dataset__level=level, serial=row["serial"])
            assert entry.kana == row["kana"]
            assert entry.english == row["english"]
            assert entry.example == row["example"]
            assert entry.example_eng == row["example_eng"]
            assert entry.batch == (entry.position - 1) // 20 + 1
        same = preview_import(path.read_bytes(), path.name, level, f"jlpt-n{level}")
        assert same.payload["unchanged"] == count
        assert not same.payload["changed"]
    assert Entry.objects.count() == 5736
