import io

import pytest
from django.db.models import Count
from openpyxl import Workbook

from learning.catalog import FIELDS, apply_import, preview_import
from learning.models import Entry


def source(serials):
    book = Workbook()
    book.active.append(FIELDS)
    for serial in serials:
        book.active.append([serial, "Extra", f"word{serial}", f"meaning{serial}", "", ""])
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


@pytest.mark.django_db
def test_partial_reimport_keeps_batches_stable_and_small():
    first = preview_import(source(range(1, 22)), "n1.xlsx", 1, "n1")
    apply_import(first.pk, backup=False)
    original = dict(Entry.objects.values_list("serial", "position"))
    # Missing rows must not be assigned the same positions as new incoming rows.
    second = preview_import(source([*range(2, 22), 22]), "n1.xlsx", 1, "n1")
    apply_import(second.pk, backup=False)
    assert Entry.objects.count() == 22
    for serial, position in original.items():
        assert Entry.objects.get(serial=serial).position == position
    assert all(
        group["size"] <= 20
        for group in Entry.objects.values("lesson", "batch").annotate(size=Count("pk"))
    )
