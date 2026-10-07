from django.contrib.auth import authenticate, login, logout
from django.db import IntegrityError
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from .serializers import LoginSerializer, SignupSerializer, UserSerializer

INVALID_CREDENTIALS = 'Invalid email or password.'


def enforce_csrf(request):
    """DRF only checks CSRF for already-authenticated sessions; check it for
    the anonymous signup/login endpoints too (raises PermissionDenied)."""
    SessionAuthentication().enforce_csrf(request)


class IpRateThrottle(SimpleRateThrottle):
    """Throttle anonymous auth attempts per client IP address."""

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class LoginThrottle(IpRateThrottle):
    scope = 'login'


class SignupThrottle(IpRateThrottle):
    scope = 'signup'


@ensure_csrf_cookie
@api_view(['GET'])
@permission_classes([AllowAny])
def csrf(request):
    """Sets the csrftoken cookie so the SPA can send it on mutating requests."""
    return Response({'csrfToken': get_token(request)})


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([SignupThrottle])
def signup(request):
    enforce_csrf(request)
    serializer = SignupSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        user = serializer.save()
    except IntegrityError:
        # Lost a race with a concurrent signup for the same email.
        return Response(
            {'email': ['An account with this email already exists.']},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login_view(request):
    enforce_csrf(request)
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = authenticate(
        request,
        username=serializer.validated_data['email'],
        password=serializer.validated_data['password'],
    )
    if user is None:
        # Same message for unknown email, wrong password and disabled account.
        return Response({'detail': INVALID_CREDENTIALS}, status=status.HTTP_401_UNAUTHORIZED)
    login(request, user)
    return Response(UserSerializer(user).data)


@api_view(['POST'])
def logout_view(request):
    logout(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
def current_user(request):
    return Response(UserSerializer(request.user).data)
