"""Backend report generation. Every figure comes from database queries; the same
structure powers the in-page preview (JSON) and the CSV download."""
import csv
import io
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django.db.models import Sum

from payments.models import PaymentMethod, Transaction, TransactionStatus

from . import analytics
from .monitoring import RULES_DISCLAIMER, get_confirmed_fraud_status, get_model_status, rule_based_indicators
from .analytics import earliest_date
from .params import describe_range, filter_by_date, resolve_buckets

NOT_AVAILABLE = 'Not available'
FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')

REPORT_TITLES = {
    'transactions': 'Transaction Summary Report',
    'users': 'User Registration Report',
    'activity': 'Transaction Activity Report',
    'fraud-monitoring': 'Fraud Monitoring Report',
}


def _scoped_transactions(params):
    queryset = filter_by_date(Transaction.objects.all(), 'created_at', params)
    if params.get('status'):
        queryset = queryset.filter(status=params['status'])
    if params.get('payment_method'):
        queryset = queryset.filter(payment_method=params['payment_method'])
    return queryset


def _filters(params, *names):
    labels = {
        'status': ('Status', lambda v: dict(TransactionStatus.choices)[v]),
        'payment_method': ('Payment method', lambda v: dict(PaymentMethod.choices)[v]),
        'account_status': ('Account status', lambda v: v.title()),
        'group_by': ('Grouped by', lambda v: v),
    }
    rows = [['Date range', describe_range(params)]]
    for name in names:
        if params.get(name):
            label, fmt = labels[name]
            rows.append([label, fmt(params[name])])
        elif name in ('status', 'payment_method', 'account_status'):
            rows.append([labels[name][0], 'All'])
    return rows


def _section(title, columns, rows):
    return {'title': title, 'columns': columns, 'rows': rows}


def _na(value):
    return NOT_AVAILABLE if value is None else value


def _summary_rows(summary):
    return [
        ['Total transactions', summary['total_transactions']],
        ['Completed', summary['completed']],
        ['Pending', summary['pending']],
        ['Failed', summary['failed']],
        ['Cancelled', summary['cancelled']],
        ['Total amount (completed only)', summary['total_amount']],
        ['Average amount (completed only)', _na(summary['average_amount'])],
    ]


def _method_rows(queryset):
    return [[m['label'], m['count'], m['amount']] for m in analytics.method_distribution(queryset)]


def _status_amount_rows(queryset):
    amounts = {r['status']: r['amount'] for r in queryset.values('status').annotate(amount=Sum('amount'))}
    counts = analytics.status_counts(queryset)
    return [[label, counts[value.lower()], analytics.money(amounts.get(value))] for value, label in TransactionStatus.choices]


def _activity_rows(queryset, group_by, buckets):
    return [[p['period'], p['count'], p['completed'], p['amount']] for p in analytics.activity_series(queryset, group_by, buckets)]


METHOD_COLUMNS = ['Payment method', 'Transactions', 'Completed amount']
STATUS_COLUMNS = ['Status', 'Transactions', 'Amount (all transactions with this status)']


def transaction_summary_report(params):
    queryset = _scoped_transactions(params)
    return {
        'filters': _filters(params, 'status', 'payment_method'),
        'notes': [analytics.MONEY_NOTE + ' Counts include every status.'],
        'sections': [
            _section('Summary', ['Metric', 'Value'], _summary_rows(analytics.transaction_summary(queryset))),
            _section('Breakdown by payment method', METHOD_COLUMNS, _method_rows(queryset)),
            _section('Breakdown by transaction status', STATUS_COLUMNS, _status_amount_rows(queryset)),
        ],
    }


def user_registration_report(params):
    users = analytics.customers()
    if params.get('account_status'):
        users = users.filter(is_active=params['account_status'] == 'active')
    in_period = filter_by_date(users, 'date_joined', params)
    group_by, buckets = resolve_buckets(params, earliest_date(users, 'date_joined'))
    period_stats = analytics.user_summary(in_period)
    return {
        'filters': _filters(params, 'account_status', 'group_by') + [['Grouping used', group_by]],
        'notes': ['Administrator accounts are excluded. No credentials or personal details are included.'],
        'sections': [
            _section('Summary', ['Metric', 'Value'], [
                ['Total registered users (all time)', users.count()],
                ['Registered in selected period', period_stats['total']],
                ['Of those, currently active', period_stats['active']],
                ['Of those, currently inactive', period_stats['inactive']],
            ]),
            _section(f'Registrations by {group_by}', ['Period', 'New users'],
                     [[r['period'], r['count']] for r in analytics.registration_series(in_period, group_by, buckets)]),
            _section('Account status breakdown (registered in period)', ['Account status', 'Users'],
                     [['Active', period_stats['active']], ['Inactive', period_stats['inactive']]]),
        ],
    }


