"""Phase 3: risk category -> alert / one-time code -> verification -> final payment status."""
import json
from datetime import timedelta
from decimal import Decimal
from smtplib import SMTPException
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.mail.backends.base import BaseEmailBackend
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .fraud import service
from .fraud.features import prepare_fraud_features
from .fraud.mapper import AlignedFeatureMapper
from .models import (
    FraudAnalysis, FraudWorkflowEvent, OneTimeCode, PaymentVerification, RiskCategory, Transaction, TransactionStatus,
)
from .test_fraud import card_txn
from .tests import BASE, CHROME_WIN, FAST_HASH, METHOD_PAYLOADS, make_txn
from .testing import HIGH, LOW, THRESHOLD, code_from, fake_prediction, force_prediction

User = get_user_model()
RATE = Decimal('85')
PAYMENT = {**BASE, 'recipient_name': 'Friend', 'recipient_email': 'friend@yahoo.com'}   # recipient != account e-mail


class FailingBackend(BaseEmailBackend):
    """Simulates an SMTP server that rejects the message, with secrets in the error text."""

    def send_messages(self, email_messages):
        raise SMTPException('535 authentication failed password=hunter2 host=smtp.secret.example')


@FAST_HASH
@override_settings(FRAUD_INR_PER_USD=RATE, OTP_RESEND_COOLDOWN_SECONDS=0, HIGH_RISK_THRESHOLD=None)
class WorkflowTestCase(TestCase):
    def setUp(self):
        cache.clear()
        service.reset_cache()
        self.addCleanup(service.reset_cache)
        self.user = User.objects.create_user('sender@gmail.com', 'sender@gmail.com', 'Str0ng-Passw0rd!', first_name='Sam')
        self.client = APIClient()
        self.client.force_login(self.user)

    # -- helpers
    def pay(self, probability=LOW, payload=None, user_agent=CHROME_WIN, key=None, client=None):
        extra = {'HTTP_USER_AGENT': user_agent, **({'HTTP_IDEMPOTENCY_KEY': key} if key else {})}
        with force_prediction(probability):
            return (client or self.client).post('/api/payments/', payload or PAYMENT, format='json', **extra)

    def act(self, txn_id, action, body=None, client=None):
        return (client or self.client).post(f'/api/payments/{txn_id}/{action}/', body or {}, format='json')

    def verify(self, txn_id, code, client=None):
        return self.act(txn_id, 'verify-otp', {'code': code}, client)

    def txn(self, txn_id):
        return Transaction.objects.get(transaction_id=txn_id)

    def events(self, txn_id):
        return [e.event_type for e in FraudWorkflowEvent.objects.filter(transaction__transaction_id=txn_id)]

    def other_client(self):
        other = User.objects.create_user('intruder@gmail.com', 'intruder@gmail.com', 'Str0ng-Passw0rd!')
        c = APIClient(); c.force_login(other)
        return c

    def wrong_code(self, code):
        return '000000' if code != '000000' else '111111'


