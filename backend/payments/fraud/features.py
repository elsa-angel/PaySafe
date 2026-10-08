"""Fraud feature preparation: the boundary between payments and XGBoost.

Planned flow (only the first two steps exist today):

    Transaction -> prepare_fraud_features()  -> FraudSourceData   (implemented)
                -> FeatureMapper.to_model_row() -> XGBoost input   (future)
                -> XGBoost prediction -> risk decision -> OTP / alert / continue

``FraudSourceData`` is *application-level* source information (what PaySafe
genuinely knows about a payment) plus real behavioural history. It is NOT the
IEEE-CIS representation. The trained model expects the exact IEEE-CIS column
names, order, encodings and missing-value handling used in training, so the
translation lives behind the ``FeatureMapper`` interface below and must be
implemented from the training pipeline's artifacts (feature list, encoders,
fill values), never guessed here.

Nothing in this package loads XGBoost or a model file, or scores anything.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Mapping, Protocol

from ..models import Transaction
from .history import HistoryFeatures, compute_history_features


class FeatureMappingNotConfigured(RuntimeError):
    """Raised when no IEEE-CIS feature mapper has been installed yet."""


@dataclass(frozen=True)
class FraudSourceData:
    # transaction
    transaction_id: str
    amount: Decimal
    currency: str
    payment_method: str
    card_network: str
    bank_name: str
    wallet_provider: str
    upi_handle: str  # the part after "@" in a UPI ID (never the full ID)
    has_description: bool
    recipient_email_domain: str
    # time
    timestamp: Any
    hour_of_day: int
    day_of_week: int
    account_age_seconds: float
    # device
    device_type: str
    browser: str
    operating_system: str
    # location (None when the user did not share it)
    latitude: Decimal | None
    longitude: Decimal | None
    location_status: str
    # behaviour
    history: HistoryFeatures

    def as_dict(self):
        return asdict(self)


class FeatureMapper(Protocol):
    """Translates FraudSourceData into the model's exact input row.

    An implementation must return a mapping keyed by the *trained model's*
    feature names, in the training column order, using the training encoders
    and missing-value conventions.
    """

    def to_model_row(self, source: FraudSourceData) -> Mapping[str, Any]: ...


def prepare_fraud_features(transaction: Transaction) -> FraudSourceData:
    """Collects everything the future feature mapper needs for one transaction."""
    local_time = transaction.timestamp
    user = transaction.user
    history = compute_history_features(
        user=user,
        as_of=transaction.timestamp,
        recipient_email=transaction.recipient_email,
        payment_method=transaction.payment_method,
        exclude_pk=transaction.pk,
    )
    return FraudSourceData(
        transaction_id=transaction.transaction_id,
        amount=transaction.amount,
        currency=transaction.currency,
        payment_method=transaction.payment_method,
        card_network=transaction.card_network,
        bank_name=transaction.bank_name,
        wallet_provider=transaction.wallet_provider,
        upi_handle=transaction.upi_id.partition('@')[2],
        has_description=bool(transaction.description),
        recipient_email_domain=transaction.recipient_email.partition('@')[2],
        timestamp=transaction.timestamp,
        hour_of_day=local_time.hour,
        day_of_week=local_time.weekday(),
        account_age_seconds=max((transaction.timestamp - user.date_joined).total_seconds(), 0.0),
        device_type=transaction.device_type,
        browser=transaction.browser,
        operating_system=transaction.operating_system,
        latitude=transaction.latitude,
        longitude=transaction.longitude,
        location_status=transaction.location_status,
        history=history,
    )


def build_model_row(source: FraudSourceData, mapper: FeatureMapper | None = None):
    """Single entry point the XGBoost stage will call."""
    if mapper is None:
        raise FeatureMappingNotConfigured(
            'No IEEE-CIS feature mapper is installed. Implement FeatureMapper from '
            "the training pipeline's feature list and encoders."
        )
    return mapper.to_model_row(source)
