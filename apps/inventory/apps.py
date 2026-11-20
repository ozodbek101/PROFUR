from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save
from django.utils.translation import gettext_lazy as _


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
    label = "inventory"
    verbose_name = _("Ombor")

    def ready(self):
        from .models import Category, clear_category_cache

        def _clear(**kwargs):
            clear_category_cache()

        post_save.connect(_clear, sender=Category, dispatch_uid="inventory.clear_category_cache.save")
        post_delete.connect(_clear, sender=Category, dispatch_uid="inventory.clear_category_cache.delete")
