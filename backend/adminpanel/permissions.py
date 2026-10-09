from rest_framework.permissions import BasePermission


class IsSuperuser(BasePermission):
    """Only active Django superusers. Checked on the server for every request;
    nothing the client sends (or stores) can grant it."""

    message = 'Administrator access is required.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_superuser)