# =============================================================== low-risk workflow
class LowRiskWorkflowTests(WorkflowTestCase):
    def test_payment_waits_and_a_code_is_emailed_to_the_registered_address_only(self):
        res = self.pay(LOW)
        self.assertEqual(res.status_code, 201, res.data)
        v = res.data['verification']
        self.assertEqual((res.data['status'], v['status'], v['risk_category'], v['next_action']), ('PENDING', 'AWAITING_OTP', 'LOW', 'ENTER_OTP'))
        self.assertTrue(v['can_verify'] and v['can_cancel'] and not v['can_continue'])
        self.assertEqual(v['otp']['delivery'], 'SENT')
        self.assertEqual(v['email_hint'], 's*****@gmail.com')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['sender@gmail.com'])           # never the recipient typed in the form
        self.assertNotIn('friend@yahoo.com', mail.outbox[0].to)
        self.assertIn('INR 250.50', mail.outbox[0].body)

    def test_correct_code_completes_the_payment_once(self):
        txn_id = self.pay(LOW).data['transaction_id']
        code = code_from(mail.outbox[0])
        with mock.patch('payments.workflow.process_transaction', wraps=__import__('payments.services', fromlist=['x']).process_transaction) as proc:
            res = self.verify(txn_id, code)
            again = self.verify(txn_id, code)
        self.assertEqual((res.status_code, res.data['status'], res.data['verification']['status']), (200, 'COMPLETED', 'VERIFIED'))
        self.assertEqual(proc.call_count, 1)
        self.assertEqual((again.status_code, again.data['code']), (409, 'already_final'))   # one-time use + no re-processing
        self.assertEqual(self.client.get('/api/payments/').data['results'][0]['status'], 'COMPLETED')   # history
        events = self.events(txn_id)
        for expected in ('FRAUD_EVALUATED', 'OTP_REQUESTED', 'OTP_SENT', 'OTP_VERIFIED', 'TRANSACTION_FINALIZED'):
            self.assertIn(expected, events)

    def test_the_code_never_appears_in_api_responses_database_logs_or_history(self):
        with self.assertNoLogs('payments', 'DEBUG'):
            created = self.pay(LOW)
            txn_id = created.data['transaction_id']
            code = code_from(mail.outbox[0])
            self.verify(txn_id, self.wrong_code(code))
            ok = self.verify(txn_id, code)
        blob = ' '.join(json.dumps(x, default=str) for x in (created.data, ok.data, self.client.get('/api/payments/').data,
                                                            list(OneTimeCode.objects.values()),
                                                            list(FraudWorkflowEvent.objects.values()),
                                                            list(PaymentVerification.objects.values())))
        self.assertNotIn(code, blob)
        stored = OneTimeCode.objects.get()
        self.assertEqual((len(stored.code_hash), stored.status), (64, 'USED'))

    def test_malformed_codes_are_rejected_without_using_an_attempt(self):
        txn_id = self.pay(LOW).data['transaction_id']
        for bad in ('', 'abc123', '12345', '1234567', ' '):
            self.assertEqual(self.verify(txn_id, bad).status_code, 400, bad)
        self.assertEqual(OneTimeCode.objects.get().attempts, 0)


# =============================================================== high-risk workflow
class HighRiskWorkflowTests(WorkflowTestCase):
    def test_high_risk_sends_an_alert_not_a_code_and_holds_the_payment(self):
        res = self.pay(HIGH)
        v = res.data['verification']
        self.assertEqual((res.data['status'], v['status'], v['risk_category'], v['next_action']), ('PENDING', 'AWAITING_USER_DECISION', 'HIGH', 'CHOOSE'))
        self.assertTrue(v['can_continue'] and v['can_cancel'] and not v['can_verify'])
        self.assertEqual(v['alert_status'], 'SENT')
        self.assertEqual(len(mail.outbox), 1)
        alert = mail.outbox[0]
        self.assertEqual(alert.to, ['sender@gmail.com'])
        self.assertIn('HIGH RISK', alert.body)
        self.assertIn('does not mean fraud has occurred', alert.body)
        self.assertIn('NOT been completed', alert.body)
        self.assertNotRegex(alert.body, r'\b\d{6}\b')                       # no code in the alert
        self.assertEqual(OneTimeCode.objects.count(), 0)
        self.assertIn('HIGH_RISK_ALERT_SENT', self.events(res.data['transaction_id']))

    def test_codes_cannot_be_entered_or_requested_before_the_user_chooses(self):
        txn_id = self.pay(HIGH).data['transaction_id']
        for action, body in (('verify-otp', {'code': '123456'}), ('resend-otp', {})):
            res = self.act(txn_id, action, body)
            self.assertEqual((res.status_code, res.data['code']), (409, 'not_awaiting_otp'), action)
        self.assertEqual(OneTimeCode.objects.count(), 0)

    def test_continue_sends_a_code_and_the_same_verification_completes_the_payment(self):
        txn_id = self.pay(HIGH).data['transaction_id']
        res = self.act(txn_id, 'continue')
        self.assertEqual((res.status_code, res.data['status'], res.data['verification']['status']), (200, 'PENDING', 'AWAITING_OTP'))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].to, ['sender@gmail.com'])
        done = self.verify(txn_id, code_from(mail.outbox[1]))
        self.assertEqual((done.status_code, done.data['status']), (200, 'COMPLETED'))
        self.assertIn('USER_CHOSE_CONTINUE', self.events(txn_id))
        self.assertEqual(self.act(txn_id, 'continue').status_code, 409)         # choosing twice is refused

    def test_cancel_terminates_and_blocks_all_further_processing(self):
        txn_id = self.pay(HIGH).data['transaction_id']
        res = self.act(txn_id, 'cancel')
        self.assertEqual((res.status_code, res.data['status'], res.data['verification']['status']), (200, 'CANCELLED', 'CANCELLED'))
        self.assertEqual(self.txn(txn_id).status, TransactionStatus.CANCELLED)
        for action, body in (('cancel', {}), ('continue', {}), ('resend-otp', {}), ('verify-otp', {'code': '123456'})):
            self.assertEqual(self.act(txn_id, action, body).status_code, 409, action)   # repeated requests
        self.assertEqual(OneTimeCode.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 1)                                          # only the alert
        self.assertEqual(self.events(txn_id).count('USER_CANCELLED'), 1)

    def test_cancelling_after_continue_invalidates_the_code(self):
        txn_id = self.pay(HIGH).data['transaction_id']
        self.act(txn_id, 'continue')
        code = code_from(mail.outbox[-1])
        self.act(txn_id, 'cancel')
        self.assertEqual(OneTimeCode.objects.get().status, 'INVALIDATED')
        res = self.verify(txn_id, code)
        self.assertEqual((res.status_code, self.txn(txn_id).status), (409, 'CANCELLED'))

    def test_alert_email_failure_is_reported_not_hidden(self):
        with override_settings(EMAIL_BACKEND='payments.test_verification.FailingBackend'), self.assertLogs('payments.notifications', 'ERROR') as logs:
            res = self.pay(HIGH)
        self.assertEqual(res.data['verification']['alert_status'], 'FAILED')
        self.assertIn('HIGH_RISK_ALERT_FAILED', self.events(res.data['transaction_id']))
        self.assertNotIn('hunter2', ' '.join(logs.output) + json.dumps(res.data, default=str))
        self.assertTrue(res.data['verification']['can_continue'])           # the in-app choice is still offered


