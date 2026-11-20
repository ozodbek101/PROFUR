from django.conf import settings
from django.middleware.locale import LocaleMiddleware
from django.utils import translation

from .models import clear_role_cache


class CookieLocaleMiddleware(LocaleMiddleware):
    """Interface language comes only from the language cookie (set by the UZ/RU/EN switch).

    Unlike Django's LocaleMiddleware it ignores the browser's Accept-Language, so a
    worker's phone set to Russian does not switch the workshop app on its own:
    Uzbek stays the default until someone picks another language.
    """

    def process_request(self, request):
        lang = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
        if lang not in dict(settings.LANGUAGES):
            lang = settings.LANGUAGE_CODE
        translation.activate(lang)
        request.LANGUAGE_CODE = translation.get_language()


class RoleCacheMiddleware:
    """Drop the per-process trade cache at the start of every request.

    Gunicorn runs several worker processes; a trade added in one of them must be
    visible in the others on their next request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clear_role_cache()
        return self.get_response(request)
