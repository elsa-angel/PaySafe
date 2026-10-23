"""Loads the Phase 1 XGBoost pipeline once, verifies it, and scores one transaction.

Nothing is trained here. The saved sklearn Pipeline (ordinal encoder + XGBClassifier) applies exactly
the training-time transformations. The artifact directory is private server-side configuration.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from . import feature_definitions as fd
from .errors import FailureCategory as F, PredictionError, PredictionUnavailable
from .mapper import AlignedFeatureMapper, SUPPORTED_PAYMENT_METHODS, check_cheap_preconditions

logger = logging.getLogger(__name__)

REQUIRED_FILES = ('xgboost_fraud_model.pkl', 'selected_features.pkl', 'model_metadata.json', 'selftest_samples.json')
MANIFEST = 'MANIFEST.sha256'
SELFTEST_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Prediction:
    predicted_class: int
    fraud_probability: float
    threshold: float
    threshold_source: str
    model_version: str


class ModelBundle:
    """A fully verified, immutable set of loaded artifacts."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._verify_files()
        self.metadata = json.loads((self.directory / 'model_metadata.json').read_text())
        self._verify_metadata()
        self._load_pipeline()
        self._self_test()

    # -- integrity -------------------------------------------------------------------------
    def _verify_files(self):
        manifest_path = self.directory / MANIFEST
        if not manifest_path.is_file():
            raise PredictionError(F.MODEL_ARTIFACTS_UNAVAILABLE)
        expected = {}
        for line in manifest_path.read_text().splitlines():
            digest, _, name = line.strip().partition('  ')
            if digest and name:
                expected[name] = digest
        for name in REQUIRED_FILES:
            path = self.directory / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected.get(name):
                logger.error('Fraud model artifact missing or failed its integrity check: %s', name)
                raise PredictionError(F.MODEL_ARTIFACTS_UNAVAILABLE)

    def _verify_metadata(self):
        meta = self.metadata
        if meta.get('feature_set') != 'aligned' or set(meta.get('input_columns_in_order', [])) != set(fd.ALIGNED_COLUMNS):
            logger.error('Model metadata does not describe the PaySafe-aligned feature set')
            raise PredictionError(F.MODEL_ARTIFACTS_UNAVAILABLE)
        if meta['target']['predict_proba_column_for_fraud'] != 1:
            raise PredictionError(F.MODEL_ARTIFACTS_UNAVAILABLE)

    # -- loading ---------------------------------------------------------------------------
    def _load_pipeline(self):
        import joblib
        import sklearn
        import xgboost

        built = self.metadata['libraries']
        if xgboost.__version__ != built['xgboost'] or sklearn.__version__ != built['scikit_learn']:
            logger.error('Model built with xgboost %s / scikit-learn %s, installed %s / %s',
                         built['xgboost'], built['scikit_learn'], xgboost.__version__, sklearn.__version__)
            raise PredictionError(F.MODEL_VERSION_MISMATCH)
        try:
            self.pipeline = joblib.load(self.directory / 'xgboost_fraud_model.pkl')
            self.input_columns = list(joblib.load(self.directory / 'selected_features.pkl'))
            encoder = self.pipeline.named_steps['preprocess'].named_transformers_['cat']
            cat_columns = list(self.pipeline.named_steps['preprocess'].transformers_[0][2])
            self.vocabulary = {
                column: [c for c in categories if isinstance(c, str)]
                for column, categories in zip(cat_columns, encoder.categories_)
            }
        except Exception:
            logger.exception('Could not load the fraud model pipeline')
            raise PredictionError(F.MODEL_ARTIFACTS_UNAVAILABLE)
        if (self.input_columns != self.metadata['input_columns_in_order']
                or set(self.input_columns) != set(fd.ALIGNED_COLUMNS) or set(self.vocabulary) != set(fd.ALIGNED_CATEGORICAL)):
            logger.error('Loaded pipeline columns differ from the PaySafe feature definitions')
            raise PredictionError(F.MODEL_ARTIFACTS_UNAVAILABLE)

    def _self_test(self):
        """Re-scores rows saved at training time; the loaded pipeline must reproduce them."""
        samples = json.loads((self.directory / 'selftest_samples.json').read_text())['rows']
        for sample in samples:
            expected = sample.pop('expected_score')
            if abs(self.score_row(sample) - expected) > SELFTEST_TOLERANCE:
                logger.error('Fraud model self-test failed: loaded model disagrees with its training-time scores')
                raise PredictionError(F.MODEL_ARTIFACTS_UNAVAILABLE)

    # -- scoring ---------------------------------------------------------------------------
    def score_row(self, row) -> float:
        import numpy as np
        import pandas as pd

        frame = pd.DataFrame([row], columns=self.input_columns)   # the artifact's own column order
        for column in fd.ALIGNED_CATEGORICAL:      # categorical columns MUST be object dtype, even if all-NaN
            frame[column] = frame[column].map(lambda v: np.nan if v is None or v != v else str(v)).astype(object)
        frame['TransactionAmt'] = frame['TransactionAmt'].astype('float32')
        return float(self.pipeline.predict_proba(frame)[0, 1])

    @property
    def model_version(self) -> str:
        return self.metadata['version']


