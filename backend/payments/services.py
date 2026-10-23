"""Payment creation and (simulated) processing.

Flow implemented here:

    validated input -> create PENDING transaction -> fraud analysis (XGBoost)
                    -> fraud-response workflow (see workflow.py)
                    -> [OTP verified] -> simulated processing -> COMPLETED (or FAILED)

The payment stays PENDING until the user has completed the verification the risk level requires.
Fraud-analysis status, verification status and payment status are three separate records.
"""
import logging
import math
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction as db_transaction

from .device import parse_user_agent
from .fraud.analysis import run_fraud_analysis
from .models import LocationStatus, Transaction, TransactionStatus

logger = logging.getLogger(__name__)

COORD_QUANTUM = Decimal('0.000001')
_BOUNDS = {'latitude': Decimal('90'), 'longitude': Decimal('180')}
MAX_ATTEMPTS = 3


class PaymentProcessingError(Exception):
    """Raised by the processor when a payment cannot be completed."""


def simulate_payment_processing(transaction):
    """Stand-in for a payment gateway. No money moves; it always succeeds.

    A real gateway integration would replace this function and raise
    PaymentProcessingError on declines/timeouts.
    """
    return True


def _coordinate(raw, axis):
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or abs(value) > _BOUNDS[axis]:
        return None
    return value.quantize(COORD_QUANTUM)


def parse_location(data):
    """Leniently extract (latitude, longitude, status) from request data.

    Location is optional: anything missing, malformed or out of range yields
    null coordinates and never blocks the payment.
    """
    if not isinstance(data, dict):
        return None, None, LocationStatus.UNAVAILABLE
    latitude = _coordinate(data.get('latitude'), 'latitude')
    longitude = _coordinate(data.get('longitude'), 'longitude')
    if latitude is not None and longitude is not None:
        return latitude, longitude, LocationStatus.PROVIDED
    reported = str(data.get('location_status') or '').upper()
    status = LocationStatus.DENIED if reported == LocationStatus.DENIED else LocationStatus.UNAVAILABLE
    return None, None, status


def find_by_idempotency_key(user, key):
    if not key:
        return None
    return Transaction.objects.filter(user=user, idempotency_key=key).first()


def create_payment(*, user, validated_data, raw_data, user_agent, idempotency_key=None):
    """Creates the PENDING transaction, runs the fraud analysis and starts the OTP workflow.
    The payment is processed later, only after verification (see workflow.verify_otp).

    Returns ``(transaction, created)``; ``created`` is False when an earlier
    request with the same idempotency key already produced this transaction.
    """
    latitude, longitude, location_status = parse_location(raw_data)
    device_type, browser, operating_system = parse_user_agent(user_agent)

    txn = None
    for _ in range(MAX_ATTEMPTS):
        try:
            with db_transaction.atomic():
                txn = Transaction.objects.create(
                    user=user,  # always the authenticated user, never client-supplied
                    idempotency_key=idempotency_key,
                    latitude=latitude,
                    longitude=longitude,
                    location_status=location_status,
                    device_type=device_type,
                    browser=browser,
                    operating_system=operating_system,
                    status=TransactionStatus.PENDING,
                    **validated_data,
                )
            break
        except IntegrityError:
            existing = find_by_idempotency_key(user, idempotency_key)
            if existing:
                return existing, False
            # Otherwise a (very unlikely) transaction_id collision: retry with a new ID.
    if txn is None:
        raise PaymentProcessingError('Could not create the transaction.')

    run_fraud_analysis(txn)  # never raises; records a prediction or an explicit "unavailable"/"error"
    _start_workflow(txn)     # never raises; the payment stays PENDING until the user has verified it
    return txn, True


def _start_workflow(txn):
    from .workflow import start_verification, start_unavailable

    try:
        start_verification(txn)
    except Exception:
        logger.exception('Fraud-response workflow could not start for %s', txn.transaction_id)
        try:
            start_unavailable(txn, reason='WORKFLOW_ERROR')
        except Exception:
            logger.exception('Could not record the workflow failure for %s', txn.transaction_id)


def process_transaction(txn):
    """Runs the (simulated) payment and records the final status. Called ONLY after the required
    verification has succeeded; never leaves a transaction in PENDING."""
    try:
        simulate_payment_processing(txn)
        txn.status = TransactionStatus.COMPLETED
        txn.failure_reason = ''
    except PaymentProcessingError as exc:
        txn.status = TransactionStatus.FAILED
        txn.failure_reason = str(exc)[:255]
    except Exception:
        logger.exception('Unexpected error while processing %s', txn.transaction_id)
        txn.status = TransactionStatus.FAILED
        txn.failure_reason = 'Unexpected processing error.'
    txn.save(update_fields=['status', 'failure_reason', 'updated_at'])
    return txn
