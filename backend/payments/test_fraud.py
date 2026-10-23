"""Tests for the XGBoost fraud-model integration: artifact loading, strict feature mapping,
predictions, persistence, the payment flow, ownership and the admin statistics."""
import json
import logging
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import mock

import joblib
import numpy as np
import pandas as pd
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .fraud import feature_definitions as fd, service
from .fraud.analysis import run_fraud_analysis
from .fraud.errors import FailureCategory as F, PredictionError, PredictionUnavailable
from .fraud.features import prepare_fraud_features
from .fraud.mapper import AlignedFeatureMapper
from .models import FraudAnalysis, FraudAnalysisStatus, Transaction, TransactionStatus
from .tests import (BASE, CHROME_WIN, COMMON, FAST_HASH, FUTURE_EXPIRY, IPAD, IPHONE, METHOD_PAYLOADS, TEST_CARD, make_txn)

User = get_user_model()
RATE = Decimal('85')
MODEL_DIR = Path(settings.BASE_DIR) / 'fraud_model' / 'aligned'
PAYMENT = {**BASE, 'recipient_email': 'Friend@Yahoo.com'}


def make_gmail_user(name='sender'):
    return User.objects.create_user(username=f'{name}@gmail.com', email=f'{name}@gmail.com',
                                    password='Str0ng-Passw0rd!', first_name='Sender')


def card_txn(user, **overrides):
    fields = dict(recipient_email='friend@yahoo.com', amount=Decimal('4250.00'), payment_method='CARD',
                  card_network='VISA', device_type='DESKTOP', browser='Chrome 126', operating_system='Windows',
                  status=TransactionStatus.PENDING)
    fields.update(overrides)
    return make_txn(user, **fields)


@FAST_HASH
@override_settings(FRAUD_INR_PER_USD=RATE, FRAUD_MODEL_ENABLED=True, HIGH_RISK_THRESHOLD=None)
class FraudTestCase(TestCase):
    def setUp(self):
        cache.clear()
        service.reset_cache()
        self.addCleanup(service.reset_cache)
        self.user = make_gmail_user()
        self.client = APIClient()
        self.client.force_login(self.user)

    def pay(self, payload=None, user_agent=CHROME_WIN, **extra):
        return self.client.post('/api/payments/', payload or PAYMENT, format='json', HTTP_USER_AGENT=user_agent, **extra)


# --------------------------------------------------------------------------- artifacts
class ArtifactLoadingTests(FraudTestCase):
    def test_artifacts_load_and_pass_their_self_test(self):
        bundle = service.get_bundle()
        self.assertEqual(bundle.input_columns, bundle.metadata['input_columns_in_order'])  # order stored with the artifact
        self.assertCountEqual(bundle.input_columns, fd.ALIGNED_COLUMNS)
        self.assertEqual(bundle.metadata['feature_set'], 'aligned')
        self.assertIs(service.get_bundle(), bundle)  # cached: loaded once per process

    def test_loaded_pipeline_reproduces_training_time_scores(self):
        bundle = service.get_bundle()
        for sample in json.loads((MODEL_DIR / 'selftest_samples.json').read_text())['rows']:
            expected = sample.pop('expected_score')
            self.assertAlmostEqual(bundle.score_row(sample), expected, places=9)

    def test_vocabulary_comes_from_the_fitted_encoder(self):
        vocab = service.get_bundle().vocabulary
        self.assertIn('gmail.com', vocab['P_emaildomain'])
        self.assertNotIn('example.com', vocab['R_emaildomain'])
        self.assertNotIn('nan', vocab['device_type'])
        self.assertCountEqual(vocab['device_type'], ['desktop', 'mobile'])

    def _broken_copy(self, mutate):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(MODEL_DIR, tmp / 'm')
        mutate(tmp / 'm')
        return tmp / 'm'

    def test_tampered_artifact_is_refused(self):
        directory = self._broken_copy(lambda d: (d / 'xgboost_fraud_model.pkl').write_bytes(b'tampered'))
        with override_settings(FRAUD_MODEL_DIR=directory), self.assertRaises(PredictionError) as ctx:
            service.get_bundle()
        self.assertEqual(ctx.exception.category, F.MODEL_ARTIFACTS_UNAVAILABLE)

    def test_missing_manifest_or_directory_is_refused(self):
        directory = self._broken_copy(lambda d: (d / 'MANIFEST.sha256').unlink())
        with override_settings(FRAUD_MODEL_DIR=directory), self.assertRaises(PredictionError):
            service.get_bundle()
        service.reset_cache()
        with override_settings(FRAUD_MODEL_DIR=Path('/nonexistent/path')), self.assertRaises(PredictionError):
            service.get_bundle()

    def test_library_version_mismatch_is_reported_as_such(self):
        def edit(d):
            meta = json.loads((d / 'model_metadata.json').read_text())
            meta['libraries']['xgboost'] = '0.0.1'
            (d / 'model_metadata.json').write_text(json.dumps(meta))
            import hashlib
            lines = [l for l in (d / 'MANIFEST.sha256').read_text().splitlines() if not l.endswith('model_metadata.json')]
            lines.append(hashlib.sha256((d / 'model_metadata.json').read_bytes()).hexdigest() + '  model_metadata.json')
            (d / 'MANIFEST.sha256').write_text('\n'.join(lines) + '\n')
        with override_settings(FRAUD_MODEL_DIR=self._broken_copy(edit)), self.assertRaises(PredictionError) as ctx:
            service.get_bundle()
        self.assertEqual(ctx.exception.category, F.MODEL_VERSION_MISMATCH)


