from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q, Sum
from django.http import Http404, HttpResponse
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from payments.models import Transaction, TransactionStatus

from . import analytics, reports
from .monitoring import RULES_DISCLAIMER, get_confirmed_fraud_status, get_model_status, rule_based_indicators
from .analytics import earliest_date
from .params import (
    TRANSACTION_ORDERING, USER_ORDERING, describe_range, filter_by_date, parse_params, resolve_buckets,
)
from .permissions import IsSuperuser
from .serializers import (
    AdminTransactionDetailSerializer, AdminTransactionListSerializer,
    AdminUserDetailSerializer, AdminUserListSerializer,
)

User = get_user_model()
CURRENCY = 'INR'
RECENT_LIMIT = 8


class AdminPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class AdminAPIView(APIView):
    permission_classes = [IsSuperuser]


def _earliest(*dates):
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def _period(params, group_by=None):
    return {
        'date_from': params.get('date_from'),
        'date_to': params.get('date_to'),
        'label': describe_range(params),
        'group_by': group_by,
    }


# ---------------------------------------------------------------- overview

class OverviewView(AdminAPIView):
    def get(self, request):
        params = parse_params(request)
        transactions = filter_by_date(Transaction.objects.all(), 'created_at', params)
        users = analytics.customers()
        new_users = filter_by_date(users, 'date_joined', params)
        group_by, buckets = resolve_buckets(
            params,
            _earliest(earliest_date(Transaction.objects.all(), 'created_at'), earliest_date(users, 'date_joined')),
        )
        user_stats = analytics.user_summary(users)
        recent = Transaction.objects.select_related('user').order_by('-created_at', '-id')[:RECENT_LIMIT]
        return Response({
            'period': _period(params, group_by),
            'currency': CURRENCY,
            'money_note': analytics.MONEY_NOTE,
            'users': {
                'total': user_stats['total'],
                'active': user_stats['active'],
                'inactive': user_stats['inactive'],
                'new_in_period': new_users.count(),
            },
            'transactions': analytics.transaction_summary(transactions),
            'charts': {
                'activity': analytics.activity_series(transactions, group_by, buckets),
                'status_distribution': analytics.status_distribution(transactions),
                'method_distribution': analytics.method_distribution(transactions),
                'registrations': analytics.registration_series(new_users, group_by, buckets),
            },
            'recent_transactions': AdminTransactionListSerializer(recent, many=True).data,
        })


# --------------------------------------------------------- fraud statistics

class FraudStatisticsView(AdminAPIView):
    """Activity analytics + preliminary rule-based indicators. The ML model and
    confirmed-fraud sections report their (unavailable) status and nothing else."""

    def get(self, request):
        params = parse_params(request)
        transactions = filter_by_date(Transaction.objects.all(), 'created_at', params)
        group_by, buckets = resolve_buckets(params, earliest_date(Transaction.objects.all(), 'created_at'))
        return Response({
            'period': _period(params, group_by),
            'currency': CURRENCY,
            'money_note': analytics.MONEY_NOTE,
            'ml_model': get_model_status(),
            'confirmed_fraud': get_confirmed_fraud_status(),
            'activity': {
                'summary': analytics.transaction_summary(transactions),
                'series': analytics.activity_series(transactions, group_by, buckets),
                'method_distribution': analytics.method_distribution(transactions),
                'status_distribution': analytics.status_distribution(transactions),
            },
            'rule_based': {
                'disclaimer': RULES_DISCLAIMER,
                'indicators': rule_based_indicators(transactions),
            },
        })


# ------------------------------------------------------------------- users

def _annotated_customers():
    completed = Q(transactions__status=TransactionStatus.COMPLETED)
    return analytics.customers().annotate(
        transaction_count=Count('transactions'),
        completed_transaction_count=Count('transactions', filter=completed),
        total_completed_amount=Sum('transactions__amount', filter=completed),
        last_transaction_at=Max('transactions__created_at'),
    )


