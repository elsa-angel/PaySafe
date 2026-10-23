from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction as db_transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .device import parse_user_agent
from .fraud import (
    FeatureMappingNotConfigured,
    build_model_row,
    compute_history_features,
    prepare_fraud_features,
)
from .models import FraudStatus, Transaction, TransactionStatus
from .services import PaymentProcessingError
from .testing import LOW, code_from, force_prediction
from django.core import mail

User = get_user_model()
FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])

CHROME_WIN = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
IPAD = 'Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36'
ANDROID_TABLET = 'Mozilla/5.0 (Linux; Android 13; SM-X700) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
FIREFOX_LINUX = 'Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0'
EDGE_MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0'

_NOW = timezone.now()
FUTURE_EXPIRY = f'{_NOW.month:02d}/{(_NOW.year + 3) % 100:02d}'
TEST_CARD = '4111 1111 1111 1111'  # the standard Visa test number (passes the Luhn check)

METHOD_PAYLOADS = {
    'CARD': {'payment_method': 'CARD', 'card_network': 'VISA', 'cardholder_name': 'Ravi Kumar',
             'card_number': TEST_CARD, 'card_expiry': FUTURE_EXPIRY, 'card_cvv': '123'},
    'UPI': {'payment_method': 'UPI', 'upi_provider': 'GOOGLE_PAY', 'upi_id': 'Ravi.K@okhdfc'},
    'BANK_TRANSFER': {'payment_method': 'BANK_TRANSFER', 'bank_name': 'HDFC', 'account_holder_name': 'Ravi Kumar',
                      'account_number': '123456789012', 'confirm_account_number': '123456789012', 'ifsc_code': 'hdfc0001234'},
    'WALLET': {'payment_method': 'WALLET', 'wallet_provider': 'PAYTM', 'wallet_identifier_type': 'MOBILE',
               'wallet_identifier': '+91 98765 43210'},
}
COMMON = {'amount': '250.50', 'recipient_name': 'Ravi Kumar', 'recipient_email': 'Ravi@Example.com', 'description': 'Rent'}
BASE = {**COMMON, **METHOD_PAYLOADS['CARD']}


def make_user(email):
    return User.objects.create_user(username=email, email=email, password='Str0ng-Passw0rd!', first_name='Test User')


def make_txn(user, **overrides):
    fields = dict(
        user=user, recipient_name='Ravi', recipient_email='ravi@example.com', amount=Decimal('100.00'),
        payment_method='CARD', card_network='VISA', status=TransactionStatus.COMPLETED,
    )
    fields.update(overrides)
    return Transaction.objects.create(**fields)


@FAST_HASH
class PaymentApiTestCase(TestCase):
    url = '/api/payments/'

    def setUp(self):
        cache.clear()
        self.user = make_user('asha@example.com')
        self.other = make_user('other@example.com')
        self.client = APIClient()
        self.client.force_login(self.user)

    def pay(self, user_agent=CHROME_WIN, key=None, **overrides):
        body = {**BASE, **overrides}
        extra = {'HTTP_USER_AGENT': user_agent}
        if key:
            extra['HTTP_IDEMPOTENCY_KEY'] = key
        return self.client.post(self.url, body, format='json', **extra)


