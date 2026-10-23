"""Model-prediction statistics computed from stored FraudAnalysis rows only.

Unavailable and error rows are counted separately and are excluded from every probability and
class statistic. Nothing here is a model-quality metric: that needs confirmed fraud labels.
"""
from django.db.models import Avg, Count, Max, Min, Q
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from payments.fraud.errors import MESSAGES
from payments.models import FraudAnalysis, FraudAnalysisStatus

TRUNC = {'day': TruncDay, 'week': TruncWeek, 'month': TruncMonth}
BINS = 10
EVALUATED = FraudAnalysisStatus.EVALUATED


def _rounded(value):
    return None if value is None else round(float(value), 4)


def prediction_statistics(transactions, group_by, buckets):
    rows = FraudAnalysis.objects.filter(transaction_id__in=transactions.values('pk'))
    counts = rows.aggregate(
        evaluated=Count('pk', filter=Q(status=EVALUATED)),
        unavailable=Count('pk', filter=Q(status=FraudAnalysisStatus.UNAVAILABLE)),
        error=Count('pk', filter=Q(status=FraudAnalysisStatus.ERROR)),
    )
    evaluated = rows.filter(status=EVALUATED)
    cls = evaluated.aggregate(
        flagged=Count('pk', filter=Q(predicted_class=1)), not_flagged=Count('pk', filter=Q(predicted_class=0)),
        average=Avg('fraud_probability'), minimum=Min('fraud_probability'), maximum=Max('fraud_probability'),
    )
    histogram = [0] * BINS
    for value in evaluated.values_list('fraud_probability', flat=True):
        histogram[min(int(value * BINS), BINS - 1)] += 1

    not_evaluated = transactions.filter(fraud_analysis__isnull=True).count()
    by_category = [
        {'category': row['failure_category'], 'message': MESSAGES.get(row['failure_category'], ''), 'count': row['count'],
         'status': row['status']}
        for row in rows.exclude(status=EVALUATED).values('status', 'failure_category')
        .annotate(count=Count('pk')).order_by('-count', 'failure_category')
    ]
    series_rows = {
        row['bucket'].astimezone(timezone.get_current_timezone()).date(): row
        for row in rows.annotate(bucket=TRUNC[group_by]('transaction__created_at', tzinfo=timezone.get_current_timezone()))
        .values('bucket').annotate(
            evaluated=Count('pk', filter=Q(status=EVALUATED)),
            flagged=Count('pk', filter=Q(status=EVALUATED, predicted_class=1)),
            unavailable=Count('pk', filter=~Q(status=EVALUATED)),
        )
    }
    series = []
    for start in buckets:
        row = series_rows.get(start)
        series.append({'period': start.isoformat(), 'evaluated': row['evaluated'] if row else 0,
                       'flagged': row['flagged'] if row else 0, 'unavailable': row['unavailable'] if row else 0})
    n = counts['evaluated']
    return {
        'total_transactions': transactions.count(),
        'evaluated': n,
        'unavailable': counts['unavailable'],
        'error': counts['error'],
        'not_evaluated': not_evaluated,   # no analysis row (e.g. made before the model was integrated)
        'unavailable_by_category': by_category,
        'predicted_classes': {'flagged': cls['flagged'], 'not_flagged': cls['not_flagged'],
                              'flagged_share': (cls['flagged'] / n) if n else None},
        'probability': {'average': _rounded(cls['average']), 'minimum': _rounded(cls['minimum']),
                        'maximum': _rounded(cls['maximum']),
                        'histogram': [{'from': i / BINS, 'to': (i + 1) / BINS, 'count': c} for i, c in enumerate(histogram)],
                        'basis': 'Evaluated transactions only.'},
        'series': series,
    }
