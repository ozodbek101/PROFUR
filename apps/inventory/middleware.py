from .models import clear_category_cache


class CategoryCacheMiddleware:
    """Drop the per-process category cache at the start of every request (see RoleCacheMiddleware)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clear_category_cache()
        return self.get_response(request)
