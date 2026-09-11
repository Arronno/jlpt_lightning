from django.urls import path

from learning import views

urlpatterns = [
    path("", views.today, name="today"),
    path("lessons/", views.lessons, name="lessons"),
    path("library/", views.library, name="library"),
    path("word/<int:pk>/", views.word, name="word"),
    path("word/<int:pk>/bookmark/", views.bookmark, name="bookmark"),
    path("word/<int:pk>/unsuspend/", views.unsuspend, name="unsuspend"),
    path("collections/", views.collections, name="collections"),
    path("study/", views.study_setup, name="study"),
    path("study/options/", views.study_options, name="study_options"),
    path("study/<uuid:pk>/", views.session_page, name="session"),
    path("study/<uuid:pk>/action/", views.session_action, name="session_action"),
    path("settings/", views.settings_page, name="settings"),
    path("data/", views.data_page, name="data"),
    path("data/import/<uuid:pk>/", views.import_preview, name="import_preview"),
    path("data/export/<str:kind>/", views.export_data, name="export"),
    path("data/backup/", views.backup, name="backup"),
]