# --------------------------------------------------------------------------- feature mapping
class FeatureMappingTests(FraudTestCase):
    def mapper(self):
        bundle = service.get_bundle()
        return AlignedFeatureMapper(RATE, bundle.vocabulary, bundle.input_columns)

    def test_maps_real_paysafe_fields_in_training_order(self):
        row = self.mapper().to_model_row(prepare_fraud_features(card_txn(self.user)))
        self.assertEqual(list(row), service.get_bundle().input_columns)
        self.assertAlmostEqual(row['TransactionAmt'], 4250 / 85)
        self.assertEqual(
            {k: row[k] for k in fd.ALIGNED_CATEGORICAL},
            {'P_emaildomain': 'gmail.com', 'R_emaildomain': 'yahoo.com', 'device_type': 'desktop',
             'browser_family': 'chrome', 'os_family': 'windows'})

    def test_mobile_device_and_family_normalisation(self):
        txn = card_txn(self.user, device_type='MOBILE', browser='Safari 17', operating_system='iOS')
        row = self.mapper().to_model_row(prepare_fraud_features(txn))
        self.assertEqual((row['device_type'], row['browser_family'], row['os_family']), ('mobile', 'safari', 'ios'))

    def assertUnavailable(self, txn, category):
        with self.assertRaises(PredictionUnavailable) as ctx:
            self.mapper().to_model_row(prepare_fraud_features(txn))
        self.assertEqual(ctx.exception.category, category)

    def test_non_card_methods_are_never_mapped_to_card_features(self):
        for method, fields in (('UPI', {'upi_id': 'a@okaxis', 'card_network': ''}),
                               ('BANK_TRANSFER', {'bank_name': 'HDFC', 'card_network': ''}),
                               ('WALLET', {'wallet_provider': 'PAYTM', 'card_network': ''})):
            self.assertUnavailable(card_txn(self.user, payment_method=method, **fields), F.UNSUPPORTED_PAYMENT_METHOD)

    def test_unsupported_or_missing_inputs_are_refused_not_defaulted(self):
        self.assertUnavailable(card_txn(self.user, currency='USD'), F.UNSUPPORTED_CURRENCY)
        self.assertUnavailable(card_txn(self.user, device_type='TABLET'), F.MISSING_DEVICE_FEATURES)
        self.assertUnavailable(card_txn(self.user, device_type='UNKNOWN', browser='Unknown', operating_system='Unknown'), F.MISSING_DEVICE_FEATURES)
        self.assertUnavailable(card_txn(self.user, browser=''), F.MISSING_DEVICE_FEATURES)
        self.assertUnavailable(card_txn(self.user, recipient_email='friend@example.com'), F.UNSEEN_EMAIL_DOMAIN)
        outsider = User.objects.create_user('o@mydomain.in', 'o@mydomain.in', 'Str0ng-Passw0rd!')
        self.assertUnavailable(card_txn(outsider), F.UNSEEN_EMAIL_DOMAIN)

    def test_missing_conversion_rate_is_refused(self):
        with self.assertRaises(PredictionUnavailable) as ctx:
            AlignedFeatureMapper(None, service.get_bundle().vocabulary).to_model_row(prepare_fraud_features(card_txn(self.user)))
        self.assertEqual(ctx.exception.category, F.CONVERSION_RATE_NOT_CONFIGURED)