_lock = threading.Lock()
_bundle = None
_bundle_error = None


def get_bundle() -> ModelBundle:
    """Loads once per process and caches the result (including a load failure, so a broken
    deployment is not re-read from disk on every payment). Call reset_cache() after fixing it."""
    global _bundle, _bundle_error
    if _bundle is not None:
        return _bundle
    if _bundle_error is not None:
        raise PredictionError(_bundle_error)
    with _lock:
        if _bundle is None and _bundle_error is None:
            try:
                _bundle = ModelBundle(settings.FRAUD_MODEL_DIR)
                logger.info('Fraud model %s loaded', _bundle.model_version)
            except PredictionError as exc:
                logger.error('Fraud model could not be loaded (%s)', exc.category)
                _bundle_error = exc.category
            except Exception:
                logger.exception('Unexpected error while loading the fraud model')
                _bundle_error = F.MODEL_ARTIFACTS_UNAVAILABLE
    if _bundle is None:
        raise PredictionError(_bundle_error)
    return _bundle


def reset_cache():
    global _bundle, _bundle_error
    with _lock:
        _bundle, _bundle_error = None, None


def resolve_threshold(bundle: ModelBundle):
    """Default: the Phase 1 validation-chosen threshold. An operator override is allowed but is
    recorded as such on every prediction."""
    override = settings.HIGH_RISK_THRESHOLD
    if override is not None:
        return float(override), 'configured_override'
    return float(bundle.metadata['thresholds']['primary']['threshold']), 'phase1_validation'


def predict(source) -> Prediction:
    """Scores one FraudSourceData. Raises PredictionUnavailable or PredictionError; never guesses."""
    if not settings.FRAUD_MODEL_ENABLED:
        raise PredictionUnavailable(F.MODEL_DISABLED)
    rate = settings.FRAUD_INR_PER_USD
    check_cheap_preconditions(source, rate)               # no artifacts needed for these refusals
    bundle = get_bundle()
    row = AlignedFeatureMapper(rate, bundle.vocabulary, bundle.input_columns).to_model_row(source)
    try:
        probability = bundle.score_row(row)
    except Exception:
        logger.exception('Fraud model inference failed')
        raise PredictionError(F.INFERENCE_FAILED)
    if not 0.0 <= probability <= 1.0 or probability != probability:
        logger.error('Fraud model returned an invalid score')
        raise PredictionError(F.INFERENCE_FAILED)
    threshold, source_name = resolve_threshold(bundle)
    return Prediction(
        predicted_class=int(probability >= threshold), fraud_probability=probability,
        threshold=threshold, threshold_source=source_name, model_version=bundle.model_version,
    )

