"""Fraud-response workflow: risk category -> alert / one-time code -> verification -> final status.

Three statuses are kept apart and never conflated:
    Transaction.status          the payment      (PENDING -> COMPLETED / FAILED / CANCELLED)
    FraudAnalysis.status        the model result (EVALUATED / UNAVAILABLE / ERROR)
    PaymentVerification.status  this workflow    (AWAITING_OTP, VERIFIED, ...)

Rules enforced here, on the backend only:
    * LOW risk (probability < threshold)   -> one-time code e-mailed to the account's registered address.
    * HIGH risk (probability >= threshold) -> alert e-mail; the user must choose Continue (then a code) or Cancel.
    * UNAVAILABLE prediction               -> the payment cannot proceed (stays PENDING, can be cancelled).
      It is never treated as low risk and never bypasses verification.
    * The payment is processed only after a code is verified, and only if its details are unchanged.

Every function runs in one DB transaction with the rows locked. Errors are captured inside the
transaction and raised AFTER it commits, so counted attempts and audit events are never rolled back.
"""
import hashlib
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction as db_transaction
from django.db.models import F
from django.utils import timezone

from . import otp
from .fraud.errors import MESSAGES as FRAUD_MESSAGES
from .fraud.presentation import get_analysis
from .models import (
    ACTIVE_VERIFICATION_STATUSES, AlertStatus, FraudWorkflowEvent, OneTimeCode, OneTimeCodeStatus,
    PaymentVerification, RiskCategory, Transaction, TransactionStatus, VerificationStatus, WorkflowEvent,
)
from .notifications import mask_email, send_high_risk_alert, send_otp_email
from .services import process_transaction

logger = logging.getLogger(__name__)
V = VerificationStatus


class WorkflowError(Exception):
    def __init__(self, code, message, http_status=400, retry_after=None):
        super().__init__(code)
        self.code, self.message, self.http_status, self.retry_after = code, message, http_status, retry_after


# ------------------------------------------------------------------------------ helpers
def details_fingerprint(txn):
    """Hash of everything the user could change about the payment. Verification is bound to it."""
    parts = [
        format(Decimal(txn.amount).quantize(Decimal('0.01')), 'f'), txn.currency, txn.recipient_email.strip().lower(),
        txn.recipient_name.strip(), txn.payment_method, txn.card_network, txn.upi_id, txn.upi_provider,
        txn.bank_name, txn.ifsc_code, txn.wallet_provider, txn.wallet_identifier_type, txn.masked_reference,
    ]
    return hashlib.sha256('\x1f'.join(str(p) for p in parts).encode()).hexdigest()


def _event(txn, event_type, detail=''):
    FraudWorkflowEvent.objects.create(transaction=txn, event_type=event_type, detail=detail[:120])


def _max_codes():
    return 1 + settings.OTP_MAX_RESENDS


def _active_code(v):
    return v.codes.filter(status=OneTimeCodeStatus.ACTIVE).first()


def _close(v, txn, verification_status, transaction_status, reason, event_type, now=None):
    """Ends the workflow: invalidates live codes, sets both final statuses, writes the audit events."""
    now = now or timezone.now()
    v.codes.filter(status=OneTimeCodeStatus.ACTIVE).update(status=OneTimeCodeStatus.INVALIDATED, resolved_at=now)
    v.status, v.resolved_at = verification_status, now
    v.save(update_fields=['status', 'resolved_at', 'updated_at'])
    txn.status, txn.failure_reason = transaction_status, reason[:255]
    txn.save(update_fields=['status', 'failure_reason', 'updated_at'])
    _event(txn, event_type, verification_status)
    _event(txn, WorkflowEvent.TRANSACTION_FINALIZED, transaction_status)


def _lock(txn):
    txn = Transaction.objects.select_for_update().select_related('user').get(pk=txn.pk)
    try:
        v = PaymentVerification.objects.select_for_update().get(transaction=txn)
    except PaymentVerification.DoesNotExist:
        raise WorkflowError('no_verification', 'This payment has no verification to act on.', 409)
    return txn, v


