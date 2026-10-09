import os
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from payments.models import Transaction, TransactionStatus

from .reports import build_report, report_to_csv, safe_cell

User = get_user_model()
FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
PASSWORD = 'Str0ng-Passw0rd!'


def make_user(email, name='Test User', **extra):
    return User.objects.create_user(username=email, email=email, password=PASSWORD, first_name=name, **extra)


def make_txn(user, amount='100.00', status=TransactionStatus.COMPLETED, method='CARD', days_ago=0, minutes_ago=0, **extra):
    fields = dict(
        user=user, recipient_name='Ravi Kumar', recipient_email='ravi@example.com', amount=Decimal(amount),
        payment_method=method, status=status,
    )
    if method == 'CARD':
        fields['card_network'] = 'VISA'
    elif method == 'UPI':
        fields['upi_id'] = 'ravi@okhdfc'
    elif method == 'BANK_TRANSFER':
        fields['bank_name'] = 'HDFC'
    else:
        fields['wallet_provider'] = 'PAYTM'
    fields.update(extra)
    txn = Transaction.objects.create(**fields)
    when = timezone.now() - timedelta(days=days_ago, minutes=minutes_ago)
    Transaction.objects.filter(pk=txn.pk).update(created_at=when)
    txn.refresh_from_db()
    return txn


@FAST_HASH
class AdminTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', PASSWORD, first_name='Boss')
        self.alice = make_user('alice@example.com', 'Alice Nair')
        self.bob = make_user('bob@example.com', 'Bob Stone')
        self.client = APIClient()
        self.client.force_login(self.admin)

    def get(self, url, **params):
        return self.client.get(url, params)

    def login_client(self, user):
        client = APIClient()
        client.force_login(user)
        return client


# ------------------------------------------------------------- auth & roles

