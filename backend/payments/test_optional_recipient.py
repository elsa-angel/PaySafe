"""Recipient e-mail is optional. It is never a destination for codes or alerts, and a missing one makes the fraud
prediction unavailable (never guessed, never low risk)."""
from decimal import Decimal

from django.core import mail

from .fraud.errors import FailureCategory as F
from .fraud.history import compute_history_features
from .models import FraudAnalysis, OneTimeCode, Transaction
from .test_verification import PAYMENT, WorkflowTestCase
from .testing import HIGH, LOW, code_from


def without_recipient_email(**extra):
    payload = {key: value for key, value in PAYMENT.items() if key != 'recipient_email'}
    return {**payload, **extra}


class OptionalRecipientEmailTests(WorkflowTestCase):
    def test_payment_is_accepted_without_a_recipient_email_whether_omitted_blank_spaces_or_null(self):
        for label, payload in {
            'omitted': without_recipient_email(),
            'empty': {**PAYMENT, 'recipient_email': ''},
            'spaces': {**PAYMENT, 'recipient_email': '   '},
            'null': {**PAYMENT, 'recipient_email': None},
        }.items():
            with self.subTest(label):
                res = self.pay(LOW, payload=payload)
                self.assertEqual(res.status_code, 201, res.data)
                txn = self.txn(res.data['transaction_id'])
                self.assertEqual((txn.recipient_email, txn.amount, txn.currency), ('', Decimal(PAYMENT['amount']), 'INR'))
                self.assertEqual(res.data['recipient_email'], '')

    def test_a_valid_recipient_email_is_still_stored_normalised(self):
        res = self.pay(LOW, payload={**PAYMENT, 'recipient_email': '  Friend@Yahoo.COM '})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(self.txn(res.data['transaction_id']).recipient_email, 'friend@yahoo.com')

    def test_an_invalid_non_empty_recipient_email_is_still_rejected(self):
        for bad in ('not-an-email', 'a@', '@b.com', 'a b@c.com', 'x@y'):
            with self.subTest(bad):
                before = Transaction.objects.count()
                res = self.pay(LOW, payload={**PAYMENT, 'recipient_email': bad})
                self.assertEqual(res.status_code, 400)
                self.assertEqual(res.data['recipient_email'], ['Enter a valid email address.'])
                self.assertEqual(Transaction.objects.count(), before)

    def test_the_other_required_fields_stay_required(self):
        for field in ('recipient_name', 'amount', 'payment_method'):
            payload = {key: value for key, value in PAYMENT.items() if key != field}
            self.assertEqual(self.pay(LOW, payload=payload).status_code, 400, field)

    def pay_with_real_model(self, payload):
        """No forced prediction: the real feature mapper and the saved XGBoost artifacts run."""
        from .tests import CHROME_WIN
        return self.client.post('/api/payments/', payload, format='json', HTTP_USER_AGENT=CHROME_WIN)

    def test_without_a_recipient_email_the_prediction_is_unavailable_and_never_low_risk(self):
        for label, payload in {'omitted': without_recipient_email(), 'blank': {**PAYMENT, 'recipient_email': ''}}.items():
            with self.subTest(label):
                mail.outbox.clear()
                res = self.pay_with_real_model(payload)
                self.assertEqual(res.status_code, 201)
                analysis = FraudAnalysis.objects.get(transaction__transaction_id=res.data['transaction_id'])
                self.assertEqual((analysis.status, analysis.failure_category), ('UNAVAILABLE', F.MISSING_EMAIL_FEATURES))
                self.assertIsNone(analysis.fraud_probability)
                self.assertEqual(res.data['status'], 'PENDING')                     # not approved
                self.assertEqual(str(res.data['verification']['status']), 'UNAVAILABLE')
                self.assertFalse(res.data['verification']['can_verify'])
                self.assertEqual(len(mail.outbox), 0)                              # no code, no alert, to anyone
                self.assertFalse(OneTimeCode.objects.filter(verification__transaction__transaction_id=res.data['transaction_id']).exists())
                self.assertIn(self.verify(res.data['transaction_id'], '000000').status_code, (400, 409))   # nothing to verify
                self.assertEqual(self.txn(res.data['transaction_id']).status, 'PENDING')
                # the safe path stays available: the user can cancel
                self.assertEqual(self.act(res.data['transaction_id'], 'cancel').status_code, 200)

    def test_with_a_recipient_email_the_existing_low_and_high_risk_flows_are_unchanged(self):
        low = self.pay(LOW)
        high = self.pay(HIGH)
        self.assertEqual((str(low.data['verification']['status']), str(high.data['verification']['status'])),
                         ('AWAITING_OTP', 'AWAITING_USER_DECISION'))
        self.assertEqual(len(mail.outbox), 2)
        for message in mail.outbox:
            self.assertEqual(message.to, ['sender@gmail.com'])               # the registered address, never the recipient
        done = self.verify(low.data['transaction_id'], code_from(mail.outbox[0]))
        self.assertEqual(done.data['status'], 'COMPLETED')

    def test_the_recipient_email_never_receives_codes_even_when_provided(self):
        self.pay(LOW, payload={**PAYMENT, 'recipient_email': 'friend@yahoo.com'})
        self.assertTrue(all('friend@yahoo.com' not in (m.to + m.cc + m.bcc) for m in mail.outbox))

    def test_unsupported_methods_and_unsupported_domains_still_are_not_low_risk(self):
        res = self.pay_with_real_model({**PAYMENT, 'recipient_email': 'someone@unknown-provider.example'})
        analysis = FraudAnalysis.objects.get(transaction__transaction_id=res.data['transaction_id'])
        self.assertEqual((analysis.status, analysis.failure_category), ('UNAVAILABLE', F.UNSEEN_EMAIL_DOMAIN))

    def test_history_features_do_not_treat_blank_recipients_as_the_same_recipient(self):
        from .tests import make_txn
        from django.utils import timezone
        make_txn(self.user, recipient_email='')
        make_txn(self.user, recipient_email='')
        make_txn(self.user, recipient_email='a@gmail.com')
        features = compute_history_features(user=self.user, as_of=timezone.now() + timezone.timedelta(seconds=5),
                                            recipient_email='', payment_method='CARD')
        self.assertEqual(features.previous_transactions_to_same_recipient, 0)
        self.assertEqual(features.distinct_previous_recipients, 1)

    def test_existing_rows_keep_their_values_and_blank_rows_can_be_created_directly(self):
        from .tests import make_txn
        existing = make_txn(self.user, recipient_email='ravi@example.com')
        blank = make_txn(self.user, recipient_email='')
        existing.refresh_from_db(); blank.refresh_from_db()
        self.assertEqual((existing.recipient_email, blank.recipient_email), ('ravi@example.com', ''))
