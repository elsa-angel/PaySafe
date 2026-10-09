"""Database-backed analytics shared by the overview, fraud statistics and reports.

Conventions (shown to admins in the UI):
  * Counts include every transaction in the selected period.
  * Monetary figures (totals, averages, min/max) include COMPLETED transactions
    only, because those are the ones where the simulated payment went through.
"""
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek

from payments.models import PaymentMethod, Transaction, TransactionStatus

User = get_user_model()
CENT = Decimal('0.01')
MONEY_BASIS = TransactionStatus.COMPLETED
MONEY_NOTE = 'Amounts include completed transactions only.'
TRUNC = {'day': TruncDay, 'week': TruncWeek, 'month': TruncMonth}


def customers():
    """Registered PaySafe users: everyone except administrator (superuser) accounts."""
    return User.objects.filter(is_superuser=False)


def money(value):
    return Decimal(value or 0).quantize(CENT)


def money_or_none(value):
    return None if value is None else Decimal(value).quantize(CENT)


def earliest_date(queryset, field):
    first = queryset.aggregate(first=Min(field))['first']
    return first.date() if first else None


def status_counts(queryset):
    stats = queryset.aggregate(
        total=Count('pk'),
        **{status.lower(): Count('pk', filter=Q(status=status)) for status in TransactionStatus.values},
    )
    return stats


def money_stats(queryset):
    stats = queryset.filter(status=MONEY_BASIS).aggregate(
        total=Sum('amount'), average=Avg('amount'), minimum=Min('amount'), maximum=Max('amount'),
    )
    return {
        'total_amount': money(stats['total']),
        'average_amount': money_or_none(stats['average']),
        'min_amount': money_or_none(stats['minimum']),
        'max_amount': money_or_none(stats['maximum']),
    }


def transaction_summary(queryset):
    counts = status_counts(queryset)
    return {
        'total_transactions': counts['total'],
        'completed': counts['completed'],
        'pending': counts['pending'],
        'failed': counts['failed'],
        'cancelled': counts['cancelled'],
        **money_stats(queryset),
        'amount_basis': MONEY_BASIS,
    }


def status_distribution(queryset):
    counts = status_counts(queryset)
    return [
        {'value': value, 'label': label, 'count': counts[value.lower()]}
        for value, label in TransactionStatus.choices
    ]


def method_distribution(queryset):
    rows = {
        row['payment_method']: row
        for row in queryset.values('payment_method').annotate(
            count=Count('pk'),
            amount=Sum('amount', filter=Q(status=MONEY_BASIS)),
        )
    }
    result = []
    for value, label in PaymentMethod.choices:
        row = rows.get(value)
        result.append({
            'value': value,
            'label': label,
            'count': row['count'] if row else 0,
            'amount': money(row['amount'] if row else 0),
        })
    return result


def _bucket_key(value):
    return value.astimezone(dt_timezone.utc).date()


def activity_series(queryset, group_by, buckets):
    rows = {
        _bucket_key(row['bucket']): row
        for row in queryset.annotate(bucket=TRUNC[group_by]('created_at', tzinfo=dt_timezone.utc))
        .values('bucket')
        .annotate(
            count=Count('pk'),
            completed=Count('pk', filter=Q(status=MONEY_BASIS)),
            amount=Sum('amount', filter=Q(status=MONEY_BASIS)),
        )
    }
    series = []
    for start in buckets:
        row = rows.get(start)
        series.append({
            'period': start.isoformat(),
            'count': row['count'] if row else 0,
            'completed': row['completed'] if row else 0,
            'amount': money(row['amount'] if row else 0),
        })
    return series


def registration_series(user_queryset, group_by, buckets):
    rows = {
        _bucket_key(row['bucket']): row['count']
        for row in user_queryset.annotate(bucket=TRUNC[group_by]('date_joined', tzinfo=dt_timezone.utc))
        .values('bucket')
        .annotate(count=Count('pk'))
    }
    return [{'period': start.isoformat(), 'count': rows.get(start, 0)} for start in buckets]


def user_summary(user_queryset):
    stats = user_queryset.aggregate(
        total=Count('pk'),
        active=Count('pk', filter=Q(is_active=True)),
        inactive=Count('pk', filter=Q(is_active=False)),
    )
    return stats