def _prelude(txn, v, now, *, guard=True):
    """Common checks. Returns a WorkflowError (state already updated) or None."""
    if txn.status != TransactionStatus.PENDING:
        return WorkflowError('already_final', 'This payment has already been finalised and cannot be changed.', 409)
    if v.status not in ACTIVE_VERIFICATION_STATUSES:
        return WorkflowError('not_active', 'This payment is not waiting for verification.', 409)
    if not guard:
        return None
    if now >= v.expires_at:
        _close(v, txn, V.EXPIRED, TransactionStatus.CANCELLED, 'Verification window expired.',
               WorkflowEvent.VERIFICATION_EXPIRED, now)
        return WorkflowError('verification_expired',
                             'The verification window for this payment has expired and it was cancelled. '
                             'Please make a new payment.', 409)
    if v.details_fingerprint != details_fingerprint(txn):
        _close(v, txn, V.INVALIDATED, TransactionStatus.CANCELLED,
               'Payment details changed after verification started.', WorkflowEvent.DETAILS_CHANGED, now)
        return WorkflowError('details_changed',
                             'The payment details changed, so the earlier verification is no longer valid and '
                             'the payment was cancelled. Please make a new payment.', 409)
    return None


def _limit_error(v, txn, now):
    """Resend / rate limits. Returns a WorkflowError or None."""
    if v.codes.count() >= _max_codes():
        return WorkflowError('resend_limit_reached', 'No more codes can be requested for this payment.', 429)
    last = v.codes.order_by('-created_at', '-id').first()
    if last and settings.OTP_RESEND_COOLDOWN_SECONDS:
        wait = (last.created_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS) - now).total_seconds()
        if wait > 0:
            n = int(wait) + 1
            return WorkflowError('resend_cooldown', f'Please wait {n} seconds before requesting another code.', 429, n)
    recent = OneTimeCode.objects.filter(verification__transaction__user_id=txn.user_id,
                                        created_at__gte=now - timedelta(hours=1)).count()
    if recent >= settings.OTP_MAX_PER_USER_PER_HOUR:
        return WorkflowError('rate_limited', 'Too many codes were requested recently. Please try again later.', 429)
    return None


def _issue_code(v, txn, now):
    """Replaces any live code with a fresh one and e-mails it. True only if the mail backend accepted it."""
    code = otp.generate_code()
    salt = otp.new_salt()
    v.codes.filter(status=OneTimeCodeStatus.ACTIVE).update(status=OneTimeCodeStatus.REPLACED, resolved_at=now)
    record = OneTimeCode.objects.create(
        verification=v, salt=salt, code_hash=otp.hash_code(code, salt, txn.pk, txn.user_id),
        created_at=now, expires_at=now + timedelta(seconds=settings.OTP_EXPIRY_SECONDS))
    _event(txn, WorkflowEvent.OTP_REQUESTED)
    delivered = send_otp_email(txn, code, max(1, round(settings.OTP_EXPIRY_SECONDS / 60)))
    del code
    if delivered:
        record.email_delivered = True
        record.save(update_fields=['email_delivered'])
        _event(txn, WorkflowEvent.OTP_SENT)
    else:  # the user never received it, so it must not be usable
        record.status, record.resolved_at = OneTimeCodeStatus.INVALIDATED, now
        record.save(update_fields=['status', 'resolved_at'])
        _event(txn, WorkflowEvent.OTP_SEND_FAILED)
    return delivered


def _maybe_exhaust(v, txn, now):
    """If no code is live and none can be requested any more, the verification has failed."""
    if v.status == V.AWAITING_OTP and not _active_code(v) and v.codes.count() >= _max_codes():
        _close(v, txn, V.FAILED, TransactionStatus.FAILED,
               'Verification failed: no valid one-time code remained.', WorkflowEvent.VERIFICATION_FAILED, now)
        return True
    return False


