"""Preliminary rule-based activity indicators.

These are simple, documented heuristics over stored transactions. They flag
activity worth a look; they are NOT fraud detection and never mark a transaction
as fraudulent. They are kept separate from analytics and from the future ML model.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Q

from payments.models import Transaction, TransactionStatus

# --- documented thresholds ---
RAPID_REPEAT_COUNT = 3
RAPID_REPEAT_WINDOW = timedelta(minutes=10)
REPEATED_FAILURE_COUNT = 3
REPEATED_FAILURE_WINDOW = timedelta(hours=1)
LARGE_AMOUNT_MULTIPLIER = Decimal('5')
LARGE_AMOUNT_MIN_BASELINE_SAMPLE = 10
MAX_SCANNED_ROWS = 20000
SAMPLE_SIZE = 25
CENT = Decimal('0.01')


def _flag_windows(rows, count, window):
    """rows: (pk, group_key, created_at) sorted by (group_key, created_at).
    Returns the pks that sit in any run of >= `count` rows of one group inside `window`."""
    flagged = set()
    groups = defaultdict(list)
    for pk, key, created_at in rows:
        groups[key].append((pk, created_at))
    for items in groups.values():
        left = 0
        for right in range(len(items)):
            while items[right][1] - items[left][1] > window:
                left += 1
            if right - left + 1 >= count:
                flagged.update(pk for pk, _ in items[left:right + 1])
    return flagged


def _sample(queryset, flagged_pks):
    rows = (
        queryset.filter(pk__in=flagged_pks)
        .select_related('user')
        .order_by('-created_at', '-id')[:SAMPLE_SIZE]
    )
    return [
        {
            'transaction_id': txn.transaction_id,
            'created_at': txn.created_at,
            'sender_email': txn.user.email,
            'recipient_email': txn.recipient_email,
            'amount': txn.amount,
            'currency': txn.currency,
            'status': txn.status,
            'status_label': txn.get_status_display(),
        }
        for txn in rows
    ]


def _windowed_rule(queryset, *, rule_id, name, description, threshold, count, window, status=None):
    scoped = queryset.filter(status=status) if status else queryset
    rows = list(scoped.order_by('user_id', 'created_at').values_list('pk', 'user_id', 'created_at')[:MAX_SCANNED_ROWS])
    flagged = _flag_windows(rows, count, window)
    return {
        'id': rule_id,
        'name': name,
        'description': description,
        'threshold': threshold,
        'available': True,
        'flagged_count': len(flagged),
        'flagged_transactions': _sample(scoped, flagged),
    }


def _large_amount_rule(queryset):
    base = {
        'id': 'large_amount',
        'name': 'Unusually large amounts',
        'description': (
            f'Payments larger than {LARGE_AMOUNT_MULTIPLIER}x the platform-wide average completed payment '
            '(all time).'
        ),
        'threshold': f'amount > {LARGE_AMOUNT_MULTIPLIER} x average completed amount',
    }
    baseline = Transaction.objects.filter(status=TransactionStatus.COMPLETED).aggregate(
        average=Avg('amount'), sample=Count('pk')
    )
    if baseline['sample'] < LARGE_AMOUNT_MIN_BASELINE_SAMPLE:
        return {
            **base,
            'available': False,
            'reason': f'Needs at least {LARGE_AMOUNT_MIN_BASELINE_SAMPLE} completed transactions to set a baseline '
                      f'(currently {baseline["sample"]}).',
            'flagged_count': None,
            'flagged_transactions': [],
        }
    limit = (Decimal(baseline['average']) * LARGE_AMOUNT_MULTIPLIER).quantize(CENT)
    flagged = queryset.filter(amount__gt=limit)
    return {
        **base,
        'available': True,
        'baseline_average': Decimal(baseline['average']).quantize(CENT),
        'limit_amount': limit,
        'flagged_count': flagged.count(),
        'flagged_transactions': _sample(queryset, flagged.values_list('pk', flat=True)),
    }


def rule_based_indicators(queryset):
    """Evaluates every indicator over the given (already date/filter-scoped) transactions."""
    return [
        _windowed_rule(
            queryset,
            rule_id='rapid_repeat',
            name='Repeated payments in a short time',
            description=f'{RAPID_REPEAT_COUNT} or more payments by the same user within '
                        f'{int(RAPID_REPEAT_WINDOW.total_seconds() // 60)} minutes (any status).',
            threshold=f'>= {RAPID_REPEAT_COUNT} payments in {int(RAPID_REPEAT_WINDOW.total_seconds() // 60)} min',
            count=RAPID_REPEAT_COUNT,
            window=RAPID_REPEAT_WINDOW,
        ),
        _large_amount_rule(queryset),
        _windowed_rule(
            queryset,
            rule_id='repeated_failures',
            name='Repeated failed payments',
            description=f'{REPEATED_FAILURE_COUNT} or more failed payments by the same user within '
                        f'{int(REPEATED_FAILURE_WINDOW.total_seconds() // 3600)} hour. A failed payment is '
                        'not treated as fraud; this only highlights repeated problems.',
            threshold=f'>= {REPEATED_FAILURE_COUNT} failed payments in '
                      f'{int(REPEATED_FAILURE_WINDOW.total_seconds() // 3600)} h',
            count=REPEATED_FAILURE_COUNT,
            window=REPEATED_FAILURE_WINDOW,
            status=TransactionStatus.FAILED,
        ),
    ]


RULES_DISCLAIMER = (
    'Preliminary rule-based monitoring: simple activity indicators, not confirmed fraud and not ML predictions.'
)
