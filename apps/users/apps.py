from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save
from django.utils.translation import gettext_lazy as _


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.users"
    label = "users"
    verbose_name = _("Foydalanuvchilar")

    def ready(self):
        from .models import WorkerRole, clear_role_cache

        def _clear(**kwargs):
            clear_role_cache()

        post_save.connect(_clear, sender=WorkerRole, dispatch_uid="users.clear_role_cache.save")
        post_delete.connect(_clear, sender=WorkerRole, dispatch_uid="users.clear_role_cache.delete")