# --------------------------------------------------------------------------- predictions
class PredictionTests(FraudTestCase):
    def predict(self, **overrides):
        return service.predict(prepare_fraud_features(card_txn(self.user, **overrides)))

    def test_prediction_equals_an_independent_run_of_the_saved_pipeline(self):
        result = self.predict()
        pipeline = joblib.load(MODEL_DIR / 'xgboost_fraud_model.pkl')
        frame = pd.DataFrame([{'TransactionAmt': np.float32(4250 / 85), 'P_emaildomain': 'gmail.com', 'R_emaildomain': 'yahoo.com',
                               'device_type': 'desktop', 'browser_family': 'chrome', 'os_family': 'windows'}])
        expected = float(pipeline.predict_proba(frame)[0, 1])
        self.assertAlmostEqual(result.fraud_probability, expected, places=7)
        self.assertTrue(0.0 <= result.fraud_probability <= 1.0)
        self.assertIn(result.predicted_class, (0, 1))
        self.assertEqual(result.threshold_source, 'phase1_validation')
        self.assertAlmostEqual(result.threshold, service.get_bundle().metadata['thresholds']['primary']['threshold'])
        self.assertEqual(result.predicted_class, int(result.fraud_probability >= result.threshold))

    def test_amount_changes_the_score_so_features_really_reach_the_model(self):
        scores = {self.predict(amount=Decimal(a)).fraud_probability for a in ('50.00', '4250.00', '250000.00')}
        self.assertGreater(len(scores), 1)

    def test_threshold_override_is_applied_and_recorded(self):
        with override_settings(HIGH_RISK_THRESHOLD=0.999):
            r = self.predict()
        self.assertEqual((r.predicted_class, r.threshold, r.threshold_source), (0, 0.999, 'configured_override'))
        with override_settings(HIGH_RISK_THRESHOLD=1e-9):
            self.assertEqual(self.predict().predicted_class, 1)

    def test_disabled_model_gives_unavailable_not_a_score(self):
        with override_settings(FRAUD_MODEL_ENABLED=False), self.assertRaises(PredictionUnavailable) as ctx:
            self.predict()
        self.assertEqual(ctx.exception.category, F.MODEL_DISABLED)

    def test_inference_failure_is_an_error_not_a_default(self):
        bundle = service.get_bundle()
        with mock.patch.object(type(bundle), 'score_row', side_effect=RuntimeError('/secret/path boom')), \
                self.assertRaises(PredictionError) as ctx:
            self.predict()
        self.assertEqual(ctx.exception.category, F.INFERENCE_FAILED)
        self.assertNotIn('secret', str(ctx.exception))