EMAIL_FAILED = ('email_failed', "We couldn't send the verification e-mail. No code was sent. Please try again shortly.", 503)


# ------------------------------------------------------------------------------ starting
def start_unavailable(txn, reason):
    now = timezone.now()
    with db_transaction.atomic():
        PaymentVerification.objects.create(
            transaction=txn, status=V.UNAVAILABLE, risk_category=RiskCategory.UNAVAILABLE, reason=reason[:40],
            details_fingerprint=details_fingerprint(txn),
            expires_at=now + timedelta(seconds=settings.VERIFICATION_WINDOW_SECONDS))
        _event(txn, WorkflowEvent.FRAUD_EVALUATED, 'UNAVAILABLE')
        _event(txn, WorkflowEvent.VERIFICATION_UNAVAILABLE, reason)


def start_verification(txn):
    """Called once, right after the fraud analysis. Decides the path from the STORED analysis only."""
    analysis = get_analysis(txn)
    risk = analysis.risk_category if analysis else RiskCategory.UNAVAILABLE
    if risk == RiskCategory.UNAVAILABLE:
        return start_unavailable(txn, (analysis.failure_category if analysis and analysis.failure_category else 'NO_ANALYSIS'))
    now = timezone.now()
    with db_transaction.atomic():
        v = PaymentVerification.objects.create(
            transaction=txn, risk_category=risk, details_fingerprint=details_fingerprint(txn),
            status=V.AWAITING_OTP if risk == RiskCategory.LOW else V.AWAITING_USER_DECISION,
            expires_at=now + timedelta(seconds=settings.VERIFICATION_WINDOW_SECONDS))
        _event(txn, WorkflowEvent.FRAUD_EVALUATED, risk)
        if risk == RiskCategory.LOW:
            err = _limit_error(v, txn, now)
            if err:
                _event(txn, WorkflowEvent.OTP_SEND_FAILED, err.code)
            else:
                _issue_code(v, txn, now)
        else:
            sent = send_high_risk_alert(txn)
            v.alert_status = AlertStatus.SENT if sent else AlertStatus.FAILED
            v.save(update_fields=['alert_status', 'updated_at'])
            _event(txn, WorkflowEvent.HIGH_RISK_ALERT_SENT if sent else WorkflowEvent.HIGH_RISK_ALERT_FAILED)
    return v


# ------------------------------------------------------------------------------ user actions
def continue_with_otp(txn):
    """High risk only: the user explicitly chooses to go on, which sends the one-time code."""
    now, error = timezone.now(), None
    with db_transaction.atomic():
        txn, v = _lock(txn)
        error = _prelude(txn, v, now)
        if not error and not (v.risk_category == RiskCategory.HIGH and v.status == V.AWAITING_USER_DECISION):
            error = WorkflowError('not_awaiting_decision', 'This payment is not waiting for your decision.', 409)
        if not error:
            v.status, v.continued_at = V.AWAITING_OTP, now
            v.save(update_fields=['status', 'continued_at', 'updated_at'])
            _event(txn, WorkflowEvent.USER_CHOSE_CONTINUE)
            error = _limit_error(v, txn, now)
            if error:
                _event(txn, WorkflowEvent.OTP_SEND_FAILED, error.code)
            elif not _issue_code(v, txn, now):
                error = WorkflowError(*EMAIL_FAILED)
    if error:
        raise error
    return txn


def resend_otp(txn):
    now, error = timezone.now(), None
    with db_transaction.atomic():
        txn, v = _lock(txn)
        error = _prelude(txn, v, now)
        if not error and v.status != V.AWAITING_OTP:
            error = WorkflowError('not_awaiting_otp', 'A one-time code cannot be requested for this payment right now.', 409)
        if not error:
            error = _limit_error(v, txn, now)
        if not error and not _issue_code(v, txn, now):
            error = WorkflowError(*EMAIL_FAILED)
    if error:
        raise error
    return txn


