"""E-mails sent by the fraud-response workflow, via Django's e-mail framework.

Messages go ONLY to the authenticated account's registered address (``user.email``), never to an
address typed into the payment form. `send_*` return True only if the configured mail backend
accepted the message; on any failure they return False and log the exception TYPE only (never
credentials or message bodies).
"""
import logging
import smtplib

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email

logger = logging.getLogger(__name__)


def _amount(txn):
    return f'{txn.currency} {txn.amount:,.2f}'


def _summary(txn):
    return (f'  Amount:       {_amount(txn)}\n'
            f'  To:           {txn.recipient_name}\n'
            f'  Method:       {txn.get_payment_method_display()}\n'
            f'  Reference:    {txn.transaction_id}\n')


def _failure_kind(exc):
    """Coarse, safe label for a delivery failure. Only this label is logged: never the exception text,
    which can contain server replies, addresses or credentials."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return 'smtp_authentication'
    if isinstance(exc, (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused)):
        return 'address_rejected'
    if isinstance(exc, TimeoutError):          # socket.timeout is TimeoutError on Python 3.10+
        return 'timeout'
    if isinstance(exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, ConnectionError, OSError)):
        return 'connection'
    if isinstance(exc, smtplib.SMTPException):
        return 'smtp_error'
    return 'other'


def _deliver(user, subject, body, kind):
    address = (user.email or '').strip()
    if not address:
        logger.error('Cannot send %s e-mail: the account has no registered e-mail address', kind)
        return False
    try:
        validate_email(address)
    except ValidationError:
        logger.error('Cannot send %s e-mail: the registered e-mail address is not valid', kind)
        return False
    try:
        sent = EmailMessage(subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[address]).send(
            fail_silently=False)
    except Exception as exc:  # smtplib / socket / backend errors
        logger.error('Could not send %s e-mail (%s: %s)', kind, type(exc).__name__, _failure_kind(exc))
        return False
    return sent == 1


def mask_email(address):
    local, _, domain = (address or '').partition('@')
    if not domain:
        return ''
    return f'{local[:1]}{"*" * max(len(local) - 1, 2)}@{domain}'


def send_otp_email(txn, code, valid_minutes):
    name = txn.user.first_name or 'there'
    body = (
        f'Hello {name},\n\n'
        f'Your PaySafe verification code is: {code}\n\n'
        f'It expires in {valid_minutes} minutes and can be used once, for this payment only:\n\n'
        f'{_summary(txn)}\n'
        'Enter it in PaySafe to complete the payment. PaySafe staff will never ask you for this code.\n'
        'If you did not start this payment, do not use the code: open PaySafe and cancel the payment.\n'
    )
    return _deliver(txn.user, 'Your PaySafe verification code', body, 'verification code')


def send_high_risk_alert(txn):
    name = txn.user.first_name or 'there'
    body = (
        f'Hello {name},\n\n'
        'PaySafe\'s fraud-detection model flagged the payment below as HIGH RISK:\n\n'
        f'{_summary(txn)}\n'
        'This is an automated prediction. It does not mean fraud has occurred, and the payment has NOT been '
        'completed. It is on hold until you decide.\n\n'
        'Open PaySafe and choose one of:\n'
        '  - Continue: we will e-mail you a one-time code to verify the payment.\n'
        '  - Cancel the transaction.\n\n'
        'If you did not start this payment, cancel it and consider changing your password.\n'
    )
    return _deliver(txn.user, 'PaySafe: a payment was flagged as high risk', body, 'high-risk alert')
