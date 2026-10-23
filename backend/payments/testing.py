"""Helpers for tests that need a controlled fraud prediction or the e-mailed one-time code.
(Test-only: nothing in the application imports this module.)"""
import re
from unittest import mock

from .fraud.service import Prediction

THRESHOLD = 0.1055
LOW = 0.02    # below THRESHOLD  -> low risk
HIGH = 0.60   # at/above THRESHOLD -> high risk


def fake_prediction(probability, threshold=THRESHOLD):
    return Prediction(predicted_class=int(probability >= threshold), fraud_probability=probability,
                      threshold=threshold, threshold_source='phase1_validation', model_version='test-model')


def force_prediction(probability, threshold=THRESHOLD):
    """Makes the fraud service return a fixed, valid prediction (the real model is tested elsewhere)."""
    return mock.patch('payments.fraud.service.predict', return_value=fake_prediction(probability, threshold))


def code_from(message):
    """Extracts the one-time code from an e-mail the way a user would read it."""
    return re.search(r'verification code is: (\d+)', message.body).group(1)
