"""Validated query parameters and date-range / time-bucket helpers shared by every admin endpoint."""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from rest_framework import serializers

from payments.models import PaymentMethod, TransactionStatus

GROUP_BY_CHOICES = ('day', 'week', 'month')
MAX_BUCKETS = 400
TRANSACTION_ORDERING = ('created_at', '-created_at', 'amount', '-amount')
USER_ORDERING = ('date_joined', '-date_joined')


class AdminQuerySerializer(serializers.Serializer):
    """Every filter an admin endpoint may accept. Unknown parameters are ignored;
    each view reads only the ones it supports."""

    q = serializers.CharField(required=False, allow_blank=True, max_length=100)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    status = serializers.ChoiceField(required=False, choices=TransactionStatus.choices)
    payment_method = serializers.ChoiceField(required=False, choices=PaymentMethod.choices)
    account_status = serializers.ChoiceField(required=False, choices=[('active', 'active'), ('inactive', 'inactive')])
    group_by = serializers.ChoiceField(required=False, choices=GROUP_BY_CHOICES)
    ordering = serializers.CharField(required=False, max_length=20)
    # Not named "format": DRF reserves ?format= for content negotiation.
    export = serializers.ChoiceField(required=False, choices=['json', 'csv'], default='json')

    def validate(self, attrs):
        start, end = attrs.get('date_from'), attrs.get('date_to')
        if start and end and start > end:
            raise serializers.ValidationError({'date_to': ['End date must not be before the start date.']})
        return attrs


def parse_params(request, ordering_choices=None):
    serializer = AdminQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    params = serializer.validated_data
    if 'ordering' in params and ordering_choices is not None and params['ordering'] not in ordering_choices:
        raise serializers.ValidationError({'ordering': [f'Choose one of: {", ".join(ordering_choices)}.']})
    return params


def _day_start(day):
    return datetime.combine(day, time.min, tzinfo=dt_timezone.utc)


def filter_by_date(queryset, field, params):
    """Inclusive date_from / date_to filtering on a datetime column (UTC days)."""
    if params.get('date_from'):
        queryset = queryset.filter(**{f'{field}__gte': _day_start(params['date_from'])})
    if params.get('date_to'):
        queryset = queryset.filter(**{f'{field}__lt': _day_start(params['date_to'] + timedelta(days=1))})
    return queryset


def describe_range(params):
    start, end = params.get('date_from'), params.get('date_to')
    if start and end:
        return f'{start.isoformat()} to {end.isoformat()}'
    if start:
        return f'from {start.isoformat()}'
    if end:
        return f'up to {end.isoformat()}'
    return 'all time'


def today():
    return datetime.now(dt_timezone.utc).date()


def choose_group_by(params, start, end):
    if params.get('group_by'):
        return params['group_by']
    span = (end - start).days + 1
    return 'day' if span <= 31 else 'week' if span <= 180 else 'month'


def bucket_start(day, group_by):
    if group_by == 'week':
        return day - timedelta(days=day.weekday())
    if group_by == 'month':
        return day.replace(day=1)
    return day


def resolve_buckets(params, earliest):
    """Returns (group_by, [bucket start dates]) covering the selected range with no gaps.

    ``earliest`` is the date of the oldest record, used when no start date is given.
    """
    end = params.get('date_to') or today()
    start = params.get('date_from') or (earliest if earliest and earliest <= end else end - timedelta(days=29))
    group_by = choose_group_by(params, start, end)

    buckets, current = [], bucket_start(start, group_by)
    while current <= end:
        buckets.append(current)
        if len(buckets) > MAX_BUCKETS:
            raise serializers.ValidationError(
                {'group_by': ['This date range has too many periods for that grouping. Choose a coarser grouping.']}
            )
        if group_by == 'day':
            current += timedelta(days=1)
        elif group_by == 'week':
            current += timedelta(days=7)
        else:
            current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return group_by, buckets
