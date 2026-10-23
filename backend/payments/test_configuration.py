"""Configuration loading, conversion-rate safety and e-mail delivery handling.

No real e-mail is ever sent: SMTP is replaced by mocks, and the console backend writes to a captured stream.
"""
import io
import json
import os
import smtplib
import socket
import tempfile
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.checks import run_checks
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMessage
from django.test import SimpleTestCase, TestCase, override_settings

from config import settings as project_settings
from config.envloader import load_env_file
from adminpanel.monitoring.model_status import get_model_status
from .fraud import service
from .fraud.analysis import run_fraud_analysis
from .fraud.errors import FailureCategory as F
from .models import FraudAnalysis, OneTimeCode, Transaction
from .test_fraud import card_txn
from .test_verification import PAYMENT, RATE, WorkflowTestCase
from .testing import LOW, HIGH

User = get_user_model()
SMTP_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
SECRET = 'app-password-do-not-log'


# ------------------------------------------------------------------------- .env loading and precedence
class EnvLoaderTests(SimpleTestCase):
    def write(self, text, binary=None):
        handle = tempfile.NamedTemporaryFile('wb', suffix='.env', delete=False)
        handle.write(binary if binary is not None else text.encode())
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def load(self, path, env):
        with mock.patch.dict(os.environ, env, clear=True):
            report = load_env_file(path)
            return report, dict(os.environ)

    def test_value_comes_from_the_env_file_when_the_environment_does_not_define_it(self):
        report, env = self.load(self.write('FRAUD_INR_PER_USD=85\n'), {})
        self.assertEqual(env['FRAUD_INR_PER_USD'], '85')
        self.assertEqual(report['applied'], ['FRAUD_INR_PER_USD'])

    def test_a_non_empty_environment_variable_wins_over_the_file(self):
        report, env = self.load(self.write('FRAUD_INR_PER_USD=85\n'), {'FRAUD_INR_PER_USD': '90'})
        self.assertEqual(env['FRAUD_INR_PER_USD'], '90')
        self.assertEqual(report['kept_from_environment'], ['FRAUD_INR_PER_USD'])

    def test_an_empty_inherited_variable_no_longer_hides_the_file_value(self):
        """The reproduced cause of `FRAUD_INR_PER_USD: None`: python-dotenv keeps an existing EMPTY variable."""
        for empty in ('', '   '):
            _, env = self.load(self.write('FRAUD_INR_PER_USD=85\n'), {'FRAUD_INR_PER_USD': empty})
            self.assertEqual(env['FRAUD_INR_PER_USD'], '85')

    def test_bom_crlf_and_blank_values_are_handled(self):
        path = self.write('', binary=b'\xef\xbb\xbfFRAUD_INR_PER_USD=85\r\nHIGH_RISK_THRESHOLD=\r\n')
        _, env = self.load(path, {})
        self.assertEqual((env['FRAUD_INR_PER_USD'], env['HIGH_RISK_THRESHOLD']), ('85', ''))

    def test_a_missing_file_is_reported_not_fatal(self):
        report, env = self.load('/nonexistent/dir/.env', {})
        self.assertFalse(report['found'])
        self.assertNotIn('FRAUD_INR_PER_USD', env)

    def test_the_report_never_contains_values(self):
        report, _ = self.load(self.write(f'EMAIL_HOST_PASSWORD={SECRET}\n'), {})
        self.assertNotIn(SECRET, json.dumps(report))

    def test_settings_use_the_backend_directory_env_file(self):
        self.assertEqual(Path(project_settings.ENV_FILE_REPORT['path']), project_settings.BASE_DIR / '.env')


