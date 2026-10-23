"""PaySafe -> `aligned` model input row (strict).

The trained model only knows six canonical inputs (see feature_definitions.py). This mapper builds
them from real PaySafe data and REFUSES (raises PredictionUnavailable) rather than substituting
defaults. In particular a missing value is never passed through as NaN: in the training data a
missing device or e-mail field meant "no identity record", which is a low-risk signal, so passing
NaN for a PaySafe user would silently lower their score.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Collection, Mapping

from . import feature_definitions as fd
from .errors import FailureCategory as F, PredictionUnavailable

# The training data (IEEE-CIS) contains ONLY card-based transactions, so only CARD is in domain.
# UPI, bank transfer and wallet payments have no representation in the training data.
SUPPORTED_PAYMENT_METHODS = frozenset({'CARD'})
SUPPORTED_CURRENCY = 'INR'


def check_cheap_preconditions(source, inr_per_usd) -> None:
    """Checks that need no model artifacts. Raises PredictionUnavailable."""
    if source.payment_method not in SUPPORTED_PAYMENT_METHODS:
        raise PredictionUnavailable(F.UNSUPPORTED_PAYMENT_METHOD)
    if str(source.currency).upper() != SUPPORTED_CURRENCY:
        raise PredictionUnavailable(F.UNSUPPORTED_CURRENCY)
    if not inr_per_usd:
        raise PredictionUnavailable(F.CONVERSION_RATE_NOT_CONFIGURED)
    if source.device_type not in ('MOBILE', 'DESKTOP') or source.browser in ('', 'Unknown') \
            or source.operating_system in ('', 'Unknown'):
        # TABLET is excluded because the training data never says how tablets are labelled.
        raise PredictionUnavailable(F.MISSING_DEVICE_FEATURES)
    if not getattr(source, 'sender_email_domain', '') or not source.recipient_email_domain:
        raise PredictionUnavailable(F.MISSING_EMAIL_FEATURES)


class AlignedFeatureMapper:
    def __init__(self, inr_per_usd: Decimal, vocabulary: Mapping[str, Collection[str]], column_order=None):
        """`vocabulary`: the categories the fitted encoder knows, per categorical column.
        `column_order`: the model's input columns in the order stored with the artifact."""
        self.column_order = list(column_order or fd.ALIGNED_COLUMNS)
        self.inr_per_usd = Decimal(inr_per_usd) if inr_per_usd else None
        self.vocabulary = {k: frozenset(v) for k, v in vocabulary.items()}

    def to_model_row(self, source) -> Mapping[str, Any]:
        check_cheap_preconditions(source, self.inr_per_usd)
        row = {
            'TransactionAmt': float(Decimal(source.amount) / self.inr_per_usd),
            'P_emaildomain': str(source.sender_email_domain).strip().lower(),
            'R_emaildomain': str(source.recipient_email_domain).strip().lower(),
            'device_type': fd.paysafe_device_type(source.device_type),
            'browser_family': fd.paysafe_browser_family(source.browser),
            'os_family': fd.paysafe_os_family(source.operating_system),
        }
        for column in fd.ALIGNED_CATEGORICAL:
            value = row[column]
            if value != value or value is None:                      # NaN: no honest mapping exists
                raise PredictionUnavailable(F.MISSING_DEVICE_FEATURES)
            if value not in self.vocabulary[column]:                 # would be silently treated as missing
                raise PredictionUnavailable(
                    F.UNSEEN_EMAIL_DOMAIN if column.endswith('emaildomain') else F.MISSING_DEVICE_FEATURES)
        return {column: row[column] for column in self.column_order}   # the artifact's column order