@FAST_HASH
class LoginAndRoleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser('boss', 'Boss@Example.com', PASSWORD)
        self.user = make_user('alice@example.com', 'Alice')
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.get('/api/auth/csrf/')

    def login(self, email, password=PASSWORD):
        token = self.client.cookies['csrftoken'].value
        res = self.client.post('/api/auth/login/', {'email': email, 'password': password}, format='json', HTTP_X_CSRFTOKEN=token)
        if res.status_code == 200:
            self.client.cookies['csrftoken'].value  # rotated on login
        return res

    def test_superuser_logs_in_with_email_through_common_login(self):
        res = self.login('boss@example.com')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['role'], 'admin')
        self.assertEqual(res.data['email'], 'Boss@example.com')  # Django lowercases the domain
        self.assertNotIn('password', res.data)
        self.assertEqual(self.client.get('/api/auth/user/').data['role'], 'admin')

    def test_email_login_is_case_insensitive_and_username_still_works_for_django_admin_style(self):
        self.assertEqual(self.login('BOSS@example.COM').status_code, 200)

    def test_regular_user_gets_user_role(self):
        res = self.login('alice@example.com')
        self.assertEqual((res.status_code, res.data['role']), (200, 'user'))

    def test_wrong_password_and_unknown_email_share_one_message(self):
        wrong = self.login('boss@example.com', 'nope-nope-nope')
        ghost = self.login('ghost@example.com', 'nope-nope-nope')
        self.assertEqual((wrong.status_code, ghost.status_code), (401, 401))
        self.assertEqual(wrong.data, ghost.data)

    def test_inactive_superuser_cannot_log_in(self):
        User.objects.filter(pk=self.admin.pk).update(is_active=False)
        self.assertEqual(self.login('boss@example.com').status_code, 401)

    def test_ambiguous_email_is_rejected_but_exact_username_match_wins(self):
        User.objects.create_user('other', 'alice@example.com', PASSWORD)  # shares email with Alice
        self.assertEqual(self.login('alice@example.com').status_code, 200)  # Alice's username matches exactly
        User.objects.create_user('first', 'dup@example.com', PASSWORD)
        User.objects.create_user('second', 'dup@example.com', PASSWORD)
        self.assertEqual(self.login('dup@example.com').status_code, 401)

    def test_createsuperuser_command_account_can_log_in_by_email(self):
        with mock.patch.dict(os.environ, {'DJANGO_SUPERUSER_PASSWORD': PASSWORD}):
            call_command('createsuperuser', interactive=False, username='root', email='root@example.com')
        res = self.login('root@example.com')
        self.assertEqual((res.status_code, res.data['role']), (200, 'admin'))

    def test_signup_cannot_create_superuser_or_staff(self):
        token = self.client.cookies['csrftoken'].value
        res = self.client.post('/api/auth/signup/', {
            'full_name': 'Mallory Evil', 'email': 'mallory@example.com', 'password': PASSWORD, 'confirm_password': PASSWORD,
            'is_superuser': True, 'is_staff': True, 'role': 'admin',
        }, format='json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['role'], 'user')
        user = User.objects.get(email='mallory@example.com')
        self.assertFalse(user.is_superuser or user.is_staff)

    def test_signup_cannot_reuse_a_superuser_email(self):
        token = self.client.cookies['csrftoken'].value
        res = self.client.post('/api/auth/signup/', {
            'full_name': 'Mallory Evil', 'email': 'boss@example.com', 'password': PASSWORD, 'confirm_password': PASSWORD,
        }, format='json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(res.status_code, 400)

    def test_profile_patch_cannot_escalate_privileges(self):
        self.login('alice@example.com')
        token = self.client.cookies['csrftoken'].value
        res = self.client.patch('/api/auth/user/', {'full_name': 'Alice B', 'is_superuser': True, 'role': 'admin'},
                                format='json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual((res.status_code, res.data['role']), (200, 'user'))
        self.assertFalse(User.objects.get(email='alice@example.com').is_superuser)

    def test_superuser_without_first_name_gets_a_display_name(self):
        self.assertEqual(self.login('boss@example.com').data['full_name'], 'Boss')


# ---------------------------------------------------------- access control

ADMIN_GET_URLS = [
    '/api/admin/overview/',
    '/api/admin/fraud-statistics/',
    '/api/admin/users/',
    '/api/admin/users/{alice}/',
    '/api/admin/users/{alice}/transactions/',
    '/api/admin/transactions/',
    '/api/admin/transactions/{txn}/',
    '/api/admin/reports/transactions/',
    '/api/admin/reports/users/',
    '/api/admin/reports/activity/',
    '/api/admin/reports/fraud-monitoring/',
    '/api/admin/reports/transactions/?export=csv',
]


class AccessControlTests(AdminTestCase):
    def urls(self):
        txn = make_txn(self.alice)
        return [u.format(alice=self.alice.pk, txn=txn.transaction_id) for u in ADMIN_GET_URLS]

    def test_unauthenticated_visitors_are_blocked_everywhere(self):
        anon = APIClient()
        for url in self.urls():
            self.assertIn(anon.get(url).status_code, (401, 403), url)
        self.assertIn(anon.patch(f'/api/admin/users/{self.alice.pk}/status/', {'is_active': False}, format='json').status_code, (401, 403))

    def test_regular_users_are_blocked_everywhere(self):
        client = self.login_client(self.alice)
        for url in self.urls():
            self.assertEqual(client.get(url).status_code, 403, url)
        res = client.patch(f'/api/admin/users/{self.bob.pk}/status/', {'is_active': False}, format='json')
        self.assertEqual(res.status_code, 403)
        self.bob.refresh_from_db()
        self.assertTrue(self.bob.is_active)

    def test_staff_without_superuser_is_blocked(self):
        staff = make_user('staff@example.com', is_staff=True)
        client = self.login_client(staff)
        self.assertEqual(client.get('/api/admin/overview/').status_code, 403)

    def test_superuser_can_access_everything(self):
        for url in self.urls():
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_forged_role_in_request_does_not_grant_access(self):
        client = self.login_client(self.alice)
        res = client.get('/api/admin/overview/', {'role': 'admin', 'is_superuser': 'true'},
                         HTTP_X_ROLE='admin', HTTP_AUTHORIZATION='Bearer admin')
        self.assertEqual(res.status_code, 403)

    def test_django_admin_site_is_untouched(self):
        self.assertIn(APIClient().get('/admin/login/').status_code, (200, 302))

    def test_user_facing_apis_remain_scoped_to_the_signed_in_user(self):
        mine, theirs = make_txn(self.alice), make_txn(self.bob)
        client = self.login_client(self.alice)
        ids = [t['transaction_id'] for t in client.get('/api/payments/').data['results']]
        self.assertEqual(ids, [mine.transaction_id])
        self.assertEqual(client.get(f'/api/payments/{theirs.transaction_id}/').status_code, 404)


# ---------------------------------------------------------------- overview

class OverviewTests(AdminTestCase):
    def test_empty_database_returns_zeros_and_no_errors(self):
        data = self.get('/api/admin/overview/').data
        self.assertEqual(data['transactions']['total_transactions'], 0)
        self.assertEqual(data['transactions']['total_amount'], Decimal('0.00'))
        self.assertIsNone(data['transactions']['average_amount'])
        self.assertEqual(data['recent_transactions'], [])
        self.assertTrue(all(p['count'] == 0 for p in data['charts']['activity']))

    def test_statistics_match_database_records(self):
        make_txn(self.alice, '100.00', 'COMPLETED')
        make_txn(self.alice, '300.00', 'COMPLETED', method='UPI')
        make_txn(self.bob, '1000.00', 'FAILED')
        make_txn(self.bob, '50.00', 'PENDING')
        make_txn(self.bob, '70.00', 'CANCELLED', method='WALLET')
        data = self.get('/api/admin/overview/').data
        t = data['transactions']
        self.assertEqual((t['total_transactions'], t['completed'], t['pending'], t['failed'], t['cancelled']), (5, 2, 1, 1, 1))
        self.assertEqual((t['total_amount'], t['average_amount']), (Decimal('400.00'), Decimal('200.00')))  # completed only
        self.assertEqual(t['amount_basis'], 'COMPLETED')
        # administrators are not counted as registered users
        self.assertEqual((data['users']['total'], data['users']['active']), (2, 2))
        charts = data['charts']
        self.assertEqual(sum(p['count'] for p in charts['activity']), 5)
        self.assertEqual(sum(Decimal(p['amount']) for p in charts['activity']), Decimal('400.00'))
        self.assertEqual({d['value']: d['count'] for d in charts['status_distribution']},
                         {'PENDING': 1, 'COMPLETED': 2, 'FAILED': 1, 'CANCELLED': 1})
        self.assertEqual({d['value']: d['count'] for d in charts['method_distribution']},
                         {'CARD': 3, 'UPI': 1, 'BANK_TRANSFER': 0, 'WALLET': 1})
        self.assertEqual(sum(r['count'] for r in charts['registrations']), 2)
        self.assertEqual(len(data['recent_transactions']), 5)

    def test_date_filter_changes_numbers_and_charts(self):
        make_txn(self.alice, '10.00', days_ago=40)
        make_txn(self.alice, '20.00', days_ago=2)
        start = (timezone.now() - timedelta(days=5)).date().isoformat()
        data = self.get('/api/admin/overview/', date_from=start).data
        self.assertEqual(data['transactions']['total_transactions'], 1)
        self.assertEqual(data['transactions']['total_amount'], Decimal('20.00'))
        self.assertEqual(sum(p['count'] for p in data['charts']['activity']), 1)
        everything = self.get('/api/admin/overview/').data
        self.assertEqual(everything['transactions']['total_transactions'], 2)

    def test_group_by_changes_bucketing(self):
        make_txn(self.alice, days_ago=1)
        weekly = self.get('/api/admin/overview/', group_by='week', date_from=(timezone.now() - timedelta(days=60)).date().isoformat()).data
        self.assertEqual(weekly['period']['group_by'], 'week')
        for period in weekly['charts']['activity']:
            self.assertEqual(datetime.fromisoformat(period['period']).weekday(), 0)  # Mondays

    def test_invalid_parameters_are_rejected(self):
        for params in [{'date_from': 'yesterday'}, {'date_to': '2026-13-45'}, {'group_by': 'year'},
                       {'date_from': '2026-02-01', 'date_to': '2026-01-01'}]:
            self.assertEqual(self.get('/api/admin/overview/', **params).status_code, 400, params)

    def test_too_many_buckets_is_a_clean_400(self):
        res = self.get('/api/admin/overview/', date_from='2000-01-01', group_by='day')
        self.assertEqual(res.status_code, 400)
        self.assertIn('group_by', res.data)


# ---------------------------------------------------------- user management

class UserManagementTests(AdminTestCase):
    url = '/api/admin/users/'

    def test_list_excludes_admins_hides_credentials_and_counts_transactions(self):
        make_txn(self.alice)
        make_txn(self.alice, status='FAILED')
        data = self.get(self.url).data
        self.assertEqual(data['count'], 2)
        by_email = {u['email']: u for u in data['results']}
        self.assertNotIn('boss@example.com', by_email)
        self.assertEqual(by_email['alice@example.com']['transaction_count'], 2)
        self.assertEqual(by_email['bob@example.com']['transaction_count'], 0)
        for user in data['results']:
            self.assertFalse({'password', 'token', 'is_superuser', 'is_staff'} & set(user))
            self.assertEqual(set(user), {'id', 'full_name', 'email', 'date_joined', 'last_login', 'is_active', 'transaction_count'})

    def test_search_filter_ordering_and_pagination(self):
        for i in range(23):
            make_user(f'bulk{i}@example.com', f'Bulk {i}')
        self.assertEqual(self.get(self.url, q='alice').data['count'], 1)
        self.assertEqual(self.get(self.url, q='stone').data['count'], 1)
        self.assertEqual(self.get(self.url, q='nobody-here').data['count'], 0)
        page1 = self.get(self.url).data
        self.assertEqual((page1['count'], len(page1['results'])), (25, 20))
        self.assertEqual(len(self.get(self.url, page=2).data['results']), 5)
        self.alice.is_active = False
        self.alice.save()
        self.assertEqual([u['email'] for u in self.get(self.url, account_status='inactive').data['results']], ['alice@example.com'])
        self.assertEqual(self.get(self.url, account_status='active').data['count'], 24)
        User.objects.filter(pk=self.bob.pk).update(date_joined=timezone.now() - timedelta(days=100))
        old = self.get(self.url, date_to=(timezone.now() - timedelta(days=50)).date().isoformat()).data
        self.assertEqual([u['email'] for u in old['results']], ['bob@example.com'])
        asc = self.get(self.url, ordering='date_joined').data['results']
        self.assertEqual(asc[0]['email'], 'bob@example.com')
        self.assertEqual(self.get(self.url, ordering='password').status_code, 400)
        self.assertEqual(self.get(self.url, account_status='banned').status_code, 400)

    def test_list_query_count_does_not_grow_with_users(self):
        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                self.get(self.url)
            return len(ctx)
        before = count_queries()
        for i in range(10):
            make_txn(make_user(f'n{i}@example.com'))
        self.assertEqual(count_queries(), before)

    def test_detail_and_user_transactions(self):
        make_txn(self.alice, '100.00')
        make_txn(self.alice, '50.00', status='FAILED')
        make_txn(self.bob, '999.00')
        detail = self.get(f'{self.url}{self.alice.pk}/').data
        self.assertEqual((detail['transaction_count'], detail['completed_transaction_count']), (2, 1))
        self.assertEqual(detail['total_completed_amount'], '100.00')
        self.assertNotIn('password', str(detail).lower())
        txns = self.get(f'{self.url}{self.alice.pk}/transactions/').data
        self.assertEqual(txns['count'], 2)
        self.assertTrue(all(t['sender_email'] == 'alice@example.com' for t in txns['results']))
        self.assertEqual(self.get(f'{self.url}{self.admin.pk}/').status_code, 404)  # admins are not listed
        self.assertEqual(self.get(f'{self.url}999999/').status_code, 404)

    def patch_status(self, user, body, client=None):
        return (client or self.client).patch(f'{self.url}{user.pk}/status/', body, format='json')

    def test_deactivate_blocks_login_and_existing_sessions_then_reactivate(self):
        alice_client = self.login_client(self.alice)
        self.assertEqual(alice_client.get('/api/auth/user/').status_code, 200)
        res = self.patch_status(self.alice, {'is_active': False})
        self.assertEqual((res.status_code, res.data['is_active']), (200, False))
        self.assertIn(alice_client.get('/api/auth/user/').status_code, (401, 403))  # old session no longer valid
        fresh = APIClient()
        fresh.get('/api/auth/csrf/')
        token = fresh.cookies['csrftoken'].value
        login = fresh.post('/api/auth/login/', {'email': 'alice@example.com', 'password': PASSWORD}, format='json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(login.status_code, 401)
        self.assertEqual(self.patch_status(self.alice, {'is_active': True}).data['is_active'], True)
        self.assertEqual(User.objects.get(pk=self.alice.pk).is_active, True)
        self.assertEqual(LogEntry.objects.filter(user=self.admin, object_id=str(self.alice.pk)).count(), 2)

    def test_status_change_never_deletes_data(self):
        txn = make_txn(self.alice)
        self.patch_status(self.alice, {'is_active': False})
        self.assertTrue(Transaction.objects.filter(pk=txn.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.alice.pk).exists())

    def test_admins_cannot_be_changed_including_oneself(self):
        other_admin = User.objects.create_superuser('boss2', 'boss2@example.com', PASSWORD)
        for target in (self.admin, other_admin):
            self.assertEqual(self.patch_status(target, {'is_active': False}).status_code, 403)
            target.refresh_from_db()
            self.assertTrue(target.is_active)

    def test_status_change_validation(self):
        for body in ({}, {'is_active': 'false'}, {'is_active': 0}, {'is_active': None}, {'is_staff': True}):
            self.assertEqual(self.patch_status(self.alice, body).status_code, 400, body)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.is_active)
        self.assertEqual(self.client.patch('/api/admin/users/999999/status/', {'is_active': False}, format='json').status_code, 404)

    def test_status_endpoint_cannot_change_privileges(self):
        self.patch_status(self.alice, {'is_active': False, 'is_superuser': True, 'is_staff': True})
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_superuser or self.alice.is_staff)


# ----------------------------------------------------- transaction management

class TransactionManagementTests(AdminTestCase):
    url = '/api/admin/transactions/'

    def setUp(self):
        super().setUp()
        self.t1 = make_txn(self.alice, '100.00', 'COMPLETED', 'CARD', days_ago=10, recipient_name='Ravi Kumar', recipient_email='ravi@example.com')
        self.t2 = make_txn(self.alice, '900.00', 'FAILED', 'UPI', days_ago=5, recipient_name='Sneha Pillai', recipient_email='sneha@example.com')
        self.t3 = make_txn(self.bob, '40.00', 'PENDING', 'WALLET', days_ago=1, recipient_name='Tom Joseph', recipient_email='tom@example.com')

    def ids(self, **params):
        return [t['transaction_id'] for t in self.get(self.url, **params).data['results']]

    def test_lists_all_users_transactions_newest_first_with_expected_fields(self):
        data = self.get(self.url).data
        self.assertEqual(self.ids(), [self.t3.transaction_id, self.t2.transaction_id, self.t1.transaction_id])
        row = data['results'][0]
        self.assertEqual(row['sender_email'], 'bob@example.com')
        self.assertEqual(row['sender_name'], 'Bob Stone')
        self.assertIsNone(row['fraud_analysis'])
        forbidden = {'latitude', 'longitude', 'device_type', 'browser', 'fraud_status', 'fraud_probability', 'password', 'upi_id', 'card_network'}
        self.assertFalse(forbidden & set(row))

    def test_search_across_id_sender_and_recipient(self):
        self.assertEqual(self.ids(q=self.t2.transaction_id[3:9]), [self.t2.transaction_id])
        self.assertEqual(self.ids(q='sneha'), [self.t2.transaction_id])
        self.assertEqual(self.ids(q='alice@'), [self.t2.transaction_id, self.t1.transaction_id])
        self.assertEqual(self.ids(q='Bob Stone'.split()[0]), [self.t3.transaction_id])
        self.assertEqual(self.ids(q='zzz-no-match'), [])

    def test_filters(self):
        self.assertEqual(self.ids(status='FAILED'), [self.t2.transaction_id])
        self.assertEqual(self.ids(payment_method='WALLET'), [self.t3.transaction_id])
        day = lambda n: (timezone.now() - timedelta(days=n)).date().isoformat()
        self.assertEqual(self.ids(date_from=day(6), date_to=day(2)), [self.t2.transaction_id])
        self.assertEqual(self.ids(status='COMPLETED', payment_method='UPI'), [])

    def test_sorting_and_validation(self):
        self.assertEqual(self.ids(ordering='amount'), [self.t3.transaction_id, self.t1.transaction_id, self.t2.transaction_id])
        self.assertEqual(self.ids(ordering='-amount')[0], self.t2.transaction_id)
        self.assertEqual(self.ids(ordering='created_at')[0], self.t1.transaction_id)
        for params in ({'ordering': 'user__password'}, {'status': 'FRAUD'}, {'payment_method': 'CASH'}, {'date_from': 'x'}):
            self.assertEqual(self.get(self.url, **params).status_code, 400, params)

    def test_pagination(self):
        for _ in range(22):
            make_txn(self.bob)
        page1 = self.get(self.url).data
        self.assertEqual((page1['count'], len(page1['results'])), (25, 20))
        self.assertEqual(len(self.get(self.url, page=2).data['results']), 5)
        self.assertEqual(len(self.get(self.url, page_size=100).data['results']), 25)

    def test_query_count_does_not_grow_with_rows(self):
        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                self.get(self.url)
            return len(ctx)
        before = count_queries()
        for _ in range(10):
            make_txn(self.bob)
        self.assertEqual(count_queries(), before)

    def test_detail_view_is_admin_safe(self):
        Transaction.objects.filter(pk=self.t1.pk).update(
            latitude=Decimal('9.6877'), longitude=Decimal('76.7798'), browser='Chrome 126', operating_system='Windows', description='Rent')
        data = self.get(f'{self.url}{self.t1.transaction_id}/').data
        self.assertEqual((data['description'], data['payment_method_detail'], data['browser']), ('Rent', 'Visa', 'Chrome 126'))
        self.assertEqual(data['sender_email'], 'alice@example.com')
        self.assertFalse({'latitude', 'longitude', 'fraud_status', 'fraud_probability', 'model_version', 'idempotency_key', 'password'} & set(data))
        self.assertNotIn('9.6877', str(data))
        self.assertEqual(self.get(f'{self.url}PS-NOPE/').status_code, 404)

    def test_viewing_never_changes_transaction_status(self):
        self.get(self.url)
        self.get('/api/admin/overview/')
        self.t2.refresh_from_db()
        self.assertEqual(self.t2.status, 'FAILED')
        self.assertEqual(self.t2.fraud_status, 'NOT_CHECKED')


# ---------------------------------------------------------- fraud statistics

class FraudStatisticsTests(AdminTestCase):
    url = '/api/admin/fraud-statistics/'
    FABRICATED = ('probability', 'accuracy', 'precision', 'recall', 'f1', 'roc', 'auc', 'risk_score', 'prediction', 'fraud_count', 'fraudulent')

    def rule(self, data, rule_id):
        return next(r for r in data['rule_based']['indicators'] if r['id'] == rule_id)

    def test_reports_ml_not_integrated_and_never_fabricates_fraud_data(self):
        make_txn(self.alice, status='FAILED')
        data = self.get(self.url).data
        self.assertFalse(data['ml_model']['integrated'])
        self.assertEqual((data['ml_model']['model'], data['ml_model']['status']), ('XGBoost', 'Not integrated'))
        self.assertEqual(data['ml_model']['message'], 'ML fraud detection is not integrated yet.')
        self.assertFalse(data['confirmed_fraud']['available'])
        keys = set()

        def collect(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    keys.add(str(key).lower())
                    collect(value)
            elif isinstance(node, list):
                for item in node:
                    collect(item)
        collect(data)
        for word in self.FABRICATED:
            self.assertFalse([k for k in keys if word in k], word)  # no fabricated metrics anywhere in the payload
        self.assertIn('not confirmed fraud', data['rule_based']['disclaimer'])

    def test_activity_statistics(self):
        make_txn(self.alice, '10.00')
        make_txn(self.alice, '90.00', method='UPI')
        make_txn(self.alice, '5000.00', status='FAILED')
        s = self.get(self.url).data['activity']['summary']
        self.assertEqual((s['total_transactions'], s['min_amount'], s['max_amount'], s['average_amount']),
                         (3, Decimal('10.00'), Decimal('90.00'), Decimal('50.00')))

    def test_rapid_repeat_rule(self):
        for minutes in (1, 3, 5):
            make_txn(self.alice, minutes_ago=minutes)
        make_txn(self.bob, minutes_ago=2)
        make_txn(self.bob, minutes_ago=4)  # only two: not flagged
        make_txn(self.bob, minutes_ago=200)
        rule = self.rule(self.get(self.url).data, 'rapid_repeat')
        self.assertEqual(rule['flagged_count'], 3)
        self.assertTrue(all(t['sender_email'] == 'alice@example.com' for t in rule['flagged_transactions']))

    def test_repeated_failures_rule_does_not_label_failures_as_fraud(self):
        for minutes in (5, 10, 20):
            make_txn(self.alice, status='FAILED', minutes_ago=minutes)
        make_txn(self.bob, status='FAILED')
        data = self.get(self.url).data
        self.assertEqual(self.rule(data, 'repeated_failures')['flagged_count'], 3)
        self.assertNotIn('fraud_status', str(data))

    def test_large_amount_rule_needs_a_baseline_and_flags_outliers(self):
        make_txn(self.alice, '5000.00')
        unavailable = self.rule(self.get(self.url).data, 'large_amount')
        self.assertFalse(unavailable['available'])
        self.assertIsNone(unavailable['flagged_count'])
        self.assertIn('at least 10', unavailable['reason'])
        for i in range(10):
            make_txn(self.bob, '100.00', days_ago=1 + i)
        rule = self.rule(self.get(self.url).data, 'large_amount')
        self.assertTrue(rule['available'])
        self.assertEqual(rule['flagged_count'], 1)
        self.assertEqual(rule['flagged_transactions'][0]['amount'], Decimal('5000.00'))
        self.assertEqual(rule['baseline_average'], Decimal('545.45'))  # (5000 + 10 x 100) / 11
        self.assertEqual(rule['limit_amount'], Decimal('2727.27'))  # 5 x the unrounded average

    def test_empty_database(self):
        data = self.get(self.url).data
        self.assertEqual(data['activity']['summary']['total_transactions'], 0)
        self.assertTrue(all(r['flagged_count'] in (0, None) for r in data['rule_based']['indicators']))


# ------------------------------------------------------------------ reports

class ReportTests(AdminTestCase):
    def setUp(self):
        super().setUp()
        make_txn(self.alice, '100.00', 'COMPLETED', 'CARD', days_ago=3)
        make_txn(self.alice, '300.00', 'COMPLETED', 'UPI', days_ago=3)
        make_txn(self.bob, '70.00', 'FAILED', 'WALLET', days_ago=2)
        make_txn(self.bob, '999.00', 'COMPLETED', 'CARD', days_ago=60)

    def report(self, kind, **params):
        return self.get(f'/api/admin/reports/{kind}/', **params)

    def section(self, data, title):
        return next(s for s in data['sections'] if s['title'].startswith(title))

    def value(self, data, metric):
        return next(r[1] for r in self.section(data, 'Summary')['rows'] if r[0] == metric)

    def test_transaction_summary_report(self):
        data = self.report('transactions').data
        self.assertEqual(data['title'], 'Transaction Summary Report')
        self.assertEqual(self.value(data, 'Total transactions'), 4)
        self.assertEqual(self.value(data, 'Failed'), 1)
        self.assertEqual(self.value(data, 'Total amount (completed only)'), Decimal('1399.00'))
        self.assertIn('completed transactions only', ' '.join(data['notes']).lower())
        methods = {r[0]: r[1:] for r in self.section(data, 'Breakdown by payment method')['rows']}
        self.assertEqual(methods['Card'], [2, Decimal('1099.00')])
        self.assertEqual(sum(r[1] for r in self.section(data, 'Breakdown by transaction status')['rows']), 4)

    def test_filters_and_date_ranges_are_respected(self):
        recent = (timezone.now() - timedelta(days=10)).date().isoformat()
        data = self.report('transactions', date_from=recent).data
        self.assertEqual(self.value(data, 'Total transactions'), 3)
        self.assertEqual(self.value(data, 'Total amount (completed only)'), Decimal('400.00'))
        self.assertEqual(self.value(self.report('transactions', status='FAILED').data, 'Total transactions'), 1)
        self.assertEqual(self.value(self.report('transactions', payment_method='CARD').data, 'Total transactions'), 2)
        self.assertEqual(self.value(self.report('activity', date_from=recent, payment_method='UPI').data, 'Total transactions'), 1)

    def test_activity_report_groups_over_time(self):
        data = self.report('activity', group_by='week', date_from=(timezone.now() - timedelta(days=30)).date().isoformat()).data
        series = self.section(data, 'Activity by week')
        self.assertEqual(sum(r[1] for r in series['rows']), 3)
        self.assertEqual(sum(r[3] for r in series['rows']), Decimal('400.00'))

    def test_user_registration_report(self):
        User.objects.filter(pk=self.bob.pk).update(date_joined=timezone.now() - timedelta(days=90))
        data = self.report('users', date_from=(timezone.now() - timedelta(days=30)).date().isoformat()).data
        self.assertEqual(self.value(data, 'Total registered users (all time)'), 2)
        self.assertEqual(self.value(data, 'Registered in selected period'), 1)
        self.assertEqual(sum(r[1] for r in self.section(data, 'Registrations by')['rows']), 1)
        self.assertNotIn('password', str(data).lower())
        inactive = self.report('users', account_status='inactive').data
        self.assertEqual(self.value(inactive, 'Total registered users (all time)'), 0)

    def test_fraud_monitoring_report_is_honest_about_missing_ml(self):
        data = self.report('fraud-monitoring').data
        status = dict(self.section(data, 'Fraud detection status')['rows'])
        self.assertEqual(status['XGBoost model'], 'Not integrated')
        self.assertEqual(status['Confirmed fraud labels'], 'Not available')
        notes = ' '.join(data['notes'])
        self.assertIn('ML fraud detection is not integrated yet.', notes)
        self.assertIn('not confirmed fraud', notes)
        blob = str(data).lower()
        for word in ('accuracy', 'precision', 'recall', 'roc', 'f1-score', 'auc'):
            self.assertNotIn(word, blob)

    def test_csv_download(self):
        res = self.report('transactions', export='csv')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res['Content-Type'].startswith('text/csv'))
        self.assertEqual(res['Content-Disposition'], 'attachment; filename="paysafe-transactions-report_all-time.csv"')
        text = res.content.decode('utf-8-sig')
        self.assertIn('Transaction Summary Report', text)
        self.assertIn('Total amount (completed only),1399.00', text)
        self.assertIn('Card,2,1099.00', text)
        named = self.report('activity', export='csv', date_from='2026-01-01', date_to='2026-01-31')
        self.assertIn('paysafe-activity-report_2026-01-01_to_2026-01-31.csv', named['Content-Disposition'])
        self.assertIn('Activity by', named.content.decode('utf-8-sig'))

    def test_empty_reports_are_handled(self):
        Transaction.objects.all().delete()
        for kind in ('transactions', 'users', 'activity', 'fraud-monitoring'):
            res = self.report(kind, export='csv')
            self.assertEqual(res.status_code, 200, kind)
        text = self.report('fraud-monitoring', export='csv').content.decode('utf-8-sig')
        self.assertIn('No data for the selected filters', text)
        self.assertIn('Not available', text)

    def test_csv_formula_injection_is_neutralised(self):
        for value in ('=1+1', '+SUM(A1)', '-2+3', '@cmd', '\t=x', '\r=x'):
            self.assertTrue(safe_cell(value).startswith("'"), repr(value))
        self.assertEqual(safe_cell('normal'), 'normal')
        self.assertEqual(safe_cell(Decimal('-5.00')), '-5.00')  # real numbers stay numbers
        evil = User.objects.create_user('=2+2@example.com', '=2+2@example.com', PASSWORD, first_name='Evil')
        for minutes in (1, 2, 3):
            make_txn(evil, minutes_ago=minutes, recipient_email='@evil.com')
        text = self.report('fraud-monitoring', export='csv').content.decode('utf-8-sig')
        self.assertIn("'=2+2@example.com", text)
        self.assertIn("'@evil.com", text)
        self.assertNotIn(',=2+2@example.com', text)
        self.assertNotIn(',@evil.com', text)

    def test_validation_and_unknown_report(self):
        self.assertEqual(self.report('transactions', date_from='nope').status_code, 400)
        self.assertEqual(self.report('transactions', date_from='2026-05-01', date_to='2026-04-01').status_code, 400)
        self.assertEqual(self.report('transactions', status='FRAUD').status_code, 400)
        self.assertEqual(self.report('transactions', export='pdf').status_code, 400)
        self.assertEqual(self.report('secrets').status_code, 404)

    def test_report_csv_for_regular_user_is_forbidden(self):
        res = self.login_client(self.alice).get('/api/admin/reports/transactions/?export=csv')
        self.assertEqual(res.status_code, 403)
        self.assertNotIn(b'Transaction Summary', res.content)

    def test_report_to_csv_marks_missing_values(self):
        Transaction.objects.all().delete()
        text = report_to_csv(build_report('transactions', {'export': 'json'}))
        self.assertIn('Average amount (completed only),Not available', text)
