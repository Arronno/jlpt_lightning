from .models import Profile


def preferences(request):
    return {"prefs": Profile.local()}
