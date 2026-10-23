"""Fraud-response (OTP / alert / cancellation) statistics, computed from stored workflow records only.

Nothing here reads or exposes one-time codes (only their hashes exist, and they are not selected), and
nothing is a model-quality metric.
"""
from django.db.models import Count, Q
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from payments.models import (
    AlertStatus, FraudWorkflowEvent, OneTimeCode, OneTimeCodeStatus, PaymentVerification, RiskCategory,
    TransactionStatus, VerificationStatus as V, WorkflowEvent,
)

TRUNC = {'day': TruncDay, 'week': TruncWeek, 'month': TruncMonth}
SERIES_EVENTS = {
    'high_risk_alerts': WorkflowEvent.HIGH_RISK_ALERT_SENT,
    'otp_verified': WorkflowEvent.OTP_VERIFIED,
    'otp_failed': WorkflowEvent.OTP_FAILED,
    'cancelled': WorkflowEvent.USER_CANCELLED,
    'unavailable': WorkflowEvent.VERIFICATION_UNAVAILABLE,
}


def response_statistics(transactions, group_by, buckets):
    pending = Q(transaction__status=TransactionStatus.PENDING)
    verifications = PaymentVerification.objects.filter(transaction_id__in=transactions.values('pk'))
    c = verifications.aggregate(
        low_risk_awaiting_otp=Count('pk', filter=Q(status=V.AWAITING_OTP, risk_category=RiskCategory.LOW) & pending),
        high_risk_awaiting_decision=Count('pk', filter=Q(status=V.AWAITING_USER_DECISION) & pending),
        high_risk_awaiting_otp=Count('pk', filter=Q(status=V.AWAITING_OTP, risk_category=RiskCategory.HIGH) & pending),
        prediction_unavailable=Count('pk', filter=Q(status=V.UNAVAILABLE) | Q(risk_category=RiskCategory.UNAVAILABLE)),
        unavailable_blocked_pending=Count('pk', filter=Q(status=V.UNAVAILABLE) & pending),
        verified=Count('pk', filter=Q(status=V.VERIFIED)),
        cancelled_by_user=Count('pk', filter=Q(status=V.CANCELLED)),
        failed=Count('pk', filter=Q(status=V.FAILED)),
        expired=Count('pk', filter=Q(status=V.EXPIRED)),
        invalidated=Count('pk', filter=Q(status=V.INVALIDATED)),
        low_risk=Count('pk', filter=Q(risk_category=RiskCategory.LOW)),
        high_risk=Count('pk', filter=Q(risk_category=RiskCategory.HIGH)),
        high_risk_continued=Count('pk', filter=Q(risk_category=RiskCategory.HIGH, continued_at__isnull=False)),
        alerts_sent=Count('pk', filter=Q(alert_status=AlertStatus.SENT)),
        alerts_failed=Count('pk', filter=Q(alert_status=AlertStatus.FAILED)),
    )
    codes = OneTimeCode.objects.filter(verification__in=verifications).aggregate(
        issued=Count('pk'), delivered=Count('pk', filter=Q(email_delivered=True)),
        delivery_failed=Count('pk', filter=Q(email_delivered=False)),
        used=Count('pk', filter=Q(status=OneTimeCodeStatus.USED)),
        locked=Count('pk', filter=Q(status=OneTimeCodeStatus.LOCKED)),
        expired=Count('pk', filter=Q(status=OneTimeCodeStatus.EXPIRED)),
    )
    events = FraudWorkflowEvent.objects.filter(transaction_id__in=transactions.values('pk'))
    incorrect = events.filter(event_type=WorkflowEvent.OTP_FAILED).count()

    series_rows = {}
    for key, event_type in SERIES_EVENTS.items():
        rows = (events.filter(event_type=event_type)
                .annotate(bucket=TRUNC[group_by]('transaction__created_at', tzinfo=timezone.get_current_timezone()))
                .values('bucket').annotate(n=Count('pk')))
        for row in rows:
            series_rows.setdefault(row['bucket'].astimezone(timezone.get_current_timezone()).date(), {})[key] = row['n']
    series = [{'period': start.isoformat(), **{k: series_rows.get(start, {}).get(k, 0) for k in SERIES_EVENTS}}
              for start in buckets]
    return {
        'total_transactions': transactions.count(),
        'without_workflow_record': transactions.filter(verification__isnull=True).count(),
        'awaiting': {
            'low_risk_awaiting_otp': c['low_risk_awaiting_otp'],
            'high_risk_awaiting_user_decision': c['high_risk_awaiting_decision'],
            'high_risk_awaiting_otp_after_continue': c['high_risk_awaiting_otp'],
            'prediction_unavailable_blocked': c['unavailable_blocked_pending'],
        },
        'risk_categories': {'low': c['low_risk'], 'high': c['high_risk'], 'unavailable': c['prediction_unavailable']},
        'outcomes': {
            'verified': c['verified'], 'cancelled_by_user': c['cancelled_by_user'], 'failed': c['failed'],
            'expired': c['expired'], 'invalidated_details_changed': c['invalidated'],
        },
        'high_risk': {'alerts_emailed': c['alerts_sent'], 'alert_delivery_failed': c['alerts_failed'],
                      'user_chose_continue': c['high_risk_continued']},
        'otp': {'codes_issued': codes['issued'], 'emails_delivered': codes['delivered'],
                'emails_failed': codes['delivery_failed'], 'codes_used': codes['used'],
                'codes_locked': codes['locked'], 'codes_expired': codes['expired'], 'incorrect_attempts': incorrect},
        'series': series,
        'note': 'Counts come from stored workflow records. A payment whose verification window has passed is closed '
                'when it is next touched or when the expire_verifications command runs, so "awaiting" can briefly '
                'include stale items.',
    }