def transaction_activity_report(params):
    queryset = _scoped_transactions(params)
    group_by, buckets = resolve_buckets(params, earliest_date(Transaction.objects.all(), 'created_at'))
    return {
        'filters': _filters(params, 'status', 'payment_method', 'group_by') + [['Grouping used', group_by]],
        'notes': [analytics.MONEY_NOTE + ' Counts include every status.'],
        'sections': [
            _section('Summary', ['Metric', 'Value'], _summary_rows(analytics.transaction_summary(queryset))),
            _section(f'Activity by {group_by}', ['Period', 'Transactions', 'Completed', 'Completed amount'],
                     _activity_rows(queryset, group_by, buckets)),
            _section('Breakdown by payment method', METHOD_COLUMNS, _method_rows(queryset)),
            _section('Breakdown by transaction status', STATUS_COLUMNS, _status_amount_rows(queryset)),
        ],
    }


def fraud_monitoring_report(params):
    queryset = _scoped_transactions(params)
    model, labels = get_model_status(), get_confirmed_fraud_status()
    indicators = rule_based_indicators(queryset)
    money = analytics.money_stats(queryset)
    flagged_rows = [
        [rule['name'], t['transaction_id'], t['created_at'].isoformat(), t['sender_email'],
         t['recipient_email'], t['amount'], t['status_label']]
        for rule in indicators for t in rule['flagged_transactions']
    ]
    return {
        'filters': _filters(params, 'status', 'payment_method'),
        'notes': [
            model['message'] + ' This report contains no ML predictions, fraud probabilities or model metrics.',
            labels['message'],
            RULES_DISCLAIMER,
            analytics.MONEY_NOTE,
        ],
        'sections': [
            _section('Fraud detection status', ['Item', 'Status'], [
                ['XGBoost model', model['status']],
                ['Confirmed fraud labels', NOT_AVAILABLE],
                ['ML predictions / risk scores', NOT_AVAILABLE],
            ]),
            _section('Transaction activity', ['Metric', 'Value'], [
                ['Total transactions', queryset.count()],
                ['Average amount (completed only)', _na(money['average_amount'])],
                ['Minimum amount (completed only)', _na(money['min_amount'])],
                ['Maximum amount (completed only)', _na(money['max_amount'])],
            ]),
            _section('Preliminary rule-based indicators', ['Indicator', 'Rule', 'Flagged transactions'], [
                [r['name'], r['threshold'], _na(r['flagged_count']) if r['available'] else f"{NOT_AVAILABLE} ({r['reason']})"]
                for r in indicators
            ]),
            _section('Flagged transactions (most recent 25 per indicator)',
                     ['Indicator', 'Transaction ID', 'Created (UTC)', 'Sender', 'Recipient', 'Amount', 'Status'], flagged_rows),
            _section('Breakdown by payment method', METHOD_COLUMNS, _method_rows(queryset)),
            _section('Breakdown by transaction status', STATUS_COLUMNS, _status_amount_rows(queryset)),
        ],
    }


BUILDERS = {
    'transactions': transaction_summary_report,
    'users': user_registration_report,
    'activity': transaction_activity_report,
    'fraud-monitoring': fraud_monitoring_report,
}


def build_report(kind, params):
    report = BUILDERS[kind](params)
    return {
        'kind': kind,
        'title': REPORT_TITLES[kind],
        'generated_at': datetime.now(dt_timezone.utc),
        **report,
    }


# ---------- CSV ----------

def safe_cell(value):
    """Neutralises spreadsheet formulas: text starting with = + - @ (or tab/CR) gets a leading quote."""
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        return str(value)
    text = str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def report_to_csv(report):
    out = io.StringIO()
    writer = csv.writer(out)

    def row(*cells):
        writer.writerow([safe_cell(cell) for cell in cells])

    row(f"PaySafe - {report['title']}")
    row('Generated (UTC)', report['generated_at'].strftime('%Y-%m-%d %H:%M:%S'))
    for label, value in report['filters']:
        row(label, value)
    for note in report['notes']:
        row('Note', note)
    for section in report['sections']:
        row()
        row(section['title'])
        row(*section['columns'])
        if section['rows']:
            for cells in section['rows']:
                row(*cells)
        else:
            row('No data for the selected filters')
    return '\ufeff' + out.getvalue()  # BOM so Excel reads UTF-8 correctly


def report_filename(kind, params):
    start, end = params.get('date_from'), params.get('date_to')
    if start and end:
        span = f'{start.isoformat()}_to_{end.isoformat()}'
    elif start:
        span = f'from_{start.isoformat()}'
    elif end:
        span = f'until_{end.isoformat()}'
    else:
        span = 'all-time'
    return f'paysafe-{kind}-report_{span}.csv'
