"""Outcome categories for fraud analysis. Only these fixed, safe strings are ever stored or shown;
exception text, file paths and stack traces never leave the server logs."""


class FailureCategory:
    # --- prediction UNAVAILABLE: the input is outside what the model can genuinely evaluate ---
    UNSUPPORTED_PAYMENT_METHOD = 'UNSUPPORTED_PAYMENT_METHOD'
    UNSUPPORTED_CURRENCY = 'UNSUPPORTED_CURRENCY'
    MISSING_DEVICE_FEATURES = 'MISSING_DEVICE_FEATURES'
    MISSING_EMAIL_FEATURES = 'MISSING_EMAIL_FEATURES'
    UNSEEN_EMAIL_DOMAIN = 'UNSEEN_EMAIL_DOMAIN'
    # --- prediction UNAVAILABLE: the deployment is not set up to run the model ---
    MODEL_DISABLED = 'MODEL_DISABLED'
    CONVERSION_RATE_NOT_CONFIGURED = 'CONVERSION_RATE_NOT_CONFIGURED'
    # --- technical ERROR: the model should have run but did not ---
    MODEL_ARTIFACTS_UNAVAILABLE = 'MODEL_ARTIFACTS_UNAVAILABLE'
    MODEL_VERSION_MISMATCH = 'MODEL_VERSION_MISMATCH'
    INFERENCE_FAILED = 'INFERENCE_FAILED'

    UNAVAILABLE = (
        UNSUPPORTED_PAYMENT_METHOD, UNSUPPORTED_CURRENCY, MISSING_DEVICE_FEATURES,
        MISSING_EMAIL_FEATURES, UNSEEN_EMAIL_DOMAIN, MODEL_DISABLED, CONVERSION_RATE_NOT_CONFIGURED,
    )
    ERRORS = (MODEL_ARTIFACTS_UNAVAILABLE, MODEL_VERSION_MISMATCH, INFERENCE_FAILED)
    ALL = UNAVAILABLE + ERRORS


# Shown to the signed-in user and to admins. Deliberately generic and free of internals.
MESSAGES = {
    FailureCategory.UNSUPPORTED_PAYMENT_METHOD:
        'The fraud model was trained only on card payments, so this payment method cannot be evaluated.',
    FailureCategory.UNSUPPORTED_CURRENCY: 'The fraud model cannot evaluate payments in this currency.',
    FailureCategory.MISSING_DEVICE_FEATURES:
        'Device details needed by the fraud model were not available for this payment.',
    FailureCategory.MISSING_EMAIL_FEATURES: 'E-mail details needed by the fraud model were not available.',
    FailureCategory.UNSEEN_EMAIL_DOMAIN:
        'An e-mail provider in this payment is not one the fraud model was trained on, so it cannot be evaluated.',
    FailureCategory.MODEL_DISABLED: 'Fraud analysis is switched off on this server.',
    FailureCategory.CONVERSION_RATE_NOT_CONFIGURED:
        'Fraud analysis is not configured on this server (currency conversion rate missing).',
    FailureCategory.MODEL_ARTIFACTS_UNAVAILABLE: 'The fraud model could not be loaded. No prediction was made.',
    FailureCategory.MODEL_VERSION_MISMATCH: 'The fraud model is incompatible with this server. No prediction was made.',
    FailureCategory.INFERENCE_FAILED: 'The fraud model failed while analysing this payment. No prediction was made.',
}


class PredictionUnavailable(Exception):
    """The transaction cannot be evaluated by this model (expected, not a malfunction)."""

    def __init__(self, category):
        assert category in FailureCategory.UNAVAILABLE, category
        super().__init__(category)
        self.category = category


class PredictionError(Exception):
    """A technical failure while loading or running the model."""

    def __init__(self, category):
        assert category in FailureCategory.ERRORS, category
        super().__init__(category)
        self.category = category
