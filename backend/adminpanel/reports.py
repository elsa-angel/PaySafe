"""Backend report generation. Every figure comes from database queries; the same
structure powers the in-page preview (JSON) and the CSV download."""
import csv
import io
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from payments.models import PaymentMethod, Transaction, TransactionStatus

from . import analytics
from .monitoring import (
    RULES_DISCLAIMER, get_confirmed_fraud_status, get_model_status, prediction_statistics, response_statistics,
    rule_based_indicators,
)
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
    rows = [['Date range', describe_range(params)], ['Time zone', timezone.get_current_timezone_name()]]
    for name in names:
        if params.get(name):
            label, fmt = labels[name]
            rows.append([label, fmt(params[name])])
        elif name in ('status', 'payment_method', 'account_status'):
            rows.append([labels[name][0], 'All'])
    return rows


def _empty_message(count, what):
    """Shown (and written to the CSV) when the selected period holds no records; every figure is then a real zero."""
    return None if count else f'No {what} match the selected period and filters. All figures below are zero.'


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
        'empty_message': _empty_message(queryset.exists(), 'transactions'),
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
        'empty_message': _empty_message(in_period.exists(), 'registrations'),
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
        'empty_message': _empty_message(queryset.exists(), 'transactions'),
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
    group_by, buckets = resolve_buckets(params, earliest_date(Transaction.objects.all(), 'created_at'))
    model, labels = get_model_status(), get_confirmed_fraud_status()
    pred = prediction_statistics(queryset, group_by, buckets)
    probability = pred['probability']
    resp = response_statistics(queryset, group_by, buckets)
    indicators = rule_based_indicators(queryset, baseline_scope=filter_by_date(Transaction.objects.all(), 'created_at', params))
    money = analytics.money_stats(queryset)
    flagged_rows = [
        [rule['name'], t['transaction_id'], t['created_at'].isoformat(), t['sender_email'],
         t['recipient_email'], t['amount'], t['status_label']]
        for rule in indicators for t in rule['flagged_transactions']
    ]
    return {
        'filters': _filters(params, 'status', 'payment_method'),
        'empty_message': _empty_message(queryset.exists(), 'transactions'),
        'notes': [
            model['message'] + ' Model predictions below come from stored results; unavailable predictions are excluded '
            'from class and probability figures. No model-quality metrics are reported.',
            labels['message'],
            RULES_DISCLAIMER,
            analytics.MONEY_NOTE,
        ],
        'sections': [
            _section('Fraud detection status', ['Item', 'Status'], [
                ['XGBoost model', model['status']],
                ['Model version', _na(model['version'])],
                ['Evaluable payment methods', ', '.join(model['supported_payment_methods'])],
                ['Confirmed fraud labels', NOT_AVAILABLE],
            ]),
            _section('XGBoost predictions (stored results)', ['Metric', 'Value'], [
                ['Transactions in selection', pred['total_transactions']],
                ['Evaluated by the model', pred['evaluated']],
                ['Prediction unavailable', pred['unavailable']],
                ['Analysis errors', pred['error']],
                ['Not evaluated (no analysis recorded)', pred['not_evaluated']],
                ['Flagged by model (evaluated only)', pred['predicted_classes']['flagged']],
                ['Not flagged by model (evaluated only)', pred['predicted_classes']['not_flagged']],
                ['Average model score (evaluated only)', _na(probability['average'])],
                ['Minimum model score (evaluated only)', _na(probability['minimum'])],
                ['Maximum model score (evaluated only)', _na(probability['maximum'])],
            ]),
            _section('Fraud response (stored workflow records)', ['Metric', 'Value'], [
                ['Low-risk payments awaiting a one-time code', resp['awaiting']['low_risk_awaiting_otp']],
                ['High-risk payments awaiting the user\'s decision', resp['awaiting']['high_risk_awaiting_user_decision']],
                ['High-risk payments awaiting a code after "continue"', resp['awaiting']['high_risk_awaiting_otp_after_continue']],
                ['Payments blocked: prediction unavailable', resp['awaiting']['prediction_unavailable_blocked']],
                ['Verified with a one-time code', resp['outcomes']['verified']],
                ['Cancelled by the user', resp['outcomes']['cancelled_by_user']],
                ['Verification failed (limits reached)', resp['outcomes']['failed']],
                ['Verification expired', resp['outcomes']['expired']],
                ['Invalidated (details changed)', resp['outcomes']['invalidated_details_changed']],
                ['High-risk alerts e-mailed', resp['high_risk']['alerts_emailed']],
                ['High-risk alert e-mails that failed', resp['high_risk']['alert_delivery_failed']],
                ['One-time code e-mails failed', resp['otp']['emails_failed']],
                ['Incorrect code attempts', resp['otp']['incorrect_attempts']],
            ]),
            _section('Unavailable / error reasons', ['Outcome', 'Reason', 'Transactions'],
                     [[r['status'], r['message'], r['count']] for r in pred['unavailable_by_category']]),
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
        **{'empty_message': None, **report},
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
    if report.get('empty_message'):
        row('Note', report['empty_message'])
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
