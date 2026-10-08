from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction as db_transaction
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

User = get_user_model()
FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])

CHROME_WIN = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
IPAD = 'Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36'
ANDROID_TABLET = 'Mozilla/5.0 (Linux; Android 13; SM-X700) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
FIREFOX_LINUX = 'Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0'
EDGE_MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0'

BASE = {
    'amount': '250.50',
    'payment_method': 'CARD',
    'card_network': 'VISA',
    'recipient_name': 'Ravi Kumar',
    'recipient_email': 'Ravi@Example.com',
    'description': 'Rent',
}
METHOD_PAYLOADS = {
    'CARD': {'payment_method': 'CARD', 'card_network': 'VISA'},
    'UPI': {'payment_method': 'UPI', 'upi_id': 'Ravi.K@okhdfc'},
    'BANK_TRANSFER': {'payment_method': 'BANK_TRANSFER', 'bank_name': 'HDFC'},
    'WALLET': {'payment_method': 'WALLET', 'wallet_provider': 'PAYTM'},
}


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
    def test_every_payment_method_succeeds(self):
        for method, extra in METHOD_PAYLOADS.items():
            res = self.pay(**extra)
            self.assertEqual(res.status_code, 201, (method, res.data))
            txn = Transaction.objects.get(transaction_id=res.data['transaction_id'])
            self.assertEqual(txn.status, TransactionStatus.COMPLETED)
            self.assertEqual(txn.payment_method, method)
            self.assertEqual(txn.user, self.user)
            self.assertEqual(txn.fraud_status, FraudStatus.NOT_CHECKED)
            self.assertIsNone(txn.fraud_probability)
            self.assertEqual(txn.model_version, '')
            self.assertEqual(txn.amount, Decimal('250.50'))
            self.assertEqual(txn.recipient_email, 'ravi@example.com')
        self.assertEqual(Transaction.objects.count(), 4)

    def test_only_relevant_method_detail_is_stored(self):
        res = self.pay(payment_method='UPI', upi_id='ravi@okhdfc', card_network='VISA', bank_name='HDFC', wallet_provider='PAYTM')
        txn = Transaction.objects.get(transaction_id=res.data['transaction_id'])
        self.assertEqual((txn.upi_id, txn.card_network, txn.bank_name, txn.wallet_provider), ('ravi@okhdfc', '', '', ''))

    def test_client_cannot_set_sender_id_status_or_fraud_fields(self):
        res = self.pay(user=self.other.pk, user_id=self.other.pk, sender='x', transaction_id='PS-HACKED000000',
                       status='FAILED', fraud_status='FRAUDULENT', fraud_probability=0.99, device_type='DESKTOP')
        self.assertEqual(res.status_code, 201)
        txn = Transaction.objects.get()
        self.assertEqual(txn.user, self.user)
        self.assertNotEqual(txn.transaction_id, 'PS-HACKED000000')
        self.assertTrue(txn.transaction_id.startswith('PS-'))
        self.assertEqual(txn.status, TransactionStatus.COMPLETED)
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
        for bad in ['', 'nope', 'a@b', 'a b@c.com']:
            self.assertIn('recipient_email', self.pay(recipient_email=bad).data, repr(bad))
        body = {k: v for k, v in BASE.items() if k not in ('recipient_name', 'recipient_email', 'amount')}
        res = self.client.post(self.url, body, format='json')
        for field in ('recipient_name', 'recipient_email', 'amount'):
            self.assertIn(field, res.data)

    def test_invalid_payment_method_and_method_specific_data(self):
        self.assertIn('payment_method', self.pay(payment_method='CASH').data)
        self.assertIn('payment_method', self.client.post(self.url, {k: v for k, v in BASE.items() if k != 'payment_method'}, format='json').data)
        cases = [
            ({'payment_method': 'CARD', 'card_network': ''}, 'card_network'),
            ({'payment_method': 'CARD', 'card_network': 'AMEX'}, 'card_network'),
            ({'payment_method': 'UPI', 'upi_id': ''}, 'upi_id'),
            ({'payment_method': 'UPI', 'upi_id': 'no-at-sign'}, 'upi_id'),
            ({'payment_method': 'UPI', 'upi_id': 'a@b'}, 'upi_id'),
            ({'payment_method': 'UPI', 'upi_id': 'name@bank name'}, 'upi_id'),
            ({'payment_method': 'BANK_TRANSFER', 'bank_name': ''}, 'bank_name'),
            ({'payment_method': 'BANK_TRANSFER', 'bank_name': 'FAKEBANK'}, 'bank_name'),
            ({'payment_method': 'WALLET', 'wallet_provider': ''}, 'wallet_provider'),
            ({'payment_method': 'WALLET', 'wallet_provider': 'NOPE'}, 'wallet_provider'),
        ]
        for overrides, field in cases:
            res = self.pay(**overrides)
            self.assertEqual(res.status_code, 400, overrides)
            self.assertIn(field, res.data, overrides)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_description_is_optional_and_length_limited(self):
        self.assertEqual(self.pay(description='').status_code, 201)
        body = {k: v for k, v in BASE.items() if k != 'description'}
        self.assertEqual(self.client.post(self.url, body, format='json').status_code, 201)
        self.assertEqual(self.pay(description='x' * 255).status_code, 201)
        self.assertIn('description', self.pay(description='x' * 256).data)

    def test_sensitive_card_data_is_never_stored_or_returned(self):
        res = self.pay(card_number='4111111111111111', cvv='123', pin='1234', upi_pin='1234', otp='999999', password='secret')
        self.assertEqual(res.status_code, 201)
        stored = str(Transaction.objects.values().get())
        for secret in ('4111111111111111', '123456', '999999', 'secret'):
            self.assertNotIn(secret, stored)
            self.assertNotIn(secret, str(res.data))


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

    def test_processing_failure_marks_transaction_failed(self):
        with mock.patch('payments.services.simulate_payment_processing', side_effect=PaymentProcessingError('declined')):
            res = self.pay(key='key-failing01')
        self.assertEqual(res.status_code, 422)
        self.assertIn('transaction_id', res.data)
        txn = Transaction.objects.get()
        self.assertEqual((txn.status, txn.failure_reason), ('FAILED', 'declined'))
        self.assertNotIn('declined', str(res.data))
        self.assertEqual(self.pay(key='key-failing01').status_code, 422)  # replay gives the same outcome
        self.assertEqual(Transaction.objects.count(), 1)

    def test_unexpected_processor_error_never_leaves_pending(self):
        with mock.patch('payments.services.simulate_payment_processing', side_effect=RuntimeError('boom')), \
                self.assertLogs('payments.services', level='ERROR'):
            res = self.pay()
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