def cancel(txn):
    now, error = timezone.now(), None
    with db_transaction.atomic():
        txn, v = _lock(txn)
        error = _prelude(txn, v, now, guard=False)
        if not error:
            _close(v, txn, V.CANCELLED, TransactionStatus.CANCELLED, 'Cancelled by user.', WorkflowEvent.USER_CANCELLED, now)
    if error:
        raise error
    return txn


def verify_otp(txn, code):
    """Checks the submitted code. The payment is processed only if it is correct."""
    now, error = timezone.now(), None
    with db_transaction.atomic():
        txn, v = _lock(txn)
        error = _prelude(txn, v, now)
        if not error and v.status != V.AWAITING_OTP:
            error = WorkflowError('not_awaiting_otp', 'Choose how to proceed before entering a code.', 409)
        record = None if error else _active_code(v)
        if not error and record is None:
            error = WorkflowError('otp_not_active', 'There is no active code. Please request a new one.', 400)
        if not error and now >= record.expires_at:
            record.status, record.resolved_at = OneTimeCodeStatus.EXPIRED, now
            record.save(update_fields=['status', 'resolved_at'])
            _event(txn, WorkflowEvent.OTP_EXPIRED)
            error = WorkflowError('verification_failed', 'No valid code remains for this payment, so it was not completed.', 409) \
                if _maybe_exhaust(v, txn, now) else WorkflowError('otp_expired', 'That code has expired. Please request a new one.', 400)
        if not error:
            OneTimeCode.objects.filter(pk=record.pk).update(attempts=F('attempts') + 1)
            record.refresh_from_db()
            if otp.matches(code, record.code_hash, record.salt, txn.pk, txn.user_id):
                record.status, record.resolved_at = OneTimeCodeStatus.USED, now
                record.save(update_fields=['status', 'resolved_at'])
                v.status, v.resolved_at = V.VERIFIED, now
                v.save(update_fields=['status', 'resolved_at', 'updated_at'])
                _event(txn, WorkflowEvent.OTP_VERIFIED)
                process_transaction(txn)                       # only now does the payment run
                _event(txn, WorkflowEvent.TRANSACTION_FINALIZED, txn.status)
            else:
                left = settings.OTP_MAX_ATTEMPTS - record.attempts
                _event(txn, WorkflowEvent.OTP_FAILED, f'attempt {record.attempts} of {settings.OTP_MAX_ATTEMPTS}')
                if left <= 0:
                    record.status, record.resolved_at = OneTimeCodeStatus.LOCKED, now
                    record.save(update_fields=['status', 'resolved_at'])
                    _event(txn, WorkflowEvent.OTP_LOCKED)
                    error = WorkflowError('verification_failed', 'Too many incorrect codes and no further codes are available, so the payment was not completed.', 409) \
                        if _maybe_exhaust(v, txn, now) else WorkflowError('otp_locked', 'Too many incorrect attempts. That code is now locked: please request a new one.', 400)
                else:
                    error = WorkflowError('otp_incorrect', f'That code is incorrect. {left} attempt(s) left for this code.', 400)
    if error:
        raise error
    return txn


def expire_stale(now=None):
    """Closes workflows whose window has passed (also done lazily on every action). Returns the count."""
    now, closed = now or timezone.now(), 0
    for pk in list(PaymentVerification.objects.filter(status__in=ACTIVE_VERIFICATION_STATUSES, expires_at__lte=now)
                   .values_list('transaction_id', flat=True)):
        with db_transaction.atomic():
            txn, v = _lock(Transaction(pk=pk))
            if txn.status == TransactionStatus.PENDING and v.status in ACTIVE_VERIFICATION_STATUSES:
                _close(v, txn, V.EXPIRED, TransactionStatus.CANCELLED, 'Verification window expired.',
                       WorkflowEvent.VERIFICATION_EXPIRED, now)
                closed += 1
    return closed


