"""Behavioural history features derived from a user's stored transactions.

Everything here is computed from real rows; nothing is invented or randomised.
Only COMPLETED transactions count as history (those are the ones where money
actually moved), and only those that happened strictly before ``as_of``.
"""
from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Max, Min, Q

from ..models import Transaction, TransactionStatus

CENT = Decimal('0.01')


@dataclass(frozen=True)
class HistoryFeatures:
    previous_transaction_count: int
    transactions_last_1h: int
    transactions_last_24h: int
    transactions_last_7d: int
    transactions_last_30d: int
    average_daily_transactions_30d: float
    average_previous_amount: Decimal | None
    max_previous_amount: Decimal | None
    min_previous_amount: Decimal | None
    last_transaction_amount: Decimal | None
    seconds_since_previous_transaction: float | None
    previous_transactions_to_same_recipient: int
    previous_transactions_same_payment_method: int
    distinct_previous_recipients: int
    last_known_latitude: Decimal | None
    last_known_longitude: Decimal | None

    def as_dict(self):
        return asdict(self)


def _quantize(value):
    return None if value is None else Decimal(value).quantize(CENT)


def compute_history_features(*, user, as_of, recipient_email, payment_method, exclude_pk=None):
    history = Transaction.objects.filter(
        user=user, status=TransactionStatus.COMPLETED, timestamp__lt=as_of
    )
    if exclude_pk is not None:
        history = history.exclude(pk=exclude_pk)

    def within(delta):
        return Count('pk', filter=Q(timestamp__gte=as_of - delta))

    stats = history.aggregate(
        total=Count('pk'),
        last_1h=within(timedelta(hours=1)),
        last_24h=within(timedelta(hours=24)),
        last_7d=within(timedelta(days=7)),
        last_30d=within(timedelta(days=30)),
        average=Avg('amount'),
        maximum=Max('amount'),
        minimum=Min('amount'),
        same_recipient=Count('pk', filter=Q(recipient_email__iexact=recipient_email)),
        same_method=Count('pk', filter=Q(payment_method=payment_method)),
        recipients=Count('recipient_email', distinct=True),
    )

    previous = history.order_by('-timestamp', '-id').values('timestamp', 'amount').first()
    last_located = (
        history.filter(latitude__isnull=False, longitude__isnull=False)
        .order_by('-timestamp', '-id')
        .values('latitude', 'longitude')
        .first()
    )

    return HistoryFeatures(
        previous_transaction_count=stats['total'],
        transactions_last_1h=stats['last_1h'],
        transactions_last_24h=stats['last_24h'],
        transactions_last_7d=stats['last_7d'],
        transactions_last_30d=stats['last_30d'],
        average_daily_transactions_30d=round(stats['last_30d'] / 30, 4),
        average_previous_amount=_quantize(stats['average']),
        max_previous_amount=_quantize(stats['maximum']),
        min_previous_amount=_quantize(stats['minimum']),
        last_transaction_amount=_quantize(previous['amount']) if previous else None,
        seconds_since_previous_transaction=(
            (as_of - previous['timestamp']).total_seconds() if previous else None
        ),
        previous_transactions_to_same_recipient=stats['same_recipient'],
        previous_transactions_same_payment_method=stats['same_method'],
        distinct_previous_recipients=stats['recipients'],
        last_known_latitude=last_located['latitude'] if last_located else None,
        last_known_longitude=last_located['longitude'] if last_located else None,
    )