class AuthenticationTests(PaymentApiTestCase):
    def test_endpoints_require_authentication(self):
        anon = APIClient()
        txn = make_txn(self.user)
        self.assertIn(anon.get(self.url).status_code, (401, 403))
        self.assertIn(anon.post(self.url, BASE, format='json').status_code, (401, 403))
        self.assertIn(anon.get(f'{self.url}{txn.transaction_id}/').status_code, (401, 403))
        self.assertEqual(Transaction.objects.count(), 1)

    def test_csrf_enforced_for_signed_in_users(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        res = client.post(self.url, BASE, format='json')
        self.assertEqual(res.status_code, 403)
        self.assertEqual(Transaction.objects.count(), 0)


class CreatePaymentTests(PaymentApiTestCase):
    def test_every_payment_method_creates_a_pending_payment_awaiting_verification(self):
        for method, extra in METHOD_PAYLOADS.items():
            res = self.pay(**extra)
            self.assertEqual(res.status_code, 201, (method, res.data))
            txn = Transaction.objects.get(transaction_id=res.data['transaction_id'])
            self.assertEqual(txn.status, TransactionStatus.PENDING)  # never completed before verification
            self.assertEqual(res.data['status'], 'PENDING')
            self.assertEqual(txn.payment_method, method)
            self.assertEqual(txn.user, self.user)
            self.assertEqual(txn.fraud_status, FraudStatus.NOT_CHECKED)
            self.assertIsNone(txn.fraud_probability)
            self.assertEqual(txn.model_version, '')
            self.assertEqual(txn.amount, Decimal('250.50'))
            self.assertEqual(txn.recipient_email, 'ravi@example.com')
        self.assertEqual(Transaction.objects.count(), 4)

    def test_fields_for_other_methods_are_ignored_and_never_stored(self):
        res = self.pay(**METHOD_PAYLOADS['UPI'], card_number=TEST_CARD, card_cvv='123', bank_name='HDFC',
                       account_number='123456789012', wallet_provider='PAYTM', wallet_identifier='9876543210')
        self.assertEqual(res.status_code, 201)
        txn = Transaction.objects.get(transaction_id=res.data['transaction_id'])
        self.assertEqual((txn.upi_id, txn.upi_provider), ('ravi.k@okhdfc', 'GOOGLE_PAY'))
        for column in ('card_network', 'bank_name', 'wallet_provider', 'wallet_identifier_type', 'masked_reference', 'ifsc_code'):
            self.assertEqual(getattr(txn, column), '', column)

    def test_client_cannot_set_sender_id_status_or_fraud_fields(self):
        res = self.pay(user=self.other.pk, user_id=self.other.pk, sender='x', transaction_id='PS-HACKED000000',
                       status='FAILED', fraud_status='FRAUDULENT', fraud_probability=0.99, device_type='DESKTOP')
        self.assertEqual(res.status_code, 201)
        txn = Transaction.objects.get()
        self.assertEqual(txn.user, self.user)
        self.assertNotEqual(txn.transaction_id, 'PS-HACKED000000')
        self.assertTrue(txn.transaction_id.startswith('PS-'))
        self.assertEqual(txn.status, TransactionStatus.PENDING)   # client-sent 'FAILED' ignored
        self.assertEqual(txn.fraud_status, FraudStatus.NOT_CHECKED)
        self.assertIsNone(txn.fraud_probability)

    def test_transaction_ids_are_unique(self):
        ids = {self.pay().data['transaction_id'] for _ in range(5)}
        self.assertEqual(len(ids), 5)

    def test_invalid_amounts_rejected(self):
        for bad in ['0', '0.00', '-5', '-0.01', 'abc', '1e3', '10.999', '', None, 'NaN', 'Infinity', '12,50', '99999999999999']:
            res = self.pay(amount=bad)
            self.assertEqual(res.status_code, 400, repr(bad))
            self.assertIn('amount', res.data, repr(bad))
        self.assertEqual(Transaction.objects.count(), 0)

    def test_decimal_and_numeric_amounts_accepted(self):
        for good, expected in [('0.01', '0.01'), ('1999', '1999.00'), (75.5, '75.50'), ('10.1', '10.10')]:
            res = self.pay(amount=good)
            self.assertEqual(res.status_code, 201, repr(good))
            self.assertEqual(res.data['amount'], expected)

    def test_missing_and_invalid_recipient(self):
        self.assertIn('recipient_name', self.pay(recipient_name='').data)
        self.assertIn('recipient_name', self.pay(recipient_name='A').data)
        for bad in ['nope', 'a@b', 'a b@c.com']:             # recipient e-mail is optional, but a given one must be valid
            self.assertIn('recipient_email', self.pay(recipient_email=bad).data, repr(bad))
        body = {k: v for k, v in BASE.items() if k not in ('recipient_name', 'recipient_email', 'amount')}
        res = self.client.post(self.url, body, format='json')
        for field in ('recipient_name', 'amount'):
            self.assertIn(field, res.data)
        self.assertNotIn('recipient_email', res.data)

    def test_invalid_payment_method(self):
        self.assertIn('payment_method', self.pay(payment_method='CASH').data)
        self.assertIn('payment_method', self.client.post(self.url, COMMON, format='json').data)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_description_is_optional_and_length_limited(self):
        self.assertEqual(self.pay(description='').status_code, 201)
        body = {k: v for k, v in BASE.items() if k != 'description'}
        self.assertEqual(self.client.post(self.url, body, format='json').status_code, 201)
        self.assertEqual(self.pay(description='x' * 255).status_code, 201)
        self.assertIn('description', self.pay(description='x' * 256).data)

    def test_pin_password_and_otp_fields_are_never_stored_or_returned(self):
        res = self.pay(pin='4821', upi_pin='7392', otp='605814', password='hunter2-secret', internet_banking_password='bank-secret')
        self.assertEqual(res.status_code, 201)
        blob = str(Transaction.objects.values().get()) + str(res.data)
        for secret in ('4821', '7392', '605814', 'hunter2-secret', 'bank-secret'):
            self.assertNotIn(secret, blob)


class LocationAndDeviceTests(PaymentApiTestCase):
    def test_coordinates_are_stored_when_provided(self):
        res = self.pay(latitude=9.6877, longitude=76.7798, location_status='PROVIDED')
        txn = Transaction.objects.get(transaction_id=res.data['transaction_id'])
        self.assertEqual((txn.latitude, txn.longitude), (Decimal('9.687700'), Decimal('76.779800')))
        self.assertEqual(txn.location_status, 'PROVIDED')

    def test_denied_or_missing_location_still_pays_with_null_coordinates(self):
        res = self.pay(latitude=None, longitude=None, location_status='DENIED')
        self.assertEqual(res.status_code, 201)
        denied = Transaction.objects.get(transaction_id=res.data['transaction_id'])
        self.assertEqual((denied.latitude, denied.longitude, denied.location_status), (None, None, 'DENIED'))
        res = self.pay()
        none = Transaction.objects.get(transaction_id=res.data['transaction_id'])
        self.assertEqual((none.latitude, none.longitude, none.location_status), (None, None, 'UNAVAILABLE'))

    def test_bad_coordinates_never_block_payment(self):
        for lat, lon in [(95, 10), (10, 190), ('abc', 'def'), (10, None), (None, 10), ('NaN', 5), (True, False), ([1], {'a': 1})]:
            res = self.pay(latitude=lat, longitude=lon)
            self.assertEqual(res.status_code, 201, (lat, lon))
            txn = Transaction.objects.get(transaction_id=res.data['transaction_id'])
            self.assertIsNone(txn.latitude, (lat, lon))
            self.assertIsNone(txn.longitude, (lat, lon))

    def test_device_info_comes_from_user_agent(self):
        expectations = {
            CHROME_WIN: ('DESKTOP', 'Chrome 126', 'Windows'),
            IPHONE: ('MOBILE', 'Safari 17', 'iOS'),
            IPAD: ('TABLET', 'Safari 17', 'iOS'),
            ANDROID: ('MOBILE', 'Chrome 126', 'Android'),
            ANDROID_TABLET: ('TABLET', 'Chrome 126', 'Android'),
            FIREFOX_LINUX: ('DESKTOP', 'Firefox 127', 'Linux'),
            EDGE_MAC: ('DESKTOP', 'Edge 126', 'macOS'),
            '': ('UNKNOWN', 'Unknown', 'Unknown'),
        }
        for ua, expected in expectations.items():
            self.assertEqual(parse_user_agent(ua), expected, ua)
        res = self.pay(user_agent=IPHONE)
        txn = Transaction.objects.get(transaction_id=res.data['transaction_id'])
        self.assertEqual((txn.device_type, txn.browser, txn.operating_system), ('MOBILE', 'Safari 17', 'iOS'))

    def test_responses_never_expose_location_device_or_fraud_data(self):
        res = self.pay(latitude=9.6877, longitude=76.7798)
        txn_id = res.data['transaction_id']
        forbidden = {'latitude', 'longitude', 'location_status', 'device_type', 'browser', 'operating_system',
                     'fraud_status', 'fraud_probability', 'model_version', 'user', 'idempotency_key', 'failure_reason', 'ip_address'}
        for payload in (res.data, self.client.get(f'{self.url}{txn_id}/').data, self.client.get(self.url).data['results'][0]):
            self.assertFalse(forbidden & set(payload), forbidden & set(payload))
        self.assertNotIn('9.6877', str(self.client.get(f'{self.url}{txn_id}/').data))


class IdempotencyAndFailureTests(PaymentApiTestCase):
    def test_duplicate_submission_with_same_key_creates_one_transaction(self):
        first = self.pay(key='key-12345678')
        second = self.pay(key='key-12345678')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['transaction_id'], second.data['transaction_id'])
        self.assertEqual(Transaction.objects.count(), 1)

    def test_different_keys_make_separate_payments_and_keys_are_per_user(self):
        self.pay(key='key-aaaaaaaa')
        self.pay(key='key-bbbbbbbb')
        other = APIClient()
        other.force_login(self.other)
        res = other.post(self.url, BASE, format='json', HTTP_IDEMPOTENCY_KEY='key-aaaaaaaa')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Transaction.objects.count(), 3)

    def test_invalid_idempotency_key_rejected(self):
        for bad in ('short', 'has spaces in it!', 'x' * 65):
            self.assertEqual(self.pay(key=bad).status_code, 400, bad)
        self.assertEqual(Transaction.objects.count(), 0)

    def _verified_low_risk_payment(self, key):
        """Creates a low-risk payment and returns (transaction_id, the code the user received by e-mail)."""
        with force_prediction(LOW):
            res = self.pay(key=key)
        self.assertEqual((res.status_code, res.data['status']), (201, 'PENDING'))
        return res.data['transaction_id'], code_from(mail.outbox[-1])

    def test_processing_failure_marks_transaction_failed(self):
        txn_id, code = self._verified_low_risk_payment('key-failing01')
        with mock.patch('payments.services.simulate_payment_processing', side_effect=PaymentProcessingError('declined')):
            res = self.client.post(f'{self.url}{txn_id}/verify-otp/', {'code': code}, format='json')
        self.assertEqual(res.status_code, 422)
        self.assertIn('transaction_id', res.data)
        txn = Transaction.objects.get()
        self.assertEqual((txn.status, txn.failure_reason), ('FAILED', 'declined'))
        self.assertNotIn('declined', str(res.data))
        self.assertEqual(self.pay(key='key-failing01').status_code, 422)  # replay gives the same outcome
        self.assertEqual(Transaction.objects.count(), 1)

    def test_unexpected_processor_error_never_leaves_pending(self):
        txn_id, code = self._verified_low_risk_payment('key-failing02')
        with mock.patch('payments.services.simulate_payment_processing', side_effect=RuntimeError('boom')), \
                self.assertLogs('payments.services', level='ERROR'):
            res = self.client.post(f'{self.url}{txn_id}/verify-otp/', {'code': code}, format='json')
        self.assertEqual(res.status_code, 422)
        self.assertEqual(Transaction.objects.get().status, 'FAILED')

    def test_payment_endpoint_is_throttled_per_user(self):
        for _ in range(30):
            self.pay()
        self.assertEqual(self.pay().status_code, 429)


