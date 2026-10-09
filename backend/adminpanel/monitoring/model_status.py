"""Status of the (future) ML fraud model and of fraud labels.

PaySafe will use XGBoost only. It is NOT integrated yet, so this module reports
exactly that and never produces predictions, probabilities or metrics. When the
model is integrated later, replace ``get_model_status`` with a real check (model
artifact loaded, feature mapping verified) and add a prediction service beside it;
the dashboards read only from this module.
"""

NOT_INTEGRATED_MESSAGE = 'ML fraud detection is not integrated yet.'


def get_model_status():
    return {
        'integrated': False,
        'model': 'XGBoost',
        'status': 'Not integrated',
        'message': NOT_INTEGRATED_MESSAGE,
    }


def get_confirmed_fraud_status():
    """Confirmed fraud labels (e.g. from investigations or chargebacks).

    PaySafe has no source of confirmed fraud labels yet, so none are reported.
    """
    return {
        'available': False,
        'message': 'No confirmed fraud labels are available. Fraud counts are not shown.',
    }
