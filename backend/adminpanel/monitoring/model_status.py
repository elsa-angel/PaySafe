"""Status of the XGBoost fraud model and of confirmed fraud labels.

The model is integrated in informational mode: it scores supported payments and the result is stored
beside, never inside, the payment status. This module reports whether it can currently run. It never
fabricates predictions or metrics.
"""
from django.conf import settings

from payments.fraud import service
from payments.fraud.errors import PredictionError
from payments.fraud.mapper import SUPPORTED_PAYMENT_METHODS

LIMITATIONS = [
    'Trained on 2017 card e-commerce data (IEEE-CIS). Only card payments can be evaluated; UPI, bank transfer '
    'and wallet payments are reported as "prediction unavailable".',
    'The model uses six inputs only (amount, sender and recipient e-mail provider, device type, browser, OS). '
    'In offline testing it flagged a large share of transactions that have device data, so many flagged '
    'payments are expected to be genuine.',
    'Payments whose e-mail providers were not in the training data cannot be evaluated.',
]


def get_model_status():
    base = {
        'model': 'XGBoost',
        'mode': 'informational',
        'supported_payment_methods': sorted(SUPPORTED_PAYMENT_METHODS),
        'limitations': LIMITATIONS,
        'version': None, 'threshold': None, 'threshold_source': None,
    }
    if not settings.FRAUD_MODEL_ENABLED:
        return {**base, 'integrated': True, 'ready': False, 'status': 'Disabled',
                'message': 'Fraud analysis is switched off (FRAUD_MODEL_ENABLED).'}
    if not settings.FRAUD_INR_PER_USD:
        return {**base, 'integrated': True, 'ready': False, 'status': 'Not configured',
                'message': 'FRAUD_INR_PER_USD is not set, so no payment can be evaluated.'}
    try:
        bundle = service.get_bundle()
    except PredictionError:
        return {**base, 'integrated': True, 'ready': False, 'status': 'Unavailable',
                'message': 'The model artifacts could not be loaded or verified. See the server log.'}
    threshold, source = service.resolve_threshold(bundle)
    return {**base, 'integrated': True, 'ready': True, 'status': 'Ready', 'version': bundle.model_version,
            'threshold': threshold, 'threshold_source': source,
            'message': 'The XGBoost model is loaded and verified. Results are informational and do not change payments.'}


def get_confirmed_fraud_status():
    """Confirmed fraud labels (e.g. from investigations or chargebacks).

    PaySafe has no source of confirmed fraud labels yet, so none are reported, and therefore no live
    accuracy, precision, recall, F1, ROC-AUC or PR-AUC can be computed.
    """
    return {
        'available': False,
        'message': 'No confirmed fraud labels are available, so live model accuracy, precision, recall, '
                   'F1-score, ROC-AUC and PR-AUC are not shown.',
    }
