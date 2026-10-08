"""Payment creation and (simulated) processing.

Flow implemented here:

    validated input -> create PENDING transaction -> simulated processing
                    -> COMPLETED (or FAILED)

FUTURE INSERTION POINT (XGBoost): between "create PENDING transaction" and
"simulated processing", call ``payments.fraud.prepare_fraud_features(txn)``,
map it with the model's FeatureMapper, score it, then decide whether to
continue, request OTP, alert or cancel. None of that exists yet.
"""
import logging
import math
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction as db_transaction

from .device import parse_user_agent
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
    """Creates the transaction and runs the simulated payment.

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

    try:
        simulate_payment_processing(txn)
        txn.status = TransactionStatus.COMPLETED
    except PaymentProcessingError as exc:
        txn.status = TransactionStatus.FAILED
        txn.failure_reason = str(exc)[:255]
    except Exception:  # never leave a transaction stuck in PENDING
        logger.exception('Unexpected error while processing %s', txn.transaction_id)
        txn.status = TransactionStatus.FAILED
        txn.failure_reason = 'Unexpected processing error.'
    txn.save(update_fields=['status', 'failure_reason', 'updated_at'])
    return txn, True
