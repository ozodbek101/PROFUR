from django.conf import settings
from django.middleware.locale import LocaleMiddleware
from django.utils import translation


class CookieLocaleMiddleware(LocaleMiddleware):
    """
    Interface language comes only from the language cookie (set by the language
    menu), defaulting to Uzbek. Unlike Django's LocaleMiddleware it ignores the
    browser's Accept-Language, so a worker's phone set to Russian does not switch
    the workshop app on its own.
    """

    def process_request(self, request):
        lang = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
        if lang not in dict(settings.LANGUAGES):
            lang = settings.LANGUAGE_CODE
        translation.activate(lang)
        request.LANGUAGE_CODE = translation.get_language()


class LabelCacheMiddleware:
    """
    Category and worker-type names are cached per process so list pages do not
    query once per row. Clearing at the start of each request means an edit made
    in one gunicorn worker shows up in every other worker on the next page load.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from apps.inventory.models import clear_category_cache

        from .models import clear_role_cache

        clear_role_cache()
        clear_category_cache()
        return self.get_response(request)
