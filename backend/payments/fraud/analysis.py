"""Runs the fraud model for one transaction and persists the outcome as a FraudAnalysis row.

Fail-safe by construction: this function never raises, never changes the payment's status, and never
records a prediction that did not come from the model. If analysis cannot run, the row says so.
"""
import logging

from django.utils import timezone

from ..models import FraudAnalysis, FraudAnalysisStatus
from . import service
from .errors import FailureCategory as F, PredictionError, PredictionUnavailable
from .features import prepare_fraud_features

logger = logging.getLogger(__name__)


def run_fraud_analysis(txn):
    """Returns the saved FraudAnalysis, or None if even recording the outcome failed."""
    fields = {}
    try:
        prediction = service.predict(prepare_fraud_features(txn))
        fields = dict(
            status=FraudAnalysisStatus.EVALUATED, predicted_class=prediction.predicted_class,
            fraud_probability=prediction.fraud_probability, threshold_used=prediction.threshold,
            threshold_source=prediction.threshold_source, model_version=prediction.model_version,
        )
    except PredictionUnavailable as exc:
        fields = dict(status=FraudAnalysisStatus.UNAVAILABLE, failure_category=exc.category)
    except PredictionError as exc:
        fields = dict(status=FraudAnalysisStatus.ERROR, failure_category=exc.category)
    except Exception:
        logger.exception('Unexpected error during fraud analysis of %s', txn.transaction_id)
        fields = dict(status=FraudAnalysisStatus.ERROR, failure_category=F.INFERENCE_FAILED)
    try:
        analysis, _ = FraudAnalysis.objects.get_or_create(
            transaction=txn, defaults={**fields, 'evaluated_at': timezone.now()})
        return analysis
    except Exception:
        logger.exception('Could not record the fraud analysis of %s', txn.transaction_id)
        return None