# =============================================================== prediction unavailable
class UnavailableWorkflowTests(WorkflowTestCase):
    def test_unsupported_method_is_blocked_not_treated_as_low_risk(self):
        res = self.client.post('/api/payments/', {**BASE, **METHOD_PAYLOADS['UPI'], 'recipient_email': 'friend@yahoo.com'},
                               format='json', HTTP_USER_AGENT=CHROME_WIN)
        txn_id = res.data['transaction_id']
        v = res.data['verification']
        self.assertEqual((res.data['status'], v['status'], v['risk_category'], v['next_action']), ('PENDING', 'UNAVAILABLE', 'UNAVAILABLE', 'CANCEL_ONLY'))
        self.assertIn('cannot proceed', v['message'])
        self.assertIsNone(res.data['fraud_analysis']['fraud_probability'])
        self.assertEqual(len(mail.outbox), 0)                              # no misleading low-risk OTP e-mail
        self.assertFalse(v['can_verify'] or v['can_continue'] or v['can_resend'])
        for action, body in (('verify-otp', {'code': '123456'}), ('continue', {}), ('resend-otp', {})):
            self.assertEqual(self.act(txn_id, action, body).status_code, 409, action)
        self.assertEqual(self.txn(txn_id).status, TransactionStatus.PENDING)   # never auto-completed
        events = self.events(txn_id)
        self.assertIn('VERIFICATION_UNAVAILABLE', events)
        self.assertEqual(PaymentVerification.objects.get().reason, 'UNSUPPORTED_PAYMENT_METHOD')

    def test_the_user_can_cancel_a_blocked_payment(self):
        txn_id = self.client.post('/api/payments/', {**BASE, **METHOD_PAYLOADS['WALLET']}, format='json',
                                  HTTP_USER_AGENT=CHROME_WIN).data['transaction_id']
        self.assertEqual(self.act(txn_id, 'cancel').data['status'], 'CANCELLED')

    def test_model_failure_and_missing_configuration_also_block(self):
        with override_settings(FRAUD_INR_PER_USD=None):
            res = self.client.post('/api/payments/', PAYMENT, format='json', HTTP_USER_AGENT=CHROME_WIN)
        self.assertEqual((res.data['status'], res.data['verification']['status']), ('PENDING', 'UNAVAILABLE'))
        with mock.patch('payments.fraud.service.predict', side_effect=RuntimeError('boom')), self.assertLogs('payments', 'ERROR'):
            res = self.client.post('/api/payments/', PAYMENT, format='json', HTTP_USER_AGENT=CHROME_WIN)
        self.assertEqual((res.data['status'], res.data['verification']['status'], res.data['fraud_analysis']['status']), ('PENDING', 'UNAVAILABLE', 'ERROR'))
        self.assertEqual(len(mail.outbox), 0)

    def test_workflow_startup_failure_blocks_instead_of_approving(self):
        with mock.patch('payments.workflow.start_verification', side_effect=RuntimeError('boom')), self.assertLogs('payments.services', 'ERROR'):
            res = self.pay(LOW)
        self.assertEqual((res.status_code, res.data['status'], res.data['verification']['status']), (201, 'PENDING', 'UNAVAILABLE'))
        self.assertEqual(PaymentVerification.objects.get().reason, 'WORKFLOW_ERROR')


