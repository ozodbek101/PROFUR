from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Mebel Ombori"

urlpatterns = [
    # Django's built-in admin is kept for superusers / data fixes; day-to-day
    # administration happens in the app's own /admin-dashboard/ pages.
    path("django-admin/", admin.site.urls),
    path("api/", include("config.api_urls")),
    # POST /i18n/setlang/ with `language` switches the interface language.
    path("i18n/", include("django.conf.urls.i18n")),
    path("", include("apps.users.urls")),
    path("", include("apps.inventory.urls")),
]
