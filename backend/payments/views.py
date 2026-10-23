import re

from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from . import workflow
from .models import Transaction, TransactionStatus
from .serializers import (
    OtpVerifySerializer,
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


class OtpThrottle(SimpleRateThrottle):
    """Limits verification / resend / continue / cancel requests per authenticated user."""

    scope = 'otp'

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


SENSITIVE_PARAMETERS = (
    'card_number', 'card_expiry', 'card_cvv', 'cardholder_name',
    'account_number', 'confirm_account_number', 'account_holder_name', 'wallet_identifier',
)


@method_decorator(sensitive_post_parameters(*SENSITIVE_PARAMETERS), name='dispatch')
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

    @sensitive_variables()
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
        return Transaction.objects.filter(user=self.request.user).select_related('fraud_analysis', 'verification')


# ----------------------------------------------------------------------------- fraud-response actions
def _workflow_error(txn, exc):
    txn = Transaction.objects.get(pk=txn.pk)   # fresh state: the failed action may have changed it
    response = Response(
        {'detail': exc.message, 'code': exc.code, 'verification': workflow.describe_verification(txn)},
        status=exc.http_status,
    )
    if exc.retry_after:
        response['Retry-After'] = str(exc.retry_after)
    return response


class _WorkflowActionView(APIView):
    """Base for the actions on one of the signed-in user's own transactions (others' IDs 404)."""

    throttle_classes = [OtpThrottle]
    action = None

    def get_transaction(self, request, transaction_id):
        return get_object_or_404(Transaction.objects.filter(user=request.user), transaction_id=transaction_id)

    def run(self, request, txn):
        return getattr(workflow, self.action)(txn)

    def post(self, request, transaction_id):
        txn = self.get_transaction(request, transaction_id)
        try:
            txn = self.run(request, txn)
        except workflow.WorkflowError as exc:
            return _workflow_error(txn, exc)
        txn = Transaction.objects.select_related('fraud_analysis', 'verification').get(pk=txn.pk)
        return _outcome(txn, replay=True)


class ContinueView(_WorkflowActionView):
    """High risk: the user chooses to continue, which e-mails a one-time code."""
    action = 'continue_with_otp'


class CancelView(_WorkflowActionView):
    """The user terminates the transaction."""
    action = 'cancel'


class ResendOtpView(_WorkflowActionView):
    action = 'resend_otp'


@method_decorator(sensitive_post_parameters('code'), name='dispatch')
class VerifyOtpView(_WorkflowActionView):
    action = 'verify_otp'

    def run(self, request, txn):
        serializer = OtpVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return workflow.verify_otp(txn, serializer.validated_data['code'])