# =============================================================== risk category + threshold (real model)
class RiskCategoryTests(WorkflowTestCase):
    def real_payment(self, **overrides):
        return self.client.post('/api/payments/', {**PAYMENT, **overrides}, format='json', HTTP_USER_AGENT=CHROME_WIN)

    def test_real_model_probability_is_compared_with_the_configured_threshold(self):
        with override_settings(HIGH_RISK_THRESHOLD=0.999):
            low = self.real_payment()
        with override_settings(HIGH_RISK_THRESHOLD=1e-9):
            high = self.real_payment()
        self.assertEqual((low.data['verification']['risk_category'], low.data['verification']['status']), ('LOW', 'AWAITING_OTP'))
        self.assertEqual((high.data['verification']['risk_category'], high.data['verification']['status']), ('HIGH', 'AWAITING_USER_DECISION'))
        self.assertGreater(low.data['fraud_analysis']['fraud_probability'], 0)

    def test_probability_equal_to_the_threshold_is_high_risk(self):
        probability = service.predict(prepare_fraud_features(card_txn(self.user, amount=Decimal('250.50')))).fraud_probability
        with override_settings(HIGH_RISK_THRESHOLD=probability):
            res = self.real_payment()
        self.assertEqual(res.data['fraud_analysis']['fraud_probability'], probability)
        self.assertEqual(res.data['verification']['risk_category'], 'HIGH')

    def test_default_threshold_comes_from_phase1_validation(self):
        res = self.real_payment()
        analysis = FraudAnalysis.objects.get()
        self.assertEqual((analysis.threshold_used, analysis.threshold_source), (service.get_bundle().metadata['thresholds']['primary']['threshold'], 'phase1_validation'))
        expected = 'HIGH' if analysis.fraud_probability >= analysis.threshold_used else 'LOW'
        self.assertEqual(res.data['verification']['risk_category'], expected)
        self.assertEqual(analysis.risk_category, expected)

    def test_the_client_cannot_choose_the_risk_category_or_threshold(self):
        res = self.pay(HIGH, payload={**PAYMENT, 'risk_category': 'LOW', 'threshold': 0.99, 'high_risk_threshold': 0.99,
                                        'predicted_class': 0, 'verification_status': 'VERIFIED', 'otp_verified': True})
        self.assertEqual((res.data['verification']['risk_category'], res.data['verification']['status']), ('HIGH', 'AWAITING_USER_DECISION'))
        self.assertEqual(res.data['status'], 'PENDING')

    def test_analysis_without_a_valid_prediction_has_no_risk_category(self):
        txn = card_txn(self.user)
        analysis = FraudAnalysis.objects.create(transaction=txn, status='UNAVAILABLE', failure_category='MODEL_DISABLED')
        self.assertEqual(analysis.risk_category, RiskCategory.UNAVAILABLE)