class TransactionVisibilityTests(PaymentApiTestCase):
    def test_list_is_scoped_to_user_newest_first_and_paginated(self):
        old = make_txn(self.user, recipient_name='Old')
        new = make_txn(self.user, recipient_name='New')
        Transaction.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))
        theirs = make_txn(self.other, recipient_name='Theirs')
        data = self.client.get(self.url).data
        self.assertEqual({'count', 'next', 'previous', 'results'}, set(data))
        self.assertEqual([t['transaction_id'] for t in data['results']], [new.transaction_id, old.transaction_id])
        self.assertNotIn(theirs.transaction_id, str(data))

    def test_pagination_page_size(self):
        for _ in range(23):
            make_txn(self.user)
        page1 = self.client.get(self.url).data
        self.assertEqual((page1['count'], len(page1['results'])), (23, 20))
        self.assertIsNotNone(page1['next'])
        self.assertEqual(len(self.client.get(self.url, {'page': 2}).data['results']), 3)

    def test_detail_only_for_owner(self):
        mine = make_txn(self.user, description='Lunch')
        theirs = make_txn(self.other)
        res = self.client.get(f'{self.url}{mine.transaction_id}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['description'], 'Lunch')
        self.assertEqual(res.data['payment_method_detail'], 'Visa')
        self.assertEqual(self.client.get(f'{self.url}{theirs.transaction_id}/').status_code, 404)
        self.assertEqual(self.client.get(f'{self.url}PS-DOESNOTEXIST/').status_code, 404)

    def test_transactions_cannot_be_modified_or_deleted_via_api(self):
        mine = make_txn(self.user)
        url = f'{self.url}{mine.transaction_id}/'
        for method in ('put', 'patch', 'delete'):
            self.assertEqual(getattr(self.client, method)(url, {'amount': '1'}, format='json').status_code, 405)


class DatabaseConstraintTests(PaymentApiTestCase):
    def assert_rejected(self, **fields):
        with self.assertRaises(IntegrityError), db_transaction.atomic():
            make_txn(self.user, **fields)

    def test_database_rejects_invalid_rows(self):
        self.assert_rejected(amount=Decimal('0'))
        self.assert_rejected(amount=Decimal('-1'))
        self.assert_rejected(card_network='')
        self.assert_rejected(payment_method='UPI', card_network='', upi_id='')
        self.assert_rejected(latitude=Decimal('91'), longitude=Decimal('10'))
        self.assert_rejected(latitude=Decimal('10'), longitude=Decimal('181'))
        self.assert_rejected(fraud_probability=1.5)
        make_txn(self.user, idempotency_key='dup-key-0001')
        self.assert_rejected(idempotency_key='dup-key-0001')

    def test_defaults_are_fraud_ready_and_unscored(self):
        txn = Transaction.objects.create(
            user=self.user, recipient_name='R', recipient_email='r@e.com', amount=Decimal('5'),
            payment_method='CARD', card_network='VISA',
        )
        self.assertEqual((txn.status, txn.fraud_status, txn.fraud_probability), ('PENDING', 'NOT_CHECKED', None))


class FraudFeaturePreparationTests(PaymentApiTestCase):
    """History features come from real stored transactions; no model is involved."""

    def setUp(self):
        super().setUp()
        self.now = timezone.now()

    def completed(self, minutes_ago, amount, recipient='ravi@example.com', method='CARD', user=None, **extra):
        extra.setdefault('card_network' if method == 'CARD' else 'upi_id', 'VISA' if method == 'CARD' else 'a@okbank')
        return make_txn(user or self.user, amount=Decimal(amount), recipient_email=recipient, payment_method=method,
                        timestamp=self.now - timedelta(minutes=minutes_ago), **extra)

    def features(self, recipient='ravi@example.com', method='CARD'):
        return compute_history_features(user=self.user, as_of=self.now, recipient_email=recipient, payment_method=method)

    def test_empty_history(self):
        f = self.features()
        self.assertEqual((f.previous_transaction_count, f.transactions_last_24h, f.average_daily_transactions_30d), (0, 0, 0))
        for value in (f.average_previous_amount, f.max_previous_amount, f.min_previous_amount, f.last_transaction_amount,
                      f.seconds_since_previous_transaction, f.last_known_latitude):
            self.assertIsNone(value)

    def test_history_aggregates(self):
        self.completed(30, '100')
        self.completed(60 * 5, '300', recipient='sam@example.com', method='UPI')
        self.completed(60 * 24 * 3, '50', recipient='RAVI@example.com')
        self.completed(60 * 24 * 40, '650', recipient='old@example.com')
        f = self.features()
        self.assertEqual(f.previous_transaction_count, 4)
        self.assertEqual((f.transactions_last_1h, f.transactions_last_24h, f.transactions_last_7d, f.transactions_last_30d), (1, 2, 3, 3))
        self.assertEqual(f.average_daily_transactions_30d, 0.1)
        self.assertEqual((f.average_previous_amount, f.max_previous_amount, f.min_previous_amount), (Decimal('275.00'), Decimal('650.00'), Decimal('50.00')))
        self.assertEqual((f.last_transaction_amount, f.seconds_since_previous_transaction), (Decimal('100.00'), 1800.0))
        self.assertEqual(f.previous_transactions_to_same_recipient, 2)
        self.assertEqual(f.previous_transactions_same_payment_method, 3)
        self.assertEqual(f.distinct_previous_recipients, 4)

    def test_history_ignores_other_users_non_completed_and_future(self):
        self.completed(10, '100')
        self.completed(10, '999', user=self.other)
        self.completed(10, '888', status=TransactionStatus.FAILED)
        self.completed(10, '777', status=TransactionStatus.PENDING)
        self.completed(10, '666', status=TransactionStatus.CANCELLED)
        self.completed(-10, '555')  # in the future relative to as_of
        f = self.features()
        self.assertEqual((f.previous_transaction_count, f.max_previous_amount), (1, Decimal('100.00')))

    def test_last_known_location_uses_most_recent_located_transaction(self):
        self.completed(60, '10', latitude=Decimal('10.5'), longitude=Decimal('76.2'))
        self.completed(30, '10')  # more recent but no coordinates
        f = self.features()
        self.assertEqual((f.last_known_latitude, f.last_known_longitude), (Decimal('10.500000'), Decimal('76.200000')))

    def test_prepare_fraud_features_collects_source_data_without_scoring(self):
        self.completed(30, '100')
        current = make_txn(self.user, amount=Decimal('900'), status=TransactionStatus.PENDING, upi_id='x@okaxis',
                           payment_method='UPI', card_network='', timestamp=self.now, description='Gift',
                           device_type='MOBILE', browser='Chrome 126', operating_system='Android')
        source = prepare_fraud_features(current)
        self.assertEqual((source.amount, source.payment_method, source.upi_handle, source.has_description), (Decimal('900.00'), 'UPI', 'okaxis', True))
        self.assertEqual((source.device_type, source.operating_system, source.recipient_email_domain), ('MOBILE', 'Android', 'example.com'))
        self.assertEqual(source.history.previous_transaction_count, 1)  # excludes the transaction itself
        self.assertNotIn('x@okaxis', str(source.as_dict()))  # full UPI ID is not part of the source data
        current.refresh_from_db()
        self.assertEqual((current.fraud_status, current.fraud_probability), ('NOT_CHECKED', None))

    def test_model_row_requires_a_real_mapper(self):
        current = self.completed(0, '10')
        with self.assertRaises(FeatureMappingNotConfigured):
            build_model_row(prepare_fraud_features(current))


# ---------------------------------------------------------------------------
# Payment-method-specific details
# ---------------------------------------------------------------------------
import logging
from datetime import date

from django.http import HttpRequest
from rest_framework.test import APIRequestFactory, force_authenticate

from . import validators
from .views import SENSITIVE_PARAMETERS, PaymentListCreateView


class MethodFieldValidationTests(PaymentApiTestCase):
    """Each method requires and validates its own fields; the rest are ignored."""

    def assert_rejected(self, field, **overrides):
        before = Transaction.objects.count()
        res = self.pay(**overrides)
        self.assertEqual(res.status_code, 400, overrides)
        self.assertIn(field, res.data, (field, res.data))
        self.assertEqual(Transaction.objects.count(), before)  # nothing was created
        return res

    def card(self, **overrides):
        return {**METHOD_PAYLOADS['CARD'], **overrides}

    def bank(self, **overrides):
        return {**METHOD_PAYLOADS['BANK_TRANSFER'], **overrides}

    def wallet(self, **overrides):
        return {**METHOD_PAYLOADS['WALLET'], **overrides}

    # ---- card ----
    def test_card_requires_every_field(self):
        for field in ('cardholder_name', 'card_network', 'card_number', 'card_expiry', 'card_cvv'):
            self.assert_rejected(field, **self.card(**{field: ''}))
        res = self.client.post(self.url, {**COMMON, 'payment_method': 'CARD'}, format='json')
        for field in ('cardholder_name', 'card_network', 'card_number', 'card_expiry', 'card_cvv'):
            self.assertIn(field, res.data)

    def test_card_number_format_length_and_luhn(self):
        for bad in ('4111 1111 1111 1112', '4111111111111', '41111111111111111', 'abcd efgh ijkl mnop', '4111-1111-1111-11!1', '0000000000000000'):
            self.assert_rejected('card_number', **self.card(card_number=bad))
        for good in ('4111111111111111', '4111-1111-1111-1111', '4111 1111 1111 1111'):
            self.assertEqual(self.pay(**self.card(card_number=good)).status_code, 201, good)

    def test_card_number_length_depends_on_network(self):
        other_13 = '4222222222222'  # a 13-digit Luhn-valid number
        self.assertTrue(validators.luhn_valid(other_13))
        self.assert_rejected('card_number', **self.card(card_number=other_13))  # Visa must be 16
        self.assertEqual(self.pay(**self.card(card_network='OTHER', card_number=other_13)).status_code, 201)

    def test_card_name_validation(self):
        for bad in ('', 'A', '1234', 'Ravi <script>', 'x' * 61):
            self.assert_rejected('cardholder_name', **self.card(cardholder_name=bad))
        self.assertEqual(self.pay(**self.card(cardholder_name="Mary-Jane O'Neil Jr.")).status_code, 201)

    def test_card_expiry_validation(self):
        today = timezone.now()
        last_month = date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)
        self.assert_rejected('card_expiry', **self.card(card_expiry=f'{last_month.month:02d}/{last_month.year % 100:02d}'))
        for bad in ('13/30', '00/30', '1/30', '12-30', '1230', 'ab/cd', f'{today.month:02d}/{(today.year + 40) % 100:02d}'):
            self.assert_rejected('card_expiry', **self.card(card_expiry=bad))
        # the current month is still valid; so are 2- and 4-digit years
        self.assertEqual(self.pay(**self.card(card_expiry=f'{today.month:02d}/{today.year % 100:02d}')).status_code, 201)
        self.assertEqual(self.pay(**self.card(card_expiry=f'{today.month:02d}/{today.year + 2}')).status_code, 201)

    def test_cvv_length(self):
        for bad in ('12', '1234', 'abc', '12a', ' '):
            self.assert_rejected('card_cvv', **self.card(card_cvv=bad))
        self.assertEqual(self.pay(**self.card(card_cvv='999')).status_code, 201)
        self.assertEqual(self.pay(**self.card(card_network='OTHER', card_cvv='1234')).status_code, 201)

    def test_card_network_must_be_supported(self):
        self.assert_rejected('card_network', **self.card(card_network='AMEX'))

    # ---- UPI ----
    def test_upi_requires_provider_and_valid_id(self):
        upi = METHOD_PAYLOADS['UPI']
        self.assert_rejected('upi_provider', **{**upi, 'upi_provider': ''})
        self.assert_rejected('upi_provider', **{**upi, 'upi_provider': 'MOBIKWIK'})
        for bad in ('', 'no-at-sign', 'a@b', 'name@bank name', '@bank', 'na me@bank', 'x' * 70 + '@bank'):
            self.assert_rejected('upi_id', **{**upi, 'upi_id': bad})
        res = self.pay(**{**upi, 'upi_provider': 'PHONEPE'})
        txn = Transaction.objects.get(transaction_id=res.data['transaction_id'])
        self.assertEqual((txn.upi_provider, txn.upi_id), ('PHONEPE', 'ravi.k@okhdfc'))
        self.assertEqual(res.data['payment_method_detail'], 'ravi.k@okhdfc · PhonePe')

    # ---- bank transfer ----
    def test_bank_requires_every_field(self):
        for field in ('bank_name', 'account_holder_name', 'account_number', 'confirm_account_number', 'ifsc_code'):
            self.assert_rejected(field, **self.bank(**{field: ''}))

    def test_account_number_rules_and_confirmation(self):
        for bad in ('12345678', '1' * 19, '12345abc9012', '1234 5678 90!2'):
            self.assert_rejected('account_number', **self.bank(account_number=bad, confirm_account_number=bad))
        self.assert_rejected('confirm_account_number', **self.bank(confirm_account_number='123456789013'))
        self.assertEqual(self.pay(**self.bank(account_number='123456789', confirm_account_number='123456789')).status_code, 201)
        self.assertEqual(self.pay(**self.bank(account_number='1' * 18, confirm_account_number='1' * 18)).status_code, 201)

    def test_ifsc_format_and_bank_prefix(self):
        for bad in ('HDFC1001234', 'HDF00001234', 'HDFC000123', 'HDFC00012345', '1234A001234', 'hdfc 0001234', 'HDFC0001-34'):
            self.assert_rejected('ifsc_code', **self.bank(ifsc_code=bad))
        self.assert_rejected('ifsc_code', **self.bank(ifsc_code='SBIN0001234'))  # HDFC selected
        res = self.pay(**self.bank(bank_name='SBI', ifsc_code='sbin0001234'))
        self.assertEqual(Transaction.objects.get(transaction_id=res.data['transaction_id']).ifsc_code, 'SBIN0001234')
        self.assertEqual(self.pay(**self.bank(bank_name='OTHER', ifsc_code='ABCD0XYZ123')).status_code, 201)

    def test_bank_must_be_supported(self):
        self.assert_rejected('bank_name', **self.bank(bank_name='FAKEBANK'))

    # ---- wallet ----
    def test_wallet_requires_provider_type_and_identifier(self):
        for field in ('wallet_provider', 'wallet_identifier_type', 'wallet_identifier'):
            self.assert_rejected(field, **self.wallet(**{field: ''}))
        self.assert_rejected('wallet_provider', **self.wallet(wallet_provider='NOPE'))
        self.assert_rejected('wallet_identifier_type', **self.wallet(wallet_identifier_type='EMAIL'))

    def test_wallet_mobile_validation(self):
        for bad in ('12345', '5876543210', '98765432101', '98765 4321x', '+1 9876543210'):
            self.assert_rejected('wallet_identifier', **self.wallet(wallet_identifier=bad))
        for good in ('9876543210', '+91 98765-43210', '919876543210', '09876543210'):
            self.assertEqual(self.pay(**self.wallet(wallet_identifier=good)).status_code, 201, good)

    def test_wallet_id_validation_depends_on_selected_type(self):
        wallet_id = self.wallet(wallet_identifier_type='WALLET_ID')
        for bad in ('ab', 'has space', '-start', 'x' * 65, '<script>'):
            self.assert_rejected('wallet_identifier', **{**wallet_id, 'wallet_identifier': bad})
        self.assertEqual(self.pay(**{**wallet_id, 'wallet_identifier': 'ravi.k@paytm'}).status_code, 201)
        # a wallet ID is not acceptable where a mobile number is required, and vice versa is fine as an ID
        self.assert_rejected('wallet_identifier', **self.wallet(wallet_identifier='ravi.k@paytm'))
        self.assertEqual(self.pay(**{**wallet_id, 'wallet_identifier': '9876543210'}).status_code, 201)

    def test_validation_messages_never_echo_the_input(self):
        secrets = {'card_number': '4111111111111112', 'card_cvv': '98x', 'card_expiry': '99/99', 'cardholder_name': '12345'}
        res = self.pay(**self.card(**secrets))
        for value in secrets.values():
            self.assertNotIn(value, str(res.data))


