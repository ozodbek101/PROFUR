from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import exceptions
from rest_framework.views import exception_handler as drf_exception_handler

from ..models import ImmutableLedgerError


def exception_handler(exc, context):
    """Translate service-layer Django ValidationErrors into DRF 400 responses."""
    if isinstance(exc, DjangoValidationError):
        detail = exc.message_dict if hasattr(exc, "error_dict") else {"non_field_errors": exc.messages}
        exc = exceptions.ValidationError(detail=detail)
    elif isinstance(exc, ImmutableLedgerError):
        exc = exceptions.PermissionDenied(detail=str(exc))
    return drf_exception_handler(exc, context)