# =============================================================== OTP security rules
class OtpRuleTests(WorkflowTestCase):
    def test_wrong_codes_are_counted_then_the_code_locks(self):
        txn_id = self.pay(LOW).data['transaction_id']
        code = code_from(mail.outbox[0])
        bad = self.wrong_code(code)
        for left in (4, 3, 2, 1):
            res = self.verify(txn_id, bad)
            self.assertEqual((res.status_code, res.data['code']), (400, 'otp_incorrect'))
            self.assertIn(f'{left} attempt', res.data['detail'])
        locked = self.verify(txn_id, bad)
        self.assertEqual((locked.status_code, locked.data['code']), (400, 'otp_locked'))
        self.assertEqual(OneTimeCode.objects.get().attempts, 5)                 # attempts persisted despite the error responses
        self.assertEqual(self.events(txn_id).count('OTP_FAILED'), 5)
        after = self.verify(txn_id, code)                                      # even the right code is now useless
        self.assertEqual((after.status_code, after.data['code']), (400, 'otp_not_active'))
        self.assertEqual(self.txn(txn_id).status, TransactionStatus.PENDING)

    def test_resend_replaces_the_previous_code(self):
        txn_id = self.pay(LOW).data['transaction_id']
        old = code_from(mail.outbox[0])
        res = self.act(txn_id, 'resend-otp')
        self.assertEqual((res.status_code, len(mail.outbox)), (200, 2))
        new = code_from(mail.outbox[1])
        self.assertEqual(OneTimeCode.objects.filter(status='REPLACED').count(), 1)
        if old != new:
            bad = self.verify(txn_id, old)
            self.assertEqual(bad.data['code'], 'otp_incorrect')                 # the replaced code no longer works
        self.assertEqual(self.verify(txn_id, new).data['status'], 'COMPLETED')

    def test_expired_code_is_refused_and_a_new_one_can_be_requested(self):
        txn_id = self.pay(LOW).data['transaction_id']
        code = code_from(mail.outbox[0])
        OneTimeCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        res = self.verify(txn_id, code)
        self.assertEqual((res.status_code, res.data['code']), (400, 'otp_expired'))
        self.assertIn('OTP_EXPIRED', self.events(txn_id))
        self.assertEqual(self.act(txn_id, 'resend-otp').status_code, 200)
        self.assertEqual(self.verify(txn_id, code_from(mail.outbox[1])).data['status'], 'COMPLETED')

    @override_settings(OTP_RESEND_COOLDOWN_SECONDS=60)
    def test_resend_cooldown(self):
        txn_id = self.pay(LOW).data['transaction_id']
        res = self.act(txn_id, 'resend-otp')
        self.assertEqual((res.status_code, res.data['code']), (429, 'resend_cooldown'))
        self.assertTrue(0 < int(res['Retry-After']) <= 61)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIsNotNone(res.data['verification']['otp']['resend_available_at'])

    @override_settings(OTP_MAX_RESENDS=2)
    def test_resend_limit(self):
        txn_id = self.pay(LOW).data['transaction_id']
        self.assertEqual(self.act(txn_id, 'resend-otp').status_code, 200)
        self.assertEqual(self.act(txn_id, 'resend-otp').status_code, 200)
        res = self.act(txn_id, 'resend-otp')
        self.assertEqual((res.status_code, res.data['code']), (429, 'resend_limit_reached'))
        self.assertEqual((len(mail.outbox), res.data['verification']['otp']['resends_remaining']), (3, 0))

    @override_settings(OTP_MAX_RESENDS=1, OTP_MAX_ATTEMPTS=2)
    def test_exhausting_every_code_fails_the_verification_and_the_payment(self):
        txn_id = self.pay(LOW).data['transaction_id']
        bad = self.wrong_code(code_from(mail.outbox[0]))
        self.verify(txn_id, bad); self.verify(txn_id, bad)                      # first code locked
        self.act(txn_id, 'resend-otp')
        bad2 = self.wrong_code(code_from(mail.outbox[1]))
        self.verify(txn_id, bad2)
        last = self.verify(txn_id, bad2)
        self.assertEqual((last.status_code, last.data['code']), (409, 'verification_failed'))
        self.assertEqual((self.txn(txn_id).status, PaymentVerification.objects.get().status), ('FAILED', 'FAILED'))
        self.assertIn('VERIFICATION_FAILED', self.events(txn_id))
        self.assertEqual(self.act(txn_id, 'resend-otp').status_code, 409)

    @override_settings(OTP_MAX_PER_USER_PER_HOUR=2)
    def test_per_user_hourly_code_limit_spans_transactions(self):
        self.pay(LOW); self.pay(LOW)
        third = self.pay(LOW)
        self.assertEqual(len(mail.outbox), 2)                                  # no third e-mail
        self.assertEqual(third.data['verification']['otp']['delivery'], 'NOT_SENT')
        res = self.act(third.data['transaction_id'], 'resend-otp')
        self.assertEqual((res.status_code, res.data['code']), (429, 'rate_limited'))

    def test_a_code_works_only_for_its_own_transaction_and_user(self):
        a = self.pay(LOW).data['transaction_id']; code_a = code_from(mail.outbox[0])
        b = self.pay(LOW).data['transaction_id']; code_b = code_from(mail.outbox[1])
        if code_a != code_b:
            self.assertEqual(self.verify(b, code_a).data['code'], 'otp_incorrect')   # other transaction, same user
        intruder = self.other_client()
        self.assertEqual(self.verify(a, code_a, intruder).status_code, 404)           # other user
        self.assertEqual(self.txn(a).status, TransactionStatus.PENDING)