class AdminUserListView(generics.ListAPIView):
    permission_classes = [IsSuperuser]
    serializer_class = AdminUserListSerializer
    pagination_class = AdminPagination

    def get_queryset(self):
        params = parse_params(self.request, USER_ORDERING)
        queryset = filter_by_date(_annotated_customers(), 'date_joined', params)
        if params.get('q'):
            term = params['q'].strip()
            queryset = queryset.filter(
                Q(first_name__icontains=term) | Q(email__icontains=term) | Q(username__icontains=term)
            )
        if params.get('account_status'):
            queryset = queryset.filter(is_active=params['account_status'] == 'active')
        return queryset.order_by(params.get('ordering', '-date_joined'), '-id')


class AdminUserDetailView(generics.RetrieveAPIView):
    permission_classes = [IsSuperuser]
    serializer_class = AdminUserDetailSerializer

    def get_queryset(self):
        return _annotated_customers()


class AdminUserStatusView(AdminAPIView):
    """Activate or deactivate an ordinary user. Never touches superusers; nothing is deleted."""

    def patch(self, request, pk):
        target = generics.get_object_or_404(User, pk=pk)
        if target.is_superuser or target.pk == request.user.pk:
            raise PermissionDenied('Administrator accounts cannot be changed here.')

        value = request.data.get('is_active') if isinstance(request.data, dict) else None
        if not isinstance(value, bool):
            return Response({'is_active': ['Provide true or false.']}, status=status.HTTP_400_BAD_REQUEST)

        if target.is_active != value:
            target.is_active = value
            target.save(update_fields=['is_active'])
            LogEntry.objects.log_actions(
                user_id=request.user.pk, queryset=[target], action_flag=CHANGE,
                change_message=f'PaySafe admin dashboard: account {"activated" if value else "deactivated"}.',
            )
        return Response(AdminUserDetailSerializer(generics.get_object_or_404(_annotated_customers(), pk=pk)).data)


# ------------------------------------------------------------ transactions

def filtered_transactions(params, base=None):
    queryset = (base if base is not None else Transaction.objects.all()).select_related('user')
    queryset = filter_by_date(queryset, 'created_at', params)
    if params.get('status'):
        queryset = queryset.filter(status=params['status'])
    if params.get('payment_method'):
        queryset = queryset.filter(payment_method=params['payment_method'])
    if params.get('q'):
        term = params['q'].strip()
        queryset = queryset.filter(
            Q(transaction_id__icontains=term)
            | Q(recipient_name__icontains=term) | Q(recipient_email__icontains=term)
            | Q(user__email__icontains=term) | Q(user__first_name__icontains=term)
        )
    ordering = params.get('ordering', '-created_at')
    return queryset.order_by(ordering, '-id')


class AdminTransactionListView(generics.ListAPIView):
    permission_classes = [IsSuperuser]
    serializer_class = AdminTransactionListSerializer
    pagination_class = AdminPagination

    def get_queryset(self):
        return filtered_transactions(parse_params(self.request, TRANSACTION_ORDERING))


class AdminTransactionDetailView(generics.RetrieveAPIView):
    permission_classes = [IsSuperuser]
    serializer_class = AdminTransactionDetailSerializer
    lookup_field = 'transaction_id'
    queryset = Transaction.objects.select_related('user')


class AdminUserTransactionsView(AdminTransactionListView):
    def get_queryset(self):
        user = generics.get_object_or_404(analytics.customers(), pk=self.kwargs['pk'])
        params = parse_params(self.request, TRANSACTION_ORDERING)
        return filtered_transactions(params, Transaction.objects.filter(user=user))


# ----------------------------------------------------------------- reports

class ReportView(AdminAPIView):
    def get(self, request, kind):
        if kind not in reports.BUILDERS:
            raise Http404
        params = parse_params(request)
        report = reports.build_report(kind, params)
        if params['export'] == 'csv':
            response = HttpResponse(reports.report_to_csv(report), content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{reports.report_filename(kind, params)}"'
            response['Cache-Control'] = 'no-store'
            return response
        return Response(report)