class ConversionRateSettingTests(SimpleTestCase):
    def rate(self, value):
        env = {} if value is None else {'FRAUD_INR_PER_USD': value}
        with mock.patch.dict(os.environ, env, clear=True):
            return project_settings._fraud_conversion_rate()

    def test_valid_rates_become_decimals(self):
        self.assertEqual(self.rate('85'), (Decimal('85'), None))
        self.assertEqual(self.rate(' 83.5 '), (Decimal('83.5'), None))

    def test_missing_empty_malformed_zero_negative_and_non_finite_rates_are_ignored_not_guessed(self):
        for bad in (None, '', '   ', 'abc', '85 INR', '"85"', '0', '-1', '-85', 'NaN', 'Infinity', '1e9', '10000'):
            value, problem = self.rate(bad)
            self.assertIsNone(value, bad)
            self.assertTrue(problem, bad)

    def test_the_optional_threshold_keeps_its_validation(self):
        with mock.patch.dict(os.environ, {'HIGH_RISK_THRESHOLD': '1.5'}, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                project_settings._optional_number('HIGH_RISK_THRESHOLD', float, 0.0, 1.0)
        with mock.patch.dict(os.environ, {'HIGH_RISK_THRESHOLD': 'nan'}, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                project_settings._optional_number('HIGH_RISK_THRESHOLD', float, 0.0, 1.0)
        with mock.patch.dict(os.environ, {'HIGH_RISK_THRESHOLD': ''}, clear=True):
            self.assertIsNone(project_settings._optional_number('HIGH_RISK_THRESHOLD', float, 0.0, 1.0))


class UnavailableWithoutRateTests(TestCase):
    """A missing/invalid rate keeps fraud analysis unavailable. It never approves or scores anything."""

    def setUp(self):
        service.reset_cache()
        self.addCleanup(service.reset_cache)
        self.user = User.objects.create_user('sender@gmail.com', 'sender@gmail.com', 'x', first_name='Sam')

    @override_settings(FRAUD_MODEL_ENABLED=True, FRAUD_INR_PER_USD=None, HIGH_RISK_THRESHOLD=None)
    def test_no_rate_means_unavailable_with_a_clear_sanitised_message_and_an_unchanged_amount(self):
        txn = card_txn(self.user, amount=Decimal('4250.00'))
        run_fraud_analysis(txn)
        analysis = FraudAnalysis.objects.get(transaction=txn)
        self.assertEqual((analysis.status, analysis.failure_category), ('UNAVAILABLE', F.CONVERSION_RATE_NOT_CONFIGURED))
        self.assertIsNone(analysis.fraud_probability)                       # no fabricated score
        self.assertEqual(Transaction.objects.get(pk=txn.pk).amount, Decimal('4250.00'))
        status = get_model_status()
        self.assertEqual((status['ready'], status['status']), (False, 'Not configured'))

    @override_settings(FRAUD_MODEL_ENABLED=True, FRAUD_INR_PER_USD=RATE, HIGH_RISK_THRESHOLD=None)
    def test_with_the_rate_the_model_loads_and_the_status_is_ready(self):
        status = get_model_status()
        self.assertEqual((status['ready'], status['status']), (True, 'Ready'))
        self.assertNotIn('85', json.dumps(status))                           # the status never echoes configuration

    @override_settings(FRAUD_MODEL_ENABLED=True, FRAUD_INR_PER_USD=None)
    def test_the_configuration_check_explains_the_problem_without_values(self):
        warnings = [m for m in run_checks() if m.id == 'payments.W001']
        self.assertEqual(len(warnings), 1)
        self.assertIn('FRAUD_INR_PER_USD', warnings[0].msg)

    @override_settings(FRAUD_MODEL_ENABLED=True, FRAUD_INR_PER_USD=RATE)
    def test_no_check_warning_when_configured(self):
        self.assertFalse([m for m in run_checks() if m.id == 'payments.W001'])


# ------------------------------------------------------------------------- e-mail configuration checks
class EmailCheckTests(SimpleTestCase):
    def ids(self, **overrides):
        with override_settings(**overrides):
            return {m.id for m in run_checks()}

    def test_a_development_backend_is_an_error_when_debug_is_off(self):
        self.assertIn('payments.E001', self.ids(DEBUG=False, EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend'))
        self.assertNotIn('payments.E001', self.ids(DEBUG=True, EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend'))

    def test_smtp_without_credentials_is_flagged(self):
        self.assertIn('payments.W002', self.ids(EMAIL_BACKEND=SMTP_BACKEND, EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD=''))
        self.assertNotIn('payments.W002', self.ids(EMAIL_BACKEND=SMTP_BACKEND, EMAIL_HOST_USER='a@gmail.com', EMAIL_HOST_PASSWORD='x',
                                                  EMAIL_HOST='smtp.gmail.com', DEFAULT_FROM_EMAIL='a@gmail.com'))

    def test_a_gmail_sender_that_differs_from_the_account_is_flagged(self):
        base = dict(EMAIL_BACKEND=SMTP_BACKEND, EMAIL_HOST='smtp.gmail.com', EMAIL_HOST_USER='a@gmail.com', EMAIL_HOST_PASSWORD='x')
        self.assertIn('payments.W003', self.ids(**base, DEFAULT_FROM_EMAIL='PaySafe <no-reply@paysafe.local>'))
        self.assertNotIn('payments.W003', self.ids(**base, DEFAULT_FROM_EMAIL='PaySafe <A@gmail.com>'))


# ------------------------------------------------------------------------- development console backend
class ConsoleBackendTests(SimpleTestCase):
    @override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend',
                       DEFAULT_FROM_EMAIL='PaySafe <no-reply@paysafe.local>')
    def test_console_backend_prints_the_message_to_the_terminal(self):
        out = io.StringIO()
        with redirect_stdout(out):
            sent = EmailMessage('Your PaySafe verification code', 'code is: 123456', to=['sender@gmail.com']).send()
        self.assertEqual(sent, 1)
        text = out.getvalue()
        for expected in ('Subject: Your PaySafe verification code', 'From: PaySafe <no-reply@paysafe.local>',
                         'To: sender@gmail.com', '123456'):
            self.assertIn(expected, text)


# ------------------------------------------------------------------------- SMTP failures
class SmtpFailureTests(WorkflowTestCase):
    FAILURES = {
        'authentication': smtplib.SMTPAuthenticationError(535, f'5.7.8 Username and Password not accepted {SECRET}'),
        'connection': ConnectionRefusedError(111, f'refused smtp.internal.example {SECRET}'),
        'timeout': socket.timeout(f'timed out talking to smtp.internal.example {SECRET}'),
        'disconnected': smtplib.SMTPServerDisconnected(f'Connection unexpectedly closed {SECRET}'),
        'recipient refused': smtplib.SMTPRecipientsRefused({'sender@gmail.com': (550, SECRET.encode())}),
        'generic': smtplib.SMTPException(SECRET),
    }

    def run_failure(self, error, payload_probability):
        with override_settings(EMAIL_BACKEND=SMTP_BACKEND, EMAIL_HOST_PASSWORD=SECRET), \
                mock.patch('django.core.mail.backends.smtp.EmailBackend.send_messages', side_effect=error), \
                mock.patch('payments.otp.generate_code', return_value='654321'), \
                self.assertLogs('payments.notifications', 'ERROR') as logs:
            res = self.pay(payload_probability)
        return res, ' '.join(logs.output) + json.dumps(res.data, default=str)

    def test_every_failure_kind_is_reported_as_failed_and_leaves_no_usable_code(self):
        for name, error in self.FAILURES.items():
            with self.subTest(name):
                OneTimeCode.objects.all().delete()
                res, visible = self.run_failure(error, LOW)
                v = res.data['verification']
                self.assertEqual((res.status_code, res.data['status']), (201, 'PENDING'))
                self.assertEqual(v['otp']['delivery'], 'FAILED')
                self.assertFalse(v['can_verify'])
                self.assertEqual([c.status for c in OneTimeCode.objects.all()], ['INVALIDATED'])
                self.assertEqual(self.verify(res.data['transaction_id'], '654321').status_code, 400)   # the code does not work
                for leaked in (SECRET, '654321', 'internal.example', 'Traceback'):
                    self.assertNotIn(leaked, visible)

    def test_alert_failure_is_flagged_and_leaks_nothing(self):
        res, visible = self.run_failure(self.FAILURES['timeout'], HIGH)
        self.assertEqual(res.data['verification']['alert_status'], 'FAILED')
        self.assertNotIn(SECRET, visible)

    def test_failure_kinds_are_logged_as_labels_only(self):
        _, visible = self.run_failure(self.FAILURES['authentication'], LOW)
        self.assertIn('smtp_authentication', visible)
        _, visible = self.run_failure(self.FAILURES['timeout'], LOW)
        self.assertIn('timeout', visible)

    def test_an_invalid_registered_address_is_never_sent_to(self):
        for bad in ('not-an-address', 'a b@c.com', 'x@'):
            self.user.email = bad
            self.user.save()
            mail.outbox.clear()
            with self.assertLogs('payments.notifications', 'ERROR'):
                res = self.pay(LOW)
            self.assertEqual((len(mail.outbox), res.data['verification']['otp']['delivery']), (0, 'FAILED'))


# ------------------------------------------------------------------------- recipients and secrets on success
class RecipientAndSecretTests(WorkflowTestCase):
    def test_otp_and_alert_go_only_to_the_registered_address_even_if_the_form_names_another(self):
        self.user.email = 'registered@gmail.com'
        self.user.save()
        payload = {**PAYMENT, 'recipient_email': 'attacker@yahoo.com'}
        low = self.pay(LOW, payload=payload)
        high = self.pay(HIGH, payload=payload)
        self.assertEqual(len(mail.outbox), 2)
        for message in mail.outbox:
            self.assertEqual(message.to, ['registered@gmail.com'])
            self.assertNotIn('attacker@yahoo.com', message.to + message.cc + message.bcc)
        self.assertEqual(low.status_code, 201)
        self.assertEqual(high.status_code, 201)

    def test_api_responses_never_contain_the_code_or_secrets(self):
        with override_settings(EMAIL_HOST_PASSWORD=SECRET), mock.patch('payments.otp.generate_code', return_value='246810'):
            res = self.pay(LOW)
            body = json.dumps(res.data, default=str) + json.dumps(
                self.client.get(f"/api/payments/{res.data['transaction_id']}/").data, default=str)
        self.assertIn('246810', mail.outbox[0].body)                         # the e-mail has it ...
        self.assertNotIn('246810', body)                                     # ... the API never does
        self.assertNotIn(SECRET, body)

    def test_amount_is_unchanged_after_payment_processing(self):
        res = self.pay(LOW, payload={**PAYMENT, 'amount': '4250.00'})
        from .testing import code_from
        done = self.verify(res.data['transaction_id'], code_from(mail.outbox[0]))
        txn = Transaction.objects.get(transaction_id=res.data['transaction_id'])
        self.assertEqual((done.data['status'], txn.amount, txn.currency), ('COMPLETED', Decimal('4250.00'), 'INR'))
