from django.contrib.auth.backends import ModelBackend


class ApprovedUserBackend(ModelBackend):
    """
    ModelBackend that only authenticates approved users.

    ``user_can_authenticate`` is consulted both at login time and every time a
    session is resolved (``get_user``), so revoking approval locks a worker out
    on their very next request, for HTML views and the API alike.
    """

    def user_can_authenticate(self, user) -> bool:
        if not super().user_can_authenticate(user):
            return False
        return bool(user.is_superuser or getattr(user, "is_approved", False))