# ------------------------------------------------------------------------------ presentation
def describe_verification(txn):
    """API representation. Contains no code, hash or salt, and nothing the client could use to decide risk."""
    try:
        v = txn.verification
    except PaymentVerification.DoesNotExist:
        return {'status': 'NOT_STARTED', 'status_label': 'Not started', 'risk_category': None, 'next_action': 'NONE',
                'can_continue': False, 'can_cancel': False, 'can_verify': False, 'can_resend': False,
                'alert_status': None, 'email_hint': None, 'otp': None, 'expires_at': None,
                'message': 'No fraud verification was started for this payment.'}
    now = timezone.now()
    live = v.status in ACTIVE_VERIFICATION_STATUSES and txn.status == TransactionStatus.PENDING
    codes = list(v.codes.all())
    active = next((c for c in codes if c.status == OneTimeCodeStatus.ACTIVE and c.expires_at > now), None)
    last = codes[-1] if codes else None
    waiting_otp = live and v.status == V.AWAITING_OTP
    resends_left = max(0, _max_codes() - len(codes))
    available_at = None
    if last and settings.OTP_RESEND_COOLDOWN_SECONDS:
        t = last.created_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
        available_at = t if t > now else None
    otp_info = None
    if v.risk_category != RiskCategory.UNAVAILABLE and (waiting_otp or codes):
        otp_info = {
            'length': settings.OTP_LENGTH,
            'expires_at': active.expires_at if active else None,
            'attempts_remaining': max(0, settings.OTP_MAX_ATTEMPTS - active.attempts) if active else None,
            'resends_remaining': resends_left,
            'resend_available_at': available_at,
            'delivery': 'SENT' if active else ('FAILED' if last and not last.email_delivered else ('EXPIRED' if last else 'NOT_SENT')),
        }
    return {
        'status': v.status, 'status_label': v.get_status_display(), 'risk_category': v.risk_category,
        'next_action': {V.AWAITING_USER_DECISION: 'CHOOSE', V.AWAITING_OTP: 'ENTER_OTP', V.UNAVAILABLE: 'CANCEL_ONLY'}.get(v.status, 'NONE') if live else 'NONE',
        'can_continue': live and v.status == V.AWAITING_USER_DECISION,
        'can_cancel': live,
        'can_verify': waiting_otp and active is not None,
        'can_resend': waiting_otp and resends_left > 0,
        'alert_status': v.alert_status if v.risk_category == RiskCategory.HIGH else None,
        'email_hint': mask_email(txn.user.email), 'otp': otp_info, 'expires_at': v.expires_at,
        'message': _message(v, txn, active, last),
    }


def _message(v, txn, active, last):
    s = v.status
    if s == V.AWAITING_USER_DECISION:
        return ('Our fraud model flagged this payment as high risk. This is an automated prediction, not confirmation '
                'of fraud, and the payment has not been completed. Choose whether to continue with e-mail '
                'verification or cancel it.')
    if s == V.AWAITING_OTP:
        if active:
            return 'Enter the one-time code we e-mailed to your registered address to complete this payment.'
        if last and not last.email_delivered:
            return "We couldn't send the verification e-mail. No code was sent. You can request a new one."
        return 'Your last code is no longer valid. Request a new one to continue.'
    if s == V.UNAVAILABLE:
        reason = FRAUD_MESSAGES.get(v.reason, 'Fraud verification could not be performed.')
        return f'Fraud verification is unavailable, so this payment cannot proceed. {reason} You can cancel it.'
    return {
        V.VERIFIED: 'Verified with a one-time code.', V.CANCELLED: 'You cancelled this payment.',
        V.FAILED: 'Verification could not be completed, so the payment was not made.',
        V.EXPIRED: 'The verification window expired and the payment was cancelled.',
        V.INVALIDATED: 'The payment details changed, so the verification was invalidated and the payment cancelled.',
    }[s]
