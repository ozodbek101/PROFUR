from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.users"
    label = "users"
    verbose_name = _("Foydalanuvchilar")

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from .models import WorkerRole, clear_role_cache

        post_save.connect(clear_role_cache, sender=WorkerRole, dispatch_uid="users.worker_role_saved")
        post_delete.connect(clear_role_cache, sender=WorkerRole, dispatch_uid="users.worker_role_deleted")