class SensitiveDataTests(PaymentApiTestCase):
    """Raw card numbers, CVVs and account numbers are validated and then discarded."""

    CARD_DIGITS = '4111111111111111'
    ACCOUNT = '123456789012'
    MOBILE = '9876543210'

    def all_rows_as_text(self):
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT * FROM {Transaction._meta.db_table}')
            return ' | '.join(str(cell) for row in cursor.fetchall() for cell in row)

    def make_all_payments(self):
        ids = {}
        for method, extra in METHOD_PAYLOADS.items():
            res = self.pay(**extra)
            self.assertEqual(res.status_code, 201, res.data)
            ids[method] = res.data['transaction_id']
        return ids

    def test_masked_references_are_stored_instead_of_raw_values(self):
        ids = self.make_all_payments()
        by_method = {m: Transaction.objects.get(transaction_id=i) for m, i in ids.items()}
        self.assertEqual(by_method['CARD'].masked_reference, '**** 1111')
        self.assertEqual(by_method['BANK_TRANSFER'].masked_reference, '**** 9012')
        self.assertEqual(by_method['WALLET'].masked_reference, '******3210')
        self.assertEqual(by_method['UPI'].masked_reference, '')
        self.assertEqual(by_method['BANK_TRANSFER'].ifsc_code, 'HDFC0001234')
        self.assertEqual(by_method['WALLET'].wallet_identifier_type, 'MOBILE')

    def test_no_raw_sensitive_value_reaches_the_database(self):
        self.make_all_payments()
        everything = self.all_rows_as_text()
        for secret in (self.CARD_DIGITS, '4111 1111 1111 1111', '123456789012', '9876543210', '98765 43210',
                       FUTURE_EXPIRY, 'Ravi Kumar'.upper() + '!'):
            self.assertNotIn(secret, everything, secret)
        # CVV is never stored: no column anywhere holds it
        self.assertFalse([f.name for f in Transaction._meta.get_fields() if 'cvv' in f.name.lower() or 'pin' in f.name.lower()])
        self.assertNotIn('123 ', everything.replace('**** 1111', '').replace('123456789012', ''))

    def test_wallet_id_is_masked_too(self):
        res = self.pay(**{**METHOD_PAYLOADS['WALLET'], 'wallet_identifier_type': 'WALLET_ID', 'wallet_identifier': 'ravi.kumar@paytm'})
        txn = Transaction.objects.get(transaction_id=res.data['transaction_id'])
        self.assertEqual(txn.masked_reference, 'ra***tm')
        self.assertNotIn('ravi.kumar@paytm', self.all_rows_as_text())

    def test_responses_and_listings_expose_only_masked_details(self):
        ids = self.make_all_payments()
        payloads = [self.client.get(self.url).data, self.client.get(f'{self.url}{ids["CARD"]}/').data,
                    self.client.get(f'{self.url}{ids["BANK_TRANSFER"]}/').data, self.client.get(f'{self.url}{ids["WALLET"]}/').data]
        text = str(payloads)
        for secret in (self.CARD_DIGITS, self.ACCOUNT, self.MOBILE, 'card_number', 'card_cvv', 'cvv', 'account_number'):
            self.assertNotIn(secret, text, secret)
        self.assertEqual(payloads[1]['payment_method_detail'], 'Visa · **** 1111')
        self.assertEqual(payloads[2]['payment_method_detail'], 'HDFC Bank · **** 9012 · IFSC HDFC0001234')
        self.assertEqual(payloads[3]['payment_method_detail'], 'Paytm · ******3210')

    def test_admin_views_stay_compatible_and_masked(self):
        ids = self.make_all_payments()
        admin = User.objects.create_superuser('boss', 'boss@example.com', 'Str0ng-Passw0rd!')
        admin_client = APIClient()
        admin_client.force_login(admin)
        listing = admin_client.get('/api/admin/transactions/')
        self.assertEqual((listing.status_code, listing.data['count']), (200, 4))
        for txn_id in ids.values():
            detail = admin_client.get(f'/api/admin/transactions/{txn_id}/')
            self.assertEqual(detail.status_code, 200)
            for secret in (self.CARD_DIGITS, self.ACCOUNT, self.MOBILE):
                self.assertNotIn(secret, str(detail.data))
        self.assertEqual(admin_client.get(f'/api/admin/transactions/{ids["CARD"]}/').data['payment_method_detail'], 'Visa · **** 1111')
        csv = admin_client.get('/api/admin/reports/fraud-monitoring/', {'export': 'csv'}).content.decode()
        for secret in (self.CARD_DIGITS, self.ACCOUNT, self.MOBILE):
            self.assertNotIn(secret, csv)

    def test_sensitive_values_are_never_logged(self):
        records = []

        class Collect(logging.Handler):
            def emit(self, record):
                records.append(f'{record.getMessage()} {record.exc_text or ""} {record.__dict__.get("args")}')

        handler, root = Collect(level=logging.DEBUG), logging.getLogger()
        previous = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            self.make_all_payments()
            self.pay(**{**METHOD_PAYLOADS['CARD'], 'card_cvv': '12'})            # a rejected request (logged by Django as a 4xx)
            with mock.patch('payments.services.simulate_payment_processing', side_effect=RuntimeError('boom')):
                self.pay(**METHOD_PAYLOADS['CARD'])                               # an unexpected error is logged with a traceback
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)
        self.assertTrue(records, 'expected some log output to inspect')
        joined = '\n'.join(records)
        for secret in (self.CARD_DIGITS, '4111 1111 1111', self.ACCOUNT, self.MOBILE, '98765', FUTURE_EXPIRY):
            self.assertNotIn(secret, joined, secret)

    def test_sensitive_parameters_are_registered_for_error_reports(self):
        request = APIRequestFactory().post(self.url, {}, format='json')
        force_authenticate(request, user=self.user)
        PaymentListCreateView.as_view()(request)
        self.assertEqual(set(request.sensitive_post_parameters), set(SENSITIVE_PARAMETERS))
        for name in ('card_number', 'card_cvv', 'card_expiry', 'account_number', 'wallet_identifier'):
            self.assertIn(name, SENSITIVE_PARAMETERS)

    def test_idempotent_retry_does_not_reprocess_or_store_details(self):
        first = self.pay(key='key-sensitive1')
        second = self.pay(key='key-sensitive1')
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertNotIn(self.CARD_DIGITS, self.all_rows_as_text())


