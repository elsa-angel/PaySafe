from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

User = get_user_model()


class EmailOrUsernameBackend(ModelBackend):
    """Authenticates by email (or username) using Django's own users and password hashing.

    PaySafe accounts use their email as the username, but accounts made with
    ``createsuperuser`` have a separate username. Matching on email as well lets
    every account, including superusers, sign in through the same login form.
    No credentials are hard-coded here, and ambiguous identifiers are rejected.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = (username or kwargs.get(User.USERNAME_FIELD) or '').strip()
        if not identifier or password is None:
            return None

        user = self._resolve_user(identifier)
        if user is None:
            User().set_password(password)  # keeps timing similar for unknown accounts
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    @staticmethod
    def _resolve_user(identifier):
        by_username = list(User.objects.filter(username__iexact=identifier)[:2])
        if len(by_username) == 1:
            return by_username[0]
        if by_username:  # several usernames differing only by case
            return None
        by_email = list(User.objects.filter(Q(email__iexact=identifier))[:2])
        return by_email[0] if len(by_email) == 1 else None
