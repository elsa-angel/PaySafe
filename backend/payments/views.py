import re

from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from .models import Transaction, TransactionStatus
from .serializers import (
    PaymentCreateSerializer,
    TransactionDetailSerializer,
    TransactionListSerializer,
)
from .services import create_payment, find_by_idempotency_key

IDEMPOTENCY_KEY_PATTERN = re.compile(r'^[A-Za-z0-9_-]{8,64}$')
PROCESSING_FAILED_MESSAGE = "We couldn't process this payment. Nothing was charged. Please try again."


class PaymentThrottle(SimpleRateThrottle):
    """Limits payment submissions per authenticated user."""

    scope = 'payment'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': request.user.pk}


class TransactionPagination(PageNumberPagination):
    page_size = 20


def _outcome(txn, *, replay=False):
    """HTTP response for a transaction that has finished processing."""
    if txn.status == TransactionStatus.FAILED:
        return Response(
            {'detail': PROCESSING_FAILED_MESSAGE, 'transaction_id': txn.transaction_id},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    code = status.HTTP_200_OK if replay else status.HTTP_201_CREATED
    return Response(TransactionDetailSerializer(txn).data, status=code)


class PaymentListCreateView(generics.ListCreateAPIView):
    """GET: the signed-in user's transactions (newest first, paginated).
    POST: make a (simulated) payment."""

    pagination_class = TransactionPagination

    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return PaymentCreateSerializer
        return TransactionListSerializer

    def get_throttles(self):
        return [PaymentThrottle()] if self.request.method == 'POST' else []

    def create(self, request, *args, **kwargs):
        key = request.headers.get('Idempotency-Key')
        if key is not None and not IDEMPOTENCY_KEY_PATTERN.match(key):
            return Response(
                {'detail': 'Invalid Idempotency-Key header.'}, status=status.HTTP_400_BAD_REQUEST
            )

        existing = find_by_idempotency_key(request.user, key)
        if existing:
            return _outcome(existing, replay=True)

        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        txn, created = create_payment(
            user=request.user,
            validated_data=serializer.validated_data,
            raw_data=request.data,
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            idempotency_key=key,
        )
        return _outcome(txn, replay=not created)


class TransactionDetailView(generics.RetrieveAPIView):
    serializer_class = TransactionDetailSerializer
    lookup_field = 'transaction_id'

    def get_queryset(self):
        # Scoped to the current user: other users' IDs simply 404.
        return Transaction.objects.filter(user=self.request.user)
