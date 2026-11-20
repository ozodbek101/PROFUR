from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
    label = "inventory"
    verbose_name = _("Ombor")

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from .models import Category, clear_category_cache

        post_save.connect(clear_category_cache, sender=Category, dispatch_uid="category_cache_save")
        post_delete.connect(clear_category_cache, sender=Category, dispatch_uid="category_cache_delete")