# --------------------------------------------------------------------------- persistence + payment flow
class PaymentFlowTests(FraudTestCase):
    def test_supported_card_payment_stores_and_returns_a_genuine_prediction(self):
        res = self.pay()
        self.assertEqual(res.status_code, 201, res.data)
        fa = res.data['fraud_analysis']
        self.assertEqual(fa['status'], 'EVALUATED')
        self.assertTrue(0 <= fa['fraud_probability'] <= 1)
        self.assertIn(fa['predicted_class'], (0, 1))
        self.assertEqual(fa['flagged'], fa['predicted_class'] == 1)
        self.assertIn('not proof', fa['disclaimer'])
        row = FraudAnalysis.objects.get(transaction__transaction_id=res.data['transaction_id'])
        self.assertEqual((row.status, row.fraud_probability, row.predicted_class), ('EVALUATED', fa['fraud_probability'], fa['predicted_class']))
        self.assertTrue(row.model_version and row.threshold_used)
        self.assertEqual(row.failure_category, '')

    def test_payment_status_is_independent_of_the_predicted_class(self):
        with override_settings(HIGH_RISK_THRESHOLD=1e-9):           # force the fraud class
            res = self.pay()
        self.assertEqual(res.data['fraud_analysis']['predicted_class'], 1)
        self.assertEqual(res.data['status'], 'PENDING')              # held for the user's decision, not failed or completed
        self.assertEqual(res.data['verification']['risk_category'], 'HIGH')
        self.assertEqual(Transaction.objects.get(transaction_id=res.data['transaction_id']).fraud_status, 'NOT_CHECKED')

    def test_unsupported_methods_are_unavailable_never_low_risk(self):
        for method in ('UPI', 'BANK_TRANSFER', 'WALLET'):
            res = self.pay({**COMMON, **METHOD_PAYLOADS[method], 'recipient_email': 'friend@yahoo.com'})
            self.assertEqual(res.status_code, 201, res.data)
            fa = res.data['fraud_analysis']
            self.assertEqual(fa['status'], 'UNAVAILABLE', method)
            for key in ('fraud_probability', 'predicted_class', 'flagged'):
                self.assertIsNone(fa[key])
            self.assertIn('only on card payments', fa['message'])
            row = FraudAnalysis.objects.get(transaction__transaction_id=res.data['transaction_id'])
            self.assertEqual(row.failure_category, F.UNSUPPORTED_PAYMENT_METHOD)
            self.assertIsNone(row.fraud_probability)

    def test_unsupported_device_email_and_config_produce_unavailable(self):
        cases = [
            (dict(user_agent=IPAD), 'UNAVAILABLE', F.MISSING_DEVICE_FEATURES),
            (dict(payload={**PAYMENT, 'recipient_email': 'a@example.com'}), 'UNAVAILABLE', F.UNSEEN_EMAIL_DOMAIN),
        ]
        for kwargs, status_, category in cases:
            res = self.pay(**kwargs)
            self.assertEqual(res.status_code, 201)
            self.assertEqual(res.data['fraud_analysis']['status'], status_)
            self.assertEqual(FraudAnalysis.objects.get(transaction__transaction_id=res.data['transaction_id']).failure_category, category)
        with override_settings(FRAUD_INR_PER_USD=None):
            res = self.pay()
        self.assertEqual(res.data['fraud_analysis']['status'], 'UNAVAILABLE')
        self.assertIn('not configured', res.data['fraud_analysis']['message'])

    def test_missing_artifacts_record_an_error_and_never_approve_or_block(self):
        with override_settings(FRAUD_MODEL_DIR=Path('/nonexistent/secret/dir')), self.assertLogs('payments.fraud.service', 'ERROR') as logs:
            res = self.pay()
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['status'], 'PENDING')                 # held, never approved on a failed analysis
        self.assertEqual(res.data['verification']['status'], 'UNAVAILABLE')
        fa = res.data['fraud_analysis']
        self.assertEqual(fa['status'], 'ERROR')
        self.assertIsNone(fa['fraud_probability'])
        self.assertNotIn('nonexistent', json.dumps(fa, default=str))                 # no server paths in API output
        self.assertNotIn('Traceback', json.dumps(fa, default=str))

    def test_unexpected_exception_in_analysis_never_breaks_the_payment(self):
        with mock.patch('payments.fraud.analysis.prepare_fraud_features', side_effect=RuntimeError('boom')), \
                self.assertLogs('payments.fraud.analysis', 'ERROR'):
            res = self.pay()
        self.assertEqual((res.status_code, res.data['status'], res.data['fraud_analysis']['status']), (201, 'PENDING', 'ERROR'))
        self.assertEqual(res.data['verification']['status'], 'UNAVAILABLE')

    def test_client_supplied_fraud_values_are_ignored(self):
        res = self.pay({**PAYMENT, 'fraud_probability': 0.0001, 'fraud_status': 'LEGITIMATE', 'predicted_class': 0,
                        'risk_category': 'LOW', 'model_version': 'evil'})
        fa = res.data['fraud_analysis']
        self.assertNotEqual(fa['model_version'], 'evil')
        row = FraudAnalysis.objects.get(transaction__transaction_id=res.data['transaction_id'])
        self.assertNotEqual(row.fraud_probability, 0.0001)

    def test_idempotent_replay_does_not_create_a_second_analysis(self):
        key = 'replay-key-12345'
        first = self.pay(HTTP_IDEMPOTENCY_KEY=key)
        second = self.pay(HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(FraudAnalysis.objects.count(), 1)
        self.assertEqual(first.data['fraud_analysis']['fraud_probability'], second.data['fraud_analysis']['fraud_probability'])

    def test_running_analysis_twice_keeps_one_record(self):
        txn = card_txn(self.user)
        a, b = run_fraud_analysis(txn), run_fraud_analysis(txn)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(FraudAnalysis.objects.filter(transaction=txn).count(), 1)

    def test_no_card_credentials_reach_logs_or_the_analysis_record(self):
        with self.assertNoLogs('payments', logging.WARNING):
            res = self.pay()
        blob = json.dumps(res.data, default=str) + str(list(FraudAnalysis.objects.values()))
        for secret in (TEST_CARD.replace(' ', ''), '4111', '123', FUTURE_EXPIRY):
            if secret != '123':
                self.assertNotIn(secret, blob)
        names = {f.name for f in FraudAnalysis._meta.get_fields()}
        self.assertFalse({'card_number', 'card_cvv', 'cvv', 'pin', 'otp'} & names)


# --------------------------------------------------------------------------- retrieval + authorization
class RetrievalAndOwnershipTests(FraudTestCase):
    def test_detail_returns_the_stored_analysis_to_its_owner_only(self):
        txn_id = self.pay().data['transaction_id']
        detail = self.client.get(f'/api/payments/{txn_id}/')
        self.assertEqual(detail.data['fraud_analysis']['status'], 'EVALUATED')
        other = make_gmail_user('intruder')
        client = APIClient(); client.force_login(other)
        self.assertEqual(client.get(f'/api/payments/{txn_id}/').status_code, 404)
        self.assertEqual(APIClient().get(f'/api/payments/{txn_id}/').status_code, 403)

    def test_old_transactions_are_reported_not_evaluated_not_invented(self):
        old = card_txn(self.user, status=TransactionStatus.COMPLETED)   # no FraudAnalysis row, like pre-integration data
        fa = self.client.get(f'/api/payments/{old.transaction_id}/').data['fraud_analysis']
        self.assertEqual(fa['status'], 'NOT_EVALUATED')
        self.assertIsNone(fa['fraud_probability'])
        self.assertIsNone(fa['flagged'])
        self.assertFalse(FraudAnalysis.objects.filter(transaction=old).exists())

    def test_list_endpoint_stays_lean_and_leaks_nothing_new(self):
        self.pay()
        item = self.client.get('/api/payments/').data['results'][0]
        self.assertNotIn('fraud_analysis', item)

    def test_admin_endpoints_require_a_superuser(self):
        self.pay()
        for url in ('/api/admin/fraud-statistics/', '/api/admin/transactions/'):
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(APIClient().get(url).status_code, 403)


# --------------------------------------------------------------------------- admin statistics
class AdminPredictionStatisticsTests(FraudTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', 'Str0ng-Passw0rd!')
        self.admin_client = APIClient(); self.admin_client.force_login(self.admin)
        self.evaluated = [self.pay().data for _ in range(3)]
        self.upi = self.pay({**COMMON, **METHOD_PAYLOADS['UPI'], 'recipient_email': 'friend@yahoo.com'}).data
        old = card_txn(self.user, status=TransactionStatus.COMPLETED)   # never analysed
        self.old_id = old.transaction_id

    def stats(self, **params):
        return self.admin_client.get('/api/admin/fraud-statistics/', params).data

    def test_counts_come_from_real_records_and_separate_unavailable_from_evaluated(self):
        pred = self.stats()['predictions']
        self.assertEqual((pred['evaluated'], pred['unavailable'], pred['error'], pred['not_evaluated']), (3, 1, 0, 1))
        self.assertEqual(pred['total_transactions'], 5)
        self.assertEqual(pred['predicted_classes']['flagged'] + pred['predicted_classes']['not_flagged'], 3)
        self.assertEqual(pred['unavailable_by_category'][0]['category'], F.UNSUPPORTED_PAYMENT_METHOD)

    def test_probability_summary_uses_evaluated_rows_only(self):
        scores = [e['fraud_analysis']['fraud_probability'] for e in self.evaluated]
        prob = self.stats()['predictions']['probability']
        self.assertAlmostEqual(prob['average'], round(sum(scores) / 3, 4), places=4)
        self.assertAlmostEqual(prob['minimum'], round(min(scores), 4), places=4)
        self.assertAlmostEqual(prob['maximum'], round(max(scores), 4), places=4)
        self.assertEqual(sum(b['count'] for b in prob['histogram']), 3)   # the UPI row is not in the histogram

    def test_series_totals_match(self):
        series = self.stats()['predictions']['series']
        self.assertEqual(sum(p['evaluated'] for p in series), 3)
        self.assertEqual(sum(p['unavailable'] for p in series), 1)

    def test_model_status_is_real_and_metrics_are_never_reported(self):
        data = self.stats()
        self.assertTrue(data['ml_model']['ready'])
        self.assertEqual(data['ml_model']['supported_payment_methods'], ['CARD'])
        self.assertTrue(data['ml_model']['version'])
        self.assertFalse(data['confirmed_fraud']['available'])
        text = json.dumps(data, default=str).lower()
        for key in ('"accuracy"', '"precision"', '"recall"', '"f1"', '"roc_auc"', '"pr_auc"'):
            self.assertNotIn(key, text)

    def test_admin_transaction_detail_and_list(self):
        detail = self.admin_client.get(f'/api/admin/transactions/{self.evaluated[0]["transaction_id"]}/').data
        self.assertEqual(detail['fraud_analysis_detail']['status'], 'EVALUATED')
        self.assertIn(detail['fraud_analysis'], ('Flagged', 'Not flagged'))
        self.assertIsNotNone(detail['fraud_analysis_detail']['threshold_used'])
        old = self.admin_client.get(f'/api/admin/transactions/{self.old_id}/').data
        self.assertIsNone(old['fraud_analysis'])
        self.assertEqual(old['fraud_analysis_detail']['status'], 'NOT_EVALUATED')
        listing = self.admin_client.get('/api/admin/transactions/').data['results']
        labels = {row['transaction_id']: row['fraud_analysis'] for row in listing}
        self.assertEqual(labels[self.upi['transaction_id']], 'Unavailable')

    def test_fraud_monitoring_report_includes_stored_predictions(self):
        data = self.admin_client.get('/api/admin/reports/fraud-monitoring/').data
        section = next(s for s in data['sections'] if s['title'].startswith('XGBoost predictions'))
        rows = dict(section['rows'])
        self.assertEqual((rows['Evaluated by the model'], rows['Prediction unavailable']), (3, 1))
        csv = self.admin_client.get('/api/admin/reports/fraud-monitoring/', {'export': 'csv'})
        self.assertEqual(csv.status_code, 200)
