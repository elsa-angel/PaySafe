"""Turns a FraudAnalysis row (or its absence) into the API representation. Nothing is invented:
a missing row is reported as NOT_EVALUATED, never as low risk."""
from ..models import FraudAnalysisStatus
from .errors import MESSAGES

NOT_EVALUATED = 'NOT_EVALUATED'
DISCLAIMER = ('This is a statistical model prediction. It is not proof that fraud has occurred, and it does '
              'not change whether the payment completed. The score is not a calibrated probability.')
FLAGGED_MESSAGE = 'The fraud model flagged this payment as higher risk.'
NOT_FLAGGED_MESSAGE = 'The fraud model did not flag this payment. This is not a guarantee that it is genuine.'
NOT_EVALUATED_MESSAGE = 'This payment was not analysed by the fraud model.'


def get_analysis(txn):
    """The related FraudAnalysis or None (a OneToOne reverse access raises when absent)."""
    try:
        return txn.fraud_analysis
    except txn.__class__.fraud_analysis.RelatedObjectDoesNotExist:
        return None


def describe(analysis):
    if analysis is None:
        return {'status': NOT_EVALUATED, 'status_label': 'Not evaluated', 'flagged': None,
                'predicted_class': None, 'fraud_probability': None, 'model_version': '',
                'evaluated_at': None, 'message': NOT_EVALUATED_MESSAGE, 'disclaimer': None}
    base = {'status': analysis.status, 'status_label': analysis.get_status_display(),
            'evaluated_at': analysis.evaluated_at, 'model_version': analysis.model_version}
    if analysis.status == FraudAnalysisStatus.EVALUATED:
        flagged = analysis.predicted_class == 1
        return {**base, 'flagged': flagged, 'predicted_class': analysis.predicted_class,
                'fraud_probability': analysis.fraud_probability,
                'message': FLAGGED_MESSAGE if flagged else NOT_FLAGGED_MESSAGE, 'disclaimer': DISCLAIMER}
    return {**base, 'flagged': None, 'predicted_class': None, 'fraud_probability': None,
            'message': MESSAGES.get(analysis.failure_category, 'No prediction is available for this payment.'),
            'disclaimer': None}


def short_label(analysis):
    """One-word label for tables; None when the transaction was never analysed."""
    if analysis is None:
        return None
    if analysis.status == FraudAnalysisStatus.EVALUATED:
        return 'Flagged' if analysis.predicted_class == 1 else 'Not flagged'
    return 'Unavailable' if analysis.status == FraudAnalysisStatus.UNAVAILABLE else 'Error'