class LegacyRecordTests(PaymentApiTestCase):
    """Transactions made before the new fields existed keep working everywhere."""

    def test_old_records_display_and_list_correctly(self):
        legacy = make_txn(self.user)  # only card_network, no masked reference
        make_txn(self.user, payment_method='UPI', upi_id='old@okaxis', card_network='')
        make_txn(self.user, payment_method='BANK_TRANSFER', bank_name='SBI', card_network='')
        make_txn(self.user, payment_method='WALLET', wallet_provider='PHONEPE', card_network='')
        self.assertEqual(self.client.get(f'{self.url}{legacy.transaction_id}/').data['payment_method_detail'], 'Visa')
        details = {t.payment_method: t.payment_method_detail for t in Transaction.objects.all()}
        self.assertEqual(details, {'CARD': 'Visa', 'UPI': 'old@okaxis', 'BANK_TRANSFER': 'State Bank of India', 'WALLET': 'PhonePe'})
        self.assertEqual(self.client.get(self.url).data['count'], 4)


class ValidatorUnitTests(TestCase):
    TODAY = date(2026, 10, 9)

    def test_luhn(self):
        self.assertTrue(validators.luhn_valid('4111111111111111'))
        self.assertTrue(validators.luhn_valid('5555555555554444'))
        self.assertFalse(validators.luhn_valid('4111111111111112'))

    def test_expiry_boundaries(self):
        self.assertEqual(validators.clean_expiry('10/26', self.TODAY), (10, 2026))   # current month is valid
        self.assertEqual(validators.clean_expiry('10 / 2026', self.TODAY), (10, 2026))
        with self.assertRaises(validators.InvalidDetail):
            validators.clean_expiry('09/26', self.TODAY)                              # last month: expired
        with self.assertRaises(validators.InvalidDetail):
            validators.clean_expiry('01/47', self.TODAY)                              # more than 20 years ahead
        self.assertEqual(validators.clean_expiry('12/46', self.TODAY), (12, 2046))

    def test_masks(self):
        self.assertEqual(validators.mask_last4('4111111111111111'), '**** 1111')
        self.assertEqual(validators.mask_mobile('9876543210'), '******3210')
        self.assertEqual(validators.mask_identifier('abcd'), '***cd')
        self.assertLessEqual(len(validators.mask_identifier('x' * 64)), 32)

    def test_ifsc_prefix_map_covers_every_named_bank(self):
        from .models import Bank
        self.assertEqual(set(validators.IFSC_BANK_PREFIX), set(Bank.values) - {Bank.OTHER})