# =============================================================== e-mail failures
class EmailFailureTests(WorkflowTestCase):
    def test_a_failed_code_email_is_never_reported_as_sent(self):
        with override_settings(EMAIL_BACKEND='payments.test_verification.FailingBackend'), self.assertLogs('payments.notifications', 'ERROR') as logs:
            res = self.pay(LOW)
        v = res.data['verification']
        self.assertEqual((res.status_code, res.data['status'], v['status']), (201, 'PENDING', 'AWAITING_OTP'))
        self.assertEqual(v['otp']['delivery'], 'FAILED')
        self.assertFalse(v['can_verify'])
        self.assertTrue(v['can_resend'])
        self.assertIn("couldn't send", v['message'])
        self.assertNotIn('e-mailed', v['message'])                           # no claim that anything was sent
        self.assertEqual(OneTimeCode.objects.get().status, 'INVALIDATED')       # an undelivered code is unusable
        self.assertIn('OTP_SEND_FAILED', self.events(res.data['transaction_id']))
        self.assertNotIn('OTP_SENT', self.events(res.data['transaction_id']))
        for secret in ('hunter2', 'smtp.secret', '535'):                       # credentials / server text: nowhere
            self.assertNotIn(secret, ' '.join(logs.output) + json.dumps(res.data, default=str))
        self.assertNotIn('SMTPException', json.dumps(res.data, default=str))    # internals: never in the API response
        # once mail works the user can ask again
        self.assertEqual(self.act(res.data['transaction_id'], 'resend-otp').status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_continue_reports_email_failure_with_503_and_stays_retryable(self):
        txn_id = self.pay(HIGH).data['transaction_id']
        with override_settings(EMAIL_BACKEND='payments.test_verification.FailingBackend'), self.assertLogs('payments.notifications', 'ERROR'):
            res = self.act(txn_id, 'continue')
        self.assertEqual((res.status_code, res.data['code']), (503, 'email_failed'))
        self.assertNotIn('hunter2', json.dumps(res.data, default=str))
        self.assertEqual(res.data['verification']['status'], 'AWAITING_OTP')
        self.assertEqual(self.act(txn_id, 'resend-otp').status_code, 200)

    def test_account_without_an_email_address_cannot_receive_a_code(self):
        self.user.email = ''; self.user.save()
        with self.assertLogs('payments.notifications', 'ERROR'):
            res = self.pay(LOW)
        self.assertEqual(res.data['verification']['otp']['delivery'], 'FAILED')
        self.assertEqual(len(mail.outbox), 0)


# =============================================================== details changed, window, replay
class IntegrityTests(WorkflowTestCase):
    def test_changing_details_after_the_code_was_sent_invalidates_verification(self):
        for field, value in (('amount', Decimal('9999.00')), ('recipient_email', 'attacker@yahoo.com'),
                             ('card_network', 'MASTERCARD'), ('recipient_name', 'Someone Else')):
            mail.outbox.clear()
            txn_id = self.pay(LOW).data['transaction_id']
            code = code_from(mail.outbox[0])
            Transaction.objects.filter(transaction_id=txn_id).update(**{field: value})
            res = self.verify(txn_id, code)                                       # the code itself is correct
            self.assertEqual((res.status_code, res.data['code']), (409, 'details_changed'), field)
            txn = self.txn(txn_id)
            self.assertEqual(txn.status, TransactionStatus.CANCELLED, field)
            self.assertEqual(txn.verification.status, 'INVALIDATED')
            self.assertEqual(txn.verification.codes.get().status, 'INVALIDATED')
            self.assertIn('DETAILS_CHANGED', self.events(txn_id))
            self.assertEqual(self.verify(txn_id, code).status_code, 409)

    def test_changing_details_before_continue_is_caught_too(self):
        txn_id = self.pay(HIGH).data['transaction_id']
        Transaction.objects.filter(transaction_id=txn_id).update(amount=Decimal('1.00'))
        res = self.act(txn_id, 'continue')
        self.assertEqual((res.status_code, res.data['code']), (409, 'details_changed'))
        self.assertEqual(OneTimeCode.objects.count(), 0)

    def test_the_verification_window_expires_the_payment(self):
        txn_id = self.pay(LOW).data['transaction_id']
        code = code_from(mail.outbox[0])
        PaymentVerification.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        res = self.verify(txn_id, code)
        self.assertEqual((res.status_code, res.data['code']), (409, 'verification_expired'))
        self.assertEqual(self.txn(txn_id).status, TransactionStatus.CANCELLED)

    def test_sweep_command_closes_stale_pending_payments(self):
        stale = self.pay(HIGH).data['transaction_id']
        fresh = self.pay(HIGH).data['transaction_id']
        PaymentVerification.objects.filter(transaction__transaction_id=stale).update(expires_at=timezone.now() - timedelta(seconds=1))
        call_command('expire_verifications', stdout=mock.MagicMock())
        self.assertEqual((self.txn(stale).status, self.txn(fresh).status), ('CANCELLED', 'PENDING'))

    def test_replayed_submission_does_not_send_another_email_or_restart_the_workflow(self):
        first = self.pay(LOW, key='replay-key-0001')
        second = self.pay(LOW, key='replay-key-0001')
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(OneTimeCode.objects.count(), 1)
        self.assertEqual(second.data['verification']['status'], 'AWAITING_OTP')

    def test_three_statuses_stay_separate(self):
        txn_id = self.pay(HIGH).data['transaction_id']
        analysis = FraudAnalysis.objects.get().predicted_class
        self.assertEqual((self.txn(txn_id).status, FraudAnalysis.objects.get().status, PaymentVerification.objects.get().status),
                         ('PENDING', 'EVALUATED', 'AWAITING_USER_DECISION'))
        self.act(txn_id, 'cancel')
        self.assertEqual((self.txn(txn_id).status, FraudAnalysis.objects.get().status, FraudAnalysis.objects.get().predicted_class),
                         ('CANCELLED', 'EVALUATED', analysis))                   # cancelling does not rewrite the model result
        self.assertEqual(self.txn(txn_id).fraud_status, 'NOT_CHECKED')


# =============================================================== authorization
class AuthorizationTests(WorkflowTestCase):
    def test_every_action_requires_login_and_ownership(self):
        txn_id = self.pay(HIGH).data['transaction_id']
        anon, intruder = APIClient(), self.other_client()
        for action, body in (('continue', {}), ('cancel', {}), ('resend-otp', {}), ('verify-otp', {'code': '123456'})):
            self.assertIn(self.act(txn_id, action, body, anon).status_code, (401, 403), action)
            self.assertEqual(self.act(txn_id, action, body, intruder).status_code, 404, action)
        self.assertEqual(intruder.get(f'/api/payments/{txn_id}/').status_code, 404)
        self.assertEqual(self.txn(txn_id).status, TransactionStatus.PENDING)
        self.assertEqual(PaymentVerification.objects.get().status, 'AWAITING_USER_DECISION')

    def test_a_superuser_has_no_user_level_access_to_someone_elses_payment(self):
        txn_id = self.pay(HIGH).data['transaction_id']
        boss = User.objects.create_superuser('boss', 'boss@gmail.com', 'Str0ng-Passw0rd!')
        c = APIClient(); c.force_login(boss)
        self.assertEqual(self.act(txn_id, 'cancel', client=c).status_code, 404)


# =============================================================== currency (INR stays INR)
class CurrencyHandlingTests(WorkflowTestCase):
    def test_conversion_happens_once_inside_the_mapper_and_never_touches_the_stored_amount(self):
        res = self.client.post('/api/payments/', {**PAYMENT, 'amount': '4250.00'}, format='json', HTTP_USER_AGENT=CHROME_WIN)
        txn = self.txn(res.data['transaction_id'])
        self.assertEqual((txn.amount, txn.currency), (Decimal('4250.00'), 'INR'))
        self.assertEqual((res.data['amount'], res.data['currency']), ('4250.00', 'INR'))
        bundle = service.get_bundle()
        row = AlignedFeatureMapper(RATE, bundle.vocabulary, bundle.input_columns).to_model_row(prepare_fraud_features(txn))
        self.assertAlmostEqual(row['TransactionAmt'], 50.0)                     # 4250 / 85, converted exactly once
        self.assertEqual(txn.amount, Decimal('4250.00'))                        # mapping did not mutate the record
        from .fraud.analysis import run_fraud_analysis
        run_fraud_analysis(txn)                                                 # running the analysis again changes nothing
        txn.refresh_from_db()
        self.assertEqual((txn.amount, txn.currency), (Decimal('4250.00'), 'INR'))

    def test_the_model_receives_usd_equivalent_amounts_that_follow_the_configured_rate(self):
        txn = card_txn(self.user, amount=Decimal('8500.00'))
        bundle = service.get_bundle()
        for rate, expected in ((Decimal('85'), 100.0), (Decimal('100'), 85.0)):
            row = AlignedFeatureMapper(rate, bundle.vocabulary, bundle.input_columns).to_model_row(prepare_fraud_features(txn))
            self.assertAlmostEqual(row['TransactionAmt'], expected)
        self.assertEqual(Transaction.objects.get(pk=txn.pk).amount, Decimal('8500.00'))

    def test_the_email_and_receipt_show_inr(self):
        res = self.pay(LOW, payload={**PAYMENT, 'amount': '4250.00'})
        self.assertIn('INR 4,250.00', mail.outbox[0].body)
        self.assertEqual(res.data['currency'], 'INR')


# =============================================================== admin dashboard
class AdminFraudResponseTests(WorkflowTestCase):
    def setUp(self):
        super().setUp()
        self.boss = User.objects.create_superuser('boss', 'boss@gmail.com', 'Str0ng-Passw0rd!')
        self.admin = APIClient(); self.admin.force_login(self.boss)
        self.low_waiting = self.pay(LOW).data['transaction_id']
        self.low_done = self.pay(LOW).data['transaction_id']
        self.verify(self.low_done, self.wrong_code(code_from(mail.outbox[-1])))          # one incorrect attempt
        self.verify(self.low_done, code_from(mail.outbox[-1]))
        self.high_waiting = self.pay(HIGH).data['transaction_id']
        self.high_cancelled = self.pay(HIGH).data['transaction_id']; self.act(self.high_cancelled, 'cancel')
        self.high_continued = self.pay(HIGH).data['transaction_id']; self.act(self.high_continued, 'continue')
        self.blocked = self.client.post('/api/payments/', {**BASE, **METHOD_PAYLOADS['UPI']}, format='json',
                                        HTTP_USER_AGENT=CHROME_WIN).data['transaction_id']
        self.stats = self.admin.get('/api/admin/fraud-statistics/').data['fraud_response']

    def test_counts_reflect_real_workflow_records(self):
        s = self.stats
        self.assertEqual(s['total_transactions'], 6)
        self.assertEqual(s['awaiting'], {'low_risk_awaiting_otp': 1, 'high_risk_awaiting_user_decision': 1,
                                         'high_risk_awaiting_otp_after_continue': 1, 'prediction_unavailable_blocked': 1})
        self.assertEqual(s['outcomes'], {'verified': 1, 'cancelled_by_user': 1, 'failed': 0, 'expired': 0, 'invalidated_details_changed': 0})
        self.assertEqual(s['risk_categories'], {'low': 2, 'high': 3, 'unavailable': 1})
        self.assertEqual(s['high_risk'], {'alerts_emailed': 3, 'alert_delivery_failed': 0, 'user_chose_continue': 1})
        self.assertEqual((s['otp']['codes_issued'], s['otp']['emails_delivered'], s['otp']['codes_used'], s['otp']['incorrect_attempts']), (3, 3, 1, 1))
        self.assertEqual(s['without_workflow_record'], 0)

    def test_series_counts_events_per_period(self):
        totals = {k: sum(p[k] for p in self.stats['series']) for k in ('high_risk_alerts', 'otp_verified', 'otp_failed', 'cancelled', 'unavailable')}
        self.assertEqual(totals, {'high_risk_alerts': 3, 'otp_verified': 1, 'otp_failed': 1, 'cancelled': 1, 'unavailable': 1})

    def test_no_otp_values_or_model_metrics_are_exposed(self):
        data = self.admin.get('/api/admin/fraud-statistics/').data
        text = json.dumps(data, default=str).lower()
        for word in ('code_hash', '"salt"', '"accuracy"', '"precision"', '"recall"', '"roc_auc"', '"pr_auc"', '"f1"'):
            self.assertNotIn(word, text)
        detail = self.admin.get(f'/api/admin/transactions/{self.low_done}/').data
        self.assertEqual(detail['verification']['status'], 'VERIFIED')
        events = [e['event_type'] for e in detail['workflow_events']]
        self.assertEqual(events[0], 'FRAUD_EVALUATED')
        self.assertIn('OTP_VERIFIED', events)
        blob = json.dumps(detail, default=str)
        for real_code in [code_from(m) for m in mail.outbox if 'verification code is' in m.body]:
            self.assertNotIn(real_code, blob)
        self.assertNotIn('code_hash', blob)

    def test_only_superusers_may_see_it(self):
        for client in (self.client, APIClient()):
            self.assertEqual(client.get('/api/admin/fraud-statistics/').status_code, 403)
            self.assertEqual(client.get(f'/api/admin/transactions/{self.low_done}/').status_code, 403)

    def test_report_includes_the_response_section(self):
        data = self.admin.get('/api/admin/reports/fraud-monitoring/').data
        section = next(s for s in data['sections'] if s['title'].startswith('Fraud response'))
        rows = dict(section['rows'])
        self.assertEqual((rows['Verified with a one-time code'], rows['Cancelled by the user'], rows['Incorrect code attempts']), (1, 1, 1))
