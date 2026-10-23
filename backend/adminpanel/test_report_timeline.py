"""Admin reports must describe the selected period, and only that period, in every section and in the CSV."""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from payments.models import (
    FraudAnalysis, FraudAnalysisStatus, FraudWorkflowEvent, PaymentVerification, Transaction, WorkflowEvent,
)

from .tests import AdminTestCase, make_txn, make_user

UTC = dt_timezone.utc
KINDS = ('transactions', 'users', 'activity', 'fraud-monitoring')


def at(year, month, day, hour=12, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


class TimelineTestCase(AdminTestCase):
    """March holds three transactions (two on a boundary-adjacent edge), April two, January none."""

    def setUp(self):
        super().setUp()
        self.t_mar_10 = self.place(make_txn(self.alice, '100.00', 'COMPLETED', 'CARD'), at(2026, 3, 10))
        self.t_mar_20 = self.place(make_txn(self.bob, '250.00', 'COMPLETED', 'UPI'), at(2026, 3, 20))
        self.t_mar_end = self.place(make_txn(self.alice, '40.00', 'COMPLETED', 'CARD'), at(2026, 3, 31, 23, 59, 59))
        self.t_apr_start = self.place(make_txn(self.bob, '60.00', 'COMPLETED', 'CARD'), at(2026, 4, 1, 0, 0, 0))
        self.t_apr_5 = self.place(make_txn(self.alice, '70.00', 'FAILED', 'WALLET'), at(2026, 4, 5))

    @staticmethod
    def place(txn, when):
        Transaction.objects.filter(pk=txn.pk).update(created_at=when)
        txn.refresh_from_db()
        return txn

    def report(self, kind, **params):
        return self.get(f'/api/admin/reports/{kind}/', **params)

    @staticmethod
    def section(data, title):
        return next(s for s in data['sections'] if s['title'].startswith(title))

    def metric(self, data, metric, section='Summary'):
        return next(r[1] for r in self.section(data, section)['rows'] if r[0] == metric)

    def filter_value(self, data, label):
        return next(v for k, v in data['filters'] if k == label)


class SelectedPeriodTests(TimelineTestCase):
    MARCH = dict(date_from='2026-03-01', date_to='2026-03-31')
    APRIL = dict(date_from='2026-04-01', date_to='2026-04-30')
    JANUARY = dict(date_from='2026-01-01', date_to='2026-01-31')

    def test_two_different_ranges_give_different_totals_and_contents(self):
        march = self.report('transactions', **self.MARCH).data
        april = self.report('transactions', **self.APRIL).data
        self.assertEqual(self.metric(march, 'Total transactions'), 3)
        self.assertEqual(self.metric(march, 'Total amount (completed only)'), Decimal('390.00'))
        self.assertEqual(self.metric(april, 'Total transactions'), 2)
        self.assertEqual(self.metric(april, 'Total amount (completed only)'), Decimal('60.00'))
        self.assertEqual(self.metric(april, 'Failed'), 1)
        self.assertEqual(self.metric(march, 'Failed'), 0)
        self.assertEqual(self.filter_value(march, 'Date range'), '2026-03-01 to 2026-03-31')
        self.assertEqual(self.filter_value(april, 'Date range'), '2026-04-01 to 2026-04-30')
        methods = {r[0]: r[1] for r in self.section(march, 'Breakdown by payment method')['rows']}
        self.assertEqual((methods['Card'], methods['UPI'], methods['Wallet']), (2, 1, 0))
        # an open-ended range and the full history still work
        self.assertEqual(self.metric(self.report('transactions', date_from='2026-04-01').data, 'Total transactions'), 2)
        self.assertEqual(self.metric(self.report('transactions').data, 'Total transactions'), 5)

    def test_boundaries_include_the_first_and_last_instant_of_the_range(self):
        # 23:59:59 on 31 March is March; 00:00:00 on 1 April is April. Nothing is counted twice or dropped.
        march = self.report('transactions', **self.MARCH).data
        april = self.report('transactions', **self.APRIL).data
        self.assertEqual(self.metric(march, 'Total transactions') + self.metric(april, 'Total transactions'), 5)
        one_day = self.report('transactions', date_from='2026-03-31', date_to='2026-03-31').data
        self.assertEqual(self.metric(one_day, 'Total transactions'), 1)
        first_instant = self.report('transactions', date_from='2026-04-01', date_to='2026-04-01').data
        self.assertEqual(self.metric(first_instant, 'Total transactions'), 1)
        self.assertEqual(self.metric(first_instant, 'Total amount (completed only)'), Decimal('60.00'))

    def test_empty_period_has_zero_figures_an_explicit_message_and_no_out_of_range_data(self):
        for kind in ('transactions', 'activity', 'fraud-monitoring'):
            data = self.report(kind, **self.JANUARY).data
            self.assertIn('selected period', data['empty_message'], kind)
            self.assertEqual(self.metric(data, 'Total transactions' if kind != 'fraud-monitoring' else 'Transactions in selection',
                                         'Summary' if kind != 'fraud-monitoring' else 'XGBoost predictions'), 0, kind)
        data = self.report('activity', **self.JANUARY).data
        self.assertEqual(self.metric(data, 'Total amount (completed only)'), Decimal('0.00'))
        series = self.section(data, 'Activity by')
        self.assertTrue(series['rows'])                                   # a real, gap-free (all-zero) timeline
        self.assertEqual(sum(r[1] for r in series['rows']), 0)
        self.assertEqual(sum(r[3] for r in series['rows']), Decimal('0.00'))
        self.assertTrue(all(r[0].startswith('2026-01') or r[0].startswith('2025-12') for r in series['rows']))
        text = self.report('transactions', export='csv', **self.JANUARY).content.decode('utf-8-sig')
        self.assertIn('No transactions match the selected period', text)
        self.assertNotIn('390', text)
        users = self.report('users', **self.JANUARY).data
        self.assertIn('registrations', users['empty_message'])
        # a populated period carries no empty message
        self.assertIsNone(self.report('transactions', **self.MARCH).data['empty_message'])

    def test_every_section_of_every_report_uses_the_same_period(self):
        for kind in ('transactions', 'activity', 'fraud-monitoring'):
            data = self.report(kind, **self.APRIL).data
            for title in ('Breakdown by payment method', 'Breakdown by transaction status'):
                rows = self.section(data, title)['rows']
                self.assertEqual(sum(r[1] for r in rows), 2, (kind, title))
        activity = self.report('activity', group_by='day', **self.MARCH).data
        series = self.section(activity, 'Activity by day')['rows']
        self.assertEqual([r[0] for r in series][0], '2026-03-01')
        self.assertEqual([r[0] for r in series][-1], '2026-03-31')
        self.assertEqual(sum(r[1] for r in series), 3)
        self.assertEqual(sum(r[3] for r in series), Decimal('390.00'))
        daily = {r[0]: r[1] for r in series}
        self.assertEqual((daily['2026-03-10'], daily['2026-03-31'], daily['2026-04-01'] if '2026-04-01' in daily else 0), (1, 1, 0))

    def test_csv_matches_the_preview_for_the_same_period(self):
        for kind in KINDS:
            preview = self.report(kind, **self.MARCH).data
            text = self.report(kind, export='csv', **self.MARCH).content.decode('utf-8-sig')
            self.assertIn('Date range,2026-03-01 to 2026-03-31', text, kind)
            for section in preview['sections']:
                self.assertIn(section['title'], text, kind)
        csv_text = self.report('transactions', export='csv', **self.APRIL).content.decode('utf-8-sig')
        self.assertIn('Total transactions,2', csv_text)
        self.assertIn('Total amount (completed only),60.00', csv_text)
        response = self.report('transactions', export='csv', **self.APRIL)
        self.assertIn('2026-04-01_to_2026-04-30', response['Content-Disposition'])

    def test_fraud_and_verification_statistics_only_count_the_selected_period(self):
        def analyse(txn, probability, verification, event_type):
            FraudAnalysis.objects.create(
                transaction=txn, status=FraudAnalysisStatus.EVALUATED, predicted_class=int(probability >= 0.1055),
                fraud_probability=probability, threshold_used=0.1055, threshold_source='phase1_validation', model_version='t')
            PaymentVerification.objects.create(transaction=txn, status=verification, risk_category='HIGH' if probability >= 0.1055 else 'LOW',
                                               details_fingerprint='x', expires_at=txn.created_at)
            # the event itself happens LATER than the transaction, even after the selected period ends
            event = FraudWorkflowEvent.objects.create(transaction=txn, event_type=event_type)
            FraudWorkflowEvent.objects.filter(pk=event.pk).update(created_at=at(2026, 6, 1))
        analyse(self.t_mar_10, 0.60, 'VERIFIED', WorkflowEvent.OTP_FAILED)
        analyse(self.t_mar_20, 0.02, 'CANCELLED', WorkflowEvent.USER_CANCELLED)
        analyse(self.t_apr_start, 0.30, 'FAILED', WorkflowEvent.OTP_FAILED)

        march = self.report('fraud-monitoring', **self.MARCH).data
        april = self.report('fraud-monitoring', **self.APRIL).data
        pred, resp = 'XGBoost predictions', 'Fraud response'
        self.assertEqual(self.metric(march, 'Transactions in selection', pred), 3)
        self.assertEqual(self.metric(march, 'Evaluated by the model', pred), 2)
        self.assertEqual(self.metric(march, 'Flagged by model (evaluated only)', pred), 1)
        self.assertEqual(self.metric(march, 'Not evaluated (no analysis recorded)', pred), 1)
        self.assertEqual(self.metric(march, 'Verified with a one-time code', resp), 1)
        self.assertEqual(self.metric(march, 'Cancelled by the user', resp), 1)
        self.assertEqual(self.metric(march, 'Incorrect code attempts', resp), 1)
        self.assertEqual(self.metric(april, 'Transactions in selection', pred), 2)
        self.assertEqual(self.metric(april, 'Evaluated by the model', pred), 1)
        self.assertEqual(self.metric(april, 'Verified with a one-time code', resp), 0)
        self.assertEqual(self.metric(april, 'Cancelled by the user', resp), 0)
        self.assertEqual(self.metric(april, 'Verification failed (limits reached)', resp), 1)
        self.assertEqual(self.metric(april, 'Incorrect code attempts', resp), 1)
        january = self.report('fraud-monitoring', **self.JANUARY).data
        for name in ('Evaluated by the model', 'Prediction unavailable', 'Flagged by model (evaluated only)'):
            self.assertEqual(self.metric(january, name, pred), 0)
        for name in ('Verified with a one-time code', 'Incorrect code attempts', 'One-time code e-mails failed'):
            self.assertEqual(self.metric(january, name, resp), 0)

    def test_fraud_statistics_series_add_up_to_the_totals_of_the_period(self):
        for txn in (self.t_mar_10, self.t_mar_20):
            FraudAnalysis.objects.create(transaction=txn, status=FraudAnalysisStatus.UNAVAILABLE, failure_category='MODEL_DISABLED')
            event = FraudWorkflowEvent.objects.create(transaction=txn, event_type=WorkflowEvent.VERIFICATION_UNAVAILABLE)
            FraudWorkflowEvent.objects.filter(pk=event.pk).update(created_at=at(2026, 5, 2))   # outside March
        data = self.get('/api/admin/fraud-statistics/', date_from='2026-03-01', date_to='2026-03-31', group_by='day').data
        self.assertEqual(sum(p['unavailable'] for p in data['fraud_response']['series']), 2)
        self.assertEqual(sum(p['unavailable'] for p in data['predictions']['series']), 2)

    def test_the_large_amount_baseline_uses_only_the_selected_period(self):
        for index in range(25):
            make_txn(self.alice, '10.00', 'COMPLETED', 'CARD', minutes_ago=index)        # "now": far outside March
        data = self.report('fraud-monitoring', **self.MARCH).data
        rule = next(r for r in self.section(data, 'Preliminary rule-based indicators')['rows'] if r[0] == 'Unusually large amounts')
        self.assertIn('Not available', str(rule[2]))                  # only 3 completed payments exist in March
        self.assertIn('Needs at least', str(rule[2]))


class TimeZoneBoundaryTests(TimelineTestCase):
    """The admin's own calendar days decide what is "in" a day, so the numbers match the times they see."""

    def setUp(self):
        super().setUp()
        # 18:29:59 UTC = 23:59:59 IST on 31 March; 18:30:00 UTC = 00:00:00 IST on 1 April.
        self.last_ist_march = self.place(make_txn(self.alice, '11.00', 'COMPLETED', 'CARD'), at(2026, 5, 31, 18, 29, 59))
        self.first_ist_june = self.place(make_txn(self.alice, '22.00', 'COMPLETED', 'CARD'), at(2026, 5, 31, 18, 30, 0))

    def count(self, **params):
        return self.metric(self.report('transactions', **params).data, 'Total transactions')

    def test_default_zone_is_utc(self):
        self.assertEqual(self.count(date_from='2026-05-31', date_to='2026-05-31'), 2)
        self.assertEqual(self.count(date_from='2026-06-01', date_to='2026-06-01'), 0)

    def test_the_requested_zone_moves_the_day_boundary_exactly_once(self):
        may = self.count(date_from='2026-05-01', date_to='2026-05-31', tz='Asia/Kolkata')
        june = self.count(date_from='2026-06-01', date_to='2026-06-30', tz='Asia/Kolkata')
        self.assertEqual((may, june), (1, 1))             # 23:59:59 IST is May, 00:00:00 IST is June
        data = self.report('transactions', date_from='2026-06-01', date_to='2026-06-01', tz='Asia/Kolkata').data
        self.assertEqual(self.filter_value(data, 'Time zone'), 'Asia/Kolkata')
        self.assertEqual(self.metric(data, 'Total amount (completed only)'), Decimal('22.00'))

    def test_buckets_use_the_same_zone_as_the_filter(self):
        data = self.report('activity', group_by='day', date_from='2026-05-31', date_to='2026-06-01', tz='Asia/Kolkata').data
        series = {r[0]: r[1] for r in self.section(data, 'Activity by day')['rows']}
        self.assertEqual(series, {'2026-05-31': 1, '2026-06-01': 1})

    def test_unknown_zone_is_rejected_and_does_not_leak_into_the_next_request(self):
        self.assertEqual(self.report('transactions', tz='Mars/Olympus').status_code, 400)
        self.assertEqual(self.report('transactions', tz='../etc/passwd').status_code, 400)
        self.report('transactions', tz='Asia/Kolkata')
        self.assertEqual(self.count(date_from='2026-05-31', date_to='2026-05-31'), 2)   # back to UTC


class ReportAccessTests(TimelineTestCase):
    def test_only_superusers_can_read_reports_for_any_period(self):
        params = dict(date_from='2026-03-01', date_to='2026-03-31')
        for kind in KINDS:
            for export in ('json', 'csv'):
                self.assertEqual(self.report(kind, export=export, **params).status_code, 200)
                self.assertEqual(self.login_client(self.alice).get(f'/api/admin/reports/{kind}/', {**params, 'export': export}).status_code, 403)
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get('/api/admin/reports/transactions/', params).status_code, (401, 403))
