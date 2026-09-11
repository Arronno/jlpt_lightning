import pytest
from django.urls import reverse
from playwright.sync_api import expect

from learning.models import Dataset, Entry, Lesson, PracticeAttempt, ReviewEvent, StudySession
from learning.study import start_session

pytestmark = [pytest.mark.browser, pytest.mark.django_db(transaction=True)]


def test_keyboard_review_retry_and_restart(
    page, live_server, browser_assets, profile, entries, study_filters
):
    session = start_session(profile, study_filters)
    page.goto(live_server.url + reverse("session", args=[session.pk]))
    assert page.locator(".card-answer").is_hidden()
    # Reveal must still work with all network requests blocked.
    page.route("**/*", lambda route: route.abort())
    page.keyboard.press("Space")
    assert page.locator(".card-answer").is_visible()
    page.keyboard.press("3")
    page.locator("#connection-error").wait_for(state="visible")
    assert ReviewEvent.objects.count() == 0
    page.unroute("**/*")
    page.keyboard.press("3")
    expect(page.locator("progress")).to_have_attribute("value", "1")
    assert ReviewEvent.objects.count() == 1
    page.reload()
    assert page.locator("progress").get_attribute("value") == "1"
    assert page.locator(".card-answer").is_hidden()


def test_ime_shortcuts_theme_and_no_voice(
    page, live_server, browser_assets, profile, entries, study_filters
):
    page.add_init_script(
        "Object.defineProperty(window, 'speechSynthesis', {value: {getVoices: () => [], addEventListener: () => {}}})"
    )
    profile.theme = "dark"
    profile.font_size = 48
    profile.save()
    session = start_session(profile, {**study_filters, "mode": "typing"})
    page.goto(live_server.url + reverse("session", args=[session.pk]))
    page.locator("#typing-answer").fill("ねこ")
    page.locator("#typing-answer").dispatch_event("compositionstart")
    page.keyboard.press("Enter")
    assert page.locator(".practice-feedback").count() == 0
    page.locator("#typing-answer").dispatch_event("compositionend")
    page.keyboard.press("Enter")
    page.locator(".practice-feedback").wait_for()
    assert "That’s a match" in page.locator(".practice-feedback").inner_text()
    assert ReviewEvent.objects.count() == 0
    assert page.locator("html").get_attribute("data-theme") == "dark"
    page.goto(live_server.url + reverse("word", args=[entries[0].pk]))
    assert page.locator(".speak").is_hidden()
    assert "No local Japanese voice" in page.locator(".speech-status").inner_text()
    assert page.locator(".jp").evaluate("el => getComputedStyle(el).fontSize") == "48px"


def test_library_htmx_navigation_and_bookmark(page, live_server, browser_assets, profile, entries):
    page.goto(live_server.url + "/library/")
    page.get_by_role("searchbox").fill("cat")
    page.get_by_role("button", name="Find words").click()
    expect(page.locator(".word-row")).to_have_count(1)
    page.get_by_role("button", name="Bookmark word", exact=True).click()
    page.get_by_role("button", name="Remove bookmark", exact=True).wait_for()
    page.get_by_role("link", name="ねこ cat").click()
    page.get_by_label("Note:").fill("Remember this word")
    page.get_by_role("button", name="Save notes & collections").click()
    assert page.get_by_label("Note:").input_value() == "Remember this word"


def test_batch_selection_repeat_and_level_change(
    page, live_server, browser_assets, profile, entries
):
    profile.daily_new = 0
    profile.save()
    Entry.objects.filter(pk=entries[-1].pk).update(batch=2)
    lesson = entries[0].lesson
    dataset = Dataset.objects.create(key="browser-n4", level=4)
    other_lesson = Lesson.objects.create(dataset=dataset, label="26", position=0)
    Entry.objects.create(
        dataset=dataset,
        lesson=other_lesson,
        serial=1,
        position=1,
        batch=3,
        kana="test",
        english="test",
        search="test",
    )
    page.goto(live_server.url + f"/study/?level=5&lesson={lesson.pk}&batch=2")
    expect(page.locator("#id_mode")).to_have_value("flashcards")
    expect(page.locator("#id_lesson")).to_have_value(str(lesson.pk))
    expect(page.locator("#id_batch")).to_have_value("2")
    for _ in range(2):
        page.get_by_role("button", name="Begin session").click()
        expect(page.locator(".selection-label")).to_contain_text("Batch 2")
        expect(page.locator(".card-prompt h1")).to_have_text(entries[-1].kana)
        page.keyboard.press("Space")
        page.keyboard.press("3")
        expect(page.locator(".session-end h1")).to_have_text("A little more familiar.")
        page.get_by_role("link", name="Continue with this selection").click()
        expect(page.locator("#id_batch")).to_have_value("2")
    assert PracticeAttempt.objects.count() == 2
    assert ReviewEvent.objects.count() == 0
    page.locator("#id_level").select_option("4")
    expect(page.locator("#id_lesson")).to_have_value("")
    expect(page.locator("#id_batch option")).to_have_count(1)
    expect(page.locator(f'#id_lesson option[value="{lesson.pk}"]')).to_have_count(0)
    page.locator("#id_lesson").select_option(str(other_lesson.pk))
    expect(page.locator('#id_batch option[value="3"]')).to_have_count(1)
    page.locator("#id_batch").select_option("3")
    page.get_by_role("button", name="Begin session").click()
    expect(page.locator(".selection-label")).to_contain_text("N4 · Lesson 26 · Batch 3")
    assert StudySession.objects.get(active=True).filters["lesson"] == other_lesson.pk
