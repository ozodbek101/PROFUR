from .models import clear_role_cache


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
